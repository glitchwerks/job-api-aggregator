"""Tests for job_api_aggregator.registry — list_plugins, get_plugin, make_enabled_sources.

Covers:
- list_plugins() returns all 10 registered plugins with complete PluginInfo.
- get_plugin(key) finds a specific plugin; returns None for unknown keys.
- make_enabled_sources() instantiates plugins when credentials are present;
  skips plugins whose required credentials are missing or whose
  REQUIRED_SEARCH_FIELDS are not satisfied.
- Public API importability from job_api_aggregator root.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, ClassVar
from unittest.mock import patch

from job_api_aggregator.base import JobSource
from job_api_aggregator.registry import get_plugin, list_plugins, make_enabled_sources
from job_api_aggregator.schema import PluginField, PluginInfo, SearchParams

# ---------------------------------------------------------------------------
# Helpers — synthetic plugin classes for isolation
# ---------------------------------------------------------------------------

_ALL_EXPECTED_KEYS = frozenset(
    {
        "adzuna",
        "arbeitnow",
        "himalayas",
        "jobicy",
        "jooble",
        "jsearch",
        "remoteok",
        "remotive",
        "the_muse",
        "usajobs",
    }
)


def _make_cred_plugin(source_key: str, cred_field: str = "api_key") -> type[JobSource]:
    """Create a minimal concrete JobSource that requires one credential field."""

    class _Src(JobSource):
        SOURCE = source_key
        DISPLAY_NAME = source_key.title()
        DESCRIPTION = f"Test source {source_key}."
        HOME_URL = f"https://{source_key}.example.com"
        GEO_SCOPE = "global"
        ACCEPTS_QUERY = "always"
        ACCEPTS_LOCATION = True
        ACCEPTS_COUNTRY = True
        RATE_LIMIT_NOTES = "None."
        REQUIRED_SEARCH_FIELDS: ClassVar[tuple[str, ...]] = ()

        def __init__(
            self,
            *,
            credentials: dict[str, Any] | None = None,
            search: SearchParams | None = None,
        ) -> None:
            """Minimal init: store credentials."""
            super().__init__(credentials=credentials, search=search)

        @classmethod
        def settings_schema(cls) -> dict[str, Any]:
            return {
                cred_field: {
                    "label": "API Key",
                    "type": "password",
                    "required": True,
                }
            }

        def pages(self) -> Iterator[list[dict[str, Any]]]:
            return iter([])

        def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
            return raw

    _Src.__name__ = f"_Src_{source_key}"
    _Src.__qualname__ = f"_Src_{source_key}"
    return _Src


def _make_no_cred_plugin(source_key: str) -> type[JobSource]:
    """Create a minimal concrete JobSource that requires no credentials."""

    class _Src(JobSource):
        SOURCE = source_key
        DISPLAY_NAME = source_key.title()
        DESCRIPTION = f"Test source {source_key}."
        HOME_URL = f"https://{source_key}.example.com"
        GEO_SCOPE = "global"
        ACCEPTS_QUERY = "always"
        ACCEPTS_LOCATION = False
        ACCEPTS_COUNTRY = False
        RATE_LIMIT_NOTES = "None."
        REQUIRED_SEARCH_FIELDS: ClassVar[tuple[str, ...]] = ()

        def __init__(
            self,
            *,
            credentials: dict[str, Any] | None = None,
            search: SearchParams | None = None,
        ) -> None:
            """Minimal init."""
            super().__init__(credentials=credentials, search=search)

        @classmethod
        def settings_schema(cls) -> dict[str, Any]:
            return {}

        def pages(self) -> Iterator[list[dict[str, Any]]]:
            return iter([])

        def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
            return raw

    _Src.__name__ = f"_Src_{source_key}"
    _Src.__qualname__ = f"_Src_{source_key}"
    return _Src


# ---------------------------------------------------------------------------
# Importability
# ---------------------------------------------------------------------------


class TestPublicApiImportability:
    """Verify that the public symbols are re-exported from job_api_aggregator root."""

    def test_list_plugins_importable_from_package_root(self) -> None:
        """list_plugins is importable from job_api_aggregator."""
        from job_api_aggregator import list_plugins as lp

        assert callable(lp)

    def test_get_plugin_importable_from_package_root(self) -> None:
        """get_plugin is importable from job_api_aggregator."""
        from job_api_aggregator import get_plugin as gp

        assert callable(gp)

    def test_make_enabled_sources_importable_from_package_root(self) -> None:
        """make_enabled_sources is importable from job_api_aggregator."""
        from job_api_aggregator import make_enabled_sources as mes

        assert callable(mes)


# ---------------------------------------------------------------------------
# list_plugins — real installed plugins
# ---------------------------------------------------------------------------


class TestListPluginsRealPlugins:
    """list_plugins() returns PluginInfo for every installed plugin."""

    def test_returns_list(self) -> None:
        """list_plugins returns a list."""
        result = list_plugins()
        assert isinstance(result, list)

    def test_returns_all_10_plugins(self) -> None:
        """list_plugins returns exactly the 10 shipped plugins."""
        result = list_plugins()
        keys = {p.key for p in result}
        assert keys == _ALL_EXPECTED_KEYS

    def test_each_item_is_plugin_info(self) -> None:
        """Every item in the list is a PluginInfo instance."""
        result = list_plugins()
        for item in result:
            assert isinstance(item, PluginInfo), f"Expected PluginInfo, got {type(item)}"

    def test_no_none_display_name(self) -> None:
        """No plugin has a None or empty display_name."""
        for plugin in list_plugins():
            assert plugin.display_name, f"Plugin {plugin.key!r} has empty display_name"

    def test_no_none_description(self) -> None:
        """No plugin has a None or empty description."""
        for plugin in list_plugins():
            assert plugin.description, f"Plugin {plugin.key!r} has empty description"

    def test_no_none_home_url(self) -> None:
        """No plugin has a None or empty home_url."""
        for plugin in list_plugins():
            assert plugin.home_url, f"Plugin {plugin.key!r} has empty home_url"

    def test_geo_scope_is_valid_literal(self) -> None:
        """All plugins have a valid geo_scope value."""
        valid = {
            "global",
            "global-by-country",
            "remote-only",
            "federal-us",
            "regional",
            "unknown",
        }
        for plugin in list_plugins():
            assert plugin.geo_scope in valid, (
                f"Plugin {plugin.key!r} has invalid geo_scope {plugin.geo_scope!r}"
            )

    def test_accepts_query_is_valid_literal(self) -> None:
        """All plugins have a valid accepts_query value."""
        valid = {"always", "partial", "never"}
        for plugin in list_plugins():
            assert plugin.accepts_query in valid, (
                f"Plugin {plugin.key!r} has invalid accepts_query {plugin.accepts_query!r}"
            )

    def test_fields_is_tuple_of_plugin_field(self) -> None:
        """Every plugin's fields attribute is a tuple of PluginField instances."""
        for plugin in list_plugins():
            assert isinstance(plugin.fields, tuple), (
                f"Plugin {plugin.key!r}: fields should be tuple, got {type(plugin.fields)}"
            )
            for field in plugin.fields:
                assert isinstance(field, PluginField), (
                    f"Plugin {plugin.key!r}: expected PluginField, got {type(field)}"
                )

    def test_required_search_fields_is_tuple(self) -> None:
        """Every plugin's required_search_fields is a tuple (may be empty)."""
        for plugin in list_plugins():
            assert isinstance(plugin.required_search_fields, tuple), (
                f"Plugin {plugin.key!r}: required_search_fields should be tuple"
            )

    def test_requires_credentials_derived_from_fields(self) -> None:
        """requires_credentials is True iff any field is required."""
        for plugin in list_plugins():
            expected = any(f.required for f in plugin.fields)
            assert plugin.requires_credentials == expected, (
                f"Plugin {plugin.key!r}: requires_credentials mismatch"
            )

    def test_adzuna_has_required_credentials(self) -> None:
        """Adzuna requires credentials (has required fields)."""
        plugin = get_plugin("adzuna")
        assert plugin is not None
        assert plugin.requires_credentials is True

    def test_adzuna_fields_include_app_id_and_app_key(self) -> None:
        """Adzuna plugin fields include app_id and app_key."""
        plugin = get_plugin("adzuna")
        assert plugin is not None
        field_names = {f.name for f in plugin.fields}
        assert "app_id" in field_names
        assert "app_key" in field_names

    def test_no_credentials_plugin_has_empty_or_no_required_fields(self) -> None:
        """Remotive (no-cred plugin) has requires_credentials == False."""
        plugin = get_plugin("remotive")
        assert plugin is not None
        assert plugin.requires_credentials is False


# ---------------------------------------------------------------------------
# get_plugin
# ---------------------------------------------------------------------------


class TestGetPlugin:
    """get_plugin(key) returns a matching PluginInfo or None."""

    def test_returns_plugin_info_for_known_key(self) -> None:
        """get_plugin returns PluginInfo for 'adzuna'."""
        result = get_plugin("adzuna")
        assert result is not None
        assert isinstance(result, PluginInfo)
        assert result.key == "adzuna"

    def test_returns_none_for_unknown_key(self) -> None:
        """get_plugin returns None for a key that doesn't exist."""
        result = get_plugin("nonexistent")
        assert result is None

    def test_returns_none_for_empty_string(self) -> None:
        """get_plugin returns None for an empty string key."""
        result = get_plugin("")
        assert result is None

    def test_all_10_keys_are_findable(self) -> None:
        """Every expected plugin key resolves to a non-None PluginInfo."""
        for key in _ALL_EXPECTED_KEYS:
            result = get_plugin(key)
            assert result is not None, f"get_plugin({key!r}) returned None"
            assert result.key == key


# ---------------------------------------------------------------------------
# list_plugins — unit-tested with mocked discover_plugins
# ---------------------------------------------------------------------------


class TestListPluginsUnit:
    """list_plugins() builds correct PluginInfo from class metadata (mocked)."""

    def test_list_plugins_with_cred_plugin_builds_plugin_info(self) -> None:
        """list_plugins builds a PluginInfo with correct fields for a cred plugin."""
        cls_a = _make_cred_plugin("testplugin")
        with patch(
            "job_api_aggregator.registry.discover_plugins",
            return_value={"testplugin": cls_a},
        ):
            result = list_plugins()

        assert len(result) == 1
        info = result[0]
        assert info.key == "testplugin"
        assert info.display_name == "Testplugin"
        assert info.requires_credentials is True
        assert len(info.fields) == 1
        assert info.fields[0].name == "api_key"
        assert info.fields[0].required is True

    def test_list_plugins_with_no_cred_plugin_has_empty_fields(self) -> None:
        """list_plugins builds PluginInfo with empty fields for a no-cred plugin."""
        cls_b = _make_no_cred_plugin("freesource")
        with patch(
            "job_api_aggregator.registry.discover_plugins",
            return_value={"freesource": cls_b},
        ):
            result = list_plugins()

        assert len(result) == 1
        info = result[0]
        assert info.requires_credentials is False
        assert info.fields == ()

    def test_list_plugins_result_sorted_by_key(self) -> None:
        """list_plugins results are sorted alphabetically by key."""
        cls_z = _make_no_cred_plugin("zzz")
        cls_a = _make_no_cred_plugin("aaa")
        with patch(
            "job_api_aggregator.registry.discover_plugins",
            return_value={"zzz": cls_z, "aaa": cls_a},
        ):
            result = list_plugins()

        assert [p.key for p in result] == ["aaa", "zzz"]


# ---------------------------------------------------------------------------
# make_enabled_sources — unit-tested with mocked plugins
# ---------------------------------------------------------------------------


class TestMakeEnabledSources:
    """make_enabled_sources() instantiates plugins ready to run, skips others."""

    def test_instantiates_plugin_when_credentials_present(self) -> None:
        """make_enabled_sources returns a plugin instance when creds are provided."""
        cls_a = _make_cred_plugin("alpha", "api_key")
        with patch(
            "job_api_aggregator.registry.discover_plugins",
            return_value={"alpha": cls_a},
        ):
            result = make_enabled_sources(
                credentials={"alpha": {"api_key": "secret123"}},
                search=SearchParams(),
            )

        assert len(result) == 1
        assert isinstance(result[0], cls_a)

    def test_skips_plugin_when_credentials_missing(self) -> None:
        """make_enabled_sources skips plugins with no entry in credentials dict."""
        cls_a = _make_cred_plugin("alpha", "api_key")
        with patch(
            "job_api_aggregator.registry.discover_plugins",
            return_value={"alpha": cls_a},
        ):
            result = make_enabled_sources(
                credentials={},
                search=SearchParams(),
            )

        assert result == []

    def test_skips_plugin_when_required_credential_field_empty(self) -> None:
        """make_enabled_sources skips a plugin whose required cred field is empty."""
        cls_a = _make_cred_plugin("alpha", "api_key")
        with patch(
            "job_api_aggregator.registry.discover_plugins",
            return_value={"alpha": cls_a},
        ):
            result = make_enabled_sources(
                credentials={"alpha": {"api_key": ""}},
                search=SearchParams(),
            )

        assert result == []

    def test_includes_no_cred_plugin_always(self) -> None:
        """make_enabled_sources includes no-credential plugins unconditionally."""
        cls_b = _make_no_cred_plugin("freesource")
        with patch(
            "job_api_aggregator.registry.discover_plugins",
            return_value={"freesource": cls_b},
        ):
            result = make_enabled_sources(
                credentials={},
                search=SearchParams(),
            )

        assert len(result) == 1
        assert isinstance(result[0], cls_b)

    def test_mixed_plugins_only_ready_ones_returned(self) -> None:
        """make_enabled_sources returns only plugins that are ready to run."""
        cls_cred = _make_cred_plugin("credplugin", "api_key")
        cls_free = _make_no_cred_plugin("freeplugin")
        with patch(
            "job_api_aggregator.registry.discover_plugins",
            return_value={"credplugin": cls_cred, "freeplugin": cls_free},
        ):
            result = make_enabled_sources(
                credentials={},  # no creds for credplugin
                search=SearchParams(),
            )

        assert len(result) == 1
        assert isinstance(result[0], cls_free)

    def test_search_params_passed_to_constructor(self) -> None:
        """make_enabled_sources passes the search params to the plugin constructor."""
        cls_b = _make_no_cred_plugin("freesource")
        search = SearchParams(query="python developer", country="us")
        with patch(
            "job_api_aggregator.registry.discover_plugins",
            return_value={"freesource": cls_b},
        ):
            result = make_enabled_sources(
                credentials={},
                search=search,
            )

        assert len(result) == 1
        assert result[0]._search is search
