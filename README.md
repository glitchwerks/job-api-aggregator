# job-api-aggregator

Reusable job aggregation library: pluggable source plugins, normalized output, no scoring or DB dependencies.

[![PyPI version](https://img.shields.io/pypi/v/job-api-aggregator)](https://pypi.org/project/job-api-aggregator/)
[![CI](https://github.com/glitchwerks/job-api-aggregator/actions/workflows/ci.yml/badge.svg)](https://github.com/glitchwerks/job-api-aggregator/actions/workflows/ci.yml)
[![Python versions](https://img.shields.io/pypi/pyversions/job-api-aggregator)](https://pypi.org/project/job-api-aggregator/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Installation

```bash
pip install job-api-aggregator
```

## Quickstart

```bash
# List available plugins and whether credentials are configured
job-api-aggregator sources

# Fetch listings from no-auth sources and enrich with full descriptions.
# Run `job-api-aggregator sources` to see which plugins need credentials —
# the example below excludes the four credentialed plugins so it runs
# out of the box without a credentials file.
job-api-aggregator jobs --query "python developer" --hours 24 \
  --exclude-sources adzuna,jooble,jsearch,usajobs \
  | job-api-aggregator hydrate > full.jsonl
```

Each line of `full.jsonl` after the first is a normalized job record. The
first line is the output envelope (see [docs/output_schema.md](docs/output_schema.md)
for the full field reference).

```bash
# With credentials for paid/keyed sources
job-api-aggregator jobs --credentials providers.json --sources adzuna,jooble --hours 24 \
  | job-api-aggregator hydrate > full.jsonl
```

See [docs/credentials_format.md](docs/credentials_format.md) for the
credentials file format and per-plugin field requirements.

## Documentation

- [Output Schema](docs/output_schema.md) — envelope structure, record fields,
  `description_source` truth table, versioning policy, and supported sources.
- [Plugin Authoring Guide](docs/plugin_authoring.md) — how to write and
  register a new source plugin.
- [Credentials Format](docs/credentials_format.md) — credentials file format
  and per-plugin field requirements.

## Status

**Pre-1.0 / Alpha.** The public API, output schema, and credentials format
are under active development and may change between releases until `v1.0.0`
is tagged.
