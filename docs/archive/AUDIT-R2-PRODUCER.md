# AUDIT-R2 — producer-ref redteam adjudication

- **Task:** AUDIT-R2 producer-ref (additive-only claim under test)
- **Repo:** D:\New folder\research-agent (GitHub ace2013hieco-aa/khwarizmi-research)
- **Base (main tip, verified):** `a8f018068e3c04b3160891ebd56cfd95d3590c95`
- **Diff under test:** `a8f0180...dbdca78` — `src/hermes/research/gateway.py` +9 (one
  behavioral line: `artifact_ids=basis_sorted`, gateway.py:2636) + `tests/test_b3_producer_ref.py`
  (new, 303 lines, 10 tests)
- **NOT-topics:** backtest_audit / SDA / TSE / Optimize-my-strategy — absent from the
  diff and its touched surfaces; no STOP triggered.
- **Method:** isolated worktree (`audit-r2-producer`), branch `audit/r2-producer` from
  main tip, diff applied uncommitted via `git cherry-pick --no-commit dbdca78`; venv
  resolves `hermes` from the worktree `src/`. Offline. Findings only — no code changed.

## VERDICT: PASS

MUST-FIX: **none.** SHOULD-FIX: 1 (non-blocking). NOTE: 4.

---

## (A) Additivity proof — PASS

**Payload key-set pin re-derived independently** (not from the test): regex extraction
of `admission_payload` from `gateway.py:2445-2458` at both endpoints of the diff, compared
against the test pin `ADMISSION_PAYLOAD_KEYS` (tests/test_b3_producer_ref.py:52-57):

```
code keys : ['admission_decision_ref', 'curated_id', 'evidence_basis', 'hypothesis_ref',
             'kind', 'operation', 'operator_id', 'program_ref', 'signature_json',
             'source_binding_ref', 'source_decision_event_ref', 'supersedes_ref']
pin==code : True
pre-fix payload keys == post-fix: True
artifact_ids in payload pre-fix: False | post-fix: False
basis write loop var: ['evidence_artifact_id']   (iterates basis_sorted)
event kwarg: ['basis_sorted']
```

The new refs ride the **separate `artifact_ids_json` column** via
`_append_event_to_db(..., artifact_ids=basis_sorted)` → `_json_dumps(artifact_ids or [])`
(repositories.py:129); `payload_json` serialization is untouched. 4 KiB discipline holds
transitively: `evidence_basis` ⊂ `admission_payload`, which is size-checked at
gateway.py:2472 (`validate_payload_size`, ≤4096 B), so the same list serialized as
`artifact_ids_json` is strictly < 4096 B. The 32-member bound (MAX_EVIDENCE_BASIS_MEMBERS,
gateway.py:2413) is unchanged.

**Consumers of `artifact_ids_json` — none broken:**
- `vault/projection.py:314-322` (`_row_subject_keys`) — the intended new consumer
  (`artifact:` namespace keys for the admission).
- `controller.py:1385-1388` (`retracted_source_review_candidates`) — SQL-filtered to
  `event_type='SourceRetracted'`; admission rows never enter.
- `cli.py:269-270` — display-only JSON parse.
- Gateway S5 predicate (gateway.py:1765-1774) consumes the **registry table**
  `curated_knowledge_retraction_basis`, not the journal column — untouched by construction.

**Downstream suites (raw):**

```
tests/test_b3_producer_ref.py ..........            10 passed in 1.05s
tests/test_s6_event_capacity.py
tests/test_step7_curated_registry.py
tests/test_q04_review_candidates.py                 138 passed in 13.60s
tests/test_p_auto_5_vault.py test_p_auto_5_fix.py
test_p_auto_5_vault_production_shapes.py
test_notes_dedup.py test_controller.py test_cli.py
test_database.py test_controller_c4.py
test_provider_orchestration.py                      295 passed in 329.04s
```

## (B) Fabrication hunt — PASS (no path)

`artifact_ids=basis_sorted`; `basis_sorted = sorted(evidence_basis)` (gateway.py:2418);
`evidence_basis` is populated **solely** at gateway.py:2401 (`evidence_basis.add(
arow["artifact_id"])`) — verified by grep (`evidence_basis.add` has exactly one hit).
Every member is an artifact resolved **in-project, fail-closed** by
`_source_artifact_resolves` (source_outcomes.py:96-156: full content hash, type-prefixed,
project edge-carried; cross-project refused at gateway.py:2385-2391). The **same variable**
feeds (i) the basis-table INSERT loop (gateway.py:2594-2598), (ii) `payload["evidence_basis"]`
(gateway.py:2455), and (iii) the new `artifact_ids` kwarg — inside one `BEGIN IMMEDIATE`
transaction with rollback-on-exception (gateway.py:2494, 2640-2647), so journal ≡ registry ≡
payload by construction; no partial/divergent write path exists. Duplicate-replay early
return (gateway.py:2502-2517) writes nothing. **A non-basis id cannot enter
`artifact_ids_json` through this hunk.** No fabrication path found.

## (C) Legacy-row semantics — PASS (documented, not denied)

Pre-fix `CuratedKnowledgeAdmitted` rows carry `artifact_ids_json=[]`, so a **bare**
`Controller.record_source_retraction` (audit-only event, controller.py:1344-1376) cannot
match them journal-only — they stay `authoritative: true` (silent-stale). This is
**documented as a contract**, not denied:
- Module docstring (tests/test_b3_producer_ref.py:1-20) and
  `test_legacy_admission_without_refs_still_projects` docstring (:277-282): "no historical
  backfill — the derived view never invents a match, so the legacy row's validity is
  unchanged"; the test asserts `authoritative: true` + no "superseded by" for a legacy row.
- Commit message: "are **now** emitted additively" — no backfill claim.
- Under the **S5 cascade** legacy rows still retire via the pre-existing `curated:` key
  (payload `curated_id`, projection.py:342-345) — only the bare-retraction path is stale.

## (D) Double-retire — PASS (no duplicate retirement actions)

The projector's retirement pass keeps `invalidated_by: dict[victim → ONE invalidator]`
(projection.py:623-636) and `_see_links` emits exactly **one** "superseded by" link
(projection.py:538); note writes are byte-deterministic and idempotent (`open(..., "w")`
over a planned, refusal-atomic write set, projection.py:638-721). Traced both producers:
- **S5 cascade:** emits `CuratedKnowledgeInvalidated` **before** `SourceRetracted`
  (gateway.py:1753-1758 comment, 1792-1804, 1867-1884). The CKI row consumes both the
  victim's `curated:` and `artifact:` keys (deletes them from `live_subjects`), so the
  later `SourceRetracted` finds no live key — the CKI deterministically remains the named
  invalidator. One link, one rewrite.
- **Bare Controller retraction:** only `SourceRetracted` exists; it retires the admission
  via the new shared `artifact:` key. One link, one rewrite.
- **Multi-member basis, sequential bare retractions:** the second retractor **overwrites**
  `invalidated_by[victim]` (projection.py:632) — the single link re-points to the latest
  invalidator. Still one link, one rewrite, deterministic (event_id ASC order).

No duplicate retirement actions under any traced shape.

---

## SHOULD-FIX (non-blocking)

1. **Documentation durability (C):** the legacy-row silent-stale semantic and the
   invalidator re-pointing rule (D) are certified only in test docstrings. Record them in
   durable docs (`docs/STATE.md` or the vault projection charter) so the derived-view
   contract survives test-file churn.

## NOTE

1. `artifact_ids_json` has **no independent size check** at the persistence boundary —
   `validate_event(event_type, payload)` (repositories.py:118 → event_validation.py:139-151)
   sees only `payload`. Today the new column is transitively bounded (< the ≤4 KiB admission
   payload that contains the same list); other writers (e.g. SourceRetracted,
   gateway.py:1873) already wrote the column unchecked. Pre-existing boundary gap, not
   introduced here.
2. Basis membership is not restricted to `source_*` artifact types at the admission site
   (gateway.py:2377-2401 accepts any typed `<type>:<hash>` that resolves in-project);
   a non-source basis member would ride `artifact_ids_json` but stay inert (both retraction
   producers name only source artifacts). Pre-existing upstream surface; the commit's
   "shared source-artifact refs" phrasing is the common case, not a type guarantee.
3. Invalidator re-pointing: when several invalidators match one victim, the note names the
   **latest** (by event_id), never the first cause; single deterministic link (see D).
4. Bare Controller retraction retires the vault note while the registry row stays
   `ADMITTED` (registry invalidation authority remains with the S5 gateway path,
   controller.py:1344-1346 "audit event ONLY") — derived view vs. authority divergence is
   the chartered B3 behavior; the vault is never authority.

## Raw gates

```
$ pytest tests/test_b3_producer_ref.py -v
collected 10 items
tests\test_b3_producer_ref.py ..........                                 [100%]
============================= 10 passed in 1.05s ==============================

$ pytest tests/test_s6_event_capacity.py tests/test_step7_curated_registry.py \
         tests/test_q04_review_candidates.py
........................................................................ [ 52%]
..................................................................       [100%]
138 passed in 13.60s

$ pytest tests/test_p_auto_5_vault.py tests/test_p_auto_5_fix.py \
         tests/test_p_auto_5_vault_production_shapes.py tests/test_notes_dedup.py \
         tests/test_controller.py tests/test_cli.py tests/test_database.py \
         tests/test_controller_c4.py tests/test_provider_orchestration.py
295 passed in 329.04s (0:05:29)

$ uvx ruff check src tests
All checks passed!

$ python scripts/run_tests.py        # full suite
3680 passed, 16 skipped in 667.61s (0:11:07)
```

Environment: Python 3.14.1, pytest 9.1.1, win32; worktree
`C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\audit-r2-producer`;
branch `audit/r2-producer` (local-only, never pushed).
