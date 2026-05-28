"""VCR integration tests for the RemoteOK plugin.

These tests replay recorded HTTP cassettes — no live network calls are made
during CI.  To re-record, delete the cassette file and run:

    uv run pytest tests/sources/remoteok/test_remoteok_integration.py \\
        --record-mode=once

Cassettes are stored under ``tests/sources/remoteok/cassettes/``.

Design note: ``pages()`` yields *raw* dicts from the API; ``normalise()``
is called per-record by the orchestrator.  The integration tests exercise
both layers together, mirroring real production usage.
"""

from __future__ import annotations

import pytest

from job_api_aggregator.plugins.remoteok import Plugin


@pytest.mark.vcr()
def test_pages_returns_at_least_one_listing() -> None:
    """pages() + normalise() must produce valid records from a live response.

    Verifies that a cassette-replayed API response is parsed and normalised
    into a non-empty list of dicts that all contain the required identity
    and always-present fields.
    """
    plugin = Plugin()
    all_records = [plugin.normalise(raw) for page in plugin.pages() for raw in page]

    assert len(all_records) >= 1, "Expected at least one normalised record"

    required_keys = {
        "source",
        "source_id",
        "description_source",
        "title",
        "url",
        "posted_at",
        "description",
    }
    for record in all_records:
        assert required_keys.issubset(record.keys()), (
            f"Record missing required keys: {required_keys - record.keys()}"
        )
        assert record["source"] == "remoteok"
        assert record["description_source"] == "snippet"
        assert record["remote_eligible"] is True


@pytest.mark.vcr()
def test_pages_skips_metadata_element() -> None:
    """pages() must not include the leading API metadata object.

    The RemoteOK API response starts with a metadata dict (no 'id' or
    'position' keys).  This test confirms it is filtered out so all raw
    dicts yielded have both 'id' and 'position' keys.
    """
    plugin = Plugin()
    raw_pages = list(plugin.pages())
    all_raw = [raw for page in raw_pages for raw in page]

    for raw in all_raw:
        assert "id" in raw and "position" in raw, (
            "Metadata element leaked through — expected only job listing dicts"
        )


@pytest.mark.vcr()
def test_normalise_html_stripped_in_description() -> None:
    """Descriptions from cassette-replayed results must not contain HTML tags."""
    plugin = Plugin()
    all_records = [plugin.normalise(raw) for page in plugin.pages() for raw in page]

    records_with_desc = [r for r in all_records if r.get("description")]
    assert len(records_with_desc) >= 1, "Expected at least one record with a description"

    for record in records_with_desc:
        assert "<" not in record["description"], (
            f"HTML found in description for record {record['source_id']!r}"
        )
