# Hermes Architecture & Repository Quality Improvement Audit — 2026-09-20

Baseline: HEAD == origin/main == `14fc64a`, branch `main`, tree clean
(untracked only: pre-existing `.freebuff/`, `IDEA.md`, plus uncommitted
certification reports including this file). Read-only audit; nothing
modified, no code/tests/issues touched.

## Executive Summary

Genuinely strong: the certified core (deterministic control, single
`apply_intent` mutation path at `src/hermes/research/gateway.py:3732`,
append-only journal, lease-fenced single writer
`src/hermes/research/controller.py:2426`, refusal-as-data with 213
structured `raise _reject` sites in `gateway.py`, N1/N9 semantics,
record/replay determinism) is real — verified against implementation,
not documentation. Provider adapters are exemplary (11 thin adapters,
zero imports of `research`/`core`/`persistence`, clean 4-hook ABC at
`src/hermes/tools/providers/base.py:139`).

Needs improvement, in order: (1) 89 root-level `.md` files bury every
newcomer and the README status is frozen pre-N9/P7; (2) three god
modules (`controller.py:4327`, `gateway.py:3868`,
`repositories.py:2754`) plus a persistence→research layer inversion
with 3 lazy-broken import cycles; (3) ~17 "Phase 0: placeholder" stub
files that now actively misdirect (the reconcile loop lives in
`controller.tick`, not `reconcile.py`); (4) no declared API stability
model and several accidental-public surfaces; (5) zero GitHub issues
(no backlog exists at all); (6) no AGENTS file, no CONTRIBUTING, no
examples/, no API reference. No cargo-cult additions recommended.

## Current Architecture (reconstructed from code)

```
CLI (cli.py:823, 15 subcommands, argparse) ──operational surface only
        ↓  Controller construction + run()/tick()
Controller (controller.py:340, 76 methods, 30 public:482-3789)
  ├── reconcile loop: tick() (lease→mode→ladder→detect→requeue→dispatch)
  ├── verdict surfaces (operator/lease/HumanDecision → intents)
  └── read surfaces (digests, cones, candidates — D8 advisory)
        ↓  Intent (internal_only:8, llm_proposable:9, director_only:2)
gateway.apply_intent (gateway.py:3732) — SOLE mutation boundary
  ├── 40+ _validate_* functions (largest: _validate_curate_knowledge 712
  │   lines :1652, _validate_retract_source 459 lines :1155)
  └── role/project/payload checks → repository.write → journal append
repositories (repositories.py:2754, 14 classes; failure_classifications,
source_outcomes, provider_interactions, program_obligations)
  ├── each writer owns its BEGIN IMMEDIATE tx (33 sites repo-wide)
  └── journal: _append_event_to_db, append-only, no DELETE in src
providers (RecordedTransport replay.py:293; paginate walk :184;
hazards evaluate_hazards :1131) — network quarantined behind transport
artifacts (content-addressed store store.py:184) + SQLite (17 migrations)
```

Real boundaries discovered: CLI→Controller→Intent→gateway→
repositories→journal is as documented; BUT persistence imports
`hermes.research` in 4 modules (failure_classifications.py:52,
program_obligations.py:55,169, repositories.py:52,62-64,236,1259,1298,
1379,2440, source_outcomes.py:41), i.e. the persistence layer depends
UPWARD on domain logic — a layer inversion, currently managed with
lazy imports at 3 known cycle pairs (repositories↔source_outcomes,
repositories↔completion, repositories↔extraction). Over-concentration:
`Controller` owns orchestration + verdicts + reads + leases;
`gateway.py` owns ~40 validators; `repositories.py` owns 14 classes.
`Controller` has 76 methods (:340-:4327); `TickResult`, `_Fenced-
Connection`, lease helpers live inside the same file.

## Architecture Diagram Proposal

Needed: (B) runtime/control-flow — tick→lease→passes→dispatch with
mutation/journal points (does not exist as a maintained doc); (C)
persistence/journal — tables, edges, events, decision artifacts,
retraction projection (scattered across S5/N9 gates, no single view).
Already covered: (D) trust/authority — `docs/diagrams/
authority_trust_boundary.html` exists; (A) system context — partially
in README + v6 §2, needs a one-page version; (E) research workflow —
NOT present as a maintained diagram (lives implicitly in tests).
Recommendation: author B + C as text-maintained diagrams (mermaid in
`docs/diagrams/mermaid/`, matching existing convention), condense A
into README, derive E from the P7-certified chain. Do not auto-create
all five as artwork; B and C are the genuine gaps.

## Code Quality

- Severity: HIGH | Category: ARCHITECTURAL RISK | Finding: god-module
  concentration | Evidence: `controller.py:4327` (76 methods),
  `gateway.py:3868` (~40 validators), `repositories.py:2754`
  (14 classes) — top-3 of 95 src files (31,574 lines) |
  Impact: change coupling, review burden, onboarding cost |
  Recommendation: bounded mechanical splits only (validator modules
  per intent family; repository per-entity files; Controller read
  surfaces extracted), each landed with the full suite green |
  Implementation risk: MEDIUM (moves code, touches certified paths;
  needs regression certification per split).
- Severity: HIGH | Category: ARCHITECTURAL RISK | Finding:
  persistence→research layer inversion + 3 lazy-broken cycles |
  Evidence: imports listed above; cycle comments at
  `source_outcomes.py:254,775`, lazy `repositories.py:236` |
  Impact: direction violation; future refactors can detonate the
  lazy discipline; new engineers misread layering |
  Recommendation: invert the seam — move shared pure helpers
  (canonical_json/sha256, EXTRACT_TEMPLATE, thesis resolvers)
  down into `core/` or a `persistence`-neutral module; keep
  `can_complete_research` behind the existing gateway/controller
  call, not a persistence import | Risk: MEDIUM (behavior-neutral
  moves, full-suite verification).
- Severity: MEDIUM | Category: CODE-QUALITY ISSUE | Finding: oversized
  functions | Evidence: `_validate_curate_knowledge` 712 lines
  (`gateway.py:1652`), `_validate_retract_source` 459 (`:1155`),
  `_compile_research_program_checked` 457 (`programs.py:583`),
  `record` 399 (`repositories.py:1232`), `_apply_evidence_ladder_pass`
  335 (`controller.py:3131`), `evaluate_hazards` 320
  (`hazards.py:1131`) | Impact: reviewability | Recommendation:
  extract sequential steps into named helpers without behavior
  change | Risk: LOW with suite green.
- Severity: MEDIUM | Category: CODE-QUALITY ISSUE | Finding:
  misleading placeholder stubs (~17 files, 1–6 lines each) |
  Evidence: `research/reconcile.py:6` ("the driver around the task
  graph") while the loop is `controller.tick()` (`:482`);
  `research/gates.py:4` placeholder while gates resolve via
  `controller.resolve_human_gate` (`:1246`); `agents/*.py:4`
  "Not implemented until P4" (P4 certified other slices);
  `vault/projection.py:6`, `recovery/*`, `engineering/*` stubs |
  Impact: active misdirection of readers | Recommendation: replace
  each stub docstring with a pointer to the real implementation
  (docs-only, zero behavior change) | Risk: NONE.
- Severity: LOW | Category: CODE-QUALITY ISSUE | Finding: scattered
  duplication of refusal/transaction idioms | Evidence: 213
  `raise _reject` (consistent — a strength, not a defect);
  `BEGIN IMMEDIATE` ×33, `refusing to persist` ×20, `fail-closed`
  ×120 all follow identical shapes | Recommendation: no
  abstraction (the explicitness is load-bearing for audit); at most
  a documented idiom note | Risk: NONE.
- Strengths (FACT): zero `TODO/FIXME` in src; zero bare `except:`;
  53 `except Exception` of which 20 carry justified `noqa: BLE001`
  (e.g. `cli.py:330`, `controller.py:529`); zero pytest imports in
  src; no test-only leakage; module globals are frozen config
  tables (`_TRANSITIONS`, `ACTION_MAP`, `PROVIDER_REGISTRY`
  `adapters/__init__.py:37`) plus one intentional timing cache
  (`_OPERATOR_DUMMY_HASH`, `repositories.py:1004`, constant-work
  PBKDF2); naming consistently snake_case (0 camelCase identifiers
  in src).

## API Surface

- Public/intended: CLI (15 subcommands, `cli.py:657-819`);
  `Controller` 30 public methods (`:476-:3789`); `IntentKind` 18
  members with role partitions (`core/intents.py:40-168`);
  `ProviderAdapter` 4-hook ABC + `PROVIDER_REGISTRY` (11 adapters);
  repository read/write methods; `apply_intent` itself.
- Internal: ~40 gateway validators, candidate-row derivation,
  digest helpers, L2 resolvers, migration internals.
- Test: per-file `_chain/_program/_classify` helpers (duplicated
  across `test_chg1/p6/n9` — see Test Architecture).
- Accidental-public (used only internally, no stability contract):
  `core/graph.py` pure queries (`failure_cone:157`,
  `blocked_roots:210`, `artifact_blast_radius:276` — only
  controller + one comment reference them);
  `base_adapter.first_present:39` / `extract_xml_items:52`
  (zero external importers); `classifications_digest`
  (`failure_classifications.py:633`, only `controller.py:624,632`).
  Recommendation: underscore-prefix or document as internal; zero
  behavior change; risk NONE.
- Implicit contract that should become explicit: `IntentKind` value
  strings + role partitions, `EventType` strings + payload keys,
  artifact content-hash schemes (`fc_`/`cx_`/`cres_`/`fx_`/`retract_`
  identity formulas), rejection-code vocabulary (16 gateway codes
  `:93-108`, ~13 controller codes, 6 completion codes
  `completion.py:96-101`, provider exception hierarchy
  `research_sources.py:614-703`). These are the de-facto wire
  contract (journal replay + cross-version reads depend on them).

## API Stability

Nothing declared; zero deprecation machinery in src (grep clean).
Minimal model recommended (no versioning machinery — unwarranted):
FROZEN-BY-CONVENTION (change only via architecture decision +
migration): intent/event type strings, content-identity schemes,
rejection-code meanings, provider fixture format, CLI command names.
EVOLVING (documented in PRs): validator strictness, detector inputs,
read-surface shapes, internal helpers. INTERNAL (free to change):
gateway validator internals, candidate derivation, L2 resolvers.
Only add machinery if an external consumer appears (none exists
today — the CLI is the sole external surface).

## Documentation

- ACTIVE (keep current): `README.md` install/operate/test sections
  (`:11-19`, `:185-231` — accurate, CI-mirrored); v6 architecture
  document; `config/hermes.toml`; `docs/ix/README.md`;
  `docs/diagrams/README.md`.
- REFERENCE: `docs/idr/` (50 records — the decision log, working as
  designed); `pyrightconfig*.json`, `scripts/*.sh` (executable docs).
- HISTORICAL (move out of root): 89 root `.md` files — design gates,
  audits, reviews, remediation reports (each valuable, collectively
  unnavigable). v3/v4 architecture docs (superseded by v6, keep as
  lineage in archive).
- STALE/MISLEADING: README status block (`:5-9`, frozen at the
  P3/Q-05 era — no P6/N9/P7/tick-loop); README `:46` ("every module
  holds a docstring placeholder" — false for ~30 implemented
  modules); README `:82`-era "YOU ARE HERE Phase 0" framing;
  stub docstrings cited above; `steal.md:240` (one-off exercise,
  archive it).
- MISSING: API reference (intents/events/errors/identities),
  examples/ end-to-end walkthrough, CONTRIBUTING, AGENTS file
  (none exists repo-wide — see AGENTS section), onboarding map,
  diagrams B/C (see §Diagram Proposal).

## AGENTS

FACT: no `AGENTS*` file exists anywhere in the repo (glob-verified).
The task premise of a bloated AGENTS document is therefore inverted:
the gap is absence, not excess. Agent guidance currently must be
reverse-engineered from README + 89 root docs + 50 IDRs (the exact
"excessive context / poor discoverability" failure, caused by missing
structure rather than a bad file). Proposed separation (to be
authored, ~150 lines total): (1) `AGENTS.md` — ACTIVE RULES only
(build/test/lint/typecheck commands, lease/journal/authority
invariants, refusal-as-data, what never to bypass, stop conditions);
(2) `docs/ARCHITECTURE.md` — invariants + module map + diagrams B/C;
(3) `docs/STATE.md` — current development state (generated per
milestone, allowed to go stale by header date); (4) `docs/archive/`
(already exists) — all certification records. Do not write yet per
audit scope; this is the single highest-leverage documentation act.

## GitHub Issues

FACT: zero issues exist (open or closed — `gh issue list --state
all` returns `[]`). There is no backlog to clean; one must be built.
Proposed clean backlog (from certified history + recorded warts):
EPICs: docs-restructure, API-contract, test-dedupe, bounded-splits.
Stories: README-status refresh; stub-pointer pass; accidental-public
pass; stability-model doc; AGENTS.md + ARCHITECTURE.md + STATE.md;
backfill issues for recorded warts (STALE project filter;
ancestor-scope question; `IntentApplied`-on-duplicate audit volume;
in-memory `_notes` growth bound). Bugs: none known (no defect found
in this audit that breaks certification). Each story must carry its
certification requirement (full suite + gates) and stop conditions.

## Repository Hygiene

- ACTIVE vs rest: `src/`, `tests/`, `scripts/`, `config/hermes.toml`,
  `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml` (single
  workflow), `docs/{idr,diagrams,ix,archive}` are coherent.
- LOCAL-ONLY but unignored (MEDIUM): `.ruff_cache/` and `.freebuff/`
  exist on disk, untracked, and match no `.gitignore` rule
  (`git check-ignore` confirms) — add both (one-line fix).
- GENERATED but present: `.venv/`, `.venv-py314/`, `.pytest_cache/`,
  `htmlcov/`, `.coverage` — all correctly ignored; `artifacts/`
  correctly root-anchored in gitignore while
  `src/hermes/artifacts/` stays tracked (verified correct).
- CERTIFICATION EVIDENCE placement is now correct (`docs/archive/`
  holds 3 gate reports + this audit will be the 4th).
- ARCHIVE-needed: the 89 root `.md` files (recommend
  `docs/archive/{gates,audits,designs}/` move with a root index;
 -forward-compat: keep v3/v4 lineage). Naming: consistent
  `hermes_<area>_<kind>.md` already — keep.
- `tests/`: 63 files, `conftest.py` (267 bytes) + empty
  `__init__.py`; `scripts/` tidy (5 files, all referenced by CI or
  README).

## Developer Onboarding

Answered today: what (README :1-3), why (v6 problem statement),
install/run/tests (README :11-19, :185-231, three supported ways),
decisions (docs/idr ×50), current-vs-historical (partially —
archive/ exists but root mixes eras). Unanswered/hard: important
APIs (no reference — must read `cli.py:657`, `intents.py:26`,
repository classes); extension guide (must infer ABC + enum seams);
never-bypass list (scattered across gates — belongs in AGENTS.md);
trust boundaries (diagram HTML exists, no text map); which of the 89
docs are current (needs the archive move + index); examples (none —
a `hermes init → run → audit` worked example is missing).
Missing-docs list is exactly the AGENTS + ARCHITECTURE.md + API
reference + examples + STATE.md set proposed above.

## Architecture Drift

- INTENTIONAL EVOLUTION: tick-loop wiring, N9 predicate, detector
  split — all gated and tested.
- BENIGN: `agents/*` placeholders (roadmap says Phase 4+, P4
  certified adjacent slices — consistent).
- DOCUMENTATION DRIFT: README status/placeholder claims (above);
  `reconcile.py`/`gates.py` docstrings vs real loop/gate homes;
  v6 §20 engineering plane vs `engineering/*` stubs (stubs say
  "later phases" — consistent, but link them).
- POTENTIAL VIOLATION: none found. The persistence→research imports
  look like drift but are load-bearing and lazy-guarded (classified
  instead as structural debt, §Code Quality).

## Dependency/Coupling

Fan-in highs: `Intent`/`IntentKind`, `TaskRepository`,
`ProjectRepository`, `_source_artifact_resolves` (7 call sites:
fetch R01 ×2, basis derivation, extraction deref, record path,
classification ownership+resolver) — all legitimate cores. Fan-out
high: `Controller` (core+persistence+6 research modules),
`gateway.py` (core+persistence+research+tools). Unstable direction:
persistence→research (above). No provider leakage (adapters import
only `tools/*`; sole exception `hazards.py:137` importing
`canonical_json` from `research.programs` — move that pure helper
down with the others). Test coupling: suites import production
surfaces only (no leakage either direction found). Smallest
separation improvements: (a) pure-helper descent (§Code Quality);
(b) validator modules per intent family; (c) keep adapter boundary
exactly as is (exemplary).

## Extensibility

Seams present and adequate — no plugin framework wanted or needed:
new provider = `ProviderAdapter` 4 hooks + registry row
(`adapters/__init__.py:37`) + hazard spec (11 precedents, ~40-60
lines each); new evidence type = `SOURCE_ARTIFACT_TYPES`-family
const + resolver prefix (explicit, fenced); new failure class =
`FailureClass` enum + `ACTION_MAP` (`failure_classification.py:116`)
+ test matrix (explicit by design); new workflow states = closed
enums (`LifecycleState`, `TaskStatus`, `OperationalMode`) + transition
tables (explicit, reviewable); new programs = `PROPOSE_RESEARCH_PROGRAM`
+ compiler (certified path); new review = proposal-action vocabulary
(IDR-041 pattern). Weakness: these seams are discoverable only by
reading code — the API reference + one worked example per seam
closes it without new machinery.

## Test Architecture

63 files / ~45,758 py lines / 2035 tests: boundaries are sensible
(`test_<area>.py` per slice; golden-fixture style deterministic;
contract tests exist for intents/authorities/replay). Issues
(MEDIUM, maintainability only): helper duplication (`_chain`,
`_program`, `_classify`, provider-machinery builders re-implemented
in `test_chg1/p6/n9/p4` — extract a shared `tests/support.py`
behind the existing `conftest.py`); `test_controller.py:7207`
(organize by class already — consider file split only if editing
friction is demonstrated); no contract test pins the `IntentApplied`
-on-duplicate audit behavior or the `_notes` growth bound (add two
small tests when touching those areas). Not slow for its size class;
not overcoupled (production surfaces only); coverage must not be
reduced.

## Unnecessary/Cargo-Cult Features

Explicitly rejected for Hermes, with reason: workflow engine
(reconcile loop + intents already are the workflow — certified);
agent framework (agents are explicit non-goals until P4+ slices;
LLM surfaces correctly quarantined by role partitions);
plugin architecture (11-adapter ABC suffices; no external consumer);
cryptographic signing (content-hash identity + journal ordering
suffice; no multi-party threat model); telemetry/dashboard
(CLI + `--json` surfaces suffice); identity/accounts (single-
operator credentials suffice); synthesis/question entities
(no consumer); observability stack (notes + events + audit CLI
suffice); microservices/event bus (single-writer SQLite is the
correct scale); API versioning machinery (no external consumer —
the stability *convention* in §API Stability suffices).

## Target State

Evolutionary, docs-first: (1) root `.md` → `docs/archive/` + index;
README status refresh + placeholder-claim corrections; (2)
`AGENTS.md` + `docs/ARCHITECTURE.md` (diagrams B/C) + API reference
+ examples/ + `docs/STATE.md`; (3) stability convention recorded;
(4) stub-pointer pass + accidental-public pass + gitignore 2 lines;
(5) shared `tests/support.py`; (6) bounded splits (validators,
repositories, Controller reads) + pure-helper descent — each gated.
Files affected: docs only for (1)-(4) (zero behavior risk);
`src/hermes/{research/gateway,controller,persistence/*}` surgically
for (6). Invariant impact: NONE if gated (full suite + ruff +
pyright + relevant gate re-run per change). Migration: none (no
schema changes proposed).

## Roadmap

- Phase 0 — Hygiene (1 day): gitignore +2 lines; archive move +
  root index; README status refresh; stub-pointer pass. Stop: full
  suite green (docs-only, but prove it). No gate needed.
- Phase 1 — Documentation + map (1 week): AGENTS.md, ARCHITECTURE.md
  (B/C diagrams), API reference, 3 worked examples, STATE.md.
  Prereq: Phase 0. Stop: onboarding questions answerable (§12
  re-tested by a fresh reader). No gate (docs-only).
- Phase 2 — API contract/stability (3 days): record stability
  convention; underscore accidental publics; pin
  IntentApplied-on-duplicate + notes-bound contract tests. Prereq:
  Phase 1. Certification: full suite + gates touching changed
  surfaces. Stop: public/internal/test split documented.
- Phase 3 — Backlog (2 days): create the EPIC/story backlog (§Issues);
  record STALE/ancestor questions as issues. Prereq: none.
- Phase 4 — Code quality (1–2 weeks): `tests/support.py`
  deduplication; validator/repository/Controller-read splits, one
  per commit. Prereq: Phase 2. Each commit: full suite + ruff +
  pyright + affected gate re-run (contradiction/governance slices
  for gateway/controller/persistence changes). Stop conditions: any
  red gate; behavior diff beyond moves (verify by test-only runs).
- Phase 5 — Structural (only if Phase 4 proves insufficient):
  pure-helper descent for the persistence→research inversion.
  Requires a design gate (authority-adjacent helpers). Stop: any
  invariant question.
- Phase 6 — DX (ongoing): examples per new seam; STATE.md per
  milestone.

## Certification Strategy

Docs-only phases: full suite green (prove no behavior change) + fresh-
reader onboarding retest. Code phases: full suite + ruff + pyright
(src strict + tests profile) + the gate owning each touched surface
(P6/N9/P7/tick-loop slices as applicable); any new behavior needs its
own gate; no phase may weaken an existing gate's assertions.

## Final Recommendations

Immediate (this week, docs-only, zero risk): gitignore 2 lines +
archive move + README refresh + stub pointers + file the backlog
(incl. STALE/ancestor issues). Next: AGENTS.md + ARCHITECTURE.md +
API reference + examples (the onboarding unlock). Then: stability
convention + `tests/support.py`. Design gates required for: any
persistence→research inversion work; any validator/repository split
that moves transaction boundaries; anything touching certified
invariants. Safely incremental without gates: everything docs-only;
underscore-renames of accidental publics (with suite); test-helper
dedup. Never without a gate: intent/event/identity vocabularies,
journal/lease/authority semantics, N1/N9/detector paths.
