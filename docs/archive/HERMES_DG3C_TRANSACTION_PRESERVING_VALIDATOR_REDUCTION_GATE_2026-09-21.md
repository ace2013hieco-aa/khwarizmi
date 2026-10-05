# HERMES DG-3C — Transaction-Preserving Large-Validator Reduction Design Gate

**Date:** 2026-09-21
**Report path:** `docs/archive/HERMES_DG3C_TRANSACTION_PRESERVING_VALIDATOR_REDUCTION_GATE_2026-09-21.md`
**Baseline:** `dffe90738bfda63aa5567d32163b30e3d04f3a41`
**Nature:** READ-ONLY DESIGN GATE. No production, test, config, or dependency change.

---

## 1. Executive verdict

```text
DG-3C — DESIGN GATE PASSED / REDUCTION AUTHORIZED
```

**Exactly one implementation target is authorized:** the S5 downstream transitive-closure
step at `src/hermes/research/gateway.py:1225-1235` inside `_validate_retract_source`,
extracted as **one module-level pure helper in `gateway.py`** (`_s5_cone_closure`).

**Why only one.** A mechanical impurity census over all 32 module-level functions and
all five transaction-owning validators finds **exactly one** non-trivial contiguous
region that is simultaneously pure (no connection, no I/O, no refusal, no clock, no
hash, no event, no identity authorship), semantically self-contained, and independently
testable. Everything else in the five targets is refusal-bearing validation, transaction
or write work, journal work, or identity authorship — moving any of it would move one of
the eight protected invariants.

**Why it qualifies.** The helper is a pure function whose entire input surface is
`(source_artifact_id, downstream)`; it never receives `conn`. Extraction therefore
*structurally removes* its ability to touch a transaction, a lock, a refusal, an event,
or an identity — the strongest available form of boundary hardening. No existing test
imports it, no Controller path reaches it, and its semantics are already characterized
indirectly by ~21 existing cascade tests plus the S6 digest-reproduction tests.

**Honest cost/benefit.** This is a small, high-confidence reduction (~11 lines moved,
net file length approximately +14 lines because the helper carries a signature and a
contract docstring). The value is boundary hardening, explicit naming of the S5 closure
responsibility, and direct unit testability — **not** line count, which this gate
explicitly rejects as a criterion. If the reviewer prefers zero structural motion for
zero structural gain, `NO SAFE REDUCTION` is the defensible alternative; the candidate
is safe but modest, and the report says so rather than overselling it.

**Nothing else is authorized.** In particular: no second validator reduction, no split of
any `BEGIN … COMMIT/ROLLBACK` pair, no refusal relocation, no identity relocation, no
journal reordering, no persistence or Controller change, no DG-5/DG-6/DG-4/S-3 work.

---

## 2. Baseline identity

| Item | Value | Verified by |
|---|---|---|
| Repository | `https://github.com/ace2013hieco-aa/khwarizmi-research.git` | `git remote -v` |
| Branch | `main` | `git branch --show-current` |
| `HEAD` | `dffe90738bfda63aa5567d32163b30e3d04f3a41` | `git rev-parse HEAD` |
| `origin/main` | `dffe90738bfda63aa5567d32163b30e3d04f3a41` | `git fetch` + `git rev-parse origin/main` |
| `HEAD == origin/main` | yes | equality check |
| Working tree | clean; 0 tracked modifications | `git status --porcelain=v1` |
| Untracked (pre-existing, recorded) | `IDEA.md`, `Prompts/`, `orci.json`, `orhead.json`, `ortree.json` | same |
| Artifact under audit | `src/hermes/research/gateway.py` — 3714 lines, 32 module-level functions, 5 `BEGIN IMMEDIATE` owners | `wc -l`, AST census |

Nothing in the working tree differs from the certified baseline; no untracked material was
touched, staged, deleted, renamed, or reinterpreted.

---

## 3. Certification-chain verification

| Commit | Role | Present in ancestry |
|---|---|---|
| `dffe907` | S-3 certification (current baseline) | `HEAD` |
| `df57650` | S-3 implementation (L2 extraction) | yes (`git merge-base --is-ancestor`) |
| `65e82c0` | DG-3B design gate | yes |
| `6e1458c` | S-2 certification | yes |
| `3cfaa38` | S-2 implementation | yes |

* `docs/archive/HERMES_S3_L2_RESOLUTION_EXTRACTION_CERTIFICATION_2026-09-20.md` exists (1 match).
* S-3 is certified: `src/hermes/research/l2_resolution.py` exists, `gateway.py:73` imports
  `_l2_resolve_upstream` from it, and the L2 slice collects **59** tests.
* This gate modifies nothing. It does not re-open S-2, S-3, N9, or any certified seam.

**Constraints treated as source-backed (not merely asserted by prior reports):** the five
gateway `BEGIN IMMEDIATE` owners are physically present at `:520, :1120, :2033, :2391,
:2624`; the Controller imports gateway privates at `controller.py:1996` and
`controller.py:3080`; only two test files import gateway privates
(`tests/test_s5_retraction.py` → `_S5_DEPENDENCY_EDGE_TYPES`;
`tests/test_n9_retraction_admission.py` → `_cx_resolve_evidence_ref`).

---

## 4. Transaction-owner inventory

All five owners run on the caller-supplied `conn`, open `BEGIN IMMEDIATE` themselves, and
close with `COMMIT` or a guarded `ROLLBACK`. All five also carry the duplicated
`except GatewayRejection/except Exception → if conn.in_transaction → ROLLBACK → raise`
idiom.

| Function | Span | Lines | BEGIN | COMMIT | ROLLBACK sites | Connection | Owner |
|---|---|---:|---:|---:|---|---|---|
| `_decision_append_transactional` | 499-549 | 51 | 520 | 545 | 531, 537, 548 | caller `conn` | tx owner (primitive) |
| `_validate_retract_source` | 1000-1445 | 446 | 1120 | 1424 | 1129, 1159, 1427, 1431 | caller `conn` | tx owner |
| `_validate_curate_knowledge` | 1497-2187 | 691 | 2033 | 2169 | 2046, 2075, 2081, 2092, 2098, 2112, 2172, 2176 | caller `conn` | tx owner |
| `_validate_record_contradiction` | 2300-2512 | 213 | 2391 | 2495 | 2400, 2406, 2423, 2434, 2439, 2450, 2498, 2502 | caller `conn` | tx owner |
| `_validate_contradiction_resolution` | 2524-2690 | 167 | 2624 | 2676 | 2631, 2642, 2655, 2679, 2683 | caller `conn` | tx owner |

No other module-level function opens a transaction: the remaining >90-line functions
(`_validate_record_classification` 235, `_validate_source_spec` 183,
`_validate_resolve_classification_proposal` 158, `_validate_propose_classification_action`
152, `_validate_evidence_transition` 132, `_validate_propose_research_program` 121,
`_validate_record_scope_review_decision` 105, `apply_intent` 102, `_payload_to_node` 92)
have **zero** `BEGIN` sites and delegate their writes to repository-owned transactions.

**Statement-level timeline (retraction — the largest path), from the in-tx statement map:**

```text
payload/authority/identity validation (pre-tx, refusals)   1057-1119
BEGIN IMMEDIATE                                            1120
duplicate check (read → ROLLBACK → duplicate)              1122-1137
STALE guard (read → ROLLBACK → refuse)                     1143-1165
decision artifact + supersedes edge (WRITE)                1169-1198
cone edge read + L2 normalization (READ)                   1205-1224
PURE CLOSURE (no I/O)                                      1225-1235   ← candidate
artifact invalidation (READ+WRITE)                         1237-1258
task invalidation (READ+WRITE+Event)                       1265-1290
Step-7 curated follow-on (READ+WRITE+Event)                1302-1345
CHG-1 contradiction supersession (READ+WRITE+Event)        1355-1381
S6 bounded payload digest (pure compute + Event)           1398-1423
COMMIT                                                     1424
guarded ROLLBACK handlers                                  1425-1432
result construction                                        1434-1445
```

---

## 5. Validator responsibility map

Method disclosure: the census below is mechanical (AST walk over module-level functions;
per-statement "impurity" = any call to `conn.execute` / `_reject` / `_append_event_to_db` /
`clock` / `hashlib` / `json.dumps` / `EventType` / `TaskStatus` / repository methods /
identity helpers, plus `import` and `raise`). A statement is *inert* only if it contains
none of those. Known limitation, stated honestly: the marker list must be complete enough
to cover each file's helper vocabulary — the classification validator's local closures
(`_req_str`/`_opt_str`/`_req_str_list`, `2748-2773`) initially looked inert because they
are named with local abbreviations; a manual pass confirmed all three raise `_reject`, so
their 15-statement block at `2784-2798` is **refusal-bearing, not inert**. All headline
classifications below were confirmed by reading the source, not by the scan alone.

| Function | Pre-transaction region | Transaction region | Post-transaction region | Responsibility mix |
|---|---|---|---|---|
| `_decision_append_transactional` | json import only (`518`) | `520-549` (one `Try`) | none | one-verdict check + append, one atomic primitive |
| `_validate_retract_source` | `1057-1119` refusal chain + HumanDecision read (`1088-1093`) + source resolve (`1103-1104`) + `retraction_id` hash (`1110-1116`) | `1120-1424` | `1434-1445` result | admission + 6-table cascade + journal |
| `_validate_curate_knowledge` | `1545-2032` refusal chain + credential check + identity derivation (`curation_command_hash`, `curated_id_of`) + payload construction + payload-cap check | `2033-2169` | `2179-2187` result | admission + registry/basis/supersession writes + 2 events |
| `_validate_record_contradiction` | `2325-2390` refusal chain + pre-tx pair rule | `2391-2495` (N9 re-resolve inside) | `2504-2512` result | admission + insert + optional head supersession + 2 events |
| `_validate_contradiction_resolution` | `2541-2623` refusal chain + operator existence + `resolution_id` identity + HumanDecision read | `2624-2676` | `2685-2690` result | admission + status ladder + 1 event |
| `_cx_classification_facts` | — | `2246-2297` (N9 predicate; read-only) | — | N9 protection (imported by its test) |
| `_cx_resolve_evidence_ref` | — | `2209-2243` (N9 predicate; read-only) | — | N9 protection (imported by its test) |
| `_resolve_ratified_proposal` | `712-779` (read-only) | — | — | Controller-imported (`controller.py:3080`) |
| `_contradiction_resolution_id` | pure derivation | — | — | Controller-imported (`controller.py:1996`) |
| `_canonical_or_none` / `_resolve_program_in_project` / `_is_*_spec` | pure/narrow helpers | — | — | already minimal |

**Inert-run census across the whole module** (maximal runs of ≥3 consecutive inert
statements): 20 of 32 functions contain such a run, but every one resolves to one of:
(a) docstring/alias preambles, (b) payload-alias blocks whose calls raise refusals,
(c) repository-delegating sequences, or (d) the single closure block. Only
`gateway.py:1225-1235` is a non-trivial pure computation.

---

## 6. `_decision_append_transactional` analysis

**Verdict: NOT-A-SEAM (it already *is* the extracted primitive).**

* Structure: `499-549`; `BEGIN IMMEDIATE` at `520`, prior-read at `521-527`,
  duplicate/conflict `ROLLBACK`+return at `531-539`, `_append_event_to_db` at `541`,
  `COMMIT` at `545`, `except Exception → ROLLBACK → raise` at `546-549`.
* It is the F6 one-verdict atomicity mechanism: the check and the append must be in the
  same immediate transaction, which is precisely why it exists as a function.
* Callers: three, all internal — `:683` (resolve-classification-proposal path), `:896`
  (evidence-transition path), `:3015` (scope-review path). **No Controller caller, no test
  importer.**
* Identity: none authored. Duplicate behavior: `verdict_key=None` = existence-only mode
  (transition admissions), otherwise a `verdict_key` compare → `appended`/`duplicate`/`conflict`.
* Its body is a single `Try` with no inert region: there is nothing to reduce inside it
  without either splitting the transaction or duplicating the one-verdict rule.
* Per §17's default: **do not extract.** No seam demonstrated.

---

## 7. Retraction analysis (`_validate_retract_source`, 1000-1445)

**Verdict: RED for every region except the closure block (GREEN).**

| Region | Lines | Class | Why it cannot move |
|---|---|---|---|
| payload contract + unknown-key check | 1057-1082 | pre-tx refusal | raises `MALFORMED_PAYLOAD` ×5 (codes live in gateway) |
| HumanDecision dereference | 1088-1093 | pre-tx read + refusal | refusal precedence (`PROPOSAL` beats source resolution — pinned by `test_missing_decision_beats_source_resolution`); moving risks reordering |
| `_s5_source_artifact_id` resolve | 1103-1104 | pre-tx read + refusal | fail-closed source typing; refusal code |
| `retraction_id` derivation | 1110-1116 | pre-tx identity AUTHOR | sha256 of the canonical command — identity authorship |
| duplicate check | 1122-1137 | in-tx read → ROLLBACK | duplicate semantics + tx state |
| STALE guard | 1143-1165 | in-tx read → ROLLBACK → refuse | state-dependent refusal inside the tx |
| decision artifact + supersedes edge | 1169-1198 | in-tx WRITE + identity (`decision_hash`) | write ownership + identity authorship |
| cone edge read + L2 normalization | 1205-1224 | in-tx READ | reads inside the tx; ordering |
| **cone closure** | **1225-1235** | **PURE** | **candidate (see §18/§19)** |
| artifact invalidation | 1237-1258 | in-tx READ+WRITE | mutates rows; idempotence marker |
| task invalidation | 1265-1290 | in-tx READ+WRITE+Event | writes `tasks` + `TaskInvalidated`; ordering before SourceRetracted |
| Step-7 curated follow-on | 1302-1345 | in-tx READ+WRITE+Event | writes `curated_knowledge_*` (gateway is sole writer) |
| CHG-1 supersession | 1355-1381 | in-tx READ+WRITE+Event | writes `contradictions` (gateway is sole writer) |
| S6 digest + `SourceRetracted` | 1398-1423 | compute + Event | journal ordering; digest is the S6 commitment |
| commit/rollback/result | 1424-1445 | tx control | transaction ownership |

Dependency classification of the whole cascade: P0 = `conn, intent, clock`; P1 =
`source_ref, reason, human_decision_ref, source_artifact_id, retraction_id`; T0 = every
`conn.execute` read; T1 = the writes and their returned ids; A0 = the HumanDecision row;
I0 = `retraction_id`/`decision_artifact_id`/`decision_hash`; J0 = four event appends;
R0 = `IntentResult`/`_reject`. No block has UNKNOWN dependencies.

---

## 8. Curation analysis (`_validate_curate_knowledge`, 1497-2187)

**Verdict: RED.** 691 lines, 55 refusal sites, one transaction.

* Stages 1-27 (`1545-2032`, pre-tx) are a single refusal chain: 46 of the 55 refusals are
  here (`EVIDENCE_REF` ×18, `MALFORMED_PAYLOAD` ×13, `PROVENANCE` ×8, `PROPOSAL` ×4,
  `ROLE` ×3, `STALE` ×2, `PROJECT_NOT_FOUND` ×1). Every stage is a guard whose failure
  path *is* the refusal — extraction would require the refusal factory or a duplicated
  vocabulary (the DG-3B §13 finding, re-confirmed here from source).
* Identity authorship sits in the pre-tx region: `curation_command_hash(payload)` and
  `curated_id_of(entry_kind, recomputed_signature, canonical_decision_ref)` (~`1978`), plus
  `recomputed_signature` from the persisted binding. Moving = RED (§13 of the gate brief).
* The in-tx region (`2033-2169`) is one `Try`: duplicate check, SUPERSEDE target ladder,
  identity-collision guard, registry insert, basis inserts, optional supersession
  insert + status flip, `CuratedKnowledgeProposed`, `CuratedKnowledgeAdmitted`, COMMIT.
  9 of the 55 refusals are in-tx (4 `STALE`, 2 `PROPOSAL`, … ) — all state-dependent.
* The pre-tx `admission_payload`/`proposed_payload` literals (`1984-2009`) are pure but
  are single dict constructions consumed by the in-tx events: extracting them is
  cosmetics, not a responsibility boundary → NOT-A-SEAM.
* `_resolve_ratified_proposal` is imported by the Controller (`controller.py:3080`) and
  is explicitly out of scope.

---

## 9. Contradiction analysis (`_validate_record_contradiction`, 2300-2512)

**Verdict: RED.**

* Pre-tx (`2325-2390`): refusal chain (11 sites: `MALFORMED_PAYLOAD` ×5, `PROPOSAL` ×3,
  `EVIDENCE_REF` ×2, `PROJECT_NOT_FOUND` ×1) plus `_cx_classification_facts` pair facts.
* In-tx (`2391-2495`): duplicate/supersede-link check (ROLLBACK+return), then **N9
  re-resolution of both parties' evidence inside the write transaction** (`2416`, `2418`)
  with a rollback+`EVIDENCE_REF` refusal, then the optional head-only supersession ladder
  (`STALE` ×2 in-tx), then the `contradictions` insert, the optional target status flip,
  `ContradictionSuperseded`, `ContradictionDetected`, COMMIT. 5 of 16 refusals are in-tx.
* The N9 re-derivation is a *deliberate* property: "the detector must not trust upstream
  filtering." Any extraction that moved it outside the transaction would break N9 →
  **RED, protected invariant**.
* DG-3B called this "cohesive — RED (tx + sole writer)". This gate re-derives the same
  conclusion from the current source, and adds the in-tx refusal count as evidence.

---

## 10. Resolution analysis (`_validate_contradiction_resolution`, 2524-2690)

**Verdict: RED.**

* Pre-tx (`2541-2623`): 13 of 15 refusals (`MALFORMED_PAYLOAD` ×5, `PROPOSAL` ×6,
  `OPERATOR` ×1), the operator-credential existence check (`2560-2566`), and identity
  authorship `resolution_id = _contradiction_resolution_id(contradiction_id)` (`2581`) —
  the same function the Controller imports at `controller.py:1996` and uses at `~2008`.
* In-tx (`2624-2676`): the status ladder — RESOLVED → duplicate-or-refuse (`PROPOSAL`,
  with its own `ROLLBACK`), SUPERSEDED → refuse (`STALE`), else `UPDATE … status='RESOLVED'`
  guarded on `status='OPEN'`, then `ContradictionResolved`, COMMIT.
* Every in-tx branch rolls back before refusing: the refusal *is* a transaction action.
  No inert region of any size exists (the only 3-statement inert run, `2527-2542`, is the
  docstring plus `kind`/`payload` aliases).
* Moving `_contradiction_resolution_id` would force a Controller edit → prohibited.

---

## 11. Controller interaction

| Gateway symbol | Controller use | Consequence for this gate |
|---|---|---|
| `apply_intent` | 10 call sites (`1094, 1164, 1462, 1539, 1634, 1767, 1902, 1994, 2119`, …) | public surface, untouched |
| `GatewayRejection` | same imports | untouched |
| `_contradiction_resolution_id` | `controller.py:1994-1998` import; used at `~2008` to derive `decision_ref` **outside** any gateway call | **RED** — moving it requires a Controller edit, which the gate prohibits |
| `_resolve_ratified_proposal` | `controller.py:3080` import; called at `3109` on `self._fenced` inside the obligation-apply loop | **RED** — Controller + fenced-connection coupling |

No Controller call reaches any private helper of the five target validators, and no
candidate below changes a signature, a connection, or a fence. **This gate authorizes no
Controller change.**

---

## 12. Authority map

Actual ordering (re-derived from source, not assumed):

```text
apply_intent
  → _require_role(intent)                       (gateway.py:151-189; ROLE refusals)
  → dispatch by kind
      _validate_retract_source:
          payload schema → HumanDecision deref (project-scoped, fail-closed)
          → source resolution (type-checked, in-project fail-closed)
          → [BEGIN] duplicate → STALE → cascade
      _validate_curate_knowledge:
          payload schema → role/kinds → credential EXISTS → HumanDecision deref
          → decision-payload binding (curation_id == full-command hash)
          → program/hypothesis/ladder/classification re-derivation
          → [BEGIN] duplicate → SUPERSEDE ladder → inserts → events
      _validate_record_contradiction:
          payload schema → detector_version/pair rule (pre-tx)
          → [BEGIN] duplicate/supersede-link → N9 evidence re-resolve → insert → events
      _validate_contradiction_resolution:
          payload schema → operator credential EXISTS → HumanDecision deref (binding resolution_id)
          → [BEGIN] status ladder → update → event
```

Every credential/operator/HumanDecision check is **pre-transaction and fail-closed**; the
only in-transaction authority-adjacent decisions are state-dependent refusals
(`STALE`, `PROPOSAL`, `EVIDENCE_REF`). Any candidate that could move an authority check
later, earlier, or across a transaction boundary is RED. The selected candidate contains
no authority code at all (§19).

---

## 13. Refusal map

93 refusal sites across the four big validators (`_decision_append_transactional` raises
none — it reports `duplicate`/`conflict` as data):

| Validator | Sites | pre-tx | in-tx | Codes used |
|---|---:|---:|---:|---|
| `_validate_retract_source` | 7 | 6 | 1 | `MALFORMED_PAYLOAD`×5, `PROPOSAL`×1, `STALE`×1 |
| `_validate_curate_knowledge` | 55 | 49 | 6 | `EVIDENCE_REF`×18, `MALFORMED_PAYLOAD`×13, `PROVENANCE`×8, `PROPOSAL`×6, `ROLE`×3, `STALE`×6, `PROJECT_NOT_FOUND`×1 |
| `_validate_record_contradiction` | 16 | 11 | 5 | `MALFORMED_PAYLOAD`×5, `PROPOSAL`×5, `EVIDENCE_REF`×3, `PROJECT_NOT_FOUND`×1, `STALE`×2 |
| `_validate_contradiction_resolution` | 15 | 13 | 2 (+1 rollback-only branch) | `MALFORMED_PAYLOAD`×5, `PROPOSAL`×8, `OPERATOR`×1, `STALE`×1 |

Vocabulary: **16 codes** — `ROLE, UNKNOWN_KIND, NOT_WIRED, PROJECT_NOT_FOUND,
MALFORMED_PAYLOAD, SCOPE_NOT_GOVERNED, NOT_COMPILED, STALE, BUDGET, DEPENDENCY,
IDEMPOTENCY_CONFLICT, PROVENANCE, CLASSIFICATION_REF, PROPOSAL, EVIDENCE_REF, OPERATOR`
(`gateway.py:93-108`).

Classification of the four categories this gate cares about: **INPUT** =
`MALFORMED_PAYLOAD`; **AUTHORITY** = `ROLE`, `OPERATOR`; **STATE/CONFLICT/DUPLICATE** =
`STALE`, `PROPOSAL`, `EVIDENCE_REF` (state-dependent, in-tx); **PROJECT** =
`PROJECT_NOT_FOUND`. A helper that could change which of these fires first, or whether it
fires inside or outside the transaction, is RED. The selected candidate raises nothing and
contains no refusal site.

---

## 14. Identity map

| Identity | Where authored | Class | Moveable? |
|---|---|---|---|
| `retraction_id` (`"retract_" + sha256(canonical command)[:24]`) | `1110-1116` (pre-tx) | AUTHOR | RED |
| `decision_artifact_id` = `f"rd-{retraction_id}"` | `1169` (in-tx) | AUTHOR | RED |
| `decision_hash` (sha256 of canonical decision JSON) | `1170-1177` (in-tx) | AUTHOR | RED |
| `cone_digest` (S6 `s5-cone-v1` commitment) | `1398-1405` (in-tx) | AUTHOR (commitment) | YELLOW — pure compute, but hash authorship |
| `curation_command_hash` (full-command hash) | pre-tx (~`1978`) | AUTHOR | RED |
| `curated_id_of(kind, signature, decision_ref)` | pre-tx (~`1978`) | AUTHOR | RED |
| contradiction `contradiction_id` (`contradiction_id_of`) | pre-tx (`2350` region) | AUTHOR | RED |
| `resolution_id` = `_contradiction_resolution_id(...)` | pre-tx (`2581`) | AUTHOR | RED (Controller-imported) |
| `classification_content_matches(...)` | `_cx_classification_facts` | VERIFY | RED (N9) |
| `source_artifact_retracted(...)` | `_cx_resolve_evidence_ref` | VERIFY | RED (N9) |
| `artifact_id`/`content_hash`/`task_id` reads | throughout | CONSUME/LOOKUP | — |

Pattern check requested by §13 of the gate brief: curate performs
`canonicalize → hash → derive ID → BEGIN` (all pre-tx); retract performs
`resolve → hash → BEGIN → derive decision id/hash`. The two orderings differ, are
deliberate, and are **not** collapsed by this gate.

---

## 15. Journal / replay map

| Validator | Event order inside the transaction |
|---|---|
| `_decision_append_transactional` | one append (`541`) — `IntentApplied`/`IntentRejected` audit usage |
| `_validate_retract_source` | `TaskInvalidated` (`1280`) → `CuratedKnowledgeInvalidated` (`1331`) → `ContradictionSuperseded` (`1371`) → `SourceRetracted` (`1406`) → COMMIT |
| `_validate_curate_knowledge` | `CuratedKnowledgeProposed` (`2152`) → `CuratedKnowledgeAdmitted` (`2161`) → COMMIT |
| `_validate_record_contradiction` | `ContradictionSuperseded` (`2473`, conditional) → `ContradictionDetected` (`2483`) → COMMIT |
| `_validate_contradiction_resolution` | `ContradictionResolved` (`2666`) → COMMIT |
| `Apply intent` audit | gateway appends `IntentApplied`/`IntentRejected` in its own transaction after admission (module docstring) |

No candidate may reorder these. The selected candidate contains **zero** event references
and no call that can append, reject, or log; state mutation remains strictly after the
closure and before the appends. Replay determinism is carried by the existing tests named
in §20.

---

## 16. N9 analysis (dedicated)

N9 is the retraction-admission protection: a classification must not be admissible on the
strength of evidence that a committed retraction has retired, and the detector must
re-verify that property inside the writing transaction rather than trusting upstream
filtering.

Source evidence:

* `_cx_classification_facts` (`2246-2297`) re-derives program/hypothesis/failure-class and
  resolves evidence, returning `None` for corrupt/forged/invalidated/foreign rows.
* `_cx_resolve_evidence_ref` (`2209-2243`) resolves typed refs project-scoped and returns
  `None` when `source_artifact_retracted(conn, project_id, artifact_id)` is true — the N9
  retraction predicate is consumed here.
* `_validate_record_contradiction` calls `_cx_classification_facts` **inside** the
  transaction (`2416`, `2418`) with a rollback+`EVIDENCE_REF` refusal on
  non-qualification after the pre-tx pair rule has already passed.
* The retraction path itself calls none of the `_cx_*` predicates; it consumes the cone.

**Trace requested by §15 of the brief:**

```text
source retraction decision (HumanDecision deref, fail-closed)
  → retraction persistence (decision artifact + supersedes edge)
  → source artifact outcome (INVALIDATED marker on cone members)
  → downstream resolution (cone via L2 normalization + closure)
  → classification admission (N9 re-resolve via _cx_classification_facts)
```

**Conclusion:** the selected candidate touches **none** of this. It computes set
membership from an adjacency map that the caller already produced in-transaction; it calls
no `_cx_*`, consults no retraction state, and cannot make post-retraction evidence look
valid. N9 remains byte-for-byte untouched (`_cx_*` is explicitly listed RED below).

---

## 17. Project-isolation analysis

| Query | Scope mechanism | Line |
|---|---|---|
| HumanDecision deref | `WHERE project_id = ? AND event_type = ?` | `1089-1093` |
| source resolution | in-project artifact lookup (`_s5_source_artifact_id`) | `1103` |
| cone edge read | `JOIN artifacts a … WHERE a.project_id = ?` | `1206-1211` |
| artifact invalidation | keyed by canonical ids already filtered by the JOIN | `1237-1258` |
| task invalidation | `JOIN tasks t … AND t.project_id = ?` | `1267-1270` |
| curated follow-on | `e.source_project_id = ?` | `1319-1324` |
| contradiction supersession | `WHERE project_id = ? AND status='OPEN'` | `1358-1364` |
| curate: program/hypothesis/credential | project-scoped lookups + credential existence | pre-tx chain |
| contradiction record | pre-tx pair rule project-scoped; N9 re-resolve passes `intent.project_id` | `2416-2418` |
| resolution | `WHERE contradiction_id = ? AND project_id = ?` | `2626-2628` |

The selected candidate performs no query at all — it receives the adjacency map the
caller built from a project-filtered JOIN (§9 of the brief: a resolved upstream is only a
match key; a foreign project's dependent rows can never enter the map). Project isolation
is therefore preserved *by construction*, not merely by convention. `test_21_cross_project_isolation`,
`test_a7_cross_project_collision`, and `test_cross_project_source_rejected` already pin it.

---

## 18. Candidate reduction table

Legend for "preserved?": ✅ by construction, ⚠️ conditional (needs design), ❌ would change.

| # | Candidate | Function | Region | Mechanism | Tx | Authority | Identity | Journal | Refusal | Isolation | Verdict |
|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| C-1 | **S5 downstream closure** | `_validate_retract_source` | 1225-1235 | module-local **pure** helper | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **GREEN** |
| C-2 | S6 cone digest commitment | `_validate_retract_source` | 1398-1405 | module-local pure helper | ✅ | ✅ | ⚠️ hash authorship | ✅ | ✅ | ✅ | YELLOW |
| C-3 | cone edge read + L2 normalization | `_validate_retract_source` | 1205-1224 | transaction-participating helper | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ | YELLOW (reads in-tx; no gain) |
| C-4 | payload schema/unknown-key chain | `_validate_retract_source` | 1057-1082 | pre-tx helper | ✅ | ⚠️ refusal factory | ✅ | ✅ | ❌ | ✅ | RED |
| C-5 | HumanDecision deref | `_validate_retract_source` | 1088-1093 | pre-tx helper | ✅ | ⚠️ precedence | ✅ | ✅ | ❌ | ✅ | RED |
| C-6 | `retraction_id` derivation | `_validate_retract_source` | 1110-1116 | pre-tx helper | ✅ | ✅ | ❌ AUTHOR | ✅ | ✅ | ✅ | RED |
| C-7 | artifact invalidation loop | `_validate_retract_source` | 1237-1258 | in-tx helper | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ | RED (writes) |
| C-8 | task invalidation block | `_validate_retract_source` | 1265-1290 | in-tx helper | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ | RED (writes + event ordering) |
| C-9 | curated follow-on | `_validate_retract_source` | 1302-1345 | in-tx helper | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ | RED (sole writer, journal) |
| C-10 | contradiction supersession | `_validate_retract_source` | 1355-1381 | in-tx helper | ⚠️ | ✅ | ✅ | ✅ | ✅ | ✅ | RED (sole writer, journal) |
| C-11 | 31-stage curate validation | `_validate_curate_knowledge` | 1545-2032 | pre-tx helper chain | ✅ | ❌ | ❌ | ✅ | ❌ (46 refusals) | ⚠️ | RED |
| C-12 | curate identity derivation | `_validate_curate_knowledge` | ~1978 | pre-tx helper | ✅ | ✅ | ❌ AUTHOR | ✅ | ✅ | ✅ | RED |
| C-13 | curate payload dicts | `_validate_curate_knowledge` | 1984-2009 | local helper | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | NOT-A-SEAM (cosmetic) |
| C-14 | curate in-tx duplicate/supersede ladder | `_validate_curate_knowledge` | 2034-2112 | in-tx helper | ⚠️ | ✅ | ✅ | ✅ | ❌ (in-tx precedence) | ✅ | RED |
| C-15 | pre-tx pair rule | `_validate_record_contradiction` | 2325-2390 | pre-tx helper | ✅ | ✅ | ✅ | ✅ | ❌ (N9 adjacency) | ✅ | RED |
| C-16 | in-tx N9 evidence re-resolve | `_validate_record_contradiction` | 2416-2418 | any | ❌ | ❌ | ✅ | ✅ | ❌ | ⚠️ | RED (**N9 protected**) |
| C-17 | `_cx_classification_facts` | N9 predicate | 2246-2297 | any | n/a | n/a | n/a | n/a | n/a | n/a | RED (N9 + test import) |
| C-18 | `_cx_resolve_evidence_ref` | N9 predicate | 2209-2243 | any | n/a | n/a | n/a | n/a | n/a | n/a | RED (N9 + test import) |
| C-19 | resolution status ladder | `_validate_contradiction_resolution` | 2624-2676 | in-tx helper | ⚠️ | ✅ | ✅ | ✅ | ❌ in-tx | ✅ | RED |
| C-20 | `resolution_id` derivation | `_validate_contradiction_resolution` | 2581 | pre-tx helper | ✅ | ✅ | ❌ AUTHOR | ✅ | ✅ | ✅ | RED (Controller-imported) |
| C-21 | `_decision_append_transactional` | — | 499-549 | any | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | NOT-A-SEAM |
| C-22 | `_resolve_ratified_proposal` | — | 712-779 | module move | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | RED (Controller-imported) |
| C-23 | `_require_role` | — | 151-189 | any | n/a | ❌ | ✅ | ✅ | ✅ | ✅ | NOT-A-SEAM (it *is* the authority boundary) |
| C-24 | `_canonical_or_none`, `_is_*_spec`, `_resolve_program_in_project` | — | 1486-1494, 3210-3302, 1459-1483 | already helper-sized | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | NOT-A-SEAM |

**Exactly one GREEN candidate: C-1.**

---

## 19. Minimum safe reduction

**Selected: C-1 — the S5 downstream transitive-closure step.**

| Property | Value |
|---|---|
| Function | `_validate_retract_source` |
| Source range | `src/hermes/research/gateway.py:1225-1235` (11 lines, 5 statements: `cone` init, `seen`, `stack`, `while`-BFS, `cone.sort()`) |
| Free inputs (fully characterized) | `source_artifact_id` (P1, derived pre-tx at `1103-1104`), `downstream` (T0-derived adjacency built in-tx at `1220-1224`) |
| Locals written | `cone`, `seen`, `stack`, `artifact_id` |
| Calls | `sorted`, `downstream.get`, `stack.pop`, `stack.extend`, `seen.add`, `cone.append`, `cone.sort` — no `conn`, no `_reject`, no `clock`, no `hashlib`, no `EventType`, no repository, no identity helper |
| Output | `cone` — sorted, de-duplicated, seed-excluded reachable-node list |
| Input mutation | none (`downstream.get` only; no `setdefault`) |
| Determinism | output is sorted; traversal order affects only de-duplication bookkeeping, so the result is a pure function of `(seed, adjacency)` |
| Destination | **module-level private function in `gateway.py`** (no new module, no `__all__` change, no import change, no package export) |
| Proposed symbol | `_s5_cone_closure(source_artifact_id: str, downstream: dict[str, list[str]]) -> list[str]` |
| Call site | exactly one — `1225-1235` becomes `cone = _s5_cone_closure(source_artifact_id, downstream)` |
| Callers affected | 1 (the retract validator); no test, script, or Controller caller exists |
| Estimates | 11 lines removed from the validator; ~24 lines added at module level (def + contract docstring + the 11 moved statements verbatim + `return cone`); net file change ≈ **+14 lines** |
| New files | none |
| Public API | none (module-private, `__all__` unchanged at three names) |
| Controller / persistence / schema / config | unchanged |

**Semantic-preservation rule for the future implementation:** the five statements move
verbatim (same identifiers, same traversal algorithm including `stack.pop(0)`, same
`sorted()` at each level, same final `cone.sort()`), with only two mechanical additions —
the `def` wrapper and a trailing `return cone`. No algorithm cleanup, no complexity
"fix", no ordering change, and no added validation, logging, caching, or types beyond the
signature annotation.

**Why this and not something larger:** §24 requires the *smallest* safe candidate. C-1 is
the minimum non-trivial pure region in the entire module (the next-smallest candidates are
3-statement alias/normalizer blocks that exist only to feed an adjacent refusal).
It is also the only candidate that reduces the *impurity surface* of the cascade rather
than relocating it: after extraction the algorithm cannot see `conn`, so it cannot open a
transaction, take a lock, issue a write, raise a refusal, or append an event — the failure
modes this gate exists to prevent become structurally unavailable.

**Latent observation recorded, explicitly NOT authorized:** the inline BFS duplicates the
concept of `hermes/core/graph.py:276 artifact_blast_radius` (used by the Controller at
`controller.py:716-745`); the retract docstring's reference to "the artifact_blast_radius
traversal (graph.py)" is stale (there is no `research/graph.py`). Unifying the two is a
**behavior change** and is prohibited here; it is recorded only so a future gate can
consider it deliberately.

---

## 20. Characterization-test requirements

**Pre-move gate (required first, mirroring S-3 §24.1).** Run the cascade slice green
before touching production code — the moved statements are already exercised through the
cascade's observable outputs:

| Property | Existing proven evidence (unchanged tests) |
|---|---|
| closure: direct children | `test_s5_retraction.py::test_direct_dependent_invalidated` |
| closure: multi-level | `test_s5_retraction.py::test_multi_level_chain`, `test_s5_l2_resolution.py::test_17_task_input_cone` |
| closure: branching / diamond de-dup | `test_branching_graph_multiple_branches`, `test_shared_dependency_no_duplicate_invalidation`, `test_22_duplicate_aliases_single_invalidation`, `test_a10_duplicate_aliases` |
| closure: empty | `test_empty_cone`, `test_s6_event_capacity.py::test_20_empty_cone_digest`, `test_25_empty_cone_reconstruction` |
| closure: cycle termination + seed exclusion | `test_23_cycle_terminates`, `test_a11_cycle_terminates` |
| closure: unreachable nodes untouched | `test_unrelated_nodes_untouched`, `test_20_sibling_production_excluded` |
| closure: non-dependency edges never propagate | `test_non_dependency_edge_never_propagates` |
| closure: project isolation | `test_21_cross_project_isolation`, `test_a7_cross_project_collision`, `test_cross_project_source_rejected` |
| closure: determinism / replay | `test_14_repeated_resolution_deterministic`, `test_29_replay_deterministic`, `test_a5_replay_identical`, `test_a4_historical_graph` |
| closure: scale | `test_a12_large_cone`, `test_s6_event_capacity.py::test_44_large_cone_no_rejection`, `test_46_10x_baseline_cone` |
| closure: cone reproducibility from state + digest | `test_21_artifact_markers_reproduce_cone`, `test_22_task_records_reproduce_cone`, `test_23_curated_records_reproduce_cone`, `test_24_recalculated_digest_matches`, `test_18_duplicate_aliases_stable_digest` |
| tx/rollback/journal unchanged | `test_mid_cascade_failure_writes_nothing`, `test_s6_event_capacity.py::test_27_persistence_failure_rolls_back`, `test_event_ordering_and_causality`, `test_payload_carries_cascade_record` |
| authority fail-closed unchanged | `test_missing_human_decision_fail_closed`, `test_missing_decision_beats_source_resolution`, `test_retract_source_is_internal_only`, `test_agent_roles_rejected` |
| duplicate semantics unchanged | `test_identical_repeat_is_duplicate_with_zero_effects`, `test_repeat_preserves_single_source_retracted_event`, `test_second_different_retraction_is_stale` |

**Additive pins (3, all post-move; the symbol does not exist pre-move):**

1. **C-DG3C-1 — pure closure semantics.** Drive the helper directly with hand-built
   adjacency maps and assert: empty adjacency → `[]`; direct child; multi-level chain;
   diamond de-dup; cycle termination; a seed reachable back through a cycle is **excluded**
   (the `seen` seed guard); an adjacency entry naming a node absent from the map is
   skipped, never `KeyError`; disjoint component unreachable from the seed never appears;
   output sorted; repeated calls equal.
2. **C-DG3C-2 — purity / structural containment.** Assert the helper's signature exposes
   no connection (no parameter named `conn`), that a second call with the same adjacency
   dict returns an equal result **and leaves the dict unchanged** (no input mutation), and
   that the function source contains no `conn`/`_reject`/`clock`/`hashlib`/`EventType`/
   `append_event` token. This is the guard that stops a future agent from quietly
   re-importing I/O into the extracted unit.
3. **C-DG3C-3 — call-site equivalence.** The single call site must produce the same cone;
   proven by the unchanged cascade slice of §20-1 plus a targeted assertion that the
   retraction result's `invalidated_artifacts` equals the sorted closure of the seeded
   in-transaction adjacency for a graph that exercises all three edge types.

**Not authorized:** any modification, weakening, renaming, or reinterpretation of the
existing tests named above; any new test that simply re-asserts what they already pin.

---

## 21. Explicit RED regions

RED = preserve intact; do not touch in any future implementation authorized by this gate.

1. `_validate_retract_source` pre-tx region `1057-1119` (refusals + HumanDecision deref +
   source resolution + `retraction_id` authorship).
2. `_validate_retract_source` tx control: `BEGIN` `1120`, duplicate `1122-1137`, STALE
   `1143-1165`, `COMMIT` `1424`, rollback handlers `1425-1432`.
3. Decision artifact / supersedes edge writes `1169-1198` (identity authorship inside).
4. Artifact invalidation `1237-1258`, task invalidation `1265-1290`, curated follow-on
   `1302-1345`, contradiction supersession `1355-1381`.
5. S6 digest + `SourceRetracted` emission `1398-1423`.
6. `_validate_curate_knowledge` stages `1545-2032` and the whole in-tx region `2033-2169`.
7. `_validate_record_contradiction` `2325-2390` and `2391-2495` (N9 re-resolve inside).
8. `_validate_contradiction_resolution` `2541-2676`.
9. `_cx_classification_facts` `2246-2297` and `_cx_resolve_evidence_ref` `2209-2243` (**N9**).
10. `_contradiction_resolution_id`, `_resolve_ratified_proposal` (Controller-imported).
11. `_decision_append_transactional` `499-549`.
12. The 16 refusal codes `93-108`, `_reject`, `GatewayRejection`, `IntentResult`,
    `apply_intent`, `gateway.__all__`, and every intent/event/schema/migration surface.
13. All four duplicated `except … ROLLBACK` idioms (not "normalized", not moved).
14. `s5-cone-v1` digest algorithm, the S6 payload cap handling, and the L2 resolution
    contract (certified in S-3).

---

## 22. Explicit non-goals

* No second reduction; no large-validator split; no C-01a "step helper" program.
* No `BEGIN`/`COMMIT`/`ROLLBACK` movement or splitting; no transaction-participating
  helper from a transaction owned by another function.
* No refusal relocation, no refusal-code duplication, no lazy "reach back" into gateway's
  refusal factory.
* No identity/canonicalization/hash relocation; no digest extraction (C-2 stays YELLOW).
* No journal reordering, no `IntentApplied` movement, no event-construction movement.
* No N9 change of any kind; no `_cx_*` extraction or relocation.
* No Controller, persistence, migration, schema, intent, event, or config change; no DG-5
  inversion work; no DG-6 invariant work; no DG-4 repository split; no S-3 re-work.
* No dependency injection, service objects, registries, workflow engines, or new modules.
* No cosmetic cleanup, no rename sweeps, no import cleanup, no comment modernization, no
  line-length targets, no SQL rewrite, no traversal optimization (including the O(n²)
  `stack.pop(0)` — preserved verbatim by design).
* No unification of the inline BFS with `core/graph.py:artifact_blast_radius`.

---

## 23. Adversarial 30-question review

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Mistake line count for architectural coupling? | **PASS** | The two largest validators (691/446) are RED on refusal/write/identity grounds, not size; the authorized candidate is the *smallest* pure region found, and the report states its payoff is modest (§1, §18, §19) |
| 2 | Mistake a read for a transaction-independent read? | **PASS** | Every in-tx read is retained in place; the candidate performs no read at all (§7, §19) |
| 3 | Move anything that depends on SQLite isolation? | **PASS** | Candidate has no SQL; the duplicate/STALE/N9 reads stay inside their transactions (§4, §9) |
| 4 | Change lock acquisition timing? | **PASS** | `BEGIN IMMEDIATE` lines `520/1120/2033/2391/2624` untouched; candidate sits *after* BEGIN and cannot affect acquisition (§4) |
| 5 | Change authority ordering? | **PASS** | Authority chain re-derived and recorded (§12); candidate contains no authority code |
| 6 | Change refusal precedence? | **PASS** | 93 refusal sites mapped with pre/in-tx classification (§13); candidate raises nothing |
| 7 | Change exception propagation? | **PASS** | Pure function of built-ins; the guarded rollback handlers remain byte-identical (§4, §21) |
| 8 | Change rollback behavior? | **PASS** | No transaction control in the candidate; `test_mid_cascade_failure_writes_nothing` and `test_27_persistence_failure_rolls_back` stay green (§20) |
| 9 | Change journal ordering? | **PASS** | Event appends at `1280/1331/1371/1406/2152/2161/2473/2483/2666` untouched (§15) |
| 10 | Change duplicate behavior? | **PASS** | Duplicate checks are in-tx reads in the validators (§4, §7); candidate precedes no duplicate check |
| 11 | Move identity authorship? | **PASS** | Identity map (§14) lists every AUTHOR site as RED; candidate authors nothing |
| 12 | Duplicate canonicalization? | **PASS** | No canonicalization exists in the candidate; none is added |
| 13 | Alter N9 semantics? | **PASS** | §16 trace; `_cx_*` untouched; candidate consults no retraction state |
| 14 | Alter project isolation? | **PASS** | §17; candidate receives an already project-filtered adjacency map |
| 15 | Require Controller changes? | **PASS — no** | The two Controller-coupled symbols (`_contradiction_resolution_id`, `_resolve_ratified_proposal`) are both RED (§11) |
| 16 | Require persistence changes? | **PASS — no** | Candidate calls no repository; §21 RED list covers all write paths |
| 17 | Create a new public API? | **PASS — no** | Module-private function; `__all__` unchanged; no new module, no docs entry |
| 18 | Create a module cycle? | **PASS — no** | No import is added or changed (§19) |
| 19 | Merely relocate complexity instead of reducing coupling? | **PASS (qualified)** | Honest qualification in §1/§19: the gain is structural (the extracted unit cannot reach `conn`, refusals, clock, hash, or journal), not a line-count or coupling-metric win |
| 20 | Identify a smaller safe seam? | **PASS** | Mechanically searched all 32 functions; remaining inert runs are ≤3 statements and exist only to feed adjacent refusals (§5, §18 C-13) |
| 21 | Any apparently safe seam that is TOCTOU-sensitive? | **PASS (flagged)** | C-3 (cone edge read, `1205-1224`) is YELLOW precisely because moving a read could invite re-snapshotting; C-1 avoids the question by containing no read (§18) |
| 22 | Distinguish transaction ownership from participation? | **PASS** | §4 labels all five owners; C-1 is neither owner nor participant (no `conn`); C-3 is participation-only and was rejected as valueless |
| 23 | Preserve the refusal vocabulary? | **PASS** | 16 codes recorded; none moved, duplicated, or renamed (§13) |
| 24 | Preserve fail-closed behavior? | **PASS** | All credential/HumanDecision/source/pair checks remain pre-tx and fail-closed (§12) |
| 25 | Could journal-failure semantics change? | **PASS — no** | No journal call in the candidate; fail-closed tests unchanged (§20) |
| 26 | Could duplicate semantics change? | **PASS — no** | Duplicate paths untouched; duplicate pins unchanged (§20) |
| 27 | Could replay determinism change? | **PASS — no** | Candidate is a deterministic pure function; replay pins unchanged (§20) |
| 28 | Could concurrent calls observe different state? | **PASS — no** | Candidate reads no state; the caller's in-tx reads and the `BEGIN IMMEDIATE` serialization are unchanged (§4) |
| 29 | Could a future agent misread the extracted helper as transaction-independent in a harmful way? | **PASS (guarded)** | The helper *is* transaction-independent (pure), and C-DG3C-2 forbids I/O/refusal/clock/hash tokens from creeping in; the docstring must state that the adjacency map comes from the caller's in-transaction reads (§19, §20) |
| 30 | Should the validators simply remain intact? | **ANSWERED — mostly yes** | Four of the five targets, and every RED/YELLOW row, remain intact; only the single mechanically-verified pure region moves, and §1 records the defensible `NO SAFE REDUCTION` alternative for a reviewer who prefers zero motion |

Unresolved answers: **none**. Two explicitly *qualified* answers (19, 30) are recorded as
qualifications rather than failures, because the gate's own criteria for C-1 are met in
full and the honest cost/benefit is disclosed.

---

## 23b. Validation record

This gate is design-only: it modified exactly one file (this report, untracked at
validation time) and no production, test, config, or dependency file.

| Gate | Command | Result |
|---|---|---|
| Full suite | `.venv/Scripts/python.exe scripts/run_tests.py -q` | 100% progress, **0 FAILED/ERROR markers, exit code 0** (the pytest summary line is suppressed by the host-venv teardown quirk documented in `scripts/run_tests.py:5-8`) |
| Collected count | `python -m pytest --collect-only -q` | **2054 tests** — identical to the S-3 certified count (2051 baseline + 3 S-3 pins) |
| Ruff | `uvx ruff check src tests` | `All checks passed!` |
| Pyright (source profile, strict) | `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| Project validation profile | `./scripts/profiled_gate.sh` | `profiled typecheck + walking-skeleton smoke: OK` (exit 0); tests profile `0 errors, 1 warning` — the pre-existing `tests/test_research_program.py:141` `reportSelfClsParameterName` warning, present on the certified baseline, in an untouched file |
| Whitespace | `git diff --check` | clean |
| Working tree | `git status --porcelain=v1` | this report plus the five known untracked items; 0 tracked modifications |

No production code was modified to make anything green, and no tooling configuration was
touched.

---

## 24. Final authorization statement

```text
DG-3C — DESIGN GATE PASSED / REDUCTION AUTHORIZED
```

Authorization is strictly limited to **one** implementation target:

* **Function:** `_validate_retract_source` (`src/hermes/research/gateway.py:1000-1445`)
* **Region:** `src/hermes/research/gateway.py:1225-1235` — the S5 downstream transitive
  closure (`cone` init, `seen`, `stack`, BFS `while`, `cone.sort()`)
* **Destination:** one module-level private helper **inside `gateway.py`**
  (`_s5_cone_closure(source_artifact_id: str, downstream: dict[str, list[str]]) -> list[str]`);
  **no new file**, no new import, no `__all__` change, no package export
* **Allowed caller change:** exactly one line — the region becomes
  `cone = _s5_cone_closure(source_artifact_id, downstream)`
* **Allowed test changes:** the three additive pins of §20 (C-DG3C-1, C-DG3C-2, C-DG3C-3);
  **no existing test may be modified, weakened, renamed, or reinterpreted**
* **Prohibited changes:** everything in §21 (RED regions) and §22 (non-goals) — in
  particular any transaction/refusal/identity/journal/N9/persistence/Controller/schema
  movement, any second reduction, and any further validator reduction
* **Characterization tests:** §20, run green before the move and after it
* **Required proof for certification:** AST-identity of the four moved statements plus the
  added `return cone`; unchanged `BEGIN`/`COMMIT`/`ROLLBACK` line ownership; the full
  cascade slice green; the full suite green; Ruff, Pyright (src strict),
  `scripts/profiled_gate.sh`, and `git diff --check` green

No other validator reduction is authorized by this gate. A second reduction requires a
separate gate. In particular, this authorization does **not** cover C-2 (cone digest),
C-3 (cone edge read), any pre-transaction validation chain, any in-transaction write
block, the contradiction or resolution paths, `_decision_append_transactional`, the
`_cx_*` N9 predicates, or `_resolve_ratified_proposal`.

```text
DG-3C — DESIGN GATE PASSED / REDUCTION AUTHORIZED
```
