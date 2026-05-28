"""Tests for the job_api_aggregator.normalizer module.

Covers:
- Round-trip serialization of JobRecord dicts.
- Parametrized description_source truth table (spec §9.6).
- posted_at backfill: provided value kept; missing → created_at; both
  missing → null + stderr warning.
- Empty string vs. null preservation (spec §9.4).
- redirect_url → url rename.
- Fixture-based integration: stub plugin output → normalizer →
  expected JobRecord.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from job_api_aggregator.normalizer import (
    SCRAPE_MIN_LENGTH,
    classify_description_source,
    normalize,
)
from job_api_aggregator.schema import JobRecord

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

LONG_DESCRIPTION = "x" * SCRAPE_MIN_LENGTH
SHORT_DESCRIPTION = "x" * (SCRAPE_MIN_LENGTH - 1)


def _minimal_plugin_output(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid plugin normalise() output dict.

    Contains all identity + always-present fields with sensible defaults.
    Any key in *overrides* replaces the corresponding default.

    Args:
        **overrides: Key-value pairs that override the defaults.

    Returns:
        A dict suitable for passing to :func:`normalize`.
    """
    base: dict[str, Any] = {
        "source": "stub",
        "source_id": "stub-1",
        "title": "Software Engineer",
        "redirect_url": "https://example.com/job/1",
        "posted_at": "2026-04-23T12:00:00Z",
        "description": "A great job.",
        "skip_scrape": False,
        "description_is_full": False,
        # Optional fields absent → should produce None in output
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# normalize() — identity + always-present fields
# ---------------------------------------------------------------------------


class TestNormalizeIdentityFields:
    """normalize() must copy source and source_id into the JobRecord."""

    def test_source_copied(self) -> None:
        """source field is preserved from plugin output."""
        record = normalize(_minimal_plugin_output(source="adzuna"))
        assert record["source"] == "adzuna"

    def test_source_id_copied(self) -> None:
        """source_id field is preserved from plugin output."""
        record = normalize(_minimal_plugin_output(source_id="abc-999"))
        assert record["source_id"] == "abc-999"

    def test_missing_source_raises(self) -> None:
        """normalize() raises ValueError when source is absent."""
        data = _minimal_plugin_output()
        del data["source"]
        with pytest.raises(ValueError, match="source"):
            normalize(data)

    def test_missing_source_id_raises(self) -> None:
        """normalize() raises ValueError when source_id is absent."""
        data = _minimal_plugin_output()
        del data["source_id"]
        with pytest.raises(ValueError, match="source_id"):
            normalize(data)


# ---------------------------------------------------------------------------
# normalize() — redirect_url rename
# ---------------------------------------------------------------------------


class TestNormalizeUrlRename:
    """redirect_url in plugin output must be renamed to url in JobRecord."""

    def test_redirect_url_becomes_url(self) -> None:
        """redirect_url is renamed to url in the output record."""
        record = normalize(_minimal_plugin_output(redirect_url="https://jobs.example.com/1"))
        assert record["url"] == "https://jobs.example.com/1"
        assert "redirect_url" not in record

    def test_url_already_named_url_is_preserved(self) -> None:
        """If plugin outputs 'url' directly (no redirect_url), it is kept."""
        data = _minimal_plugin_output()
        del data["redirect_url"]
        data["url"] = "https://direct.example.com/1"
        record = normalize(data)
        assert record["url"] == "https://direct.example.com/1"

    def test_empty_redirect_url_preserved_as_empty_string(self) -> None:
        """Empty redirect_url becomes empty string url (not None) — §9.4."""
        record = normalize(_minimal_plugin_output(redirect_url=""))
        assert record["url"] == ""


# ---------------------------------------------------------------------------
# normalize() — posted_at backfill
# ---------------------------------------------------------------------------


class TestNormalizePostedAtBackfill:
    """posted_at backfill rules from spec §9.1."""

    def test_posted_at_provided_is_kept(self) -> None:
        """When posted_at is non-empty, it is preserved unchanged."""
        record = normalize(_minimal_plugin_output(posted_at="2026-04-23T12:00:00Z"))
        assert record["posted_at"] == "2026-04-23T12:00:00Z"

    def test_missing_posted_at_backfills_from_created_at(self) -> None:
        """When posted_at is absent, created_at is used as posted_at."""
        data = _minimal_plugin_output()
        del data["posted_at"]
        data["created_at"] = "2026-04-01T08:00:00Z"
        record = normalize(data)
        assert record["posted_at"] == "2026-04-01T08:00:00Z"

    def test_none_posted_at_backfills_from_created_at(self) -> None:
        """When posted_at is explicitly None, created_at is used."""
        data = _minimal_plugin_output(posted_at=None)
        data["created_at"] = "2026-04-01T08:00:00Z"
        record = normalize(data)
        assert record["posted_at"] == "2026-04-01T08:00:00Z"

    def test_both_missing_yields_none_and_warns_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When both posted_at and created_at are absent, posted_at is None
        and a warning is printed to stderr."""
        data = _minimal_plugin_output()
        del data["posted_at"]
        record = normalize(data)
        assert record["posted_at"] is None
        captured = capsys.readouterr()
        assert captured.err != ""

    def test_both_none_yields_none_and_warns_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When both posted_at=None and created_at=None, result is None
        with a warning on stderr."""
        data = _minimal_plugin_output(posted_at=None)
        data["created_at"] = None
        record = normalize(data)
        assert record["posted_at"] is None
        captured = capsys.readouterr()
        assert captured.err != ""


# ---------------------------------------------------------------------------
# normalize() — empty string vs null preservation (§9.4)
# ---------------------------------------------------------------------------


class TestNormalizeEmptyVsNull:
    """Empty string and None must round-trip correctly per §9.4."""

    def test_empty_string_title_preserved(self) -> None:
        """Empty string title is preserved as empty string, not None."""
        record = normalize(_minimal_plugin_output(title=""))
        assert record["title"] == ""

    def test_empty_string_description_preserved(self) -> None:
        """Empty string description is preserved as empty string, not None."""
        record = normalize(_minimal_plugin_output(description=""))
        assert record["description"] == ""

    def test_absent_company_becomes_none(self) -> None:
        """Absent company key in plugin output → None in JobRecord."""
        data = _minimal_plugin_output()
        # company not in data at all
        record = normalize(data)
        assert record["company"] is None

    def test_none_company_stays_none(self) -> None:
        """Explicit None company in plugin output → None in JobRecord."""
        record = normalize(_minimal_plugin_output(company=None))
        assert record["company"] is None

    def test_empty_string_company_preserved(self) -> None:
        """Empty string company is preserved as empty string, not None."""
        record = normalize(_minimal_plugin_output(company=""))
        assert record["company"] == ""

    def test_real_company_preserved(self) -> None:
        """Non-empty company value is passed through unchanged."""
        record = normalize(_minimal_plugin_output(company="Acme Corp"))
        assert record["company"] == "Acme Corp"

    def test_absent_location_becomes_none(self) -> None:
        """Absent location key → None in JobRecord."""
        data = _minimal_plugin_output()
        record = normalize(data)
        assert record["location"] is None

    def test_empty_string_location_preserved(self) -> None:
        """Empty string location is preserved, not coerced to None."""
        record = normalize(_minimal_plugin_output(location=""))
        assert record["location"] == ""


# ---------------------------------------------------------------------------
# normalize() — optional numeric / bool fields
# ---------------------------------------------------------------------------


class TestNormalizeOptionalFields:
    """Optional fields absent from plugin output default to None."""

    def test_salary_min_defaults_to_none(self) -> None:
        """salary_min is None when not in plugin output."""
        record = normalize(_minimal_plugin_output())
        assert record["salary_min"] is None

    def test_salary_max_defaults_to_none(self) -> None:
        """salary_max is None when not in plugin output."""
        record = normalize(_minimal_plugin_output())
        assert record["salary_max"] is None

    def test_salary_currency_defaults_to_none(self) -> None:
        """salary_currency is None when not in plugin output."""
        record = normalize(_minimal_plugin_output())
        assert record["salary_currency"] is None

    def test_salary_period_defaults_to_none(self) -> None:
        """salary_period is None when not in plugin output."""
        record = normalize(_minimal_plugin_output())
        assert record["salary_period"] is None

    def test_remote_eligible_defaults_to_none(self) -> None:
        """remote_eligible is None when not in plugin output."""
        record = normalize(_minimal_plugin_output())
        assert record["remote_eligible"] is None

    def test_salary_values_passed_through(self) -> None:
        """Numeric salary values are copied into the record."""
        record = normalize(
            _minimal_plugin_output(
                salary_min=50000.0,
                salary_max=80000.0,
                salary_currency="USD",
                salary_period="annual",
            )
        )
        assert record["salary_min"] == 50000.0
        assert record["salary_max"] == 80000.0
        assert record["salary_currency"] == "USD"
        assert record["salary_period"] == "annual"

    def test_remote_eligible_true_passed_through(self) -> None:
        """remote_eligible=True is copied into the record."""
        record = normalize(_minimal_plugin_output(remote_eligible=True))
        assert record["remote_eligible"] is True


# ---------------------------------------------------------------------------
# normalize() — extra blob assembly
# ---------------------------------------------------------------------------


class TestNormalizeExtraBlob:
    """extra blob must be scoped under extra.<plugin_key>.*."""

    def test_no_extra_in_plugin_output_yields_none(self) -> None:
        """When plugin output has no 'extra' key, extra is None."""
        data = _minimal_plugin_output()
        record = normalize(data)
        assert record["extra"] is None

    def test_extra_none_in_plugin_output_yields_none(self) -> None:
        """When plugin output has extra=None, extra is None."""
        record = normalize(_minimal_plugin_output(extra=None))
        assert record["extra"] is None

    def test_extra_dict_scoped_under_plugin_key(self) -> None:
        """A non-empty extra dict is scoped as extra[source][...] in output."""
        record = normalize(
            _minimal_plugin_output(
                source="adzuna",
                extra={"category": "IT Jobs", "adref": "ref123"},
            )
        )
        assert record["extra"] == {"adzuna": {"category": "IT Jobs", "adref": "ref123"}}

    def test_extra_already_scoped_is_not_double_scoped(self) -> None:
        """If plugin outputs extra already keyed by source, it is not
        double-wrapped — raw extra dict is always re-scoped."""
        record = normalize(
            _minimal_plugin_output(
                source="stub",
                extra={"field": "value"},
            )
        )
        assert record["extra"] == {"stub": {"field": "value"}}


# ---------------------------------------------------------------------------
# classify_description_source() — §9.6 truth table (jobs orchestrator rows)
# ---------------------------------------------------------------------------


class TestClassifyDescriptionSource:
    """Parametrized truth table for the 'jobs' orchestrator (spec §9.6).

    The five rows of the jobs-orchestrator portion of the §9.6 table:

    Row | skip_scrape | description_is_full | len >= MIN | Result
    ----+-------------+--------------------+-----------+--------
    1   | True        | True               | True      | "full"
    2   | True        | True               | False     | "snippet"
    3   | True        | False              | n/a       | "snippet"
    4   | False       | n/a                | n/a       | "snippet"
    5   | n/a         | n/a                | empty     | "none"
    """

    @pytest.mark.parametrize(
        "skip_scrape,description_is_full,description,expected",
        [
            # Row 1: skip_scrape=T, is_full=T, long → "full"
            (True, True, LONG_DESCRIPTION, "full"),
            # Row 2: skip_scrape=T, is_full=T, short → "snippet"
            (True, True, SHORT_DESCRIPTION, "snippet"),
            # Row 3: skip_scrape=T, is_full=F → "snippet" (non-empty)
            (True, False, LONG_DESCRIPTION, "snippet"),
            (True, False, SHORT_DESCRIPTION, "snippet"),
            # Row 4: skip_scrape=F → "snippet" (non-empty)
            (False, True, LONG_DESCRIPTION, "snippet"),
            (False, False, LONG_DESCRIPTION, "snippet"),
            (False, True, SHORT_DESCRIPTION, "snippet"),
            # Row 5: empty description → "none" regardless of all other flags.
            # This is a terminal override that must fire before rows 3 and 4.
            (True, True, "", "none"),
            (True, False, "", "none"),
            (False, True, "", "none"),
            (False, False, "", "none"),
        ],
        ids=[
            "skip_full_long→full",
            "skip_full_short→snippet",
            "skip_notfull_long→snippet",
            "skip_notfull_short→snippet",
            "noscrape_full_long→snippet",
            "noscrape_notfull_long→snippet",
            "noscrape_full_short→snippet",
            "empty_skip_full→none",
            "empty_skip_notfull→none",
            "empty_noscrape_full→none",
            "empty_noscrape_notfull→none",
        ],
    )
    def test_classify_description_source(
        self,
        skip_scrape: bool,
        description_is_full: bool,
        description: str,
        expected: str,
    ) -> None:
        """classify_description_source returns expected value for each row."""
        result = classify_description_source(
            skip_scrape=skip_scrape,
            description_is_full=description_is_full,
            description=description,
        )
        assert result == expected

    def test_empty_description_any_flags_yields_none(self) -> None:
        """Empty description is a terminal override — always yields 'none'.

        Row 5 of §9.6 fires unconditionally before rows 1-4 when
        description == '', regardless of skip_scrape and description_is_full.
        """
        for skip_scrape in (True, False):
            for description_is_full in (True, False):
                result = classify_description_source(
                    skip_scrape=skip_scrape,
                    description_is_full=description_is_full,
                    description="",
                )
                assert result == "none", (
                    f"Expected 'none' for skip_scrape={skip_scrape}, "
                    f"description_is_full={description_is_full}, description=''"
                )


# ---------------------------------------------------------------------------
# normalize() — description_source set correctly via classify
# ---------------------------------------------------------------------------


class TestNormalizeDescriptionSource:
    """normalize() must call classify_description_source and store result."""

    def test_description_source_snippet_when_no_skip_scrape(self) -> None:
        """skip_scrape=False produces description_source='snippet'."""
        record = normalize(
            _minimal_plugin_output(
                skip_scrape=False,
                description_is_full=True,
                description=LONG_DESCRIPTION,
            )
        )
        assert record["description_source"] == "snippet"

    def test_description_source_full_when_skip_full_long(self) -> None:
        """skip_scrape=True, is_full=True, long description → 'full'."""
        record = normalize(
            _minimal_plugin_output(
                skip_scrape=True,
                description_is_full=True,
                description=LONG_DESCRIPTION,
            )
        )
        assert record["description_source"] == "full"

    def test_description_source_none_when_empty_description_skip_full(self) -> None:
        """Empty description with skip_scrape=True, is_full=True → 'none'."""
        record = normalize(
            _minimal_plugin_output(
                skip_scrape=True,
                description_is_full=True,
                description="",
            )
        )
        assert record["description_source"] == "none"

    def test_description_source_none_when_empty_description_no_skip(self) -> None:
        """Empty description with skip_scrape=False → 'none' (row-5 override).

        Previously returned 'snippet' because row 4 fired first. Row 5 must
        be checked before rows 1-4 per the corrected spec interpretation.
        """
        record = normalize(
            _minimal_plugin_output(
                skip_scrape=False,
                description_is_full=False,
                description="",
            )
        )
        assert record["description_source"] == "none"

    def test_description_source_none_when_empty_description_skip_notfull(self) -> None:
        """Empty description with skip_scrape=True, is_full=False → 'none'."""
        record = normalize(
            _minimal_plugin_output(
                skip_scrape=True,
                description_is_full=False,
                description="",
            )
        )
        assert record["description_source"] == "none"


# ---------------------------------------------------------------------------
# Round-trip serialization
# ---------------------------------------------------------------------------


class TestJobRecordSerialization:
    """JobRecord dicts must survive JSON round-trips without data loss."""

    def test_round_trip_minimal_record(self) -> None:
        """A minimal JobRecord survives json.dumps / json.loads unchanged."""
        record = normalize(_minimal_plugin_output())
        serialized = json.dumps(record)
        loaded: dict[str, Any] = json.loads(serialized)
        # All required fields present after round-trip.
        assert loaded["source"] == record["source"]
        assert loaded["source_id"] == record["source_id"]
        assert loaded["description_source"] == record["description_source"]
        assert loaded["title"] == record["title"]
        assert loaded["url"] == record["url"]
        assert loaded["description"] == record["description"]

    def test_round_trip_preserves_none_fields(self) -> None:
        """None values are preserved as JSON null → Python None."""
        record = normalize(_minimal_plugin_output())
        loaded: dict[str, Any] = json.loads(json.dumps(record))
        assert loaded["posted_at"] == record["posted_at"]
        assert loaded["company"] is None
        assert loaded["salary_min"] is None

    def test_round_trip_preserves_extra_blob(self) -> None:
        """extra blob survives JSON round-trip with source scoping."""
        record = normalize(
            _minimal_plugin_output(
                source="adzuna",
                extra={"category": "IT Jobs"},
            )
        )
        loaded: dict[str, Any] = json.loads(json.dumps(record))
        assert loaded["extra"] == {"adzuna": {"category": "IT Jobs"}}

    def test_round_trip_preserves_empty_strings(self) -> None:
        """Empty strings are preserved through JSON serialization (not None)."""
        record = normalize(_minimal_plugin_output(title="", description="", url=""))
        loaded: dict[str, Any] = json.loads(json.dumps(record))
        assert loaded["title"] == ""
        assert loaded["description"] == ""
        assert loaded["url"] == ""


# ---------------------------------------------------------------------------
# Fixture-based integration: stub plugin output → normalize → JobRecord
# ---------------------------------------------------------------------------


class TestNormalizeIntegration:
    """Integration tests using representative plugin-style output dicts."""

    def test_adzuna_style_output(self) -> None:
        """Adzuna-style plugin output (redirect_url, created, extra) normalizes
        correctly."""
        plugin_output: dict[str, Any] = {
            "source": "adzuna",
            "source_id": "12345678",
            "title": "Python Developer",
            "redirect_url": "https://adzuna.com/jobs/1",
            "posted_at": "2026-04-20T10:00:00Z",
            "description": "Write Python code.",
            "company": "Tech Corp",
            "location": "London, UK",
            "salary_min": 60000.0,
            "salary_max": 80000.0,
            "salary_currency": None,
            "salary_period": None,
            "contract_type": "permanent",
            "contract_time": "full_time",
            "remote_eligible": None,
            "skip_scrape": False,
            "description_is_full": False,
            "extra": {"category": {"label": "IT Jobs"}, "adref": "xyzabc"},
        }
        record: JobRecord = normalize(plugin_output)
        assert record["source"] == "adzuna"
        assert record["source_id"] == "12345678"
        assert record["url"] == "https://adzuna.com/jobs/1"
        assert record["posted_at"] == "2026-04-20T10:00:00Z"
        assert record["description_source"] == "snippet"
        assert record["extra"] == {"adzuna": {"category": {"label": "IT Jobs"}, "adref": "xyzabc"}}

    def test_remoteok_style_output_no_posted_at(self) -> None:
        """RemoteOK-style output (no posted_at, has created_at) backfills
        posted_at from created_at."""
        plugin_output: dict[str, Any] = {
            "source": "remoteok",
            "source_id": "remoteok-7890",
            "title": "Senior Engineer",
            "redirect_url": "https://remoteok.com/job/7890",
            "description": "Remote job.",
            "created_at": "2026-04-18T00:00:00Z",
            "skip_scrape": False,
            "description_is_full": False,
        }
        record: JobRecord = normalize(plugin_output)
        assert record["posted_at"] == "2026-04-18T00:00:00Z"
        assert record["url"] == "https://remoteok.com/job/7890"

    def test_plugin_with_full_description_no_scrape(self) -> None:
        """Plugin with skip_scrape=True + is_full=True + long desc → 'full'."""
        plugin_output: dict[str, Any] = {
            "source": "himalayas",
            "source_id": "him-001",
            "title": "Staff Engineer",
            "redirect_url": "https://himalayas.app/job/001",
            "description": LONG_DESCRIPTION,
            "posted_at": "2026-04-22T00:00:00Z",
            "skip_scrape": True,
            "description_is_full": True,
        }
        record: JobRecord = normalize(plugin_output)
        assert record["description_source"] == "full"

    def test_output_contains_all_required_keys(self) -> None:
        """normalize() always produces a record with every required key."""
        record = normalize(_minimal_plugin_output())
        required_keys = (
            "source",
            "source_id",
            "description_source",
            "title",
            "url",
            "posted_at",
            "description",
            "company",
            "location",
            "salary_min",
            "salary_max",
            "salary_currency",
            "salary_period",
            "contract_type",
            "contract_time",
            "remote_eligible",
            "extra",
        )
        for key in required_keys:
            assert key in record, f"Key '{key}' missing from normalized record"
