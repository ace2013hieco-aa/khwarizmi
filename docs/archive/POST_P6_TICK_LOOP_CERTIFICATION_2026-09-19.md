# Post-P6 Tick-Loop Certification — 2026-09-19

## 1. Repository identity

- `ace2013hieco-aa/khwarizmi-research`, branch `main`,
  `HEAD == origin/main == 14fc64a` (post-fetch verified).
- Tree clean: no tracked modifications (untracked only: pre-existing
  `.freebuff/`, `IDEA.md`, plus uncommitted certification reports —
  this task creates files only, commits nothing).
- `633cff1` is an ancestor of HEAD.

## 2. Exact tick-loop commit ancestry

- `633cff1` "wire contradiction detector into the ACTIVE reconcile loop"
  (2026-09-19): `src/hermes/research/controller.py` +111/−46,
  `tests/test_chg1_contradictions.py` +34 (`TestTickWiring::
  test_tick_detects_conflict`).
- `2328399` "surface contradiction-detection diagnostic in loop notes":
  `controller.py` +3 (success-count note).
- `14fc64a`: docs-only N9 merge-certification report (no code).

## 3. Change-surface map

| Change | Class |
|---|---|
| `tick()` invokes `_detect_contradictions_pass()` every ACTIVE tick (`controller.py:567-574`) | (1) production loop behavior |
| Lease-wrapper split: `detect_contradictions` acquires/releases (`:1884-1897`); lock-less core `_detect_contradictions_pass` (`:1899+`) runs on the tick's held lease/fence | (1) + (2) contradiction interaction |
| RECORD_CONTRADICTION admission through `apply_intent` on `self._fenced`; `DETERMINISTIC` role; no credential; refusal-as-data | (2), unchanged semantics |
| Failure note (`:1926`) + success-counts note (`:1961-1963`); read-only `notes` property (`:475-480`) consumed by CLI/digest | (4) diagnostic only |
| `TestTickWiring::test_tick_detects_conflict` | (5) test only |
| Classification handling, providers, journal vocabulary, N1, S5 | (6) unrelated — untouched |

Old behavior: detector reachable only via standalone `detect_contradictions()`
(no `tick()` caller). New: fires every ACTIVE tick before
requeue/dispatch; standalone path preserved with identical body.

## 4. Architectural contract (recovered)

- Tick cause: external/scheduler call to `tick()` / `run(max_ticks=1000)`
  (`controller.py:482,597`); `run` loops until idle (`:612`).
- Inspects (authoritative committed state): mode, recovery/heartbeat
  state, ladder facts, digest-valid classifications, task eligibility.
- May mutate — durable: task statuses, source/classification/con-
  tradiction/ladder rows; journal: status/contradiction/ladder/task
  events; derived: rankings, candidate rows; diagnostic: `_notes`
  (in-memory only).
- Must never: duplicate transitions (idempotent intents + duplicate
  returns); unauthorized mutation (lease + `internal_only` roles);
  unjournaled durable mutation (all writes via `apply_intent` +
  events); reopen RESOLVED/SUPERSEDED (status-guarded updates);
  bypass N9 (predicate in derivation + validator); cross projects
  (`project_id` scoping throughout); live provider activity
  (transport boundary untouched); nondeterminism (pure detector +
  content identity).

## 5. Control-flow trace

`tick()` (`:482-595`): `_acquire_lock` → fail = `idle="lock_held"` (`:490`);
recovery pass every mode (`:505`); parked-gate diagnostics (`:510`);
AWAITING_HUMAN self-heal both directions (`:512-555`, fail-closed notes);
non-ACTIVE → idle (`:556-560`, **detection skipped while parked**);
ladder pass (`:565`); `_detect_contradictions_pass()` (`:574`);
requeue/re-execute (`:578-579`); dispatch (`:581`); `finally:
_release_lock` (`:594`); `LockLostError` → `idle="lock_lost"` (`:588`).
Pass (`:1899+`): candidate rows (N9-filtered) → pure N1 → one
`RECORD_CONTRADICTION` intent per candidate via `apply_intent(
self._fenced, …)` → recorded/duplicates/refused tallies; detector
exception → `DETECTOR` refusal, zero writes. Choke points: lease,
ACTIVE gate, gateway validator (N1+N9, in-tx re-resolution),
SQLite single-writer, fenced connection (lock-validated writes).

## 6. Determinism

T1 (same state + repeated tick): exactly 1 `ContradictionDetected`,
1 cx row across ticks. Rebuild-identical IDs proven in P7 re-run
(`fc_1473…`/`fc_5410…`/`cx_8bd1…`); cross-run identical
(`fc_cdfb…`/`fc_f406…`/`cx_244a…` reproduced on mainline);
cross-baseline identical (same IDs at `ff79bb6` and `14fc64a`).
Source of determinism: pure `detect_classification_conflicts` +
content-hash identity + deterministic ordering; no clock/random in
the pass (timestamps come from the injected clock).

## 7. Idempotency

T2: tick records once (`OPEN`), re-tick → duplicate path, still 1 row.
T9: two ticks → exactly 1 detection event, 1 row (duplicate admissions
carry only the pre-existing `IntentApplied` audit row, no semantic
state). T8: corrupt classification row skipped, pair still detected,
tick never raises. `run()` terminates (idle break + `max_ticks` cap).

## 8. Contradiction interaction

OPEN: tick retains exactly 1 OPEN row; HR-08 choke unchanged (P7 S8
re-proven on mainline). RESOLVED (T3): re-ticks add no detection,
status stable. SUPERSEDED (N9-B re-run): re-ticks add nothing.
Post-retraction fresh pair: write-refused + `recorded: []` (N9).
Re-review seeding `reached_via="contradiction"` intact (P7 S12 re-run).
Parked ticks (T7b genuine `WAITING_HUMAN` gate): `idle`
`mode:AWAITING_HUMAN`, 0 contradictions — detection is ACTIVE-only by
construction. Stale-mode self-heal (T7a) re-derives ACTIVE first, then
detection fires — pre-existing AUDIT behavior, ordering documented.

## 9. Authority boundary

T2: loop creates zero `HumanDecisionReceived` events. Resolution/
verdict/credential paths untouched by the wiring (no new intent kinds,
no role changes; `CONTRADICTION_RESOLUTION` still internal-only +
human-verdict-bound, P7 S9 re-proven). The pass admits derived state
only; governance transitions remain operator-gated.

## 10. Mutation-path analysis

Detection mutations flow exclusively through `apply_intent(
self._fenced, RECORD_CONTRADICTION)` (`controller.py` pass body) into
the gateway validator (N1+N9, own `BEGIN IMMEDIATE`). Dispatch mutations
flow through handler/repository boundaries (pre-existing). No direct
`INSERT/UPDATE` on durable tables in the new code (only `SELECT`
predicate reads + `_notes.append`); no direct journal writes (events
only via `_append_event_to_db` inside gateway/repository
transactions). Single `apply_intent` boundary preserved.

## 11. Concurrency/lease analysis

T6: lock held by another controller → `idle="lock_held"`, zero writes,
pair undetected until lease free. Same-lease execution inside tick
(the wrapper/core split exists precisely so the pass never deletes
the tick's own lock row). SQLite `BEGIN IMMEDIATE` serializes writers
(busy fails closed, never torn). `LockLostError` mid-tick → `idle=
"lock_lost"`, authoritative writes already failed closed + rolled
back. Existing `test_concurrency.py` green in the full run. No new
locking introduced or needed.

## 12. Project isolation

T5: p1 tick leaves p2 event count stable, 0 p2 contradiction rows.
Detection, candidate derivation, validator, and intents are all
`project_id`-scoped; N9 predicate project-filters on the decision
row (P7 N5/N9-D re-proven on mainline).

## 13. Journal/replay integrity

Tick-sequence replay reproduces terminal state (T1/T2/T9 stable
counts/rows/IDs). Every durable tick effect carries an event
(detection → `ContradictionDetected` + `IntentApplied` audit;
exactly-once detection proven). No unjournaled durable mutation
introduced. Provider replay determinism re-proven on mainline
(identical hashes + IDs, 0 live contacts).

## 14. Failure/refusal semantics

Detector exception → `DETECTOR` refusal, zero writes (code path
`:1921-1926`). Gateway refusals surface as `refused[]` data, loop
never raises (T8 + `test_tick_detects_conflict` healthy-tick
assertion). Corrupt rows skipped. Stale/locked ticks idle cleanly.
Oversized rationale refused pre-write (`RATIONALE`) per existing
`test_controller.py:1010,2972`, `test_s6a_retraction_ingestion.py:496`
(green). Refusals write nothing semantic; re-ticks deterministic.

## 15. Boundedness

`_notes` grows in-memory per tick (bounded by `max_ticks=1000` ×
short strings; non-persisted, read-only property). Journal growth per
idle re-tick is at most the pre-existing `IntentApplied` audit row
for duplicate admissions — no semantic duplication, archive-not-
delete preserved. No unbounded payloads (IDs/hashes only), retries
(retry policy pre-existing), recursion, or queue growth introduced.
4 KiB event discipline untouched (no payload-shape changes).

## 16. Test matrix

Tick-loop suites fresh on this tree, 383/383: `test_controller.py`,
`test_chg1_contradictions.py` (incl. `TestTickWiring::
test_tick_detects_conflict`), `test_controller_q02/q04/c4`,
`test_provider_orchestration.py`, `test_walking_skeleton.py`,
`test_cli.py`, `test_n9_retraction_admission.py`,
`test_p6_classification.py`, `test_hr08_completion_invariant.py` —
0 failed, 0 errors, 0 skipped. Full suite: **2035/2035, 0/0/0**.
Probes T1–T11 (+T7a): all pass (evidence `Temp/opencode/
tick_evidence.jsonl`).

## 17. Adversarial results

1. duplicate tick → 1 detection, 1 row. 2. stale tick → `lock_held`,
zero writes. 3. tick after COMPLETED lifecycle (T11: walked to
REPORTING, HR-08-completed, re-ticked) → stable, no new detection.
4. tick during OPEN → 1 OPEN row retained. 5. after resolution →
RESOLVED, stable. 6. after retraction → no resurrection (RESOLVED
stays; SUPERSEDED stays). 7. cross-project → p2 untouched.
8. concurrent → `lock_held` (+ `test_concurrency.py` green).
9. refusal retry → duplicates, no new state. 10. replayed ticks →
identical terminal state. 11. malformed/oversized → skip/refuse,
never raise (existing RATIONALE/MALFORMED tests green). 12. authority
escalation → zero `HumanDecisionReceived` from the loop; no verdict
surface reachable. No attack succeeded; nothing repaired (read-only
gate).

## 18. Static checks

`ruff check src tests`: clean. `pyright src`: 0 errors. Tests
profile: 0 errors + 1 pre-existing warning
(`test_research_program.py:141`, untouched). Tree: no tracked
modifications (this report file only, uncommitted).

## 19. Scope verification

Certified: tick-loop wiring only (`633cff1`, `2328399`). Explicitly
not certified/modified: STALE project-filter wart, ancestor
semantics, provider architecture, N1, N9 implementation, workflow/
agent/telemetry/signing abstractions, repo hygiene. P7/N9 behavior
re-proven as context, not redefined.

## 20. Final verdict

### A — TICK-LOOP CERTIFIED
