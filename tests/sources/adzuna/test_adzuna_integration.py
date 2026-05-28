"""VCR integration tests for the Adzuna plugin.

Cassettes are recorded once against the live API and then replayed on
every subsequent CI run.  Credentials are never stored in cassettes —
see the brief for scrubbing instructions.

Run with real credentials to re-record:

    $env:ADZUNA_APP_ID="<id>"; $env:ADZUNA_APP_KEY="<key>"
    uv run pytest tests/sources/adzuna/test_adzuna_integration.py --record-mode=once
"""

from __future__ import annotations

import os

import pytest

from job_api_aggregator.plugins.adzuna import Plugin
from job_api_aggregator.schema import SearchParams

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def credentials() -> dict[str, str]:
    """Return credentials from env vars or VCR-safe placeholders.

    When cassettes are being replayed, the actual values sent in the
    request are replaced by the scrubbed cassette values, so real creds
    are only needed during --record-mode=once runs.
    """
    return {
        "app_id": os.environ.get("ADZUNA_APP_ID", "FAKE_APP_ID"),
        "app_key": os.environ.get("ADZUNA_APP_KEY", "FAKE_APP_KEY"),
    }


@pytest.fixture()
def plugin(credentials: dict[str, str]) -> Plugin:
    """Return a Plugin configured for a minimal GB search."""
    return Plugin(
        credentials=credentials,
        search=SearchParams(
            query="python developer",
            country="gb",
            max_pages=1,
            extra={"results_per_page": 5},
        ),
    )


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.vcr()
def test_pages_returns_at_least_one_record(plugin: Plugin) -> None:
    """pages() must yield at least one non-empty page of results."""
    all_records: list[dict[str, object]] = []
    for page in plugin.pages():
        all_records.extend(page)

    assert len(all_records) >= 1, "Expected at least one raw result from Adzuna"


@pytest.mark.vcr()
def test_normalised_record_has_required_fields(plugin: Plugin) -> None:
    """Each normalised record must contain all identity and always-present fields."""
    required_fields = (
        "source",
        "source_id",
        "description_source",
        "title",
        "url",
        "posted_at",
        "description",
    )
    for page in plugin.pages():
        for raw in page:
            record = plugin.normalise(raw)
            for field in required_fields:
                assert field in record, f"Normalised record missing required field: {field!r}"
        break  # Only check first page in integration tests.


@pytest.mark.vcr()
def test_normalised_source_is_adzuna(plugin: Plugin) -> None:
    """Every normalised record must carry source='adzuna'."""
    for page in plugin.pages():
        for raw in page:
            record = plugin.normalise(raw)
            assert record["source"] == "adzuna"
        break
