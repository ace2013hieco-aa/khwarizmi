"""Isolated pytest runner — scrubs the host Hermes venv from sys.path.

When khwarizmi-research is developed inside the Hermes desktop app, the app's
own venv (``.../hermes/hermes-agent/venv``) leaks onto sys.path
before our project venv. Its `hypothesis` plugin is broken under Python 3.14
and crashes pytest at session teardown, even though all tests pass.

This runner removes any site-packages directory that doesn't belong to
our own venv before invoking pytest, so `python scripts/run_tests.py`
reproduces identically inside or outside the Hermes app.

Portability: "our own venv" is derived from the interpreter that is running
this script, never from a hardcoded layout. The previous spelling,
``<repo>/.venv/Lib/site-packages``, is the WINDOWS directory layout — on
POSIX the same venv lives at ``<repo>/.venv/lib/python3.14/site-packages``,
so the literal matched nothing, every entry counted as a foreign leak, and
the scrub stripped our OWN site-packages: ``import pytest`` then failed
before a single test was collected. ``sysconfig`` builds the path from
``sys.prefix`` with ``os.path`` and the running interpreter's version, so
one expression is correct on every platform.
"""
from __future__ import annotations

import os
import sys
import sysconfig

# Our venv's site-packages (== this interpreter's purelib: inside a venv,
# ``sys.prefix`` IS the venv root). Canonicalised so separator style, case
# (Windows) and symlinked venv paths still compare equal.
our_venv = os.path.normcase(os.path.realpath(sysconfig.get_paths()["purelib"]))

# Strip any site-packages that isn't ours
scrubbed = []
for p in sys.path:
    if "site-packages" in p and os.path.normcase(os.path.realpath(p)) != our_venv:
        continue  # host venv leak — remove
    scrubbed.append(p)
sys.path = scrubbed

# Now invoke pytest
import pytest  # noqa: E402 — after the sys.path scrub above

# Put THIS checkout's source first, and hand it to subprocesses too.
#
# The venv installs `hermes` editable against exactly one checkout. Before this
# block, a run from any other worktree imported that checkout's src — so the
# suite reported on a tree nobody was editing. Two shapes, both seen: the tree
# guard failed naming the other checkout, and TestCredentialGuardTeeth failed
# because the guard it neutralized in this tree was not the guard its subprocess
# ran (`python -m hermes.eval.platform_cli` resolved to the editable install).
#
# `src` first fixes the in-process import; PYTHONPATH fixes the children, which
# inherit the environment but not sys.path. On the checkout the venv points at,
# both are already true and this changes nothing.
_SRC = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src")
if os.path.isdir(_SRC):
    sys.path.insert(0, _SRC)
    _existing = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = (_SRC + (os.pathsep + _existing
                                        if _existing else ""))

raise SystemExit(pytest.main(sys.argv[1:]))
