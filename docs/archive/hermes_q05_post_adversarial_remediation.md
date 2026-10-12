# HERMES Q-05 — POST-IMPLEMENTATION ADVERSARIAL REMEDIATION

**Date:** 2026-08-15 · **HEAD:** `d7931ec` (working tree; nothing committed)
**Scope:** closes the four findings of the independent post-implementation
adversarial review against the Q-05 package (substrate + persistence slice +
controller consumption), corrects the governance wording, and re-verifies.
Q-02 was NOT implemented; its design was revised (§7).

---

## 1. Findings and fixes

| # | Finding | Fix | Evidence |
|---|---|---|---|
| 1 | `classifications_digest` silently skipped malformed persisted rows — the Director would see "no classification" instead of "classification exists but is corrupt/unavailable", hiding evidence-integrity problems | Digest rewritten (v2 shape): `items` + `errors` + `integrity_status` ("OK"/"FLAGGED"/"DEGRADED"). Corrupt rows are DROPPED with an explicit diagnostic (`WRONG_ARTIFACT_TYPE`, `MALFORMED_METADATA`, `FORGED_IDENTITY`, `MISSING_CLASSIFICATION_ID`, `MISSING_REQUIRED_METADATA`, `INVALID_FAILURE_CLASS`) or SURFACED with recomputed values + an integrity flag (`MALFORMED_PERMITTED_ACTIONS`, `STORED_ACTIONS_MISMATCH`, `STORED_CONFIRMATION_MISMATCH`). No new authority, no event | `TestDigestCorruptionObservable` (6 fixtures: forged identity, wrong type, missing metadata, malformed action set, mixed valid+corrupt, determinism) + updated `TestDigest`/`TestControllerConsumption` |
| 2 | Class-specific citation targets (program constraints/predictions, ScopeBrief fields) resolved PRE-transaction — could they change between resolution and persistence? | **Option A proven**: `research_programs` has no UPDATE/DELETE path (immutability structural; versions SUPERSEDE as new rows), `scope_briefs` are frozen with no UPDATE path in src. Citation targets cannot change post-record. The mutable parts (task binding, evidence ownership, one-shot identity) stay INSIDE `BEGIN IMMEDIATE`. | `TestResolverSnapshotImmutability` (4 fixtures: frozen target across supersession, historical integrity, stale program ref fails closed, stale brief ref fails closed); proof in §3 |
| 3 | IDR-036/037 used "Status: Ratified" while the independent review remains standing — collapsing operator adoption with independent verification | Governance model corrected everywhere: **IMPLEMENTED + TESTED / ARCHITECTURE ADOPTED BY OPERATOR / INDEPENDENT REVIEW PENDING**. Nothing is claimed INDEPENDENTLY VERIFIED or CLOSED. | IDR-036, IDR-037 status blocks; README index; design doc §13 |
| 4 | IDR-036 claimed "No roadmap change" after persistence was implemented early | Roadmap correction recorded: the Evidence Ladder remains deferred; Q-05 advisory persistence was implemented EARLY as preparatory infrastructure so the future REFUTED write path consumes an existing ratified contract. Architecture not structurally expanded; implementation SEQUENCE changed. | IDR-036 §Context; design doc §13 |

Also carried forward from the prior audit (still enforced by tests): the D8
advisory boundary (a classification can never be cited as claim evidence —
Fix A, `_dereference_artifact_ref` closed vocabulary) and the F2 recompute
rule (digest derives `permitted_actions` and `requires_human_confirmation`
from the ratified substrate, never from stored metadata).

---

## 2. Digest corruption handling (Issue 1 — the model)

    classifications_digest(rows)
        ├── valid classifications ──────────────► items (permitted_actions +
        │                                          requires_human_confirmation
        │                                          RE-COMPUTED from the class)
        ├── forged / malformed / wrong-type ────► errors (dropped, diagnosed;
        │                                          never a recommendation)
        └── stored-derived disagreement ────────► surfaced WITH integrity_flags
                                                   (corruption reported, values
                                                   recomputed)

`integrity_status`: **OK** (no errors, no flags) / **FLAGGED** (only
stored-derived disagreements) / **DEGRADED** (at least one dropped row). The
invariant: persisted corruption is observable and never silently disappears;
a malformed row is never turned into a valid advisory recommendation.

---

## 3. Resolver snapshot / immutability proof (Issue 2 — Option A)

**Snapshot model.** `record()` runs the substrate with real resolvers
pre-transaction; the class-specific citation targets it resolves are:

| Citation target | Resolver | Immutability contract |
|---|---|---|
| program constraints (`hypothesis:<H>:falsification_condition`, `methodology_constraint:<i>`) | `_constraint_resolver` → `_resolve_program` (project-scoped, by id or content-hash) | `ResearchProgramRepository`: "No UPDATE/DELETE path exists at all — immutability is structural" (class docstring); versions supersede as NEW rows (E9 head-only) |
| mechanism/prediction (`prediction:<P>`) | `_mechanism_resolver` → same program row | same |
| ScopeBrief field | `_scope_field_resolver` → `scope_briefs.scope_text_json` (project-scoped) | briefs frozen (`frozen_at`); no UPDATE path in `src` |

**Why a citation cannot change between validation and persistence:** the
resolved rows are structurally immutable — nothing in the repository can
mutate a program or brief row after insertion, so a pre-transaction
resolution against them is stable for the lifetime of the write. The mutable
parts (producing task exists/same-project/RUNNING, evidence ownership via
two-hop `derived_from`) are re-verified INSIDE `BEGIN IMMEDIATE` — the
A2-02 TOCTOU closure. Supersession creates new rows and never touches the
cited one, so an old classification stays valid for the old version (tests:
program target byte-identical across supersession; old classification
unchanged; new classification can still cite the superseded version). Stale
references (foreign program, foreign/missing brief field) fail closed at the
resolver — nothing is ever persisted against a target the resolver did not
see in that snapshot.

---

## 4. Governance status (Issue 3 — exact vocabulary)

Until the independent Q-05 review has actually run:

    IMPLEMENTED + TESTED
    ARCHITECTURE ADOPTED BY OPERATOR
    INDEPENDENT REVIEW PENDING

After the independent review passes (future):

    IMPLEMENTED + TESTED
    INDEPENDENTLY VERIFIED
    RATIFIED / CLOSED

Updated: IDR-036, IDR-037 (status blocks now carry the three-part model and
explicitly disclaim INDEPENDENTLY VERIFIED/CLOSED), README IDR index
("OPERATOR-ADOPTED … INDEPENDENT REVIEW PENDING"), and the Q-05 design doc
§13 (roadmap correction + governance).

---

## 5. Test matrix (this remediation round)

| Suite / fixture | Count | Covers |
|---|---|---|
| `TestDigestCorruptionObservable` (new) | 6 | Issue 1: forged identity, wrong artifact type, missing required metadata, malformed permitted-action set (surface+flag), mixed valid+corrupt (valid visible + corruption reported), deterministic same-state digest |
| `TestResolverSnapshotImmutability` (new) | 3 | Issue 2: frozen program target across supersession (byte-identical program + classification rows), historical integrity of old-version citations, stale/foreign program ref fails closed, stale brief ref (foreign + absent field) fails closed |
| Updated `TestDigest` / `TestControllerConsumption` | 8 | v2 digest shape: OK/FLAGGED/DEGRADED statuses, errors surfaced, controller read-only + empty + post-tick still read-only |
| Prior audit regressions (unchanged, still green) | — | Fix A (classification never citable as evidence, closed dereference vocabulary), F2 recompute (both derived fields + tamper flags) |

## 6. Verification (fresh, 2026-08-15)

| Metric | Result |
|---|---|
| Full suite | **993 passed** (baseline 984 + 6 digest + 3 immutability), 0 failed, 0 errors |
| pyright (`uvx pyright src`) | 0 errors, 0 warnings |
| Targeted Q-05 suite (`test_q05_persistence.py` + `test_failure_classification.py`) | all pass |
| Structural | no new tables/events/intents/scheduler/authority; digest and resolvers remain pure/read-only; no write path added |

Authority re-asserted (§8 of the review): a classification still cannot
create a task/program/hypothesis, mutate ScopeBrief, change evidence state,
bypass the Gateway, alter budgets/scheduler, override the Director, or become
evidence. Integrity: forged ids/hashes/versions/evidence refs, wrong-project
evidence, classification-as-evidence, and stale targets all fail closed.
Historical integrity: a new classifier version is a new derived row; old rows
stay byte-identical; no in-place reclassification.

## 7. Q-02 design revision (design only — NOT implemented)

`hermes_q02_epistemic_roi_design.md` rewritten (353 lines, 17 sections) to
resolve the mixed authority model: **Model B chosen** (versioned deterministic
controller policy via an ActionEvaluation **EligibleTask mode**, option-C
deterministic proxies from existing obligations, LLM quarantined to the
Director-visible advisory surface, the nine required acceptance tests, exact
precedence and versioning defined). Verdict: **DESIGN READY FOR
IMPLEMENTATION** — implementation still waits for the Q-05 independent
review + closure. No Q-02 code, no scheduler modification.

## 8. Current Q-05 status — CLOSED

    IMPLEMENTED + TESTED
    ARCHITECTURE ADOPTED BY OPERATOR (IDR-036 / IDR-037)
    ADVERSARIALLY REVIEWED (2026-08-15, at operator instruction — see §10)
    RATIFIED / CLOSED (2026-08-15 — the operator accepted the §10 audit as
    the Q-05 closure gate)

Q-05 is not claimed INDEPENDENTLY VERIFIED by an external party; the §10
record states precisely who ran the review. Closure is by operator authority. The closure-gate
package `hermes_researchsourceprovider_closure_gate_package.md` is scope-
pinned to its historical HEAD `55c35c2` (§A1): a verdict there certifies the
provider slice at that commit only and does NOT cover `d7931ec` or the Q-05/
Q-02 changes; a rerun at a new HEAD requires a NEW package.

## 9. STOP — scope discipline (unchanged)

Q-09, Q-04, Q-07, CV-01, TRIZ, Obsidian, 4S: NOT started. Q-02: design only.
Nothing committed; the working tree holds all remediation for review.

---

## 10. Adversarial review at the remediated HEAD (2026-08-15)

Executed per operator instruction as the closing review. **Reviewer
provenance:** performed by the implementation agent in a fresh-eyes posture
against the committed HEAD — re-reading the code, running probes not in the
suite, re-verifying numbers. It is an adversarial audit, NOT a claim of
external human independence; the operator is the authority on whether it
satisfies the closure gate for their process.

**Reviewed HEAD:** `92423e1` (remediation commit). **Result: two findings,
both remediated and regression-locked in a follow-up commit `3438231`.**

| # | Severity | Finding | Fix |
|---|---|---|---|
| F3 | MEDIUM | A non-list `evidence_refs` (bare string) iterated per-character, surfacing garbage refs (`['1',':','a','a',…]`) with NO flag and status OK — corrupt data presented as valid evidence | `MALFORMED_EVIDENCE_REFS` flag (also fires when a `failure_classification:` ref is claimed as evidence — D8); surfaced refs are emptied, status FLAGGED |
| F4 | LOW | A row with no `content_hash` surfaced with `failure_class_ref: None` and status OK, yet can never satisfy the D3 dereference contract | `MISSING_CONTENT_HASH` flag, status FLAGGED |

**Post-remediation re-verification (fresh):** full suite **997 passed** (993 +
4 regression fixtures), 0 failed; `uvx pyright src` **0 errors / 0 warnings**;
the original F3/F4 probes re-run and closed; controller read-only surface
unaffected; no new write path/authority/table.

**Verdict: PASSED after remediation.** Q-05 (substrate + persistence slice +
controller consumption) survives the adversarial review at HEAD `3438231`.
**Operator acceptance recorded: the operator accepted this audit as the Q-05
closure gate on 2026-08-15 — Q-05 is RATIFIED / CLOSED (see §8 and
IDR-036/IDR-037).** The record above states exactly who ran the review and
under what instruction; INDEPENDENTLY VERIFIED by an external party remains
unclaimed.
