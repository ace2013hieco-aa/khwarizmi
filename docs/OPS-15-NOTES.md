# OPS-15 — phase-2 rulings and implementation notes

| Item | Value |
| --- | --- |
| Slice | OPS-15, phase 2 |
| Base | `main` at `fd66a65` (OPS-14 landed) |
| Branch | `slice/ops-15-retry-feedback` |
| Design gate | `docs/idr/LIVE-CONTRACT-RETRY.md` (unchanged; approved by these rulings) |
| Date | 2026-10-25 |

The design gate was written on `528a72c` ("OPS-14 is not landed"). The branch is
rebased onto `fd66a65`; the gate's §9.1 caveat is discharged by OPS-14's landed
contract. Re-checked at implementation time: OPS-14 added no whole-reply
`MALFORMED_PAYLOAD` check at the model plane — its new refusals are gateway
payload validators, post-draft, so nothing in OPS-14 changes the retryable-site
census below.

## Rulings

### R1 — the predicate: approved

A boolean `contract_feedback` set at the exact `_validate_output` sites is the
predicate, not a code set. `ROLE` is emitted at unrelated partition sites, and
detail-prefix matching would make wording into a contract. The existing
`RETRYABLE_MODEL_REFUSALS` fallback stays for the LOOP-4 `RATIONALE` retry.

### R2 — one retry per model phase per tick: approved

`min(1, supervisor_retry, call_budget - 1)` is the shape. It reuses
`RetryBudget`, makes a second refusal terminal, and makes a third call
impossible.

**Recorded asymmetry, not a bug:** `researcher`, `experimenter`, `critic` and
`synthesizer` declare `max_model_calls_per_tick: 2` and get one retry;
`planner` and `verifier` declare `1` and get none. Two of the stages most prone
to `kind None` — QUESTION on `planner`, EVIDENCE on `verifier` — therefore have
no retry, which is why run 8 failed at QUESTION's first attempt and at
CRITIQUE. Raising those caps is a separate cost decision.

### R3 — what the cap does and does not bound

`per_run_tokens` is a **provider-request** counter, and the methodology handler
reports zero provider requests, so model calls are not charged to it today.
The declared token cap does not bind model spend, retry or no retry, and a
retry spends real money that no declared ceiling accounts for.

The implemented rule bounds **model calls per phase per tick**, and only that.
The note, the code comments and the tests must not claim token or dollar
boundedness.

> **OPS-16 — model-call accounting.** The Controller's `per_run_tokens`
> envelope counts provider transport requests, and the methodology handler
> reports zero of them; model calls are therefore not charged to it. Until
> OPS-16 lands, **no run may be described as spend-capped**: OPS-15 bounds
> model calls per phase per tick, not tokens or dollars.

### R4 — trace and metrics: approved

Two `MODEL_REQUESTED` events, an attempt-level `MODEL_REFUSED`, both refusals
retained in `ProposalSet.refusals`; M1 and M6 count both. A `SUCCEEDED` retried
run may retain a refusal: the run succeeded *after* a refusal, and hiding that
would understate the refusal rate. Pinned.

### R5 — the feedback envelope, with the escaping extension

`runtime.contract_feedback`, `{attempt, code, detail}`, canonical JSON,
4 KiB bounded, no excerpt. If the opening-tag forging test fails, extend
`render_user`'s escaping to opening tags — the escape is the control, and a tag
that can be opened from inside an envelope defeats it. That change needs its
own pin and must not alter the rendered text of any non-forging prompt; the
baseline is checked before accepting it.

### R6 — the crash/resume gap: recorded, not fixed

The retry counter is process-local. A crash before the tick checkpoint can
replay the tick and pay for the retry again on resume. Recorded as debt; no
resume state is added in this slice.

### R7 — the 8-call worst case: accepted, bound stated

If `MALFORMED_PAYLOAD` stays retryable, a model that always malforms costs two
runtime calls per stage instead of one, and each runtime call may cost the
router's existing four provider attempts — 8 provider attempts in the worst
case for that class. The bound per run is **stages × 2** runtime calls (two
attempts per stage where the profile's cap allows), which is strictly cheaper
than the current recovery: a task-level retry re-runs the whole methodology.

## Invariants

- No new event kind, no new write, no transaction. Census unchanged:
  124 / 28 (19/5/4) / 1 / 15 / 0.
- The LOOP baseline must not move. A pinned row or digest that moves is a
  failure to report, never a re-pin.
- Drain-only unchanged. B4 stays 24. Governed docs untouched.
- A second refusal fails the run exactly as today.
- No key material anywhere.

## Implementation outline

1. `tools/models/router.py`: `contract_feedback` on `_Refusal` and
   `ModelRefusal`; mark the `_validate_output` shape sites and the kind-check
   `ROLE`; copy it in `_refuse`. `as_dict()` and `TERMINAL_REFUSALS` unchanged.
2. `agents/runtime/run.py`: `_retryable_model_refusal`; the one-retry budget;
   the `on_retry` hook; the attempt-2 `MODEL_REQUESTED`, the attempt-level
   `MODEL_REFUSED`, and the retained attempt refusal.
3. `agents/runtime/supervisor.py`: optional `on_retry`, fired only after the
   budget and deadline checks pass, before sleeping.
4. `agents/runtime/assembly.py`: `CONTRACT_FEEDBACK_ORIGIN` and
   `contract_feedback_envelope`; choose it by the refusal's marker.
5. `tools/models/cloud.py`: escape opening tags as well as closing tags.
6. `tests/test_ops15_contract_retry.py`: the refusal-site enumeration, both
   falsifiers, the envelope pins, the digest pins; update the existing
   retryable-matrix assertion.

License: Apache-2.0 (LICENSE).
