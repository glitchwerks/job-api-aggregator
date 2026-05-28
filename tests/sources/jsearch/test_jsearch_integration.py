"""VCR integration tests for the jsearch plugin.

Cassettes are recorded once against the real RapidAPI endpoint and then
replayed on subsequent runs.  No network access is needed after recording.
Credentials are read from the environment (``JSEARCH_API_KEY``).
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_key() -> str:
    """Return the JSearch API key, skipping the test if it is not set."""
    key = os.environ.get("JSEARCH_API_KEY", "")
    if not key:
        pytest.skip("JSEARCH_API_KEY not set — skipping integration test")
    return key


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.vcr()
def test_pages_returns_results(api_key: str) -> None:
    """pages() yields at least one page with at least one normalised record."""
    from job_api_aggregator.plugins.jsearch import Plugin
    from job_api_aggregator.schema import SearchParams

    plugin = Plugin(
        credentials={"api_key": api_key},
        search=SearchParams(query="python developer", location="Atlanta, GA", max_pages=1),
    )
    pages = list(plugin.pages())
    assert len(pages) >= 1
    first_page = pages[0]
    assert isinstance(first_page, list)
    assert len(first_page) >= 1


@pytest.mark.vcr()
def test_normalised_record_has_required_fields(api_key: str) -> None:
    """Every record from pages() has the three identity fields filled."""
    from job_api_aggregator.plugins.jsearch import Plugin
    from job_api_aggregator.schema import SearchParams

    plugin = Plugin(
        credentials={"api_key": api_key},
        search=SearchParams(query="python developer", location="Atlanta, GA", max_pages=1),
    )
    for page in plugin.pages():
        for record in page:
            assert record.get("source") == "jsearch"
            assert record.get("source_id"), "source_id must be non-empty"
            assert record.get("description_source") in ("full", "snippet", "none")
            break  # one record is enough
        break
