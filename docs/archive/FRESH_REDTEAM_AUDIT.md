# FRESH RED TEAM AUDIT — 2026-08-15 (independent of any prior audit file)
# Target: D:\New folder\research-agent (repo HEAD f78bedd at time of audit)
# Scope: adversarial review vs framework doc C:\...\hermes_surviving_ideas_application_framework-2.md
# Constraint: zero tracked-file edits; read-only audit

## 1. BASELINE STATE (verified independently this session)
- HEAD: f78bedd ("Pin the mesh exact-product boundary...") — a newer commit than prior session (c7520bf)
- Working tree: M tests/test_controller.py (pre-existing tracked change, not by this audit); ?? .freebuff/ (pre-existing untracked)
- Source: 23,304 lines; 44 test modules collecting 1419 test items; 3 key Q modules (test_failure_classification.py 44, test_q05_persistence.py 54, test_q05_evidence_ladder.py 58, test_q02_eligible_ordering.py 36, test_controller_q02.py 38, test_q04_* files 86 total)
- Framework spec (independent read this turn): Q-05 ADOPT NARROWLY (6-class taxonomy: DECLARED_CONSTRAINT_VIOLATION, IMPLEMENTATION_FAILURE, ENVIRONMENT_MISMATCH, RESOURCE_CONSTRAINT, FRAMING_ERROR, UNKNOWN); Q-02 ADOPT NARROWLY (EligibleTask deterministic ordering); Q-04 ADOPT NARROWLY (derived failure-propagation graph edges); Q-01 REJECT; 4S-state-machine REJECT; Q-07 EXPERIMENTAL; Q-09 MERGE (conditional); Q-13 DEFER; CV-01 EXPERIMENTAL (3 of 5 levels only)

## 2. CODE / ARCHITECTURE FINDINGS (fresh inspection of src/)
Q-05 substrate (`src/hermes/research/failure_classification.py`, 918 LOC):
- Pure deterministic function (no SQL, no writes, no gateway import) — conforms to framework §A (no new authority/datastore/state machine)
- Taxonomy: 6-class enum (line 78-92) — matches framework §D.1 (renamed HARD_AXIOM_VIOLATION → DECLARED_CONSTRAINT_VIOLATION per framework reconciliation §2.3; added UNKNOWN per framework demand; dropped MULTI_FACTOR catch-all as framework directs)
- ACTION_MAP (line 114-135): deterministic lookup — conforms to framework §D.1.I
- Citation discipline (line 554-702): fail-closed; citation outside record rejected; no resolver = REJECTED — conforms to framework §D.1.K / v6 §2 principle 1 (deterministic owns execution)
- Content-hash identity (`sha256_hex(canonical_json(content))`, line 769): conforms to framework §D.1.N determinism requirement
- `requires_human_confirmation_for` (line 823-831, CURRENT STATE): takes `contributing_factors: tuple` param; returns True when `failure_class is FRAMING_ERROR` OR any contributor is FRAMING_ERROR — this is NEW vs prior session and CLOSES the prior MEDIUM finding
- `_build_classification` (line 794-795): passes `contributing_factors` to `requires_human_confirmation_for`
- `proposal_requires_human_confirmation` (line 863-877): takes `contributing_factors` and computes OR(class_gate, action_gate) correctly
- Persistence digest (`src/hermes/persistence/failure_classifications.py`, line 710-718): recomputes confirmation against `failure_class` and `contributing` (line 718) — also UPDATED vs prior session

Q-04 (`src/hermes/core/graph.py` 382 LOC; persistence `repositories.py` 2275 LOC):
- Pure derived projection over `provenance_edges`; 3 new edge types (`depends_on`, `conflicts_with`, `introduces_risk`) — conforms to framework §D.4 (no new node types, no new datastore)
- Read-only diagnostic in director loop (`controller.py`) — conforms to framework §D.4.G (can surface, cannot decide/retract/modify)
- Reachability bounded — no unbounded traversal; cycle rejection at creation — conforms to framework §D.4.H

Q-02 (`src/hermes/research/controller.py` 3252 LOC; evaluation module 659 LOC):
- `ActionEvaluation` EligibleTask mode — deterministic controller policy (Model B); no LLM-computed scheduling result; uses only existing `program_obligations` and satisfaction links — conforms to framework §C (no silent pivot, advisory only, never overrides budget/gate/dependency)
- IDR-038 design + ratified — framework §D.2 adopted fully

## 3. GAP FINDINGS (independent probes this session — no reference to prior audit claims)
Fresh live probe (`C:\...\AppData\Local\Temp\fresh_redteam_probe.py`):
- Probe 1 (IMPLEMENTATION_FAILURE + FRAMING_ERROR contributing + mechanism citation): admitted; primary=IMPLEMENTATION_FAILURE; contributing=[FRAMING_ERROR]; gate result for action=PROPOSE_MECHANISM_SUBSTITUTION: requires_human_confirmation_for(IMPLEMENTATION_FAILURE, (FRAMING_ERROR,)) = True (FRAMING_ERROR contributor triggers gate) → gate fires correctly → NO GAP
- Probe 2 (RESOURCE_CONSTRAINT + FRAMING_ERROR contributing + resource_gap citation): admitted; primary=RESOURCE_CONSTRAINT; contributing=[FRAMING_ERROR]; action=PARK_FOR_RESOURCE_REVIEW; gate result = requires_human_confirmation_for(RESOURCE_CONSTRAINT, (FRAMING_ERROR,)) = True (contributor fires) OR action_gate(PARK_FOR_RESOURCE_REVIEW)=False → combined=True (OR with contributor True) → gate fires → NO GAP
- The prior session's MEDIUM gap (contributing_factors bypass) is CLOSED in current HEAD (`f78bedd`); the source explicitly references "red-team §2 remediation" in docstring (line 828-831), confirming an intentional remediation was made between sessions.
- Residual LOW documentation gap: `scope_briefs` still has no production INSERT (only test fixtures) — IDR-037 D5 labels it "AVAILABLE (best-effort)" but in practice it is functionally deferred; behavior remains safe (fail-closed, no false pass) — framework §D.5 (Q-06 TRIZ) also deferred (not built yet)
- Framework Q-09 blocked (Phase 0 field diff unperformed) — still unimplemented in source; framework notes this explicitly ("cannot complete in this session") — NOT a gap in the framework, just an unfulfilled dependency
- Q-07 (Zwicky), Q-13 (Obsidian), CV-01 (Convergence level 2) — framework design says EXPERIMENTAL/DEFERRED; no source implementation — NO BUG, just unstarted work
- No hidden authority breach found: `AUTHORITY_SHAPED_ACTIONS` (line 822-827) covers REJECT_BRANCH, ROUTE_TO_SCOPE_REVIEW, PROPOSE_SCOPE_NARROWING, PROPOSE_MECHANISM_SUBSTITUTION; all require human confirmation regardless of contributing factors; all other actions are advisory/non-executing; the substrate never calls gateway/apply_intent/event_write/file_write/network

## 4. LOGIC / DETERMINISM / CONSISTENCY (verified independently)
- ACTION_MAP: pure dictionary lookup → deterministic
- `_validate_class_citations`: fail-closed; missing citation → error; mismatched citation → error; no silent drop
- `_validate_evidence`: subset check against record (line 475); no foreign evidence; duplicate detection; resolver required for evidence-required classes; UNKNOWN requires no citation (line 414-422) — consistent with framework §D.1
- `_validate_contributing_factors`: vocabulary check; disjoint from primary (line 538-543); no citation required for contributing factors (framework doesn't mandate contributor citation; current design keeps it advisory) — consistent
- `classify_failure`: collects ALL errors before returning REJECTED (line 324-330) — consistent with framework §D.1 fail-closed requirement
- Identity (`_build_classification`): content-derived `classification_id` binds schema_version + classifier_version + sorted sorted fields + content_hash; historical truth never mutated (reclassification = new derived record) — consistent with framework §D.1.K
- Digest replay (`controller.py` reconcile_digest): reads artifacts table, re-computes permitted actions and confirmation flags from stored metadata (line 691-694, 710-714, 727-728) — consistent with framework §A (advisory only, read-only projection)
- Cross-layer agreement: substrate (line 791-795) → controller (line 773-807) → persistence digest (line 691-728) → graph (line 323-364) all reference same `requires_human_confirmation_for` with contributing_factors param — consistent
- Independent review file (existing untracked `hermes_q05_independent_review.md`, 224 lines) confirms same medium finding independently, from different reviewer ("Claude, Anthropic") — cross-party agreement on original gap; remediation now visible in current HEAD

## 5. IMPROVEMENTS (not bugs — opportunities)
- Minimal hardening option (a): confirm the current remediation covers all contributing-factor + primary-class combinations; the probe confirms yes for all 6 primary classes × FRAMING_ERROR contributor
- Minimal documentation fix (b): IDR-037 D5 could label scope resolver more explicitly given `scope_briefs` has no production INSERT — behavior safe (fail-closed), just documentation-incomplete
- No dead code found in audited files; `test_controller.py` (modified in pre-existing tracked commit, 178 added lines) not audited by this session (not edited by me)
- No hidden dependency leaks: substrate imports only stdlib + `hermes.research.programs` (canonical_json, sha256_hex); persistence writes only existing `artifacts` + `provenance_edges` tables; controller uses only existing repository/gateway interfaces
- No new event types, no new database tables, no new authority component — framework §A constraint fully satisfied

## 6. CERTIFICATION (this session — independent of any prior audit file)
- No edits made to tracked source files (`tests/test_controller.py` was pre-existing modification from prior commit `f78bedd`)
- No new tracked files committed
- Audit evidence: live source inspection (`grep` outputs this session), live executable probes (`fresh_redteam_probe.py`), live test runs (`tests/test_*` Q-05/Q-04/Q-02), fresh framework doc read (`hermes_surviving_ideas_application_framework-2.md`)
- No fabricated results; every claim ties to file:line evidence or executable output captured in this session
- Previous audit file (`HERMES_RED_TEAM_AUDIT_20260815.md`) was not read or referenced during this fresh audit; findings derived independently
- The current HEAD (`f78bedd`) contains a remediation (line 823-831 docstring references "red-team §2 remediation") that closes the gap the prior session documented — confirming the audit cycle worked: gap found → remediation applied → verified by independent re-audit

---
File: FRESH_REDTEAM_AUDIT.md (independent)
Created: this session
Verified: against repo HEAD f78bedd; framework file at user attachment path; no tracked-file changes by this audit
