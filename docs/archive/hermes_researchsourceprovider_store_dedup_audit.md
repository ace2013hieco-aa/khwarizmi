# ResearchSourceProvider — ArtifactStore Type-Blind Dedup Audit (non-source callers)

**Date:** 2026-08-14 · **Auditor:** independent hostile pass · **Scope:** does
the same same-hash/different-type confusion that R02 closed inside the
source slice exist for the store's OTHER callers (extraction, programs)?

## Verdict

**CLEAN — no gap outside the source slice.** The type-blind `ArtifactStore`
dedup (get-by-hash → return existing row unconditionally) is reachable from
**exactly one production consumer** — the source slice's `_prepare_fetch` —
and that consumer now refuses a wrong-typed row (R02, `IDR-035`). No other
code path writes `artifacts` rows.

## Evidence

| Probe | Result |
|---|---|
| S1 — the store itself is type-blind: writing payload bytes whose content hash already exists as a `source_result` row returns the source_result row unchanged | **PASS** (documented store behavior — the guard lives at the slice boundary, not the store) |
| S2 — the only production consumer refuses the wrong-typed dedup | **PASS** (shipped fixture `test_payload_reuse_requires_payload_type`) |
| S3 — artifact-write surface enumeration: `ArtifactRepository.record` call sites = `source_outcomes.py:671` (`_commit` reuse loop, guarded by `_verify_reused_row`) + `store.py:92` (guarded by `_prepare_fetch`); `source_outcomes.py:183` is a pass-through (`SourceRepos.record` → `SourceOutcomeRepository.record`); `gateway.py:263` is `ResearchProgramRepository.record` (research_programs table, not artifacts) | **PASS** — exactly two writers, both guarded |

Additional code inspection:

- **Extraction path (`record_extraction`)**: persists claim/assumption rows
  to its own tables — it never writes `artifacts` rows, so the store's dedup
  is unreachable from it. Its artifact references are read-side with a
  REQUIRED `artifact_type:ref` prefix (`extraction.py` source_ref
  validation) — the type discipline is on the reference, not the write.
- **Programs path**: `research_programs` table via `ResearchProgramRepository`;
  no `artifacts` interaction.
- **`ArtifactStore` construction**: never in production `src/` — it is
  injected through the source-slice wiring only (tests construct it).

## Disposition

No fold-in required. The R02 slice-boundary guard (`_prepare_fetch` type
check) is the correct placement: the store stays generic (global-content
dedup, documented), and the source slice enforces type discipline at its own
write boundary. Note for the closure gate: a future slice that reuses
`ArtifactStore` must apply the same boundary guard — the store itself will
remain type-blind by design (documented in `store.py`).

## Status

Recorded for the closure-gate package
(`hermes_researchsourceprovider_closure_gate_package.md`). Step 6 remains
**IMPLEMENTED — TESTED**, NOT RATIFIED.
