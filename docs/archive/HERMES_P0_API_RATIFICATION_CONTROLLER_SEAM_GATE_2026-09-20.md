# P0 — API Stability Ratification + Controller Seam Design Gate

## §0 Executive decision

Ratify the four-state convention with a meanings-frozen rule, and
approve DG-2 design on one basis: the ONLY green first extraction is
the detector row-derivation readers
(`_detector_candidate_rows:1967`, `_detector_resolve_ref:2025`,
`_open_contradiction_parties:825`); everything else is YELLOW
(requires per-seam design) or RED (lease/fence/tick/recovery).
Additionally: the dual retraction surfaces
(`record_source_retraction:836` raising vs
`record_source_retraction_decision:1725` returning data) must be
reconciled before any decomposition touches them.

## §1 Baseline

`HEAD == origin/main == 979311f`, branch `main`, tree clean except
known untracked (`IDEA.md`, external `orci/orhead/ortree.json`).
Chain verified: Phase 0/1/1.1/2/3 reports present;
`AGENTS.md`, `docs/{ARCHITECTURE,API,STATE,README}.md` read;
Phase 2 report read in full (A-05/E-01/E-02 confirmed P0,
A-05 precedes structural gates, decomposition requires DG-2).
Read-only gate: no source/test/config/doc modifications follow
(this report file excepted).

## §2 Certification-chain verification

P0 prerequisites hold as specified. No contradiction between
repository state and gate assumptions.

## §3 A-05 stability convention (ratified wording)

FROZEN (name + meaning, architecture decision + migration + gate
re-run to change): durable intent value strings; event names;
content-hash/identity formulas; idempotency-key derivations;
refusal-code meanings; journal append-order + ordering reads
(`ORDER BY event_id ASC`, `repositories.py:732-746`); replay
semantics; authorization partitions and accepted paths; adapter
required hooks. EVOLVING (PR-documented + tested; set may grow,
meanings frozen once emitted): CLI flags/outputs, Controller
method set, rejection-code set, optional hooks, fixture format,
read-surface shapes. INTERNAL (suite-green only): validators,
candidate derivation, L2 resolvers, migration internals, all
`_` methods, fence/lease mechanics, notes contents. UNDECLARED
(no promise; must not be treated as contract): repository direct
construction, `TickResult`/`notes` shapes, `__all__` beyond the
above, the 6 validator-less intents, `run(max_ticks)` tuning.
Package-level guarantee: NONE (no consumer exists; CLI is the
sole external surface).

## §4 Breaking-change classifications (verified)

Rename durable intent: FROZEN-break (journal + validators key on
strings). Change intent meaning with same string: FROZEN-break
(e.g. widening an internal_only kind's proposers bypasses
`gateway.py:175`; narrowing `llm_proposable` silently
disenfranchises declarants). Add optional intent field: FROZEN-break
unless explicitly ignored by all readers (payload schemas are
exact-key validated, e.g. `RETRACT_SOURCE` keys
`gateway.py:923`). Rename durable event: FROZEN-break (history +
readers). Alter event semantics: FROZEN-break (same name, new
obligations on readers). Change refusal code: FROZEN-break
(certified meanings, pinned tests). Reword detail text: allowed
(human layer; `reason` is free text in `GatewayRejection`,
`gateway.py:205`). Change canonical hash: FROZEN-break (dedup,
replay, idempotency, journal identity all keyed on it; e.g.
`fixture_id_of` deliberately EXCLUDES adapter version,
`replay.py:102-115` — reversing that inclusion silently forks
corpora). Change idempotency key: FROZEN-break (duplicates become
new rows). Reorder journal events: FROZEN-break (ordering reads
`repositories.py:732-746` define replay/audit order). Alter replay
semantics: FROZEN-break (CHG-2 + parity tests). Move internal
validator: INTERNAL-allowed (no caller outside gateway).
Move internal derivation: INTERNAL-allowed (same). Change
EVOLVING Controller method compatibly: allowed with tests.
Remove undeclared public symbol: allowed after DG-1 acknowledgment
(no promise existed). Change required hook: FROZEN-break (11
adapters + contract tests). Add optional hook: allowed
(`validate_fetch` default precedent).

## §5 A-05 decision

```text
A-05 — RATIFIED
```
Exact convention: §3 wording above. Concise durable rule for later
inclusion in AGENTS.md/API.md: "Names and meanings listed FROZEN
change only by architecture decision with migration and gate
re-run; EVOLVING surfaces change only PR-documented and tested;
everything else is INTERNAL unless deliberately classified."

## §6 Controller physical inventory

`src/hermes/research/controller.py`, 4327 lines, classes
`LockLostError:101`, `SourceRetractionError:110`,
`_FencedConnection:116` (per-statement lease-generation fence,
`execute:194`, rejects `executescript`/`cursor`/`commit`/
`rollback`, HD-01/ADV-02), `TickResult:272`,
`_HeartbeatRefresher:287`, `Controller:340` with 76 methods
(`:389-:4321`, full list verified by AST). Imports: core,
persistence (repositories incl. 11 repos, failure_classifications,
program_obligations, source_outcomes), research (extraction,
evaluation, failure_classification, gateway lazily per-call,
source_handlers, + ranges), event_validation. Fan-in: CLI (run,
resolve_human_gate), tests (tick ×234, resolve ×93, detect ×46).
Fan-out: gateway `apply_intent` (9 call sites), repositories,
handlers, journal. Tx entry points owned in-file: lease
(`:2428/2462`), `resolve_human_gate` (`:1405`), floor persist
(`:2909`), ladder write (`:3719`); all other writes via repository
txs through the fence. Lease: acquire/release/assert/refresh
(`:2392-2469`); journal via `_append_event_to_db` inside
transactions; authority via credential + HumanDecision surfaces;
providers via typed handler bundle only; persistence via fenced
repos; replay: none direct (transport layer's job).

## §7 Responsibility map (abridged; full cluster line lists verified)

- R-TICK loop/orchestration (`tick:482`, `run:597`, `notes:476`):
  inputs scheduler calls; outputs `TickResult`/notes; state: mode,
  lease; tx: none owned (lease only); lease: acquires; journal:
  none direct; authority: none; provider: none; persistence:
  fence rebuild; replay: none; identity: none; API: PUBLIC.
  Tests: controller suites, cli run test.
- R-LEASE (`_refresh_fence:2392`, `_assert_lock_valid:2409`,
  `_acquire_lock:2426`, `_release_lock:2469`, `_FencedConnection`):
  lease row lifecycle + generation fence; tx: own lease tx only;
  journal: none. API: INTERNAL.
- R-READS (19 methods `:620-:1020,2311,2365,3724-3789`): inputs
  conn+project; outputs digests/rankings/candidates; state: reads
  only; tx/lease/journal/authority/provider: none; persistence:
  SELECTs; identity: none (recomputed downstream); API:
  PUBLIC/EVOLVING reads. Tests: digest/candidate suites.
- R-DETECT (`detect_contradictions:1872`,
  `_detect_contradictions_pass:1901`, `_detector_candidate_rows:
  1967`, `_detector_resolve_ref:2025`,
  `_open_contradiction_parties:825`): inputs classifications;
  outputs recorded/duplicates/refused + row; tx: none owned
  (gateway tx inside); lease: wrapper acquires, pass assumes;
  journal: via gateway only; authority: none (machine admission);
  identity: consumes (never authors); API: PUBLIC (wrapper),
  INTERNAL (rest). Tests: chg1/N9 suites.
- R-VERDICTS (10 methods `:1214-:2298` incl. all `record_*`,
  `resolve_human_gate`, `register_operator`, `_verify_operator`):
  inputs operator credential+decision; outputs dict refusals or
  intent results; tx: lease + HD append + gateway tx (multi-tx op);
  lease: held throughout; journal: HD + audited intents;
  authority: enforces (never asserts); provider: none; identity:
  binds hashes; API: PUBLIC/SUPPORTED. Tests: authority/matrix
  suites. NOTE: `record_source_retraction:836` is audit-event-only
  RAISING `SourceRetractionError`, while
  `record_source_retraction_decision:1725` runs the S5 cascade
  returning data — dual surfaces, §13 YELLOW + §15 anti-seam.
- R-RECOVERY (`_recovery_pass:2477`, `_requeue_recovered:2539`,
  `_re_execute_requeued:2566`, `_is_stale*:4311,4321`, parked notes
  `:3945`, cone notes `:3912`): NO_SIGNAL ladder, requeue,
  re-execute; tx: status transitions via repos; lease: tick-held;
  journal: status/task events; API: INTERNAL. Tests: recovery
  suites + `test_concurrency.py`.
- R-DISPATCH (22 methods `:2601-:3107,3973-4297`): discovery,
  ordering, handlers, heartbeat, gates parking, retries; tx: via
  handler/repo boundaries; lease: tick-held; provider: typed
  bundle; journal: task/outcome events; API: INTERNAL (tick/run
  are the surface). Tests: orchestration suites.
- R-LADDER (6 methods `:3131-:3606` + readers `:3724-:3789`):
  obligation/terminus evaluation + `_write_ladder_transition`
  (own tx `:3719`); tx: owned; journal: transition events; API:
  readers PUBLIC/EVOLVING, pass INTERNAL. Tests: ladder suites.
- R-FLOOR (7 methods `:2817-:3107`): satisfaction counts, floor
  transitions (own tx `:2909`); API: INTERNAL. Tests: q02/c4.

## §8 Dependency/call map

High fan-in: `tick/run` (CLI, tests, scheduler), `_acquire_lock`
(9 verdict/tick sites), `apply_intent` (9 sites),
`_append_event_to_db` (via repos). High fan-out: `tick` (recovery,
ladder, detect, requeue, dispatch), `_dispatch_pass` (handlers,
gates, retries, floor). Shared state: `_fenced` (all writers),
`_conn` (lock ops + reads), `_clock`, `_project_id`, rebuilt repos
(`:2397-2407`), `_notes` (append-only diagnostics). Shared tx
contexts: NONE across methods (each tx self-contained; multi-tx
ops sequence lease→HD→gateway→audit). No recursion/reentrancy
(`run` loops `tick`; handlers never call back into Controller).
Cohesive-looking boundary crossers: `_detect_contradictions_pass`
(reads + gateway writes — the write is the seam, not the rows);
`resolve_human_gate` (verdict + own tx + mode write — must stay
whole); `_run_handler` (dispatch + structural verification).

## §9 Transaction map (must-not-move boundaries)

- Lease tx: `_acquire_lock` BEGIN `:2428` → COMMIT `:2462`
  (ROLLBACK `:2460,2466`). Must stay paired with `_release_lock`
  and fence generation.
- Verdict op: lease → HD existence-check + append (autocommit
  single INSERT, e.g. `:2273-2285`) → `apply_intent` →
  repository tx (e.g. classification `:233`/`321`,
  retraction cascade, contradiction `:2546`/`2650`, resolution
  `:2779`/`2831`) → audit tx (`:3832` path). Order + lease
  bracket must not move (anti-seam §15).
- `resolve_human_gate`: own tx (`:1405/1407`) covering status +
  HumanGateResolved event, then mode write outside it with
  self-heal note (`:1415-1431`). Must stay whole.
- Floor (`:2909/2911`) and ladder (`:3719/3721`) persist txs:
  owned, must stay with their evaluation.
- tick() itself opens NO tx (lease only) — extraction must not
  add one (would serialize against repository txs).

## §10 Invariant ownership map

Determinism: owned by pure detector/identity + injected clocks
(consumed everywhere, enforced in `contradictions.py`,
`replay.py`). Single mutation path: enforced by fence + HD-01
(`:116-245`) — Controller owns the fence object. Append-only:
delegated (no DELETE anywhere; Controller never deletes).
Replay: consumed (no direct replay code in Controller).
Curation: consumed via digest/screens (advisory only).
Human-authority: ENFORCED at verdict surfaces (credential,
lease, HD binding) — extraction must keep all three checks with
the mutation. 4 KiB: delegated (event_validation at append).
Isolation: enforced per-call via `self._project_id` on every
query/intent — extraction must thread project explicitly.
Prohibited-claims: N/A (docs). Archive/supersession/refusal:
delegated to gateway/repos, surfaced as data. Lease fencing:
OWNED (`:2426-2469` + fence class) — never split. Identity:
consumed, never authored (recomputed downstream).

## §11 Public API preservation map

PUBLIC/SUPPORTED (exact signature + return + refusal semantics
preserved; may move module only with re-export + DG-2):
`tick`, `run`, `resolve_human_gate`, `register_operator`,
`record_failure_classification`,
`record_contradiction_resolution`,
`record_source_retraction_decision`, `record_operator_decision`,
`record_scope_review_decision`, `record_curation_decision`,
`detect_contradictions`, `notes`.
PUBLIC/EVOLVING (semantics preserved; shape may grow; may move
with re-export): all 18 read/digest methods (`:620-:1020`,
`:2311,2365,:3724-:3789`), `note`.
ACCIDENTALLY PUBLIC (may become explicitly internal after DG-1
acknowledgment; must not gain callers meanwhile):
`record_source_retraction` (audit-only raiser — ambiguous twin
of the decision surface; reconcile before decomposing),
`screen_near_miss_refutations`, `audit_curated_registry`
(niche advisory; verify callers first).
INTERNAL (free): all 46 `_` methods. No renames in this gate.

## §12 Candidate extraction seams

- S-1 detector row derivation (`_detector_candidate_rows:1967`,
  `_detector_resolve_ref:2025`, `_open_contradiction_parties:825`)
  → pure reader module taking `(conn, project_id)`: tx N/A
  (reads), lease N/A, journal N/A, authority N/A, replay N/A,
  identity consumed-only, isolation via explicit project param,
  API: wrapper stays, readers move; tests: chg1/N9 suites
  unchanged. **GREEN.**
- S-2 verdict surfaces, one per surface (e.g. classification,
  resolution, retraction-decision): tx preserved (lease+HD+gateway
  sequence kept whole inside moved unit), lease bracket kept,
  journal order kept (HD before intent), authority checks move
  with mutation, isolation via project param, API: same names
  (re-export or keep facade). **YELLOW** (per-seam design: HD
  idempotency check placement, fence object passing — fenced
  conn must travel, never be rebuilt inside).
- S-3 read/digest cluster: tx N/A, lease N/A, journal N/A,
  authority N/A; needs explicit fence-vs-raw read convention
  (`self._conn` reads vs `self._fenced`) + project threading.
  **YELLOW.**
- S-4 dispatch sub-clusters: share fence + recovery state +
  heartbeat + retry policy; splitting risks duplicating the
  exactly-once ladder. **YELLOW-RED: design required, no
  mechanical move.**
- S-5 recovery state machine: lease + NO_SIGNAL + requeue +
  re-execute + fence interplay. **RED: do not extract.**
- S-6 lease/fence/connection lifecycle (`:2392-2469` + class
  `:116`): the single-writer heart. **RED.**
- S-7 tick orchestration sequence: mode gates + pass ordering
  (ladder→detect→requeue→dispatch) is load-bearing.
  **RED.**

## §13 Anti-seams (must stay whole prematurely)

Credential-verify → lock → HD check/append → apply_intent (order
+ single lease bracket); lease acquire/release + fence generation
+ `_refresh_fence` rebuild set; HD append + intent admission (no
interleaving writer); `resolve_human_gate` status-tx + mode
follow-up; floor/ladder evaluate→persist tx pairs; identity
compute + idempotency check (same tx); recovery claim→requeue→
re-execute chain; detector rows→pure N1→gateway admission
(N9-filtered inputs must travel together); fence object and the
writes it attributes (never rebuild mid-operation; never pass raw
conn to a writer).

## §14 First extraction candidate

S-1 detector row derivation: strong cohesion (3 pure readers, one
job: rows for N1), inputs `(conn, project_id)` + clock-free,
outputs row dicts, no tx/lease/journal/authority/provider,
project isolation explicit, identity consumed-only, test surface
(chg1/N9 suites) exercises behavior not location. Honest value
assessment: modest (~120 lines moved) but the ONLY seam with zero
invariant coupling — correct first cut to prove the extraction
discipline before YELLOW seams. No manufactured alternative:
S-2+ all need per-seam design first.

## §15 E-02 preparation requirements

REQUIRED BEFORE EXTRACTION: this responsibility/tx/invariant/API
map (done here); S-1 characterization tests pinning row shapes
for valid/corrupt/invalidated/retracted inputs (behavior, not
location); fence-passing convention (fenced conn travels as a
parameter; HD-01 prohibitions restated in the seam spec);
lease-bracket rule (extracted units never acquire/release).
USEFUL BUT OPTIONAL: read-path query inventory; `_notes`
conventions doc. NOT NEEDED: new fixtures, renames, shims,
versioning.

## §16 Multi-agent implementation boundaries

Single-agent files during any extraction: `controller.py` (the
donor — one agent moves code OUT, none edits around it in the
same change); the receiving module (one owner). Independently
auditable seams: S-1 readers (row-shape tests), S-2 per surface
(refusal-matrix tests), S-3 reads (digest tests). Independently
addable tests: characterization tests per seam (additive files
only). Isolated artifacts: temp DBs per test (existing pattern).
Ordering: S-1 → S-3 → S-2 surfaces → S-4+ only post-design.
Evidence boundaries: each seam change carries its own
before/after test run + gate slice. Contamination prevention:
one-seam-per-commit, donor-file lockstep (no two agents editing
`controller.py` concurrently), no shared helper edits without
owning-gate review (helpers serve multiple seams).

## §17 DG-2 pass/block criteria

PASS requires ALL: responsibility map complete (§7) ✓; dependency
map complete (§8) ✓; transaction map complete (§9) ✓; invariant
map complete (§10) ✓; public API map complete (§11) ✓; seams
identified with YES/NO checklists (§12) ✓; anti-seams identified
(§13) ✓; first candidate identified with honesty assessment or
explicitly rejected (§14: S-1 identified) ✓; characterization
coverage listed (§15) ✓; zero ambiguity affecting safety
(retraction-surface reconciliation flagged as required pre-work —
see §19). BLOCK on: any missing map; any seam crossing an
unmapped tx/lease; any invariant without an owner; any new module
created (this gate is read-only).

## §18 Adversarial review

1. Size vs responsibility? PASS (76-method clusters + cohesion
   verdicts; only S-1 proposed). 2. Seams crossing tx? PASS
   (S-1 has none; YELLOWs require tx-ownership proof). 3. Lease
   crossing? PASS (S-1 leaseless; S-2 keeps bracket). 4. Journal
   order change? PASS (no reorder; HD-before-intent kept).
5. `apply_intent` bypass? PASS (all writes flow through it;
   fence rejects escapes). 6. Weaker authorization? PASS
   (checks move with mutations; partitions untouched). 7. Replay
   harm? PASS (no replay code in Controller; clocks injected).
8. Identity change? PASS (consumed-only; formulas elsewhere).
9. New publics? PASS (facade-or-re-export rule; `__all__`
   discipline in E-02). 10. Preserving accidental API? PASS
   (`record_source_retraction` flagged for reconciliation, not
   enshrined). 11. First extraction cohesive? PASS (3 readers,
   one job, zero coupling). 12. Concurrent agents? PASS (§16
   boundaries). 13. Contract vs implementation tests? PASS
   (row-shape/refusal-matrix behavior specified). 14. A-05
   sufficient? PASS (§3 + §4 give move/no-move rules per
   category). 15. Blocking ambiguity? AMBIGUOUS → resolved as
   required pre-work: dual retraction surfaces must be
   reconciled (one raising audit-only vs one data-returning
   cascade) before S-2 touches either — recorded in §19, not
   hidden. Result: 14 PASS, 0 FAIL, 1 AMBIGUOUS-with-path
   (documented).

## §19 Final recommendation

Ratify A-05 as worded (§3). Approve DG-2 design scope LIMITED to
S-1 (detector row derivation) + S-2/S-3 per-seam designs, with
mandatory pre-work: reconcile the dual retraction surfaces'
conventions (raise-vs-data) without changing either behavior.
Forbid S-5/S-6/S-7 extraction and any tx/lease/validator moves
until their own designs pass. Next: characterization tests for
S-1, then the S-1 move as the discipline-proving first cut.

## §20 Final decision

```text
P0 — A-05 RATIFIED / DG-2 READY FOR REVIEW
```
