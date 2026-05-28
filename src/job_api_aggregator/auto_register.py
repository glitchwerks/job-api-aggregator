"""Entry-point based plugin discovery with collision detection.

This module is intentionally free of side effects on import.  The
:func:`discover_plugins` function must be called explicitly by the
registry (:mod:`job_aggregator.registry`, Issue F) or by tests.

Collision policy (spec §6):
    When two registrations resolve to the same ``SOURCE`` key (detected
    by loading each entry-point's class and reading its ``SOURCE``
    attribute — NOT by entry-point name alone), a
    :exc:`~job_aggregator.errors.PluginConflictError` is raised listing
    both registration sources.  No silent first-wins or last-wins.

Disable mechanism:
    Set ``JOB_SCRAPER_DISABLE_PLUGINS=key1,key2`` to force-disable
    specific plugin keys.  Filtering is applied *after* collision
    detection so mis-configured third-party plugins are never silently
    hidden.
"""

from __future__ import annotations

import os
from importlib.metadata import entry_points

from job_aggregator.base import JobSource
from job_aggregator.errors import PluginConflictError

# ---------------------------------------------------------------------------
# Entry-point group name (must match pyproject.toml)
# ---------------------------------------------------------------------------

_PLUGIN_GROUP = "job_aggregator.plugins"

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover_plugins() -> dict[str, type[JobSource]]:
    """Discover and return all registered :class:`~job_aggregator.base.JobSource` plugins.

    Reads entry-points from the ``job_aggregator.plugins`` group,
    loads each class, and indexes the result by the class's ``SOURCE``
    attribute.

    Collision detection (spec §6):
        If two entry-points load classes that share the same ``SOURCE``
        key a :exc:`~job_aggregator.errors.PluginConflictError` is raised
        listing *both* registration sources in the form
        ``"<dist-name>::<entry-point-name>"``.  This is evaluated
        **before** any disable filtering so that mis-configured packages
        are never silently ignored.

    Disable filtering:
        Keys in the ``JOB_SCRAPER_DISABLE_PLUGINS`` environment variable
        (comma-separated, whitespace around values is stripped) are
        excluded from the returned mapping after collision detection runs.

    Returns:
        A dict mapping plugin ``SOURCE`` key → plugin class for all
        discovered, non-disabled plugins.

    Raises:
        PluginConflictError: When two registrations claim the same
            ``SOURCE`` key.
    """
    eps = entry_points(group=_PLUGIN_GROUP)

    # ----------------------------------------------------------------
    # Phase 1 — load all entry-points and collect (source_key → class)
    # while detecting collisions.
    # ----------------------------------------------------------------

    # Maps SOURCE key → (class, registration_label)
    # Registration label format: "<dist-name>::<ep-name>"
    found: dict[str, tuple[type[JobSource], str]] = {}

    for ep in eps:
        cls: type[JobSource] = ep.load()
        source_key: str = cls.SOURCE

        # Build a human-readable label for this registration
        dist_name: str = ep.dist.name if ep.dist is not None else "unknown-dist"
        label = f"{dist_name}::{ep.name}"

        if source_key in found:
            _existing_cls, existing_label = found[source_key]
            raise PluginConflictError(
                key=source_key,
                sources=[existing_label, label],
            )

        found[source_key] = (cls, label)

    # ----------------------------------------------------------------
    # Phase 2 — apply JOB_SCRAPER_DISABLE_PLUGINS filtering
    # ----------------------------------------------------------------

    disabled_keys = _parse_disable_env()
    return {key: cls for key, (cls, _label) in found.items() if key not in disabled_keys}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_disable_env() -> frozenset[str]:
    """Parse the ``JOB_SCRAPER_DISABLE_PLUGINS`` env var into a set of keys.

    Returns:
        A frozenset of plugin keys to disable.  Returns an empty frozenset
        when the variable is unset or blank.
    """
    raw = os.environ.get("JOB_SCRAPER_DISABLE_PLUGINS", "")
    if not raw.strip():
        return frozenset()
    return frozenset(key.strip() for key in raw.split(",") if key.strip())
