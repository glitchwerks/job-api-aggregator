"""Unit tests for the arbeitnow plugin.

Tests cover:
- ClassVar metadata presence and correct values
- settings_schema() returns an empty dict (no credentials required)
- normalise() field mapping for all documented fields
- normalise() HTML stripping from description
- normalise() location resolution (explicit vs. remote fallback)
- normalise() contract_time normalisation (_CONTRACT_TIME_MAP)
- normalise() Unix timestamp → ISO 8601 conversion
- normalise() graceful handling of missing / None fields
- pages() yields raw listing dicts (no double-normalisation)

All tests use synthetic dicts — no network I/O.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from job_api_aggregator.plugins.arbeitnow import Plugin
from job_api_aggregator.schema import SearchParams

# ---------------------------------------------------------------------------
# Fixtures: synthetic raw listing dicts
# ---------------------------------------------------------------------------

FULL_RAW: dict[str, Any] = {
    "slug": "senior-python-engineer-acme-12345",
    "title": "Senior Python Engineer",
    "company_name": "Acme GmbH",
    "location": "Berlin, Germany",
    "remote": False,
    "job_types": ["full-time permanent"],
    "description": "<p>We are looking for a <strong>Python</strong> engineer.</p>",
    "url": "https://www.arbeitnow.com/jobs/acme/senior-python-engineer-12345",
    "created_at": 1700000000,
    "tags": ["python", "backend"],
    "language": "en",
    "visa_sponsorship": False,
}

REMOTE_RAW: dict[str, Any] = {
    "slug": "remote-dev-456",
    "title": "Remote Developer",
    "company_name": "Fully Remote Corp",
    "location": "",
    "remote": True,
    "job_types": ["berufserfahren"],
    "description": "<p>Work from anywhere.</p>",
    "url": "https://www.arbeitnow.com/jobs/remote-dev-456",
    "created_at": 1700001000,
    "tags": [],
    "language": "en",
    "visa_sponsorship": True,
}

MINIMAL_RAW: dict[str, Any] = {
    "slug": "minimal-job-789",
    "title": "Minimal Job",
}


# ---------------------------------------------------------------------------
# ClassVar metadata
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    """Plugin class-level metadata is correctly declared."""

    def test_source_key(self) -> None:
        """SOURCE equals 'arbeitnow'."""
        assert Plugin.SOURCE == "arbeitnow"

    def test_display_name(self) -> None:
        """DISPLAY_NAME is 'Arbeitnow'."""
        assert Plugin.DISPLAY_NAME == "Arbeitnow"

    def test_description_non_empty(self) -> None:
        """DESCRIPTION is a non-empty string."""
        assert isinstance(Plugin.DESCRIPTION, str)
        assert Plugin.DESCRIPTION.strip()

    def test_home_url(self) -> None:
        """HOME_URL points to arbeitnow.com."""
        assert Plugin.HOME_URL == "https://www.arbeitnow.com"

    def test_geo_scope(self) -> None:
        """GEO_SCOPE is 'regional' (EU-focused board, not remote-only)."""
        assert Plugin.GEO_SCOPE == "regional"

    def test_accepts_query_never(self) -> None:
        """ACCEPTS_QUERY is 'never' — API has no free-text query parameter."""
        assert Plugin.ACCEPTS_QUERY == "never"

    def test_accepts_location_false(self) -> None:
        """ACCEPTS_LOCATION is False — API does not filter by location."""
        assert Plugin.ACCEPTS_LOCATION is False

    def test_accepts_country_false(self) -> None:
        """ACCEPTS_COUNTRY is False — API does not accept a country filter."""
        assert Plugin.ACCEPTS_COUNTRY is False

    def test_rate_limit_notes_non_empty(self) -> None:
        """RATE_LIMIT_NOTES is a non-empty string."""
        assert isinstance(Plugin.RATE_LIMIT_NOTES, str)
        assert Plugin.RATE_LIMIT_NOTES.strip()

    def test_required_search_fields_empty(self) -> None:
        """REQUIRED_SEARCH_FIELDS is empty — no fields are required."""
        assert Plugin.REQUIRED_SEARCH_FIELDS == ()

    def test_plugin_is_job_source_subclass(self) -> None:
        """Plugin subclasses JobSource (ABC contract enforced at import)."""
        from job_api_aggregator.base import JobSource

        assert issubclass(Plugin, JobSource)


# ---------------------------------------------------------------------------
# settings_schema
# ---------------------------------------------------------------------------


class TestSettingsSchema:
    """settings_schema() returns an empty dict (no credentials required)."""

    def test_returns_empty_dict(self) -> None:
        """settings_schema() returns {}."""
        assert Plugin.settings_schema() == {}


# ---------------------------------------------------------------------------
# normalise() — field mapping
# ---------------------------------------------------------------------------


class TestNormaliseFieldMapping:
    """normalise() maps raw Arbeitnow fields to JobRecord fields."""

    def setup_method(self) -> None:
        """Create a plugin instance shared by all mapping tests."""
        self.plugin = Plugin()

    def test_source_field(self) -> None:
        """source is always 'arbeitnow'."""
        result = self.plugin.normalise(FULL_RAW)
        assert result["source"] == "arbeitnow"

    def test_source_id_from_slug(self) -> None:
        """source_id maps from slug."""
        result = self.plugin.normalise(FULL_RAW)
        assert result["source_id"] == "senior-python-engineer-acme-12345"

    def test_title_mapping(self) -> None:
        """title maps from title."""
        result = self.plugin.normalise(FULL_RAW)
        assert result["title"] == "Senior Python Engineer"

    def test_company_mapping(self) -> None:
        """company maps from company_name."""
        result = self.plugin.normalise(FULL_RAW)
        assert result["company"] == "Acme GmbH"

    def test_url_mapping(self) -> None:
        """url maps from url field."""
        result = self.plugin.normalise(FULL_RAW)
        assert result["url"] == FULL_RAW["url"]

    def test_posted_at_iso8601(self) -> None:
        """posted_at converts Unix timestamp to ISO 8601 UTC string."""
        result = self.plugin.normalise(FULL_RAW)
        # 1700000000 → 2023-11-14T22:13:20Z
        assert result["posted_at"] == "2023-11-14T22:13:20Z"

    def test_description_source_full(self) -> None:
        """description_source is 'full' when description is non-empty."""
        result = self.plugin.normalise(FULL_RAW)
        assert result["description_source"] == "full"

    def test_description_html_stripped(self) -> None:
        """description has HTML tags removed."""
        result = self.plugin.normalise(FULL_RAW)
        assert "<p>" not in result["description"]
        assert "<strong>" not in result["description"]
        assert "Python" in result["description"]

    def test_salary_fields_none(self) -> None:
        """salary_min, salary_max, salary_currency, salary_period are None
        because Arbeitnow does not expose salary data.
        """
        result = self.plugin.normalise(FULL_RAW)
        assert result["salary_min"] is None
        assert result["salary_max"] is None
        assert result["salary_currency"] is None
        assert result["salary_period"] is None

    def test_contract_type_none(self) -> None:
        """contract_type is always None — Arbeitnow has no contract_type field."""
        result = self.plugin.normalise(FULL_RAW)
        assert result["contract_type"] is None

    def test_remote_eligible_from_remote_flag(self) -> None:
        """remote_eligible maps from the remote boolean field."""
        result = self.plugin.normalise(FULL_RAW)
        assert result["remote_eligible"] is False

        result_remote = self.plugin.normalise(REMOTE_RAW)
        assert result_remote["remote_eligible"] is True

    def test_extra_contains_tags(self) -> None:
        """extra dict preserves tags and other non-mapped fields."""
        result = self.plugin.normalise(FULL_RAW)
        assert result["extra"] is not None
        assert result["extra"]["tags"] == ["python", "backend"]

    def test_extra_contains_visa_sponsorship(self) -> None:
        """extra dict preserves visa_sponsorship."""
        result = self.plugin.normalise(FULL_RAW)
        assert result["extra"]["visa_sponsorship"] is False


# ---------------------------------------------------------------------------
# normalise() — location resolution
# ---------------------------------------------------------------------------


class TestNormaliseLocation:
    """normalise() resolves location with explicit value and remote fallback."""

    def setup_method(self) -> None:
        """Create a plugin instance."""
        self.plugin = Plugin()

    def test_explicit_location_used_when_present(self) -> None:
        """Explicit location string is used as-is."""
        result = self.plugin.normalise(FULL_RAW)
        assert result["location"] == "Berlin, Germany"

    def test_remote_fallback_when_location_blank_and_remote_true(self) -> None:
        """'Remote' is used when location is blank and remote flag is True."""
        result = self.plugin.normalise(REMOTE_RAW)
        assert result["location"] == "Remote"

    def test_location_none_when_both_blank_and_not_remote(self) -> None:
        """location is None when no location string and remote=False."""
        raw: dict[str, Any] = {
            **MINIMAL_RAW,
            "location": "",
            "remote": False,
        }
        result = self.plugin.normalise(raw)
        assert result["location"] is None


# ---------------------------------------------------------------------------
# normalise() — contract_time normalisation
# ---------------------------------------------------------------------------


class TestNormaliseContractTime:
    """normalise() normalises known Arbeitnow job_types strings."""

    def setup_method(self) -> None:
        """Create a plugin instance."""
        self.plugin = Plugin()

    def test_full_time_permanent_normalised(self) -> None:
        """'full-time permanent' → 'full_time'."""
        raw = {**FULL_RAW, "job_types": ["full-time permanent"]}
        assert self.plugin.normalise(raw)["contract_time"] == "full_time"

    def test_berufserfahren_normalised(self) -> None:
        """'berufserfahren' → 'full_time'."""
        raw = {**FULL_RAW, "job_types": ["berufserfahren"]}
        assert self.plugin.normalise(raw)["contract_time"] == "full_time"

    def test_professional_experienced_normalised(self) -> None:
        """'professional / experienced' → 'full_time'."""
        raw = {**FULL_RAW, "job_types": ["professional / experienced"]}
        assert self.plugin.normalise(raw)["contract_time"] == "full_time"

    def test_unknown_job_type_passed_through(self) -> None:
        """Unknown job_type strings are passed through unchanged."""
        raw = {**FULL_RAW, "job_types": ["internship"]}
        assert self.plugin.normalise(raw)["contract_time"] == "internship"

    def test_case_insensitive_normalisation(self) -> None:
        """Map lookup is case-insensitive."""
        raw = {**FULL_RAW, "job_types": ["Full-Time Permanent"]}
        assert self.plugin.normalise(raw)["contract_time"] == "full_time"

    def test_empty_job_types_gives_none(self) -> None:
        """Empty job_types list → contract_time is None."""
        raw = {**FULL_RAW, "job_types": []}
        assert self.plugin.normalise(raw)["contract_time"] is None

    def test_missing_job_types_gives_none(self) -> None:
        """Missing job_types key → contract_time is None."""
        result = self.plugin.normalise(MINIMAL_RAW)
        assert result["contract_time"] is None


# ---------------------------------------------------------------------------
# normalise() — timestamp conversion edge cases
# ---------------------------------------------------------------------------


class TestNormaliseTimestamp:
    """normalise() handles timestamp edge cases gracefully."""

    def setup_method(self) -> None:
        """Create a plugin instance."""
        self.plugin = Plugin()

    def test_missing_created_at_gives_none(self) -> None:
        """Missing created_at → posted_at is None."""
        result = self.plugin.normalise(MINIMAL_RAW)
        assert result["posted_at"] is None

    def test_none_created_at_gives_none(self) -> None:
        """None created_at → posted_at is None."""
        raw = {**FULL_RAW, "created_at": None}
        assert self.plugin.normalise(raw)["posted_at"] is None

    def test_invalid_timestamp_gives_none(self) -> None:
        """Non-numeric created_at → posted_at is None."""
        raw = {**FULL_RAW, "created_at": "not-a-timestamp"}
        assert self.plugin.normalise(raw)["posted_at"] is None


# ---------------------------------------------------------------------------
# normalise() — minimal/missing fields
# ---------------------------------------------------------------------------


class TestNormaliseMinimalRaw:
    """normalise() is robust when most fields are absent."""

    def setup_method(self) -> None:
        """Create a plugin instance."""
        self.plugin = Plugin()

    def test_minimal_raw_does_not_raise(self) -> None:
        """normalise() completes without exception on minimal input."""
        result = self.plugin.normalise(MINIMAL_RAW)
        assert result["source"] == "arbeitnow"
        assert result["source_id"] == "minimal-job-789"
        assert result["title"] == "Minimal Job"

    def test_minimal_raw_description_source_none(self) -> None:
        """description_source is 'none' when no description provided."""
        result = self.plugin.normalise(MINIMAL_RAW)
        assert result["description_source"] == "none"
        assert result["description"] == ""

    def test_minimal_raw_company_none(self) -> None:
        """company is None when company_name is absent."""
        result = self.plugin.normalise(MINIMAL_RAW)
        assert result["company"] is None


# ---------------------------------------------------------------------------
# pages() — raw listing dicts, no double-normalisation
# ---------------------------------------------------------------------------


class TestPages:
    """pages() yields raw listing dicts from the API without normalising."""

    def test_pages_yields_raw_dicts(self) -> None:
        """pages() yields the raw data list from the API response."""
        fake_page1 = {"data": [FULL_RAW, REMOTE_RAW], "meta": {"last_page": 1}}

        plugin = Plugin()
        with patch("job_api_aggregator.plugins.arbeitnow.plugin.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = fake_page1
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            pages: list[list[dict[str, Any]]] = list(plugin.pages())

        assert len(pages) == 1
        assert pages[0] == [FULL_RAW, REMOTE_RAW]

    def test_pages_stops_on_empty_page(self) -> None:
        """pages() stops early when a page returns no data."""
        meta_resp = {"data": [], "meta": {"last_page": 5}}

        plugin = Plugin()
        with patch("job_api_aggregator.plugins.arbeitnow.plugin.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = meta_resp
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            pages = list(plugin.pages())

        assert pages == []

    def test_pages_respects_max_pages(self) -> None:
        """pages() honours the max_pages constructor argument."""
        meta_response = {"data": [FULL_RAW], "meta": {"last_page": 10}}
        page_response = {"data": [FULL_RAW], "meta": {"last_page": 10}}

        plugin = Plugin(search=SearchParams(max_pages=2))
        with patch("job_api_aggregator.plugins.arbeitnow.plugin.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.side_effect = [
                meta_response,
                page_response,
                page_response,
            ]
            mock_get.return_value = mock_resp

            pages = list(plugin.pages())

        assert len(pages) == 2

    def test_pages_returns_iterator(self) -> None:
        """pages() returns an iterator (not a plain list)."""
        plugin = Plugin()
        with patch("job_api_aggregator.plugins.arbeitnow.plugin.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"data": [], "meta": {"last_page": 1}}
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            result = plugin.pages()

        assert hasattr(result, "__iter__")
        assert hasattr(result, "__next__")
