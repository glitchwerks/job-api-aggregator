# Credentials File Format

This document specifies the credentials file format owned by the
`job-api-aggregator` package. This is a stable contract — the shape is covered
by semantic versioning.

---

## Table of Contents

1. [File Format](#file-format)
2. [Top-Level Fields](#top-level-fields)
3. [Plugin Credential Fields](#plugin-credential-fields)
4. [How `required` Drives Validation](#how-required-drives-validation)
5. [Usage Example](#usage-example)

---

## File Format

Credentials are stored in a JSON file with the following shape:

```json
{
  "schema_version": "1.0",
  "plugins": {
    "adzuna": {
      "app_id": "abc123",
      "app_key": "def456"
    },
    "jooble": {
      "api_key": "your_jooble_key_here"
    }
  }
}
```

Pass the file path to the CLI with the `--credentials` flag:

```bash
job-api-aggregator jobs --query "python developer" --credentials ~/.job-api-aggregator/creds.json
```

---

## Top-Level Fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | string | Always `"1.0"` for this format. |
| `plugins` | object | A mapping from plugin key to that plugin's credential fields. |

Only plugins that require credentials need an entry under `plugins`. Plugins
with an empty `settings_schema()` (no required credentials) run without any
entry in this file.

---

## Plugin Credential Fields

Each key under `"plugins"` is a plugin's `SOURCE` key (e.g. `"adzuna"`).
The value is a flat object whose keys are the field names declared by that
plugin's `settings_schema()`.

The exact fields required by each plugin are described in
[plugin_authoring.md](plugin_authoring.md#implementing-settings_schema) and
are discoverable at runtime via `job-api-aggregator sources`:

```bash
job-api-aggregator sources --credentials path/to/creds.json
```

When `--credentials` is supplied, the `sources` output includes a
`credentials_configured` flag for each plugin indicating whether the
credentials file contains an entry for it.

### Current plugins and their credential fields

| Plugin | Required Fields | Notes |
|---|---|---|
| `adzuna` | `app_id`, `app_key` | From the Adzuna developer console. |
| `arbeitnow` | (none) | Public API. |
| `himalayas` | (none) | Public API. |
| `jobicy` | (none) | Public API. |
| `jooble` | `api_key` | Request a key at jooble.org. |
| `jsearch` | `api_key` | RapidAPI key with JSearch subscription. |
| `remoteok` | (none) | Public API. |
| `remotive` | (none) | Public API. |
| `the_muse` | `api_key` (optional) | Public API; key is optional and reduces throttling. |
| `usajobs` | `email`, `api_key` | USAJOBS requires an email-tagged user-agent. |

---

## How `required` Drives Validation

Each field in a plugin's `settings_schema()` has an optional `"required"`
boolean. When `"required": true`, the orchestrator checks that the field is
present and non-empty in the credentials dict before constructing the plugin.
If the field is missing, the plugin raises `CredentialsError` from its
`__init__`.

Fields marked `"required": false` (or without a `"required"` key) are
optional enhancements. Missing optional fields do not prevent the plugin from
running.

The `PluginInfo.requires_credentials` property (accessible via
`job_api_aggregator.list_plugins()`) is `True` when any field in the plugin's
schema has `"required": true`. This lets callers quickly determine which
plugins need a credentials entry before attempting to run them.

---

## Usage Example

To run `jobs` with credentials for Adzuna and Jooble:

```bash
# Save your credentials
cat > ~/.job-api-aggregator/creds.json <<'EOF'
{
  "schema_version": "1.0",
  "plugins": {
    "adzuna": {
      "app_id": "YOUR_APP_ID",
      "app_key": "YOUR_APP_KEY"
    },
    "jooble": {
      "api_key": "YOUR_JOOBLE_KEY"
    }
  }
}
EOF

# Run a search using those credentials
job-api-aggregator jobs \
  --query "python developer" \
  --hours 24 \
  --credentials ~/.job-api-aggregator/creds.json \
  | job-api-aggregator hydrate > full.jsonl
```

Plugins without a credentials entry in the file are still run if they do not
require credentials (e.g. `remoteok`, `himalayas`).

To restrict which plugins run on a given invocation, use the `--sources` and
`--exclude-sources` CLI flags:

```bash
# Run only adzuna and jooble
job-api-aggregator jobs --query "python developer" --credentials creds.json \
  --sources adzuna,jooble

# Run all configured sources except the_muse and usajobs
job-api-aggregator jobs --query "python developer" --credentials creds.json \
  --exclude-sources the_muse,usajobs
```

The `JOB_SCRAPER_DISABLE_PLUGINS` environment variable provides a persistent
override — plugins listed there are excluded from every run regardless of
`--sources`. This is useful for suppressing a broken or rate-limited source
across multiple invocations without editing your credentials file, or for
resolving collisions when two registered plugins share a key:

```bash
export JOB_SCRAPER_DISABLE_PLUGINS="the_muse,usajobs"
job-api-aggregator jobs --query "python developer" --credentials creds.json
```
