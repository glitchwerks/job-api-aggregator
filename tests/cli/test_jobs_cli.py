"""CLI integration tests for ``job-aggregator jobs``.

Covers the credentials-optional behaviour introduced in Issue #50:

- Test 1: ``jobs --sources <no-auth>`` with no ``--credentials`` —
  parser accepts and orchestrator runs (no HTTP).
- Test 2: ``jobs --sources adzuna`` with no ``--credentials`` — exits 2,
  error message names ``adzuna``.
- Test 3: ``jobs --sources himalayas,adzuna`` with no ``--credentials`` —
  exits 2, error message names ``adzuna`` (not ``himalayas``).
- Test 4: ``jobs --sources <no-auth> --credentials <empty-file>`` —
  back-compat: supplying a credentials file for a no-auth-only run
  must succeed.
- Existing credentialed-path tests: ``--credentials`` supplied for a run
  that includes credentialed sources must succeed.
"""

from __future__ import annotations

import json
from io import StringIO
from typing import Any
from unittest.mock import patch

import pytest

from job_api_aggregator.cli.__main__ import _build_parser
from job_api_aggregator.schema import PluginField, PluginInfo
from tests.fixtures.plugins.stub_plugins import AlwaysQueryPlugin

# ---------------------------------------------------------------------------
# PluginInfo helpers
# ---------------------------------------------------------------------------

_FIELD_APP_ID = PluginField(
    name="app_id",
    label="App ID",
    type="text",
    required=True,
)

_FIELD_API_KEY = PluginField(
    name="api_key",
    label="API Key",
    type="password",
    required=True,
)


def _make_noauth_info(key: str = "himalayas") -> PluginInfo:
    """Return a PluginInfo with no required credential fields.

    Args:
        key: Plugin key to use (default: ``"himalayas"``).

    Returns:
        A :class:`~job_api_aggregator.schema.PluginInfo` with empty
        ``fields``, so ``requires_credentials`` is ``False``.
    """
    return PluginInfo(
        key=key,
        display_name=key.title(),
        description=f"Stub {key} plugin.",
        home_url=f"https://example.com/{key}",
        geo_scope="global",
        accepts_query="always",
        accepts_location=False,
        accepts_country=False,
        rate_limit_notes="No limit.",
        required_search_fields=(),
        fields=(),
    )


def _make_credentialed_info(key: str = "adzuna") -> PluginInfo:
    """Return a PluginInfo with required credential fields.

    Args:
        key: Plugin key to use (default: ``"adzuna"``).

    Returns:
        A :class:`~job_api_aggregator.schema.PluginInfo` with two required
        fields, so ``requires_credentials`` is ``True``.
    """
    return PluginInfo(
        key=key,
        display_name=key.title(),
        description=f"Stub {key} plugin.",
        home_url=f"https://example.com/{key}",
        geo_scope="global",
        accepts_query="always",
        accepts_location=True,
        accepts_country=True,
        rate_limit_notes="Keyed API.",
        required_search_fields=(),
        fields=(_FIELD_APP_ID, _FIELD_API_KEY),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_jobs_cli(
    argv: list[str],
    *,
    list_plugins_return: list[PluginInfo],
    plugin_classes: dict[str, Any] | None = None,
) -> tuple[str, str, int]:
    """Invoke the ``jobs`` subcommand via the real argparse parser.

    Patches ``job_api_aggregator.cli.jobs.list_plugins`` (used by
    ``_resolve_selected_sources``) and
    ``job_api_aggregator.orchestrator.discover_plugins`` (used by
    ``run_jobs``).

    Args:
        argv: Arguments passed *after* ``"jobs"`` on the command line.
        list_plugins_return: The list of :class:`PluginInfo` objects that
            ``list_plugins()`` should return in ``_resolve_selected_sources``.
        plugin_classes: Optional mapping of plugin key → class for the
            orchestrator.  When ``None``, an empty dict is used so no
            real HTTP calls are made.

    Returns:
        Tuple of ``(stdout_text, stderr_text, exit_code)``.
    """
    if plugin_classes is None:
        plugin_classes = {}

    parser = _build_parser()
    full_argv = ["jobs", *argv]

    stdout_buf = StringIO()
    stderr_buf = StringIO()
    exit_code = 0

    try:
        ns = parser.parse_args(full_argv)
    except SystemExit as exc:
        return "", "", int(exc.code or 0)

    with (
        patch("sys.stdout", stdout_buf),
        patch("sys.stderr", stderr_buf),
        patch(
            "job_api_aggregator.cli.jobs.list_plugins",
            return_value=list_plugins_return,
        ),
        patch(
            "job_api_aggregator.orchestrator.discover_plugins",
            return_value=plugin_classes,
        ),
    ):
        try:
            ns.func(ns)
        except SystemExit as exc:
            exit_code = int(exc.code or 0)

    return stdout_buf.getvalue(), stderr_buf.getvalue(), exit_code


# ---------------------------------------------------------------------------
# Test 1 — no-auth source, no --credentials → succeeds
# ---------------------------------------------------------------------------


class TestNoCredsNoAuthSource:
    """``jobs --sources <no-auth>`` with no --credentials must succeed."""

    def test_no_credentials_no_auth_source_exits_zero(self) -> None:
        """Parser accepts and run completes when source needs no creds.

        Uses a stub AlwaysQueryPlugin (SOURCE="stub_always") so no real
        HTTP calls are made.
        """
        _stdout, _stderr, code = _run_jobs_cli(
            ["--sources", "stub_always", "--dry-run", "--format", "json"],
            list_plugins_return=[_make_noauth_info("stub_always")],
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
        )
        assert code == 0

    def test_no_credentials_no_auth_source_emits_envelope(self) -> None:
        """run() emits a valid JSON envelope to stdout when no creds needed."""
        stdout, _stderr, code = _run_jobs_cli(
            ["--sources", "stub_always", "--dry-run", "--format", "json"],
            list_plugins_return=[_make_noauth_info("stub_always")],
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
        )
        assert code == 0
        data = json.loads(stdout)
        assert "schema_version" in data
        assert "jobs" in data


# ---------------------------------------------------------------------------
# Test 2 — credentialed source, no --credentials → exits 2 naming adzuna
# ---------------------------------------------------------------------------


class TestNoCredsCredentialedSource:
    """``jobs --sources adzuna`` with no --credentials exits 2."""

    def test_exits_nonzero_when_creds_required(self) -> None:
        """Exit code must be 2 (argparse convention) when creds missing."""
        _stdout, _stderr, code = _run_jobs_cli(
            ["--sources", "adzuna"],
            list_plugins_return=[_make_credentialed_info("adzuna")],
        )
        assert code == 2

    def test_error_message_names_adzuna(self) -> None:
        """Error message must name the source that needs credentials."""
        _stdout, stderr, _code = _run_jobs_cli(
            ["--sources", "adzuna"],
            list_plugins_return=[_make_credentialed_info("adzuna")],
        )
        assert "adzuna" in stderr

    def test_error_message_mentions_credentials_flag(self) -> None:
        """Error message must mention ``--credentials`` so user knows the fix."""
        _stdout, stderr, _code = _run_jobs_cli(
            ["--sources", "adzuna"],
            list_plugins_return=[_make_credentialed_info("adzuna")],
        )
        assert "--credentials" in stderr


# ---------------------------------------------------------------------------
# Test 3 — mixed sources, no --credentials → names only adzuna (not himalayas)
# ---------------------------------------------------------------------------


class TestMixedSourcesNoCredsError:
    """Mixed no-auth + credentialed sources without --credentials."""

    def test_exits_nonzero(self) -> None:
        """Exit code must be 2 when a credentialed source is selected."""
        _stdout, _stderr, code = _run_jobs_cli(
            ["--sources", "himalayas,adzuna"],
            list_plugins_return=[
                _make_noauth_info("himalayas"),
                _make_credentialed_info("adzuna"),
            ],
        )
        assert code == 2

    def test_error_names_adzuna_only(self) -> None:
        """Error message must name adzuna but not himalayas."""
        _stdout, stderr, _code = _run_jobs_cli(
            ["--sources", "himalayas,adzuna"],
            list_plugins_return=[
                _make_noauth_info("himalayas"),
                _make_credentialed_info("adzuna"),
            ],
        )
        assert "adzuna" in stderr
        assert "himalayas" not in stderr

    def test_error_suggests_exclude_sources(self) -> None:
        """Error message must mention --exclude-sources as a remedy."""
        _stdout, stderr, _code = _run_jobs_cli(
            ["--sources", "himalayas,adzuna"],
            list_plugins_return=[
                _make_noauth_info("himalayas"),
                _make_credentialed_info("adzuna"),
            ],
        )
        assert "--exclude-sources" in stderr


# ---------------------------------------------------------------------------
# Test 4 — no-auth source + --credentials supplied → back-compat
# ---------------------------------------------------------------------------


class TestCredsSuppliedNoAuthSource:
    """Supplying --credentials for a no-auth-only run must not break."""

    def test_creds_file_for_noauth_source_exits_zero(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Back-compat: supplying an empty credentials file must succeed."""
        empty_creds = tmp_path / "empty_creds.json"  # type: ignore[operator]
        empty_creds.write_text(json.dumps({"schema_version": "1.0", "plugins": {}}))

        _stdout, _stderr, code = _run_jobs_cli(
            [
                "--sources",
                "stub_always",
                "--credentials",
                str(empty_creds),
                "--dry-run",
                "--format",
                "json",
            ],
            list_plugins_return=[_make_noauth_info("stub_always")],
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
        )
        assert code == 0

    def test_creds_file_for_noauth_source_emits_envelope(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Envelope is emitted normally when credentials file is supplied."""
        empty_creds = tmp_path / "empty_creds.json"  # type: ignore[operator]
        empty_creds.write_text(json.dumps({"schema_version": "1.0", "plugins": {}}))

        stdout, _stderr, code = _run_jobs_cli(
            [
                "--sources",
                "stub_always",
                "--credentials",
                str(empty_creds),
                "--dry-run",
                "--format",
                "json",
            ],
            list_plugins_return=[_make_noauth_info("stub_always")],
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
        )
        assert code == 0
        data = json.loads(stdout)
        assert "schema_version" in data


# ---------------------------------------------------------------------------
# Existing path — credentialed run with --credentials supplied
# ---------------------------------------------------------------------------


class TestCredsSuppliedCredentialedSource:
    """``--credentials`` supplied for a credentialed source must succeed."""

    def test_credentialed_run_with_creds_file_exits_zero(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """When --credentials is supplied with real keys, run succeeds."""
        creds_file = tmp_path / "creds.json"  # type: ignore[operator]
        creds_file.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "plugins": {
                        "stub_always": {
                            "app_id": "dummy-id",
                            "api_key": "dummy-key",
                        }
                    },
                }
            )
        )

        _stdout, _stderr, code = _run_jobs_cli(
            [
                "--sources",
                "stub_always",
                "--credentials",
                str(creds_file),
                "--dry-run",
                "--format",
                "json",
            ],
            list_plugins_return=[_make_noauth_info("stub_always")],
            plugin_classes={AlwaysQueryPlugin.SOURCE: AlwaysQueryPlugin},
        )
        assert code == 0
