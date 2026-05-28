"""Arbeitnow job-board API plugin for job-aggregator.

Wraps the public Arbeitnow REST API (no authentication required).
Pagination is driven by ``meta.last_page`` returned on page 1.
Descriptions are delivered as HTML and are stripped to plain text.

API reference: https://www.arbeitnow.com/api/job-board-api
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, ClassVar

import requests
from bs4 import BeautifulSoup

from job_aggregator.base import JobSource
from job_aggregator.errors import ScrapeError
from job_aggregator.schema import SearchParams

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.arbeitnow.com/api/job-board-api"

# Arbeitnow uses inconsistent strings for full-time employment — some in
# English, some in German.  This map normalises them to the canonical
# "full_time" value.  Lookup is case-insensitive.  Unmapped values are
# passed through unchanged so genuinely part-time or contract roles are
# still identifiable downstream.
_CONTRACT_TIME_MAP: dict[str, str] = {
    "full-time permanent": "full_time",
    "berufserfahren": "full_time",  # German: "experienced professional"
    "professional / experienced": "full_time",
}


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode character entities.

    Uses BeautifulSoup so that entities (``&amp;``, ``&nbsp;``, etc.)
    are decoded correctly.  Words separated only by tags are joined with
    a single space to produce readable prose.

    Args:
        html: Raw HTML string from the Arbeitnow API.

    Returns:
        Plain-text string with all HTML markup removed.
    """
    return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)


def _unix_to_iso(ts: Any) -> str | None:
    """Convert a Unix timestamp to an ISO 8601 UTC string.

    Args:
        ts: Unix timestamp (int or float).  ``None`` or non-numeric
            values return ``None``.

    Returns:
        ISO 8601 string of the form ``"YYYY-MM-DDTHH:MM:SSZ"``, or
        ``None`` when the input cannot be converted.
    """
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OSError):
        return None


class Plugin(JobSource):
    """JobSource implementation for the Arbeitnow job-board API.

    Arbeitnow is a European tech job board offering a free, public API
    with no authentication required.  The API returns paginated results
    via ``?page=N``; page 1's ``meta.last_page`` is read once to
    determine the total page count.

    This plugin does **not** accept query, location, or country filters
    because the Arbeitnow API provides no such parameters — it returns
    all available listings in a fixed ordering.

    Attributes:
        SOURCE: ``"arbeitnow"``
        GEO_SCOPE: ``"regional"`` — EU-focused board; strong coverage
            of German-speaking markets and EU-remote roles.
        ACCEPTS_QUERY: ``"never"`` — no free-text query parameter.
        ACCEPTS_LOCATION: ``False`` — no location filter.
        ACCEPTS_COUNTRY: ``False`` — no country filter.
    """

    SOURCE = "arbeitnow"
    DISPLAY_NAME = "Arbeitnow"
    DESCRIPTION = (
        "European tech job board with a free, open API. "
        "Strong coverage of remote and EU-based software roles. "
        "No API key required."
    )
    HOME_URL = "https://www.arbeitnow.com"
    GEO_SCOPE = "regional"
    ACCEPTS_QUERY = "never"
    ACCEPTS_LOCATION = False
    ACCEPTS_COUNTRY = False
    RATE_LIMIT_NOTES = "Public API; no documented rate limit. Practical cap: ~1 req/s."
    REQUIRED_SEARCH_FIELDS: ClassVar[tuple[str, ...]] = ()

    def __init__(
        self,
        *,
        credentials: dict[str, Any] | None = None,
        search: SearchParams | None = None,
    ) -> None:
        """Initialise the Arbeitnow plugin.

        Arbeitnow requires no authentication; the ``credentials``
        argument is accepted for API uniformity but is silently ignored.

        Args:
            credentials: Accepted for interface uniformity; not used.
            search: :class:`~job_aggregator.schema.SearchParams` carrying
                ``max_pages``.  All other search fields are ignored
                because the Arbeitnow API has no query, location, or
                country filter.
        """
        super().__init__(credentials=credentials, search=search)
        self._max_pages: int | None = search.max_pages if search is not None else None
        self._cached_total_pages: int | None = None

    # ------------------------------------------------------------------
    # JobSource interface
    # ------------------------------------------------------------------

    @classmethod
    def settings_schema(cls) -> dict[str, Any]:
        """Return an empty settings schema.

        Arbeitnow requires no credentials.

        Returns:
            An empty dict — no fields to configure.
        """
        return {}

    def pages(self) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of raw Arbeitnow listing dicts.

        Fetches page 1 to determine ``meta.last_page``, then iterates
        through each subsequent page.  Stops early if:

        - a page returns zero results, or
        - ``max_pages`` has been reached (when set at construction time).

        Yields:
            A list of raw listing dicts as returned by the ``data``
            array in each Arbeitnow API response page.

        Raises:
            ScrapeError: If the first request (used to read total pages)
                fails with a non-200 status or a network error.
        """
        total = self._get_total_pages()
        limit = total if self._max_pages is None else min(total, self._max_pages)

        for page_num in range(1, limit + 1):
            raw_page = self._fetch_page(page_num)
            if not raw_page:
                logger.info(
                    "arbeitnow: page %d returned 0 results; stopping early",
                    page_num,
                )
                return
            yield raw_page

    def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map a raw Arbeitnow listing dict to the JobRecord shape.

        Field mapping (§9.3 audit):

        - ``slug``              → ``source_id``
        - ``title``             → ``title``
        - ``company_name``      → ``company``  (None when absent)
        - ``url``               → ``url``
        - ``created_at``        → ``posted_at`` (Unix → ISO 8601 UTC)
        - ``description``       → ``description`` (HTML stripped)
        - ``remote``            → ``remote_eligible``
        - ``location``/``remote`` → ``location``
          (explicit string, or ``"Remote"`` fallback, or None)
        - ``job_types[0]``      → ``contract_time``
          (normalised via ``_CONTRACT_TIME_MAP``; None when absent)
        - ``salary_min``        → None  # drop: not exposed by API
        - ``salary_max``        → None  # drop: not exposed by API
        - ``salary_currency``   → None  # drop: not exposed by API
        - ``salary_period``     → None  # drop: not exposed by API
        - ``contract_type``     → None  # drop: not exposed by API
        - ``tags``              → ``extra["tags"]``
        - ``visa_sponsorship``  → ``extra["visa_sponsorship"]``
        - ``language``          → ``extra["language"]``

        Args:
            raw: A single entry from the Arbeitnow ``data`` array.

        Returns:
            A dict conforming to the :class:`~job_aggregator.schema.JobRecord`
            TypedDict contract.
        """
        # --- location: prefer explicit string; fall back to "Remote" ---
        location_raw: str = raw.get("location", "") or ""
        remote: bool = bool(raw.get("remote", False))
        if location_raw:
            location: str | None = location_raw
        elif remote:
            location = "Remote"
        else:
            location = None

        # --- contract_time: first job_types entry, normalised ----------
        job_types: list[Any] = raw.get("job_types") or []
        raw_contract_time: str | None = job_types[0] if job_types else None
        contract_time: str | None = (
            _CONTRACT_TIME_MAP.get(raw_contract_time.lower(), raw_contract_time)
            if raw_contract_time is not None
            else None
        )

        # --- description: strip HTML; track provenance -----------------
        raw_desc: str = raw.get("description", "") or ""
        if raw_desc:
            description = _strip_html(raw_desc)
            description_source: str = "full"
        else:
            description = ""
            description_source = "none"

        # --- company: None when absent ---------------------------------
        company_raw = raw.get("company_name")
        company: str | None = company_raw if company_raw else None

        # --- extra: non-mapped fields preserved for downstream use -----
        extra: dict[str, Any] = {}
        for key in ("tags", "visa_sponsorship", "language"):
            if key in raw:
                extra[key] = raw[key]

        return {
            "source": self.SOURCE,
            "source_id": str(raw.get("slug", "")),
            "description_source": description_source,
            "title": raw.get("title", "") or "",
            "url": raw.get("url", "") or "",
            "posted_at": _unix_to_iso(raw.get("created_at")),
            "description": description,
            "company": company,
            "location": location,
            "salary_min": None,  # drop: Arbeitnow does not expose salary data
            "salary_max": None,  # drop: Arbeitnow does not expose salary data
            "salary_currency": None,  # drop: Arbeitnow does not expose salary data
            "salary_period": None,  # drop: Arbeitnow does not expose salary data
            "contract_type": None,  # drop: Arbeitnow does not expose this field
            "contract_time": contract_time,
            "remote_eligible": remote,
            "extra": extra if extra else None,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_total_pages(self) -> int:
        """Fetch page 1 and return ``meta.last_page`` (cached).

        Returns:
            Total page count from the API, or ``1`` as a safe fallback
            when the request fails or the ``meta`` key is absent.

        Raises:
            ScrapeError: On non-200 HTTP status from page 1.
        """
        if self._cached_total_pages is not None:
            return self._cached_total_pages

        try:
            response = requests.get(_BASE_URL, params={"page": 1}, timeout=15)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except requests.HTTPError as exc:
            raise ScrapeError(_BASE_URL, f"HTTP {exc.response.status_code}") from exc
        except (requests.RequestException, ValueError) as exc:
            logger.warning("arbeitnow: total_pages request failed: %s", exc)
            self._cached_total_pages = 1
            return 1

        meta = data.get("meta", {})
        last_page = meta.get("last_page", 1) if isinstance(meta, dict) else 1
        try:
            self._cached_total_pages = int(last_page)
        except (TypeError, ValueError):
            self._cached_total_pages = 1

        return self._cached_total_pages

    def _fetch_page(self, page: int) -> list[dict[str, Any]]:
        """Fetch a single page of raw Arbeitnow listings.

        On non-200 status or network/JSON error, logs a warning and
        returns an empty list so the caller can stop gracefully.

        Args:
            page: 1-based page number.

        Returns:
            List of raw listing dicts from the ``data`` array, or ``[]``
            on any error.
        """
        try:
            response = requests.get(_BASE_URL, params={"page": page}, timeout=15)
        except requests.RequestException as exc:
            logger.warning("arbeitnow: request failed (page %d): %s", page, exc)
            return []

        if response.status_code != 200:
            logger.warning(
                "arbeitnow: HTTP %d on page %d; skipping",
                response.status_code,
                page,
            )
            return []

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("arbeitnow: invalid JSON on page %d: %s", page, exc)
            return []

        result: list[dict[str, Any]] = data.get("data", [])
        return result
