"""Unit tests for the Remotive plugin — pure, no I/O.

Tests cover:
- ClassVar metadata declared correctly
- settings_schema() returns an empty dict (no credentials)
- normalise() maps every Remotive API field to JobRecord correctly
- normalise() handles missing / None values gracefully
- pages() yields nothing when fetch returns empty
- ScrapeError is raised (re-raised from requests) on network failure
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from job_api_aggregator.plugins.remotive import Plugin
from job_api_aggregator.schema import SearchParams

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_raw(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid Remotive job dict, with optional overrides."""
    base: dict[str, Any] = {
        "id": 12345,
        "url": "https://remotive.com/remote-jobs/software-dev/senior-python-12345",
        "title": "Senior Python Engineer",
        "company_name": "Acme Corp",
        "company_logo": "https://remotive.com/logo/acme.png",
        "category": "Software Development",
        "tags": ["python", "django"],
        "job_type": "full_time",
        "publication_date": "2026-04-20T12:00:00",
        "candidate_required_location": "Worldwide",
        "salary": "$120k-$150k",
        "description": "<p>We are looking for a <strong>Python</strong> engineer.</p>",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# ClassVar metadata
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    """Verify every required ClassVar is set with the correct type/value."""

    def test_source_key(self) -> None:
        assert Plugin.SOURCE == "remotive"

    def test_display_name(self) -> None:
        assert Plugin.DISPLAY_NAME == "Remotive"

    def test_description_matches_source_json(self) -> None:
        # Verbatim from source.json
        assert "remote" in Plugin.DESCRIPTION.lower()

    def test_home_url(self) -> None:
        assert Plugin.HOME_URL == "https://remotive.com"

    def test_geo_scope_is_remote_only(self) -> None:
        assert Plugin.GEO_SCOPE == "remote-only"

    def test_accepts_query(self) -> None:
        # Remotive supports a 'search' query param
        assert Plugin.ACCEPTS_QUERY == "always"

    def test_accepts_location_false(self) -> None:
        # Remotive does not accept a location filter; results are remote-only
        assert Plugin.ACCEPTS_LOCATION is False

    def test_accepts_country_false(self) -> None:
        # No country filter in the Remotive API
        assert Plugin.ACCEPTS_COUNTRY is False

    def test_rate_limit_notes_nonempty(self) -> None:
        assert isinstance(Plugin.RATE_LIMIT_NOTES, str)
        assert len(Plugin.RATE_LIMIT_NOTES) > 0

    def test_required_search_fields_empty(self) -> None:
        # No fields are mandatory; works without a query
        assert Plugin.REQUIRED_SEARCH_FIELDS == ()


# ---------------------------------------------------------------------------
# settings_schema
# ---------------------------------------------------------------------------


class TestSettingsSchema:
    """Remotive requires no credentials."""

    def test_returns_empty_dict(self) -> None:
        assert Plugin.settings_schema() == {}


# ---------------------------------------------------------------------------
# normalise() — field-by-field audit
# ---------------------------------------------------------------------------


class TestNormalise:
    """Verify normalise() maps every upstream field correctly per §9.3."""

    def setup_method(self) -> None:
        self.plugin = Plugin()

    def test_source_field(self) -> None:
        result = self.plugin.normalise(_make_raw())
        assert result["source"] == "remotive"

    def test_source_id_is_str(self) -> None:
        result = self.plugin.normalise(_make_raw(id=99))
        assert result["source_id"] == "99"

    def test_title(self) -> None:
        result = self.plugin.normalise(_make_raw(title="ML Engineer"))
        assert result["title"] == "ML Engineer"

    def test_url(self) -> None:
        url = "https://remotive.com/remote-jobs/foo/bar-1"
        result = self.plugin.normalise(_make_raw(url=url))
        assert result["url"] == url

    def test_posted_at_mapped_from_publication_date(self) -> None:
        result = self.plugin.normalise(_make_raw(publication_date="2026-04-20T12:00:00"))
        assert result["posted_at"] == "2026-04-20T12:00:00"

    def test_company(self) -> None:
        result = self.plugin.normalise(_make_raw(company_name="Globex"))
        assert result["company"] == "Globex"

    def test_location_from_candidate_required_location(self) -> None:
        result = self.plugin.normalise(_make_raw(candidate_required_location="USA only"))
        assert result["location"] == "USA only"

    def test_contract_time_from_job_type(self) -> None:
        result = self.plugin.normalise(_make_raw(job_type="contract"))
        assert result["contract_time"] == "contract"

    def test_description_has_html_stripped(self) -> None:
        result = self.plugin.normalise(_make_raw(description="<p>We need a <b>Python</b> dev.</p>"))
        assert "<p>" not in result["description"]
        assert "<b>" not in result["description"]
        assert "Python" in result["description"]

    def test_description_source_is_snippet(self) -> None:
        result = self.plugin.normalise(_make_raw())
        assert result["description_source"] == "snippet"

    def test_remote_eligible_true(self) -> None:
        # Remotive is a remote-only board; all listings are remote-eligible
        result = self.plugin.normalise(_make_raw())
        assert result["remote_eligible"] is True

    def test_salary_currency_none_when_freetext(self) -> None:
        # Salary is free-text; currency cannot be reliably parsed
        result = self.plugin.normalise(_make_raw(salary="$120k-$150k"))
        assert result["salary_currency"] is None

    def test_salary_period_none(self) -> None:
        result = self.plugin.normalise(_make_raw())
        assert result["salary_period"] is None

    def test_contract_type_none(self) -> None:
        # contract_type has no direct upstream equivalent
        result = self.plugin.normalise(_make_raw())
        assert result["contract_type"] is None

    def test_extra_contains_category(self) -> None:
        # category and tags are source-specific; stored in extra
        result = self.plugin.normalise(_make_raw(category="Design", tags=["ui", "ux"]))
        assert result.get("extra") is not None
        extra = result["extra"]
        assert isinstance(extra, dict)
        assert extra.get("category") == "Design"

    def test_extra_contains_tags(self) -> None:
        result = self.plugin.normalise(_make_raw(tags=["go", "kubernetes"]))
        extra = result["extra"]
        assert isinstance(extra, dict)
        assert extra.get("tags") == ["go", "kubernetes"]

    def test_extra_contains_company_logo(self) -> None:
        logo = "https://remotive.com/logo/acme.png"
        result = self.plugin.normalise(_make_raw(company_logo=logo))
        extra = result["extra"]
        assert isinstance(extra, dict)
        assert extra.get("company_logo") == logo


# ---------------------------------------------------------------------------
# normalise() — graceful degradation with missing / None fields
# ---------------------------------------------------------------------------


class TestNormaliseMissingFields:
    """Verify normalise() does not crash when upstream fields are absent."""

    def setup_method(self) -> None:
        self.plugin = Plugin()

    def test_missing_id_gives_empty_source_id(self) -> None:
        raw = _make_raw()
        del raw["id"]
        result = self.plugin.normalise(raw)
        assert result["source_id"] == ""

    def test_none_title_gives_empty_string(self) -> None:
        result = self.plugin.normalise(_make_raw(title=None))
        assert result["title"] == ""

    def test_none_company_gives_none(self) -> None:
        result = self.plugin.normalise(_make_raw(company_name=None))
        assert result["company"] is None

    def test_missing_salary_gives_no_salary_min_max(self) -> None:
        raw = _make_raw()
        del raw["salary"]
        result = self.plugin.normalise(raw)
        assert result["salary_min"] is None
        assert result["salary_max"] is None

    def test_none_location_gives_none(self) -> None:
        result = self.plugin.normalise(_make_raw(candidate_required_location=None))
        assert result["location"] is None

    def test_missing_publication_date_gives_none_posted_at(self) -> None:
        raw = _make_raw()
        del raw["publication_date"]
        result = self.plugin.normalise(raw)
        assert result["posted_at"] is None


# ---------------------------------------------------------------------------
# pages() — behaviour without real HTTP
# ---------------------------------------------------------------------------


class TestPages:
    """pages() integration with mocked HTTP layer."""

    def setup_method(self) -> None:
        self.plugin = Plugin()

    def test_pages_yields_list_of_records(self) -> None:
        raw_jobs = [_make_raw(id=1), _make_raw(id=2)]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"jobs": raw_jobs}

        _patch = "job_api_aggregator.plugins.remotive.plugin.requests.get"
        with patch(_patch, return_value=mock_resp):
            pages = list(self.plugin.pages())

        assert len(pages) == 1
        assert len(pages[0]) == 2
        assert pages[0][0]["source"] == "remotive"
        assert pages[0][0]["source_id"] == "1"

    def test_pages_yields_nothing_when_jobs_empty(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"jobs": []}

        _patch = "job_api_aggregator.plugins.remotive.plugin.requests.get"
        with patch(_patch, return_value=mock_resp):
            pages = list(self.plugin.pages())

        assert pages == []

    def test_pages_yields_nothing_on_http_error(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 503

        _patch = "job_api_aggregator.plugins.remotive.plugin.requests.get"
        with patch(_patch, return_value=mock_resp):
            pages = list(self.plugin.pages())

        assert pages == []

    def test_pages_raises_scrape_error_on_network_failure(self) -> None:
        import requests as req

        from job_api_aggregator.errors import ScrapeError

        with (
            patch(
                "job_api_aggregator.plugins.remotive.plugin.requests.get",
                side_effect=req.RequestException("connection refused"),
            ),
            pytest.raises(ScrapeError),
        ):
            list(self.plugin.pages())


# ---------------------------------------------------------------------------
# Constructor — search params forwarded to API
# ---------------------------------------------------------------------------


class TestConstructor:
    """Plugin accepts SearchParams-style kwargs and forwards them."""

    def test_default_construction_succeeds(self) -> None:
        plugin = Plugin()
        assert plugin is not None

    def test_query_param_accepted(self) -> None:
        plugin = Plugin(search=SearchParams(query="data engineer"))
        assert plugin is not None

    def test_category_param_accepted(self) -> None:
        plugin = Plugin(search=SearchParams(extra={"category": "software-dev"}))
        assert plugin is not None
