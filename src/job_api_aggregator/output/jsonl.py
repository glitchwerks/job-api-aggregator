"""JSONL output formatter for the job-aggregator ``jobs`` command (§9.2).

Produces a JSONL stream where:

* **Line 1** — the §9.2 envelope dict with ``"jobs": []`` (records are
  *not* inlined into the envelope in JSONL mode).
* **Lines 2+** — one :class:`~job_aggregator.schema.JobRecord` per line,
  serialised as compact JSON (no trailing newline per line).

This layout lets streaming consumers start processing records before the
full run completes because the envelope metadata is known upfront.

Public API:
    :func:`format_jsonl` — format a completed run as a JSONL string.
    :func:`iter_jsonl_lines` — lazily yield JSONL lines as they are built.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from job_aggregator.envelope import build_jsonl_lines
from job_aggregator.schema import JobRecord


def iter_jsonl_lines(
    *,
    jobs: list[JobRecord],
    sources_used: list[str],
    sources_failed: list[str],
    request_summary: dict[str, Any],
    query_applied: dict[str, bool] | None = None,
    generated_at: str | None = None,
) -> Iterator[str]:
    """Yield JSONL lines for a completed ``jobs`` run.

    The first yielded line is the §9.2 envelope with ``"jobs": []`` and
    an optional ``"query_applied"`` field.  Each subsequent line is a
    single :class:`~job_aggregator.schema.JobRecord` serialised as compact
    JSON.

    Args:
        jobs: Normalised job records to emit.
        sources_used: Plugin keys that contributed records.
        sources_failed: Plugin keys that failed.
        request_summary: Search-parameter summary dict.
        query_applied: Optional mapping of plugin key → bool.  When
            provided, added as ``"query_applied"`` to the envelope line.
        generated_at: Optional ISO-8601 UTC string override for
            ``generated_at``.  Defaults to the current UTC time.

    Yields:
        JSON strings — first the envelope (``jobs=[]``), then one per
        record.  No trailing ``\\n`` characters.
    """
    import json

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

    if query_applied is not None and lines:
        first_obj = json.loads(lines[0])
        first_obj["query_applied"] = query_applied
        lines[0] = json.dumps(first_obj, separators=(",", ":"))

    yield from lines


def format_jsonl(
    *,
    jobs: list[JobRecord],
    sources_used: list[str],
    sources_failed: list[str],
    request_summary: dict[str, Any],
    query_applied: dict[str, bool] | None = None,
    generated_at: str | None = None,
) -> str:
    """Return a JSONL string for a completed ``jobs`` run.

    Calls :func:`iter_jsonl_lines` and joins the results with ``"\\n"``.

    Args:
        jobs: Normalised job records.
        sources_used: Successful plugin keys.
        sources_failed: Failed plugin keys.
        request_summary: Search-parameter summary dict.
        query_applied: Optional query_applied mapping.
        generated_at: Optional ``generated_at`` override.

    Returns:
        JSONL string with the envelope on the first line and one record
        per subsequent line.
    """
    return "\n".join(
        iter_jsonl_lines(
            jobs=jobs,
            sources_used=sources_used,
            sources_failed=sources_failed,
            request_summary=request_summary,
            query_applied=query_applied,
            generated_at=generated_at,
        )
    )
