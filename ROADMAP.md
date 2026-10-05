# ROADMAP — Step 4: the regime-axis (ICSS-v1) sequence + IDR-045

This file records the landed slice sequence and the close-out state for the
Step 4 regime-axis work; the binding charter lives with the orchestrating
operator. Design record: `docs/idr/IDR-044.md` (+ its S-R2 and close-out
addenda). Branches are local-only; no pushes.

- [x] **S-R1 — regime registry substrate** (LANDED, `step-4/s-r1`):
  `src/hermes/research/regimes.py` — pure, stdlib-only, deterministic;
  closed `REGISTRY` frozenset seeded with exactly the one ICSS-v1 axis
  entry the live claims path already assumes (`ICSS-v1:low-vol`); versioned
  `RegimeRef(id, version)`; classification-time-only `RegimeSnapshot`
  (post-outcome fields unrepresentable); closed
  `IN_REGIME`/`NOT_IN_REGIME`/`INDETERMINATE` verdicts with
  decision-interness. Fixtures: `tests/test_regimes.py`. Adversarial audit
  (`step-4/s-r1-audit`): PASS WITH CONDITIONS (C1→S-R2 mandatory, C2→next
  touch).
- [x] **S-R2 — wiring** (LANDED, `step-4/s-r2`, + its S-R2 addendum in
  IDR-044): the transition layer (`RegimeTransition` — versioned
  (id, regime_ref) pairs + timestamp/program/hypothesis context, closed
  response enum, cited evidence, `Literal["SIMULATED"]`-AND-`__post_init__`
  provenance; C1-safe `derive_transition` re-derivation) and all three
  waiting integrations: (a) `target_regime` registry validation (the
  free-string form no longer admitted — versioned form required,
  `UNVERSIONED_REGIME`/`UNREGISTERED_REGIME`; the blank guard retained;
  the EMIT_PARALLEL_REGIME_PROGRAM path compiles through the same wiring);
  (b) the failure-classification store's once-DEFERRED resolver wired to
  the registry (the ENVIRONMENT_MISMATCH write-path refusal lifted — the
  registered-tag discipline is live on both layers); (c) the claims
  `regime` dereference activated (`_make_resolver` resolves the dim live;
  hand-marked ADMITTED verdicts cannot evade the dim re-check). C2
  hardening (audit F-1/F-2) landed as typed-input refusals with codes.
  Fixtures: `tests/test_regimes.py` (+transitions), `tests/
  test_research_program.py` (+registry refusal rows), `tests/
  test_gateway.py` (registered-tag fixtures), `tests/test_q05_
  persistence.py` (asymmetry lifted + boundary forge dies), `tests/
  test_claims_write_path.py` (+live-dim rows).
- **CLOSE-OUT (Step 4 complete).** The regime-axis substrate is COMPLETE:
  the registry substrate (S-R1) and the wiring (S-R2) have landed, tested,
  and passed both adversarial audits (S-R1 audit: PASS WITH CONDITIONS,
  both conditions C1/C2 discharged in S-R2; S-R2 audit: PASS —
  `step-4/s-r2-audit`). Merge-to-main remains open and is not part of this
  close-out.
- [x] **IDR-045 — plan admission + provenance** (LANDED, `idr-045/implement@96c52e7`; ratified D1-A/D2-A, Q1=plan-once, Q7=keyed-otherwise; implement `96c52e7` + audit `idr-045/impl-audit@7695c0c` PASS; merge-to-main open): controller plan_admission_pass (ACTIVE-only, filtered head MAX(version) WHERE parent_program_id IS NULL — C1; build_task_plan+plan_to_payloads via per-payload ADMIT_TASK/DETERMINISTIC — C6; supersession leave-in-place+admit-new-DAG+observable no-op — C2) + Intent additive provenance (origin_kind/origin_ref/model_ref/run_id/prompt_template_version/charter_version — V1 records-never-authority with grep-guard, V3 reader-default "origin unrecorded", C5 per-field max lengths pre-validate_payload_size, V2 byte-identical default when non-default-absent; DIRECTOR sites carry origin_kind/origin_ref). Tests §3.6+§4.6 all green incl. B3C-child-head, revised-program disjointness, crash k-of-n, oversized-refusal, byte-identical default. Audit5 C1–C6 each closed with code (not recording). Follow-ons remain severable. Design record: `docs/idr/IDR-045.md`; audit: `docs/IDR45-impl-audit.md`.
- [ ] **Catalyst — B0 / B1 / A2** (CHARTERED, pending replies; per `CATALYST-ALIGNMENT-ROADMAP-ADDENDUM.md` — **that file is not tracked in this repo**; it exists only as an untracked working-tree document, so this bullet points at something no reader of the tree can open. Track it or strike the reference): B0 repositioning (docs/help-text only, DP1) + B1 break-it harness (scripts/, ≥8 scenarios, feeds A3) + A2 claims-safe wording sheet — all chartered, pending replies. DP1/DP2 + Ace inputs outstanding per the Catalyst brief (DP1 domain-neutral positioning; DP2 wedge — governed evidence synthesis / research integrity; A0 positioning/wedge record, corpus, embedding target, advisor, metric still outstanding). No implementation prompt issued until DP1/DP2 ratified.
- [ ] **S-R4 — downstream consumption** (DEFERRED-UNTIL-CONSUMER, per the
  Step-4 close-out): surfaces that consume resolved regimes. The trigger
  for picking S-R4 up is a production flow that needs transition records
  (i.e. a consumer that must persist or act on `RegimeTransition` rows);
  until such a flow exists, no S-R4 work is owed. When it is picked up it
  OWES: re-derivation everywhere (never consume a caller-built
  `RegimeTransition`/evaluation — re-derive from registry + snapshot, the
  C1/F-3/A2 precedent), and the owner-gate re-runs for whatever surfaces
  it touches.

- **Open decisions (IDR-045 close-out):** Q-pass follow-ups: none — Q1/Q3/Q7 all closed and now recorded in `docs/idr/IDR-045.md` §"Ratified open-questions and their answers" (Q3: no test asserts exact 4-key `IntentApplied` payload — V2/V3 byte-identical holds, evidence `docs/IDR45-Q37-evidence.md` §Q3; Q7: B3C filtered head `MAX(version) WHERE parent_program_id IS NULL`, child never steals plan — the *production* path is the inline filtered query in `controller._plan_admission_pass`, not `current_primary`, which has no production caller; corrected by MERGE-AUDIT-045 F4). Follow-on records: envelope/lease/stall/lifecycle/trace still unchartered (each needs its own IDR; envelope per-tick admission cap noted in audit5 §3 but not shipped; lease horizon per task, FAILED-dependent stall handling, REPORTING→COMPLETED lifecycle driver, reasoning-trace artifacts all deferred per IDR-045 Constraints).
