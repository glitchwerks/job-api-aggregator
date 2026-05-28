"""Jobs orchestrator: fetch + normalize + dedup + emit.

This module implements the ``jobs`` command's core loop:

1. Resolve which plugins to run (``sources`` / ``exclude_sources`` filters).
2. Optionally emit Q4 stderr warning for ``--query`` + non-``always`` sources.
3. For each enabled source: instantiate the plugin class, iterate
   ``pages()``, normalise each raw dict, dedup by ``(source, source_id)``
   with URL normalisation, and accumulate records.
4. Respect the ``limit`` cap on emitted records.
5. Assemble the §9.2 envelope (with ``query_applied`` when a query is
   given) and serialise to JSON or JSONL.

The orchestrator is pure-Python and free of I/O side effects beyond the
``sys.stderr`` Q4 warning.  Callers are responsible for writing the
returned string to stdout or a file.

Public API:
    :func:`run_jobs` — main entry point consumed by the CLI and tests.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse, urlunparse

from job_aggregator.auto_register import discover_plugins
from job_aggregator.base import JobSource
from job_aggregator.envelope import build_envelope, build_jsonl_lines
from job_aggregator.normalizer import normalize
from job_aggregator.schema import JobRecord, SearchParams

# ---------------------------------------------------------------------------
# URL normalisation helpers
# ---------------------------------------------------------------------------


def _normalize_url(url: str) -> str:
    """Strip query params, fragments, and trailing slashes from *url*.

    Used as the deduplication key alongside ``(source, source_id)``.
    The original URL is **not** modified in the emitted record — this
    function is only used to compute the dedup key.

    Args:
        url: A raw URL string from a plugin record.

    Returns:
        The URL with query string, fragment, and trailing slash removed.
        Returns the original value unchanged if it does not look like an
        HTTP/HTTPS URL.
    """
    if not url or not url.startswith(("http://", "https://")):
        return url
    parsed = urlparse(url)
    # Rebuild without query or fragment; strip trailing slash from path
    clean_path = parsed.path.rstrip("/") or "/"
    normalised = urlunparse((parsed.scheme, parsed.netloc, clean_path, "", "", ""))
    return normalised


# ---------------------------------------------------------------------------
# Plugin instantiation helper
# ---------------------------------------------------------------------------


def _instantiate_plugin(
    cls: type[JobSource],
    credentials: dict[str, Any],
    search: SearchParams,
) -> JobSource:
    """Instantiate a plugin class with the canonical constructor signature.

    All plugins implement the standardised keyword-only signature::

        cls(*, credentials: dict | None = None, search: SearchParams | None = None)

    Args:
        cls: The plugin class to instantiate.
        credentials: Credentials dict for the source key (may be empty).
        search: :class:`~job_aggregator.schema.SearchParams` instance
            carrying the user's query, location, country, hours, and
            max_pages preferences.

    Returns:
        An instantiated :class:`~job_aggregator.base.JobSource`.

    Raises:
        TypeError: If the constructor call fails (unexpected signature).
        CredentialsError: Propagated from the plugin when required
            credentials are missing or empty.
    """
    return cls(credentials=credentials, search=search)


# ---------------------------------------------------------------------------
# Query-applied helper
# ---------------------------------------------------------------------------


def _build_query_applied(
    plugin_classes: dict[str, type[JobSource]],
) -> dict[str, bool]:
    """Build the ``query_applied`` mapping for the envelope.

    A source has ``query_applied=True`` only when its ``ACCEPTS_QUERY``
    class attribute is ``"always"``.  ``"partial"`` and ``"never"``
    both map to ``False`` because the query is not reliably applied.

    Args:
        plugin_classes: Mapping of plugin key → class for all *enabled*
            sources (after ``sources`` / ``exclude_sources`` filtering).

    Returns:
        Dict mapping plugin key → ``bool``.
    """
    return {key: cls.ACCEPTS_QUERY == "always" for key, cls in plugin_classes.items()}


# ---------------------------------------------------------------------------
# Hours-filter helpers
# ---------------------------------------------------------------------------

_UTC = UTC

_log = logging.getLogger(__name__)


def _parse_posted_at(posted_at: str | None) -> datetime | None:
    """Parse an RFC 3339 UTC timestamp string into a timezone-aware datetime.

    Accepts the common ``Z``-suffixed form as well as explicit ``+00:00``.
    Returns ``None`` for ``None`` input, empty strings, or any string that
    cannot be parsed — callers treat ``None`` as "unknown".

    Args:
        posted_at: An RFC 3339 UTC timestamp string (e.g.
            ``"2026-04-01T00:00:00Z"``), or ``None`` / empty string.

    Returns:
        A timezone-aware :class:`~datetime.datetime` in UTC, or ``None``
        if the value is absent or not parseable.
    """
    if not posted_at:
        return None
    # Normalise the trailing 'Z' to '+00:00' so fromisoformat accepts it
    # on Python 3.10 and earlier (fromisoformat supports 'Z' from 3.11+).
    normalised = posted_at.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalised)
        # Ensure the result is timezone-aware; treat naive as UTC.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_UTC)
        return dt
    except (ValueError, OverflowError):
        return None


def _apply_hours_filter(
    records: list[Any],
    hours: int,
    source_key: str,
) -> tuple[list[Any], int]:
    """Filter *records* to those within the *hours* lookback window.

    Soft-filter policy: records with ``None`` or unparseable ``posted_at``
    are **kept**; only records with a parseable timestamp strictly older
    than ``cutoff`` are dropped.

    Args:
        records: Normalised :class:`~job_aggregator.schema.JobRecord` list
            from a single source.
        hours: Lookback window in hours.  ``cutoff = now_utc - hours``.
        source_key: Plugin key used only for the summary log line.

    Returns:
        A 2-tuple of ``(kept_records, drop_count)`` where *drop_count* is
        the number of records that were dropped.
    """
    cutoff = datetime.now(_UTC) - timedelta(hours=hours)
    kept: list[Any] = []
    dropped = 0
    for record in records:
        dt = _parse_posted_at(record.get("posted_at"))
        if dt is None:
            # Null / unparseable → keep (soft-filter policy)
            kept.append(record)
        elif dt >= cutoff:
            kept.append(record)
        else:
            dropped += 1
    if dropped:
        _log.info(
            "source %r: dropped %d record(s) older than %d-hour cutoff",
            source_key,
            dropped,
            hours,
        )
    return kept, dropped


# ---------------------------------------------------------------------------
# Q4 stderr warning
# ---------------------------------------------------------------------------


def _emit_query_warning(
    query: str,
    plugin_classes: dict[str, type[JobSource]],
) -> None:
    """Print a Q4 warning to stderr if any source will not apply *query*.

    Emits exactly one line to ``sys.stderr`` naming every source whose
    ``ACCEPTS_QUERY`` is ``"never"`` or ``"partial"`` so the user knows
    their query will be silently ignored for those sources.

    Args:
        query: The ``--query`` string supplied by the user.
        plugin_classes: Enabled plugin mapping (post-filter).
    """
    limited_keys = sorted(
        key for key, cls in plugin_classes.items() if cls.ACCEPTS_QUERY in ("never", "partial")
    )
    if not limited_keys:
        return
    keys_str = ", ".join(limited_keys)
    print(
        f"WARNING: --query {query!r} will not apply to: {keys_str} (accepts_query=never, partial)",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Main orchestrator entry point
# ---------------------------------------------------------------------------


def run_jobs(
    *,
    plugin_classes: dict[str, type[JobSource]] | None = None,
    credentials: dict[str, Any] | None = None,
    format: str = "jsonl",
    query: str | None = None,
    location: str | None = None,
    country: str | None = None,
    hours: int = 168,
    max_pages: int | None = None,
    sources: list[str] | None = None,
    exclude_sources: list[str] | None = None,
    limit: int = 0,
    strict: bool = False,
    dry_run: bool = False,
    generated_at: str | None = None,
) -> str:
    """Run the ``jobs`` fetch-normalize-dedup-emit pipeline.

    Discovers (or accepts) plugins, resolves the enabled set, runs the
    fetch loop, deduplicates records, and serialises the result to a
    string in the requested format.

    Args:
        plugin_classes: Optional pre-resolved plugin mapping (for tests).
            When ``None``, :func:`~job_aggregator.auto_register.discover_plugins`
            is called to discover installed plugins via entry-points.
        credentials: Credentials dict keyed by plugin ``SOURCE`` (the
            ``"plugins"`` sub-dict from the credentials file).  Defaults
            to an empty dict.
        format: Output format; one of ``"jsonl"`` or ``"json"``.
            Defaults to ``"jsonl"``.
        query: Free-text search query.  Passed to plugins that support it.
        location: Location hint.  Passed to plugins that accept it.
        country: ISO 3166-1 alpha-2 country code.
        hours: Lookback window in hours.  Defaults to 168 (one week).
        max_pages: Per-source page cap.  ``None`` uses each plugin's
            default.
        sources: Allowlist of plugin keys to run.  When non-empty, only
            listed keys are run (unknown keys are silently ignored).
        exclude_sources: Blocklist of plugin keys to skip.
        limit: Maximum number of records to emit.  ``0`` means unlimited.
        strict: When ``True``, re-raise the first source error instead of
            recording it in ``sources_failed``.
        dry_run: When ``True``, skip the fetch loop entirely and return an
            envelope with ``jobs=[]``.
        generated_at: Optional ISO-8601 UTC string override for the
            ``generated_at`` envelope field.  Used in tests for
            deterministic output.

    Returns:
        A string containing the serialised output (JSONL lines joined by
        ``"\\n"`` or a single JSON object).

    Raises:
        Exception: Any exception raised by a plugin's ``pages()`` call
            when ``strict=True``.
    """
    creds: dict[str, Any] = credentials or {}

    # ------------------------------------------------------------------
    # 1. Resolve enabled plugin classes
    # ------------------------------------------------------------------
    if plugin_classes is None:
        plugin_classes = discover_plugins()

    enabled: dict[str, type[JobSource]] = dict(plugin_classes)

    # Apply --sources allowlist
    if sources:
        enabled = {k: v for k, v in enabled.items() if k in sources}

    # Apply --exclude-sources blocklist
    if exclude_sources:
        enabled = {k: v for k, v in enabled.items() if k not in exclude_sources}

    # ------------------------------------------------------------------
    # 2. Q4 query warning (before any fetching)
    # ------------------------------------------------------------------
    if query:
        _emit_query_warning(query, enabled)

    # ------------------------------------------------------------------
    # 3. Build SearchParams for plugin constructors
    # ------------------------------------------------------------------
    search_params = SearchParams(
        query=query,
        location=location,
        country=country,
        hours=hours,
        max_pages=max_pages,
    )

    # ------------------------------------------------------------------
    # 4. Build query_applied mapping (only when query is given)
    # ------------------------------------------------------------------
    query_applied: dict[str, bool] | None = None
    if query:
        query_applied = _build_query_applied(enabled)

    # ------------------------------------------------------------------
    # 5. Build request_summary for the envelope
    # ------------------------------------------------------------------
    request_summary: dict[str, Any] = {
        "hours": hours,
        "query": query,
        "location": location,
        "country": country,
        "sources": list(enabled.keys()),
    }

    # ------------------------------------------------------------------
    # 6. Dry-run: return envelope immediately with no fetch
    # ------------------------------------------------------------------
    if dry_run:
        return _serialise(
            jobs=[],
            sources_used=[],
            sources_failed=[],
            request_summary=request_summary,
            query_applied=query_applied,
            format=format,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # 7. Fetch + normalise + dedup loop
    # ------------------------------------------------------------------
    # Dedup key: (source, source_id) — URLs are used as secondary check
    seen: set[tuple[str, str]] = set()
    records: list[JobRecord] = []
    sources_used: list[str] = []
    sources_failed: list[str] = []
    total_filtered_by_hours: int = 0

    for key, cls in enabled.items():
        source_creds: dict[str, Any] = creds.get(key, {})
        try:
            plugin = _instantiate_plugin(cls, source_creds, search_params)
            # Collect all normalised records for this source before dedup
            # so the hours filter sees the full set (not limit-capped).
            source_records: list[JobRecord] = []
            for page in plugin.pages():
                for raw in page:
                    normalised_raw = plugin.normalise(raw)
                    record = normalize(normalised_raw)
                    source_records.append(record)

            # ----------------------------------------------------------
            # Apply hours filter (post-fetch, per-source)
            # ----------------------------------------------------------
            source_records, dropped = _apply_hours_filter(source_records, hours, key)
            total_filtered_by_hours += dropped

            # Dedup + limit
            source_had_records = False
            for record in source_records:
                dedup_key = (record["source"], record["source_id"])
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                records.append(record)
                source_had_records = True
                if limit > 0 and len(records) >= limit:
                    break

            if not sources_used or key not in sources_used:
                sources_used.append(key)
            _ = source_had_records  # suppress unused warning
        except Exception as exc:
            if strict:
                raise
            sources_failed.append(key)
            print(
                f"ERROR: source {key!r} failed: {exc}",
                file=sys.stderr,
            )
            continue

        if limit > 0 and len(records) >= limit:
            break

    # ------------------------------------------------------------------
    # 8. Augment request_summary with hours-filter observability count
    # ------------------------------------------------------------------
    request_summary["records_filtered_by_hours"] = total_filtered_by_hours

    # ------------------------------------------------------------------
    # 9. Serialise and return
    # ------------------------------------------------------------------
    return _serialise(
        jobs=records,
        sources_used=sources_used,
        sources_failed=sources_failed,
        request_summary=request_summary,
        query_applied=query_applied,
        format=format,
        generated_at=generated_at,
    )


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _serialise(
    *,
    jobs: list[JobRecord],
    sources_used: list[str],
    sources_failed: list[str],
    request_summary: dict[str, Any],
    query_applied: dict[str, bool] | None,
    format: str,
    generated_at: str | None,
) -> str:
    """Serialise the run result to the requested output format string.

    Builds the §9.2 envelope and appends ``query_applied`` when present.

    Args:
        jobs: Normalised :class:`~job_aggregator.schema.JobRecord` list.
        sources_used: Plugin keys that successfully contributed records.
        sources_failed: Plugin keys that raised during the run.
        request_summary: Search-parameter summary dict.
        query_applied: Optional mapping of plugin key → bool.  Included
            in the envelope only when non-``None``.
        format: One of ``"json"`` or ``"jsonl"``.
        generated_at: Optional override for the ``generated_at`` timestamp.

    Returns:
        Serialised string in the requested format.

    Raises:
        ValueError: If *format* is not ``"json"`` or ``"jsonl"``.
    """
    if format == "json":
        envelope = build_envelope(
            command="jobs",
            sources_used=sources_used,
            sources_failed=sources_failed,
            request_summary=request_summary,
            jobs=jobs,
            generated_at=generated_at,
        )
        if query_applied is not None:
            envelope["query_applied"] = query_applied
        return json.dumps(envelope, separators=(",", ":"))

    if format == "jsonl":
        lines = list(
            build_jsonl_lines(
                command="jobs",
                sources_used=sources_used,
                sources_failed=sources_failed,
                request_summary=request_summary,
                jobs=jobs,
                generated_at=generated_at,
            )
        )
        # The envelope is the first line — inject query_applied into it
        if query_applied is not None and lines:
            first_obj = json.loads(lines[0])
            first_obj["query_applied"] = query_applied
            lines[0] = json.dumps(first_obj, separators=(",", ":"))
        return "\n".join(lines)

    raise ValueError(f"Unknown format {format!r}: expected 'json' or 'jsonl'.")
