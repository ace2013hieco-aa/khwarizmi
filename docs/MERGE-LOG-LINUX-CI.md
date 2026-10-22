# MERGE-LOG-LINUX-CI — full `ubuntu-latest` coverage + fallback smoke (GAP-1 D9-A)

## Provenance

| Item | Value |
| --- | --- |
| Task | LINUX-CI-MERGE (merge gate; local FF — the push is bundled with the wave-2 fleet under one human D9 pin) |
| Base (`main` before) | `7d08c2e` (DECISION-PACKETS landing + its merge log) |
| Slice | `slice/linux-ci@c960cca`; restacked as `slice/linux-ci-final@050188d` (cherry-pick only; no restamp — no test-count change) |
| Landed tip (FF'd to) | `050188d9b222eb6f11bdf90d40d9283657b26649` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — bundled with the wave-2 fleet under one human D9 pin |

## Scope

```
.github/workflows/ci.yml | +115    (three new ubuntu-latest jobs; existing jobs byte-identical)
docs/LINUX-CI.md         |  +59    (slice note: posture + expected first-run risk profile)
docs/SUITE-COUNT.md      | unchanged 4929 (no tests added/removed)
```

No `src/` or `tests/` changes.

## What was certified

- **`linux` job** (ubuntu-latest, Python 3.14, same pinned action versions as
  the Windows jobs): `uv sync`; `PYTHONPATH=$GITHUB_WORKSPACE/src`;
  `.venv/bin/python scripts/stamp_suite_count.py --check`;
  `.venv/bin/python scripts/run_tests.py -v --cov=...`; coverage artifact
  `coverage-report-linux`. Mirrors the Windows `test` job exactly.
- **`linux-gates`**: `uvx pyright src`; `uvx pyright --pythonpath
  .venv/bin/python --project pyrightconfig.tests.json`; `uvx ruff check src
  tests` — mirrors the Windows `typecheck` + `lint` jobs.
- **`linux-smoke`**: `uv venv --python 3.14`; `uv sync`;
  `.venv/bin/python scripts/run_tests.py -q tests/test_walking_skeleton.py`;
  strict pyright + ruff — mirrors the Windows `local-gate` intent.
- **Fallback preserved**: every existing `windows-latest` job is untouched
  (byte-identical), triggers unchanged. Posture (recorded in the job comments
  and `docs/LINUX-CI.md`): Windows-specific baseline-red fallout is handled as
  FOLLOW-UP FIXES — never by weakening/skipping tests in this slice.

## Expected first-run risk profile (follow-up list, not fixes)

- `tests/test_eval_plane.py:192,1079,2046` — hardcoded `PYTHONPATH="src;."`
  (POSIX wants `:`); masked by the editable install, latent portability defect.
- `tests/test_p_auto_5_vault.py`, `tests/test_p_auto_5_fix.py` — symlink/
  hardlink planting is unprivileged on Linux, so real-link branches execute
  instead of Windows fallbacks (`skipif(os.name != "nt")` tests skip but stay
  collected).
- `tests/test_controller.py` — real-sleep lease/heartbeat races; likeliest
  runner-speed flake.
- `scripts/profiled_gate.sh` — hardcodes `.venv/Scripts/python.exe`; not
  invoked on Linux (porting is a follow-up; `linux-gates` mirrors its
  commands).

## Gates (raw)

Agent: YAML parses (`jobs: test, typecheck, local-gate, profiled-gate, lint,
audit, linux, linux-gates, linux-smoke`); walking skeleton **5 passed**; full
suite unchanged **4858 passed, 3 skipped** at its tip; ruff pass; pyright
0/0/0 + 0/1; NOT-list 0; no `src`/`tests` diff.

Director at landed tip `050188d`: YAML parse OK (9 jobs); stamp `--check` OK
**4929**; census PASS; B4 **24 passed**; ruff `All checks passed!`;
pyright src 0/0/0; NOT-list **0 hits** (word-boundary). These workflow files
cannot execute here; correctness is by diff review + parse, and the first
live Actions run is the follow-up evidence.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| existing Windows job semantics changed | **none** — appended jobs only |
| test weakened/skipped to make Linux pass | **none** — zero test edits |
| action-version inconsistency | **none** — copied from existing jobs |
| B4 governed corpora | **PASS** — 24/24; no governed-doc edits |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `7d08c2e` |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies CI coverage breadth. It makes no validity,
reproducibility, or admissibility claim; a green Linux job is a platform
smoke, not scientific evidence.

License: Apache-2.0 (LICENSE).
