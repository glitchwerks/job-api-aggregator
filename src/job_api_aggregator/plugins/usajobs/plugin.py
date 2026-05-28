"""USAJobs source plugin for job-aggregator.

Wraps the USAJobs REST API (https://developer.usajobs.gov/API-Reference),
handling pagination, authentication, and normalisation to the canonical
:class:`~job_aggregator.schema.JobRecord` shape.

Authentication note:
    The USAJobs API requires two headers:

    - ``Authorization-Key``: the API key obtained from usajobs.gov
    - ``User-Agent``: the contact email registered with the API key

    Both are mandatory; the API returns HTTP 403 if either is absent or
    does not match the registered account.

Rate limiting:
    USAJobs does not publish a hard numeric limit, but the API is
    email-tagged via ``User-Agent``.  Treat it as best-effort / fair-use.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, ClassVar, Literal

import requests

from job_aggregator.base import JobSource
from job_aggregator.errors import CredentialsError, ScrapeError
from job_aggregator.schema import SearchParams

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_SEARCH_URL: str = "https://data.usajobs.gov/api/search"

# Only map salary figures when the pay interval is annual (per annum).
_ANNUAL_RATE_CODE: str = "PA"

_DEFAULT_RESULTS_PER_PAGE: int = 25


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_float(value: object) -> float | None:
    """Cast *value* to float, returning ``None`` on failure or if absent.

    Args:
        value: Any value to attempt conversion on. ``None`` and empty
            strings are handled gracefully.

    Returns:
        The float representation of *value*, or ``None`` if conversion
        fails for any reason.
    """
    if value is None:
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class Plugin(JobSource):
    """USAJobs source plugin.

    Implements the :class:`~job_aggregator.base.JobSource` ABC for the
    US federal government job board at https://www.usajobs.gov.

    The USAJobs API accepts a ``Keyword`` query parameter, so free-text
    queries are forwarded as-is (``ACCEPTS_QUERY = "partial"`` because
    the API does not support structured location or country filtering —
    location data comes from the listing itself, not the search request).

    Attributes:
        SOURCE: ``"usajobs"``
        DISPLAY_NAME: ``"USAJobs"``
        GEO_SCOPE: ``"federal-us"``
        ACCEPTS_QUERY: ``"partial"``
        ACCEPTS_LOCATION: ``False``
        ACCEPTS_COUNTRY: ``False``
        RATE_LIMIT_NOTES: One-line rate-limit note.
        REQUIRED_SEARCH_FIELDS: ``()`` — no fields are strictly required.
    """

    # ------------------------------------------------------------------
    # Required ClassVar metadata
    # ------------------------------------------------------------------

    SOURCE: ClassVar[str] = "usajobs"
    DISPLAY_NAME: ClassVar[str] = "USAJobs"
    DESCRIPTION: ClassVar[str] = (
        "Official US federal government job board. Requires a free API key "
        "and contact email from usajobs.gov. Best for government or "
        "contractor roles."
    )
    HOME_URL: ClassVar[str] = "https://www.usajobs.gov"
    GEO_SCOPE: ClassVar[
        Literal["global", "global-by-country", "remote-only", "federal-us", "regional", "unknown"]
    ] = "federal-us"
    ACCEPTS_QUERY: ClassVar[Literal["always", "partial", "never"]] = "partial"
    ACCEPTS_LOCATION: ClassVar[bool] = False
    ACCEPTS_COUNTRY: ClassVar[bool] = False
    RATE_LIMIT_NOTES: ClassVar[str] = "Email-tagged user-agent required; no published numeric limit"
    REQUIRED_SEARCH_FIELDS: ClassVar[tuple[str, ...]] = ()

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        credentials: dict[str, Any] | None = None,
        search: SearchParams | None = None,
    ) -> None:
        """Construct a Plugin instance, validating required credentials.

        Args:
            credentials: Dict containing ``api_key`` and ``email``.
                Both fields are required; a missing or empty value
                raises :exc:`~job_aggregator.errors.CredentialsError`.
            search: :class:`~job_aggregator.schema.SearchParams` carrying
                ``query`` and ``max_pages``.  Location and country are
                ignored because the USAJobs API does not support them.

        Raises:
            CredentialsError: If ``api_key`` or ``email`` is missing or
                empty in *credentials*.
        """
        super().__init__(credentials=credentials, search=search)
        creds: dict[str, Any] = credentials or {}

        api_key: str = str(creds.get("api_key") or "").strip()
        email: str = str(creds.get("email") or "").strip()

        missing: list[str] = []
        if not api_key:
            missing.append("api_key")
        if not email:
            missing.append("email")
        if missing:
            raise CredentialsError(self.SOURCE, missing)

        s = search or SearchParams()
        self._api_key: str = api_key
        # email is used as the User-Agent header per USAJobs API requirements
        self._email: str = email
        self._query: str = s.query or "software engineer"
        self._max_pages: int | None = s.max_pages
        self._results_per_page: int = _DEFAULT_RESULTS_PER_PAGE

    # ------------------------------------------------------------------
    # JobSource interface
    # ------------------------------------------------------------------

    @classmethod
    def settings_schema(cls) -> dict[str, Any]:
        """Return the credential field definitions for USAJobs.

        Returns:
            A dict with two required fields: ``api_key`` (password)
            and ``email`` (email address used as the ``User-Agent``
            header per the USAJobs API authentication scheme).
        """
        return {
            "api_key": {
                "label": "API Key",
                "type": "password",
                "required": True,
                "help_text": ("Obtain a free API key at https://developer.usajobs.gov/apirequest/"),
            },
            "email": {
                "label": "Contact Email (User-Agent)",
                "type": "email",
                "required": True,
                "help_text": (
                    "The email address registered with your USAJobs API key. "
                    "Sent as the User-Agent header on every request."
                ),
            },
        }

    def pages(self) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of raw USAJobs ``SearchResultItems`` dicts.

        Fetches page 1 first to discover the total page count, then
        iterates subsequent pages up to ``_max_pages`` (or exhaustion).
        Stops early if a page returns zero results.

        Yields:
            A list of raw ``SearchResultItems`` dicts for each page.

        Raises:
            ScrapeError: If the page-1 request fails or returns a
                non-200 status, making total-page discovery impossible.
        """
        total = self._fetch_total_pages()
        limit = total if self._max_pages is None else min(total, self._max_pages)

        for page_num in range(1, limit + 1):
            items = self._fetch_page(page_num)
            if not items:
                logger.info(
                    "usajobs: page %d returned 0 results; stopping early",
                    page_num,
                )
                return
            yield items

    def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map a raw ``SearchResultItems`` entry to the canonical schema.

        Field mapping summary (spec §9.3 audit):

        - ``MatchedObjectId``            → ``source_id``
        - ``MatchedObjectDescriptor``    → container for all other fields
        - ``PositionTitle``              → ``title``
        - ``PositionURI``                → ``url``
        - ``PublicationStartDate``       → ``posted_at``
        - ``QualificationSummary``       → ``description`` (snippet only)
        - ``OrganizationName``           → ``company``
        - ``PositionLocationDisplay``    → ``location``
        - ``PositionRemuneration[0]``    → ``salary_min``, ``salary_max``,
                                           ``salary_currency``, ``salary_period``
                                           (PA rate code only; others dropped)
        - ``PositionOfferingType[0]``    → ``contract_type``
        - ``ScheduleTypeName``           → ``contract_time``

        Deliberately dropped fields:
        - ``DepartmentName``       # drop: duplicated by OrganizationName
        - ``JobGrade``             # drop: US federal pay scale; not in schema
        - ``PositionSchedule``     # drop: redundant with ScheduleTypeName
        - ``SubAgency``            # drop: agency detail not in schema
        - ``PositionFormattedDesc``# drop: HTML blob; QualificationSummary used
        - ``ApplicationCloseDate`` # drop: deadline not in schema
        - ``UserArea``             # drop: metadata/pagination fields only
        - ``PositionSensitivity``  # drop: clearance level; not in schema
        - ``SecurityClearance``    # drop: clearance level; not in schema
        - ``DrugTestRequired``     # drop: HR field not in schema
        - ``NumberOfPositions``    # drop: count field not in schema
        - Non-PA PositionRemuneration entries
                                   # drop: non-annual pay intervals not mappable

        Args:
            raw: A single ``SearchResultItems`` dict as returned by the
                USAJobs Search API.

        Returns:
            A dict conforming to the :class:`~job_aggregator.schema.JobRecord`
            shape.
        """
        descriptor: dict[str, Any] = raw.get("MatchedObjectDescriptor") or {}

        # --- salary (annual only) ---
        salary_min: float | None = None
        salary_max: float | None = None
        salary_currency: str | None = None
        salary_period: str | None = None

        remuneration_list: list[dict[str, Any]] = descriptor.get("PositionRemuneration") or []
        if remuneration_list:
            pay = remuneration_list[0]
            if pay.get("RateIntervalCode") == _ANNUAL_RATE_CODE:
                salary_min = _parse_float(pay.get("MinimumRange"))
                salary_max = _parse_float(pay.get("MaximumRange"))
                # Only set currency/period when we have at least one salary value
                if salary_max is not None or salary_min is not None:
                    salary_currency = "USD"
                if salary_max is not None:
                    salary_period = "annual"

        # --- contract type / time ---
        offering_types: list[dict[str, Any]] = descriptor.get("PositionOfferingType") or []
        contract_type: str | None = offering_types[0].get("Name") if offering_types else None
        contract_time: str | None = descriptor.get("ScheduleTypeName") or None

        return {
            # Identity
            "source": self.SOURCE,
            "source_id": str(raw.get("MatchedObjectId") or ""),
            "description_source": "snippet",
            # Always-present
            "title": descriptor.get("PositionTitle") or "",
            "url": descriptor.get("PositionURI") or "",
            "posted_at": descriptor.get("PublicationStartDate") or None,
            "description": descriptor.get("QualificationSummary") or "",
            # Optional
            "company": descriptor.get("OrganizationName") or None,
            "location": descriptor.get("PositionLocationDisplay") or None,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": salary_currency,
            "salary_period": salary_period,
            "contract_type": contract_type,
            "contract_time": contract_time,
            "remote_eligible": None,  # USAJobs does not expose this field
            # Extra blob
            "extra": None,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        """Return the authentication headers required by the USAJobs API.

        Returns:
            Dict with ``Authorization-Key``, ``User-Agent``, and
            ``Host`` headers as required by the USAJobs API auth scheme.
        """
        return {
            "Authorization-Key": self._api_key,
            "User-Agent": self._email,
            "Host": "data.usajobs.gov",
        }

    def _build_params(self, page: int) -> dict[str, Any]:
        """Build the query parameters for a search request.

        Args:
            page: 1-based page number.

        Returns:
            Dict of query parameters for the USAJobs search endpoint.
        """
        return {
            "Keyword": self._query,
            "Page": page,
            "ResultsPerPage": self._results_per_page,
        }

    def _fetch_total_pages(self) -> int:
        """Discover the total number of result pages for the current query.

        Makes a page-1 request and reads ``NumberOfPages`` from the
        ``SearchResult.UserArea`` envelope.

        Returns:
            Total number of pages available, or ``1`` if the metadata
            cannot be read.

        Raises:
            ScrapeError: If the HTTP request fails or returns a
                non-200 status.
        """
        try:
            response = requests.get(
                _SEARCH_URL,
                params=self._build_params(page=1),
                headers=self._build_headers(),
                timeout=15,
            )
        except requests.RequestException as exc:
            raise ScrapeError(_SEARCH_URL, str(exc)) from exc

        if response.status_code != 200:
            raise ScrapeError(
                _SEARCH_URL,
                f"HTTP {response.status_code}",
            )

        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ScrapeError(_SEARCH_URL, f"Invalid JSON: {exc}") from exc

        try:
            total: int = int(data["SearchResult"]["UserArea"]["NumberOfPages"])
        except (KeyError, TypeError, ValueError):
            logger.warning("usajobs: could not read NumberOfPages; defaulting to 1")
            total = 1

        return total

    def _fetch_page(self, page: int) -> list[dict[str, Any]]:
        """Fetch a single page of raw USAJobs search results.

        Non-200 responses are logged as warnings and return an empty
        list (non-fatal) so that a transient error on a later page does
        not abort the entire run.

        Args:
            page: 1-based page number.

        Returns:
            List of raw ``SearchResultItems`` dicts, or an empty list on
            HTTP error or JSON parse failure.
        """
        try:
            response = requests.get(
                _SEARCH_URL,
                params=self._build_params(page=page),
                headers=self._build_headers(),
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.warning("usajobs: request failed on page %d: %s", page, exc)
            return []

        if response.status_code != 200:
            logger.warning(
                "usajobs: HTTP %d on page %d; skipping",
                response.status_code,
                page,
            )
            return []

        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            logger.warning("usajobs: invalid JSON on page %d: %s", page, exc)
            return []

        items: list[dict[str, Any]] = data.get("SearchResult", {}).get("SearchResultItems", [])
        return items
