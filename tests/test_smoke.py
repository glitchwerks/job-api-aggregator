"""Smoke tests for the job_api_aggregator package.

These are placeholder tests that verify the package installs
correctly and exposes the minimum expected public surface.
Real functional tests are added with each subsequent issue.
"""


def test_package_imports() -> None:
    """Verify the package imports cleanly and exposes a version string.

    This test exists to catch installation failures (missing
    pyproject.toml metadata, broken __init__, or missing
    importlib.metadata entry) before any functional code is written.
    """
    import job_api_aggregator

    assert isinstance(job_api_aggregator.__version__, str), "__version__ must be a string"
    assert job_api_aggregator.__version__, "__version__ must be a non-empty string"
