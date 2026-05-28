"""CLI subcommand: job-aggregator hydrate.

Reads job records from stdin or a file, scrapes full descriptions for each
record, and emits enriched records (spec §8.2 / Phase E, Issue #17).

Input handling follows the §8.2.1 table exactly:
- Records with ``description_source = "full"`` are passed through unchanged.
- Records with absent, null, empty, or non-HTTP/HTTPS ``url`` are passed
  through unchanged with a stderr warning.
- Records with an unrecognised ``description_source`` value are passed through
  unchanged with a stderr warning (future-compat / defensive).
- A ``schema_version`` major mismatch in the input envelope causes exit code 4.

Format inference (when ``--format`` is not set explicitly): peek the first
non-whitespace byte of input.  If it is ``{`` **and** the first complete JSON
value parses as a single object containing a ``"jobs"`` key, treat as
``--format json``.  Otherwise treat as ``--format jsonl``.

Integration pattern
-------------------
This module follows the same conflict-friendly dispatcher pattern as
``cli/sources.py`` and ``cli/jobs.py``:

- :func:`register` — adds the ``hydrate`` subparser to an existing
  :class:`argparse.ArgumentParser` subparsers group.
- :func:`run` — executes the command given a parsed
  :class:`argparse.Namespace`.

The dispatcher wires this in with two lines::

    from job_aggregator.cli import hydrate as _hydrate_cmd
    _hydrate_cmd.register(subparsers)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from job_aggregator.errors import SchemaVersionError
from job_aggregator.hydrator import HydrateConfig, hydrate

# ---------------------------------------------------------------------------
# Public subcommand API
# ---------------------------------------------------------------------------


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the ``hydrate`` subcommand to an argparse subparsers group.

    Registers all §8.2 flags and sets ``func=run`` as the dispatch target.

    Args:
        subparsers: The ``_SubParsersAction`` returned by
            ``parser.add_subparsers()``.
    """
    p = subparsers.add_parser(
        "hydrate",
        help="Scrape full job descriptions for records produced by `jobs`.",
        description=(
            "Read job records from stdin or --input, fetch the full job "
            "description for each record, and emit enriched records.\n\n"
            "Input handling (§8.2.1):\n"
            "  description_source='full'   — passed through unchanged\n"
            "  url absent/null/empty       — passed through, warning emitted\n"
            "  url not http/https          — passed through, warning emitted\n"
            "  unknown description_source  — passed through, warning emitted\n"
            "  schema_version major mismatch — exit code 4\n\n"
            "Format inference (when --format not set): "
            "if the first non-whitespace byte is '{' and the input parses as "
            "a JSON object containing 'jobs', treat as --format json; "
            "otherwise treat as --format jsonl."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # --- Input / output ---
    p.add_argument(
        "--input",
        metavar="PATH",
        default=None,
        help=("JSONL or JSON file produced by `jobs`.  Use '-' or omit to read from stdin."),
    )
    p.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Output file path.  Defaults to stdout.",
    )

    # --- Timeout ---
    p.add_argument(
        "--timeout-per-request",
        type=int,
        default=15,
        metavar="N",
        help="Per-URL HTTP timeout in seconds (default: 15).",
    )
    p.add_argument(
        "--timeout-total",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Hard wall-clock budget for the whole run in seconds.  "
            "When exceeded, remaining records are passed through unchanged "
            "and a warning is logged.  Default: no limit."
        ),
    )

    # --- Error handling ---
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        default=True,
        help=(
            "When a scrape fails, pass the record through unchanged and "
            "log to stderr.  This is the default behaviour."
        ),
    )
    p.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Exit non-zero on the first scrape failure.",
    )

    # --- Format ---
    p.add_argument(
        "--format",
        dest="fmt",
        choices=["json", "jsonl"],
        default=None,
        metavar="FORMAT",
        help=(
            "Output format: 'json' (single envelope object) or 'jsonl' "
            "(envelope first line, one record per subsequent line).  "
            "Inferred from input when not set."
        ),
    )

    # --- Verbosity ---
    verbosity = p.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v",
        dest="verbosity",
        action="store_const",
        const=1,
        default=0,
        help="Verbose output.",
    )
    verbosity.add_argument(
        "-vv",
        dest="verbosity",
        action="store_const",
        const=2,
        help="Very verbose output.",
    )
    verbosity.add_argument(
        "--quiet",
        dest="verbosity",
        action="store_const",
        const=-1,
        help="Suppress all non-error output.",
    )

    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    """Execute the hydrate subcommand.

    Opens the input stream, constructs a :class:`~job_aggregator.hydrator.HydrateConfig`
    from *args*, delegates to :func:`~job_aggregator.hydrator.hydrate`, and
    writes the output.

    Exit codes:
        0 — success (or failure tolerated by ``--continue-on-error``).
        1 — unrecoverable I/O or parse error.
        2 — scrape failure when ``--strict`` is set.
        4 — cross-major ``schema_version`` mismatch in the input envelope.

    Args:
        args: The parsed :class:`argparse.Namespace`.  Recognised attributes:

            - ``input`` (:class:`str` | ``None``) — path to input file;
              ``None`` or ``"-"`` reads from stdin.
            - ``output`` (:class:`str` | ``None``) — path to output file;
              ``None`` writes to stdout.
            - ``timeout_per_request`` (:class:`int`) — per-URL HTTP timeout.
            - ``timeout_total`` (:class:`int` | ``None``) — total budget.
            - ``strict`` (:class:`bool`) — exit non-zero on any failure.
            - ``continue_on_error`` (:class:`bool`) — tolerate failures.
            - ``fmt`` (:class:`str` | ``None``) — format override.
            - ``verbosity`` (:class:`int`) — 0/1/2/-1.
    """
    # --- Open input stream ---
    input_path: str | None = getattr(args, "input", None)
    if input_path is None or input_path == "-":
        raw = sys.stdin.read()
    else:
        try:
            raw = Path(input_path).read_text(encoding="utf-8")
        except OSError as exc:
            print(
                f"job-aggregator hydrate: cannot read input file {input_path!r}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

    # --- Build config ---
    config = HydrateConfig(
        timeout_per_request=int(args.timeout_per_request),
        timeout_total=(int(args.timeout_total) if args.timeout_total is not None else None),
        continue_on_error=bool(getattr(args, "continue_on_error", True)),
        strict=bool(args.strict),
        fmt=getattr(args, "fmt", None),
        verbosity=int(getattr(args, "verbosity", 0)),
    )

    # --- Run hydrator ---
    from io import StringIO

    try:
        output = hydrate(StringIO(raw), config)
    except SchemaVersionError as exc:
        print(
            f"job-aggregator hydrate: {exc}",
            file=sys.stderr,
        )
        sys.exit(4)
    except Exception as exc:
        print(
            f"job-aggregator hydrate: unexpected error: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)

    # --- Write output ---
    output_path: str | None = getattr(args, "output", None)
    if output_path is None:
        print(output)
    else:
        try:
            Path(output_path).write_text(output + "\n", encoding="utf-8")
        except OSError as exc:
            print(
                f"job-aggregator hydrate: cannot write output file {output_path!r}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
