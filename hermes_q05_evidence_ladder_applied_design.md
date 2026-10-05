# HERMES RESEARCH — EVIDENCE LADDER APPLIED SIDE
## DESIGN GATE (design only; NOT implemented)

**Status:** DESIGN GATE COMPLETE — the APPLIED side of the evidence ladder
(the transition EXECUTOR that consumes `EVIDENCE_TRANSITION_PROPOSED`
records with ratified refs and actually changes evidence state) is **DESIGN
READY FOR IMPLEMENTATION**. No code in this task. The design is
architecture input for a future phase, building on the ratified IDR-041
admission (the proposal-shaped EVIDENCE_TRANSITION validator) and the
ratified handoff (IDR-040 §3.5 + IDR-041 AC-4).

**HEAD reconciled against:** `ccabbad` (AC-5 consumer), full suite
**1215 passed**, pyright `src` **0 errors**.

---

## 1. Role and gate question

The gate question: *how do ratified branch transitions actually change
evidence state?*

IDR-041 wired the EVIDENCE_TRANSITION ADMISSION — the validator enforces
the transition shape and the AC-4 ratification-ref contract, emits
`EVIDENCE_TRANSITION_PROPOSED`, and deliberately never APPLIES (changing
evidence state is the future Evidence Ladder's authority). This design
specifies that authority: the deterministic executor that consumes the
admitted records (and the ratified Q-05 classification / ladder-obligation
facts) and writes the new evidence state, atomically with
`EVIDENCE_TRANSITION_APPLIED`.

The answer this design defends: **the APPLY is the ladder's only write, and
it is driven by ratified facts — never by an agent's bare claim.** The rung
of a hypothesis advances when its program's obligations complete
(obligation-driven climbs) or when a ratified falsification record /
human-approved transition exists (the any → REFUTED terminus). The state is
DERIVED from those ratified sources (F2) and re-derivable after any crash.

---

## 2. Reconciliation against the live repository (verified facts)

| Fact | Verified at HEAD `ccabbad` |
|---|---|
| No evidence-state substrate exists | no evidence table, no EvidenceRepository (the v6 §10 ladder is Phase 0); `EvidenceTransitionApplied` is never emitted anywhere |
| Ladder rungs are per-HYPOTHESIS | `ladder_target` (SUPPORTED / ROBUST / REPLICATED) lives in `research_programs.hypothesis_json`; `LADDER_OBLIGATIONS` (`programs.py:119`) maps each target to its artifact/gate obligation sets |
| The admission is proposal-shaped | the IDR-041 validator emits `EVIDENCE_TRANSITION_PROPOSED` (deterministic `tr_<hash>` id, idempotent), never APPLIES; shape: evidence ref, ratified states, AC-4 ref |
| The ratification facts exist | `ClassificationActionDecision` (APPROVED/REJECTED, one-verdict); the shared `_resolve_ratified_proposal` (AC-4) enforces the binding |
| The falsification fact exists | the ratified Q-05 classification (advisory metadata) with D3 dereference; REFUTED is the ratified terminus (v6 §10.2 "any → REFUTED") |
| Obligation completion exists | `program_requirement_satisfactions` (recorded per requirement when evidence tasks complete — the gateway/controller write path) |
| The state machine discipline exists | task statuses are a ratified ladder (NO_SIGNAL/recovery, IDR-029) with atomic, idempotent, crash-safe writes — the pattern to mirror |

---

## 3. The substrate — where evidence state lives

**Subject:** the evidence state is PER (program, hypothesis) — the ladder
rung of the hypothesis — not per artifact. The EVIDENCE_TRANSITION's
`evidence_artifact_ref` is the FALSIFYING evidence cited by the transition
(the same citation discipline as the Q-05 classification), not the state
owner.

**Record:** a new immutable, versioned `evidence_ladder_state` row per
(program_id, hypothesis_ref) — the `research_programs` / `scope_briefs`
pattern: content-derived or sequential identity, `UNIQUE (program_id,
version)`, head-only supersession (`supersedes_id` with a self-supersede
CHECK), no UPDATE/DELETE path. Each row stores the DERIVED rung
(`SUPPORTED` / `ROBUST` / `REPLICATED` / `REFUTED`), the transition id that
produced it, and the ratified inputs it consumed.

**Derived, never trusted (F2):** the CURRENT rung is never read from a
stored field alone — it is recomputed from the ratified sources: the
program's compiled obligations (which rung the obligations certify),
the recorded obligation satisfactions (what has completed), the recorded
classifications (which hypothesis was falsified), and the applied
transitions. The stored row is the CACHE of that derivation, not its
authority — a tampered row re-derives to the true rung.

## 4. The executor — the APPLY pass

A deterministic controller pass (the `_dispatch_pass` pattern) that runs
before/with dispatch and writes rung transitions. Two advance drivers:

1. **Obligation-driven climbs (SUPPORTED → ROBUST → REPLICATED).** The
   ladder advances when the program's obligations for the target complete —
   the satisfaction records already exist (`program_requirement_satisfactions`).
   The pass derives the highest rung whose obligation set is satisfied and
   writes the new rung atomically with `EVIDENCE_TRANSITION_APPLIED`
   (correlation = a deterministic transition id derived from the
   satisfactions). No agent intent, no ratification needed — the completed
   obligations ARE the ratification.

2. **Falsification-driven REFUTED (any → REFUTED).** The terminus is only
   reached on DECISIVE falsification, and only from ratified inputs:
   - an APPROVED classification-action transition (a REJECT_BRANCH proposal
     with an APPROVED decision — the AC-4 binding, live when the authority
     model routes branch rejection to human confirmation), OR
   - a ratified Q-05 classification of the falsifying evidence (the D3
     dereference + digest-valid row) — the consumed record the Q-05
     substrate was built for.
   The pass consumes `EVIDENCE_TRANSITION_PROPOSED` records whose
   ratification re-verifies, and writes REFUTED atomically with
   `EVIDENCE_TRANSITION_APPLIED`. REFUTED is TERMINAL: no transition may
   leave it (already enforced at admission).

**The admission stays the gate:** the APPLY re-runs the same AC-4 checks
(shared `_resolve_ratified_proposal`) and the shape checks at apply time —
a proposal whose ratification vanished or whose state is stale is skipped
with a note, never applied. The APPLY never trusts the proposal payload
alone; it recomputes the current rung and refuses a no-op or a backwards
move.

## 5. Authority boundary

- **CAN** write the ladder rung: the APPLY pass is the ladder's ONLY write
  path — atomic `evidence_ladder_state` rows + `EVIDENCE_TRANSITION_APPLIED`
  events, driven by ratified inputs.
- **CAN** re-verify at apply time: the AC-4 binding and the shape checks
  re-run at APPLY, never trusting the admission alone.
- **CANNOT** be invoked by agents: no intent kind applies a transition —
  agents propose (EVIDENCE_TRANSITION), the deterministic pass applies.
- **CANNOT** move backwards or reverse REFUTED: the rung is monotonic and
  the terminus is terminal. A re-falsification is a NEW ladder lifecycle
  (a new hypothesis/record), never a revert of an applied REFUTED.
- **CANNOT** write evidence state from a bare agent claim: an obligation-
  driven climb requires the recorded satisfactions; a REFUTED requires a
  ratified classification or an APPROVED transition (AC-4).
- **CANNOT** bypass the Q-05 substrate: the classification input is the
  digest-valid, D3-dereferenced record — the same fail-closed discipline as
  the advisory surfaces.

## 6. Determinism and recovery

- **Idempotent:** every APPLY derives a deterministic transition id from
  its ratified inputs (the satisfactions hash / the proposal id), so a
  re-run applies nothing new — the same ladder derives the same rung.
- **Replay-safe:** the current rung is DERIVED, not stored-authoritative, so
  a crashed pass re-derives and applies only the delta that was not yet
  recorded; a mid-apply crash either committed atomically (row + event) or
  rolled back — never a half-state.
- **Deterministic order:** the pass iterates programs/hypotheses in
  sorted order and applies first-visit-wins; the same stored facts ⇒ the
  same resulting ladder (the recovery-safety discipline already proven for
  the Q-02 ordering).
- **Tamper-fail-closed:** a tampered rung row re-derives to the true rung;
  a forged proposal whose ratification does not re-verify is skipped with a
  note; a forged classification is dropped by the digest.

## 7. Deferred (explicitly NOT in this design)

- The substrate itself (the `evidence_ladder_state` table + repository)
  lands WITH the executor in the future phase — this design specifies the
  contract, not the migration.
- The Q-05 REFUTED record write path (the classification → falsification
  record) is the same future phase; the APPLY consumes whatever record
  phase lands it.
- No UI / no new event kinds beyond the ratified
  `EVIDENCE_TRANSITION_APPLIED` catalog member.
- The authority-model question (routing branch rejection to human
  confirmation so REJECT_BRANCH approvals become reachable) is a SEPARATE
  decision, explicitly not decided here.

## 8. Hostile self-review of THIS design

- **Could an agent fake a climb?** No — obligation climbs require the
  recorded satisfactions (written by the gateway/controller from real task
  completion); the APPLY derives from them, never from the payload.
- **Could a forged proposal apply a REFUTED?** The APPLY re-runs AC-4 and
  the shape checks; a proposal whose APPROVED decision, proposal, or class
  binding does not re-verify is skipped. The residual boundary is the
  documented one (DB-write access ⇒ the audit itself is rewriteable).
- **Is REFUTED-terminal too strong?** No — v6 §10.2 is "any → REFUTED" on
  decisive falsification; a terminal REFUTED is the falsification discipline
  (a revived hypothesis is a NEW hypothesis with its own ladder lifecycle).
- **Does the derived-rung rule fight idempotency?** No — the derivation is
  deterministic, so cache and derivation agree; a tampered cache re-derives
  and the next APPLY writes the corrected row (self-healing, not silent).
- **Why a pass, not an intent?** Because applying is the ladder's authority
  (a deterministic write), and the ratified input is already an intent or a
  recorded fact — an apply-INTENT would double the authority surface. The
  pass mirrors the task-status recovery ladder's discipline (IDR-029).

## 9. Acceptance criteria for the future implementation phase

AC-1 — an obligation-satisfied program advances SUPPORTED → ROBUST →
REPLICATED deterministically and idempotently, each advance emitting one
`EVIDENCE_TRANSITION_APPLIED` with a deterministic correlation id.
AC-2 — REFUTED is applied only from a re-verified ratified input (an
APPROVED REJECT_BRANCH proposal or a digest-valid classification); a forged
or stale proposal/classification applies nothing (note + skip).
AC-3 — REFUTED is terminal: no applied REFUTED is ever reverted, and no
admission from REFUTED passes (already admission-enforced).
AC-4 — the current rung is fully re-derivable from ratified sources after a
crash mid-apply (multi-tick crash test: deterministic across the crash —
the recovery-safety proof pattern).
AC-5 — the APPLY never writes from a bare payload: every write traces to a
ratified source (satisfaction records / AC-4 binding / digest-valid
classification).

## 10. Verdict

**DESIGN READY FOR IMPLEMENTATION — subject to the operator's ratification
gate.** The APPLIED side is the ladder's one deterministic writer: ratified
inputs in, atomic rung + event out, derived-and-recoverable state, no new
agent authority, no bypass of the admission or the Q-05 substrate. No
implementation in this task.
