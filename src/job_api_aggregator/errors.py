"""Exception hierarchy for the job-aggregator package.

All package-specific exceptions inherit from ``JobAggregatorError`` so
callers can catch any package error with a single except clause while
still being able to distinguish individual failure modes.
"""

from __future__ import annotations


class JobAggregatorError(Exception):
    """Base class for all job-aggregator exceptions."""


class PluginConflictError(JobAggregatorError):
    """Two registrations claim the same plugin SOURCE key.

    Raised by :func:`job_aggregator.auto_register.discover_plugins` when
    the entry-point scan finds duplicate ``SOURCE`` values across different
    distribution packages or entry-point names.  The error is fatal: the
    ambiguity must be resolved by the user (uninstall the duplicate or add
    the key to ``JOB_SCRAPER_DISABLE_PLUGINS``) before the package can
    start cleanly.

    Attributes:
        key: The conflicting plugin key (e.g. ``"adzuna"``).
        sources: Both registration identifiers in the form
            ``"<dist-name>::<entry-point-name>"``.
    """

    def __init__(self, key: str, sources: list[str]) -> None:
        """Initialise the error with the conflicting key and both sources.

        Args:
            key: The plugin SOURCE key that is claimed by multiple
                registrations.
            sources: A two-element list of registration identifiers, each
                in the form ``"<dist-name>::<entry-point-name>"``.
        """
        self.key = key
        self.sources = sources
        super().__init__(str(self))

    def __str__(self) -> str:
        """Return a human-readable description listing both sources.

        Returns:
            A string naming the conflicting key and both registration
            sources so the user knows exactly which packages to examine.
        """
        sources_str = ", ".join(self.sources)
        return (
            f"Plugin key {self.key!r} is registered by multiple sources: "
            f"{sources_str}. "
            f"Uninstall one of the conflicting packages or add "
            f"{self.key!r} to JOB_SCRAPER_DISABLE_PLUGINS."
        )


class ScrapeError(JobAggregatorError):
    """HTTP or parse failure while scraping a job description URL.

    Raised (or stored and emitted) by
    :func:`job_aggregator.scraping.scrape_description` when the HTTP
    request fails or the response body cannot be parsed.

    Attributes:
        url: The URL that was being scraped.
        reason: Human-readable explanation of the failure (e.g.
            ``"HTTP 404"`` or ``"connection timed out"``).
    """

    def __init__(self, url: str, reason: str) -> None:
        """Initialise the error with the target URL and failure reason.

        Args:
            url: The job posting URL that triggered the scrape failure.
            reason: A short human-readable explanation of why the scrape
                failed (HTTP status, network error, parse error, etc.).
        """
        self.url = url
        self.reason = reason
        super().__init__(str(self))

    def __str__(self) -> str:
        """Return a human-readable description of the scrape failure.

        Returns:
            A string combining the URL and reason for quick log diagnosis.
        """
        return f"Scrape failed for {self.url!r}: {self.reason}"


class CredentialsError(JobAggregatorError):
    """Missing or invalid credentials at plugin construction time.

    Raised by a ``JobSource`` subclass ``__init__`` when the credentials
    dict supplied by the caller omits one or more required fields.

    Attributes:
        plugin_key: The SOURCE key of the plugin that raised this error.
        missing_fields: Names of the credential fields that were absent or
            empty in the supplied credentials dict.
    """

    def __init__(self, plugin_key: str, missing_fields: list[str]) -> None:
        """Initialise the error with the plugin key and missing field names.

        Args:
            plugin_key: The ``SOURCE`` key of the plugin that detected the
                missing credentials (e.g. ``"adzuna"``).
            missing_fields: List of field names that are absent or empty in
                the credentials dict provided by the caller.
        """
        self.plugin_key = plugin_key
        self.missing_fields = missing_fields
        super().__init__(str(self))

    def __str__(self) -> str:
        """Return a human-readable description of the missing fields.

        Returns:
            A string naming the plugin and each missing field so the user
            knows exactly what to supply.
        """
        fields_str = ", ".join(self.missing_fields)
        return f"Plugin {self.plugin_key!r} is missing required credentials: {fields_str}."


class SchemaVersionError(JobAggregatorError):
    """Input envelope schema_version is incompatible with this package version.

    Raised by ``job-aggregator hydrate`` when the envelope's
    ``schema_version`` major component differs from the package's current
    major version (cross-major is refused; see spec §8.2.1).

    Attributes:
        got: The ``schema_version`` string found in the input envelope.
        expected: The ``schema_version`` string the package expects (current
            major, e.g. ``"1.0"``).
    """

    def __init__(self, got: str, expected: str) -> None:
        """Initialise the error with the received and expected versions.

        Args:
            got: The ``schema_version`` value found in the input envelope.
            expected: The ``schema_version`` value this package version
                accepts.
        """
        self.got = got
        self.expected = expected
        super().__init__(str(self))

    def __str__(self) -> str:
        """Return a human-readable description of the version mismatch.

        Returns:
            A string comparing the received version against the expected
            version so the user knows how to resolve the incompatibility.
        """
        return (
            f"Input schema_version {self.got!r} is incompatible with "
            f"this package (expected major version {self.expected!r}). "
            f"Re-generate the input with a compatible version of "
            f"job-aggregator."
        )
