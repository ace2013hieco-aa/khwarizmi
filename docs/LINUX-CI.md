# LINUX-CI — GAP-1 ruling D9-A slice note

Status: landed on `slice/linux-ci` (base `6e76fee`). Scope: `.github/workflows/ci.yml`
plus this note. No `src/` or `tests/` changes; no restamp (suite count unchanged).

## What landed

Three new `ubuntu-latest` jobs; every existing `windows-latest` job is
untouched and remains the fallback. Action versions are copied from the
existing jobs (checkout `v7.0.1`, setup-uv `v8.3.2`, upload-artifact
`v7.0.1`).

| Job | Command(s) | Mirrors |
| :--- | :--- | :--- |
| `linux` | `uv sync`; `PYTHONPATH=$GITHUB_WORKSPACE/src .venv/bin/python scripts/stamp_suite_count.py --check`; `.venv/bin/python scripts/run_tests.py -v --cov=hermes --cov-report=html:htmlcov --cov-report=term`; upload `coverage-report-linux` | Windows `test` |
| `linux-gates` | `uv sync`; `uvx pyright src`; `uvx pyright --pythonpath .venv/bin/python --project pyrightconfig.tests.json`; `uvx ruff check src tests` | Windows `typecheck` + `lint` |
| `linux-smoke` | `uv venv --python 3.14`; `uv sync`; `.venv/bin/python scripts/run_tests.py -q tests/test_walking_skeleton.py`; `uvx pyright src`; `uvx ruff check src tests` | Windows `local-gate` |

## Posture

Windows-specific baseline-red fallout in the portable suite is handled as
FOLLOW-UP FIXES. This slice never weakens, skips or edits a test to make
Linux pass; a red Linux job is evidence for a follow-up, not a reason to
loosen the gate. The Linux jobs are additive: the Windows jobs stay green
as the fallback, and `linux-smoke` keeps the cheapest onboarding path
observable even when the full Linux suite is red.

Coverage is kept (structurally identical to the Windows `test` job, only
the venv path and artifact name differ). `scripts/profiled_gate.sh` is not
invoked on Linux because it hardcodes `.venv/Scripts/python.exe`;
`linux-gates` mirrors its pyright invocation directly instead.

## Static first-run risk profile (reviewed, not guessed)

- `tests/test_eval_plane.py` — hardcoded `PYTHONPATH = "src;."` in three
  subprocess env fallbacks (lines ~192/1079/2046); POSIX needs `os.pathsep`
  (`:`, as `hermes/eval/matrix.py:225` already uses). Expected green because
  the synced venv's editable install makes the fallback unused, but this is
  a latent portability defect for the follow-up list.
- `tests/test_p_auto_5_vault.py`, `tests/test_p_auto_5_fix.py` — planted
  symlink (`symlink_to`) and hardlink (`os.link`) cases: unprivileged on
  Linux, so the real-link branches run instead of the Windows fallbacks.
  Two `skipif(os.name != "nt")` path-normalization tests skip on POSIX;
  they are still collected, so the stamped count (4861) is unchanged.
- `tests/test_controller.py` — real-sleep lease/heartbeat race tests
  (`time.sleep(0.3..0.8)`, 1–5 s joins) are timing-sensitive; a loaded
  `ubuntu-latest` runner is the likeliest non-portability flake.
- `scripts/test_py314.sh` is portable (it probes `Scripts` then `bin`);
  `scripts/profiled_gate.sh` is not (see above).
- Subprocess-heavy tests (`test_eval_plane.py`, `test_census_check.py`,
  `test_ranking_plane.py`, `test_agent_runtime.py`) use `sys.executable`
  and `os.pathsep`, except the `test_eval_plane.py` case above.

## Verification

YAML parse (PyYAML `safe_load`), `uvx ruff check src tests`,
`uvx pyright src` + tests profile, walking-skeleton smoke, full suite on
the slice tip; NOT-list scan over the slice diff. See the commit message
and the slice report for raw output.
