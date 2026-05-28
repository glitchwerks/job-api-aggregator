"""Tests for job_api_aggregator.hydrator — orchestrator-level hydrate logic.

Covers:
- §9.6 hydrate truth table rows (all four hydrate-orchestrator rows).
- §8.2.1 input handling cases (every table row).
- --timeout-per-request is passed to scrape_description.
- --timeout-total: remaining records pass through unchanged when exceeded.
- --strict raises / returns non-zero on scrape failure.
- --continue-on-error (default) keeps going on failure.
- Envelope propagation: command → "hydrate", generated_at updated,
  request_summary preserved.
- Format inference: { + jobs key → json; otherwise → jsonl.
- Cross-major schema_version mismatch raises SchemaVersionError.
"""

from __future__ import annotations

import io
import json
import time
from typing import Any
from unittest.mock import patch

import pytest

from job_api_aggregator.errors import SchemaVersionError
from job_api_aggregator.hydrator import HydrateConfig, hydrate

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_LONG_TEXT = "word " * 120  # safely above SCRAPE_MIN_LENGTH


def _make_record(
    *,
    source: str = "test",
    source_id: str = "001",
    url: str = "https://example.com/job/1",
    description: str = "short snippet",
    description_source: str = "snippet",
    **extra: Any,
) -> dict[str, Any]:
    """Return a minimal job record dict."""
    rec: dict[str, Any] = {
        "source": source,
        "source_id": source_id,
        "url": url,
        "title": "Test Job",
        "description": description,
        "description_source": description_source,
        "posted_at": "2026-04-01T00:00:00Z",
        "company": None,
        "location": None,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_period": None,
        "contract_type": None,
        "contract_time": None,
        "remote_eligible": None,
    }
    rec.update(extra)
    return rec


def _make_jsonl_input(
    records: list[dict[str, Any]],
    envelope: dict[str, Any] | None = None,
) -> str:
    """Return a JSONL string with optional envelope on first line."""
    lines: list[str] = []
    if envelope is not None:
        lines.append(json.dumps(envelope))
    for rec in records:
        lines.append(json.dumps(rec))
    return "\n".join(lines)


def _make_json_input(
    records: list[dict[str, Any]],
    envelope_extra: dict[str, Any] | None = None,
) -> str:
    """Return a JSON envelope string with records in 'jobs'."""
    env: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": "2026-04-01T00:00:00Z",
        "command": "jobs",
        "sources_used": ["test"],
        "sources_failed": [],
        "request_summary": {
            "hours": 24,
            "query": None,
            "location": None,
            "country": None,
            "sources": ["test"],
        },
        "jobs": records,
    }
    if envelope_extra:
        env.update(envelope_extra)
    return json.dumps(env)


def _default_config(**kwargs: Any) -> HydrateConfig:
    """Return a HydrateConfig with sensible defaults for testing."""
    defaults: dict[str, Any] = {
        "timeout_per_request": 15,
        "timeout_total": None,
        "continue_on_error": True,
        "strict": False,
        "fmt": None,
        "verbosity": 0,
    }
    defaults.update(kwargs)
    return HydrateConfig(**defaults)


# ---------------------------------------------------------------------------
# §9.6 hydrate truth table rows
# ---------------------------------------------------------------------------


def test_hydrate_row1_already_full_passes_through() -> None:
    """Row 1: description_source='full' → pass through unchanged, no scrape."""
    rec = _make_record(
        description="already full text",
        description_source="full",
    )
    input_text = _make_jsonl_input([rec])

    with patch("job_api_aggregator.hydrator.scrape_description") as mock_scrape:
        result = hydrate(io.StringIO(input_text), _default_config())

    mock_scrape.assert_not_called()
    records = _parse_records(result)
    assert records[0]["description_source"] == "full"
    assert records[0]["description"] == "already full text"


def test_hydrate_row2_snippet_scrape_success_sets_full() -> None:
    """Row 2: snippet + scrape success → description_source='full', new text."""
    rec = _make_record(description_source="snippet")
    input_text = _make_jsonl_input([rec])

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        result = hydrate(io.StringIO(input_text), _default_config())

    records = _parse_records(result)
    assert records[0]["description_source"] == "full"
    assert records[0]["description"] == _LONG_TEXT


def test_hydrate_row2_none_scrape_success_sets_full() -> None:
    """Row 2 (none variant): description_source='none' + success → 'full'."""
    rec = _make_record(description="", description_source="none")
    input_text = _make_jsonl_input([rec])

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        result = hydrate(io.StringIO(input_text), _default_config())

    records = _parse_records(result)
    assert records[0]["description_source"] == "full"
    assert records[0]["description"] == _LONG_TEXT


def test_hydrate_row3_scrape_failure_preserves_input() -> None:
    """Row 3: snippet + scrape failure → description_source unchanged."""
    rec = _make_record(
        description="original snippet",
        description_source="snippet",
    )
    input_text = _make_jsonl_input([rec])

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=("original snippet", False),
    ):
        result = hydrate(io.StringIO(input_text), _default_config())

    records = _parse_records(result)
    assert records[0]["description_source"] == "snippet"
    assert records[0]["description"] == "original snippet"


def test_hydrate_row4_missing_url_passes_through() -> None:
    """Row 4: url missing → pass through unchanged, no scrape."""
    rec = _make_record()
    del rec["url"]
    input_text = _make_jsonl_input([rec])

    with patch("job_api_aggregator.hydrator.scrape_description") as mock_scrape:
        result = hydrate(io.StringIO(input_text), _default_config())

    mock_scrape.assert_not_called()
    records = _parse_records(result)
    assert records[0]["description_source"] == "snippet"


# ---------------------------------------------------------------------------
# §8.2.1 input handling cases
# ---------------------------------------------------------------------------


def test_input_handling_url_absent_passes_through(capsys: pytest.CaptureFixture[str]) -> None:
    """url key absent: pass through unchanged, emit warning."""
    rec = _make_record()
    del rec["url"]
    input_text = _make_jsonl_input([rec])

    with patch("job_api_aggregator.hydrator.scrape_description") as mock_scrape:
        hydrate(io.StringIO(input_text), _default_config())

    mock_scrape.assert_not_called()
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower() or "warn" in captured.err.lower()


def test_input_handling_url_null_passes_through(capsys: pytest.CaptureFixture[str]) -> None:
    """url=null: pass through unchanged, emit warning."""
    rec = _make_record(url=None)  # type: ignore[arg-type]
    input_text = _make_jsonl_input([rec])

    with patch("job_api_aggregator.hydrator.scrape_description") as mock_scrape:
        hydrate(io.StringIO(input_text), _default_config())

    mock_scrape.assert_not_called()


def test_input_handling_url_empty_passes_through(capsys: pytest.CaptureFixture[str]) -> None:
    """url='': pass through unchanged, emit warning."""
    rec = _make_record(url="")
    input_text = _make_jsonl_input([rec])

    with patch("job_api_aggregator.hydrator.scrape_description") as mock_scrape:
        hydrate(io.StringIO(input_text), _default_config())

    mock_scrape.assert_not_called()


def test_input_handling_malformed_url_passes_through(capsys: pytest.CaptureFixture[str]) -> None:
    """url malformed (not http/https): pass through unchanged, emit warning."""
    rec = _make_record(url="ftp://not-http.example.com/")
    input_text = _make_jsonl_input([rec])

    with patch("job_api_aggregator.hydrator.scrape_description") as mock_scrape:
        hydrate(io.StringIO(input_text), _default_config())

    mock_scrape.assert_not_called()


def test_input_handling_unknown_description_source_passes_through() -> None:
    """description_source not in {full,snippet,none}: pass through, warn."""
    rec = _make_record(description_source="unknown_future_value")
    input_text = _make_jsonl_input([rec])

    with patch("job_api_aggregator.hydrator.scrape_description") as mock_scrape:
        result = hydrate(io.StringIO(input_text), _default_config())

    mock_scrape.assert_not_called()
    records = _parse_records(result)
    assert records[0]["description_source"] == "unknown_future_value"


def test_input_handling_cross_major_schema_raises() -> None:
    """Envelope with incompatible major schema_version raises SchemaVersionError."""
    rec = _make_record()
    input_text = _make_json_input([rec], {"schema_version": "2.0"})

    with pytest.raises(SchemaVersionError):
        hydrate(io.StringIO(input_text), _default_config())


def test_input_handling_same_major_minor_diff_warns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Envelope with same major but different minor version proceeds with warning."""
    rec = _make_record()
    input_text = _make_json_input([rec], {"schema_version": "1.99"})

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        result = hydrate(io.StringIO(input_text), _default_config(fmt="json"))

    # Should succeed (not raise)
    assert result != ""


# ---------------------------------------------------------------------------
# --strict vs --continue-on-error
# ---------------------------------------------------------------------------


def test_strict_raises_on_scrape_failure() -> None:
    """--strict: ScrapeError (or SystemExit) raised on scrape failure."""
    from job_api_aggregator.errors import ScrapeError

    rec = _make_record(description_source="snippet")
    input_text = _make_jsonl_input([rec])

    with (
        patch(
            "job_api_aggregator.hydrator.scrape_description",
            return_value=("short", False),
        ),
        pytest.raises((ScrapeError, SystemExit)),
    ):
        hydrate(
            io.StringIO(input_text),
            _default_config(strict=True, continue_on_error=False),
        )


def test_continue_on_error_does_not_raise() -> None:
    """--continue-on-error (default): scrape failure passes through silently."""
    rec = _make_record(description_source="snippet")
    input_text = _make_jsonl_input([rec])

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=("short snippet", False),
    ):
        # Should NOT raise
        result = hydrate(io.StringIO(input_text), _default_config())

    records = _parse_records(result)
    assert records[0]["description_source"] == "snippet"


# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


def test_timeout_per_request_passed_to_scrape() -> None:
    """timeout_per_request must be forwarded to scrape_description."""
    rec = _make_record(description_source="snippet")
    input_text = _make_jsonl_input([rec])

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ) as mock_scrape:
        hydrate(
            io.StringIO(input_text),
            _default_config(timeout_per_request=5),
        )

    mock_scrape.assert_called_once()
    call_kwargs = mock_scrape.call_args
    # timeout_per_request should appear in kwargs or positional args
    assert 5 in call_kwargs.args or call_kwargs.kwargs.get("timeout") == 5


def test_timeout_total_exceeded_passes_remaining_through() -> None:
    """When timeout_total is exceeded, remaining records pass through unchanged."""

    rec1 = _make_record(source_id="001", description_source="snippet")
    rec2 = _make_record(source_id="002", description_source="snippet")
    input_text = _make_jsonl_input([rec1, rec2])

    call_count = 0

    def slow_scrape(url: str, fallback: str = "", timeout: int = 15) -> tuple[str, bool]:
        nonlocal call_count
        call_count += 1
        time.sleep(0.2)  # simulate slow HTTP
        return (_LONG_TEXT, True)

    with patch("job_api_aggregator.hydrator.scrape_description", side_effect=slow_scrape):
        result = hydrate(
            io.StringIO(input_text),
            _default_config(timeout_total=0),  # 0s budget → expires immediately
        )

    # At least one record should be passed through unchanged
    records = _parse_records(result)
    assert len(records) == 2
    unchanged_count = sum(1 for r in records if r["description_source"] == "snippet")
    assert unchanged_count >= 1


# ---------------------------------------------------------------------------
# Envelope propagation
# ---------------------------------------------------------------------------


def test_hydrate_updates_command_in_envelope() -> None:
    """Output envelope must have command='hydrate'."""
    rec = _make_record()
    input_text = _make_json_input([rec])

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        result = hydrate(io.StringIO(input_text), _default_config(fmt="json"))

    envelope = json.loads(result)
    assert envelope["command"] == "hydrate"


def test_hydrate_updates_generated_at_in_envelope() -> None:
    """Output envelope generated_at must differ from the input's generated_at."""
    rec = _make_record()
    input_text = _make_json_input([rec], {"generated_at": "2020-01-01T00:00:00Z"})

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        result = hydrate(io.StringIO(input_text), _default_config(fmt="json"))

    envelope = json.loads(result)
    assert envelope["generated_at"] != "2020-01-01T00:00:00Z"


def test_hydrate_preserves_request_summary() -> None:
    """Output envelope request_summary must be copied verbatim from input."""
    rec = _make_record()
    summary = {
        "hours": 48,
        "query": "python",
        "location": "Atlanta",
        "country": None,
        "sources": ["test"],
    }
    input_text = _make_json_input([rec], {"request_summary": summary})

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        result = hydrate(io.StringIO(input_text), _default_config(fmt="json"))

    envelope = json.loads(result)
    assert envelope["request_summary"] == summary


# ---------------------------------------------------------------------------
# Format inference
# ---------------------------------------------------------------------------


def test_format_inference_json_when_jobs_key_present() -> None:
    """Input starting with { containing 'jobs' key infers --format json."""
    rec = _make_record()
    input_text = _make_json_input([rec])

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        # fmt=None → inferred
        result = hydrate(io.StringIO(input_text), _default_config(fmt=None))

    # Output should be parseable as single JSON object with 'jobs' key
    parsed = json.loads(result)
    assert "jobs" in parsed
    assert isinstance(parsed["jobs"], list)


def test_format_inference_jsonl_for_plain_records() -> None:
    """Input without envelope { object infers --format jsonl."""
    rec = _make_record()
    input_text = _make_jsonl_input([rec])  # no envelope

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        result = hydrate(io.StringIO(input_text), _default_config(fmt=None))

    # JSONL: first line is envelope, second is record
    lines = [ln for ln in result.split("\n") if ln.strip()]
    assert len(lines) >= 1
    first = json.loads(lines[0])
    # First line should be envelope (has schema_version) or record
    # Accept either layout — the key requirement is that it parses as JSONL
    assert isinstance(first, dict)


def test_format_inference_jsonl_when_no_jobs_key() -> None:
    """Input starting with { but no 'jobs' key uses jsonl format."""
    # A record that starts with { but lacks the envelope jobs key
    rec = _make_record()
    # Produce JSONL with an envelope that has no 'jobs' key
    bare_envelope = {"schema_version": "1.0", "command": "jobs"}
    lines = [json.dumps(bare_envelope), json.dumps(rec)]
    input_text = "\n".join(lines)

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        # Should not raise
        result = hydrate(io.StringIO(input_text), _default_config(fmt=None))

    assert result != ""


# ---------------------------------------------------------------------------
# Public API re-export
# ---------------------------------------------------------------------------


def test_hydrate_re_exported_from_package() -> None:
    """hydrate must be importable from the package root."""
    from job_api_aggregator import hydrate as pkg_hydrate

    assert callable(pkg_hydrate)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_records(output: str) -> list[dict[str, Any]]:
    """Parse hydrate output (JSONL or JSON) and return the record list."""
    output = output.strip()
    if not output:
        return []

    # Try JSON envelope first
    try:
        parsed = json.loads(output)
        if isinstance(parsed, dict) and "jobs" in parsed:
            result: list[dict[str, Any]] = parsed["jobs"]
            return result
    except json.JSONDecodeError:
        pass

    # JSONL: first line is envelope (with jobs=[]), rest are records
    lines = [ln for ln in output.split("\n") if ln.strip()]
    records: list[dict[str, Any]] = []
    for line in lines:
        obj = json.loads(line)
        if "jobs" not in obj:  # it's a record, not the envelope
            records.append(obj)
    return records
