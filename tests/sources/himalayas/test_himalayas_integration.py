"""VCR integration tests for the Himalayas plugin.

These tests replay a recorded HTTP interaction so no live network is needed
in CI.  Re-record by deleting the cassette and running:

    uv run pytest tests/sources/himalayas/ --record-mode=once

The cassette is committed to the repo. No credentials need scrubbing —
the Himalayas API is public.
"""

from __future__ import annotations

import pytest

from job_api_aggregator.plugins.himalayas import Plugin
from job_api_aggregator.schema import SearchParams


@pytest.fixture()
def plugin() -> Plugin:
    """Return a Plugin instance with page_size=1 to match cassettes.

    Returns:
        A :class:`Plugin` configured for a single-listing first page.
    """
    return Plugin(search=SearchParams(extra={"page_size": 1}))


@pytest.mark.vcr()
def test_pages_yields_at_least_one_page(plugin: Plugin) -> None:
    """pages() yields at least one non-empty list from the live API."""
    pages = list(plugin.pages())
    assert len(pages) >= 1
    assert len(pages[0]) >= 1


@pytest.mark.vcr()
def test_normalised_record_has_required_fields(plugin: Plugin) -> None:
    """Each record from the first page satisfies the JobRecord identity contract."""
    first_page = next(iter(plugin.pages()))
    assert first_page, "Expected at least one raw job"

    record = plugin.normalise(first_page[0])

    # Identity fields
    assert record["source"] == "himalayas"
    assert isinstance(record["source_id"], str)
    assert record["source_id"]  # non-empty
    assert record["description_source"] in ("full", "snippet", "none")

    # Always-present fields
    assert isinstance(record["title"], str)
    assert isinstance(record["url"], str)
    # posted_at may be None if pubDate is absent in this listing
    assert isinstance(record["description"], str)


@pytest.mark.vcr()
def test_normalised_record_url_is_application_link(plugin: Plugin) -> None:
    """The 'url' field in a normalised record is not empty for real listings."""
    first_page = next(iter(plugin.pages()))
    record = plugin.normalise(first_page[0])
    assert record["url"], "Expected a non-empty url from applicationLink"
