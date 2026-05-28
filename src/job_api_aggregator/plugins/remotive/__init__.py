"""job_aggregator.plugins.remotive — Remotive remote-jobs source plugin.

Exports :class:`Plugin` as the single public name so the entry-point
loader and consumers can use a consistent import path::

    from job_aggregator.plugins.remotive import Plugin
"""

from job_aggregator.plugins.remotive.plugin import RemotivePlugin as Plugin

__all__ = ["Plugin"]
