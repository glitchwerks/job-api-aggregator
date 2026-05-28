"""VCR integration tests for the Jooble plugin.

These tests replay a recorded HTTP cassette so no real network call is made
in CI.  To re-record, delete the cassette and run with a live ``JOOBLE_API_KEY``
in the environment:

    $env:JOOBLE_API_KEY = "your-key"
    uv run pytest tests/sources/jooble/test_jooble_integration.py --record-mode=once

The cassette is scrubbed before commit: ``JOOBLE_API_KEY`` values in the
recorded YAML are replaced with the literal ``FAKE_JOOBLE_API_KEY`` placeholder.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from job_api_aggregator.plugins.jooble import Plugin
from job_api_aggregator.schema import SearchParams

# ---------------------------------------------------------------------------
# API key strategy
# ---------------------------------------------------------------------------
#
# The Jooble API key is embedded in the request URL:
#   https://jooble.org/api/{key}
#
# VCR matches cassette entries against the full request URI, so the key in
# the cassette must match what the plugin sends at replay time.
#
# Approach used here:
#   1. Record with the real key → cassettes contain the real key in the URI.
#   2. Scrub cassettes post-recording (replace real key with FAKE_JOOBLE_API_KEY).
#   3. Re-run tests using FAKE_JOOBLE_API_KEY → VCR replays successfully.
#
# To re-record cassettes:
#   1. Delete the yaml files under cassettes/.
#   2. Set JOOBLE_API_KEY to the real key in the environment.
#   3. Run: uv run pytest tests/sources/jooble/ --record-mode=once
#   4. Scrub: replace the real key with FAKE_JOOBLE_API_KEY in all cassettes.
#   5. Verify replay: uv run pytest tests/sources/jooble/test_jooble_integration.py
#
# In CI (no real key), JOOBLE_API_KEY is absent; the plugin uses the
# placeholder and VCR replays successfully from the scrubbed cassettes.

_FAKE_API_KEY = "FAKE_JOOBLE_API_KEY"
_LIVE_API_KEY = os.environ.get("JOOBLE_API_KEY", "")

# Use the live key only when it's available AND the cassettes do not yet
# exist (i.e. we are in record mode).  In replay (CI) mode, cassettes
# exist and contain the fake key, so we always use the fake key.
_CASSETTE_DIR = __import__("pathlib").Path(__file__).parent / "cassettes"
_USE_LIVE = bool(
    _LIVE_API_KEY and _LIVE_API_KEY != _FAKE_API_KEY and not any(_CASSETTE_DIR.glob("*.yaml"))
)
_API_KEY = _LIVE_API_KEY if _USE_LIVE else _FAKE_API_KEY


def _make_plugin() -> Plugin:
    """Construct a Plugin instance for integration tests.

    Uses the live API key only when recording new cassettes (detected by
    absence of existing cassette files and presence of ``JOOBLE_API_KEY``
    in the environment).  Otherwise uses the ``FAKE_JOOBLE_API_KEY``
    placeholder that matches the scrubbed cassette URIs.

    Returns:
        A Plugin instance configured for either recording or replay.
    """
    return Plugin(
        credentials={"api_key": _API_KEY},
        search=SearchParams(query="software engineer", max_pages=1),
    )


# ---------------------------------------------------------------------------
# VCR integration tests
# ---------------------------------------------------------------------------


@pytest.mark.vcr()
def test_pages_returns_at_least_one_listing() -> None:
    """pages() yields at least one listing from the live API (cassette replay).

    Verifies that the pagination loop runs without error and that each
    returned dict contains the minimum required keys.
    """
    plugin = _make_plugin()
    all_listings: list[dict[str, Any]] = []
    for page in plugin.pages():
        all_listings.extend(page)

    assert len(all_listings) > 0, "Expected at least one listing from Jooble"


@pytest.mark.vcr()
def test_normalised_listing_has_required_keys() -> None:
    """Every listing returned by pages() contains all required JobRecord keys.

    Checks that the normalised output from the VCR replay satisfies the
    minimum key contract expected by the orchestrator.
    """
    required_keys = {
        "source",
        "source_id",
        "description_source",
        "title",
        "url",
        "posted_at",
        "description",
    }

    plugin = _make_plugin()
    found_any = False
    for page in plugin.pages():
        for listing in page:
            for key in required_keys:
                assert key in listing, f"Listing missing required key {key!r}: {listing!r}"
            assert listing["source"] == "jooble"
            assert listing["description_source"] == "snippet"
            found_any = True
        break  # Only check first page

    assert found_any, "No listings returned by pages()"


@pytest.mark.vcr()
def test_total_pages_returns_positive_integer() -> None:
    """total_pages() returns a positive integer for a live search."""
    plugin = _make_plugin()
    total = plugin.total_pages()
    assert isinstance(total, int)
    assert total >= 1
