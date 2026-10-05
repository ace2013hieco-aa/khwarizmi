# Documentation index

## Start here

- `../README.md` — what Hermes is, install/operate/test, certified chain.
- `../AGENTS.md` — operating rules for agents and developers (invariants,
  change discipline, verification commands).
- `ARCHITECTURE.md` — current architecture map from source (layers,
  write/read paths, boundaries, diagrams). **Normative map.**
- `API.md` — supported surfaces (CLI, Controller, intents, adapters,
  events, errors) with PUBLIC / INTERNAL / UNDECLARED stability labels.
- `STATE.md` — what is certified *now*, known debt, deliberate
  non-goals, next phase.
- `../examples/first_run.py` — executable CLI tour (init → doctor →
  project → run → status → audit) on a temp database.

## Design / decisions

- `../hermes_research_architecture_v6.md` — authoritative v6 design
  contract (ratified baseline; read alongside ARCHITECTURE.md, which
  describes the implementation as built).
- `idr/` — 50 architecture decision records (the decision log).
- `ix/` — structural-observability snapshots (import/call-graph
  reports, versioned per run; see `ix/README.md`).
- `diagrams/` — maintained architecture figures (HTML + mermaid +
  exports) with provenance manifests.

## Historical evidence

- `archive/` — certification gate reports (P6/N9/P7/tick-loop,
  Phase 0/1), closed audits, design gates, remediation records.
  Read as history, never as the current contract. Root-level
  `hermes_*` design/audit documents are closed-slice reference;
  active reference stays at root or `docs/` (see STATE.md).

Labels used across these docs: CURRENT / NORMATIVE (must hold),
CURRENT / IMPLEMENTATION DETAIL (true today, may evolve),
HISTORICAL / CERTIFICATION EVIDENCE (frozen record),
FUTURE / PROPOSED (not implemented, needs a gate).
