"""Hydrate orchestrator: read records, scrape descriptions, emit enriched output.

Implements the ``hydrate`` command's core loop (spec §8.2, §9.2, §9.6):

1. Infer or accept the input format (JSON envelope or JSONL).
2. Parse the input stream, detecting an optional §9.2 envelope.
3. For each record, apply the §8.2.1 input handling rules:
   - Skip if ``description_source = "full"``.
   - Skip (warn) if ``url`` is absent, null, empty, or non-HTTP/HTTPS.
   - Skip (warn) if ``description_source`` is an unknown value.
   - Pass through unchanged if the total wall-clock budget is exhausted.
4. For records that need scraping, call :func:`~job_aggregator.scraping.scrape_description`.
5. Emit enriched records in the same format as the input (or as overridden
   by ``HydrateConfig.fmt``).
6. Propagate the input envelope, updating ``command`` → ``"hydrate"`` and
   ``generated_at`` → now (spec §9.2).

Public API:
    :class:`HydrateConfig` — typed configuration bag.
    :func:`hydrate` — main entry point consumed by the CLI and tests.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from typing import Any

from job_aggregator.envelope import SCHEMA_VERSION, build_envelope, build_jsonl_lines
from job_aggregator.errors import SchemaVersionError, ScrapeError
from job_aggregator.scraping import scrape_description

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid description_source values understood by this version of the package.
# ---------------------------------------------------------------------------

_KNOWN_DESCRIPTION_SOURCES = frozenset({"full", "snippet", "none"})

# ---------------------------------------------------------------------------
# HydrateConfig — typed configuration bag
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HydrateConfig:
    """Typed configuration for :func:`hydrate`.

    Attributes:
        timeout_per_request: Per-URL HTTP timeout in seconds (§8.2).
        timeout_total: Hard wall-clock budget for the whole run in seconds,
            or ``None`` for no limit (§8.2).
        continue_on_error: When ``True`` (default), scrape failures are
            logged and the record is passed through unchanged.
        strict: When ``True``, raise :class:`~job_aggregator.errors.ScrapeError`
            on the first scrape failure (§8.2).
        fmt: Output format override — ``"json"``, ``"jsonl"``, or ``None``
            to infer from the input.
        verbosity: 0 = default, 1 = ``-v``, 2 = ``-vv``, -1 = ``--quiet``.
    """

    timeout_per_request: int
    timeout_total: int | None
    continue_on_error: bool
    strict: bool
    fmt: str | None
    verbosity: int


# ---------------------------------------------------------------------------
# Format inference
# ---------------------------------------------------------------------------


def _infer_format(raw: str) -> str:
    """Infer the input format from the first non-whitespace byte.

    Per spec §8.2.1: if the first non-whitespace character is ``{`` AND
    the first complete JSON value parses as a single object containing a
    ``"jobs"`` key, treat as ``"json"``.  Otherwise treat as ``"jsonl"``.

    Args:
        raw: The full input string (may be empty).

    Returns:
        ``"json"`` or ``"jsonl"``.
    """
    stripped = raw.lstrip()
    if not stripped.startswith("{"):
        return "jsonl"

    # Try to parse the entire string as a JSON object
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict) and "jobs" in obj:
            return "json"
    except json.JSONDecodeError:
        pass

    return "jsonl"


# ---------------------------------------------------------------------------
# Envelope / record parsing
# ---------------------------------------------------------------------------


def _check_schema_version(schema_version: str) -> None:
    """Raise SchemaVersionError if the major version is incompatible.

    Args:
        schema_version: The ``schema_version`` string from the input envelope.

    Raises:
        SchemaVersionError: If the major component of *schema_version* differs
            from the package's current major version.
    """
    try:
        input_major = int(schema_version.split(".")[0])
        package_major = int(SCHEMA_VERSION.split(".")[0])
    except (ValueError, IndexError):
        # Malformed version — treat as incompatible
        raise SchemaVersionError(got=schema_version, expected=SCHEMA_VERSION) from None

    if input_major != package_major:
        raise SchemaVersionError(got=schema_version, expected=SCHEMA_VERSION)

    if schema_version != SCHEMA_VERSION:
        logger.warning(
            "Input schema_version %r differs from package version %r; proceeding best-effort.",
            schema_version,
            SCHEMA_VERSION,
        )


def _parse_json_input(raw: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parse a JSON-format input string.

    Args:
        raw: A JSON string representing a §9.2 envelope.

    Returns:
        A ``(envelope, records)`` tuple where *envelope* is the full
        envelope dict and *records* is the list of job dicts from the
        ``"jobs"`` field.
    """
    envelope: dict[str, Any] = json.loads(raw)
    records: list[dict[str, Any]] = list(envelope.get("jobs", []))
    return envelope, records


def _parse_jsonl_input(
    raw: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Parse a JSONL-format input string.

    The first line is examined to see if it is an envelope (contains
    ``"schema_version"`` and an empty or absent ``"jobs"`` list).  All
    remaining non-empty lines are treated as job records.

    Args:
        raw: A JSONL string.

    Returns:
        A ``(envelope_or_none, records)`` tuple.
    """
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return None, []

    envelope: dict[str, Any] | None = None
    start = 0

    first = json.loads(lines[0])
    if isinstance(first, dict) and "schema_version" in first:
        envelope = first
        start = 1

    records = [json.loads(line) for line in lines[start:]]
    return envelope, records


# ---------------------------------------------------------------------------
# Record processing
# ---------------------------------------------------------------------------


def _should_skip_record(
    record: dict[str, Any],
) -> tuple[bool, str]:
    """Determine whether a record should be skipped without scraping.

    Implements §8.2.1 input handling rules.

    Args:
        record: A job record dict.

    Returns:
        A ``(skip, reason)`` tuple.  *skip* is ``True`` if the record
        should be passed through unchanged; *reason* is a short string
        describing why (empty when *skip* is ``False``).
    """
    ds = record.get("description_source", "")

    # Row 1: already full — no re-scrape.
    if ds == "full":
        return True, "already_full"

    # Defensive: unknown description_source — pass through.
    if ds not in _KNOWN_DESCRIPTION_SOURCES:
        return True, f"unknown_description_source:{ds}"

    # Rows 2-4: check URL validity.
    url = record.get("url")
    if url is None or url == "":
        return True, "missing_url"

    if not str(url).startswith(("http://", "https://")):
        return True, "malformed_url"

    return False, ""


def _warn_skip(
    record: dict[str, Any],
    reason: str,
) -> None:
    """Emit a stderr warning for a skipped record.

    Only emits when the skip reason is informative (not ``"already_full"``).

    Args:
        record: The job record being skipped.
        reason: The reason returned by :func:`_should_skip_record`.
    """
    if reason == "already_full":
        return
    source = record.get("source", "?")
    source_id = record.get("source_id", "?")
    print(
        f"WARNING: hydrate skipping ({source}, {source_id}): {reason}",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def hydrate(
    stream: StringIO,
    config: HydrateConfig,
) -> str:
    """Read job records from *stream*, scrape descriptions, return enriched output.

    Implements the full §8.2 / §9.6 hydrate pipeline:

    1. Read the full input from *stream*.
    2. Infer or apply the configured format.
    3. Validate the envelope schema version (if present).
    4. Process each record per §8.2.1 and the §9.6 hydrate truth table.
    5. Emit the enriched records, propagating the envelope per §9.2.

    Args:
        stream: Readable text stream containing job records (JSONL or JSON).
        config: A :class:`HydrateConfig` controlling timeouts, error handling,
            output format, and verbosity.

    Returns:
        A string containing the enriched output (JSONL or JSON).

    Raises:
        SchemaVersionError: When the input envelope's major ``schema_version``
            differs from the package's current major version.
        ScrapeError: When ``config.strict`` is ``True`` and a scrape fails.
    """
    raw = stream.read()

    # Determine format.
    fmt = config.fmt if config.fmt is not None else _infer_format(raw)

    # Parse input.
    envelope: dict[str, Any] | None
    if fmt == "json":
        envelope, records = _parse_json_input(raw)
    else:
        envelope, records = _parse_jsonl_input(raw)

    # Validate schema version if present.
    if envelope is not None:
        sv = envelope.get("schema_version", SCHEMA_VERSION)
        _check_schema_version(str(sv))

    # Build a mutable copy of the envelope for propagation.
    input_envelope: dict[str, Any] | None = envelope

    # Track wall-clock budget.
    run_start = time.monotonic()
    budget_exhausted = False

    enriched: list[dict[str, Any]] = []

    for record in records:
        skip, reason = _should_skip_record(record)
        if skip:
            _warn_skip(record, reason)
            enriched.append(record)
            continue

        # Check total timeout budget.
        if config.timeout_total is not None:
            elapsed = time.monotonic() - run_start
            if elapsed >= config.timeout_total:
                if not budget_exhausted:
                    logger.warning(
                        "hydrate: total timeout (%ds) exceeded; "
                        "remaining records passed through unchanged.",
                        config.timeout_total,
                    )
                    budget_exhausted = True
                enriched.append(record)
                continue

        url = str(record["url"])
        fallback_desc = str(record.get("description", ""))

        scraped_text, ok = scrape_description(
            url,
            fallback=fallback_desc,
            timeout=config.timeout_per_request,
        )

        if ok:
            new_record = dict(record)
            new_record["description"] = scraped_text
            new_record["description_source"] = "full"
            enriched.append(new_record)
        else:
            # Scrape failed.
            if config.strict:
                raise ScrapeError(url=url, reason="scrape returned ok=False")
            enriched.append(record)

    # Assemble the output envelope.
    now = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    if input_envelope is not None:
        sources_used: list[str] = list(input_envelope.get("sources_used", []))
        sources_failed: list[str] = list(input_envelope.get("sources_failed", []))
        request_summary: dict[str, Any] = dict(input_envelope.get("request_summary", {}))
    else:
        sources_used = []
        sources_failed = []
        request_summary = {}

    if fmt == "json":
        out_envelope = build_envelope(
            command="hydrate",
            sources_used=sources_used,
            sources_failed=sources_failed,
            request_summary=request_summary,
            jobs=enriched,  # type: ignore[arg-type]
            generated_at=now,
        )
        return json.dumps(out_envelope, separators=(",", ":"))
    else:
        lines = list(
            build_jsonl_lines(
                command="hydrate",
                sources_used=sources_used,
                sources_failed=sources_failed,
                request_summary=request_summary,
                jobs=enriched,  # type: ignore[arg-type]
                generated_at=now,
            )
        )
        return "\n".join(lines)
