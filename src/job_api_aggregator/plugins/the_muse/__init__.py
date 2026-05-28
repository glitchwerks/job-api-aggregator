"""The Muse job-source plugin for job-aggregator.

Exposes :class:`Plugin` as the single public symbol so the entry-point
loader and ``from job_aggregator.plugins.the_muse import Plugin`` both
resolve correctly.
"""

from job_aggregator.plugins.the_muse.plugin import Plugin

__all__ = ["Plugin"]
