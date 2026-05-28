"""Remotive source plugin for job-aggregator.

Wraps the public Remotive remote-jobs API (https://remotive.com/api/remote-jobs).
No authentication is required.  The API returns a single page of results;
pagination is not supported upstream.

HTML is stripped from the ``description`` field using :mod:`html.parser`
via :class:`html.parser.HTMLParser` rather than importing BeautifulSoup at
the module level, which keeps the import dependency explicit and avoids
pulling in bs4 unless it is already installed.

Salary is returned as free-text by Remotive (e.g. ``"$120k-$150k"``).
``salary_min`` / ``salary_max`` are set to ``None`` because reliable parsing
would require a heuristic that is out of scope for this plugin; the raw
string is preserved in ``extra.salary_raw``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from html.parser import HTMLParser
from typing import Any

import requests

from job_aggregator.base import JobSource
from job_aggregator.errors import ScrapeError
from job_aggregator.schema import SearchParams

logger = logging.getLogger(__name__)

_REMOTIVE_URL = "https://remotive.com/api/remote-jobs"


# ---------------------------------------------------------------------------
# HTML stripping helper
# ---------------------------------------------------------------------------


class _HTMLStripper(HTMLParser):
    """Minimal HTMLParser subclass that collects text content only.

    Attributes:
        _parts: Accumulated text fragments between tags.
    """

    def __init__(self) -> None:
        """Initialise the parser and the internal text-accumulator."""
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        """Append a text fragment from between tags.

        Args:
            data: Raw text content extracted by the HTML parser.
        """
        self._parts.append(data)

    @property
    def text(self) -> str:
        """Return all accumulated text joined into a single string.

        Returns:
            Concatenated text fragments with no extra whitespace added.
        """
        return "".join(self._parts)


def _strip_html(raw: str) -> str:
    """Remove HTML tags from *raw* and return plain text.

    Args:
        raw: A string that may contain HTML markup.

    Returns:
        Plain text with all HTML tags removed.  Whitespace inside the
        original HTML is preserved as-is; no additional normalisation is
        applied.
    """
    stripper = _HTMLStripper()
    stripper.feed(raw)
    return stripper.text


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class RemotivePlugin(JobSource):
    """JobSource plugin for the Remotive remote-jobs API.

    Remotive exposes a single public endpoint that returns a JSON object
    containing a ``"jobs"`` list.  The API is not paginated — one request
    returns all matching listings up to the configured ``limit``.

    No credentials are required.  Pass a ``query`` to filter by keyword
    or a ``category`` to restrict to a job category (e.g.
    ``"software-dev"``).  Both are optional; omitting them returns all
    recently posted remote jobs.

    Attributes:
        SOURCE: Plugin key ``"remotive"``.
        DISPLAY_NAME: ``"Remotive"``.
        DESCRIPTION: From ``source.json``.
        HOME_URL: ``"https://remotive.com"``.
        GEO_SCOPE: ``"remote-only"`` — Remotive is a curated remote board.
        ACCEPTS_QUERY: ``"always"`` — supports free-text ``search`` param.
        ACCEPTS_LOCATION: ``False`` — no location filter; all jobs remote.
        ACCEPTS_COUNTRY: ``False`` — no country filter in the API.
        RATE_LIMIT_NOTES: No published rate limit; conservative use advised.
        REQUIRED_SEARCH_FIELDS: ``()`` — no mandatory search parameters.
    """

    SOURCE = "remotive"
    DISPLAY_NAME = "Remotive"
    DESCRIPTION = (
        "Curated remote tech jobs across software, design, and marketing. "
        "Free API with no authentication. "
        "Smaller volume but strong signal-to-noise."
    )
    HOME_URL = "https://remotive.com"
    GEO_SCOPE = "remote-only"
    ACCEPTS_QUERY = "always"
    ACCEPTS_LOCATION = False
    ACCEPTS_COUNTRY = False
    RATE_LIMIT_NOTES = "No published rate limit; public API, use conservatively."
    REQUIRED_SEARCH_FIELDS = ()

    def __init__(
        self,
        *,
        credentials: dict[str, Any] | None = None,
        search: SearchParams | None = None,
    ) -> None:
        """Initialise the Remotive plugin.

        Remotive requires no authentication; the ``credentials``
        argument is accepted for API uniformity but is silently ignored.

        Args:
            credentials: Accepted for interface uniformity; not used.
            search: :class:`~job_aggregator.schema.SearchParams` instance.
                ``query`` is forwarded to the Remotive ``search``
                parameter.  Location and country are ignored because
                Remotive is a remote-only board.
        """
        super().__init__(credentials=credentials, search=search)
        self._query: str | None = search.query if search is not None else None
        extra = search.extra if search is not None else None
        self._category: str | None = extra.get("category") if extra else None
        self._limit: int = (
            search.max_pages if search is not None and search.max_pages is not None else 100
        )

    # ------------------------------------------------------------------
    # JobSource interface
    # ------------------------------------------------------------------

    @classmethod
    def settings_schema(cls) -> dict[str, Any]:
        """Return an empty schema — Remotive requires no credentials.

        Returns:
            An empty dict, as the Remotive API is public.
        """
        return {}

    def pages(self) -> Iterator[list[dict[str, Any]]]:
        """Yield the single page of Remotive listings.

        Remotive is a single-page API.  This method makes one GET request
        and yields a list of normalised :class:`~job_aggregator.schema.JobRecord`
        dicts.  Yields nothing if the API returns no listings.

        Yields:
            A single list of normalised listing dicts, or nothing if the
            response is empty or non-200.

        Raises:
            ScrapeError: If the HTTP request fails due to a network-level
                error (connection refused, timeout, DNS failure, etc.).
        """
        params: dict[str, Any] = {"limit": self._limit}
        if self._query:
            params["search"] = self._query
        if self._category:
            params["category"] = self._category

        try:
            response = requests.get(_REMOTIVE_URL, params=params, timeout=15)
        except requests.RequestException as exc:
            raise ScrapeError(
                url=_REMOTIVE_URL,
                reason=f"Network error: {exc}",
            ) from exc

        if response.status_code != 200:
            logger.warning(
                "Remotive returned HTTP %d; skipping.",
                response.status_code,
            )
            return

        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            logger.warning("Remotive response is not valid JSON: %s", exc)
            return

        raw_jobs: list[dict[str, Any]] = data.get("jobs") or []
        if not raw_jobs:
            return

        yield [self.normalise(job) for job in raw_jobs]

    def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map a single Remotive job dict to the canonical JobRecord shape.

        Field audit (§9.3 categories):

        **Identity:**
        - ``source`` — always ``"remotive"``
        - ``source_id`` — ``str(raw["id"])``; empty string when absent
        - ``description_source`` — ``"snippet"`` (Remotive provides HTML
          descriptions; full text is available but not scraped here)

        **Always-present:**
        - ``title`` — ``raw["title"]``; empty string when None
        - ``url`` — ``raw["url"]``; empty string when None
        - ``posted_at`` — ``raw["publication_date"]``; None when absent
        - ``description`` — ``raw["description"]`` with HTML stripped

        **Optional:**
        - ``company`` — ``raw["company_name"]``; None when None/absent
        - ``location`` — ``raw["candidate_required_location"]``; None when
          None/absent
        - ``salary_min`` — None (salary is free-text; cannot parse reliably)
        - ``salary_max`` — None (same reason)
        - ``salary_currency`` — None (same reason)
        - ``salary_period`` — None (same reason)
        - ``contract_type`` — None (no direct upstream equivalent)
        - ``contract_time`` — ``raw["job_type"]``; None when absent
        - ``remote_eligible`` — ``True`` (Remotive is a remote-only board)

        **Dropped fields (source-specific, stored in extra):**
        - ``raw["company_logo"]`` → ``extra["company_logo"]``
        - ``raw["category"]`` → ``extra["category"]``
        - ``raw["tags"]`` → ``extra["tags"]``
        - ``raw["salary"]`` → ``extra["salary_raw"]`` (preserved verbatim)

        Args:
            raw: A single entry from the Remotive ``"jobs"`` array.

        Returns:
            A dict conforming to :class:`~job_aggregator.schema.JobRecord`.
        """
        raw_id = raw.get("id")
        source_id = str(raw_id) if raw_id is not None else ""

        title = raw.get("title") or ""
        url = raw.get("url") or ""
        posted_at: str | None = raw.get("publication_date") or None
        raw_desc = raw.get("description") or ""
        description = _strip_html(raw_desc)

        company_raw = raw.get("company_name")
        company: str | None = company_raw if company_raw is not None else None

        location_raw = raw.get("candidate_required_location")
        location: str | None = location_raw if location_raw is not None else None

        contract_time_raw = raw.get("job_type")
        contract_time: str | None = contract_time_raw if contract_time_raw is not None else None

        # Salary is free-text (e.g. "$120k-$150k"); reliable parsing is
        # out-of-scope.  Preserve raw string in extra; numeric fields → None.
        salary_raw: str | None = raw.get("salary") or None

        extra: dict[str, Any] = {}
        if salary_raw is not None:
            extra["salary_raw"] = salary_raw
        if raw.get("company_logo") is not None:
            extra["company_logo"] = raw["company_logo"]
        if raw.get("category") is not None:
            extra["category"] = raw["category"]
        if raw.get("tags") is not None:
            extra["tags"] = raw["tags"]

        return {
            # Identity
            "source": self.SOURCE,
            "source_id": source_id,
            "description_source": "snippet",
            # Always-present
            "title": title,
            "url": url,
            "posted_at": posted_at,
            "description": description,
            # Optional
            "company": company,
            "location": location,
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_period": None,
            "contract_type": None,
            "contract_time": contract_time,
            "remote_eligible": True,
            # Source-specific blob
            "extra": extra if extra else None,
        }
