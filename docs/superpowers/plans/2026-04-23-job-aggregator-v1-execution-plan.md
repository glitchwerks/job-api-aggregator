# job-api-aggregator v1.0 — Phase 1 Execution Plan

**Date:** 2026-04-23
**Status:** Revised — all 7 open questions resolved by user; CI/tooling and public-package audits folded in
**Author:** Christopher Beaulieu (with Claude Code, project-planner)
**Source spec:** `docs/superpowers/specs/2026-04-23-job-api-aggregator-design.md` (v3-patched)
**Scope:** Phase 1 only — standalone `job-api-aggregator` package v1.0. Phase 2 (`job-matcher-pr` migration; spec §12, Issues H-K) is explicitly **deferred** and acknowledged here only as the gated next phase.

---

## 1. Executive summary

- **Critical path is dominated by the 10 per-plugin migration/audit issues (B1-B10).** Issue B (the new ABC + schemas) blocks them, but once B lands, B1-B10 can run in parallel — the long pole is whichever single plugin takes longest, not the sum.
- **Three true serial gates:** Issue A (skeleton + full CI + public-package metadata) blocks everything; Issue B (ABC contract + exception hierarchy) blocks B1-B10, C, D, E, F; the new **Preflight** live-API smoke test (Q7) blocks B1-B10 from opening at all.
- **Phase 1 is now split into two exit gates:** a **Code-complete gate** that can finish on its own schedule (green CI, deptry clean, all cassettes recorded, docs published, `v1.0.0-rc1` tag) and a **Ship gate** that depends on the external consumer's own readiness and produces the final `v1.0.0` PyPI release.
- **Public-package readiness is now explicit.** `LICENSE`, `CHANGELOG.md`, full `pyproject.toml` metadata, `py.typed`, `__version__`, library-logger pattern, PyPI trusted publishing workflow, issue/PR templates, `CONTRIBUTING.md`, `SECURITY.md`, exception hierarchy, and README badges are all in Phase 1 scope — not deferred.
- **Custom AST import-fence is dropped.** Replaced with `deptry` as a CI job — the invariant ("every import in `src/` must be declared or stdlib") maps more naturally to deptry's whitelist model than to a custom blacklist scanner.
- **Biggest hidden risk** is the §11.5 metadata catalog — each row must carry all 7 attributes + code-citation justifications + rate-limit notes grounded in actual behavior. The plan below pins down what "done" means for one row and flags that rows with `?` values are not shippable.
- **Milestone scaffolding:** one milestone (`job-api-aggregator v1`) with **19 issues** — Preflight, A, B, B1-B10, C, D, E, F, G, M — all created up front so the dependency graph is visible from day one.

---

## 2. Spec clarifications applied by this plan

These reconcile inconsistencies noticed while planning. They are planning-layer decisions, not spec rewrites.

### 2.1 PyPI publishing is Phase 1, not Phase 2

Spec §12.3 implies PyPI publishing is Phase 2, but the v1.0 primary user story (§4 story #1) is `pip install job-api-aggregator`. These contradict. Resolution: **PyPI publishing infrastructure (trusted-publishing workflow, TestPyPI rehearsal) and the first publish both happen in Phase 1.** Phase 2's scope is narrowed to "`job-matcher-pr` switches its install source from editable-sibling to pinned PyPI version" — it is the *consumer migration*, not the *package publication*.

### 2.2 Import-fence implementation: deptry instead of custom AST

Spec §14.1 proposes a grep/AST scan of `src/job_api_aggregator/` for a blacklist of forbidden imports (`db`, `flask`, `psycopg2`, LLM clients, etc.). We replace this with **`deptry` as a CI job**. Rationale: the real invariant is "every import in `src/` must be declared in `pyproject.toml` dependencies or be in the Python stdlib." Deptry checks this directly via whitelist (declared deps) rather than blacklist (forbidden list). The no-DB / no-framework / no-LLM goal falls out for free because `psycopg2`, `flask`, `anthropic`, `openai`, `google.*` are never declared as dependencies. Zero custom test code to maintain. Post-Phase-2, augment with a clean-venv install smoke test in CI (Issue A's acceptance).

### 2.3 N3 `--query` mixed-mode handling: both warning and envelope metadata

User decided to implement both approaches (B + C) rather than pick one:

- **B (stderr warning):** At `jobs` startup, if `--query` is passed and any enabled source has `accepts_query` in `{"never", "partial"}`, emit `WARNING: --query "<value>" will not apply to: <source_keys> (accepts_query=never)` to stderr.
- **C (envelope metadata):** Add `query_applied: {source_key: bool}` to the envelope's `sources_used` section (or a sibling field). Programmatic consumers can assert on this.

Both land in Issue D. Update §9.2 envelope example and §8.1 docstring accordingly.

### 2.4 Deprecation policy anchor: PEP 387

Any removal or breaking change to Identity / Always-present schema fields or the Python API must be preceded by at least one minor release that emits a `DeprecationWarning` and documents the coming change in `CHANGELOG.md`. Pure field renames may use dual-emit (both old and new keys present during the deprecation window) where feasible. This lives in `docs/output_schema.md` §9.5 (Issue G).

### 2.5 §11.5 catalog row acceptance is tightened

Each row must carry all 7 attributes + code-citation justifications (line ranges in the plugin's `fetch_page()`) + rate-limit notes grounded in actual behavior (quoted from official docs or explicitly marked "Unknown — not documented by source"). **No row may ship with a `?` value.** This is enforced in the B1-B10 issue template.

---

## 3. Pre-work checklist

Resolve before Issue A is opened.

- [x] **Confirm Python 3.11+** — uv will manage the interpreter via `.python-version = 3.11` (installs automatically on both dev and CI via `astral-sh/setup-uv`).
- [x] **Confirm PyPI package name `job-api-aggregator` is unclaimed** — verified 2026-04-23: `https://pypi.org/pypi/job-api-aggregator/json` returns 404 (available).
- [x] **Adopt uv for Python tooling** — all venv management, installs, and tool invocation use `uv` (not `pip` / `venv` / `virtualenv`). Lock file `uv.lock` committed; `.python-version` committed; CI uses `astral-sh/setup-uv@v3`.
- [x] **Decide LICENSE** — **Resolved: MIT.** `pyproject.toml` sets `license = "MIT"` (SPDX); `LICENSE` file holds standard MIT text (© 2026 Christopher Beaulieu).
- [ ] **Decide GitHub repo visibility** (affects PyPI trusted-publishing OIDC trust setup and whether external consumers can `pip install git+…`).
- [ ] **Configure PyPI trusted publishing** (pending LICENSE/name decisions above) — register the project on PyPI and TestPyPI with the `cbeaulieu-gt/job-api-aggregator` repo + `publish.yml` workflow as the trusted publisher. No API tokens stored anywhere.
- [ ] **Reserve the GitHub Milestone** `job-api-aggregator v1` before opening any issues.
- [ ] **All 10 plugins' credentials are on hand.** (User confirmed: yes.) Cassettes will be recorded for all 10 plugins — including those with no credential requirement, to capture real HTTP shape.

Resolved (documented here for traceability):

- Q1 — §11.5 row acceptance: **confirmed as in §2.5 above.**
- Q2 — Cassette coverage: **all 10 plugins get cassettes. No skip-cassette fallback.**
- Q3 — Import enforcement: **deptry, per §2.2 above.** No custom AST scanner.
- Q4 — `--query` mixed-mode: **both warning + envelope metadata, per §2.3.**
- Q5 — Deprecation policy: **PEP 387 one-minor-release window, per §2.4.**
- Q6 — External consumer: **not yet ready.** User will update consumer separately. Phase 1 exit is split into Code-complete gate + Ship gate (see §6).
- Q7 — Pre-flight smoke test: **new Preflight issue added**, runs after B lands but before B1-B10 open. Classifies each plugin `green` / `needs-fixing` / `broken-defer-to-v1.1`.

---

## 4. Sequenced issue list with dependency graph

```
                         ┌─────────────────────────────┐
                         │  A: Skeleton + full CI +    │
                         │  public-package metadata    │
                         │  (deptry, ruff, mypy,       │
                         │  pytest, pip-audit, publish)│
                         └──────────────┬──────────────┘
                                        │
                    ┌───────────────────┼──────────────────────┐
                    │                   │                      │
                    ▼                   ▼                      ▼
        ┌──────────────────┐   ┌─────────────────┐   ┌─────────────────┐
        │ B: ABC v3 +      │   │ M: Community    │   │ (G: docs —      │
        │ PluginInfo/Field │   │ meta            │   │  draft only     │
        │ + exception      │   │ (CONTRIBUTING,  │   │  until C/D/E/F) │
        │ hierarchy        │   │  SECURITY, tpl) │   └─────────────────┘
        └────────┬─────────┘   └─────────────────┘
                 │
                 ▼
        ┌──────────────────────┐
        │ Preflight: live-API  │
        │ smoke test, 10 srcs  │
        │ → green / needs-fix  │
        │   / defer-to-v1.1    │
        └────────┬─────────────┘
                 │ Preflight + B both gate B1-B10
    ┌────────────┼─────────────────────────────────┐
    │            │                                 │
    ▼            ▼                                 ▼
┌───────────────────┐              ┌────────────────────────┐
│ B1-B10 (parallel) │              │ C: JobRecord schema    │
│ per-plugin audit  │              │    + record normalizer │
│ + cassettes +     │              └───────────┬────────────┘
│ §11.5 rows        │                          │ C blocks D, E
└────────┬──────────┘                          ▼
         │                       ┌──────────────────────────┐
         │                       │ D: jobs orchestrator +   │
         │                       │   formatters + dedup +   │
         │                       │   --query warning +      │
         │                       │   query_applied envelope │
         │                       └──────────┬───────────────┘
         │                                  ▼
         │                       ┌──────────────────────────┐
         │                       │ E: hydrate + move        │
         │                       │   scrape_description +   │
         │                       │   §8.2.1 input handling  │
         │                       └──────────┬───────────────┘
         │                                  │
         │                                  ▼
         │                       ┌──────────────────────────┐
         │                       │ F: sources + list_plugins│
         │                       │   / get_plugin API       │
         │                       └──────────┬───────────────┘
         │                                  │
         └──────────┬───────────────────────┘
                    ▼
        ┌──────────────────────────────────────┐
        │ G: docs final pass (README,          │
        │ output_schema.md inc. PEP 387 policy,│
        │ plugin_authoring.md, sample fixture) │
        └────────────┬─────────────────────────┘
                     │
                     ▼
        ┌──────────────────────────────────────┐
        │ CODE-COMPLETE GATE:                  │
        │  • all 5 CI jobs green on main       │
        │  • deptry clean                      │
        │  • 10 cassettes recorded             │
        │  • §11.5 catalog full, no ?          │
        │  • docs published                    │
        │  • pip install . in clean venv OK    │
        │  • v1.0.0-rc1 tag + draft Release    │
        └────────────┬─────────────────────────┘
                     │
                     ▼
        ┌──────────────────────────────────────┐
        │ SHIP GATE (blocks v1.0 + Phase 2):   │
        │  • external consumer integrates +    │
        │    signs off against v1.0.0-rc1      │
        │  • v1.0.0 tag → trusted-publish PyPI │
        │  • job-matcher-pr Phase 2 unlocked   │
        └──────────────────────────────────────┘
```

**Graph notes:**

- **B1-B10 now depend on Preflight + B.** Preflight classifies each plugin before its migration issue opens for work; broken plugins either get scope amended or are deferred out of v1.0.
- **M runs in parallel with B and the whole core arm** — it only touches meta files, no code dependency.
- **C still blocks D and E** — D emits `JobRecord`, E reads/modifies them.
- **F depends on B** (reads `PluginInfo` + exception hierarchy), independent of D/E.
- **G can begin as a draft after B; substantive sections wait on C/D/E/F.**

---

## 5. Critical path analysis

Minimum wall-clock path:

```
A → B → Preflight → max( slowest single B-N , C → D → E → F ) → G → Code-complete gate → Ship gate
```

- The per-plugin arm (B1-B10) remains the long pole. 10 plugins × 1-3h each is 10-30h serial; parallelism for a solo developer is attention-bounded.
- Preflight adds a small serial segment (~30 min of runtime + triage) but **shrinks the critical-path risk** by pulling "broken upstream" discovery to the front.
- The C→D→E→F arm is roughly: small → medium → medium → small — probably 1-3 days if sequential.
- Code-complete gate is independent of external consumer readiness; the Ship gate waits on external work that this plan does not schedule.

---

## 6. Phase 1 exit criteria (split into two gates)

### 6.1 Code-complete gate — package is technically done

This gate unblocks the RC release and lets the external consumer begin integration testing. It does NOT require the external consumer to be ready.

1. **All 5 CI jobs green on `main`:**
   - `lint` — ruff check + ruff format --check
   - `typecheck` — mypy strict on `src/`
   - `deps` — deptry on `src/` (catches undeclared / forbidden imports per §2.2)
   - `test` — pytest (unit + VCR-replay + schema round-trip + orchestrator integration + CLI smoke)
   - `audit` — pip-audit on resolved lockfile
2. **All 10 §11.5 metadata catalog rows complete** with no `?` / `TBD` values; every value code-cited; rate-limit notes grounded (quoted source doc, or explicit "Unknown — not documented").
3. **All 10 plugins have VCR cassettes** recorded against their real endpoints (credentials used where required).
4. **`docs/output_schema.md` published**: §9 record categories, envelope (with Q4 `query_applied` field), `description_source` truth table, `extra.*` policy, schema-version semantics, PEP 387 deprecation policy (per §2.4).
5. **`docs/plugin_authoring.md` published**, covering all 7 metadata attributes + how to record a VCR cassette + exception hierarchy.
6. **`docs/examples/sample-output.jsonl`** is committed, produced from a real `job-api-aggregator jobs` run.
7. **`pip install .` in a clean venv passes a smoke test** (the CI workflow runs this; verifies the wheel + declared deps resolve).
8. **`v1.0.0-rc1` tag pushed** + **GitHub Release drafted** (not published) pointing at TestPyPI.
9. **Preflight-deferred plugins (if any) are documented** in `docs/preflight-report.md` with clear v1.1 deferral scope.

### 6.2 Ship gate — unblocks v1.0 and Phase 2

10. **External consumer integrates with `v1.0.0-rc1`** (installed from TestPyPI) and produces non-zero scored output end-to-end. User signs off.
11. **`v1.0.0` tag pushed** → `publish.yml` publishes to production PyPI via trusted publishing.
12. **Phase 2 milestone created in `job-matcher-pr`** and ready for H-K issues.
13. **No open issues on `job-api-aggregator v1` milestone.**

Gates 6.1 (items 1-9) and 6.2 (items 10-13) collectively define "v1.0 shipped."

---

## 7. CI and tooling stack (consolidated into Issue A)

Issue A is no longer just "skeleton" — it stands up the full CI/tooling stack so that every subsequent issue lands against an opinionated, enforced baseline.

### 7.1 `pyproject.toml` tool configuration

- `[tool.ruff]` — select rules `E, F, W, I, N, UP, B, SIM, RUF`; `line-length = 100`; `target-version = "py311"`.
- `[tool.ruff.format]` — standard formatter config.
- `[tool.mypy]` — `strict = true`, `python_version = "3.11"`, `packages = ["job_api_aggregator"]`.
- `[dependency-groups] dev` — `ruff`, `mypy`, `deptry`, `pytest`, `pytest-recording` (VCR), `pip-audit`, `pre-commit`.

### 7.2 `.github/workflows/ci.yml` — 5 parallel jobs

Per user's `feedback_ci_split_lint_and_test.md`, split rather than chained:

| Job | Command | Fails on |
|---|---|---|
| `lint` | `ruff check . && ruff format --check .` | style / lint violations |
| `typecheck` | `mypy src/` | any type error under strict |
| `deps` | `deptry src/` | undeclared import, unused dep, dev-dep in src |
| `test` | `pytest` | any test failure (cassettes replayed; no live HTTP in CI) |
| `audit` | `pip-audit` | known CVE in resolved tree |

Matrix: **Python 3.11 only for v1.0.** (3.12 is a v1.1 candidate once all 10 plugin cassettes confirm 3.12 compatibility.)

### 7.3 `.pre-commit-config.yaml`

Mirrors the `lint` CI job (ruff check + ruff format) for local-dev parity. Optional: `deptry` hook on commit.

### 7.4 `.github/workflows/publish.yml`

PyPI trusted publishing via OIDC — no stored API tokens. Trigger on tag push:

- `v*.*.*-rc*` → TestPyPI
- `v*.*.*` (final) → production PyPI

### 7.5 Initial CI smoke commit

Issue A's final commit must produce an all-green CI run on an empty skeleton (no plugins yet). This proves the pipeline before any real code lands.

---

## 8. Public-package readiness (folded into Issue A, Issue B, and new Issue M)

### 8.1 Into Issue A

- **LICENSE** file (MIT / Apache-2.0 / BSD-3-Clause — pre-work decision).
- **CHANGELOG.md** skeleton, Keep-a-Changelog format, starting with `## [Unreleased]`.
- **Full `pyproject.toml` metadata** beyond spec §6: `description`, `readme = "README.md"`, `authors`, `license` (SPDX identifier), `classifiers` (Development Status, Python versions, OS, Topic, License), `keywords`, `urls` (Homepage, Repository, Issues, Changelog, Documentation).
- **`src/job_api_aggregator/py.typed`** — empty marker file, PEP 561, required for mypy to pick up the package's types when installed.
- **`__version__`** in `job_api_aggregator/__init__.py` via `importlib.metadata.version("job-api-aggregator")`.
- **Library logger pattern** — `logging.getLogger("job_api_aggregator")` with `logging.NullHandler()` attached at package init, PEP 282 convention. **Never** configure the root logger.
- **README badges** — PyPI version, CI status, Python versions, license.
- **`.github/workflows/publish.yml`** — trusted publishing per §7.4.

### 8.2 Into Issue B

- **Exception hierarchy** — all rooted at `JobAggregatorError`:
  - `JobAggregatorError` (base)
  - `PluginConflictError` (spec §6 — duplicate `source_key` at entry-point load)
  - `ScrapeError`
  - `CredentialsError`
  - `SchemaVersionError`
- Documented in `docs/output_schema.md` and re-exported via `job_api_aggregator.__init__` for a clean public API surface.

### 8.3 New Issue M — "Meta / community" (parallel to B1-B10)

- **CONTRIBUTING.md** — dev setup (editable install + venv + pre-commit), how to run tests, how to record a VCR cassette, PR process.
- **SECURITY.md** — private security-report flow via GitHub Security Advisories. (Rationale: the package handles 10 sets of API credentials — security disclosure is materially more relevant than for a typical package.)
- **`.github/ISSUE_TEMPLATE/`** — `bug_report.md`, `feature_request.md`, `plugin_request.md`.
- **`.github/PULL_REQUEST_TEMPLATE.md`**.

### 8.4 Deferred to v1.1+

- `CODE_OF_CONDUCT.md`
- Dependabot config
- SBOM generation
- Sigstore signing
- Coverage threshold in CI
- MkDocs documentation site

---

## 9. Milestone scaffolding (copy-ready for issue creation)

**Milestone:** `job-api-aggregator v1`
**Repo:** `cbeaulieu-gt/job-api-aggregator`
**Description:** "Phase 1: ship standalone job-api-aggregator package v1.0 (per design spec 2026-04-23) through Code-complete gate + Ship gate. Phase 2 migration of job-matcher-pr is tracked separately."

Target: **19 issues.** Create in this order (parents before children) so GitHub renders the dependency graph correctly.

| # | Title | Labels | Depends on | One-line description |
|---|---|---|---|---|
| A | Set up package skeleton, full CI pipeline, and public-package metadata | `infra`, `phase-1` | — | pyproject (3.11+, full metadata, SPDX license, classifiers, urls), `src/job_api_aggregator/` + `py.typed` + `__version__`, library logger, `LICENSE`, `CHANGELOG.md`, README with badges, `.pre-commit-config.yaml`, `ci.yml` with 5 parallel jobs (lint/typecheck/deps/test/audit), `publish.yml` with TestPyPI+PyPI trusted publishing, clean-venv install smoke test, initial all-green CI commit. |
| B | Plugin contract: JobSource ABC v3 + PluginInfo/PluginField + entry-point collision policy + exception hierarchy | `design`, `phase-1` | A | ABC with 7 metadata attributes (`DISPLAY_NAME`, `HOME_URL`, `GEO_SCOPE`, `ACCEPTS_QUERY`, `ACCEPTS_LOCATION`, `ACCEPTS_COUNTRY`, `RATE_LIMIT_NOTES`) plus `REQUIRED_SEARCH_FIELDS` and `DESCRIPTION`. `PluginInfo` + `PluginField` dataclasses. `auto_register` raising `PluginConflictError`. Exception hierarchy (`JobAggregatorError`, `PluginConflictError`, `ScrapeError`, `CredentialsError`, `SchemaVersionError`) re-exported from package root. |
| Preflight | Live-API smoke test across all 10 sources | `infra`, `phase-1`, `preflight` | B | 30-minute live run against each plugin's real endpoint using real credentials. Classify each as `green` / `needs-fixing` / `broken-defer-to-v1.1`. Deliverable: `docs/preflight-report.md`. Needs-fixing plugins have their B-N issue opened with scope amended; broken plugins are explicitly deferred out of v1.0 with a follow-up v1.1 issue. |
| B1 | Migrate `adzuna` plugin + fill §11.5 row + VCR cassette | `plugin-migration`, `phase-1` | Preflight, B | Move plugin into package, fill all 7 metadata attributes with code-cited values, audit `normalise()` against §9.3, write `normalise()` unit test + VCR cassette for `fetch_page()`. Reference `job-matcher-pr` repo for existing `fetch_page()` shape. |
| B2 | Migrate `arbeitnow` plugin + fill §11.5 row + VCR cassette | `plugin-migration`, `phase-1` | Preflight, B | Same shape as B1 for arbeitnow. |
| B3 | Migrate `himalayas` plugin + fill §11.5 row + VCR cassette | `plugin-migration`, `phase-1` | Preflight, B | Same shape as B1 for himalayas. |
| B4 | Migrate `jobicy` plugin + fill §11.5 row + VCR cassette | `plugin-migration`, `phase-1` | Preflight, B | Same shape as B1 for jobicy. |
| B5 | Migrate `jooble` plugin + fill §11.5 row + VCR cassette | `plugin-migration`, `phase-1` | Preflight, B | Same shape as B1 for jooble. |
| B6 | Migrate `jsearch` plugin + fill §11.5 row + VCR cassette | `plugin-migration`, `phase-1` | Preflight, B | Same shape as B1 for jsearch. |
| B7 | Migrate `remoteok` plugin + fill §11.5 row + VCR cassette | `plugin-migration`, `phase-1` | Preflight, B | Same shape as B1 for remoteok. |
| B8 | Migrate `remotive` plugin + fill §11.5 row + VCR cassette | `plugin-migration`, `phase-1` | Preflight, B | Same shape as B1 for remotive. |
| B9 | Migrate `the_muse` plugin + fill §11.5 row + VCR cassette | `plugin-migration`, `phase-1` | Preflight, B | Same shape as B1 for the_muse. |
| B10 | Migrate `usajobs` plugin + fill §11.5 row + VCR cassette | `plugin-migration`, `phase-1` | Preflight, B | Same shape as B1 for usajobs. |
| C | JobRecord schema + record normalizer | `core`, `phase-1` | B | Identity / Always-present / Optional / `extra.*` categories. Normalizer: `redirect_url` → `url`, date normalization, `posted_at` backfill from `created_at`, empty-vs-null preservation per §9.4, `extra` blob assembly. |
| D | `jobs` orchestrator + output formatters + in-memory dedup + --query warning + query_applied envelope | `core`, `cli`, `phase-1` | C | Fetch loop, `--strict`/`--dry-run`/`--limit`/`--sources`/`--exclude-sources` per §8.1. JSONL + JSON envelope per §9.2. In-memory dedup. Stderr warning when `--query` set with `accepts_query` in `{never,partial}`. Envelope carries `query_applied: {source_key: bool}`. |
| E | `hydrate` command + move `scrape_description` + `SCRAPE_MIN_LENGTH` + §8.2.1 + truth-table tests | `core`, `cli`, `phase-1` | C | Move `scrape_description` / `SCRAPE_MIN_LENGTH` into `job_api_aggregator.scraping`. Implement §8.2.1 input handling table exhaustively. Parametrized test covering every row of the §9.6 `description_source` truth table. |
| F | `sources` command + `list_plugins` / `get_plugin` Python API | `core`, `cli`, `phase-1` | B | Public API per §7. CLI per §8.3 (with `credentials_configured: bool` when `--credentials` passed). |
| G | Documentation: README, output_schema.md (with PEP 387 policy), plugin_authoring.md, sample fixture | `docs`, `phase-1` | A (metadata); substantive sections need C, D, E, F | Publish `docs/output_schema.md` (§9 + `query_applied` + PEP 387 deprecation policy), `docs/plugin_authoring.md` (7 metadata attrs + cassette recording + exception hierarchy), `docs/examples/sample-output.jsonl` (real run), `extra.*` policy, schema-version policy. |
| M | Community meta — CONTRIBUTING, SECURITY, issue/PR templates | `docs`, `phase-1`, `community` | A | `CONTRIBUTING.md`, `SECURITY.md` (GitHub Security Advisories process), `.github/ISSUE_TEMPLATE/{bug_report,feature_request,plugin_request}.md`, `.github/PULL_REQUEST_TEMPLATE.md`. Independent of core code. |

### 9.1 Issue body template

```
## Goal
<one sentence>

## Acceptance criteria
- [ ] <specific, testable check>
- [ ] <specific, testable check>
- [ ] Tests added/updated and passing in CI (all 5 jobs green)
- [ ] (For B1-B10) §11.5 catalog row fully populated — no `?` or TBD; every value code-cited; rate-limit notes grounded in source docs or explicitly "Unknown — not documented"

## Depends on
- #<issue numbers>

## References
- Spec: docs/superpowers/specs/2026-04-23-job-api-aggregator-design.md §<section>
- Plan: docs/superpowers/plans/2026-04-23-job-api-aggregator-v1-execution-plan.md §<section>
```

### 9.2 Issues NOT to create in this milestone

- **H, I, J, K** from spec §13 — Phase 2, live in `job-matcher-pr` milestone.
- **Concurrency for `hydrate`** — spec §18, deferred to v1.1.
- **CODE_OF_CONDUCT.md, Dependabot, SBOM, sigstore, coverage threshold, MkDocs** — per §8.4, v1.1+.
- **Python 3.12 support matrix** — v1.1 once cassettes confirm compatibility.

---

## 10. Self-review against spec

- §2 Phase 1 goals → A, B, C, D, E, F, G
- §4 user story #1 (`pip install job-api-aggregator`) → A (publish.yml) + Ship gate (v1.0.0 → PyPI)
- §5.3 drift mitigation → E's parametrized §9.6 truth-table test (in-repo). Cross-repo parity is Phase 2's Issue J.
- §6 package structure + pyproject → A (now also full public-package metadata)
- §7 public Python API → F + B (exceptions re-exported)
- §8 CLI surface → §8.1 D (incl. --query warning + query_applied), §8.2 + §8.2.1 E, §8.3 F
- §9 output schema → §9.1 B1-B10, §9.2 D (+ query_applied addition), §9.3-§9.5 C + G (PEP 387), §9.6 E
- §10 credentials format → F
- §11 plugin contract → B (ABC + exception hierarchy)
- §11.5 metadata catalog → B1-B10 per-row; G publishes consolidated table
- §12.3 PyPI publishing contradiction → resolved in §2.1 (Phase 1)
- §13 issue breakdown → reproduced in §9 with Preflight + M added
- §14.1 testing strategy → lint/typecheck/deps/test/audit CI jobs in A; per-plugin cassettes in B1-B10; schema round-trip in C; orchestrator integration in D; §9.6 truth-table parametrized test in E; clean-venv install in A; CLI smoke in D/E/F
- §15 constraints → enforced by deptry CI job (§2.2)
- §16 inquisitor findings → N3 resolved by §2.3 (both warning + metadata)
- §18 deferred items → correctly out of scope

Phase 2 / §12 / Issues H-K → correctly excluded. Will live in `job-matcher-pr` milestone.

---

## 11. What happens after this plan is approved

1. User completes the pre-work checklist in §3 (LICENSE decision + PyPI name confirmation + trusted-publishing registration + milestone reservation).
2. User reviews the 19-issue list in §9 and confirms titles/labels/descriptions.
3. Router creates the milestone, then the 19 issues in dependency order, each with the issue-body template in §9.1.
4. **Creation is not start-of-work** — per CLAUDE.md, explicit go-ahead is required before Issue A's first commit.
5. Work proceeds: A → (B + M in parallel) → Preflight → (B1-B10 + C in parallel) → D → E → F → G → Code-complete gate → external consumer integration → Ship gate → v1.0.0 on PyPI.
