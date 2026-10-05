#!/usr/bin/env bash
# Run the full Hermes suite under a dedicated Python 3.14 venv, sidestepping
# any stale/broken project `.venv` (e.g. one left on 3.11 whose dist-info is
# locked and makes `uv sync` fail). CI (.github/workflows/ci.yml) already runs
# the suite on Python 3.14 for every commit — this is the LOCAL equivalent, so
# the 3.11-vs-3.14 interpreter trap can never bite a developer machine.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv-py314"

# Locate a Python >= 3.14 interpreter: uv-managed, then on-PATH, then the
# standard Windows install location (often not on PATH).
PY_BIN=""
candidates=()
if command -v uv >/dev/null 2>&1; then
  candidates+=("$(uv python find 3.14 2>/dev/null || true)")
fi
candidates+=("$(command -v python3.14 || true)" "$(command -v python || true)")
candidates+=("$LOCALAPPDATA/Programs/Python/Python314/python.exe")
for c in "${candidates[@]}"; do
  [ -n "$c" ] && [ -x "$c" ] || continue
  if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)' \
      >/dev/null 2>&1; then
    PY_BIN="${c//\//}"
    break
  fi
done
if [ -z "$PY_BIN" ]; then
  echo "error: no Python >= 3.14 found; run 'uv python install 3.14' first" >&2
  exit 1
fi

if [ ! -x "$VENV/Scripts/python.exe" ] && [ ! -x "$VENV/bin/python" ]; then
  echo "creating Python 3.14 venv at $VENV"
  if command -v uv >/dev/null 2>&1; then
    uv venv --python "$PY_BIN" "$VENV" >/dev/null
  else
    "$PY_BIN" -m venv "$VENV"
  fi
fi
PYEXE="$VENV/Scripts/python.exe"
[ -x "$PYEXE" ] || PYEXE="$VENV/bin/python"

# Install only when the editable package is missing — the editable install
# always reflects src/, so re-running `uv pip install -e .` on every call
# would churn the dist-info (and can trip a transient Windows file lock,
# the same "Access is denied" that broke the original .venv).
if ! "$PYEXE" -c "import hermes" >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$PYEXE" -e . pytest >/dev/null
  else
    "$PYEXE" -m pip install --quiet -e . pytest
  fi
fi

cd "$ROOT"
exec "$PYEXE" -m pytest "$@"
