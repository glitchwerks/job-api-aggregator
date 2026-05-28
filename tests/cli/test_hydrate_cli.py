"""CLI integration tests for ``job-aggregator hydrate``.

Covers:
- ``--help`` prints all §8.2 flags.
- Format inference (json vs jsonl) wired through CLI.
- ``--strict`` exits non-zero on scrape failure.
- ``--continue-on-error`` (default) exits 0 on scrape failure.
- ``--timeout-per-request`` forwarded to hydrator.
- ``--timeout-total`` forwarded to hydrator.
- ``--input`` reads from a file instead of stdin.
- ``--output`` writes to a file instead of stdout.
- Exit code 4 on cross-major schema_version mismatch.
- ``-v``/``-vv``/``--quiet`` flags are accepted (no crash).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from job_api_aggregator.cli import hydrate as hydrate_cmd
from job_api_aggregator.cli.__main__ import _build_parser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LONG_TEXT = "word " * 120


def _make_record(
    *,
    source_id: str = "001",
    description_source: str = "snippet",
    url: str = "https://example.com/job/1",
) -> dict[str, Any]:
    return {
        "source": "test",
        "source_id": source_id,
        "url": url,
        "title": "Test Job",
        "description": "short snippet",
        "description_source": description_source,
        "posted_at": "2026-04-01T00:00:00Z",
        "company": None,
        "location": None,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_period": None,
        "contract_type": None,
        "contract_time": None,
        "remote_eligible": None,
    }


def _json_input(records: list[dict[str, Any]]) -> str:
    """Return a JSON envelope string."""
    env: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": "2026-04-01T00:00:00Z",
        "command": "jobs",
        "sources_used": ["test"],
        "sources_failed": [],
        "request_summary": {
            "hours": 24,
            "query": None,
            "location": None,
            "country": None,
            "sources": ["test"],
        },
        "jobs": records,
    }
    return json.dumps(env)


def _jsonl_input(records: list[dict[str, Any]]) -> str:
    """Return JSONL (no envelope) string."""
    return "\n".join(json.dumps(r) for r in records)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse argv using the real top-level parser."""
    parser = _build_parser()
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------


def test_hydrate_help_lists_all_flags() -> None:
    """``hydrate --help`` must document every §8.2 flag."""
    parser = _build_parser()
    subparsers_action = None
    for action in parser._actions:
        if hasattr(action, "_parser_class"):
            subparsers_action = action
            break

    # Get the hydrate subparser via choices dict (cast required for mypy
    # since stub types choices as Iterable[Any] even though at runtime
    # argparse uses a dict here).
    assert subparsers_action is not None
    choices: dict[str, argparse.ArgumentParser] = subparsers_action.choices  # type: ignore[assignment]
    hydrate_parser = choices["hydrate"]
    help_text = hydrate_parser.format_help()

    expected_flags = [
        "--input",
        "--output",
        "--timeout-per-request",
        "--timeout-total",
        "--continue-on-error",
        "--strict",
        "--format",
        "-v",
        "--quiet",
    ]
    for flag in expected_flags:
        assert flag in help_text, f"Flag {flag!r} missing from hydrate --help output"


# ---------------------------------------------------------------------------
# register() and run() shape
# ---------------------------------------------------------------------------


def test_hydrate_register_adds_subcommand() -> None:
    """register() must add 'hydrate' to the subparsers group."""
    parser = _build_parser()
    subparsers_action = None
    for action in parser._actions:
        if hasattr(action, "_parser_class"):
            subparsers_action = action
            break
    assert subparsers_action is not None
    assert subparsers_action.choices is not None
    assert "hydrate" in subparsers_action.choices


# ---------------------------------------------------------------------------
# run() wired through CLI — exit codes
# ---------------------------------------------------------------------------


def test_run_exits_0_on_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """run() must complete without exception when scrape succeeds."""
    input_file = tmp_path / "input.jsonl"
    input_file.write_text(_jsonl_input([_make_record()]))

    args = _parse_args(["hydrate", "--input", str(input_file)])

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        # Should NOT raise — successful run returns normally (exit 0)
        hydrate_cmd.run(args)

    captured = capsys.readouterr()
    assert captured.out.strip() != ""


def test_run_continue_on_error_exits_0_on_scrape_failure(
    tmp_path: Path,
) -> None:
    """--continue-on-error (default) exits 0 even when scrape fails."""
    input_file = tmp_path / "input.jsonl"
    input_file.write_text(_jsonl_input([_make_record()]))

    args = _parse_args(["hydrate", "--input", str(input_file)])

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=("short", False),
    ):
        # Should NOT raise SystemExit with non-zero code
        try:
            hydrate_cmd.run(args)
        except SystemExit as e:
            assert e.code == 0 or e.code is None


def test_run_strict_exits_nonzero_on_scrape_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--strict exits non-zero when a scrape fails."""
    input_file = tmp_path / "input.jsonl"
    input_file.write_text(_jsonl_input([_make_record()]))

    args = _parse_args(["hydrate", "--strict", "--input", str(input_file)])

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=("short", False),
    ):
        with pytest.raises(SystemExit) as exc_info:
            hydrate_cmd.run(args)
        assert exc_info.value.code != 0


def test_run_exits_4_on_cross_major_schema_mismatch(
    tmp_path: Path,
) -> None:
    """Cross-major schema_version in input envelope exits with code 4."""
    input_file = tmp_path / "input.json"
    rec = _make_record()
    bad_env = json.loads(_json_input([rec]))
    bad_env["schema_version"] = "2.0"
    input_file.write_text(json.dumps(bad_env))

    args = _parse_args(["hydrate", "--input", str(input_file), "--format", "json"])

    with pytest.raises(SystemExit) as exc_info:
        hydrate_cmd.run(args)
    assert exc_info.value.code == 4


# ---------------------------------------------------------------------------
# --input / --output file handling
# ---------------------------------------------------------------------------


def test_run_reads_from_input_file(tmp_path: Path) -> None:
    """--input PATH reads records from the given file."""
    rec = _make_record()
    input_file = tmp_path / "in.jsonl"
    input_file.write_text(_jsonl_input([rec]))
    output_file = tmp_path / "out.jsonl"

    args = _parse_args(["hydrate", "--input", str(input_file), "--output", str(output_file)])

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        hydrate_cmd.run(args)

    content = output_file.read_text()
    lines = [ln for ln in content.splitlines() if ln.strip()]
    assert len(lines) >= 1


def test_run_writes_to_output_file(tmp_path: Path) -> None:
    """--output PATH writes enriched records to the file."""
    rec = _make_record()
    input_file = tmp_path / "in.jsonl"
    input_file.write_text(_jsonl_input([rec]))
    output_file = tmp_path / "out.jsonl"

    args = _parse_args(["hydrate", "--input", str(input_file), "--output", str(output_file)])

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        hydrate_cmd.run(args)

    assert output_file.exists()
    assert output_file.stat().st_size > 0


# ---------------------------------------------------------------------------
# --format flag
# ---------------------------------------------------------------------------


def test_run_explicit_json_format_produces_envelope(tmp_path: Path) -> None:
    """--format json produces a single JSON object with 'jobs' key."""
    rec = _make_record()
    input_file = tmp_path / "in.json"
    input_file.write_text(_json_input([rec]))
    output_file = tmp_path / "out.json"

    args = _parse_args(
        [
            "hydrate",
            "--input",
            str(input_file),
            "--output",
            str(output_file),
            "--format",
            "json",
        ]
    )

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        hydrate_cmd.run(args)

    parsed = json.loads(output_file.read_text())
    assert "jobs" in parsed
    assert parsed["command"] == "hydrate"


def test_run_explicit_jsonl_format_produces_lines(tmp_path: Path) -> None:
    """--format jsonl produces multiple JSONL lines."""
    rec = _make_record()
    input_file = tmp_path / "in.jsonl"
    input_file.write_text(_jsonl_input([rec]))
    output_file = tmp_path / "out.jsonl"

    args = _parse_args(
        [
            "hydrate",
            "--input",
            str(input_file),
            "--output",
            str(output_file),
            "--format",
            "jsonl",
        ]
    )

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        hydrate_cmd.run(args)

    lines = [ln for ln in output_file.read_text().splitlines() if ln.strip()]
    assert len(lines) >= 2  # envelope + at least one record


# ---------------------------------------------------------------------------
# Verbosity flags accepted without crash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["-v", "-vv", "--quiet"])
def test_verbosity_flags_accepted(flag: str, tmp_path: Path) -> None:
    """Verbosity flags must be accepted without error."""
    rec = _make_record()
    input_file = tmp_path / "in.jsonl"
    input_file.write_text(_jsonl_input([rec]))

    args = _parse_args(["hydrate", "--input", str(input_file), flag])

    with patch(
        "job_api_aggregator.hydrator.scrape_description",
        return_value=(_LONG_TEXT, True),
    ):
        # Should not raise
        try:
            hydrate_cmd.run(args)
        except SystemExit as e:
            assert e.code == 0 or e.code is None


# ---------------------------------------------------------------------------
# --timeout-per-request / --timeout-total forwarded
# ---------------------------------------------------------------------------


def test_timeout_per_request_forwarded(tmp_path: Path) -> None:
    """--timeout-per-request N must be forwarded to the hydrator."""

    rec = _make_record()
    input_file = tmp_path / "in.jsonl"
    input_file.write_text(_jsonl_input([rec]))

    args = _parse_args(["hydrate", "--timeout-per-request", "7", "--input", str(input_file)])

    with patch("job_api_aggregator.cli.hydrate.hydrate") as mock_hydrate:
        mock_hydrate.return_value = _jsonl_input([rec])
        hydrate_cmd.run(args)

    call_args = mock_hydrate.call_args
    config = call_args.args[1] if call_args.args else call_args.kwargs["config"]
    assert config.timeout_per_request == 7


def test_timeout_total_forwarded(tmp_path: Path) -> None:
    """--timeout-total N must be forwarded to the hydrator."""
    rec = _make_record()
    input_file = tmp_path / "in.jsonl"
    input_file.write_text(_jsonl_input([rec]))

    args = _parse_args(["hydrate", "--timeout-total", "60", "--input", str(input_file)])

    with patch("job_api_aggregator.cli.hydrate.hydrate") as mock_hydrate:
        mock_hydrate.return_value = _jsonl_input([rec])
        hydrate_cmd.run(args)

    call_args = mock_hydrate.call_args
    config = call_args.args[1] if call_args.args else call_args.kwargs["config"]
    assert config.timeout_total == 60
