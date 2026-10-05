# ResearchSourceProvider — Step 6 Post-Implementation Hostile Code Audit

**Scope:** the SHIPPED step-6 orchestration path (SOURCE_SEARCH/SOURCE_FETCH handlers, `SourceOutcomeRepository.record`, the typed dispatch surface, the recovery ladder) — attack binding/idempotency, the handler surface, and recovery for the same bypass classes the design gates used.
**HEAD at audit:** `d82228a` + the uncommitted step-6 implementation (869-passing suite).
**Method:** source inspection + four live probes against real SQLite through the shipped drivers (`tests/test_provider_orchestration.py` fakes).
**Verdict:** **MERGE WITH REMEDIATION** — 3 P1s, 1 P2, 1 P3 pin, all confirmed by reproduction, all folded in. No architecture violations (single write path, one authority, edge-carried ownership preserved).

## Findings

| ID | Sev | Surface | Finding | Probe result |
|---|---|---|---|---|
| S6-A1 | **P1** | resolver / admission | `_source_artifact_resolves` matched content-hash + project edges only — the `source_result:` / `source_payload:` prefix was validated then DISCARDED. `source_result:<payload-hash>` resolved True; SOURCE_FETCH admission (SD-05) accepted a payload hash cited as a `source_result` ref. | `resolves: True` → now `False` |
| S6-A2 | **P1** | A2-01 binding | The provider mix check fired only for >1 result providers — a forged outcome with `log.provider="arxiv"` and a SINGLE `pubmed` result passed the binding and RECORDED under an arxiv spec. | `RECORDED: NEW` → refused (`contradicts`) |
| S6-A3 | **P1** | handler contract | `_run_handler` treated any non-None return as completed — a handler returning a dict/str/None silently SUCCEEDED the task (design: wrong result type → fail closed). | `status: SUCCEEDED` → `FAILED` |
| S6-A4 | **P2** | fetch input | `load_search_results` selected by `task_id` (stamped only at write); reused rows keep the ORIGINAL task's id, so a project that legitimately reused another project's content found an EMPTY fetch input while `dereference_ref` resolved the same refs — the two read surfaces disagreed. | `load=0 / resolve=True` → both agree |
| S6-A5 | **P3** | reuse path | `_verify_reused_row` re-verifies `source_result` rows in full (both hashes) but outcome-row metadata is content-hash-only. Outcome metadata is AUDIT-ONLY (no decision reads it); the semantic identity lives in content_hash; observation fields vary by design — pinned as a scope-honesty note, no code change. | code-reading pin |

## Fold-in (all minimal, architecture-preserving)

1. **S6-A1** — `_source_artifact_resolves(conn, project_id, content_hash, artifact_type="")`: the type is part of the resolution; `dereference_ref` and the gateway's SD-05 admission pass it. A `source_result:` ref can no longer dereference a `source_payload` row (or vice versa).
2. **S6-A2** — the binding now requires the log and the delivered results to AGREE when both are present (`result_providers == {log_provider}`); a single contradicting result provider is refused like a mix.
3. **S6-A3** — `_run_handler` requires `isinstance(result, HandlerResult)`; any other return type FAILS the task loudly (`S6-A3` reason) — never a silent SUCCEEDED.
4. **S6-A4** — `load_search_results` is EDGE-based (two-hop `derived_from` reachability — the same model the resolver uses): outcome→task, results→outcome. Original and reusing tasks both find the input.
5. **S6-A5** — docstring scope-honesty note on `_verify_reused_row` (OB-04's inconsistent-forge honesty applied to outcome rows).

## Regression fixtures (5, in `tests/test_provider_orchestration.py`)

- `test_resolver_honors_artifact_type_prefix` — `source_result:<payload-hash>` False, `source_payload:<payload-hash>` True, true-type refs resolve; cross-type refs never.
- `test_admission_rejects_payload_hash_as_source_result` — the gate refuses a payload hash cited as `source_result` (typed SD-05).
- `test_log_result_provider_contradiction_refused` — forged log-arxiv/pubmed-single refused; legit agreement still records.
- `test_handler_wrong_return_type_fails_closed` — None / dict / str returns all FAIL the task.
- `test_load_search_results_edge_based_cross_project` — a reusing project finds the shared input; resolver and loader agree.

## Verification

- Full suite: **874 passed** (869 + 5), 0 failed, 0 errors
- Targeted orchestration suite: 26 passed
- Pyright (`npx pyright src`, the CI command): **0 errors**
- Live probes re-run: all four FAIL → PASS

## Remaining risks (not folded — intentional)

- The post-implementation adversarial code audit requested by §26 has now run and is folded. The remaining standing conditions before RATIFIED-AS-IMPLEMENTED: the §26 Ix structural comparison (pre- vs post-step-6 graph), and the external closure gate. Step 7 remains untouched.
- S6-A5 remains a documented scope limit (audit-log metadata on reused outcome rows), consistent with OB-04.
