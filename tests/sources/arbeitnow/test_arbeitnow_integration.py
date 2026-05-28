"""VCR integration tests for the arbeitnow plugin.

These tests replay real HTTP interactions recorded in the ``cassettes/``
directory.  No network I/O occurs during CI — the cassette is played
back by pytest-recording (vcrpy).

To re-record: ``uv run pytest tests/sources/arbeitnow/ --record-mode=once``
"""

from __future__ import annotations

import pytest

from job_api_aggregator.plugins.arbeitnow import Plugin
from job_api_aggregator.schema import SearchParams


@pytest.mark.vcr()
def test_first_page_returns_listings() -> None:
    """pages() yields at least one listing from the live API (cassette)."""
    plugin = Plugin(search=SearchParams(max_pages=1))
    pages = list(plugin.pages())
    assert len(pages) >= 1
    assert len(pages[0]) > 0


@pytest.mark.vcr()
def test_normalise_real_listing_has_required_fields() -> None:
    """normalise() on a real API listing produces all required JobRecord fields."""
    plugin = Plugin(search=SearchParams(max_pages=1))
    pages = list(plugin.pages())
    assert pages, "No pages returned — cassette may need re-recording"

    first_listing = pages[0][0]
    result = plugin.normalise(first_listing)

    # Identity fields
    assert result["source"] == "arbeitnow"
    assert result["source_id"]
    assert result["description_source"] in ("full", "snippet", "none")

    # Always-present fields
    assert isinstance(result["title"], str)
    assert isinstance(result["url"], str)
    assert isinstance(result["description"], str)
    # posted_at may be None if the listing lacks created_at
    assert "posted_at" in result

    # Salary fields are always None for this source
    assert result["salary_min"] is None
    assert result["salary_max"] is None
    assert result["salary_currency"] is None
    assert result["salary_period"] is None
    assert result["contract_type"] is None
