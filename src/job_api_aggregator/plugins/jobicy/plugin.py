"""Jobicy plugin — wraps the Jobicy remote-jobs public API.

The Jobicy API (https://jobicy.com/api/v2/remote-jobs) is unauthenticated
and single-page.  It returns up to 50 listings in one JSON response.
HTML is stripped from ``jobDescription`` using BeautifulSoup.

No API key or credentials are required.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import requests
from bs4 import BeautifulSoup

from job_aggregator.base import JobSource
from job_aggregator.errors import ScrapeError
from job_aggregator.schema import SearchParams

logger = logging.getLogger(__name__)

_API_URL = "https://jobicy.com/api/v2/remote-jobs"

# Maximum listings per request accepted by the Jobicy API.
_MAX_COUNT = 100


def _strip_html(html: str) -> str:
    """Strip HTML tags from a string using BeautifulSoup.

    Args:
        html: Raw HTML string, possibly with nested tags.

    Returns:
        Plain-text string with all HTML tags removed.  Whitespace is
        normalised to single spaces and stripped of leading/trailing
        whitespace.
    """
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator=" ").strip()


def _coerce_contract_field(value: object) -> str | None:
    """Normalise a raw Jobicy ``jobType`` field to a plain string or None.

    The Jobicy API is inconsistent: ``jobType`` may arrive as a string
    (``"full_time"``), a list (``["full_time"]``), or absent/null.

    Rules:
        - Non-empty list whose first element is a non-empty string →
          first element returned as-is.
        - List with a non-string or empty first element → ``None``.
        - Empty list → ``None``.
        - Truthy non-list scalar → coerced to ``str`` and returned.
        - ``None`` or other falsy value → ``None``.

    Args:
        value: Raw value of the ``jobType`` key from a Jobicy listing dict.

    Returns:
        A plain string, or ``None`` when no usable value is available.
    """
    if isinstance(value, list):
        if not value:
            return None
        first = value[0]
        return first if isinstance(first, str) and first else None
    if value:
        return str(value)
    return None


class Plugin(JobSource):
    """JobSource plugin for the Jobicy remote-jobs board.

    Jobicy exposes a free, unauthenticated REST API that returns up to
    ``count`` remote job listings (max 100) in a single JSON response.
    Pagination is not supported by the upstream API; ``pages()`` always
    yields at most one page.

    The API accepts three optional query parameters:

    - ``tag`` — keyword filter (e.g. ``"python"``).
    - ``geo`` — geographic filter string (e.g. ``"usa"``).  Despite the
      name, Jobicy only lists remote-only roles so this is a loose filter
      that many callers leave as the default ``"anywhere"``.
    - ``count`` — number of listings to return (1-100, default 50).

    Class Attributes:
        SOURCE: ``"jobicy"``
        DISPLAY_NAME: ``"Jobicy"``
        DESCRIPTION: Copied verbatim from ``source.json``.
        HOME_URL: ``"https://jobicy.com"``
        GEO_SCOPE: ``"remote-only"`` — Jobicy exclusively lists remote roles.
        ACCEPTS_QUERY: ``"partial"`` — the ``tag`` parameter provides
            keyword filtering but it is fuzzy and not full-text search.
        ACCEPTS_LOCATION: ``False`` — the ``geo`` parameter is a loose
            geographic hint, not a true location filter; the API may
            return listings outside the requested geo.  We treat it as
            unsupported rather than exposing a misleading filter.
        ACCEPTS_COUNTRY: ``False`` — no country-code filter is supported.
        RATE_LIMIT_NOTES: No published rate limit; a single request per
            run is all that is needed.
        REQUIRED_SEARCH_FIELDS: ``()`` — no search fields are required.
    """

    SOURCE = "jobicy"
    DISPLAY_NAME = "Jobicy"
    DESCRIPTION = (
        "Remote job board with a free, unauthenticated API. "
        "Returns full job descriptions — no scraping needed. "
        "Good for remote software and data roles."
    )
    HOME_URL = "https://jobicy.com"
    GEO_SCOPE = "remote-only"
    ACCEPTS_QUERY = "partial"
    ACCEPTS_LOCATION = False
    ACCEPTS_COUNTRY = False
    RATE_LIMIT_NOTES = "No published rate limit; single request per run."
    REQUIRED_SEARCH_FIELDS = ()

    def __init__(
        self,
        *,
        credentials: dict[str, Any] | None = None,
        search: SearchParams | None = None,
    ) -> None:
        """Initialise the Jobicy plugin.

        Jobicy requires no authentication; the ``credentials`` argument
        is accepted for API uniformity but is silently ignored.

        The ``query`` field of *search* is forwarded to the Jobicy
        ``tag`` keyword-filter parameter when present.

        Args:
            credentials: Accepted for interface uniformity; not used.
            search: :class:`~job_aggregator.schema.SearchParams` instance.
                ``query`` is used as the ``tag`` filter; other fields are
                not forwarded because the Jobicy API has no location or
                country parameter.
        """
        super().__init__(credentials=credentials, search=search)
        self._query: str | None = search.query if search is not None else None
        extra = search.extra if search is not None else None
        self._count: int = int(extra.get("count", _MAX_COUNT) if extra else _MAX_COUNT)

    # ------------------------------------------------------------------
    # JobSource interface
    # ------------------------------------------------------------------

    @classmethod
    def settings_schema(cls) -> dict[str, Any]:
        """Return an empty schema — Jobicy requires no credentials.

        Returns:
            An empty dict because Jobicy's API is unauthenticated.
        """
        return {}

    def pages(self) -> Iterator[list[dict[str, Any]]]:
        """Yield the single page of raw Jobicy listings.

        Makes one HTTP GET request to the Jobicy API and yields the raw
        ``jobs`` list if it is non-empty.  Yields nothing on network
        errors, non-200 responses, or empty result sets.

        Yields:
            A single list of raw job dicts as returned by the API.

        Raises:
            ScrapeError: If the HTTP request fails or the response
                cannot be parsed as JSON.  The error is raised (not
                swallowed) so the orchestrator can log it and decide
                whether to continue with other sources.
        """
        params: dict[str, str | int] = {"count": self._count}
        if self._query:
            params["tag"] = self._query

        try:
            response = requests.get(_API_URL, params=params, timeout=15)
        except requests.RequestException as exc:
            raise ScrapeError(_API_URL, str(exc)) from exc

        if response.status_code != 200:
            raise ScrapeError(
                _API_URL,
                f"HTTP {response.status_code}",
            )

        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ScrapeError(_API_URL, f"Invalid JSON: {exc}") from exc

        raw_jobs: list[dict[str, Any]] = data.get("jobs") or []
        if raw_jobs:
            yield raw_jobs

    def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map a single Jobicy API listing dict to the JobRecord schema.

        **Field mapping:**

        +-----------------------+---------------------+----------+
        | Jobicy field          | JobRecord field     | Notes    |
        +=======================+=====================+==========+
        | ``id``                | ``source_id``       | → str    |
        +-----------------------+---------------------+----------+
        | ``jobTitle``          | ``title``           |          |
        +-----------------------+---------------------+----------+
        | ``companyName``       | ``company``         |          |
        +-----------------------+---------------------+----------+
        | ``jobGeo``            | ``location``        |          |
        +-----------------------+---------------------+----------+
        | ``url``               | ``url``             |          |
        +-----------------------+---------------------+----------+
        | ``pubDate``           | ``posted_at``       |          |
        +-----------------------+---------------------+----------+
        | ``jobDescription``    | ``description``     | HTML→txt |
        +-----------------------+---------------------+----------+
        | ``annualSalaryMin``   | ``salary_min``      | → float  |
        +-----------------------+---------------------+----------+
        | ``annualSalaryMax``   | ``salary_max``      | → float  |
        +-----------------------+---------------------+----------+
        | ``salaryCurrency``    | ``salary_currency`` |          |
        +-----------------------+---------------------+----------+
        | ``jobType``           | ``contract_time``   | coerced  |
        +-----------------------+---------------------+----------+
        | (derived)             | ``salary_period``   | "annual" |
        +-----------------------+---------------------+----------+
        | (derived)             | ``contract_type``   | None     |
        +-----------------------+---------------------+----------+
        | (derived)             | ``remote_eligible`` | True     |
        +-----------------------+---------------------+----------+
        | (derived)             | ``description_source`` | "full"|
        +-----------------------+---------------------+----------+

        **Explicitly dropped to ``extra``:**

        - ``jobSlug`` — internal URL slug; redundant with ``url``.
        - ``jobIndustry`` — category list; preserved in extra for callers.
        - ``jobLevel`` — seniority label; preserved in extra for callers.
        - ``jobExcerpt`` — short excerpt; full text in ``description``.
        - ``companyLogo`` — image URL; not in JobRecord schema.

        Args:
            raw: A single dict from the ``jobs`` array in the Jobicy
                API response.

        Returns:
            A dict conforming to the :class:`~job_aggregator.schema.JobRecord`
            TypedDict contract.
        """
        # ---- Salary ----
        salary_min_raw = raw.get("annualSalaryMin")
        salary_max_raw = raw.get("annualSalaryMax")
        salary_min: float | None = None
        salary_max: float | None = None
        salary_period: str | None = None

        if salary_min_raw is not None or salary_max_raw is not None:
            salary_period = "annual"
            try:
                salary_min = float(salary_min_raw) if salary_min_raw is not None else None
            except (TypeError, ValueError):
                salary_min = None
            try:
                salary_max = float(salary_max_raw) if salary_max_raw is not None else None
            except (TypeError, ValueError):
                salary_max = None

        # ---- Description ----
        raw_desc: str = raw.get("jobDescription") or ""
        description = _strip_html(raw_desc) if raw_desc else ""

        # ---- Extra blob (non-schema fields preserved, not silently dropped) ----
        extra: dict[str, Any] = {}
        if raw.get("jobSlug"):
            extra["jobSlug"] = raw["jobSlug"]  # drop: redundant with url
        if raw.get("jobIndustry") is not None:
            extra["jobIndustry"] = raw["jobIndustry"]  # drop: not in schema
        if raw.get("jobLevel"):
            extra["jobLevel"] = raw["jobLevel"]  # drop: not in schema
        if raw.get("jobExcerpt"):
            extra["jobExcerpt"] = raw["jobExcerpt"]  # drop: full text in description
        if raw.get("companyLogo"):
            extra["companyLogo"] = raw["companyLogo"]  # drop: image URL, not in schema

        return {
            # ---- Identity ----
            "source": self.SOURCE,
            "source_id": str(raw.get("id", "")),
            "description_source": "full",
            # ---- Always-present ----
            "title": raw.get("jobTitle") or "",
            "url": raw.get("url") or "",
            "posted_at": raw.get("pubDate") or None,
            "description": description,
            # ---- Optional ----
            "company": raw.get("companyName") or None,
            "location": raw.get("jobGeo") or None,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": raw.get("salaryCurrency") or None,
            "salary_period": salary_period,
            "contract_type": None,  # drop: Jobicy has no contract type field
            "contract_time": _coerce_contract_field(raw.get("jobType")),
            "remote_eligible": True,  # Jobicy is remote-only
            # ---- Source-specific blob ----
            "extra": extra if extra else None,
        }
