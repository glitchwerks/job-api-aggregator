"""CLI subcommand: job-aggregator sources.

Emits a JSON document describing every registered plugin per spec §8.3.
When ``--credentials PATH`` is provided, each plugin entry also carries a
``credentials_configured: bool`` field indicating whether all required
credential fields are present and non-empty in the supplied file.

Integration pattern
-------------------
This module exposes two functions designed for conflict-friendly dispatcher
integration (spec §F shared-file coordination):

- :func:`register` — adds the ``sources`` subparser to an existing
  :class:`argparse.ArgumentParser` subparsers group.
- :func:`run` — executes the command given a parsed :class:`argparse.Namespace`.

The dispatcher only needs two lines to wire this in::

    from job_aggregator.cli import sources as _sources_cmd
    _sources_cmd.register(subparsers)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from job_aggregator.registry import list_plugins
from job_aggregator.schema import PluginInfo

# ---------------------------------------------------------------------------
# JSON serialisation helpers
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = "1.0"


def _plugin_info_to_dict(
    info: PluginInfo,
    credentials: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialise a :class:`PluginInfo` to a JSON-compatible dict.

    Follows the §8.3 field order: key, display_name, description,
    home_url, geo_scope, accepts_query, accepts_location, accepts_country,
    rate_limit_notes, fields.  When *credentials* is provided, a
    ``credentials_configured`` boolean is appended.

    Args:
        info: The :class:`PluginInfo` to serialise.
        credentials: The full credentials mapping
            (``{plugin_key: {field_name: value}}``).  When ``None``,
            the ``credentials_configured`` field is omitted.

    Returns:
        A JSON-serialisable dict representing the plugin entry.
    """
    fields_list = [
        {
            "name": f.name,
            "label": f.label,
            "type": f.type,
            "required": f.required,
            **({"help_text": f.help_text} if f.help_text is not None else {}),
        }
        for f in info.fields
    ]

    entry: dict[str, Any] = {
        "key": info.key,
        "display_name": info.display_name,
        "description": info.description,
        "home_url": info.home_url,
        "geo_scope": info.geo_scope,
        "accepts_query": info.accepts_query,
        "accepts_location": info.accepts_location,
        "accepts_country": info.accepts_country,
        "rate_limit_notes": info.rate_limit_notes,
        "fields": fields_list,
    }

    if credentials is not None:
        plugin_creds: dict[str, Any] = credentials.get(info.key, {})
        entry["credentials_configured"] = _credentials_configured(info, plugin_creds)

    return entry


def _credentials_configured(
    info: PluginInfo,
    plugin_creds: dict[str, Any],
) -> bool:
    """Return True when the plugin's required credential fields are all present.

    A plugin with no required fields is always considered configured.

    Args:
        info: The :class:`PluginInfo` describing the plugin's required fields.
        plugin_creds: The credentials dict for this specific plugin
            (i.e. ``credentials[info.key]``).

    Returns:
        ``True`` if every field where ``required=True`` has a truthy
        value in *plugin_creds*; ``False`` otherwise.
    """
    required_names = [f.name for f in info.fields if f.required]
    if not required_names:
        return True
    return all(bool(plugin_creds.get(name)) for name in required_names)


# ---------------------------------------------------------------------------
# Credentials loading
# ---------------------------------------------------------------------------


def _load_credentials(path: str) -> dict[str, Any]:
    """Load and parse a JSON credentials file.

    Args:
        path: File system path to a JSON credentials file.  The file
            must contain a JSON object (dict at the top level).

    Returns:
        The parsed credentials dict.

    Raises:
        SystemExit: With exit code 1 if the file cannot be read or is not
            valid JSON.  An error message is written to stderr.
    """
    creds_path = Path(path)
    try:
        raw = creds_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"job-aggregator sources: cannot read credentials file {path!r}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(
            f"job-aggregator sources: credentials file {path!r} is not valid JSON: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not isinstance(data, dict):
        print(
            f"job-aggregator sources: credentials file {path!r} must contain a JSON object.",
            file=sys.stderr,
        )
        sys.exit(1)

    return data


# ---------------------------------------------------------------------------
# Public subcommand API
# ---------------------------------------------------------------------------


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``sources`` subcommand to an argparse subparsers group.

    Call this from the top-level dispatcher (``cli/__main__.py``) so that
    the ``sources`` subcommand is wired in with a single import::

        from job_aggregator.cli import sources as _sources
        _sources.register(subparsers)

    Args:
        subparsers: The ``_SubParsersAction`` returned by
            ``parser.add_subparsers()``.
    """
    parser = subparsers.add_parser(
        "sources",
        help="List all registered job-source plugins as JSON.",
        description=(
            "Emit a JSON document describing every registered plugin. "
            "Pass --credentials to check which plugins are fully configured."
        ),
    )
    parser.add_argument(
        "--credentials",
        metavar="PATH",
        default=None,
        help=(
            "Path to a JSON credentials file "
            "({plugin_key: {field_name: value}}).  "
            "When provided, each plugin entry includes "
            "credentials_configured: bool."
        ),
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Execute the sources subcommand.

    Enumerates all registered plugins via :func:`~job_aggregator.registry.list_plugins`,
    serialises them to the §8.3 JSON shape, and writes the result to
    stdout.

    Args:
        args: The parsed :class:`argparse.Namespace`.  Recognised
            attributes:

            - ``credentials`` (:class:`str` | ``None``) — path to a
              JSON credentials file; ``None`` omits
              ``credentials_configured`` from the output.
    """
    credentials: dict[str, Any] | None = None
    if args.credentials is not None:
        credentials = _load_credentials(args.credentials)

    plugins = list_plugins()
    plugin_entries = [_plugin_info_to_dict(info, credentials) for info in plugins]

    document: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "plugins": plugin_entries,
    }

    print(json.dumps(document, indent=2))
