# Hermes Architecture Harvest — v2 Addendum (Fresh Verification)

**Status:** ADDENDUM. The authoritative report remains `hermes_architecture_harvest_report.md` committed at `f9df74b`. This document does not replace, rewrite, or supersede it; it records an independent fresh verification performed on 2026-08-24 against current upstream repository states.

---

## 1. Baseline

- **Authoritative harvest report:** `hermes_architecture_harvest_report.md`, committed at `f9df74b`.
- **Hermes baseline re-verified at:** `f9df74b` (working tree HEAD during this addendum session).
- **Test suite:** `1701 passed in 332.55s` (executed in this session via `scripts/run_tests.py -q`, 2026-08-24).
- **Lint:** `uvx ruff check src tests` → all checks passed.
- **Types:** `uvx pyright --pythonpath .venv/Scripts/python.exe --project pyrightconfig.tests.json` → 0 errors, 1 pre-existing warning in `tests/test_research_program.py:141` (baseline noise).
- **Method:** fresh shallow clones of all seven upstream repositories into `.freebuff/audit2/`, followed by direct source inspection (grep + read) executed in this session. No LLM subagent completed an inspection (all were rate-limited, HTTP 429); every mechanism claim below traces to a file read in-session. Inspector notes preserved at `.freebuff/audit2/inspect_notes.md`.

## 2. Fresh External Verification — Clone Pins

| Repository | Fresh clone commit (2026-08-24) | Original audit reference |
|---|---|---|
| idsia/sacred | `86865b0` | `86865b0` — unchanged |
| nextflow-io/nextflow | `2e13110` | inspected at then-HEAD |
| e2b-dev/E2B | `b802997` | inspected at then-HEAD |
| Panniantong/Agent-Reach | `93ae1d1` | inspected at then-HEAD |
| OpenNSWM-Lab/FAROS | `9f6ac0b` | inspected at then-HEAD |
| elizaOS/eliza | `f11cedd3` | `a40cc65` — advanced |
| DeusData/codebase-memory-mcp | `010569f` | inspected at then-HEAD |

## 3. Evidence Confirmations

Each mechanism claimed by the original harvest report was re-verified against the fresh clone. No claim was refuted.

- **nextflow task fingerprint + retry salt — CONFIRMED.** `modules/nextflow/src/main/groovy/nextflow/processor/TaskHasher.groovy:41-139` computes the cache hash over: `session.uniqueId`, process name, `task.source`, container fingerprint (`task.getContainerFingerprint()`), input name/value pairs, eval-output command text (sorted for determinism), script-referenced global vars, bin-script entries, module-bundle fingerprint, and conda/spack environments. Retry salting confirmed at `TaskProcessor.groovy:815` — on retry, `hash = HashBuilder.defaultHasher().putBytes(hash.asBytes()).putInt(tries).hash()`, so a retried task cannot consume the original attempt's cache entry. The original ADAPT verdict for this mechanism (into the unbuilt v6 §16.2 / PA1 cache-key spec) stands.
- **sacred observer quarantine + run identity — CONFIRMED.** `run.py:417-423` `_safe_call` swallows observer exceptions, appends the observer to `_failed_observers`, and never re-raises — an observer failure cannot fail the run (contrast: Hermes' journal triggers are fail-closed; the journal is the stricter mechanism, as the original report concluded). Run ID is assigned by the first observer via `started_event`/`queued_event` (`run.py:34,299-342`), not by the core — confirming that sacred's identity model is observer-dependent. Unknown config keys raise `KeyError` (`config/config_scope.py:60-70`). Hierarchical seed derivation present in `randomness.py:13-48`.
- **E2B sandbox lifecycle — CONFIRMED.** `packages/python-sdk/e2b/sandbox_async/main.py:169-528` exposes `create`/`connect`/`kill` and `fork` (`:359-475`). The fork/snapshot semantics exist as an API surface; no authoritative artifact-extraction boundary condition is specified in the Python SDK beyond what the original report adapted into the T4 sandbox contract. Python-SDK lifecycle surface additionally verified at `packages/python-sdk/e2b/sandbox/sandbox_api.py:483-562`: `SandboxOnTimeoutPause`, `SandboxOnTimeoutKill`, `SandboxLifecycle`, including `on_timeout` behavior and the `keep_memory` full-snapshot flag — this confirms the pause/kill-with-memory semantics from the Python SDK side, in addition to the infrastructure-side evidence already recorded in the authoritative report. The ratified E2B disposition is unchanged: the deliberate-artifact-extraction boundary condition remains an ADOPTED contract condition (not ADAPT), and E2B remains a future PROVIDER behind `SandboxedPythonTool` — never authority.
- **Agent-Reach probe taxonomy — CONFIRMED.** `agent_reach/probe.py:28-120` classifies command health as `ok | missing | broken | timeout | error`, distinguishes "which() finds it but exec fails" (exit codes 126/127, FileNotFoundError) as `broken`, and skips retries for missing/broken (they cannot heal; `probe.py:72-82`). Channel ABC verified at `agent_reach/channels/base.py:29-80`: `can_handle(url)`, `ordered_backends(config)` with the per-channel `<channel>_backend` user override, and `check()` performing a real probe and setting `active_backend` — evidence completion only; the decision below is unchanged. The CLI (`cli.py`) is an installer/doctor/configure tool — confirming the original finding that Agent-Reach is **not** a runtime capability router. REJECT runtime / ADAPT diagnostic-pattern verdict stands.
- **FAROS lacks single-gateway discipline — CONFIRMED.** `backend/app/faros/registry/` holds runtime-modifiable registries (`AgentRegistry.register` mutates `_package_agents` directly); capabilities bind statically via adapters under `capabilities/adapters/`; persistence is file-backed (`README`: "File-backed run, event, artifact, and memory persistence"); the README itself lists "full DAG scheduling and parallel orchestration" and "DB-backed FAROS runtime metadata" as **Not Yet Included**. No single mutation gateway, no append-only journal with fail-closed triggers found. REJECT verdict stands.
- **eliza AbortSignal + effectReceipts vs god-runtime — CONFIRMED.** `packages/core/src/types/components.ts:747` shows providers receive `signal: AbortSignal`; `:753` notes handling for providers that fail to cooperatively observe abort; `:967` shows `effectReceipts` on effects. Provider interface contract additionally verified at `packages/core/src/types/components.ts:720-755`, including the read-only `get` surface and `ProviderExecutionContext.signal: AbortSignal` — evidence completion only; the architectural verdict is unchanged. The runtime composes agents from plugins with stringly-typed registration and LLM-mediated action selection — the inverse of Hermes' deterministic dispatch. REJECT architecture / ADAPT micro-patterns verdict stands.
- **codebase-memory-mcp is development infrastructure — CONFIRMED.** Tree-sitter AST indexing across 158 languages into a persistent code knowledge graph (`README.md`); source tree (`src/`: cypher, daemon, git, graph_buffer, mcp, pipeline, watcher) exposes an MCP tool surface over code structure only. No research-evidence surface exists. DEVELOPMENT TOOL verdict stands; merging it into the research evidence graph remains a category error.

## 4. Hermes Drift Check (at `f9df74b`)

- `ExperimentRun`: **0 references** in `src/` (grep-verified this session) — remains unimplemented.
- `src/hermes/tools/sandbox.py` and `src/hermes/tools/execution.py`: still `"Phase 0: placeholder."` docstrings — unchanged.
- `RESULT_REUSED` remains declared at `src/hermes/core/events.py:68` with **no producer** in `src/` — unchanged.
- Task state machine unchanged: `src/hermes/core/task_status.py:20` (PENDING/READY/RUNNING/SUCCEEDED/FAILED/RETRYING/NO_SIGNAL/WAITING_HUMAN/WAITING_EXTERNAL/CANCELLED/SKIPPED + INVALIDATED via the S5 cascade).
- Persistence unchanged in shape: 22 `CREATE TABLE` statements, 28 migrations in `src/hermes/persistence/migrations.py`.
- Architecture authority boundaries (single `apply_intent` gateway, lease-fenced controller, journal as sole append-only record, PS-03 recorder boundary): **unchanged** between the original audit baseline `060872c` and this session's `f9df74b` (the only delta on main is the original harvest report itself, a docs-only commit).
- **No structural architecture change is justified by this fresh verification.**

## 5. Verdict

**The fresh audit CONFIRMS rather than supersedes the original harvest conclusions.** Every ratified amendment (sacred run-record completeness → v6 §16.2 ExperimentRun design; nextflow content-hash fingerprint + retry-salt → PA1/§16.2 cache-key formula; E2B artifact-extraction boundary condition → T4 sandbox contract; E2B as future PROVIDER behind `SandboxedPythonTool`; eliza provider-purity + collision-policy clauses; codebase-memory-mcp as DEVELOPMENT TOOL) and every explicit rejection (sacred observers/queue, nextflow channels/executors/resume, Agent-Reach router posture, FAROS layers, eliza god-runtime/LLM-routing, code-graph merge) remains supported by the freshly inspected sources.

**No production implementation is authorized by this addendum.** It modifies no architecture, no code, and no prior ratification; it attests only that the original report's evidence claims still match the upstream sources as of 2026-08-24.

## 6. Evidence Limitation

This was a **targeted fresh verification**, not a complete re-audit. For each repository, the fresh inspection re-read the specific files and mechanisms the original report relied on (the evidence-bearing paths listed in §3). It did **not** re-inspect every subsystem of every repository, did not re-run the six parallel deep inspections of the original audit, and did not re-derive the 13-question evaluation for every mechanism from scratch. Conclusions beyond the listed evidence points continue to rest on the original report at `f9df74b`. This addendum claims no greater coverage than was actually performed.
