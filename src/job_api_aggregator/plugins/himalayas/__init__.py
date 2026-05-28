"""Himalayas job-source plugin for job-aggregator.

Exports the single :class:`Plugin` name required by the
``job_aggregator.plugins`` entry-point contract.
"""

from job_aggregator.plugins.himalayas.plugin import Plugin

__all__ = ["Plugin"]
