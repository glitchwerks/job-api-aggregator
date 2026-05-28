"""Unit tests for the Adzuna plugin.

Tests use synthetic dicts — no HTTP calls, no VCR.
"""

from __future__ import annotations

import pytest

from job_api_aggregator.plugins.adzuna import Plugin
from job_api_aggregator.schema import SearchParams

# ---------------------------------------------------------------------------
# ClassVar / metadata tests
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    """Verify all required ClassVar attributes are present and well-typed."""

    def test_source_key(self) -> None:
        """SOURCE must be the canonical plugin key."""
        assert Plugin.SOURCE == "adzuna"

    def test_display_name(self) -> None:
        """DISPLAY_NAME must be the human-readable name from source.json."""
        assert Plugin.DISPLAY_NAME == "Adzuna"

    def test_geo_scope(self) -> None:
        """GEO_SCOPE must be 'global-by-country' — API requires a country code."""
        assert Plugin.GEO_SCOPE == "global-by-country"

    def test_accepts_query(self) -> None:
        """ACCEPTS_QUERY must be 'always' — Adzuna passes 'what' to API."""
        assert Plugin.ACCEPTS_QUERY == "always"

    def test_accepts_location(self) -> None:
        """ACCEPTS_LOCATION must be True — 'where' param is supported."""
        assert Plugin.ACCEPTS_LOCATION is True

    def test_accepts_country(self) -> None:
        """ACCEPTS_COUNTRY must be True — country is a required URL segment."""
        assert Plugin.ACCEPTS_COUNTRY is True

    def test_rate_limit_notes_non_empty(self) -> None:
        """RATE_LIMIT_NOTES must be a non-empty string."""
        assert isinstance(Plugin.RATE_LIMIT_NOTES, str)
        assert len(Plugin.RATE_LIMIT_NOTES) > 0

    def test_required_search_fields_contains_country(self) -> None:
        """country must be required — it is part of the URL path."""
        assert "country" in Plugin.REQUIRED_SEARCH_FIELDS

    def test_required_search_fields_contains_query(self) -> None:
        """query must be required — maps to 'what' in the API call."""
        assert "query" in Plugin.REQUIRED_SEARCH_FIELDS

    def test_description_non_empty(self) -> None:
        """DESCRIPTION must be copied verbatim from source.json."""
        assert isinstance(Plugin.DESCRIPTION, str)
        assert len(Plugin.DESCRIPTION) > 0

    def test_home_url(self) -> None:
        """HOME_URL must match source.json."""
        assert Plugin.HOME_URL == "https://www.adzuna.com"


# ---------------------------------------------------------------------------
# settings_schema tests
# ---------------------------------------------------------------------------


class TestSettingsSchema:
    """Verify the credentials schema declares app_id and app_key."""

    def test_schema_has_app_id(self) -> None:
        """settings_schema must declare the app_id field."""
        schema = Plugin.settings_schema()
        assert "app_id" in schema

    def test_schema_has_app_key(self) -> None:
        """settings_schema must declare the app_key field."""
        schema = Plugin.settings_schema()
        assert "app_key" in schema

    def test_app_id_is_required(self) -> None:
        """app_id must be marked required=True."""
        schema = Plugin.settings_schema()
        assert schema["app_id"].get("required") is True

    def test_app_key_is_required(self) -> None:
        """app_key must be marked required=True."""
        schema = Plugin.settings_schema()
        assert schema["app_key"].get("required") is True


# ---------------------------------------------------------------------------
# CredentialsError tests
# ---------------------------------------------------------------------------


class TestCredentialsValidation:
    """Verify CredentialsError is raised for missing credentials."""

    def test_missing_app_id_raises(self) -> None:
        """Plugin must raise CredentialsError when app_id is absent."""
        from job_api_aggregator.errors import CredentialsError

        with pytest.raises(CredentialsError) as exc_info:
            Plugin(credentials={"app_key": "fake_key"})
        assert "app_id" in str(exc_info.value)

    def test_missing_app_key_raises(self) -> None:
        """Plugin must raise CredentialsError when app_key is absent."""
        from job_api_aggregator.errors import CredentialsError

        with pytest.raises(CredentialsError) as exc_info:
            Plugin(credentials={"app_id": "fake_id"})
        assert "app_key" in str(exc_info.value)

    def test_empty_credentials_raises(self) -> None:
        """Plugin must raise CredentialsError when credentials dict is empty."""
        from job_api_aggregator.errors import CredentialsError

        with pytest.raises(CredentialsError):
            Plugin(credentials={})


# ---------------------------------------------------------------------------
# normalise() tests — full field mapping audit
# ---------------------------------------------------------------------------


_RAW_FULL: dict[str, object] = {
    "id": "12345",
    "title": "Python Developer",
    "company": {"display_name": "Acme Corp"},
    "location": {"display_name": "London"},
    "description": "We need a Python wizard.",
    "redirect_url": "https://www.adzuna.com/jobs/12345",
    "created": "2026-04-23T10:00:00Z",
    "salary_min": 60000.0,
    "salary_max": 80000.0,
    "contract_type": "permanent",
    "contract_time": "full_time",
    "salary_is_predicted": "0",
    "category": {"label": "IT Jobs", "tag": "it-jobs"},
    "adref": "ref_abc",
    "latitude": 51.5074,
    "longitude": -0.1278,
}

_RAW_MINIMAL: dict[str, object] = {
    "id": "99",
    "title": "Dev",
    "redirect_url": "https://www.adzuna.com/jobs/99",
    "created": "2026-04-22T08:00:00Z",
}


class TestNormalise:
    """Verify normalise() maps every upstream field correctly."""

    def setup_method(self) -> None:
        """Instantiate plugin with minimal valid credentials."""
        self.plugin = Plugin(
            credentials={"app_id": "fake_id", "app_key": "fake_key"},
            search=SearchParams(query="python", country="gb"),
        )

    def test_source_field(self) -> None:
        """normalise() must set source to the plugin SOURCE key."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["source"] == "adzuna"

    def test_source_id_is_string(self) -> None:
        """normalise() must coerce id to a string for source_id."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["source_id"] == "12345"

    def test_title(self) -> None:
        """normalise() must map title directly."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["title"] == "Python Developer"

    def test_company_from_nested_object(self) -> None:
        """normalise() must extract company.display_name."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["company"] == "Acme Corp"

    def test_location_from_nested_object(self) -> None:
        """normalise() must extract location.display_name."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["location"] == "London"

    def test_description(self) -> None:
        """normalise() must map description directly."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["description"] == "We need a Python wizard."

    def test_url_from_redirect_url(self) -> None:
        """normalise() must map redirect_url to url."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["url"] == "https://www.adzuna.com/jobs/12345"

    def test_posted_at_from_created(self) -> None:
        """normalise() must map created to posted_at."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["posted_at"] == "2026-04-23T10:00:00Z"

    def test_salary_min(self) -> None:
        """normalise() must map salary_min as float."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["salary_min"] == 60000.0

    def test_salary_max(self) -> None:
        """normalise() must map salary_max as float."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["salary_max"] == 80000.0

    def test_salary_currency_is_none(self) -> None:
        """salary_currency must be None — Adzuna does not expose it."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["salary_currency"] is None

    def test_salary_period_is_none(self) -> None:
        """salary_period must be None — Adzuna does not expose a pay-period."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["salary_period"] is None

    def test_contract_type(self) -> None:
        """normalise() must map contract_type directly."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["contract_type"] == "permanent"

    def test_contract_time(self) -> None:
        """normalise() must map contract_time directly."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["contract_time"] == "full_time"

    def test_remote_eligible_is_none(self) -> None:
        """remote_eligible must be None — Adzuna does not expose this."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["remote_eligible"] is None

    def test_description_source_is_snippet(self) -> None:
        """description_source must be 'snippet' — Adzuna returns truncated text."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["description_source"] == "snippet"

    def test_extra_contains_salary_is_predicted(self) -> None:
        """extra blob must include salary_is_predicted (Adzuna-specific field)."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["extra"] is not None
        assert "salary_is_predicted" in result["extra"]

    def test_extra_salary_is_predicted_coerced_to_int(self) -> None:
        """salary_is_predicted must be coerced from string '0' to int 0."""
        result = self.plugin.normalise(_RAW_FULL)
        assert result["extra"]["salary_is_predicted"] == 0

    def test_extra_contains_category(self) -> None:
        """extra blob must include category from Adzuna response."""
        result = self.plugin.normalise(_RAW_FULL)
        assert "category" in result["extra"]

    def test_minimal_record_has_required_fields(self) -> None:
        """normalise() must populate identity/always-present fields even from sparse input."""
        result = self.plugin.normalise(_RAW_MINIMAL)
        for field in ("source", "source_id", "description_source", "title", "url", "description"):
            assert field in result, f"Missing required field: {field}"

    def test_company_none_when_missing(self) -> None:
        """company must be None when the upstream 'company' key is absent."""
        result = self.plugin.normalise(_RAW_MINIMAL)
        assert result.get("company") is None

    def test_location_none_when_missing(self) -> None:
        """location must be None when the upstream 'location' key is absent."""
        result = self.plugin.normalise(_RAW_MINIMAL)
        assert result.get("location") is None

    def test_posted_at_none_when_created_missing(self) -> None:
        """posted_at must be None when the upstream 'created' key is absent."""
        raw_no_date = dict(_RAW_MINIMAL)
        del raw_no_date["created"]
        result = self.plugin.normalise(raw_no_date)
        assert result["posted_at"] is None

    def test_description_empty_string_when_missing(self) -> None:
        """description must be empty string (not None) when absent."""
        result = self.plugin.normalise(_RAW_MINIMAL)
        assert result["description"] == ""

    def test_company_none_when_not_dict(self) -> None:
        """company must be None when value is not a dict (defensive guard)."""
        raw = dict(_RAW_FULL, company="Acme")  # string, not dict
        result = self.plugin.normalise(raw)
        assert result["company"] is None

    def test_location_none_when_not_dict(self) -> None:
        """location must be None when value is not a dict (defensive guard)."""
        raw = dict(_RAW_FULL, location="London")  # string, not dict
        result = self.plugin.normalise(raw)
        assert result["location"] is None

    def test_salary_is_predicted_coerce_invalid_value(self) -> None:
        """salary_is_predicted must default to 0 on unparseable value."""
        raw = dict(_RAW_FULL, salary_is_predicted="bad")
        result = self.plugin.normalise(raw)
        assert result["extra"]["salary_is_predicted"] == 0
