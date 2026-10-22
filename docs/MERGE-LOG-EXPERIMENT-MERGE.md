# MERGE-LOG-EXPERIMENT-MERGE — declare-experiment design record + fixture pins (GAP-1 D2-A, implementation deferred)

## Provenance

| Item | Value |
| --- | --- |
| Task | EXPERIMENT-MERGE (merge gate; local FF — the push is bundled with the wave-2 fleet under one human D9 pin) |
| Base (`main` before) | `8e913b4` (HYGIENE-1 landing + its merge log) |
| Artifact | `design/experiment-intent@331efa5` (single commit; LOCAL-ONLY authoring branch) |
| Slice | verified as `slice/experiment-merge@4a7fdb9`; **restacked** as `slice/experiment-merge-restacked@20e5d98` (artifact + landing reconciliation; the slice's own re-stamp dropped and re-created) |
| Landed tip (FF'd to) | `20e5d9865d73b7d6c091679a51e970fe8e8b38b2` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — bundled with the wave-2 fleet under one human D9 pin |

## Scope

```
docs/idr/EXPERIMENT-DECLARATION.md            | +326     (new design record)
tests/test_experiment_declaration_fixtures.py | +357     (31 collected tests)
docs/SUITE-COUNT.md                           |  +3 -3   (4886 -> 4917)
```

No `src/` change; no runtime authority implemented (D2-A: design record +
fixture pins only; the implementation owes its own charter).

## What was certified

- The design record is a **design/authority record only**: status "DESIGN
  (proposed — not implemented, not wired, not certified)"; the proposed
  `DECLARE_EXPERIMENT` kind is specified but absent from the vocabulary
  (`git grep` = 0 hits in `src/`). Prohibited-claims audit PASS — every
  validity/reproducibility mention is an explicit negation ("replay =
  byte/evidence determinism only, never validity"; "no digest/derived view
  is presented as authority").
- The fixture module is a **pure, in-memory test-local replica**: imports
  only `hashlib/json/re/pytest/dataclasses/typing` + the read-only
  `IntentKind` enum vocabulary; no gateway/controller/repository/provider/
  transport/DB import, no network, no DB, no filesystem writes, no clock.
  All 31 collected cases pass.
- 30 fixtures pin the specified schema/validator behavior (closed keys,
  bounds, 4 KiB rationale, role/project/credential/human gates,
  idempotency/supersession, project-scoped registry shape); 1 baseline lock
  pins the vocabulary has no experiment kind.

## Landing reconciliation (recorded)

The artifact authored its baseline lock when `IntentKind` had **19** kinds
(`_EXPECTED_KIND_COUNT = 19`). CRED-1 later added two director-only
credential kinds, so at the landing tip the live count is **21**
(director_only 4, llm_proposable 9, internal_only 9). The merge therefore
reconciled — in a dedicated line-owner-style commit `f548a6b`:
`_EXPECTED_KIND_COUNT` 19→21; doc §0.3 counts 19→21 and director_only 2→4;
partition line refs updated (`:135/:144/:158`); a note records that the
enumeration was authored at 19 kinds before CRED-1. The pin's intent
(no experiment kind; no partition membership) is unchanged — only the
incidental vocabulary count moved. This is the artifact's own "regen is a
line-owner duty" rule executed by the landing owner and documented here.

## Gates (raw)

Agent verification at slice tip: fixture file **1 failed, 30 passed** —
the ONLY failure was the stale count pin (`assert 21 == 19`), a STOP hit
reported verbatim rather than silently reconciled (correct behavior).
Full suite at that tip: 1 failed, 4888 passed, 3 skipped.

After reconciliation: fixture file **31 passed** (0.12s). Director gates at
restacked tip `20e5d98`: stamp `--check` OK **4917** (4886 + 31); census
PASS; B4 **24 passed**; ruff `All checks passed!`; NOT-list **0 hits**
(word-boundary). Full-suite proof for the composition is the final
combined wave-2 gate.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| prohibited claim in the design record | **none** — explicit negations; recorded |
| runtime authority / wiring smuggled in | **none** — 0 `src/` hits; fixture replica only |
| stale baseline pin | **reported as STOP, then reconciled as a documented landing edit** |
| B4 governed corpora | **PASS** — 24/24 (new IDR file is outside the governed corpus) |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `8e913b4` |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate lands a design record and fixture pins only. It certifies no
implementation, no validity, no reproducibility, and no admissibility.

License: Apache-2.0 (LICENSE).
