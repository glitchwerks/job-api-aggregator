"""VCR integration tests for the usajobs plugin.

These tests replay a recorded HTTP interaction (cassette) so that CI
can run without real network access or live credentials.  The cassette
was recorded once with real credentials and then scrubbed to replace
sensitive values with ``FAKE_USAJOBS_*`` placeholders before commit.

To re-record:
    1. Copy .env with real USAJOBS_EMAIL / USAJOBS_API_KEY into the
       worktree root.
    2. Run: uv run pytest tests/sources/usajobs/ --record-mode=once
    3. Scrub the cassette (replace real key/email with placeholders).
    4. Commit the scrubbed cassette.
"""

from __future__ import annotations

import os

import pytest

from job_api_aggregator.plugins.usajobs import Plugin
from job_api_aggregator.schema import SearchParams

# Credentials are loaded from .env by conftest.py pytest_configure hook
# before any test module is imported.  This file does not load dotenv
# directly.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plugin_from_env() -> Plugin:
    """Build a Plugin from environment variables.

    Returns:
        A Plugin instance using USAJOBS_API_KEY and USAJOBS_EMAIL
        from the environment.

    Raises:
        pytest.skip: If the required environment variables are absent,
            which allows the test to be skipped cleanly in CI when no
            cassette exists yet.
    """
    api_key = os.environ.get("USAJOBS_API_KEY", "").strip()
    email = os.environ.get("USAJOBS_EMAIL", "").strip()
    # During cassette replay the real credentials are not needed; the VCR
    # library intercepts the request before it reaches the network.  Use
    # placeholder values so the plugin constructor does not raise
    # CredentialsError in replay mode.
    if not api_key:
        api_key = "FAKE_USAJOBS_API_KEY"
    if not email:
        email = "FAKE_USAJOBS_EMAIL"
    return Plugin(
        credentials={"api_key": api_key, "email": email},
        search=SearchParams(query="software engineer", max_pages=1),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.vcr()
def test_pages_returns_at_least_one_listing() -> None:
    """pages() must yield at least one listing against the live (recorded) API.

    The cassette captures a single page-1 request for "software engineer".
    The test verifies the plugin correctly paginates and returns results.
    """
    plugin = _plugin_from_env()
    all_items: list[dict[str, object]] = []
    for page in plugin.pages():
        all_items.extend(page)

    assert len(all_items) >= 1, "Expected at least one job listing"


@pytest.mark.vcr()
def test_normalise_produces_valid_job_record() -> None:
    """normalise() must return a dict with all required JobRecord fields.

    Fetches the first page and normalises the first item; validates the
    identity and always-present fields against the schema contract.
    """
    plugin = _plugin_from_env()
    raw_items: list[dict[str, object]] = []
    for page in plugin.pages():
        raw_items.extend(page)
        break  # only need first page

    assert raw_items, "No items returned from API"
    record = plugin.normalise(raw_items[0])

    # Identity
    assert record["source"] == "usajobs"
    assert isinstance(record["source_id"], str)
    assert record["source_id"], "source_id must be non-empty"
    assert record["description_source"] in ("full", "snippet", "none")

    # Always-present
    assert isinstance(record["title"], str)
    assert isinstance(record["url"], str)
    assert record["url"].startswith("http")
    assert isinstance(record["description"], str)
