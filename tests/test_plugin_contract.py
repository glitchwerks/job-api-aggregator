"""ABC-level plugin contract tests.

Verifies that every registered plugin class:

- Can be instantiated via ``cls(credentials=<stub>, search=None)``
  using the canonical keyword-only constructor signature.
- Exposes ``settings_schema()`` as a ``@classmethod`` that returns a
  dict without requiring an instance.
- Does not raise on ``cls.settings_schema()`` (class-level call).

For credential-requiring plugins, a minimal stub dict is built by
inspecting ``cls.settings_schema()`` to discover required field names and
supplying a non-empty placeholder value for each one.

These tests do **not** make HTTP requests; they only exercise the
constructor and schema machinery.
"""

from __future__ import annotations

from typing import Any

import pytest

from job_api_aggregator.auto_register import discover_plugins
from job_api_aggregator.base import JobSource
from job_api_aggregator.schema import SearchParams

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_credentials(cls: type[JobSource]) -> dict[str, Any]:
    """Build a minimal stub credentials dict for *cls*.

    Reads ``cls.settings_schema()`` (classmethod, no instance needed) and
    returns a dict with every required field set to a non-empty placeholder
    string so that the plugin's credential-validation logic passes.

    Args:
        cls: A concrete :class:`~job_api_aggregator.base.JobSource` subclass.

    Returns:
        Dict mapping each required field name to a placeholder string.
        Returns an empty dict for no-auth plugins.
    """
    schema: dict[str, Any] = cls.settings_schema()
    return {
        name: f"stub_{name}"
        for name, field_def in schema.items()
        if field_def.get("required", False)
    }


def _all_plugin_classes() -> list[type[JobSource]]:
    """Return every registered concrete plugin class.

    Returns:
        List of plugin classes sorted alphabetically by ``SOURCE``.
    """
    plugins = discover_plugins()
    return [plugins[key] for key in sorted(plugins)]


# ---------------------------------------------------------------------------
# Parametrised fixture
# ---------------------------------------------------------------------------

_PLUGIN_CLASSES = _all_plugin_classes()
_PLUGIN_IDS = [cls.SOURCE for cls in _PLUGIN_CLASSES]


# ---------------------------------------------------------------------------
# Test: settings_schema is a classmethod
# ---------------------------------------------------------------------------


class TestSettingsSchemaIsClassmethod:
    """``settings_schema()`` must be callable on the class without an instance."""

    @pytest.mark.parametrize("cls", _PLUGIN_CLASSES, ids=_PLUGIN_IDS)
    def test_settings_schema_callable_on_class(self, cls: type[JobSource]) -> None:
        """``cls.settings_schema()`` succeeds without constructing an instance.

        Args:
            cls: Parametrised plugin class under test.
        """
        schema = cls.settings_schema()
        assert isinstance(schema, dict), (
            f"{cls.__name__}.settings_schema() must return dict, got {type(schema)}"
        )

    @pytest.mark.parametrize("cls", _PLUGIN_CLASSES, ids=_PLUGIN_IDS)
    def test_settings_schema_is_classmethod_descriptor(self, cls: type[JobSource]) -> None:
        """``settings_schema`` must be bound as a classmethod on the class.

        Args:
            cls: Parametrised plugin class under test.
        """
        import inspect

        method = inspect.getattr_static(cls, "settings_schema")
        assert isinstance(method, classmethod), (
            f"{cls.__name__}.settings_schema must be a @classmethod, got {type(method)}"
        )


# ---------------------------------------------------------------------------
# Test: constructor accepts canonical keyword-only signature
# ---------------------------------------------------------------------------


class TestCanonicalConstructorSignature:
    """Every plugin can be instantiated with ``cls(credentials=..., search=None)``."""

    @pytest.mark.parametrize("cls", _PLUGIN_CLASSES, ids=_PLUGIN_IDS)
    def test_instantiates_with_stub_credentials(self, cls: type[JobSource]) -> None:
        """``cls(credentials=stub, search=None)`` produces a valid instance.

        Credential-requiring plugins receive a stub dict; no-auth plugins
        receive an empty dict.  Neither case should raise.

        Args:
            cls: Parametrised plugin class under test.
        """
        creds = _stub_credentials(cls)
        instance = cls(credentials=creds, search=None)
        assert isinstance(instance, JobSource), (
            f"{cls.__name__}(credentials=..., search=None) did not return a JobSource instance"
        )

    @pytest.mark.parametrize("cls", _PLUGIN_CLASSES, ids=_PLUGIN_IDS)
    def test_instantiates_with_search_params(self, cls: type[JobSource]) -> None:
        """``cls(credentials=stub, search=SearchParams())`` produces a valid instance.

        Verifies that passing a :class:`~job_api_aggregator.schema.SearchParams`
        object does not cause a crash at construction time.

        Args:
            cls: Parametrised plugin class under test.
        """
        creds = _stub_credentials(cls)
        search = SearchParams(query="python developer", country="us")
        instance = cls(credentials=creds, search=search)
        assert isinstance(instance, JobSource), (
            f"{cls.__name__}(credentials=..., search=SearchParams()) did not "
            f"return a JobSource instance"
        )

    @pytest.mark.parametrize("cls", _PLUGIN_CLASSES, ids=_PLUGIN_IDS)
    def test_no_auth_plugin_accepts_none_credentials(self, cls: type[JobSource]) -> None:
        """Plugins with no required credentials accept ``credentials=None``.

        Credential-requiring plugins are skipped (they would raise
        ``CredentialsError`` with ``None`` credentials).

        Args:
            cls: Parametrised plugin class under test.
        """
        schema = cls.settings_schema()
        has_required = any(v.get("required", False) for v in schema.values())
        if has_required:
            pytest.skip(f"{cls.SOURCE} requires credentials — skipping None test")

        instance = cls(credentials=None, search=None)
        assert isinstance(instance, JobSource)
