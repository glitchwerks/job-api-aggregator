"""VCR integration tests for the jobicy plugin.

Uses pytest-recording (vcrpy under the hood) to replay a recorded HTTP
cassette so no live network calls are made during CI.

Record cassettes once with::

    uv run pytest tests/sources/jobicy/test_jobicy_integration.py --record-mode=once

Cassette files are stored in ``tests/sources/jobicy/cassettes/``.
"""

from __future__ import annotations

import pytest

from job_api_aggregator.plugins.jobicy import Plugin
from job_api_aggregator.schema import SearchParams


@pytest.mark.vcr()
def test_pages_yields_at_least_one_listing() -> None:
    """pages() must yield at least one non-empty list from the live API.

    The cassette captures a real Jobicy response.  The test verifies
    the plugin can successfully call the API and return results without
    raising.
    """
    plugin = Plugin(search=SearchParams(extra={"count": 5}))
    pages = list(plugin.pages())
    assert len(pages) >= 1, "Expected at least one page of results"
    assert len(pages[0]) >= 1, "Expected at least one listing on first page"


@pytest.mark.vcr()
def test_normalise_produces_valid_record_shape() -> None:
    """pages() + normalise() round-trip produces a valid JobRecord shape.

    Walks the first listing returned by the cassette and checks that all
    identity and always-present fields are populated.
    """
    plugin = Plugin(search=SearchParams(extra={"count": 5}))
    pages = list(plugin.pages())
    assert pages, "No pages returned from cassette"

    first_listing = pages[0][0]
    record = plugin.normalise(first_listing)

    # Identity fields (always required)
    assert record["source"] == "jobicy"
    assert isinstance(record["source_id"], str)
    assert record["source_id"], "source_id must be non-empty"
    assert record["description_source"] in ("full", "snippet", "none")

    # Always-present fields
    assert isinstance(record["title"], str)
    assert isinstance(record["url"], str)
    assert isinstance(record["description"], str)

    # remote_eligible must be True for all Jobicy listings
    assert record["remote_eligible"] is True
