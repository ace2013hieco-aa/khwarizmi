"""Shared utilities for the Hermes core.

Timestamp helper — injectable clock for deterministic testing (IDR-011).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

# Type alias: a zero-argument callable returning a UTC ISO-8601 string.
Clock = Callable[[], str]


def utc_now() -> str:
    """Default clock: UTC ISO-8601 with microsecond precision (IDR-011).

    Format: ``YYYY-MM-DDTHH:MM:SS.ffffff+00:00``
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def frozen_clock(timestamp: str) -> Clock:
    """Return a clock that always yields ``timestamp`` (for deterministic tests).

    >>> clock = frozen_clock("2026-01-01T00:00:00.000000+00:00")
    >>> clock() == "2026-01-01T00:00:00.000000+00:00"
    True
    """
    return lambda: timestamp


def advancing_clock(start: str) -> Clock:
    """Return a clock that returns ``start`` then increments by 1 microsecond
    on each call. Useful for ordering events deterministically in tests."""
    base = datetime.fromisoformat(start)
    counter = [0]

    def _tick() -> str:
        ts = base + timedelta(microseconds=counter[0])
        counter[0] += 1
        return ts.isoformat(timespec="microseconds")

    return _tick
