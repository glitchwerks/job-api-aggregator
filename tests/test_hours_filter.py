"""Tests for the --hours post-fetch filter in the orchestrator.

Covers acceptance criteria from issue #54:
- Past-cutoff records are excluded.
- Within-cutoff records are kept.
- Null posted_at records are kept (soft-filter policy).
- Unparseable posted_at records are kept (soft-filter policy).
- request_summary.records_filtered_by_hours is populated.
- Integration test: mocked plugin output spanning the cutoff boundary.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Literal

import pytest

from job_aggregator.base import JobSource
from job_aggregator.schema import SearchParams
from tests.fixtures.plugins.stub_plugins import _make_record

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = UTC


def _utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime.

    Returns:
        Current UTC datetime with tzinfo set.
    """
    return datetime.now(_UTC)


def _iso(dt: datetime) -> str:
    """Format *dt* as an RFC 3339 UTC string.

    Args:
        dt: A timezone-aware UTC datetime.

    Returns:
        ISO 8601 string with 'Z' suffix.
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_hours_record(
    source: str,
    idx: int,
    *,
    posted_at: str | None,
) -> dict[str, Any]:
    """Return a normalise()-compatible record with the given posted_at.

    Args:
        source: Plugin SOURCE key.
        idx: Unique record index.
        posted_at: ISO 8601 timestamp string, or None.

    Returns:
        A minimal dict conforming to the normalise() output contract.
    """
    return _make_record(source, idx, posted_at=posted_at)


def _import_run_jobs() -> Any:
    """Import run_jobs from the orchestrator.

    Returns:
        The ``run_jobs`` callable.
    """
    from job_aggregator.orchestrator import run_jobs

    return run_jobs


# ---------------------------------------------------------------------------
# Stub plugin factory for hours-filter tests
# ---------------------------------------------------------------------------


def _make_hours_plugin(
    records: list[dict[str, Any]],
) -> type[JobSource]:
    """Create a stub plugin class that yields *records* in a single page.

    Args:
        records: The list of pre-normalised dicts to yield.

    Returns:
        A new ``JobSource`` subclass that emits exactly *records*.
    """

    class _HoursStubPlugin(JobSource):
        """Stub plugin for hours-filter tests."""

        SOURCE: ClassVar[str] = "stub_hours"
        DISPLAY_NAME: ClassVar[str] = "Stub Hours"
        DESCRIPTION: ClassVar[str] = "Hours-filter stub."
        HOME_URL: ClassVar[str] = "https://example.com/hours"
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
        RATE_LIMIT_NOTES: ClassVar[str] = "No limit."
        REQUIRED_SEARCH_FIELDS: ClassVar[tuple[str, ...]] = ()

        _records: list[dict[str, Any]] = records

        def __init__(
            self,
            *,
            credentials: dict[str, Any] | None = None,
            search: SearchParams | None = None,
        ) -> None:
            """Initialise; ignore credentials and search.

            Args:
                credentials: Ignored.
                search: Ignored.
            """
            super().__init__(credentials=credentials, search=search)

        @classmethod
        def settings_schema(cls) -> dict[str, Any]:
            """Return empty schema.

            Returns:
                Empty dict.
            """
            return {}

        def pages(self) -> Iterator[list[dict[str, Any]]]:
            """Yield one page containing all pre-set records.

            Yields:
                A single list of normalise()-compatible dicts.
            """
            yield list(self._records)

        def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
            """Return raw unchanged.

            Args:
                raw: The dict yielded by ``pages()``.

            Returns:
                The same dict, unchanged.
            """
            return raw

    return _HoursStubPlugin


# ---------------------------------------------------------------------------
# Unit tests — hours filter behaviour per record
# ---------------------------------------------------------------------------


class TestHoursFilterDropsPastCutoff:
    """Records with parseable posted_at older than cutoff must be dropped."""

    def test_record_older_than_cutoff_is_excluded(self) -> None:
        """A record posted 25 hours ago must not appear with --hours 24."""
        run_jobs = _import_run_jobs()
        now = _utc_now()
        old_posted_at = _iso(now - timedelta(hours=25))
        plugin_cls = _make_hours_plugin(
            [_make_hours_record("stub_hours", 1, posted_at=old_posted_at)]
        )
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format="json",
            hours=24,
            generated_at="2026-01-01T00:00:00Z",
        )
        data = json.loads(result)
        assert len(data["jobs"]) == 0

    def test_record_exactly_at_cutoff_boundary_is_kept(self) -> None:
        """A record posted exactly at the cutoff must be kept (>= semantics).

        The filter drops strictly-before-cutoff records; at-cutoff is kept.
        """
        run_jobs = _import_run_jobs()
        now = _utc_now()
        # Slightly before now so the cutoff is definitely in the past relative
        # to when the filter runs — use 24h - 1s so it lands right on boundary.
        at_cutoff = _iso(now - timedelta(hours=24) + timedelta(seconds=1))
        plugin_cls = _make_hours_plugin([_make_hours_record("stub_hours", 1, posted_at=at_cutoff)])
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format="json",
            hours=24,
            generated_at="2026-01-01T00:00:00Z",
        )
        data = json.loads(result)
        assert len(data["jobs"]) == 1


class TestHoursFilterKeepsWithinCutoff:
    """Records with parseable posted_at within the window must be kept."""

    def test_recent_record_is_kept(self) -> None:
        """A record posted 1 hour ago must appear with --hours 24."""
        run_jobs = _import_run_jobs()
        now = _utc_now()
        recent = _iso(now - timedelta(hours=1))
        plugin_cls = _make_hours_plugin([_make_hours_record("stub_hours", 1, posted_at=recent)])
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format="json",
            hours=24,
            generated_at="2026-01-01T00:00:00Z",
        )
        data = json.loads(result)
        assert len(data["jobs"]) == 1


class TestHoursFilterSoftPolicyNullPostedAt:
    """Records with null posted_at must be retained (soft-filter policy)."""

    def test_null_posted_at_is_kept(self) -> None:
        """A record with posted_at=None must not be dropped by the filter."""
        run_jobs = _import_run_jobs()
        plugin_cls = _make_hours_plugin([_make_hours_record("stub_hours", 1, posted_at=None)])
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format="json",
            hours=24,
            generated_at="2026-01-01T00:00:00Z",
        )
        data = json.loads(result)
        assert len(data["jobs"]) == 1


class TestHoursFilterSoftPolicyUnparseablePostedAt:
    """Records with unparseable posted_at must be retained (soft policy)."""

    def test_unparseable_posted_at_is_kept(self) -> None:
        """A record with an invalid timestamp string must not be dropped."""
        run_jobs = _import_run_jobs()
        plugin_cls = _make_hours_plugin(
            [
                _make_hours_record(
                    "stub_hours",
                    1,
                    posted_at="not-a-date",
                )
            ]
        )
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format="json",
            hours=24,
            generated_at="2026-01-01T00:00:00Z",
        )
        data = json.loads(result)
        assert len(data["jobs"]) == 1

    def test_empty_string_posted_at_is_kept(self) -> None:
        """A record with posted_at='' must not be dropped by the filter."""
        run_jobs = _import_run_jobs()
        plugin_cls = _make_hours_plugin([_make_hours_record("stub_hours", 1, posted_at="")])
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format="json",
            hours=24,
            generated_at="2026-01-01T00:00:00Z",
        )
        data = json.loads(result)
        assert len(data["jobs"]) == 1


# ---------------------------------------------------------------------------
# request_summary.records_filtered_by_hours
# ---------------------------------------------------------------------------


class TestRecordsFilteredByHoursSummary:
    """request_summary must include records_filtered_by_hours count."""

    def test_summary_field_zero_when_nothing_filtered(self) -> None:
        """records_filtered_by_hours must be 0 when all records are recent."""
        run_jobs = _import_run_jobs()
        now = _utc_now()
        recent = _iso(now - timedelta(hours=1))
        plugin_cls = _make_hours_plugin([_make_hours_record("stub_hours", 1, posted_at=recent)])
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format="json",
            hours=24,
            generated_at="2026-01-01T00:00:00Z",
        )
        data = json.loads(result)
        assert data["request_summary"]["records_filtered_by_hours"] == 0

    def test_summary_field_counts_dropped_records(self) -> None:
        """records_filtered_by_hours must count the dropped past-cutoff records."""
        run_jobs = _import_run_jobs()
        now = _utc_now()
        old = _iso(now - timedelta(hours=50))
        recent = _iso(now - timedelta(hours=1))
        plugin_cls = _make_hours_plugin(
            [
                _make_hours_record("stub_hours", 1, posted_at=old),
                _make_hours_record("stub_hours", 2, posted_at=old),
                _make_hours_record("stub_hours", 3, posted_at=recent),
            ]
        )
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format="json",
            hours=24,
            generated_at="2026-01-01T00:00:00Z",
        )
        data = json.loads(result)
        assert data["request_summary"]["records_filtered_by_hours"] == 2
        assert len(data["jobs"]) == 1

    def test_summary_field_present_in_jsonl_envelope(self) -> None:
        """records_filtered_by_hours must also appear in the JSONL envelope."""
        run_jobs = _import_run_jobs()
        now = _utc_now()
        old = _iso(now - timedelta(hours=50))
        plugin_cls = _make_hours_plugin([_make_hours_record("stub_hours", 1, posted_at=old)])
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format="jsonl",
            hours=24,
            generated_at="2026-01-01T00:00:00Z",
        )
        envelope = json.loads(result.strip().splitlines()[0])
        assert "records_filtered_by_hours" in envelope["request_summary"]
        assert envelope["request_summary"]["records_filtered_by_hours"] == 1

    def test_null_records_not_counted_in_filtered(self) -> None:
        """Kept null-posted_at records must not increment the filter count."""
        run_jobs = _import_run_jobs()
        plugin_cls = _make_hours_plugin([_make_hours_record("stub_hours", 1, posted_at=None)])
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format="json",
            hours=24,
            generated_at="2026-01-01T00:00:00Z",
        )
        data = json.loads(result)
        assert data["request_summary"]["records_filtered_by_hours"] == 0


# ---------------------------------------------------------------------------
# Integration test: mocked plugin spanning the cutoff boundary
# ---------------------------------------------------------------------------


class TestHoursFilterIntegration:
    """End-to-end orchestrator run with records spanning the cutoff."""

    def test_mixed_records_only_recent_emitted(self) -> None:
        """Only records within the hours window are emitted end-to-end.

        3 records: 1 recent, 1 old, 1 null posted_at.
        Expected outcome: 2 emitted (recent + null), 1 filtered.
        """
        run_jobs = _import_run_jobs()
        now = _utc_now()
        recent_ts = _iso(now - timedelta(hours=2))
        old_ts = _iso(now - timedelta(hours=48))

        plugin_cls = _make_hours_plugin(
            [
                _make_hours_record("stub_hours", 1, posted_at=recent_ts),
                _make_hours_record("stub_hours", 2, posted_at=old_ts),
                _make_hours_record("stub_hours", 3, posted_at=None),
            ]
        )
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format="json",
            hours=24,
        )
        data = json.loads(result)
        assert len(data["jobs"]) == 2
        assert data["request_summary"]["records_filtered_by_hours"] == 1
        emitted_ids = {j["source_id"] for j in data["jobs"]}
        assert "stub_hours-1" in emitted_ids  # recent → kept
        assert "stub_hours-2" not in emitted_ids  # old → dropped
        assert "stub_hours-3" in emitted_ids  # null → kept

    def test_all_recent_no_records_dropped(self) -> None:
        """All-recent input: zero records filtered, all jobs emitted."""
        run_jobs = _import_run_jobs()
        now = _utc_now()
        plugin_cls = _make_hours_plugin(
            [
                _make_hours_record("stub_hours", i, posted_at=_iso(now - timedelta(hours=i)))
                for i in range(1, 5)
            ]
        )
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format="json",
            hours=168,
        )
        data = json.loads(result)
        assert len(data["jobs"]) == 4
        assert data["request_summary"]["records_filtered_by_hours"] == 0

    def test_all_old_records_none_emitted(self) -> None:
        """All-old input: all records filtered, jobs array is empty."""
        run_jobs = _import_run_jobs()
        now = _utc_now()
        old_ts = _iso(now - timedelta(hours=200))
        plugin_cls = _make_hours_plugin(
            [
                _make_hours_record("stub_hours", 1, posted_at=old_ts),
                _make_hours_record("stub_hours", 2, posted_at=old_ts),
            ]
        )
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format="json",
            hours=24,
        )
        data = json.loads(result)
        assert len(data["jobs"]) == 0
        assert data["request_summary"]["records_filtered_by_hours"] == 2

    @pytest.mark.parametrize("fmt", ["json", "jsonl"])
    def test_filter_count_consistent_across_formats(self, fmt: str) -> None:
        """records_filtered_by_hours must match for both output formats."""
        run_jobs = _import_run_jobs()
        now = _utc_now()
        old_ts = _iso(now - timedelta(hours=50))
        recent_ts = _iso(now - timedelta(hours=1))
        plugin_cls = _make_hours_plugin(
            [
                _make_hours_record("stub_hours", 1, posted_at=old_ts),
                _make_hours_record("stub_hours", 2, posted_at=recent_ts),
            ]
        )
        result = run_jobs(
            plugin_classes={plugin_cls.SOURCE: plugin_cls},
            credentials={},
            format=fmt,
            hours=24,
        )
        if fmt == "json":
            data = json.loads(result)
            summary = data["request_summary"]
        else:
            summary = json.loads(result.strip().splitlines()[0])["request_summary"]
        assert summary["records_filtered_by_hours"] == 1
