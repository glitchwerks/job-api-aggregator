# Plugin Authoring Guide

This guide explains how to write a new `job-api-aggregator` source plugin —
either as part of the bundled set or as a third-party package distributed
separately on PyPI.

---

## Table of Contents

1. [Overview](#overview)
2. [Subclassing JobSource](#subclassing-jobsource)
3. [Class-Level Metadata Attributes](#class-level-metadata-attributes)
4. [Constructor Signature](#constructor-signature)
5. [Implementing `settings_schema()`](#implementing-settings_schema)
6. [Implementing `pages()`](#implementing-pages)
7. [Implementing `normalise()`](#implementing-normalise)
8. [Credentials and Validation](#credentials-and-validation)
9. [Registering via Entry-Points](#registering-via-entry-points)
10. [Testing with VCR Cassettes](#testing-with-vcr-cassettes)
11. [Exception Hierarchy](#exception-hierarchy)

---

## Overview

A plugin is a Python class that:

1. Subclasses `job_api_aggregator.JobSource` (an abstract base class).
2. Declares nine required class-level metadata attributes.
3. Implements `settings_schema()`, `pages()`, and `normalise()`.
4. Registers itself via a `job_api_aggregator.plugins` entry-point.

The base class enforces attribute presence at class-creation time (not at
runtime), so a missing attribute raises `TypeError` on import rather than
producing a confusing `AttributeError` during a live run.

---

## Subclassing JobSource

```python
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from job_api_aggregator import JobSource
from job_api_aggregator.schema import SearchParams


class Plugin(JobSource):
    SOURCE = "mysource"
    DISPLAY_NAME = "My Source"
    DESCRIPTION = "Fetches jobs from the My Source API."
    HOME_URL = "https://mysource.example.com"
    GEO_SCOPE = "global"
    ACCEPTS_QUERY = "always"
    ACCEPTS_LOCATION = True
    ACCEPTS_COUNTRY = False
    RATE_LIMIT_NOTES = "No published rate limit."
    REQUIRED_SEARCH_FIELDS: tuple[str, ...] = ()

    @classmethod
    def settings_schema(cls) -> dict[str, Any]:
        return {
            "api_key": {
                "label": "API Key",
                "type": "password",
                "required": True,
                "help_text": "Found in your My Source developer console.",
            }
        }

    def __init__(
        self,
        *,
        credentials: dict[str, Any] | None = None,
        search: SearchParams | None = None,
    ) -> None:
        super().__init__(credentials=credentials, search=search)
        creds = credentials or {}
        if not creds.get("api_key"):
            from job_api_aggregator import CredentialsError
            raise CredentialsError(self.SOURCE, ["api_key"])
        self._api_key = creds["api_key"]

    def pages(self) -> Iterator[list[dict[str, Any]]]:
        # Fetch pages from the API and yield each page as a list of raw dicts.
        ...

    def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
        # Map a raw API dict to the JobRecord shape.
        ...
```

---

## Class-Level Metadata Attributes

Every concrete `JobSource` subclass must declare all nine attributes below.
Missing any one raises `TypeError` at import time.

| Attribute | Type | Description |
|---|---|---|
| `SOURCE` | `str` | Unique machine-readable plugin key. Used as the `source` field in output records and as the dict key in credentials files. Must be lowercase with underscores (e.g. `"my_source"`). Must not collide with any other registered plugin. |
| `DISPLAY_NAME` | `str` | Human-readable name shown in UIs and the `job-api-aggregator sources` listing (e.g. `"My Source"`). |
| `DESCRIPTION` | `str` | Short description of what this source provides (one or two sentences). |
| `HOME_URL` | `str` | URL for the source's public homepage or API documentation. |
| `GEO_SCOPE` | `str` | Geographic coverage. One of: `"global"`, `"global-by-country"`, `"remote-only"`, `"federal-us"`, `"regional"`, `"unknown"`. |
| `ACCEPTS_QUERY` | `str` | How the source handles a free-text search query. One of: `"always"` (query is sent to the API), `"partial"` (best-effort or category-based), `"never"` (source ignores the query). |
| `ACCEPTS_LOCATION` | `bool` | `True` if the source API accepts a location string parameter. |
| `ACCEPTS_COUNTRY` | `bool` | `True` if the source API accepts an ISO 3166-1 alpha-2 country code. |
| `RATE_LIMIT_NOTES` | `str` | Human-readable description of the source's rate limits or throttling behaviour. Required even if only to say "No published limit." |

There is one additional optional class attribute:

| Attribute | Type | Default | Description |
|---|---|---|---|
| `REQUIRED_SEARCH_FIELDS` | `tuple[str, ...]` | `()` | Names of `SearchParams` fields that must be non-`None` for the plugin to run. If a required field is absent, the orchestrator skips the plugin with a warning rather than raising. |

---

## Constructor Signature

Every plugin **must** use this exact keyword-only constructor signature and
call `super().__init__()` first:

```python
def __init__(
    self,
    *,
    credentials: dict[str, Any] | None = None,
    search: SearchParams | None = None,
) -> None:
    super().__init__(credentials=credentials, search=search)
    # validate credentials and unpack search parameters here
```

- The base class stores `credentials` as `self._credentials` and `search` as
  `self._search`.
- No-auth plugins must still accept `credentials` and pass it to `super()`;
  they simply ignore the value.
- If required credentials are missing or empty, raise `CredentialsError`
  from `job_api_aggregator` immediately in `__init__` rather than deferring the
  failure to `pages()`.

---

## Implementing `settings_schema()`

`settings_schema()` is a `@classmethod` that returns a dict describing the
credential fields the plugin requires. It must be callable without
constructing an instance.

```python
@classmethod
def settings_schema(cls) -> dict[str, Any]:
    return {
        "app_id": {
            "label": "App ID",
            "type": "text",
            "required": True,
            "help_text": "Your application identifier.",
        },
        "app_key": {
            "label": "App Key",
            "type": "password",
            "required": True,
        },
    }
```

Each key in the dict is a credential field name (matches the key in the
credentials file). Each value is a field definition dict with these keys:

| Key | Type | Required | Description |
|---|---|---|---|
| `"label"` | string | Yes | Human-readable display name for the field. |
| `"type"` | string | Yes | One of `"text"`, `"password"`, `"email"`, `"url"`, `"number"`. |
| `"required"` | boolean | No | Whether the plugin cannot function without this field. Defaults to `False`. |
| `"help_text"` | string | No | Explanatory text shown alongside the input in UIs. |

The package uses `settings_schema()` to build `PluginInfo.fields` (a tuple
of `PluginField` objects). `PluginInfo.requires_credentials` is automatically
derived as `True` when at least one field has `required=True`.

No-auth plugins should return an empty dict:

```python
@classmethod
def settings_schema(cls) -> dict[str, Any]:
    return {}
```

---

## Implementing `pages()`

`pages()` is a generator that yields pages of raw listing dicts from the
source API. Search parameters are available via `self._search`.

```python
def pages(self) -> Iterator[list[dict[str, Any]]]:
    search = self._search or SearchParams()
    page = 1
    while True:
        response = self._fetch_page(page, search)
        listings = response.get("results", [])
        if not listings:
            break
        yield listings
        page += 1
        if search.max_pages and page > search.max_pages:
            break
```

- Yield each page as a `list` of raw dicts exactly as returned by the API.
- Yielding an empty list is valid and signals "no more results".
- The orchestrator passes each raw dict to `normalise()` individually.
- Respect `self._search.max_pages` if set to cap the number of API requests.

---

## Implementing `normalise()`

`normalise()` maps a single raw API dict to the package's `JobRecord` shape.
The returned dict must include all Identity and Always-present fields.

```python
def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        # Identity
        "source": self.SOURCE,
        "source_id": str(raw.get("id", "")),
        "description_source": "snippet",
        # Always-present
        "title": raw.get("title", ""),
        "url": raw.get("redirect_url", ""),
        "posted_at": raw.get("created", None),
        "description": raw.get("description", ""),
        # Optional
        "company": raw.get("company", {}).get("display_name"),
        "location": raw.get("location", {}).get("display_name"),
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "salary_currency": None,
        "salary_period": None,
        "contract_type": raw.get("contract_type"),
        "contract_time": raw.get("contract_time"),
        "remote_eligible": None,
        # Source-specific
        "extra": None,
    }
```

See [output_schema.md](output_schema.md) for the full field reference and the
empty-string-vs-null contract.

---

## Credentials and Validation

The credentials file format is documented in
[credentials_format.md](credentials_format.md). A plugin receives its
credentials as a plain `dict[str, Any]` via the constructor.

Validate required fields in `__init__` and raise `CredentialsError` if any
are missing:

```python
from job_api_aggregator import CredentialsError

def __init__(
    self,
    *,
    credentials: dict[str, Any] | None = None,
    search: SearchParams | None = None,
) -> None:
    super().__init__(credentials=credentials, search=search)
    creds = credentials or {}
    missing = [f for f in ("app_id", "app_key") if not creds.get(f)]
    if missing:
        raise CredentialsError(self.SOURCE, missing)
    self._app_id = creds["app_id"]
    self._app_key = creds["app_key"]
```

The `required` flag in `settings_schema()` drives which fields are validated
by the orchestrator's pre-flight check, and also determines
`PluginInfo.requires_credentials`. Your `__init__` validation should be
consistent with what `settings_schema()` marks as required.

---

## Registering via Entry-Points

Third-party plugins register themselves using the `job_api_aggregator.plugins`
entry-point group in their `pyproject.toml`:

```toml
[project.entry-points."job_api_aggregator.plugins"]
my_source = "my_package.plugin:Plugin"
```

The left-hand side (e.g. `my_source`) is the entry-point name; the
right-hand side is the dotted import path to your `Plugin` class. The
entry-point name need not match `SOURCE` — `SOURCE` is read from the class
attribute after the class is loaded.

**Collision detection**: if two installed packages register classes that share
the same `SOURCE` value, the package raises `PluginConflictError` at startup.
To resolve a conflict, either uninstall one of the packages or add the
conflicting key to the `JOB_SCRAPER_DISABLE_PLUGINS` environment variable
(comma-separated list of plugin keys to suppress).

For bundled plugins (those shipped inside this package), the entry-points are
declared in the package's own `pyproject.toml` under
`[project.entry-points."job_api_aggregator.plugins"]`.

---

## Testing with VCR Cassettes

Integration tests for plugins use
[`pytest-recording`](https://github.com/kiwicom/pytest-recording) (a
`pytest` wrapper around `vcrpy`) to record and replay HTTP interactions.
Cassettes capture the real API response once and replay it on every CI run,
so tests remain deterministic without live API credentials.

### Directory layout

```
tests/sources/<plugin_key>/
    __init__.py
    conftest.py
    test_<plugin_key>.py           # unit tests (no HTTP)
    test_<plugin_key>_integration.py  # VCR integration tests
    cassettes/
        test_<test_name>.yaml      # recorded HTTP interaction
```

### Writing an integration test

```python
import pytest
from job_api_aggregator.plugins.my_source import Plugin
from job_api_aggregator.schema import SearchParams


@pytest.fixture()
def plugin() -> Plugin:
    return Plugin(
        credentials={"api_key": "FAKE_API_KEY"},
        search=SearchParams(query="python developer", max_pages=1),
    )


@pytest.mark.vcr()
def test_pages_returns_listings(plugin: Plugin) -> None:
    pages = list(plugin.pages())
    assert len(pages) > 0
    assert len(pages[0]) > 0
```

The `@pytest.mark.vcr()` decorator tells `pytest-recording` to look for (or
create) a cassette file named after the test function in the `cassettes/`
subdirectory.

### Recording a cassette

To record a real cassette against the live API, run:

```bash
# Supply real credentials as environment variables
export MY_SOURCE_API_KEY="your_real_key"
uv run pytest tests/sources/my_source/test_my_source_integration.py \
    --record-mode=once
```

`--record-mode=once` records on the first run and replays on subsequent runs.
After recording, **scrub any credentials** from the cassette YAML before
committing. Check that the cassette does not contain your API key in request
headers, query parameters, or the response body.

### Replaying cassettes in CI

No special flags are needed. With a cassette file in place, the test runs
without any network access or credentials.

---

## Exception Hierarchy

All package exceptions inherit from `JobAggregatorError`. Catching the base
class captures any package-specific error; catching a subclass targets a
specific failure mode.

```
JobAggregatorError
├── CredentialsError        — missing/invalid credentials at plugin init
├── PluginConflictError     — two plugins claim the same SOURCE key
├── ScrapeError             — HTTP or parse failure during hydrate
└── SchemaVersionError      — input envelope major version mismatch
```

**`CredentialsError`** (`plugin_key: str`, `missing_fields: list[str]`) —
raised by a plugin's `__init__` when required credential fields are absent
or empty.

**`PluginConflictError`** (`key: str`, `sources: list[str]`) — raised by the
plugin registry when two registrations share the same `SOURCE` key.

**`ScrapeError`** (`url: str`, `reason: str`) — raised (or stored) by the
hydrator when an HTTP request fails or the response body cannot be parsed.

**`SchemaVersionError`** (`got: str`, `expected: str`) — raised by
`job-api-aggregator hydrate` when the input envelope's `schema_version` major
component does not match the package's current major version.

All exceptions are importable directly from `job_api_aggregator`:

```python
from job_api_aggregator import (
    CredentialsError,
    JobAggregatorError,
    PluginConflictError,
    SchemaVersionError,
    ScrapeError,
)
```
