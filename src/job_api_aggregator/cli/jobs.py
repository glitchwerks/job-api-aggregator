"""CLI subcommand: job-aggregator jobs.

Fetches, normalises, deduplicates, and emits job listings from all
configured sources (spec §8.1 / Phase D, Issue #16).

Integration pattern
-------------------
This module follows the same conflict-friendly dispatcher pattern as
``cli/sources.py`` (Issue F / #18):

- :func:`register` — adds the ``jobs`` subparser to an existing
  :class:`argparse.ArgumentParser` subparsers group.
- :func:`run` — executes the command given a parsed
  :class:`argparse.Namespace`.

The dispatcher wires this in with two lines::

    from job_aggregator.cli import jobs as _jobs_cmd
    _jobs_cmd.register(subparsers)

Credentials are optional (#50)
-------------------------------
``--credentials`` is no longer required.  When omitted, the command
inspects the selected sources and proceeds with an empty credentials
dict if none of them require credentials.  If any selected source
*does* require credentials and ``--credentials`` was not supplied, the
command exits non-zero with a message naming the offending sources.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from job_aggregator.registry import list_plugins
from job_aggregator.schema import PluginInfo

# ---------------------------------------------------------------------------
# Public subcommand API
# ---------------------------------------------------------------------------


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the ``jobs`` subcommand to an argparse subparsers group.

    Registers all §8.1 flags and sets ``func=run`` as the dispatch target.

    Args:
        subparsers: The ``_SubParsersAction`` returned by
            ``parser.add_subparsers()``.
    """
    p = subparsers.add_parser(
        "jobs",
        help="Fetch and normalise job listings from configured sources.",
        description=(
            "Fetch job listings from all configured sources, normalise "
            "them to the package schema, deduplicate, and emit to stdout "
            "as JSONL (default) or JSON."
        ),
    )

    # --- Fetch parameters ---
    p.add_argument(
        "--hours",
        type=int,
        default=168,
        metavar="N",
        help="Lookback window in hours (default: 168 = one week).",
    )
    p.add_argument(
        "--query",
        type=str,
        default=None,
        metavar="STRING",
        help=(
            "Free-text search query. Applied per accepts_query per source. "
            "Sources with accepts_query=never or partial will emit a warning."
        ),
    )
    p.add_argument(
        "--location",
        type=str,
        default=None,
        metavar="STRING",
        help="Free-text location hint (no client-side geo filtering).",
    )
    p.add_argument(
        "--country",
        type=str,
        default=None,
        metavar="CODE",
        help="ISO 3166-1 alpha-2 country code (e.g. 'us', 'gb').",
    )

    # --- Source selection ---
    p.add_argument(
        "--sources",
        type=str,
        default=None,
        metavar="LIST",
        help="Comma-separated list of plugin keys to enable. Defaults to all configured sources.",
    )
    p.add_argument(
        "--exclude-sources",
        type=str,
        default=None,
        dest="exclude_sources",
        metavar="LIST",
        help="Comma-separated list of plugin keys to skip.",
    )

    # --- Pagination / limits ---
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Maximum number of records to emit (0 = unlimited).",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=None,
        dest="max_pages",
        metavar="N",
        help="Per-source page cap (default: each plugin's own default).",
    )

    # --- Credentials / output ---
    p.add_argument(
        "--credentials",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Path to a JSON credentials file (see docs/credentials_format.md). "
            "Optional when all selected sources are no-auth; required when any "
            "selected source needs credentials."
        ),
    )
    p.add_argument(
        "--format",
        type=str,
        default="jsonl",
        choices=["jsonl", "json"],
        metavar="FORMAT",
        help="Output format: 'jsonl' (default) or 'json'.",
    )
    p.add_argument(
        "--output",
        type=str,
        default=None,
        metavar="PATH",
        help="Write output to PATH instead of stdout.",
    )

    # --- Behaviour flags ---
    p.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Exit non-zero on any source error (default: continue).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help="List which sources would run with which params; no HTTP calls.",
    )

    # --- Verbosity ---
    verbosity = p.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v",
        action="count",
        default=0,
        dest="verbosity",
        help="Increase stderr verbosity (-v = verbose, -vv = debug).",
    )
    verbosity.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress all stderr output except errors.",
    )

    p.set_defaults(func=run)


def _resolve_selected_sources(
    sources: list[str] | None,
    exclude_sources: list[str] | None,
) -> list[PluginInfo]:
    """Return the effective list of selected :class:`PluginInfo` objects.

    Uses the registry to enumerate all registered plugins and applies the
    same ``--sources`` / ``--exclude-sources`` filter logic as the
    orchestrator, so the CLI can inspect ``requires_credentials`` before
    deciding whether a credentials file is mandatory.

    Args:
        sources: Allowlist of plugin keys from ``--sources``, or ``None``
            to select all registered plugins.
        exclude_sources: Blocklist of plugin keys from
            ``--exclude-sources``, or ``None`` for no exclusions.

    Returns:
        A list of :class:`PluginInfo` for the selected plugins (may be
        empty when no plugins are registered or none match the filters).
    """
    all_plugins = list_plugins()

    # Apply --sources allowlist
    selected = [p for p in all_plugins if p.key in sources] if sources else list(all_plugins)

    # Apply --exclude-sources blocklist
    if exclude_sources:
        selected = [p for p in selected if p.key not in exclude_sources]

    return selected


def run(ns: argparse.Namespace) -> None:
    """Execute the ``jobs`` subcommand.

    Resolves credentials (loading from file when ``--credentials`` is
    supplied, or using an empty dict when all selected sources are
    no-auth), then delegates to
    :func:`~job_aggregator.orchestrator.run_jobs` and writes the result
    to stdout (or the file named by ``--output``).

    When ``--credentials`` is omitted but one or more selected sources
    require credentials, the command exits with code 2 and a message
    naming the offending sources.

    Args:
        ns: Parsed :class:`argparse.Namespace` from the ``jobs`` subparser.
    """
    from job_aggregator.orchestrator import run_jobs

    # Parse comma-separated source lists (needed for creds check too)
    sources: list[str] | None = None
    if getattr(ns, "sources", None):
        sources = [s.strip() for s in ns.sources.split(",") if s.strip()]

    exclude_sources: list[str] | None = None
    if getattr(ns, "exclude_sources", None):
        exclude_sources = [s.strip() for s in ns.exclude_sources.split(",") if s.strip()]

    # ------------------------------------------------------------------
    # Credentials: load from file, or validate that none are needed
    # ------------------------------------------------------------------
    credentials: dict[str, Any] = {}

    if ns.credentials is not None:
        # --credentials supplied — load and validate as before
        try:
            with open(ns.credentials, encoding="utf-8") as fh:
                creds_doc = json.load(fh)
            # Credentials file format:
            #   {"schema_version": "1.0", "plugins": {...}}
            if isinstance(creds_doc, dict):
                credentials = creds_doc.get("plugins", {})
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"ERROR: Cannot load credentials from {ns.credentials!r}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        # --credentials omitted — check whether any selected source needs
        # credentials; if so, exit with a helpful error message.
        selected = _resolve_selected_sources(sources, exclude_sources)
        needs_creds = [p.key for p in selected if p.requires_credentials]
        if needs_creds:
            keys_str = ", ".join(sorted(needs_creds))
            print(
                f"error: --credentials is required because the following "
                f"selected sources need credentials: {keys_str}. "
                f"Omit these sources (via --exclude-sources) or supply a "
                f"credentials file.",
                file=sys.stderr,
            )
            sys.exit(2)
        # No selected source needs credentials — proceed with empty dict

    result = run_jobs(
        credentials=credentials,
        format=ns.format,
        query=ns.query,
        location=ns.location,
        country=ns.country,
        hours=ns.hours,
        max_pages=ns.max_pages,
        sources=sources,
        exclude_sources=exclude_sources,
        limit=ns.limit,
        strict=ns.strict,
        dry_run=ns.dry_run,
    )

    # Write output
    if ns.output:
        try:
            with open(ns.output, "w", encoding="utf-8") as fh:
                fh.write(result)
        except OSError as exc:
            print(
                f"ERROR: Cannot write output to {ns.output!r}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print(result, end="")
