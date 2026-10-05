# DG-2 — Controller Structural Design Gate

## §0 Executive Verdict

```text
DG-2 — CONTROLLER DESIGN GATE PASSED / S-1 IMPLEMENTATION AUTHORIZED
```

S-1 (detector row derivation: `_detector_candidate_rows:1967`,
`_detector_resolve_ref:2025`, `_open_contradiction_parties:825`) is
verified side-effect-free readers with fully classified
dependencies, a pinned row contract, and no invariant ownership.
The retraction-surface ambiguity is closed as LEGITIMATE DUAL
SURFACE with S-1 provably independent of both. All 20 DG-2
criteria hold; adversarial review 19 PASS / 0 FAIL / 1 AMBIGUOUS
with an explicit path (pre-work, not a block).

## §1 Baseline / Identity

`HEAD == origin/main == 19cda3a`, branch `main`, tree clean except
known untracked (`IDEA.md`, external `orci/orhead/ortree.json`,
operator `Prompts/` gate-text file — all untracked, none affect
the repo). P0-commit delta vs HEAD: exactly the P0 report file
(verified: `git diff 979311f..HEAD --stat` = 1 file). Baseline
exact: YES.

## §2 Certification Chain

P6 (`ff79bb6`), N9 (`02cb976`), tick-loop (`633cff1`), Phase 0/1/
1.1/2/3/P0 reports — all present in `docs/archive/`, all SHAs
ancestors of HEAD (verified `merge-base --is-ancestor` for
P6/N9/tick). DG-2 operates on the correct baseline.

## §3 Physical Controller Inventory

`src/hermes/research/controller.py`, 4327 lines. Classes:
`LockLostError:101`, `SourceRetractionError:110`,
`_FencedConnection:116` (per-statement lease-generation fence;
rejects `executescript`/`cursor`/`commit`/`rollback`, HD-01/ADV-02),
`TickResult:272`, `_HeartbeatRefresher:287`,
`Controller:340` (76 methods `:389-:4321`, AST-verified).
Constructor (`:388`): conn, project_id, extract_fn,
gate_verdict_fn, task_handlers, owner, clock, lease_seconds,
max_calls_per_tick, artifact_store, epistemic-ordering/floor
flags, heartbeat params. Class state: `_fenced` (rebuilt
`:2396`), `_conn`, `_clock`, `_project_id`, rebuilt repos
(`:2397-2407`), `_notes:471`, lock generation. Module state:
`DEFAULT_MAX_CALLS_PER_TICK:249`,
`DEFAULT_LEASE_SECONDS:252`, heartbeat constants `:253-268`
(pure config). Imports: core, persistence (11 repos,
failure_classifications, program_obligations, source_outcomes),
research (extraction, evaluation, failure_classification,
gateway per-call, source_handlers), event_validation.
Fan-in: CLI (`run`, `resolve_human_gate`), tests (tick ×234).
Fan-out: `apply_intent` (9 sites), repositories, handlers,
journal. Dependency graph: Controller → gateway → validators →
repositories → journal (mutations); Controller → repositories
(reads); Controller → handlers → repos (dispatch); NO
Controller → provider/network; NO Controller → replay;
Controller → fence → lease-generation check on every write.

## §4 Nine-Cluster Verification

Independently verified against the 76-method AST list — P0's nine
clusters match the physical code: tick/loop (4: `tick:482`,
`run:597`, `notes:476`, `note:616`), lease/fence (4 + fence
class), reads (19: `:620-:1020,2311,2365,3724-3789`),
detection (5), verdicts (10), recovery (6+notes), dispatch (22),
ladder (6+3 readers), floor (7). These are responsibility
boundaries, not filename groups: each cluster has distinct
inputs/outputs/mutation profiles (detailed §7-§11); sharing is
confined to `_fenced/_conn/_clock/_project_id` plumbing and the
lease bracket — which is precisely what seams must thread
explicitly.

## §5 S-1 Exact Seam

- `_detector_candidate_rows:1967` — caller: only
  `_detect_contradictions_pass:1922`. Callees:
  `classification_proposals` (self), `_detector_resolve_ref`
  (self), `source_artifact_retracted` (imported),
  `conn.execute` SELECT, `json`.
- `_detector_resolve_ref:2025` — caller: only the above.
  Callees: `conn.execute` SELECT ×2. Pure string ops otherwise.
- `_open_contradiction_parties:825` — caller: only
  `re_review_candidates:801`. Callees:
  `ContradictionRepository(self._conn).open_contradictions`
  (read-only repo). Zero test files reference any of the three
  directly (grep-verified) — characterization tests are
  genuinely missing and must be added.

## §6 S-1 Dependency Classification

`_detector_candidate_rows`: inputs none (self) → specify
`(conn, project_id, digest_items)`; outputs row-dict list;
mutations NONE; DB: SELECT on `artifacts` only; tx: none opened;
lease/fence: none touched (uses raw `self._conn`; fence passes
reads through — `controller.py:194-245` — so caller may pass
either conn); journal: none; provider: none; authority: none;
identity: reads hashes/metadata, computes only `sorted()`;
exceptions: fail-safe `continue` (never raises);
ordering: digest order in (oldest-first,
`failure_classifications.py:554-560`), N1 output sorted by cid
regardless; globals: none; tests: none direct.
`_detector_resolve_ref`: same, plus zero journal/lease/auth.
`_open_contradiction_parties`: same via read-only repository.
Every dependency: READ-ONLY DATA ACCESS or PURE. Zero
TRANSACTION/LEASE/AUTHORITY/IDENTITY/REPLAY-coupled, zero
UNKNOWN. S-1 GREEN confirmed (not merely read-only: no clock,
no randomness, no writes, no decisions).

## §7 S-1 Row Contract

Fields: `artifact_id` (str, required — row skipped otherwise),
`project_id` (str), `program_ref`/`hypothesis_ref`/`failure_class`
(str or None; N1 skips falsy `artifact_id`/`failure_class`,
`contradictions.py:126-137`), `evidence` (sorted str list,
possibly empty → N1 skips pair), `invalidated` (bool from
`invalidation_marker`). No timestamps, no linkage, no sentinels.
Internal implementation shape (not durable, not in `__all__`,
consumed only by `detect_classification_conflicts` + future
characterization tests). Preserve exactly — no DTO/dataclass
(the dict IS the contract; a new type would add surface for
zero benefit).

## §8 Retraction-Surface Reconciliation — LEGITIMATE DUAL SURFACE

Three `SourceRetracted` emitters exist, deliberately different:
(A) `Controller.record_source_retraction:836` — audit-event-only
(`payload {artifact_id}`, default correlation), raises
`SourceRetractionError` on bad input, touches NO state machine
(docstring: "the retraction authority stays where it already
lives"); (B) `record_source_retraction_decision:1725` + gateway
S5 cascade — decision row `rd-`, `supersedes` edge, cone
invalidation, contradiction supersession, correlation
`retract_<hash>`, dict refusals; (C) fetch-path auto-emit
(`source_outcomes.py:767-789`) — machine-observed provider-
declared retraction, payload `{artifact_id: <ref-string>,
no_full_text_kind, observed_by_task}`, same-tx as the outcome.
Canonical source of truth for governance effect: (B)'s
projection (decision + edge + cone + events). Raises: (A) only.
Returns data: (B) (dicts) and (C) (outcome dict). Callers: (A)
tests + external audit callers, zero src-internal callers; (B)
operator verdict path; (C) fetch handler path. Disagreement:
impossible on N9 (predicate reads decision edges only —
`source_outcomes.py:159`); re-review seeding reads
`artifact_ids_json`, present in all three shapes (verified
`controller.py:880-928` handles bare IDs, ref-strings, and
corruption fail-closed); STALE guard matches only `retract_*`
correlations, so (A)/(C) never block (B). Observable by S-1:
no — S-1 reads classifications + artifacts + predicate, never
events. N9 depends on (B) only; (A) is intentionally
non-fencing audit. Behavior intentional (docstrings +
per-surface tests), not accidental. Verdict:
LEGITIMATE DUAL (+observed) SURFACE — SAFE for S-1.

## §9 N9 Bypass Analysis

Chain: retracted source → S5 decision + `supersedes` edge →
`source_artifact_retracted(conn, project, artifact_id)` (exact
relational check, project-joined) → False at substrate resolver
(`failure_classifications.py:388`), in-tx ownership re-check
(`:361`), derivation skip (`controller.py:2009`), validator
None (`gateway.py:2396`), in-tx re-resolution (`:2571`).
S-1 calls the same predicate path (consumes its result; does not
reimplement it), duplicates nothing, opens no tx (predicate is a
SELECT inside the caller's context), preserves exception
behavior (skip, never raise), preserves project scoping
(explicit `project_id` param), preserves order (sorted evidence;
N1 sorts output). Proof of no fresh classification path: S-1
contains zero `INSERT/UPDATE`, zero `apply_intent`, zero intent
construction — it cannot admit anything; admission lives
exclusively in gateway validators + repository write txs, both
N9-fenced independently of S-1.

## §10 Transaction Boundary Analysis

Before: `_detect_contradictions_pass` reads (autocommit SELECTs)
then gateway opens its own tx per candidate. After (design):
identical — extracted readers take the caller's conn and run the
same SELECTs in the caller's context; the ONLY tx owner remains
the gateway validator. No new tx, no moved boundary, no
independent commit, no retained connection (no closures stored),
no lease crossing (readers never touch lease state), no lock-order
change (no locks taken), rollback behavior unchanged (readers
cannot fail a tx — fail-safe skips). S-1 is transaction-agnostic
by construction: a read-only function of committed state.

## §11 Lease/Fence Safety

Lease acquired in `tick()`/wrapper (`controller.py:490,1892`);
fence object rebuilt per acquisition (`:2396`); validation per
write (`:194-197`); S-1 executes between, touching neither.
S-1 cannot cause stale reads beyond what the caller already sees
(same conn, same snapshot); cannot retain the fenced conn (no
storage); cannot execute outside the lease (it has no scheduler
identity — it is called, never scheduled). Reads pass through
the fence unfenced either way. No lease acquire/release/refresh/
validate in S-1 now or after extraction.

## §12 Authority Analysis

S-1 paths reach: no HumanDecision (no event reads), no human
gate, no credential check, no verdict persistence, no refusal
generation (skips, never `PROPOSAL`/`ROLE`), no completion, no
dispatch. Extraction moves no check, duplicates none, bypasses
none, alters no refusal and no authority-then-mutation order
(the pass's order — derive → N1 → gateway admission — is owned
by `_detect_contradictions_pass`, which does NOT move).

## §13 Identity/Idempotency Analysis

S-1 touches: content_hash (read), artifact_id (read),
classification_id (read), contradiction inputs (pass-through
pair members). CLASSIFICATION: IDENTITY CONSUMED (all),
IDENTITY DERIVED (none — `sorted()` is ordering, not identity),
IDENTITY AUTHORED (none), IDEMPOTENCY ENFORCED (none —
duplicate handling lives in the gateway tx). No second
authoring path is created: the only writers of `cx_` remain the
gateway insert path.

## §14 Project Isolation

`project_id` is an explicit parameter at every S-1 boundary
(digest is pre-scoped by `classifications_for_project`;
every SELECT filters `project_id = ?`; predicate joins the
decision row's project). No global current project (verified —
`self._project_id` threaded, no module global), no cross-project
query (all predicates project-bound), no cache, no fallback
(`None` → skip, never default project), no shared mutable state.
Exact predicates cited in §6/§9.

## §15 Replay/Determinism

S-1 touches: no journal replay, no event reconstruction, no
timestamps (rows carry none), no UUIDs, no randomness, no
provider calls, no environment values. Inputs (committed rows +
digest order oldest-first) fully determine outputs; N1 output
order is cid-sorted regardless of input order. Moving S-1
changes no deterministic output — byte-identical functions of
byte-identical inputs. Evidence: determinism probes (rebuild-
identical IDs across runs/baselines) + exactly-once detection
across re-ticks.

## §16 API Preservation

A-05 holds: S-1 symbols are INTERNAL today (underscore-prefixed,
zero test/direct references) and stay INTERNAL (new module is an
implementation location, not a surface; no `__all__` addition;
tests import behavior via `detect_contradictions`, never the
module). SUPPORTED API unchanged (`detect_contradictions`
signature/semantics/lease behavior stay on Controller).
EVOLVING reads unchanged. No accidental new public API (the
module path must not be documented as supported;wording guard
for the implementation change).

## §17 Characterization-Test Design

C1 row-shape: fixture DB with valid/corrupt/invalidated/
retracted/missing-metadata classifications → exact expected row
dicts (7 fields). C2 ordering: shuffled insertion → identical
multiset + sorted evidence lists. C3 isolation: p1/p2 fixtures →
no cross rows. C4 retraction: pre/post S5 cascade → retracted
refs contribute nothing; rows otherwise identical. C5
exceptions: corrupt JSON/non-dict/missing row → skip, no raise.
C6 empty: empty DB + empty refs → `[]`. C7 idempotency: repeated
evaluation → identical output (pure reads). C8 determinism:
rebuild-identical DBs → identical rows. All additive new tests;
no existing test moves (none reference S-1 directly).

## §18 Multi-Agent Safety

Donor `controller.py`: single agent, S-1 symbols only, one
commit; no concurrent edits to the file in the same change.
Receiver module: single owner, no other content. Additive
characterization tests: separate files per author, no shared
helper edits without owning-gate review. Temp DBs per test
(existing pattern). Ordering: characterization tests land with
(or just before) the move in the SAME commit (they pin it);
no second seam starts until S-1 merges. Evidence per seam:
before/after suite + gate slice. Rollback: single-commit revert
(no migration, no state, no test-framework change).

## §19 Proposed First Extraction

New module `src/hermes/research/contradiction_candidates.py`
(IMPLEMENTATION shape — design only here): move
`_detector_candidate_rows` → `detector_candidate_rows(conn,
project_id, digest_items)`, `_detector_resolve_ref` →
`detector_resolve_ref(conn, project_id, ref)`,
`_open_contradiction_parties` → `open_contradiction_parties(
conn, project_id)`; Controller keeps thin wrappers or calls
directly with `(self._conn, self._project_id, digest)` (wrapper
retention preferred — zero caller churn, facade preserves the
INTERNAL-but-stable call graph). Imports added: one import line
in controller; removed: none elsewhere. No helper object (pure
functions suffice). No new public symbol (no `__all__`; module
undocumented as surface). Tests stay (behavioral, location-
agnostic) + additive C1–C8 file. Diff ≈ +140/−110. Commit:
one seam, one commit, suite + chg1/N9 slices green. Rollback:
`git revert` of that commit. No cleaner abstraction exists —
rejected a DTO/dataclass and a "reader object" as surface for
surface's sake.

## §20 Protected Non-Moving Surfaces

Lease/fence lifecycle (`:2392-2469` + class `:116`); all
credential/HumanDecision handling; all journal writes; all
identity derivation + idempotency enforcement; recovery state
machine; tick orchestration + pass ordering; dispatch +
handlers + retries + gates; floor/ladder evaluate→persist pairs;
N9 admission boundary (substrate + in-tx + validator +
predicate); S5 cascade; STALE/duplicate guards; provider
transport; migration set; event catalog. Evidence: each owns a
tx, a lease interaction, an authority check, or an identity
derivation enumerated above.

## §21 DG-2 Criteria

Architecture: responsibilities genuinely understood (§4 vs
76-method AST — match) ✓. S-1: symbols exact (§5) ✓; dependencies
complete, zero UNKNOWN (§6) ✓; row contract pinned (§7) ✓; no
invariant ownership (§10-§15) ✓; no tx movement (§10) ✓; no lease
ownership (§11) ✓; no authority (§12) ✓; no identity authoring
(§13) ✓; no isolation weakness (§14) ✓; no replay change (§15)
✓. Retraction: dual surfaces reconciled (§8 verdict recorded)
✓; canonical semantics known (S5 projection) ✓; N9 unbypassable
(§9 proof) ✓; exception/data preserved (skip-vs-row, raise sites
untouched) ✓. API: A-05 valid (§16) ✓; no new publics ✓; no
supported changes ✓. Tests: C1–C8 concrete (§17) ✓; existing
coverage mapped (zero direct refs — additive only) ✓. Implemen-
tation: seam exact (§19) ✓; one-commit boundary ✓; multi-agent
safe (§18) ✓; revertible ✓. Certification: zero source/test/
config changes this gate (verified §24) ✓; suite green ✓.

## §22 Adversarial Review

1. Pure vs read-only? PASS (READ-ONLY DATA ACCESS, classified —
   no clock/random/writes/decisions). 2. Connection tx semantics
   matter? PASS (SELECTs in caller context; no tx opened/needed;
   identical pre/post). 3. Lease/fence observable? PASS (never
   touched; reads pass through either way). 4. Read across fence
   validation? PASS (no validation crossed — reads need none).
5. N9 bypass? PASS (§9 proof; no admission path in S-1).
6. Surfaces equivalent? PASS (deliberately different acts —
   audit fact vs authority cascade vs machine observation —
   §8 evidence). 7. Can they disagree? PASS (disagreement
   impossible on N9/governance reads; audit-fact duplication is
   harmless by construction). 8. Exception-vs-data dependence?
   PASS (S-1 skips; raisers untouched). 9. Consumed identity
   expected elsewhere? PASS (downstream recomputes/validates).
10. Second authoring path? PASS (zero authoring in S-1).
11. project_id guaranteed? PASS (explicit param + per-query
   predicates). 12. Accidentally public module? PASS (§16
   guards: no `__all__`, no docs-as-surface). 13. `__all__`
   issue? PASS (none added; existing 39 sites untouched).
14. Hidden provider/env dependence? PASS (none found;
   json/select/sorted only). 15. Ordering change? PASS
   (sorted evidence + cid-sorted N1 output). 16. Rollback
   change? PASS (no tx participation). 17. Exception
   propagation? PASS (fail-safe skips preserved verbatim).
18. Characterization sufficient? PASS (C1–C8 cover shape,
   order, isolation, retraction, exceptions, empties,
   idempotency, determinism — every S-1 behavior). 19. Two
   agents on adjacent seams? PASS (§18: donor lockstep,
   one-seam-per-commit). 20. Reason NOT to start with S-1?
   PASS (none found — modest size honestly stated, zero
   coupling verified; YELLOW seams correctly deferred).
Result: 19 PASS, 0 FAIL, 1 AMBIGUOUS→resolved (§8 verdict recorded
as precondition, not open ambiguity).

## §23 Residual Risks / Preconditions

(a) Dual retraction surfaces must stay reconciled as documented —
   any future change to either surface's event shape needs N9 +
   re-review regression (precondition, not blocker). (b) S-1 move
   must keep the `(conn, project_id, digest_items)` signature —
   no convenience widening. (c) No characterization suite exists
   today — C1–C8 MUST land with the move (same commit). (d) The
   `record_source_retraction` audit-only raiser vs decision-cascade
   naming overlap remains a readability trap — reconcile
   conventions (docs/naming, no behavior change) before S-2.

## §24 Final Verdict

```text
DG-2 — CONTROLLER DESIGN GATE PASSED / S-1 IMPLEMENTATION AUTHORIZED
```
