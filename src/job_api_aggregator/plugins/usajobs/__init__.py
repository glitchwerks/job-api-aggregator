"""USAJobs plugin for job-aggregator.

Exposes :class:`Plugin` as the public entry-point for the entry-point
loader (``job_aggregator.plugins`` group).
"""

from job_aggregator.plugins.usajobs.plugin import Plugin

__all__ = ["Plugin"]
