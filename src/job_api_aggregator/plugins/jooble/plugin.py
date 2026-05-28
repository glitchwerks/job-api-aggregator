"""Jooble API implementation of the JobSource plugin contract.

Wraps the Jooble job-search REST API (POST ``https://jooble.org/api/{key}``):

- Page-number pagination with ``totalCount``-based ceiling calculation.
- First-page response is cached so ``pages()`` never issues a duplicate
  HTTP request for page 1.
- HTML is stripped from ``snippet`` using BeautifulSoup.
- Salary is parsed best-effort from the free-text ``salary`` field.
- The ``type`` field is mapped to canonical ``contract_time`` values.
- ``salary_period`` and ``salary_currency`` are always ``None`` because
  neither can be reliably determined from Jooble's free-text salary field.
- ``description_source`` is always ``"snippet"``; Jooble ``/jdp/`` detail
  pages return HTTP 403 to unauthenticated requests so full-text scraping
  is not viable.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterator
from typing import Any, ClassVar, Literal

import requests
from bs4 import BeautifulSoup

from job_aggregator.base import JobSource
from job_aggregator.errors import CredentialsError
from job_aggregator.schema import SearchParams

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://jooble.org/api/{api_key}"

_DEFAULT_RESULTS_PER_PAGE = 20
_DEFAULT_MAX_PAGES = 5

# Mapping of Jooble ``type`` strings (lower-cased) to canonical values.
_CONTRACT_TIME_MAP: dict[str, str] = {
    "full-time": "full_time",
    "part-time": "part_time",
    "contract": "contract",
}

# Salary parsing: match sequences of digits (with optional commas/dots).
_SALARY_NUMBER_RE = re.compile(r"[\d,]+(?:\.\d+)?")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_html(text: str) -> str:
    """Remove HTML tags from *text* and collapse whitespace.

    Uses BeautifulSoup with the built-in ``html.parser`` backend (no
    external parser dependency required).

    Args:
        text: Raw HTML string, possibly empty.

    Returns:
        Plain-text string with tags removed and whitespace normalised.
        Returns an empty string if *text* is empty or only whitespace.
    """
    if not text:
        return ""
    plain = BeautifulSoup(text, "html.parser").get_text(separator=" ")
    return " ".join(plain.split())


def _parse_salary(salary_text: str) -> tuple[float | None, float | None]:
    """Parse salary bounds from a free-text Jooble salary string.

    Extracts all numeric tokens from *salary_text* (stripping commas),
    treats the first as ``salary_min`` and the second (if present) as
    ``salary_max``.

    Args:
        salary_text: Raw salary string, e.g. ``"$120,000 - $150,000"``
            or ``"From $80k"`` or an empty string.

    Returns:
        A ``(salary_min, salary_max)`` tuple.  Either value may be
        ``None`` when the corresponding bound cannot be parsed.
    """
    if not salary_text:
        return None, None

    matches = _SALARY_NUMBER_RE.findall(salary_text)
    if not matches:
        return None, None

    def _to_float(token: str) -> float | None:
        """Convert a token string to float, returning None on failure.

        Args:
            token: Numeric string possibly containing commas.

        Returns:
            Float value or None if conversion fails.
        """
        try:
            return float(token.replace(",", ""))
        except ValueError:
            return None

    salary_min = _to_float(matches[0])
    salary_max = _to_float(matches[1]) if len(matches) >= 2 else None
    return salary_min, salary_max


def _normalise_contract_time(raw_type: str) -> str:
    """Map a Jooble ``type`` string to the canonical ``contract_time`` value.

    Known values such as ``"Full-time"`` and ``"Part-time"`` are mapped
    to their canonical equivalents.  Unmapped values are passed through
    unchanged so downstream filters can still process them.

    Args:
        raw_type: Raw type string from the Jooble API (e.g. ``"Full-time"``).

    Returns:
        Canonical ``contract_time`` string, or the original value if no
        mapping exists.
    """
    return _CONTRACT_TIME_MAP.get(raw_type.lower(), raw_type)


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------


class Plugin(JobSource):
    """JobSource plugin for the Jooble job-search API.

    Jooble uses page-number pagination with a POST body.  ``total_pages()``
    fetches page 1 to read ``totalCount`` and computes the page ceiling.
    Results are capped at ``max_pages`` (default 5) to limit API usage.

    The first-page response from ``total_pages()`` is cached so that
    ``pages()`` does not re-issue the same HTTP request.

    Attributes:
        SOURCE: Plugin key ``"jooble"``.
        DISPLAY_NAME: ``"Jooble"``.
        DESCRIPTION: Description copied verbatim from legacy ``source.json``.
        HOME_URL: ``"https://jooble.org"``.
        GEO_SCOPE: ``"global"`` — Jooble aggregates from hundreds of boards
            worldwide with no per-country filter.
        ACCEPTS_QUERY: ``"always"`` — the ``keywords`` parameter is always
            sent in the POST body.
        ACCEPTS_LOCATION: ``True`` — the ``location`` parameter is supported.
        ACCEPTS_COUNTRY: ``False`` — no country-code filter exists in the API.
        RATE_LIMIT_NOTES: Free-tier key; no published hard limit but
            Jooble recommends keeping requests reasonable.
        REQUIRED_SEARCH_FIELDS: ``()`` — no field is mandatory.
    """

    SOURCE: ClassVar[str] = "jooble"
    DISPLAY_NAME: ClassVar[str] = "Jooble"
    DESCRIPTION: ClassVar[str] = (
        "Aggregates listings from hundreds of boards worldwide. "
        "Free API key required (register at jooble.org). "
        "Broad coverage; description quality varies."
    )
    HOME_URL: ClassVar[str] = "https://jooble.org"
    GEO_SCOPE: ClassVar[
        Literal[
            "global",
            "global-by-country",
            "remote-only",
            "federal-us",
            "regional",
            "unknown",
        ]
    ] = "global"
    ACCEPTS_QUERY: ClassVar[Literal["always", "partial", "never"]] = "always"
    ACCEPTS_LOCATION: ClassVar[bool] = True
    ACCEPTS_COUNTRY: ClassVar[bool] = False
    RATE_LIMIT_NOTES: ClassVar[str] = "No published hard limit; free-tier key, use responsibly."
    REQUIRED_SEARCH_FIELDS: ClassVar[tuple[str, ...]] = ()

    def __init__(
        self,
        *,
        credentials: dict[str, Any] | None = None,
        search: SearchParams | None = None,
    ) -> None:
        """Construct a Jooble plugin instance.

        Args:
            credentials: Dict containing ``"api_key"`` (required).
            search: :class:`~job_aggregator.schema.SearchParams` carrying
                ``query``, ``location``, and ``max_pages``.

        Raises:
            CredentialsError: If ``credentials`` does not contain a
                non-empty ``"api_key"``.
        """
        super().__init__(credentials=credentials, search=search)
        creds: dict[str, Any] = credentials or {}
        api_key: str = str(creds.get("api_key") or "").strip()
        if not api_key:
            raise CredentialsError(
                plugin_key=self.SOURCE,
                missing_fields=["api_key"],
            )

        s = search or SearchParams()
        self._api_key: str = api_key
        self._query: str = s.query or "software engineer"
        self._location: str = s.location or ""
        self._results_per_page: int = _DEFAULT_RESULTS_PER_PAGE
        self._max_pages: int = s.max_pages if s.max_pages is not None else _DEFAULT_MAX_PAGES
        self._url: str = _BASE_URL.format(api_key=self._api_key)

        # Cache populated by the first call to total_pages().
        self._cached_total_pages: int | None = None
        self._cached_first_page: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # JobSource abstract method implementations
    # ------------------------------------------------------------------

    @classmethod
    def settings_schema(cls) -> dict[str, Any]:
        """Return the credential field definitions for the Jooble plugin.

        Returns:
            A dict with a single ``"api_key"`` field definition marked
            as required.
        """
        return {
            "api_key": {
                "label": "API Key",
                "type": "password",
                "required": True,
                "help_text": ("Register for a free key at https://jooble.org/api/about"),
            },
        }

    def pages(self) -> Iterator[list[dict[str, Any]]]:
        """Yield normalised listing lists, one per API page.

        Reuses the page-1 response cached by ``total_pages()`` to avoid
        a duplicate HTTP request, then iterates from page 2 up to
        ``total_pages()`` (inclusive).  Stops early if a page returns
        zero results.

        Yields:
            Lists of normalised listing dicts produced by
            :meth:`normalise`.
        """
        total = self.total_pages()  # populates _cached_first_page

        if self._cached_first_page is not None:
            yield [self.normalise(r) for r in self._cached_first_page]
            start_page = 2
        else:
            start_page = 1

        for page in range(start_page, total + 1):
            raw_jobs = self._fetch_raw_page(page)
            if not raw_jobs:
                logger.info("Jooble page %d returned 0 results; stopping early.", page)
                return
            yield [self.normalise(r) for r in raw_jobs]

    def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map a single Jooble API listing dict to the normalised schema.

        HTML is stripped from the ``snippet`` field using BeautifulSoup.
        Salary bounds are parsed best-effort from the free-text ``salary``
        field.  ``salary_period`` and ``salary_currency`` are always
        ``None`` because neither can be reliably inferred from Jooble's
        format.  ``contract_time`` is mapped from the ``type`` field
        where possible.

        ``description_source`` is set to ``"snippet"`` because Jooble's
        ``/jdp/<id>`` detail pages return HTTP 403 to unauthenticated
        requests — the API snippet is the only description text available.

        Field audit (§9.3 categories):

        Identity fields:
            - ``id``            → ``source_id`` (str coercion)
            - (constant)        → ``source`` = ``"jooble"``
            - (constant)        → ``description_source`` = ``"snippet"``

        Always-present fields:
            - ``title``         → ``title``
            - ``link``          → ``url``
            - ``updated``       → ``posted_at``
            - ``snippet``       → ``description`` (HTML stripped)

        Optional fields:
            - ``company``       → ``company``
            - ``location``      → ``location``
            - ``salary``        → ``salary_min``, ``salary_max`` (parsed)
            - ``type``          → ``contract_time`` (mapped)
            - (drop) ``salary`` → ``salary_period`` = None
              (reason: period not inferrable from free-text)
            - (drop) ``salary`` → ``salary_currency`` = None
              (reason: currency not reliably parseable)
            - (drop) n/a        → ``contract_type`` = None
              (reason: Jooble has no separate contract type field)
            - (drop) n/a        → ``remote_eligible`` = None
              (reason: Jooble does not expose a remote flag)
            - (drop) n/a        → ``extra`` = None
              (reason: no source-specific fields worth preserving)

        Args:
            raw: A single entry from the Jooble ``jobs`` array.

        Returns:
            Normalised dict conforming to the :class:`~job_aggregator.schema.JobRecord`
            contract.
        """
        salary_min, salary_max = _parse_salary(raw.get("salary") or "")

        raw_type: str = raw.get("type") or ""
        contract_time: str = _normalise_contract_time(raw_type) if raw_type else ""

        return {
            # ---- Identity ----
            "source": self.SOURCE,
            "source_id": str(raw.get("id") or ""),
            "description_source": "snippet",
            # ---- Always-present ----
            "title": raw.get("title") or "",
            "url": raw.get("link") or "",
            "posted_at": raw.get("updated") or "",
            "description": _strip_html(raw.get("snippet") or ""),
            # ---- Optional ----
            "company": raw.get("company") or "",
            "location": raw.get("location") or "",
            "salary_min": salary_min,
            "salary_max": salary_max,
            # drop: salary_period — period not inferrable from free-text
            "salary_period": None,
            # drop: salary_currency — currency not reliably parseable
            "salary_currency": None,
            # drop: contract_type — no separate contract type field in Jooble
            "contract_type": None,
            "contract_time": contract_time,
            # drop: remote_eligible — Jooble does not expose a remote flag
            "remote_eligible": None,
            # drop: extra — no source-specific fields worth preserving
            "extra": None,
        }

    # ------------------------------------------------------------------
    # Pagination helpers
    # ------------------------------------------------------------------

    def total_pages(self) -> int:
        """Return the number of available pages, capped at ``max_pages``.

        Fetches page 1 on the first call to read ``totalCount``.  The
        result is cached for the lifetime of the instance so subsequent
        calls do not issue additional HTTP requests.  The raw page-1 jobs
        are also cached so :meth:`pages` can reuse them.

        Returns:
            ``ceil(totalCount / results_per_page)`` capped at
            ``max_pages``.  Returns ``1`` as a safe fallback on any
            request or parse error.
        """
        if self._cached_total_pages is not None:
            return self._cached_total_pages

        payload: dict[str, Any] = {
            "keywords": self._query,
            "location": self._location,
            "page": 1,
        }

        try:
            response = requests.post(self._url, json=payload, timeout=15)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Jooble total_pages() request failed: %s", exc)
            self._cached_total_pages = 1
            return 1

        # Cache raw page-1 results so pages() does not re-fetch.
        self._cached_first_page = data.get("jobs", [])

        try:
            total_count = int(data.get("totalCount", 0))
        except (TypeError, ValueError):
            total_count = 0

        if total_count <= 0:
            self._cached_total_pages = 1
            return 1

        page_count = math.ceil(total_count / self._results_per_page)
        self._cached_total_pages = min(page_count, self._max_pages)
        return self._cached_total_pages

    def _fetch_raw_page(self, page: int) -> list[dict[str, Any]]:
        """Fetch a single page of raw Jooble listing dicts.

        On any non-200 HTTP status or network / JSON error the method
        logs a warning and returns an empty list so the caller can
        continue without crashing.

        Args:
            page: 1-based page number.

        Returns:
            List of raw listing dicts from the Jooble ``jobs`` array.
            Returns ``[]`` on any error.
        """
        payload: dict[str, Any] = {
            "keywords": self._query,
            "location": self._location,
            "page": page,
        }

        try:
            response = requests.post(self._url, json=payload, timeout=15)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except requests.RequestException as exc:
            logger.warning("Jooble request failed (page %d): %s", page, exc)
            return []
        except ValueError as exc:
            logger.warning("Jooble response is not valid JSON (page %d): %s", page, exc)
            return []

        raw_jobs: list[dict[str, Any]] = data.get("jobs", [])
        return raw_jobs
