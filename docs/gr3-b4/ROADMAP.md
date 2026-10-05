# GR3 v0 workflow — ROADMAP (project khwarizmi-research, program mainline)

Status: LIVE (created by GR3-P0-context on branch `gr3-b4/p0` from
`main@c0b5777`). No live roadmap existed on `main` (only the historical
audit `docs/archive/HERMES_PHASE3_BACKLOG_ROADMAP_AUDIT_2026-09-20.md`);
this file is the workflow's phase table. Full context:
`docs/gr3-b4/P0-context.md`.

**Amended by GR3-P3-repair** (branch `gr3-b4/p3-repair`, from
`gr3-b4/p3-audit@d383be2`) — a **branch-name tracker correction**: the
P3 seat's branch had been consumed by a task the table did not describe,
so the seat is split into what `gr3-b4/p3` actually holds and the name
newly reserved for the chartered phase. See §Notes. This is tracking
truth, not a charter: the chartered phase's substance is unchanged and
still requires its own charter.

**Closed by GR3-closeout** (branch `gr3-b4/closeout`, from
`gr3-b4/p3-r1r2@ad2c33f`) — workflow outcome recorded in §Outcome
(FINISHED). Local-only, no push.

## Bounds (every phase)

- S6 non-negotiable invariants (`AGENTS.md:10-64`) bound everything
  downstream; any invariant-adjacent change needs a design gate plus the
  owning certification slice re-run first.
- Role slots, not researcher-assistant framing: DETERMINISTIC (sole
  mutation author) / DIRECTOR / RESEARCHER / IMPLEMENTER / ADVERSARY
  (allowlisted proposals) / OPERATOR (credential + lease + recorded
  `HumanDecisionReceived`); providers and untrusted text are never authority.
- No new intent kind, event type, or authority is presumed by any phase
  (`docs/ARCHITECTURE.md:202-213` — "Merely possible (not supported —
  requires a design gate)").
- TEXP twin (`experiments/texp-001/`, pinned `texp-001/s6-audit
  @ a927c7a`) is read-only reference; never modify from this workflow,
  except for additive, absent-safe B4 wiring: the `B4 SOURCE` section
  appended after `__all__` in `experiments/texp-001/fixtures.py` (+181/0,
  no existing line edited, no behavior change to the 85 pre-existing
  twin tests) plus the additive `B4 SOURCE` test file
  `experiments/texp-001/test_b4_source.py`. This exception is recorded
  as P2-b4fixtures decision C2 and is closed — no further twin edits
  without a new charter.
- Prohibited claims: no scientific reproducibility, no replay-as-validity,
  no digest/derived view as authority.

## Phase table

| Phase | Branch (from `main`) | Goal | Entry requires | Exit (acceptance) |
|---|---|---|---|---|
| P0 context | `gr3-b4/p0` | Ratify starting context (this file + `P0-context.md`) | `main@c0b5777` confirmed | P0-context.md committed locally; zero `src/` changes; all premises marked; no push |
| P1 edges | `gr3-b4/p1` (TBD, charter first) | Admit a first governed source corpus; author GR3 edge rows (`supports`/`entails`) through the existing write path only | P0 accepted; corpus nominated; design gate if any invariant adjacency | Admitted corpus + GR3 edges recorded; cascade walks 5 types; full suite green; no new intent/event/authority |
| P2 b4fixtures | `gr3-b4/p2` (re-chartered: B4 reference graphs) | Package real typed-edge reference graphs (cites-only, 12-doc governed corpus) for TEXP-001 twin consumption — the B4 task that replaces the twin's "no real graph" placeholder. Traversal remains UNCHARTERED (deferred). | P1b accepted; twin pin a927c7a | Additive B4 wiring + 4 content-addressed fixtures + report committed locally; full suite green; twin suite 97 passed; no new intent/event/authority; traversal still TBD |
| P3 reconcile — **ACTUAL on `gr3-b4/p3`** | `gr3-b4/p3` (`p3` → `p3-audit` → `p3-repair`) | TEXP-001 grounded sweep/bank/redesign decision against the B4 fixtures. Outcome **BANK-now**: texp-001 shelved pre-EVAL under three stated shelve conditions (`P3-reconciliation.md` §D3). | P2-b4fixtures report + adversary audit; base hash `git rev-parse`-checked before cutover | `P3-reconciliation.md` + `P3-audit.md` + `P3-repair.md` committed locally; probe reproducible and re-runnable; suites green; no `src/`; no push |
| P3 contradiction flags | **`gr3-b4/p3-contradiction`** (RESERVED — see §Notes; TBD, charter first) | Graph-structural contradiction flagging ("graph proposes; validated evidence decides"), N1/N9 preserved verbatim | P2 accepted; §19/N1/N9 gate review | Flags advisory only; OPEN/COMPLETED lifecycle unchanged; HR-08 + N1 + N9 slices re-run green |
| P4+ | UNCHARTERED | Not in GR3 v0 scope | — | Any continuation needs a new charter + gates |

## Notes

- **Branch-name correction (GR3-P3-repair, P3-audit C5).** `gr3-b4/p3`
  was chartered above for *contradiction flags*, but was in fact used for
  the TEXP-001 reconciliation (`gr3-b4/p3` → `gr3-b4/p3-audit` →
  `gr3-b4/p3-repair`). The chartered phase is re-pointed to the
  **reserved** name `gr3-b4/p3-contradiction` and remains **UNSTARTED** —
  it still needs its own charter and its own §19/N1/N9 gate review. This
  edit records which branch holds what; it does not charter, re-scope or
  cancel the chartered phase, which remains a director action.
- **P2 seat status (do not read as closed).** `gr3-b4/p2` was audited as
  **ACCEPT WITH CONDITIONS (C1–C3)** (`gr3-b4/p2-audit`), and `da79dfd`
  (`gr3-b4/p2-fix`) applies those conditions, but **no audit of `p2-fix`
  exists**, so a plain "P2 accepted" is not yet earned. Recorded here so
  the P3-contradiction entry condition is not taken as satisfied.
- **texp-001 status.** **Shelved pre-EVAL** per
  `docs/gr3-b4/P3-reconciliation.md` §D3 (double NO-GO; B4 supplies no
  admissible structure to the twin; three shelve conditions). The twin
  stays pinned at `texp-001/s6-audit@a927c7a` and stays read-only from
  this workflow.
- Next free mainline IDR file slot: `docs/idr/IDR-042.md`, with the
  caveat that label `IDR-042` already appears in unmerged side history
  (`48e4ce9`, `texp-001/p2`, plan-only). Coordinate numbering at P1
  charter time (see P0-context §(g)).
- Candidate corpus for P1: ABSENT at P0 — Phase 1 must nominate and
  admit sources before extracting any GR3 edge (see P0-context §(i)).
- Branch hygiene: one concern per commit; docs-only vs behavior commits
  never mixed; `git diff --stat` checked before every commit; local-only
  (no push without explicit human override).

## Outcome (GR3-closeout — workflow FINISHED)

- **OUTCOME = BANK.** Twin texp-001 shelved pre-EVAL: double NO-GO (P4 +
  p4-repilot) with the coverage-AND-rank mechanism measured on the pinned
  machinery; B4 fixtures landed as advisory reference structure (0
  admissible paths — nothing the twin can ingest for calibration). Revisit
  iff a shelve condition fires (`P3-reconciliation.md` §D3): (1) a
  B4-scale grounding exists (alphabet-member edge type, or a chartered
  documents→nodes / `cites`→class mapping); (2) a production sampler
  exists; (3) a rank-side design arrives with its own pre-registered
  protocol.
- **NEXT MILESTONE = none scheduled.** No further GR3 v0 phase is
  chartered; the reserved `gr3-b4/p3-contradiction` slot stays UNSTARTED
  (charter-first, director action).
- **Commit-hash trail (all `git rev-parse`-verified, local-only):**
  P0 `547d5f6` (audited `3dbcf32`) → P1a `e5f01d3` (audited `6ce52ee`) →
  P1b `13565f8` (audited `1a051e4`) → P2 `761a35f` (audited `485f09a`,
  fix `da79dfd` un-audited) → P3 BANK `ad2c33f` (reconcile `168afd7`,
  audit `d383be2`, repair `71c955d`, re-audit `d32fbeb`, r1r2 `ad2c33f`).
  Closeout recorded on `gr3-b4/closeout`; no push.
