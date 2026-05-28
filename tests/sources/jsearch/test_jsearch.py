"""Unit tests for the jsearch plugin.

Tests use synthetic dicts — no network calls.  Each test exercises one
discrete behaviour of the Plugin class or its private helpers.
"""

from __future__ import annotations

import pytest

from job_api_aggregator.errors import CredentialsError
from job_api_aggregator.plugins.jsearch import Plugin
from job_api_aggregator.schema import SearchParams

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plugin(
    query: str = "python developer",
    location: str = "Atlanta, GA",
    max_pages: int = 2,
    api_key: str = "FAKE_KEY",
) -> Plugin:
    """Construct a Plugin instance with minimal valid params."""
    return Plugin(
        credentials={"api_key": api_key},
        search=SearchParams(
            query=query,
            location=location,
            max_pages=max_pages,
        ),
    )


def _raw_job(overrides: dict[str, object] | None = None) -> dict[str, object]:
    """Return a synthetic JSearch raw job dict."""
    base: dict[str, object] = {
        "job_id": "abc123",
        "job_title": "Senior Python Developer",
        "employer_name": "Acme Corp",
        "job_city": "Atlanta",
        "job_state": "GA",
        "job_country": "US",
        "job_location": "Atlanta, GA, US",
        "job_description": "We need a Python wizard.",
        "job_employment_type": "FULLTIME",
        "job_apply_link": "https://acme.example.com/apply/123",
        "job_google_link": "https://www.google.com/search?q=job123",
        "job_posted_at_datetime_utc": "2026-04-01T12:00:00.000Z",
        "job_min_salary": 100_000.0,
        "job_max_salary": 150_000.0,
        "job_salary_period": "YEAR",
    }
    if overrides:
        base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# ClassVar metadata
# ---------------------------------------------------------------------------


class TestClassVarMetadata:
    """Plugin declares all required ClassVar attributes with correct values."""

    def test_source_key(self) -> None:
        assert Plugin.SOURCE == "jsearch"

    def test_display_name(self) -> None:
        assert Plugin.DISPLAY_NAME == "JSearch (RapidAPI)"

    def test_geo_scope(self) -> None:
        assert Plugin.GEO_SCOPE == "global"

    def test_accepts_query(self) -> None:
        assert Plugin.ACCEPTS_QUERY == "always"

    def test_accepts_location(self) -> None:
        assert Plugin.ACCEPTS_LOCATION is True

    def test_accepts_country(self) -> None:
        assert Plugin.ACCEPTS_COUNTRY is False

    def test_rate_limit_notes(self) -> None:
        assert "RapidAPI" in Plugin.RATE_LIMIT_NOTES

    def test_description_is_non_empty(self) -> None:
        assert Plugin.DESCRIPTION

    def test_home_url_points_to_rapidapi(self) -> None:
        assert "rapidapi.com" in Plugin.HOME_URL


# ---------------------------------------------------------------------------
# Constructor / credential handling
# ---------------------------------------------------------------------------


class TestConstructor:
    """Plugin.__init__ validates credentials and stores params."""

    def test_raises_credentials_error_when_api_key_missing(self) -> None:
        with pytest.raises(CredentialsError) as exc_info:
            Plugin(credentials={}, search=SearchParams(query="dev", max_pages=1))
        assert "api_key" in str(exc_info.value)

    def test_raises_credentials_error_when_api_key_empty_string(self) -> None:
        with pytest.raises(CredentialsError):
            Plugin(
                credentials={"api_key": ""},
                search=SearchParams(query="dev", max_pages=1),
            )

    def test_accepts_valid_credentials(self) -> None:
        plugin = _make_plugin()
        assert plugin is not None

    def test_settings_schema_has_api_key_field(self) -> None:
        schema = Plugin.settings_schema()
        assert "api_key" in schema
        assert schema["api_key"]["required"] is True
        assert schema["api_key"]["type"] == "password"


# ---------------------------------------------------------------------------
# normalise() — field mapping
# ---------------------------------------------------------------------------


class TestNormalise:
    """normalise() maps raw JSearch dicts to the JobRecord contract."""

    def setup_method(self) -> None:
        self.plugin = _make_plugin()

    def test_source_field(self) -> None:
        result = self.plugin.normalise(_raw_job())
        assert result["source"] == "jsearch"

    def test_source_id_from_job_id(self) -> None:
        result = self.plugin.normalise(_raw_job())
        assert result["source_id"] == "abc123"

    def test_title_from_job_title(self) -> None:
        result = self.plugin.normalise(_raw_job())
        assert result["title"] == "Senior Python Developer"

    def test_company_from_employer_name(self) -> None:
        result = self.plugin.normalise(_raw_job())
        assert result["company"] == "Acme Corp"

    def test_location_assembled_from_city_state_country(self) -> None:
        result = self.plugin.normalise(_raw_job())
        assert result["location"] == "Atlanta, GA, US"

    def test_location_falls_back_to_job_location(self) -> None:
        raw = _raw_job(
            {
                "job_city": "",
                "job_state": "",
                "job_country": "",
                "job_location": "Remote",
            }
        )
        result = self.plugin.normalise(raw)
        assert result["location"] == "Remote"

    def test_location_none_when_no_location_fields(self) -> None:
        raw = _raw_job(
            {
                "job_city": "",
                "job_state": "",
                "job_country": "",
                "job_location": "",
            }
        )
        result = self.plugin.normalise(raw)
        assert result["location"] is None

    def test_url_prefers_apply_link(self) -> None:
        result = self.plugin.normalise(_raw_job())
        assert result["url"] == "https://acme.example.com/apply/123"

    def test_url_falls_back_to_google_link(self) -> None:
        raw = _raw_job({"job_apply_link": None})
        result = self.plugin.normalise(raw)
        assert result["url"] == "https://www.google.com/search?q=job123"

    def test_url_empty_string_when_no_links(self) -> None:
        raw = _raw_job({"job_apply_link": None, "job_google_link": None})
        result = self.plugin.normalise(raw)
        assert result["url"] == ""

    def test_description_from_job_description(self) -> None:
        result = self.plugin.normalise(_raw_job())
        assert result["description"] == "We need a Python wizard."

    def test_description_source_is_full(self) -> None:
        """JSearch provides full descriptions — description_source must be 'full'."""
        result = self.plugin.normalise(_raw_job())
        assert result["description_source"] == "full"

    def test_posted_at_from_utc_field(self) -> None:
        result = self.plugin.normalise(_raw_job())
        assert result["posted_at"] == "2026-04-01T12:00:00.000Z"

    def test_posted_at_none_when_absent(self) -> None:
        raw = _raw_job({"job_posted_at_datetime_utc": None})
        result = self.plugin.normalise(raw)
        assert result["posted_at"] is None

    def test_salary_min(self) -> None:
        result = self.plugin.normalise(_raw_job())
        assert result["salary_min"] == 100_000.0

    def test_salary_max(self) -> None:
        result = self.plugin.normalise(_raw_job())
        assert result["salary_max"] == 150_000.0

    def test_salary_min_none_when_absent(self) -> None:
        raw = _raw_job({"job_min_salary": None})
        result = self.plugin.normalise(raw)
        assert result["salary_min"] is None

    def test_salary_period_year_maps_to_annual(self) -> None:
        result = self.plugin.normalise(_raw_job())
        assert result["salary_period"] == "annual"

    def test_salary_period_hour_maps_to_hourly(self) -> None:
        raw = _raw_job({"job_salary_period": "HOUR"})
        result = self.plugin.normalise(raw)
        assert result["salary_period"] == "hourly"

    def test_salary_period_month_maps_to_monthly(self) -> None:
        raw = _raw_job({"job_salary_period": "MONTH"})
        result = self.plugin.normalise(raw)
        assert result["salary_period"] == "monthly"

    def test_salary_period_none_when_absent(self) -> None:
        raw = _raw_job({"job_salary_period": None})
        result = self.plugin.normalise(raw)
        assert result["salary_period"] is None

    def test_salary_period_unknown_value_returns_none(self) -> None:
        raw = _raw_job({"job_salary_period": "DECADE"})
        result = self.plugin.normalise(raw)
        assert result["salary_period"] is None

    def test_contract_time_fulltime_maps_to_full_time(self) -> None:
        result = self.plugin.normalise(_raw_job())
        assert result["contract_time"] == "full_time"

    def test_contract_time_parttime_maps_to_part_time(self) -> None:
        raw = _raw_job({"job_employment_type": "PARTTIME"})
        result = self.plugin.normalise(raw)
        assert result["contract_time"] == "part_time"

    def test_contract_time_contractor_maps_to_contract(self) -> None:
        raw = _raw_job({"job_employment_type": "CONTRACTOR"})
        result = self.plugin.normalise(raw)
        assert result["contract_time"] == "contract"

    def test_contract_time_intern_maps_to_intern(self) -> None:
        raw = _raw_job({"job_employment_type": "INTERN"})
        result = self.plugin.normalise(raw)
        assert result["contract_time"] == "intern"

    def test_contract_time_none_when_absent(self) -> None:
        raw = _raw_job({"job_employment_type": None})
        result = self.plugin.normalise(raw)
        assert result["contract_time"] is None

    def test_contract_type_none_always(self) -> None:
        """JSearch has no permanent/contract distinction — always None."""
        result = self.plugin.normalise(_raw_job())
        assert result["contract_type"] is None

    def test_remote_eligible_true_for_remote_jobs_only(self) -> None:
        raw = _raw_job({"job_is_remote": True})
        result = self.plugin.normalise(raw)
        assert result["remote_eligible"] is True

    def test_remote_eligible_false_when_not_remote(self) -> None:
        raw = _raw_job({"job_is_remote": False})
        result = self.plugin.normalise(raw)
        assert result["remote_eligible"] is False

    def test_remote_eligible_none_when_absent(self) -> None:
        raw = _raw_job()
        raw.pop("job_is_remote", None)
        result = self.plugin.normalise(raw)
        assert result["remote_eligible"] is None

    def test_salary_currency_none(self) -> None:
        """JSearch does not expose currency — field must be None."""
        result = self.plugin.normalise(_raw_job())
        assert result["salary_currency"] is None

    def test_extra_is_none(self) -> None:
        result = self.plugin.normalise(_raw_job())
        assert result.get("extra") is None


# ---------------------------------------------------------------------------
# pages() iterator
# ---------------------------------------------------------------------------


class TestPagesIterator:
    """pages() yields deduplicated normalised records per page."""

    def test_pages_returns_iterator(self) -> None:
        import collections.abc

        plugin = _make_plugin()
        assert isinstance(plugin.pages(), collections.abc.Iterator)

    def test_settings_schema_is_class_method(self) -> None:
        """settings_schema must be callable on the class itself, not an instance."""
        schema = Plugin.settings_schema()
        assert isinstance(schema, dict)
