# ResearchSourceProvider — Step 6 Remediation 2 (P1 + C1)

**Date:** 2026-08-14 · **HEAD at start:** `c45c0eb` · **Gate:** pre-step-7
closure — the second independent adversarial review of the shipped step-6
path. **Scope:** the SOURCE_FETCH lineage and provider contracts only — no
redesign, no step-7 work, no new components.

## Verdict

**REMEDIATED.** The P1 finding (cross-project search lineage) was **VERIFIED
against the shipped code** — the gateway resolved the cited search task and
verified existence / SOURCE_SEARCH marker / declared dependency, but never
checked `search_row.project_id == intent.project_id`. Under the global-content
sharing model (migration 1: `content_hash` UNIQUE + edge-carried project
ownership) a Project-B fetch can legitimately resolve Project-A-produced
content, so the refs check alone could not pin the lineage — the cited
PRODUCING task is the missing link. Both enforcement points now close it.

## Remediation 1 (P1) — SOURCE_FETCH must not cross project search lineage

Invariant: **a SOURCE_FETCH task may only cite a SOURCE_SEARCH task of the
same project.** Enforced at both authoritative binding surfaces:

- **A. Gateway admission** (`src/hermes/research/gateway.py`,
  `_validate_source_spec`): after the existence + SOURCE_SEARCH-marker
  checks, a fourth check requires
  `search_row["project_id"] == intent.project_id` — rejected with the
  PROVENANCE code and a `P1 lineage` reason. Reached even when every ref
  dereferences (the probe ran the same search content in p1 and p2, so the
  p2 refs resolved — the citation of p1's search task was still refused).
- **B. Write path** (`src/hermes/persistence/source_outcomes.py`,
  `_validate_task_binding` fetch branch): inside the write transaction (the
  V6-P7-A2 discipline — the status reads are atomic with the write), the
  producing fetch task's `spec.search_task_id` must resolve to an EXISTING
  SOURCE_SEARCH task of the SAME project. A forged/stale row (simulated by
  rewriting a RUNNING fetch task's spec to cite the foreign search task) is
  refused at record time, never recorded against an ambiguous lineage; the
  honest lineage then records normally.

## Remediation 2 (C1) — provider contract alignment

The gateway's SOURCE_FETCH branch allowed `provider=None` while the fetch
handler (`_run_fetch`) requires a provider for adapter routing — a
provider-less fetch passed admission and then FAILED at execution, violating
the architecture's admission-time doctrine ("rejected at admission, never at
execution"). **Closed from both ends:** the gateway now requires a non-empty
allowlisted provider (IDR-030), and `build_source_fetch_task_payload` makes
`provider` a required parameter (all existing callers already passed it).

## Reviewed and accepted (no change) — documented for the record

- **Fetch refs from a NON-cited same-project search:** the gateway scopes ref
  resolution by project (correct under the global-content model — identical
  content legitimately recurs across searches), and the write path's A2-01
  check requires the outcome refs to equal the producing task's spec refs, so
  an input/refs mismatch fails closed at record time. A further
  "refs must come from the cited search" admission rule would be WRONG for
  the legitimate shared-content case; the two-layer enforcement stands.
- **`load_search_results` read surface is task-keyed, not project-keyed:** it
  is reachable only from an admitted fetch task, whose lineage is now pinned
  same-project at admission AND re-pinned at the write path; a foreign task
  id would require a direct DB forgery, outside the deterministic trust
  boundary.

## Verification

- Hostile probes (`_probe_p1.py`, run then removed): P1-A cross-project
  admission → rejected `(P1 lineage)`; P1-A same-project → admits; P1-B
  forged foreign lineage at the write → refused `(same-project (P1))`;
  P1-B honest lineage → records; C1 provider-less → rejected
  (IDR-030 allowlist). All PASS.
- Regression fixtures (`tests/test_provider_orchestration.py`):
  `test_fetch_cannot_cite_foreign_project_search_at_admission`,
  `test_fetch_write_path_rechecks_search_lineage`,
  `test_fetch_requires_provider_at_admission`.
- Orchestration suite: **36 passed** (33 + 3).
- Full suite: **884 passed** (881 + 3), 0 failed, 0 errors.
- Pyright (`npx pyright src`): **0 errors, 0 warnings**.

## Status

Step 6 remains **IMPLEMENTED — TESTED**, **NOT RATIFIED-AS-IMPLEMENTED**.
The P1/C1 remediation is a pre-step-7 closure item; step 7 and the external
closure gate remain standing. Recorded in `docs/idr/IDR-033.md`.
