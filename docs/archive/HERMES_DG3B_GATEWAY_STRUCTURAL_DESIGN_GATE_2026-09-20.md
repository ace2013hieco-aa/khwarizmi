# DG-3B — Gateway Structural Design Gate (read-only)

Baseline `HEAD == origin/main == 6e1458c042b907dfa511e557d2cb269ab98060b9`.
Scope: `src/hermes/research/gateway.py` decomposition eligibility.
This gate changed exactly one file: this report. No production, test,
config, or dependency change (verified §1/§17/§23).

## §0 Executive decision

```text
DG-3B — GATEWAY DESIGN GATE PASSED / IMPLEMENTATION AUTHORIZED
```

Authorization is limited to **one** seam (§18): the L2 upstream-reference
resolution family (`_l2_lookup_artifact_by_hash`, `_l2_resolve_ref_to_artifacts`,
`_l2_task_spec_refs`, `_l2_task_outputs`, `_l2_resolve_upstream`, plus
`_L2_HASH_TYPED_PREFIXES`; `gateway.py:950-1103`) may move to one internal,
stdlib-only module. Nothing else is authorized.

Why this is the only seam: the gateway is not uniformly structured. It contains
**five gateway-owned `BEGIN IMMEDIATE` transactions** (§7), four of which are the
**sole write path for four tables** (`contradictions`, `curated_knowledge_entries`,
`curated_knowledge_retraction_basis`, `curated_knowledge_supersession`; §13/§15),
and 213 structured refusal sites whose vocabulary is imported by ~20 test files
and the Controller (§16). Any seam that owns a transaction, owns a write, authors
an identity, or raises a refusal carries relocation cost that makes it
ineligible today. The L2 family carries none of those: it is pure, read-only,
refusal-free, transaction-free, identity-consuming, and its storage-representation
knowledge has a ratified owner (the S5 L2 design gate) and a dedicated 56-test
suite.

Honest value statement: this move removes 154 lines (4.0%) of gateway.py and does
**not** reduce any admission-semantic risk. Its value is ownership hygiene plus
the durable negative map this gate produces (§13/§17/§22), which proves which
gateway responsibilities must stay.

## §1 Baseline identity (hard stop check)

| Check | Value | Result |
|---|---|---|
| Repository | `github.com/ace2013hieco-aa/khwarizmi-research` | PASS |
| Branch | `main` | PASS |
| `HEAD` | `6e1458c042b907dfa511e557d2cb269ab98060b9` | PASS |
| `origin/main` (fetched) | `6e1458c042b907dfa511e557d2cb269ab98060b9` | PASS |
| `HEAD == origin/main` | equal | PASS |
| Descended from `6e1458c` | `git merge-base --is-ancestor` → YES | PASS |
| S-2 certification commit present | `git log`: `6e1458c docs(archive): certify S-2 …` ← `3cfaa38 refactor(controller): extract S-2 …` ← `fe0aa1c docs(archive): complete DG-3A …` | PASS |
| Working tree | 5 known untracked items only: `IDEA.md`, `Prompts/`, `orci.json`, `orhead.json`, `ortree.json` | PASS |
| Tracked modifications | none (`git status --porcelain` shows `??` only) | PASS |

The untracked items were not modified, staged, renamed, or reinterpreted.

## §2 Certification-chain verification

Read and re-derived against source, not assumed:

* `AGENTS.md` (109 lines) — invariants: determinism owns control; single
  mutation path `apply_intent`; append-only journal; replay determinism;
  human-authority fail-closed boundary (`PROPOSAL`); 4 KiB payload discipline;
  project isolation; content-hash identity; N1/N9 frozen; lease-fenced writer;
  "no direct SQL mutation outside repository write boundaries, each of which
  owns its `BEGIN IMMEDIATE` transaction"; canonical test/lint/typecheck
  commands; "split only mechanically, with the owning gate re-run per split"
  (`docs/ARCHITECTURE.md` §3.10).
* `docs/ARCHITECTURE.md` (231 lines) — layer map (§3.2: gateway "sole writer
  `apply_intent:3732`", "re-derives identity, re-resolves refs"); primary write
  path (§3.3: `role gate → project gate → payload schema → credential-exists →
  HumanDecision dereference + hash binding → domain validators →
  repository.write (own `BEGIN IMMEDIATE`) → journal append → COMMIT`); §3.7
  N1/N9; §3.9 project isolation; §3.10 persistence→research debt (DG-5 owns);
  §3.11 "split only mechanically".
* `docs/API.md` (99 lines) — stability labels FROZEN-BY-DECISION / EVOLVING /
  INTERNAL / UNDECLARED; `apply_intent` is the sole mutation entry; refusal codes
  "EVOLVING in set but FROZEN in meaning once emitted"; all `_`-prefixed methods
  UNDECLARED; gateway validator internals INTERNAL.
* `docs/STATE.md` (77 lines) — CERTIFIED chain (P6 `ff79bb6`, N9 `02cb976` PR #1,
  P7, tick-loop `633cff1`+`2328399`, Phase 0 `adab69d`, Phase 1 `335d300`);
  known debt list; "bounded code-quality splits only with owning-gate re-runs;
  any invariant-adjacent change needs a design gate first".
* Phase 3 backlog (387 lines) — E-02 = this gate; DG-3 = "validator placement
  with tx-ownership proof; shared-helper ownership"; §9 matrix marks
  "validator placement: NO (DG-3 + tx-ownership proof)" and "journal/replay/
  identity/authorization/persistence direction: NO".
* DG-2 (388 lines) — controller gate precedent: mapping clusters, proving
  side-effect freedom, classification of dependencies, additive characterization
  when none exists, adversarial review, single-seam authorization.
* DG-3A (425 lines) — authorized only the S-2 controller-side HumanDecision
  idempotent-append seam; explicitly rejected per-surface verdict extraction.
* S-2 certification (335 lines) — `3cfaa38` (implementation) + `6e1458c`
  (certification); helper `src/hermes/research/verdict_decisions.py`
  (`record_human_decision_once`, no `__all__`, LF, INTERNAL); full suite 2051;
  CI run `35521366270` all jobs success; four V-a surfaces intact.

Source-backed constraints for this gate: (1) `apply_intent` is the only
mutation entry; (2) repositories/validators own their transactions and each
transaction's BEGIN and COMMIT stay together; (3) refusals are data with stable
code meanings; (4) identity is recomputed, never trusted or invented;
(5) journal is append-only and ordered; (6) project isolation fails closed;
(7) N1/N9 are frozen; (8) `_`-prefixed symbols are INTERNAL/UNDECLARED.

S-2 is untouched by this gate: no controller, no test, no documentation
reference to it changed. This gate does not modify any certified behavior.

## §3 Previous-report reconciliation (physical evidence wins)

Three previous claims were re-measured. Two are imprecise but immaterial; one
materially sharpens the design and is recorded as a standing finding.

**(a) Validator count — confirmed.** Phase 3 §3 corrected the original audit's
"~40 validators" to 14; the AST census confirms exactly **14** functions named
`_validate_*` plus one `_is_*`-style predicate family (not counted as validators).

**(b) Large-validator line counts — measurement-method variance, not a
contradiction.** C-01a cites `_validate_curate_knowledge` 712 lines
(`gateway.py:1652`) and `_validate_retract_source` 459 (`:1155`). AST-measured
spans are **691** lines (`1652-2342`) and **446** (`1155-1600`). The cited
numbers equal *region* spans that include the adjacent constant blocks
(`_CURATE_KNOWLEDGE_PAYLOAD_KEYS`, `_CONTRADICTION_TYPE`, …). Start lines are
exact; end lines differ by the measurement method. Immaterial: the seam
conclusions do not depend on ±21 lines.

**(c) "The contradiction pair is the one clean seam" — refined (§12).** The
contradiction *validators* are not separable (both own `BEGIN IMMEDIATE` and are
the sole writer of the `contradictions` table). The contradiction *fact pair*
(`_cx_resolve_evidence_ref`, `_cx_classification_facts`) is genuinely separable
but is not the cleanest seam: it is N9-adjacent and its entry point is imported
directly by the N9-owning certified test file. It is ranked YELLOW (§17), not
RED — but a cleaner candidate exists that the audit never evaluated as a
candidate: the L2 resolution family.

**(d) STANDING FINDING — "repositories own transactions" is an over-generalization.**
`AGENTS.md` ("no direct SQL mutation outside repository write boundaries, each of
which owns its `BEGIN IMMEDIATE` transaction"), `ARCHITECTURE.md` §3.3, and the
improvement audit ("each writer owns its BEGIN IMMEDIATE tx (33 sites repo-wide)")
describe the repository-owned model as universal. Physical source shows **three
transaction owners** on the certified write path:

1. repositories — `ProjectRepository.create:151`, `TaskRepository.create:389`,
   `EventRepository.append_transactional:784`, `ResearchProgramRepository.record:1232`,
   `EmptyResultArtifactRepository.record:2432`, `failure_classifications.record:127`,
   `source_outcomes.record:268`;
2. the gateway — five sites (§7), one of which (`_validate_retract_source`) also
   owns the sole write path for `contradictions` and the three
   `curated_knowledge_*` tables;
3. the Controller — `resolve_human_gate` opens `conn.execute("BEGIN")` and
   directly `UPDATE`s `tasks` (`controller.py:1357-1382`), out of DG-3B scope.

A repository *method* can also be transaction-participating rather than
transaction-owning: `ArtifactRepository.record` (`repositories.py:842-869`) and
`_append_event_to_db` (`repositories.py:92-125`) contain **no** `BEGIN`/`COMMIT`
and therefore run inside whatever transaction the caller holds — the same
contract the S-2 helper uses. Impact on this gate: it *strengthens* the RED
classification of the four transaction-owning validators (they are not merely
tx owners but architectural write owners), and it is the main reason the durable
outcome of DG-3B is the negative map rather than a decomposition plan. Gate
remains valid; the selected seam is unaffected (zero writes, zero transactions).

**(e) Precedent for transaction relocation.** `EventRepository.append_transactional`
(`repositories.py:784-824`) documents: "the gateway's audit/decision writes now
live here (B7), replacing the manual BEGIN/COMMIT/ROLLBACK the gateway used to
hold". The established direction is *downward into persistence*, with the
transaction staying owned by one function. DG-3B adopts that precedent: no seam
is approved whose transaction owner moves sideways into a sibling research
module.

## §4 Gateway responsibility map (physical)

`src/hermes/research/gateway.py` — 3868 lines, 86 top-level statements, CRLF.
Module docstring `:1-41`; imports `:42-88`; `__all__` `:90`
(`GatewayRejection`, `IntentResult`, `apply_intent`).

Structure (AST-measured):

| Kind | Count | Members |
|---|---|---|
| Classes | 2 | `GatewayRejection:119-129` (subclasses `IntentRejectedError`), `IntentResult:133-147` (frozen slots dataclass) |
| Entry | 1 | `apply_intent:3732-3833` (102 lines) |
| Validators | 14 | §5 |
| Helpers | 22 | §6 |
| Refusal codes | 16 | `:93-108` |
| Payload-key frozensets | 10 | `_TASK_PAYLOAD_KEYS:112`, `_CLASSIFICATION_ACTION_PAYLOAD_KEYS`, `_RESOLVE_PROPOSAL_PAYLOAD_KEYS`, `_EVIDENCE_TRANSITION_PAYLOAD_KEYS`, `_SCOPE_REVIEW_DECISION_PAYLOAD_KEYS`, `_RETRACT_SOURCE_PAYLOAD_KEYS`, `_CURATE_KNOWLEDGE_PAYLOAD_KEYS`, `_RECORD_CONTRADICTION_PAYLOAD_KEYS`, `_RESOLVE_CONTRADICTION_PAYLOAD_KEYS`, `_RECORD_CLASSIFICATION_PAYLOAD_KEYS` |
| Domain constants | 4 | `_S5_DEPENDENCY_EDGE_TYPES`, `_S5_SOURCE_ARTIFACT_TYPES`, `_S5_DECISION_ARTIFACT_TYPE`, `_L2_HASH_TYPED_PREFIXES:975-982`, `_CONTRADICTION_TYPE` |

### A. Admission entry (`apply_intent`)

`TypeError` guard for non-`Intent`; repository defaults (project/task/program);
then, **inside one `try`**, the admission order
`UNKNOWN_KIND` → `_require_role:3768` → `_require_project:3769` → `budget_check`
hook (`BUDGET`) → dispatch ladder `:3782-3815` → `else NOT_WIRED :3816-3824`.
Any rejection or exception appends `IntentRejected` via
`_append_audit_event(conn, clock, intent, applied=False)` (`:3826`, `:3829`) and
re-raises; success appends `IntentApplied` (`:3832`) and returns the result
(`:3833`). `apply_intent` opens no transaction of its own — the audit event is
appended by `EventRepository.append_transactional` in its own transaction
(`repositories.py:784-824`, docstring: "it is a record of the admission, never
a gate on it").

### B. Intent → validator → transaction → persistence → journal map

| Intent | Validator | Transaction owner | Journal write | Result event |
|---|---|---|---|---|
| `PROPOSE_RESEARCH_PROGRAM` | `:211-331` | `ResearchProgramRepository.record` | inside repo tx | `ResearchProgramCompiled` |
| `PROPOSE_CLASSIFICATION_ACTION` | `:339-490` | `EventRepository.append_transactional` | own tx (proposal-only intent; no state row) | `ClassificationActionProposed` |
| `RESOLVE_CLASSIFICATION_PROPOSAL` | `:551-708` | `_decision_append_transactional:498-548` | **gateway tx** | `ClassificationActionDecision` |
| `EVIDENCE_TRANSITION` | `:785-916` | `_decision_append_transactional` | **gateway tx** | `EvidenceTransitionProposed` |
| `RECORD_SCOPE_REVIEW_DECISION` | `:3094-3198` | `_decision_append_transactional` | **gateway tx** | `ScopeReviewDecided` |
| `RETRACT_SOURCE` | `:1155-1600` | **validator** (`BEGIN IMMEDIATE :1275`) | inside own tx | `SourceRetracted` (+`TaskInvalidated`, `ContradictionSuperseded`, `CuratedKnowledgeInvalidated`) |
| `CURATE_KNOWLEDGE` | `:1652-2342` | **validator** (`:2188`) | inside own tx | `CuratedKnowledgeProposed` + `…Admitted` |
| `RECORD_CONTRADICTION` | `:2455-2667` | **validator** (`:2546`) | inside own tx | `ContradictionDetected` (+`…Superseded`) |
| `CONTRADICTION_RESOLUTION` | `:2679-2845` | **validator** (`:2779`) | inside own tx | `ContradictionResolved` |
| `RECORD_CLASSIFICATION` | `:2857-3091` | `FailureClassificationRepository.record` | inside repo tx | none by design (audit + artifact row) |
| `INSERT_TASK` / `ADMIT_TASK` | `:3653-3727` | `TaskRepository.create` | inside repo tx | `TaskCreated` |
| 6 declared kinds | — | — | — | `NOT_WIRED` (`:3816-3824`) |

### C. Shared helpers (measured, not assumed)

Fan-in counted by AST across the whole module (a helper is "shared" only where
the call graph says so):

* `_reject:205-206` — fan-in **213** (whole-module refusal factory).
* `_require_role:150-188`, `_require_project:191-202` — fan-in 1 each
  (`apply_intent`). Not shared helpers: they are the entry gates.
* `_decision_append_transactional:498-548` — fan-in **3**
  (`_validate_resolve_classification_proposal`, `_validate_evidence_transition`,
  `_validate_record_scope_review_decision`).
* `_resolve_ratified_proposal:711-778` — fan-in **3** (same three validators
  plus `controller.py:3045,3080,3105`).
* `_l2_*` family — a single chain rooted at `_l2_resolve_upstream:1066-1103`
  (fan-in 1: `_validate_retract_source:1376`), internally
  `_l2_resolve_upstream → _l2_resolve_ref_to_artifacts (×3) → _l2_lookup_artifact_by_hash`,
  `→ _l2_task_spec_refs (×2)`, `→ _l2_task_outputs (×2)`.
* `_cx_resolve_evidence_ref:2364-2398` — fan-in 1 (`_cx_classification_facts`);
  `_cx_classification_facts:2401-2452` — fan-in 4 (all in
  `_validate_record_contradiction`).
* `_s5_source_artifact_id:1106-1152` — fan-in 1 (retract); raises 4 refusals.
* `_canonical_or_none:1641-1649` — fan-in 6, all inside
  `_validate_curate_knowledge`; `_resolve_program_in_project:1614-1638` —
  fan-in 1 (curate).
* `_contradiction_resolution_id:2670-2676` — fan-in 1 in-gateway **plus
  `controller.py:1996,2008`**.
* `_payload_to_node:3201-3292`, `_validate_provenance:3295-3362`,
  `_is_extract_spec:3365-3376`, `_validate_extract_source:3379-3439`,
  `_is_source_search_spec:3442-3449`, `_is_source_fetch_spec:3452-3457`,
  `_validate_source_spec:3460-3642`, `_task_exists:3645-3650` — the INSERT_TASK
  predicate family (fan-in 1 each from `_validate_insert_task`).
* `_append_audit_event:3836-3868` — fan-in 3 (`apply_intent`).
* Cross-module importers of private symbols (the de-facto internal surface),
  measured across `src/`, `tests/`, `scripts/`: `controller.py` imports
  `_resolve_ratified_proposal` and `_contradiction_resolution_id`;
  `tests/test_s5_l2_resolution.py:50` imports `_l2_resolve_upstream`;
  `tests/test_n9_retraction_admission.py:49` imports `_cx_resolve_evidence_ref`;
  `tests/test_s5_retraction.py:614-617` imports `_S5_DEPENDENCY_EDGE_TYPES`;
  `scripts/adversarial_probe_s5.py` imports five privates. Same-named symbols in
  `persistence/repositories.py`, `research/extraction.py` (`_is_extract_spec`,
  `_TASK_PAYLOAD_KEYS`) are *local definitions*, not gateway references
  (verified: neither file imports from `research.gateway`).

## §5 Validator inventory (14)

`R`/`W` = raw `conn.execute` reads/writes inside the validator; `Tx` =
transaction owner; `Auth` = credential and/or HumanDecision verification;
`Id` = identity work performed; `scope` = explicit `project_id` predicate on
its own queries; `journal` = event writes.

| # | Validator | Lines | Intent(s) | R/W | Tx | Auth | Id | scope | journal | Repo/helper dependencies |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `_validate_propose_research_program` | 211-331 | `PROPOSE_RESEARCH_PROGRAM` | 0/0 | repo | — | compiled content hash (research) | via repo | repo | `ResearchProgramRepository` (`resolve_scope_content_hash`, `superseded_program_ids`, `slot_vocabulary`, `get_by_hash`, `record`), `compile_from_payload`, lazy `PermittedAction` |
| 2 | `_validate_propose_classification_action` | 339-490 | `PROPOSE_CLASSIFICATION_ACTION` | 0/0 | repo | — | `prop_` sha256 id | yes (repo helpers) | `append_transactional` | `FailureClassificationRepository`, `ArtifactRepository`, `EventRepository`, research `failure_classification` |
| 3 | `_decision_append_transactional` (helper) | 498-548 | serves 3 intents | 1/0 | **gateway** | — | none (caller-built) | caller-provided | `_append_event_to_db` | — |
| 4 | `_validate_resolve_classification_proposal` | 551-708 | `RESOLVE_CLASSIFICATION_PROPOSAL` | yes | gateway (helper) | operator exists + decision binding | consumes `prop_` | yes | helper | `OperatorCredentialRepository`, `ArtifactRepository`, `EventRepository`, `_resolve_ratified_proposal` |
| 5 | `_validate_evidence_transition` | 785-916 | `EVIDENCE_TRANSITION` | yes | gateway (helper) | ratification ref | `tr_` sha256 id | yes | helper | research `evidence_transitions`, `_resolve_ratified_proposal` |
| 6 | `_validate_retract_source` | 1155-1600 | `RETRACT_SOURCE` | 7/6 | **gateway** (`:1275`) | HumanDecision deref | `retract_`, `rd-`, `s5-cone-v1` digest | yes (HumanDecision, artifacts, cone JOIN) | `_append_event_to_db` ×4 | `_s5_source_artifact_id`, `_l2_*`, `source_artifact_retracted` (indirect) |
| 7 | `_validate_curate_knowledge` | 1652-2342 | `CURATE_KNOWLEDGE` | 11/4 | **gateway** (`:2188`) | HumanDecision + command-hash binding | recomputes `curation_command_hash`, `curated_id`, signature, binding hash | yes | `_append_event_to_db` ×2 | `event_validation`, `evidence_ladder`, `feature_binding` (11 names) |
| 8 | `_validate_record_contradiction` | 2455-2667 | `RECORD_CONTRADICTION` | 4/2 | **gateway** (`:2546`) | — | consumes `contradiction_id_of` (research) | yes | `_append_event_to_db` ×2 | `_cx_classification_facts`, research `contradictions` |
| 9 | `_validate_contradiction_resolution` | 2679-2845 | `CONTRADICTION_RESOLUTION` | 3/1 | **gateway** (`:2779`) | operator exists + HumanDecision binding | `cres_` via helper | yes | `_append_event_to_db` | `OperatorCredentialRepository`, `_contradiction_resolution_id` |
| 10 | `_validate_record_classification` | 2857-3091 | `RECORD_CLASSIFICATION` | 1/0 | repo | operator exists + HumanDecision binding | `classification_command_hash` | yes | repo | `FailureClassificationRepository.record` (own tx), research `failure_classification` |
| 11 | `_validate_record_scope_review_decision` | 3094-3198 | `RECORD_SCOPE_REVIEW_DECISION` | yes | gateway (helper) | operator exists + ratification | consumes proposal id | yes | helper | research `scope_review`, `_resolve_ratified_proposal` |
| 12 | `_validate_provenance` | 3295-3362 | `INSERT_TASK`/`ADMIT_TASK` | 0/0 | — | — | deref by repo | yes (via repo row check) | — | `ResearchProgramRepository.get` |
| 13 | `_validate_extract_source` | 3379-3439 | `INSERT_TASK`/`ADMIT_TASK` (EXTRACT) | 0/0 | — | — | — | yes | — | `DatasetManifestRepository` |
| 14 | `_validate_source_spec` | 3460-3642 | `INSERT_TASK`/`ADMIT_TASK` (SOURCE_*) | 0/0 | — | — | — | yes | — | `TaskRepository.get`, `_source_artifact_resolves` |
| 15 | `_validate_insert_task` | 3653-3727 | `INSERT_TASK`/`ADMIT_TASK` | 0/0 | repo | — | — | via repo | repo | `TaskRepository.create`, `_payload_to_node`, validators 12-14 |

Count of functions named `_validate_*` = **14** (rows 1, 2, 4-15); row 3 is
the shared helper counted separately in §6. Read/write counts are raw-SQL
counts only; repository-mediated statements are shown as "repo".

## §6 Shared-helper inventory (22)

| Helper | Lines | Fan-in | Cross-module importers | Raises refusals | Classification |
|---|---|---|---|---|---|
| `_require_role` | 150-188 | 1 | — | yes ×4 | entry gate — NOT-A-SEAM |
| `_require_project` | 191-202 | 1 | — | yes | entry gate — NOT-A-SEAM |
| `_reject` | 205-206 | 213 | controller (indirect via codes) | factory | refusal machinery — NOT-A-SEAM |
| `_decision_append_transactional` | 498-548 | 3 | — | no | **owns a transaction** — RED |
| `_resolve_ratified_proposal` | 711-778 | 3 | `controller.py:3045,3080,3105` | no (returns None) | authority contract — RED |
| `_l2_lookup_artifact_by_hash` | 985-997 | 1 | — | no | selected seam — GREEN |
| `_l2_resolve_ref_to_artifacts` | 1000-1027 | 3 | — | no | selected seam — GREEN |
| `_l2_task_spec_refs` | 1030-1054 | 2 | — | no | selected seam — GREEN |
| `_l2_task_outputs` | 1057-1063 | 2 | — | no | selected seam — GREEN |
| `_l2_resolve_upstream` | 1066-1103 | 1 | `tests/test_s5_l2_resolution.py:50,119` | no | selected seam — GREEN |
| `_s5_source_artifact_id` | 1106-1152 | 1 | `scripts/adversarial_probe_s5.py:73` | yes ×4 | refusal-carrying resolver — NOT-A-SEAM (must not ride with the seam) |
| `_resolve_program_in_project` | 1614-1638 | 1 | — | no | too small / single caller — no value |
| `_canonical_or_none` | 1641-1649 | 6 (one validator) | — | no | too small / single validator — no value |
| `_cx_resolve_evidence_ref` | 2364-2398 | 1 | `tests/test_n9_retraction_admission.py:49,843,852` | no | N9-adjacent pair — YELLOW |
| `_cx_classification_facts` | 2401-2452 | 4 (one validator) | — | no | N9-adjacent pair — YELLOW |
| `_contradiction_resolution_id` | 2670-2676 | 1 | `controller.py:1996,2008` | no | authors identity + controller import — RED |
| `_payload_to_node` | 3201-3292 | 1 | — | yes ×12 | INSERT_TASK predicate family — YELLOW |
| `_is_extract_spec` | 3365-3376 | 1 | — | no | predicate family — YELLOW |
| `_validate_extract_source` | 3379-3439 | 1 | — | yes ×5 | predicate family — YELLOW |
| `_is_source_search_spec` / `_is_source_fetch_spec` | 3442-3457 | 2/1 | — | no | predicate family — YELLOW |
| `_validate_source_spec` | 3460-3642 | 1 | — | yes ×19 | predicate family — YELLOW |
| `_task_exists` | 3645-3650 | 1 | — | no | trivial — no value |
| `_append_audit_event` | 3836-3868 | 3 | — | no | audit writer (repo tx) — NOT-A-SEAM |

No helper is "shared" by assertion: every fan-in above is an AST call count.
The two genuinely multi-validator helpers (`_decision_append_transactional`,
`_resolve_ratified_proposal`) are disqualified by transaction ownership and by
the Controller's direct import, not by reuse.

## §7 Transaction-ownership map

Five gateway-owned transactions (all `BEGIN IMMEDIATE`, each BEGIN/COMMIT pair
inside one function — never split):

| Symbol | BEGIN | COMMIT | ROLLBACKs | Callers |
|---|---|---|---|---|
| `_decision_append_transactional` | 519 | 544 | 530, 536, 547 | validators 4, 5, 11 |
| `_validate_retract_source` | 1275 | 1579 | 1284, 1314, 1582, 1586 | `apply_intent` |
| `_validate_curate_knowledge` | 2188 | 2324 | 2201, 2230, 2236, 2247, 2253, 2267, 2327, 2331 | `apply_intent` |
| `_validate_record_contradiction` | 2546 | 2650 | 2555, 2561, 2578, 2589, 2594, 2605, 2653, 2657 | `apply_intent` |
| `_validate_contradiction_resolution` | 2779 | 2831 | 2786, 2797, 2810, 2834, 2838 | `apply_intent` |

Repository-owned transactions reached from validators: `ProjectRepository.create:151`
(`BEGIN`/`COMMIT`/`ROLLBACK`), `TaskRepository.create:389`, `EventRepository.append_transactional:784`
(plain `BEGIN`; `retry_without_project` re-BEGINs on FK failure),
`ResearchProgramRepository.record:1232`, `EmptyResultArtifactRepository.record:2432`,
`FailureClassificationRepository.record:127`, `SourceOutcomeRepository.record:268`.

Transaction-participating (no BEGIN of their own): `_append_event_to_db:92-125`
and `ArtifactRepository.record:842-869`. `apply_intent` opens no transaction:
its `IntentApplied`/`IntentRejected` audit rows are appended by
`_append_audit_event` → `EventRepository.append_transactional` **after** the
mutation transaction has ended (the audit is a record, never a gate).

Transaction-ownership facts that constrain this gate:

1. Gateway-owned and repository-owned transactions are mutually exclusive per
   call path (SQLite forbids nested `BEGIN`): a validator either owns the whole
   admission transaction or delegates it.
2. The rollback contract is duplicated verbatim in four validators
   (`except GatewayRejection: if conn.in_transaction: ROLLBACK; raise` +
   `except Exception: …`) — this is the certified failure semantics and must not
   be "cleaned up" during a decomposition commit.
3. Moving any of the five symbols above would move the transaction owner
   sideways out of the module that owns admission. Per §5's hard rule and
   precedent (e), all five are RED.

## §8 Authority map

Order inside `apply_intent` (unchanged by any candidate in this gate):
known-kind → role → project → budget hook → per-intent validator (payload
schema first, then credential/decision binding, then domain checks, then
mutation).

* Role gate `_require_role:150-188` — `director_only` → `DIRECTOR` only;
  `internal_only` → `DETERMINISTIC` only; LLM-proposable → the four agent
  profiles, never `DETERMINISTIC`; refusal code `ROLE`.
* Project gate `_require_project:191-202` — `PROJECT_NOT_FOUND` (stale project).
* Budget hook — caller-supplied; `BUDGET` on any non-rejection exception.
* Credential re-verification (existence only; the token never travels in an
  intent/event): `_validate_resolve_classification_proposal:605`,
  `_validate_contradiction_resolution:2726`, `_validate_record_classification:2973`,
  `_validate_record_scope_review_decision:3151` → `OPERATOR`.
* HumanDecision dereference (read-only, project-scoped, fail-closed → `PROPOSAL`)
  at four sites: `_validate_retract_source:1240-1253`,
  `_validate_curate_knowledge:1792-1810`,
  `_validate_contradiction_resolution:2734-2760`,
  `_validate_record_classification:2981-3012`. Gateway references
  `HUMAN_DECISION_RECEIVED` **only** in these four `SELECT`s — it never appends
  a HumanDecision row. The S-2 helper (`verdict_decisions.record_human_decision_once`)
  remains the only HumanDecision writer; DG-3B adds no second path.
* Decision binding: curate recomputes the full-command hash and requires
  `curation_id == curation_command_hash(payload)` (`:1818-1823`); classification
  requires `classification_hash == classification_command_hash(command)`
  (`:3026-3034`); contradiction resolution requires `decision ==
  "CONTRADICTION_RESOLUTION"` and `resolution_id`/`contradiction_id` agreement
  (`:2762-2777`).
* Ratification contract `_resolve_ratified_proposal:711-778` — recomputes the
  class's permitted set from the dereferenced classification (F2), never the
  stored state; returns `None` on any failure (fail-closed, no exception).
  Used by `PROPOSE_RESEARCH_PROGRAM`, `EVIDENCE_TRANSITION`,
  `RECORD_SCOPE_REVIEW_DECISION`, and by the Controller's evidence-ladder apply
  pass.
* The contradiction/curation/retraction validators each hard-check
  `internal_only` membership again in-body (defense in depth) — e.g.
  `_validate_curate_knowledge:1727-1736`.

Refusal-as-data: 213 `_reject(...)` sites and 5 direct `GatewayRejection(...)`
raises. No candidate seam in this gate carries any authority code, and the
selected seam raises nothing at all (verified: no `_reject`, no
`GatewayRejection`, no `EventType` reference in `950-1103`).

## §9 Identity / hash map

| Identity | Site | Class |
|---|---|---|
| `prop_<sha256[:24]>` (classification-action proposal id) | 459-467 | authoritative creation (gateway) |
| `tr_<sha256[:24]>` (evidence-transition id) | 883-891 | authoritative creation (gateway) |
| `retract_<sha256[:24]>` (retraction id) | 1265-1272 | authoritative creation (gateway) |
| `rd-<retraction_id>` + `decision_content` sha256 | 1321-1334 | authoritative creation (gateway) |
| `cone_digest` (`s5-cone-v1`) | 1553-1560 | authoritative creation (gateway) |
| `intent-<kind>-<clock()>` audit correlation | 3863 | audit identity (clock-derived, by design) |
| `cres_` contradiction resolution id | `_contradiction_resolution_id:2670-2676` | creation; **imported by controller** |
| `curation_command_hash`, `curated_id_of`, `signature_from_binding`, `binding_content_hash` | curate `:1818`, `:2148-2150`, `:2129`, `:2064` | verification-by-recomputation (research-owned formulas) |
| `cx_` contradiction id | `contradiction_id_of` (research), consumed at `:2543` | consumption |
| `fc_` / artifact content hashes | `classification_content_matches`, `metadata_json_by_hash`, `_source_artifact_resolves` | verification/consumption |
| content-hash lookups in `_l2_*` | 985-1103 | **consumption only** (no creation) |
| task/artifact primary-key lookups | `_l2_task_*`, `_s5_source_artifact_id`, `_task_exists` | ordinary lookup |

No `uuid`, `random`, or `time` import exists in gateway.py (verified); no
provider import exists (verified). Hash canonicalization in the movable unit is
not performed — `_l2_*` only *compares* stored values to committed rows.

## §10 Journal / replay map

Event types referenced by gateway (18): `CLASSIFICATION_ACTION_PROPOSED`,
`CLASSIFICATION_ACTION_DECISION`, `EVIDENCE_TRANSITION_PROPOSED`,
`EVIDENCE_TRANSITION_APPLIED` (read), `SCOPE_REVIEW_DECIDED`,
`SOURCE_RETRACTED`, `TASK_INVALIDATED`, `CURATED_KNOWLEDGE_PROPOSED`,
`CURATED_KNOWLEDGE_ADMITTED`, `CURATED_KNOWLEDGE_INVALIDATED`,
`CONTRADICTION_DETECTED`, `CONTRADICTION_SUPERSEDED`, `CONTRADICTION_RESOLVED`,
`HUMAN_DECISION_RECEIVED` (read ×4), `INTENT_APPLIED`, `INTENT_REJECTED`,
`RESEARCH_PROGRAM_COMPILED`, `TASK_CREATED`.

Journal writers: `_append_event_to_db` — 10 call sites inside gateway-owned
(or repository-owned) transactions: retract ×4, curate ×2,
record-contradiction ×2, contradiction-resolution ×1, plus 1 inside
`_decision_append_transactional`; `EventRepository.append_transactional` — 3
sites (`PROPOSE_CLASSIFICATION_ACTION`, `_append_audit_event`, and indirectly
none). Ordering per admission is `validation → identity → state mutation →
journal → COMMIT`, and the `IntentApplied`/`IntentRejected` audit append happens
*after* that transaction (including on duplicates — recorded A-04 debt, not a
DG-3B target).

Replay determinism: content-hash identities are recomputed; duplicate detection
uses `ORDER BY rowid LIMIT 1` (`_decision_append_transactional:522`, retract
`:1282`, curate `:2194`); cone/curated/contradiction iteration orders are
`sorted()`/`ASC`; `_l2_*` results are deterministic set operations with a
per-traversal memo. The movable unit contains no `EventType` reference, opens no
transaction and performs no write, so C-GW-4/C-GW-9 are structural non-events
for it (pinned by the existing suites, §19).

## §11 Project-isolation map

Explicitly project-scoped: every `_validate_*` query for artifacts,
tasks, events, contradictions, curated entries, programs and ladders passes
`project_id`; `_cx_resolve_evidence_ref`/`_cx_classification_facts`,
`_s5_source_artifact_id`, `_resolve_ratified_proposal`, `_resolve_program_in_project`
and the four HumanDecision dereferences all carry explicit predicates.
Global-by-key (intentional, documented): `_l2_lookup_artifact_by_hash`
(content_hash is UNIQUE), `_l2_resolve_ref_to_artifacts` (artifact_id PK),
`_l2_task_spec_refs`/`_l2_task_outputs` (task_id PK), `_l2_resolve_upstream`,
and the pure `_contradiction_resolution_id`. Isolation for the L2 family is
enforced **at emission**, not inside the resolver: the cone query
(`gateway.py:1361-1365`) `JOIN artifacts a ON a.artifact_id = e.artifact_id
WHERE a.project_id = ?`, so resolved upstream values can only ever act as match
keys against project-filtered rows. The comment at `:1367-1373` and the L2 test
suite (`test_21_cross_project_isolation`, `test_a7_cross_project_collision`,
`test_20_sibling_production_excluded`) make this contract explicit.

Known, untouched (recorded debt, out of DG-3B scope): the retract STALE probe
(`:1295-1300`) has no project filter (Phase 3 F-01); the record-contradiction
existing-row check (`:2548-2552`) is by `contradiction_id` only, while its
supersede-target check (`:2598-2601`) is project-scoped; the retract cone walk's
artifact `UPDATE`s are by `artifact_id` (rows already project-vetted at emission).
DG-3B changes none of them and authorizes no change: any "fix" here is an
S5/CHG-1 semantic change requiring DG-6, not a decomposition.

## §12 Contradiction-pair analysis

Independently re-derived (not assumed safe because the audit called it clean).

| Function | Lines | Inputs → outputs | Callers | Callees | Persistence | Tx | Identity | Authority | Journal | Project scope | Research imports | Reverse deps |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `_cx_resolve_evidence_ref` | 2364-2398 | `(conn, project_id, ref)` → `artifact_id \| None` | `_cx_classification_facts` (+`tests/test_n9_retraction_admission.py:843,852`) | `conn.execute` SELECT, `source_artifact_retracted` | read-only | none | none | none | none | explicit (`project_id` in query) | `source_outcomes` (persistence), N9 predicate | test (1 file) |
| `_cx_classification_facts` | 2401-2452 | `(conn, project_id, artifact_id)` → facts dict \| None | `_validate_record_contradiction` ×4 | `_cx_resolve_evidence_ref`, `classification_content_matches`, `FailureClass` | read-only | none | none (verifies digest identity) | none | none | explicit | `evidence_ladder`, `failure_classification` | — |
| `_contradiction_resolution_id` | 2670-2676 | `contradiction_id` → `cres_…` | `_validate_contradiction_resolution` | `hashlib`, `json` | none | none | **creates identity** | none | none | n/a | none | `controller.py:1996,2008` |
| `_validate_record_contradiction` | 2455-2667 | intent → `IntentResult` | `apply_intent` | `_cx_classification_facts`, research `contradictions`, `_append_event_to_db` | `INSERT`/`UPDATE` `contradictions` (sole writer) | **owns** (2546) | consumes `contradiction_id_of` | N9 in-tx re-resolution | ×2 | explicit | `contradictions` | — |
| `_validate_contradiction_resolution` | 2679-2845 | intent → `IntentResult` | `apply_intent` | `_contradiction_resolution_id`, credential check, `_append_event_to_db` | `UPDATE contradictions` (sole writer) | **owns** (2779) | via helper | operator + HumanDecision binding | ×1 | explicit | — | — |

Verdicts: the **fact pair is separable** (one entry point, read-only,
refusal-free, explicit project scoping) → YELLOW, not GREEN, because (i) the
N9-owning certified test imports `_cx_resolve_evidence_ref` directly, so a move
requires retargeting a line in `tests/test_n9_retraction_admission.py` and
re-running the N9 slice; (ii) the pair contains the N9 exclusion call, so the
move is N9-adjacent by construction; (iii) it sits inside the frozen N1
lifecycle, where the cheapest correct action is to leave it. `_contradiction_resolution_id`
and both validators are RED (identity creation + Controller import;
transaction + sole-writer ownership). They can be extracted neither together nor
separately today.

## §13 Large-validator analysis

| Validator | Lines | Size represents | Verdict |
|---|---|---|---|
| `_validate_curate_knowledge` | 691 (1652-2342) | one cohesive transaction-bound admission with 31 numbered stages: stages 1-27 are pre-transaction validation and derivation (no writes), 28-31 are the in-transaction duplicate check, supersede guard, inserts and two events; a verbatim duplicated rollback idiom (2327-2333). Genuinely separable *sequential steps* exist, but every step raises refusals, so no step can leave the module without either a lazy reach-back into gateway's refusal factory or a duplicated refusal vocabulary. | Cohesive (2). In-file named step helpers = C-01a, a different seam class — YELLOW, not authorized here. |
| `_validate_retract_source` | 446 (1155-1600) | three stages: pre-tx validation/identity (payload → HumanDecision deref → `_s5_source_artifact_id` → `retract_`), the single cascade transaction (decision artifact + edge, cone walk via `_l2_*`, artifact/task/curated/contradiction invalidation, bounded-digest emission), commit. It is the **sole writer** of `contradictions`/`curated_knowledge_*` rows in the cascade and writes `artifacts`/`provenance_edges`/`tasks` directly. | Cohesive (2) + mixed ownership only in the sense that the cascade legitimately spans six tables — RED: cannot move without relocating transaction ownership and write ownership. |
| `_validate_record_contradiction` | 213 | one cohesive N1 admission + optional head-only supersession in one transaction; the pre-tx pair rule is deliberately re-derived inside the transaction (N9). | Cohesive — RED (tx + sole writer). |
| `_validate_record_classification` | 235 | cohesive front-end that validates and then delegates the semantic core to the repository write boundary ("this validator opens none", docstring). | Cohesive, repository-delegating — NOT-A-SEAM. |
| `_validate_source_spec` (183), `_validate_contradiction_resolution` (167), `_validate_propose_classification_action` (152), `_validate_evidence_transition` (132), `_validate_propose_research_program` (121), `_validate_record_scope_review_decision` (105), `_validate_insert_task` (75), `_validate_provenance` (68), `_validate_extract_source` (61) | — | each is one admission predicate chain; none mixes architectural ownership. | NOT-A-SEAM / YELLOW per §17. |

Explicitly rejected: splitting either large validator at the `BEGIN IMMEDIATE`
line, or "extracting the validation half" into a module. The pre-transaction
half is the authority-bearing part (credential, HumanDecision binding, payload
schema, identity recomputation) and the in-transaction half is the certified
atomic cascade; separating them would put a module boundary where the
certification boundary is. Size is not a seam criterion (§0, §22).

## §14 Gateway dependency analysis (gateway → research/tools)

Module-level research imports: `extraction` (`EXTRACT_COST_CLASS`,
`EXTRACT_PROFILE`, `EXTRACT_SCOPES`, `EXTRACT_TEMPLATE`, `:67`), `programs`
(`CompilationStatus`, `compile_from_payload`, `:73`), `source_templates`
(nine names incl. `_check_retry_policy`, `:77`). Lazy (function-level) research
imports: `failure_classification` (`:278,379,422,636,731,871,2412,2884`),
`evidence_ladder` (`:1683,2411`), `feature_binding` (11 names, `:1686`),
`contradictions` (`:2474`), `evidence_transitions` (`:812`), `scope_review`
(`:3121`). Tools: `SOURCE_PROVIDER_ALLOWLIST` (`:88`).

| Import | Classification | Why source supports it |
|---|---|---|
| `programs.compile_from_payload` | intentional architectural ownership | module docstring `:24-31`: "validator = epistemic derivation authority (compile_from_payload)"; NOT_COMPILED is a gate violation |
| `extraction` / `source_templates` constants | intentional | the pinned template profile/scope/cost class are gateway invariants (V6-P7-E02) |
| `tools.research_sources.SOURCE_PROVIDER_ALLOWLIST` | intentional | IDR-030 admission allowlist |
| `failure_classification` (classes, permitted actions, command hashes) | intentional | F2 recompute discipline; the domain owns class semantics |
| `contradictions` (`canonical_pair`, `contradiction_id_of`) | intentional | N1 pair rule and `cx_` identity are research-owned and re-derived |
| `feature_binding` (signature/curated-id/binding-hash) | intentional | chartered formulas recomputed, never trusted |
| `evidence_ladder.classification_content_matches` | intentional | digest-valid identity check is research-owned |
| `evidence_transitions` / `scope_review` vocabularies | intentional | ratified vocabularies |
| persistence imports | safe downward dependency | gateway → persistence is the allowed direction (§15) |
| incidental / cycle-producing | **none found** | no provider import; no import of `research.gateway` from any layer; the selected seam's module imports stdlib only |

The DG-5 inversion (persistence → research) is untouched by this gate and is
explicitly not "fixed": domain validators stay research-owned, nothing is moved
downward, and no import is edited. The selected seam does not change the import
graph except by adding one leaf module that imports nothing from the project.

## §15 Persistence dependency analysis

Gateway reaches persistence through: `repositories` (module-level: eight
classes + `_append_event_to_db`), `source_outcomes` (`_source_artifact_resolves`,
`source_artifact_retracted`), plus lazy `failure_classifications`,
`event_validation`, `repositories` (`OperatorCredentialRepository`, `_json_loads`).

Transaction orchestration: gateway owns five transactions (§7) and delegates
eleven admission paths to repository-owned ones. Helper extraction that crosses
that boundary is prohibited by §7's hard rule; nothing in this gate proposes
moving gateway writes down into repositories (that would be a semantic change
for DG-4/DG-6 to own, not a decomposition).

Write-boundary facts (§13): `contradictions` and the three `curated_knowledge_*`
tables have **no repository writer** — gateway validators are their only writer;
`artifacts` (gateway retract + `ArtifactRepository.record`), `provenance_edges`
(retract + three repository writers), and `tasks` (retract + `TaskRepository.create`
+ the Controller's human-gate path) have more than one writer.

The selected seam touches none of this: it issues `SELECT`s only, calls no
repository method, opens no transaction, and therefore cannot create a
persistence→gateway cycle or change orchestration.

## §16 API / stability analysis

Using the ratified convention (`docs/API.md`):

| Surface | Label | Evidence | Movement rule |
|---|---|---|---|
| `apply_intent` | PUBLIC/SUPPORTED, EVOLVING | `__all__:90`; imported by controller, CLI, 26 test files, 2 scripts | FROZEN for this gate — no touch |
| `GatewayRejection`, `IntentResult` | PUBLIC, EVOLVING set | `__all__:90`; ~20 test importers | FROZEN — no touch |
| 16 refusal codes `:93-108` | EVOLVING set / FROZEN meanings | imported by 8 test files | stay in gateway; no duplication |
| intent/event names, payload keys | FROZEN-BY-DECISION | `core/intents.py`, `core/events.py` | no touch |
| 14 validators | INTERNAL | `_`-prefixed, no docs entry | movable only per §17 verdicts |
| `_decision_append_transactional`, `_resolve_ratified_proposal`, `_contradiction_resolution_id` | INTERNAL but cross-module | `controller.py:3045/3080/3105`, `:1996/2008` | RED — a move would force Controller edits (prohibited by §20) |
| `_l2_*` family | INTERNAL / UNDECLARED | one test importer | selected seam; authorize the single test import retarget |
| `_cx_*` pair | INTERNAL / UNDECLARED | one N9-test importer | YELLOW (§12) |

No new public API is introduced. The new module must not be added to
`gateway.__all__` (still three names), must not gain an `__all__` of its own,
must not appear in `docs/API.md`, and must not be exported by
`hermes.research.__init__` (verified: that file is a docstring only).

## §17 Candidate seam table

| # | Candidate | Responsibility | Cohesion | Coupling | Tx risk | Authority risk | Identity risk | Replay risk | Isolation risk | Import risk | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | L2 resolution family (950-1103) | resolve stored provenance refs to canonical artifact ids | HIGH | LOW (1 in-gateway caller; 1 test importer) | NONE | NONE | LOW (consumes lookups) | NONE | MEDIUM (global-by-key by design; emission filter at 1364 — must be preserved, never "fixed") | LOW (new stdlib-only module; 1 test import line) | **GREEN — SELECTED** |
| 2 | N1 contradiction fact pair (`_cx_resolve_evidence_ref`, `_cx_classification_facts`) | derive digest-valid pair facts with N9 exclusion | HIGH | LOW-MED | NONE | NONE | LOW | NONE | LOW (explicit scoping) | MED (N9-owning test retarget + N9 slice re-run) | YELLOW |
| 3 | `_contradiction_resolution_id` | deterministic `cres_` id | HIGH | HIGH | NONE | NONE | **HIGH (creates identity)** | NONE | NONE | HIGH (Controller import) | RED |
| 4 | Decision-append seam (`_decision_append_transactional` + 3 callers) | one-verdict check + append in ONE tx | MED (3 intents) | MED | **RED (owns BEGIN IMMEDIATE)** | MED (refusal precedence) | LOW | MED (event ordering) | LOW | MED | RED |
| 5 | Ratification contract (`_resolve_ratified_proposal`) | recompute approval from stored decisions | HIGH | HIGH | NONE | HIGH (authority contract) | LOW | NONE | LOW | HIGH (Controller import) | RED |
| 6 | `_validate_retract_source` | S5 cascade | n/a | HIGH | RED (tx owner) | HIGH (HumanDecision) | MED (`retract_`/`rd-`/digest) | HIGH (ordering, once-only) | MED (documented STALE wart) | HIGH | RED |
| 7 | `_validate_curate_knowledge` | curated registry admission | n/a | HIGH | RED (tx owner) | HIGH (HumanDecision + command hash) | HIGH (recomputes 4 identities) | HIGH | LOW | HIGH | RED |
| 8 | `_validate_record_contradiction` | N1 admission + supersession | n/a | HIGH | RED (tx + sole writer) | MED | MED (consumes `cx_`) | MED | LOW | HIGH | RED |
| 9 | `_validate_contradiction_resolution` | human verdict resolution | n/a | HIGH | RED (tx + sole writer) | HIGH | HIGH (`cres_`) | MED | LOW | HIGH | RED |
| 10 | Repository-delegating validators (propose program, propose action, record classification, insert task) | one admission path each | HIGH each | MED | NONE (repo-owned) | HIGH (admission authority) | MED | MED | LOW | MED | NOT-A-SEAM |
| 11 | Refusal machinery (`_reject`, `GatewayRejection`, 16 codes) | refusal vocabulary + factory | HIGH | EXTREME (213 sites, ~20 test importers) | NONE | HIGH | NONE | NONE | NONE | EXTREME | NOT-A-SEAM |
| 12 | INSERT_TASK predicate family (`_payload_to_node`, `_validate_provenance`, `_is_*_spec`, `_validate_extract_source`, `_validate_source_spec`) | task-admission predicates (~420 lines) | HIGH | LOW in-gateway | NONE | HIGH (admission authority) | LOW | NONE | LOW | MED-HIGH (every member raises `_reject` → the new module must reach back into gateway lazily or duplicate the refusal vocabulary) | YELLOW |
| 13 | In-file step helpers for curate/retract (C-01a) | readability decomposition, no module move | n/a | n/a | NONE (stays in gateway) | MED | NONE | MED | NONE | NONE | YELLOW (different seam class; not authorized) |
| 14 | `_s5_source_artifact_id` riding with #1 | source-ref resolution | HIGH | MED | NONE | MED (raises refusals) | LOW | NONE | HIGH (type check + project param) | MED | NOT-A-SEAM as part of #1 |
| 15 | `_canonical_or_none`, `_resolve_program_in_project`, `_task_exists` | tiny single-caller helpers | HIGH | NONE | NONE | NONE | NONE | NONE | NONE | LOW | NOT-A-SEAM (no value) |

Ranking criterion was ownership, not size: rows 1 and 2 are the only candidates
with zero transaction, zero write, zero authority and zero identity-creation
risk; row 1 additionally has zero project imports, zero refusal coupling and an
existing dedicated 56-test suite.

## §18 Selected first seam (single authorization)

**Identity.** The L2 upstream-reference resolution family, `gateway.py:950-1103`:
comment preamble `950-974`, `_L2_HASH_TYPED_PREFIXES:975-982`,
`_l2_lookup_artifact_by_hash:985-997`, `_l2_resolve_ref_to_artifacts:1000-1027`,
`_l2_task_spec_refs:1030-1054`, `_l2_task_outputs:1057-1063`,
`_l2_resolve_upstream:1066-1103`.

**Responsibility (one sentence).** Normalize every stored `provenance_edges`
upstream reference form (bare artifact id, typed `<type>:<hash>`, bare task id)
to canonical `artifacts.artifact_id` identities, as a pure deterministic
function of committed state, never rewriting storage.

**Owner.** The ratified S5 L2 read-path contract (design gate verdict
"Option B"), whose dedicated suite already exists
(`tests/test_s5_l2_resolution.py`, 56 tests, matrix documented in its header).
The module lives in `hermes/research/` (same layer as gateway; research →
persistence is the allowed direction).

**Proposed location.** `src/hermes/research/l2_resolution.py` — INTERNAL, no
`__all__`, docstring naming the ratified gate and stating explicitly that it
opens no transaction, performs no write, raises no refusal, and that project
isolation is enforced at emission. Alternative name `provenance_refs.py` was
rejected because `research/provenance.py` already exists as a Phase 0
placeholder for the future lineage layer (avoid name collision/squatting).

**Contract (must remain byte-identical).** Signatures
`(conn, content_hash, artifact_type) -> str | None`,
`(conn, value) -> set[str]`,
`(conn, task_id) -> tuple[list[str], bool]`,
`(conn, task_id) -> set[str]`,
`(conn, value, edge_type, _memo=None) -> set[str]`; the `_memo` traversal-memo
parameter and its semantics; the fixed rule precedence (artifact identity →
typed form → task hop → unresolved); fail-safe empty-set/None returns (never an
exception); exact-match-only behavior (no prefix guessing/truncation).

**Estimates.** ~154 source lines moved (119 function lines + 25 comment lines +
8-line constant) → ~180-line new file; 1 call site (`gateway.py:1374-1378`,
inside `_validate_retract_source`) plus 1 import statement in `gateway.py`;
1 file created; 1 test import line retargeted
(`tests/test_s5_l2_resolution.py:50`); 0 required new characterization tests
(§19 adds 3 cheap additive pins); re-run slices: L2 56, S5 retraction 34,
S6 event capacity 44 (its sections 38-43 are L2 integration), step-7 68,
gateway 33, N9 21, full suite 2051. No Controller, persistence, intent, event,
schema, or config change.

**Why it satisfies every §16 criterion.** Single responsibility; clear owner;
stable input/output contract; no transaction crossing; no authority crossing;
no identity-ownership movement (consumption only); no journal-ordering change;
project scoping preserved *as designed* (global-by-key with emission filtering);
no public API expansion; no persistence-direction violation (it is a read helper
in the allowed direction); manageable characterization surface (56 existing tests).

**Explicitly not authorized by this verdict:** any second seam, the §17 YELLOW
rows, in-file step-helper refactors (C-01a), large-validator splits, refusal
machinery relocation, transaction relocations, persistence-write relocation,
or DG-5/DG-6 work.

## §19 Characterization-test design

Existing pins (mapped, not assumed — every row names the test that proves it):

| Property | Existing evidence |
|---|---|
| C-GW-1 output equivalence | `test_s5_l2_resolution.py`: `test_1_bare_artifact_hit`, `test_2`-`test_2f`, `test_3`-`test_5`, `test_6`/`test_7`/`test_8` (task-hop per edge type), `test_9`-`test_13`, `test_14_repeated_resolution_deterministic`, `test_15`-`test_19` |
| C-GW-2 refusal/error equivalence | The unit raises nothing; caller-side refusals pinned by `test_s5_retraction.py`: `test_nonexistent_source_rejected`, `test_bad_hash_prefix_rejected`, `test_cross_project_source_rejected`, `test_missing_human_decision_fail_closed`, `test_missing_decision_beats_source_resolution` |
| C-GW-3 transaction-failure equivalence | `test_s5_retraction.py:test_mid_cascade_failure_writes_nothing`; `test_s6_event_capacity.py` (S6 bounded-payload/atomicity sections) |
| C-GW-4 journal-ordering equivalence | `test_s5_retraction.py:test_event_ordering_and_causality`, `test_deterministic_correlation_key`, `test_payload_carries_cascade_record`; `test_s6_event_capacity.py:38-43` |
| C-GW-5 identity/hash equivalence | `test_2f_type_prefix_is_part_of_identity`, `test_4b_truncated_hash_never_matches`, `test_13_artifact_before_task_precedence`, `test_a6_ambiguous_alias_precedence` |
| C-GW-6 duplicate/idempotency equivalence | `test_22_duplicate_aliases_single_invalidation`, `test_30_idempotency_stale_unchanged`, `test_a5_replay_identical`, `test_s5_retraction.py:test_identical_repeat_is_duplicate_with_zero_effects`, `test_second_different_retraction_is_stale` |
| C-GW-7 project-isolation equivalence | `test_21_cross_project_isolation`, `test_a7_cross_project_collision`, `test_20_sibling_production_excluded` |
| C-GW-8 authority/fail-closed equivalence | No authority code in the unit (structural); admission-side pins `test_s5_retraction.py:test_retract_source_is_internal_only`, `test_agent_roles_rejected`, `test_apply_apply_same_state` |
| C-GW-9 replay/determinism equivalence | `test_29_replay_deterministic`, `test_31`-`test_34` (compatibility), `test_a1`-`test_a4`, `test_a12_large_cone`, `test_23_cycle_terminates` |
| C-GW-10 existing-slice preservation | The eight-slice run in §23 |

Additive tests required (3 — only where existing tests do **not** pin the
property directly; no redundant test is manufactured):

1. **Module-boundary / no-duplicate pin** — import all five symbols from the new
   module and assert `gateway` exposes the *same function objects* (identity
   check) and that no second `_l2_` definition remains in `gateway.py`
   (source-level assertion). Prevents a copy-paste relocation from silently
   creating a second implementation.
2. **Purity pin** — drive the resolver with a spy connection whose `execute`
   records every statement, and assert all statements are `SELECT` and that no
   `BEGIN`/`COMMIT`/`ROLLBACK` is issued. Pins "no write, no transaction" as a
   property rather than an observation.
3. **Scope-by-design pin** — assert directly that `_l2_resolve_upstream`
   resolves a p2 artifact id identically when called for p1 (global-by-key
   lookup) and that isolation is supplied by the caller's project-filtered
   emission query; pins the contract that must not be "fixed" during the move.

Each additive test lands in the same commit as the move, must be green against
the pre-move tree where it can be (pins 1-3 are extraction-stable by
construction: 2 and 3 target the moved code through both import paths, 1 is
checked post-move only).

## §20 Multi-agent implementation constraints

1. One agent owns `src/hermes/research/gateway.py` for the duration; no
   concurrent gateway structural edit.
2. One seam per implementation commit. The commit contains only: the move, the
   gateway import, the call-site substitution, the single test import retarget,
   and the three additive pins. Nothing else.
3. Additive characterization tests first (green against the pre-move tree where
   constructible, per §19), then the move.
4. No Controller edits, no persistence edits, no intent/event changes, no
   schema/migration changes, no config/dependency changes, no gateway API
   change, no `__all__` change, no invariant change.
5. No second seam: the §17 YELLOW rows, the C-01a in-file step helpers, and the
   large-validator splits stay untouched until a separate gate authorizes them.
6. No DG-5 inversion work, no DG-6 invariant work, no S-3 work, no test
   weakening, no assertion relaxation, no "while we are here" cleanups.
7. Re-run before certifying: the L2 slice, the S5 retraction slice, the S6
   event-capacity slice (L2 integration sections), the step-7 slice, the N9
   slice, the gateway slice, the full suite, Ruff, Pyright (src profile),
   `scripts/profiled_gate.sh`, `git diff --check`.
8. Stop conditions for the implementer: if the move requires touching
   `_s5_source_artifact_id`, adding any refusal, adding any project filter,
   opening or participating in a transaction, generating an identity, editing
   the Controller or persistence, changing a signature, or adding a
   compatibility shim/re-export beyond the single gateway import — **STOP** and
   report; do not solve it opportunistically.

## §21 Adversarial 30-question review

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Mistake file size for a seam? | PASS | Size explicitly rejected (§13, §22); the two largest validators are RED, the selected unit is 154 lines |
| 2 | Confuse validator reuse with ownership? | PASS | Fan-in measured (§4C, §6); the two shared helpers are disqualified by tx ownership and a Controller import, not by reuse |
| 3 | Cross a transaction boundary? | PASS | The unit opens, participates in, and observes no transaction (§7; §19 pin 2) |
| 4 | Move transaction ownership? | PASS | All five gateway-owned `BEGIN IMMEDIATE` sites stay in `gateway.py` (§7; §24) |
| 5 | Change exception semantics? | PASS | The unit raises nothing; refusal machinery untouched (§8, §17 row 11) |
| 6 | Change refusal precedence? | PASS | Dispatch ladder `:3782-3824` and stage order byte-identical (§4A) |
| 7 | Weaken fail-closed behavior? | PASS | No authority code is moved; four HumanDecision gates and four credential gates untouched (§8) |
| 8 | Duplicate identity logic? | PASS (precondition) | The unit creates no identity; additive pin 1 asserts no second `_l2_` implementation exists (§9, §19) |
| 9 | Alter journal ordering? | PASS | Zero `EventType` references in the unit; C-GW-4 pins named (§10, §19) |
| 10 | Alter replay semantics? | PASS | Pure reads, fixed precedence, memo per traversal; C-GW-9 pins named (§10, §19) |
| 11 | Weaken project isolation? | PASS (precondition 4) | Global-by-key lookups are the ratified design; emission JOIN at `1361-1365` unchanged; additive pin 3 forbids "fixing" it (§11, §19) |
| 12 | Accidentally bypass HumanDecision authority? | PASS | Gateway reads `HumanDecisionReceived` in four `SELECT`s only; no write site exists (§8) |
| 13 | Duplicate the S-2 seam? | PASS | The unit appends no event; `record_human_decision_once` remains the only HumanDecision writer (§8, §10) |
| 14 | Create a gateway→gateway cycle? | PASS | New module imports stdlib only; no project import (§14) |
| 15 | Create a persistence→gateway cycle? | PASS | Persistence untouched; nothing in `persistence/` imports gateway beyond existing reads (§14, §15) |
| 16 | Improperly "fix" the DG-5 inversion? | PASS | Zero import edits; no downward moves; domain validators stay research-owned (§14) |
| 17 | Create a new public API? | PASS | INTERNAL module, no `__all__`, `gateway.__all__:90` unchanged, no docs entry (§16) |
| 18 | Assume an existing test proves more than it does? | PASS | Every C-GW row names the proving test; the three properties without direct pins are listed and get additive tests (§19) |
| 19 | Is the seam independently characterizable? | PASS | 56 dedicated L2 tests + 34 S5 + 44 S6 capacity (§19, §23) |
| 20 | Smaller/safer seam missed? | PASS | `_canonical_or_none` (9), `_task_exists` (6), `_is_*_spec` (16), `_resolve_program_in_project` (25) reviewed — smaller but refusal-raising or valueless (§17 rows 12, 15) |
| 21 | Is the contradiction pair genuinely separable? | PASS (YELLOW) | Fact pair separable; validators not (§12) |
| 22 | Are the large validators actually cohesive? | PASS | Single transaction-bound admissions; splitting them would place a module boundary at the certification boundary (§13) |
| 23 | Could extraction alter rollback behavior? | PASS | Four duplicated rollback idioms stay byte-identical; the unit has no transaction (§7, §13) |
| 24 | Could extraction alter journal-failure behavior? | PASS | No journal calls in the unit; `test_mid_cascade_failure_writes_nothing` re-run (§19, §23) |
| 25 | Could extraction alter duplicate behavior? | PASS | Duplicate checks live inside the validators' transactions and are untouched (§7, §10) |
| 26 | Could extraction alter deterministic output? | PASS | Pure functions, stable ordering, `_memo` semantics preserved (§10, §18) |
| 27 | Hidden reverse dependencies? | PASS (enumerated) | Controller imports 2 gateway privates (RED-guarded), tests import 4, scripts import 5; the selected unit has exactly one test importer (§4C, §16, §24) |
| 28 | Clear architectural owner? | PASS | Ratified S5 L2 contract; research-layer module; allowed direction (§18) |
| 29 | Any reason to prohibit implementation despite apparent safety? | PASS | None found; costs disclosed (1 test import line, 3 additive pins, modest value) (§0, §24) |
| 30 | Reduce risk or merely relocate it? | PASS (honest) | Relocates an S5 read responsibility to its proper owner; does not reduce admission risk. The durable risk reduction is the negative map: tx-owning validators, refusal-carrying predicates and identity-creating helpers are proven ineligible (§0, §13, §17, §22) |

Result: **30 PASS, 0 FAIL**, with three explicit preconditions carried into §24
(no duplicate implementation; no refusal/tx/project-filter additions; no second
seam).

## §22 Explicit non-goals (prohibited by this gate)

* Extracting any transaction-owning validator (`_validate_retract_source`,
  `_validate_curate_knowledge`, `_validate_record_contradiction`,
  `_validate_contradiction_resolution`).
* Extracting `_decision_append_transactional` or any part of the F6/F9
  one-verdict atomicity mechanism.
* Extracting or relocating `_resolve_ratified_proposal`,
  `_contradiction_resolution_id`, `GatewayRejection`, `IntentResult`, the 16
  refusal codes, `_reject`, or `apply_intent`.
* Splitting a `BEGIN … COMMIT/ROLLBACK` pair, or "normalizing" the four
  duplicated rollback idioms.
* In-file step-helper refactors of the large validators (C-01a) — a different
  seam class, not authorized here.
* Moving gateway writes into repositories, or any change to write ownership.
* DG-5 (persistence→research inversion), DG-6 (invariant impact), DG-4
  (repository split), DG-2 follow-ons (Controller reads), S-3, or DG-3C.
* Gateway modernization: dependency injection, service classes, registries,
  workflow engines, event buses, plugin frameworks, versioning machinery.
* Line-count targets, cosmetic renames, comment cleanups, or "while we are
  here" refactors inside `gateway.py`.
* Any test weakening, assertion relaxation, or new test that pins behavior the
  certified suite already pins.

## §23 Validation record and final gate verdict

This gate is design-only: it modified exactly one file (this report, untracked
at validation time) and no production, test, config, or dependency file
(`git status --porcelain`: the report plus the five known untracked items).
Validation therefore proves the certified baseline is green and that the gate
changed nothing.

| Gate | Command | Result |
|---|---|---|
| Full suite | `.venv/Scripts/python.exe scripts/run_tests.py -q` | 100% progress, **zero F/E markers**, exit code **0**; the pytest summary line is suppressed by the host-venv teardown issue documented in `scripts/run_tests.py:5-8` ("crashes pytest at session teardown, even though all tests pass") |
| Collected count | `.venv/Scripts/python.exe -m pytest --collect-only -q` | **2051 tests in 63 files** — identical to the S-2 certified count (2045 baseline + 6 S-2 tests) |
| Ruff | `uvx ruff check src tests` | `All checks passed!` |
| Pyright (source profile, strict) | `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| Project validation profile | `./scripts/profiled_gate.sh` | tests-profile typecheck `0 errors, 1 warning` (pre-existing, `tests/test_research_program.py:141`, untouched by this gate) + walking-skeleton smoke `5 passed` → `profiled typecheck + walking-skeleton smoke: OK` |
| Whitespace | `git diff --check` | clean |
| Working tree | `git status --porcelain=v1` | only this report + the five known untracked items (`IDEA.md`, `Prompts/`, `orci.json`, `orhead.json`, `ortree.json`) |

Pre-existing-warning determination: `tests/test_research_program.py:141`'s
`reportSelfClsParameterName` warning is present on the certified baseline and is
recorded as pre-existing in the S-2 certification; it is not attributable to
this gate. No production code was modified to make anything green, and no
tooling configuration was touched.

### Final gate verdict

```text
DG-3B — GATEWAY DESIGN GATE PASSED / IMPLEMENTATION AUTHORIZED
```

Authorization scope: **exactly one seam** — §18's L2 upstream-reference
resolution family (5 functions + 1 constant, `gateway.py:950-1103`) may be moved
to one internal, stdlib-only module under the §20 constraints and §24
prerequisites. No other gateway extraction is authorized; in particular the
§17 RED and NOT-A-SEAM rows, the §17 YELLOW rows, and the C-01a in-file
step-helper refactors remain unauthorized pending separate gates.

## §24 Exact implementation prerequisites

1. **Characterization first.** Add the three additive pins of §19 (module
   boundary/no-duplicate; purity/no-write/no-transaction; scope-by-design) and
   run the existing L2 slice (`tests/test_s5_l2_resolution.py`, 56 tests) green
   *before* moving production code. If any characterization test fails against
   the pre-move tree, STOP.
2. **Byte-identical contract.** Move the five functions verbatim: same names,
   same signatures (including `_memo=None` and `edge_type`), same docstrings
   (they carry contract text, including "project isolation is enforced at
   EMISSION"), same fixed rule precedence, same fail-safe `None`/empty-set
   returns, same exact-match-only behavior. `_L2_HASH_TYPED_PREFIXES` moves with
   them.
3. **No stabilization by import re-export.** The new module defines the symbols;
   `gateway.py` imports them for its single call site. Retarget the one import
   line in `tests/test_s5_l2_resolution.py:50` to the new module so no test
   depends on a re-export. `gateway.__all__` stays exactly
   `["GatewayRejection", "IntentResult", "apply_intent"]`.
4. **No behavior "fixes".** Do not add a project filter, a refusal, a
   transaction, a write, a cache, a log, an identity, or provider/clock access.
   The documented L2 identifier-form defect and the F-01 STALE wart stay exactly
   as they are.
5. **Transaction ownership frozen.** The five gateway-owned `BEGIN IMMEDIATE`
   sites (`_decision_append_transactional:519`, retract `:1275`, curate `:2188`,
   record-contradiction `:2546`, contradiction-resolution `:2779`) and their
   COMMIT/ROLLBACK pairs stay in `gateway.py`, byte-identical.
6. **Do not extend the scope.** Do not touch `_s5_source_artifact_id`,
   `_cx_*`, `_contradiction_resolution_id`, `_resolve_ratified_proposal`, the
   refusal machinery, the Controller, persistence, intents, events, schemas,
   migrations, or configuration.
7. **One commit.** The implementation commit carries the move, the gateway
   import, the call-site substitution, the one test import retarget, and the
   three additive pins — nothing else.
8. **Re-run and certify.** Before declaring the seam done: the L2 slice (56),
   S5 retraction (34), S6 event capacity (44, L2-integration sections 38-43),
   step-7 curated registry (68), N9 admission (21), gateway (33), the full suite
   (2051), Ruff, Pyright source profile, `scripts/profiled_gate.sh`, and
   `git diff --check`. Any red gate stops the change; no test may be weakened.
9. **Stop conditions.** If the move requires any of: a signature change, a new
   refusal, a project filter, a transaction, a repository call, an identity, a
   compatibility shim, a second test importer update beyond
   `tests/test_s5_l2_resolution.py`, or any Controller/persistence edit — STOP
   and report; do not solve it opportunistically.
10. **No second seam.** Do not begin the §17 YELLOW rows, DG-5, DG-6, DG-4,
    S-3, or C-01a until a separate gate authorizes them.

## Final Verdict

```text
DG-3B — GATEWAY DESIGN GATE PASSED / IMPLEMENTATION AUTHORIZED
```
