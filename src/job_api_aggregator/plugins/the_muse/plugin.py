"""The Muse job-source plugin.

Wraps The Muse public Jobs API (https://www.themuse.com/api/public/jobs).

Key API characteristics:
- 0-indexed pagination via a ``page`` query parameter.
- Optional ``api_key`` reduces rate-limiting but is not required for
  basic usage.
- Listings are filtered by ``category`` (e.g. "Software Engineer"), which
  maps to the ``SearchParams.query`` field.
- The API returns HTML in the ``contents`` field; we strip it to plain
  text via BeautifulSoup.
- No salary, location-filter, or country-filter support in the API.

GEO_SCOPE rationale: The Muse lists jobs globally (US-heavy but not
exclusively). The API does not expose a country or location filter, so
``GEO_SCOPE="global"`` with ``ACCEPTS_LOCATION=False`` and
``ACCEPTS_COUNTRY=False``.

ACCEPTS_QUERY rationale: ``query`` is mapped to the ``category``
parameter, which is a categorical filter (not free-text search), so
``ACCEPTS_QUERY="partial"``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import requests
from bs4 import BeautifulSoup

from job_aggregator.base import JobSource
from job_aggregator.schema import SearchParams

logger = logging.getLogger(__name__)

_THE_MUSE_BASE: str = "https://www.themuse.com/api/public/jobs"
_DEFAULT_CATEGORY: str = "Software Engineer"
_DEFAULT_RESULTS_PER_PAGE: int = 20
_REQUEST_TIMEOUT: int = 15


class Plugin(JobSource):
    """JobSource plugin for The Muse public Jobs API.

    The Muse offers a public jobs API with optional API key for higher
    rate limits.  Results are filtered by job category (mapped from
    ``SearchParams.query``).  The API returns full HTML job descriptions
    which are stripped to plain text before storage.

    Attributes:
        SOURCE: ``"the_muse"``
        DISPLAY_NAME: ``"The Muse"``
        DESCRIPTION: Short description copied from legacy source.json.
        HOME_URL: ``"https://www.themuse.com"``
        GEO_SCOPE: ``"global"`` — international board, no country filter.
        ACCEPTS_QUERY: ``"partial"`` — query maps to category filter.
        ACCEPTS_LOCATION: ``False`` — no location filter in API.
        ACCEPTS_COUNTRY: ``False`` — no country filter in API.
        RATE_LIMIT_NOTES: Summary of documented rate-limit behaviour.
        REQUIRED_SEARCH_FIELDS: ``()`` — all fields optional.
    """

    SOURCE = "the_muse"
    DISPLAY_NAME = "The Muse"
    DESCRIPTION = (
        "US-focused job board with company culture context. "
        "Free API with optional key to reduce rate limits. "
        "Good coverage of mid-to-large tech companies."
    )
    HOME_URL = "https://www.themuse.com"
    GEO_SCOPE = "global"
    ACCEPTS_QUERY = "partial"
    ACCEPTS_LOCATION = False
    ACCEPTS_COUNTRY = False
    RATE_LIMIT_NOTES = "Public API; no published hard limit. Optional api_key reduces throttling."
    REQUIRED_SEARCH_FIELDS = ()

    def __init__(
        self,
        *,
        credentials: dict[str, Any] | None = None,
        search: SearchParams | None = None,
    ) -> None:
        """Initialise the plugin with optional credentials and search params.

        The Muse API is public; credentials are accepted for interface
        uniformity.  An optional ``api_key`` in *credentials* is used to
        reduce rate-limiting.

        Args:
            credentials: Optional dict.  If it contains an ``"api_key"``
                key that is non-empty, the key is sent with every request
                to reduce rate-limiting.
            search: :class:`~job_aggregator.schema.SearchParams` instance.
                ``query`` is mapped to the category filter; ``max_pages``
                caps the page count.  Location and country are ignored.
        """
        super().__init__(credentials=credentials, search=search)
        creds: dict[str, Any] = credentials or {}
        s = search or SearchParams()
        self._category: str = s.query or _DEFAULT_CATEGORY
        self._max_pages: int | None = s.max_pages
        self._api_key: str | None = str(creds.get("api_key") or "").strip() or None
        self._results_per_page: int = _DEFAULT_RESULTS_PER_PAGE
        # Cache total page count after the first probe call.
        self._page_count: int | None = None

    # ------------------------------------------------------------------
    # JobSource — settings_schema
    # ------------------------------------------------------------------

    @classmethod
    def settings_schema(cls) -> dict[str, Any]:
        """Return field definitions for this plugin's optional configuration.

        The Muse API is public and requires no credentials.  An optional
        ``api_key`` field is exposed for users who have registered.

        Returns:
            An empty dict because no fields are *required*; the api_key
            is passed as a constructor argument, not via the credentials
            settings system.
        """
        return {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_params(self, page: int) -> dict[str, Any]:
        """Build the query-parameter dict for a single API request.

        Args:
            page: 0-based page index (the API is 0-indexed).

        Returns:
            Dict of query parameters ready for ``requests.get(params=...)``.
        """
        params: dict[str, Any] = {
            "category": self._category,
            "page": page,
            "results_per_page": self._results_per_page,
        }
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    @staticmethod
    def _strip_html(html: str | None) -> str:
        """Convert an HTML string to plain text.

        Uses BeautifulSoup with the built-in ``html.parser`` so no
        external parser (lxml, html5lib) is required.

        Args:
            html: Raw HTML string, or ``None`` / empty string.

        Returns:
            Plain-text string with leading/trailing whitespace stripped.
            Returns an empty string when *html* is falsy.
        """
        if not html:
            return ""
        return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)

    def _get_page(self, page: int) -> dict[str, Any]:
        """Perform a single GET request and return the parsed JSON body.

        Network failures, non-200 responses, and invalid JSON are logged
        as warnings and result in an empty dict being returned — the
        caller should treat an empty dict as "no results on this page".

        Args:
            page: 0-based page index.

        Returns:
            Parsed JSON dict from the API.  Returns ``{}`` on any
            network, HTTP, or parse error.

        """
        params = self._build_params(page)
        try:
            response = requests.get(_THE_MUSE_BASE, params=params, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("the_muse: request failed on page %d: %s", page, exc)
            return {}

        if response.status_code != 200:
            logger.warning(
                "the_muse: HTTP %d on page %d; skipping",
                response.status_code,
                page,
            )
            return {}

        try:
            return response.json()  # type: ignore[no-any-return]
        except ValueError as exc:
            logger.warning("the_muse: invalid JSON on page %d: %s", page, exc)
            return {}

    def _total_pages(self) -> int:
        """Return the total page count as reported by the API.

        Probes page 0 of the API and caches the result so subsequent
        calls do not make additional HTTP requests.

        Returns:
            Total page count from the API.  Returns 0 if the probe
            request fails or if the API returns no ``page_count`` field.
        """
        if self._page_count is not None:
            return self._page_count
        data = self._get_page(0)
        self._page_count = int(data.get("page_count", 0))
        return self._page_count

    # ------------------------------------------------------------------
    # JobSource — pages
    # ------------------------------------------------------------------

    def pages(self) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of normalised job listings from The Muse API.

        The Muse API uses 0-based page numbering; ``page_count`` is the
        total number of pages, so valid page indices are 0..(page_count-1).
        Page 0 is fetched first as a probe to discover ``page_count``; its
        results are yielded immediately.  Subsequent pages (1..page_count-1)
        are fetched in order.  Iteration stops early if a page returns zero
        results.

        Yields:
            A list of normalised :class:`~job_aggregator.schema.JobRecord`
            dicts for each page.  Each element has already been passed
            through :meth:`normalise`.
        """
        # Page 0 serves double-duty: probe for page_count AND first results.
        probe_data = self._get_page(0)
        self._page_count = int(probe_data.get("page_count", 0))
        total = self._page_count

        if self._max_pages is not None:
            total = min(total, self._max_pages)

        # Yield the probe page's results first (page 0).
        probe_results: list[dict[str, Any]] = probe_data.get("results", [])
        if not probe_results:
            return
        yield [self.normalise(r) for r in probe_results]

        # Fetch remaining pages (1..total-1).
        for page in range(1, total):
            data = self._get_page(page)
            raw_results: list[dict[str, Any]] = data.get("results", [])
            if not raw_results:
                logger.info(
                    "the_muse: page %d returned 0 results; stopping early",
                    page,
                )
                return
            yield [self.normalise(r) for r in raw_results]

    # ------------------------------------------------------------------
    # JobSource — normalise
    # ------------------------------------------------------------------

    def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map a raw The Muse API listing dict to the JobRecord schema.

        Field mapping:

        - ``id`` → ``source_id`` (coerced to str)
        - ``name`` → ``title``
        - ``refs.landing_page`` → ``url``
        - ``publication_date`` → ``posted_at``
        - ``contents`` (HTML) → ``description`` (plain text via
          BeautifulSoup; ``description_source="full"``)
        - ``company.name`` → ``company``
        - ``locations[0].name`` → ``location`` (first entry only)
        - ``type`` → ``contract_time``

        Dropped fields (no JobRecord equivalent):
        - ``model_type``: internal Muse record type; not user-facing. # drop: internal metadata
        - ``levels``: seniority tags (e.g. "Senior Level"); not mapped. # drop: no JobRecord field
        - ``tags``: freeform tags; stored nowhere in schema.            # drop: no JobRecord field
        - ``categories``: category list; query param is the input.  # drop: redundant with query
        - ``refs.canonical_url``: secondary URL; landing_page preferred.# drop: redundant with url

        The Muse does not expose salary data; ``salary_min``,
        ``salary_max``, ``salary_currency``, and ``salary_period`` are
        always ``None``.  ``contract_type`` and ``remote_eligible`` are
        also not available in the API response.

        Args:
            raw: A single entry from the The Muse API ``results`` array.

        Returns:
            A normalised dict conforming to the
            :class:`~job_aggregator.schema.JobRecord` TypedDict contract.
        """
        company_obj: dict[str, Any] = raw.get("company") or {}
        company: str = company_obj.get("name") or ""

        locations: list[dict[str, Any]] = raw.get("locations") or []
        location: str | None = locations[0].get("name") if locations else None

        refs: dict[str, Any] = raw.get("refs") or {}
        url: str = refs.get("landing_page") or ""

        return {
            # Identity
            "source": self.SOURCE,
            "source_id": str(raw.get("id", "")),
            "description_source": "full",
            # Always-present
            "title": raw.get("name") or "",
            "url": url,
            "posted_at": raw.get("publication_date") or None,
            "description": self._strip_html(raw.get("contents")),
            # Optional
            "company": company,
            "location": location,
            "salary_min": None,  # drop: The Muse API exposes no salary data
            "salary_max": None,  # drop: The Muse API exposes no salary data
            "salary_currency": None,  # drop: no salary data
            "salary_period": None,  # drop: no salary data
            "contract_type": None,  # drop: not in API response
            "contract_time": raw.get("type") or None,
            "remote_eligible": None,  # drop: not in API response
            # Source-specific blob
            "extra": None,
        }
