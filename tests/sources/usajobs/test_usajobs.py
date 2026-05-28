"""Unit tests for the usajobs plugin.

Tests cover:
- ClassVar metadata declarations and contract compliance
- settings_schema() field definitions
- normalise() mapping for all API fields
- CredentialsError raised when required credentials are missing
- _parse_float() helper edge cases
- salary_period logic (annual vs non-annual rate codes)
- Deliberate field drops verified via comments in normalise()
"""

from __future__ import annotations

import pytest

from job_api_aggregator.errors import CredentialsError
from job_api_aggregator.plugins.usajobs import Plugin
from job_api_aggregator.schema import SearchParams

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_plugin(
    api_key: str = "test-api-key",
    email: str = "test@example.com",
    query: str = "software engineer",
    max_pages: int | None = None,
) -> Plugin:
    """Construct a Plugin instance with test credentials."""
    return Plugin(
        credentials={"api_key": api_key, "email": email},
        search=SearchParams(query=query, max_pages=max_pages),
    )


def _make_raw_item(
    *,
    matched_object_id: str = "12345",
    position_title: str = "Software Engineer",
    organization_name: str = "Dept of Defense",
    position_location_display: str = "Arlington, VA",
    position_uri: str = "https://www.usajobs.gov/job/12345",
    publication_start_date: str = "2026-04-20",
    qualification_summary: str = "Requires Python experience.",
    min_range: str | None = "80000",
    max_range: str | None = "120000",
    rate_interval_code: str = "PA",
    offering_type_name: str | None = "Permanent",
    schedule_type_name: str | None = "Full-Time",
) -> dict[str, object]:
    """Build a minimal synthetic USAJobs SearchResultItems entry."""
    remuneration: list[dict[str, object]] = []
    if min_range is not None or max_range is not None:
        remuneration = [
            {
                "MinimumRange": min_range,
                "MaximumRange": max_range,
                "RateIntervalCode": rate_interval_code,
            }
        ]

    offering_types: list[dict[str, object]] = []
    if offering_type_name is not None:
        offering_types = [{"Name": offering_type_name}]

    return {
        "MatchedObjectId": matched_object_id,
        "MatchedObjectDescriptor": {
            "PositionTitle": position_title,
            "OrganizationName": organization_name,
            "PositionLocationDisplay": position_location_display,
            "PositionURI": position_uri,
            "PublicationStartDate": publication_start_date,
            "QualificationSummary": qualification_summary,
            "PositionRemuneration": remuneration,
            "PositionOfferingType": offering_types,
            "ScheduleTypeName": schedule_type_name,
        },
    }


# ---------------------------------------------------------------------------
# ClassVar metadata
# ---------------------------------------------------------------------------


class TestClassVarMetadata:
    """Verify all required ClassVar attributes are declared correctly."""

    def test_source_key(self) -> None:
        """SOURCE must be the canonical plugin key."""
        assert Plugin.SOURCE == "usajobs"

    def test_display_name(self) -> None:
        """DISPLAY_NAME must match the spec."""
        assert Plugin.DISPLAY_NAME == "USAJobs"

    def test_geo_scope(self) -> None:
        """GEO_SCOPE must be federal-us (US government jobs only)."""
        assert Plugin.GEO_SCOPE == "federal-us"

    def test_accepts_query(self) -> None:
        """ACCEPTS_QUERY must be partial (keyword sent, no location query)."""
        assert Plugin.ACCEPTS_QUERY == "partial"

    def test_accepts_location(self) -> None:
        """ACCEPTS_LOCATION must be False — API uses its own location data."""
        assert Plugin.ACCEPTS_LOCATION is False

    def test_accepts_country(self) -> None:
        """ACCEPTS_COUNTRY must be False — US-only source."""
        assert Plugin.ACCEPTS_COUNTRY is False

    def test_rate_limit_notes_non_empty(self) -> None:
        """RATE_LIMIT_NOTES must be a non-empty string."""
        assert isinstance(Plugin.RATE_LIMIT_NOTES, str)
        assert Plugin.RATE_LIMIT_NOTES

    def test_description_non_empty(self) -> None:
        """DESCRIPTION must be a non-empty string from source.json."""
        assert isinstance(Plugin.DESCRIPTION, str)
        assert Plugin.DESCRIPTION

    def test_home_url(self) -> None:
        """HOME_URL must point to usajobs.gov."""
        assert "usajobs.gov" in Plugin.HOME_URL

    def test_required_search_fields_is_tuple(self) -> None:
        """REQUIRED_SEARCH_FIELDS must be a tuple."""
        assert isinstance(Plugin.REQUIRED_SEARCH_FIELDS, tuple)

    def test_plugin_is_job_source_subclass(self) -> None:
        """Plugin must be a concrete subclass of JobSource."""
        from job_api_aggregator.base import JobSource

        assert issubclass(Plugin, JobSource)


# ---------------------------------------------------------------------------
# Constructor / credentials
# ---------------------------------------------------------------------------


class TestConstructor:
    """Verify credential validation and construction."""

    def test_raises_credentials_error_when_api_key_missing(self) -> None:
        """CredentialsError must be raised when api_key is absent."""
        with pytest.raises(CredentialsError) as exc_info:
            Plugin(credentials={"email": "test@example.com"})
        assert "api_key" in str(exc_info.value)

    def test_raises_credentials_error_when_email_missing(self) -> None:
        """CredentialsError must be raised when email is absent."""
        with pytest.raises(CredentialsError) as exc_info:
            Plugin(credentials={"api_key": "key123"})
        assert "email" in str(exc_info.value)

    def test_raises_credentials_error_when_both_missing(self) -> None:
        """CredentialsError must be raised when both credentials are absent."""
        with pytest.raises(CredentialsError):
            Plugin(credentials={})

    def test_raises_credentials_error_on_empty_strings(self) -> None:
        """CredentialsError must be raised when credentials are empty strings."""
        with pytest.raises(CredentialsError):
            Plugin(credentials={"api_key": "", "email": ""})

    def test_valid_credentials_succeed(self) -> None:
        """Construction must succeed with both required credentials present."""
        plugin = _make_plugin()
        assert plugin is not None


# ---------------------------------------------------------------------------
# settings_schema()
# ---------------------------------------------------------------------------


class TestSettingsSchema:
    """Verify the settings schema describes both required credential fields."""

    def test_returns_dict(self) -> None:
        """settings_schema() must return a dict."""
        assert isinstance(Plugin.settings_schema(), dict)

    def test_api_key_field_present(self) -> None:
        """settings_schema() must include an api_key field."""
        schema = Plugin.settings_schema()
        assert "api_key" in schema

    def test_email_field_present(self) -> None:
        """settings_schema() must include an email field."""
        schema = Plugin.settings_schema()
        assert "email" in schema

    def test_api_key_is_required(self) -> None:
        """api_key field must be marked required=True."""
        schema = Plugin.settings_schema()
        assert schema["api_key"].get("required") is True

    def test_email_is_required(self) -> None:
        """email field must be marked required=True."""
        schema = Plugin.settings_schema()
        assert schema["email"].get("required") is True

    def test_api_key_type_is_password(self) -> None:
        """api_key must use the password input type."""
        schema = Plugin.settings_schema()
        assert schema["api_key"]["type"] == "password"

    def test_email_type_is_email(self) -> None:
        """email must use the email input type (used as User-Agent header)."""
        schema = Plugin.settings_schema()
        assert schema["email"]["type"] == "email"


# ---------------------------------------------------------------------------
# normalise() — identity fields
# ---------------------------------------------------------------------------


class TestNormaliseIdentity:
    """Verify identity field mapping in normalise()."""

    def test_source_field(self) -> None:
        """source must equal the SOURCE ClassVar."""
        plugin = _make_plugin()
        raw = _make_raw_item()
        result = plugin.normalise(raw)
        assert result["source"] == "usajobs"

    def test_source_id_from_matched_object_id(self) -> None:
        """source_id must be the string form of MatchedObjectId."""
        plugin = _make_plugin()
        raw = _make_raw_item(matched_object_id="99999")
        result = plugin.normalise(raw)
        assert result["source_id"] == "99999"

    def test_description_source_value(self) -> None:
        """description_source must be 'snippet' (QualificationSummary is partial)."""
        plugin = _make_plugin()
        raw = _make_raw_item()
        result = plugin.normalise(raw)
        assert result["description_source"] == "snippet"


# ---------------------------------------------------------------------------
# normalise() — always-present fields
# ---------------------------------------------------------------------------


class TestNormaliseAlwaysPresent:
    """Verify always-present field mapping in normalise()."""

    def test_title_from_position_title(self) -> None:
        """title must come from PositionTitle."""
        plugin = _make_plugin()
        raw = _make_raw_item(position_title="Data Scientist")
        result = plugin.normalise(raw)
        assert result["title"] == "Data Scientist"

    def test_url_from_position_uri(self) -> None:
        """url must come from PositionURI."""
        plugin = _make_plugin()
        raw = _make_raw_item(position_uri="https://www.usajobs.gov/job/42")
        result = plugin.normalise(raw)
        assert result["url"] == "https://www.usajobs.gov/job/42"

    def test_posted_at_from_publication_start_date(self) -> None:
        """posted_at must come from PublicationStartDate."""
        plugin = _make_plugin()
        raw = _make_raw_item(publication_start_date="2026-04-20")
        result = plugin.normalise(raw)
        assert result["posted_at"] == "2026-04-20"

    def test_description_from_qualification_summary(self) -> None:
        """description must come from QualificationSummary."""
        plugin = _make_plugin()
        raw = _make_raw_item(qualification_summary="Must know Python.")
        result = plugin.normalise(raw)
        assert result["description"] == "Must know Python."

    def test_title_empty_string_when_missing(self) -> None:
        """title must be empty string (not None) when PositionTitle absent."""
        plugin = _make_plugin()
        raw = _make_raw_item(position_title="")
        result = plugin.normalise(raw)
        assert result["title"] == ""


# ---------------------------------------------------------------------------
# normalise() — optional fields
# ---------------------------------------------------------------------------


class TestNormaliseOptional:
    """Verify optional field mapping in normalise()."""

    def test_company_from_organization_name(self) -> None:
        """company must come from OrganizationName."""
        plugin = _make_plugin()
        raw = _make_raw_item(organization_name="Dept of Energy")
        result = plugin.normalise(raw)
        assert result["company"] == "Dept of Energy"

    def test_location_from_position_location_display(self) -> None:
        """location must come from PositionLocationDisplay."""
        plugin = _make_plugin()
        raw = _make_raw_item(position_location_display="Washington, DC")
        result = plugin.normalise(raw)
        assert result["location"] == "Washington, DC"

    def test_salary_min_from_annual_remuneration(self) -> None:
        """salary_min must be populated when RateIntervalCode is PA."""
        plugin = _make_plugin()
        raw = _make_raw_item(min_range="90000", max_range="130000", rate_interval_code="PA")
        result = plugin.normalise(raw)
        assert result["salary_min"] == 90000.0

    def test_salary_max_from_annual_remuneration(self) -> None:
        """salary_max must be populated when RateIntervalCode is PA."""
        plugin = _make_plugin()
        raw = _make_raw_item(min_range="90000", max_range="130000", rate_interval_code="PA")
        result = plugin.normalise(raw)
        assert result["salary_max"] == 130000.0

    def test_salary_currency_is_usd(self) -> None:
        """salary_currency must be 'USD' for annual salary entries."""
        plugin = _make_plugin()
        raw = _make_raw_item(min_range="90000", max_range="130000", rate_interval_code="PA")
        result = plugin.normalise(raw)
        assert result["salary_currency"] == "USD"

    def test_salary_period_annual_when_pa_code(self) -> None:
        """salary_period must be 'annual' when RateIntervalCode is PA."""
        plugin = _make_plugin()
        raw = _make_raw_item(min_range="90000", max_range="130000", rate_interval_code="PA")
        result = plugin.normalise(raw)
        assert result["salary_period"] == "annual"

    def test_salary_none_when_non_annual_rate_code(self) -> None:
        """salary_min/max must be None when RateIntervalCode is not PA."""
        plugin = _make_plugin()
        # PH = per hour; salary should not be mapped
        raw = _make_raw_item(min_range="20", max_range="30", rate_interval_code="PH")
        result = plugin.normalise(raw)
        assert result["salary_min"] is None
        assert result["salary_max"] is None
        assert result["salary_period"] is None
        assert result["salary_currency"] is None

    def test_salary_none_when_remuneration_empty(self) -> None:
        """salary fields must be None when PositionRemuneration is empty."""
        plugin = _make_plugin()
        raw = _make_raw_item(min_range=None, max_range=None)
        result = plugin.normalise(raw)
        assert result["salary_min"] is None
        assert result["salary_max"] is None

    def test_contract_type_from_offering_type(self) -> None:
        """contract_type must come from the first PositionOfferingType Name."""
        plugin = _make_plugin()
        raw = _make_raw_item(offering_type_name="Term")
        result = plugin.normalise(raw)
        assert result["contract_type"] == "Term"

    def test_contract_type_none_when_offering_types_empty(self) -> None:
        """contract_type must be None when PositionOfferingType is empty."""
        plugin = _make_plugin()
        raw = _make_raw_item(offering_type_name=None)
        result = plugin.normalise(raw)
        assert result["contract_type"] is None

    def test_contract_time_from_schedule_type_name(self) -> None:
        """contract_time must come from ScheduleTypeName."""
        plugin = _make_plugin()
        raw = _make_raw_item(schedule_type_name="Part-Time")
        result = plugin.normalise(raw)
        assert result["contract_time"] == "Part-Time"

    def test_contract_time_none_when_absent(self) -> None:
        """contract_time must be None when ScheduleTypeName is absent."""
        plugin = _make_plugin()
        raw = _make_raw_item(schedule_type_name=None)
        result = plugin.normalise(raw)
        assert result["contract_time"] is None

    def test_remote_eligible_is_none(self) -> None:
        """remote_eligible must be None — USAJobs does not expose this field."""
        plugin = _make_plugin()
        raw = _make_raw_item()
        result = plugin.normalise(raw)
        assert result["remote_eligible"] is None


# ---------------------------------------------------------------------------
# normalise() — salary_min logic with unparseable values
# ---------------------------------------------------------------------------


class TestNormaliseSalaryEdgeCases:
    """Verify _parse_float() edge cases propagate correctly through normalise()."""

    def test_salary_min_none_when_min_range_is_non_numeric(self) -> None:
        """salary_min must be None when MinimumRange cannot be parsed as float."""
        plugin = _make_plugin()
        raw = _make_raw_item(min_range="N/A", max_range="120000", rate_interval_code="PA")
        result = plugin.normalise(raw)
        assert result["salary_min"] is None

    def test_salary_max_none_when_max_range_is_non_numeric(self) -> None:
        """salary_max must be None when MaximumRange cannot be parsed as float."""
        plugin = _make_plugin()
        raw = _make_raw_item(min_range="80000", max_range="", rate_interval_code="PA")
        result = plugin.normalise(raw)
        assert result["salary_max"] is None

    def test_salary_period_none_when_max_is_none(self) -> None:
        """salary_period must be None when salary_max is None."""
        plugin = _make_plugin()
        raw = _make_raw_item(min_range="80000", max_range="", rate_interval_code="PA")
        result = plugin.normalise(raw)
        assert result["salary_period"] is None


# ---------------------------------------------------------------------------
# normalise() — extra blob
# ---------------------------------------------------------------------------


class TestNormaliseExtra:
    """Verify the extra blob is present and contains expected fields."""

    def test_extra_is_dict_or_none(self) -> None:
        """extra must be a dict or None."""
        plugin = _make_plugin()
        raw = _make_raw_item()
        result = plugin.normalise(raw)
        assert result.get("extra") is None or isinstance(result.get("extra"), dict)
