"""Plugin registry — introspection API for registered job-aggregator plugins.

Provides three public functions that form the core of the Phase F
introspection surface:

- :func:`list_plugins` — enumerate all registered plugins as
  :class:`~job_aggregator.schema.PluginInfo` objects.
- :func:`get_plugin` — look up a single plugin by its ``SOURCE`` key.
- :func:`make_enabled_sources` — instantiate plugins whose required
  credentials are present in the provided credentials dict.

All three functions call :func:`~job_aggregator.auto_register.discover_plugins`
on each invocation; no module-level singleton is kept so that tests can
cleanly patch ``discover_plugins`` without import-order side effects.
"""

from __future__ import annotations

import logging
from typing import Any

from job_aggregator.auto_register import discover_plugins
from job_aggregator.base import JobSource
from job_aggregator.errors import CredentialsError
from job_aggregator.schema import PluginField, PluginInfo, SearchParams

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_plugin_info(cls: type[JobSource]) -> PluginInfo:
    """Build a :class:`PluginInfo` from a :class:`JobSource` subclass.

    Reads the class-level metadata attributes and calls
    :meth:`~job_aggregator.base.JobSource.settings_schema` on a transient
    instance to obtain the field definitions.

    Args:
        cls: A concrete :class:`~job_aggregator.base.JobSource` subclass.

    Returns:
        A fully populated :class:`PluginInfo` dataclass.
    """
    # settings_schema() is a classmethod — call it directly on the class
    # without constructing an instance, avoiding credential validation.
    try:
        schema: dict[str, Any] = cls.settings_schema()
    except Exception:
        # Fallback to an empty schema if the classmethod raises unexpectedly.
        logger.debug(
            "Could not call settings_schema() on %s; using empty schema.",
            cls.__name__,
        )
        schema = {}

    fields: tuple[PluginField, ...] = tuple(
        PluginField(
            name=field_name,
            label=field_def.get("label", field_name),
            type=field_def.get("type", "text"),
            required=bool(field_def.get("required", False)),
            help_text=field_def.get("help_text") or None,
        )
        for field_name, field_def in schema.items()
    )

    return PluginInfo(
        key=cls.SOURCE,
        display_name=cls.DISPLAY_NAME,
        description=cls.DESCRIPTION,
        home_url=cls.HOME_URL,
        geo_scope=cls.GEO_SCOPE,
        accepts_query=cls.ACCEPTS_QUERY,
        accepts_location=cls.ACCEPTS_LOCATION,
        accepts_country=cls.ACCEPTS_COUNTRY,
        rate_limit_notes=cls.RATE_LIMIT_NOTES,
        required_search_fields=cls.REQUIRED_SEARCH_FIELDS,
        fields=fields,
    )


def _credentials_satisfied(
    info: PluginInfo,
    plugin_creds: dict[str, Any],
) -> bool:
    """Return True if all required credential fields are present and non-empty.

    A plugin with no required fields is always considered satisfied.

    Args:
        info: The :class:`PluginInfo` describing the plugin's fields.
        plugin_creds: The credentials dict for this specific plugin
            (i.e. ``credentials[plugin_key]``).

    Returns:
        ``True`` if every field where ``required=True`` has a non-empty
        value in *plugin_creds*; ``False`` otherwise.
    """
    required_names = [f.name for f in info.fields if f.required]
    if not required_names:
        return True
    return all(bool(plugin_creds.get(name)) for name in required_names)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_plugins() -> list[PluginInfo]:
    """Return a :class:`PluginInfo` for every registered plugin, sorted by key.

    Discovers plugins via entry-points (see
    :func:`~job_aggregator.auto_register.discover_plugins`) and builds a
    :class:`PluginInfo` for each one.  Results are sorted alphabetically
    by :attr:`PluginInfo.key` for stable output.

    Returns:
        A list of :class:`PluginInfo` objects, one per registered plugin,
        sorted by ``key``.

    Raises:
        PluginConflictError: Propagated from
            :func:`~job_aggregator.auto_register.discover_plugins` when
            two registrations claim the same ``SOURCE`` key.
    """
    plugins = discover_plugins()
    return sorted(
        (_build_plugin_info(cls) for cls in plugins.values()),
        key=lambda info: info.key,
    )


def get_plugin(key: str) -> PluginInfo | None:
    """Look up a registered plugin by its ``SOURCE`` key.

    Args:
        key: The plugin's unique machine-readable identifier
            (e.g. ``"adzuna"``).

    Returns:
        The :class:`PluginInfo` for the matching plugin, or ``None`` if
        no plugin with that key is registered.

    Raises:
        PluginConflictError: Propagated from
            :func:`~job_aggregator.auto_register.discover_plugins` when
            two registrations claim the same ``SOURCE`` key.
    """
    plugins = discover_plugins()
    cls = plugins.get(key)
    if cls is None:
        return None
    return _build_plugin_info(cls)


def make_enabled_sources(
    credentials: dict[str, Any],
    search: SearchParams,
) -> list[JobSource]:
    """Instantiate plugins whose required credentials are present and non-empty.

    Discovers all registered plugins, checks whether the required
    credential fields for each plugin are satisfied by the provided
    *credentials* dict, and attempts to instantiate each ready plugin.

    The calling convention used for instantiation is
    ``cls(credentials=plugin_creds, search=search)``.  Plugin classes
    that were written before this registry API existed (and therefore
    have different constructor signatures) should be wrapped or updated
    to accept this convention.  If instantiation raises
    :exc:`~job_aggregator.errors.CredentialsError` the plugin is silently
    dropped; a :exc:`TypeError` from a mismatched constructor is logged
    and the plugin is also dropped.

    Args:
        credentials: A mapping of plugin key →
            ``{field_name: value}`` dicts.  Plugins whose key is absent
            are treated as having no credentials supplied.
        search: The search parameters to pass to each plugin constructor.

    Returns:
        A list of instantiated :class:`~job_aggregator.base.JobSource`
        objects that are ready to run, in alphabetical order by plugin
        key.

    Raises:
        PluginConflictError: Propagated from
            :func:`~job_aggregator.auto_register.discover_plugins` when
            two registrations claim the same ``SOURCE`` key.
    """
    plugins = discover_plugins()
    result: list[JobSource] = []

    for key in sorted(plugins):
        cls = plugins[key]
        info = _build_plugin_info(cls)
        plugin_creds: dict[str, Any] = credentials.get(key, {})

        if not _credentials_satisfied(info, plugin_creds):
            logger.debug(
                "Skipping plugin %r: required credentials not satisfied.",
                key,
            )
            continue

        try:
            instance = cls(credentials=plugin_creds, search=search)
            result.append(instance)
        except CredentialsError as exc:
            logger.debug("Skipping plugin %r: CredentialsError — %s", key, exc)
        except TypeError as exc:
            logger.debug(
                "Skipping plugin %r: constructor signature mismatch — %s",
                key,
                exc,
            )

    return result
