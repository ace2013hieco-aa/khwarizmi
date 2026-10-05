# Hermes Phase 3 Backlog + Roadmap Audit — 2026-09-20

## §0 Executive decision

Do NOT split god modules yet. First: ratify the stability convention
(A-05), consolidate test helpers (D-01), and run three design gates
(DG-2 controller, DG-3 gateway, DG-5 inversion — DG-4 repository is
near-mechanical). Only then decompose, smallest-seam first
(repositories per-class, gateway contradiction-pair, controller
reads). Everything else is P2/P3 or explicitly rejected.

## §1 Baseline

`HEAD == origin/main == 44aa1a3`, branch `main`, tree clean except
known untracked (`IDEA.md`, external `orci/orhead/ortree.json`).
Chain verified: Phase 0 (`HERMES_PHASE0…`), Phase 1
(`HERMES_PHASE1…`), Phase 1.1 (`HERMES_PHASE1_1…`, verdict
`PHASE 1.1 — CERTIFIED` for `97c09ce`), Phase 2
(`HERMES_PHASE2…`). Read in full: `AGENTS.md`, `docs/ARCHITECTURE.md`,
`docs/API.md`, `docs/STATE.md`, Phase 2 report, original improvement
audit. Read-only: validation rerun proves zero behavior change
(2035/0/0/0, ruff clean, pyright src 0, tests-profile 0+1
pre-existing).

## §2 Certification-chain verification

Phase 0 → 1 → 1.1 → 2 reports present and internally consistent
with the tree (counts, SHAs, gates). No certified invariant was
touched by documentation phases (suite identical).

## §3 Previous-audit reconciliation

- H1 god modules (controller 4327 / gateway 3868 / repositories 2754
  — re-measured current, unchanged): OPEN, refined. Controller
  cohesion LOW (76 methods, 8 duty clusters sharing
  `_fenced/_conn/_clock/_project_id` on every path); only the
  detection-read cluster is near-separable. Gateway cohesion MEDIUM
  (14 validators despite "~40" shorthand — corrected count; 3 share
  `_decision_append_transactional`, 3 share
  `_resolve_ratified_proposal`, rest intent-isolated; contradiction
  pair is the one clean seam). repositories cohesion HIGH per-class
  / LOW per-file (11 repos, disjoint tx sets — mechanically
  splittable). Size alone never justifies a split; seams above do.
- H2 inversion: OPEN, refined. 13 upward imports in 4 files; 11 are
  ARCHITECTURAL (domain validators/types re-run at write paths:
  substrate, identity re-derivation, HR-08 guard, slot vocabulary,
  resolvers) and only 2 sites INCIDENTAL (generic
  `canonical_json`/`sha256_hex` in `program_obligations.py:55,169`
  — 10+ importers across research+tools). A naive "correction"
  moving domain logic down would violate Model D/EC-V6 self-
  consistency. DG-5 mandatory.
- H3 sprawl: PARTIALLY RESOLVED (6 zero-reference moves + 4 reports
  closed; 83 tracked root `.md` remain, densely cross-referenced —
  remainder needs a reference-migration plan, item B-01).
- Mediums: test duplication OPEN (D-01); accidental publics OPEN
  (A-03); stability model PARTIALLY RESOLVED (convention exists in
  `docs/API.md`, needs ratification A-05); AGENTS RESOLVED;
  backlog itself RESOLVED-BY-THIS-REPORT (issues still zero —
  deliberate until items are ISSUE-READY); diagrams RESOLVED
  (B/C added in Phase 1 `ARCHITECTURE.md`); onboarding PARTIALLY
  RESOLVED (Phase 1 done; per-seam examples B-02 remain);
  notes-bound + IntentApplied-on-duplicate OPEN (A-04); STALE wart
  OPEN (F-01); ancestor scope OPEN, leaning DEFERRED (F-02).
- Lows: naming nits INVALIDATED as work (cosmetic, DO-NOT-TRACK);
  `.ruff_cache` RESOLVED (Phase 0); placeholder stubs PARTIALLY
  RESOLVED (3 pointed, rest documented).

## §4 Phase 2-derived findings

N1 validator-less intents (6 kinds, `NOT_WIRED` only) need a dead-
or-future decision (A-01). CLI repository-direct reads are a
de-facto supported read pattern, undocumented as such (A-02).
`__all__` + package-attribute access create a thin compatibility
surface (`adapters.ArxivAdapter`, `TickResult`, `notes`,
`run(max_ticks)`) needing declaration (A-03/F-03). Contract tests
missing for IntentApplied-on-duplicate + notes bound (A-04).
Stability convention needs ratification, not new machinery (A-05).

## §5 Backlog

### A — Contract / API

**A-01 Decide the six validator-less intents.** Class: A. Priority:
P1. Problem: `BRANCH,ABANDON,REQUEST_HUMAN,REQUEST_REPLICATION,
REQUEST_ADDITIONAL_EXPERIMENT,PROPOSE_GATE_OVERRIDE` parse but can
never validate (`gateway.py:3816-3824` `NOT_WIRED`). Evidence:
zero `Intent(kind=…)` constructions in `src/`. Affected:
`core/intents.py:40-47,115-121`, `gateway.py:3816`. Prerequisites:
none. Risk: LOW (decide dead→remove from enum or specify→new
validators). Benefit: kills a whole ambiguity class. API impact:
removal is breaking-if-relied-upon (nothing relies — verified);
specification is new surface. Invariants: none if removal; full
gate if specification. Gate: DG-1. Status: DESIGN ONLY first
(decide dead vs future). Validation: suite + role-partition tests.
Depends on: —. Blocks: E-02 (final intent set). DoD: enum +
partitions + docs/API.md updated, or removal with tests proving
zero references.

**A-02 Document CLI repository-direct reads as the supported read
pattern.** Class: A. Priority: P2. Problem: `docs/API.md` labels
repository construction UNDECLARED while `cli.py` constructs
repositories for every read (`:176-177,249,326,343,364,401,433,457,
604,644`). Evidence: above lines. Files: `docs/API.md` only.
Risk: NONE (docs). Benefit: ends the contradiction. Gate: none.
Validation: link audit. DoD: API.md read-pattern section merged.

**A-03 Declare accidental publics.** Class: A. Priority: P2.
Problem: `core/graph.py` queries, `first_present/
extract_xml_items`, `classifications_digest`, `TickResult`/`notes`
shapes, package-attribute adapter access are reachable without a
stated contract. Evidence: Phase 2 §4/§7. Files: docs first;
renames (`_` prefix) only with DG-1 + suite. Risk: LOW (docs),
MEDIUM (renames — controller-internal callers only, verified).
Gate: DG-1 for renames; docs portion needs none. DoD: every item
labeled INTERNAL or underscore-renamed with tests green.

**A-04 Contract tests: IntentApplied-on-duplicate + notes bound.**
Class: A(+D). Priority: P2. Problem: governed behaviors without
named tests (Phase 2 §7 gaps). Evidence: `gateway.py:3832`,
`controller.py:476` property. Files: `tests/` only. Risk: NONE
(test-only). Gate: none. DoD: 2+ tests pinning event-count on
duplicate admission and notes growth bound.

**A-05 Ratify the stability convention.** Class: A. Priority: P0.
Problem: `docs/API.md` convention works but is unratified; every
structural refactor needs it frozen first. Evidence: Phase 2 §5/§12.
Files: decision record (+ API.md pointer). Risk: NONE. Gate:
DG-1 (it declares public surfaces). Status: DESIGN ONLY (a
decision, not code). DoD: IDR merged; decomposition gates
reference it.

### B — Documentation / DX

**B-01 Root historical-sprawl migration plan.** Class: B. Priority:
P1. Problem: 83 tracked root `.md`, densely cross-referenced;
Phase 0 moved only the 6 zero-reference files. Evidence: §3 + H3.
Prerequisites: none. Risk: LOW (moves + reference migration,
verified by link audit; stop on ambiguity per Phase 0 rules).
Gate: none (docs). DoD: root holds entrypoints + contracts only;
index updated; link audit clean; suite green.

**B-02 Per-seam worked examples.** Class: B. Priority: P3.
Problem: adapter/classification/extension seams discoverable only
by reading code. Depends on: A-05 (contract frozen first).
Risk: NONE. Gate: none. DoD: one runnable example per seam using
only PUBLIC surfaces (CLI tour precedent:
`examples/first_run.py`).

**B-03 STATE.md upkeep cadence.** Class: B. Priority: P2. Problem:
STATE rots between milestones. Evidence: Phase 1.1 drift it just
fixed. Risk: NONE. DoD: dated STATE refresh per milestone (process,
not code).

### C — Code quality

**C-01a Extract oversized gateway validators.** Class: C. Priority:
P2. Problem: `_validate_curate_knowledge` 712 lines
(`gateway.py:1652`), `_validate_retract_source` 459 (`:1155`).
Evidence: measured. Prerequisites: A-05, DG-3 design. Risk:
MEDIUM (tx boundaries inside — extract steps, never split a
`BEGIN/COMMIT` pair). Gate: DG-3 + owning slice re-run. DoD:
named step-helpers, identical behavior (suite + gate).

**C-01b Extract oversized repository/program methods.** Class: C.
Priority: P2. Problem: `record` 399 (`repositories.py:1232`),
`record_extraction` 359 (`:1939`), `_compile_research_program_
checked` 457 (`programs.py:583`), ladder pass 335
(`controller.py:3131`), `evaluate_hazards` 320
(`hazards.py:1131`). Same conditions as C-01a. Gate: DG-2/DG-4 as
applicable. DoD: same.

**C-01c Ladder/evaluation/hazard helpers.** Class: C. Priority:
P3. Same pattern, lower value. Gate: owning slice re-run. DoD: same.

### D — Test architecture

**D-01 Shared `tests/support.py`.** Class: D. Priority: P1.
Problem: `_make` ×15 files, `_classify` ×4, `_chain`/`_program`
variants, provider-machinery builders re-implemented
(`test_chg1/p6/n9/p4`, …). Evidence: Phase 2 §7 inventory.
Prerequisites: none. Risk: LOW (test-only, behavior-neutral).
Gate: none (full suite is the gate). DoD: helpers consolidated,
all suites green, no production import changes.

**D-02 Split `test_controller.py` (7207 lines).** Class: D/G.
Priority: P3, BACKLOG-ONLY, conditional on demonstrated editing
friction. Risk: LOW. DoD: split only with a stated trigger.

### E — Structural refactoring

**E-01 Controller responsibility map.** Class: E. Priority: P0.
Status: AUDIT FIRST + DESIGN ONLY. Problem: 76 methods, 8 duty
clusters, all sharing fence/clock/project — no split is safe
without an ownership map. Evidence: §3/H1. Gate: feeds DG-2.
DoD: cluster map + shared-state table + seam ranking, no code.

**E-02 Gateway validator extraction seam.** Class: E. Priority:
P0. Status: DESIGN ONLY. Problem: placement of 14 validators +
shared helpers (`_require_*`, `_resolve_ratified_proposal`,
`_decision_append_transactional`, `_cx_*`) across modules without
splitting transactions. Depends on: A-01 (final intent set), A-05.
Gate: DG-3. DoD: module map with tx-ownership proof per validator.

**E-03 Repository per-class split.** Class: E. Priority: P1.
Problem: 11 transactionally-isolated repos in one 2754-line file.
Evidence: disjoint `BEGIN/COMMIT/ROLLBACK` sets per class; shared
helpers only `_json_*`, `_append_event_to_db`. Depends on: DG-4,
A-05. Risk: LOW-MEDIUM (mechanical moves). Gate: DG-4 + full
suite + write-path slices. DoD: one module per repo, imports
updated, suite + gates green.

**E-04 Controller reads extraction.** Class: E. Priority: P2.
Problem: 19 read/digest methods coupled to the fence owner.
Depends on: E-01, DG-2. Risk: MEDIUM (fence lifetime coupling).
Gate: DG-2 + read-slice tests. DoD: reads module with explicit
fence-passing contract, behavior identical.

**E-05 Persistence→research direction correction.** Class: E.
Priority: P1. Status: DG-5 FIRST (mandatory), then minimal
implementation. Problem: 13 upward imports; 11 ARCHITECTURAL
(domain re-derivation at write paths — must NOT move down),
2 INCIDENTAL (`canonical_json`/`sha256_hex` uses in
`program_obligations.py:55,169`). Depends on: DG-5, A-05. Risk:
HIGH if misscoped (Model D/EC-V6 boundaries live here). Gate:
DG-5 + P6/N9/P7 slices. DoD: generic helpers descended to
`core/` (or equivalent) with all ~12 importers updated; domain
validators stay research-owned; lazy cycles reduced, none added;
suite + gates green.

**E-06 Lazy-cycle formalization.** Class: E. Priority: P2. Part
of DG-5. Problem: 3 lazy pairs held together by comments.
Depends on: DG-5. DoD: each pair documented with owner + rule,
or dissolved by E-05.

### F — Architecture correction

**F-01 STALE-guard project filter.** Class: F. Priority: P2.
Problem: S5 STALE probe (`gateway.py:1295-1300`) lacks a project
filter — retracting a globally-shared row in p1 makes p2's later
retraction STALE. Evidence: P7/N9 gates. Depends on: DG-6 review
+ S5 slice re-run. Risk: MEDIUM (retraction semantics adjacent).
Gate: DG-6. DoD: project-scoped STALE with S5 regression green;
p2 independence proven by test.

**F-02 Ancestor-scope question.** Class: F. Priority: P3. Status:
DESIGN ONLY. Problem: whether retraction should fence transitive
citations (S5 is point-in-time by design). Risk: HIGH if answered
wrong (permanent ancestry poisoning). Gate: DG-6 + dedicated
design deliberation. DoD: decision record either way.

**F-03 Package export surface declaration.** Class: F(+A).
Priority: P2. Problem: `__all__` (39 sites) + package-attribute
access imply compatibility silently. Depends on: A-05. Risk: LOW
(declaration first; trims only under DG-1). Gate: DG-1 for trims.
DoD: export policy recorded; trims (if any) with suite green.

### G — Deferred / Optional

G-01 D-02 (conditional split). G-02 B-02 (post-contract examples).
G-03 per-provider worked examples beyond contract cards. G-04
migration-down tooling: REJECTED (forward-only is architecture).

## §6 Non-work / rejected work

DO NOT IMPLEMENT: semver/schema-registry/deprecation-framework/
compatibility-matrix/generated-specs (no consumer — Phase 2 §12);
telemetry, dashboards, plugins, signing, microservices, event bus,
agent frameworks, workflow engines, synthesis entities,
observability stacks, modernization sweeps, arbitrary line-count
targets, cosmetic renames (naming nits), `IntentApplied` audit-
volume reduction, notes-cap tests-first, migration downgrades,
moving files for aesthetics, tests for pure internals, versioning
machinery of any kind. Rationale per item: no demonstrated need +
certified behavior at risk; recorded here so future prompts cannot
reintroduce them as "obvious improvements".

## §7 Dependency graph

Hard: A-05 → {E-02, E-03, E-04, DG-2, DG-3, DG-4, F-03};
E-01 → DG-2 → E-04; DG-5 → {E-05, E-06}; DG-6 → F-01.
Soft: A-01 → E-02; D-01 → {E-03, E-04} (eases, not required);
A-05 → B-02; A-02/A-03 → B-02 examples.
Independent: B-01, B-03, C-01a/b/c (post-gate), F-02 deliberation,
A-04, D-01. Mutually exclusive: remove-vs-specify in A-01 (decide
once). Must wait for gates: all E-03..E-06 implementation, F-01,
C-01a/b/c, A-03 renames.

## §8 Design gates

DG-1 Public API boundary (A-01, A-03 renames, F-03 trims):
establish observable-surface list + compatibility promise first.
DG-2 Controller (E-01 → E-04): responsibility ownership, tx
boundaries, API preservation, invariant ownership, test seams.
DG-3 Gateway (E-02, C-01a): validator placement with tx-ownership
proof; shared-helper ownership. DG-4 Repository (E-03):
per-class module map; read-only classes trivially approved.
DG-5 Inversion (E-05, E-06) MANDATORY: desired direction,
concept ownership, lazy-import replacement, tx/identity/replay/
isolation/invariant preservation proofs. DG-6 Invariant impact
(F-01, C-01*): explicit review for anything touching
apply_intent/journal/replay/lease/authority/identity/
contradiction/retraction/payload-bounds/isolation.

## §9 Safe/unsafe refactor matrix

| Area | Safe now? | Conditions |
|---|---|---|
| pure internal helper | YES | suite green; no tx crossing |
| validator placement | NO | DG-3 + tx-ownership proof |
| read grouping | NO | DG-2 (fence coupling) |
| Controller | NO | E-01 + DG-2 |
| Gateway | NO | E-02 + DG-3 |
| repositories | NO | DG-4 (then mechanical) |
| provider adapters | YES (additive) | contract tests green; no hook changes without DG-1 |
| intents | NO | DG-1 (A-01 decision first) |
| events | NO | architecture decision (durable) |
| journal | NO | never (append-only invariant) |
| replay | NO | CHG-2 gate |
| identity/hash | NO | certified invariant + gate |
| authorization | NO | human-authority gate |
| persistence direction | NO | DG-5 mandatory |

## §10 Roadmap

Stage A — Contract closure: A-05 (decision) → A-01 (decide) →
A-02/A-03-docs/A-04 (docs+tests). No behavior change; unlocks all
structural work.
Stage B — Low-risk quality: D-01, B-01, B-03, F-03-declaration,
A-03-doc-labels. Independent, parallelizable.
Stage C — Structural design: E-01, E-02, DG-2/3/4/5/6, F-02
deliberation. Design-only artifacts.
Stage D — Structural implementation (gates passed only): E-03,
E-04, E-05-incidental, F-01, C-01a/b/c.
Stage E — Verification: full suite + ruff + pyright + owning-gate
re-runs + adversarial probe of moved boundaries + conformance
review against §9 matrix. No calendar dates; dependency order only.

## §11 Issue readiness

ISSUE-READY: A-02, A-04, B-01, B-03, D-01, F-03-declaration.
NEEDS-DESIGN-FIRST: A-01, A-03-renames, C-01a/b/c, E-03, E-04,
E-05, F-01, B-02. BACKLOG-ONLY: D-02, F-02, G-01..G-03.
DO-NOT-TRACK: naming nits, line-count targets, all §6 machinery.
No issues created (zero-issue policy holds until owners approve
tracking; this report IS the backlog).

## §12 Adversarial review

1. Work from age/size? PASS (H1 refined to seams; C-graded by
   value; §6 rejects size-targets). 2. Duplicating Phase 0/1?
   PASS (H3 split: done vs remainder; no reopened items).
3. Every symbol an API project? PASS (INTERNAL/UNDECLARED default;
   only evidenced surfaces tracked). 4. Abstractions before
   ownership? PASS (E-01/E-02/DG-5 precede moves). 5. Superficial
   inversion fix? PASS (11/13 sites classified ARCHITECTURAL —
   must stay; only incidental helpers move). 6. Splits breaking
   tx? PASS (tx-ownership proof required in DG-2/3/4, C-01).
7. Tests for internals? PASS (A-04/D-01 target contracts and
   helpers, not internals). 8. Unneeded machinery? PASS (§6
   rejects all six). 9. Invariants altered gateless? PASS
   (DG-6 + matrix mark 9 areas NO). 10. Dependencies modeled?
   PASS (§7 hard/soft/independent/exclusive). 11. Weak value?
   AMBIGUOUS (B-02 examples: value assumed from onboarding gap,
   not yet demonstrated — flagged, P3). 12. Parallel execution?
   PASS (Stage B independent; D journeys isolated; gates
   serialize only D). 13. Too broad to validate? PASS (units
   sized with DoD each; E-items split map/design/implement).
14. Contract preserved? PASS (A-05 first; §9 matrix). 15. Risk
   reduced not moved? PASS (splits follow tx seams; inversion
   keeps domain ownership; nothing relocated for aesthetics).
Result: 14 PASS, 0 FAIL, 1 AMBIGUOUS (documented).

## §13 Final recommendation

Execute Stage A now (A-05 decision, A-01 decision, A-02/A-04
docs+tests — zero behavior risk, unlocks everything). Then Stage
B in parallel (D-01 first — highest value/lowest risk). Then
Stage C gates before any structural move. First implementation
after gates: E-03 (mechanical, highest clarity yield), then E-05
incidental helpers, then E-04. F-01 rides DG-6 when S5-adjacent
work opens. Never without gates: §9 NO rows.

## §14 Phase 3 decision

```text
PHASE 3 — BACKLOG + ROADMAP COMPLETE / IMPLEMENTATION GATE REQUIRED
```
