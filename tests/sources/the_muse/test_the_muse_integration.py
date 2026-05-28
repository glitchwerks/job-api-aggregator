"""VCR integration tests for the the_muse plugin.

These tests replay a recorded HTTP cassette so no real network call is
made during CI.  Record (or re-record) the cassette by running:

    uv run pytest tests/sources/the_muse/ --record-mode=once

The cassette is stored at:
    tests/sources/the_muse/cassettes/test_live_search.yaml
"""

from __future__ import annotations

import pytest


@pytest.mark.vcr()
def test_live_search_returns_records() -> None:
    """Plugin returns at least one normalised record against live API cassette.

    Verifies end-to-end: the plugin constructs the correct URL, parses the
    response, and normalises at least one record with the required identity
    fields populated.
    """
    from job_api_aggregator.plugins.the_muse import Plugin
    from job_api_aggregator.schema import SearchParams

    plugin = Plugin(search=SearchParams(query="Software Engineer", max_pages=1))
    all_records: list[dict] = []  # type: ignore[type-arg]
    for page in plugin.pages():
        all_records.extend(page)

    assert len(all_records) > 0, "Expected at least one job listing"

    first = all_records[0]
    # Identity fields — always required
    assert first["source"] == "the_muse"
    assert isinstance(first["source_id"], str)
    assert first["source_id"] != ""
    assert first["description_source"] == "full"

    # Always-present fields
    assert isinstance(first["title"], str)
    assert isinstance(first["url"], str)
    assert first["url"].startswith("https://")
    assert isinstance(first["description"], str)
    # description should be non-empty (API returns real HTML)
    assert len(first["description"]) > 0

    # Salary fields must all be None (The Muse provides no salary data)
    assert first["salary_min"] is None
    assert first["salary_max"] is None
    assert first["salary_currency"] is None
    assert first["salary_period"] is None

    # contract_type and remote_eligible not in API
    assert first["contract_type"] is None
    assert first["remote_eligible"] is None
