"""Arbeitnow job-board plugin for job-aggregator.

Exports :class:`Plugin` as the entry-point target registered under
``job_api_aggregator.plugins`` → ``arbeitnow``.
"""

from job_api_aggregator.plugins.arbeitnow.plugin import Plugin

__all__ = ["Plugin"]
