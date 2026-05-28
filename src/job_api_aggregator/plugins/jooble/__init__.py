"""Jooble job-source plugin for job-aggregator.

Exports the single :class:`Plugin` class that the entry-point loader
discovers via ``job_api_aggregator.plugins`` group in ``pyproject.toml``.
"""

from job_api_aggregator.plugins.jooble.plugin import Plugin

__all__ = ["Plugin"]
