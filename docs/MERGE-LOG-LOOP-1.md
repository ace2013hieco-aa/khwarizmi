# MERGE-LOG-LOOP-1 — deterministic context-assembly port + LOOP-0 probe inversion

## Provenance

| Item | Value |
| --- | --- |
| Task | LOOP-1-MERGE (merge gate only — no push) |
| Base (`main` before) | `b687b8bce5a0aaeb17cba1d9e17067de7414a7aa` |
| Slice (FF'd to) | `7202d08c64d624f7ac859dede8e2b0566343dd3c` |
| Slice commits | `d2e7ac4` (deterministic context-assembly port) + `b24a90b` (render payloads/review drafts into prompts) + `34a3685` (invert the LOOP-0 E1 probe) + `7202d08` (restamp 4452 -> 4463) |
| Branch | `slice/loop-1-assembler` |
| Merge worktree (gate runs + this log) | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/loop-1-merge-wt` |
| Merge method | **fast-forward** — `git merge --ff-only` in the main-bound house worktree |
| FF evidence | `merge-base(main, slice)` == `main`; `main..slice` = 4, `slice..main` = 0 |
| Rebase / merge commit / force | **none** — FF only, linear single-parent chain |
| Audit of record | `7cb00ac` — `AUDIT-LOOP-1-REDTEAM.md`, verdict **PASS 0 MUST-FIX / 0 SHOULD-FIX / 4 NOTEs** |

## Scope

6 files, +757/-11, **spine diff 0** (`git diff b687b8b..7202d08 -- src/hermes/research/gateway.py src/hermes/controller.py src/hermes/persistence/ src/hermes/events.py src/hermes/intents.py` is empty):

```
docs/SUITE-COUNT.md                    |   3 +-    (restamp 4452 -> 4463)
src/hermes/agents/runtime/__init__.py  |   2 +
src/hermes/agents/runtime/assembly.py  | 135 ++++  (new)
src/hermes/agents/runtime/run.py       |  33 +- 8
tests/test_loop0_e1_probe.py           | 320 ++++  (new, inverted)
tests/test_loop1_context_assembly.py   | 264 ++++  (new)
```

The slice adds a deterministic context-assembly port and wires it into the runtime's
model-request path, then inverts the LOOP-0 E1 characterisation probe to pin the fixed
behaviour. New `src/` imports are exactly one (`run.py` imports the new `assembly`
port); the port itself imports stdlib + `runtime.types` + `security.boundaries` only
(machine-checked by the purity test). No gateway / controller / persistence / events /
intents surface moved.

Stamp delta is self-consistent: base `Collected: 4452` -> landed `Collected: 4463` =
**+11** = +8 (`test_loop1_context_assembly.py`) + +3 (`test_loop0_e1_probe.py`).

## HARD RULE — audit duty (carried, not adjudicated)

A PASS audit already exists on this exact range (`7cb00ac`, AUDIT-LOOP-1-REDTEAM, on
`audit/loop-1-redteam`). Per the HARD RULE this gate does not re-adjudicate it; it is
carried and independently spot-confirmed:

| Audit claim | This gate's re-derivation |
| --- | --- |
| Verdict PASS 0/0/4 | carried as recorded |
| Injection BLOCKED (privileged slots byte-identical under a hostile payload; `applier_calls=0`) | carried; the pinning assertions are inside the landed `11/11` re-run below |
| 4 NOTEs (N1-N4) | carried verbatim (below) |
| Spine diff 0 | re-derived live: empty |
| Stamp 4452 -> 4463 | re-derived live: `--check` OK 4463 |

### The 4 NOTEs (carried, no fix required)

- **N1 — injectable-port precondition documented-not-enforced.** `assembly.py:51-58`:
  any caller may inject its own `ContextAssembler`; determinism is a stated precondition,
  not a runtime check. Accepted: enforcement is a design decision; the shipped defaults
  are purity-pinned.
- **N2 — no assembly size cap; router pre-flight is the backstop.** Only review bodies
  are capped (`MAX_PAYLOAD_BYTES` -> explicit `payload_omitted_bytes`); payload envelopes
  are uncapped by count. Accepted: W3 pre-flight / claim limits upstream remain the bound.
- **N3 — ordinary delegation children still get the spec digest.** `_delegate_one` keeps
  `digest_of(child_payload)` with origin `runtime.delegation` for non-review children;
  only the review child gets `proposal_envelopes`. Accepted: in E1/G4 scope, explicitly
  future work.
- **N4 — tick marker appended post-assembler.** `_model_request` appends the
  `runtime.tick` marker after the assembler output (loop state, not context). Accepted
  and pinned by the injected-assembler test (`prompt[-1]` is the tick).

## Gates (raw, on the landed tip `7202d08`, `PYTHONPATH=<wt>/src`, no extra `-q`)

Interpreter for every gate below:
`C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/loop-1-merge-wt/.venv/Scripts/python.exe`
(a directory junction to the repo venv; **Test-Path: True** for both the repo venv
`D:/New folder/research-agent/.venv/Scripts/python.exe` and the junction, identical
SHA-256 `22D89D728C105376D48ECD425EBA826C05F713A9962805B9B39924664A203076`;
Python 3.14.1, pytest 9.1.1, pyright 1.1.414, ruff 0.16.10).

- **Collect** (`scripts/run_tests.py --collect-only`) -> `4463 tests collected in 7.67s` (== 4463).
- **Stamp `--check`** (`scripts/stamp_suite_count.py --check`) ->
  `OK: docs\SUITE-COUNT.md collected=4463 matches the live collect` (exit 0).
- **Probe + assembly** (`scripts/run_tests.py tests/test_loop0_e1_probe.py tests/test_loop1_context_assembly.py`)
  -> `11 passed in 0.50s` (**11/11**).
- **B4** (`scripts/run_tests.py tests/test_b4_ref_graphs.py`) -> `24 passed in 8.82s`
  = **24/24**; fixtures byte-identical (`git diff -- docs/gr3-b4/` empty).
- **Census** (`scripts/check_census.py`) -> `PASS - every certified figure is reproduced exactly.`
  (121 transaction-control calls; owners 18/5/4 = 27; rollback-only 1;
  persistence->research imports 15; outside 0).
- **Ruff** (`python -m ruff check src tests`) -> `All checks passed!` (exit 0).
- **Pyright src** (`python -m pyright src --pythonpath "<venv python>"`) ->
  `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests-config**, two recordings:
  1. (a) `python -m pyright --pythonpath "<venv python>" --project pyrightconfig.tests.json`
     -> `108 errors, 1 warning, 0 informations` (exit 1). All 108 are
     `reportMissingImports` on `Import "pytest"`; `--pythonpath` does not resolve
     `pytest` in this environment.
  2. (b) with the venv made discoverable to pyright (`venvPath`/`venv`, via the `.venv`
     junction; probe config not committed) -> `0 errors, 1 warning, 0 informations`
     (exit 0), the only warning being the pre-existing
     `tests/test_research_program.py:144 reportSelfClsParameterName`.
     (b) is the recorded standard: **0 errors** on the tests project.
- **Full suite** (`scripts/run_tests.py tests --tb=short -rf`, idle machine) ->
  `5 failed, 4455 passed, 3 skipped, 1 warning in 736.93s (0:12:16)`.
  Pass + skip + failed = 4455 + 3 + 5 = **4463** == collect.

## Red set: EXACTLY baseline-5 (not a superset)

```
tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

Environmental races / Windows symlink privilege — flaky by nature, unchanged from the
documented baseline. **Delta = 0.** The documented `eval_plane` timing flake
(`tests/test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree`)
**did not fire**, so no isolation proof was required.

## NOT-list scan: PASS (no functional coupling)

Binding rule: the four terms bar DOING WORK in those domains; clearance prose asserting
absence is NOT a hit; only functional coupling stops the gate. The canonical four:
`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy` (external engines, per
`docs/ARCHITECTURE.md`).

- Range diff (`git diff b687b8b..7202d08`), word-boundary, case-insensitive -> **0 hits**.
- Whole landed tree
  (`git grep -inE "backtest_audit|optimize-my-strategy|\bSDA\b|\bTSE\b" 7202d08 -- src tests`)
  -> **0 hits**.

**No hit = no functional coupling. Scan PASSES; no STOP.** (The audit's own additional
scope scan of `apply_intent` / `sqlite3` / `persistence`/`research` / decided-by-model
transition kinds likewise found prose-only references; the landed `src/` production
modules import stdlib + `runtime.types` + `security.boundaries` and the new `assembly`
port only, purity-test enforced.)

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits, range + tree |
| `main` moved before the FF | **PASS** — re-verified unmoved at `b687b8b` (local == `origin/main` == `ls-remote`) immediately pre-FF |
| FF-ability | **PASS** — `merge-base(main, slice)` == `main`; `--ff-only` used, exit 0; `slice..main` = 0 |
| dirty main-bound worktree | **PASS** — house worktree clean pre-FF and FF'd in place; clean post-FF |
| red set superset of baseline-5 | **PASS** — exactly the 5, delta 0 |
| `--check` drift | **PASS** — collected 4463 == stamp |
| FAIL audit on the landing range | **PASS** — none; `7cb00ac` is PASS 0/0/4 |
| stale main-bound worktree left behind | **PASS** — house worktree clean at the final tip |
| push without a human hash-pin | **none performed** |

## Worktree hygiene

- **House main-bound worktree** (`C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt`,
  the arrangement carried from prior gates): bound to `main@b687b8b` and clean -> FF'd
  **in place** to `7202d08` (the slice landing) -> then FF'd in place again to this log
  commit -> ends bound to `main` at the final tip, clean.
- **`loop-1-merge-wt`** (this gate's worktree): detached at the landed tip `7202d08`;
  every gate ran here; this log was authored and committed here, then FF'd onto `main`.
- `slice/loop-1-assembler` worktree (`loop-1-wt`) and `audit/loop-1-redteam` worktree
  (`loop-1-audit-wt`) left as found. The shared checkout, `.hermes/`, `or*.json`, and
  other worktrees were not touched.

## Dual push plans — drafted, NOT executed (D8/D9)

No push was performed by this gate. Both plans require a human hash-pin.

1. **`origin` plain-push** (`https://github.com/ace2013hieco-aa/khwarizmi-research`):
   push `<merge-gate-tip>:refs/heads/main`, single refspec, no force, no tags, after
   re-verifying live `origin/main` is a strict ancestor of the tip (FF).
2. **public mirror orphan-sync** (`https://github.com/ace2013hieco-aa/khwarizmi`):
   add a temp remote, `fetch --no-tags`, re-read the live mirror pin, build a sync commit
   whose tree is `<tip>^{tree}` and whose parent is the mirror HEAD (orphan convention —
   `merge-base` must be empty), push exact-hash with **no force** (rule #5), then remove
   the temp remote. Mirror HEAD is a moving target: always re-run `ls-remote` immediately
   before the sync.

## Verdict

### A — LOOP-1 MERGED (LOCAL-ONLY)

`main` FF'd `b687b8bce5a0aaeb17cba1d9e17067de7414a7aa` ->
`7202d08c64d624f7ac859dede8e2b0566343dd3c`; this log commits on top. The deterministic
context-assembly port and the LOOP-0 probe inversion are landed; the spine is untouched.
No push executed.

License: Apache-2.0 (LICENSE).
