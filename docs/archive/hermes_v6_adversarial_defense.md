# HERMES v6 — ADVERSARIAL DEFENSE & ADJUDICATION

**Scope:** response to (a) the AR-01…AR-10 protest-stage attack on the ratified v6 baseline (§1–§28) + CONTRA candidate (§29), and (b) the IDR29-01…06 attack on the IDR-029 controller-wiring design.
**Method:** every finding was checked against the actual ratified text and the actual IDR-029 text — no finding is conceded on the reviewer's say-so, none is dismissed on the design's say-so. Dispositions: **CONFIRMED** (fix adopted), **CONFIRMED-DEFERRED** (real; explicitly deferred; re-labeled or re-specified as required), **PARTIAL** (real mechanism, overstated severity or missing counter-mechanism), **REJECTED** (misreads the text).

---

## Part A — IDR-029 findings (the design under attack)

The two P1 findings are **CONFIRMED spec gaps**, and both are remediated directly in the IDR-029 text (this is the design stage; the remediation is part of the design, not an implementation).

| ID | Disposition | Remediation |
|---|---|---|
| IDR29-01 (P1) | **CONFIRMED** | Decision 4 now specifies the exact recovery chain: stale RUNNING → `NO_SIGNAL` → second miss → `FAILED` → `RETRYING` → `RUNNING` (attempt increments) → re-acceptance idempotent. Critically, it states **A2-03 one-shot is keyed on `producing_task_id`, not `attempt`** — the idempotency survives the attempt increment (the one-shot check compares the task's persisted content hashes; `attempt` is a dispatch counter, not an identity component). The recovery pass is now part of tick discovery (scan stale-RUNNING after READY selection). Acceptance criterion 3 rewritten to assert the chain + the attempt-increment survival. |
| IDR29-02 (P1) | **CONFIRMED** | Decision 2's pseudocode now **splits the `ExtractionTaskBindingError` cases**: (a) lease race — task already left RUNNING (the from-state check would reject the transition anyway, IDR-013); the controller re-reads status, does **not** transition, logs, and recovery owns the task; (b) source/spec mismatch — task still RUNNING, `RUNNING → RETRYING/FAILED` is correct. Acceptance criterion 6 covers both branches. |
| IDR29-03 (P2) | **CONFIRMED** | Decision 4 now claims *lease-based* single-writer, explicitly **not** PA7 generation-fenced, and records that v6 §28.6 must mark the ratified §8 "every mutation path validates the caller's generation" as PA7-pending until the fencing slice lands. The reviewer is right that the ratified §8 text overstates the current guarantee; the remedy is the §28.6 notation (a ratified-text clarification, not a redesign). |
| IDR29-04 (P2) | **CONFIRMED** | Decision 5 now states the honest status: **no bounded-autonomy claim for the C-tier controller until the budget ledger lands** — "budget-capped" stays DEFERRED (v6 §28.6 already says so; nothing relabels it). A hard `max_calls_per_tick` stopgap on `extract_fn` (liveness floor, configurable, defaulted small) prevents unbounded in-tick model spinning; the ledger spec itself is the AR-02 P1-phase prerequisite, out of this slice. |
| IDR29-05 (P3) | **CONFIRMED** | Decision 3 now specifies the mode check: the tick reads the project's lifecycle state + mode (v6 §6.2) before the first dispatch; `AWAITING_HUMAN`/`PAUSED` → the tick dispatches nothing and returns `idle=waiting_human`. The wave stops because the *mode* says the project is not dispatchable — no per-gate flag. Acceptance criterion 8 updated. |
| IDR29-06 (P3) | **CONFIRMED** | Decision 3 now enumerates: a gate is a `GATE` task iff its verdict is deterministic and closed over controller-readable state; any gate requiring open-ended judgment is an `AGENT_TASK` under the owning profile — **the Adversarial gate (§12) is an `AGENT_TASK` under the Adversary profile** (its `Critique` PASS/FAIL is LLM judgment), with deterministic checks (refuted-registry screen, pre-registration compliance) as `GATE` tasks feeding it. The enumeration lives in task_plan.py (the template authority); the controller dispatches what the plan says. |

**Disposition: the two P1 findings are closed in the design text. IDR-029 remains DESIGNED — the reviewer's gate-blocking verdict is accepted *as a condition on Part 3 implementation*, which is exactly the five-stage loop's discipline.**

---

## Part B — AR findings on the ratified baseline + CONTRA candidate

### AR-01 (P1) — epistemic validity at the write path — **PARTIAL**

**What is real:** `ResearchProgramRepository` re-derives identity/hash/obligation self-consistency (EC-V6-11..16) and deliberately does **not** re-run the E1–E5 epistemic checks (§28.2 text: "The repository re-verifies artifact *self-consistency*; it does not re-run the epistemic validator"). A forged-but-self-consistent program — correct hashes, missing predictions — would persist if any code path called the repository directly.

**What the review misses:** §28.2's trust model is *layered* and the no-receipt choice is deliberate and documented — "no component may treat a caller-claimed `COMPILED` object as trustworthy." The write path is the gateway (`apply_intent`), which compiles from the *payload* (never a caller-claimed program object) and passes the validator's own result to the repository; the repository then re-derives identity so even the *validator's* output is not trusted on identity. The reviewer's own wording concedes the defense — "the gateway must never persist anything but the validator's own compiled program" — and calls it a call convention. It is not merely conventional: the repository's identity re-derivation makes any *other* path's output fail closed, and the gateway's compile-from-payload makes a caller-claimed `COMPILED` object unpresentable. The remaining gap is narrow: a code path *inside the trusted boundary* that both compiles a self-consistent-but-epistemically-invalid program *and* routes it through the gateway would need the validator itself to be wrong — at which point the E-checks are the validator's job, and re-running them in the repository would make the repository a second full validator, which §28.2 explicitly rejects (Model D: the compiler is the epistemic authority).

**Disposition:** not a P1 against anything the architecture claims as implemented — the E-checks *are* the compiler's domain and are implemented (IDR-018, 65 tests). The cheap hardening the reviewer proposes (repository re-run of the pure E-checks, or a compilation receipt) is a reasonable **phase-next candidate** — recorded as such below — but it is a defense-in-depth improvement, not a structural hole. Severity: **P2-phase-next**, not P1-gate-blocking.

### AR-02 (P1) — budget ledger unspecified — **CONFIRMED-DEFERRED**

The v6 text itself says "no budget ledger exists" (§28.6) and no section claims PA2 is implemented. The finding is therefore **confirmed as a deferred item, correctly labeled** — the architecture never claims bounded autonomy is live. What AR-02 correctly adds: the *safety claims that end in "budget-capped"* must not be relabeled as implemented when the ledger lands without a spec. The fix (a P1-phase ledger spec — turn/token/wall-clock/financial axes, single-writer, ledger entry per dispatch — before PA2 is called implemented) is adopted as a **standing phase-next requirement**. IDR29-04's honest-status amendment now makes the same point at the controller level. Severity P1 applies only to any future claim that PA2 is implemented; against the current text it is a DEFERRED item honestly marked.

### AR-03 (P1) — ThesisVerdict counter-search self-attested — **PARTIAL**

**What is real:** the round-2 compliance rule accepts `counter_search: {result: NONE_FOUND}` as a schema'd self-reported field (§9.1 line 537/555); the Researcher controls row selection and direction labels.

**What the review misses — two counter-mechanisms in the ratified text:** (1) **Round 1 is not Researcher-chosen.** The protocol (§9.1 line 553) dispatches *balanced* angles — supporting, opposing, mechanistic, meta/review, adjacent — and "CONTRARIAN routes to the Adversary profile (context-isolated)." The opposing/contrarian rows are produced by a structurally different agent with isolated context, not by the Researcher. (2) The thesis gate is a **human gate**: `ThesisEvidenceTable` + computed `ThesisVerdict` are *preconditions* at §9.1, never a self-certifying ladder rung, and the human sees the table. The verdict mapping is deterministic; the input selection is adversary-bounded and human-gated.

**What remains real:** a lazy *round 2* could still self-declare NONE_FOUND rather than dispatch the weaker-side search — the compliance rule is a validator check on a self-reported enum, and the human gate reviews the table, not the search's provenance. The reviewer's fix (NONE_FOUND requires a persisted empty-result-set artifact: query + provider response; Adversary spot-check via S8-style fixtures) is sound and cheap. **Disposition:** PARTIAL — severity P1 overstated (adversary isolation + human gate exist), but the empty-result artifact is a genuine hardening. Adopted as a **phase-next item for the thesis-mode slice** (the thesis mode is not yet implemented; the fix lands with its implementation, not as a retro-fit to ratified text).

### AR-04 (P2) — caller-role attestation — **PARTIAL**

In the *current runtime*, `proposed_by` is an intent payload field and role checks read it — the reviewer is right that this is honor-based at the dispatch layer. But the ratified §13 profile model already specifies the structural answer the reviewer proposes: tasks belong to profiles with isolated contexts; the "dispatch record" is the task row's `profile` column and the intent's provenance, both written by the controller. The gap is that the *current* gateway checks read the payload field rather than a controller-issued dispatch credential. **Disposition:** PARTIAL-CONFIRMED as a **phase-next runtime item** — when the controller lands (IDR-029's own slice), the task→profile binding in the dispatch record becomes the authoritative role source and `proposed_by` becomes provenance, exactly as AR-04's fix demands. IDR-029's controller design already writes `proposed_by` from its own dispatch context; the structural binding is the Part-3 implementation's contract.

### AR-05 (P2) — §29.2 rule 3 tag asymmetry — **CONFIRMED — fix adopted in candidate text**

The reviewer is exactly right: "differing context" is not "known context on both sides." A tag-poor claim vs. a tag-rich claim differs *because of omission*, and routing it to CONTEXTUALIZED (advisory) demotes a possibly-real contradiction by tag omission — the exact failure CT-R1 forbids ("no context difference may hide a real contradiction"). **Adopted:** rule 3 now requires equivalence on every *specified* axis; an axis present on one side and absent on the other is **unknown**, failing open to the contradiction-candidate (UNCERTAIN) path. (Applied to §29.2 rule 3 — see the amendment below.)

### AR-06 (P2) — §28.3 dimension provenance — **CONFIRMED — fix adopted in candidate text**

`dimensions{...}` is labeled "(facts from state)" but `frontier_value`/`contradiction_reduction` are *predictions of a candidate's effect*, not state reads. If proposer-estimated, the "no LLM in evaluation" rule holds for the ranking and not its inputs. **Adopted:** the schema splits dimensions — **evaluator-computed** (derived deterministically from state: `evidence_gap_closure` count, `rival_discrimination` coverage, `coverage` — the reviewer's "state reads") vs. **proposer-declared** (predictions: `frontier_value`, `contradiction_reduction` — labeled, discounted, provenance-tagged with their proposer, never ranked as if state-derived). (Applied to §28.3/§29 candidate text.)

### AR-07 (P3) — kernel→artifact poisoning — **CONFIRMED-DEFERRED**

Real, and the Data gate catches structure, not adversarial content. The kernel is PA1, which is **deferred** (P1-phase per the phase table) — nothing claims PA1 is implemented. The S6 validated-before-acceptance path this session has been hardening (the EXTRACT pipeline, the claim write path) is precisely the pattern the kernel's artifact acceptance must follow. **Disposition:** adopted as a **standing requirement on the PA1 slice** (validated-before-acceptance on kernel-produced artifacts, content-verified like every other accepted artifact), not a gap in anything currently implemented.

### AR-08 (P3) — ResearchChallenge has no retraction cascade — **CONFIRMED — fix adopted in candidate text**

Real: S5 retraction cascades walk claim edges; a `ResearchChallenge` whose `counter_evidence[]` is retracted stays OPEN with stale ammunition. **Adopted:** the §29.3 `ResearchChallenge` lifecycle gains the S5 pattern — retraction of a `counter_evidence[]` source deterministically re-routes the challenge (status → SUPERSEDED, deterministic and version-aware, already in the vocabulary) with the retraction recorded in provenance; no new event, no new authority. (Applied to §29.3 candidate text.)

### AR-09 (P3) — idempotent admit of a terminally FAILED node — **CONFIRMED**

§7 rule 2 returns "the existing node" on duplicate admission — including a terminally FAILED one. The caller receives a dead handle. The current code's behavior is confirmed (the gateway returns the existing row). **Disposition:** specified — the idempotent return of a **terminally FAILED** node is a rejection surfaced as `ATTEMPT_EXHAUSTED` (the caller must not treat a dead node as claimable), and re-admission with a fresh `attempt` is the sanctioned recovery. This is a **phase-next gateway item** (small, contained, ratified-text-consistent — it sharpens rule 2, which already keys idempotency on `idempotency_key + attempt`). IDR-029's recovery chain already assumes the controller "re-claims, never re-admits"; AR-09 closes the corner where a duplicate *admit* intent would silently return a FAILED node.

### AR-10 (P3) — closure gate ignores provider diversity — **CONFIRMED**

Cheap and correct. The §27 item 43 closure-gate record should record the verifier's `model_ref` (v6 §14.4 already requires it for judgments) so correlated-failure risk is auditable. **Disposition:** adopted as a **closure-record field for the next closure gate** (the v6 ratification's closure record is already written and ratified; the field becomes part of the closure-gate checklist going forward, not a rewrite of the past record).

---

## Part C — candidate-text amendments adopted (AR-05, AR-06, AR-08)

Three findings were CONFIRMED against **candidate** text (§29 / the CONTRA candidate), so their fixes are adopted directly in the candidate text — labeled DESIGNED, preserving the ratified baseline untouched, per the §29 amendment discipline.

1. **§29.2 rule 3 (AR-05):** equivalence requires identity on all *specified* axes; any axis present on one side and absent on the other is **unknown** → the contradiction-candidate (UNCERTAIN) path, not CONTEXTUALIZED. Tag omission can no longer demote a real contradiction.
2. **§28.3 dimensions (AR-06):** dimensions split into evaluator-computed (state-derived) vs. proposer-declared (predicted — labeled, discounted, provenance-tagged). The ranking's inputs are provenance-clean; "no LLM in evaluation" now holds for inputs and ranking alike.
3. **§29.3 ResearchChallenge (AR-08):** retraction of a `counter_evidence[]` source deterministically SUPERSEDES the challenge (existing vocabulary) with provenance; no new event, no new authority.

---

## Part D — standing phase-next items (ratified-baseline findings)

These are CONFIRMED or PARTIAL findings whose targets are **ratified** text or **deferred** slices. The ratification discipline forbids silent edits to ratified text; each is recorded as a condition on its slice's implementation, not retro-fitted:

- **AR-01:** repository re-run of the pure E-checks, or a compilation receipt the write path requires — defense-in-depth for the ResearchProgram write path. **IMPLEMENTED (post-review hardening):** `validate_program_epistemic` in `programs.py` re-runs the prediction-level E-checks (E1/E4/E5 + the contradiction rule — the checks that do NOT feed the obligation derivation) directly on the compiled program, and `ResearchProgramRepository.record` fails closed on any error at the write path (`ResearchProgramIntegrityError`, 0 rows, 0 events). E2/E3 remain covered by the existing obligation re-derivation. Regression tests `test_ar01_*` in `tests/test_research_program.py` (missing predictions, stripped rival coverage, prediction conflict — each self-consistently re-hashed, proving the pre-hardening write path would have persisted them); genuine compiles still persist. 543 passed. Model D preserved: the compiler remains the epistemic authority; the repository re-validates, it does not replace.
- **AR-02 / IDR29-04:** budget-ledger spec (axes, single-writer, per-dispatch entry) **before** any PA2 "bounded continuation" claim; controller's `max_calls_per_tick` stopgap meanwhile (already in IDR-029).
- **AR-03:** `NONE_FOUND` requires a persisted empty-result-set artifact (query + provider response); Adversary spot-check via S8-style fixtures. **IMPLEMENTED (post-review hardening):** migration 6→7 adds `empty_result_artifacts` (content-addressed `sr_<sha256>[:24]`, project-scoped, idempotent, immutable); `EmptyResultArtifactRepository` (`repositories.py`) is the write path; `validate_thesis_evidence` (`src/hermes/research/thesis.py`, pure) enforces the round-2+ rule — a `NONE_FOUND` counter-search must dereference to a persisted artifact whose recorded terms cover the declared terms, and a round-2+ table without a resolver cannot be certified (fail-closed). Regression fixtures `tests/test_thesis_ar03.py` (16 tests): uncited/undereferenceable/mismatched NONE_FOUND rejected, matching artifact accepted, FOUND-without-minority-row rejected, round-1 exempt, minority-row sufficient, cross-project artifacts unresolvable, forged ids fail closed, pure fail-closed shapes. 559 passed. The full §9.1 verdict mapping + Adversary spot-check remain part of the thesis-mode slice (S1, P1/P2/P4).
- **AR-04:** dispatch record (task row's `profile` + controller-issued provenance) becomes the authoritative role source; `proposed_by` becomes provenance — a contract on IDR-029's Part-3 controller.
- **AR-07:** validated-before-acceptance on kernel-produced artifacts — a requirement on the PA1 slice.
- **AR-09:** idempotent return of a terminally FAILED node → `ATTEMPT_EXHAUSTED` rejection; fresh-attempt re-admission is the recovery — phase-next gateway item.
- **AR-10:** closure-gate records carry the verifier's `model_ref` — added to the closure checklist.

---

## Part E — verdict

- **IDR-029:** the two P1 findings were real and are closed in the design text; the four P2/P3 findings are closed likewise. The reviewer's "MERGE WITH REMEDIATION" is accepted — as a condition on Part 3 implementation, which the five-stage loop already enforces.
- **AR-01…AR-10:** none of the ten findings is REJECTED outright; three are CONFIRMED against candidate text (fixes adopted now), five are CONFIRMED-DEFERRED or PARTIAL with standing phase-next dispositions, and the two P1s (AR-01, AR-03) are PARTIAL — real mechanisms, overstated severity, with the architecture's own counter-mechanisms (layered trust, adversary isolation, human gates) documented in the rebuttal. No finding demonstrates a structural collapse of the single-mutation-path spine; the review's own "what survives" list agrees.
