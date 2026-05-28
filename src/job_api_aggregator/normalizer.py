"""Normalizer for plugin ``normalise()`` output → validated ``JobRecord``.

Converts the raw dict returned by a plugin's ``normalise()`` method into a
fully validated :class:`~job_aggregator.schema.JobRecord`.  Key
responsibilities:

- Enforces that identity fields ``source`` and ``source_id`` are present.
- Renames ``redirect_url`` → ``url`` (spec §9.1).
- Backfills ``posted_at`` from ``created_at`` when ``posted_at`` is absent
  or ``None``; emits a stderr warning when both are unavailable (spec §9.1).
- Preserves the empty-string vs. ``None`` distinction for all fields
  (spec §9.4).
- Classifies ``description_source`` using the §9.6 truth table.
- Scopes any ``extra`` dict under ``extra[source]`` to form the
  ``extra.<plugin_key>.*`` blob (spec §9.5).

Public constants:
    :data:`SCRAPE_MIN_LENGTH` — minimum description length (in characters)
    for a description to qualify as "full".  Consumed by the ``hydrate``
    orchestrator and the parity test in ``job-matcher-pr``.
"""

from __future__ import annotations

import sys
from typing import Any, Literal

from job_aggregator.schema import JobRecord

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------
# Canonical definition lives in scraping.py (spec §9.6).  Re-exported here
# so that existing callers of normalizer.SCRAPE_MIN_LENGTH keep working.
from job_aggregator.scraping import SCRAPE_MIN_LENGTH as SCRAPE_MIN_LENGTH

# ---------------------------------------------------------------------------
# description_source classifier — §9.6 truth table (jobs orchestrator rows)
# ---------------------------------------------------------------------------

DescriptionSource = Literal["full", "snippet", "none"]


def classify_description_source(
    *,
    skip_scrape: bool,
    description_is_full: bool,
    description: str,
) -> DescriptionSource:
    """Classify the ``description_source`` field for the *jobs* orchestrator.

    Implements the jobs-orchestrator portion of the §9.6 truth table exactly.
    Row 5 is evaluated **first** as a terminal override:

    +-------------+--------------------+-----------+---------+
    | skip_scrape | description_is_full| len>=MIN  | Result  |
    +=============+====================+===========+=========+
    | n/a         | n/a                | empty     | "none"  |  ← checked first
    +-------------+--------------------+-----------+---------+
    | True        | True               | True      | "full"  |
    +-------------+--------------------+-----------+---------+
    | True        | True               | False     | "snippet"|
    +-------------+--------------------+-----------+---------+
    | True        | False              | n/a       | "snippet"|
    +-------------+--------------------+-----------+---------+
    | False       | n/a                | n/a       | "snippet"|
    +-------------+--------------------+-----------+---------+

    Row 5 is a **terminal override**: if the description is empty the result
    is ``"none"`` unconditionally, regardless of ``skip_scrape`` or
    ``description_is_full``.  This check runs first, before rows 1-4.

    Args:
        skip_scrape: ``True`` if the plugin signals that scraping should
            be skipped for this record.
        description_is_full: ``True`` if the plugin asserts that the
            description it provided is already the complete text.
        description: The description text as returned by the plugin.

    Returns:
        One of ``"full"``, ``"snippet"``, or ``"none"``.
    """
    # Row 5 (terminal override): empty description → "none" unconditionally.
    # Checked first so that rows 3 and 4 cannot accidentally return "snippet"
    # when there is literally no text to snippet.
    if not description.strip():
        return "none"

    # Row 4: skip_scrape=False → always "snippet" regardless of other flags.
    if not skip_scrape:
        return "snippet"

    # skip_scrape is True from here onward.

    # Row 3: skip_scrape=True, description_is_full=False → "snippet".
    if not description_is_full:
        return "snippet"

    # skip_scrape=True, description_is_full=True from here onward.

    # Row 1 vs Row 2: length gate.
    if len(description) >= SCRAPE_MIN_LENGTH:
        return "full"

    return "snippet"


# ---------------------------------------------------------------------------
# normalize() — main entry point
# ---------------------------------------------------------------------------


def normalize(plugin_output: dict[str, Any]) -> JobRecord:
    """Convert a plugin's ``normalise()`` output dict into a ``JobRecord``.

    The *plugin_output* dict is the raw return value from a concrete
    :class:`~job_aggregator.base.JobSource` subclass's ``normalise()``
    method.  This function:

    1. Validates that the identity fields ``source`` and ``source_id``
       are present (raises :exc:`ValueError` if either is missing).
    2. Renames ``redirect_url`` → ``url``; also accepts ``url`` directly.
    3. Backfills ``posted_at`` from ``created_at`` when ``posted_at`` is
       absent or ``None``.  Emits a warning to ``stderr`` when both are
       unavailable (spec §9.1).
    4. Preserves empty strings as empty strings (not ``None``) for all
       always-present fields (spec §9.4).
    5. Classifies ``description_source`` via :func:`classify_description_source`.
    6. Scopes the ``extra`` dict under ``extra[source].*`` (spec §9.5).

    Args:
        plugin_output: A dict returned by a plugin's ``normalise()`` method.
            Must contain at minimum ``source`` and ``source_id``.

    Returns:
        A fully populated :class:`~job_aggregator.schema.JobRecord`.

    Raises:
        ValueError: If ``source`` or ``source_id`` is absent from
            *plugin_output*.
    """
    # ------------------------------------------------------------------
    # 1. Validate identity fields.
    # ------------------------------------------------------------------
    if "source" not in plugin_output:
        raise ValueError("Plugin output is missing required identity field 'source'.")
    if "source_id" not in plugin_output:
        raise ValueError("Plugin output is missing required identity field 'source_id'.")

    source: str = str(plugin_output["source"])
    source_id: str = str(plugin_output["source_id"])

    # ------------------------------------------------------------------
    # 2. Resolve url: prefer 'url', fall back to 'redirect_url'.
    # ------------------------------------------------------------------
    url_raw = plugin_output["url"] if "url" in plugin_output else plugin_output.get("redirect_url")
    # Preserve empty string; coerce None to "".
    url: str = url_raw if isinstance(url_raw, str) else ""

    # ------------------------------------------------------------------
    # 3. Resolve posted_at with backfill from created_at.
    # ------------------------------------------------------------------
    posted_at_raw = plugin_output.get("posted_at")
    posted_at: str | None

    if posted_at_raw:
        posted_at = str(posted_at_raw)
    else:
        created_at_raw = plugin_output.get("created_at")
        if created_at_raw:
            posted_at = str(created_at_raw)
        else:
            posted_at = None
            print(
                f"WARNING: record source={source!r} source_id={source_id!r} "
                "has no parseable posted_at or created_at; "
                "posted_at will be null.",
                file=sys.stderr,
            )

    # ------------------------------------------------------------------
    # 4. Always-present string fields (preserve empty string).
    # ------------------------------------------------------------------
    title_raw = plugin_output.get("title")
    title: str = title_raw if isinstance(title_raw, str) else ""

    description_raw = plugin_output.get("description")
    description: str = description_raw if isinstance(description_raw, str) else ""

    # ------------------------------------------------------------------
    # 5. Classify description_source.
    # ------------------------------------------------------------------
    skip_scrape: bool = bool(plugin_output.get("skip_scrape", False))
    description_is_full: bool = bool(plugin_output.get("description_is_full", False))
    description_source: DescriptionSource = classify_description_source(
        skip_scrape=skip_scrape,
        description_is_full=description_is_full,
        description=description,
    )

    # ------------------------------------------------------------------
    # 6. Optional fields — preserve empty string / None distinction.
    # ------------------------------------------------------------------
    def _optional_str(key: str) -> str | None:
        """Return str value or None; preserve empty string as empty string."""
        if key not in plugin_output:
            return None
        val = plugin_output[key]
        if val is None:
            return None
        return str(val)

    def _optional_float(key: str) -> float | None:
        """Return float value or None."""
        val = plugin_output.get(key)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _optional_bool(key: str) -> bool | None:
        """Return bool value or None."""
        val = plugin_output.get(key)
        if val is None:
            return None
        return bool(val)

    company = _optional_str("company")
    location = _optional_str("location")
    salary_min = _optional_float("salary_min")
    salary_max = _optional_float("salary_max")
    salary_currency = _optional_str("salary_currency")

    # salary_period must be a valid Literal or None.
    salary_period_raw = plugin_output.get("salary_period")
    salary_period: Literal["annual", "monthly", "hourly"] | None
    if salary_period_raw in ("annual", "monthly", "hourly"):
        salary_period = salary_period_raw
    else:
        salary_period = None

    contract_type = _optional_str("contract_type")
    contract_time = _optional_str("contract_time")
    remote_eligible = _optional_bool("remote_eligible")

    # ------------------------------------------------------------------
    # 7. Scope extra blob under extra[source].
    # ------------------------------------------------------------------
    extra_raw = plugin_output.get("extra")
    extra: dict[str, Any] | None = (
        {source: extra_raw} if extra_raw and isinstance(extra_raw, dict) else None
    )

    # ------------------------------------------------------------------
    # Assemble and return the JobRecord.
    # ------------------------------------------------------------------
    record: JobRecord = {
        # Identity
        "source": source,
        "source_id": source_id,
        "description_source": description_source,
        # Always-present
        "title": title,
        "url": url,
        "posted_at": posted_at,
        "description": description,
        # Optional
        "company": company,
        "location": location,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "salary_period": salary_period,
        "contract_type": contract_type,
        "contract_time": contract_time,
        "remote_eligible": remote_eligible,
        # Source-specific blob
        "extra": extra,
    }
    return record
