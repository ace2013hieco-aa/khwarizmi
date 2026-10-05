# ResearchSourceProvider — Step 6 Closure-Candidate Evidence Map

**Date:** 2026-08-14 · **HEAD:** `55c35c2` (final review fold-in) ·
**Purpose:** the evidence bundle the external closure gate reviews before
any step-6 status beyond IMPLEMENTED — TESTED is claimed. The gate's single
entry point is `hermes_researchsourceprovider_closure_gate_package.md`
(evidence index, status matrix, verification commands, and the verbatim
gate-reviewer prompt).

## Status-term legend

Every claim below uses exactly one of: **IMPLEMENTED**, **TESTED**,
**DEFERRED**. **RATIFIED** and **EXTERNALLY VERIFIED** are **UNCLAIMED** —
nothing in this document or the step-6 work substitutes for the external
independent closure gate.

## Capability → evidence map

| Capability | Status | Implementation | Evidence |
|---|---|---|---|
| SOURCE_SEARCH task handler | IMPLEMENTED + TESTED | `src/hermes/research/source_handlers.py` (`_run_search`), `src/hermes/research/source_templates.py` | `tests/test_provider_orchestration.py` (search e2e, EMPTY/UNAVAILABLE, provider-agreement) |
| SOURCE_FETCH task handler | IMPLEMENTED + TESTED | `_run_fetch` (fetch_batch → record, A2-02 task binding) | fetch retry idempotency, divergent-retry rejection fixtures |
| SourceTaskExecutionContext | IMPLEMENTED + TESTED | `SourceHandler`/`SourceTaskExecutionContext` (HD-02 — the ONLY normative handler contract) | dispatch-threaded handler fixtures; non-`HandlerResult` return → FAILED |
| Per-tick fenced repository wiring | IMPLEMENTED + TESTED | `Controller._refresh_fence` → `SourceRepos` over the CURRENT fenced connection (SD2-03/HD-03) | `test_source_repos_built_over_current_fence` |
| record_source_outcome() | IMPLEMENTED + TESTED | `src/hermes/persistence/source_outcomes.py` (one transactional commit; pure `_validate_identities`/`_proposed_set`/`_resolve_idempotency`) | OB hash-SET one-shot, A2-01/02 binding re-check, crash-after-commit recovery fixtures |
| Lossless SearchResult persistence/resolution | IMPLEMENTED + TESTED | round-trip helpers in `src/hermes/tools/research_sources.py`; edge-based `load_search_results` (S6-A4) | round-trip equality fixture; resolver type filter (S6-A1) |
| Artifact + provenance persistence | IMPLEMENTED + TESTED | artifacts rows + two-hop `derived_from` edges, global-content/project-provenance model | cross-project sharing, forged-ref rejection fixtures |
| Idempotent crash-recovery | IMPLEMENTED + TESTED | one-shot hash-SET, identical-reuse / divergent-refusal, recovery ladder re-execution | crash-after-outcome-commit / before-SUCCEEDED, duplicate-recovery fixtures |
| Template-generic recovery | IMPLEMENTED + TESTED | `_re_execute_requeued` re-runs each task's OWN handler | unknown-template fail-closed, template-generic recovery fixtures |
| Controller-owned terminal transitions | IMPLEMENTED + TESTED | controller owns RUNNING → SUCCEEDED/FAILED; record_source_outcome never touches task status | no-task-mutation fixture |
| Task-scoped write view (S6-C2) | IMPLEMENTED + TESTED | `TaskScopedSourceRepos` at the dispatch seam | foreign-citation refusal, cross-task handler fixtures |
| No-escape reach-in (S6-D4) | IMPLEMENTED + TESTED | scoped view retains NO raw bundle | `test_ctx_repos_no_raw_bundle_reach_in` (AttributeError) |
| Semantic content_hash / observation_hash | IMPLEMENTED + TESTED | semantic preimage excludes observation metadata; `observation_hash_of_search_result` | semantic-identity-stability, observation-tamper fixtures |
| Gateway admission (SOURCE_SEARCH/SOURCE_FETCH) | IMPLEMENTED + TESTED | OQ-5: marker/profile/cost_class, provider allowlist, bounds, dereference, declared dependency, full-hash source_refs; **P1 (pre-step-7): same-project search lineage required** | gateway admission fixtures + lineage fixtures |
| Fetch search-lineage invariant (P1 + R01) | IMPLEMENTED + TESTED | same-project `search_task_id` at gateway admission AND re-checked inside the write transaction; **R01:** refs must resolve FROM the cited search (two-hop), the cited search must be a declared dependency edge, outcome ⊆ spec ⊆ search-output | `test_fetch_cannot_cite_foreign_project_search_at_admission`, `test_fetch_write_path_rechecks_search_lineage`, `test_fetch_cited_search_must_be_declared_dependency` |
| Fetch provider contract (C1 + R04) | IMPLEMENTED + TESTED | provider required at admission and in the builder (IDR-030 allowlist); **R04:** fetch provider must agree with the cited search's provider at the write path | `test_fetch_requires_provider_at_admission`, `test_fetch_provider_must_agree_with_search` |
| Artifact-type reuse guard (R02) | IMPLEMENTED + TESTED | `_verify_reused_row` rejects same-hash/different-type reuse (SourceOutcomeIntegrityError); same-type stays REUSE | `test_reuse_requires_same_artifact_type`, `test_reuse_same_type_is_idempotent_reuse` |
| Fetch bounds contract (R03) | IMPLEMENTED + TESTED | builder carries `max_sources`/`size_cap_bytes`/`retry_policy` (S11 caps); gateway validates at admission; handler builds FetchRequest from the persisted spec, fails loud on missing bounds | `test_fetch_bounds_carried_validated_persisted`, `test_fetch_execution_never_substitutes_defaults` |
| Execution scope = spec refs (B3) | IMPLEMENTED + TESTED | `_run_fetch` filters the persisted stream to the cited refs — partial fetches fetch exactly the subset, never a silent over-fetch | `test_partial_refs_fetch_scopes_execution_to_cited_subset` (transport.calls == 1) |
| Payload-write type guard (final review) | IMPLEMENTED + TESTED | `_prepare_fetch` refuses an existing row of a different type standing in for a `source_payload` through the type-blind store dedup | `test_payload_reuse_requires_payload_type` |

## Audit trail (all records in-repo)

| Audit | Verdict | Result |
|---|---|---|
| Step-6 design audits (SD-01…05 + OB/HD third gate) | MERGE WITH REMEDIATION → folded | design records + `_FencedConnection` hardening |
| Code audit 1 (S6-A1…A5) | 3 P1 / 1 P2 / 1 P3 — all folded | `hermes_researchsourceprovider_step6_code_audit.md` |
| Code audit 2 (S6-B1…B3) | 2 P2 / 1 P3 — all folded | `hermes_researchsourceprovider_step6_code_audit2.md` |
| Code audit 3 (S6-C2 + passes) | 1 P2 — folded at the dispatch seam | `hermes_researchsourceprovider_step6_code_audit3.md` |
| Code audit 4 (S6-D1…D4) | CLEAN — 1 P3 hardened | `hermes_researchsourceprovider_step6_code_audit4.md` |
| Ix structural comparison | CLEAN (re-verified at `06dc7b6`) | `docs/ix/step6_structural_comparison_20260814.md`, `docs/ix/map_20260814_step6.txt`, `docs/ix/smells_20260814_step6.txt`, `docs/ix/doctor_20260814_step6.txt` |
| IDR record | IMPLEMENTED — TESTED, NOT RATIFIED | `docs/idr/IDR-032.md` |

## Test evidence

- Provider orchestration suite: **33 passed** (21 step-6 + 11 regression
  fixtures from S6-A/B/C + 1 from S6-D).
- Full suite: **881 passed**, 0 failed, 0 errors.
- Pyright (`npx pyright src`): **0 errors, 0 warnings**.
- CI (GitHub Actions, push to main): green on both jobs through the
  pre-fourth-gate commits; this package re-verified locally.

## Explicitly DEFERRED (not claimed here)

- Step 7 of 7 (the remaining ResearchSourceProvider slice) — **DEFERRED**.
- RATIFIED / EXTERNALLY VERIFIED status for the provider slice — **DEFERRED
  to the external independent closure gate** (§27 item 43 standing).
- Post-closure items the gate may raise — **DEFERRED** pending its verdict.
