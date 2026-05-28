"""Envelope generator for job-aggregator output (spec §9.2).

Produces the top-level JSON envelope that wraps a collection of
:class:`~job_aggregator.schema.JobRecord` dicts, and provides a JSONL
mode where the envelope is the first line (with an empty ``jobs`` list)
followed by one record per subsequent line.

Public interface:
    :func:`build_envelope` — build the full §9.2 envelope dict.
    :func:`build_jsonl_lines` — yield JSONL lines (envelope first, then
    records).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from job_aggregator.schema import JobRecord

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Schema version for the output envelope.  Major bump = breaking change
#: to Identity / Always-present fields.  Minor bump = new optional fields.
SCHEMA_VERSION: str = "1.0"

# ---------------------------------------------------------------------------
# Envelope TypedDict (informal — not exported as part of public API)
# ---------------------------------------------------------------------------

# The envelope is intentionally a plain dict[str, Any] rather than a
# TypedDict because its shape is fully described by the spec and tested
# directly.  A TypedDict would add maintenance overhead for no runtime
# benefit (TypedDicts are not validated at runtime in Python).

# ---------------------------------------------------------------------------
# build_envelope()
# ---------------------------------------------------------------------------


def build_envelope(
    *,
    command: str,
    sources_used: list[str],
    sources_failed: list[str],
    request_summary: dict[str, Any],
    jobs: list[JobRecord],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the §9.2 JSON envelope dict.

    Produces a dict conforming to the §9.2 envelope schema with
    ``schema_version="1.0"`` and a freshly generated ``generated_at``
    timestamp (unless overridden via the optional *generated_at* argument,
    which is provided for deterministic testing).

    Args:
        command: The CLI command that produced this output (e.g.
            ``"jobs"`` or ``"hydrate"``).
        sources_used: List of plugin keys whose data is included in
            *jobs*.
        sources_failed: List of plugin keys that failed during the run.
        request_summary: Dict describing the search parameters (hours,
            query, location, country, sources).  Preserved verbatim
            from the ``jobs`` run when called from ``hydrate``.
        jobs: List of :class:`~job_aggregator.schema.JobRecord` dicts
            to include in the ``"jobs"`` field.
        generated_at: Optional ISO-8601 UTC string to use as
            ``generated_at``.  Defaults to the current UTC time.  Pass
            an explicit value in tests to avoid time-dependent assertions.

    Returns:
        A ``dict[str, Any]`` matching the §9.2 envelope shape, ready to
        pass to :func:`json.dumps`.
    """
    if generated_at is None:
        now = datetime.now(tz=UTC)
        # Format as RFC 3339 UTC with 'Z' suffix (spec §9.3 posted_at style).
        generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "command": command,
        "sources_used": sources_used,
        "sources_failed": sources_failed,
        "request_summary": request_summary,
        "jobs": list(jobs),
    }


# ---------------------------------------------------------------------------
# build_jsonl_lines()
# ---------------------------------------------------------------------------


def build_jsonl_lines(
    *,
    command: str,
    sources_used: list[str],
    sources_failed: list[str],
    request_summary: dict[str, Any],
    jobs: list[JobRecord],
    generated_at: str | None = None,
) -> Iterator[str]:
    """Yield JSONL lines for the §9.2 JSONL output mode.

    The first yielded line is the envelope with ``"jobs": []``.  Each
    subsequent line is a single :class:`~job_aggregator.schema.JobRecord`
    serialized as compact JSON (no trailing newline on each line — the
    caller is responsible for joining with ``"\\n"`` if writing to a file).

    Args:
        command: CLI command string (e.g. ``"jobs"``).
        sources_used: Plugin keys whose data is included.
        sources_failed: Plugin keys that failed.
        request_summary: Search-parameter summary dict.
        jobs: Records to emit as subsequent lines.
        generated_at: Optional override for the ``generated_at`` timestamp.
            Defaults to current UTC time.

    Yields:
        JSON strings — first the envelope (``jobs=[]``), then one per
        record.  No trailing ``\\n`` characters.
    """
    envelope = build_envelope(
        command=command,
        sources_used=sources_used,
        sources_failed=sources_failed,
        request_summary=request_summary,
        jobs=[],
        generated_at=generated_at,
    )
    yield json.dumps(envelope, separators=(",", ":"))

    for record in jobs:
        yield json.dumps(record, separators=(",", ":"))
