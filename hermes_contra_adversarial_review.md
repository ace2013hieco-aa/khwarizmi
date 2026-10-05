# HERMES v6 — CONTRA / INTERNAL ADVERSARIAL MEMORY
## Architecture Protest & Amendment Review (Part 1)

**Role:** Hermes Research architecture-design agent — protest-first evaluation of the CONTRA research-vault design against `hermes_research_architecture_v6.md` (RATIFIED, HEAD `1279ebe`).
**Method:** every comparison below is grounded in the actual v6 text and the ratified code (`src/hermes/core/events.py`, `src/hermes/core/intents.py`), not in the source's naming. Findings are given new ids in the house style: **CT-01…CT-06** (protest/rejection) and **CT-R1…CT-R4** (reconciliation corrections, recorded in IDR-024).
**Status of this document:** Part 1 protest review. It proposes amendment text (§20) but does **not** edit the ratified v6 document — a Part 2 reconciliation/amendment step decides adoption, and any amendment to the ratified baseline requires its own decision record and the five-stage loop.

---

## 1. Executive Verdict

**MERGE INTO EXISTING V6 COMPONENTS.**

The source's headline capability — *internal contradiction detection* — already exists in Hermes, in a stronger, more governed form: §19 "Contradictions as first-class events", the `ContradictionDetected` event, the `CONTRADICTION_RESOLUTION` intent, UNCERTAIN demotion that preserves both positions ("never forces a false binary conclusion"), the `contradicts` edge in the unified edge catalog, GR3's graph-structural contradiction flagging ("the graph proposes; validated evidence decides"), GR6's contradiction-driven gap proposals, and the P11 Adversarial Research phase row. **CONTRA is not a missing subsystem; it is a missing *substrate* and a missing *distinction* inside machinery Hermes already owns.**

Three genuine gaps survive the protest, all landable inside existing components:

1. **`ResearchAssumption`** — the most valuable concept in the source. Hermes says the Adversary must "attack assumptions" (§13) and the statistical gate checks "assumptions" (§12), but no object answers *"which assumptions does this claim depend on?"* and *"which conclusions become questionable if assumption A fails?"*
2. **Contextualized contradiction handling** — Hermes treats a conflict as a `contradicts` edge / UNCERTAIN. It does not yet distinguish a *direct contradiction under materially equivalent context* from a *contextual tension* (both claims valid, different regime/timeframe/population/methodology). The source's core insight is real, and it prevents false UNCERTAIN demotions.
3. **Steelman as a structured Adversary mode** — the capability exists in spirit (S10 CONTRARIAN-angle literature; the Critique artifact), but not as a named, schema'd, artifact-cited counterargument mode.

**Rejected or deferred:** the CONTRA scheduler (cron/watcher/periodic loops) — a competing scheduler, explicitly barred; direct vault writes — violates the §21 single-writer projection; "dual-model operation" — Hermes already has S/M/C model tiers; cross-domain concept transfer — already rejected as GX3 ("no falsifiability surface; no gate it can pass"); ghost-self — deferred to P12/P13, needs mature history; a "CONTRA engine" as any kind of new authority — rejected.

**Zero new authority, zero new scheduler, zero new event types, zero new intents.** The surviving ideas become artifact rows, an Adversary mode, an extension of §19's routing, and a renderer template.

---

## 2. What the Source Adds

Stripped of its vault-loop packaging, the source contributes four ideas Hermes does not already have:

1. **Explicit assumption representation** — the claim that apparent contradictions are analyzable as *differences in premises/context* rather than disagreements.
2. **A contradiction taxonomy** — direct contradiction vs. contextual tension vs. assumption conflict vs. methodological/data/temporal/interpretation conflict, each deserving a different response.
3. **Structured steelmanning** — actively construct the strongest opposing position, artifact-cited.
4. **Longitudinal self-critique ("ghost-self")** — a mature corpus debating its own past positions.

And it contributes one governance principle Hermes already holds: *surface contradictions, never silently auto-merge or auto-resolve them*.

---

## 3. Architectural Protest — what I rejected and why

**CT-01 — REJECT: the CONTRA scheduler.** Cron, file watchers, and 6–12 hour periodic loops are a second scheduling authority. Hermes has exactly one: the Reconcile loop (§8) with scheduled re-entries governed by PA5 claim-then-deliver and tick coalescing (§19/PA5, S14 staleness scans). A CONTRA daemon/controller would violate "one authoritative mutation path," the no-competing-scheduler invariant, and the steal/prime/graph reaffirmations ("no second ... communication path, no second memory"). *Verdict: the work triggers through the existing Reconcile loop (whose responsibility (8) already says "detect contradictions") and ordinary `INSERT_TASK`/`DIRECTOR_REVIEW` admission.*

**CT-02 — REJECT: direct vault writes / authoritative notes.** The source assumes a writable markdown vault as the system of record. Hermes's §21 model is fixed: authoritative state → renderer → vault projection; `_inbox/` is the only input channel; the renderer never emits Intents; content hashes detect tampering. CONTRA artifacts follow the established pattern: `Hermes DB / artifacts → ResearchChallenge → renderer → /contra/CH-xxx.md`, regenerated from authoritative state, never read back as authority. Human decisions flow through the existing governed inbox/gate mechanism.

**CT-03 — REJECT: cross-domain concept transfer as a discovery engine.** v6 already ran this exact idea through its exclusion process: **GX3** rejected "unbounded cross-domain 'isomorphic' reasoning as a discovery engine" for having "no falsifiability surface; no gate it can pass," adopting only the bounded residue (GR4b path-sampling inside the SPECULATIVE quarantine). The source's Pass 3 is the GX3 shape. *Verdict: rejection stands; do not re-litigate; the quarantined GR4b residue is the only admissible form, and it is already in the architecture.*

**CT-04 — REJECT: "dual-model operation" as a new concept.** Hermes already operates model capability tiers (S/M/C, §13) with a recorded fallback ladder, provider diversity, and golden fixtures. Nothing in the source's two-model scheme is new; no vendor/model names belong in the architecture.

**CT-05 — REJECT: a "CONTRA engine" or `ResearchClaim` as a new authority.** Option B (CONTRA as Adversary capability) and Option C (deterministic analysis service feeding Adversary tasks) are the only shapes that survive. No new component may promote evidence, invalidate claims, approve gates, or declare scientific truth — the existing §19/GR3 boundaries already enforce this for the machinery we extend.

**CT-06 — DEFER (not reject): ghost-self.** It is the natural endpoint of "research history as an active adversary," but it requires exactly what Hermes does not yet have: mature, verifiable project history. v6 itself records that the honesty instrument "is only meaningful after real project history exists" (§27 item 9). Scheduling it before P12 would violate the manual-proof-first rule (below) against an empty corpus. Phase: P12/P13, with a history-depth trigger.

---

## 4. Real Hermes Gaps

What Hermes currently cannot do, after the protest:

| Capability (source's term) | Hermes gap? | Evidence |
|---|---|---|
| Contradiction detection | **No — exists** (§19, GR3, GR6, `ContradictionDetected`, `CONTRADICTION_RESOLUTION`, UNCERTAIN) | §19, §8, events.py:53, intents.py:35 |
| Preserve both positions, no auto-merge | **No — exists** | §19: "never forces a false binary conclusion"; GR3: "graph proposes; validated evidence decides"; R1: `contradicts` is never a cascade trigger |
| Explicit assumption representation | **Yes — genuine gap** | §13 Adversary "attack assumptions" and §12 statistical "assumptions checked" are prose; no structural `ResearchAssumption` |
| Context vs. contradiction distinction | **Yes — genuine gap** | `contradicts` handling is binary; the subject-tags screen (§10.2/§16 R1/F1) is the only structured context overlap and it is claim-type-only |
| Structured steelmanning | **Partial** — behavior exists (S10 CONTRARIAN, Critique) but no named schema'd mode | §13, §16 `Critique` |
| Longitudinal self-critique | **Yes — deferred by design** | no history exists; P12 is the standing-test phase |
| Cross-domain transfer | **No — already decided (reject)** | GX3 excluded; GR4b residue adopted |
| Scheduled execution | **No — already decided (reject)** | one Reconcile loop; PA5 claim-then-deliver |
| Manual proof before automation | **No — already the house rule** | phase discipline; P11's acceptance is fixture-based; walkthrough not yet running |

---

## 5. Overlap Analysis — CONTRA vs. the existing system

| Hermes component | Overlap with CONTRA | Resolution |
|---|---|---|
| **Adversary (§13)** | "prove the research conclusion wrong: attack assumptions, hunt leakage, find alternative explanations"; CONTRARIAN-angle literature (S10); artifact-cited `Critique` | **This is where CONTRA lives.** Steelman becomes a named mode; the extraction substrate feeds it; contradiction routing (§19) stays. Option B confirmed. |
| **§19 contradictions** | ContradictionDetected + resolution + UNCERTAIN | **Already the contradiction engine.** CONTRA adds the context/premise *distinction* (routing) and the extraction substrate — nothing else. |
| **Graph Fabric (GR3/GR6)** | `contradicts` edges; contested claims; OPEN_CONTRADICTION gaps | Graph stays derived. Contextualized challenges and assumptions are project artifacts, not graph nodes — for graph-enabled projects they may *bind* to claim nodes, never the reverse. |
| **Evidence Ladder (§10.2)** | any → UNCERTAIN on conflict | Unchanged. A ResearchChallenge never moves a ladder rung; only a *validated* conflict (Adversary finding or Validation) fires the ladder-affecting `ContradictionDetected` (R2 preserved). |
| **Reconcile (§8)** | responsibility (8) already "detect contradictions" | The trigger surface. No new loop. |
| **Obsidian (§21)** | vault projection | The challenge card is a renderer template; single writer preserved. |
| **PA8 / knowledge amendments (§16.6)** | long-term knowledge changes are evidence-cited, human-gated | Challenges are *project* advisory artifacts, never `AMEND_KNOWLEDGE` payloads; the resolution path reuses `CONTRADICTION_RESOLUTION`/`ResearchDecision`, not a new amendment kind. |

---

## 6. Claims / Assumptions Decision

**Verdict: ADOPT IN REDUCED FORM — `ResearchClaim` and `ResearchAssumption` as first-class, project-scoped, advisory §16 artifacts; no new authority.**

**Why `ResearchClaim` is not `Hypothesis` (the distinction the source forces us to make):** a `Hypothesis` is a *governed research proposition* — created by the Director, admitted through the gateway, tracked on the Evidence Ladder, referenced by the ResearchProgram, protected by human gates. A `ResearchClaim` is an *atomic assertion extracted from a research artifact* (a literature passage, a result, a note, a critique) — ungoverned, advisory, never ladder-tracked, never a `Validation` citable for promotion. The existing `Claim`/`EvidenceRecord` (§10.2, E2) is the citable-class concept bound to evidence; `ResearchClaim` is the extraction substrate *upstream* of that. The distinction is valid, so the artifact exists — but only as substrate: it inherits the "never evidence" rule (PA2/GR3) verbatim.

**Why `ResearchAssumption` is the highest-value artifact:** it answers the two questions the architecture cannot currently answer — *which assumptions does this claim depend on?* and *which conclusions become questionable if assumption A fails?* — and it is what makes apparent contradictions analyzable as premise differences (the source's core insight). Model:

```
ResearchAssumption
├── assumption_id        # content-derived: rp-style hash of statement+context
├── statement
├── context_tags         # structured, from §12 dimensions below
├── supporting_artifacts[]
├── dependent_claims[]   # back-references maintained by the validator
├── status               # ACTIVE | SUSPENDED | SUPERSEDED (advisory, not evidence)
├── provenance           # extraction source, task, model_ref
└── version              # supersession-edged like all §16 artifacts
```

Assumptions are **not** duplicated onto Hypothesis/Prediction/ResearchProgram/ExperimentSpec. They live once in the corpus layer; the governed objects may *reference* assumption ids (a ResearchProgram's methodology constraints, an ExperimentSpec's design assumptions) but never embed them. The dependency direction is: claim → assumptions; assumption → dependent claims, both maintained deterministically by the validator on extraction and on supersession.

**Why it stays advisory:** an assumption is a *declared premise*, not a verdict. Its status is derived from the corpus and human/Adversary investigation, never from an automatic promotion rule. SUSPENDED is a surfacing state, not a refutation.

**Context (§12) — ADOPT IN REDUCED FORM as structured dimension refs, not a free-form blob.** Hermes already has authoritative context carriers: `ScopeBrief` (scope), `ExperimentSpec` (conditions, methodology), `DatasetManifest` (dataset version), the ICSS-v1 regime axis (§27 item 6), timeframe via experiment windows. The artifact therefore carries a small, closed set of **context tags** (`regime`, `timeframe`, `population`, `methodology`, `dataset_ref`, `theoretical_framework`) that either *dereference* to an existing authoritative object (`dataset_ref` → DatasetManifest; `regime` → the versioned regime axis) or are free strings only where no authoritative carrier exists. The validator rejects context tags that reference a nonexistent authoritative object — the same dereference discipline IDR-022 applied to task provenance.

---

## 7. Contradiction Model

**Verdict: ADOPT AS P11 — extend §19 with a contradiction *taxonomy that is a routing function, not a labeling scheme*.** The taxonomy collapses into exactly three response classes, so it has operational meaning without becoming bureaucracy:

| Class | Definition | Routing (operational response) |
|---|---|---|
| **Direct contradiction** | A and ¬A under materially equivalent context | **Existing §19 path**: `ContradictionDetected` → UNCERTAIN (both positions preserved) → human / `DIRECTOR_REVIEW` → `CONTRADICTION_RESOLUTION` intent. |
| **Context / premise difference** (contextual tension + assumption conflict) | A and B conflict *only because* regime/timeframe/population/premise differs | **NOT a contradiction.** Advisory `ResearchChallenge` (type CONTEXTUALIZED), no UNCERTAIN, no evidence effect. Deterministic check: context-tag overlap below a threshold ⇒ route here; equal-or-higher overlap and conflicting content ⇒ direct-contradiction class. This prevents false demotions — the source's best insight, made a check. |
| **Method / data / interpretation / temporal conflict** | Same content, different methods, datasets, interpretations, or times | **Route to existing deterministic checks or §19 machinery**: methodological → gates/Adversary (M4 test-selection, statistical gate); data → DatasetManifest/data gate; interpretation → human/Director (v6 §27 item 2: irreducibly judgment); temporal → supersession/versioning (both positions already preserved by immutable artifacts) + S14 freshness. |

The classifier is deterministic on structured fields (context tags, claim refs, artifact types). The *content-level* judgment ("do these two claims actually conflict?") stays with the Adversary/LLM — but only as candidate generation; the class + routing are deterministic.

**Severity — ADOPT the anti-score stance.** No magical contradiction score. The existing `Critique` severity model (PASS / FAIL / PASS_WITH_CONCERNS, severity-ranked findings) plus a small deterministic eligibility set (§17) is the entire severity system. Severity is advisory; it never changes evidence status.

---

## 8. ResearchChallenge Design

**Verdict: ADOPT — one durable, immutable, supersession-edged artifact; minimal fields.**

```
ResearchChallenge
├── challenge_id
├── challenge_type          # DIRECT_CONTRADICTION | CONTEXTUALIZED | COUNTERARGUMENT | ASSUMPTION_FLAG
├── target_refs[]           # ResearchClaim / Hypothesis / artifact ids
├── claims[]                # the conflicting/extracted claim ids
├── assumptions[]           # assumption ids implicated (assumption conflict class)
├── context_delta           # structured: differing tags between the two sides
├── counter_evidence[]      # artifact refs, span refs where available
├── steelman                # the strongest opposing position (artifact-cited prose or refs)
├── severity                # Adversary Critique-style advisory severity
├── affected_hypotheses[]   # populated only where a governed Hypothesis is implicated
├── detection_method        # deterministic rule id | Adversary task id | human
├── model_ref               # for LLM-contributed fields (advisory provenance)
├── status                  # OPEN | INVESTIGATED | CONTEXTUALIZED | SUPERSEDED | UNRESOLVED | RESOLVED_BY_EVIDENCE
└── provenance              # → source claims → source artifacts → assumptions → analysis
```

- **Status vocabulary maps to existing Hermes semantics**: CONTEXTUALIZED = the direct-vs-context routing resolved it as a context difference; SUPERSEDED = a later claim version/amendment replaced one side (immutability preserved — supersession edge, never deletion); RESOLVED_BY_EVIDENCE = a subsequent `Validation`/experiment resolved it **through the normal ladder path**, never by the challenge itself; UNRESOLVED = acknowledged open item (surfaced, not merged).
- The artifact **cannot** change evidence status: only the existing `EVIDENCE_TRANSITION`/`CONTRADICTION_DETECTED` + §10.2 precondition path can. This is a normative rule (§14 of the amendment).
- **No new event type.** Direct contradictions fire the existing `ContradictionDetected` (§19); the challenge artifact itself is the durable record and carries `CritiqueGenerated`-class events where an Adversary task produced it. The event catalog is untouched (S6 payload bounds respected — the event references the artifact; detail lives in the artifact).

---

## 9. Steelman Design

**Verdict: ADOPT AS P11 — a named Adversary mode, one sentence of §13, one schema'd output.**

- Workflow: active claim/hypothesis → search the authoritative research corpus (deterministic retrieval over `Source[]`/claims/LitKG where graph-enabled) → Adversary (context-isolated) constructs the **strongest** opposing position → output a `Critique`-grade artifact with a `steelman` section: the position, its supporting artifact refs (span refs where available), and the premises/assumptions it rests on.
- **A steelman without artifact references is not a challenge** — it is advisory noise. The validator rejects a steelman whose claims carry no dereferenceable source refs (same discipline as GR9's closed provenance and IDR-022's dereference rule).
- The steelman feeds a `ResearchChallenge` of type COUNTERARGUMENT, which then enters the ordinary §19 routing (advisory → human/Director). It never auto-demotes the target hypothesis.

---

## 10. Cross-Domain Design

**Verdict: DEFER TO P12/P13, and confirm GX3.** The source's Pass 3 (analogous failure modes, transferred techniques, counterexamples from distant domains) is the GX3 shape — already rejected for having no falsifiability surface and no gate it can pass. The admissible residue is already in the architecture (GR4b quarantined path sampling). Nothing in this review re-opens GX3; if a future phase wants domain transfer, it must first give it a falsifiability surface and a gate — and then it will be evaluated as a new capability under the five-stage loop, not as a CONTRA default.

---

## 11. Ghost-Self Decision

**Verdict: DEFER TO P12/P13.** Past-position-vs-present-position comparison is real value, but it requires the exact thing Hermes lacks: mature verifiable history (v6 §27 item 9: the honesty instrument is only meaningful after real project history exists). Trigger when history reaches a meaningful depth — minimum artifact count, position-change events recorded, and the P12 standing integration test existing. When it ships, it is an **advisory** artifact (a longitudinal `ResearchChallenge` variant): it can surface "in month 3 you argued X; month 9 evidence argues Y" and route through the ordinary §19 path — it can never by itself declare a position wrong. **Not implemented now.**

---

## 12. Obsidian Projection

**Verdict: ADOPT — renderer template, read-derived, single writer preserved.**

```
Hermes DB / artifact store → ResearchChallenge artifact → renderer → /contra/CH-xxx.md
```

The note contains: challenge; affected claims; assumptions; contexts; source links (artifact ids + vault links where the renderer already emits them); counter-evidence refs; status; provenance; recommended next step. It is **regenerated from authoritative state** on every render pass (the §21 pipeline the Reconcile loop triggers). Edits in the note never mutate Hermes state (content hashes detect tampering; no intent path from the renderer — §18 T1). Human decisions flow through `_inbox/` → the governed intent mechanism (`CONTRADICTION_RESOLUTION` etc.) exactly as every other human action.

---

## 13. Event Model

**Verdict: zero new event types.** The catalog already has `ContradictionDetected` (§19; `events.py:53`) and `GraphContradictionFlagged` (advisory, GR3). The challenge artifact is a §16 artifact; artifact creation/status transitions are recorded by the existing project-event pattern. Payloads reference artifact ids; detail lives in the artifact (S6 4 KiB cap respected).

---

## 14. Provenance

**Verdict: no second lineage system.** Every `ResearchChallenge` carries the chain challenge → source claims → source artifacts → assumptions/context → counter-evidence → analysis, as artifact references (the existing §14 provenance edges + per-artifact `provenance` fields). "Why was this raised?" is answerable from the challenge's `detection_method`, `target_refs`, and source-claim ids; "which artifacts caused this?" from `counter_evidence`/`claims`. LLM contributions are provenance-tagged with `model_ref` but never *authoritative* lineage (the existing rule: an LLM explanation is not provenance — GR7/GX7).

---

## 15. Model Boundary

**Verdict: adopt the split, mapped onto Hermes's existing S/M/C tiers — no vendor names.**

- **Deterministic (S-tier services, no LLM in admissibility):** schema conformance of claim/assumption extraction (the S6/GR5 validation pattern), span/provenance binding, content-derived identity, context-tag dereference, the direct-vs-context classifier, duplicate suppression, eligibility/filtering, event creation, supersession handling.
- **Strong model (M):** steelman construction; contradiction interpretation; assumption surfacing prose.
- **Cheap model (C):** claim/assumption extraction candidates; tagging; preliminary candidate matching.
- The deterministic validator **decides** what enters the artifact store; LLM output is proposal-only — the exact GR1/GR5 "LLM proposes, validator decides" pattern, which this review reuses rather than reinvents.

---

## 16. Trigger Model

**Verdict: no new scheduler — existing mechanisms only.**

- **Event-triggered (primary):** new ResearchClaim/ResearchAssumption artifact, new hypothesis, new `Validation`/evidence → the Reconcile loop's existing responsibility (8) ("detect contradictions") picks up candidates and routes through `DIRECTOR_REVIEW`/Adversary tasks via ordinary `INSERT_TASK` admission.
- **Operator-triggered:** "challenge this claim" → a `DIRECTOR_REVIEW`/Adversary `INSERT_TASK` via the gateway (the only admission path).
- **Gate-triggered:** the §10.2 preconditions already include no-open-contradiction screens before PLAUSIBLE/SUPPORTED/ROBUST/REPLICATION; the challenge substrate feeds those screens, it does not add new gates.
- **Periodic:** only via the existing PA5 claim-then-deliver scheduled re-entries (S14 staleness/freshness scans) — never a cron/watcher.
- All triggers end at `apply_intent`; there is no second write path.

---

## 17. Anti-Noise / Goodhart Controls

**Verdict: adopt the deterministic, minimal set — no opaque score.**

- **Minimum context/premise overlap:** the deterministic context-tag overlap check routes context-difference candidates away from the contradiction path (and, where overlap is below the floor, suppresses the challenge entirely as noise) — the same structured-match pattern as the §10.2 subject-tags screen (R1/F1) and the S7 refuted-registry screen.
- **Duplicate suppression:** challenge identity is content-derived (claim pair + type + context hash) — a repeated candidate returns the existing challenge (the PA4 idempotency pattern applied to challenges).
- **Repeated-challenge suppression + aging:** a challenge whose status is already OPEN/INVESTIGATED for the same claim pair is not re-raised; a stale challenge (target claim superseded) is re-validated against the current version, not re-raised against history.
- **Freshness:** challenges bind to current claim versions; supersession edges mean an old challenge follows the claim's history, never auto-reopens.
- **Source-quality filtering:** venue-tier and provenance-closure checks (S2, GR9) gate which artifacts are eligible to *generate* a challenge.
- **Severity thresholds:** advisory, in the Critique model; an operator may set a project-level floor on which challenges surface to the Director. Human feedback (status transitions) is the calibration loop — P13.

---

## 18. Manual-Proof-First Policy

**Verdict: ADOPT — as an explicit rule for this capability (it is already the house phase discipline).**

```
new CONTRA/claim/assumption capability → manual proof on real research material
→ golden fixture (assertion-correctness, not behavioral drift — the S8 pattern)
→ adversarial review → only then scheduled execution
```

Concretely: the steelman mode and the context classifier ship with golden fixtures (e.g., a known-overfit result produces a steelmanned counterargument that cites the actual artifacts; a regime-different pair is classified CONTEXTUALIZED, not contradictory) before any loop runs them automatically. The P11 phase row's acceptance (a known-overfit result gets FAIL and blocks promotion) is the standing proof; nothing is scheduled against an empty corpus.

---

## 19. Phase Placement

| Mechanism | Phase | Rationale |
|---|---|---|
| `ResearchClaim`/`ResearchAssumption` extraction substrate + validator | **P7** | same phase as the first real literature integration (LitKG build, GR1 extraction) — claims/assumptions come from real sources, not from nothing |
| Contradiction contextualization (taxonomy routing) | **P11** | extends the existing §19/GR3/GR6 machinery in the Adversarial Research phase |
| Steelman mode (Adversary) | **P11** | part of structured falsification |
| Challenge projection (`/contra/`) | **P7–P11** (with the renderer) | renderer template; ships when the renderer ships, read-derived |
| Ghost-self | **P12/P13** | needs mature history + standing test |
| Cross-domain challenge | **P12/P13** | GX3 stands; only a gated, falsifiable variant could ever be considered |
| Quality calibration / feedback / noise tuning | **P13** | measurement over real history |

**Deliberately NOT in P4:** no new agent-runtime extraction loop, no scheduler, no autonomous review.

---

## 20. Exact v6 Amendment (proposed text for Part 2 — not yet applied)

### 20.1 `ResearchClaim` / `ResearchAssumption` artifacts (§16)

- **SECTION:** §16 (artifact catalog) + §12 (statistical assumption checks reference) + §13 (Adversary input surface).
- **CURRENT RULE:** claims appear as (a) the §10.2 citable-class `Claim`/`EvidenceRecord` link, and (b) graph claim nodes for graph-enabled projects (GR1/GR3); "assumptions" appear only in prose ("attack assumptions", "assumptions checked"); no artifact answers which assumptions a claim depends on.
- **NEW RULE:** `ResearchClaim` and `ResearchAssumption` are first-class, project-scoped, advisory §16 artifacts. `ResearchClaim` = an atomic assertion extracted from a research artifact (statement, `source_ref` + span refs, context tags, `assumption_ids[]`, `extracted_by`); `ResearchAssumption` = a declared premise (statement, context tags, `supporting_artifacts[]`, `dependent_claims[]`, status ACTIVE/SUSPENDED/SUPERSEDED). Both are immutable, supersession-edged, content-addressed. Both are **advisory substrate**: never a `Validation`, never ladder-citable, never a gate input (PA2/GR3 "never evidence" applies verbatim). Assumptions live once in the corpus layer; governed objects may reference assumption ids but never embed them.
- **RESPONSIBILITY OWNER:** Research Corpus layer (artifact store); deterministic `ClaimAssumptionValidator` (new deterministic service, the GR1/GR5/S6 validation pattern); extraction proposed by LLM tasks (C-tier), validated deterministically.
- **DATA MODEL:** as in §6/§8 above; `context_tags` dereference existing authoritative carriers where they exist (DatasetManifest, regime axis, ScopeBrief).
- **EVENT MODEL:** none new; artifact-creation events via the existing project-event pattern.
- **PROVENANCE:** per-artifact `provenance` + §14 edges to source artifacts and spans; LLM contributions tagged `model_ref`, never authoritative lineage.
- **MODEL BOUNDARY:** deterministic validator decides admissibility; LLM proposes extraction candidates (C-tier); M-tier for interpretation.
- **AUTHORITY LIMIT:** claims/assumptions cannot promote/refute evidence, cannot invalidate hypotheses, cannot approve or fail gates.
- **TRIGGER:** extraction via ordinary schema'd tasks admitted through the gateway (P7); supersession/amendment re-extraction only.
- **PHASE:** P7.
- **ACCEPTANCE TESTS:** same source → deterministic claim identity (content-hash); assumption stays linked to its claims across re-extraction; unknown context tag / dangling `dataset_ref` rejected; a ResearchClaim is never a citable `Validation` (structural test).
- **DEFERRED PARTS:** cross-project claim/assumption registry (global scope) — stays project-scoped; PA8-style amendment of claims (they are not knowledge amendments).

### 20.2 Contradiction contextualization (§19)

- **SECTION:** §19 (Contradictions as first-class events).
- **CURRENT RULE:** a conflict between validated evidence paths fires `ContradictionDetected` → UNCERTAIN; graph conflicts flag advisory `GRAPH_CONTRADICTION_FLAGGED`; the taxonomy is implicit.
- **NEW RULE:** the §19 detection path gains a deterministic **context/premise gate**: candidate conflicts are first compared on structured context tags. Materially equivalent context + conflicting content → the existing direct-contradiction path (UNCERTAIN, resolution). Context/premise difference → an advisory `ResearchChallenge` (type CONTEXTUALIZED or ASSUMPTION_FLAG), **no** `ContradictionDetected`, **no** UNCERTAIN, no evidence effect. Methodological/data/interpretation/temporal conflicts route per the §7 table to existing deterministic checks and the §19 human/Director path. A `ResearchChallenge` never changes evidence status; only the existing `EVIDENCE_TRANSITION`/validated-conflict path can.
- **RESPONSIBILITY OWNER:** Reconcile loop (responsibility 8) + deterministic classifier (S-tier) + Adversary (candidate interpretation).
- **DATA MODEL:** `ResearchChallenge` artifact (§8); `challenge_type` taxonomy as routing classes; `context_delta` structured.
- **EVENT MODEL:** none new — direct contradictions fire the existing `ContradictionDetected`; contextualized challenges are artifacts with project events.
- **PROVENANCE:** challenge → claims → artifacts → assumptions → analysis (§14).
- **MODEL BOUNDARY:** classification/routing deterministic; interpretation LLM-proposed, validated.
- **AUTHORITY LIMIT:** a challenge surfaces, compares, challenges, steelmans, requests investigation — never promotes/invalidates evidence, never approves gates, never declares truth. **Normative.**
- **TRIGGER:** event-triggered via Reconcile responsibility (8); gate-triggered via existing §10.2 no-open-contradiction screens; operator-triggered via `INSERT_TASK`.
- **PHASE:** P11.
- **ACCEPTANCE TESTS:** two conflicting claims → structured challenge, never auto-resolution; context-different claims (regime split) → CONTEXTUALIZED, no UNCERTAIN, no false demotion; every challenge cites source artifacts; a challenge never changes evidence status (structural test); duplicates suppressed (content-derived identity); same challenge not re-raised while OPEN.
- **DEFERRED PARTS:** interpretation-conflict adjudication (human/Director only, as today); temporal-conflict analytics beyond supersession.

### 20.3 Adversary steelman mode (§13)

- **SECTION:** §13 (Adversary role).
- **CURRENT RULE:** the Adversary proves conclusions wrong via critique (severity-ranked, artifact-cited, PASS/FAIL/PASS_WITH_CONCERNS) and receives CONTRARIAN-angle literature tasks (S10).
- **NEW RULE:** the Adversary gains a named **steelman** mode: construct the strongest opposing position to a target claim/hypothesis from the authoritative corpus, artifact-cited (span refs where available), premises/assumptions stated, output as a `Critique`-grade artifact (or `ResearchChallenge` type COUNTERARGUMENT). A steelman without dereferenceable source refs is rejected by the validator (closed-provenance discipline). The steelman is advisory; it never auto-demotes its target.
- **RESPONSIBILITY OWNER:** Adversary profile (context-isolated); deterministic retrieval over `Source[]`/claims.
- **DATA MODEL:** `Critique` gains a `steelman` section; or COUNTERARGUMENT `ResearchChallenge`.
- **EVENT MODEL:** none new (`CritiqueGenerated` where applicable).
- **PROVENANCE:** steelman claims carry artifact refs; rejection of citation-free steelman is deterministic.
- **MODEL BOUNDARY:** M-tier for construction; deterministic validator for reference admissibility.
- **AUTHORITY LIMIT:** advisory; gate-blocking only via the existing Critique verdict semantics, never via the steelman itself.
- **TRIGGER:** as §16 (event/operator/gate), through the gateway.
- **PHASE:** P11.
- **ACCEPTANCE TESTS (golden fixture):** a known-overfit result produces a steelmanned counterargument citing the actual artifacts; a citation-free steelman is rejected; the target hypothesis status is unchanged by the steelman alone.
- **DEFERRED PARTS:** automated steelman quality scoring (measurement, P13).

### 20.4 Challenge projection (§21)

- **SECTION:** §21 (vault) / §14 Layer 0 renderer.
- **CURRENT RULE:** the renderer emits typed-wikilink projections of research/evidence views; single vault writer; `_inbox/` is the only input channel.
- **NEW RULE:** the renderer gains a `/contra/` template emitting one read-derived `CH-xxx.md` per `ResearchChallenge` (challenge, claims, assumptions, contexts, source links, counter-evidence, status, provenance, recommended next step). Regenerated from authoritative state on every render pass. No edit-back path; content hashes detect tampering; human decisions flow through the governed inbox/intent mechanism only.
- **RESPONSIBILITY OWNER:** renderer (existing); Reconcile loop triggers the render (existing).
- **DATA MODEL:** none new — projection of the `ResearchChallenge` artifact.
- **EVENT MODEL:** none.
- **PROVENANCE:** rendered from the artifact's own provenance.
- **MODEL BOUNDARY:** none (rendering is deterministic).
- **AUTHORITY LIMIT:** the note is never authoritative; Obsidian remains a projection.
- **TRIGGER:** existing render pipeline.
- **PHASE:** P7–P11 with the renderer.
- **ACCEPTANCE TESTS:** a challenge renders to `/contra/`; editing the note changes nothing (structural); regeneration from state is byte-stable; no intent path from the renderer.
- **DEFERRED PARTS:** interactive challenge triage in Obsidian (through `_inbox` only, later).

### 20.5 Manual-proof-first rule (§28.5 P11 row)

- **SECTION:** §28.5 P11 row + §24 phase discipline.
- **CURRENT RULE:** P11 acceptance is fixture-based (known-overfit result gets FAIL, blocks promotion); the walkthrough is designed, not yet running.
- **NEW RULE:** the contextualization and steelman capabilities follow the explicit sequence — manual proof on real research material → golden fixture (assertion-correctness, S8 pattern) → adversarial review → scheduled execution. No autonomous loop over the corpus until the fixture suite passes.
- **RESPONSIBILITY OWNER:** implementation phases; **PHASE:** P11 (fixtures) before any P11 automation; **ACCEPTANCE TESTS:** the fixture suite is CI green before the feature can run scheduled.
- **DEFERRED PARTS:** ghost-self and cross-domain (P12/P13), quality measurement (P13).

---

## 21. Acceptance Tests (summary — the required list, mapped)

| Requirement | Test |
|---|---|
| Claim extraction determinism | Same source → same content-derived claim identity |
| Assumptions linked | Assumption `dependent_claims[]` maintained across re-extraction and supersession |
| No auto-resolution | Two conflicting claims → structured `ResearchChallenge`, never silent merge/overwrite |
| Context distinction | Regime-different claims → CONTEXTUALIZED, no UNCERTAIN, no demotion |
| Provenance | Every challenge cites source artifacts; citation-free steelman rejected |
| Evidence boundary | A challenge never changes evidence status (structural test) |
| Human boundary | No challenge automatically changes research truth (status transitions are human/Director-driven) |
| Obsidian | `/contra/` is read-derived; edits change nothing; no renderer intent path |
| No scheduler duplication | All triggers end at Reconcile/`apply_intent`; no cron/watcher/daemon (structural test) |
| Noise suppression | Duplicate challenges collapse to the existing artifact; context-below-floor candidates suppressed |
| Steelman | Output contains dereferenceable source artifact refs |
| Ghost-self | Requires history depth; advisory only (P12/P13, not now) |

---

## 22. Explicitly Rejected / Deferred Ideas

- **REJECTED:** CONTRA scheduler (cron/watcher/periodic loops) — competing authority (CT-01).
- **REJECTED:** direct vault writes / markdown as authority — §21 single-writer model (CT-02).
- **REJECTED:** cross-domain concept transfer as a discovery engine — GX3 stands (CT-03).
- **REJECTED:** "dual-model operation" as new — model tiers already exist (CT-04).
- **REJECTED:** any CONTRA "engine" with authority — Option B/C shapes only (CT-05).
- **REJECTED:** contradiction score / opaque severity — anti-score stance; Critique severity only.
- **REJECTED:** auto-merge / auto-resolve / auto-invalidate — §19 + GR3 R2 already forbid; made normative for challenges.
- **DEFERRED:** ghost-self → P12/P13 with history-depth trigger (CT-06).
- **DEFERRED:** challenge quality measurement / false-positive dashboards → P13 (honesty-instrument philosophy, never an optimization target).
- **DEFERRED:** cross-project claim/assumption registry, global-scope challenges → after multi-project topology is decided (§27 item 32).

---

## 23. Final Decision

**MERGE INTO EXISTING V6 COMPONENTS.**

The surviving ideas are: `ResearchClaim` + `ResearchAssumption` artifacts (advisory substrate, P7); the contradiction contextualization routing in §19 (P11); the Adversary steelman mode (P11); the `/contra/` renderer projection (with the renderer); the manual-proof-first rule for all of it; ghost-self and cross-domain deferred. Every one lands inside an existing component — artifact store, §19, §13 Adversary, §21 renderer, Reconcile triggers, existing events and intents. **Zero new authorities. Zero new schedulers. Zero new events. Zero new intents. No second memory, no second graph, no second evidence engine.**

The deeper capability the source points at — *Hermes using its own accumulated research history as an active adversary, surfacing contradictions, assumptions, and strongest counterarguments without becoming an autonomous scientific authority* — is already the direction of the ratified v6. This review adds the substrate (claims/assumptions) and the distinction (context vs. contradiction) that let the existing machinery do it well, and defers the parts that need a history Hermes does not yet have.
