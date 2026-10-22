# MERGE-LOG-COND-TYPE — `condition_type` admitted with a versioned command hash (GAP-1 D4-A)

## Provenance

| Item | Value |
| --- | --- |
| Task | COND-TYPE-MERGE (merge gate; local FF — the push is bundled with the wave-2 fleet under one human D9 pin) |
| Base (`main` before) | `2d444dc` (HYGIENE-2 landing + its merge log) |
| Slice | `slice/cond-type@24e8846`; **restacked** as `slice/cond-type-restacked@dc4c509` (cherry-pick of `1db4f9d`; the slice's own re-stamp dropped and re-created for the combined count) |
| Landed tip (FF'd to) | `dc4c509da3ef667a711ceac6282d12768d15a5eb` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — bundled with the wave-2 fleet under one human D9 pin |

## Scope

```
src/hermes/research/failure_classification.py | +87 -26  (hash v2 + v1 verify-only)
src/hermes/research/gateway.py                | +42      (closed key, default, dual-read)
src/hermes/research/controller.py             |  +7      (condition_type pass-through)
tests/test_cond_type_1_condition_type.py      | +365     (12 tests)
docs/SUITE-COUNT.md                           |  +3 -3   (4866 -> 4878)
```

## What was certified

- `condition_type` joins the closed RECORD_CLASSIFICATION payload keys; an
  absent/`None` value is the declared `UNDETERMINED` default (explicit, not
  implicit); any non-enum value refuses `MALFORMED_PAYLOAD` before any write.
- **Hash version 2** of the HumanDecision command binding: the canonical
  preimage now carries `condition_type` plus an in-band `hash_version` tag.
  **Dual-read**: a `HumanDecisionReceived` recorded before the bump still
  binds its command under the v1 preimage (`legacy_classification_command_hash`,
  verify-only), but ONLY for the declared default `UNDETERMINED` mapping — a
  pre-bump approval can never authorize a non-default condition type. Stored
  hashes are never rehashed or mutated.
- The condition is part of the operator-approved command from v2 onward;
  the duplicate rule is unchanged (a different `condition_type` yields a
  different content-addressed command identity, per the existing rule — no
  new idempotency policy was invented).
- 12 tests: canonical preimage includes the field+version; legacy verify
  path; non-default requires the v2 binding; unknown value refuses; default
  stability; closed-key behavior; controller pass-through.

## Gates (raw)

Agent run at slice tip: **FULL suite 4870 passed, 3 skipped, 0 failed**;
stamp 4873; census PASS; B4 24; ruff pass; pyright 0/0/0.

Director re-derivation at restacked tip `dc4c509`: battery
(`test_cond_type_1_condition_type.py` + `test_p6_classification.py` +
`test_cres_digest_binding.py` + `test_s2_human_decision_append.py`)
**61 passed**; stamp `--check` OK **4878** (4866 + 12); census PASS;
B4 **24 passed**; ruff `All checks passed!`; NOT-list **0 hits**
(word-boundary).

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| stored-hash mutation / silent rehash | **none** — dual-read is verify-only |
| v1 approval widening to non-default condition types | **blocked** — legacy admits `UNDETERMINED` only |
| census shift | **none** — 124 / 28 unchanged |
| B4 governed corpora | **PASS** — 24/24; no governed-doc edits |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `2d444dc` |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies a versioned command-binding field. It makes no validity,
reproducibility, or admissibility claim.

License: Apache-2.0 (LICENSE).
