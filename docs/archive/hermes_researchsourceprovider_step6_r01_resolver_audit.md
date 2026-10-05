# ResearchSourceProvider — Step 6 R01 Resolver + Dependency Re-Check Audit

**Date:** 2026-08-14 · **Auditor:** independent hostile pass (no role in the
R01–R04 remediation) · **Scope:** the extended resolver's `upstream_task_id`
two-hop path and the in-transaction dependency-edge re-check, for the same
bypass classes (foreign-task refs, hop-direction/type confusion,
project-column-only ownership, partial-refs over-fetch, wrong-target
dependency edges).

## Verdict

**MERGE WITH REMEDIATION — one confirmed finding (B3), folded in.** The
two-hop ownership path and the dependency-edge re-check hold under hostile
probing; the partial-refs execution contract was the single crack, and it is
closed.

## Findings

| ID | Sev | Finding | Probe | Disposition |
|---|---|---|---|---|
| B1 | — | A same-project fetch citing search X with refs produced by search Y is rejected at admission (`SD-05/R01`) — the `upstream_task_id` two-hop constrains to X's own edges | live | **PASS** — no change |
| B2 | — | An artifact owned only by its `project_id` column (no two-hop path from X) does NOT satisfy refs-ownership — the `AND EXISTS` two-hop conjunct is enforced even when the project OR-branch holds | live (forged row) | **PASS** — no change |
| **B3** | **P2** | A planner-tightened (partial-refs) fetch ADMITS but the handler fed the WHOLE persisted search stream to `fetch_batch` — the outcome over-fetched the uncited results and FAILED the A2-01 write check late, after wasted execution | live end-to-end | **FOLDED IN** — `_run_fetch` now filters the persisted stream to exactly the spec refs (the refs ARE the fetch scope); a partial fetch fetches only its cited subset and records cleanly (`transport.calls == 1` in the fixture) |
| D2 | — | A forged `task_dependencies` edge pointing at a DIFFERENT task (not the cited search) is refused at the write path (`task-graph dependency (R01)`) — the re-check is exact-edge, inside `BEGIN IMMEDIATE` | live | **PASS** — no change |
| D3 | — | Extra legitimate declared dependencies do not block admission (positive control) | live | **PASS** — no change |

Also verified: the "in-transaction" claim — `record()` wraps the binding
re-checks in `BEGIN IMMEDIATE` (with ROLLBACK on any error), so the
dependency-edge SELECT and the refs-ownership SELECTs are atomic with the
write (TOCTOU closed).

## Fold-in (B3)

`_run_fetch` (in `src/hermes/research/source_handlers.py`) now filters
`load_search_results(search_task_id)` to the spec refs' hashes before calling
`fetch_batch`. Honest full-refs payloads are unchanged (the filter is
lossless); partial-refs payloads (the R03 "planner may tighten" case) fetch
exactly the cited subset and record cleanly. Ref hashes not present in the
stream are impossible (admission requires refs-ownership), and the empty
post-filter case fails loudly.

## Verification

- Probe suite: **5/5 PASS** (B1/B2/D2/D3 hold; B3 FAIL → FOLDED → PASS).
- Regression fixture: `test_partial_refs_fetch_scopes_execution_to_cited_subset`
  (asserts `transport.calls == 1` — the uncited result is never fetched).
- Orchestration suite: **44 passed**; full suite: **892 passed**;
  pyright: **0 errors, 0 warnings**.

## Status

The R01 surface is now closed end-to-end: admission refs-ownership, the
in-transaction dependency-edge + refs-ownership re-checks, and the
execution-scope filter. Step 6 remains **IMPLEMENTED — TESTED**, NOT
RATIFIED; the final step-6 review verdict is recorded separately.
