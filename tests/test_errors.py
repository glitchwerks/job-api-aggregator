"""Tests for the job_api_aggregator exception hierarchy.

Every exception class must:
- Inherit from JobAggregatorError
- Accept structured constructor arguments
- Expose those arguments as attributes
- Produce a useful __str__ representation
"""

from job_api_aggregator.errors import (
    CredentialsError,
    JobAggregatorError,
    PluginConflictError,
    SchemaVersionError,
    ScrapeError,
)


class TestJobAggregatorError:
    """Base exception class tests."""

    def test_is_exception(self) -> None:
        """JobAggregatorError must be a standard Exception subclass."""
        err = JobAggregatorError("test message")
        assert isinstance(err, Exception)

    def test_message_preserved(self) -> None:
        """Constructor message is accessible via args[0]."""
        err = JobAggregatorError("boom")
        assert str(err) == "boom"


class TestPluginConflictError:
    """Tests for PluginConflictError."""

    def test_inherits_from_base(self) -> None:
        """PluginConflictError is a JobAggregatorError."""
        err = PluginConflictError(
            key="adzuna",
            sources=["job-aggregator (built-in)", "adzuna-extra (third-party)"],
        )
        assert isinstance(err, JobAggregatorError)

    def test_key_attribute(self) -> None:
        """The conflicting plugin key is stored on the exception."""
        err = PluginConflictError(
            key="adzuna",
            sources=["pkg-a::adzuna", "pkg-b::adzuna"],
        )
        assert err.key == "adzuna"

    def test_sources_attribute(self) -> None:
        """Both registration sources are stored on the exception."""
        sources = ["job-aggregator::adzuna", "adzuna-extra::adzuna"]
        err = PluginConflictError(key="adzuna", sources=sources)
        assert err.sources == sources

    def test_str_contains_both_sources(self) -> None:
        """__str__ must name both registration sources."""
        err = PluginConflictError(
            key="adzuna",
            sources=["job-aggregator::adzuna", "adzuna-extra::adzuna"],
        )
        msg = str(err)
        assert "job-aggregator::adzuna" in msg
        assert "adzuna-extra::adzuna" in msg

    def test_str_contains_key(self) -> None:
        """__str__ includes the conflicting key."""
        err = PluginConflictError(key="adzuna", sources=["a::x", "b::x"])
        assert "adzuna" in str(err)


class TestScrapeError:
    """Tests for ScrapeError."""

    def test_inherits_from_base(self) -> None:
        """ScrapeError is a JobAggregatorError."""
        err = ScrapeError(url="https://example.com/job/1", reason="HTTP 404")
        assert isinstance(err, JobAggregatorError)

    def test_url_attribute(self) -> None:
        """The target URL is stored on the exception."""
        err = ScrapeError(url="https://example.com/job/1", reason="timeout")
        assert err.url == "https://example.com/job/1"

    def test_reason_attribute(self) -> None:
        """The failure reason is stored on the exception."""
        err = ScrapeError(url="https://example.com/job/1", reason="HTTP 503")
        assert err.reason == "HTTP 503"

    def test_str_contains_url_and_reason(self) -> None:
        """__str__ includes both url and reason for quick diagnosis."""
        err = ScrapeError(url="https://example.com/job/1", reason="connection refused")
        msg = str(err)
        assert "https://example.com/job/1" in msg
        assert "connection refused" in msg


class TestCredentialsError:
    """Tests for CredentialsError."""

    def test_inherits_from_base(self) -> None:
        """CredentialsError is a JobAggregatorError."""
        err = CredentialsError(plugin_key="adzuna", missing_fields=["app_id"])
        assert isinstance(err, JobAggregatorError)

    def test_plugin_key_attribute(self) -> None:
        """The plugin key is stored on the exception."""
        err = CredentialsError(plugin_key="adzuna", missing_fields=["app_key"])
        assert err.plugin_key == "adzuna"

    def test_missing_fields_attribute(self) -> None:
        """The list of missing fields is stored on the exception."""
        err = CredentialsError(plugin_key="adzuna", missing_fields=["app_id", "app_key"])
        assert err.missing_fields == ["app_id", "app_key"]

    def test_str_contains_plugin_and_fields(self) -> None:
        """__str__ includes the plugin key and missing field names."""
        err = CredentialsError(plugin_key="adzuna", missing_fields=["app_id", "app_key"])
        msg = str(err)
        assert "adzuna" in msg
        assert "app_id" in msg
        assert "app_key" in msg


class TestSchemaVersionError:
    """Tests for SchemaVersionError."""

    def test_inherits_from_base(self) -> None:
        """SchemaVersionError is a JobAggregatorError."""
        err = SchemaVersionError(got="2.0", expected="1.0")
        assert isinstance(err, JobAggregatorError)

    def test_got_attribute(self) -> None:
        """The received schema version is stored on the exception."""
        err = SchemaVersionError(got="2.0", expected="1.0")
        assert err.got == "2.0"

    def test_expected_attribute(self) -> None:
        """The expected schema version is stored on the exception."""
        err = SchemaVersionError(got="2.0", expected="1.0")
        assert err.expected == "1.0"

    def test_str_contains_both_versions(self) -> None:
        """__str__ includes both the received and expected versions."""
        err = SchemaVersionError(got="2.0", expected="1.0")
        msg = str(err)
        assert "2.0" in msg
        assert "1.0" in msg
