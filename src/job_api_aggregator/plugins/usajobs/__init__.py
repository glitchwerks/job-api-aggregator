"""USAJobs plugin for job-api-aggregator.

Exposes :class:`Plugin` as the public entry-point for the entry-point
loader (``job_api_aggregator.plugins`` group).
"""

from job_api_aggregator.plugins.usajobs.plugin import Plugin

__all__ = ["Plugin"]
