# Red-Team Audit — Operator Loop (Attack the Logic)

**Audited:** 2026-08-15
**Target:** the shipped operator loop — `resolve_human_gate`, gate parking,
the scheduler lease + heartbeat refresher, the mode state machine, operator
credentials, and the recovery ladder — at HEAD `e53632f`.
**Method:** adversarial code reading + live probes against real SQLite
(in-memory and file), including failure injection (fenced-write loss,
event-append crash, mode-write failure) and a second pass with the same
lens over the proposal-decision surface.
**Result:** 1 P2 defect found and REMEDIATED (F1); 3 minor findings found
and REMEDIATED (F2, F3, F6, F7); 1 informational note (F4); 1 accepted
exposure (F5). No P0/P1.

## Executive summary

The loop holds fail-closed where it matters: verdicts are atomic, the
one-verdict rule survives status tampering, the escape hatch is scoped to
post-park invalidation only, and a lost lease cannot be written through.
The one real defect found is a class of **silent failure**: the operational
mode transitions were wrapped in `contextlib.suppress`, so a failed write
left the project in a state that contradicts its gates — permanently
parked with no gate to resolve, or a waiting gate under ACTIVE mode (wave
dispatches past an unapproved gate). Both directions are now self-healing
and the failures are surfaced. Details below.

---

## F1 (P2 — REMEDIATED in this audit): silent mode-transition failure

### Attack

Two `contextlib.suppress(Exception)` blocks hid the only two mode writes:

1. **Resolve side** — after the final gate verdict commits, the ACTIVE
   write is suppressed. Probe: class-level injection of a failure into
   `ProjectRepository.transition_mode` after a legit approve produced:

   ```
   resolve: {'task_id': 'gate-1', 'verdict': 'APPROVED', 'rejected': False}
   gate status: TaskStatus.SUCCEEDED
   mode after suppressed failure: OperationalMode.AWAITING_HUMAN
   next tick idle: mode:AWAITING_HUMAN | dispatched: []
   next tick idle 2: mode:AWAITING_HUMAN
   ```

   The project is **permanently parked**: zero WAITING_HUMAN gates remain,
   so nothing can be resolved, and the mode check refuses every tick. The
   only escape was a manual `hermes resume` — which the operator has no
   reason to know is needed, because the failure was silent.

2. **Park side (worse direction)** — if the AWAITING_HUMAN write fails
   while parking, the gate is WAITING_HUMAN under ACTIVE mode; the next
   tick's dispatch loop finds the post-gate tasks eligible and executes
   them **past the unapproved gate** — a gate bypass, not just a stall.

Reachability is the same window the fencing was built for: a lease
reclaimed between two fenced writes (the verdict commit and the mode
write are separate transactions), a terminal-lifecycle race, or any DB
transient. The suppress converted those into silent, contradictory state.

### Fix (committed as part of this audit)

- The mode is now **derived from gate state, not imperative**: every tick
  self-heals both directions — AWAITING_HUMAN with no WAITING_HUMAN gate →
  ACTIVE (resume); ACTIVE with a WAITING_HUMAN gate → AWAITING_HUMAN
  (stop the wave). Safe because AWAITING_HUMAN is exclusively gate-derived
  (no manual path sets it; `hermes pause/resume` only touch PAUSED/ACTIVE).
- Both mode writes now surface failures on the notes channel instead of
  swallowing them.

### Verification

- `test_11_audit_final_verdict_mode_write_failure_surfaces_and_self_heals`
  — verdict commits, failure surfaces as a note, next tick self-heals to
  ACTIVE and resumes.
- `test_11_audit_park_mode_write_failure_self_heals_wave_stops` — gate
  parks under ACTIVE mode, failure surfaces, next tick re-derives
  AWAITING_HUMAN and does NOT dispatch the eligible task after the gate.

---

## F2 (P3): operator_id existence timing oracle

`OperatorCredentialRepository.verify` returns False immediately for an
unknown operator_id (one SELECT) but spends ~0.1s (PBKDF2, 210k
iterations) for a known id. An attacker with a stopwatch and network
access to `hermes gate resolve` can enumerate valid operator_ids.
Operator ids are usernames, not secrets, so impact is minor — but the fix
is trivial: precompute a fixed dummy PBKDF2 for the unknown-id path so
both branches cost the same.

## F3 (P3): oversized `rationale` surfaces as a generic TRANSITION refusal

The verdict payload (`rationale`) is capped by the event validator (F-04,
4096 bytes). A rationale over the cap makes the whole verdict fail with
`code=TRANSITION` and a raw validator message — the operator cannot tell
"rationale too long" from "state machine refused". Improvement: pre-validate
the rationale length in `resolve_human_gate` and return a specific refusal
code/detail.

## F4 (P3): stored iteration count is attacker-influenced

The self-describing hash carries its own iteration count, so a DB writer
could set a huge count and turn every `verify` into a DoS. A DB writer can
already do far worse (rewrite the hash to match a chosen token), so this
is informational only — noted for completeness.

## F5 (accepted, documented): `--token` on argv

Process-list exposure on a shared host. Accepted for a single-operator
lab tool; tracked in the P2 governance record with the same status.

---

## Attacked and held (no finding)

- **One-verdict rule under status tamper** — the journal is consulted
  before the mutable status; a WAITING_HUMAN status tampered back after a
  legit resolve cannot yield a second verdict (`ALREADY_RESOLVED`).
- **Escape-hatch scope** — the verdict hop only bypasses the F-10
  dependency check; a gate that never parked (dep failed BEFORE
  eligibility) is refused `NOT_WAITING`. The hatch cannot admit a gate.
- **Lost-lease writes** — every post-claim write is generation-fenced;
  the refresher's lease refresh is owner-guarded on the raw connection.
- **Horizon cliff** — a >horizon handler is discard-and-re-execute: B
  re-executes exactly once (attempt 2, one output); A's late commit is
  refused by the IDR29-02 binding guard (the fence is the backstop).
- **Verdict atomicity** — crash injection at the final event append rolls
  back the entire verdict (zero journal rows).
- **Lock discipline** — `resolve_human_gate` and `record_operator_decision`
  both refuse `LOCK` when another controller holds the lease; the lock row
  is cleared on release.
- **Determinism** — verdict event order and Q-02 ordering are fixed and
  tested; no wall-clock or row-order dependence in the verdict path.

## Second pass — proposal-decision surface (F6, F7)

### F6 (P3 — REMEDIATED): one-verdict check raced outside the append transaction

`_validate_resolve_classification_proposal` (and the S16 intake) read the
prior decision in autocommit, THEN appended in a separate transaction —
the events table has no uniqueness constraint on (event_type,
correlation_id). Live probe with two connections racing contradictory
verdicts on one proposal:

```
A: ('ok', False)
B: ('ok', False)
decision events: 2
   APPROVED
   REJECTED
```

Both verdicts landed on the journal. The sanctioned controller path
(`record_operator_decision`) is lease-serialized, so the race needs two
concurrent direct gateway callers — but the gateway is the deterministic
authority for intent admission, and the one-verdict rule is its contract.
Fix: a new `_decision_append_transactional` runs the prior-read and the
append in ONE `BEGIN IMMEDIATE` transaction (the second racer blocks on
the write lock, then sees the first verdict and refuses). Regression test
`test_f6_one_verdict_race_closed` reproduces the exact two-thread race
and asserts exactly one decision event.

### F7 (P3 — REMEDIATED): S16 scope-review verdicts had no proof-of-humanity

`record_scope_review_decision` was the only human-verdict surface without
an operator credential — no token verification, no gateway existence
check — while A4 requires every operator verdict to carry a ratified
credential. The verdict itself is ratification metadata (nothing executes,
no brief amendment), but the A4 principle was violated by the surface
that records the most consequential-looking decisions. Fix: the surface
now requires `operator_id` + `operator_token` (verified at the controller,
existence re-checked at the gateway, like `record_operator_decision`),
and the recorded payload cites the operator. Tests updated; a refusal test
proves an unratified call writes nothing.

### Attacked and held on this surface

- **Rationale cap with a SPECIFIC refusal** — the gateway caps rationale
  at 2000 chars with `MALFORMED_PAYLOAD` (the F3 counterpart already
  existed here; F3 fixed the same gap on `resolve_human_gate`).
- **Lease discipline** — `record_operator_decision` /
  `record_scope_review_decision` refuse `LOCK` while another controller
  holds the lease; nothing is written on refusal.
- **Gateway re-verification** — the gateway re-checks the operator
  credential exists (the token never travels in an intent/event).
- **F2 recompute** — decidable proposals are recomputed from the cited
  classification's class, never from stored admission state; corrupt or
  undereferenceable citations fail closed.
- **Idempotent duplicates** — an identical re-record is `duplicate=True`
  (no second event); a contradictory one is refused.

## Recommended next steps (ranked)

1. Constant-time unknown-operator verify (F2) — DONE (dummy PBKDF2 branch
   in `verify`); the same work-burn should be considered for the gateway's
   `exists()` if it ever sits on a network boundary.
2. Pre-validate `rationale` length with a specific refusal (F3) — DONE
   (`RATIONALE` code on `resolve_human_gate`; the gateway surfaces already
   had their own caps).
3. F4 (stored iteration count) and F5 (argv token) remain accepted/
   informational — revisit if the tool leaves the single-operator lab
   host.
4. Next surface to probe with the same injection lens: the evidence
   ladder APPLY path (`EVIDENCE_TRANSITION` / terminus writes) — it has a
   state machine with more moving parts than the decision surfaces.
