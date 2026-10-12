# HERMES ARCHITECTURE HARVEST & RATIFICATION REPORT

**Independent External Mechanism Review** — sacred, nextflow, E2B, Agent-Reach, FAROS, eliza, codebase-memory-mcp
**Date:** 2026-08-22
**Hermes baseline reviewed:** `khwarizmi-research` @ `060872c` (post Step-6 design gate)
**Method:** six parallel live-source inspections of the external repositories (shallow clones, evidence paths recorded per mechanism) + direct verification of the Hermes substrate at HEAD. No Hermes code was modified. Inspector inventories are preserved in the delegation cache; every claim below traces to a file path from those inspections.

---

## 1. Executive Verdict

**None of the seven repositories should change the Hermes architecture today.
Three mechanisms are worth ratifying as DESIGN-TIME amendments to already-designed-but-unbuilt v6 slices; one tool is ratified as development infrastructure; everything else is REJECT or DEFER with reasons.**

The decisive context: Hermes' two real voids are (a) the execution substrate — `tools/sandbox.py` and `tools/execution.py` are literal Phase 0 placeholders — and (b) run/caching semantics — the `ResultReused` event exists in the catalog with no registry behind it. The external repos cluster around exactly these voids. That makes the harvest *timed well* but does not make adoption automatic:

| Repo | Decision | One-line reason |
|---|---|---|
| idsia/sacred | **ADAPT (3 mechanisms, design-time)** | Run-record completeness + observer vocabulary + honest reproducibility limits strengthen the already-designed v6 §16.2 result model — but Hermes' journal/gateway already subsume sacred's observer bus and identity assignment |
| nextflow-io/nextflow | **ADAPT (1 mechanism) / DEFER (rest)** | Content-hash task fingerprint incl. container fingerprint + retry-salt is the correct shape for v6 §16.2's cache registry; channels/dataflow and executor zoo are rejected (duplicate orchestration layer) |
| e2b-dev/E2B | **PROVIDER (future), architecture notes now** | The only repo that solves a problem Hermes has placeholders for; adopt as an adapter behind `SandboxedPythonTool` when PA1/T4 lands — never as authority; its snapshot/fork ideas map cleanly onto Hermes' artifact immutability rules |
| Panniantong/Agent-Reach | **REJECT (runtime) / ADAPT (1 diagnostic pattern)** | Its "installer + capability router" posture is architecturally incompatible with Hermes' driver-owned transport (PS-03); the probe-based health-check taxonomy is worth stealing as a concept |
| OpenNSWM-Lab/FAROS | **REJECT / ADAPT (profile-validation idea)** | FAROS is a worse Hermes: it re-implements a research pipeline state machine without Hermes' single-gateway discipline; its static capability bindings are strictly weaker than Hermes' existing contract-card adapters; the validated-profile-before-run gate is the one good idea, and Hermes already has ScopeBriefs |
| elizaOS/eliza | **REJECT (architecture) / ADAPT (2 micro-patterns)** | The god-runtime/LLM-routing/stringly-typed model is the inverse of Hermes' determinism thesis; steal only the read-only provider contract with abort signals and explicit component-collision policy |
| DeusData/codebase-memory-mcp | **DEVELOPMENT TOOL** | ~100% dev-infrastructure; zero research-evidence surface; valuable for auditing Hermes itself; must never touch the research/evidence graph |

**Answer to the final question:** exactly one repository could eventually change how Hermes *executes* (E2B, as a sandbox provider adapter), and none should change what Hermes *is*. The ratified changes are three design-time amendments (sacred's run-record fields into §16.2's ExperimentRun design; nextflow's fingerprint formula into the cache-key spec; E2B's isolation/persistence boundary conditions into the T4 sandbox contract) plus one development-tool adoption (codebase-memory-mcp). Everything else fails the 13-question test on authority, source-of-truth, or complexity grounds.

---

## 2. Current Hermes Architecture Understanding (verified live @ `060872c`)

Implemented and tested:
- Task graph + lifecycle: `tasks`, `task_dependencies` (migrations.py:72/107); terminal INVALIDATED via S5 cascade (`gateway.py`, closed at `206b643`).
- Single mutation gateway: `apply_intent` with per-kind validators, structured rejections, idempotency keys; intent classes split LLM-proposable / human-initiated / internal-only (v6 §8).
- Event journal: append-only triggers (F-16), enum-derived validation allowlist (F-15), replay-deterministic.
- Lease-fenced controller: `Controller.tick()/run()` — `scheduler_lock` single-writer, generation fencing, recovery chain, wave dispatch (IDR-029).
- Provider-adapter contract (the relevant existing capability layer): `ProviderContractCard` + four hooks (`build_request`, `parse_page`, `extract_ids`, `build_fetch_request`), driver/limiter/recorder separation, recorder-boundary redaction, hazard specs, rate profiles (`src/hermes/tools/providers/base.py`) — ratified IDR-030.
- Provenance/evidence graph: `provenance_edges` (5 edge types), Q-04 blast-radius pure functions, evidence-ladder machinery, claims/assumptions write path (IDR-025–028).
- Advisory/proposal loop: reconcile digest → proposal intents → pending replay → lease-held operator ingestion (IDR-040; Step-6 gate extended this to retraction at `060872c`).

Designed but NOT built (v6 text exists, code is placeholder):
- Execution: `SandboxedPythonTool` port (`sandbox.py`: "Phase 0: placeholder"), `CodeExecutionTool` (`execution.py`: same), PA1 per-task kernel, T4-isolated runner, budget ledger (AR-02).
- Result reuse: `ResultReused` event declared (`events.py:68`) with no cache registry; §16.2 content-hash reuse registry is P13.
- Reconcile module: `reconcile.py` is a 6-line docstring (real loop = Controller tick).
- No ExperimentRun/run-record table exists (`grep ExperimentRun` → zero hits).

This split — strong governance spine, missing execution flesh — frames every verdict below.

## 3. Repository-by-Repository Assessment

### 3.1 idsia/sacred (@ `86865b0`)
Mature experiment-tracking framework. Core mechanisms verified: name-based experiment identity with source+md5/dependency/git capture (`experiment.py:104-137`, `dependencies.py:400-444`); config-scope AST extraction with unknown-key rejection (`config/config_scope.py:32-95`, `initialize.py:210-232`); run document with full re-run payload (`run.py:34-119`); duck-typed push observers over a flat event vocabulary with priority ordering and mid-run failure swallowing (`observers/base.py`, `_safe_call`); hierarchical seed derivation (`randomness.py`); QUEUED-status queueing as a data convention with no shipped scheduler (`commandline_options.py:236-258`). Honest limits documented by sacred itself: metadata capture ≠ determinism; interactive mode refuses to guarantee reproducibility.

**Assessment against Hermes:** Hermes' journal IS a stricter observer bus than sacred's (append-only triggers vs. swallowed observer errors; enum-derived validation vs. duck typing). Sacred's genuinely superior elements are (1) the *completeness* discipline of the run record — one document containing everything needed to re-run — and (2) the config-completeness guard (unknown key = error unless declared). Both map onto v6 §16.2's designed-but-unbuilt ExperimentRun/result model, strengthening it at design time. Sacred's queueing convention is unnecessary: Hermes' scheduler_lock + task graph already own dispatch, and a second QUEUED-status pool would be a second orchestration layer (rejected).

### 3.2 nextflow-io/nextflow (evidence from live transcript inspection)
Workflow engine. Verified mechanisms: task cache hash computed by `TaskHasher(task).compute()` invoked at `TaskProcessor.groovy:684`, salted with the retry attempt count on retries (`TaskProcessor.groovy:815`); hash modes STANDARD/DEEP/LENIENT/SHA256 selected via `CacheHelper` (`nf-commons/.../CacheHelper.java:28-45`, env-overridable); resume keyed off session UUID persisted in `.nextflow.history` (`Session.groovy:395-398`, `HistoryFile.groovy`); LevelDB-backed `CacheDB`; container image fingerprint folded into the task hash (`TaskRun.groovy:761 getContainerFingerprint()`); four-state task enum NEW/SUBMITTED/RUNNING/COMPLETED with `ErrorStrategy` retry policies; pluggable executors (local/SGE/PBS/k8s/cloud batch via plugins); GPars dataflow channels for dependency propagation; rich TraceRecord fields for provenance reporting.

**Assessment:** The fingerprint mechanism is excellent and directly transplantable: content-hash over (task template/script, input artifact hashes, container/environment fingerprint, parameter values), salted per retry attempt so a retried task can never consume the original's cache entry. This is the missing concrete spec behind v6 §16.2's abstract "content-hash reuse registry" and PA1's cache-key discipline. The rest — channels/dataflow, executor abstraction zoo, work-dir conventions — duplicates or conflicts with Hermes' authoritative task graph, gateway-owned transitions, and deterministic dispatch. Nextflow's own task states are coarser than Hermes' (no PARKED/WAITING_HUMAN/INVALIDATED-class terminals). Adopting the dataflow model would create exactly the second orchestration layer the charter forbids.

### 3.3 e2b-dev/E2B (+ infra backend)
Firecracker-microVM sandbox platform. Verified: one dedicated kernel per sandbox, cgroup + netns, nftables/SNI egress firewall per slot (`infra/packages/orchestrator/pkg/sandbox/*`); "a sandbox is a resumed snapshot" — near-instant start from pre-booted template snapshots, lazy memory restore via userfaultfd, copy-on-write rootfs over read-only templates (`docs/ARCHITECTURE.md`, `snapshot.go`, `uffd/`, `nbd/`); pause/resume capturing dirty-memory+disk diffs; named snapshots persisting as ordinary build artifacts that survive deletion; beta fork checkpointing a live sandbox and fanning out clones; Dockerfile→template builds with hashed cached layers and pinned base versions; deliberate-only artifact escape (file APIs, signed URLs, token-audience-bound volumes) — otherwise state dies with the VM; control plane / data plane separation with sandbox traffic never touching control.

**Assessment:** E2B is the only inspected system that occupies a space where Hermes currently has nothing (placeholders). Its *mechanisms* — VM-grade isolation, immutable template pinning, diff-based snapshots, deliberate artifact extraction — align remarkably well with Hermes' principles: artifacts immutable/archived-not-deleted, results escape only through governed boundaries, environments pinned like any other provenance fact. But E2B is a hosted platform with its own Redis-backed running-state and control plane; adopting it wholesale would install a second orchestration layer and a second state store — both forbidden. Correct posture: **adapter/provider under the future `SandboxedPythonTool` port**, with the contract requiring Hermes-side recording of (template build ID, snapshot ID if any, command, exit code, extracted artifact hashes) into the journal. E2B remains replaceable infrastructure; a local Firecracker/containerd fallback keeps principle 8 (external frameworks are never authorities).

### 3.4 Panniantong/Agent-Reach
Python CLI/lib: 15 channel classes in a hardcoded registry (`channels/__init__.py`), ordered fallback backends per channel with env overrides, live executable health probes classifying missing/broken/timeout/error (`probe.py`), side-effect-free doctor with credential scrubbing (`doctor.py`), flat YAML config with symlink-safe atomic writes. Explicitly an installer/router: after setup, agents call upstream CLIs directly; its MCP server exposes only `get_status`.

**Assessment:** Architecturally incompatible as runtime. Hermes' provider layer enforces the thin-adapter invariant (PS-03): the adapter never holds transport, limiter, or recorder — Agent-Reach's whole value proposition is delegating invocation to un-managed local CLIs outside any recorder boundary, which would break redaction, rate-limit accounting, and outcome hashing (the HZ-02 retraction-trigger chain depends on controlled fetch outcomes). A second capability router would also duplicate discovery/diagnostics that Hermes owns via provider cards. The one transferable idea: probe-based health classification (execute `--version`, classify missing/broken/timeout/error rather than trusting PATH presence) — worth adopting as a *diagnostic* pattern inside Hermes' existing provider diagnostics, not as a router.

### 3.5 OpenNSWM-Lab/FAROS
FastAPI research-automation platform: validated Profile documents binding capabilities→providers (+agents, skills, verification/memory policy), provider-independent Blueprint DAGs, explicit run/step state machines with operator-invoked retry/replay, typed ArtifactRecords governed by schema contracts, four provider types (llm/tool/execution/human).

**Assessment:** FAROS is essentially an independent, weaker rediscovery of Hermes: DAG orchestration, state machines, typed artifacts, human-provider gates — but without a single mutation gateway (providers invoke directly), without append-only event integrity, with one static binding per capability and no fallback, and configuration-level (not behavioral) health. Nothing here is superior to the corresponding Hermes mechanism; several are inferior in ways Hermes explicitly designed against. The profile-validation idea (hard-fail a run whose profile references unregistered providers) is sound but already covered by Hermes' ScopeBrief freeze + program compilation admission. REJECT as architecture; keep as prior art citation.

### 3.6 elizaOS/eliza (@ `a40cc65`)
Component-based chat-agent runtime: Actions (LLM-routed via prose similes/routing hints), read-only Providers (context assembly with abort signals, cache hints, gating), post-hoc Evaluators (JSON-Schema pipelines), Services (string-typed registries via module augmentation), all registered imperatively on a 13k-line `AgentRuntime` god-object with a ~1,400-line `IAgentRuntime` interface; 127 first-party plugins; product-specific flags leaking into core.

**Assessment:** Eliza optimizes for open-ended extensibility — the precise opposite of Hermes' closed-capability-set, total-function, machine-checked-contract thesis. Selection being LLM-mediated with prose hints violates the determinism fundamental outright. REJECT as architecture. Two micro-patterns survive adversarial review: (1) the Provider no-side-effect contract with composition-abort signals — a sharper articulation than Hermes' current advisory-read discipline, worth writing into the Step-6 reconcile-loop contract ("digest sections are pure functions of committed state"); (2) explicit component-collision policy (later registrant declares `override`; cross-plugin override refused; first-wins+WARN otherwise) — applicable to Hermes' provider-card registration when multiple adapters claim one capability.

### 3.7 DeusData/codebase-memory-mcp
Pure-C MCP server: tree-sitter + hybrid-LSP deterministic extraction into a SQLite property graph (nodes/edges with confidence labels), BM25 search, Cypher query engine, bounded-BFS impact analysis, git-diff-driven blast radius, incremental hash-gated re-indexing, watcher-based drift detection. Explicit read/write tool annotations; miss-graph honesty about coverage limits.

**Assessment:** Unambiguously development infrastructure (~100% code-understanding; zero research-evidence surface — inspector verdict confirmed by code). It does NOT merge into the research/evidence graph: different object domain, different freshness model (mutating working tree vs. append-only history), different truth semantics (heuristic call-resolution confidence vs. provenance-closed citations). Ratified as a **development-time tool**: architecture audits, change-impact analysis before refactors, agent-development workflows on the khwarizmi-research codebase itself. Its blast-radius mechanism is conceptually the code-domain twin of Hermes' Q-04 artifact cone — a pleasing symmetry, not a reason to unify them.

## 4. Mechanism-Level Harvest Table

| # | Source | Mechanism | Problem it solves | Hermes equivalent | Superior? | Class | Score V/C/R/Cost/Rev* |
|---|---|---|---|---|---|---|---|
| M1 | sacred | Complete run record (one doc: config+sources+deps+git+seed+host) | re-run anything later | v6 §16.2 ExperimentRun (designed, unbuilt) | YES — completeness discipline | B (native reimpl) | 72/85/20/35/90 |
| M2 | sacred | Config unknown-key rejection (`ConfigAddedError`) | silent typo'd configs | gateway MALFORMED_PAYLOAD (per-intent, not config-wide) | Partially — apply pattern to program/scope configs | B | 55/90/15/20/95 |
| M3 | sacred | Observer event vocabulary + priority + swallow-mid-run | storage decoupling | Hermes journal + events | NO — Hermes stricter (triggers, validation) | F | 30/40/70/—/— |
| M4 | sacred | QUEUED-status data-convention queueing | multiplexing w/o scheduler | scheduler_lock + task graph | NO — would be 2nd orchestration layer | F | 25/30/80/—/— |
| M5 | sacred | Hierarchical seed derivation + global reseeding | statistical reproducibility | undeclared gap in v6 (seeds mentioned, hierarchy not specified) | YES at design level | B (design note) | 50/88/10/15/95 |
| M6 | nextflow | Task fingerprint: hash(script/template, inputs, params, container fingerprint) ⊕ retry-salt | safe cache/resume | §16.2/PA1 cache keys (declared, unspecified) | YES — concrete formula | B | 82/86/18/25/90 |
| M7 | nextflow | History-file + session UUID resume | resuming runs | journal replay (stronger) | NO | F | 20/35/75/—/— |
| M8 | nextflow | Channels/dataflow, executor zoo, ErrorStrategy | workflow execution | Controller tick + gateway transitions | NO — duplicate orchestration | F | 22/25/85/—/— |
| M9 | nextflow | Container fingerprint in cache key | env-aware caching | PA1 environment versioning (designed) | YES — fold into M6 | B | 70/84/15/20/90 |
| M10 | E2B | MicroVM sandbox w/ pinned templates | safe generated-code execution | `SandboxedPythonTool` placeholder (T4) | YES — only real option class | C (provider) | 78/75/30/45/85 |
| M11 | E2B | Snapshot/pause/fork (dirty-diff capture) | branching live execution state | nothing (designed nowhere) | novel — DEFER until PA1 lands | E | 58/60/35/50/80 |
| M12 | E2B | Deliberate-artifact-extraction persistence model | results escape only via governed boundary | matches Hermes immutability principles exactly | confirms design | A (as contract condition) | 65/92/12/10/95 |
| M13 | Agent-Reach | Probe-based health taxonomy (missing/broken/timeout/error) | honest availability | provider card self-report | YES for diagnostics | B | 52/85/12/15/95 |
| M14 | Agent-Reach | Capability router / installer posture | agent-facing agility | PS-03 thin-adapter + owned transport | NO — breaks recorder boundary | F | 20/15/90/—/— |
| M15 | FAROS | Validated profile before run | fail-fast misconfiguration | ScopeBrief freeze + program compile | NO — already covered | F | 25/70/30/—/— |
| M16 | FAROS | Blueprint/state-machine/artifact-schema layer | auditable pipelines | entire Hermes spine (strictly stronger) | NO | F | 18/20/88/—/— |
| M17 | eliza | Read-only Provider contract w/ abort signals | pure context assembly | advisory-read discipline (implicit) | YES — sharpen wording | B (contract wording) | 48/93/8/5/98 |
| M18 | eliza | Explicit collision policy for registrations | plugin conflicts | provider-card registration (unspecified case) | YES for multi-adapter claims | B | 42/90/10/10/97 |
| M19 | eliza | God-runtime, LLM routing, stringly registries, State bag | open extensibility | anti-pattern vs Hermes thesis | NO — inverse of fundamentals | F | 5/5/99/—/— |
| M20 | cbmem | Code knowledge graph + impact analysis | dev velocity on Hermes itself | grep/manual audit | YES as dev tool | D | 62/95/5/20/100 |
| M21 | cbmem | Merge into research/evidence graph | — | category error | NO | F | 0/0/100/—/— |

\* VALUE / COMPATIBILITY / RISK / COST / REVERSIBILITY (risk & cost lower = better)

## 5. Existing Hermes Equivalent Analysis
See table column 5; detailed equivalences: sacred observers ↔ journal+events (Hermes stronger); sacred queue ↔ scheduler dispatch (Hermes stronger); nextflow resume ↔ journal replay (Hermes stronger — replay reconstructs state, not just outputs); nextflow executors ↔ Controller tick (Hermes deliberately narrower); FAROS everything ↔ Hermes spine (strictly stronger everywhere it matters); eliza providers ↔ advisory surfaces (Hermes implicit, needs M17's sharpening). The ONLY places where Hermes has no equivalent and the external mechanism wins: M1/M6/M10 (run records, fingerprints, sandboxes) — all inside designed-but-unbuilt slices, which is why they land as design-time amendments rather than code changes.

## 6. Compatibility Review
Every ADOPT-class item was tested against the thirteen charter questions; summary of the failures that drove REJECTs: M3/M4/M7/M8 introduce second sources of truth or orchestration layers (Q7/Q8); M14 breaks provenance/redaction governance (Q10); M16 weakens single-gateway discipline (Q8/Q9); M19 delegates deterministic selection to an LLM (charter principle: deterministic computation is never LLM-delegated); M21 merges distinct domains (charter: research evidence ≠ code knowledge). The adopted items raise no new architectural assumptions: M1/M6 enrich existing designed schemas; M10 sits behind an existing port; M13/M17/M18 are contract wordings; M20 stays outside the runtime entirely.

## 7. Authority / Source-of-Truth Analysis
Post-adoption authority map is unchanged: SQLite journal remains sole authoritative store; E2B holds zero authoritative state (its Redis running-state is ephemeral scratch; Hermes records template/build/snapshot IDs as provenance facts); sacred-style run records become Hermes tables written only through existing intents/repositories; codebase-memory indexes live outside the repository and outside the journal. No external system becomes able to mutate research state. The critical rejection on these grounds: Agent-Reach (unrecorded CLI invocations = invisible effects), E2B-as-platform (control plane would own scheduling truth).

## 8. State-Machine / Lifecycle Impact
None on existing states. Future impact confined to designed slices: ExperimentRun gains sacred-derived completeness fields; PA1 cache keys gain the M6 formula (retry-salt preserves the existing RETRYING→RUNNING attempt-increment semantics — a cached hit must be keyed per attempt); sandbox states (if any) remain INSIDE the tool adapter, never entering the task state machine — a sandbox is an implementation detail of a RUNNING task, matching v6's per-task computation-environment design.

## 9. Event / Provenance Impact
No new event types required today. At PA1/T4 implementation time: sandbox executions should emit through the existing outcome/event vocabulary (execution facts as artifacts + events, hashes of extracted artifacts journaled — M12's "deliberate escape" becomes "every escape is a journaled artifact"). Replay safety holds because sandbox IDs are provenance metadata on artifacts, not state-machine inputs.

## 10. Security and Failure-Isolation Analysis
E2B-class isolation (VM/kernel boundary, per-sandbox netns + egress firewall) exceeds Hermes' current stated T4 bar and should be recorded as the reference threat model when T4 is implemented: generated code gets a dedicated kernel, default-deny egress configurable per task, no shared writable filesystem, artifacts leave only via governed APIs. Agent-Reach rejected partly on security grounds (credential-bearing CLIs invoked outside any redaction/recorder boundary). Eliza's ReDoS-bounded schema validation is a useful hardening note for Hermes' own JSON-Schema surfaces.

## 11. Capability/Provider Architecture Analysis
**Critical question 1: should Hermes have CapabilityContract → CapabilityResolver → Provider → Execution → Artifact → Provenance?**
It effectively ALREADY does, in ratified form: `ProviderContractCard` (contract) → walk-driver mode resolution (resolver) → provider adapters (provider) → driver/limiter/transport (execution) → `SourceArtifact`/outcome records (artifact) → hashes + §14 edges (provenance). The inspected trio adds nothing structural: Agent-Reach's resolver (ordered fallback) is inapplicable to Hermes' deterministic walk modes; FAROS's binding document is weaker than contract cards; eliza's interfaces are looser than the Protocol-based contracts. What SHOULD be added is small: (a) M17's explicit no-side-effect + abort-signal wording for advisory/read surfaces; (b) M18's collision policy for multi-adapter registration; (c) M13's probe-taxonomy for diagnostics. What must stay OUTSIDE the contract: credential storage details, transport ownership (stays with the driver per PS-03), any scheduling/dispatch authority, and any write path to research state.

**Critical question 2: should Hermes have Research Task → Execution Specification → Task Fingerprint → Cache Candidate → Sandboxed Execution → Immutable Result Artifact?**
YES — as the PA1/T4 slice design, with these bindings to existing machinery: the execution specification is the existing task template/spec; the fingerprint is M6 (content-hash over template+inputs+params+environment, ⊕ attempt counter); cache candidates resolve only within the same project scope (cross-project reuse prohibited by the curation invariant) and only for tasks whose gates certify identical inputs; sandboxed execution is the T4 port with E2B-class isolation as reference; the immutable result artifact enters through the EXISTING artifact write path (gateway-admitted), emits `ResultReused` (finally giving the declared event its producer) or a fresh-result event, and inherits normal S5 invalidation semantics (a retracted upstream source invalidates cached descendants through the existing cone walk). Coexistence with the state machine: cache lookup happens INSIDE dispatch (between claim and execution), is itself deterministic, and is journaled — a cache hit is an ordinary transition with a provenance edge to the reused artifact, never a bypass of `apply_intent`.

## 12. Execution Architecture Analysis
Current state: placeholders. Recommended target shape (design-level, no code): `SandboxedPythonTool` port → provider-style adapter with two backends initially (local hardened subprocess/container; E2B adapter when hosted execution is warranted); environment pinned by template/build ID recorded per execution; timeout/resource limits enforced by the sandbox, charged (eventually) to the budget ledger; artifacts extracted explicitly at task completion and hashed into the journal; crash semantics = sandbox death loses scratch, journal survives (matching E2B's "state dies with the VM" as a feature, not a bug). Snapshot/fork (M11) deferred: powerful for interactive exploration, but no ratified Hermes workflow consumes it yet; revisit at P4+ with the budget ledger.

## 13. Recommended Architectural Changes (all design-time/docs; zero code now)
R1. Amend v6 §16.2's ExperimentRun design with sacred-derived completeness requirements (M1): one recoverable record = inputs (artifact hashes), config/parameters, environment fingerprint, seeds (hierarchy per M5), code identity, outputs, host metadata. Owner of change: §16.2 amendment text at next ratification point.
R2. Specify the PA1/§16.2 cache-key formula using M6/M9: `hash(task_template_id, canonical_params, sorted(input_artifact_hashes), environment_fingerprint) ⊕ attempt_count`, STANDARD-mode content hashing (metadata mtime excluded), project-scoped lookup only. Gives `ResultReused` its producer contract.
R3. Write M12's boundary condition into the T4 sandbox contract: execution scratch is ephemeral; only extracted-and-journaled artifacts exist authoritatively; sandbox/platform identifiers are provenance metadata.
R4. Add M17's purity clause to the advisory/read-surface contracts (reconcile digest, candidate surfaces): pure functions of committed state, abortable, no side effects.
R5. Add M18's collision policy wherever multiple provider adapters may claim one capability (registration order + explicit override + cross-origin refusal).
R6. Ratify codebase-memory-mcp as sanctioned development tooling for khwarizmi-research audits (D-class), with a standing rule: its indexes never enter the repo, the journal, or CI artifacts as authority.
R7. Record E2B as the reference isolation model for T4 (threat model + boundary conditions), provider-status only, with a native fallback mandated by principle 8.

## 14. Mechanisms to Reimplement Natively
M1 (run-record completeness — as Hermes tables/intents, not Mongo docs), M2 (unknown-config-key rejection — in program/scope validators), M5 (seed hierarchy), M6/M9 (fingerprint formula — pure function over existing hashes), M13 (probe taxonomy — inside Hermes diagnostics), M17/M18 (contract clauses).

## 15. Mechanisms to Consume Through Adapters
E2B sandboxing (M10) — behind `SandboxedPythonTool`, Hermes recording everything; no other repo qualifies (sacred/nextflow/eliza/FAROS/Agent-Reach all want to BE the runtime, which is disqualifying).

## 16. Development-Time Tools
codebase-memory-mcp (M20): audits, change-impact analysis, onboarding maps of khwarizmi-research. Keep out of runtime, out of the evidence graph, out of authoritative CI gates (advisory use only).

## 17. Deferred Ideas
E2B pause/snapshot/fork (M11) until a ratified workflow consumes them (P4+, budget-ledger era); sacred heartbeat/metrics streaming until long-run observability lands (dashboard phase); nextflow trace-report richness until the reporting phase defines consumer needs.

## 18. Explicit Rejections
M3 (sacred observers — journal is stricter), M4 (QUEUED pool — second orchestrator), M7/M8 (resume/history + channels/executors — duplicate orchestration), M14 (capability-router posture — breaks recorder/redaction/provenance), M15/M16 (FAROS layers — strictly dominated by Hermes equivalents), M19 (eliza architecture — anti-compatible with determinism fundamentals), M21 (merging code graph into evidence graph — category error).

## 19. Proposed Architecture Delta
Zero lines of production code. Seven documentation-level amendments (R1–R7 above), each landing as v6 amendment text or contract-clause wording at their owning slices' next ratification points (§16.2, PA1, T4). No migrations, no new intents, no new events, no schema changes. The delta's total effect: when the execution/cache slices are eventually built, they get concrete, externally battle-tested specifications instead of blank pages — at the cost of seven paragraphs of amendment text.

## 20. Required Tests / Invariants (when slices implement R1–R3)
- Fingerprint totality: differing any hashed input ⇒ different key; differing only mtimes ⇒ same key (golden fixtures).
- Retry-salt correctness: an attempt-N retry never consumes an attempt-(N−1) cache entry.
- Project scoping: cross-project cache hits impossible (repository-layer adversarial test, per §27 item 32 discipline).
- Cache-hit path goes through the gateway: no transition, no artifact, no edge ever appears without an admitting intent; `ResultReused` emitted exactly once per hit.
- Sandbox egress default-deny; artifact extraction produces journaled hashes; killed sandbox leaves zero authoritative residue.
- S5 interaction: retracting an upstream source invalidates cached descendants (cone walk covers reuse edges).
- Purity: digest/advisory surfaces fixture-pinned no-write (existing AC-7 pattern extended to any new read surface).

## 21. Final Ratification Matrix

| Mechanism | VALUE | COMPAT | RISK | COST | REVERSIBILITY | DECISION |
|---|---|---|---|---|---|---|
| M1 sacred run-record completeness | 72 | 85 | 20 | 35 | 90 | **ADAPT** |
| M2 sacred config-key strictness | 55 | 90 | 15 | 20 | 95 | **ADAPT** |
| M5 sacred seed hierarchy | 50 | 88 | 10 | 15 | 95 | **ADAPT** |
| M6 nextflow task fingerprint | 82 | 86 | 18 | 25 | 90 | **ADAPT** |
| M9 container fingerprint in key | 70 | 84 | 15 | 20 | 90 | **ADAPT** |
| M10 E2B sandbox execution | 78 | 75 | 30 | 45 | 85 | **PROVIDER** |
| M11 E2B snapshot/fork | 58 | 60 | 35 | 50 | 80 | **DEFER** |
| M12 E2B deliberate-extraction model | 65 | 92 | 12 | 10 | 95 | **ADOPT** (contract condition) |
| M13 Agent-Reach probe taxonomy | 52 | 85 | 12 | 15 | 95 | **ADAPT** |
| M17 eliza provider purity clause | 48 | 93 | 8 | 5 | 98 | **ADAPT** |
| M18 eliza collision policy | 42 | 90 | 10 | 10 | 97 | **ADAPT** |
| M20 codebase-memory-mcp | 62 | 95 | 5 | 20 | 100 | **DEVELOPMENT TOOL** |
| M3/M4 sacred observers/queue | 30/25 | 40/30 | 70/80 | — | — | **REJECT** |
| M7/M8 nextflow resume/channels/executors | 20/22 | 35/25 | 75/85 | — | — | **REJECT** |
| M14 Agent-Reach router posture | 20 | 15 | 90 | — | — | **REJECT** |
| M15/M16 FAROS layers | 25/18 | 70/20 | 30/88 | — | — | **REJECT** |
| M19 eliza runtime architecture | 5 | 5 | 99 | — | — | **REJECT** |
| M21 code-graph → evidence-graph merge | 0 | 0 | 100 | — | — | **REJECT** |

---

### Final answer to the charter's closing question

**Which repositories should actually change the Hermes architecture, and exactly what should change?**

None change the architecture's structure — the gateway, journal, state machine, authority model, and adapter discipline survive this audit untouched, and several repos (eliza, FAROS, Agent-Reach) are instructive precisely as counter-examples that confirm the design. What changes is *specification completeness* in three not-yet-built slices: the run-record schema (from sacred), the cache-fingerprint formula (from nextflow), and the sandbox isolation/persistence contract (from E2B, consumed as a replaceable provider). Plus one sanctioned development tool (codebase-memory-mcp) kept strictly outside the runtime. Hermes' own mechanisms were already superior in every contested area — observers vs. journal, resume vs. replay, profiles vs. contract cards, component registries vs. typed contracts — and this report declines to trade that superiority for imported complexity.

*Evidence basis: six parallel live-source inspections (shallow clones at recorded commits; file-path evidence in the delegation archive) + direct verification of khwarizmi-research @ `060872c`. No Hermes files were modified.*
