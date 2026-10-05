# Contradiction Lifecycle & Classification Wiring — Continuation Audit (docs-only)

**Date:** 2026-09-16 · **HEAD:** `ff79bb6` (`ff79bb64a656d08209ba417080c978dc05937846`) ·
**Branch:** `main` (== `origin/main`) · **Scope:** commits `24225df`, `80f5459`, `ff79bb6`

## Purpose

This is the continuation of the audit carried out the previous session (2026-09-16),
which established findings but was interrupted before the report landed. It records,
with executed evidence, what the three most recent `main` commits wire and — importantly —
the single honest open item they leave behind. **Docs-only: zero `src/` or `tests/` edits.**

## Verification run — real output

| Check | Result |
|---|---|
| Full suite | `scripts/run_tests.py -q` → **2013 passed, EXIT=0** (reported last session) |
| CI Tests job (`34355667628`, HEAD) | log line **`2013 passed, 15 warnings in 516.71s`** (executed via `gh run view --log`) |
| CI all-jobs | **6/6 success** (Tests, pyright src-strict, local-runner smoke, ruff, uv audit, profiled gate) on `ff79bb6`, `80f5459`, `24225df` |
| Branch sync | `git rev-parse HEAD origin/main` → identical; tracked tree clean (only `.freebuff/` untracked) |

## What the three commits wire

| Commit | Scope | Key surfaces (verified) |
|---|---|---|
| `24225df` | substrate | `src/hermes/research/contradictions.py` (`detect_classification_conflicts`, DETECTOR_VERSION), gateway +522, controller +300, provider adapters, migrations |
| `80f5459` | provider record-replay | `providers/replay.py`, `source_handlers.py`, `persistence/provider_interactions.py` |
| `ff79bb6` | classification → contradiction | `core/intents.py` (+`RECORD_CLASSIFICATION`), `gateway.py` (+`_validate_record_classification`), `controller.py` (+`record_failure_classification`), `failure_classification.py`, `tests/test_p6_classification.py` (+701) |

## Classification ingestion is fail-closed and correctly gated

- `RECORD_CLASSIFICATION` and `RECORD_CONTRADICTION` are both **internal-only** —
  `intents.py:135–143` `internal_only()` returns them, and `llm_proposable()`
  (`intents.py:114–121`) excludes them. An LLM can never propose them.
- `_validate_record_classification` (`gateway.py:2832–2849`): operator-asserted P6
  admission through the IDR-040 §3 record-operator-decision precedent. Fail-closed:
  ratified operator credential, recorded `HumanDecision` binding the deterministic
  command hash, closed payload schema, ratified failure class, and the existing
  `FailureClassificationRepository.record` write boundary (own transaction) re-verifies
  project match, evidence ownership, digest identity, content-hash idempotency.
- No dedicated mutation event by design — `IntentApplied` + artifact row are the trail
  (gateway validator docstring).
- Controller surfaces (all lease-held, rejections surfaced as data, never raised):
  - `record_failure_classification` (`controller.py:2122`) — records the HumanDecision first, then submits.
  - `record_contradiction_resolution` (`controller.py:2012`) — operator verdict via `HumanDecision` binding `resolution_id`.

## Contradiction detector — deterministic and machine-derived

- `detect_classification_conflicts` (`contradictions.py:106–139`) — pure pass: same
  project/program/hypothesis, different `failure_class`, neither invalidated, non-empty
  evidence overlap; deterministic ordering, no I/O/clock/randomness; a failure asserts
  nothing (absence of a record is never evidence of absence).
- `Controller.detect_contradictions` (`controller.py:1862`) — builds `RECORD_CONTRADICTION`
  intents, submits via `apply_intent` (gateway re-verifies each pair rule fail-closed),
  **no operator credential** (no human verdict; lease alone serializes the write).
  Detector failure returns `{"rejected": True, "code": "DETECTOR"}` with zero writes.

## Open item — the detector is not loop-invoked (honest finding)

`grep -rn "detect_contradictions" src/` returns **only** the definition at
`controller.py:1862` plus test callers in `tests/test_chg1_contradictions.py` and
`tests/test_p6_classification.py`. The production `tick()` body (`controller.py:481–577`)
runs recovery → mode check/self-heal → evidence-ladder APPLY (`_apply_evidence_ladder_pass`,
:564) → requeue/re-execute → `_dispatch_pass` (:571), and **never** calls
`detect_contradictions`. Neither does `run()` (:587–604). The `hermes run` CLI path
(`cli.py:494`) drives only `ctrl.run(...)`.

So the classification→contradiction pipeline exists end-to-end and is exercised by tests,
but in production it is reachable **only by an explicit/scheduled call** — not by the
reconcile loop itself. Whether that is intended (Director/scheduler-driven) or a pending
wiring step is **not stated** in the three commit messages.

**Disposition:** documented and scoped here per the repo's gate discipline ("latent defects
found mid-gate get documented + scoped + referred to a separate gate, never fixed as a side
effect"). This report does **not** change code. A decision on wiring `detect_contradictions`
into the ACTIVE tick (or a scheduler leg) is deferred to a separately-chartered step.

## Provenance & scope controls honored

- No production-code edits (this is a docs-only continuation).
- No Git history rewrite, no force-push, no reset.
- `.freebuff/` untracked and un-staged; tracked tree clean.
- All claims above cite file:line against HEAD `ff79bb6`.