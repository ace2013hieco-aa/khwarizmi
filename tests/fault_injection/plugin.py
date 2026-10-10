"""The harness's pytest plugin: apply the selected kills, scoped, opt-in.

Load it explicitly (it is deliberately NOT wired into ``tests/conftest.py``,
which another change is rewriting, and it must never load implicitly):

    HERMES_FAULT_KILL=quarantine python -m pytest \
        -p tests.fault_injection.plugin tests/test_p_auto_6_loop.py
    # -> 3 failed, 3 passed   (the envelope claims go red)

    HERMES_FAULT_KILL=deadline python -m pytest \
        -p tests.fault_injection.plugin tests/test_p_auto_6_loop.py
    # -> 1 failed, 5 passed

    HERMES_FAULT_KILL=all python -m pytest -p tests.fault_injection.plugin tests
    # -> the same 3 + 1 red, everything else green (kills are file-scoped)

Without ``HERMES_FAULT_KILL`` the plugin is inert: every hook below is one
dict lookup and nothing is patched. An unknown name refuses the session before
a single test runs (``UNKNOWN_FAULT_KILL``), never a silent typo.
"""
from __future__ import annotations

import pytest

from tests.fault_injection import kills


def pytest_configure(config: pytest.Config) -> None:
    """Validate the opt-in selection loudly (no-op when unset)."""
    kills.selected()


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Apply the selected kills while a scoped test runs."""
    kills.begin(item.nodeid)


def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:
    """Undo whatever ``pytest_runtest_setup`` applied."""
    kills.end()
