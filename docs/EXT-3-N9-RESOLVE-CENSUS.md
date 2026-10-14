# EXT-3 — N9 evidence-resolve path census (triage L3 closure)

- **Slice:** `slice/ext-3-n9pin` (local-only, no push)
- **Base:** `main@6cce97c029dce670be8b57e33f62467131ffc036`
- **Triage input:** `audit/ext-1-triage@bc1a5da`, item **L3 — N9 predicate
  state drift** (verdict PARTIAL)
- **Predicate:** `source_artifact_retracted` —
  `src/hermes/persistence/source_outcomes.py`
- **Resolver under audit:** `_source_artifact_resolves` —
  `src/hermes/persistence/source_outcomes.py`
- **Scope:** no new scope. No production behaviour change lands in this slice
  (see "Wiring" below); the deliverable is a recorded census plus the pin that
  enforces it.

## 1. Method

The census is derived by AST, not by reading: every `ast.Call` in
`src/hermes/**/*.py` whose callee name is `_source_artifact_resolves` or
`source_artifact_retracted` is recorded with its **class-qualified enclosing
function**. `tests/test_n9_resolve_path_pin.py` re-runs the same derivation and
fails if the live tree disagrees with the tables below.

## 2. Census — 8 resolve sites

| # | Resolve site | Enclosing function | Verdict |
| :-- | :--- | :--- | :--- |
| R1 | `persistence/failure_classifications.py:361` | `FailureClassificationRepository._verify_evidence_owned` | **FENCED** (predicate `:378`) |
| R2 | `persistence/failure_classifications.py:401` | `FailureClassificationRepository._evidence_resolver` | **FENCED** (predicate `:411`) |
| R3 | `persistence/graph_edges.py:338` | `GraphEdgeRepository._resolve_endpoint` | non-evidence |
| R4 | `persistence/repositories.py:2002` | `ClaimAssumptionRepository._dereference_artifact_ref` | **frozen gap** |
| R5 | `persistence/source_outcomes.py:474` | `SourceOutcomeRepository.dereference_ref` | non-evidence |
| R6 | `persistence/source_outcomes.py:719` | `SourceOutcomeRepository._validate_task_binding` | non-evidence |
| R7 | `research/gateway.py:2386` | `_validate_curate_knowledge` | **frozen gap** |
| R8 | `research/gateway.py:3953` | `_validate_source_spec` | non-evidence |

## 3. Census — 4 predicate sites (certified, FROZEN)

| # | Predicate site | Enclosing function |
| :-- | :--- | :--- |
| P1 | `persistence/failure_classifications.py:378` | `FailureClassificationRepository._verify_evidence_owned` |
| P2 | `persistence/failure_classifications.py:411` | `FailureClassificationRepository._evidence_resolver` |
| P3 | `research/contradiction_candidates.py:65` | `detector_candidate_rows` |
| P4 | `research/gateway.py:2712` | `_cx_resolve_evidence_ref` |

P1/P2 are the resolve-side fences for R1/R2. P3 and P4 resolve through their own
project-scoped SQL rather than the shared helper, so they are pinned by presence
only. This set matches the N9 certification
(`docs/archive/N9_MAINLINE_MERGE_CERTIFICATION_2026-09-19.md`, commit `02cb976`,
"`source_artifact_retracted` call sites in all 4 src files"), with the controller
site now living in `contradiction_candidates.py` after the S-1 detector-row
extraction.

## 4. Judgement — non-evidence resolve paths (deliberately unfenced)

The invariant being enforced is narrow: *N9 fences admissibility of a retracted
source as evidence for a **new decision***. A resolve path is an evidence
position iff its resolved artifact becomes the basis or the evidence of a
decision. These four are not:

- **R3 `_resolve_endpoint`** — gr3 corpus-edge endpoints. Binds a content hash to
  its admitted artifact id and anti-substitutes against the row's `corpus_ref`
  metadata. This is corpus membership/identity: a retracted payload may remain a
  corpus member, and N9 bars it as evidence for a new decision, not from the
  corpus graph.
- **R5 `dereference_ref`** — the shared typed ref→bool helper (SD-05 / S6-A1). It
  answers a form/resolution question (*does this typed ref point at a real
  carrier of the matching type?*). Admissibility is the caller's question;
  fencing the helper would fence every caller indiscriminately, including pure
  provenance bindings.
- **R6 `_validate_task_binding`** — SOURCE_FETCH R01 binding: the fetch's spec
  refs must be produced by the cited search task (two-hop `derived_from`).
  Provenance binding, not admissibility — a retracted `source_result` may still
  be the fetch's own declared input, and the payload read path is guarded by
  `UntrustedContent` envelopment plus content-hash re-verification (EXT-1 R2),
  not by N9.
- **R8 `_validate_source_spec`** — the same R01/D2 binding at the SOURCE_FETCH
  admission gate.

## 5. Wiring — NOT performed; two sites are gate-blocked (STOP-and-report)

The task asked for the predicate to be wired into paths that resolve evidence for
decisions. **Two sites are genuine evidence positions and lack the fence — and
both sit on certified writers/validators, so the change may not be improvised.**

**R7 `_validate_curate_knowledge` (`research/gateway.py:2386`).** This function
resolves a classification's `falsifying_evidence_refs` into `evidence_basis`,
which becomes the `evidence_basis` of the CURATE_KNOWLEDGE admission payload —
i.e. the basis that justifies a retraction. That is squarely an admissibility
position and the fence *does* belong in this function. It is, however, a
certified gateway validator: one of the 27 acquisition owners, owning its own
`BEGIN IMMEDIATE` boundary, in the P7 governance lifecycle, and adjacent to the
N9-certified gateway site. `AGENTS.md` requires a design gate plus the owning
certification slice re-run for changes near the frozen N9 surface. **Blocked.**

**R4 `_dereference_artifact_ref` (`persistence/repositories.py:2002`).** The
extraction/claim `source_ref` dereference is an evidence position — a claim's
cited source is its evidence. But this helper's contract is *dereference* under a
closed vocabulary (*does a carrier exist?*), not *admissibility*; the N9 fence
belongs at the certified writer call site (`record_extraction`, a persistence
acquisition owner under the ResearchSourceProvider step-6 gate record), not in
the shared helper, which also serves non-evidence supporting refs. **Blocked.**

Neither was changed. Both are recorded in `N9_FROZEN_GAP_REGISTER` in the pin, so
the gap is explicit, exactly bounded, and cannot silently grow. Closing either
requires the owning gate re-run — a Director decision, not a fixer improvisation.

## 6. The pin (how future drift is prevented)

`tests/test_n9_resolve_path_pin.py` scans `src/hermes/**/*.py` and requires every
function that calls `_source_artifact_resolves` to appear in exactly one of three
tables: `N9_FENCED_RESOLVE_SITES` (must carry the predicate, ordered after the
resolve), `N9_NON_EVIDENCE_ALLOWLIST` (documented reason), or
`N9_FROZEN_GAP_REGISTER` (gate-blocked). It also pins the certified predicate set
to exactly four sites.

A new resolve path therefore cannot land silently: it appears in the scan and in
no table, and `test_every_resolve_site_is_classified` fails naming the site. The
only way to add a resolve path is to classify it deliberately in the pin.

## 7. Pin proof (scratch copy, then removed)

Both proofs ran in `…/Temp/opencode/ext-3-pin-scratch` (a copy of `src/` plus the
pin), then the scratch was deleted.

1. **Planted bypass** — a new function calling `_source_artifact_resolves` with
   no predicate appended to `persistence/graph_edges.py`:
   `2 failed, 3 passed (EXIT=1)`; the failure names
   `('persistence/graph_edges.py', '_ext3_planted_bypass')`.
2. **Fence removal** — the predicate deleted from `_evidence_resolver`
   (`failure_classifications.py:411`): `2 failed, 3 passed (EXIT=1)`; the failures
   name `FailureClassificationRepository._evidence_resolver (fence missing)` and
   report `Removed: [('persistence/failure_classifications.py',
   'FailureClassificationRepository._evidence_resolver')]`.

On the real tree the pin is green: `5 passed`.

## 8. Scope discipline

- No production file changed; `git status` in the slice shows the new test file
  only. No new writes, no `apply_intent` change, single-mutation-path discipline
  intact.
- The N9 predicate, its four certified sites, the N1 pair rule, S5, the journal,
  migrations, intents and providers are untouched.
- **Prohibited-claims discipline:** this census records *code structure* — which
  resolve paths carry the retraction predicate and which do not. It claims no
  scientific validity, no reproducibility, and no completeness of N9 fencing
  beyond the 8 resolve sites enumerated here.

License: Apache-2.0 (LICENSE).
