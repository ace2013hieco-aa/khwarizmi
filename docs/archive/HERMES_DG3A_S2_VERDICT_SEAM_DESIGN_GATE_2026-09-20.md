# DG-3A — S-2 Verdict Seam Design Gate

## §0 Executive Verdict

```text
DG-3A — S-2 DESIGN GATE PASSED / IMPLEMENTATION AUTHORIZED
```

Scope of authorization is NARROW and explicit: the ONLY authorized
S-2 unit is the shared idempotent-`HumanDecision` append step
(S-2h, specified §17), proved byte-shape-identical across the four
intent-based verdict surfaces. Per-surface method moves are
REJECTED (§18 anti-seams with per-question evidence): each would
require moving lease acquisition (S-6 RED), creating
module→Controller reverse dependencies, or splitting the
lease-fenced bracket across a module boundary. No framework, no DI,
no renames, no behavior change.

## §1 Baseline / Identity

`HEAD == origin/main == 0de76db`, branch `main`, tree clean except
known untracked (`IDEA.md`, operator `Prompts/`, external
`orci/orhead/ortree.json` — none affect the repo). S-1 commits
present (`231cd75` implementation, `0de76db` certification).
Controller measured at 4256 lines (4327 pre-S-1 minus 90 moved
plus 19 wrapper lines — consistent, no unexpected change).

## §2 S-1 Certification Dependency

S-1 CERTIFIED (`231cd75`/`0de76db`, 2045 tests, residual Risks
(a)–(d) all scope-compatible with this gate: S-2h touches no
retraction event shape, keeps the exact `(conn, project_id,
digest_items)` discipline analog (`(conn, clock, project_id,
correlation_id, caused_by, reason, payload)` — caller-owned
context only), adds no characterization debt (V-suite specified
§19), and does not touch the dual-surface naming overlap).
S-1 output (`detector_candidate_rows`) is consumed, never
modified, by anything in S-2 scope.

## §3 Physical Verdict Inventory

Ten methods on `Controller` (`controller.py`), verified by AST +
full reads (line numbers current at HEAD):

| Method | Lines | Shape | Lease | HD append | Gateway intent | Own tx | Refusal style |
|---|---|---|---|---|---|---|---|
| `register_operator` | 1214–1232 | V-d direct repo | none | none | none | repo-internal | data (`OPERATOR`) |
| `_verify_operator` | 1234–1240 | helper | none | none | none | none | bool |
| `resolve_human_gate` | 1242–1435 | V-c own tx | acquire/release | none | none | `BEGIN:1352`/COMMIT/ROLLBACK + mode write outside | data (`VERDICT/RATIONALE/OPERATOR/LOCK/NOT_FOUND/NOT_HUMAN_GATE/NOT_WAITING/ALREADY_RESOLVED/TRANSITION`) |
| `record_operator_decision` | 1437–1512 | V-b lease+gateway | acquire/release | none | `RESOLVE_CLASSIFICATION_PROPOSAL` | gateway-owned | data + `duplicate` |
| `record_scope_review_decision` | 1514–1591 | V-b lease+gateway | acquire/release | none | `RECORD_SCOPE_REVIEW_DECISION` | gateway-owned | data + `duplicate` |
| `record_curation_decision` | 1595–1719 | V-a lease+HD+gateway | acquire/release | check-append `:1682-1694` | `CURATE_KNOWLEDGE` | gateway-owned | data + `duplicate`; size-check `RATIONALE` pre-lock |
| `record_source_retraction_decision` | 1721–1861 | V-a lease+HD+gateway | acquire/release | check-append `:1830-1842` | `RETRACT_SOURCE` | gateway-owned (S5 cascade) | data + `duplicate` |
| `record_contradiction_resolution` | 2052–2089 | V-a lease+HD+gateway | acquire/release | check-append `:2054-2066` | `CONTRADICTION_RESOLUTION` | gateway-owned | data + `duplicate` |
| `record_failure_classification` | 2091–2238 | V-a lease+HD+gateway | acquire/release | check-append `:2202-2214` | `RECORD_CLASSIFICATION` | repository-owned | data + `duplicate`; input-shape checks pre-lock |
| `record_source_retraction` | 836–871 | V-d audit append | none | none | none | none (single autocommit append) | RAISES `SourceRetractionError` |

Callers: verdict surfaces have zero src-internal callers (CLI
calls `run` + `resolve_human_gate` only; tests call all ten —
`test_controller.py:114` hits on `record_operator_decision`-family
names). Callee fan-out per surface: `_verify_operator`,
`_acquire_lock`/`_release_lock`, `_append_event_to_db`,
`apply_intent`, per-surface hash builders. Database ops: HD
SELECT-exists + conditional INSERT (V-a ×4, identical shape);
`resolve_human_gate` status UPDATEs + 4 events in own tx;
`register_operator`/audit paths single statements.

## §4 Verdict Responsibility Clusters

The ten methods are NOT one responsibility — four shapes (V-a…V-d
above). Coherent sub-responsibilities actually present: (i) the
HD idempotent-append step, identical across all four V-a
surfaces; (ii) per-kind intent construction + result mapping
(surface-specific, inseparable from each surface's command
vocabulary); (iii) the lease bracket + refusal envelope (shared
discipline, S-6-owned mechanics). Only (i) is extractable without
moving lifecycle state — hence the narrowed authorization (§17).
"Verdict production / validation / admission / persistence /
audit / refusal / authority / dispatch / completion / recovery"
(§5 prompt list) map as: derivation+validation = per-surface
command building (inseparable); authority = credential + HD
binding (spans caller + gateway, must not split); admission =
gateway validators (do not move); persistence = repository txs
(do not move); audit = HD + IntentApplied (HD step is (i),
IntentApplied stays in gateway); refusal = per-surface envelopes
(stay — they name surface-specific echo fields); dispatch/
completion/recovery = NOT verdict work (tick/dispatch clusters,
out of scope).

## §5 Exact S-2 Candidate

AUTHORIZED UNIT ONLY — S-2h, idempotent HumanDecision append:

- Symbols: one new function `record_human_decision_once(*, conn,
  clock, project_id, correlation_id, caused_by, reason, payload)
  -> bool` (True = recorded now, False = already present;
  callers ignore the return, exactly as today).
- Call sites replaced (4): classification `:2202-2214`,
  resolution `:2054-2066`, retraction-decision `:1830-1842`,
  curation `:1682-1694` — the SELECT-exists + conditional-append
  blocks only; every surrounding line stays.
- Inputs: caller-owned conn (fenced as today), clock, project,
  precomputed correlation/payload strings. Outputs: bool.
  Mutations: at most one event row (identical to today).
  Tx: none owned (runs inside caller's lease bracket + gateway
  tx sequencing, unchanged). Lease/fence: none touched (conn
  passed through, as today). Authority: none performed (verify
  stays in callers). Gateway: untouched. Repository: only the
  pre-existing `_append_event_to_db` call (same module it already
  lives in). Journal: same single conditional append.
  Identity: correlation strings built by callers (unchanged).
  Project: explicit param. Provider/replay: none. Exceptions:
  append failure propagates (no catch — identical to all four
  sites today, each of which catches only `GatewayRejection`;
  classification's propagation is pinned by the P7
  journal-failure test). Callers: the 4 V-a surfaces.
- Dependency classification: PURE plumbing over READ-ONLY DATA
  ACCESS (existence check) + one conditional append through the
  existing journal writer. Zero TRANSACTION/LEASE/AUTHORITY/
  IDENTITY/REPLAY-coupled, zero UNKNOWN. No other S-2 unit
  survives classification — per-surface moves all require
  TRANSACTION-COUPLED (lease/tx) or LEASE/FENCE-COUPLED
  primitives, hence REJECTED (§18).

## §6 Dependency Classification

Per §5 table (full matrix in report body): the helper's only
callees are `conn.execute` (SELECT) and the pre-existing
`_append_event_to_db` import (same source module it is called
from today — `persistence.repositories`, no new edge). No
gateway import, no clock construction, no uuid/hashlib, no
random, no provider, no env. Direction:
Controller → verdict_decisions → persistence.repositories
(append only) — no cycle (repositories imports nothing new).

## §7 Lease/Fence Boundary

| Operation | Lease held? | Fence validated? | Transaction | Commit owner |
|---|---|---|---|---|
| credential verify | no (pre-lock, read) | n/a (read) | none | — |
| rationale size-check | no | n/a | none | — |
| `_acquire_lock` | acquires | n/a | own lease tx (`controller.py:2428/2462`) | controller |
| HD exists-check + append (→S-2h) | YES (inside bracket) | SELECT passes; append IS a write → fence-checked on `self._fenced`, exactly as today (conn object unchanged) | none owned (rides caller context; gateway tx comes later) | — (same as today) |
| intent build | YES | n/a | none | — |
| `apply_intent` | YES | per-statement inside validators' txs | gateway + repository txs | gateway/repos |
| result mapping / refusal envelope | YES | n/a | none | — |
| `_release_lock` | releases | n/a | own lease tx | controller |

S-2h moves no row of this table: same conn object, same bracket
position (called at the exact current call sites), no second
lease, no independent commit, no lock-order change (no locks),
no lifetime extension (no stored references), no stale-fence
exposure (fence validation happens per-statement inside the
existing validated writes, unchanged).

## §8 Authority/HumanDecision Ordering

Verified order in all four V-a surfaces: input-shape checks →
credential verify (`_verify_operator`) → decision-identity
derivation → rationale size-check → lease acquire → HD
check-append (→S-2h) → intent build → `apply_intent` →
result/refusal mapping → lease release. Authority checked at
(1) controller credential, (2) gateway credential-exists +
decision-binding re-verification; the surface that checks is
never the surface that decides (human decides; code verifies).
V-b surfaces omit HD (gateway checks proposal state instead —
unchanged). No surface mutates before authority: the earliest
write in every surface is post-`_verify_operator` (V-a/V-b/V-c)
or is the authority-independent audit append (V-d, by design).
S-2h performs no check and moves no check — ordering preserved
by calling it at the identical program point.

## §9 Gateway Boundary

Callers of gateway from verdict scope: the 4 V-a + 2 V-b
surfaces via `apply_intent(self._fenced, intent)` (dispatch
table `gateway.py:3782-3815`). Passed: built intents
(kind/project/justification/payload). Gateway validates
(role, project, schema, credential-exists, decision/proposal
binding), mutates via repository txs, returns
`IntentResult(entity_id, duplicate)` or raises
`GatewayRejection`, owns all its transactions, writes journal
inside those txs, derives deterministic IDs
(`retraction_id`, `resolution_id`, `curation_id`), emits
refusal codes, performs authorization re-verification. Gateway
never calls `apply_intent` (it IS the dispatcher; verified
dispatch table has no self-call). Direction stays
Controller/S-2h → gateway → persistence/journal. S-2h never
touches gateway (no import, no call) — no reverse dependency
possible by construction.

## §10 Identity/Idempotency

Per surface: verdict identity = deterministic decision refs
(`classification-decision-{classify_hash}`,
`contradiction-decision-{cres_}`, `retract-decision-{id}`,
`curate-decision-{hash}`) AUTHORIALLY derived in callers (hash
builders stay — anti-seam); command/entity IDs derived in
gateway/repositories. Classification: CONSUMED (S-2h),
DERIVED (callers/gateway, unchanged), AUTHORED (gateway/repos,
unchanged), ENFORCED (gateway duplicate + idempotency keys,
unchanged). Repeated submission today: duplicate (not refusal,
not new row) — preserved because S-2h keeps check-then-append
and callers keep unconditional proceed-to-intent. No new
UUID/hash generation anywhere in S-2h scope.

## §11 Journal/Replay Semantics

Events per V-a verdict: at most one `HumanDecisionReceived`
(correlation = decision ref) + gateway admission/audit events;
order HD-before-intent is load-bearing (gateway dereferences
the decision). S-2h preserves call position, so order is
identical; duplicate path (existing row → skip append) is
identical. `IntentApplied` (including on duplicates) stays in
gateway (`:3832`) — S-2h cannot move or duplicate it (never
imports gateway). Append-only untouched; replay unaffected
(no timestamps authored — clock passed through; no randomness).

## §12 Persistence Boundary

Touched operations: one conditional `events` INSERT via the
existing `_append_event_to_db` (same module it already comes
from). Read: one existence SELECT. Tx owner: the caller's
(none opened by S-2h). Connection owner: the caller (object
passed through). Commit owner: unchanged (gateway/repo txs).
Project scoping: explicit param, same predicate shape.
Identity/idempotency constraints: unchanged (caller + gateway
own them). No DG-5 dependency: S-2h imports one function from
`persistence.repositories` (append path both sides already use);
it adds no research→persistence edge beyond the existing one
and no persistence→research edge at all.

## §13 N9/Retracted-Source Safety

Trace: retracted source → S5 decision + `supersedes` edge →
`source_artifact_retracted()` → False at substrate resolver,
in-tx ownership check, derivation skip, validator None. S-2h
touches none of these (no resolver, no admission, no
predicate — verified by symbol inventory of the helper).
S-2h cannot create a classification path (zero intents, zero
writes except the HD event it already writes today), cannot
accept a retracted source, cannot bypass admission (it precedes
it, unconditionally), creates no alternate verdict path (4
call sites, same callers). N9 suite (21 tests) exercises the
fenced paths S-2h preserves; S-2h changes no N9-covered line.

## §14 Project Isolation

`project_id` explicit in the helper signature; callers pass
`self._project_id` as today; the existence SELECT filters
`project_id = ?`; the append writes the same field. No global
project, no fallback (missing/empty correlation behaves as
today — callers always pass derived non-empty refs), no cache,
no cross-project mutation (single-row conditional insert
scoped by the caller's project).

## §15 Exception/Refusal Semantics

Inventory per surface: input-shape `MALFORMED_PAYLOAD`/`VERDICT`
(pre-lock, data); `OPERATOR` (pre-lock, data); `RATIONALE`
(pre-lock, data); `LOCK` (data); gateway codes (data);
`TRANSITION` (resolve_human_gate catch-all, data);
`SourceRetractionError` RAISED (audit surface only, unchanged);
journal-append failure RAISED through (all four V-a —
pinned by P7 test for classification). Persisted: only
refusal envelopes are data; raised exceptions persist nothing
(lease released in `finally`; gateway txs roll back).
Retryable: `LOCK` (explicit); replays idempotent via
correlations. Replay-visible: HD + admission events only.
S-2h preserves the trichotomy exactly: it raises nothing new,
catches nothing, returns bool ignored by callers —
exception ≠ refusal ≠ mutation, byte-for-byte.

## §16 API/Visibility

`record_*`/`resolve_*` signatures, return shapes, and refusal
codes unchanged (wrappers untouched — only bodies delegate
one step). New module INTERNAL: no `__all__`, no package
export, no docs-as-surface (docstring states internal seam),
no test imports of it required (behavioral tests via
Controller). A-05 holds: no SUPPORTED/EVOLVING change.

## §17 Proposed S-2 Shape (authorized unit only)

New module `src/hermes/research/verdict_decisions.py`:
`record_human_decision_once(*, conn, clock, project_id,
correlation_id, caused_by, reason, payload) -> bool`
(check-exists → conditional `_append_event_to_db`, else
return False). Controller: 4 call sites replaced (8 lines →
1 line each, same position). Imports added: one function-level
import per site (house precedent for cycle safety) or one
top-level import (no cycle exists — either; specify top-level
`from hermes.research.verdict_decisions import
record_human_decision_once` since repositories↛new-module).
Returns: bool (ignored, as today). Context: caller-owned conn
(fenced as today), clock, project. Ownership stays: tx with
callers+gateway, lease with Controller, authority split
unchanged, gateway owns admission, persistence owns append
primitive, identity with callers/gateway. Tests: additive
`tests/test_verdict_decisions.py` — idempotent double-record
(one event), failure propagation (mock append raising →
propagates, zero partial), per-surface equivalence via
EXISTING suites (P6 27, chg1 authority, S5, step7 — no moves).
Files allowed: new module + 4 controller hunks + 1 test file.
Commit: one seam, one commit, suite + P6/N9 slices green.
Rollback: single revert. REJECTED as non-seams: generic
VerdictService, DI container, lifecycle manager, whole-surface
moves, V-b/V-c/V-d changes, renames.

## §18 Anti-Seams (must NOT move)

Lease acquire/release + fence lifecycle (S-6 RED heart);
credential acquisition/verification; HumanDecision BINDING
semantics (which decision binds which command — per surface);
`apply_intent` + gateway validators + their txs; journal
append primitive ownership; identity/hash derivation;
idempotency enforcement points; recovery state machine; tick
orchestration + pass ordering; dispatch/handlers/retries/gates;
floor/ladder evaluate→persist pairs; N9 substrate/in-tx/
validator/predicate; S5 cascade; STALE/duplicate guards;
provider transport; migration set; event catalog; V-b intent
construction (bound to per-kind gateway contracts); V-c own-tx
+ mode follow-up; V-d audit/raising surfaces (DG-2 naming
precondition still open). Each owns a tx, lease interaction,
authority check, or identity derivation per §§7–13.

## §19 Characterization-Test Design

V1 verdict equivalence: existing per-surface suites (P6 27,
chg1 authority, S5 follow-on, step7 curation, controller gate/
credential tests) — reference, do not duplicate. V2 authority
ordering: existing OPERATOR/LOCK/PROPOSAL tests + one additive
test asserting HD precedes intent (event_id ordering on a
fresh verdict). V3 refusal equivalence: existing code-matrix
tests. V4 transaction equivalence: no new tx in helper
(code inspection) + journal-failure rollback test (exists for
classification; add one for a second surface — resolution).
V5 lease/fence: existing LOCK tests + fence tests untouched.
V6 identity: existing hash/duplicate tests. V7 duplicates:
existing duplicate-True tests per surface. V8 journal: HD
event count on fresh + repeat verdict (1 then still 1) —
additive. V9 isolation: existing cross-project tests. V10 N9:
existing 21-test suite (helper is N9-orthogonal by
construction — assert no N9-line changes via diff audit).

## §20 Multi-Agent Safety

Donor `controller.py`: single agent, 4 hunks + 1 import only.
New module: single owner, helper + docstring only. Gateway,
repositories, `source_outcomes.py` (N9 predicate): PROTECTED
(zero changes). Tests: one new file, additive only; no edits
to existing suites. Design gates serialize: S-2h lands alone;
S-2-adjacent work (retraction naming, V-b/V-c/V-d) explicitly
excluded from the commit. Full suite + P6/N9 slices required.

## §21 DG-3A Pass Criteria

Responsibility: S-2h is genuine (single rule: one decision
event per command hash — §5) ✓; per-surface moves rejected,
not bundled ✓. Dependency: zero UNKNOWN (every callee
inventoried) ✓; direction Controller → helper → repositories-
append (acyclic, verified) ✓. Lease/fence: bracket known
(§7 table), nothing moves ✓; no stale-fence risk (no
lifecycle) ✓. Authority: ordering known (verify → lock → HD →
intent) ✓; fail-closed preserved ✓; no pre-authority mutation
(earliest write stays post-verify) ✓. Gateway: authoritative
untouched ✓; no reverse dep (helper never imports gateway) ✓.
Identity: ownership unchanged ✓; no alternate path (helper
takes correlation as input) ✓. Journal: append-only ✓; replay
untouched ✓. Persistence: tx ownership explicit (caller's)
✓; no DG-5 dependency (no new research↔persistence edge) ✓.
N9: no bypass (§13 proof) ✓. Isolation: scoped (§14) ✓. API:
signatures/codes preserved; no new publics (§16) ✓. Tests:
C-requirements concrete (§19; existing suites mapped) ✓.
Implementation: seam exact (§17) ✓; one-commit boundary ✓;
multi-agent safe (§20) ✓; revertible (no migration/state) ✓.

## §22 Adversarial Review

Scope note: per-surface moves are REJECTED findings below
(marked [REJ]), the authorized helper is what PASS applies to.
1. Real boundary? PASS (one rule, 4 identical shapes, §5).
2. All 10 one responsibility? FAIL [REJ] — four shapes
(V-a…V-d); this FAIL is WHY per-surface moves are rejected,
not a block on the helper. 3. Orchestration, not verdict?
PASS (helper does no orchestration; orchestration stays).
4. Live tx dependency? PASS (runs inside caller's; owns none).
5. Lease/fence lifecycle? PASS (untouched). 6. Move fence
validation? PASS (none in scope). 7. Move a commit? PASS
(none in scope). 8. Rollback change? PASS (same tx, same
handlers). 9. Authority ordering? PASS (position preserved).
10. Mutation before HD? PASS (helper IS the HD step, called
at the same point). 11. Gateway bypass? PASS (untouched,
still called after). 12. Duplicate Gateway? PASS (no gateway
code in helper). 13. Second identity path? PASS (inputs only).
14. Idempotency change? PASS (check-then-append verbatim).
15. Journal order? PASS (same call position). 16. Replay?
PASS (nothing replay-visible added). 17. N9 bypass? PASS
(§13). 18. Refusal codes? PASS (untouched envelopes).
19. Exception propagation? PASS (no catch added).
20. Isolation? PASS (§14). 21. Accidentally public? PASS
(no `__all__`, INTERNAL). 22. Cycle? PASS (verified acyclic).
23. Characterization sufficient? PASS (§19 + existing suites).
24. Protected files untouched? PASS (§20 list). 25. Reason NOT
to proceed? PASS (none — helper is safe, scoped, specified).
Result: 24 PASS + 1 scoped FAIL[REJ] (per-surface moves
rejected by design); 0 blocking FAIL, 0 AMBIGUOUS.

## §23 Residual Risks / Preconditions

(a) The helper MUST keep the exact check-then-append shape —
any "improvement" (e.g. swallowing append errors, branching on
the return) voids this authorization. (b) DG-2 naming
precondition (retraction-surface readability) remains open
for future work, unaffected by S-2h (neither surface moves).
(c) V-b/V-c/V-d surfaces are NOT authorized for extraction
under this gate — future proposals must re-prove each.
(d) If a fifth verdict surface appears, it must reuse the
helper or document why not (convention, enforced by review).

## §24 Final Verdict

```text
DG-3A — S-2 DESIGN GATE PASSED / IMPLEMENTATION AUTHORIZED
```
