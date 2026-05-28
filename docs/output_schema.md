# Output Schema

This document specifies the JSON/JSONL output produced by `job-api-aggregator jobs`
and `job-api-aggregator hydrate`. It is the authoritative reference for all
consumers of the package's output.

---

## Table of Contents

1. [Envelope](#envelope)
2. [Record Fields](#record-fields)
   - [Identity Fields](#identity-fields)
   - [Always-Present Fields](#always-present-fields)
   - [Optional Fields](#optional-fields)
   - [Source-Specific Blob](#source-specific-blob)
3. [Empty String vs. Null](#empty-string-vs-null)
4. [description\_source Truth Table](#description_source-truth-table)
5. [Schema Versioning](#schema-versioning)
6. [Deprecation Policy](#deprecation-policy)
7. [Supported Sources](#supported-sources)

---

## Envelope

Every output from `job-api-aggregator jobs` or `job-api-aggregator hydrate` begins
with an envelope object.

**JSON format** (`--format json`): the envelope is the top-level object; the
`"jobs"` key holds all records as an array.

**JSONL format** (`--format jsonl`, the default): the first line is the
envelope with `"jobs": []`; every subsequent line is a single record.

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-04-23T18:45:12Z",
  "command": "jobs",
  "sources_used": ["adzuna", "jooble"],
  "sources_failed": [],
  "request_summary": {
    "hours": 24,
    "query": "python developer",
    "location": "Atlanta, GA",
    "country": null,
    "sources": ["adzuna", "jooble"]
  },
  "jobs": []
}
```

| Field | Type | Description |
|---|---|---|
| `schema_version` | string | Semver string — see [Schema Versioning](#schema-versioning). |
| `generated_at` | string | RFC 3339 UTC timestamp when the output was produced. |
| `command` | string | `"jobs"` or `"hydrate"`, depending on which command produced the output. |
| `sources_used` | array of strings | Plugin keys that returned at least one result. |
| `sources_failed` | array of strings | Plugin keys that raised an error; their listings are absent. |
| `request_summary` | object | The search parameters used for this run. See [request_summary fields](#request_summary-fields) below. |
| `jobs` | array | Present in JSON format only; empty array in JSONL envelope line. |

`hydrate` propagates the envelope from its input, updating `command` to
`"hydrate"` and `generated_at` to the current time. The original
`request_summary` is preserved unchanged.

### `request_summary` fields

| Field | Type | Description |
|---|---|---|
| `hours` | integer | Lookback window in hours as specified by `--hours` (default 168). |
| `query` | string \| null | Free-text search query, or `null` if none was given. |
| `location` | string \| null | Location hint, or `null` if none was given. |
| `country` | string \| null | ISO 3166-1 alpha-2 country code, or `null`. |
| `sources` | array of strings | Plugin keys that were enabled for this run (before any per-source errors). |
| `records_filtered_by_hours` | integer | Count of records dropped because their `posted_at` was older than the `hours` cutoff. See [Hours Filter Semantics](#hours-filter-semantics) below. |

### Hours Filter Semantics

The `--hours` flag (default 168, i.e. one week) controls a post-fetch
filter applied by the orchestrator after all plugin records have been
normalised and before deduplication.

**Cutoff computation:** `cutoff = now_utc - timedelta(hours=hours)`.

**Filter policy per record:**

| `posted_at` value | Action |
|---|---|
| Parseable RFC 3339 UTC timestamp, `>= cutoff` | **Kept** |
| Parseable RFC 3339 UTC timestamp, `< cutoff` | **Dropped** |
| `null` (absent or `None`) | **Kept** — soft-filter policy |
| Non-empty but unparseable string | **Kept** — soft-filter policy |

**Soft-filter policy (null / unparseable):** Records whose `posted_at`
cannot be parsed are retained rather than dropped. This preserves recall
for sources that frequently omit `posted_at` (e.g. Remotive). The
trade-off is documented here so consumers can decide whether to apply
their own strict filter downstream.

`records_filtered_by_hours` counts only **dropped** records.  Kept
null/unparseable records do **not** increment this counter.

---

## Record Fields

Each record is a JSON object with three categories of fields.

### Identity Fields

These fields are always present and are validated at output time.

| Field | Type | Description |
|---|---|---|
| `source` | string | Plugin key identifying the source (e.g. `"adzuna"`, `"remoteok"`). |
| `source_id` | string | Source-provided unique identifier. May be an empty string if the upstream API provides none — passed through unchanged. |
| `description_source` | string | One of `"full"`, `"snippet"`, or `"none"`. See the [truth table](#description_source-truth-table) for exact semantics. |

### Always-Present Fields

These fields are always serialized. They may be empty according to the rules
in [Empty String vs. Null](#empty-string-vs-null).

| Field | Type | Description |
|---|---|---|
| `title` | string | Job title. May be an empty string when the source provides nothing. |
| `url` | string | Canonical URL for the listing (renamed from `redirect_url` in source APIs). May be empty. `hydrate` requires a non-empty `url` to perform a scrape; records with empty `url` pass through unchanged. |
| `posted_at` | string \| null | RFC 3339 UTC timestamp. Backfilled from `created_at` by the `jobs` orchestrator. `null` when neither `posted_at` nor `created_at` is parseable (a warning is logged to stderr). |
| `description` | string | Job description text. After `jobs`: the source's snippet. After a successful `hydrate`: the full extracted text. Empty string when the source provides no description. |

### Optional Fields

These fields are always serialized and are typically `null`. They are present
whenever the source provides the data.

| Field | Type | Description |
|---|---|---|
| `company` | string \| null | Company name. Empty string preserved if the source emits an empty string; `null` when the key is absent. |
| `location` | string \| null | Free-text location as provided by the source. No normalisation is applied. |
| `salary_min` | number \| null | Minimum salary figure as provided by the source. |
| `salary_max` | number \| null | Maximum salary figure as provided by the source. |
| `salary_currency` | string \| null | ISO 4217 currency code where the source provides one. |
| `salary_period` | string \| null | One of `"annual"`, `"monthly"`, or `"hourly"`. Currently `null` for all bundled plugins. |
| `contract_type` | string \| null | Contract classification (e.g. `"permanent"`, `"contract"`). Source-specific vocabulary. |
| `contract_time` | string \| null | Full-time or part-time indicator. Source-specific vocabulary. |
| `remote_eligible` | boolean \| null | `true` if the listing is marked as remote-eligible by the source. |

### Source-Specific Blob

| Field | Type | Description |
|---|---|---|
| `extra` | object \| null | Plugin-specific key/value pairs (e.g. `extra.adzuna.category`). **Explicitly excluded from schema versioning** — see [`extra.*` policy](#extra-policy). |

---

## Empty String vs. Null

This is a documented contract, not an implementation detail.

- **Empty string** (`""`) means the source provided a value, and that value
  was empty.
- **`null`** means the source did not provide this field at all.

Consumers can distinguish "source sent an empty string" from "source omitted
the field entirely." Do not conflate the two when filtering.

---

## `description_source` Truth Table

The `description_source` field is a contract between `jobs`, `hydrate`, and
any downstream consumer. Both orchestrators implement these tables
identically. Tests in the package validate against them.

### `jobs` orchestrator (no scrape — emit what plugins provide)

| Plugin sets `skip_scrape` | Plugin sets `description_is_full` | `len(description) >= SCRAPE_MIN_LENGTH` | Result `description_source` |
|---|---|---|---|
| True | True | True | `"full"` |
| True | True | False | `"snippet"` |
| True | False | n/a | `"snippet"` |
| False | n/a | n/a | `"snippet"` |
| n/a | n/a | description is empty | `"none"` |

### `hydrate` orchestrator (performs HTTP scrape)

| Input `description_source` | Scrape outcome | Result `description_source` | Result `description` |
|---|---|---|---|
| `"full"` | (skipped — already full) | `"full"` (unchanged) | unchanged |
| `"snippet"` or `"none"` | success, body ≥ MIN | `"full"` | scraped text |
| `"snippet"` or `"none"` | failure (HTTP error, parse fail, body < MIN) | unchanged | unchanged |
| `"snippet"` or `"none"` | url empty/missing | unchanged | unchanged |

`SCRAPE_MIN_LENGTH` is a public constant exported from
`job_api_aggregator.scraping`. Downstream consumers that implement equivalent
scrape logic must import it rather than hard-coding a value.

---

## Schema Versioning

`schema_version` follows [Semantic Versioning](https://semver.org/).

**Major version bump** (breaking change) — triggers for:
- Removing or renaming an Identity or Always-present field.
- Changing the type of an existing field.

**Minor version bump** (backward-compatible addition) — triggers for:
- Adding a new Optional field.
- Adding a new envelope key.

### `extra.*` Policy

`extra.*` is **not covered by `schema_version`**. Specifically:

- The package may change `extra.*` keys, types, and structure in any
  release (including patch versions) without notice.
- Tests in the package do not assert `extra.*` shape; only that `extra` is
  an object when present.
- Consumers depending on `extra.*` are explicitly out of warranty.
- When a field inside `extra` is consistently demanded by consumers, it is
  promoted to a real Optional field in a minor version bump, at which point it
  becomes covered by schema versioning. Until then, `extra` is
  best-effort raw passthrough.

---

## Deprecation Policy

Per [PEP 387](https://peps.python.org/pep-0387/), any removal or breaking
change to a schema-versioned field is announced via a `DeprecationWarning`
emitted from at least one minor release before the change takes effect in the
next major version. Pure field renames may dual-emit (both old and new names
present) during the deprecation window. `extra.*` is explicitly excluded from
this policy per the [`extra.*` policy](#extra-policy) above.

---

## Supported Sources

The table below is the canonical plugin metadata catalog. Each row reflects
what the plugin's bundled implementation actually supports.

| Plugin | Display Name | GEO_SCOPE | ACCEPTS_QUERY | ACCEPTS_LOCATION | ACCEPTS_COUNTRY | RATE_LIMIT_NOTES | Required Search Fields |
|---|---|---|---|---|---|---|---|
| `adzuna` | Adzuna | global-by-country | always | true | true | ~1 req/sec sustained; free tier capped at 250 req/day. | `country`, `query` |
| `arbeitnow` | Arbeitnow | regional | never | false | false | Public API; no documented rate limit. Practical cap: ~1 req/s. | (none) |
| `himalayas` | Himalayas | remote-only | never | false | false | Public API; no published limit. Observed soft limit ~1 req/sec. | (none) |
| `jobicy` | Jobicy | remote-only | partial | false | false | No published rate limit; single request per run. | (none) |
| `jooble` | Jooble | global | always | true | false | No published hard limit; free-tier key, use responsibly. | (none) |
| `jsearch` | JSearch (RapidAPI) | global | always | true | false | RapidAPI quota varies by plan; free tier 200 requests/month. | `query` |
| `remoteok` | RemoteOK | remote-only | never | false | false | Public, soft rate limits. | (none) |
| `remotive` | Remotive | remote-only | always | false | false | No published rate limit; public API, use conservatively. | (none) |
| `the_muse` | The Muse | global | partial | false | false | Public API; no published hard limit. Optional api_key reduces throttling. | (none) |
| `usajobs` | USAJobs | federal-us | partial | false | false | Email-tagged user-agent required; no published numeric limit. | (none) |

**Column definitions:**

- **GEO_SCOPE** — geographic coverage of the source. Possible values:
  `global`, `global-by-country`, `remote-only`, `federal-us`, `regional`.
- **ACCEPTS_QUERY** — how the source handles a free-text search query:
  `always` (sent to the API), `partial` (best-effort support), `never`
  (source does not accept a query parameter).
- **ACCEPTS_LOCATION** — whether the source accepts a free-text location
  filter in its API.
- **ACCEPTS_COUNTRY** — whether the source accepts an ISO 3166-1 alpha-2
  country code filter.
- **Required Search Fields** — `SearchParams` fields that must be non-`None`
  for the plugin to run. Passing `None` for a required field causes the
  plugin to be skipped with a warning.
