"""Unit tests for the RemoteOK plugin.

Tests use synthetic dicts — no HTTP calls are made.  The VCR integration
tests live in ``test_remoteok_integration.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from job_api_aggregator.plugins.remoteok import Plugin

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_raw(**overrides: Any) -> dict[str, Any]:
    """Return a minimal realistic raw RemoteOK listing dict.

    Args:
        **overrides: Key/value pairs that override the defaults.

    Returns:
        A dict resembling a single RemoteOK API job object.
    """
    base: dict[str, Any] = {
        "id": "12345",
        "position": "Senior Python Developer",
        "company": "Acme Corp",
        "location": "Remote",
        "description": "<p>Great job for a <strong>Python</strong> dev.</p>",
        "url": "https://remoteok.com/jobs/12345",
        "date": "2026-04-20T12:00:00Z",
        "salary_min": 100000,
        "salary_max": 150000,
        "tags": ["python", "django"],
        "logo": "https://remoteok.com/cdn/logo.png",
        "apply_url": "https://acme.com/apply",
    }
    base.update(overrides)
    return base


@pytest.fixture()
def plugin() -> Plugin:
    """Return a Plugin instance with no search params.

    Returns:
        A Plugin ready for normalise() calls.
    """
    return Plugin()


# ---------------------------------------------------------------------------
# ClassVar metadata
# ---------------------------------------------------------------------------


class TestClassVars:
    """Verify all required ClassVar metadata is present and correct."""

    def test_source_key(self) -> None:
        """SOURCE must be the canonical plugin key."""
        assert Plugin.SOURCE == "remoteok"

    def test_display_name(self) -> None:
        """DISPLAY_NAME must match source.json."""
        assert Plugin.DISPLAY_NAME == "Remote OK"

    def test_geo_scope(self) -> None:
        """GEO_SCOPE must be remote-only (all listings are remote)."""
        assert Plugin.GEO_SCOPE == "remote-only"

    def test_accepts_query_never(self) -> None:
        """ACCEPTS_QUERY must be 'never' — API has no query param."""
        assert Plugin.ACCEPTS_QUERY == "never"

    def test_accepts_location_false(self) -> None:
        """ACCEPTS_LOCATION must be False — no location filter in API."""
        assert Plugin.ACCEPTS_LOCATION is False

    def test_accepts_country_false(self) -> None:
        """ACCEPTS_COUNTRY must be False — no country filter in API."""
        assert Plugin.ACCEPTS_COUNTRY is False

    def test_rate_limit_notes_present(self) -> None:
        """RATE_LIMIT_NOTES must be a non-empty string."""
        assert isinstance(Plugin.RATE_LIMIT_NOTES, str)
        assert Plugin.RATE_LIMIT_NOTES.strip()

    def test_required_search_fields_empty(self) -> None:
        """REQUIRED_SEARCH_FIELDS must be empty — no mandatory params."""
        assert Plugin.REQUIRED_SEARCH_FIELDS == ()

    def test_description_present(self) -> None:
        """DESCRIPTION must be a non-empty string."""
        assert isinstance(Plugin.DESCRIPTION, str)
        assert Plugin.DESCRIPTION.strip()

    def test_home_url(self) -> None:
        """HOME_URL must match source.json."""
        assert Plugin.HOME_URL == "https://remoteok.com"


# ---------------------------------------------------------------------------
# settings_schema
# ---------------------------------------------------------------------------


class TestSettingsSchema:
    """Verify settings_schema returns an empty dict (no creds needed)."""

    def test_empty_schema(self, plugin: Plugin) -> None:
        """settings_schema must return {} for a no-credentials source."""
        assert Plugin.settings_schema() == {}


# ---------------------------------------------------------------------------
# normalise() — identity fields
# ---------------------------------------------------------------------------


class TestNormaliseIdentity:
    """Verify identity fields are always present in normalised output."""

    def test_source_field(self, plugin: Plugin) -> None:
        """source must equal the plugin SOURCE key."""
        result = plugin.normalise(_make_raw())
        assert result["source"] == "remoteok"

    def test_source_id_from_id(self, plugin: Plugin) -> None:
        """source_id must be stringified 'id' from raw."""
        result = plugin.normalise(_make_raw(id="99"))
        assert result["source_id"] == "99"

    def test_source_id_coerced_to_str(self, plugin: Plugin) -> None:
        """source_id must be a string even when raw 'id' is an int."""
        result = plugin.normalise(_make_raw(id=42))
        assert result["source_id"] == "42"

    def test_description_source_is_snippet(self, plugin: Plugin) -> None:
        """description_source must be 'snippet' for RemoteOK listings."""
        result = plugin.normalise(_make_raw())
        assert result["description_source"] == "snippet"


# ---------------------------------------------------------------------------
# normalise() — always-present fields
# ---------------------------------------------------------------------------


class TestNormaliseAlwaysPresent:
    """Verify always-present output fields map correctly."""

    def test_title_from_position(self, plugin: Plugin) -> None:
        """title must map from 'position' field."""
        result = plugin.normalise(_make_raw(position="Staff Engineer"))
        assert result["title"] == "Staff Engineer"

    def test_url_from_url(self, plugin: Plugin) -> None:
        """url must map from 'url' field."""
        result = plugin.normalise(_make_raw(url="https://remoteok.com/jobs/1"))
        assert result["url"] == "https://remoteok.com/jobs/1"

    def test_posted_at_backfilled_from_date(self, plugin: Plugin) -> None:
        """posted_at must be backfilled from 'date' because RemoteOK never
        sets posted_at directly.
        """
        result = plugin.normalise(_make_raw(date="2026-04-20T12:00:00Z"))
        assert result["posted_at"] == "2026-04-20T12:00:00Z"

    def test_posted_at_none_when_date_missing(self, plugin: Plugin) -> None:
        """posted_at must be None when 'date' is absent."""
        raw = _make_raw()
        raw.pop("date")
        result = plugin.normalise(raw)
        assert result["posted_at"] is None

    def test_description_html_stripped(self, plugin: Plugin) -> None:
        """description must have HTML tags stripped."""
        result = plugin.normalise(
            _make_raw(description="<p>Great job for a <strong>Python</strong> dev.</p>")
        )
        assert "<" not in result["description"]
        assert "Python" in result["description"]

    def test_description_empty_string_when_absent(self, plugin: Plugin) -> None:
        """description must be empty string when raw field is absent."""
        raw = _make_raw()
        raw.pop("description")
        result = plugin.normalise(raw)
        assert result["description"] == ""


# ---------------------------------------------------------------------------
# normalise() — optional fields
# ---------------------------------------------------------------------------


class TestNormaliseOptional:
    """Verify optional field mappings and null-handling."""

    def test_company(self, plugin: Plugin) -> None:
        """company must map from 'company' field."""
        result = plugin.normalise(_make_raw(company="Globex"))
        assert result["company"] == "Globex"

    def test_location_defaults_to_remote(self, plugin: Plugin) -> None:
        """location must fall back to 'Remote' when raw value is empty."""
        result = plugin.normalise(_make_raw(location=""))
        assert result["location"] == "Remote"

    def test_location_preserved_when_set(self, plugin: Plugin) -> None:
        """location must be preserved when raw provides a non-empty value."""
        result = plugin.normalise(_make_raw(location="Worldwide"))
        assert result["location"] == "Worldwide"

    def test_salary_min_present(self, plugin: Plugin) -> None:
        """salary_min must be mapped from 'salary_min' field."""
        result = plugin.normalise(_make_raw(salary_min=80000))
        assert result["salary_min"] == 80000

    def test_salary_max_present(self, plugin: Plugin) -> None:
        """salary_max must be mapped from 'salary_max' field."""
        result = plugin.normalise(_make_raw(salary_max=120000))
        assert result["salary_max"] == 120000

    def test_salary_min_zero_becomes_none(self, plugin: Plugin) -> None:
        """salary_min of 0 must map to None (RemoteOK uses 0 for unset)."""
        result = plugin.normalise(_make_raw(salary_min=0))
        assert result["salary_min"] is None

    def test_salary_max_zero_becomes_none(self, plugin: Plugin) -> None:
        """salary_max of 0 must map to None (RemoteOK uses 0 for unset)."""
        result = plugin.normalise(_make_raw(salary_max=0))
        assert result["salary_max"] is None

    def test_salary_min_absent_becomes_none(self, plugin: Plugin) -> None:
        """salary_min must be None when key is absent from raw."""
        raw = _make_raw()
        raw.pop("salary_min")
        result = plugin.normalise(raw)
        assert result["salary_min"] is None

    def test_salary_max_absent_becomes_none(self, plugin: Plugin) -> None:
        """salary_max must be None when key is absent from raw."""
        raw = _make_raw()
        raw.pop("salary_max")
        result = plugin.normalise(raw)
        assert result["salary_max"] is None

    def test_salary_currency_none(self, plugin: Plugin) -> None:
        """salary_currency must always be None (RemoteOK omits currency)."""
        result = plugin.normalise(_make_raw())
        assert result["salary_currency"] is None

    def test_salary_period_none(self, plugin: Plugin) -> None:
        """salary_period must always be None (RemoteOK omits pay period)."""
        result = plugin.normalise(_make_raw())
        assert result["salary_period"] is None

    def test_contract_type_none(self, plugin: Plugin) -> None:
        """contract_type must always be None (not exposed by RemoteOK API)."""
        result = plugin.normalise(_make_raw())
        assert result["contract_type"] is None

    def test_contract_time_none(self, plugin: Plugin) -> None:
        """contract_time must always be None (not exposed by RemoteOK API)."""
        result = plugin.normalise(_make_raw())
        assert result["contract_time"] is None

    def test_remote_eligible_true(self, plugin: Plugin) -> None:
        """remote_eligible must be True (RemoteOK is a remote-only board)."""
        result = plugin.normalise(_make_raw())
        assert result["remote_eligible"] is True

    def test_extra_contains_tags(self, plugin: Plugin) -> None:
        """extra dict must contain 'tags' from raw listing."""
        result = plugin.normalise(_make_raw(tags=["python", "django"]))
        assert result["extra"] is not None
        assert result["extra"]["tags"] == ["python", "django"]


# ---------------------------------------------------------------------------
# normalise() — field drops (deliberate)
# ---------------------------------------------------------------------------


class TestNormaliseDroppedFields:
    """Verify that fields deliberately dropped from normalise() are absent
    from the output dict.
    """

    def test_logo_dropped(self, plugin: Plugin) -> None:
        """'logo' must not appear in normalised output."""
        result = plugin.normalise(_make_raw(logo="https://example.com/logo.png"))
        assert "logo" not in result

    def test_apply_url_dropped(self, plugin: Plugin) -> None:
        """'apply_url' must not appear in normalised output (url is used)."""
        result = plugin.normalise(_make_raw(apply_url="https://example.com/apply"))
        assert "apply_url" not in result


# ---------------------------------------------------------------------------
# pages() behaviour (stub — real HTTP tested in integration)
# ---------------------------------------------------------------------------


class TestPages:
    """Verify pages() structural contract without making HTTP calls."""

    def test_pages_is_generator(self, plugin: Plugin) -> None:
        """pages() must return an iterator."""
        import inspect

        assert inspect.isgeneratorfunction(plugin.pages)
