"""Tests for the job-aggregator sources CLI subcommand.

Covers:
- CLI invocation produces valid JSON matching §8.3 shape.
- --credentials PATH adds credentials_configured field per plugin.
- Invalid credentials path produces a clean error (non-zero exit).
- register() and run() API surface for dispatcher integration.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from job_api_aggregator.cli.sources import register, run
from job_api_aggregator.schema import PluginField, PluginInfo

# ---------------------------------------------------------------------------
# Helpers — build synthetic PluginInfo objects
# ---------------------------------------------------------------------------


def _make_plugin_info(
    key: str,
    *,
    requires_creds: bool = False,
) -> PluginInfo:
    """Build a minimal PluginInfo for testing."""
    fields: tuple[PluginField, ...] = ()
    if requires_creds:
        fields = (
            PluginField(
                name="api_key",
                label="API Key",
                type="password",
                required=True,
            ),
        )
    return PluginInfo(
        key=key,
        display_name=key.title(),
        description=f"Test description for {key}.",
        home_url=f"https://{key}.example.com",
        geo_scope="global",
        accepts_query="always",
        accepts_location=True,
        accepts_country=True,
        rate_limit_notes="None.",
        required_search_fields=(),
        fields=fields,
    )


_SAMPLE_PLUGINS = [
    _make_plugin_info("adzuna", requires_creds=True),
    _make_plugin_info("remotive", requires_creds=False),
]


# ---------------------------------------------------------------------------
# run() function — unit tests with mocked list_plugins
# ---------------------------------------------------------------------------


class TestRunOutputShape:
    """run() emits a JSON document matching spec §8.3."""

    def test_output_is_valid_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        """run() writes valid JSON to stdout."""
        import argparse

        args = argparse.Namespace(credentials=None)
        with patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS):
            run(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, dict)

    def test_output_contains_schema_version(self, capsys: pytest.CaptureFixture[str]) -> None:
        """run() output includes schema_version: '1.0'."""
        import argparse

        args = argparse.Namespace(credentials=None)
        with patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS):
            run(args)

        data = json.loads(capsys.readouterr().out)
        assert data["schema_version"] == "1.0"

    def test_output_contains_plugins_list(self, capsys: pytest.CaptureFixture[str]) -> None:
        """run() output includes a 'plugins' list."""
        import argparse

        args = argparse.Namespace(credentials=None)
        with patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS):
            run(args)

        data = json.loads(capsys.readouterr().out)
        assert "plugins" in data
        assert isinstance(data["plugins"], list)

    def test_plugins_list_length_matches(self, capsys: pytest.CaptureFixture[str]) -> None:
        """run() emits one entry per plugin returned by list_plugins."""
        import argparse

        args = argparse.Namespace(credentials=None)
        with patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS):
            run(args)

        data = json.loads(capsys.readouterr().out)
        assert len(data["plugins"]) == len(_SAMPLE_PLUGINS)

    def test_plugin_entry_has_required_fields(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Each plugin entry in the JSON has all required §8.3 fields."""
        import argparse

        args = argparse.Namespace(credentials=None)
        with patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS):
            run(args)

        data = json.loads(capsys.readouterr().out)
        required_fields = {
            "key",
            "display_name",
            "description",
            "home_url",
            "geo_scope",
            "accepts_query",
            "accepts_location",
            "accepts_country",
            "rate_limit_notes",
            "fields",
        }
        for entry in data["plugins"]:
            missing = required_fields - set(entry.keys())
            assert not missing, f"Plugin entry missing fields: {missing}"

    def test_plugin_fields_serialised_as_list_of_objects(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Each plugin's 'fields' value is a list of field-descriptor objects."""
        import argparse

        args = argparse.Namespace(credentials=None)
        with patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS):
            run(args)

        data = json.loads(capsys.readouterr().out)
        adzuna_entry = next(p for p in data["plugins"] if p["key"] == "adzuna")
        assert isinstance(adzuna_entry["fields"], list)
        assert len(adzuna_entry["fields"]) == 1
        field = adzuna_entry["fields"][0]
        assert field["name"] == "api_key"
        assert field["type"] == "password"
        assert field["required"] is True

    def test_no_credentials_configured_field_without_flag(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Without --credentials, no plugin entry has credentials_configured."""
        import argparse

        args = argparse.Namespace(credentials=None)
        with patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS):
            run(args)

        data = json.loads(capsys.readouterr().out)
        for entry in data["plugins"]:
            assert "credentials_configured" not in entry


class TestRunWithCredentials:
    """run() with --credentials adds credentials_configured per plugin."""

    def test_credentials_configured_true_when_all_required_fields_present(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """credentials_configured=True when all required fields have non-empty values."""
        import argparse

        creds = {"adzuna": {"api_key": "val123"}}
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps(creds))

        args = argparse.Namespace(credentials=str(creds_file))
        with patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS):
            run(args)

        data = json.loads(capsys.readouterr().out)
        adzuna_entry = next(p for p in data["plugins"] if p["key"] == "adzuna")
        assert adzuna_entry["credentials_configured"] is True

    def test_credentials_configured_false_when_plugin_missing_from_file(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """credentials_configured=False when plugin key absent from credentials file."""
        import argparse

        creds: dict[str, Any] = {}
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps(creds))

        args = argparse.Namespace(credentials=str(creds_file))
        with patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS):
            run(args)

        data = json.loads(capsys.readouterr().out)
        adzuna_entry = next(p for p in data["plugins"] if p["key"] == "adzuna")
        assert adzuna_entry["credentials_configured"] is False

    def test_credentials_configured_true_for_no_cred_plugin(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """No-cred plugins always have credentials_configured=True."""
        import argparse

        creds: dict[str, Any] = {}
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps(creds))

        args = argparse.Namespace(credentials=str(creds_file))
        with patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS):
            run(args)

        data = json.loads(capsys.readouterr().out)
        remotive_entry = next(p for p in data["plugins"] if p["key"] == "remotive")
        assert remotive_entry["credentials_configured"] is True

    def test_credentials_configured_false_when_required_field_empty(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """credentials_configured=False when a required field value is empty string."""
        import argparse

        creds = {"adzuna": {"api_key": ""}}
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps(creds))

        args = argparse.Namespace(credentials=str(creds_file))
        with patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS):
            run(args)

        data = json.loads(capsys.readouterr().out)
        adzuna_entry = next(p for p in data["plugins"] if p["key"] == "adzuna")
        assert adzuna_entry["credentials_configured"] is False

    def test_credentials_configured_field_present_for_all_plugins(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """With --credentials, every plugin entry has a credentials_configured key."""
        import argparse

        creds: dict[str, Any] = {}
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps(creds))

        args = argparse.Namespace(credentials=str(creds_file))
        with patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS):
            run(args)

        data = json.loads(capsys.readouterr().out)
        for entry in data["plugins"]:
            assert "credentials_configured" in entry, (
                f"Plugin {entry.get('key')!r} missing credentials_configured"
            )


# ---------------------------------------------------------------------------
# run() error handling
# ---------------------------------------------------------------------------


class TestRunErrorHandling:
    """run() handles invalid input gracefully."""

    def test_nonexistent_credentials_path_exits_with_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """run() raises SystemExit with non-zero code for a missing credentials file."""
        import argparse

        args = argparse.Namespace(credentials="/nonexistent/path/creds.json")
        with (
            patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS),
            pytest.raises(SystemExit) as exc_info,
        ):
            run(args)

        assert exc_info.value.code != 0

    def test_invalid_json_credentials_file_exits_with_error(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """run() raises SystemExit with non-zero code when credentials file is not valid JSON."""
        import argparse

        bad_file = tmp_path / "bad.json"
        bad_file.write_text("NOT JSON {{{{")

        args = argparse.Namespace(credentials=str(bad_file))
        with (
            patch("job_api_aggregator.cli.sources.list_plugins", return_value=_SAMPLE_PLUGINS),
            pytest.raises(SystemExit) as exc_info,
        ):
            run(args)

        assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# register() — argparse integration
# ---------------------------------------------------------------------------


class TestRegister:
    """register() correctly wires a 'sources' subparser."""

    def test_register_adds_sources_subcommand(self) -> None:
        """register() adds 'sources' to the subparsers without raising."""
        import argparse

        parser = argparse.ArgumentParser(prog="job-aggregator")
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        # 'sources' subcommand should now parse without error
        args = parser.parse_args(["sources"])
        assert args.command == "sources"

    def test_register_sources_accepts_credentials_flag(self) -> None:
        """register() wires --credentials flag on the sources subcommand."""
        import argparse

        parser = argparse.ArgumentParser(prog="job-aggregator")
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["sources", "--credentials", "/some/path.json"])
        assert args.credentials == "/some/path.json"

    def test_register_sources_credentials_defaults_to_none(self) -> None:
        """--credentials defaults to None when not provided."""
        import argparse

        parser = argparse.ArgumentParser(prog="job-aggregator")
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["sources"])
        assert args.credentials is None


# ---------------------------------------------------------------------------
# CLI integration — invoke via subprocess for full end-to-end check
# ---------------------------------------------------------------------------


class TestCLIIntegration:
    """End-to-end invocation via subprocess using the installed CLI entry point."""

    def test_sources_subcommand_exits_zero(self) -> None:
        """'job-aggregator sources' exits 0."""
        result = subprocess.run(
            [sys.executable, "-m", "job_api_aggregator.cli", "sources"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_sources_subcommand_stdout_is_valid_json(self) -> None:
        """'job-aggregator sources' stdout is valid JSON."""
        result = subprocess.run(
            [sys.executable, "-m", "job_api_aggregator.cli", "sources"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_sources_subcommand_has_all_10_plugins(self) -> None:
        """'job-aggregator sources' output includes all 10 plugins."""
        result = subprocess.run(
            [sys.executable, "-m", "job_api_aggregator.cli", "sources"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        keys = {p["key"] for p in data["plugins"]}
        expected = {
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
        assert keys == expected

    def test_sources_with_credentials_file_adds_configured_field(self, tmp_path: Path) -> None:
        """'job-aggregator sources --credentials PATH' adds credentials_configured."""
        creds: dict[str, Any] = {}
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps(creds))

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "job_api_aggregator.cli",
                "sources",
                "--credentials",
                str(creds_file),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        for entry in data["plugins"]:
            assert "credentials_configured" in entry

    def test_sources_with_nonexistent_credentials_exits_nonzero(self) -> None:
        """'job-aggregator sources --credentials /bad/path' exits non-zero."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "job_api_aggregator.cli",
                "sources",
                "--credentials",
                "/nonexistent/creds.json",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0


# Type alias used in test body above
from typing import Any  # noqa: E402
