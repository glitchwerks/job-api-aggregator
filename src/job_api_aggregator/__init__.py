"""job-aggregator — reusable job aggregation library.

Provides pluggable source plugins, normalized job-record output,
and a structured CLI.  No scoring, no database, no LLM dependencies.
"""

import logging
from importlib.metadata import PackageNotFoundError, version

from job_aggregator.base import JobSource
from job_aggregator.envelope import build_envelope, build_jsonl_lines
from job_aggregator.errors import (
    CredentialsError,
    JobAggregatorError,
    PluginConflictError,
    SchemaVersionError,
    ScrapeError,
)
from job_aggregator.hydrator import HydrateConfig, hydrate
from job_aggregator.normalizer import (
    classify_description_source,
    normalize,
)
from job_aggregator.orchestrator import run_jobs
from job_aggregator.registry import (
    get_plugin,
    list_plugins,
    make_enabled_sources,
)
from job_aggregator.schema import (
    JobRecord,
    PluginField,
    PluginInfo,
    SearchParams,
)
from job_aggregator.scraping import SCRAPE_MIN_LENGTH, scrape_description

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

try:
    __version__: str = version("job-aggregator")
except PackageNotFoundError:
    # Package is not installed (e.g. running directly from source tree
    # without `pip install -e .`).
    __version__ = "0.0.0+unknown"

# ---------------------------------------------------------------------------
# Library logger — PEP 282 convention
#
# Attach a NullHandler so that log records emitted by this library are
# silently discarded unless the *consuming application* configures a
# handler.  This prevents "No handlers could be found for logger
# 'job_aggregator'" warnings in library consumers that have not
# configured logging.
# ---------------------------------------------------------------------------

logging.getLogger(__name__).addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# Public API surface — Issues B + D + F exports.
# Remaining exports (scrape_description) are added by Issue E.
# One symbol per line for clean merge diffs with parallel PRs.
# ---------------------------------------------------------------------------

__all__: list[str] = [
    "SCRAPE_MIN_LENGTH",
    "CredentialsError",
    "HydrateConfig",
    "JobAggregatorError",
    "JobRecord",
    "JobSource",
    "PluginConflictError",
    "PluginField",
    "PluginInfo",
    "SchemaVersionError",
    "ScrapeError",
    "SearchParams",
    "__version__",
    "build_envelope",
    "build_jsonl_lines",
    "classify_description_source",
    "get_plugin",
    "hydrate",
    "list_plugins",
    "make_enabled_sources",
    "normalize",
    "run_jobs",
    "scrape_description",
]
