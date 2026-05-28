"""Unit tests for the Himalayas job-source plugin.

Tests cover:
- ClassVar metadata declarations
- ``settings_schema()`` returns empty dict (no credentials)
- ``normalise()`` field mapping for all JobRecord fields
- HTML stripping in descriptions
- ``pubDate`` parsing (ISO string, Unix seconds, Unix ms, None)
- ``employmentType`` / ``contract_time`` mapping including space-separated variants
- Location handling (restriction list present, empty list → "Worldwide")
- ``url`` field pulled from ``applicationLink``
- Missing/falsy optional fields are mapped to ``None``
"""

from __future__ import annotations

from job_api_aggregator.plugins.himalayas import Plugin

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_raw(**overrides: object) -> dict[str, object]:
    """Return a minimal valid Himalayas API job dict.

    All optional API fields are provided with representative values so that
    tests only need to override the field under test.

    Args:
        **overrides: Key/value pairs that replace the defaults.

    Returns:
        A dict shaped like a single entry from the Himalayas ``jobs`` array.
    """
    base: dict[str, object] = {
        "guid": "abc-123",
        "title": "Senior Python Developer",
        "companyName": "Acme Corp",
        "locationRestrictions": ["USA", "Canada"],
        "minSalary": 100000,
        "maxSalary": 150000,
        "employmentType": "FULL_TIME",
        "description": "<p>Build great things.</p>",
        "applicationLink": "https://himalayas.app/jobs/abc-123/apply",
        "pubDate": "2026-04-23T10:00:00Z",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Metadata / ClassVar tests
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    """Plugin-level ClassVar attributes are correctly declared."""

    def test_source_key(self) -> None:
        """SOURCE is 'himalayas'."""
        assert Plugin.SOURCE == "himalayas"

    def test_display_name(self) -> None:
        """DISPLAY_NAME is 'Himalayas'."""
        assert Plugin.DISPLAY_NAME == "Himalayas"

    def test_geo_scope_is_remote_only(self) -> None:
        """GEO_SCOPE is 'remote-only' — Himalayas is a remote-jobs board."""
        assert Plugin.GEO_SCOPE == "remote-only"

    def test_accepts_query_never(self) -> None:
        """ACCEPTS_QUERY is 'never' — the public API has no query parameter."""
        assert Plugin.ACCEPTS_QUERY == "never"

    def test_accepts_location_false(self) -> None:
        """ACCEPTS_LOCATION is False — no location filter on the public API."""
        assert Plugin.ACCEPTS_LOCATION is False

    def test_accepts_country_false(self) -> None:
        """ACCEPTS_COUNTRY is False — no country filter on the public API."""
        assert Plugin.ACCEPTS_COUNTRY is False

    def test_rate_limit_notes_non_empty(self) -> None:
        """RATE_LIMIT_NOTES is a non-empty string."""
        assert isinstance(Plugin.RATE_LIMIT_NOTES, str)
        assert Plugin.RATE_LIMIT_NOTES.strip()

    def test_required_search_fields_empty(self) -> None:
        """REQUIRED_SEARCH_FIELDS is empty — no params are required."""
        assert Plugin.REQUIRED_SEARCH_FIELDS == ()

    def test_description_non_empty(self) -> None:
        """DESCRIPTION is a non-empty string."""
        assert isinstance(Plugin.DESCRIPTION, str)
        assert Plugin.DESCRIPTION.strip()

    def test_home_url(self) -> None:
        """HOME_URL points to the Himalayas site."""
        assert Plugin.HOME_URL == "https://himalayas.app"

    def test_settings_schema_empty(self) -> None:
        """settings_schema() returns {} — no credentials required."""
        assert Plugin.settings_schema() == {}


# ---------------------------------------------------------------------------
# normalise() — identity + always-present fields
# ---------------------------------------------------------------------------


class TestNormaliseIdentityFields:
    """normalise() populates the three identity fields correctly."""

    def setup_method(self) -> None:
        """Create a fresh plugin instance for each test."""
        self.plugin = Plugin()

    def test_source_field(self) -> None:
        """'source' equals Plugin.SOURCE."""
        record = self.plugin.normalise(_make_raw())
        assert record["source"] == "himalayas"

    def test_source_id_from_guid(self) -> None:
        """'source_id' is cast from the 'guid' field."""
        record = self.plugin.normalise(_make_raw(guid="xyz-999"))
        assert record["source_id"] == "xyz-999"

    def test_source_id_missing_guid_is_empty_string(self) -> None:
        """'source_id' is '' when guid is absent."""
        raw = _make_raw()
        del raw["guid"]
        record = self.plugin.normalise(raw)
        assert record["source_id"] == ""

    def test_description_source_full_when_html(self) -> None:
        """'description_source' is 'full' when a description is provided."""
        record = self.plugin.normalise(_make_raw(description="<p>Some text</p>"))
        assert record["description_source"] == "full"

    def test_description_source_none_when_description_absent(self) -> None:
        """'description_source' is 'none' when description is empty/absent."""
        record = self.plugin.normalise(_make_raw(description=""))
        assert record["description_source"] == "none"


class TestNormaliseAlwaysPresentFields:
    """normalise() populates title, url, posted_at, and description."""

    def setup_method(self) -> None:
        """Create a fresh plugin instance."""
        self.plugin = Plugin()

    def test_title(self) -> None:
        """'title' is pulled from the 'title' field."""
        record = self.plugin.normalise(_make_raw(title="Staff Engineer"))
        assert record["title"] == "Staff Engineer"

    def test_url_from_application_link(self) -> None:
        """'url' is pulled from 'applicationLink'."""
        record = self.plugin.normalise(
            _make_raw(applicationLink="https://himalayas.app/jobs/abc/apply")
        )
        assert record["url"] == "https://himalayas.app/jobs/abc/apply"

    def test_url_empty_when_application_link_absent(self) -> None:
        """'url' is '' when applicationLink is absent."""
        raw = _make_raw()
        del raw["applicationLink"]
        record = self.plugin.normalise(raw)
        assert record["url"] == ""

    def test_posted_at_passthrough_iso_string(self) -> None:
        """'posted_at' passes an ISO string through unchanged."""
        record = self.plugin.normalise(_make_raw(pubDate="2026-01-15T08:30:00Z"))
        assert record["posted_at"] == "2026-01-15T08:30:00Z"

    def test_posted_at_none_when_absent(self) -> None:
        """'posted_at' is None when pubDate is absent."""
        raw = _make_raw()
        del raw["pubDate"]
        record = self.plugin.normalise(raw)
        assert record["posted_at"] is None

    def test_description_html_stripped(self) -> None:
        """'description' has HTML tags removed."""
        record = self.plugin.normalise(_make_raw(description="<p>Build great things.</p>"))
        assert "<p>" not in record["description"]
        assert "Build great things." in record["description"]

    def test_description_plain_text_unchanged(self) -> None:
        """'description' is returned as-is when there are no HTML tags."""
        record = self.plugin.normalise(_make_raw(description="Plain text description."))
        assert record["description"] == "Plain text description."

    def test_description_empty_when_blank(self) -> None:
        """'description' is '' when the field is absent or empty."""
        record = self.plugin.normalise(_make_raw(description=""))
        assert record["description"] == ""


# ---------------------------------------------------------------------------
# normalise() — optional fields
# ---------------------------------------------------------------------------


class TestNormaliseOptionalFields:
    """normalise() maps optional Himalayas fields to JobRecord optionals."""

    def setup_method(self) -> None:
        """Create a fresh plugin instance."""
        self.plugin = Plugin()

    def test_company(self) -> None:
        """'company' is pulled from 'companyName'."""
        record = self.plugin.normalise(_make_raw(companyName="Widgets LLC"))
        assert record["company"] == "Widgets LLC"

    def test_company_none_when_absent(self) -> None:
        """'company' is None when companyName is absent."""
        raw = _make_raw()
        del raw["companyName"]
        record = self.plugin.normalise(raw)
        assert record["company"] is None

    def test_location_from_restriction_list(self) -> None:
        """'location' joins locationRestrictions with ', '."""
        record = self.plugin.normalise(_make_raw(locationRestrictions=["USA", "Canada"]))
        assert record["location"] == "USA, Canada"

    def test_location_worldwide_when_empty_list(self) -> None:
        """'location' is 'Worldwide' when locationRestrictions is empty."""
        record = self.plugin.normalise(_make_raw(locationRestrictions=[]))
        assert record["location"] == "Worldwide"

    def test_location_worldwide_when_absent(self) -> None:
        """'location' is 'Worldwide' when locationRestrictions is absent."""
        raw = _make_raw()
        del raw["locationRestrictions"]
        record = self.plugin.normalise(raw)
        assert record["location"] == "Worldwide"

    def test_salary_min(self) -> None:
        """'salary_min' is pulled from 'minSalary'."""
        record = self.plugin.normalise(_make_raw(minSalary=90000))
        assert record["salary_min"] == 90000

    def test_salary_min_none_when_absent(self) -> None:
        """'salary_min' is None when minSalary is absent."""
        raw = _make_raw()
        del raw["minSalary"]
        record = self.plugin.normalise(raw)
        assert record["salary_min"] is None

    def test_salary_max(self) -> None:
        """'salary_max' is pulled from 'maxSalary'."""
        record = self.plugin.normalise(_make_raw(maxSalary=130000))
        assert record["salary_max"] == 130000

    def test_salary_currency_none(self) -> None:
        """'salary_currency' is None — Himalayas API does not expose it."""
        record = self.plugin.normalise(_make_raw())
        assert record["salary_currency"] is None

    def test_salary_period_none(self) -> None:
        """'salary_period' is None — Himalayas API does not expose pay period."""
        record = self.plugin.normalise(_make_raw())
        assert record["salary_period"] is None

    def test_contract_type_none(self) -> None:
        """'contract_type' is None — Himalayas has no perm/contract distinction."""
        record = self.plugin.normalise(_make_raw())
        assert record["contract_type"] is None

    def test_contract_time_full_time(self) -> None:
        """'contract_time' maps 'FULL_TIME' to 'full_time'."""
        record = self.plugin.normalise(_make_raw(employmentType="FULL_TIME"))
        assert record["contract_time"] == "full_time"

    def test_contract_time_part_time(self) -> None:
        """'contract_time' maps 'PART_TIME' to 'part_time'."""
        record = self.plugin.normalise(_make_raw(employmentType="PART_TIME"))
        assert record["contract_time"] == "part_time"

    def test_contract_time_space_variant(self) -> None:
        """'contract_time' maps space-separated 'FULL TIME' to 'full_time'."""
        record = self.plugin.normalise(_make_raw(employmentType="FULL TIME"))
        assert record["contract_time"] == "full_time"

    def test_contract_time_contract(self) -> None:
        """'contract_time' maps 'CONTRACT' to 'contract'."""
        record = self.plugin.normalise(_make_raw(employmentType="CONTRACT"))
        assert record["contract_time"] == "contract"

    def test_contract_time_unknown_lowercased(self) -> None:
        """Unmapped employmentType is lower-cased with spaces replaced."""
        record = self.plugin.normalise(_make_raw(employmentType="SHIFT WORK"))
        assert record["contract_time"] == "shift_work"

    def test_contract_time_none_when_absent(self) -> None:
        """'contract_time' is None when employmentType is absent."""
        raw = _make_raw()
        del raw["employmentType"]
        record = self.plugin.normalise(raw)
        assert record["contract_time"] is None

    def test_remote_eligible_true(self) -> None:
        """'remote_eligible' is True — all Himalayas listings are remote."""
        record = self.plugin.normalise(_make_raw())
        assert record["remote_eligible"] is True

    def test_extra_is_none(self) -> None:
        """'extra' is None — no source-specific blob needed."""
        record = self.plugin.normalise(_make_raw())
        assert record["extra"] is None


# ---------------------------------------------------------------------------
# pubDate parsing edge cases
# ---------------------------------------------------------------------------


class TestParsePubDate:
    """pubDate parsing handles ISO strings, Unix seconds, Unix ms, and None."""

    def setup_method(self) -> None:
        """Create a fresh plugin instance."""
        self.plugin = Plugin()

    def test_unix_seconds(self) -> None:
        """Unix-seconds timestamp is converted to ISO 8601."""
        # 1700000000 seconds → 2023-11-14T22:13:20Z
        record = self.plugin.normalise(_make_raw(pubDate=1700000000))
        assert record["posted_at"] == "2023-11-14T22:13:20Z"

    def test_unix_milliseconds(self) -> None:
        """Unix-milliseconds timestamp is divided by 1000 first."""
        # 1700000000000 ms == 1700000000 s
        record = self.plugin.normalise(_make_raw(pubDate=1700000000000))
        assert record["posted_at"] == "2023-11-14T22:13:20Z"

    def test_none_pubdate(self) -> None:
        """None pubDate yields None posted_at."""
        record = self.plugin.normalise(_make_raw(pubDate=None))
        assert record["posted_at"] is None
