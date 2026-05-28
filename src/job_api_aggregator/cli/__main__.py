"""Entry point for the ``job-aggregator`` console script.

Wires up argparse sub-commands.  Sub-commands are implemented as
self-contained modules under ``job_aggregator/cli/`` and registered
here with a single ``register(subparsers)`` call per module — making
parallel-PR integration a 2-line diff per new command.

Current sub-commands:
    ``jobs``    — fetch, normalise, dedup, and emit job listings (Issue #16 / Phase D).
    ``sources`` — list registered plugins as JSON (Issue F / #18).
    ``hydrate`` — scrape full descriptions (Issue #17 / Phase E).

Public API (consumed by tests):
    :func:`main` — console-script entry point.
    :func:`_build_parser` — returns the configured :class:`argparse.ArgumentParser`.
    :func:`cmd_jobs` — alias for :func:`job_aggregator.cli.jobs.run`
        (preserved for backward-compatibility with existing tests).
"""

from __future__ import annotations

import argparse
import sys

from job_aggregator import __version__
from job_aggregator.cli import hydrate as _hydrate_cmd
from job_aggregator.cli import jobs as _jobs_cmd
from job_aggregator.cli import sources as _sources_cmd

# ---------------------------------------------------------------------------
# Backward-compatible alias — tests import cmd_jobs from this module.
# ---------------------------------------------------------------------------

cmd_jobs = _jobs_cmd.run


# ---------------------------------------------------------------------------
# Parser builder
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser.

    Registers ``jobs``, ``sources``, and ``hydrate`` sub-commands.
    Adding a new sub-command in a parallel PR is a 2-line change:
    one import + one ``<module>.register(subparsers)`` call here.

    Returns:
        A configured :class:`argparse.ArgumentParser` with all registered
        sub-commands attached.
    """
    parser = argparse.ArgumentParser(
        prog="job-aggregator",
        description=(
            "Fetch and normalise job listings from multiple sources. "
            "See subcommand --help for details."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="COMMAND",
    )

    # Register each sub-command module here — one line per module.
    _jobs_cmd.register(subparsers)
    _sources_cmd.register(subparsers)
    _hydrate_cmd.register(subparsers)

    return parser


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments and dispatch to the appropriate sub-command handler.

    This is the console-script entry point declared in ``pyproject.toml``::

        [project.scripts]
        job-aggregator = "job_aggregator.cli.__main__:main"

    Sub-commands set ``args.func`` via
    :meth:`argparse.ArgumentParser.set_defaults`.  If no sub-command is
    given, help is printed and the process exits 0.

    Returns:
        None.
    """
    parser = _build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func") or args.func is None:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
