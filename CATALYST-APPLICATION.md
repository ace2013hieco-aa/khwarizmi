# Catalyst Grant Application — Khwarizmi

**Project:** Khwarizmi — governed research-agent control plane for evidence synthesis and research integrity.
**Applicant:** Ali Osat Zoghi (solo founder).
**Repository (public, Apache-2.0):** https://github.com/ace2013hieco-aa/khwarizmi
**Certified tip (control plane only):** production declaration 2026-10-04 (`docs/archive/CERT_GATE_RERUN_CERTIFICATION_2026-10-04.md`); 4,440 collected (docs/SUITE-COUNT.md); 5 documented environmental reds (docs/MERGE-LOG-NUM-1.md); Ruff and Pyright clean.
**Annex:** [Q&A detail](CATALYST-QA-ANNEX.md)

## 1. The problem

Research agents produce convincing answers; trusting the actions and evidence behind them is the harder problem. Each non-trivial question repeats a manual loop — search, compare, check provenance, spot contradictions or retractions, judge sufficiency, document — costly when evidence is contradictory, incomplete or high-stakes. Tools improve answers; Khwarizmi asks: **can the research process itself be governed, audited and safely advanced?**

## 2. Our workflow

Khwarizmi is a research-agent control plane: a researcher defines a program and question; typed tasks pass deterministic admission checks; approved sources are searched; material persists with provenance and identity; evidence (contradictions, retractions) is evaluated; the controller decides next steps. Human-authority tasks park at explicit gates as journaled, attributable verdicts; the state can be inspected and replayed. Deterministic code owns transitions; models propose without silent-mutation authority; humans keep consequential decisions.

Standalone CLI today (vault-note projection), not a plugin; providers and workbench integrations sit behind governed interfaces. Control-plane production declaration 2026-10-04 covers the control plane only — nothing about scientific validity. Section 7 shows integration.

## 3. Trust, audit and governance

Trust is architectural. Every mutation passes a single intent gateway; append-only journal, content-addressed artifacts, provenance and project isolation record it. Providers record and replay; retrieval binds to its task. Source text stays untrusted — never instruction or fact. Failures are typed data (empty, unavailable, shortfall); mismatches, stale leases and contradictions refuse rather than self-repair. Budget envelopes bound runs with named refusal codes; loops quarantine poison tasks. Consequential decisions need recorded human verdicts. Replay reproduces the evidence path, never scientific validity.

## 4. Team

Founder-led by Ali Osat Zoghi, researcher across quantitative research, methodology and agentic systems — architecture, implementation, testing and adversarial review. No institutional advisors or industry partners are claimed; a Catalyst objective is adding methodology, scholarly-communication and infrastructure expertise and validating against real researcher needs.

## 5. Where we are today

Working system, certified control plane — production for that scope, not a scaled product. The repository holds the controller, intent gateway, task/evidence/provenance model, allowlisted search/fetch with re-validation, contradiction/retraction governance, human-decision surfaces, budget envelopes with quarantine, and the journal-projecting vault.

Fault-injection and adversarial batteries included; every autonomy phase red-teamed in-tree. A held-out checker catches seeded unsupported claims same-pipeline review misses (11/12 vs 12/12, union 12/12), shipped as a test.

Not production-adoption evidence. Next: a researcher-facing workflow validated on real tasks with real users.

## 6. Alternatives & competitors

Status quo — scholarly search, reference managers, spreadsheets, manual judgement — plus AI alternatives: Elicit (auditable evidence synthesis with source-linked claims), Consensus (academic search and synthesis), ResearchRabbit (discovery, citation networks), Scite (support/contradiction citations). Khwarizmi complements them: the control plane around agentic research — typed tasks, admission, provenance, deterministic authority, failure states, contradiction/retraction governance, human gates, auditable state — governing tools, not replacing them.

## 7. Integration path

Khwarizmi wraps researchers' tools rather than replacing them; today a standalone CLI. Integrations use three existing surfaces. **Read:** `hermes vault project` emits labelled notes (authoritative or process-only); `hermes vault verify` refuses on journal/note mismatch. **Source:** code-owned provider registry; OpenAlex and PubMed live. **Decision:** one intent gateway with role checks; human verdicts need operator credential and recorded decision; no network API yet — a plugin proposes under the same check and gains no authority.

**Obsidian first:** vault layout (one folder, human areas refused), localhost service for gates/contradictions with credentialed verdicts, community plugin for in-vault approve/reject. Status: notes untested in Obsidian; service and plugin do not exist yet.

**Zotero second:** read a collection's identifiers via its local read-only API; check metadata/retraction through governed providers; optionally write back e.g. `khwarizmi:retracted`. Zotero seeds; evidence enters only through governed fetch.

**Roadmap** (Phases 1–2 from §10's £9,000 + £6,000 lines). **Phase 1 (months 0–2):** decision service and Obsidian plugin — exit: resolve a contradiction and a retraction inside Obsidian with `hermes vault verify` still passing. **Phase 2 (months 2–4):** Zotero seed and tag write-back, pilot with 3–5 researchers — exit: review time and problem detection measured against manual process. **Phase 3 (months 4–6):** scoping with Digital Science (a scholarly-data source such as Dimensions behind the provider interface; replayable audit bundles to Figshare) — exit: a written integration plan agreed with Digital Science; no commitment is assumed.

**Unchanged:** researchers keep tools and notes; models propose, code decides state, humans decide verdicts; integrations are additive and removable — uninstall leaves CLI and journal authoritative.

## 8. Where this goes

Vision: a **governed operating layer for agentic research** — delegate programs without delegating responsibility, coordinating discovery, literature, data and compute tools under common governance. Model: B2B/B2Institution — team subscriptions, then institutional licensing, deployment and API. Objective: less **human review time per evidence-backed decision**, more integrity failures caught.

Recorded walkthrough (three demos, narrated, exit 0): https://github.com/ace2013hieco-aa/khwarizmi/releases/download/demo-2026-10-11/Demo.mp4

## 9. Fit with Digital Science

Khwarizmi fits the 2026 theme, "Agentic Workflows You Can Trust." The initial wedge is evidence synthesis and research integrity, with adjacent uses in discovery and peer-review preparation. It does not automate scientific judgement; it governs the chain of actions and evidence leading to a decision. Target users are researchers and teams who use AI but remain accountable for what their agents do.

Enhance, not compete. Digital Science supplies scholarly data, attention signals, repositories and reference management; Khwarizmi adds a replayable record of which evidence a decision depended on and who approved it. It holds no scholarly database, computes no attention scores, hosts no outputs and does not screen authors or manuscripts. Where a product already detects a problem, Khwarizmi consumes the signal, shows what depended on it and records the human decision. All four pilots are read-only, use public or non-commercial access routes and need no engineering from Digital Science.

Pilots (targets, not results; no partner or agreement exists today):
Figshare, months 0–2: pin the dataset version and file checksum an analysis cites, via the public API, and detect later changes.Dimensions, months 2–4: trace the claims and decisions that depended on a source Dimensions flags (for example retracted), checked against researchers' manual audits. We ask for pilot API access and a call on which retraction fields it exposes.Altmetric, months 2–4: rank the decisions affected by a problem source by reach, using the free counts-only API with attribution.ReadCube, months 3–5: audit an exported systematic-review library for provenance, contradiction and retraction issues; we ask for introductions to 2–3 users.

## 10. Budget

The £25,000 maximum funds a validated pilot:

* £9,000 — interface, orchestration, integration, deployment.
* £6,000 — pilot studies, benchmark tasks, failure-mode and usability evaluation.
* £4,000 — adversarial, provenance/audit and integrity-failure evaluation, independent review.
* £3,000 — research-methodology and scholarly-communication advice.
* £2,000 — hosting, data/API access, test environments.
* £1,000 — documentation, demos, pilot materials.

Goal: a real-user multi-step workflow with measured review savings, documented failure/escalation behaviour, and governance evidence beyond synthetic tests.

## Technical Validation

Synthetic control-plane baselines only — fail-closed handling, never scientific validity; replay reproduces the evidence path only. Headlines re-derived live at `258fe2b`: seeded-defect review union 12/12 (11/12 vs 12/12); end-to-end harness 51/51 with same-tree consecutive-run replay digest `219cf7c41971e3a3f6549339457d8d311728a33ee111a2a3f70077bdc97249ca` (equality across consecutive runs is the claim); hostile refusals 8/8; digest fold 5/5 fail-closed; closed-loop faults 3/3; suite 4425 passed + 15 skipped, 0 failed, all targets in §8/annex stay targets. Full methods + commands in annex §7.

License: Apache-2.0 (LICENSE).
