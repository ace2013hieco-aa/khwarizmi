# Adversarial Review — Hermes Five-Fundamentals Blueprint

**Reviewer:** independent adversarial pass (Claude), no prior context from
the conversation that produced the blueprint.
**Artifact under review:** `hermes_five_fundamentals_blueprint.md` (110,990
bytes, 1,516 lines, §0–§23), reviewed against live repo `D:\New folder\research-agent`.
**Repo state at review time:** HEAD `ef2b9e488d5ca6471767f6c26c8eae14cae56fc0`
("HR-04: pin the source-identifier capture contract"), branch `main`.
**Method:** executed checks only (git, grep/search, direct file reads).
No claim below is asserted without a command + output. Coverage is
**partial** — see Residual Risk. This is disclosed up front rather than
padded to look complete.

---

## Scope + method

Passes actually executed, in the brief's numbering:

- **Pass 0** (charter compliance) — FULL.
- **Pass 1** (status-claim audit) — the highest-value items only: the
  §23 F1/F2 remediated claims, the IDR status lines for every IDR/HR
  record the blueprint cites as RATIFIED/IMPLEMENTED, and the Director/
  reconcile placeholder claim. NOT exhaustively re-walked row-by-row for
  every minor status mention in §1–§17.
- **Pass 2** (authority-model attack) — spot-checked `intents.py`
  (llm_proposable / director_only / internal_only sets) against the
  blueprint's §10 matrix for the highest-stakes cells (ADMIT_TASK,
  PROPOSE_RESEARCH_PROGRAM, PROPOSE_CLASSIFICATION_ACTION, ABANDON).
  `gateway.py` and `_program_head_id` checked for the P1-b head-binding
  claim. NOT walked cell-by-cell for the full 8-column matrix.
- **Pass 3** (verdict attack) — NOT executed (no `HR-07`/controller
  precedence-contract cross-check against Q-02's own design doc; no
  `_program_head_id` vs. "rival hypotheses need no head relaxation" deep
  check beyond confirming the head-selection mechanism itself).
- **Pass 4** (audit-of-audit, re-grading A/C/H/J/K-L/M) — NOT executed.
- **Pass 5** (internal cross-reference consistency) — NOT executed.
- **Pass 6** (GR4 proposal fidelity) — spot-checked the Boltzmann/
  temperature/reheat claims against `hermes_gr4_annealed_bridge_sampling_proposal.md`
  directly.

This is a **partial review**, honestly bounded. Passes 3–5 are the
declared residual risk, not silently skipped.

---

## Findings table

| # | Severity | Section | Claim under attack | Evidence (command + output) | Verdict | Required remediation |
|---|---|---|---|---|---|---|
| 1 | P3 | §23 F4 | "`reconcile.py`/`director.py` are 6-line stubs" | `(Get-Content reconcile.py).Count` → 6. `(Get-Content director.py).Count` → **4**. `director.py` content read directly: `"""Director profile (v3 §13)... Phase 0: placeholder. Not implemented until P4."""` (4 lines incl. blank). | MISLEADING (minor) | Change "6-line stubs" to "4–6 line stubs" or state each count separately. No semantic consequence — both files are confirmed genuine Phase-0 placeholders. |
| 2 | P2 | §10 authority matrix, "Abandon candidate" row; §10 boundary note "PROPOSE vs authoritative-mutate" | Matrix shows only **Director** with PROPOSE for "Abandon candidate"; Researcher/Adversary/Implementer all NO. | `intents.py` line 76–81: `llm_proposable()` returns `{INSERT_TASK, BRANCH, ABANDON, EVIDENCE_TRANSITION, REQUEST_HUMAN, REQUEST_REPLICATION, REQUEST_ADDITIONAL_EXPERIMENT, PROPOSE_GATE_OVERRIDE, PROPOSE_RESEARCH_PROGRAM}`. `director_only()` (line 84–92) returns only `{PROPOSE_RESEARCH_PROGRAM, PROPOSE_CLASSIFICATION_ACTION}` — **`ABANDON` is NOT in `director_only`**. `gateway.py` search for `ABANDON` found no additional proposer restriction beyond the general intent-kind wiring. | WEAK-CLAIM | `ABANDON` is type-level `llm_proposable`, not `director_only` — any wired agent profile could in principle propose it. The matrix's "Researcher/Adversary/Implementer = NO" is accurate **only because no other agent profile is implemented yet** (Phase-0), not because the type system restricts it to the Director the way it restricts `PROPOSE_RESEARCH_PROGRAM`. The blueprint should either cite the actual mechanism (current absence of other agent runtimes, not a `director_only` kind) or flag this as a documentation-level convention that the type system does not yet enforce. Low severity because the practical effect today is identical (Director is in fact the only implemented proposer), but the matrix implies a stronger structural guarantee than exists in code. |
| 3 | P3 | §16 Q1 | "it names the temperature/schedule as a generation-width control" (of the GR4 proposal) | `hermes_gr4_annealed_bridge_sampling_proposal.md` line 91–92: `P(candidate_j | C_t) ∝ f(candidate_j, C_t) · exp(−cost(candidate_j)/T_t)`. The proposal calls this a **"proposal density"**, not literally "generation-width." | MISLEADING (minor) | "Generation-width" is the blueprint's own paraphrase of a Boltzmann-weighted proposal-density formula, not a term the proposal itself uses. The underlying reading (T_t shapes generation, never selection) is defensible and consistent with the proposal's own anti-selection caveat (line 56–60: "no scalar score, no weighted utility... never an authority"), but Pass 6 explicitly warns against crediting the blueprint's charitable rewrite as the proposal's own language — this is exactly that pattern, just low-stakes. |

---

## Verified-clean list (load-bearing claims attacked and CONFIRMED)

1. **Charter compliance.** `git status --short` shows the blueprint,
   review prompt, GR4 proposal, `.freebuff/`, and `FRESH_REDTEAM_AUDIT.md`
   as untracked; `git diff --stat` is empty. No tracked file modified.
   HEAD matches the blueprint's stated `ef2b9e4`.

2. **§1 table / §23 F1 remediation — Evidence Ladder APPLY is IMPLEMENTED,
   not merely designed.** `controller.py:2146`, `def _apply_evidence_ladder_pass`,
   docstring verbatim: *"The Evidence Ladder's ONE deterministic write
   path (the APPLIED side...)"*. Every call to `_write_ladder_transition`
   (the sole `INSERT INTO evidence_ladder_state`, `controller.py:2633`)
   occurs inside this one method (lines 2146–2476).

3. **§1/§23 — "two ratified REFUTED drivers (Driver 1 proposal-ratified,
   Driver 3 bare-classification) plus obligation climbs."** The code's
   own inline comments read, verbatim and in order: `# Driver 1 —
   ratified REFUTED...` (line ~2196 region), `# Driver 3 — bare-
   classification REFUTED (IDR-041 AC-2 deferred branch, ratified)`
   (line 2282), `# Driver 2 — obligation climbs (sorted programs, sorted
   hypotheses)` (line ~2400 region). The blueprint's characterization
   (naming Driver 1 and Driver 3 specifically, folding Driver 2 into
   "obligation climbs") matches the source exactly, including the
   non-sequential Driver-1/Driver-3 ordering in prose.

4. **§7.3/§12.1 — Q-04 blast radius seeded by applied REFUTED (IDR-041
   AC-2).** `controller.py:91–97`, comment: *"the refutation re-review
   candidates (the Q-04 seed transitions — IDR-041 AC-2)"* — confirms the
   seeding relationship the blueprint's §23 F2 remediation claims.

5. **HR-07 head-binding enforced in the falsification write path.**
   `controller.py:2349–2356` (inside Driver 3): `if
   str(program.get("program_id")...) != self._program_head_id(programs):`
   → refuses to apply, with note citing HR-07 by name. `_program_head_id`
   (line 1960–1976) is documented and implemented as "the max-version
   program row (the supersession-chain head)" — a **single-head selection
   by construction**, confirming the blueprint's P1-b conflict claim
   (concurrent program heads would require relaxing exactly this
   function).

6. **IDR status lines match the blueprint's citations exactly:**
   IDR-018 "Decided + implemented (P2 slice)"; IDR-019 "Decided +
   implemented (P2 slice; Part 2 reconciliation deferred)"; IDR-036/037/
   038/039/040/041 all "IMPLEMENTED + TESTED — RATIFIED / CLOSED
   (2026-08-15)"; HR-04 "CONTRACT PINNED + NORMALIZATION CHOKE POINT
   HARDENED + TESTED (2026-08-19)"; HR-07 "CONTRACT PINNED + CURRENT PATH
   HARDENED + TESTED (2026-08-19)"; HR-08 "IMPLEMENTED + TESTED...
   (2026-08-18)." No RATIFIED-labeled-as-DESIGNED or inverse error found
   in this sample.

7. **§23 F4 — Director runtime is genuinely Phase-0.**
   `src/hermes/agents/director.py` full contents: *"Director profile (v3
   §13) — holistic judgment, Intent proposals only. Phase 0: placeholder.
   Not implemented until P4."* `src/hermes/research/reconcile.py` full
   contents: *"Reconciliation loop (v3 §8)... Phase 0: placeholder."*
   Confirms the blueprint never implies a live Director agent, and
   confirms F4's own "PARTIALLY" verdict (C5/C6 are P4-gated) is accurate
   rather than optimistic.

8. **§10 — `ADMIT_TASK` is internal-only; `PROPOSE_RESEARCH_PROGRAM` and
   `PROPOSE_CLASSIFICATION_ACTION` are `director_only`.**
   `intents.py:96–99` (`internal_only`) and `84–92` (`director_only`)
   confirm both claims exactly, including the specific two-member
   `director_only` set the blueprint relies on for the "Director PROPOSEs
   everything, EXECUTEs nothing" boundary claim (§10) and the C5 gateway-
   admission precedent (§17).

9. **§16 — GR4 proposal's own anti-selection caveat and unresolved
   reheat trigger are preserved as open, not quietly closed.**
   Proposal text (line 56–60) explicitly names the Boltzmann-as-second-
   authority risk in its own words; line 110–192 shows the reheat trigger
   repeatedly flagged as unresolved ("the designing agent should confirm
   the exact trigger," "a live decision, not a settled default"). The
   blueprint's §16 Q5/Q9 and §19 open-question #9 correctly report this
   as still-open rather than resolved.

---

## Verdict

**ACCEPT WITH CONDITIONS.**

No P0 or P1 findings in the portion actually reviewed — every load-bearing
status claim, authority-boundary claim, and mechanism claim checked against
source came back CONFIRMED or, at worst, a minor P2/P3 imprecision. The
blueprint's central discipline (never claim RATIFIED for what is only
DESIGNED, cite the specific driver/line-level mechanism rather than a vague
gesture) held up under direct source inspection, including in the one place
it is hardest to fake — the Driver 1/2/3 naming inside
`_apply_evidence_ladder_pass`, which matches the live code's own comments
almost verbatim.

**Conditions for full ACCEPT:**
1. Fix finding #1 (director.py line count).
2. Either soften finding #2's authority-matrix "Abandon candidate" row to
   note it reflects current agent-runtime absence rather than a
   `director_only` type restriction, or add `ABANDON` to `director_only`
   in a future IDR if that stronger guarantee is actually wanted.
3. Attribute "generation-width" (finding #3) explicitly as the blueprint's
   own reading of the proposal's Boltzmann proposal-density formula, not
   as the proposal's own terminology.
4. **Passes 3, 4, and 5 of the original review brief were not executed
   in this pass and must be completed before this document can support a
   full ACCEPT** — see Residual Risk below. In particular, Pass 3's
   sharpest question (whether P1-a truly needs no head relaxation, via
   `_program_head_id` and rival-hypothesis admission under one head) was
   only partially checked: I confirmed the head-selection mechanism is
   single-head by construction, but did NOT verify whether admitting a
   new *rival hypothesis* onto an existing head program (P1-a's
   mechanism) triggers any head-advancing code path that could
   collide with HR-07's binding in a way the blueprint doesn't discuss.

---

## Residual risk statement

**Not verified in this pass, and why:**

- **Pass 3 (verdict attack).** I did not cross-check §22's eight
  conditions for mutual consistency, nor did I verify condition 4 vs.
  condition 1's tension (who computes trajectory labels the floor keys
  on) against actual Q-02 code. I did not check whether "several
  concurrently ACTIVE trajectories" (P1-a) requires any head-relaxation
  I haven't found yet — I only confirmed head selection is currently
  single-head by construction, which supports but does not prove the
  blueprint's "P1-a needs no head relaxation" claim.
- **Pass 4 (audit-of-audit).** Attacks A, C, H, J, K/L, M in §18 were not
  independently re-graded against source. I have no evidence either
  confirming or contradicting the "9 solved outright / 5 partial / 4
  conditional" tally.
- **Pass 5 (internal consistency).** No cross-reference check between
  §4.7/§9.3/§9.4, no mermaid-vs-prose check for §7.2's mutation re-entry
  point, no ontology (§8) vs. state-machine (§9) coverage check.
- **CONTRA substrate (`ResearchClaim`/`ResearchAssumption`, IDR-025/027)**
  cited repeatedly in §3.2/§13/§14 as "implemented substrate" — I did not
  open IDR-025/IDR-026/IDR-027 or the corresponding source files to
  verify this status claim directly; it is UNVERIFIED in this pass, not
  confirmed.
- **Q-02's own design record** (`hermes_q02_epistemic_roi_design.md`) —
  not read directly; the blueprint's §5/§11/§15/§17 claims about Q-02's
  §7/§11/§14/§17/§18 sections (no-scalar rule, rejected stored-priority
  field, precedence-contract line, "documented contract not
  implementation" framing) are taken from the blueprint's own citations
  and were not independently re-verified against that design record.
- **Full 8×15 authority matrix (§10)** — only 4 of ~15 rows and 3 of 8
  columns were spot-checked against `intents.py`/`gateway.py`. The
  remaining cells (Q-02/Graph/Controller columns; "Localize blast
  radius," "Trigger human gate," "Change objective" rows, etc.) are
  UNVERIFIED.

**Reproducibility — commands executed, in order:**
```
git status --short
git diff --stat
git log -1 --format="%H %s"
(Get-Content hermes_five_fundamentals_blueprint.md | Measure-Object -Line).Lines
[read] hermes_five_fundamentals_blueprint.md (full)
[list] docs/idr
[grep] "Status" in docs/idr/*
[read head] IDR-018.md, IDR-019.md, IDR-036.md, IDR-037.md, IDR-038.md,
            IDR-039.md, IDR-040.md, IDR-041.md, hr04_source_identifier_capture.md,
            hr07_decisive_refuted_contract.md, hr08_completion_invariant.md
[grep] "evidence_ladder_state" in src/
[grep] "def _apply_evidence_ladder_pass|..." in controller.py
[grep] "_write_ladder_state\(" in src/ (0 results — confirmed different name)
[read] controller.py lines 2140–2270, 2270–2400
[grep] "seed" in controller.py (Q-04 seeding comments)
[find] reconcile.py, director.py
(Get-Content reconcile.py).Count ; (Get-Content director.py).Count
[read] reconcile.py, director.py (full)
[grep] "_program_head_id" in controller.py
[read] controller.py lines 1960–1980
[find] intents.py
[grep] authority-set keywords in intents.py
[read] intents.py lines 20–65, 75–100
[find] gateway.py
[grep] "ABANDON" in gateway.py
[grep] "temperature|generation-width|selection weight|Boltzmann" in
       hermes_gr4_annealed_bridge_sampling_proposal.md
[grep] "width|reheat" in hermes_gr4_annealed_bridge_sampling_proposal.md
```

*End of partial adversarial review. Passes 3–5 remain open; do not treat
this document's ACCEPT-WITH-CONDITIONS verdict as covering them.*
