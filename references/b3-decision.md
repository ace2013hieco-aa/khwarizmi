# ADR-041 B3: Child Program Substance Derivation — Decision

## Context

The B3 controller method `_consume_approved_parallel_regime_proposals()`
(controller.py:3040) consumes APPROVED `PROPOSE_CLASSIFICATION_ACTION` events
whose action is `PROPOSE_PARALLEL_REGIME_TEST`, and is supposed to emit a
`PROPOSE_RESEARCH_PROGRAM` intent through the gateway.

**Current state of the stub (broken):**
The method builds a `PROPOSE_RESEARCH_PROGRAM` intent with:
- `proposed_by="DETERMINISTIC"` — **rejected** by `_require_role` (gateway.py:168),
  because `PROPOSE_RESEARCH_PROGRAM` is `director_only` (intents.py:131). Only
  `proposed_by="DIRECTOR"` passes the role gate.
- `scope_ref=""` (from `proposal.get("scope_ref", "")`) — **rejected** by the
  gateway with `SCOPE_NOT_GOVERNED` (gateway.py:230), since the proposal payload
  has no `scope_ref` field.
- Missing `epistemic_objective`, `hypotheses`, `predictions`, `discrimination_requirements`,
  `methodology_constraints` — these are **required** by `_draft_from_payload`
  (programs.py:1337+) and would cause a `KeyError`/`NOT_COMPILED` rejection.

**Consumed-tracking:** The stub claims idempotency via content_hash
collision (the gateway PA4 duplicate check at gateway.py:427), but this is
fragile — two ticks could race (though the lease fence prevents this). There
is **no explicit consumed-flag**: if emission fails on first attempt, a repeat
tick would retry the same proposal. The stub has no `upsert_intent`
(repositories.py has no `IntentRepository` — intents are ephemeral).

## Options

### (a) Clone parent substance, controller emits PROPOSE_RESEARCH_PROGRAM with proposed_by="DIRECTOR"

**Problem:** The controller IS `DETERMINISTIC`, not `DIRECTOR`. Emitting with
`proposed_by="DIRECTOR"` is an authority fraud — the controller is impersonating
the Director. The gateway's `_require_role` (gateway.py:168-171) enforces that
only `DIRECTOR` may propose `director_only` kinds. Bypassing this check would
require weakening the role boundary — explicitly forbidden by AGENTS.md
("No LLM/model output may decide a transition").

Even if we could bypass the role check, the substance would need to be cloned:
```python
parent = program_repo.get(parent_program_id)  # repositories.py:1677
payload = {
    "scope_ref": parent["scope_ref"],
    "epistemic_objective": parent["epistemic_objective"],
    "hypotheses": parent["hypotheses"],
    "predictions": parent["predictions"],
    "discrimination_requirements": parent["discrimination_requirements"],
    "methodology_constraints": parent["methodology_constraints"],
    "parent_program_id": parent_program_id,
    "parent_hypothesis_ref": parent_hypothesis_ref,
    "target_regime": target_regime,
    "triggering_classification_id": triggering_classification_id,
}
```

**Verdict: REJECTED.** Violates the director-only authority boundary. The
controller cannot impersonate the Director.

### (b) Controller emits a Director intent to fill in substance

"Controller emits a Director intent" — this is the same problem. The controller
is `DETERMINISTIC`. It cannot emit anything with `proposed_by="DIRECTOR"`.

If we interpret this as "the controller writes to the digest, and a later
Director turn converts it to a program" — this changes the B3 contract
fundamentally. ADR-041 AC-7 says the controller **emits** a
`PROPOSE_RESEARCH_PROGRAM` intent per approval. Making it a digest-only entry
means the controller does nothing automated — the Director must manually
convert each approved proposal. This defeats the "consumes APPROVED proposals"
design.

**Verdict: REJECTED.** Doesn't fulfill ADR-041 AC-7. The controller cannot emit
director-only intents.

### (c) New internal-only intent kind for controller-originated programs

Add `EMIT_PARALLEL_REGIME_PROGRAM` to `IntentKind` and to `internal_only()`
(intents.py:135-143). This intent is **admitted only by `DETERMINISTIC`**
(the controller's role), matching the internal-only precedent
(`RESOLVE_CLASSIFICATION_PROPOSAL`, `RECORD_SCOPE_REVIEW_DECISION`,
`RECORD_CLASSIFICATION`).

**Wired in the gateway** via a dedicated validator
`_validate_emit_parallel_regime_program` that:
- Dereferences `triggering_classification_id` (same 4-check guard as B2)
- Resolves `parent_program_id` from the repository via `program_repo.get()`
- **Clones the parent's substance** (`scope_ref`, `epistemic_objective`,
  `hypotheses`, `predictions`, `discrimination_requirements`,
  `methodology_constraints`) into the child payload
- Compiles via `compile_from_payload` + records with `produced_by="DETERMINISTIC"`
- Returns an `IntentResult` with `duplicate` from the PA4 get_by_hash check

**Scope_ref source:** The parent program's `scope_ref` column
(stored in `research_programs.scope_ref`, repositories.py:1610). Resolved via
`program_repo.get(parent_program_id)["scope_ref"]` — the PARENT program's
scope, not the proposal's. The scope is a frozen brief ID that remains valid
for the parallel regime (same project, same governed scope).

**Substance derivation:** Clone from `program_repo.get(parent_program_id)`
(repositories.py:1677 — returns `scope_ref`, `epistemic_objective`,
`hypotheses`, `predictions`, `discrimination_requirements`,
`methodology_constraints` as parsed JSON from the row). The child program
gets identical substance with `target_regime` swapped.

**Consumed-tracking mechanism:**

Mark consumed on the `ClassificationActionDecision` event itself — the gateway
already writes a `ClassificationActionDecision` event (gateway.py:577) with
`decision="APPROVED"`. The controller's query (controller.py:3078) joins
`events p` (ClassificationActionProposed) with `events d`
(ClassificationActionDecision) on `correlation_id`.

The tracking is done via an **idempotency key** on the program: the content_hash
of the parallel-regime program (which includes `parent_program_id`,
`parent_hypothesis_ref`, `target_regime` per `canonical_content_dict` at
programs.py:1500) serves as the dedup key. The gateway's PA4 check
(`program_repo.get_by_hash(program.content_hash)` at gateway.py:427) returns
`duplicate=True` for a repeat submission. The controller checks
`result.duplicate` and only appends to `consumed` when `!result.duplicate` —
so a repeat tick skips the already-emitted proposal. On a **refusal**
(`GatewayRejection`), the proposal is NOT marked consumed — the next tick
retries. This ensures no proposal is silently dropped on transient failure.

**The consumed-tracking is implicit via content_hash + gateway duplicate
detection, not an explicit flag.** This is the existing PA4 pattern (same as
supersession idempotency, gateway.py:424).

**IDR change required:**
- Add `EMIT_PARALLEL_REGIME_PROGRAM` to `IntentKind` enum
- Add to `internal_only()` frozenset (intents.py:135-143)
- NOT added to `llm_proposable()` (DETERMINISTIC-only)

**Amendment A1 (authority attribution):** The `produced_by` field on the
recorded program row must reflect the controller's actual role (DETERMINISTIC),
not be spoofed to "DIRECTOR". The `caused_by` on the
`ClassificationActionDecision` journal event already truthfully records
`operator` for the Director's approval; the controller's EMIT intent carries
`proposed_by="DETERMINISTIC"` (authorized via `internal_only`). The gateway
may **validate** the triggering classification and **clone** parent substance,
but it must NOT construct an inner Intent with `proposed_by="DIRECTOR"` or
otherwise re-attribute authorship. The trail must show DETERMINISTIC origin.

**Verdict: SELECTED.** This is the architecturally correct path:
- The controller (`DETERMINISTIC`) proposes an internal-only intent
- The gateway validates the triggering classification, clones parent substance,
  compiles, and records with `produced_by="DETERMINISTIC"`
- The consumed-tracking is implicit via content_hash dedup (no new state needed)
- Scope_ref comes from the parent program's stored scope_ref column
- Authority attribution is truthful: DETERMINISTIC origin preserved end-to-end

## Implementation Plan (Option C)

1. **intents.py:** Add `EMIT_PARALLEL_REGIME_PROGRAM = "EMIT_PARALLEL_REGIME_PROGRAM"` to `IntentKind`, add to `internal_only()`.
2. **gateway.py:** Add `_validate_emit_parallel_regime_program(conn, intent, *, program_repo, clock)` that:
   - Validates proposed_by="DETERMINISTIC" (via internal_only role check)
   - Dereferences `triggering_classification_id` with the 4-check guard (same as PROPOSE_RESEARCH_PROGRAM's B2 validation)
   - Resolves parent program via `program_repo.get(parent_program_id)`, clones `scope_ref`/`epistemic_objective`/`hypotheses`/`predictions`/`discrimination_requirements`/`methodology_constraints`
   - Calls `compile_from_payload` + `record(produced_by="DETERMINISTIC")` — NO inner Intent re-attribution (Amendment A1)
   - Returns IntentResult with `duplicate` from PA4
3. **controller.py:** Switch to `EMIT_PARALLEL_REGIME_PROGRAM` with `proposed_by="DETERMINISTIC"`, linkage-only payload (no scope_ref, no rationale). Add pre-check skip + in-memory refused-set.
4. **test_c1_slot_ref.py:** Add `EMIT_PARALLEL_REGIME_PROGRAM` to AC-6's pinned vocabulary set.
