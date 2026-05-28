"""Schema types for the job-aggregator package.

Defines the structured data types used across the public API:

- :class:`PluginField` — describes one credential or configuration field
  that a plugin requires.
- :class:`PluginInfo` — a complete, serialisable description of a plugin
  built from its class-level metadata and ``settings_schema()`` return
  value.
- :class:`SearchParams` — the search parameters accepted by ``jobs``.
- :class:`JobRecord` — the normalized per-job output record (TypedDict).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

# ---------------------------------------------------------------------------
# PluginField
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PluginField:
    """Describes one credential or configuration field for a plugin.

    Used to build :attr:`PluginInfo.fields`.  The consuming application
    renders these fields as HTML inputs or CLI prompts — the package
    describes *what* is needed but does not render or validate.

    Attributes:
        name: Machine-readable field identifier (e.g. ``"app_id"``).
            Must be a valid Python identifier; used as the dict key in
            the credentials file.
        label: Human-readable display name for the field
            (e.g. ``"App ID"``).
        type: Input type hint for the consuming UI.  One of
            ``"text"``, ``"password"``, ``"email"``, ``"url"``,
            ``"number"``.
        required: ``True`` if the plugin cannot function without this
            field; ``False`` for optional enhancement fields.
        help_text: Optional explanatory text shown alongside the input,
            e.g. ``"Found in your Adzuna developer console."``
    """

    name: str
    label: str
    type: Literal["text", "password", "email", "url", "number"]
    required: bool = False
    help_text: str | None = None


# ---------------------------------------------------------------------------
# PluginInfo
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PluginInfo:
    """Complete, serialisable description of a registered plugin.

    Built from a :class:`~job_aggregator.base.JobSource` subclass's
    class-level metadata and its :meth:`settings_schema` return value.
    Consumed by ``list_plugins()`` / ``get_plugin()`` and emitted by
    ``job-aggregator sources``.

    Attributes:
        key: Unique plugin identifier (mirrors ``JobSource.SOURCE``).
        display_name: Human-readable plugin name
            (mirrors ``JobSource.DISPLAY_NAME``).
        description: Short description of the source
            (mirrors ``JobSource.DESCRIPTION``).
        home_url: URL for the source's public homepage
            (mirrors ``JobSource.HOME_URL``).
        geo_scope: Geographic coverage of the source
            (mirrors ``JobSource.GEO_SCOPE``).
        accepts_query: How the source handles free-text search queries
            (mirrors ``JobSource.ACCEPTS_QUERY``).
        accepts_location: Whether the source accepts a location filter
            (mirrors ``JobSource.ACCEPTS_LOCATION``).
        accepts_country: Whether the source accepts a country filter
            (mirrors ``JobSource.ACCEPTS_COUNTRY``).
        rate_limit_notes: Human-readable rate-limit description
            (mirrors ``JobSource.RATE_LIMIT_NOTES``).
        required_search_fields: Field names that must be present in
            :class:`SearchParams` for this plugin to run successfully
            (mirrors ``JobSource.REQUIRED_SEARCH_FIELDS``).
        fields: Credential / config field definitions built from
            ``JobSource.settings_schema()``.
        requires_credentials: ``True`` if any field in :attr:`fields`
            is marked ``required=True``.  Derived property.
    """

    key: str
    display_name: str
    description: str
    home_url: str
    geo_scope: str
    accepts_query: str
    accepts_location: bool
    accepts_country: bool
    rate_limit_notes: str
    required_search_fields: tuple[str, ...]
    fields: tuple[PluginField, ...]

    @property
    def requires_credentials(self) -> bool:
        """Return True if any field is marked required.

        Returns:
            ``True`` when at least one :class:`PluginField` in
            :attr:`fields` has ``required=True``; ``False`` otherwise
            (including when :attr:`fields` is empty).
        """
        return any(f.required for f in self.fields)


# ---------------------------------------------------------------------------
# SearchParams
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchParams:
    """Parameters that control a ``job-aggregator jobs`` run.

    All fields are optional; omitted fields use sensible defaults.
    Pass an instance to ``make_enabled_sources()`` or the ``jobs``
    orchestrator.

    Attributes:
        query: Free-text search query (e.g. ``"python developer"``).
            Ignored by plugins where ``accepts_query="never"``.
        location: Free-text location hint (e.g. ``"Atlanta, GA"``).
            Used as a search parameter by plugins that support it; no
            client-side geo filtering is performed.
        country: ISO 3166-1 alpha-2 country code (e.g. ``"us"``).
            Passed to plugins that accept a country filter.
        hours: Lookback window in hours.  Only listings posted within
            the last ``hours`` hours are returned.  Defaults to 168
            (one week).
        max_pages: Per-source page cap.  ``None`` means each plugin
            uses its own default maximum.
        extra: Plugin-specific freeform configuration, symmetric with
            :attr:`JobRecord.extra`.  Intended for parameters that are
            meaningful only to a single plugin (e.g. Remotive's
            ``category`` filter, Himalayas' ``page_size``, Jobicy's
            ``count``).  Not covered by schema versioning; consumers
            depend on ``extra.*`` at their own risk.
    """

    query: str | None = None
    location: str | None = None
    country: str | None = None
    hours: int = 168
    max_pages: int | None = None
    extra: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# JobRecord
# ---------------------------------------------------------------------------

# PEP 655 Required / NotRequired are available in Python 3.11+ via typing.
# We use NotRequired for optional fields so the TypedDict is total=True
# for the required base and uses NotRequired for everything else — cleaner
# than the two-class inheritance pattern and compatible with mypy --strict.


class JobRecord(TypedDict, total=False):
    """Normalised per-job output record.

    Produced by plugin ``normalise()`` calls and emitted by the ``jobs``
    orchestrator.  Consumed by ``hydrate`` (which may update
    ``description`` and ``description_source``).

    Three field categories match spec §9.3:

    **Identity (always present, validation-checked):**
    ``source``, ``source_id``, ``description_source``

    **Always-present (always serialised, may be empty per stated rules):**
    ``title``, ``url``, ``posted_at``, ``description``

    **Optional (serialised, often null):**
    ``company``, ``location``, ``salary_min``, ``salary_max``,
    ``salary_currency``, ``salary_period``, ``contract_type``,
    ``contract_time``, ``remote_eligible``

    **Source-specific blob:**
    ``extra`` — explicitly *not* covered by schema versioning; consumers
    depend on ``extra.*`` at their own risk.

    Notes:
        Empty string means "source provided an empty value".
        ``None`` means "source did not provide this key at all".
    """

    # ---- Identity (required) ----
    source: str
    source_id: str
    description_source: Literal["full", "snippet", "none"]

    # ---- Always-present (required) ----
    title: str
    url: str
    posted_at: str | None
    description: str

    # ---- Optional ----
    company: str | None
    location: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_period: Literal["annual", "monthly", "hourly"] | None
    contract_type: str | None
    contract_time: str | None
    remote_eligible: bool | None

    # ---- Source-specific blob ----
    extra: dict[str, Any] | None
