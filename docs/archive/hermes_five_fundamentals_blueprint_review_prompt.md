# ADVERSARIAL REVIEW BRIEF — Five-Fundamentals Blueprint

**You are an independent adversarial reviewer.** You have no prior context
from the conversation that produced the artifact under review. Your job is
to attack it, not to confirm it. A review that finds nothing is a failed
review unless the artifact is genuinely clean — and you must prove it is
clean with executed evidence, not agreement.

---

## 1. Artifact under review

`D:\New folder\research-agent\hermes_five_fundamentals_blueprint.md`
(~111 KB, sections §0–§23). It is a **design blueprint** proposing five
"candidate fundamentals" (candidate portfolio / parallel research,
structural decomposition + preservation, conditional failure + mutation,
research allocation + exploration/exploitation, convergence + pivot) for
the `ace2013hieco-aa/khwarizmi-research` architecture. It claims to modify
nothing and to be compatible with the ratified architecture except for
named candidate extensions (C1–C6).

The blueprint already contains a hostile self-review (§23) in which the
author found and remediated two of their own errors. **Do not treat §23 as
evidence of correctness.** It is a claim, like everything else in the
document. Re-verify its remediations and hunt for what it missed.

## 2. Sources of truth (authority order — do not invert)

1. The live repository at `D:\New folder\research-agent` (branch `main`,
   HEAD `ef2b9e4`, full suite 1513 passed at time of writing). **Read the
   code, not the blueprint's description of the code.**
2. Ratified architecture: `hermes_research_architecture_v6.md` (especially
   §7 task graph, §8 gateway, §10 evidence ladder, §13 agents, §16
   artifacts, §28.2 ResearchProgram, §28.3 ActionEvaluation, §29/§30
   candidate packages).
3. Ratified IDRs in `docs/idr/` — status lines are authoritative
   (IDR-018/019/036/037/038/039/040/041 and the HR-04/07/08 records).
4. Design records: `hermes_q02_epistemic_roi_design.md`,
   `hermes_q04_failure_propagation_design_gate.md`,
   `hermes_q05_failure_classification_design.md`,
   `hermes_q05_evidence_ladder_applied_design.md`,
   `hermes_surviving_ideas_application_framework.md`.
5. The GR4 proposal `hermes_gr4_annealed_bridge_sampling_proposal.md` —
   PROPOSAL status only; never an authority.
6. The blueprint itself — **lowest authority**. Every claim it makes about
   the repository must be re-verified against layers 1–5.

## 3. Hard rules for you (the reviewer)

- **Modify nothing.** No edits to the blueprint, no edits to any repo file,
  no commits, no new branches. You produce a findings report only.
- **Trust nothing reported.** Not the blueprint, not its §23 self-review,
  not this brief's summary of the blueprint's claims, not your own prior
  knowledge. Every load-bearing fact gets an executed check (grep, read,
  git command, or test run) with the command and output recorded.
- **No fabrication.** If you cannot verify a claim, record it as
  UNVERIFIED, not as true or false.
- **Severity honesty.** Do not inflate or deflate. A wrong verdict in the
  blueprint's compatibility table is a higher-severity finding than a typo.
- **Stay in scope.** You are reviewing the blueprint against the
  repository. You are NOT re-designing the five fundamentals and NOT
  implementing anything.

## 4. Environment facts

- Repo: `D:\New folder\research-agent` (Windows; git-bash POSIX syntax in
  shells; native tools need `C:/...`-style paths).
- Test runner: `.venv/Scripts/python.exe scripts/run_tests.py` (bare
  `pytest` is broken in this repo — `hypothesis._native` import failure).
  You should not need the full suite; targeted greps/reads suffice for
  most probes. Run a targeted suite only if a probe demands behavioral
  evidence.
- Type/lint gates (if needed): `uvx pyright`, `uvx ruff` (not in `.venv`).
- Expected clean state: blueprint untracked; `git diff` empty.

## 5. Review procedure (execute in order)

### Pass 0 — Charter compliance (10 minutes)
1. `git status --short` and `git diff --stat` — confirm the blueprint is
   untracked and NO tracked file was modified. Any modification to a
   tracked file is an automatic **P0**.
2. Confirm the blueprint labels all five mechanisms as CANDIDATE/DESIGN
   QUESTIONS and never as DESIGNED/RATIFIED.
3. Confirm the GR4 proposal file is untouched and its PROPOSAL status is
   preserved wherever the blueprint cites it.

### Pass 1 — Status-claim audit (the highest-value pass)
The blueprint's §23 admits the author got two status claims wrong on the
first draft. Your task: **find the next one.** For EVERY row of §1's
"already exists" table, every "RATIFIED/IMPLEMENTED/DESIGNED/DEFERRED"
label, and every IDR citation in the document:
- Verify against `docs/idr/<IDR>.md` status lines and `src/` reality.
- Specifically re-verify the §23-remediated claims: is
  `_apply_evidence_ladder_pass` really the ladder's only write path? Are
  there really two ratified REFUTED drivers (Driver 1 proposal-ratified,
  Driver 3 bare-classification) plus obligation climbs? Is the Q-04 blast
  radius really seeded by applied REFUTED (IDR-041 AC-2)?
- Check the inverse direction too: does the blueprint call anything
  IMPLEMENTED that is only DESIGNED, or RATIFIED that is only implemented?
  (e.g., the CONTRA §29 P11 pieces, GR1–GR9, the Director runtime —
  `reconcile.py`/`director.py` are 6-line placeholders; verify the
  blueprint never implies a live Director agent.)

### Pass 2 — Authority-model attack
The blueprint's core promise: the five fundamentals add **zero new
authorities, optimizers, or schedulers**. Attack it:
1. Read §10's authority matrix cell by cell against `src/hermes/core/intents.py`
   (`llm_proposable`, `director_only`, `internal_only`), the gateway
   (`src/hermes/research/gateway.py`), and the controller. Any cell that
   grants an agent EXECUTE/YES where the code grants PROPOSE-only is a
   finding.
2. For each candidate extension C1–C6 (§21): does its described mechanism
   smuggle in a write path, a persistent state, a ranking input, or a
   dispatch influence that the ratified architecture forbids? Test each
   against: the no-scalar rule (IDR-019), the no-stored-priority rule
   (Q-02 §14), the single-mutation-path invariant (apply_intent only),
   GX1/GX2 (no graph DB, no agent graph writes), the never-evidence rule
   (PA2/GR3).
3. The exploration floor (C4) is the most dangerous one: it lives inside
   the Q-02 ordering policy. Verify the blueprint's claim that a floor is
   "a constraint on ordering, never a second scheduler." Under what
   predicate could it become one? Does the blueprint's own §18 attack A/B
   actually cover it, or did the author grade their own homework?
4. Director priority (C5): check the five conditions (§17) against the
   Q-02 design's §11/§18.2 precedence contract. Is "ratified Director
   priority > epistemic policy" actually reservable the way C5 claims, or
   does it contradict Q-02's own rejection of a priority field?

### Pass 3 — Verdict attack
For each of the five compatibility verdicts (§20):
- Find the strongest argument that the verdict is one level too optimistic
  (e.g., "compatible with extension" should really be "requires
  architectural change"). The blueprint itself flags P1-b as
  requires-architectural-change — is P1-a really free of the same
  conflict? (Check `_program_head_id` in `controller.py` and HR-07's
  head-binding: does rival-hypothesis portfolio actually need no head
  relaxation, or does "several concurrently ACTIVE trajectories" quietly
  require it?)
- Check the §22 eight conditions: are they sufficient? Are they
  consistent with each other? Does any pair contradict (e.g., condition 4
  "allocation stays inside Q-02" vs condition 1 "portfolio is a
  projection" — who computes the trajectory labels the floor keys on, and
  is that computation itself a new authority)?

### Pass 4 — Audit-of-the-audit
§18 scores the A–R attack battery "9 solved outright, 5 partially, 4
conditionally." Re-grade at least attacks A, C, H, J, K/L, M yourself:
- Is "solved" justified by a ratified mechanism, or by a candidate
  extension that doesn't exist yet? (An attack "solved" by an unbuilt C4
  is not solved outright.)
- Did the author miss any attack the brief's failure-mode list implies?
  (The original brief's list is A–R; check coverage is 1:1 and that no
  failure mode was quietly merged or dropped.)

### Pass 5 — Internal consistency
- Cross-reference every §-citation in the document (does §4.7's table
  match §9.3/§9.4? does §7.3's component table match §10's matrix?).
- Check the mermaid diagrams against their prose (e.g., §7.2's loop: does
  the mutation re-entry at ADMISSION match §4.5's mutation model?).
- Check the ontology (§8) against the state machines (§9): any entity with
  a lifecycle that the authority matrix doesn't cover?

### Pass 6 — The GR4 answers
§16 answers 10 questions about the Annealed Metropolis proposal. Read the
proposal itself and check:
- Did the blueprint misstate the proposal anywhere (strawman or
  steelman)?
- Is the "generation-width, never selection-weight" resolution actually
  what the proposal says, or the blueprint's charitable rewrite? If the
  proposal's own text supports a selection reading, that's a finding.
- Are the proposal's self-declared open questions (reheat trigger,
  schedule ownership, candidate-set bounds, phase placement) preserved as
  open, or did the blueprint quietly close them?

## 6. Findings format

Produce a report with:

1. **Findings table** — one row per finding:
   `| # | Severity | Section | Claim under attack | Evidence (command + output) | Verdict (CONFIRMED-ERROR / WEAK-CLAIM / MISLEADING / CLEAN) | Required remediation |`
   Severity scale (use the repo's convention):
   - **P0** — charter violation (something was modified) or the blueprint
     grants authority the ratified architecture forbids.
   - **P1** — a status/verdict/authority claim that is factually wrong
     against the repo and load-bearing for a conclusion.
   - **P2** — a claim that is technically true but misleading, or a gap in
     the adversarial audit's coverage.
   - **P3** — wording, cross-reference, or diagram/prose drift with no
     semantic consequence.
2. **Verified-clean list** — the load-bearing claims you attacked and
   confirmed, each with the evidence. (This is what distinguishes a real
   review from a drive-by.)
3. **Verdict** — exactly one of:
   - `REJECT` — P0 present, or P1 findings that invalidate a final answer.
   - `REVISE AND RE-REVIEW` — P1 findings, remediable.
   - `ACCEPT WITH CONDITIONS` — P2/P3 only; list the conditions.
   - `ACCEPT` — no findings above P3. (You should be suspicious of
     yourself if you land here.)
4. **Residual risk statement** — what you could NOT verify and why.

## 7. Anti-patterns you must avoid

- Do not accept "the blueprint says X, and X sounds right." Verify X.
- Do not let §23's self-review lower your guard; it proves the author is
   fallible, not that the remaining text is infallible.
- Do not propose new architecture. Your remediations point at the
  blueprint's text or at the repo's existing mechanisms, never at new
  machinery.
- Do not run the full test suite as a substitute for reading the code —
  green tests do not verify the blueprint's *claims about* the code.
- Do not edit the blueprint to fix what you find. Report it.

## 8. Deliverable

A single markdown report: `D:\New folder\research-agent\hermes_five_fundamentals_blueprint_adversarial_review.md`
(untracked, like the blueprint). Sections: scope + method, findings table,
verified-clean list, verdict, residual risks. End with the exact list of
commands you executed, so the review itself is reproducible.

**The blueprint's final answer (§22) is "yes, under eight conditions."
Your most important output is whether those eight conditions are real,
sufficient, and consistent — or whether one of them is load-bearing
fiction. Attack that question hardest.**
