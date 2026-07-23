"""Test utilities and fixtures for apc_operations.

This module hosts the `before_test` hook entry point referenced from
`hooks.py` (`before_tests` setting). Used to seed any global test data.
"""


def before_test():
    """Run once before the test suite executes.

    Currently a no-op; per-test fixtures are defined inside each test
    module (see e.g. ``apc_operations/shipping/doctype/job_order/test_job_order.py``).
    """
    return None
