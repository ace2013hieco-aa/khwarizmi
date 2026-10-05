"""Isolated pytest runner — scrubs the host Hermes venv from sys.path.

When khwarizmi-research is developed inside the Hermes desktop app, the app's
own venv (C:\\Users\\...\\hermes\\hermes-agent\\venv) leaks onto sys.path
before our project venv. Its `hypothesis` plugin is broken under Python 3.14
and crashes pytest at session teardown, even though all tests pass.

This runner removes any site-packages directory that doesn't belong to
our own venv before invoking pytest, so `python scripts/run_tests.py`
reproduces identically inside or outside the Hermes app.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Our venv's site-packages
our_venv = Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages"

# Strip any site-packages that isn't ours
scrubbed = []
for p in sys.path:
    if "site-packages" in p and p != str(our_venv):
        continue  # host venv leak — remove
    scrubbed.append(p)
sys.path = scrubbed

# Now invoke pytest
import pytest  # noqa: E402 — after the sys.path scrub above

raise SystemExit(pytest.main(sys.argv[1:]))
