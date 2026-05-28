"""JSON output formatter for the job-aggregator ``jobs`` command (§9.2).

Produces a single JSON object (the §9.2 envelope) with all records
inlined into the ``"jobs"`` array.  Suitable for consumers that prefer
a single parse over streaming.

Public API:
    :func:`format_json` — format a completed run as a JSON string.
"""

from __future__ import annotations

import json
from typing import Any

from job_aggregator.envelope import build_envelope
from job_aggregator.schema import JobRecord


def format_json(
    *,
    jobs: list[JobRecord],
    sources_used: list[str],
    sources_failed: list[str],
    request_summary: dict[str, Any],
    query_applied: dict[str, bool] | None = None,
    generated_at: str | None = None,
) -> str:
    """Return a compact JSON string for a completed ``jobs`` run.

    Builds the §9.2 envelope via :func:`~job_aggregator.envelope.build_envelope`
    and appends the optional ``query_applied`` field when provided.

    Args:
        jobs: Normalised job records to include in the ``"jobs"`` array.
        sources_used: Plugin keys that contributed records.
        sources_failed: Plugin keys that failed during the run.
        request_summary: Search-parameter summary dict.
        query_applied: Optional mapping of plugin key → bool.  When
            provided, added as ``"query_applied"`` to the envelope.
        generated_at: Optional ISO-8601 UTC string override for the
            ``generated_at`` field.  Defaults to the current UTC time.

    Returns:
        Compact JSON string (no extra whitespace) representing the full
        §9.2 envelope with all records inlined.
    """
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
