"""Tests for the auto_register entry-point discovery module.

Uses unittest.mock to patch importlib.metadata.entry_points so no real
installed plugins are needed. Tests cover:
- Normal discovery (no conflicts, no disables)
- Collision detection (same SOURCE key from two registrations)
- JOB_SCRAPER_DISABLE_PLUGINS env-var filtering
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from job_api_aggregator.auto_register import discover_plugins
from job_api_aggregator.base import JobSource
from job_api_aggregator.errors import PluginConflictError

# ---------------------------------------------------------------------------
# Helpers: synthetic JobSource subclasses and mock entry-points
# ---------------------------------------------------------------------------


def _make_source_class(source_key: str) -> type[JobSource]:
    """Dynamically create a minimal concrete JobSource with the given SOURCE key."""

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
        REQUIRED_SEARCH_FIELDS = ()

        @classmethod
        def settings_schema(cls) -> dict[str, Any]:
            return {}

        def pages(self) -> Iterator[list[dict[str, Any]]]:
            return iter([])

        def normalise(self, raw: dict[str, Any]) -> dict[str, Any]:
            return raw

    # Give the class a unique name so Python's type system doesn't merge them
    _Src.__name__ = f"_Src_{source_key}"
    _Src.__qualname__ = f"_Src_{source_key}"
    return _Src


def _make_entry_point(name: str, cls: type[JobSource], dist_name: str) -> MagicMock:
    """Return a mock object that satisfies the EntryPoint protocol used in auto_register."""
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = cls
    ep.dist = MagicMock()
    ep.dist.name = dist_name
    return ep


# ---------------------------------------------------------------------------
# Happy-path: multiple distinct plugins
# ---------------------------------------------------------------------------


class TestDiscoverPluginsHappyPath:
    """discover_plugins returns all registered plugins when there are no conflicts."""

    def test_returns_empty_dict_when_no_entry_points(self) -> None:
        """discover_plugins returns {} when no entry-points are registered."""
        with patch(
            "job_api_aggregator.auto_register.entry_points",
            return_value=[],
        ):
            result = discover_plugins()
        assert result == {}

    def test_single_plugin_registered(self) -> None:
        """discover_plugins returns {SOURCE: cls} for one registered plugin."""
        cls_a = _make_source_class("adzuna")
        ep_a = _make_entry_point("adzuna", cls_a, "job-aggregator")

        with patch(
            "job_api_aggregator.auto_register.entry_points",
            return_value=[ep_a],
        ):
            result = discover_plugins()

        assert "adzuna" in result
        assert result["adzuna"] is cls_a

    def test_multiple_distinct_plugins_all_returned(self) -> None:
        """All distinct plugin classes are returned when there are no conflicts."""
        cls_a = _make_source_class("adzuna")
        cls_b = _make_source_class("remoteok")
        eps = [
            _make_entry_point("adzuna", cls_a, "job-aggregator"),
            _make_entry_point("remoteok", cls_b, "job-aggregator"),
        ]

        with patch(
            "job_api_aggregator.auto_register.entry_points",
            return_value=eps,
        ):
            result = discover_plugins()

        assert set(result.keys()) == {"adzuna", "remoteok"}
        assert result["adzuna"] is cls_a
        assert result["remoteok"] is cls_b


# ---------------------------------------------------------------------------
# Collision detection
# ---------------------------------------------------------------------------


class TestDiscoverPluginsCollisionDetection:
    """Raises PluginConflictError when two registrations claim the same SOURCE key."""

    def test_same_source_key_raises_conflict_error(self) -> None:
        """Two entry-points loading classes with the same SOURCE key raises PluginConflictError."""
        cls_builtin = _make_source_class("adzuna")
        cls_thirdparty = _make_source_class("adzuna")
        eps = [
            _make_entry_point("adzuna", cls_builtin, "job-aggregator"),
            _make_entry_point("adzuna-extra", cls_thirdparty, "adzuna-extra-pkg"),
        ]

        with (
            pytest.raises(PluginConflictError) as exc_info,
            patch(
                "job_api_aggregator.auto_register.entry_points",
                return_value=eps,
            ),
        ):
            discover_plugins()

        err = exc_info.value
        assert err.key == "adzuna"

    def test_conflict_error_lists_both_registration_sources(self) -> None:
        """PluginConflictError str/sources includes both dist+name identifiers."""
        cls_a = _make_source_class("adzuna")
        cls_b = _make_source_class("adzuna")
        eps = [
            _make_entry_point("adzuna", cls_a, "job-aggregator"),
            _make_entry_point("adzuna-extra", cls_b, "adzuna-extra-pkg"),
        ]

        with (
            pytest.raises(PluginConflictError) as exc_info,
            patch(
                "job_api_aggregator.auto_register.entry_points",
                return_value=eps,
            ),
        ):
            discover_plugins()

        err = exc_info.value
        msg = str(err)
        # Both registration sources must appear in the error message
        assert "job-aggregator" in msg
        assert "adzuna-extra-pkg" in msg

    def test_conflict_detected_by_source_attribute_not_ep_name(self) -> None:
        """Collision is detected via the class's SOURCE attr, not entry-point name.

        Scenario: entry-point is named 'foo' but loads a class with SOURCE='adzuna',
        which conflicts with a correctly-named 'adzuna' entry-point.
        """
        cls_correct = _make_source_class("adzuna")
        cls_misnamed = _make_source_class("adzuna")  # SOURCE='adzuna' but ep name='foo'
        eps = [
            _make_entry_point("adzuna", cls_correct, "job-aggregator"),
            _make_entry_point("foo", cls_misnamed, "some-other-pkg"),
        ]

        with (
            pytest.raises(PluginConflictError) as exc_info,
            patch(
                "job_api_aggregator.auto_register.entry_points",
                return_value=eps,
            ),
        ):
            discover_plugins()

        assert exc_info.value.key == "adzuna"


# ---------------------------------------------------------------------------
# JOB_SCRAPER_DISABLE_PLUGINS env-var filtering
# ---------------------------------------------------------------------------


class TestDiscoverPluginsDisableFilter:
    """Keys listed in JOB_SCRAPER_DISABLE_PLUGINS are excluded from results."""

    def test_disabled_key_excluded_from_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A key in JOB_SCRAPER_DISABLE_PLUGINS does not appear in the result."""
        monkeypatch.setenv("JOB_SCRAPER_DISABLE_PLUGINS", "adzuna")
        cls_a = _make_source_class("adzuna")
        cls_b = _make_source_class("remoteok")
        eps = [
            _make_entry_point("adzuna", cls_a, "job-aggregator"),
            _make_entry_point("remoteok", cls_b, "job-aggregator"),
        ]

        with patch(
            "job_api_aggregator.auto_register.entry_points",
            return_value=eps,
        ):
            result = discover_plugins()

        assert "adzuna" not in result
        assert "remoteok" in result

    def test_multiple_disabled_keys_all_excluded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Multiple comma-separated keys are all excluded."""
        monkeypatch.setenv("JOB_SCRAPER_DISABLE_PLUGINS", "adzuna,remoteok")
        cls_a = _make_source_class("adzuna")
        cls_b = _make_source_class("remoteok")
        cls_c = _make_source_class("jooble")
        eps = [
            _make_entry_point("adzuna", cls_a, "job-aggregator"),
            _make_entry_point("remoteok", cls_b, "job-aggregator"),
            _make_entry_point("jooble", cls_c, "job-aggregator"),
        ]

        with patch(
            "job_api_aggregator.auto_register.entry_points",
            return_value=eps,
        ):
            result = discover_plugins()

        assert "adzuna" not in result
        assert "remoteok" not in result
        assert "jooble" in result

    def test_disable_filter_applied_after_collision_detection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Collision detection runs on the full set before disable filtering.

        Even if a colliding key would later be disabled, the collision must
        still be raised.  This prevents a scenario where disabling one entry
        silently hides a mis-configured third-party plugin.
        """
        monkeypatch.setenv("JOB_SCRAPER_DISABLE_PLUGINS", "adzuna")
        cls_a = _make_source_class("adzuna")
        cls_b = _make_source_class("adzuna")  # conflict!
        eps = [
            _make_entry_point("adzuna", cls_a, "job-aggregator"),
            _make_entry_point("adzuna-dupe", cls_b, "some-pkg"),
        ]

        with (
            pytest.raises(PluginConflictError),
            patch(
                "job_api_aggregator.auto_register.entry_points",
                return_value=eps,
            ),
        ):
            discover_plugins()

    def test_no_disable_var_returns_all_plugins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When JOB_SCRAPER_DISABLE_PLUGINS is not set, all plugins are returned."""
        monkeypatch.delenv("JOB_SCRAPER_DISABLE_PLUGINS", raising=False)
        cls_a = _make_source_class("adzuna")
        cls_b = _make_source_class("remoteok")
        eps = [
            _make_entry_point("adzuna", cls_a, "job-aggregator"),
            _make_entry_point("remoteok", cls_b, "job-aggregator"),
        ]

        with patch(
            "job_api_aggregator.auto_register.entry_points",
            return_value=eps,
        ):
            result = discover_plugins()

        assert set(result.keys()) == {"adzuna", "remoteok"}

    def test_disable_var_with_spaces_around_commas(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Spaces around comma separators are stripped when parsing the disable list."""
        monkeypatch.setenv("JOB_SCRAPER_DISABLE_PLUGINS", " adzuna , remoteok ")
        cls_a = _make_source_class("adzuna")
        cls_b = _make_source_class("remoteok")
        eps = [
            _make_entry_point("adzuna", cls_a, "job-aggregator"),
            _make_entry_point("remoteok", cls_b, "job-aggregator"),
        ]

        with patch(
            "job_api_aggregator.auto_register.entry_points",
            return_value=eps,
        ):
            result = discover_plugins()

        assert result == {}
