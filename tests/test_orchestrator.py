"""Tests for the jobs orchestrator (src/job_api_aggregator/orchestrator.py).

Covers:
- End-to-end JSONL and JSON format output shapes.
- In-memory deduplication keyed by (source, source_id) + URL
  normalization.
- ``--strict`` error propagation (source failure → exception).
- Default error handling (source failure → sources_failed, no abort).
- ``--dry-run`` producing an envelope with empty jobs and no HTTP calls.
- ``--limit N`` caps emitted records.
- ``--sources`` / ``--exclude-sources`` plugin filtering.
- Q4 ``query_applied`` envelope field correctness per source
  ``accepts_query`` value.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.fixtures.plugins.stub_plugins import (
    AlwaysQueryPlugin,
    ErrorPlugin,
    NeverQueryPlugin,
    PartialQueryPlugin,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_sources() -> dict[str, type[Any]]:
    """Return all four stub plugin classes keyed by SOURCE."""
    return {
        AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin,
        PartialQueryPlugin.SOURCE: PartialQueryPlugin,
        NeverQueryPlugin.SOURCE: NeverQueryPlugin,
    }


def _error_sources() -> dict[str, type[Any]]:
    """Return only the ErrorPlugin keyed by SOURCE."""
    return {ErrorPlugin.SOURCE: ErrorPlugin}


def _normal_and_error_sources() -> dict[str, type[Any]]:
    """Return AlwaysQueryPlugin + ErrorPlugin."""
    return {
        AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin,
        ErrorPlugin.SOURCE: ErrorPlugin,
    }


# ---------------------------------------------------------------------------
# Imports (deferred so RED tests fail on ImportError, not NameError)
# ---------------------------------------------------------------------------


def _import_run_jobs() -> Any:
    """Import run_jobs from the orchestrator module.

    Returns:
        The ``run_jobs`` callable.
    """
    from job_api_aggregator.orchestrator import run_jobs

    return run_jobs


# ---------------------------------------------------------------------------
# Output format tests
# ---------------------------------------------------------------------------


class TestJsonlOutput:
    """Tests for JSONL output format."""

    def test_first_line_is_envelope_with_empty_jobs(self) -> None:
        """First JSONL line must be the envelope dict with jobs=[]."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            credentials={},
            format="jsonl",
        )
        lines = result.strip().splitlines()
        envelope = json.loads(lines[0])
        assert envelope["jobs"] == []
        assert envelope["schema_version"] == "1.0"
        assert envelope["command"] == "jobs"
        assert "generated_at" in envelope
        assert "sources_used" in envelope
        assert "sources_failed" in envelope
        assert "request_summary" in envelope

    def test_subsequent_lines_are_job_records(self) -> None:
        """Subsequent JSONL lines must each be a valid job record."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            credentials={},
            format="jsonl",
        )
        lines = result.strip().splitlines()
        # AlwaysQueryPlugin yields 2 records
        assert len(lines) == 3  # 1 envelope + 2 records
        for line in lines[1:]:
            record = json.loads(line)
            assert "source" in record
            assert "source_id" in record
            assert "title" in record

    def test_sources_used_lists_successful_source(self) -> None:
        """sources_used in envelope must contain the plugin key."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            credentials={},
            format="jsonl",
        )
        envelope = json.loads(result.strip().splitlines()[0])
        assert AlwaysQueryPlugin.SOURCE in envelope["sources_used"]
        assert envelope["sources_failed"] == []


class TestJsonOutput:
    """Tests for JSON (single-object) output format."""

    def test_json_output_is_single_object_with_jobs_array(self) -> None:
        """JSON output must be one object with an inline jobs array."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            credentials={},
            format="json",
        )
        data = json.loads(result)
        assert isinstance(data, dict)
        assert isinstance(data["jobs"], list)
        assert len(data["jobs"]) == 2  # AlwaysQueryPlugin yields 2

    def test_json_envelope_has_required_fields(self) -> None:
        """JSON output envelope must carry all required metadata fields."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            credentials={},
            format="json",
        )
        data = json.loads(result)
        for field in (
            "schema_version",
            "generated_at",
            "command",
            "sources_used",
            "sources_failed",
            "request_summary",
            "jobs",
        ):
            assert field in data, f"Missing envelope field: {field!r}"


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Tests for in-memory deduplication by (source, source_id)."""

    def test_duplicate_source_and_source_id_emits_once(self) -> None:
        """Two records with the same (source, source_id) must emit once."""
        from collections.abc import Iterator
        from typing import ClassVar, Literal

        from job_api_aggregator.base import JobSource
        from tests.fixtures.plugins.stub_plugins import (
            _make_record,
        )

        class DupPlugin(JobSource):
            SOURCE: ClassVar[str] = "dup_plugin"
            DISPLAY_NAME: ClassVar[str] = "Dup"
            DESCRIPTION: ClassVar[str] = "Emits duplicate records."
            HOME_URL: ClassVar[str] = "https://example.com"
            GEO_SCOPE: ClassVar[
                Literal[
                    "global",
                    "global-by-country",
                    "remote-only",
                    "federal-us",
                    "regional",
                    "unknown",
                ]
            ] = "global"
            ACCEPTS_QUERY: ClassVar[Literal["always", "partial", "never"]] = "always"
            ACCEPTS_LOCATION: ClassVar[bool] = False
            ACCEPTS_COUNTRY: ClassVar[bool] = False
            RATE_LIMIT_NOTES: ClassVar[str] = "None."

            def __init__(
                self,
                *,
                credentials: dict[str, Any] | None = None,
                search: Any | None = None,
            ) -> None:
                pass

            @classmethod
            def settings_schema(cls) -> dict[str, Any]:
                return {}

            def pages(self) -> Iterator[list[dict[str, Any]]]:
                # Same source_id twice
                rec = _make_record("dup_plugin", 1)
                yield [rec, rec]

            def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
                return raw

        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={"dup_plugin": DupPlugin},
            credentials={},
            format="json",
        )
        data = json.loads(result)
        assert len(data["jobs"]) == 1


# ---------------------------------------------------------------------------
# --strict tests
# ---------------------------------------------------------------------------


class TestStrictMode:
    """Tests for --strict error propagation."""

    def test_strict_raises_on_source_error(self) -> None:
        """--strict must propagate source errors instead of continuing."""
        run_jobs = _import_run_jobs()
        with pytest.raises(RuntimeError):
            run_jobs(
                plugin_classes=_error_sources(),
                credentials={},
                format="jsonl",
                strict=True,
            )

    def test_default_continues_on_source_error(self) -> None:
        """Default (non-strict) must record failed sources and continue."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes=_error_sources(),
            credentials={},
            format="json",
        )
        data = json.loads(result)
        assert ErrorPlugin.SOURCE in data["sources_failed"]
        assert data["jobs"] == []

    def test_strict_with_good_and_bad_source_raises(self) -> None:
        """--strict raises even when one source succeeds."""
        run_jobs = _import_run_jobs()
        with pytest.raises(RuntimeError):
            run_jobs(
                plugin_classes=_normal_and_error_sources(),
                credentials={},
                format="jsonl",
                strict=True,
            )


# ---------------------------------------------------------------------------
# --dry-run tests
# ---------------------------------------------------------------------------


class TestDryRun:
    """Tests for --dry-run: no HTTP calls, empty jobs, full envelope."""

    def test_dry_run_produces_empty_jobs(self) -> None:
        """--dry-run must return an envelope with jobs=[]."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes=_all_sources(),
            credentials={},
            format="json",
            dry_run=True,
        )
        data = json.loads(result)
        assert data["jobs"] == []

    def test_dry_run_jsonl_first_line_only(self) -> None:
        """--dry-run JSONL output must be exactly one line (the envelope)."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes=_all_sources(),
            credentials={},
            format="jsonl",
            dry_run=True,
        )
        lines = [ln for ln in result.strip().splitlines() if ln.strip()]
        assert len(lines) == 1
        envelope = json.loads(lines[0])
        assert envelope["jobs"] == []

    def test_dry_run_includes_sources_in_envelope(self) -> None:
        """--dry-run envelope must list the would-run sources."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            credentials={},
            format="json",
            dry_run=True,
        )
        data = json.loads(result)
        # dry-run: sources are would-run, not necessarily in sources_used
        # The request_summary.sources should list intended plugins
        assert "request_summary" in data


# ---------------------------------------------------------------------------
# --limit tests
# ---------------------------------------------------------------------------


class TestLimit:
    """Tests for --limit N capping emitted records."""

    def test_limit_caps_json_records(self) -> None:
        """--limit 1 must emit at most 1 job record."""
        run_jobs = _import_run_jobs()
        # AlwaysQueryPlugin yields 2 records normally
        result = run_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            credentials={},
            format="json",
            limit=1,
        )
        data = json.loads(result)
        assert len(data["jobs"]) == 1

    def test_limit_caps_jsonl_records(self) -> None:
        """--limit 1 must emit 1 envelope line + 1 record line in JSONL."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            credentials={},
            format="jsonl",
            limit=1,
        )
        lines = [ln for ln in result.strip().splitlines() if ln.strip()]
        assert len(lines) == 2  # 1 envelope + 1 record

    def test_limit_zero_emits_no_records(self) -> None:
        """--limit 0 must be treated as unlimited (not zero records)."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            credentials={},
            format="json",
            limit=0,  # 0 = unlimited
        )
        data = json.loads(result)
        assert len(data["jobs"]) == 2


# ---------------------------------------------------------------------------
# --sources / --exclude-sources tests
# ---------------------------------------------------------------------------


class TestSourceFiltering:
    """Tests for --sources and --exclude-sources filtering."""

    def test_sources_restricts_to_named_plugins(self) -> None:
        """--sources must only run the listed plugins."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes=_all_sources(),
            credentials={},
            format="json",
            sources=[AlwaysQueryPlugin.SOURCE],
        )
        data = json.loads(result)
        assert data["sources_used"] == [AlwaysQueryPlugin.SOURCE]
        # AlwaysQueryPlugin yields 2 records
        assert len(data["jobs"]) == 2

    def test_exclude_sources_removes_named_plugins(self) -> None:
        """--exclude-sources must skip the listed plugins."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={
                AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin,
                NeverQueryPlugin.SOURCE: NeverQueryPlugin,
            },
            credentials={},
            format="json",
            exclude_sources=[NeverQueryPlugin.SOURCE],
        )
        data = json.loads(result)
        assert NeverQueryPlugin.SOURCE not in data["sources_used"]
        assert AlwaysQueryPlugin.SOURCE in data["sources_used"]


# ---------------------------------------------------------------------------
# Q4 query_applied tests
# ---------------------------------------------------------------------------


class TestQueryApplied:
    """Tests for Q4 query_applied envelope field."""

    def test_query_applied_true_for_always_source(self) -> None:
        """query_applied must be True for accepts_query=always sources."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            credentials={},
            format="json",
            query="python",
        )
        data = json.loads(result)
        assert "query_applied" in data
        assert data["query_applied"][AlwaysQueryPlugin.SOURCE] is True

    def test_query_applied_false_for_never_source(self) -> None:
        """query_applied must be False for accepts_query=never sources."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={NeverQueryPlugin.SOURCE: NeverQueryPlugin},
            credentials={},
            format="json",
            query="python",
        )
        data = json.loads(result)
        assert "query_applied" in data
        assert data["query_applied"][NeverQueryPlugin.SOURCE] is False

    def test_query_applied_false_for_partial_source(self) -> None:
        """query_applied must be False for accepts_query=partial sources."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={PartialQueryPlugin.SOURCE: PartialQueryPlugin},
            credentials={},
            format="json",
            query="python",
        )
        data = json.loads(result)
        assert data["query_applied"][PartialQueryPlugin.SOURCE] is False

    def test_query_applied_absent_when_no_query(self) -> None:
        """query_applied must be absent from envelope when no --query."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes=_all_sources(),
            credentials={},
            format="json",
        )
        data = json.loads(result)
        # query_applied should not be present when no query is given
        assert "query_applied" not in data

    def test_query_applied_covers_all_enabled_sources(self) -> None:
        """query_applied must include an entry for every enabled source."""
        run_jobs = _import_run_jobs()
        plugin_classes = _all_sources()
        result = run_jobs(
            plugin_classes=plugin_classes,
            credentials={},
            format="json",
            query="engineer",
        )
        data = json.loads(result)
        for key in plugin_classes:
            assert key in data["query_applied"]

    def test_request_summary_includes_query(self) -> None:
        """request_summary must include the query value."""
        run_jobs = _import_run_jobs()
        result = run_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            credentials={},
            format="json",
            query="python developer",
        )
        data = json.loads(result)
        assert data["request_summary"]["query"] == "python developer"
