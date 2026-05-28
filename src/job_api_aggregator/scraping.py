"""HTTP scraping helpers for job description pages.

Provides :func:`scrape_description`, which fetches a job listing URL,
strips navigation/chrome noise, and returns the visible text.  Also
exports :data:`SCRAPE_MIN_LENGTH`, the minimum character length for a
description to qualify as a "full" description (spec §9.6).

This is the **canonical** definition of ``SCRAPE_MIN_LENGTH``.
``normalizer.py`` and the package root both import from here.

NOTE: No inter-request delay or robots.txt check is performed.  This is
acceptable for personal use at low volume (~50-250 listings per run), but
would require rate limiting and robots.txt compliance for any
higher-volume or production deployment.

Public API:
    :data:`SCRAPE_MIN_LENGTH` — minimum character count for "full" status.
    :func:`scrape_description` — fetch and extract visible text from a URL.
"""

from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Minimum character length for a scraped description to be classified as
#: "full" (spec §9.6).  Imported by :mod:`job_aggregator.normalizer` and
#: by ``ingest.py`` in the job-matcher-pr repo — never redefined locally.
SCRAPE_MIN_LENGTH: int = 500

# ---------------------------------------------------------------------------
# Module-private constants
# ---------------------------------------------------------------------------

_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

#: HTML tags whose content is purely structural / non-content noise.
_NOISE_TAGS: list[str] = ["script", "style", "nav", "header", "footer"]

# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def scrape_description(
    url: str,
    fallback: str = "",
    timeout: int = 15,
) -> tuple[str, bool]:
    """GET a job listing page and extract its visible text.

    Removes noise tags (script, style, nav, header, footer) and collapses
    whitespace before returning.  Falls back to *fallback* if the request
    fails, the status code is not 200, or the extracted text is under
    :data:`SCRAPE_MIN_LENGTH` characters.

    Args:
        url: The job listing URL to scrape.
        fallback: Text to return when scraping fails (typically the API
            snippet already stored in the record).
        timeout: Per-request HTTP timeout in seconds.  Defaults to 15.

    Returns:
        A ``(description_text, scraped_ok)`` tuple where ``scraped_ok`` is
        ``True`` on success and ``False`` when the fallback was used.
    """
    try:
        response = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning("Scrape request failed for %s: %s", url, exc)
        return fallback, False

    if response.status_code != 200:
        logger.warning("Scrape returned HTTP %d for %s", response.status_code, url)
        return fallback, False

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in _NOISE_TAGS:
        for element in soup.find_all(tag):
            element.decompose()

    raw_text = soup.get_text(separator=" ", strip=True)
    # Collapse runs of whitespace (spaces, tabs, newlines) to single spaces.
    cleaned = re.sub(r"\s+", " ", raw_text).strip()

    if len(cleaned) < SCRAPE_MIN_LENGTH:
        logger.warning(
            "Scraped text too short (%d chars) for %s; using fallback",
            len(cleaned),
            url,
        )
        return fallback, False

    return cleaned, True
