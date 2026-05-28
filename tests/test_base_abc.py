"""Tests for the JobSource abstract base class.

Tests verify:
- A fully-declared concrete subclass instantiates successfully
- Missing any one required class-level attribute raises TypeError at
  class-definition time
- Failing to implement an abstract method raises TypeError on instantiation
- The abstract method ABC enforcement is independent of attribute enforcement
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from job_api_aggregator.base import JobSource

# ---------------------------------------------------------------------------
# A complete, valid concrete subclass used across multiple tests
# ---------------------------------------------------------------------------


class _ValidSource(JobSource):
    """Minimal concrete JobSource for tests."""

    SOURCE = "valid"
    DISPLAY_NAME = "Valid Source"
    DESCRIPTION = "A test source."
    HOME_URL = "https://valid.example.com"
    GEO_SCOPE = "global"
    ACCEPTS_QUERY = "always"
    ACCEPTS_LOCATION = True
    ACCEPTS_COUNTRY = True
    RATE_LIMIT_NOTES = "No known limits."
    REQUIRED_SEARCH_FIELDS = ()

    @classmethod
    def settings_schema(cls) -> dict[str, Any]:
        """Return empty settings schema."""
        return {}

    def pages(self) -> Iterator[list[dict[str, Any]]]:
        """Yield no pages."""
        return iter([])

    def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Return raw unchanged."""
        return raw


# ---------------------------------------------------------------------------
# Happy-path: valid subclass
# ---------------------------------------------------------------------------


class TestValidSubclass:
    """A fully-conforming subclass works without errors."""

    def test_instantiates_successfully(self) -> None:
        """A concrete subclass with all required attrs and methods instantiates."""
        src = _ValidSource()
        assert src is not None

    def test_source_attribute_accessible(self) -> None:
        """SOURCE attribute is accessible on the instance."""
        src = _ValidSource()
        assert src.SOURCE == "valid"

    def test_pages_is_callable(self) -> None:
        """pages() is callable and returns an iterator."""
        src = _ValidSource()
        result = src.pages()
        # Must be iterable; consuming it should produce no pages for _ValidSource
        pages = list(result)
        assert pages == []

    def test_normalise_is_callable(self) -> None:
        """normalise() is callable and returns a dict."""
        src = _ValidSource()
        raw: dict[str, Any] = {"key": "value"}
        assert src.normalise(raw) == raw

    def test_settings_schema_returns_dict(self) -> None:
        """settings_schema() returns a dict."""
        src = _ValidSource()
        schema = src.settings_schema()
        assert isinstance(schema, dict)


# ---------------------------------------------------------------------------
# Attribute enforcement: missing required class-level attrs → TypeError
# ---------------------------------------------------------------------------


class TestMissingRequiredAttributes:
    """Each missing required class-level attribute raises TypeError at class definition."""

    REQUIRED_ATTRS = (
        "SOURCE",
        "DISPLAY_NAME",
        "DESCRIPTION",
        "HOME_URL",
        "GEO_SCOPE",
        "ACCEPTS_QUERY",
        "ACCEPTS_LOCATION",
        "ACCEPTS_COUNTRY",
        "RATE_LIMIT_NOTES",
    )

    def _make_subclass_missing(self, missing_attr: str) -> None:
        """Dynamically create a subclass that omits one required attribute.

        We use type() rather than exec() so the class is constructed in
        a way that triggers __init_subclass__ at class-creation time.
        """
        # Build a namespace with all required attrs except the missing one
        namespace: dict[str, Any] = {
            "SOURCE": "test",
            "DISPLAY_NAME": "Test",
            "DESCRIPTION": "Test source.",
            "HOME_URL": "https://test.example.com",
            "GEO_SCOPE": "global",
            "ACCEPTS_QUERY": "always",
            "ACCEPTS_LOCATION": True,
            "ACCEPTS_COUNTRY": True,
            "RATE_LIMIT_NOTES": "None.",
            "REQUIRED_SEARCH_FIELDS": (),
            "settings_schema": classmethod(lambda cls: {}),
            "pages": lambda self: iter([]),
            "normalise": lambda self, raw: raw,
        }
        del namespace[missing_attr]
        # type() triggers __init_subclass__ — should raise TypeError
        type("_IncompleteSource", (JobSource,), namespace)

    @pytest.mark.parametrize("attr", REQUIRED_ATTRS)
    def test_missing_attribute_raises_type_error(self, attr: str) -> None:
        """Creating a subclass that omits a required attribute raises TypeError."""
        with pytest.raises(TypeError, match=attr):
            self._make_subclass_missing(attr)


# ---------------------------------------------------------------------------
# Abstract method enforcement: missing implementation → TypeError on init
# ---------------------------------------------------------------------------


class TestAbstractMethodEnforcement:
    """Subclasses missing abstract method implementations cannot be instantiated."""

    def test_missing_pages_raises_type_error(self) -> None:
        """A subclass missing pages() cannot be instantiated."""

        class _NoPagesSource(JobSource):
            SOURCE = "no_pages"
            DISPLAY_NAME = "No Pages"
            DESCRIPTION = "Missing pages."
            HOME_URL = "https://no-pages.example.com"
            GEO_SCOPE = "global"
            ACCEPTS_QUERY = "always"
            ACCEPTS_LOCATION = False
            ACCEPTS_COUNTRY = False
            RATE_LIMIT_NOTES = "N/A"
            REQUIRED_SEARCH_FIELDS = ()

            @classmethod
            def settings_schema(cls) -> dict[str, Any]:
                return {}

            def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
                return raw

            # pages() intentionally omitted

        with pytest.raises(TypeError):
            _NoPagesSource()  # type: ignore[abstract]

    def test_missing_normalise_raises_type_error(self) -> None:
        """A subclass missing normalise() cannot be instantiated."""

        class _NoNormaliseSource(JobSource):
            SOURCE = "no_normalise"
            DISPLAY_NAME = "No Normalise"
            DESCRIPTION = "Missing normalise."
            HOME_URL = "https://no-normalise.example.com"
            GEO_SCOPE = "remote-only"
            ACCEPTS_QUERY = "never"
            ACCEPTS_LOCATION = False
            ACCEPTS_COUNTRY = False
            RATE_LIMIT_NOTES = "N/A"
            REQUIRED_SEARCH_FIELDS = ()

            @classmethod
            def settings_schema(cls) -> dict[str, Any]:
                return {}

            def pages(self) -> Iterator[list[dict[str, Any]]]:
                return iter([])

            # normalise() intentionally omitted

        with pytest.raises(TypeError):
            _NoNormaliseSource()  # type: ignore[abstract]

    def test_missing_settings_schema_raises_type_error(self) -> None:
        """A subclass missing settings_schema() cannot be instantiated."""

        class _NoSchemaSource(JobSource):
            SOURCE = "no_schema"
            DISPLAY_NAME = "No Schema"
            DESCRIPTION = "Missing schema."
            HOME_URL = "https://no-schema.example.com"
            GEO_SCOPE = "federal-us"
            ACCEPTS_QUERY = "partial"
            ACCEPTS_LOCATION = False
            ACCEPTS_COUNTRY = False
            RATE_LIMIT_NOTES = "N/A"
            REQUIRED_SEARCH_FIELDS = ()

            def pages(self) -> Iterator[list[dict[str, Any]]]:
                return iter([])

            def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
                return raw

            # settings_schema() intentionally omitted

        with pytest.raises(TypeError):
            _NoSchemaSource()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Intermediate abstract subclasses are not attribute-checked
# ---------------------------------------------------------------------------


class TestAbstractSubclassSkipsAttrEnforcement:
    """Abstract subclasses (still abstract) don't trigger attribute enforcement."""

    def test_abstract_subclass_without_attrs_does_not_raise(self) -> None:
        """An abstract intermediate class that omits metadata doesn't raise TypeError."""
        import abc

        # This class is itself abstract (has un-implemented abstract methods),
        # so __init_subclass__ enforcement should be skipped.
        class _AbstractMiddle(JobSource):
            # Still abstract — does not implement all abstract methods
            @abc.abstractmethod
            def extra_method(self) -> None: ...

        # Class creation should NOT raise TypeError because _AbstractMiddle is
        # still abstract (has abstractmethods). This is correct — we only
        # enforce attr presence on concrete (non-abstract) subclasses.
        # If we get here without an exception, the test passes.
        assert True
