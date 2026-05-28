"""Himalayas job-source plugin.

Wraps the Himalayas Jobs REST API (offset-based pagination) and normalises
raw response dicts to the :class:`~job_aggregator.schema.JobRecord` contract.

API endpoint: GET https://himalayas.app/jobs/api?limit=<n>&offset=<n>
Response shape: ``{"jobs": [...], "total": N}``

No authentication is required. The API is public and free.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from math import ceil
from typing import Any

import requests
from bs4 import BeautifulSoup

from job_aggregator.base import JobSource
from job_aggregator.errors import ScrapeError
from job_aggregator.schema import SearchParams

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_API_URL = "https://himalayas.app/jobs/api"
_DEFAULT_PAGE_SIZE = 100
_REQUEST_TIMEOUT = 15  # seconds

#: Threshold separating Unix-seconds from Unix-milliseconds timestamps.
#: Values below this are treated as seconds; at or above, as milliseconds.
_MS_THRESHOLD = 10_000_000_000

#: Maps Himalayas ``employmentType`` values to canonical ``contract_time``
#: strings.  Includes both the standard underscore form (``"FULL_TIME"``)
#: and the space-separated form (``"FULL TIME"``) seen in some API responses
#: per legacy issue #239.
_JOB_TYPE_MAP: dict[str, str] = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACT": "contract",
    "FREELANCE": "freelance",
    "INTERNSHIP": "internship",
    # Space-separated variants (some API responses use spaces — legacy #239)
    "FULL TIME": "full_time",
    "PART TIME": "part_time",
}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _strip_html(text: str) -> str:
    """Strip HTML tags from *text* using BeautifulSoup.

    If the string contains no ``<`` character the input is returned
    unchanged, preserving plain-text and Markdown descriptions.

    Args:
        text: Raw description string, possibly containing HTML markup.

    Returns:
        Plain-text string with HTML tags removed, or the original string
        when no HTML tags are detected.
    """
    if "<" not in text:
        return text
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)


def _parse_pub_date(value: int | str | None) -> str | None:
    """Convert a Himalayas ``pubDate`` value to an ISO 8601 string.

    Himalayas returns ``pubDate`` as an ISO 8601 string, a Unix-seconds
    integer, or a Unix-milliseconds integer.  Integers below
    :data:`_MS_THRESHOLD` (10 billion) are treated as seconds; at or above
    that threshold they are divided by 1000 first.  ``None`` passes through
    unchanged.

    Args:
        value: ISO 8601 string, Unix-seconds int, Unix-milliseconds int,
            or ``None``.

    Returns:
        ISO 8601 string (e.g. ``"2026-01-02T12:34:56Z"``) or ``None``.
    """
    if value is None:
        return None
    if isinstance(value, int):
        ts_seconds = value / 1000 if value >= _MS_THRESHOLD else float(value)
        return datetime.fromtimestamp(ts_seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    # String — pass through unchanged (assume already ISO 8601).
    return str(value)


def _map_employment_type(job_type: str | None) -> str | None:
    """Map a Himalayas ``employmentType`` to the canonical ``contract_time``.

    Known values are looked up in :data:`_JOB_TYPE_MAP`.  Unknown values
    are lower-cased and spaces are replaced with underscores so that future
    API values degrade to a usable snake_case token rather than a string
    with spaces that fails downstream normalisation.

    Args:
        job_type: Himalayas employment-type string, e.g. ``"FULL_TIME"``
            or ``"Full Time"``.

    Returns:
        Canonical contract-time string, or ``None`` if *job_type* is falsy.
    """
    if not job_type:
        return None
    return _JOB_TYPE_MAP.get(job_type, job_type.lower().replace(" ", "_"))


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class Plugin(JobSource):
    """JobSource implementation for the Himalayas Jobs REST API.

    Handles offset-based pagination, HTML stripping of job descriptions,
    and normalisation of raw Himalayas dicts to the
    :class:`~job_aggregator.schema.JobRecord` TypedDict contract.

    Himalayas is a remote-first tech job board.  The public API requires
    no authentication and has no published hard rate limits.

    Attributes:
        SOURCE: ``"himalayas"``
        DISPLAY_NAME: ``"Himalayas"``
        GEO_SCOPE: ``"remote-only"``
        ACCEPTS_QUERY: ``"never"`` — the public API has no query parameter.
        ACCEPTS_LOCATION: ``False``
        ACCEPTS_COUNTRY: ``False``
        RATE_LIMIT_NOTES: Short description of the public rate limits.
        REQUIRED_SEARCH_FIELDS: ``()`` — no parameters required to run.
    """

    SOURCE = "himalayas"
    DISPLAY_NAME = "Himalayas"
    DESCRIPTION = (
        "Remote-first tech job board focused on software and product roles. "
        "Free API with no authentication required. High-quality listings."
    )
    HOME_URL = "https://himalayas.app"
    GEO_SCOPE = "remote-only"
    ACCEPTS_QUERY = "never"
    ACCEPTS_LOCATION = False
    ACCEPTS_COUNTRY = False
    RATE_LIMIT_NOTES = "Public API; no published rate limit. Observed soft limit ~1 req/sec."
    REQUIRED_SEARCH_FIELDS = ()

    def __init__(
        self,
        *,
        credentials: dict[str, Any] | None = None,
        search: SearchParams | None = None,
    ) -> None:
        """Initialise the Himalayas plugin.

        Himalayas requires no authentication; the ``credentials``
        argument is accepted for API uniformity but is silently ignored.

        Args:
            credentials: Accepted for interface uniformity; not used.
            search: :class:`~job_aggregator.schema.SearchParams` instance.
                All search fields are ignored because the Himalayas
                public API accepts no query, location, or country
                parameters.
        """
        super().__init__(credentials=credentials, search=search)
        extra = search.extra if search is not None else None
        self._page_size: int = int(
            extra.get("page_size", _DEFAULT_PAGE_SIZE) if extra else _DEFAULT_PAGE_SIZE
        )
        self._total: int | None = None  # cached after the first API response

    # ------------------------------------------------------------------
    # JobSource abstract method implementations
    # ------------------------------------------------------------------

    @classmethod
    def settings_schema(cls) -> dict[str, Any]:
        """Return an empty dict — Himalayas requires no credentials.

        Returns:
            An empty :class:`dict`.
        """
        return {}

    def pages(self) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of raw Himalayas job dicts.

        Fetches pages sequentially from offset 0 until either the total
        page count is exhausted or a page returns an empty ``jobs`` array.
        The ``total`` field from the first successful response is cached to
        avoid a separate count request.

        Yields:
            A list of raw job dicts (as returned by the Himalayas API)
            for each page of results.

        Raises:
            ScrapeError: If every page fetch fails (network error or
                non-200 HTTP status).
        """
        page = 1
        total_pages = self._fetch_total_pages()

        while page <= total_pages:
            raw_jobs = self._fetch_raw_page(page)
            if not raw_jobs:
                logger.info("himalayas: page %d returned 0 jobs — stopping early", page)
                return
            yield raw_jobs
            page += 1

    def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map a raw Himalayas job dict to the JobRecord schema.

        Field mapping:

        - ``guid``                → ``source_id``
        - ``title``               → ``title``
        - ``applicationLink``     → ``url``
        - ``pubDate``             → ``posted_at`` (parsed via
          :func:`_parse_pub_date`)
        - ``description``         → ``description`` (HTML stripped via
          :func:`_strip_html`)
        - ``companyName``         → ``company``
        - ``locationRestrictions``→ ``location`` (joined with ``", "``;
          ``"Worldwide"`` when the list is empty or absent)
        - ``minSalary``           → ``salary_min``
        - ``maxSalary``           → ``salary_max``
        - ``employmentType``      → ``contract_time`` (mapped via
          :func:`_map_employment_type`)

        Dropped fields (API returns but schema has no slot):

        - ``companyLogo`` — drop: UI-only asset; not part of job data
        - ``companyUrl``  — drop: company website; url field covers apply link
        - ``categories``  — drop: taxonomy tags; no schema field
        - ``skills``      — drop: keyword list; no schema field

        Args:
            raw: A single entry from the Himalayas ``jobs`` array.

        Returns:
            A dict conforming to :class:`~job_aggregator.schema.JobRecord`.
        """
        location_restrictions: list[str] = raw.get("locationRestrictions") or []
        location = ", ".join(location_restrictions) if location_restrictions else "Worldwide"

        description_raw: str = raw.get("description") or ""
        description = _strip_html(description_raw) if description_raw else ""
        description_source = "full" if description else "none"

        company_raw: str | None = raw.get("companyName") or None

        return {
            # Identity
            "source": self.SOURCE,
            "source_id": str(raw.get("guid", "")),
            "description_source": description_source,
            # Always-present
            "title": raw.get("title") or "",
            "url": raw.get("applicationLink") or "",
            "posted_at": _parse_pub_date(raw.get("pubDate")),
            "description": description,
            # Optional
            "company": company_raw,
            "location": location,
            "salary_min": raw.get("minSalary"),
            "salary_max": raw.get("maxSalary"),
            "salary_currency": None,  # drop: API does not expose currency
            "salary_period": None,  # drop: API does not expose pay period
            "contract_type": None,  # drop: no perm/contract distinction
            "contract_time": _map_employment_type(raw.get("employmentType")),
            "remote_eligible": True,  # all Himalayas listings are remote
            "extra": None,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_raw_page(self, page: int) -> list[dict[str, Any]]:
        """Fetch a single page of raw Himalayas job dicts.

        Converts the 1-based *page* number to an offset
        (``offset = (page - 1) * page_size``) before calling the API.
        Caches the ``total`` value from the response.

        Args:
            page: 1-based page number.

        Returns:
            List of raw job dicts, or an empty list on any error.

        Raises:
            ScrapeError: On non-200 HTTP responses or network failures.
        """
        offset = (page - 1) * self._page_size
        params: dict[str, int] = {"limit": self._page_size, "offset": offset}

        try:
            response = requests.get(_API_URL, params=params, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise ScrapeError(_API_URL, str(exc)) from exc

        if response.status_code != 200:
            raise ScrapeError(
                _API_URL,
                f"HTTP {response.status_code} for page {page} (offset {offset})",
            )

        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ScrapeError(_API_URL, f"invalid JSON: {exc}") from exc

        if "total" in data:
            self._total = int(data["total"])

        return list(data.get("jobs", []))

    def _fetch_total_pages(self) -> int:
        """Return the total number of pages available.

        If :attr:`_total` is already populated (from a prior call to
        :meth:`_fetch_raw_page`) it is used directly.  Otherwise the first
        page is fetched to read the ``total`` count.

        Returns:
            ``ceil(total / page_size)``, or 1 if total is unknown.
        """
        if self._total is not None:
            return ceil(self._total / self._page_size)

        # Fetch page 1 purely to read the total count.
        try:
            self._fetch_raw_page(1)
        except ScrapeError as exc:
            logger.warning("himalayas: could not determine total pages: %s", exc)
            return 1

        if self._total:
            return ceil(self._total / self._page_size)
        return 1
