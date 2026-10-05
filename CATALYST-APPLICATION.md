# Catalyst Grant Application — Khwarizmi

**Project:** Khwarizmi — governed research-agent control plane for evidence synthesis and research integrity.
**Applicant:** Ali Osat Zoghi (solo founder).
**Repository (public, MIT):** https://github.com/ace2013hieco-aa/khwarizmi
**Certified tip:** control-plane production declaration recorded 2026-10-04 (`docs/archive/CERT_GATE_RERUN_CERTIFICATION_2026-10-04.md`); suite 2,699 green with Ruff and Pyright clean.
**Annex:** [Q&A detail](CATALYST-QA-ANNEX.md)

## 1. The problem

Research agents are becoming capable of finding papers, extracting information and producing convincing answers. The harder problem is deciding whether the chain of actions and evidence behind those answers can be trusted.

This affects researchers, research teams, analysts and eventually institutions making evidence-based decisions. Today, a researcher typically performs this work manually: formulate a question, search multiple sources, inspect sources, retrieve documents, compare claims, check provenance, notice contradictions or retractions, decide whether evidence is sufficient, and document what happened. This process is repeated for essentially every non-trivial research question and becomes particularly expensive when evidence is contradictory, incomplete or high-stakes.

Existing AI research tools substantially improve discovery and synthesis, but the underlying workflow often remains centred on producing an answer. Khwarizmi addresses a different question: **can the research process itself be governed, audited and safely advanced?**

## 2. Our workflow

Khwarizmi is a research-agent control plane. A typical workflow is:

1. A researcher defines a research program and question.
2. The system decomposes the work into typed research tasks.
3. Tasks pass deterministic admission and integrity checks.
4. The research system searches approved sources.
5. Retrieved material is persisted with provenance and content identity.
6. Evidence is evaluated, including contradictions and retractions.
7. The controller determines what can safely happen next.
8. Tasks requiring human authority are parked at explicit human gates.
9. Human decisions become journaled, attributable decisions rather than invisible model outputs.
10. The resulting research state can be inspected and replayed.

The system is intentionally hybrid. Deterministic code owns state transitions, admission and governance; models can propose research actions but do not have authority to silently mutate the research state. Human reviewers retain authority over consequential decisions.

The current system is an independent CLI/control-plane system with vault-note projection, rather than a plugin embedded inside an established daily-use research application. Its architecture is deliberately designed so that research-source providers and future workbench integrations can sit behind governed interfaces. A control-plane production declaration was recorded 2026-10-04; it covers the control plane only and declares nothing about scientific validity.

## 3. Trust, audit and governance

Trust is a first-class architectural requirement rather than a post-processing feature.

Every important mutation passes through a single intent gateway. The system maintains an append-only journal, content-addressed artifacts, provenance relationships and project isolation. Provider interactions can be recorded and replayed. Source retrieval is bound to the task that requested it, preventing a worker from silently attaching evidence to another task.

The system also distinguishes trusted structural information from untrusted source content. Source text is explicitly treated as untrusted content rather than automatically becoming an instruction or authoritative fact.

Failure is data, not a hidden exception. Searches can produce typed outcomes such as empty, unavailable or shortfall states. Provider mismatches, invalid provenance, stale leases and contradictory evidence are refused rather than silently repaired. Deterministic budget envelopes bound every run; over-budget dispatches refuse with named codes, loop patterns quarantine poison tasks instead of retrying silently, and a fully-capped tick emits a named idle code.

Human authority is explicit. Contradiction resolution, source retraction and other consequential decisions require recorded human decisions. The architecture therefore provides an accountability chain from research intent → task → source → evidence/artifact → system decision → human decision.

Importantly, Khwarizmi does **not** claim that replay proves scientific validity. Replay proves that the computational/evidence handling path can be reproduced; scientific validity remains a human and domain-level question.

## 4. Team

Khwarizmi is currently founder-led by Ali Osat Zoghi, an independent researcher and software builder working across quantitative research, research methodology and agentic systems.

The founder has built the system from the architecture and governance model through implementation, testing and adversarial review. The public repository contains a substantial deterministic research-control implementation rather than a conceptual mock-up, including a full autonomy loop (planner, prompts, live fetch, safety caps, vault projection, closed-loop fault-injection test), each phase red-teamed before merging.

There are currently no formal institutional advisors or research-industry partners being claimed. A major objective of the Catalyst period would be to add domain expertise from research methodology, scholarly communication and research-infrastructure stakeholders and validate the workflow against real researcher needs.

## 5. Where we are today

Khwarizmi is a working system with a certified control plane: in production for its control-plane scope, and not yet a scaled commercial product.

Repository: https://github.com/ace2013hieco-aa/khwarizmi

The repository contains the deterministic controller, intent gateway, research-program/task model, evidence and provenance infrastructure, live allowlisted source-search/source-fetch with redirect re-validation, contradiction and retraction governance, human-decision surfaces, autonomy budget envelopes with quarantine, a journal-projecting vault, persistence and an append-only journal.

The certified tip passes 2,699 tests with Ruff and Pyright clean, including seeded fault-injection and adversarial batteries, and every autonomy phase carries a red-team audit trail in-tree. An independent reviewer built on different checks catches seeded unsupported claims that same-pipeline review misses (measured 11/12 vs 12/12 with a held-out checker, union 12/12), and that measurement ships as a test.

The important limitation is that this is not yet evidence of production adoption. The next step is to turn the existing control architecture into a researcher-facing workflow and validate it with real research tasks and users.

## 6. Alternatives & competitors

Today the problem is largely solved through a combination of conventional scholarly search, reference-management tools, spreadsheets, manual review and researcher judgement.

AI-native alternatives include:

* Elicit — research-agent, literature-review and systematic-review workflows. Elicit now provides documented, auditable evidence-synthesis workflows with source-linked claims.
* Consensus — AI-powered academic search and synthesis across a large scholarly corpus.
* ResearchRabbit — literature discovery, citation-network exploration and review organisation.
* Scite — scholarly search and Smart Citations designed to identify whether research has subsequently been supported or contradicted.

Khwarizmi is complementary rather than simply another paper-search product. Its differentiation is the **control plane around agentic research**: typed tasks, admission, provenance, deterministic authority, explicit failure states, contradiction/retraction governance, human gates and an auditable state machine. The long-term opportunity is to govern multiple research tools rather than replace every one of them.

## 7. Where this goes

The long-term vision is a **governed operating layer for agentic research**.

Researchers should be able to delegate substantial research programs to agents without delegating responsibility for the resulting decisions. Khwarizmi would coordinate discovery tools, literature systems, data tools, computational workbenches and eventually institutional research infrastructure while maintaining a common governance and provenance layer.

The commercial model would likely be B2B/B2Institution: researcher/team subscriptions initially, followed by institutional licensing, governed deployment and infrastructure/API offerings. Pricing would ultimately depend on whether the primary customer is an individual researcher, research group, university or research-intensive organisation.

The first measurable objective is not "more AI-generated text." It is reducing the **human review time required to reach an evidence-backed research decision**, while increasing detection of provenance, contradiction and integrity failures.

## 8. Fit with Digital Science

Khwarizmi directly fits the 2026 Catalyst theme, **"Agentic Workflows You Can Trust."** Digital Science describes the opportunity as AI that acts on research while carrying provenance, governance and accountability through the workflow.

The initial lifecycle wedge is **evidence synthesis and research integrity**, with adjacent applications in discovery and preparation for peer review. Khwarizmi does not attempt to automate scientific judgement itself. Instead, it governs the chain of actions and evidence leading to a research decision.

The target users are researchers and research teams who increasingly use AI but need to remain accountable for what their agents do.

Digital Science is particularly relevant because it combines research infrastructure, scholarly data and products spanning the research lifecycle.

The strongest collaboration opportunity would be to test Khwarizmi against real research workflows, integrate it with existing scholarly infrastructure, establish practical trust/audit metrics, and determine where a research-control layer creates value across the Digital Science ecosystem.

## 9. Budget

The maximum £25,000 would be used primarily to convert the existing technical prototype into a validated researcher-facing pilot:

* £9,000 — product and workflow development: researcher-facing interface, workflow orchestration, integration surfaces and deployment tooling.
* £6,000 — research validation: structured pilot studies with researchers, benchmark research tasks, failure-mode evaluation and usability testing.
* £4,000 — trust and governance evaluation: adversarial testing, provenance/audit evaluation, integrity-failure benchmarks and independent technical review.
* £3,000 — scholarly/research-domain expertise: external research-methodology and scholarly-communication advice.
* £2,000 — infrastructure and operating costs: hosting, research-data/API access, testing environments and software services.
* £1,000 — documentation and dissemination: public technical documentation, demonstrations and pilot materials.

The goal at the end of the grant would be a demonstrated multi-step research workflow with real users, measurable human-review savings, documented failure/escalation behaviour, and evidence that the governance model works outside synthetic tests.

---

# Part B — supporting detail (checklist answers)
Labels: measured results vs pilot targets are distinguished throughout; targets are explicitly marked as targets.

## 1. Which research decision does the agent affect, and who makes it today?

Decision: whether evidence is sufficiently trustworthy, relevant, internally consistent, and properly sourced to support a research conclusion — and whether a research task should proceed, pause, be rejected, or be escalated for human judgment.

Today: the researcher/PI/analyst makes that decision manually, typically by searching literature, checking sources, reconciling contradictions, checking provenance, and deciding whether the evidence is adequate.

Khwarizmi is designed to move the evidence-governance work into a deterministic, auditable control loop while keeping consequential research judgments with humans. The repository explicitly has mandatory human-gate handling and a controller/gateway architecture rather than allowing an LLM to silently make authoritative decisions.

## 2. Which lifecycle stage does it sit in?

Primary stage: evidence synthesis + research integrity.

Secondary stages are discovery and peer-review preparation.

It does not currently cover writing, funding, or peer review end-to-end, and none is claimed. Its strongest current capability is the controlled acquisition, provenance, validation, contradiction/retraction handling, and admission of research evidence.

The current repository has implemented source-search / source-fetch orchestration, content-addressed artifacts, provenance edges, retraction-aware evidence admission, contradiction/governance lifecycle, and integrity-oriented gates.

## 3. Which existing tool does it embed in, and who uses it daily?

This is the weakest point today, and it is stated as such.

Current answer: it is an independent CLI/control-plane research prototype rather than an already-deployed plugin inside a widely used research product.

The repository documents:

CLI → Controller tick/loop → intent gateway → validators → repositories → SQLite + append-only journal

and the production surface is currently this control plane, while agent profiles and several broader integrations remain deferred.

So where the application requires an existing embedded product, the answer is:

"The current prototype is not yet embedded in a third-party daily research tool; the intended users are researchers/analysts who currently perform evidence discovery and validation manually. Product integration is a next-stage deployment target."

That is considerably more credible than claiming daily active users that don't yet exist.

## 4. Proof it needs multi-step reasoning rather than a single prompt

This is one of Khwarizmi's strongest differentiators.

A representative research task is:

research question → formulate/admit research program → decompose into tasks → search → validate source/provider → fetch → persist artifacts → establish provenance → evaluate evidence → detect contradiction/retraction/integrity problems → determine next action → human gate → produce an auditable research state.

The repository implements a deterministic controller/tick loop, task graph, intent gateway, admission controls, source-search/source-fetch task handlers, persisted outcomes, provenance, and human decisions. Source fetch consumes persisted results from a previous search task rather than accepting an arbitrary hand-written list — an explicit dependency between steps.

The unit of value is not an answer; it is a reproducible chain of research actions and evidence decisions.

## 5. Where does it break — and what should it do?

Use a contradictory / insufficient / integrity-compromised evidence case.

For example:

A source search returns apparently relevant literature, but the evidence contains a provider/provenance contradiction, a retraction signal, insufficient full text, or content that cannot safely cross the untrusted-content boundary. Khwarizmi does not "reason through" the problem and invent a conclusion. It classifies the problem, refuses the unsafe transition, preserves the evidence and provenance, and escalates for human review or requests another research step.

That behavior is already reflected architecturally: the repository contains retraction-aware evidence admission, contradiction handling, typed source outcomes, provider-agreement checks, untrusted-content boundaries, and explicit human-decision surfaces.

A particularly good example: if two sources materially contradict each other, the system does not average them into an answer. It preserves both claims, records the contradiction, determines what evidence is needed to resolve it, and escalates when the system cannot safely resolve it.

## 6. Outcome metric

Reviewer-hours saved is not claimed as an existing measured result.

The primary target metric is:

Human review hours per research question reaching an evidence-backed decision.

With measurable secondary metrics:

Human intervention minutes / research task; % of evidence chains accepted without manual provenance reconstruction; % of unsupported/unsafe conclusions correctly blocked; time from research question → evidence-ready conclusion; contradiction/retraction detection rate; false-admission rate — evidence that should have been blocked but wasn't.

The headline target is: 50%+ reduction in human evidence-review time per research question, while maintaining ≥99% blocking of predefined integrity failures — stated as a target to be measured in the pilot, not an achieved result.
