"""Plugin sub-packages for job-aggregator.

Each sub-package exposes a single ``Plugin`` class that subclasses
:class:`~job_aggregator.base.JobSource`.  Plugins are discovered at
runtime via the ``job_aggregator.plugins`` entry-point group defined
in ``pyproject.toml``.
"""
