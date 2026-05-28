"""JSearch (RapidAPI) job-source plugin for job-aggregator.

Wraps the JSearch API (https://jsearch.p.rapidapi.com/search), which
aggregates job listings from Google for Jobs and returns full plaintext
descriptions in the API response — no scraping step required.

Free tier: 200 requests/month.  This plugin issues **two** API requests
per page: one geo-matched query and one remote-only query.  With the
default ``max_pages=5`` that is 10 API calls per run — roughly 20 runs
per month on the free tier.

Authentication is via the ``X-RapidAPI-Key`` request header (not a query
parameter).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any, ClassVar, Literal

import requests

from job_aggregator.base import JobSource
from job_aggregator.errors import CredentialsError
from job_aggregator.schema import SearchParams

logger = logging.getLogger(__name__)

_JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"
_JSEARCH_HOST = "jsearch.p.rapidapi.com"

# ---------------------------------------------------------------------------
# Canonical mapping tables
# ---------------------------------------------------------------------------

# JSearch employment-type → canonical contract_time
_CONTRACT_TIME_MAP: dict[str, str] = {
    "FULLTIME": "full_time",
    "PARTTIME": "part_time",
    "CONTRACTOR": "contract",
    "INTERN": "intern",
}

# JSearch salary-period → canonical salary_period (JobRecord literal)
_SALARY_PERIOD_MAP: dict[str, str] = {
    "YEAR": "annual",
    "HOUR": "hourly",
    "MONTH": "monthly",
}

# Reverse map for translating a canonical contract_time filter back to the
# JSearch employment_types query parameter.
_REVERSE_CONTRACT_TIME_MAP: dict[str, str] = {v: k for k, v in _CONTRACT_TIME_MAP.items()}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _normalise_contract_time(raw: str | None) -> str | None:
    """Map a JSearch employment-type string to the canonical contract_time value.

    Lookup is case-insensitive after stripping hyphens and spaces so that
    ``"FULL-TIME"``, ``"full time"``, and ``"FULLTIME"`` all resolve to
    ``"full_time"``.  Unknown values are lowercased and passed through.
    ``None`` or empty string returns ``None``.

    Args:
        raw: Raw employment-type string from the JSearch API.

    Returns:
        Canonical contract_time string, the lowercased raw value for unknown
        types, or ``None`` when *raw* is absent.
    """
    if not raw:
        return None
    key = raw.upper().replace("-", "").replace(" ", "")
    return _CONTRACT_TIME_MAP.get(key, raw.lower())


def _normalise_salary_period(raw: str | None) -> str | None:
    """Map a JSearch salary-period string to the canonical salary_period value.

    Only the three JobRecord-legal literals (``"annual"``, ``"hourly"``,
    ``"monthly"``) are supported.  Unknown period codes are discarded and
    return ``None`` rather than being passed through, because an
    unrecognised period code is meaningless downstream.

    Args:
        raw: Raw salary-period string from the JSearch API (e.g. ``"YEAR"``).

    Returns:
        One of ``"annual"``, ``"hourly"``, ``"monthly"``, or ``None``.
    """
    if not raw:
        return None
    return _SALARY_PERIOD_MAP.get(raw.upper())


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class Plugin(JobSource):
    """JobSource plugin for the JSearch (RapidAPI) job-search API.

    JSearch aggregates listings from Google for Jobs and returns complete
    plaintext job descriptions in the API response, so ``description_source``
    is always ``"full"`` and no secondary scrape step is needed.

    Each call to :meth:`pages` makes **two** API requests per page iteration:

    1. A geo-matched query (``"{query} in {location}"`` plus optional
       ``radius``) when a ``location`` parameter is provided.
    2. A remote-only query (``remote_jobs_only=true``).

    Results are deduplicated by ``job_id`` before being normalised.

    Auth is via the ``X-RapidAPI-Key`` HTTP request header.

    Attributes:
        SOURCE: Plugin key ``"jsearch"``.
        DISPLAY_NAME: ``"JSearch (RapidAPI)"``.
        DESCRIPTION: Short description copied verbatim from ``source.json``.
        HOME_URL: RapidAPI listing page for the JSearch API.
        GEO_SCOPE: ``"global"`` — the API aggregates worldwide listings.
        ACCEPTS_QUERY: ``"always"`` — free-text query is always sent.
        ACCEPTS_LOCATION: ``True`` — location is injected into the query
            string and ``radius`` is supported.
        ACCEPTS_COUNTRY: ``False`` — no native country-code filter exists;
            country is embedded in the location string by the caller.
        RATE_LIMIT_NOTES: RapidAPI quota summary.
        REQUIRED_SEARCH_FIELDS: ``("query",)`` — a query string is required
            because the JSearch API mandates a ``query`` parameter.
    """

    SOURCE: ClassVar[str] = "jsearch"
    DISPLAY_NAME: ClassVar[str] = "JSearch (RapidAPI)"
    DESCRIPTION: ClassVar[str] = (
        "Job aggregator powered by Google for Jobs, accessed via RapidAPI. "
        "Free tier: 200 requests/month."
    )
    HOME_URL: ClassVar[str] = "https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch"
    GEO_SCOPE: ClassVar[
        Literal["global", "global-by-country", "remote-only", "federal-us", "regional", "unknown"]
    ] = "global"
    ACCEPTS_QUERY: ClassVar[Literal["always", "partial", "never"]] = "always"
    ACCEPTS_LOCATION: ClassVar[bool] = True
    ACCEPTS_COUNTRY: ClassVar[bool] = False
    RATE_LIMIT_NOTES: ClassVar[str] = "RapidAPI quota varies by plan; free tier 200 requests/month"
    REQUIRED_SEARCH_FIELDS: ClassVar[tuple[str, ...]] = ("query",)

    def __init__(
        self,
        *,
        credentials: dict[str, Any] | None = None,
        search: SearchParams | None = None,
    ) -> None:
        """Construct the plugin from credentials and search parameters.

        Args:
            credentials: Dict containing ``api_key`` (the RapidAPI key).
            search: :class:`~job_aggregator.schema.SearchParams` carrying
                ``query``, ``location``, and ``max_pages``.

        Raises:
            CredentialsError: If ``api_key`` is absent or empty in
                *credentials*.
        """
        super().__init__(credentials=credentials, search=search)
        creds: dict[str, Any] = credentials or {}
        api_key: str = str(creds.get("api_key") or "").strip()
        if not api_key:
            raise CredentialsError(self.SOURCE, ["api_key"])

        s = search or SearchParams()
        self._api_key: str = api_key
        self._query: str = s.query or ""
        self._location: str = s.location or ""
        self._max_pages: int = s.max_pages if s.max_pages is not None else 5
        self._distance: int = 0
        self._max_days_old: int = 0

    # ------------------------------------------------------------------
    # JobSource interface
    # ------------------------------------------------------------------

    @classmethod
    def settings_schema(cls) -> dict[str, Any]:
        """Return field definitions for the RapidAPI key credential.

        Returns:
            A single-entry dict describing the ``api_key`` password field.
        """
        return {
            "api_key": {
                "label": "RapidAPI Key",
                "type": "password",
                "required": True,
                "help_text": (
                    "Your RapidAPI subscription key for the JSearch API. "
                    "Found in your RapidAPI developer dashboard."
                ),
            }
        }

    def pages(self) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of normalised job listings from the JSearch API.

        Each iteration makes two API requests (local + remote).  Results are
        deduplicated by ``job_id`` within each page before normalisation.

        Yields:
            A list of normalised :class:`~job_aggregator.schema.JobRecord`
            dicts for each page.  An empty list signals that the page
            returned no usable data.
        """
        headers: dict[str, str] = {
            "X-RapidAPI-Key": self._api_key,
            "X-RapidAPI-Host": _JSEARCH_HOST,
        }

        date_posted = _map_date_posted(self._max_days_old)

        base_params: dict[str, Any] = {"num_pages": 1}
        if date_posted is not None:
            base_params["date_posted"] = date_posted

        for page_num in range(1, self._max_pages + 1):
            page_params = {**base_params, "page": page_num}

            # --- Local (geo-matched) query ---
            local_raw: list[dict[str, Any]] = []
            if self._location:
                local_p = {
                    **page_params,
                    "query": f"{self._query} in {self._location}",
                }
                if self._distance:
                    local_p["radius"] = self._distance
                local_raw = self._fetch_raw(local_p, headers, page_num, label="local")

            # --- Remote-only query ---
            remote_p = {
                **page_params,
                "query": self._query,
                "remote_jobs_only": "true",
            }
            remote_raw = self._fetch_raw(remote_p, headers, page_num, label="remote")

            # Deduplicate by job_id and normalise.
            seen: set[str] = set()
            normalised: list[dict[str, Any]] = []
            for job in local_raw + remote_raw:
                job_id = str(job.get("job_id", ""))
                if job_id in seen:
                    continue
                seen.add(job_id)
                normalised.append(self.normalise(job))

            yield normalised

    def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map a single JSearch listing dict to the canonical JobRecord shape.

        JSearch provides full plaintext descriptions in every response, so
        ``description_source`` is always ``"full"``.  Apply links point to
        ATS portals; ``job_google_link`` is used as the fallback URL when
        ``job_apply_link`` is absent.

        Field audit against spec §9.3:

        **Identity:**
        - ``source`` ← hardcoded ``"jsearch"``
        - ``source_id`` ← ``job_id``
        - ``description_source`` ← hardcoded ``"full"``

        **Always-present:**
        - ``title`` ← ``job_title``
        - ``url`` ← ``job_apply_link`` (fallback: ``job_google_link``, then ``""``)
        - ``posted_at`` ← ``job_posted_at_datetime_utc``
        - ``description`` ← ``job_description``

        **Optional:**
        - ``company`` ← ``employer_name``
        - ``location`` ← assembled from ``job_city``, ``job_state``,
          ``job_country``; falls back to ``job_location``; ``None`` when empty
        - ``salary_min`` ← ``job_min_salary``
        - ``salary_max`` ← ``job_max_salary``
        - ``salary_currency`` ← ``None`` (JSearch does not expose currency)
        - ``salary_period`` ← ``job_salary_period`` via ``_normalise_salary_period``
        - ``contract_type`` ← ``None`` (no permanent/contract distinction)
        - ``contract_time`` ← ``job_employment_type`` via ``_normalise_contract_time``
        - ``remote_eligible`` ← ``job_is_remote`` (bool or ``None``)

        **Dropped fields (deliberate):**
        - ``job_publisher`` — drop: routing metadata, not useful for display
        - ``job_id`` — captured as ``source_id``; raw field not propagated
        - ``employer_logo`` — drop: UI asset, not part of the record schema
        - ``employer_website`` — drop: company metadata, not a job field
        - ``job_highlights`` — drop: structured sub-sections already in description
        - ``job_offer_expiration_datetime_utc`` — drop: internal ATS metadata
        - ``job_required_experience`` — drop: structured sub-field in description
        - ``job_required_skills`` — drop: structured sub-field in description
        - ``job_required_education`` — drop: structured sub-field in description
        - ``job_benefits`` — drop: structured sub-field in description
        - ``job_google_link`` — used as URL fallback only; not propagated further
        - ``job_apply_is_direct`` — drop: routing hint, not schema field
        - ``job_apply_quality_score`` — drop: internal ranking score

        Args:
            raw: A single entry from the JSearch ``data`` array.

        Returns:
            A normalised dict conforming to :class:`~job_aggregator.schema.JobRecord`.
        """
        # Assemble location from structured parts; fall back to job_location.
        location_parts = [
            raw.get("job_city") or "",
            raw.get("job_state") or "",
            raw.get("job_country") or "",
        ]
        location_str = ", ".join(p for p in location_parts if p)
        if not location_str:
            location_str = raw.get("job_location") or ""
        location: str | None = location_str if location_str else None

        url: str = raw.get("job_apply_link") or raw.get("job_google_link") or ""

        # job_is_remote may be absent entirely — map to None in that case.
        is_remote_raw = raw.get("job_is_remote")
        remote_eligible: bool | None = bool(is_remote_raw) if is_remote_raw is not None else None

        return {
            # Identity
            "source": self.SOURCE,
            "source_id": str(raw.get("job_id", "")),
            "description_source": "full",
            # Always-present
            "title": raw.get("job_title") or "",
            "url": url,
            "posted_at": raw.get("job_posted_at_datetime_utc") or None,
            "description": raw.get("job_description") or "",
            # Optional
            "company": raw.get("employer_name") or None,
            "location": location,
            "salary_min": raw.get("job_min_salary"),
            "salary_max": raw.get("job_max_salary"),
            "salary_currency": None,  # drop: JSearch does not expose currency
            "salary_period": _normalise_salary_period(raw.get("job_salary_period")),
            "contract_type": None,  # drop: no permanent/contract distinction
            "contract_time": _normalise_contract_time(raw.get("job_employment_type")),
            "remote_eligible": remote_eligible,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_raw(
        self,
        params: dict[str, Any],
        headers: dict[str, str],
        page: int,
        label: str = "",
    ) -> list[dict[str, Any]]:
        """Execute one API request with retry/back-off, returning raw job dicts.

        On HTTP 429 the request is retried up to three times with exponential
        back-off (2 s, 4 s, 8 s).  Any other non-200 status, network error,
        or malformed JSON returns ``[]`` after logging a warning.

        An additional envelope check guards against RapidAPI 200-OK error
        responses: if ``status != "OK"`` the page is treated as empty.

        Args:
            params: Query parameters to send with the GET request.
            headers: HTTP headers (API key, host).
            page: 1-based page number, used only for log messages.
            label: Short identifier for the sub-query type
                (``"local"`` or ``"remote"``); used in log messages.

        Returns:
            Raw list of job dicts from the ``data`` key of the API response,
            or ``[]`` on any error.

        Raises:
            ScrapeError: Not raised directly; ``ScrapeError`` is part of the
                package error hierarchy but HTTP errors here are logged and
                swallowed so that a single bad page does not abort the run.
        """
        prefix = f"JSearch [{label}]" if label else "JSearch"
        backoff_delays = [2, 4, 8]
        response: requests.Response | None = None

        for attempt, delay in enumerate([0, *backoff_delays]):
            if delay:
                logger.warning(
                    "%s rate-limited (429); retrying in %d s (attempt %d/3)",
                    prefix,
                    delay,
                    attempt,
                )
                time.sleep(delay)

            try:
                response = requests.get(
                    _JSEARCH_URL,
                    headers=headers,
                    params=params,
                    timeout=20,
                )
            except requests.RequestException as exc:
                logger.warning("%s request failed: %s", prefix, exc)
                return []

            if response.status_code == 200:
                break
            if response.status_code == 429:
                if attempt < len(backoff_delays):
                    continue
                logger.warning(
                    "%s rate limit not resolved after %d retries; page %d skipped",
                    prefix,
                    len(backoff_delays),
                    page,
                )
                return []
            else:
                logger.warning(
                    "%s returned HTTP %d for page %d; skipping",
                    prefix,
                    response.status_code,
                    page,
                )
                return []

        if response is None:
            return []

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("%s response is not valid JSON: %s", prefix, exc)
            return []

        # Guard against HTTP-200 RapidAPI error envelopes.
        if data.get("status") != "OK":
            logger.warning(
                "%s response status is not 'OK' (got %r); page %d skipped",
                prefix,
                data.get("status"),
                page,
            )
            return []

        return list(data.get("data", []))


# ---------------------------------------------------------------------------
# Public re-export (entry-point target)
# ---------------------------------------------------------------------------

__all__ = ["Plugin"]


def _map_date_posted(max_days_old: int) -> str | None:
    """Convert a ``max_days_old`` integer to a JSearch ``date_posted`` value.

    JSearch accepts a small set of named intervals.  Values are bucketed to
    the nearest supported interval.  ``0`` means no filter — the caller
    should omit the parameter entirely.

    Args:
        max_days_old: Maximum listing age in days.

    Returns:
        One of ``"today"``, ``"3days"``, ``"week"``, ``"month"``, or ``None``
        when *max_days_old* is ``0``.
    """
    if max_days_old == 0:
        return None
    if max_days_old == 1:
        return "today"
    if max_days_old <= 3:
        return "3days"
    if max_days_old <= 7:
        return "week"
    return "month"
