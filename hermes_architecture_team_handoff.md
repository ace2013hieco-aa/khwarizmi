# HERMES Five-Fundamentals — Architecture-Team Handoff

**Date:** 2026-08-20
**Repo:** `ace2013hieco-aa/khwarizmi-research` @ `main` = `3a1e890`
**Package status:** DESIGN-COMPLETE, REVIEWED, **NOT RATIFIED**. Nothing here
is implemented; nothing changes runtime behavior.

> **Ratification update (2026-08-20, additive):** the package was
> subsequently RATIFIED by operator ratification —
> `hermes_architecture_ratification.md` (Decisions 1–3 recorded;
> architecture frozen). The status line above is the historical
> pre-ratification record and is preserved unchanged. This document is the
decision packet the architecture team needs to ratify (or reject) the
package.

---

## 0. What you are being asked to decide

The five-fundamentals blueprint proposes five capabilities for the research
controller. It went through a full adversarial audit (attacks A–R) and four
independent review passes. Its open questions §19 named four candidate
extensions — **C1, C4, C5, C6** — that "should probably become architecture
after their own five-stage loops." **This package is those four design
gates, written, cross-checked, and independently adversarially reviewed.**

You are being asked to:

1. **Ratify (or reject) the blueprint** — the five fundamentals + corrected
   audit tally.
2. **Rule on one open design decision** — C5 §2.2 (below-dimensions priority
   position vs. Q-02 §11.5's literal reading). See §5.
3. **Approve each design gate** for implementation (each is independently
   gated on your approval; none auto-implements).

You are **not** being asked to approve any code. No production code was
edited in this package. Implementation is a later, separately-chartered
phase.

---

## 1. Package inventory (all on `main`)

| Artifact | File | Commit | Status |
|---|---|---|---|
| Five-fundamentals blueprint | `hermes_five_fundamentals_blueprint.md` | `783831b` | Reviewed, corrected, **unratified** |
| C1 `slot_ref` design gate | `hermes_c1_slot_ref_design_gate.md` | `7eab07b` | DESIGN, reviewed |
| C4 exploration-floor design gate | `hermes_c4_exploration_floor_design_gate.md` | `486c5dc` | DESIGN, reviewed |
| C5 Director-priority design gate | `hermes_c5_director_priority_design_gate.md` | `4b3c2b4` | DESIGN, reviewed |
| C6 convergence-diagnostic design gate | `hermes_c6_convergence_diagnostic_design_gate.md` | `9765ecf` | DESIGN, reviewed |
| Cross-check remediation (substrate fix) | C4/C5/C6 | `e3091e8` | applied |
| Adversarial-review remediation | C1/C4/C6 | `4554a27` | applied |
| C5 TTL remediation | C5 | `3a1e890` | applied |

Review evidence (findings tables, one per gate):
`C:/Users/Ali Zoghi/gate_review/{c1,c4,c5,c6}_findings.md`.

---

## 2. The blueprint — corrected audit tally

The blueprint's adversarial audit originally claimed **9 solved outright /
5 partial / 4 conditional**. A transcript-verified re-grade (blueprint §27,
2026-08-19) **retracted the unverified 9/5/4 verdict** and downgraded five
attacks whose cited defenses turned out to be *deferred subsystems, not
implemented ones*:

- **G** (S5 invalidation cascade) — deferred to the reconcile loop (P3), not built.
- **E** (budget ledger) — does not exist in `src/`.
- **Q** (ModelClient record/replay) — no such class in `src/`.
- **F, M** (refuted-registry screen / S7) — absent from `src/`.

**Corrected tally (blueprint §27.2):**

| Category | Count | Attacks |
|---|---|---|
| Solved outright | **5** | D, I, N, O, R |
| Solved partially | **10** | B, C, E, F, G, H, J, K/L, M, Q |
| Solved only if candidate extensions land | **3** | A + the K/L residual |

**What survives the correction:** no attack exposes a conflict with a
ratified invariant. The central claim holds — **the five fundamentals
introduce no new admission path; every entry is a proposal through the
existing gateway.** What the correction removed was overstatement: several
"current defenses" are deferred, not implemented, and the package is honest
about that (see §6, open dependency).

---

## 3. The four design gates — verdicts

Each gate resolves one blueprint §19 open question into a decidable
contract with acceptance criteria. Each was independently adversarially
reviewed against live source (findings files cited above). **All four:
HOLDS WITH CAVEATS.** No gate FAILED; no gate is unqualified.

### C1 — `slot_ref` design-concept identity (resolves §19 Q2)
- **Verdict:** HOLDS WITH CAVEATS — 4/4 load-bearing claims confirmed, 0 contradicted.
- **Shape:** one optional field on `HypothesisSpec`; Director assigns,
  validator checks a closed per-project slot vocabulary; content-addressed
  WITH the program (a slot change is a contract change); E6 check surface.
- **Key verified fact:** the AC-1 identity hazard is real — `canonical_json`
  serializes `None` keys, so a naive `"slot_ref": None` would rehash every
  existing program. The gate's mitigation (emit only when non-None) is
  correct and sufficient.
- **Caveat for the team:** §4.3 rules an **append-only slot vocabulary over
  the full supersession history**, which refines blueprint §21 F-B's "must
  already exist in the supersession chain" wording. The refinement is
  defensible (the live-chain-only reading would defeat the blueprint's own
  F6 resurrection-screening payoff) and is transparently flagged in §7.1 —
  but **ratify the full-history reading explicitly**, don't inherit it silently.

### C4 — exploration floor (resolves §19 Q3)
- **Verdict:** HOLDS WITH CAVEATS — 11 confirmed, 1 contradicted (fixed).
- **Shape:** a versioned clause in the Q-02 ordering policy: one reserved
  slot (last position) to a non-leading trajectory; operates WITHIN the
  per-tick call cap; F-C decay/kill-switch (derived counter, no stored
  state); degenerate-to-baseline fallback.
- **Key verified fact:** the ratified `_task_ordering_key` is NOT modified;
  no scalar/weight/composite (attack D intact); never reads spent budget
  (attack O intact).
- **Caveat (fixed):** see §4 defect #1 — the C4↔C5 composition was one-sided.

### C5 — Director priority input (resolves §19 Q4)
- **Verdict:** HOLDS WITH CAVEATS — 2 confirmed, 2 contradicted (both fixed).
- **Shape:** a `director_only` proposal intent (`PROPOSE_DIRECTOR_PRIORITY`);
  3-value closed strength enum (ELEVATE/SUSTAIN/DEPRIORITIZE); trajectory-keyed,
  never task-keyed; per-policy-version ratification; supersession + operator
  revocation + TTL.
- **The core distinction survives the hardest attack:** C5's priority is an
  **admitted proposal record, NOT a stored field on tasks** — it threads
  Q-02 §14's rejection. Q-02 §18.2 itself carves out exactly this shape
  ("IF a ratified override mechanism is ever built … Q-02 itself must never
  introduce a priority field"). The "functionally a priority store" objection
  proves too much (it would forbid every append-only fact the ordering consumes).
- **Caveats (one fixed, one OPEN):** TTL semantics fixed (§4 defect #2);
  the §2.2 position is the **one open decision** (§5 below).

### C6 — convergence diagnostic (resolves §19 Q6)
- **Verdict:** HOLDS WITH CAVEATS — 10/10 load-bearing claims confirmed, 0 contradicted.
- **Shape:** a read-only `convergence` section of `reconcile_digest`
  (version 4→5): obligation coverage, rival status, open contradictions,
  mutation depth, floor exhaustion. `NOT_DERIVABLE` honesty discipline for
  absent sources; never-a-gate-input enforced by construction + structural fixtures.
- **Key verified fact:** the `NOT_DERIVABLE` for open contradictions is
  genuinely honest — `CONTRADICTION_DETECTED` exists only as an enum
  declaration with **zero emitters** in `src/`.
- **Caveats (fixed):** AC-5 now names the no-program shape; AC-6 pins
  named-key-only digest access; §7.5 enumerates the 6 concrete
  `digest_version == "4"` test pins the 4→5 bump will touch.

---

## 4. What the hostile review caught (and fixed)

The independent adversarial review (deleg_a790ff80, 2026-08-20) found three
real defects. All three are fixed and pushed. They are listed here because
they are the strongest evidence the review was genuinely hostile, not a
rubber stamp.

1. **C4↔C5 composition was one-sided (MAJOR, fixed `4554a27`).** The
   composition rules lived in C5 §5 only; C4 was silent on C5, and C5's
   "C4 §7.4" cross-reference was a misattribution. **Fix:** C4 now has §4.5
   mirroring C5 §5 verbatim; both gates cite each other. Composition is
   bidirectional.
2. **C5's TTL counter was ill-defined (MAJOR, fixed `3a1e890`).** "Eligible
   rounds since admission" derived from READY→RUNNING claim events — but
   zero-claim rounds emit nothing, so the counter would silently stall and
   priorities live longer than designed. **Fix:** §2.5 pins dispatch-round
   semantics (a dispatch round = a round with ≥1 persisted claim event;
   zero-claim rounds deliberately don't advance the counter because priority
   is inert there). §7.6 flags the calendar-round alternative.
3. **Minor citation/fixture gaps (fixed `4554a27`).** C1's E2/E3 citation
   ranges corrected (they live at 758/770, not in 401–465); C1 dual-consumer
   `_h_to_dict` note added; C6 fixture enumeration added.

---

## 5. THE ONE OPEN DECISION — C5 §2.2 priority position

This is the single decision the package cannot resolve on its own. It needs
your explicit ruling.

**The conflict.** Q-02 §11.5 (ratified, design-level) states the precedence
literally: *"ratified Director priority > epistemic policy > created_at/task_id
tie-break."* Q-02 §18.2 reaffirms: *"IF a ratified override mechanism is ever
built, it ranks above the policy."* But **C5 §2.2 places priority BELOW the
six epistemic dimensions** (above cost/created_at/task_ref) — the opposite of
the literal ratified contract.

**Option A — below-dimensions (C5 as designed).** Priority breaks ties among
epistemically-equal tasks; it never overrides an epistemic difference. A
HIGH-gap task of a non-prioritized trajectory still orders above a LOW-gap
task of an ELEVATE'd one.
- *Pro:* the literal reading, implemented, **IS attack C** — a priority that
  outranks the epistemic dimensions is a hidden scheduler. Below-dimensions
  is the attack-C-safe position.
- *Con:* it inverts a ratified design-level assertion.

**Option B — literal priority-over-policy.** Priority outranks the epistemic
dimensions, per Q-02 §11.5's letter.
- *Pro:* faithful to the ratified text.
- *Con:* requires **explicit attack-C risk acceptance on record** — you are
  knowingly admitting a scheduler-shaped authority above the epistemic ordering.

**The gate's position:** C5 designed Option A and flagged Option B as the
overrule path, but only with an explicit attack-C risk acceptance. A design
gate may refine a ratified design-level assertion only transparently and with
the refinement routed back for ratification — C5 did both. **So this is an
open decision, not a contract violation.** Rule on it explicitly; do not let
it be inherited silently in either direction.

---

## 6. Open dependencies the team should accept or sequence

From blueprint §19 Q14 and review finding F4 — these are honest partial
states, not defects:

- **Fundamental #3's preserve-and-mutate loop leans on two deferred
  subsystems:** the S5 invalidation cascade (deferred to the reconcile loop,
  P3) and the refuted-registry screen (S7, unimplemented). Until both land,
  failure localization is partial: Q-05 classification + Q-04 cone are real,
  but the invalidation cascade and the refutation screen are not. **Accept
  this partial operational state, or sequence P3/S7 ahead of the portfolio layer.**
- **C5/C6 consumption surfaces are P4-gated.** The Director RUNTIME is still
  a Phase-0 placeholder (`director.py` a 4-line stub, `reconcile.py` a 6-line
  stub). C5/C6 are designed against the ratified Director CONTRACT (v6 §13),
  but cannot be exercised until the agent runtime lands. **C4 (floor) is
  implementable against the controller alone; C5/C6 are P4-gated.** §19
  ordering should respect this.

---

## 7. What is explicitly NOT in this package

- **No implementation.** All four gates are DESIGN-status. Implementation is
  a later, separately-chartered phase, gated on (a) blueprint ratification
  and (b) per-gate operator approval.
- **No production-code edits.** The standing constraint (no production edits
  unless explicitly chartered) was honored throughout.
- **No new IDR.** Design gates are pre-architecture records in the Q-02 house
  format; the next IDR number (IDR-042) remains reserved/unused.
- **C2, C3, and GR4-reheat** stay "design experiments" per blueprint §21 —
  correctly not gated in this package. (The GR4 proposal
  `hermes_gr4_annealed_bridge_sampling_proposal.md` is a separate artifact,
  not yet committed.)

---

## 8. Recommended ratification sequence

1. Ratify the blueprint (five fundamentals + corrected 5/10/3 tally).
2. Rule on C5 §2.2 (Option A vs Option B) — §5 above.
3. Ratify C1's full-history slot-vocabulary reading explicitly (C1 §7.1).
4. Accept or sequence the §6 open dependencies (P3/S7, P4-gating).
5. Approve gates for implementation in dependency order: **C4 first**
   (controller-only), then **C1**, then **C5/C6** (P4-gated).

---

*Prepared from executed repository evidence at `main` = `3a1e890`. Every
claim above is traceable to a commit, a gate section, or a findings file.
No verdict in this packet was recorded from a subagent self-report without
independent verification.*
