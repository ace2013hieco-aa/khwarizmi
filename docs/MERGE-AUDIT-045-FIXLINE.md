# MERGE-AUDIT-045-FIXLINE — adversarial audit of `merge/idr045-fixline@f475ef0`

Role: Adversary, fresh independent session. Method: falsify, do not confirm.
Branch: `merge/audit-fixline` from `f475ef0`. Local-only. No push.
Scope: read-only except this file. No `src/`, `tests/`, or other `docs/` edits.

## Inputs receipt (all readable, no STOP)

- `merge/idr045-fixline@f475ef0` full tree (merge `c5aacd9` + log `f475ef0`) — read from the repo.
- `docs/MERGE-LOG-045-FIXLINE.md` at `f475ef0` — read; its gate table is the claim under test, not evidence.
- Prior audits: `84665d2` (merge/audit-045 FAIL), `ea075b3` (fix audit PASS WITH CONDITIONS), `e4444f4` (C1b ruling: provenance echo total) — read; their assertions are the re-probe targets.
- `main@c2c8fa9` (`origin/main` identical) — read as baseline.

## Isolation and import proof (STOP avoided)

All execution ran in a dedicated detached worktree
(`%LOCALAPPDATA%\Temp\opencode\audit-fixline`, pinned at `f475ef0`) with
`PYTHONPATH` set to that worktree's `src`. Proof recorded before any probe:
`hermes.__file__` resolves to `...\audit-fixline\src\hermes\__init__.py`, and it
is the only `audit-fixline` entry on `sys.path`. Probe scripts live in system
temp, never in the repo. A second scratch worktree (`fixline-replay`, at
`c2c8fa9`, since left detached and untouched) served the mechanical replay.
No other session's branch, worktree, or checkout was entered or modified.

## Verdict: PASS

All six attack lines executed. Nothing falsified. One methodology note (not a
product condition): the full-suite re-run in the isolated worktree exited 0
with 2304 progress dots and 0 failure/error markers, but pytest did not print
its final summary line — the same host teardown quirk previously recorded
against this machine. Coverage for that gap: the targeted 5-file re-run in the
same worktree prints its summary normally (`136 passed`), and the canonical
full summary (`2304 passed`) from the merge run is cited below as corroboration
with its provenance stated, not as this audit's evidence.

## 1. C1/C1b re-probes — executed, all hold

Five independent probes (own script, `bypass_intent` via `object.__new__` plus a
true post-construction `object.__setattr__` case), all against the worktree:

- P1 non-str `origin_ref=12345` → `MALFORMED_PAYLOAD`, 0 task rows, exactly one
  `IntentRejected`; payload omits the value with marker
  `origin_ref=<omitted non-str int>`; payload bytes within the cap.
- P2 oversized `origin_ref="x"*5000` → `MALFORMED_PAYLOAD` ("exceeds max length
  64"), task/event counts 0/0/1, echo clamped to 64 chars with
  `provenance_bounded == ['origin_ref=<truncated 5000->64>']`, payload bounded.
- P3 post-construction assignment of a 5000-char `origin_ref` onto a validly
  constructed intent (the exact C1b shape) → `MALFORMED_PAYLOAD`, 0 rows, one
  `IntentRejected`, clamped echo with the truncation marker, payload bounded.
- P4 sized-but-unserialisable, bare `object()`, dict, list → four
  `MALFORMED_PAYLOAD` refusals, zero bare `TypeError` escapes, four
  `IntentRejected` rows, all payloads bounded.
- P5 in-bounds control → applied with one `IntentApplied`, echo verbatim, and
  NO `provenance_bounded` key (the default path is byte-identical).

The F2 signature (durable row, no `IntentApplied`, raw error to the caller) was
not reproducible on any route. The C1b totality claim holds: refusal journaling
cannot fail on the values it reports.

## 2. Merge fidelity — zero-resolution claim holds

Independent mechanical replay: fresh detached worktree at `c2c8fa9`,
`git merge --no-ff e4444f4` → exit 0, resulting tree `f46091ce…`, identical to
both the integrand tip tree and the `c5aacd9` merge tree; `git ls-files -u`
empty; no conflict markers. The placeholder move reported in the log was a
tree-level collision of two 0-byte untracked files, verified empty before the
move — no semantic content existed to choose between, so there was no semantic
conflict to adjudicate and none was hidden. Changed-file list (resolutions
only): none, confirmed.

## 3. Cross-line interactions — no inversion found

- Intent fields × validators/repositories: one limits table
  (`_PROVENANCE_FIELD_LIMITS`, `gateway.py:126-133`; `origin_ref` cap 64),
  enforced at construction (`intents.py:204-225`), at the gateway boundary
  pre-write (`gateway.py:210-225`, type-before-length), and made total at the
  journal builder (`gateway.py:4209-4225`). Direct-SQL sweep of `controller.py`
  shows only task-status transitions, lease-fence operations, and the ladder
  APPLY's own `evidence_ladder_state` insert — no admission-path write bypasses
  `apply_intent` (ADMIT_TASK admitted through the gateway at `:4185-4195`).
- Pass × ladder/dispatch/tick: `tick()` acquires the lease first (`:526`),
  then runs plan admission (`:606`), ladder APPLY (`:611`), regime proposals,
  then dispatch — admission before ladder before dispatch, matching the IDR.
  The F3 marker is present in-tree (`_expected_gates` deliberately unused,
  `:4149-4154`); the repository write path independently checks BOTH derived
  requirement sets (`repositories.py:1376-1384`), which narrows F3's exposure to
  hand-written rows exactly as the carry-forward states.

## 4. Gate integrity — re-run in the isolated tree

| Gate (worktree, import proof above) | Raw output |
|---|---|
| Full suite (`pytest tests -q`) | exit 0, 2304 dots, 0 `F`/`E` markers; summary line absent (quirk disclosed above) |
| Targeted: idr045 plan-admission (26) + merge-audit-045 (20) + merge-audit-045-c1 (37) + task_plan (12) + gateway (41) | `136 passed in 1.58s` with summary, rootdir = worktree |
| `ruff check src tests` | `All checks passed!` |
| `pyright src` | `0 errors, 0 warnings, 0 informations` |
| `pyright` tests project | `0 errors, 1 warning` — `test_research_program.py:144` pre-existing (file empty-diff vs `c2c8fa9`) |
| `check_census.py` | `PASS` — 121/121, 18/18, 5/5, 4/4, 27/27, 1/1, 15/15, 0/0 |

Corroboration (trusted, not mine): the merge run's canonical full summary
`2304 passed in 418.99s` agrees exactly with this audit's dot count. The
`run_tests.py` wrapper was not used in the worktree because it keys `.venv` to
its own checkout; direct `pytest` with the proven `PYTHONPATH` ran the identical
collection (`testpaths=tests`, repo `pyproject.toml`).

## 5. F3/F4 carry-forward — honest and findable

Both items are stated open in the log AND in-tree at `docs/idr/IDR-045.md:97`
(F3 known gap), `:371-372` (F4 corrected-not-refactored; F3 open recorded),
`:92` (F4 correction). Verified against code: the `_expected_gates` marker at
`controller.py:4149-4154` and the production inline filtered-head query at
`:4115` (`AND parent_program_id IS NULL ORDER BY version DESC LIMIT 1`) match
the record exactly. Nothing silently closed.

## 6. S6 / DG-5 / single mutation path — mainline reading holds

- S6: 4 KiB cap at schema `CHECK` (`migrations.py:137`) and
  `validate_payload_size` (`event_validation.py:23,74`); the post-commit audit
  wrapper (`:142-150`) is the pre-existing hazard class the log names, and the
  C1b clamp keeps refusal echoes inside it (P2 payload bounded; ruling probe
  252 bytes). Reading accurate.
- DG-5: census re-run in the worktree reproduces persistence→research imports
  15/15 — intentional architecture intact on the merged tree.
- Single mutation path: admission flows through `apply_intent`; no durable
  write around it on the integrated line. Reading accurate.

## Post-audit integrity checks

| Check | Result |
|---|---|
| This branch | `merge/audit-fixline` from `f475ef0`; one commit (this file) to follow |
| `main` / `origin/main` / `merge/fix045-c1b` | `c2c8fa9` / `c2c8fa9` / `e4444f4`, all unchanged |
| Pushes | none — new branch has no upstream; no push ran anywhere |
| Other sessions' work | untouched; work confined to the new branch, system-temp probes, and two new detached worktrees |
| Forbidden topics | re-scan of `c2c8fa9..e4444f4`: 5 hits, all audit-scan boilerplate, zero coupling — reported, not triggered |
