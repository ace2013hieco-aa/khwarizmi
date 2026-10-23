# LOOP-5 (E4) — proposal admission vs the tick's evidence gathering

| Item | Value |
| --- | --- |
| Task | LOOP-5 / E4: does a proposal cross the write path before the tick's tool phase? |
| Base | `87f2cd2` (`main`; LOOP-M baseline landed) |
| Branch | `slice/loop-5-ordering` |
| Phase | 1 — design gate only; **no code, tests, migration, or fixture change** |
| Status | **RULED A — the ordering is correct** (2026-10-23, human) |
| Decision | A — document the current order; the ruling and E4 reclassification are below |

This note is the design gate, not the implementation. The design gate made no
runtime file edit; the A follow-up changes only a `_tick` docstring and the
probe's claim. The measured target is `docs/LOOP-BASELINE.md`, where scenario
S6 is pinned at `TOOL_FAILED`, 1 tick, **1 admitted proposal**, 1 other
refusal, and trace digest `a2fab43e…` (`docs/LOOP-BASELINE.md:68,107`).

## Ruling (2026-10-23, human): A — the ordering is correct

1. **`IntentApplied` records admission, not execution.** The journal says a
   decision was admitted; it does not claim the decision succeeded.
2. **The tick's tools are siblings of its proposals, not their justification.**
   Both come from the *same model response*: `_model_phase` takes
   `result.structured` (which carries the drafts and `tool_calls`) and calls
   `_emit_drafts` before returning `(structured, drafted)`; `_tool_phase` then
   runs `structured["tool_calls"]`.
3. **A tool cannot consume a same-tick admission.** `_tool_phase`
   (`run.py:1077-1238`) contains **no reference** to `state.proposals`,
   `entity_id`, or an admission result. The model wrote its tool-call arguments
   before the admission existed, so no tool call can depend on it.
4. Therefore a tick-N proposal is justified by ticks 1..N-1 evidence, and a
   *sibling* tool failing does not retroactively unjustify it.
5. **B would be an audit regression.** Under B a `TOOL_FAILED` run discards the
   staged intent and leaves **no record that the model decided anything** —
   while the tools it requested failed. That contradicts the posture AUDIT-TXN
   just established: the record should say what happened, and what happened is
   "a decision was admitted, then a sibling tool failed."
6. **E4's fact was right; its inference was not.** The probe proved the
   ordering. The phrase "the tools that justify them" is the unsupported step,
   and §2.1's inventory is the evidence that it is false.

**E4 is reclassified:** the ordering is confirmed; the justification inference
is rejected. B was declined on **audit grounds**, not measurement grounds. The
LOOP-M baseline is an instrument, and its S6 row is a pin, not a defect marker;
a deliberate amendment could record a different ordering, but it cannot make
the audit record say what B would omit.

## 1. The finding, live

The tick order at this base is:

```
_tick (run.py:632)
  _model_phase (run.py:646)
    └─ _emit_drafts (run.py:819)
       └─ _emit_intent (run.py:861 → :1023)
          └─ _apply (run.py:1031) → apply_intent (the single mutation path)
  _tool_phase (run.py:653)
     └─ failure: state.terminate(FAILED, TOOL_FAILED) (run.py:657)
  _delegation_phase (run.py:659)
  _absorb_evidence (run.py:662)
  _tick_termination (run.py:667)
  supervisor.check (run.py:674)
  state.terminate(SUCCEEDED, termination) (run.py:680)
```

The LOOP-0 probe pins it: `tests/test_loop0_e1_probe.py:295-320` asserts
`state == FAILED`, `termination == TOOL_FAILED`, `len(applier.calls) == 1`, and
one `INSERT_TASK` proposal. The probe's own print reports
`applier_calls=1`.

This is a contract decision because `apply_intent` is the single mutation path
and there is no compensation/retraction primitive for an applied proposal. The
runtime cannot "take back" a tick-N proposal if the tick's tool batch fails
afterwards. The only levers are changing *when* admission happens (B), declaring
the order correct (A), or making the timing a declared policy (C).

## 2. Dependency inventory (the crux)

The question: does anything in tick N consume something that exists only if a
tick-N proposal was already applied?

| # | Dependency | Evidence | Same-tick admitted input? |
| --- | --- | --- | --- |
| 1 | `capability_refs` (LOOP-4 E8) | `_evidence_refs` (`run.py:868-879`) is called inside `_emit_drafts` (`:828`) before any admission. It reads `state.feedback`, which is populated only by `_one_tool_call` (`:1161, :1174, :1207, :1223, :1234`) — i.e. by ticks that already completed. `_model_request` appends those envelopes at `:1547-1549`, before the current tick's tools run. | **No.** The refs are a pre-tool snapshot of prior evidence; the current tick's admission cannot appear in them. |
| 2 | `_tool_phase` inputs | `_tool_phase` (`:1077-1119`) and `_one_tool_call` (`:1121-1238`) read `structured["tool_calls"]`, `spec`, `context`, `state` (`tool_calls`, `refusals`, `feedback`), `run_id`, and `tick`. `InvokeRequest` is built from the call item, the derived idempotency key, spec/profile, and grant (`:1185-1194`). They never read `state.proposals`, `Proposal.admitted_entity_id`, or an admission-populated artifact store. The applier's `entity_id` is stored only on the `Proposal` (`_emit_intent`, `:1054`). | **No.** No tool receives a same-tick admitted entity or artifact. |
| 3 | Delegation | `_delegation_phase` (`:1242-1262`, called at `:659`) runs after tools. `_delegate_one` (`:1264-1389`) builds the child context from the child payload/context envelopes (`:1362-1370`) and starts the child run (`:1371`). The parent's tick-N `state.proposals` is not an input. The child command admission at `:1351` is itself post-tools. | **No.** The child does not depend on the parent's same-tick draft admissions. |
| 4 | Audit row (AUDIT-TXN) | `_emit_intent` emits `INTENT_EMITTED` (`:1028`), calls `_apply` (`:1031`), whose applier is `apply_intent` in production (`gateway.py:4646`). The audit record is built at `gateway.py:4750-4757` and carried into the validator's transaction; `IntentApplied` lands atomically with the mutation. | **No dependency; atomicity is preserved.** Deferring `_apply` defers the row with the mutation; a never-applied staged draft has no row. |
| 5 | Review | `_close` (`:542-580`) runs the review after the tick; `_maybe_review` (`:1417-1455`) builds reviewer envelopes from `state.proposals` (`proposal_envelopes`). | **No dependency, ordering constraint.** B must commit the staged drafts before `_close`; then the reviewer sees the same admitted set. |
| 6 | `state.proposals` consumers | `_tick_termination` max-proposals (`:730`), review presence (`:1409`), result assembly (`:1625`), delegation append (`:1353`). | **No dependency, placement constraint.** B must commit before `_tick_termination` and `_delegation_phase` so the max-proposal check and proposal order see the same set. |
| 7 | Artifact store during the tick | `self._artifacts` is used only for oversized model output (`:801-803`, `:845-848`); admission does not write to it from the runtime. The model cannot author a derived identity (`_derive_payload`, `:1004-1010`). | **No.** There is no admission-populated artifact for a tool to read. |

**Conclusion:** no tool, delegation, audit, or review path consumes a same-tick
admitted artifact. B is functionally possible. The obstacle to B is not a
dependency; it is the audit-record contract: a `TOOL_FAILED` run would discard
the staged intent and leave no record that the model decided anything. The
event/trace movement is a measurement cost and would require a deliberate
baseline amendment; it is not the reason the ruling declines B.

Scope caveat: this inventory covers the runtime's **provided inputs**. A tool
implementation that independently queries durable state could observe a
same-tick admission, but no shipped capability port does, and the runtime hands
a tool no same-tick entity or artifact. Such a query would be an undeclared
tool-contract coupling, not a dependency of the tick order.

## 3. Options

### A — status quo, documented

The model proposes from the evidence gathered in ticks `1..N-1`; the tool phase
in tick N gathers evidence for tick N+1. A `TOOL_FAILED` therefore ends the run
with tick N's proposals durable. The claim must be stated plainly: **a proposal
can be admitted on evidence that a later tool call in the same tick fails to
materialise, and the runtime does not roll it back.**

Cost: rewrite the E4 probe so it asserts the documented behaviour rather than
calling it a defect; add the claim to this note/runtime documentation. No
runtime code, no baseline movement. S6 stays exactly at 1 admitted / `a2fab43e…`.

### B — stage, then admit after the tools succeed

Split the propose/commit path:

1. `_model_phase` validates the drafts and emits `PROPOSAL_DRAFTED` (and any
   `PROPOSAL_REFUSED`) but does **not** call `_emit_intent`/`_apply`. It stages
   `(kind, rationale, payload, artifact_ref, capability_refs)` with
   `capability_refs` snapshotted before tools (`_evidence_refs`, `:868-879`).
2. `_tool_phase` runs. On failure it returns `False`; the staged intents are
   discarded; the run terminates `FAILED`/`TOOL_FAILED`; no `INTENT_EMITTED`,
   no `IntentApplied`, no durable proposal.
3. On success, commit the staged intents in proposal order by calling
   `_emit_intent` (which emits `INTENT_EMITTED`, calls `_apply`, and emits the
   admission event) **before `_delegation_phase`, `_tick_termination`, and
   `_close`**. Then continue as today.
4. Tool-phase cancellation/deadline: `_tool_phase` currently breaks its batch
   on a supervisor check (`:1112-1115`) and returns `True`. The commit must know
   that the batch stopped on a supervisor check and skip the staged intents.
   A `stopped` flag (or equivalent) is required. A model-call expiry that
   occurs before the tool phase (scenario S7) must still preserve S7's
   one-admitted/TIMEOUT baseline if that row is to stay fixed; the commit must
   distinguish it from a tool-phase stop.

Consequences:

- **S6**: admitted count becomes **0**; trace digest changes.
- **S1, S2, S3**: admission events move after the tool events. The event order
  changes (`PROPOSAL_DRAFTED → TOOL_REQUESTED → TOOL_OBSERVED → INTENT_EMITTED
  → INTENT_ADMITTED`), and `Supervisor.trace_digest` hashes event kind,
  sequence, and detail (`supervisor.py:240-243`), so **their trace digests
  change** even though all non-trace metrics stay the same.
- **S4, S5, S7, S8**: no tool call interleaves with a draft admission (S4/S5
  review children and S7/S8 have empty tool phases), so their trace order can
  stay identical; the implementation must assert that.
- **S7**: the model-call deadline expires before the tool phase; the commit
  point determines whether S7 stays at 1 admitted or moves to 0. If S7 must
  stay fixed, commit before the terminal check and only skip on a tool-batch
  supervisor stop. This is a design choice the implementation must pin.
- All non-trace metrics for S1–S5/S7–S8 must be unchanged; only S6's admitted
  count is supposed to move.

### C — per-profile `proposal_admission` policy

A new declared knob (`immediate` | `after_tools`), default `immediate`
(preserves every baseline row). Two code paths to pin; the E4 baseline would
not move unless a profile opted in. The dependency inventory found no
profile-specific dependency, so there is no need for both behaviours. C is
only a fallback if the Director wants B but also wants to keep `immediate` for
some profiles.

### Recommendation

**A — the ordering is correct.** The dependency inventory shows no same-tick
consumer, so B was implementable; the decisive reason for A is the audit
contract, not the baseline. `IntentApplied` records that a decision was
admitted, not that it executed successfully. A tick's proposals and tool calls
are siblings from one model response; the model wrote the tool arguments before
admission existed, and `_tool_phase` reads no `state.proposals`, `entity_id`, or
admission result. A tick-N proposal is therefore justified by ticks 1..N-1
evidence, and a sibling tool failure does not retroactively unjustify it. Under
B a `TOOL_FAILED` run would discard the staged intent and leave no record that
the model decided anything while the tools it requested failed — an audit
regression against AUDIT-TXN. The LOOP-M baseline is an instrument; a
deliberate B amendment could record a movement, but it cannot make the audit
record say what B would omit. E4's ordering fact stands; its "tools that
justify them" inference does not.

## 4. Invariants to preserve (either option)

1. **Single mutation path.** Admission only through `_emit_intent` → `_apply` →
   `apply_intent`; B stages plain data and commits through the same call. No
   new writer, no direct repository call.
2. **R4 terminal semantics.** `TOOL_FAILED`, `TIMEOUT`, `CANCELLED`,
   `SUCCEEDED` keep their meanings and precedence. A cancel or deadline
   observed during the tool phase is the terminal state; under B the staged
   intents are not applied after such a stop.
3. **AUDIT-TXN atomicity.** One `IntentApplied` per admitted staged intent, in
   the same transaction as its mutation; a never-admitted staged intent has no
   row (`gateway.py:4750-4757`).
4. **TAMPER-2.** No new event kind, no raw event insert; the existing
   `INTENT_*` events and the chained journal writer are unchanged.
5. **Census.** 124 / 28 (19/5/4) / 1 / 15 / 0. Staging is in-memory; commit
   reuses `_emit_intent`/`_apply`. If a new transaction-control call is needed,
   stop and report.
6. **LOOP-1..4 behaviour.** Context assembly, retained feedback, review rounds,
   deadline/retry. `capability_refs` must be snapshotted at propose time, not
   recomputed after tools. Happy-path intents/order/verdicts stay identical.
   Under B, trace equality is asserted for S4/S5/S7/S8 and the expected changes
   for S1/S2/S3/S6; under A, every trace digest stays identical.

## 5. Falsifiers the implementation must ship

- **E4 fault.** Under A: the probe asserts the documented order — one admitted
  proposal, `TOOL_FAILED`, applier called once — and the S6 baseline stays
  pinned at 1 / `a2fab43e…`. Under B: zero `INTENT_EMITTED` with an admission,
  zero `IntentApplied`, zero proposals in the result, `TOOL_FAILED`; the S6
  baseline is re-pinned to 0 and a new trace digest.
- **Happy path.** Identical intents, order, and admission verdicts against the
  pre-change tree. Under B, S1–S3 trace digests are expected to change (event
  reordering) and must be explicitly re-pinned if B is approved; S4/S5/S7/S8
  must remain identical.
- **Review (LOOP-3).** A failing verdict still re-drives drafting with the same
  round bounds; no staged intent leaks across a review round; S4/S5 unchanged.
- **Deadline (LOOP-4).** An expiry during the tool phase still terminates
  `TIMEOUT`; under B no staged intent is applied. If S7 is to stay fixed, a
  model-call expiry before the tool phase must still admit the staged draft
  exactly once before the terminal record.
- **Cancel during the tool phase.** `CANCELLED`; under B no staged intent
  applied.
- **Audit.** One `IntentApplied` per admitted proposal; none for a discarded
  staged draft; the journal chain verifies.
- **Census/B4.** The certified census is unchanged and the 24 B4 tests still
  pass.

## 6. Decision requested

The ruling above is the decision; this is the request as it was put to the
human.

> **LOOP-5 ruling.** No tool, delegation, audit, or review path consumes a
> same-tick admitted artifact; option B is implementable. But B moves the
> trace digests of S1, S2, S3 (and S6) because admission events reorder after
> the tool events, while the charter fixes every row except S6. Do we
> (A) document the current order — proposals are admitted on ticks 1..N-1
> evidence and survive a later tool failure — and rewrite the E4 probe to
> assert it; or (B) move admission after the tools, accepting a baseline
> amendment that re-pins S1–S3 trace digests and S6 to zero? Recommended:
> **A**, because the journal records admission, not execution, and B would
> leave no record of the admitted decision when a sibling tool fails. The
> baseline remains a pin; a deliberate B amendment could move it, but that is
> not the reason. If B is chosen, approve the baseline amendment explicitly;
> C (a per-profile knob) is not justified because no same-tick dependency
> exists.

## 7. What this gate does not do

The design gate itself made no code change. Under the A ruling, the approved
follow-up changes only the E4 probe's claim, the `_tick` docstring, and the
baseline note; no behavior, event, write, or transaction changes.

License: Apache-2.0 (LICENSE).
