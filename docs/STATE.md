# Hermes current state (2026-09-21)

Labels: CERTIFIED (gated evidence in `archive/`);
INTENTIONAL (deliberate architecture, retained by design gate);
DEFERRED (owned future work with a trigger or gate);
OPEN (acknowledged, owned, non-structural);
DELIBERATELY DEFERRED (explicit non-goals).

## What is currently certified

CERTIFIED structural chain on `main` (full suite green per docs/SUITE-COUNT.md, Ruff/Pyright
clean, remote CI green):

- P6 production classification writer — `ff79bb6`.
- N9 retraction-aware evidence admission — `02cb976` (PR #1).
- P7 contradiction/governance lifecycle — **CERTIFIED / CLOSED**
  (prior B lifted by N9).
- Post-P6 tick-loop detector wiring — **CERTIFIED**
  (`633cff1` + `2328399`).
- Phase 0 repository hygiene — `adab69d`.
- Phase 1 documentation + architecture map — **CERTIFIED**
  (`335d300`; record
  `archive/HERMES_PHASE1_DOCUMENTATION_CERTIFICATION_2026-09-20.md`).
- Phase 1.1 documentation drift closure — `97c09ce`.
- Phase 2 API contract audit — `44aa1a3` (findings feed the backlog below).
- Phase 3 backlog/roadmap audit — `979311f`.
- P0 API stability ratification (A-05) — `19cda3a`.
- DG-2 controller structure → S-1 detector-row extraction —
  `558a8d5` → `231cd75` → `0de76db`.
- DG-3A verdict seam → S-2 HumanDecision append extraction —
  `fe0aa1c` → `3cfaa38` → `6e1458c`.
- DG-3B gateway structure → S-3 L2 resolution extraction —
  `65e82c0` → `df57650` → `dffe907`.
- DG-3C validator reduction → S-4 S5 cone closure extraction —
  `03ff3e4` → `f54af56` → `0f86189`.
- DG-4 repository structure → G-1 proposed-set extraction —
  `4b501e9` → `b9a30a9` → `9cf1837`.
- DG-5 persistence→research inversion design gate — `49db9d9`
  (verdict: NO CORRECTION; residual dependencies INTENTIONAL).
- DG-6 final architecture closure gate — `67a128d`
  (verdict: CLOSURE CONDITIONALLY PASSED / DOCUMENTATION
  RECONCILIATION REQUIRED; this reconciliation executes it).

Evidence: `archive/N9_MAINLINE_MERGE_CERTIFICATION_2026-09-19.md`,
`archive/P7_MAINLINE_CERTIFICATION_2026-09-19.md`,
`archive/POST_P6_TICK_LOOP_CERTIFICATION_2026-09-19.md`,
`archive/HERMES_PHASE0_HYGIENE_CERTIFICATION_2026-09-20.md`,
plus the `HERMES_DG*`, `HERMES_S*`, `HERMES_G1*`, `HERMES_PHASE*`,
and `HERMES_P0*` records in `archive/`.
Earlier slices (Q-05/Q-02/Q-04, ResearchSourceProvider steps 1–6)
remain as their own gate records state; v6 §27-item-43 baseline
per IDR-023.

**GAP-1 wave-1 hardening** landed on `c368886` → `ce41570`: role-gate
exhaustiveness closed fail-closed (`c6680b7`), task admission fail-closed
on content/project with the pinned 13-field canonical byte domain
(`f2b6cae`), append-only journal triggers stage S (`1556706`), and
operator-credential revoke/rotate + legacy rehash + token stdin
(`b989b6d`). Suite chain 4743 → 4759 → 4773 → 4807 → 4838
(`docs/SUITE-COUNT.md`); census 124 calls / 28 owners (persistence 19);
schema v22. Decisions and couplings: `docs/GAP1-RULINGS.md`. Stage S
deters in-DB `UPDATE`/`DELETE` only; hash chain + re-chain remain
TAMPER-2, chartered-deferred.

## Authoritative architecture

`hermes_research_architecture_v6.md` (ratified design contract) +
`docs/ARCHITECTURE.md` (implementation map as built; wins on any
conflict with older text). Decisions: `docs/idr/` (50 records).

## What is production

CLI → Controller tick/loop → intent gateway → validators →
repositories → SQLite + append-only journal; provider adapters
behind `RecordedTransport`; operator verdict surfaces with
credential + lease + journaled HumanDecision. Anything else
(stub modules, unimplemented agent profiles, deferred surfaces)
is not production — see the stub-pointer docstrings in `src/`
and §Known residual debt.

## Historical

`docs/archive/` (gate reports, closed audits/remediations, moved
root records) + root `hermes_*` design/audit documents from closed
slices + `docs/idr/` history. Read as history, never as contract.

## Intentional architecture (INTENTIONAL, retained by gate)

- persistence→research upward imports (13 sites) + 3 lazy-guarded
  cycle pairs — INTENTIONAL per DG-5 (`49db9d9`): Model-D integrity
  boundaries, HR-08 completion choke point, admission/write
  agreement; do not extend without a design gate
  (`ARCHITECTURE.md` §3.10).
- `Controller` (78 methods) / `gateway.py` (15 validators) /
  `repositories.py` (19 classes) concentration — ACCEPTABLE per
  DG-2 / DG-3C / DG-4; no further split justified.
- `hazards.py:137` research import (single recorded exception).
- `IntentApplied` audit row on duplicate admissions (intended
  audit volume, not semantic duplication); in-memory `_notes`
  bound by `max_ticks`.
- Operator-credential lifecycle boundary — DOCUMENTED-AND-ACCEPTED
  (GAP-1 D5-A; human override of the recommended key-custody IDR):
  credential mutations are director-only intents through
  `apply_intent`, with a single acquisition owner
  (`OperatorCredentialRepository._apply_credential_mutation`); revoke
  is terminal and archive-not-delete. No key-custody IDR unless that
  work is ever scoped to include key custody. The model-API-key policy
  (human-held, env-only, never wired) remains unchanged. Boundary
  acceptance only — not a validity, reproducibility, or admissibility
  claim.
- Database-writer trust boundary — DOCUMENTED-AND-ACCEPTED
  (GAP-1 P2-2; ruling A): SQLite write access lets an actor insert or
  rewrite decision/intent rows, including a `HumanDecisionReceived` row
  cited as authority; the gateway admits it. `proposed_by` is a checked
  claim, not authorship (gateway-validated against `AgentProfile`/role
  partition; runtime-filled from the trusted spec): it bounds what the
  runtime says, not who wrote the row. TAMPER-2's unkeyed per-event chain
  makes journal tampering evident (only an out-of-band tip detects a
  re-chain), not forgery: a forger writes a valid chain; chain is not
  authorship. Model output proposes; deterministic code and the
  human-authority gates decide; the audit trail records what the database
  says, not who typed it. No command signing, MAC, key material or
  custody is adopted (D5 stands); signing is a new authority surface and
  custody track. Boundary acceptance only — not a validity,
  reproducibility, or admissibility claim, and not an
  audit-trail-is-forgery-proof claim.

## Known residual debt

- Causal support is structurally inadmissible (AUDIT-CLAIM-GROUND
  finding C, resolution (b); pinned by
  `tests/test_experiment_gate_pin_v2.py`). Causal/experimental claims
  with `support_state` DIRECT or PARTIAL refuse with
  `unverified_experiment_ref` for every experiment ref, because no
  experiment registry exists and no gated declaration intent admits
  one; the hardened resolver (`claims.py`, G12) fails closed. The only
  admissible downgrade path is INFERRED or SPECULATIVE. This stays
  until an experiment registry with a gated declaration intent is
  designed and certified (a future authority design, not a bug fix).
  Note: `main` (`ac1860a`) still carries the prefix-only M4 check,
  which admits these refs; the refusal holds only on the claim-ground
  line.
- STALE-guard project filter wart (F-01; OPEN, owned — needs a
  targeted S5-adjacent gate + S5 slice re-run, not structural).
- Ancestor-scope question (F-02; DEFERRED deliberation, recorded,
  not fenced by design).
- A-01 validator-less intent kinds (OPEN decision: dead vs future;
  `gateway.py` `NOT_WIRED`, no invariant impact).
- Contract/test/docs backlog (DEFERRED, suite- or docs-gated):
  A-02 read-pattern docs, A-03 accidental publics, A-04 contract
  pins, D-01 shared test helpers, D-02 conditional controller-test
  split, B-01 root-sprawl moves, B-03 state cadence, F-03 export
  policy. Full disposition: DG-6 §9.

## Deliberately deferred (non-goals)

Agent runtime profiles, workflow-engine abstractions, plugin
systems, telemetry/dashboards, signing, microservices/event bus,
scientific-validity claims, auto-resolution/reversal, API
versioning machinery.

**Platform line (R1–R7 / W0–W4 / O1–O5) — landed; inert by default, reachable
only through a configured model plane.** The platform planes (R1–R7), the
wiring slices (W0–W4) and the O-series substrates (O1–O5) are committed on the
line as substrate: with `[model_tiers]` empty — the shipped default — the CLI
constructs the controller with no handlers, so none of it is reachable from the
shipped CLI. With at least one tier naming a registry provider, `hermes run`
composes the model plane and the methodology handler (OPS-1,
`docs/idr/LIVE-CLI-COMPOSITION.md`); that path is reachable from the shipped
CLI, and a run states its mode and names the provider it used. Reachability is
not certification, and no run output is evidence of scientific validity or
reproducibility. O2 is load-bearing (ratified by IDR-046); O1/O3/O4/O5 are
unwired and remain deferrable bulk — O1 pending its sidecar design gate, O5
pending a ranker design gate, O4 blocked on `ARCHITECTURE_DELTA` B-6. Only O2
is in scope for the certified tree; the rest is not a certified capability.

## Program status

The architecture/repository structural-improvement program
(Phase 0 → DG-6) is **CLOSED** with this documentation
reconciliation. Closure covers structural decomposition,
inversion review, and architecture mapping only. The residual
backlog above (F-01, A-01, deferred docs/test items) remains
available for later work under ordinary gate discipline; any
invariant-adjacent change still needs a design gate first.
