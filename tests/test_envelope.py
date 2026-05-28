"""Tests for the job_api_aggregator.envelope module.

Covers:
- build_envelope() produces the correct §9.2 structure.
- schema_version is "1.0".
- generated_at is a valid UTC ISO-8601 string.
- jobs list is included in JSON mode.
- JSONL mode: envelope line has jobs=[], records follow on subsequent
  lines.
- Envelope fields: command, sources_used, sources_failed,
  request_summary.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from job_api_aggregator.envelope import build_envelope, build_jsonl_lines
from job_api_aggregator.schema import JobRecord

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_record(**overrides: Any) -> JobRecord:
    """Return a minimal valid JobRecord for use in envelope tests.

    Args:
        **overrides: Fields to override in the default record.

    Returns:
        A JobRecord dict with sensible defaults.
    """
    base: JobRecord = {
        "source": "stub",
        "source_id": "1",
        "description_source": "snippet",
        "title": "Engineer",
        "url": "https://example.com/1",
        "posted_at": "2026-04-23T12:00:00Z",
        "description": "A job.",
        "company": None,
        "location": None,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_period": None,
        "contract_type": None,
        "contract_time": None,
        "remote_eligible": None,
        "extra": None,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


_DEFAULT_REQUEST_SUMMARY: dict[str, Any] = {
    "hours": 24,
    "query": "python developer",
    "location": "Atlanta, GA",
    "country": None,
    "sources": ["adzuna", "jooble"],
}


# ---------------------------------------------------------------------------
# build_envelope() — structure
# ---------------------------------------------------------------------------


class TestBuildEnvelopeStructure:
    """build_envelope() must produce the §9.2 envelope shape."""

    def test_schema_version_is_1_0(self) -> None:
        """schema_version is always '1.0'."""
        env = build_envelope(
            command="jobs",
            sources_used=["adzuna"],
            sources_failed=[],
            request_summary=_DEFAULT_REQUEST_SUMMARY,
            jobs=[],
        )
        assert env["schema_version"] == "1.0"

    def test_generated_at_is_utc_iso8601(self) -> None:
        """generated_at is a valid UTC ISO-8601 string (ends with 'Z')."""
        env = build_envelope(
            command="jobs",
            sources_used=["adzuna"],
            sources_failed=[],
            request_summary=_DEFAULT_REQUEST_SUMMARY,
            jobs=[],
        )
        generated_at = env["generated_at"]
        assert isinstance(generated_at, str)
        assert generated_at.endswith("Z")
        # Must be parseable as a UTC datetime.
        dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        assert dt.tzinfo == UTC

    def test_command_stored(self) -> None:
        """command field is stored from the argument."""
        env = build_envelope(
            command="hydrate",
            sources_used=[],
            sources_failed=[],
            request_summary=_DEFAULT_REQUEST_SUMMARY,
            jobs=[],
        )
        assert env["command"] == "hydrate"

    def test_sources_used_stored(self) -> None:
        """sources_used list is stored unchanged."""
        env = build_envelope(
            command="jobs",
            sources_used=["adzuna", "jooble"],
            sources_failed=[],
            request_summary=_DEFAULT_REQUEST_SUMMARY,
            jobs=[],
        )
        assert env["sources_used"] == ["adzuna", "jooble"]

    def test_sources_failed_stored(self) -> None:
        """sources_failed list is stored unchanged."""
        env = build_envelope(
            command="jobs",
            sources_used=["adzuna"],
            sources_failed=["jooble"],
            request_summary=_DEFAULT_REQUEST_SUMMARY,
            jobs=[],
        )
        assert env["sources_failed"] == ["jooble"]

    def test_request_summary_stored(self) -> None:
        """request_summary dict is stored unchanged."""
        env = build_envelope(
            command="jobs",
            sources_used=["adzuna"],
            sources_failed=[],
            request_summary=_DEFAULT_REQUEST_SUMMARY,
            jobs=[],
        )
        assert env["request_summary"] == _DEFAULT_REQUEST_SUMMARY

    def test_jobs_list_stored(self) -> None:
        """jobs list is stored in the envelope."""
        records = [_make_record(source_id="1"), _make_record(source_id="2")]
        env = build_envelope(
            command="jobs",
            sources_used=["stub"],
            sources_failed=[],
            request_summary=_DEFAULT_REQUEST_SUMMARY,
            jobs=records,
        )
        assert len(env["jobs"]) == 2
        assert env["jobs"][0]["source_id"] == "1"

    def test_empty_jobs_list(self) -> None:
        """jobs=[] is valid and produces an empty list in the envelope."""
        env = build_envelope(
            command="jobs",
            sources_used=[],
            sources_failed=[],
            request_summary=_DEFAULT_REQUEST_SUMMARY,
            jobs=[],
        )
        assert env["jobs"] == []


# ---------------------------------------------------------------------------
# build_envelope() — JSON serialization
# ---------------------------------------------------------------------------


class TestBuildEnvelopeSerialization:
    """Envelope dicts must survive JSON round-trips."""

    def test_envelope_is_json_serializable(self) -> None:
        """build_envelope() returns a dict that json.dumps handles without
        error."""
        env = build_envelope(
            command="jobs",
            sources_used=["adzuna"],
            sources_failed=[],
            request_summary=_DEFAULT_REQUEST_SUMMARY,
            jobs=[_make_record()],
        )
        serialized = json.dumps(env)
        loaded = json.loads(serialized)
        assert loaded["schema_version"] == "1.0"
        assert len(loaded["jobs"]) == 1

    def test_round_trip_preserves_null_fields(self) -> None:
        """None values in request_summary survive as JSON null."""
        summary = {**_DEFAULT_REQUEST_SUMMARY, "country": None}
        env = build_envelope(
            command="jobs",
            sources_used=["adzuna"],
            sources_failed=[],
            request_summary=summary,
            jobs=[],
        )
        loaded = json.loads(json.dumps(env))
        assert loaded["request_summary"]["country"] is None


# ---------------------------------------------------------------------------
# build_jsonl_lines() — JSONL mode
# ---------------------------------------------------------------------------


class TestBuildJsonlLines:
    """build_jsonl_lines() must yield envelope-line then record-lines."""

    def test_first_line_is_envelope_with_empty_jobs(self) -> None:
        """First line of JSONL output is the envelope with jobs=[]."""
        records = [_make_record(source_id="r1")]
        lines = list(
            build_jsonl_lines(
                command="jobs",
                sources_used=["stub"],
                sources_failed=[],
                request_summary=_DEFAULT_REQUEST_SUMMARY,
                jobs=records,
            )
        )
        assert len(lines) >= 1
        first = json.loads(lines[0])
        assert first["schema_version"] == "1.0"
        assert first["jobs"] == []

    def test_subsequent_lines_are_records(self) -> None:
        """Lines after the first are individual JobRecord dicts."""
        records = [
            _make_record(source_id="r1"),
            _make_record(source_id="r2"),
        ]
        lines = list(
            build_jsonl_lines(
                command="jobs",
                sources_used=["stub"],
                sources_failed=[],
                request_summary=_DEFAULT_REQUEST_SUMMARY,
                jobs=records,
            )
        )
        assert len(lines) == 3  # 1 envelope + 2 records
        rec1 = json.loads(lines[1])
        rec2 = json.loads(lines[2])
        assert rec1["source_id"] == "r1"
        assert rec2["source_id"] == "r2"

    def test_empty_jobs_yields_only_envelope_line(self) -> None:
        """With no records, only the envelope line is produced."""
        lines = list(
            build_jsonl_lines(
                command="jobs",
                sources_used=[],
                sources_failed=[],
                request_summary=_DEFAULT_REQUEST_SUMMARY,
                jobs=[],
            )
        )
        assert len(lines) == 1

    def test_each_line_is_valid_json(self) -> None:
        """Every line produced by build_jsonl_lines() is valid JSON."""
        records = [_make_record(source_id=str(i)) for i in range(3)]
        lines = list(
            build_jsonl_lines(
                command="jobs",
                sources_used=["stub"],
                sources_failed=[],
                request_summary=_DEFAULT_REQUEST_SUMMARY,
                jobs=records,
            )
        )
        for line in lines:
            json.loads(line)  # Must not raise.

    def test_no_trailing_newlines_in_lines(self) -> None:
        """Lines returned by build_jsonl_lines() do not end with newline."""
        lines = list(
            build_jsonl_lines(
                command="jobs",
                sources_used=[],
                sources_failed=[],
                request_summary=_DEFAULT_REQUEST_SUMMARY,
                jobs=[_make_record()],
            )
        )
        for line in lines:
            assert not line.endswith("\n"), f"Line has trailing newline: {line!r}"
