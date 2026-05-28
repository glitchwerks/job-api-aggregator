"""Unit tests for the jobicy plugin.

All tests use synthetic dicts — no HTTP calls are made.
The VCR integration tests live in test_jobicy_integration.py.
"""

from __future__ import annotations

from job_api_aggregator.plugins.jobicy import Plugin

# ---------------------------------------------------------------------------
# Minimal raw job dict — mirrors the Jobicy API response shape.
# ---------------------------------------------------------------------------

MINIMAL_RAW: dict[str, object] = {
    "id": 42,
    "jobSlug": "senior-python-dev-42",
    "jobTitle": "Senior Python Developer",
    "companyName": "Acme Corp",
    "companyLogo": "https://example.com/logo.png",
    "jobIndustry": ["Software"],
    "jobType": ["full_time"],
    "jobGeo": "Worldwide",
    "jobLevel": "Senior",
    "jobExcerpt": "A great opportunity.",
    "jobDescription": "<p>Full job details here.</p>",
    "pubDate": "2026-04-20 10:00:00",
    "url": "https://jobicy.com/jobs/42-senior-python-dev",
    "annualSalaryMin": None,
    "annualSalaryMax": None,
    "salaryCurrency": None,
}


# ---------------------------------------------------------------------------
# ClassVar metadata
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    """Verify all required ClassVar attributes are set correctly."""

    def test_source_key(self) -> None:
        """Plugin.SOURCE must be 'jobicy'."""
        assert Plugin.SOURCE == "jobicy"

    def test_display_name(self) -> None:
        """Plugin.DISPLAY_NAME must be set."""
        assert Plugin.DISPLAY_NAME == "Jobicy"

    def test_geo_scope_is_remote_only(self) -> None:
        """Jobicy is a remote-only board; GEO_SCOPE must reflect that."""
        assert Plugin.GEO_SCOPE == "remote-only"

    def test_accepts_query_partial(self) -> None:
        """Jobicy accepts a 'tag' search param — partial query support."""
        assert Plugin.ACCEPTS_QUERY == "partial"

    def test_accepts_location_false(self) -> None:
        """Jobicy API has no location filter; ACCEPTS_LOCATION must be False."""
        assert Plugin.ACCEPTS_LOCATION is False

    def test_accepts_country_false(self) -> None:
        """Jobicy API has no country filter; ACCEPTS_COUNTRY must be False."""
        assert Plugin.ACCEPTS_COUNTRY is False

    def test_rate_limit_notes_set(self) -> None:
        """RATE_LIMIT_NOTES must be a non-empty string."""
        assert isinstance(Plugin.RATE_LIMIT_NOTES, str)
        assert Plugin.RATE_LIMIT_NOTES

    def test_required_search_fields_empty(self) -> None:
        """Jobicy needs no required search fields — it works with defaults."""
        assert Plugin.REQUIRED_SEARCH_FIELDS == ()

    def test_description_set(self) -> None:
        """DESCRIPTION must be copied verbatim from source.json."""
        assert "remote" in Plugin.DESCRIPTION.lower()

    def test_home_url_set(self) -> None:
        """HOME_URL must point to the Jobicy homepage."""
        assert Plugin.HOME_URL == "https://jobicy.com"


# ---------------------------------------------------------------------------
# settings_schema — no credentials needed
# ---------------------------------------------------------------------------


class TestSettingsSchema:
    """Verify settings_schema returns empty dict (no credentials)."""

    def test_settings_schema_empty(self) -> None:
        """Jobicy needs no API key; settings_schema must return {}."""
        assert Plugin.settings_schema() == {}


# ---------------------------------------------------------------------------
# normalise() — field mapping
# ---------------------------------------------------------------------------


class TestNormalise:
    """Verify normalise() maps Jobicy raw dicts to JobRecord correctly."""

    def setup_method(self) -> None:
        """Instantiate a plugin once per test method."""
        self.plugin = Plugin()

    def test_source_field(self) -> None:
        """normalise() sets source to Plugin.SOURCE."""
        record = self.plugin.normalise(MINIMAL_RAW)
        assert record["source"] == "jobicy"

    def test_source_id_is_string(self) -> None:
        """normalise() converts integer id to a string source_id."""
        record = self.plugin.normalise(MINIMAL_RAW)
        assert record["source_id"] == "42"

    def test_title_mapped(self) -> None:
        """normalise() maps jobTitle to title."""
        record = self.plugin.normalise(MINIMAL_RAW)
        assert record["title"] == "Senior Python Developer"

    def test_company_mapped(self) -> None:
        """normalise() maps companyName to company."""
        record = self.plugin.normalise(MINIMAL_RAW)
        assert record["company"] == "Acme Corp"

    def test_location_mapped(self) -> None:
        """normalise() maps jobGeo to location."""
        record = self.plugin.normalise(MINIMAL_RAW)
        assert record["location"] == "Worldwide"

    def test_url_mapped(self) -> None:
        """normalise() maps url to url."""
        record = self.plugin.normalise(MINIMAL_RAW)
        assert record["url"] == "https://jobicy.com/jobs/42-senior-python-dev"

    def test_posted_at_mapped(self) -> None:
        """normalise() maps pubDate to posted_at."""
        record = self.plugin.normalise(MINIMAL_RAW)
        assert record["posted_at"] == "2026-04-20 10:00:00"

    def test_description_html_stripped(self) -> None:
        """normalise() strips HTML tags from jobDescription."""
        record = self.plugin.normalise(MINIMAL_RAW)
        assert "<p>" not in record["description"]
        assert "Full job details here." in record["description"]

    def test_description_source_is_full(self) -> None:
        """Jobicy returns full descriptions; description_source must be 'full'."""
        record = self.plugin.normalise(MINIMAL_RAW)
        assert record["description_source"] == "full"

    def test_salary_none_when_absent(self) -> None:
        """normalise() sets salary_min/max to None when both are absent."""
        record = self.plugin.normalise(MINIMAL_RAW)
        assert record["salary_min"] is None
        assert record["salary_max"] is None
        assert record["salary_period"] is None

    def test_salary_parsed_when_present(self) -> None:
        """normalise() converts salary fields to float and sets period=annual."""
        raw = {**MINIMAL_RAW, "annualSalaryMin": 80000, "annualSalaryMax": 120000}
        record = self.plugin.normalise(raw)
        assert record["salary_min"] == 80000.0
        assert record["salary_max"] == 120000.0
        assert record["salary_period"] == "annual"

    def test_salary_partial_min_only(self) -> None:
        """normalise() handles only annualSalaryMin being set."""
        raw = {**MINIMAL_RAW, "annualSalaryMin": 60000, "annualSalaryMax": None}
        record = self.plugin.normalise(raw)
        assert record["salary_min"] == 60000.0
        assert record["salary_max"] is None
        assert record["salary_period"] == "annual"

    def test_salary_currency_mapped(self) -> None:
        """normalise() maps salaryCurrency to salary_currency when present."""
        raw = {
            **MINIMAL_RAW,
            "annualSalaryMin": 80000,
            "salaryCurrency": "USD",
        }
        record = self.plugin.normalise(raw)
        assert record["salary_currency"] == "USD"

    def test_salary_currency_none_when_absent(self) -> None:
        """normalise() sets salary_currency to None when salaryCurrency absent."""
        record = self.plugin.normalise(MINIMAL_RAW)
        assert record["salary_currency"] is None

    def test_contract_time_string_passthrough(self) -> None:
        """normalise() passes a string jobType value through as contract_time."""
        raw = {**MINIMAL_RAW, "jobType": "full_time"}
        record = self.plugin.normalise(raw)
        assert record["contract_time"] == "full_time"

    def test_contract_time_list_first_element(self) -> None:
        """normalise() extracts the first element when jobType is a list."""
        raw = {**MINIMAL_RAW, "jobType": ["part_time"]}
        record = self.plugin.normalise(raw)
        assert record["contract_time"] == "part_time"

    def test_contract_time_empty_list_is_none(self) -> None:
        """normalise() returns None for contract_time when jobType is []."""
        raw = {**MINIMAL_RAW, "jobType": []}
        record = self.plugin.normalise(raw)
        assert record["contract_time"] is None

    def test_contract_time_missing_is_none(self) -> None:
        """normalise() returns None for contract_time when jobType absent."""
        raw = {k: v for k, v in MINIMAL_RAW.items() if k != "jobType"}
        record = self.plugin.normalise(raw)
        assert record["contract_time"] is None

    def test_contract_type_always_none(self) -> None:
        """contract_type is always None — Jobicy has no separate type field."""
        record = self.plugin.normalise(MINIMAL_RAW)
        assert record["contract_type"] is None

    def test_remote_eligible_true(self) -> None:
        """Jobicy is remote-only; all listings are remote_eligible=True."""
        record = self.plugin.normalise(MINIMAL_RAW)
        assert record["remote_eligible"] is True

    def test_extra_contains_dropped_fields(self) -> None:
        """normalise() stores non-mapped fields in extra blob."""
        record = self.plugin.normalise(MINIMAL_RAW)
        extra = record.get("extra") or {}
        # jobSlug, jobIndustry, jobLevel, jobExcerpt, companyLogo are dropped
        # into extra rather than silently discarded.
        assert "job_slug" in extra or "jobSlug" in extra

    def test_missing_title_defaults_to_empty_string(self) -> None:
        """normalise() defaults title to '' when jobTitle is absent."""
        raw = {k: v for k, v in MINIMAL_RAW.items() if k != "jobTitle"}
        record = self.plugin.normalise(raw)
        assert record["title"] == ""

    def test_missing_description_defaults_to_empty_string(self) -> None:
        """normalise() defaults description to '' when jobDescription absent."""
        raw = {k: v for k, v in MINIMAL_RAW.items() if k != "jobDescription"}
        record = self.plugin.normalise(raw)
        assert record["description"] == ""


# ---------------------------------------------------------------------------
# _coerce_contract_field helper (tested via normalise)
# ---------------------------------------------------------------------------


class TestCoerceContractField:
    """Edge-case coverage for the jobType coercion helper."""

    def setup_method(self) -> None:
        """Instantiate plugin once per test."""
        self.plugin = Plugin()

    def test_none_list_element_is_none(self) -> None:
        """[None] as jobType should yield None for contract_time."""
        raw = {**MINIMAL_RAW, "jobType": [None]}
        record = self.plugin.normalise(raw)
        assert record["contract_time"] is None

    def test_null_jobtype_is_none(self) -> None:
        """null jobType value yields None for contract_time."""
        raw = {**MINIMAL_RAW, "jobType": None}
        record = self.plugin.normalise(raw)
        assert record["contract_time"] is None


# ---------------------------------------------------------------------------
# pages() — pagination behaviour
# ---------------------------------------------------------------------------


class TestPages:
    """Verify pages() yields correctly (requires mocking HTTP)."""

    def test_pages_returns_iterator(self) -> None:
        """pages() must return an iterator (without calling HTTP)."""
        plugin = Plugin()
        import inspect

        assert inspect.isgeneratorfunction(type(plugin).pages)
