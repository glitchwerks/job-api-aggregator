# Contributing to job-api-aggregator

`job-api-aggregator` is a standalone Python package extracted from the `job-matcher-pr` project.
It provides 10 job-source plugins via a `JobSource` abstract base class, normalises raw API
responses into a common `JobRecord` TypedDict, and exposes each source through Python's
entry-point plugin system so consumers can swap or extend sources without forking the core
library.

---

## Dev setup

**Prerequisites:** Python 3.11+ (the repo ships a `.python-version` file that tools like
`pyenv` and `mise` pick up automatically).

```bash
# Install all dependency groups (runtime + dev + test)
uv sync --all-groups
```

---

## Running tests

```bash
uv run pytest
```

VCR cassettes (stored under `tests/sources/<name>/cassettes/`) replay pre-recorded HTTP
responses, so the test suite runs fully offline with no live API calls in CI.

---

## Recording new VCR cassettes

Four sources (adzuna, jooble, jsearch, usajobs) require paid-API credentials.

1. Copy `.env.example` to `.env` at the repo root.
2. Fill in the credentials for the sources you need to record.
3. Record cassettes for a single source:

   ```bash
   uv run pytest tests/sources/<name>/ --record-mode=once
   ```

4. **Scrub credential values from the generated YAML before committing.**
   Open each cassette file and replace any value that matches `API_KEY`, `APP_ID`,
   `EMAIL`, or similar credential fields with a `FAKE_<NAME>` placeholder (e.g.
   `FAKE_ADZUNA_APP_ID`). Cassettes are committed to the repo and will be published
   to PyPI — real credentials must never appear in them.

5. Verify `.env` is not staged: `git status` — it is gitignored but double-check.

Sources that need no credentials (arbeitnow, himalayas, jobicy, remoteok, remotive,
the_muse) follow the same recording flow, with no scrubbing required.

---

## Lint and format

```bash
uv run ruff check src tests scripts
uv run ruff format src tests scripts
```

`ruff format` is the project formatter (replaces Black). CI enforces both checks.

---

## Type checking

```bash
uv run mypy src tests scripts
```

CI runs `mypy --strict` against `src/`, `tests/`, and `scripts/`. If you add another
top-level directory with Python code, extend the `Type check` step in
`.github/workflows/ci.yml` to cover it.

---

## Dependency audit

```bash
uv run deptry .
```

---

## Workflow

- Branch from `main` for every change.
- Follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages
  (e.g. `feat: add himalayas plugin`, `fix: normalise salary range for adzuna`).
- Open a pull request against `main`. In the PR body, close the linked issue with plain
  text — no backticks:

  ```
  Closes #42
  ```

  GitHub auto-closes the issue only when the keyword appears as plain text; wrapping it
  in backticks (`` `Closes #42` ``) prevents auto-close.

---

## Adding a new job-source plugin

1. **Create the plugin package** at `src/job_api_aggregator/plugins/<name>/` with an
   `__init__.py` that exports a class named `Plugin`. Use the existing plugins in that
   directory as templates.

2. **Subclass `JobSource`** from `src/job_api_aggregator/base.py`. Set all 9 required
   `ClassVar` attributes at class level — the base class enforces their presence via
   `__init_subclass__`:

   | Attribute | Description |
   |---|---|
   | `SOURCE` | Unique machine-readable plugin key (lowercase with underscores, e.g. `"my_source"`) |
   | `DISPLAY_NAME` | Human-readable source name |
   | `DESCRIPTION` | Short human-readable description of the source |
   | `HOME_URL` | Canonical homepage URL for the job source |
   | `GEO_SCOPE` | One of `"global"`, `"global-by-country"`, `"remote-only"`, `"federal-us"`, `"regional"`, `"unknown"` |
   | `ACCEPTS_QUERY` | `"always"`, `"partial"`, or `"never"` |
   | `ACCEPTS_LOCATION` | `bool` — whether a location filter is supported |
   | `ACCEPTS_COUNTRY` | `bool` — whether a country filter is supported |
   | `RATE_LIMIT_NOTES` | One-line summary of upstream rate limits |

3. **Implement `search()`** — fetch from the upstream API and call `normalise()` on each
   raw result. Raise `ScrapeError` or `CredentialsError` from `src/job_api_aggregator/errors.py`;
   never raise a bare `Exception`.

4. **Write tests** under `tests/sources/<name>/`:
   - `test_<name>.py` — unit tests using synthetic dicts (no HTTP).
   - `test_<name>_integration.py` — VCR tests that replay recorded cassettes.

5. **Register the entry point** in `pyproject.toml` under
   `[project.entry-points."job_api_aggregator.plugins"]`, sorted alphabetically:

   ```toml
   <name> = "job_api_aggregator.plugins.<name>:Plugin"
   ```
