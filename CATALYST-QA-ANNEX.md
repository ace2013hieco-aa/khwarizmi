# Catalyst Grant — supporting Q&A annex

Companion to [CATALYST-APPLICATION.md](CATALYST-APPLICATION.md). Labels: measured results vs pilot targets are distinguished throughout; targets are explicitly marked as targets.

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
