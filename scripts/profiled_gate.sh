#!/usr/bin/env bash
# C3 — the profiled typecheck gate, reproducible locally in ONE command:
# pyright with the tests profile (pyrightconfig.tests.json — src + tests,
# untyped-fixture noise silenced, every other rule active) followed by the
# walking-skeleton smoke — the exact pair the CI `typecheck` + `local-gate`
# jobs enforce, so the gate can be verified on a developer machine before
# pushing. CI runs this script itself (the `profiled-gate` job).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/Scripts/python.exe ]; then
  echo "Project .venv missing — run: uv venv --python 3.14 && uv sync" >&2
  exit 1
fi

uvx pyright --pythonpath .venv/Scripts/python.exe --project pyrightconfig.tests.json
./scripts/test_py314.sh -q tests/test_walking_skeleton.py
echo "profiled typecheck + walking-skeleton smoke: OK"
