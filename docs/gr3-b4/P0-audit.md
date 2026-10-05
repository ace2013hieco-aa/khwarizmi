# ADVERSARY audit — GR3 P0-context report (`547d5f6`, branch `gr3-b4/p0`)

Verdict: ACCEPT WITH CONDITIONS (2 conditions, 4 observations).
Scope: `docs/gr3-b4/P0-context.md` + `docs/gr3-b4/ROADMAP.md` at `547d5f6`
(P0 commit, parent `main@c0b5777`) reviewed against LIVE SOURCE on branch
`gr3-b4/p0-audit` (cut from `547d5f6`). Every finding cites source
locations. No claim was passed on the report's own authority. No remote
push (standing local-only order).

## Method (independent re-verification)

- Re-ran absence nets wider than the report: `GR3|GR4|gr3|gr4|
  GraphHypothesis|graph_hypothesis|anneal|LitKG|litkg` over `src/`;
  `supports|entails` over `src/`; `git log --oneline --all -- src/`
  filtered for `GR3|GR4|gr3|gr4|graph`; branch/worktree enumeration.
- Re-read each quoted invariant against `AGENTS.md:10-64` line by line;
  checked `docs/ARCHITECTURE.md:202-213` and `docs/STATE.md:58,105-110`.
- Checked role/profile/allowlist/schema vocabulary against
  `src/hermes/core/node.py:22-39`, `src/hermes/research/gateway.py:151-189`,
  `src/hermes/tools/research_sources.py:189-193`.
- Recounted `docs/idr/` (41 numbered + 9 others = 50); confirmed
  `docs/gr3-b4/` absent at `c0b5777`; confirmed `48e4ce9` not an
  ancestor of mainline.

## Passes (claims verified in code, no finding)

- (a) No "mature" overstatement: extraction end-to-end is wired
  (gateway EXTRACT admission `gateway.py:3594-3635`, imports `:67-71`;
  controller calls `accept_extraction_output` at `controller.py:4256`;
  `ClaimAssumptionRepository.record_extraction` at
  `persistence/repositories.py:1992`). Ladder derivation is consumed by
  the controller APPLY pass (`controller.py:566-569`,
  `_apply_evidence_ladder_pass` at `:3041`, importing
  `derive_obligation_rung` at `:3074-3077`). Gates/provenance/
  integrity_gates correctly reported as pointer/placeholder
  (`gates.py:1-6`, `integrity_gates.py:1-4`, `provenance.py:1-4`).
  Test pins exist (`test_extraction_pipeline.py`,
  `test_q05_evidence_ladder.py`, `test_chg1_contradictions.py`,
  `test_claims.py`, `test_s1_detector_rows.py`,
  `test_claims_write_path.py`).
- (b) GR3/GR4 absence as implementation CONFIRMED: wider net over `src/`
  returns only `gateway.py:1295-1297` (forward-reference comment) plus
  English-prose "supports" in `claims.py:74,188,474` (SupportState
  comments, not edge types). No `GraphHypothesisService`, no annealing,
  no LitKG in `src/`. `src/hermes/core/graph.py:91` (`detect_cycle`)
  and commit `24a3fad` (Q-04 failure cone) are task-dependency/cycle
  utilities, not GR3 (see observation O4). No `gr3/gr4` branches;
  worktrees are `n9-closure`, `Development`, `platform/r1-delta`,
  `Research-agent`, `step-4`. Log hits for GR3/GR4 are docs-only
  (ratification/proposal records, e.g. `b576090`, `ccb685d`,
  `48e4ce9` on the unmerged `texp-001/p2` line).
- (c) S6 quotes VERIFIED faithful: all 12 bullets match
  `AGENTS.md:16-64` verbatim; `ARCHITECTURE.md:202-213` is §3.11
  ("Merely possible (not supported — requires a design gate)");
  `STATE.md:58` states "50 records"; `STATE.md:105-110` defers agent
  runtimes. The "no literal S6 heading" correction is itself correct
  (no `S6` match in `AGENTS.md`, `ARCHITECTURE.md`, `STATE.md`,
  `API.md` by direct search).
- Line-citation spot checks all pass: `cli.py:59`
  (`pkg_version("khwarizmi-research")`); `http.py:110` (user-agent);
  `intents.py:124/133/144` (`llm_proposable`/`director_only`/
  `internal_only`); `gateway.py:93-109` (codes), `:2593`
  (`_cx_resolve_evidence_ref`); `event_validation.py:22-23,74-81`
  (4 KiB); `source_outcomes.py:159` (N9 predicate).
- (e) Roadmap/IDR claims hold: `docs/gr3-b4/` absent at `c0b5777`;
  sole roadmap-like file at baseline is the historical audit
  `docs/archive/HERMES_PHASE3_BACKLOG_ROADMAP_AUDIT_2026-09-20.md`;
  `docs/idr/` counts 41 × `IDR-*.md` + 9 others = 50; `48e4ce9`
  (texp `IDR-042` plan-only) is not a mainline ancestor
  (`merge-base --is-ancestor` exit 1); TEXP twin absent from the
  `c0b5777` tree, 23 files under `experiments/texp-001/` at
  `texp-001/s6-audit @ a927c7a`.

## CONDITION C1 — schema CHECK admits five edge types, not three

Report §(d) states "schema (`migrations.py`, `provenance_edges` CHECK)
carries exactly these three", quoting the `gateway.py:1293-1302`
comment. Live source: `migrations.py:260-262` —
`CHECK (edge_type IN ('cites', 'derived_from', 'supersedes',
'used_as_input', 'justifies'))`. The "exactly three"
(`cites`/`derived_from`/`used_as_input`) is the *dependency-class
subset* the S5 cascade walks (`gateway.py:1302`), not the schema
domain: `supersedes` (supersession) and `justifies` (ratification-ref
carriers) are also schema-legal. The GR3 delta (`supports`/`entails`
absent) is unaffected. Correction required at P1 charter: cite the
5-value CHECK with the 3-type cascade subset distinguished.

## CONDITION C2 — "project allowlist" is not a repo convention

Report Decisions states `project allowlist "khwarizmi-research"`. The
repo defines no project allowlist: projects are UUID rows with
per-query isolation (`ARCHITECTURE.md:127-136`; cross-project citation
fails closed). The repo's allowlist is provider-scoped:
`SOURCE_PROVIDER_ALLOWLIST` (`research_sources.py:189-193`,
`gateway.py:89`). "khwarizmi-research" is the package/repo name
(`pyproject.toml`), not a project scope, and P0 touched no project.
Correction required at P1 charter: replace the field with "no project
touched; provider allowlist untouched (`research_sources.py:193`)".
Role-slot values themselves are valid vocabulary (`AgentProfile`:
`node.py:32-39` — DIRECTOR/RESEARCHER/IMPLEMENTER/ADVERSARY +
DETERMINISTIC; role gate `gateway.py:151-189`), and the report
correctly records that no intent/event/authority was exercised, so
this is a field-convention defect only, not an authority breach.

## Observations (no action required for P0 acceptance)

- O1: Role fillings (`IMPLEMENTER` profile, `DETERMINISTIC`
  partition) are nominal — P0 proposed no intent, so no role was
  exercised. Harmless as workflow bookkeeping; valid vocabulary.
- O2: "task GR3-P0-context" is a workflow label, not a repo `task_id`
  (content-addressed per `extraction.py`); the report does not
  conflate them.
- O3: "Phase 0 placeholder" language at `evidence_transitions.py:3`
  and `failure_classification.py:4-5` refers to the v6 §10 evidence
  *store* (no evidence table/`EvidenceRepository`), distinct from the
  implemented ladder derivation + APPLY pass. No contradiction with
  the report's ladder characterization. Same for the historical
  "explicitly deferred" note at `claims.py:25` — superseded by the
  wired P7 path cited above.
- O4: `src` graph utilities (`core/graph.py`, Q-04 cone) predate GR3
  and are outside its scope; the report's absence claim is correctly
  scoped to GR3/GR4 implementation.

## Acceptance

P0 stands ACCEPTED WITH CONDITIONS C1+C2, both owned by the P1
charter (wording corrections only; no code, no re-run, no gate
implied beyond P1's own chartering). This audit is docs-only:
`docs/gr3-b4/P0-audit.md` added on `gr3-b4/p0-audit` from `547d5f6`;
zero `src/`/`tests/` changes; no push.
