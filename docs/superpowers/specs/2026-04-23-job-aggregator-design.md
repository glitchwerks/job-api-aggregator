# `job-api-aggregator` Package — Design Spec (v3-patched)

**Date:** 2026-04-23
**Status:** Draft v3-patched — pending user review
**Author:** Christopher Beaulieu (with Claude Code)
**Repo strategy:** Separate repo (`job-api-aggregator`) developed **standalone**;
**Phase 1** ships v1.0 of the package independently. **Phase 2 (deferred)**
migrates `job-matcher-pr` to consume the package. The two phases are
sequenced — Phase 2 does not begin until Phase 1's v1.0 is shipped and
validated against the target external consumer.

This separation guarantees no cross-contamination during initial
development: changes to `job-matcher-pr` cannot disrupt `job-api-aggregator`'s
work, and vice versa, until the deliberate Phase 2 migration.

**Revision history:**
- v1 → v2: address inquisitor blockers (translator/extraction/schema)
- v2 → v3: **structural reframe.** Extract the data-source layer into an
  independent `job-api-aggregator` package. `job-matcher-pr` becomes a consumer of
  that package (alongside the user's other evaluation tools). Eliminates 9 of
  14 inquisitor findings outright by removing the in-repo coupling that
  forced them. See §15 for the v2→v3 reframe rationale.

---

## 1. Problem statement

The job-aggregation logic in `job-matcher-pr` is currently inseparable from
its LLM scoring and database-write stages — it is a private orchestrator with
no public interface. Other job-evaluation tools the user maintains cannot
reuse this work; they have to rebuild source coverage from scratch.

The user wants a **reusable, structured data source** that any tool can
consume. The user has a specific target consumer (an existing
non-`job-matcher-pr` evaluation system the user maintains) in mind that needs
full job descriptions for LLM scoring. That consumer should be able to:

```bash
pip install job-api-aggregator
job-api-aggregator jobs --hours 24 --query "python developer" --credentials creds.json \
  | job-api-aggregator hydrate > full.jsonl
# now consumer's own pipeline reads full.jsonl
```

**The structural decision in v3:** rather than building this CLI inside
`job-matcher-pr` (which forces refactoring the pipeline primitives,
behaviour-preservation problems, DB-import topology issues, and the
translator/`PipelineConfig` complications that v2's inquisitor identified),
build it as a **fully independent Python package** in its own repo. Both
`job-matcher-pr` and external tools become consumers of the package. Plugin
code lives once.

## 2. Goals

### Phase 1 (this spec's primary scope)

Ship a standalone Python package `job-api-aggregator` v1.0 providing:

- `job-api-aggregator jobs` — fetch listings from configured aggregator sources,
  normalize them, emit structured records
- `job-api-aggregator hydrate` — read records from stdin/file, scrape full job
  descriptions, emit enriched records
- `job-api-aggregator sources` — discovery: enumerate available plugins
- A typed Python introspection API (`list_plugins()`, `get_plugin(key)`)
  consumable by any UI host
- A stable, semver-versioned package contract (output schema, credentials
  format, plugin contract) that external consumers can pin against

The user's target external consumer integrates with v1.0 to validate the
contract. **`job-matcher-pr` is not modified during Phase 1.**

### Phase 2 (deferred to a separate later milestone)

Migrate `job-matcher-pr` to consume `job-api-aggregator`:

- Replace `job-matcher-pr/job_sources/` and `job-matcher-pr/plugins/sources/`
  with imports from `job-api-aggregator`
- Migrate `web/settings.py` and `web/admin.py` to use
  `job_api_aggregator.list_plugins()` introspection
- Add credentials adapter at the boundary
- Preserve `job-matcher-pr`'s observable behaviour (ingest output, scoring,
  DB writes all unchanged from a user perspective)

Phase 2 begins only after Phase 1 is shipped, validated by the external
consumer, and the package's contract has stabilized. Phase 2 details
(§12-13 sub-sections labeled Phase 2) are included in this spec for
forward-planning but are NOT part of the immediate work.

## 3. Non-goals

- **No scoring in the package.** LLM evaluation is the consumer's job.
- **No database access from the package.** `job-api-aggregator` cannot import or
  require any database client. External consumers run without `DATABASE_URL`.
- **No filtering in the package** *beyond* fetch-side params (hours, source
  selection). Title/contract filters and geo filters stay in
  `job-matcher-pr` (they're tied to user profile / app config and don't
  generalize).
- **No XML output format.** JSONL (default) and JSON (envelope) only.
- **No concurrency in v1.** Both `jobs` and `hydrate` are serial. v1.1 will
  add `--concurrency N` to `hydrate` once the v1 contract is validated.
- **Package does not store credentials.** Consumers (apps) own credential
  storage. The package describes what credentials each plugin needs and
  accepts them at invocation time.

## 4. User stories

### Phase 1 user stories

1. **External consumer ad-hoc.** `pip install job-api-aggregator`. Run
   `job-api-aggregator sources` to see what's available. Run `job-api-aggregator jobs
   --hours 24 --query "python" --credentials ./my-creds.json | job-api-aggregator
   hydrate > today.jsonl`. Feed `today.jsonl` into their own scoring
   pipeline. **This is the primary Phase 1 validation user story.**

2. **External consumer programmatic.** A Python script in another project
   does `from job_api_aggregator import list_plugins, ScrapeRunner` and
   orchestrates scraping in-process without spawning subprocesses.

3. **Plugin author.** A developer wanting to add a new aggregator source
   reads `docs/plugin_authoring.md`, subclasses `JobSource`, declares
   metadata attributes, optionally publishes their plugin as a separate PyPI
   package using entry-points.

### Phase 2 user stories (deferred)

4. **`job-matcher-pr` self-use.** `python ingest.py` works exactly as today.
   Internally, `ingest.py` now does `from job_api_aggregator import
   make_enabled_sources, scrape_description, ...` and uses the package's
   primitives. No observable change for the user.

5. **`job-matcher-pr` settings UI.** The user opens Settings → Sources, sees
   the same list of sources with the same descriptions and credential fields
   they see today. Internally, the route handler now calls
   `job_api_aggregator.list_plugins()` instead of introspecting local plugin
   classes. No visible change.

## 5. Architectural decisions

### 5.1 Two-command split (`jobs` and `hydrate`)

`jobs` does fetch + normalize + emit (no scrape). Fast — completes in
seconds for hundreds of listings. Output is records with snippet-level
descriptions (whatever the source API returns) and `description_source` set
to `"snippet"` or `"none"`.

`hydrate` reads records (from stdin or `--input PATH`), fetches the full job
description from each record's `url`, and emits the same records with
`description` replaced and `description_source` set to `"full"` (or
preserved as `"snippet"` on failure).

**Why split rather than one command with a flag:** clean separation between
the fast and slow stages. Consumers who only need metadata don't pay for
scraping. The slow stage is named so its cost is visible. Each command is
independently testable. Composable via shell pipes:

```bash
job-api-aggregator jobs --hours 24 --query python | job-api-aggregator hydrate > full.jsonl
```

### 5.2 Package owns plugin definitions; apps own user state

| Concern | Owned by |
|---|---|
| What plugins exist | Package |
| What each plugin does (description, geo scope) | Package |
| What credentials each plugin needs (typed `PluginField` definitions) | Package |
| Behavioural traits (`accepts_query`, etc.) | Package |
| Per-user enable/disable state | App (e.g. `providers.json`) |
| Per-user credential values | App |
| How a credential field is rendered (HTML, label styling) | App |
| Validation of submitted credential values | App, using package's typed field metadata |

The package exposes typed `PluginInfo` and `PluginField` dataclasses;
consuming apps render them however they want.

### 5.3 No code shared between `ingest.run()` and the package's CLI

This is the structural lesson from v2. `ingest.run()` keeps its current
loop (scoring, DB writes, per-provider cost tracking, SSE event emission,
filtering) untouched. The package's `job-api-aggregator jobs` orchestrator has its
own loop (fetch + normalize + emit). They both call the same primitives
(plugin `pages()`, `scrape_description`) but neither orchestrator depends
on the other.

This means:
- No `process_listing()` extraction needed (v2 blocker B2 — eliminated)
- No `PipelineConfig` translator needed (v2 blocker B1 — eliminated)
- No behaviour-preservation drama for `ingest.run()` — its loop is unchanged
- No `DATABASE_URL` import topology issue — package never imports `db`

The cost: the per-listing call sequencing exists in two places (~30 LOC of
duplicated control flow). This is acceptable because:
- The duplicated lines are mechanical (`for listing: prefilter; geo; dedup;
  scrape`)
- Bug fixes to the actual logic (`prefilter`, `scrape_description`) live in
  one place each — `prefilter` in `job-matcher-pr`, `scrape_description` in
  the package
- The two orchestrators have intentionally different semantics anyway
  (different dedup, different output sink, different stages run)

**Drift hazard the user must guard against (acknowledged):**

The `description_source` classification (`"full"` / `"snippet"` / `"none"`)
is part of the package's stable schema AND `ingest.run()`'s persistence path
(via `db.insert_listing`'s `description_source` column). The classification
logic (the truth table in §9.6) is implemented in the package's `hydrate`
orchestrator and mirrored by `ingest.run()`'s inline scrape branch (lines
1390-1416). If the user changes the logic in one place without the other,
listings get inconsistent provenance depending on which code path produced
them.

**Mitigations:**
- `_SCRAPE_MIN_LENGTH` lives in the package (`job_api_aggregator.scraping`),
  exported as a public constant. `ingest.py` imports it: `from
  job_api_aggregator.scraping import SCRAPE_MIN_LENGTH`. **One source of truth for
  the constant.**
- The truth table in §9.6 is the definitional reference. Both orchestrators
  must implement it identically; tests in both repos validate against the
  table.
- A small contract test in `job-matcher-pr` (~20 LOC, in
  `tests/test_scrape_classification_parity.py`) feeds a synthetic listing
  with each table-row's input combination through `ingest.run()`'s scrape
  branch and asserts the resulting `description_source` matches the table.
  Future bugs in either implementation surface here.

### 5.4 No GeoFilter in the package

`GeoFilter` stays in `job-matcher-pr`. It has DB-cache coupling
(`db.geocache_get_many` / `db.geocache_put`) that doesn't fit a no-DB
package. External consumers needing geo filtering implement their own.

The package CLI has no `--remote` or `--location` flag. Consumers do
geo-related filtering on their own data. (This was v2's M2 blocker — fully
eliminated by removing the feature.)

## 6. Package structure

```
job-api-aggregator/                           # NEW REPO
├── pyproject.toml                     # console script: job-api-aggregator
├── README.md
├── LICENSE
├── docs/
│   ├── output_schema.md               # public per-record contract
│   ├── plugin_authoring.md            # how to write a new plugin
│   └── examples/sample-output.jsonl
├── src/
│   └── job_api_aggregator/
│       ├── __init__.py                # public API: re-exports
│       ├── base.py                    # JobSource ABC (moved from job-matcher-pr/job_sources/base.py)
│       ├── loader.py                  # plugin discovery (moved from job_sources/loader.py)
│       ├── auto_register.py           # entry-point + filesystem registration
│       ├── registry.py                # list_plugins / get_plugin
│       ├── plugins/                   # 10 plugins (moved from job-matcher-pr/plugins/sources/)
│       │   ├── adzuna/
│       │   ├── arbeitnow/
│       │   ├── ... (10 total)
│       ├── schema.py                  # JobRecord, PluginInfo, PluginField
│       ├── scraping.py                # scrape_description (moved from ingest.py)
│       ├── orchestrator.py            # the fetch loop for `jobs`
│       ├── hydrator.py                # the scrape loop for `hydrate`
│       ├── output/
│       │   ├── jsonl.py
│       │   └── json.py
│       └── cli/
│           ├── __init__.py
│           └── __main__.py            # argparse for jobs / hydrate / sources
├── tests/
│   ├── conftest.py
│   ├── test_orchestrator.py
│   ├── test_hydrator.py
│   ├── test_registry.py
│   ├── test_schema.py
│   ├── plugins/                       # one test file per plugin
│   └── fixtures/
└── .github/workflows/ci.yml
```

`pyproject.toml` declares:

```toml
[project]
name = "job-api-aggregator"
version = "0.1.0"
requires-python = ">=3.11"          # Himalayas plugin uses from datetime import UTC (3.11+)
dependencies = [
    "requests>=2.31",
    "beautifulsoup4>=4.12",
]
# NOTE: no psycopg2, no flask, no llm/anthropic/openai/google packages.
# CI must enforce this — see §14.

[project.scripts]
job-api-aggregator = "job_api_aggregator.cli.__main__:main"

[project.entry-points."job_api_aggregator.plugins"]
# v1 ships with built-in plugins; third parties can add via their own packages.
adzuna = "job_api_aggregator.plugins.adzuna:AdzunaSource"
# ... all 10 ...
```

**CI matrix for v1**: Python 3.11 only. Widening (3.12, 3.13) deferred until
all plugins are audited for version-specific syntax/imports.

**Entry-point collision policy**: when `auto_register` discovers two
registrations claiming the same `source_key` (built-in vs third-party,
duplicate filesystem registration vs entry-point, stale editable install vs
PyPI install, etc.), it raises a clear `PluginConflictError` at startup
listing both registration sources. **No silent first-wins or last-wins**:
plugin identity ambiguity should fail loudly. Users resolve by uninstalling
the duplicate or setting `JOB_SCRAPER_DISABLE_PLUGINS=key1,key2` env var to
force-disable specific keys.

## 7. Public Python API

```python
# Re-exported from job_api_aggregator.__init__:
from job_api_aggregator import (
    # Discovery
    list_plugins,           # () -> list[PluginInfo]
    get_plugin,             # (key: str) -> PluginInfo | None

    # Plugin management
    make_enabled_sources,   # (credentials: dict, search: SearchParams) -> list[JobSource]
    JobSource,              # ABC; for plugin authors

    # Pipeline primitives
    scrape_description,     # (url: str, fallback: str) -> tuple[str, bool]

    # Schema types
    JobRecord,              # output dataclass / TypedDict
    PluginInfo,
    PluginField,
    SearchParams,           # input dataclass — see below
)

# SearchParams shape:
@dataclass(frozen=True)
class SearchParams:
    query: str | None = None
    location: str | None = None
    country: str | None = None        # ISO 3166-1 alpha-2
    hours: int = 168
    max_pages: int | None = None      # per-source cap; None = each plugin's default
    extra: dict[str, Any] | None = None  # plugin-specific freeform config (unstable)
    # `extra` is symmetric with JobRecord.extra: plugin-specific kwargs that do not
    # belong in the shared schema (e.g. Remotive category, Himalayas page_size, Jobicy
    # count, Adzuna results_per_page).  Not covered by schema_version — consumers use
    # extra.* at their own risk.
```

`job-matcher-pr/ingest.py` migration:

```python
# Before:
from job_sources import make_enabled_sources, get_required_search_fields
# (scrape_description was a local function in ingest.py)

# After:
from job_api_aggregator import make_enabled_sources, scrape_description, list_plugins
# get_required_search_fields equivalent: list_plugins() returns
# requires_credentials per plugin
```

## 8. CLI surface

### 8.1 `job-api-aggregator jobs`

```
job-api-aggregator jobs [OPTIONS]
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--hours N` | int | 168 | Lookback window. |
| `--query STRING` | string | none | Search terms. Applied per `accepts_query` per source. |
| `--location STRING` | string | none | Free-text location. Plugins use as a search hint where supported (no client-side geo filtering). |
| `--country CODE` | string | none | ISO 3166-1 alpha-2. |
| `--sources LIST` | comma list | all configured | Plugins to enable. |
| `--exclude-sources LIST` | comma list | none | |
| `--limit N` | int | unlimited | Cap on emitted records. |
| `--max-pages N` | int | source default | Cap per source. |
| `--credentials PATH` | path | required | JSON file of credentials per plugin. See §10. |
| `--format FORMAT` | enum | `jsonl` | `jsonl` \| `json`. |
| `--output PATH` | path | stdout | |
| `--strict` | flag | off | Exit non-zero on any source error. |
| `--dry-run` | flag | off | List which sources would run with which params. No HTTP calls. |
| `-v` / `-vv` / `--quiet` | flag | off | Stderr verbosity. |

### 8.2 `job-api-aggregator hydrate`

```
job-api-aggregator hydrate [OPTIONS]
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--input PATH` | path | stdin | JSONL file produced by `jobs`. `-` or omit for stdin. |
| `--output PATH` | path | stdout | |
| `--timeout-per-request N` | int | 15 | Per-URL HTTP timeout in seconds. |
| `--timeout-total N` | int | none | Hard wall-clock budget for the whole run. When exceeded, remaining records pass through unchanged (description not replaced) and a warning is logged. |
| `--continue-on-error` | flag | on | When a scrape fails (HTTP error, parse fail), pass the record through unchanged and log to stderr. Use `--strict` to exit non-zero on first failure instead. |
| `--strict` | flag | off | Exit non-zero on any scrape failure. |
| `--format FORMAT` | enum | inferred from input envelope | `jsonl` \| `json`. |
| `-v` / `-vv` / `--quiet` | flag | off | |

`hydrate` reads the envelope (if present) and propagates it; it modifies
`description` and `description_source` on each record. Records with
`description_source = "full"` already are passed through unchanged (no re-scrape).

#### 8.2.1 `hydrate` input handling — explicit cases

| Input record state | `hydrate` behaviour |
|---|---|
| `description_source = "full"` already | Pass through unchanged. No re-scrape. |
| `url` key absent OR `url = null` OR `url = ""` | Pass through unchanged. Emit warning to stderr identifying the record by `(source, source_id)`. Do not crash. |
| `url` is malformed (not http/https) | Same as missing url: pass through, warn. |
| `description_source` value not in `{"full","snippet","none"}` | Pass through unchanged. Emit warning. Defensive — handle records from future package versions gracefully. |
| Envelope `schema_version` differs from package's current major | Emit warning, proceed best-effort. Future-compat: same major version is required; cross-major refuses (exit code 4). |
| Scrape returns < `SCRAPE_MIN_LENGTH` chars | Treat as failure: preserve input description and `description_source`. Log to stderr. |
| Scrape returns HTTP 4xx/5xx or network error | Treat as failure: same behaviour as above. Log to stderr. |

**`--format` inference rule** (when `--format` not set explicitly): peek the
first non-whitespace byte of input. If it is `{` AND the first complete JSON
value parses as a single object containing `"jobs"`, treat as `--format
json`. Otherwise treat as `--format jsonl`. Document this in `--help`.

### 8.3 `job-api-aggregator sources`

Emits a JSON document describing every registered plugin:

```json
{
  "schema_version": "1.0",
  "plugins": [
    {
      "key": "adzuna",
      "display_name": "Adzuna",
      "description": "Global job aggregator with broad coverage...",
      "home_url": "https://www.adzuna.com",
      "geo_scope": "global-by-country",
      "accepts_query": "always",
      "accepts_location": true,
      "accepts_country": true,
      "rate_limit_notes": "1 req/sec, 250/day on free tier.",
      "fields": [
        {"name": "app_id", "label": "App ID", "type": "password", "required": true},
        {"name": "app_key", "label": "App Key", "type": "password", "required": true}
      ]
    }
  ]
}
```

If `--credentials PATH` is provided, also includes per-plugin
`credentials_configured: bool`.

## 9. Output schema

### 9.1 Plugin output audit (basis for the schema)

Audited Adzuna and RemoteOK `normalise()` output. Inconsistencies the
package's record normalizer must handle:

| Field | Adzuna | RemoteOK | Normalizer behaviour |
|---|---|---|---|
| `source` | always | always | Required; passed through |
| `source_id` | always (str) | always (str) | Required; records with empty value are emitted with empty string (NOT dropped — `ingest.run()` doesn't drop today; package doesn't either) |
| `title` | always | always | Required; may be empty string |
| `posted_at` | sometimes set | **never set** | Required after backfill; package's `jobs` orchestrator backfills from `created_at` (mirrors `ingest.run()` line 1503-1504) |
| `redirect_url` | always | always | Renamed to `url` in output; may be empty string |
| `description` | snippet | HTML-stripped snippet | Always present; in `jobs` output, this is the source's snippet. After `hydrate`, replaced with full text. |
| `salary_period` | always None | always None | Optional; null for both audited plugins. Documented as "rarely populated by current plugins". |

Audit must be repeated for the remaining 8 plugins as part of Issue B (see
§13). Any normalization edge cases discovered get added to this section.

### 9.2 Envelope

For `--format json`:

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
  "jobs": [ /* records */ ]
}
```

For `--format jsonl`: first line is the envelope (with `"jobs": []`); each
subsequent line is one record.

`hydrate` propagates the envelope from its input but updates `command` and
`generated_at`; `request_summary` from `jobs` is preserved.

### 9.3 Record fields — three categories

**Identity (always present, validation-checked):**

| Field | Type | Notes |
|---|---|---|
| `source` | string | Plugin key. |
| `source_id` | string | May be empty if upstream provides none — passed through unchanged. |
| `description_source` | enum | `"full"` (after `hydrate` succeeded) \| `"snippet"` (source-provided) \| `"none"` (no description available) |

**Always-present (always serialised, may be empty per stated rules):**

| Field | Type | Notes |
|---|---|---|
| `title` | string | May be empty when source provides nothing. |
| `url` | string | Renamed from `redirect_url`. May be empty. `hydrate` requires non-empty `url` to perform the scrape; records with empty `url` pass through unchanged. |
| `posted_at` | string \| null | RFC 3339 UTC. Backfilled from `created_at` by `jobs` orchestrator; null when both sources unparseable (logged to stderr). |
| `description` | string | Snippet from source after `jobs`; full text after successful `hydrate`; empty string when source provides none. |

**Optional (always serialised, often null):**

| Field | Type | Notes |
|---|---|---|
| `company` | string \| null | Empty string preserved if source provides it; absent key → null. |
| `location` | string \| null | Free-text from source. |
| `salary_min` | number \| null | |
| `salary_max` | number \| null | |
| `salary_currency` | string \| null | ISO 4217 where source provides. |
| `salary_period` | enum \| null | `"annual"` \| `"monthly"` \| `"hourly"`. **Currently null for all audited plugins.** |
| `contract_type` | string \| null | |
| `contract_time` | string \| null | |
| `remote_eligible` | bool \| null | |

**Source-specific blob:**

| Field | Type | Notes |
|---|---|---|
| `extra` | object \| null | Plugin-specific keys (e.g. `extra.adzuna.category`). **Marked unstable** — schema versioning does not promise stability of `extra.*`. |

### 9.4 Empty string vs. null

A documented contract: empty string means "source provided an empty value";
null means "source did not provide this key at all". Consumers can
distinguish.

### 9.5 Schema versioning

`schema_version` follows semver. Major bump for: removed/renamed Identity or
Always-present fields, type changes. Minor bump for: new Optional fields,
new envelope keys.

**`extra.*` policy (explicit):**
- `extra.*` shape is **NOT** covered by `schema_version`.
- The package may change `extra.*` keys, types, and structure in any
  release (including patch versions) without notice.
- Tests in the package do **not** assert `extra.*` shape; only that `extra`
  is an object when present.
- Consumers depending on `extra.*` are explicitly out of warranty.
- When a field in `extra` is consistently demanded by consumers, it gets
  promoted to a real Category 3 field in a minor version bump (which IS
  covered by `schema_version`). Until then, `extra` is "best effort raw
  passthrough."

This policy is non-negotiable: a "documented unstable" subtree without
testing or stability is the only sane way to handle source-specific data
that the package can't generalize.

### 9.6 `description_source` truth table (the canonical reference)

Both the package's `jobs` orchestrator, the package's `hydrate` orchestrator,
and `job-matcher-pr`'s `ingest.run()` scrape branch must implement this
table identically. Tests in both repos validate against it.

**`jobs` orchestrator (no scrape, just emit what plugins provide):**

| Plugin sets `skip_scrape` | Plugin sets `description_is_full` | `len(description) >= SCRAPE_MIN_LENGTH` | Result `description_source` |
|---|---|---|---|
| True | True | True | `"full"` |
| True | True | False | `"snippet"` |
| True | False | n/a | `"snippet"` |
| False | n/a | n/a | `"snippet"` |
| n/a | n/a | description is empty | `"none"` |

**`hydrate` orchestrator (does HTTP scrape):**

| Input `description_source` | Scrape outcome | Result `description_source` | Result `description` |
|---|---|---|---|
| `"full"` | (skipped — already full) | `"full"` (unchanged) | unchanged |
| `"snippet"` or `"none"` | success, body ≥ MIN | `"full"` | scraped text |
| `"snippet"` or `"none"` | failure (HTTP error, parse fail, body < MIN) | unchanged | unchanged |
| `"snippet"` or `"none"` | url empty/missing | unchanged | unchanged |

**`ingest.run()` per-listing scrape branch:** logically equivalent to
`jobs` row classification + (if scraping is in scope for the run) `hydrate`
row classification. The contract test described in §5.3 validates this.

**`SCRAPE_MIN_LENGTH`** is defined as a public constant in
`job_api_aggregator.scraping`. `ingest.py` imports it; never redefines it locally.

## 10. Credentials file format

The package OWNS this format (it's part of the package's stable contract).

```json
{
  "schema_version": "1.0",
  "plugins": {
    "adzuna": {
      "app_id": "abc123",
      "app_key": "def456"
    },
    "jooble": {
      "api_key": "..."
    }
  }
}
```

`job-matcher-pr` continues to use its existing `providers.json` shape (which
has `job_sources.<key>.<field>` rather than `plugins.<key>.<field>`) — the
app's existing storage is preserved. A named adapter function in
`job-matcher-pr` (suggested location:
`job-matcher-pr/credentials.py::translate_to_package_credentials`)
translates the app's internal credential dict into the package's expected
shape at the boundary where `make_enabled_sources()` is called.

This adapter is **not 10 lines** — it must handle:

1. **Env-var precedence**: `credentials.load_providers()` already injects
   `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` from env vars into the providers dict
   via `_inject_env_var_credentials()`. The adapter receives the
   **post-injection** dict (env-var precedence is preserved transparently).
2. **Drop user state**: strip `enabled` toggle from each source entry — the
   package's credential format only carries credential field values.
3. **Skip disabled sources**: the package's `make_enabled_sources()` is
   driven by which keys appear in the credentials dict; the adapter only
   includes entries for sources whose `enabled = True` (or default-enabled
   keyless sources with no entry). This mirrors the existing
   `make_enabled_sources()` filtering logic.
4. **Pass through the legacy `keys.json` migration**: `load_providers()`
   handles this before the adapter sees the dict. No change needed in the
   adapter itself.

The adapter is ~30-40 LOC including its own unit tests. It lives in
`job-matcher-pr` (not in the package) because the conversion is
app-specific. External consumers of the package write credentials directly
in the package's format — no adapter needed for them.

The user-facing `providers.json` file on disk does not change shape; the
Settings UI continues to read and write `providers.json` exactly as today.

The package documents its credentials shape in `docs/output_schema.md`
alongside the output schema. External consumers write credentials in this
shape directly.

## 11. Plugin contract

Each plugin is a Python class that:

1. Subclasses `job_api_aggregator.JobSource` (ABC)
2. Declares class-level metadata: `SOURCE` (key), `DISPLAY_NAME`,
   `DESCRIPTION`, `HOME_URL`, `GEO_SCOPE`, `ACCEPTS_QUERY`,
   `ACCEPTS_LOCATION`, `ACCEPTS_COUNTRY`, `RATE_LIMIT_NOTES`
3. Implements `@classmethod settings_schema(cls) -> dict` returning the
   field definitions used to populate `PluginInfo.fields`.  The classmethod
   decoration is required so callers can introspect the schema without
   constructing an instance.
4. Implements a keyword-only constructor with the canonical signature:
   ```python
   def __init__(
       self,
       *,
       credentials: dict[str, Any] | None = None,
       search: SearchParams | None = None,
   ) -> None:
       super().__init__(credentials=credentials, search=search)
       # validate credentials and unpack search here …
   ```
   No-auth plugins accept but ignore `credentials`.  Plugins that require
   credentials raise `CredentialsError` from `__init__` if required fields
   are absent or empty.
5. Implements `pages() -> Iterator[list[dict]]` yielding pages of normalized
   listings
6. Implements `normalise(raw: dict) -> dict` mapping source-API responses to
   the package's expected output shape

`PluginInfo` is built by reading these declarations + the `settings_schema()`
classmethod return value. `requires_credentials` is derived at runtime from
`fields[].required`.

**`required_search_fields` moves to `PluginInfo`** (drift mitigation per
v3 inquisitor finding #8). Currently `REQUIRED_SEARCH_FIELDS` is a class
attribute on each `JobSource` subclass, consumed by
`ingest.validate_search_config` in `job-matcher-pr`. After migration:

- The class attribute moves to the package alongside the rest of the plugin
  metadata.
- `PluginInfo.required_search_fields: list[str]` exposes it.
- `validate_search_config` in `job-matcher-pr` reads from `PluginInfo` via
  `list_plugins()`, NOT from the class attribute directly.
- A new plugin declaring `REQUIRED_SEARCH_FIELDS = ("foo",)` automatically
  flows through to the validator without requiring `job-matcher-pr` updates.

This eliminates the silent cross-repo drift risk where adding a required
search field in the package would cause runtime failures in
`job-matcher-pr` until its validator was manually updated.

The 10 existing plugins in `job-matcher-pr/plugins/sources/` mostly conform
to the basic structure but **do not currently declare** the new metadata
attributes (`DISPLAY_NAME`, `DESCRIPTION`, `HOME_URL`, `GEO_SCOPE`,
`ACCEPTS_QUERY`, `ACCEPTS_LOCATION`, `ACCEPTS_COUNTRY`,
`RATE_LIMIT_NOTES`). Filling these in for each plugin is a **real audit
task**, not mechanical — the user must read each plugin's `fetch_page()` to
determine actual query/location/country handling. This audit is tracked as
per-plugin sub-issues in §13 (Issues B1-B10).

## 11.5 Plugin metadata catalog (audit deliverable for Issues B1-B10)

This section is the canonical audit deliverable. Each row is filled in by
its corresponding per-plugin migration issue (B1-B10). Values left as `?`
are unknown until the plugin's `fetch_page()` is read; values left as TBD
are decisions the migrator makes based on that reading.

| Plugin | DISPLAY_NAME | GEO_SCOPE | ACCEPTS_QUERY | ACCEPTS_LOCATION | ACCEPTS_COUNTRY | RATE_LIMIT_NOTES | REQUIRED_SEARCH_FIELDS |
|---|---|---|---|---|---|---|---|
| adzuna | Adzuna | global-by-country | always | true | true | "~1 req/sec sustained; free tier capped at 250 req/day." | ("country","query") — verified #5 |
| arbeitnow | Arbeitnow | regional | never | false | false | "Public API; no documented rate limit. Practical cap: ~1 req/s." | () |
| himalayas | Himalayas | remote-only | never | false | false | "Public API; no published limit. Observed soft limit ~1 req/sec." | () |
| jobicy | Jobicy | remote-only | partial | false | false | "No published rate limit; single request per run." | () |
| jooble | Jooble | global | always | true | false | "No published hard limit; free-tier key, use responsibly." | () |
| jsearch | JSearch (RapidAPI) | global | always | true | false | "RapidAPI quota varies by plan; free tier 200 requests/month" | ("query",) |
| remoteok | RemoteOK | remote-only | never | false | false | "Public, soft rate limits" | () |
| remotive | Remotive | remote-only | always | false | false | "No published rate limit; public API, use conservatively." | () |
| the_muse | The Muse | global | partial | false | false | "Public API; no published hard limit. Optional api_key reduces throttling." | () |
| usajobs | USAJobs | federal-us | partial | false | false | "Email-tagged user-agent required; no published numeric limit" | () |

The audit is real work, not mechanical. The values shown for adzuna,
remoteok, jsearch, and usajobs are starting points based on what is already
known from CLAUDE.md, plugin source, or prior context — they still must be
verified against actual plugin behaviour as part of B1-B10.

`DESCRIPTION` and `HOME_URL` for each plugin are reused from the existing
`source.json` files (already populated; copy verbatim).

The completed catalog becomes part of `docs/output_schema.md` in the
package as the canonical "what each plugin supports" reference.

## 12. Migration plan for `job-matcher-pr` — **PHASE 2 (DEFERRED)**

> **This entire section describes Phase 2 work. It is included in the spec
> for forward-planning but does NOT begin until Phase 1 has shipped v1.0 of
> `job-api-aggregator` and the target external consumer has validated the
> package contract. Treat the content below as a planning artifact, not as
> immediate work.**

### 12.1 Repo layout during development

```
~/code/
├── job-matcher-pr/         # existing repo
└── job-api-aggregator/            # NEW repo (sibling)
```

`job-matcher-pr`'s dev venv:

```bash
pip install -e ../job-api-aggregator
```

This means the working code on disk is the only copy; both repos read from
the same source. **Zero divergence window.**

### 12.2 Migration sequence (revised — lockstep to avoid plugin-set disagreement)

The original ordering migrated UI before ingest, creating a window where
the settings UI listed package plugins while ingest still loaded local
plugins. If the two plugin sets disagreed (typo in entry-point, plugin added
mid-migration), the user could enable a source in the UI that ingest
couldn't run, or vice versa. Revised sequence eliminates this window:

1. **Build `job-api-aggregator` package** (Issues A-G in §13). Install into
   `job-matcher-pr` venv via editable install. Verify package CLI works
   standalone.
2. **Add a parity assertion test** in `job-matcher-pr` (~10 LOC) that
   imports both the local `job_sources.get_sources()` and
   `job_api_aggregator.list_plugins()` and asserts the keys match. This test is
   added BEFORE step 3 and removed in step 4. It guards the migration.
3. **Lockstep migration PR**: a single PR that migrates BOTH `ingest.py`
   AND `web/settings.py` + `web/admin.py` to import from `job_api_aggregator`. The
   parity test from step 2 ensures plugin sets match before this PR can
   merge. UI and ingest read from the same source from the moment the PR
   lands.
4. **Delete `job-matcher-pr/job_sources/`** and
   `job-matcher-pr/plugins/`. Remove the parity test (no longer applicable
   — only one source of plugin definitions remains).
5. **Run full test suite** (2062 tests). Fix any test breakage from import
   path changes.
6. **Add `job-api-aggregator>=1.0`** to `requirements.txt`.

The lockstep PR (step 3) is the only step with risk; the parity test (step
2) and full-suite verification (step 5) bracket it.

### 12.3 Production deployment

Two phases:
- **Phase 1 (development)**: editable install from sibling directory. No
  PyPI publish needed.
- **Phase 2 (production)**: publish `job-api-aggregator` to PyPI; pin in
  `job-matcher-pr/requirements.txt` (`job-api-aggregator==1.0.0`). Optional —
  during the development period, consumers can install via git ref
  (`pip install git+https://github.com/.../job-api-aggregator.git@v1.0.0`).

## 13. Issue breakdown

A Milestone titled **"job-api-aggregator v1"** in the new repo. A separate
Milestone titled **"Migrate to job-api-aggregator"** in `job-matcher-pr`.

### `job-api-aggregator` repo issues (Phase 1 — start here):

| # | Title | Scope |
|---|---|---|
| A | Set up package skeleton (pyproject with `requires-python = ">=3.11"`, tests dir, CI workflow with import-fence check enforcing no `db`/`flask` imports, README) | Pure infrastructure |
| B | **Plugin contract design**: define `JobSource` ABC v3 with new metadata attributes (`DISPLAY_NAME`, `DESCRIPTION`, `HOME_URL`, `GEO_SCOPE`, `ACCEPTS_QUERY`, `ACCEPTS_LOCATION`, `ACCEPTS_COUNTRY`, `RATE_LIMIT_NOTES`, `REQUIRED_SEARCH_FIELDS`). Define `PluginInfo` and `PluginField` schemas. Define entry-point collision policy. | New ABC + schemas |
| B1-B10 | **Per-plugin migration** (one issue per plugin): adzuna, arbeitnow, himalayas, jobicy, jooble, jsearch, remoteok, remotive, the_muse, usajobs. For each: move file, fill in 8 new metadata attributes (read `fetch_page()` to verify actual behaviour), audit `normalise()` output against §9.3 categories, write per-plugin tests including VCR-recorded `fetch_page()` cassette (see §14.1), populate the metadata catalog row in §11.5. | 10 separate issues, ~1-3h each. The metadata audit is **explicit work**, not mechanical. |
| C | Build `JobRecord` schema + record normalizer (renames, date normalization, posted_at backfill, empty-vs-null preservation, extra blob assembly) | New |
| D | Build `job-api-aggregator jobs` orchestrator + output formatters + in-memory deduplicator | New |
| E | Build `job-api-aggregator hydrate` command (move `scrape_description` and `SCRAPE_MIN_LENGTH` from ingest.py to `job_api_aggregator.scraping`); implement §8.2.1 input handling table | New |
| F | Build `job-api-aggregator sources` command + `list_plugins`/`get_plugin` Python API | New |
| G | Documentation: README, output schema (§9 of this spec), plugin authoring guide (incl. metadata attribute meanings), sample fixture (`docs/examples/sample-output.jsonl`), `extra.*` policy disclaimer | Docs |

### `job-matcher-pr` repo issues (Phase 2 — deferred until Phase 1 ships):

| # | Title | Scope |
|---|---|---|
| H | Add parity assertion test (per §12.2 step 2) that locks plugin-set equality between local and package | Pre-migration safety net |
| I | **Lockstep migration PR**: migrate `ingest.py` AND `web/settings.py` + `web/admin.py` to use `job_api_aggregator`. Includes credentials adapter (per §10) at `credentials.py::translate_to_package_credentials` with its own unit tests. Update `validate_search_config` to read `required_search_fields` from `PluginInfo`. Delete local `job_sources/` and `plugins/`. Remove parity test. | The single risky step in the migration |
| J | Add `tests/test_scrape_classification_parity.py` — contract test asserting `ingest.run()`'s scrape branch matches the §9.6 truth table (drift mitigation per §5.3) | Drift guard |
| K | Update `requirements.txt`; verify CI passes against the editable install (or pinned version); update README with new dependency note | Plumbing |

## 14. Testing strategy

### 14.1 In `job-api-aggregator`

**Per-plugin tests** (one file each, 10 files):

- `normalise()` test: pass a synthetic raw API dict, assert output conforms
  to §9.3 categories. Pure unit test, no I/O.
- `fetch_page()` test: use VCR.py (`pytest-recording` or
  `vcrpy`) cassettes. Each plugin has 1-2 cassettes recorded once with real
  credentials by the maintainer, committed to
  `tests/cassettes/<plugin>/`. CI replays cassettes — **no live API calls
  in CI, no credential dependency**. To re-record (when a source's API
  format changes), the maintainer deletes the cassette, runs the test
  locally with real credentials, commits the new cassette.
- `pages()` iteration test: drives `pages()` against a stub `fetch_page()`
  return; asserts pagination termination and per-page list shape.

**Schema tests:**

- `JobRecord`, `PluginInfo`, `PluginField` round-trip serialization
- `schema_version` compatibility: emit a v1.0 record, parse with v1.0
  consumer, assert ≅
- `extra.*` is **not** asserted — see §9.5 policy

**Orchestrator tests** (end-to-end with stub plugins from
`tests/fixtures/plugins/`):

- `jobs`: JSONL stream shape, envelope correctness, `--strict` behaviour,
  `--dry-run`, `--limit`, `--sources` filtering, `--exclude-sources`
- `hydrate`: stub HTTP server (`responses` library), assert scrape success,
  scrape failure → preserve, timeout enforcement, `--strict` vs default,
  every row of the §9.6 hydrate truth table

**CLI integration tests:** invoke `job-api-aggregator` as subprocess with various
args; verify exit codes per §11; verify smoke test passes (`job-api-aggregator
--help`, `job-api-aggregator sources`, `job-api-aggregator jobs --dry-run`).

**Import-fence test** (added to CI): `tests/test_no_db_imports.py` greps
the entire `src/job_api_aggregator/` tree for `import db`, `from psycopg2`, `from
flask`, `from anthropic`, etc. Fails CI if any forbidden import is added.
Enforces the no-DB / no-web / no-LLM constraint structurally.

### 14.2 In `job-matcher-pr` — **PHASE 2 (DEFERRED)**

- The existing 2062-test suite must continue to pass after migration
- One new integration test: render `/settings/sources` page and assert all
  10 plugins appear with correct field types
- Contract test asserting `ingest.run()`'s scrape branch matches the §9.6
  truth table (drift mitigation per §5.3)

## 15. Constraints

| # | Decision |
|---|---|
| 1 | Package is its own repo, separate from `job-matcher-pr`. |
| 2 | Editable install (`pip install -e ../job-api-aggregator`) used during development. **No code duplication, no divergence window.** |
| 3 | Package has zero database access. Cannot import `psycopg2`, `db`, or anything that does. CI enforces this with an import check. |
| 4 | Package has zero web-framework access. No Flask, no Django imports. |
| 5 | No filtering in package beyond fetch-side params (hours, source list). Title/contract/geo filters stay in `job-matcher-pr`. |
| 6 | `jobs` and `hydrate` are separate commands; no `--include-descriptions` flag. |
| 7 | Output schema is versioned per §9.5. Breaking changes bump major. |
| 8 | Credentials file format is owned by package and versioned per §10. |
| 9 | Plugin contract is the package's `JobSource` ABC; plugins authored against package version. |
| 10 | `job-matcher-pr/ingest.py` continues to do its own scoring + DB writes. Package never touches scoring or DB. |

## 16. Inquisitor finding resolution (v1 + v2 + v3-pass)

| Finding | v1 status | v2 status | v3 status | v3 post-patch |
|---|---|---|---|---|
| B1 (salary_min consolidation) | Real | Paper-fixed | ✅ Eliminated (no filtering in package) | unchanged |
| B2 (`process_listing()` extraction) | Real | Real | ✅ Eliminated (separate orchestrators) | unchanged |
| B2 follow-on (empty source_id drop) | Real | Real | ✅ Eliminated (preserves empty) | unchanged |
| B3 (`requires_credentials` audit) | Real | Real | 🟡 Tractable | ✅ **Resolved** — split into B1-B10 with per-plugin audit; §11.5 catalog tracks completion |
| M1 ("required" fields not actually required) | Real | Real | 🟡 Tractable | ✅ **Resolved** — same split + §11.5 catalog |
| M2 (GeoFilter DB coupling) | Real | Paper-fixed | ✅ Eliminated | unchanged |
| M3 (30-min serial runs) | Real | Mitigated | ✅ Reframed | unchanged |
| M4 (hours filter duplicated) | Real | Fixed via extraction | ✅ Eliminated | unchanged |
| m8 (`--credentials` shape stability) | Real | Documented | ✅ Cleaner | unchanged |
| m9 (`extra: {}` foot-gun) | Real | Documented | 🟡 Same | ✅ **Resolved** — explicit policy in §9.5: not version-covered, not tested, consumer-out-of-warranty |
| m10 (`--dry-run` Nominatim) | Real | Fixed | ✅ Eliminated | unchanged |
| N1 (`import ingest` requires DATABASE_URL) | — | Real | ✅ Eliminated | unchanged |
| N2 (DBDeduplicator regression) | — | Real | ✅ Eliminated | unchanged |
| N3 (`--query` mixed-mode trap) | — | Real | 🟡 Same | unchanged (documented design choice) |
| **v3-pass: scrape decision tree drift** | — | — | — | ✅ **Resolved** — `SCRAPE_MIN_LENGTH` pinned to package; truth table in §9.6; parity test in `job-matcher-pr` (Issue J) |
| **v3-pass: Issue B under-scoped** | — | — | — | ✅ **Resolved** — split into B + B1-B10; §11.5 catalog visualizes the work |
| **v3-pass: migration step ordering** | — | — | — | ✅ **Resolved** — lockstep migration PR (§12.2 step 3) + parity test (Issue H) |
| **v3-pass: credentials translation > 10 lines** | — | — | — | ✅ **Resolved** — promoted to named function `translate_to_package_credentials` with own tests; precedence rules documented in §10 |
| **v3-pass: `hydrate` input contract gaps** | — | — | — | ✅ **Resolved** — §8.2.1 with explicit per-case behaviour table |
| **v3-pass: entry-point collision semantics** | — | — | — | ✅ **Resolved** — error-on-collision policy in §6 |
| **v3-pass: Python version policy** | — | — | — | ✅ **Resolved** — `requires-python = ">=3.11"` in §6 |
| **v3-pass: `REQUIRED_SEARCH_FIELDS` cross-repo coupling** | — | — | — | ✅ **Resolved** — moved to `PluginInfo`; `validate_search_config` reads from package introspection (§11) |
| **v3-pass: `fetch_page()` test fixtures** | — | — | — | ✅ **Resolved** — VCR cassettes per plugin; documented in §14.1 |
| **v3-pass: `extra.*` enforcement policy** | — | — | — | ✅ **Resolved** — explicit policy in §9.5 |

**Tally after v3 patches:** 23 of 24 findings resolved. 1 (N3) remains as a
documented design choice with consumer-side mitigation.

## 17. v2 → v3 reframe rationale

v2 attempted to ship the CLI inside `job-matcher-pr` while sharing pipeline
primitives with `ingest.run()`. The v2 inquisitor found that the
combination of three goals — reuse existing primitives, no DB required from
CLI, behaviour-preserving for `ingest.run()` — could not all be honored
simultaneously. Each spec revision tightened one constraint at the cost of
another.

v3 dissolves the constraint by removing the in-repo coupling. Pipeline
primitives move to a separate package; `job-matcher-pr` becomes a consumer
of the package on the same footing as external evaluation tools. The
package is structurally independent (its own repo, its own `pyproject.toml`,
its own tests, its own CI, its own contract), so behaviour-preservation,
import topology, and DB coupling become non-issues — the package literally
cannot import the things that caused v2's problems, and `ingest.run()` is
not modified.

The cost is approximately the same engineering effort as v2 (move plugins,
build CLI, build introspection API, write tests, migrate `ingest.py` and
`web/settings.py`) but the result is structurally simpler and produces a
real reusable package.

## 18. Deferred (NOT for v1)

- `--concurrency N` for `hydrate` (track as separate issue once v1 ships)
- Salary normalization across `salary_period`
- Caching layer between `jobs` and `hydrate` (consumers compose with shell)
- Progress bar on stderr
- `extra.*` field promotion process
- REST/gRPC API surface
- Plugin author publishing to PyPI as separate packages (entry-points
  support is in place; documentation and ergonomics deferred to v1.1)

## 19. References

- **Brainstorm session** (2026-04-23) — this conversation
- **Inquisitor reviews** — v1 review (3 blockers, 4 majors, 3 minors); v2
  review (verified blockers + 3 new findings); v3 expected to be
  substantially cleaner
- **Existing code** — `job-matcher-pr/job_sources/`, `plugins/sources/`,
  `ingest.py` (functions to migrate: `make_enabled_sources`, `scrape_description`)
- **Plugin output audit** — Adzuna `plugins/sources/adzuna/plugin.py` lines
  186-222; RemoteOK `plugins/sources/remoteok/plugin.py` lines 146-196.
  Remaining 8 plugins to be audited as part of Issue B.
