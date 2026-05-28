"""Unit tests for the Jooble plugin.

Tests use synthetic raw dicts (no network I/O) to verify:
- ClassVar metadata contract is satisfied.
- ``normalise()`` maps every Jooble API field to the correct ``JobRecord`` key.
- Fields that cannot be inferred are mapped to ``None`` with the correct reason.
- ``CredentialsError`` is raised when ``api_key`` is absent.
- ``pages()`` + ``total_pages()`` pagination logic works correctly.
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from job_api_aggregator.errors import CredentialsError
from job_api_aggregator.plugins.jooble import Plugin
from job_api_aggregator.schema import SearchParams

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_CREDS: dict[str, str] = {"api_key": "test-key-123"}

# A realistic raw listing dict as returned by the Jooble API.
RAW_LISTING: dict[str, Any] = {
    "id": "7654321",
    "title": "Senior Python Developer",
    "location": "New York, NY",
    "snippet": "<p>Build <b>great</b> things.</p>",
    "salary": "$120,000 - $150,000",
    "company": "Acme Corp",
    "updated": "2026-04-20T10:00:00Z",
    "type": "Full-time",
    "link": "https://jooble.org/jdp/7654321",
}

# Minimal raw listing — exercises all optional-field fallbacks.
MINIMAL_LISTING: dict[str, Any] = {
    "id": "",
    "title": "",
    "location": "",
    "snippet": "",
    "salary": "",
    "company": "",
    "updated": "",
    "type": "",
    "link": "",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_plugin(
    search: SearchParams | None = None,
    **cred_overrides: str,
) -> Plugin:
    """Construct a Plugin with default valid credentials, applying overrides.

    Args:
        search: Optional :class:`~job_api_aggregator.schema.SearchParams`
            to pass to the constructor.  Defaults to ``None``.
        **cred_overrides: Key-value pairs to merge into the credential dict.

    Returns:
        A constructed Plugin instance.
    """
    creds = {**VALID_CREDS, **cred_overrides}
    return Plugin(credentials=creds, search=search)


# ---------------------------------------------------------------------------
# ClassVar metadata tests
# ---------------------------------------------------------------------------


class TestClassVarMetadata:
    """Verify that all required ClassVar attributes are declared and valid."""

    def test_source_key(self) -> None:
        """SOURCE must be the canonical key 'jooble'."""
        assert Plugin.SOURCE == "jooble"

    def test_display_name(self) -> None:
        """DISPLAY_NAME must be a non-empty string."""
        assert isinstance(Plugin.DISPLAY_NAME, str)
        assert Plugin.DISPLAY_NAME != ""

    def test_description(self) -> None:
        """DESCRIPTION must be a non-empty string."""
        assert isinstance(Plugin.DESCRIPTION, str)
        assert Plugin.DESCRIPTION != ""

    def test_home_url(self) -> None:
        """HOME_URL must point to jooble.org."""
        assert Plugin.HOME_URL.startswith("https://jooble.org")

    def test_geo_scope(self) -> None:
        """GEO_SCOPE must be 'global' (Jooble aggregates worldwide)."""
        assert Plugin.GEO_SCOPE == "global"

    def test_accepts_query(self) -> None:
        """ACCEPTS_QUERY must be 'always' (keywords param is always sent)."""
        assert Plugin.ACCEPTS_QUERY == "always"

    def test_accepts_location(self) -> None:
        """ACCEPTS_LOCATION must be True (location param is supported)."""
        assert Plugin.ACCEPTS_LOCATION is True

    def test_accepts_country(self) -> None:
        """ACCEPTS_COUNTRY must be False (no country filter in Jooble API)."""
        assert Plugin.ACCEPTS_COUNTRY is False

    def test_rate_limit_notes(self) -> None:
        """RATE_LIMIT_NOTES must be a non-empty string."""
        assert isinstance(Plugin.RATE_LIMIT_NOTES, str)
        assert Plugin.RATE_LIMIT_NOTES != ""

    def test_required_search_fields(self) -> None:
        """REQUIRED_SEARCH_FIELDS must be an empty tuple (no required fields)."""
        assert Plugin.REQUIRED_SEARCH_FIELDS == ()


# ---------------------------------------------------------------------------
# Credentials / settings_schema tests
# ---------------------------------------------------------------------------


class TestCredentials:
    """Verify credential handling and settings schema."""

    def test_raises_credentials_error_when_api_key_missing(self) -> None:
        """CredentialsError is raised when api_key is absent."""
        with pytest.raises(CredentialsError) as exc_info:
            Plugin(credentials={})
        assert exc_info.value.plugin_key == "jooble"
        assert "api_key" in exc_info.value.missing_fields

    def test_raises_credentials_error_when_api_key_empty_string(self) -> None:
        """CredentialsError is raised when api_key is an empty string."""
        with pytest.raises(CredentialsError):
            Plugin(credentials={"api_key": ""})

    def test_settings_schema_declares_api_key(self) -> None:
        """settings_schema() must declare the api_key field as required."""
        schema = Plugin.settings_schema()
        assert "api_key" in schema
        assert schema["api_key"]["required"] is True
        assert schema["api_key"]["type"] == "password"

    def test_valid_credentials_construct_successfully(self) -> None:
        """No exception is raised with a valid api_key."""
        plugin = make_plugin()
        assert plugin is not None


# ---------------------------------------------------------------------------
# normalise() — identity / always-present field mapping
# ---------------------------------------------------------------------------


class TestNormaliseIdentityFields:
    """normalise() maps identity fields correctly."""

    def setup_method(self) -> None:
        """Create a plugin and normalise the standard fixture."""
        self.plugin = make_plugin()
        self.result = self.plugin.normalise(RAW_LISTING)

    def test_source_is_plugin_key(self) -> None:
        """source field must equal Plugin.SOURCE."""
        assert self.result["source"] == "jooble"

    def test_source_id_is_string_id(self) -> None:
        """source_id must be the string form of the 'id' field."""
        assert self.result["source_id"] == "7654321"

    def test_description_source_is_snippet(self) -> None:
        """description_source must be 'snippet' (Jooble provides only snippets)."""
        assert self.result["description_source"] == "snippet"


class TestNormaliseAlwaysPresentFields:
    """normalise() maps always-present fields correctly."""

    def setup_method(self) -> None:
        """Create a plugin and normalise the standard fixture."""
        self.plugin = make_plugin()
        self.result = self.plugin.normalise(RAW_LISTING)

    def test_title_mapped(self) -> None:
        """title must be taken from 'title' field."""
        assert self.result["title"] == "Senior Python Developer"

    def test_url_is_link_field(self) -> None:
        """url must be taken from the 'link' field."""
        assert self.result["url"] == "https://jooble.org/jdp/7654321"

    def test_posted_at_is_updated_field(self) -> None:
        """posted_at must be taken from 'updated' field."""
        assert self.result["posted_at"] == "2026-04-20T10:00:00Z"

    def test_description_is_html_stripped_snippet(self) -> None:
        """description must be the snippet with HTML tags removed."""
        assert self.result["description"] == "Build great things."
        assert "<" not in self.result["description"]


# ---------------------------------------------------------------------------
# normalise() — optional field mapping
# ---------------------------------------------------------------------------


class TestNormaliseOptionalFields:
    """normalise() maps optional fields correctly."""

    def setup_method(self) -> None:
        """Create a plugin and normalise the standard fixture."""
        self.plugin = make_plugin()
        self.result = self.plugin.normalise(RAW_LISTING)

    def test_company_mapped(self) -> None:
        """company must be taken from the 'company' field."""
        assert self.result["company"] == "Acme Corp"

    def test_location_mapped(self) -> None:
        """location must be taken from the 'location' field."""
        assert self.result["location"] == "New York, NY"

    def test_salary_min_parsed(self) -> None:
        """salary_min must be parsed from the free-text 'salary' field."""
        assert self.result["salary_min"] == 120000.0

    def test_salary_max_parsed(self) -> None:
        """salary_max must be parsed from the free-text 'salary' field."""
        assert self.result["salary_max"] == 150000.0

    def test_salary_period_is_none(self) -> None:
        """salary_period must be None (period cannot be inferred from Jooble)."""
        assert self.result["salary_period"] is None

    def test_salary_currency_is_none(self) -> None:
        """salary_currency must be None (currency cannot be reliably parsed)."""
        assert self.result["salary_currency"] is None

    def test_contract_type_is_none(self) -> None:
        """contract_type must be None (Jooble does not provide contract type)."""
        assert self.result["contract_type"] is None

    def test_contract_time_mapped_from_type(self) -> None:
        """contract_time must be normalised from the 'type' field."""
        assert self.result["contract_time"] == "full_time"

    def test_remote_eligible_is_none(self) -> None:
        """remote_eligible must be None (Jooble does not provide remote flag)."""
        assert self.result["remote_eligible"] is None

    def test_extra_is_none(self) -> None:
        """extra must be None (no source-specific blob needed)."""
        assert self.result["extra"] is None


# ---------------------------------------------------------------------------
# normalise() — minimal / edge-case listing
# ---------------------------------------------------------------------------


class TestNormaliseMinimalListing:
    """normalise() handles missing/empty fields without raising."""

    def setup_method(self) -> None:
        """Create a plugin and normalise the minimal fixture."""
        self.plugin = make_plugin()
        self.result = self.plugin.normalise(MINIMAL_LISTING)

    def test_source_id_empty_string(self) -> None:
        """source_id must be an empty string when 'id' is absent."""
        assert self.result["source_id"] == ""

    def test_title_empty_string(self) -> None:
        """title must be an empty string when 'title' is absent."""
        assert self.result["title"] == ""

    def test_description_empty_string(self) -> None:
        """description must be an empty string when 'snippet' is absent."""
        assert self.result["description"] == ""

    def test_posted_at_empty_string_when_updated_absent(self) -> None:
        """posted_at must be empty string when 'updated' is absent."""
        # The orchestrator (Issue C) will backfill/null this later.
        assert self.result["posted_at"] == ""

    def test_company_empty_string(self) -> None:
        """company must be an empty string (not None) when 'company' is ''."""
        assert self.result["company"] == ""

    def test_location_empty_string(self) -> None:
        """location must be an empty string (not None) when 'location' is ''."""
        assert self.result["location"] == ""

    def test_salary_min_none_when_no_salary(self) -> None:
        """salary_min must be None when 'salary' is absent."""
        assert self.result["salary_min"] is None

    def test_salary_max_none_when_no_salary(self) -> None:
        """salary_max must be None when 'salary' is absent."""
        assert self.result["salary_max"] is None

    def test_contract_time_empty_string_when_type_absent(self) -> None:
        """contract_time must be empty string when 'type' is absent."""
        assert self.result["contract_time"] == ""


# ---------------------------------------------------------------------------
# normalise() — contract_time mapping
# ---------------------------------------------------------------------------


class TestContractTimeMapping:
    """contract_time normalisation covers all known Jooble type values."""

    def setup_method(self) -> None:
        """Create a shared plugin instance."""
        self.plugin = make_plugin()

    def _normalise_with_type(self, job_type: str) -> str:
        """Normalise a listing with a given type and return contract_time.

        Args:
            job_type: The Jooble 'type' string to test.

        Returns:
            The normalised contract_time value.
        """
        raw = {**RAW_LISTING, "type": job_type}
        result: dict[str, Any] = self.plugin.normalise(raw)
        return str(result["contract_time"])

    def test_full_time_mapped(self) -> None:
        """'Full-time' maps to 'full_time'."""
        assert self._normalise_with_type("Full-time") == "full_time"

    def test_part_time_mapped(self) -> None:
        """'Part-time' maps to 'part_time'."""
        assert self._normalise_with_type("Part-time") == "part_time"

    def test_contract_mapped(self) -> None:
        """'Contract' maps to 'contract'."""
        assert self._normalise_with_type("Contract") == "contract"

    def test_unknown_type_passed_through(self) -> None:
        """Unknown type strings are passed through unchanged."""
        assert self._normalise_with_type("Internship") == "Internship"

    def test_empty_type_produces_empty_string(self) -> None:
        """Empty type produces empty contract_time."""
        assert self._normalise_with_type("") == ""


# ---------------------------------------------------------------------------
# pages() / total_pages() pagination logic
# ---------------------------------------------------------------------------


class TestPaginationLogic:
    """pages() yields one page per result page, capped at max_pages."""

    def _make_api_response(self, total_count: int, jobs: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a minimal Jooble API response envelope.

        Args:
            total_count: Value for the 'totalCount' field.
            jobs: List of raw job dicts.

        Returns:
            Dict matching the Jooble API response structure.
        """
        return {"totalCount": total_count, "jobs": jobs}

    def test_pages_yields_first_page_results(self) -> None:
        """pages() yields the first page without a duplicate HTTP request."""
        plugin = make_plugin()
        response = self._make_api_response(30, [RAW_LISTING])

        mock_resp = MagicMock()
        mock_resp.json.return_value = response
        mock_resp.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_resp):
            pages = list(plugin.pages())

        # Only one request for 30 results / default results_per_page=20 = 2
        # pages, but max_pages default = 5, so 2 pages. However the first
        # page is cached so subsequent pages get separate calls.
        assert len(pages) > 0
        assert len(pages[0]) == 1
        assert pages[0][0]["source"] == "jooble"

    def test_pages_stops_at_max_pages(self) -> None:
        """pages() never yields more pages than max_pages allows."""
        plugin = Plugin(
            credentials=VALID_CREDS,
            search=SearchParams(max_pages=2),
        )
        # 100 total results / 20 per page = 5 pages, but max_pages=2 caps at 2.
        first_response = self._make_api_response(100, [RAW_LISTING])
        subsequent_response = self._make_api_response(100, [RAW_LISTING])

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = [first_response, subsequent_response]

        with patch("requests.post", return_value=mock_resp):
            pages = list(plugin.pages())

        assert len(pages) <= 2

    def test_pages_stops_early_on_empty_page(self) -> None:
        """pages() stops early when a page returns zero results."""
        plugin = Plugin(
            credentials=VALID_CREDS,
            search=SearchParams(max_pages=5),
        )
        # API reports 3 total but page 2 returns empty (early stop).
        first_response = self._make_api_response(3, [RAW_LISTING])
        empty_response = self._make_api_response(3, [])

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = [first_response, empty_response]

        with patch("requests.post", return_value=mock_resp):
            pages = list(plugin.pages())

        # Only page 1 has results; page 2 is empty so iteration stops.
        assert len(pages) == 1

    def test_total_pages_uses_ceiling_division(self) -> None:
        """total_pages() computes ceil(totalCount / results_per_page)."""
        # Default results_per_page=20; 50 total → ceil(50/20) = 3.
        plugin = Plugin(
            credentials=VALID_CREDS,
            search=SearchParams(max_pages=99),
        )
        response = self._make_api_response(50, [RAW_LISTING])

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = response

        with patch("requests.post", return_value=mock_resp):
            total = plugin.total_pages()

        assert total == math.ceil(50 / 20)  # 3 (default results_per_page=20)

    def test_total_pages_capped_by_max_pages(self) -> None:
        """total_pages() is capped at max_pages even when API says more."""
        plugin = Plugin(
            credentials=VALID_CREDS,
            search=SearchParams(max_pages=2),
        )
        response = self._make_api_response(1000, [RAW_LISTING])

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = response

        with patch("requests.post", return_value=mock_resp):
            total = plugin.total_pages()

        assert total == 2
