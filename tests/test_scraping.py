"""Tests for job_api_aggregator.scraping — scrape_description and SCRAPE_MIN_LENGTH.

Covers:
- SCRAPE_MIN_LENGTH is a public int constant.
- scrape_description returns (text, True) on a successful scrape.
- scrape_description returns (fallback, False) on HTTP non-200.
- scrape_description returns (fallback, False) on a network error.
- scrape_description returns (fallback, False) when scraped text is below
  SCRAPE_MIN_LENGTH.
- Noise tags (script, style, nav, header, footer) are stripped from the output.
- Whitespace is collapsed to single spaces.
- SCRAPE_MIN_LENGTH is importable from the package root (re-export check).
"""

from __future__ import annotations

import responses as resp

from job_api_aggregator.scraping import SCRAPE_MIN_LENGTH, scrape_description

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LONG_TEXT = "word " * 120  # 600 chars — safely above MIN


def _html_page(body_inner: str) -> str:
    """Wrap *body_inner* in minimal HTML."""
    return f"<html><body>{body_inner}</body></html>"


# ---------------------------------------------------------------------------
# SCRAPE_MIN_LENGTH
# ---------------------------------------------------------------------------


def test_scrape_min_length_is_public_int() -> None:
    """SCRAPE_MIN_LENGTH must be a public integer constant."""
    assert isinstance(SCRAPE_MIN_LENGTH, int)
    assert SCRAPE_MIN_LENGTH > 0


def test_scrape_min_length_re_exported_from_package() -> None:
    """SCRAPE_MIN_LENGTH must still be importable from the package root."""
    from job_api_aggregator import SCRAPE_MIN_LENGTH as PKG_MIN

    assert PKG_MIN is SCRAPE_MIN_LENGTH


# ---------------------------------------------------------------------------
# scrape_description — success
# ---------------------------------------------------------------------------


@resp.activate
def test_scrape_description_success_returns_text_and_true() -> None:
    """A 200 response with enough text returns (text, True)."""
    url = "https://example.com/job/1"
    html = _html_page(f"<p>{_LONG_TEXT}</p>")
    resp.add(resp.GET, url, body=html, status=200)

    text, ok = scrape_description(url)

    assert ok is True
    assert len(text) >= SCRAPE_MIN_LENGTH
    # Collapsed whitespace — no double spaces
    assert "  " not in text


@resp.activate
def test_scrape_description_uses_fallback_by_default() -> None:
    """Default fallback is empty string when no fallback is supplied."""
    url = "https://example.com/job/2"
    resp.add(resp.GET, url, status=404)

    text, ok = scrape_description(url)

    assert ok is False
    assert text == ""


@resp.activate
def test_scrape_description_uses_supplied_fallback_on_failure() -> None:
    """When scrape fails, the caller-supplied fallback is returned."""
    url = "https://example.com/job/3"
    resp.add(resp.GET, url, status=500)

    text, ok = scrape_description(url, fallback="original snippet")

    assert ok is False
    assert text == "original snippet"


# ---------------------------------------------------------------------------
# scrape_description — HTTP failures
# ---------------------------------------------------------------------------


@resp.activate
def test_scrape_description_non_200_returns_fallback_false() -> None:
    """Any non-200 HTTP status triggers the fallback path."""
    url = "https://example.com/job/4"
    resp.add(resp.GET, url, status=403)

    _, ok = scrape_description(url, fallback="fb")

    assert ok is False


@resp.activate
def test_scrape_description_5xx_returns_fallback_false() -> None:
    """5xx responses also trigger the fallback path."""
    url = "https://example.com/job/5"
    resp.add(resp.GET, url, status=503)

    _, ok = scrape_description(url, fallback="fb")

    assert ok is False


# ---------------------------------------------------------------------------
# scrape_description — network error
# ---------------------------------------------------------------------------


@resp.activate
def test_scrape_description_network_error_returns_fallback_false() -> None:
    """A network-level exception (ConnectionError) triggers the fallback."""
    import requests as _req

    url = "https://example.com/job/6"
    resp.add(resp.GET, url, body=_req.exceptions.ConnectionError("timeout"))

    text, ok = scrape_description(url, fallback="kept")

    assert ok is False
    assert text == "kept"


# ---------------------------------------------------------------------------
# scrape_description — text too short
# ---------------------------------------------------------------------------


@resp.activate
def test_scrape_description_short_body_returns_fallback_false() -> None:
    """Scraped text shorter than SCRAPE_MIN_LENGTH is treated as failure."""
    url = "https://example.com/job/7"
    short_text = "x" * (SCRAPE_MIN_LENGTH - 1)
    html = _html_page(f"<p>{short_text}</p>")
    resp.add(resp.GET, url, body=html, status=200)

    text, ok = scrape_description(url, fallback="kept snippet")

    assert ok is False
    assert text == "kept snippet"


@resp.activate
def test_scrape_description_exactly_min_length_succeeds() -> None:
    """Text of exactly SCRAPE_MIN_LENGTH characters is classified as success."""
    url = "https://example.com/job/8"
    exact_text = "a" * SCRAPE_MIN_LENGTH
    html = _html_page(f"<p>{exact_text}</p>")
    resp.add(resp.GET, url, body=html, status=200)

    text, ok = scrape_description(url)

    assert ok is True
    assert len(text) >= SCRAPE_MIN_LENGTH


# ---------------------------------------------------------------------------
# scrape_description — noise-tag removal
# ---------------------------------------------------------------------------


@resp.activate
def test_scrape_description_strips_noise_tags() -> None:
    """script, style, nav, header, footer content must not appear in output."""
    url = "https://example.com/job/9"
    html = (
        "<html><body>"
        "<script>var x=1;</script>"
        "<style>.foo{color:red}</style>"
        "<nav>Home About Contact</nav>"
        "<header>Site Header Text</header>"
        "<footer>Site Footer Text</footer>"
        f"<main><p>{_LONG_TEXT}</p></main>"
        "</body></html>"
    )
    resp.add(resp.GET, url, body=html, status=200)

    text, ok = scrape_description(url)

    assert ok is True
    assert "var x=1" not in text
    assert ".foo" not in text
    assert "Site Header Text" not in text
    assert "Site Footer Text" not in text


# ---------------------------------------------------------------------------
# scrape_description — whitespace collapsing
# ---------------------------------------------------------------------------


@resp.activate
def test_scrape_description_collapses_whitespace() -> None:
    """Multiple whitespace characters in the body are collapsed to one space."""
    url = "https://example.com/job/10"
    # Use enough repetitions that after whitespace collapse the text is
    # still >= SCRAPE_MIN_LENGTH.  "word " (5 chars) * 120 = 600 chars
    # before collapse; after collapse still well above 500.
    padded = ("word   \n\n   " * 120).strip()
    html = _html_page(f"<p>{padded}</p>")
    resp.add(resp.GET, url, body=html, status=200)

    text, ok = scrape_description(url)

    assert ok is True
    assert "  " not in text
