"""Jobicy plugin for job-aggregator.

Exports the single :class:`Plugin` class that the entry-point loader
discovers via the ``job_aggregator.plugins`` group.
"""

from job_aggregator.plugins.jobicy.plugin import Plugin

__all__ = ["Plugin"]
