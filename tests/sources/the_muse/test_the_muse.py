"""Unit tests for the the_muse plugin.

Tests verify the plugin's contract conformance, ClassVar metadata,
normalise() field mapping, and edge-case handling using synthetic
dicts (no real HTTP calls).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from job_api_aggregator.base import JobSource
from job_api_aggregator.schema import SearchParams

# ---------------------------------------------------------------------------
# Helpers — synthetic raw records matching The Muse API shape
# ---------------------------------------------------------------------------


def _make_raw_job(
    *,
    job_id: int = 12345,
    name: str = "Software Engineer",
    job_type: str = "full-time",
    company_name: str = "Acme Corp",
    location_name: str = "New York, NY",
    contents: str = "<p>Great job opportunity.</p>",
    landing_page: str = "https://www.themuse.com/jobs/acme/software-engineer",
    publication_date: str = "2026-04-20T12:00:00Z",
) -> dict[str, Any]:
    """Return a synthetic raw The Muse API job dict."""
    return {
        "id": job_id,
        "name": name,
        "type": job_type,
        "company": {"name": company_name},
        "locations": [{"name": location_name}],
        "contents": contents,
        "refs": {"landing_page": landing_page},
        "publication_date": publication_date,
    }


# ---------------------------------------------------------------------------
# ClassVar metadata contract
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    """The Plugin class must expose correct ClassVar metadata."""

    def test_plugin_is_importable(self) -> None:
        """Plugin class can be imported from the package path."""
        from job_api_aggregator.plugins.the_muse import Plugin

        assert Plugin is not None

    def test_plugin_subclasses_job_source(self) -> None:
        """Plugin must subclass JobSource."""
        from job_api_aggregator.plugins.the_muse import Plugin

        assert issubclass(Plugin, JobSource)

    def test_source_key(self) -> None:
        """SOURCE must be 'the_muse'."""
        from job_api_aggregator.plugins.the_muse import Plugin

        assert Plugin.SOURCE == "the_muse"

    def test_display_name(self) -> None:
        """DISPLAY_NAME must be 'The Muse'."""
        from job_api_aggregator.plugins.the_muse import Plugin

        assert Plugin.DISPLAY_NAME == "The Muse"

    def test_geo_scope(self) -> None:
        """GEO_SCOPE must be 'global' (board is international, no country filter)."""
        from job_api_aggregator.plugins.the_muse import Plugin

        assert Plugin.GEO_SCOPE == "global"

    def test_accepts_query_partial(self) -> None:
        """ACCEPTS_QUERY must be 'partial' (maps query to category param)."""
        from job_api_aggregator.plugins.the_muse import Plugin

        assert Plugin.ACCEPTS_QUERY == "partial"

    def test_accepts_location_false(self) -> None:
        """ACCEPTS_LOCATION must be False (API has no location filter)."""
        from job_api_aggregator.plugins.the_muse import Plugin

        assert Plugin.ACCEPTS_LOCATION is False

    def test_accepts_country_false(self) -> None:
        """ACCEPTS_COUNTRY must be False (API has no country filter)."""
        from job_api_aggregator.plugins.the_muse import Plugin

        assert Plugin.ACCEPTS_COUNTRY is False

    def test_rate_limit_notes_is_string(self) -> None:
        """RATE_LIMIT_NOTES must be a non-empty string."""
        from job_api_aggregator.plugins.the_muse import Plugin

        assert isinstance(Plugin.RATE_LIMIT_NOTES, str)
        assert Plugin.RATE_LIMIT_NOTES

    def test_required_search_fields_empty(self) -> None:
        """REQUIRED_SEARCH_FIELDS must be empty (no mandatory search fields)."""
        from job_api_aggregator.plugins.the_muse import Plugin

        assert Plugin.REQUIRED_SEARCH_FIELDS == ()

    def test_description_set(self) -> None:
        """DESCRIPTION must be a non-empty string copied from source.json."""
        from job_api_aggregator.plugins.the_muse import Plugin

        assert isinstance(Plugin.DESCRIPTION, str)
        assert Plugin.DESCRIPTION

    def test_home_url(self) -> None:
        """HOME_URL must be 'https://www.themuse.com'."""
        from job_api_aggregator.plugins.the_muse import Plugin

        assert Plugin.HOME_URL == "https://www.themuse.com"


# ---------------------------------------------------------------------------
# Constructor and settings_schema
# ---------------------------------------------------------------------------


class TestPluginConstruction:
    """Plugin instantiates correctly with and without optional params."""

    def test_instantiates_no_args(self) -> None:
        """Plugin instantiates with no arguments."""
        from job_api_aggregator.plugins.the_muse import Plugin

        p = Plugin()
        assert p is not None

    def test_instantiates_with_query(self) -> None:
        """Plugin accepts a query (used as category filter)."""
        from job_api_aggregator.plugins.the_muse import Plugin

        p = Plugin(search=SearchParams(query="Data Engineer"))
        assert p is not None

    def test_instantiates_with_max_pages(self) -> None:
        """Plugin accepts a max_pages argument."""
        from job_api_aggregator.plugins.the_muse import Plugin

        p = Plugin(search=SearchParams(max_pages=3))
        assert p is not None

    def test_settings_schema_returns_empty_dict(self) -> None:
        """settings_schema() returns an empty dict (no credentials required)."""
        from job_api_aggregator.plugins.the_muse import Plugin

        assert Plugin.settings_schema() == {}


# ---------------------------------------------------------------------------
# normalise() — field mapping
# ---------------------------------------------------------------------------


class TestNormalise:
    """normalise() maps The Muse API fields to the JobRecord schema."""

    def _plugin(self) -> Any:
        from job_api_aggregator.plugins.the_muse import Plugin

        return Plugin()

    def test_source_field(self) -> None:
        """normalise() sets source to 'the_muse'."""
        result = self._plugin().normalise(_make_raw_job())
        assert result["source"] == "the_muse"

    def test_source_id_is_string(self) -> None:
        """normalise() converts integer id to string source_id."""
        result = self._plugin().normalise(_make_raw_job(job_id=99))
        assert result["source_id"] == "99"

    def test_title_from_name(self) -> None:
        """normalise() maps 'name' field to 'title'."""
        result = self._plugin().normalise(_make_raw_job(name="Backend Developer"))
        assert result["title"] == "Backend Developer"

    def test_url_from_landing_page(self) -> None:
        """normalise() maps refs.landing_page to url."""
        result = self._plugin().normalise(
            _make_raw_job(landing_page="https://www.themuse.com/jobs/co/eng")
        )
        assert result["url"] == "https://www.themuse.com/jobs/co/eng"

    def test_posted_at_from_publication_date(self) -> None:
        """normalise() maps publication_date to posted_at."""
        result = self._plugin().normalise(_make_raw_job(publication_date="2026-04-20T12:00:00Z"))
        assert result["posted_at"] == "2026-04-20T12:00:00Z"

    def test_description_strips_html(self) -> None:
        """normalise() strips HTML tags from contents for description.

        BeautifulSoup's separator=" " joins text nodes with a space, so
        "<p>Great <b>opportunity</b>.</p>" becomes "Great opportunity ."
        (the period is a separate text node after the <b> close tag).
        """
        result = self._plugin().normalise(_make_raw_job(contents="<p>Plain text description.</p>"))
        # Verify HTML tags are removed and text content is preserved.
        assert "Plain text description" in result["description"]
        assert "<p>" not in result["description"]
        assert "<" not in result["description"]

    def test_description_source_is_full(self) -> None:
        """normalise() sets description_source to 'full' (API returns full HTML)."""
        result = self._plugin().normalise(_make_raw_job())
        assert result["description_source"] == "full"

    def test_company_from_nested_object(self) -> None:
        """normalise() extracts company name from nested company.name."""
        result = self._plugin().normalise(_make_raw_job(company_name="TechCo"))
        assert result["company"] == "TechCo"

    def test_location_from_first_locations_entry(self) -> None:
        """normalise() maps first entry in locations list to location."""
        result = self._plugin().normalise(_make_raw_job(location_name="Austin, TX"))
        assert result["location"] == "Austin, TX"

    def test_contract_time_from_type(self) -> None:
        """normalise() maps 'type' field to contract_time."""
        result = self._plugin().normalise(_make_raw_job(job_type="full-time"))
        assert result["contract_time"] == "full-time"

    def test_salary_min_is_none(self) -> None:
        """normalise() sets salary_min to None (API provides no salary data)."""
        result = self._plugin().normalise(_make_raw_job())
        assert result["salary_min"] is None

    def test_salary_max_is_none(self) -> None:
        """normalise() sets salary_max to None (API provides no salary data)."""
        result = self._plugin().normalise(_make_raw_job())
        assert result["salary_max"] is None

    def test_salary_currency_is_none(self) -> None:
        """normalise() sets salary_currency to None (not in API response)."""
        result = self._plugin().normalise(_make_raw_job())
        assert result["salary_currency"] is None

    def test_salary_period_is_none(self) -> None:
        """normalise() sets salary_period to None (API provides no salary data)."""
        result = self._plugin().normalise(_make_raw_job())
        assert result["salary_period"] is None

    def test_contract_type_is_none(self) -> None:
        """normalise() sets contract_type to None (not in API response)."""
        result = self._plugin().normalise(_make_raw_job())
        assert result["contract_type"] is None

    def test_remote_eligible_is_none(self) -> None:
        """normalise() sets remote_eligible to None (not in API response)."""
        result = self._plugin().normalise(_make_raw_job())
        assert result["remote_eligible"] is None


# ---------------------------------------------------------------------------
# normalise() — edge cases
# ---------------------------------------------------------------------------


class TestNormaliseEdgeCases:
    """normalise() handles missing / null API fields gracefully."""

    def _plugin(self) -> Any:
        from job_api_aggregator.plugins.the_muse import Plugin

        return Plugin()

    def test_empty_locations_gives_none_location(self) -> None:
        """normalise() returns None for location when locations list is empty."""
        raw = _make_raw_job()
        raw["locations"] = []
        result = self._plugin().normalise(raw)
        assert result["location"] is None

    def test_missing_locations_key_gives_none(self) -> None:
        """normalise() returns None for location when locations key is absent."""
        raw = _make_raw_job()
        del raw["locations"]
        result = self._plugin().normalise(raw)
        assert result["location"] is None

    def test_null_contents_gives_empty_description(self) -> None:
        """normalise() returns empty string description when contents is None."""
        raw = _make_raw_job()
        raw["contents"] = None
        result = self._plugin().normalise(raw)
        assert result["description"] == ""

    def test_missing_contents_gives_empty_description(self) -> None:
        """normalise() returns empty string description when contents key absent."""
        raw = _make_raw_job()
        del raw["contents"]
        result = self._plugin().normalise(raw)
        assert result["description"] == ""

    def test_missing_company_gives_empty_string(self) -> None:
        """normalise() returns empty string for company when company key absent."""
        raw = _make_raw_job()
        del raw["company"]
        result = self._plugin().normalise(raw)
        assert result["company"] == ""

    def test_null_company_gives_empty_string(self) -> None:
        """normalise() returns empty string for company when company is None."""
        raw = _make_raw_job()
        raw["company"] = None
        result = self._plugin().normalise(raw)
        assert result["company"] == ""

    def test_null_publication_date_gives_none(self) -> None:
        """normalise() returns None for posted_at when publication_date is None."""
        raw = _make_raw_job()
        raw["publication_date"] = None
        result = self._plugin().normalise(raw)
        assert result["posted_at"] is None

    def test_missing_refs_gives_empty_url(self) -> None:
        """normalise() returns empty string url when refs key is absent."""
        raw = _make_raw_job()
        del raw["refs"]
        result = self._plugin().normalise(raw)
        assert result["url"] == ""

    def test_null_type_gives_none_contract_time(self) -> None:
        """normalise() returns None for contract_time when type is None."""
        raw = _make_raw_job()
        raw["type"] = None
        result = self._plugin().normalise(raw)
        assert result["contract_time"] is None

    def test_source_id_coerces_to_string(self) -> None:
        """normalise() coerces non-string id to string."""
        raw = _make_raw_job(job_id=42)
        result = self._plugin().normalise(raw)
        assert result["source_id"] == "42"
        assert isinstance(result["source_id"], str)


# ---------------------------------------------------------------------------
# pages() — pagination logic (mocked HTTP)
# ---------------------------------------------------------------------------


class TestPages:
    """pages() yields results correctly using mocked HTTP responses.

    The Muse API is 0-indexed.  Page 0 is both the probe (to discover
    page_count) and the first page of results.  Pages 1..page_count-1
    are fetched subsequently.
    """

    def _plugin(self, search: SearchParams | None = None) -> Any:
        from job_api_aggregator.plugins.the_muse import Plugin

        return Plugin(search=search)

    def test_pages_yields_normalised_records(self) -> None:
        """pages() yields lists of normalised dicts when page 0 has results."""
        raw_job = _make_raw_job()
        # page_count=1 means only page 0 exists.
        api_resp: dict[str, Any] = {"results": [raw_job], "page_count": 1}

        plugin = self._plugin()
        with patch.object(plugin, "_get_page", return_value=api_resp):
            pages = list(plugin.pages())

        assert len(pages) == 1
        assert len(pages[0]) == 1
        record = pages[0][0]
        assert record["source"] == "the_muse"
        assert record["source_id"] == str(raw_job["id"])

    def test_pages_stops_when_probe_returns_empty(self) -> None:
        """pages() yields nothing when page 0 (probe) returns no results."""
        plugin = self._plugin()
        with patch.object(
            plugin,
            "_get_page",
            return_value={"results": [], "page_count": 3},
        ):
            all_pages = list(plugin.pages())

        assert all_pages == []

    def test_pages_stops_early_on_empty_subsequent_page(self) -> None:
        """pages() stops when a page after the probe returns empty results."""
        raw_job = _make_raw_job()

        plugin = self._plugin()

        def fake_get_page(page: int) -> dict[str, Any]:
            # page 0 = probe+first page; page 1 = empty → stop early
            if page == 0:
                return {"results": [raw_job], "page_count": 5}
            return {"results": [], "page_count": 5}

        with patch.object(plugin, "_get_page", side_effect=fake_get_page):
            all_pages = list(plugin.pages())

        # Only page 0's results should be yielded; page 1 was empty
        assert len(all_pages) == 1

    def test_pages_respects_max_pages(self) -> None:
        """pages() yields at most max_pages pages."""
        raw_job = _make_raw_job()

        plugin = self._plugin(search=SearchParams(max_pages=2))

        def fake_get_page(page: int) -> dict[str, Any]:
            return {"results": [raw_job], "page_count": 10}

        with patch.object(plugin, "_get_page", side_effect=fake_get_page):
            all_pages = list(plugin.pages())

        # max_pages=2 → pages 0 and 1 yielded; page 2 not fetched
        assert len(all_pages) == 2

    def test_pages_fetches_multiple_pages(self) -> None:
        """pages() fetches page 0 and subsequent pages when page_count > 1."""
        raw_job = _make_raw_job()
        fetched: list[int] = []

        plugin = self._plugin()

        def fake_get_page(page: int) -> dict[str, Any]:
            fetched.append(page)
            return {"results": [raw_job], "page_count": 3}

        with patch.object(plugin, "_get_page", side_effect=fake_get_page):
            all_pages = list(plugin.pages())

        # page_count=3 → pages 0, 1, 2 fetched
        assert len(all_pages) == 3
        assert fetched == [0, 1, 2]

    def test_pages_is_iterator(self) -> None:
        """pages() returns an Iterator."""
        plugin = self._plugin()
        with patch.object(plugin, "_get_page", return_value={"results": [], "page_count": 0}):
            result = plugin.pages()
        assert hasattr(result, "__iter__")
        assert hasattr(result, "__next__")
