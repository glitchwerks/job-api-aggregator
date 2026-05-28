"""VCR integration tests for the Remotive plugin.

Uses pytest-recording (vcrpy) cassettes to replay a real API response
without making live network calls.  Record once with::

    uv run pytest tests/sources/remotive/test_remotive_integration.py \\
        --record-mode=once

No scrubbing is required — Remotive is a public API with no credentials.
"""

from __future__ import annotations

import pytest

from job_api_aggregator.plugins.remotive import Plugin
from job_api_aggregator.schema import SearchParams


@pytest.mark.vcr()
def test_pages_returns_listings_from_cassette() -> None:
    """pages() returns at least one normalised listing via cassette.

    Verifies the full request→parse→normalise round-trip against a
    recorded real response.
    """
    plugin = Plugin(search=SearchParams(query="python", max_pages=5))
    pages = list(plugin.pages())

    assert len(pages) >= 1, "Expected at least one page of results"
    records = pages[0]
    assert len(records) >= 1, "Expected at least one listing"

    first = records[0]
    # Identity fields
    assert first["source"] == "remotive"
    assert isinstance(first["source_id"], str)
    assert first["source_id"] != ""
    assert first["description_source"] == "snippet"

    # Always-present fields
    assert isinstance(first["title"], str)
    assert isinstance(first["url"], str)
    assert isinstance(first["description"], str)
    # HTML must be stripped
    assert "<" not in first["description"]

    # remote_eligible must be True for all Remotive listings
    assert first["remote_eligible"] is True


@pytest.mark.vcr()
def test_pages_with_category_filter() -> None:
    """pages() works when a category filter is supplied."""
    plugin = Plugin(
        search=SearchParams(
            max_pages=3,
            extra={"category": "software-dev"},
        )
    )
    pages = list(plugin.pages())

    assert len(pages) >= 1
    for record in pages[0]:
        assert record["source"] == "remotive"
