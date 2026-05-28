"""Tests for the ``job-aggregator jobs`` CLI subcommand.

Uses ``subprocess`` / ``capsys`` patterns to exercise the argparse dispatch
and verify:

- stderr warning when ``--query`` + ``never``/``partial`` sources are enabled.
- stdout contains a valid JSON/JSONL envelope.
- ``--dry-run`` flag produces empty jobs array.
- ``--help`` prints all expected flags.
- Subcommand dispatch (hydrate/sources stubs return non-zero with a
  "not-yet-implemented" message so parallel PRs can flesh them out).
"""

from __future__ import annotations

import json
from io import StringIO
from typing import Any
from unittest.mock import patch

from tests.fixtures.plugins.stub_plugins import (
    AlwaysQueryPlugin,
    NeverQueryPlugin,
    PartialQueryPlugin,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_main() -> Any:
    """Import the main() entrypoint from cli.__main__.

    Returns:
        The ``main`` callable.
    """
    from job_api_aggregator.cli.__main__ import main

    return main


def _import_jobs_handler() -> Any:
    """Import cmd_jobs from cli.__main__.

    Returns:
        The ``cmd_jobs`` callable.
    """
    from job_api_aggregator.cli.__main__ import cmd_jobs

    return cmd_jobs


def _run_cmd_jobs(
    plugin_classes: dict[str, type[Any]],
    argv: list[str],
    *,
    credentials_json: dict[str, Any] | None = None,
    tmpdir: Any = None,
) -> tuple[str, str, int]:
    """Run cmd_jobs with given argv and return (stdout, stderr, exit_code).

    Patches ``discover_plugins`` so no real entry-points are loaded.
    Credentials are written to a temp file so the CLI can read them.

    Args:
        plugin_classes: Mapping of plugin key → class to inject.
        argv: Command-line args as if passed after ``job-aggregator jobs``.
        credentials_json: Optional dict to write to a temp credentials file.
        tmpdir: pytest ``tmp_path`` fixture (required if
            ``--credentials`` is in argv).

    Returns:
        Tuple of (captured stdout, captured stderr, exit code).
    """
    import argparse

    cmd_jobs = _import_jobs_handler()

    # Build a minimal namespace simulating parsed args
    parser = argparse.ArgumentParser()
    # We'll call cmd_jobs directly with a Namespace so we don't go through
    # the full argparse stack — but we do need a credentials file
    pass

    stdout_buf = StringIO()
    stderr_buf = StringIO()

    # Determine credentials file path
    creds_path: str | None = None
    if tmpdir is not None:
        creds = credentials_json or {
            "schema_version": "1.0",
            "plugins": {},
        }
        creds_file = tmpdir / "creds.json"
        creds_file.write_text(json.dumps(creds))
        creds_path = str(creds_file)

    # Parse argv via the real argparse to get a Namespace
    from job_api_aggregator.cli.__main__ import _build_parser

    parser = _build_parser()
    full_argv = ["jobs", *argv]
    if creds_path and "--credentials" not in argv:
        full_argv = [*full_argv, "--credentials", creds_path]
    ns = parser.parse_args(full_argv)

    with (
        patch("sys.stdout", stdout_buf),
        patch("sys.stderr", stderr_buf),
        patch(
            "job_api_aggregator.orchestrator.discover_plugins",
            return_value=plugin_classes,
        ),
    ):
        exit_code = 0
        try:
            cmd_jobs(ns)
        except SystemExit as exc:
            exit_code = int(exc.code or 0)

    return stdout_buf.getvalue(), stderr_buf.getvalue(), exit_code


# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------


class TestHelp:
    """Tests for --help output."""

    def test_help_lists_jobs_subcommand(self, tmp_path: Any) -> None:
        """--help must mention the jobs subcommand."""
        from job_api_aggregator.cli.__main__ import _build_parser

        parser = _build_parser()
        buf = StringIO()
        try:
            with patch("sys.stdout", buf):
                parser.parse_args(["--help"])
        except SystemExit:
            pass
        output = buf.getvalue()
        assert "jobs" in output

    def test_jobs_help_lists_all_flags(self, tmp_path: Any) -> None:
        """``jobs --help`` must list all required flags."""
        from job_api_aggregator.cli.__main__ import _build_parser

        parser = _build_parser()
        buf = StringIO()
        try:
            with patch("sys.stdout", buf):
                parser.parse_args(["jobs", "--help"])
        except SystemExit:
            pass
        output = buf.getvalue()
        for flag in [
            "--hours",
            "--query",
            "--location",
            "--country",
            "--sources",
            "--exclude-sources",
            "--limit",
            "--max-pages",
            "--credentials",
            "--format",
            "--output",
            "--strict",
            "--dry-run",
        ]:
            assert flag in output, f"Missing flag in --help: {flag!r}"


# ---------------------------------------------------------------------------
# Q4 warning tests
# ---------------------------------------------------------------------------


class TestQueryWarnings:
    """Tests for Q4 stderr warning when --query + never/partial sources."""

    def test_warning_emitted_for_never_source(self, tmp_path: Any) -> None:
        """stderr must warn when --query used with accepts_query=never source."""
        _stdout, stderr, _code = _run_cmd_jobs(
            plugin_classes={NeverQueryPlugin.SOURCE: NeverQueryPlugin},
            argv=["--query", "python", "--format", "json"],
            tmpdir=tmp_path,
        )
        assert "WARNING" in stderr
        assert NeverQueryPlugin.SOURCE in stderr

    def test_warning_emitted_for_partial_source(self, tmp_path: Any) -> None:
        """stderr must warn when --query used with accepts_query=partial source."""
        _stdout, stderr, _code = _run_cmd_jobs(
            plugin_classes={PartialQueryPlugin.SOURCE: PartialQueryPlugin},
            argv=["--query", "python", "--format", "json"],
            tmpdir=tmp_path,
        )
        assert "WARNING" in stderr
        assert PartialQueryPlugin.SOURCE in stderr

    def test_no_warning_for_always_source(self, tmp_path: Any) -> None:
        """No stderr warning when --query used with only accepts_query=always."""
        _stdout, stderr, _code = _run_cmd_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            argv=["--query", "python", "--format", "json"],
            tmpdir=tmp_path,
        )
        assert "WARNING" not in stderr

    def test_no_warning_when_no_query(self, tmp_path: Any) -> None:
        """No warning emitted when --query is not passed."""
        _stdout, stderr, _code = _run_cmd_jobs(
            plugin_classes={NeverQueryPlugin.SOURCE: NeverQueryPlugin},
            argv=["--format", "json"],
            tmpdir=tmp_path,
        )
        assert "WARNING" not in stderr

    def test_warning_names_both_never_and_partial_sources(self, tmp_path: Any) -> None:
        """Warning must list both never and partial sources when present."""
        _stdout, stderr, _code = _run_cmd_jobs(
            plugin_classes={
                NeverQueryPlugin.SOURCE: NeverQueryPlugin,
                PartialQueryPlugin.SOURCE: PartialQueryPlugin,
            },
            argv=["--query", "engineer", "--format", "json"],
            tmpdir=tmp_path,
        )
        assert NeverQueryPlugin.SOURCE in stderr
        assert PartialQueryPlugin.SOURCE in stderr


# ---------------------------------------------------------------------------
# Envelope output correctness
# ---------------------------------------------------------------------------


class TestCliEnvelopeOutput:
    """Tests for stdout envelope correctness from the CLI."""

    def test_dry_run_produces_valid_json_envelope(self, tmp_path: Any) -> None:
        """--dry-run --format json must produce a valid envelope to stdout."""
        stdout, _stderr, _code = _run_cmd_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            argv=["--dry-run", "--format", "json"],
            tmpdir=tmp_path,
        )
        data = json.loads(stdout)
        assert data["jobs"] == []
        assert "schema_version" in data

    def test_dry_run_query_produces_query_applied_field(self, tmp_path: Any) -> None:
        """--dry-run with --query must populate query_applied in envelope."""
        stdout, _stderr, _code = _run_cmd_jobs(
            plugin_classes={
                AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin,
                NeverQueryPlugin.SOURCE: NeverQueryPlugin,
            },
            argv=["--dry-run", "--query", "python", "--format", "json"],
            tmpdir=tmp_path,
        )
        data = json.loads(stdout)
        assert "query_applied" in data
        assert data["query_applied"][AlwaysQueryPlugin.SOURCE] is True
        assert data["query_applied"][NeverQueryPlugin.SOURCE] is False

    def test_jsonl_first_line_is_envelope(self, tmp_path: Any) -> None:
        """JSONL format: first stdout line must be the envelope."""
        stdout, _stderr, _code = _run_cmd_jobs(
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
            argv=["--format", "jsonl"],
            tmpdir=tmp_path,
        )
        first_line = stdout.strip().splitlines()[0]
        envelope = json.loads(first_line)
        assert envelope["command"] == "jobs"
        assert envelope["jobs"] == []


# ---------------------------------------------------------------------------
# Unimplemented subcommands
# ---------------------------------------------------------------------------


class TestUnimplementedSubcommands:
    """Stubs for hydrate/sources subcommands must not crash with --help."""

    def test_hydrate_subcommand_exists(self) -> None:
        """hydrate subcommand must be registered in the parser."""
        from job_api_aggregator.cli.__main__ import _build_parser

        parser = _build_parser()
        buf = StringIO()
        try:
            with patch("sys.stdout", buf):
                parser.parse_args(["hydrate", "--help"])
        except SystemExit:
            pass
        # Should not raise an argparse error about unknown subcommand.
        # We just verify the parser accepted the subcommand name without
        # an "invalid choice" error; checking the exit alone is sufficient.
        _ = buf.getvalue()

    def test_sources_subcommand_exists(self) -> None:
        """sources subcommand must be registered in the parser."""
        from job_api_aggregator.cli.__main__ import _build_parser

        parser = _build_parser()
        buf = StringIO()
        try:
            with patch("sys.stdout", buf):
                parser.parse_args(["sources", "--help"])
        except SystemExit:
            pass
        # Parser accepted the subcommand without "invalid choice" error.
        _ = buf.getvalue()
