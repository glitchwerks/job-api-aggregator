"""Live-API preflight smoke test for job-api-aggregator.

PURPOSE
-------
Verifies that each of the 10 job-source APIs is reachable, credentials
are valid, and the response shape matches the expected contract — before
the plugin migration (Issues B1-B10) begins.

DESIGN TRADE-OFF: inline probes vs. importing legacy plugin code
----------------------------------------------------------------
The 10 source plugins live in a separate legacy repo (job-matcher-pr)
that is not yet part of this package.  The migration to copy them in
is Phase B1-B10, explicitly BLOCKED until this preflight passes.

Two options were considered:

1. Import legacy plugin code as a library — rejected because the legacy
   repo is not installed in this environment and adding it as a path-
   based dependency would create a tight coupling that should not exist
   until Phase B migration is deliberately done.

2. Inline HTTP probes (chosen) — each source gets a small probe that
   hits one documented endpoint with a minimal query.  This directly
   tests the endpoint + credentials without exercising any legacy code,
   which is exactly what a preflight should do: validate the external
   contract, not the internal adapter.

USAGE
-----
PowerShell (user's shell):
    # Dry-run (default — no network calls):
    uv run python scripts/preflight_smoke.py

    # Live run against all sources:
    uv run python scripts/preflight_smoke.py --live

    # Run only specific sources:
    uv run python scripts/preflight_smoke.py --live --only adzuna,jooble

    # Skip a source:
    uv run python scripts/preflight_smoke.py --live --skip jsearch

CREDENTIALS
-----------
Copy .env.example to .env in the repo root and fill in values:
    ADZUNA_APP_ID      - from console.adzuna.com
    ADZUNA_APP_KEY     - from console.adzuna.com
    JOOBLE_API_KEY     - from jooble.org/api/index
    JSEARCH_API_KEY    - RapidAPI key for JSearch
    USAJOBS_EMAIL      - email used when registering at developer.usajobs.gov
    USAJOBS_API_KEY    - from developer.usajobs.gov

OUTPUT
------
Raw JSON responses are saved to .tmp/preflight/<source>.json.
A summary Markdown table is written to docs/preflight-smoke-test-results.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Bootstrap: load .env from the project root (sibling of scripts/)
# ---------------------------------------------------------------------------

# dotenv is a dev-only dependency; guard so the module is importable even
# in environments where python-dotenv is not installed (e.g. pure tests).
try:
    from dotenv import load_dotenv as _load_dotenv

    _DOTENV_AVAILABLE = True
except ImportError:  # pragma: no cover
    _DOTENV_AVAILABLE = False

_PROJECT_ROOT = Path(__file__).parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"

if _DOTENV_AVAILABLE and _ENV_FILE.exists():
    _load_dotenv(_ENV_FILE)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("preflight_smoke")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUERY = "python"
MAX_CALLS = 10

# ---------------------------------------------------------------------------
# Source configuration registry
#
# Each entry describes:
#   url       - the endpoint to probe (str or callable(creds) -> str)
#   params    - query params for requests.get (may be callable(creds) -> dict)
#   headers   - optional request headers (may be callable(creds) -> dict)
#   cred_keys - list of env-var names required; empty = no credentials needed
#   list_key  - dot-path to the listings array in the JSON response
#               e.g. "results" or "data.jobs" (first component only for now)
# ---------------------------------------------------------------------------

SOURCE_CONFIGS: dict[str, dict[str, Any]] = {
    "adzuna": {
        "url": ("https://api.adzuna.com/v1/api/jobs/us/search/1"),
        "params": lambda creds: {
            "app_id": creds.get("ADZUNA_APP_ID", ""),
            "app_key": creds.get("ADZUNA_APP_KEY", ""),
            "what": QUERY,
            "results_per_page": 1,
        },
        "headers": {},
        "cred_keys": ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"],
        "list_key": "results",
    },
    "arbeitnow": {
        "url": "https://www.arbeitnow.com/api/job-board-api",
        "params": {"q": QUERY, "limit": 1},
        "headers": {},
        "cred_keys": [],
        "list_key": "data",
    },
    "himalayas": {
        "url": "https://himalayas.app/jobs/api",
        "params": {"q": QUERY, "limit": 1},
        "headers": {},
        "cred_keys": [],
        "list_key": "jobs",
    },
    "jobicy": {
        "url": "https://jobicy.com/api/v2/remote-jobs",
        "params": {"count": 1, "tag": QUERY},
        "headers": {},
        "cred_keys": [],
        "list_key": "jobs",
    },
    "jooble": {
        "url": lambda creds: f"https://jooble.org/api/{creds.get('JOOBLE_API_KEY', '')}",
        "params": {},
        "headers": {"Content-Type": "application/json"},
        "cred_keys": ["JOOBLE_API_KEY"],
        "list_key": "jobs",
        # Jooble uses POST with a JSON body; handled specially in probe_source.
        "method": "POST",
        "json_body": lambda _creds: {"keywords": QUERY, "resultsOnPage": 1},
    },
    "jsearch": {
        "url": "https://jsearch.p.rapidapi.com/search",
        "params": {"query": QUERY, "num_pages": 1, "page": 1},
        "headers": lambda creds: {
            "X-RapidAPI-Key": creds.get("JSEARCH_API_KEY", ""),
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
        },
        "cred_keys": ["JSEARCH_API_KEY"],
        "list_key": "data",
    },
    "remoteok": {
        "url": "https://remoteok.com/api",
        "params": {},
        "headers": {"User-Agent": "job-api-aggregator-preflight/0.1"},
        "cred_keys": [],
        "list_key": None,  # top-level list (first item is metadata)
    },
    "remotive": {
        "url": "https://remotive.com/api/remote-jobs",
        "params": {"search": QUERY, "limit": 1},
        "headers": {},
        "cred_keys": [],
        "list_key": "jobs",
    },
    "the_muse": {
        "url": "https://www.themuse.com/api/public/jobs",
        "params": {"query": QUERY, "page": 1, "limit": 1},
        "headers": {},
        "cred_keys": [],
        "list_key": "results",
    },
    "usajobs": {
        "url": "https://data.usajobs.gov/api/search",
        "params": {"Keyword": QUERY, "ResultsPerPage": 1},
        "headers": lambda creds: {
            "Host": "data.usajobs.gov",
            "User-Agent": creds.get("USAJOBS_EMAIL", ""),
            "Authorization-Key": creds.get("USAJOBS_API_KEY", ""),
        },
        "cred_keys": ["USAJOBS_EMAIL", "USAJOBS_API_KEY"],
        "list_key": "SearchResult.SearchResultItems",
    },
}

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    """The outcome of probing a single job source.

    Attributes:
        source: The source key (e.g. ``"adzuna"``).
        status: One of ``"green"``, ``"needs-fixing"``,
            ``"broken-defer-to-v1.1"``, or ``"dry-run"``.
        note: Optional human-readable explanation (drift description,
            error message, missing-creds notice, etc.).
        http_status: The HTTP status code returned, or ``None`` in
            dry-run mode or when a network error occurred.
    """

    source: str
    status: str
    note: str = ""
    http_status: int | None = None
    _raw: dict[str, Any] = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


class _PreflightParser(argparse.ArgumentParser):
    """ArgumentParser subclass that derives ``dry_run`` from ``--live``.

    argparse has no built-in way to express "flag A is the logical negation
    of flag B when B is set".  This subclass overrides ``parse_args`` to
    apply the post-parse rule ``args.dry_run = not args.live`` so that
    both ``args.live`` and ``args.dry_run`` are always consistent for all
    callers (including tests).
    """

    def parse_args(  # type: ignore[override]
        self,
        args: list[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> argparse.Namespace:
        """Parse args and ensure dry_run is the negation of live.

        Args:
            args: Argument list (defaults to ``sys.argv[1:]``).
            namespace: Optional namespace to populate.

        Returns:
            A :class:`argparse.Namespace` where ``dry_run == not live``.
        """
        ns = super().parse_args(args, namespace)
        ns.dry_run = not ns.live
        return ns


def build_arg_parser() -> _PreflightParser:
    """Build and return the CLI argument parser.

    Returns:
        A configured :class:`_PreflightParser` instance.
    """
    parser = _PreflightParser(
        prog="preflight_smoke",
        description=(
            "Preflight smoke test for job-api-aggregator source APIs. "
            "Default mode is --dry-run (no network calls). "
            "Pass --live to make actual HTTP requests."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Make live HTTP requests (requires credentials in .env).",
    )
    # --dry-run is accepted as an explicit no-op (default behaviour).
    # The authoritative dry_run value is derived as `not args.live`
    # by the parser's overridden parse_args — see _PreflightParser.
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help=(
            "Print what would be called; make zero network requests "
            "(default — this flag exists for explicitness)."
        ),
    )
    parser.add_argument(
        "--only",
        type=lambda s: [x.strip() for x in s.split(",")],
        default=None,
        metavar="SOURCE[,SOURCE...]",
        help="Comma-separated list of sources to run (default: all 10).",
    )
    parser.add_argument(
        "--skip",
        type=lambda s: [x.strip() for x in s.split(",")],
        default=[],
        metavar="SOURCE[,SOURCE...]",
        help="Comma-separated list of sources to exclude.",
    )
    return parser


# ---------------------------------------------------------------------------
# Source selection
# ---------------------------------------------------------------------------


def resolve_sources(
    only: list[str] | None,
    skip: list[str],
) -> list[str]:
    """Return the ordered list of source keys to probe.

    Args:
        only: If not ``None``, restrict to exactly these source keys.
            Raises ``ValueError`` for any unknown key.
        skip: Source keys to exclude.  Raises ``ValueError`` for any
            unknown key.

    Returns:
        An ordered list of source keys to probe.

    Raises:
        ValueError: If any key in ``only`` or ``skip`` is not registered
            in :data:`SOURCE_CONFIGS`.
    """
    known = set(SOURCE_CONFIGS.keys())

    for key in only or []:
        if key not in known:
            raise ValueError(f"unknown source {key!r} in --only. Known: {', '.join(sorted(known))}")
    for key in skip:
        if key not in known:
            raise ValueError(f"unknown source {key!r} in --skip. Known: {', '.join(sorted(known))}")

    base: list[str] = list(only) if only is not None else list(SOURCE_CONFIGS.keys())
    return [s for s in base if s not in skip]


# ---------------------------------------------------------------------------
# Call-cap guard
# ---------------------------------------------------------------------------


def assert_call_cap(total_calls: int) -> None:
    """Assert that the number of live HTTP calls does not exceed MAX_CALLS.

    Args:
        total_calls: The number of HTTP calls that would be (or were) made.

    Raises:
        AssertionError: If ``total_calls`` exceeds :data:`MAX_CALLS`.
    """
    assert total_calls <= MAX_CALLS, (
        f"Call cap exceeded: {total_calls} calls requested but max is {MAX_CALLS}."
    )


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------


def load_creds(cred_keys: list[str]) -> tuple[dict[str, str], list[str]]:
    """Read credential values from environment variables.

    Args:
        cred_keys: Names of env vars to read (e.g. ``["ADZUNA_APP_ID"]``).

    Returns:
        A two-element tuple ``(creds, missing)`` where ``creds`` maps
        env-var name to its value for every var that is set, and
        ``missing`` lists the names of vars that were absent or empty.
    """
    creds: dict[str, str] = {}
    missing: list[str] = []
    for key in cred_keys:
        value = os.environ.get(key, "")
        if value:
            creds[key] = value
        else:
            missing.append(key)
    return creds, missing


# ---------------------------------------------------------------------------
# Response classification
# ---------------------------------------------------------------------------


def _resolve_list_key(
    data: dict[str, Any],
    list_key: str | None,
) -> list[Any] | None:
    """Navigate a dot-path list_key into the response dict.

    Supports one level of nesting (e.g. ``"SearchResult.SearchResultItems"``).

    Args:
        data: Parsed JSON response body.
        list_key: Dot-separated key path, or ``None`` for top-level lists.

    Returns:
        The list found at ``list_key``, or ``None`` if the key is absent
        or the value is not a list.
    """
    if list_key is None:
        return None  # top-level list sources handled separately

    parts = list_key.split(".", 1)
    value: Any = data.get(parts[0])
    if len(parts) == 2 and isinstance(value, dict):
        value = value.get(parts[1])
    return value if isinstance(value, list) else None


def classify_response(
    source: str,
    response: Any,
    listing_key: str | None,
) -> ProbeResult:
    """Classify an HTTP response into a :class:`ProbeResult`.

    Args:
        source: The source key being probed.
        response: A ``requests.Response``-like object with ``.status_code``
            and ``.json()`` attributes.
        listing_key: Dot-path to the listings array in the JSON body.
            ``None`` means the response is itself a top-level list.

    Returns:
        A :class:`ProbeResult` with status ``"green"``,
        ``"needs-fixing"``, or ``"broken-defer-to-v1.1"``.
    """
    code: int = response.status_code

    if code in (401, 403, 404, 429, 500, 502, 503):
        return ProbeResult(
            source=source,
            status="broken-defer-to-v1.1",
            note=f"HTTP {code}",
            http_status=code,
        )

    if code != 200:
        return ProbeResult(
            source=source,
            status="broken-defer-to-v1.1",
            note=f"HTTP {code} (unexpected)",
            http_status=code,
        )

    # HTTP 200 — parse body and inspect listings
    try:
        body: Any = response.json()
    except Exception as exc:
        return ProbeResult(
            source=source,
            status="needs-fixing",
            note=f"JSON parse error: {exc}",
            http_status=code,
        )

    # RemoteOK returns a top-level JSON array; first element is a legal
    # notice dict, remainder are job listings.
    if listing_key is None:
        if isinstance(body, list) and len(body) > 1:
            return ProbeResult(
                source=source,
                status="green",
                note="top-level list",
                http_status=code,
                _raw={"items": body},
            )
        return ProbeResult(
            source=source,
            status="needs-fixing",
            note="expected top-level list with >1 items",
            http_status=code,
        )

    listings = _resolve_list_key(body if isinstance(body, dict) else {}, listing_key)
    if listings is None:
        present_keys = list(body.keys()) if isinstance(body, dict) else []
        return ProbeResult(
            source=source,
            status="needs-fixing",
            note=(f"expected key {listing_key!r} not found; got keys: {present_keys}"),
            http_status=code,
            _raw=body if isinstance(body, dict) else {},
        )

    if len(listings) == 0:
        return ProbeResult(
            source=source,
            status="needs-fixing",
            note=f"HTTP 200 but {listing_key!r} list is empty",
            http_status=code,
            _raw=body if isinstance(body, dict) else {},
        )

    return ProbeResult(
        source=source,
        status="green",
        note=f"{len(listings)} listing(s) returned",
        http_status=code,
        _raw=body if isinstance(body, dict) else {},
    )


# ---------------------------------------------------------------------------
# Single-source probe
# ---------------------------------------------------------------------------


def probe_source(
    source: str,
    dry_run: bool,
    creds: dict[str, str],
) -> ProbeResult:
    """Probe one source API and return a classified :class:`ProbeResult`.

    In dry-run mode no HTTP request is made and status is ``"dry-run"``.
    On HTTP 429 the run aborts cleanly (``sys.exit(1)``).

    Args:
        source: Key from :data:`SOURCE_CONFIGS`.
        dry_run: If ``True``, skip the network call entirely.
        creds: Mapping of env-var name to value for this source.

    Returns:
        A :class:`ProbeResult` describing the outcome.
    """
    cfg = SOURCE_CONFIGS[source]
    cred_keys: list[str] = cfg["cred_keys"]

    # Resolve URL
    raw_url: Any = cfg["url"]
    url: str = raw_url(creds) if callable(raw_url) else raw_url

    # Resolve params
    raw_params: Any = cfg.get("params", {})
    params: dict[str, Any] = raw_params(creds) if callable(raw_params) else raw_params

    # Resolve headers
    raw_headers: Any = cfg.get("headers", {})
    headers: dict[str, str] = raw_headers(creds) if callable(raw_headers) else raw_headers

    list_key: str | None = cfg.get("list_key")

    if dry_run:
        log.info("[DRY-RUN] %s  →  %s  params=%s", source, url, params)
        cred_display = [k for k in cred_keys if creds.get(k)]
        missing = [k for k in cred_keys if not creds.get(k)]
        note_parts = []
        if cred_display:
            note_parts.append(f"creds present: {cred_display}")
        if missing:
            note_parts.append(f"creds missing: {missing}")
        return ProbeResult(
            source=source,
            status="dry-run",
            note="; ".join(note_parts) if note_parts else "no creds required",
        )

    # ---- Live probe ----
    method: str = str(cfg.get("method", "GET"))

    try:
        if method == "POST":
            raw_body: Any = cfg.get("json_body")
            json_body: dict[str, Any] = raw_body(creds) if callable(raw_body) else (raw_body or {})
            response = requests.post(
                url,
                json=json_body,
                headers=headers,
                timeout=15,
            )
        else:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=15,
            )
    except requests.exceptions.RequestException as exc:
        log.error("[%s] Network error: %s", source, exc)
        return ProbeResult(
            source=source,
            status="broken-defer-to-v1.1",
            note=f"Network error: {exc}",
        )

    log.info("[%s] HTTP %d", source, response.status_code)

    if response.status_code == 429:
        log.error("[%s] Rate-limited (HTTP 429) — aborting run cleanly.", source)
        sys.exit(1)

    result = classify_response(source, response, list_key)

    # Persist raw response
    _save_raw(source, response)

    return result


# ---------------------------------------------------------------------------
# Raw response persistence
# ---------------------------------------------------------------------------


def _save_raw(source: str, response: Any) -> None:
    """Save the raw JSON response to .tmp/preflight/<source>.json.

    Args:
        source: Source key, used as the filename stem.
        response: A ``requests.Response``-like object.
    """
    tmp_dir = _PROJECT_ROOT / ".tmp" / "preflight"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / f"{source}.json"
    try:
        body = response.json()
        out_path.write_text(
            json.dumps(body, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("[%s] Raw response saved to %s", source, out_path)
    except Exception as exc:
        log.warning("[%s] Could not save raw response: %s", source, exc)


# ---------------------------------------------------------------------------
# Markdown report rendering
# ---------------------------------------------------------------------------

_STATUS_EMOJI: dict[str, str] = {
    "green": "green",
    "needs-fixing": "needs-fixing",
    "broken-defer-to-v1.1": "broken-defer-to-v1.1",
    "dry-run": "dry-run",
    "skipped": "skipped",
}


def render_markdown_report(
    results: list[ProbeResult],
    dry_run: bool,
) -> str:
    """Render a Markdown summary table from a list of probe results.

    Args:
        results: The list of :class:`ProbeResult` objects to summarise.
        dry_run: If ``True``, prepend a banner indicating no live data.

    Returns:
        A Markdown string ready to write to disk.
    """
    lines: list[str] = []

    lines.append("# Preflight Smoke-Test Results")
    lines.append("")

    if dry_run:
        lines.append(
            "> **DRY RUN — no live results.**  "
            "Run `uv run python scripts/preflight_smoke.py --live` "
            "to populate this table with real data."
        )
        lines.append("")

    lines.append("| Source | Status | HTTP | Note |")
    lines.append("| --- | --- | --- | --- |")

    for r in results:
        http_col = str(r.http_status) if r.http_status is not None else "—"
        note_col = r.note.replace("|", "\\|")
        lines.append(f"| {r.source} | {r.status} | {http_col} | {note_col} |")

    lines.append("")
    lines.append(f"*Generated by `scripts/preflight_smoke.py` — {_run_timestamp()}*")
    return "\n".join(lines) + "\n"


def _run_timestamp() -> str:
    """Return the current UTC timestamp as an ISO-8601 string.

    Returns:
        Current UTC time formatted as ``YYYY-MM-DDTHH:MM:SSZ``.
    """
    import datetime

    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the preflight smoke test and write docs/preflight-smoke-test-results.md.

    Parses CLI arguments, resolves sources, enforces the 10-call cap,
    probes each source (or logs what it would do in dry-run mode), and
    writes a Markdown summary to docs/preflight-smoke-test-results.md.

    Exits with code 0 on success.  Exits with code 1 on rate-limit (429)
    or if any required setup check fails.
    """
    parser = build_arg_parser()
    args = parser.parse_args()

    # Normalise: --live overrides the default --dry-run=True
    dry_run: bool = not args.live

    try:
        sources = resolve_sources(only=args.only, skip=args.skip)
    except ValueError as exc:
        log.error("%s", exc)
        sys.exit(1)

    # Enforce the hard cap before making any calls.
    if not dry_run:
        assert_call_cap(len(sources))

    log.info(
        "Mode: %s | Sources: %s",
        "DRY-RUN" if dry_run else "LIVE",
        ", ".join(sources),
    )

    results: list[ProbeResult] = []

    for source in sources:
        cfg = SOURCE_CONFIGS[source]
        cred_keys: list[str] = cfg["cred_keys"]

        # Load credentials for this source
        all_creds, missing = load_creds(cred_keys)

        if missing and not dry_run:
            log.warning(
                "[%s] Skipping — missing credentials: %s",
                source,
                ", ".join(missing),
            )
            results.append(
                ProbeResult(
                    source=source,
                    status="skipped",
                    note=f"missing env vars: {', '.join(missing)}",
                )
            )
            continue

        result = probe_source(source, dry_run=dry_run, creds=all_creds)
        results.append(result)

    # Write report
    report_path = _PROJECT_ROOT / "docs" / "preflight-smoke-test-results.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    md = render_markdown_report(results, dry_run=dry_run)
    report_path.write_text(md, encoding="utf-8")
    log.info("Report written to %s", report_path)

    # Summary
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    log.info("Summary: %s", counts)


if __name__ == "__main__":
    main()
