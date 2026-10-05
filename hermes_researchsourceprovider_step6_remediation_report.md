# ResearchSourceProvider — Step 6 Remediation Report (S6-R01…R04)

**Date:** 2026-08-14 · **Gate:** second-round pre-step-7 closure remediation.

## A. Baseline

- **HEAD at start:** `1e2450c` (the P1/C1 remediation commit from the first
  part of this round).
- **Suite:** 884 passed / 0 failed / pyright 0 errors.
- **Slice status:** steps 1–6 IMPLEMENTED + TESTED; NOT RATIFIED.

## B. Findings (exactly the four from the review)

| ID | Severity | Finding |
|---|---|---|
| **S6-R01** | P1 | SOURCE_FETCH cross-project search lineage: the cited search task's project was never pinned (remediation-1 closed admission + write-path project; this round closes the remaining binding checks) |
| **S6-R02** | P1 | Artifact TYPE does not participate in content-hash reuse validation: `_verify_reused_row` checked content_hash and re-verified `source_result` rows, but a same-hash/different-type existing row was reused — semantic type-confusion |
| **S6-R03** | P2 | SOURCE_FETCH bounds contract mismatch: the builder carried no bounds, the gateway validated none, and the handler built `FetchRequest` from global policy defaults — admission semantics ≠ execution semantics |
| **S6-R04** | P2 | SOURCE_FETCH provider contract mismatch: admission allowed `provider=None` while the handler required it (closed in remediation-1); this round adds the write-path provider agreement between the fetch task and its cited search |

## C. Root cause

- **R01:** the refs check is project-edge-scoped by design (global-content
  sharing), so the cited *producing task* was the only lineage pin — and it
  was not re-verified inside the write transaction (dependency edge,
  refs-ownership).
- **R02:** `content_hash` is globally unique but type-blind; the reuse path
  keyed on the hash alone.
- **R03:** the task template architecture promised builder-carried bounds but
  the SOURCE_FETCH builder/handler never carried them.
- **R04:** the provider contract lived in two layers that disagreed, and no
  layer checked fetch-provider vs search-provider agreement.

## D. Fix

**R01 (completion of the lineage closure):**
- Gateway admission: refs must now resolve **from the cited search task**
  (`upstream_task_id` two-hop `derived_from` reachability), not merely in the
  project — a fetch's `source_result:` refs must BELONG to its search.
- Write path (`_validate_task_binding`, fetch branch, inside the write
  transaction): the cited search task must be a **declared task-graph
  dependency** (`task_dependencies` edge), and every spec ref must resolve
  **from the cited search task**. Combined with the existing A2-01
  outcome-⊆-spec-refs check, the fetch outcome can never introduce results
  outside the cited search's result set.
- The earlier round's same-project checks (admission PROVENANCE + write-path
  re-check) remain.

**R02:** `_verify_reused_row` now rejects
`existing.artifact_type != proposed.artifact_type` with
`SourceOutcomeIntegrityError` **before** the reuse is reported — never a
silent coercion, never a duplicate row, never left for the resolver to
discover later. Same hash + same type remains REUSE (idempotency intact).

**R03:** `build_source_fetch_task_payload` now carries
`max_sources` / `size_cap_bytes` / `retry_policy` (S11-cap validated,
defaults persisted in the spec); the gateway validates all three at
admission (int-in-range, no bool/0/negative, canonical retry-policy shape);
`_run_fetch` builds the runtime `FetchRequest` **from the persisted spec**
and FAILS LOUDLY (`ProviderValidationError`) if a bound is missing on a
forged row — the execution never silently substitutes the global defaults.

**R04:** the write path requires the fetch task's `provider` to equal its
cited search task's `provider` (the fetched sources ARE the search's
results), plus the defense-in-depth per-source provider agreement; the
builder and gateway already require the allowlisted provider (remediation-1).

## E. Tests added

Six regression fixtures in `tests/test_provider_orchestration.py`:

1. `test_fetch_cited_search_must_be_declared_dependency` (R01 attack 6 —
   admission DEPENDENCY rejection + write-path dependency-edge re-check).
2. `test_reuse_requires_same_artifact_type` (R02 — existing
   source_payload/source_fetch_outcome/unrelated type vs proposed
   source_result → IntegrityError, nothing persisted).
3. `test_reuse_same_type_is_idempotent_reuse` (R02 positive — NEW then
   IDENTICAL).
4. `test_fetch_bounds_carried_validated_persisted` (R03 — builder defaults,
   custom 30/12345/retry survives builder→gateway→persisted task, over-bound
   max_sources/size_cap_bytes and malformed retry_policy rejected at
   admission).
5. `test_fetch_execution_never_substitutes_defaults` (R03 — forged row with a
   missing bound → ProviderValidationError through the real handler).
6. `test_fetch_provider_must_agree_with_search` (R04 — pmc fetch over arxiv
   search refused at the write path).

## F. Full suite result

**890 passed** (884 + 6), 0 failed, 0 errors, ~10s, exit 0.

## G. Pyright result

`npx pyright src` — **0 errors, 0 warnings, 0 informations**.

## H. Ix result

`ix map` + `ix smells` on the remediated tree vs the archived step-6
baseline (`docs/ix/*_step6.txt`): **153 → 161 candidates**, every delta the
documented non-code orphan/connection-graph artifact class (+8 orphan files =
the new doc records; no new God Module, no new Weak Component; the changed
code files retain real fan_in/fan_out — `source_outcomes.py` 5/25,
`source_handlers.py` 2/48, `gateway.py` 6/49). Structural watch-items:
**zero new write paths** (the only added SQL is SELECT; no INSERT/UPDATE/
DELETE beyond the existing edge idempotency), **zero cycles** (suite
import-proof), **single handler→repository boundary** (`SourceRepos.record`),
**no authority drift** (no new scheduler/gateway/event/schema).
Reports archived at `docs/ix/map_20260814_r01remediation.txt` +
`smells_20260814_r01remediation.txt`.

## I. Adversarial reproduction

| Attack | Previous behavior | Fix | Current behavior |
|---|---|---|---|
| A-search → A-fetch | works | — | works (PASS) |
| A-search → B-fetch | ADMITTED (lineage ambiguous) | R01 | REJECTED at admission (PROVENANCE, P1 lineage) |
| A-search → B-fetch, shared artifact | ADMITTED (refs resolved) | R01 | REJECTED at admission even with resolving refs |
| Direct repository call (bypass Gateway) | recorded | R01 | REJECTED at the write path (same-project + dependency + refs-ownership re-checked in-transaction) |
| Forged search_task_id | recorded | R01 | REJECTED (missing/foreign search task) |
| Correct project, non-dependency search | ADMITTED | R01 | REJECTED at admission (DEPENDENCY) and at the write path (dependency edge) |
| same hash + same type reuse | reused | R02 | REUSE (idempotent) |
| same hash + different type | REUSED (type-confused) | R02 | SourceOutcomeIntegrityError, nothing persisted |
| over-bound max_sources / size_cap_bytes | (no bounds existed) | R03 | REJECTED at admission |
| malformed retry_policy | (no policy existed) | R03 | REJECTED at admission |
| forged row, missing bound | silently used defaults | R03 | ProviderValidationError (fail loud) |
| task max_sources=5 vs default 20 | default won | R03 | persisted spec wins (5) |
| fetch provider ≠ search provider | recorded | R04 | REJECTED at the write path |
| provider omitted / unknown / non-string | ADMITTED | R04/remediation-1 | REJECTED at admission |

## J. Architecture impact

**NO architectural redesign.** Local contract hardening only: three
SELECT-only validations + one reuse-path guard inside existing functions;
the builder carries existing S11-cap bounds; no new authority, no new event,
no new schema, no new table, no scheduler/gateway/provenance-model change.
Global content-addressed artifacts + project/task-scoped provenance edges
unchanged.

## K. Final status

**REMEDIATION COMPLETE — READY FOR FINAL STEP-6 REVIEW.**

Step 6 is NOT marked RATIFIED. Next actions per the review: the final
independent step-6 review, then the step-7 record/replay acceptance gate.
