# AUDIT-R1: Manifest Verifier Red-Team Audit

**Branch:** audit/r1-manifest  
**Base commit:** a8f0180 (main)  
**Head commit:** fccfd80 (R-1 derived-view manifest + recomputing verify)  
**Changed files:** src/hermes/vault/manifest.py (new), src/hermes/vault/projection.py (refactor), src/hermes/cli.py (CLI), tests/test_vault_manifest.py (22 tests)

---

## Executive Summary

**VERDICT: FAIL** — Three false-OK conditions found where `verify_manifest` returns `ok=True` despite vault/journal disagreement. One is by architectural design (non-head journal mutations invisible to projection); two are verifier gaps requiring fixes.

---

## (A) False-OK Hunt — Three Conditions Where Verify Returns OK While Wrong

| # | Condition | Result | Root Cause |
|---|-----------|--------|------------|
| A1 | Non-head journal row modified in columns not used by projection (e.g., `correlation_id`) | **FALSE-OK** (by design) | Manifest verifies *projection* (rendered notes), not journal integrity. Columns not in `_render()` are invisible. Head row changes caught via `JOURNAL_HEAD_CHANGED`. |
| A2 | Manifest `gap_event_ids` forged to wrong value; actual journal gaps differ | **FALSE-OK** (verifier gap) | Verifier recomputes gaps via `journal_gap_event_ids()` and reports as `GAP_RANGE` findings, but **never compares** against `manifest["gap_event_ids"]`. The manifest's gap list is stale metadata, not verified. |
| A3 | Note file renamed to non-canonical name; manifest updated to match; digest matches | **FALSE-OK** (verifier gap) | Verifier checks: (1) manifest filename exists on disk, (2) digest matches manifest. Never validates that filename == `note_filename(event_id, event_type)` (canonical naming). Projector invariant "stable file names from content IDs" not enforced at verify time. |

**A1** is architectural intent — the manifest is a *derived view of the projection*, not the journal. Documented in `MANIFEST_VERSION` schema: "authority: derived view — recomputed from the journal; never authority".

**A2** and **A3** are verifier bugs — the manifest claims these fields as part of its certified state, but the verifier does not validate them.

---

## (B) Planner Refactor Regressions — Old vs New Projection Bytes

**Test:** Scratch projection (full range) vs incremental (windowed) across 11 event types including authoritative facts, invalidations, curated knowledge, contradictions, source retractions.

**Result: PASS** — All 12 notes byte-identical between a8f0180 (old monolithic `project()`) and fccfd80 (refactored `_window_plans` + `_stale_plans` + `_plan_range`).

```
evt-000001-research-created.md           MATCH (411 bytes)
evt-000002-task-created.md               MATCH (370 bytes)
evt-000003-task-status-changed.md        MATCH (468 bytes)
evt-000004-task-status-changed.md        MATCH (470 bytes)
evt-000005-human-decision-received.md    MATCH (474 bytes)
evt-000006-evidence-transition-applied.md MATCH (592 bytes)
evt-000007-task-invalidated.md           MATCH (429 bytes)
evt-000008-curated-knowledge-admitted.md MATCH (496 bytes)
evt-000009-curated-knowledge-invalidated.md MATCH (436 bytes)
evt-000010-contradiction-resolved.md     MATCH (508 bytes)
evt-000011-contradiction-superseded.md   MATCH (430 bytes)
evt-000012-source-retracted.md           MATCH (405 bytes)
```

Refactor preserved: creation-link resolution across full journal, validity over full history, late-invalidation rewrites byte-identical to scratch, link emission single path (`_see_links`).

---

## (C) CLI Verify-vs-Project Consistency

**Test:** `hermes vault project` → `hermes vault verify` round-trip; tampered/missing notes refused.

| Scenario | Project RC | Verify RC | Findings |
|----------|------------|-----------|----------|
| Clean project + verify | 0 | 0 | OK (0 findings) |
| Note tampered after project | 0 | 1 | `TAMPERED_NOTE` event_ids=[3] |
| Note deleted after project | 0 | 1 | `MISSING_NOTE` event_ids=[3] |

**Result: PASS** — Verify passes exactly what project writes; verify refuses what project would refuse (tampered/missing notes detected with correct IDs).

---

## (D) 18-Code Closed Set Completeness

**FINDING_CODES (18):**
1. BACKFILLED_RANGE
2. CURSOR_MISMATCH
3. CURSOR_MISSING
4. CURSOR_RESTORED_AHEAD
5. DANGLING_LINK
6. GAP_RANGE
7. INVENTED_NOTE
8. JOURNAL_HEAD_CHANGED
9. JOURNAL_HEAD_REGRESSED
10. LOST_RANGE
11. MANIFEST_MISSING
12. MANIFEST_PROJECT_MISMATCH
13. MANIFEST_UNREADABLE
14. MISSING_NOTE
15. NOTE_BEYOND_CURSOR
16. NOTE_DIGEST_DIVERGES
17. RECOMPUTE_REFUSED
18. TAMPERED_NOTE

**19th failure shape:** Manifest `gap_event_ids` not verified (A2) — the manifest includes `gap_event_ids` as a certified field, but the verifier treats it as informational only, reporting current journal gaps as `GAP_RANGE` without comparing to the manifest's recorded gaps. A forged manifest with incorrect `gap_event_ids` passes verification.

**Additional gap:** Filename canonicality not verified (A3) — the manifest records filenames, but the verifier does not check they match `note_filename(event_id, event_type)`.

The existing test `test_every_emitted_finding_code_is_in_the_closed_set` passes because it only checks codes *emitted* by the verifier, not codes that *should be emitted* for missing validations.

---

## Raw Gate Outputs

### 22-Test Vault Manifest Suite
```
tests\test_vault_manifest.py ......................  [100%]
22 passed in 0.97s
```

### Ruff (src/hermes/vault/manifest.py, projection.py, cli.py)
```
All checks passed!
```

### Pyright (strict, same files)
```
0 errors, 0 warnings, 0 informations
```

---

## Findings Classification

### MUST-FIX (blockers — false-OK on certified manifest fields)

| ID | Finding | Fix Required |
|----|---------|--------------|
| M1 | Manifest `gap_event_ids` not verified against journal | In `verify_manifest`: after recomputing `gaps = journal_gap_event_ids(conn, cursor_after)`, compare with `manifest["gap_event_ids"]`; if different, emit `GAP_RANGE` (or new `GAP_MANIFEST_MISMATCH`) with both sets. |
| M2 | Filename canonicality not verified | In vault scan loop: for each `covered = manifest_entries[event_id]`, compute `canonical = note_filename(event_id, event_type_from_journal)` and verify `covered[0] == canonical`; if not, emit `NON_CANONICAL_FILENAME` (new code) or `INVENTED_NOTE` with detail. |

### SHOULD-FIX (architectural clarity)

| ID | Finding | Recommendation |
|----|---------|----------------|
| S1 | Document A1 (non-head journal mutations invisible) in manifest docstring | Add explicit note: "The manifest verifies the *projected notes* match the journal's *projection*. Journal column mutations that do not affect note rendering (e.g., `correlation_id` on non-head rows) are not detected. Head row mutations are anchored via `journal_head_hash`." |
| S2 | Consider promoting `RECOMPUTE_REFUSED` detail codes to first-class findings | Projector refusals (`INVALIDATOR_MISSING`, `VICTIM_MISSING`, `LINK_ESCAPE`, `BAD_EVENT_ID`, `VAULT_ROOT_*`, `PATH_*`, `SYMLINK_ESCAPE`, `ALIAS_ESCAPE`) are wrapped in `RECOMPUTE_REFUSED`. For auditability, consider mapping to dedicated finding codes. |

### NOTE (informational)

| ID | Observation |
|----|-------------|
| N1 | Scratch == incremental invariant holds perfectly across refactor — excellent preservation of P-AUTO-5 determinism guarantees. |
| N2 | CLI surface clean: `vault project` writes manifest + cursor atomically; `vault verify --json` emits stable schema for automation. |
| N3 | `test_every_emitted_finding_code_is_in_the_closed_set` is a valuable drift guard but only validates *emitted* codes, not *missing* validations. |

---

## Files Changed in This Audit Branch

- `tests/test_vault_manifest.py` — 22 tests (all pass)
- Adversarial test scripts (not committed): `test_false_ok.py`, `capture_old_projection.py`, `compare_projections.py`, `test_cli_consistency.py`

---

## Commit Hash

```
fccfd80 feat(vault): R-1 derived-view manifest + recomputing verify — closes D2/G silence (local-only)
```