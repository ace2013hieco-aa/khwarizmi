# AGENTS.md — Operating Rules for Agents and Developers

Hermes Research is a deterministic quantitative-research control system:
a typed state machine (projects, tasks, evidence, classifications,
contradictions) advanced by a lease-fenced controller through a single
intent gateway, with an append-only journal and recorded/transcript
provider replay. See `docs/ARCHITECTURE.md` for the map,
`docs/API.md` for surfaces, `docs/STATE.md` for what is certified.

## Non-negotiable architectural invariants

These are certified and enforced in code. Do not weaken them; changes
near them need a design gate plus the owning certification slice
re-run (P6/N9/P7/tick-loop records live in `docs/archive/`).

- Determinism owns control. No LLM/model output may decide a
  transition; models are routed behind ports, never authorities
  (`src/hermes/research/evaluation.py`, deterministic libraries only).
- Single mutation path: `apply_intent`
  (`src/hermes/research/gateway.py:3961`). Never write durable state
  around it — no direct repository writes from orchestration, no
  direct SQL mutation outside certified transaction boundaries:
  27 acquisition owners across persistence (18), gateway (5), and
  Controller (4), plus one rollback-only participant (DG-4/DG-6;
  details in `docs/ARCHITECTURE.md` §3.10). Most boundaries own a
  `BEGIN IMMEDIATE` transaction; a few intentional plain-`BEGIN`
  cases exist (repository creates, event-retry path, migrations,
  Controller floor/ladder/human-gate paths).
- Append-only journal (`src/hermes/core/events.py`; writer
  `src/hermes/persistence/repositories.py`). No DELETE exists in
  `src/`; supersession/invalidation are new rows/events, history is
  never rewritten.
- Replay determinism: provider bytes replay identically through
  `RecordedTransport` (`src/hermes/tools/providers/replay.py`);
  replay proves byte/evidence determinism only — never scientific
  validity, and never admissibility of retracted sources (N9).
- Human-authority fail-closed boundary: `CONTRADICTION_RESOLUTION`,
  `RECORD_CLASSIFICATION`, `RETRACT_SOURCE` and 6 more kinds are
  `internal_only` (`src/hermes/core/intents.py:144`); LLM-proposable
  kinds are listed at `intents.py:124`. A missing/unbound
  `HumanDecisionReceived` journal row refuses the command
  (`gateway.py`, `PROPOSAL`).
- Bounded payload discipline (4 KiB): event payloads are size-checked
  (`src/hermes/persistence/event_validation.py`); oversized verdicts
  refuse with `RATIONALE` before any write.
- Project isolation: every resolver, detector row, validator, and
  retraction predicate is project-scoped; cross-project citation
  fails closed (`EVIDENCE_DOES_NOT_RESOLVE`).
- Prohibited-claims discipline: never claim scientific
  reproducibility, never present replay as validity, never present a
  digest/derived view as authority.
- Archive-not-delete; head-only supersession (a second supersede
  link on one row is refused); refusal-as-data (rejections return
  data with codes from `gateway.py:93-109`, never silent success).
- Lease-fenced single writer: controller surfaces acquire the
  scheduler lock (`controller.py:2336`); contention returns `LOCK`;
  mid-tick loss aborts to `lock_lost` with rollback.
- Content-hash identity: `fc_`/`cx_`/`cres_`/`fx_`/`retract_` IDs are
  recomputed, never trusted (`contradictions.py:75`,
  N1 pair rule `:106`, N9 predicate
  `source_outcomes.py:159`).
- N1 contradiction semantics and N9 retraction fencing are frozen:
  same project/program/hypothesis, different failure class, neither
  party invalidated, non-empty currently-valid evidence overlap.

## Change discipline

- Read the code and the owning gate record before touching
  architecture; check `git log`, `git status`, `git diff` first.
- Minimal diffs; one concern per commit; never mix behavior changes
  into documentation commits.
- No provider leakage into core layers: adapters import only
  `hermes.tools.*` (the single exception,
  `hazards.py:137`, is recorded debt).
- No persistence→research imports beyond the existing intentional
  exceptions — 15 statements, CERTIFIED INTENTIONAL ARCHITECTURE, NOT
  DEBT (DG-5: Model-D integrity boundaries — inclusive of the
  `hermes.research.regimes` regime dereference, IDR-044 A6/A7 — HR-08
  completion choke point, admission/write agreement; the full census
  lives in `docs/ARCHITECTURE.md` §3.10). Do not add new upward
  dependencies without an explicit design gate.
- No unrelated project mixing: keep diffs scoped; verify with
  `git diff --stat` before committing.

## Testing / verification

Canonical commands (Python 3.14, see README “Operate”):

```bash
uv venv --python 3.14; uv sync
.venv/Scripts/python.exe scripts/run_tests.py -v   # full suite (2101)
uvx ruff check src tests                            # lint gate (C3)
uvx pyright src                                     # strict type gate
uvx pyright --pythonpath .venv/Scripts/python.exe --project pyrightconfig.tests.json
./scripts/profiled_gate.sh                          # tests-profile + smoke
```

Architectural changes require the full suite plus the gate owning
each touched surface (P6/N9/P7/tick-loop slices); a red gate stops
the change. Docs-only changes still require the full suite green
(to prove no behavior change).

## Current architecture map (orientation)

CLI (`cli.py`) → Controller tick/loop (`controller.py:486,597`) →
intent intents (`core/intents.py`) → `apply_intent` gateway →
validators → repositories (own transactions) → SQLite + journal.
Providers sit behind `RecordedTransport`; replay serves fixtures
with a refusing inner transport. Details: `docs/ARCHITECTURE.md`.
Structural program closed (DG-6): S-1/S-2/S-3/S-4/G-1 extracted +
certified; module concentration accepted; see `docs/STATE.md`.

## Historical records

Certification evidence (P6/N9/P7/tick-loop, audits, phase reports)
lives in `docs/archive/` — read it as history, never as the current
contract. `docs/idr/` holds architecture decision records. Design
gates/audits from closed slices live in `docs/archive/`; active
design reference stays at root or `docs/` until Phase 1 navigation
says otherwise. `docs/STATE.md` records what is certified *now*.
