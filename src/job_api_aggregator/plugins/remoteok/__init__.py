"""RemoteOK job-source plugin for job-aggregator.

RemoteOK exposes a single public endpoint (https://remoteok.com/api) that
returns all current remote listings as one JSON array.  The first element
in the array is an API metadata object and is skipped during ingestion.

No API key is required, but the server blocks requests that omit a
``User-Agent`` header.  The default user-agent string can be overridden
by passing ``user_agent`` as a keyword argument to the constructor.

Example::

    from job_aggregator.plugins.remoteok import Plugin

    plugin = Plugin()
    for page in plugin.pages():
        for record in page:
            print(record["title"])
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, ClassVar, Literal

import requests
from bs4 import BeautifulSoup

from job_aggregator.base import JobSource
from job_aggregator.errors import ScrapeError
from job_aggregator.schema import SearchParams

logger = logging.getLogger(__name__)

_REMOTEOK_API: str = "https://remoteok.com/api"
_DEFAULT_USER_AGENT: str = "job-aggregator/1.0"


class Plugin(JobSource):
    """JobSource implementation for the RemoteOK public jobs API.

    RemoteOK returns all listings in a single un-paginated request.
    ``pages()`` therefore yields at most one list.  The API has soft
    rate limits with no published quota — callers should add their own
    back-off when running automated jobs.

    Attributes:
        SOURCE: Canonical plugin key ``"remoteok"``.
        DISPLAY_NAME: Human-readable name ``"Remote OK"``.
        DESCRIPTION: Short description from ``source.json``.
        HOME_URL: ``"https://remoteok.com"``.
        GEO_SCOPE: ``"remote-only"`` — every listing is a remote role.
        ACCEPTS_QUERY: ``"never"`` — the API has no query parameter.
        ACCEPTS_LOCATION: ``False`` — no location filter available.
        ACCEPTS_COUNTRY: ``False`` — no country filter available.
        RATE_LIMIT_NOTES: One-line rate-limit summary.
        REQUIRED_SEARCH_FIELDS: ``()`` — no mandatory search params.
    """

    SOURCE: ClassVar[str] = "remoteok"
    DISPLAY_NAME: ClassVar[str] = "Remote OK"
    DESCRIPTION: ClassVar[str] = (
        "Remote-only job board with a free public API. High volume of dev, "
        "design, and tech roles worldwide. No API key required."
    )
    HOME_URL: ClassVar[str] = "https://remoteok.com"
    GEO_SCOPE: ClassVar[
        Literal["global", "global-by-country", "remote-only", "federal-us", "regional", "unknown"]
    ] = "remote-only"
    ACCEPTS_QUERY: ClassVar[Literal["always", "partial", "never"]] = "never"
    ACCEPTS_LOCATION: ClassVar[bool] = False
    ACCEPTS_COUNTRY: ClassVar[bool] = False
    RATE_LIMIT_NOTES: ClassVar[str] = (
        "Public API, no published quota; soft rate limits enforced server-side."
    )
    REQUIRED_SEARCH_FIELDS: ClassVar[tuple[str, ...]] = ()

    def __init__(
        self,
        *,
        credentials: dict[str, Any] | None = None,
        search: SearchParams | None = None,
    ) -> None:
        """Initialise the RemoteOK plugin.

        RemoteOK requires no authentication; the ``credentials``
        argument is accepted for API uniformity but is silently ignored.

        Args:
            credentials: Accepted for interface uniformity; not used.
            search: :class:`~job_aggregator.schema.SearchParams` instance.
                All search fields are ignored because RemoteOK has no
                query, location, or country filter.
        """
        super().__init__(credentials=credentials, search=search)
        self._user_agent: str = _DEFAULT_USER_AGENT

    # ------------------------------------------------------------------
    # JobSource abstract method implementations
    # ------------------------------------------------------------------

    @classmethod
    def settings_schema(cls) -> dict[str, Any]:
        """Return an empty settings schema — RemoteOK needs no credentials.

        Returns:
            An empty dict because RemoteOK is a fully public API.
        """
        return {}

    def pages(self) -> Iterator[list[dict[str, Any]]]:
        """Yield the single page of raw RemoteOK listings.

        Fetches ``https://remoteok.com/api``, filters out the leading
        metadata element, and yields the remaining items as one list.
        Yields nothing if the API request fails or returns no valid
        listings.

        Yields:
            A single list of raw listing dicts from the RemoteOK API.

        Raises:
            ScrapeError: If the HTTP request fails with a non-200 status
                or the response body is not parseable JSON.
        """
        raw_jobs = self._fetch_all()
        if raw_jobs:
            yield raw_jobs

    def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map a raw RemoteOK listing dict to the JobRecord schema.

        Field-level notes:

        - ``posted_at``: RemoteOK never sets a ``posted_at`` field;
          the value is backfilled from the ``date`` field (mirrors
          ``ingest.run()`` lines 1503-1504 in the legacy repo).
        - ``salary_min`` / ``salary_max``: RemoteOK uses ``0`` to mean
          "not specified"; these are coerced to ``None``.
        - ``location``: falls back to ``"Remote"`` when raw value is
          empty — every RemoteOK listing is a remote role.
        - ``description``: HTML tags are stripped via BeautifulSoup so
          downstream scoring sees plain text.
        - ``remote_eligible``: always ``True`` — RemoteOK is a
          remote-only board.
        - ``salary_currency``: dropped — RemoteOK does not expose a
          currency field; always ``None``.
        - ``salary_period``: dropped — RemoteOK does not expose a
          pay-period field; always ``None``.
        - ``contract_type``: dropped — not exposed by API.
        - ``contract_time``: dropped — not exposed by API.
        - ``tags``: stored in ``extra`` dict for downstream use.
        - ``logo``: drop — presentation concern, not a job attribute.
        - ``apply_url``: drop — ``url`` (the canonical listing URL) is
          used instead; ``apply_url`` is a duplicate with different UX
          intent.

        Args:
            raw: A single raw listing dict from the RemoteOK API.

        Returns:
            A normalised dict conforming to :class:`~job_aggregator.schema.JobRecord`.
        """
        # ---- salary: 0 or absent → None --------------------------------
        raw_salary_min = raw.get("salary_min")
        raw_salary_max = raw.get("salary_max")
        salary_min: float | None = float(raw_salary_min) if raw_salary_min else None
        salary_max: float | None = float(raw_salary_max) if raw_salary_max else None
        if salary_min == 0.0:
            salary_min = None
        if salary_max == 0.0:
            salary_max = None

        # ---- location: empty → "Remote" --------------------------------
        location: str = (raw.get("location") or "").strip() or "Remote"

        # ---- description: strip HTML -----------------------------------
        raw_description: str = raw.get("description") or ""
        if raw_description:
            description: str = BeautifulSoup(raw_description, "html.parser").get_text(
                separator=" ", strip=True
            )
        else:
            description = ""

        # ---- posted_at backfilled from date ----------------------------
        # RemoteOK never sets posted_at; backfill from `date` which holds
        # the listing creation timestamp (mirrors legacy ingest.run() logic).
        posted_at: str | None = raw.get("date") or None

        # ---- extra: retain tags for downstream use ---------------------
        tags = raw.get("tags")
        extra: dict[str, Any] | None = {"tags": tags} if tags is not None else None

        # ---- dropped fields (see docstring) ----------------------------
        # logo     → drop: presentation concern, not a job attribute
        # apply_url → drop: url (canonical listing URL) is used instead

        return {
            # Identity
            "source": self.SOURCE,
            "source_id": str(raw.get("id", "")),
            "description_source": "snippet",
            # Always-present
            "title": raw.get("position", "") or "",
            "url": raw.get("url", "") or "",
            "posted_at": posted_at,
            "description": description,
            # Optional
            "company": raw.get("company") or None,
            "location": location,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_currency": None,  # drop: not exposed by RemoteOK API
            "salary_period": None,  # drop: not exposed by RemoteOK API
            "contract_type": None,  # drop: not exposed by RemoteOK API
            "contract_time": None,  # drop: not exposed by RemoteOK API
            "remote_eligible": True,  # always True — remote-only board
            # Source-specific blob
            "extra": extra,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_all(self) -> list[dict[str, Any]]:
        """Fetch the full RemoteOK listing array from the public API.

        Skips the first element of the response array (API metadata object)
        by filtering for items that have both ``"id"`` and ``"position"``
        keys.  This matches the legacy plugin behaviour and handles the case
        where RemoteOK changes the metadata object position.

        Returns:
            List of raw job listing dicts.

        Raises:
            ScrapeError: If the HTTP request returns a non-200 status or
                the response body cannot be decoded as JSON.
        """
        headers = {"User-Agent": self._user_agent}
        try:
            response = requests.get(_REMOTEOK_API, headers=headers, timeout=15)
        except requests.RequestException as exc:
            raise ScrapeError(_REMOTEOK_API, str(exc)) from exc

        if response.status_code != 200:
            raise ScrapeError(
                _REMOTEOK_API,
                f"HTTP {response.status_code}",
            )

        try:
            data: list[Any] = response.json()
        except ValueError as exc:
            raise ScrapeError(_REMOTEOK_API, f"JSON decode error: {exc}") from exc

        if not isinstance(data, list):
            raise ScrapeError(_REMOTEOK_API, "Response is not a JSON array")

        # Filter to items that look like job listings (have both "id" and
        # "position").  This naturally skips the metadata object at data[0]
        # which lacks these fields.
        return [
            item for item in data if isinstance(item, dict) and "id" in item and "position" in item
        ]
