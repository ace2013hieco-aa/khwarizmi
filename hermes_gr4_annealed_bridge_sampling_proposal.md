# Proposal: Annealed Metropolis Kernel as the GR4 Path-Based Method

**Status:** PROPOSAL — pre-protest, not yet run through the five-stage loop. Written for
discussion with the designing agent before any Part 1 protest review is opened. Does not
claim DESIGNED status on the state ladder and does not alter the ratified baseline (§28)
or any existing IDR.

**Targets:** `GraphHypothesisService` (v6 §5, GR4) — currently specified only as "link
prediction / bridge-path sampling... path-based methods first" with no concrete sampling
algorithm chosen. This proposal fills that gap. Phase: P7 (per §24's phase table), same
as the rest of the graph-fabric slices, which are DEFERRED/unimplemented as of v6.

**Author's note on sourcing:** the mapping below was worked out in a design conversation,
not against the live GR4 implementation (there isn't one yet). Every claim about *current*
v6 text is cited to §-numbers from `hermes_research_architecture_v6.md`; everything else
is a proposal, marked as such.

---

## 1. Motivating example (informal, for intuition only — not a Hermes literal use case)

Consider a design-space search: "cheapest way to send a package to a space station."
A candidate decomposes into an abstract function ("generate upward force") and an
implementation ("combustion-lift"). Under condition `vacuum`, combustion-lift is
infeasible. The desired behavior is: the *decomposition* survives (the graph remembers
"we need upward force, and this cheap-body sub-design was good"), only the infeasible
*implementation* branch is pruned, and the system proposes a fresh implementation
instance for the same function node — without re-deriving why fire failed.

This is structurally the same problem GR4 exists to solve for Hermes's actual domain
(literature-grounded hypothesis/claim graphs, not physical designs): given a graph node
whose current implementation is infeasible under the active evidential/data context,
propose a fresh, diverse set of alternative candidate paths through the graph, without
re-litigating history the graph already encodes.

## 2. Formal mapping (Hermes vocabulary, not the space-station toy domain)

| Design-search concept | Hermes v6 equivalent | Source |
|---|---|---|
| Abstract function node | A graph node representing a claim/hypothesis slot to be filled | GR3 claim/evidence graph, §14 |
| Implementation instance | A candidate bridge-path / link-prediction proposal | GR4, §5 |
| Condition vector `C` | The active evidential context: which sources, which schema version, which prior contradictions are live | GR2 (answerability), GR3 (contested-claim state) |
| Feasibility gate `f(instance, C)` | Schema/edge-domain conformance, entity resolution, contradiction pre-scan | `GraphValidationService`, GR1/GR5, §5 |
| Decomposition graph (persistent memory) | The LitKG / claim-evidence graph itself | GR1, GR3, §14 |
| "Fire fails in vacuum, cheap-body survives" | A pruned candidate path is discarded; the surviving sub-structure (already-validated claim/evidence edges) remains in the graph and is available to future path-sampling calls | Follows from GX2 (no LLM graph mutation) + GR1 (derived, regenerable projection) |

## 3. The conflict this proposal must resolve — flagged for the designing agent

A natural sampling rule for "propose diverse candidates weighted toward cheaper/better
ones" is Metropolis-style: `P(candidate_j) ∝ exp(−cost(candidate_j)/T)`, optionally
annealed (`T` decaying over iterations) so the process explores broadly early and
converges toward low-cost candidates later.

**This rule, used as a decision mechanism, is a scalar-weighted utility.** §27 item 38's
resolution (via IDR-019, the `ActionEvaluator`) states candidate ranking must be
"deterministic... **no scalar score, no weighted utility**, no LLM in the evaluation,
never an authority." §3d records that an "optimizer *authority* — a second Director with
a scoreboard" was rejected hard during the v6 amendment round. A Boltzmann-weighted
convergence-to-argmin process is that rejected pattern in different math, if it is what
*decides* the outcome.

**Proposed resolution — split generation from selection, using components that already
exist in the ratified/designed architecture:**

- The annealed Metropolis kernel lives *inside* `GraphHypothesisService` (GR4) as a
  **candidate generator only**. Its output is a bounded set of SPECULATIVE-by-construction
  `(candidate_path, cost, evidential_path)` tuples. It never emits a single "winner" —
  annealing here controls *exploration breadth over iterations*, not a final decision.
- Final selection among the generated candidate set is delegated to the existing
  `ActionEvaluator` (IDR-019): a deterministic multidimensional comparison with a
  documented lexicographic ordering (cost tier, feasibility, evidential-path length, etc.,
  as separately ordered criteria) — never a Boltzmann-blended scalar.

This adds no new authority and no new write path. It reuses GR4 (generation) and IDR-019
(selection) exactly as both are already specified, which satisfies §2 principle 7
("never over-engineer" / no new box) and principle 6 (burden of proof on making anything
agentic — here, nothing new becomes agentic; the sampler is a deterministic-except-for-
its-seeded-RNG algorithm, same status as any other library function).

## 4. Proposed amendment text (draft — for protest review, not final)

**SECTION:** §5 (Component Ownership), `GraphHypothesisService` row — extends GR4.

**CURRENT RULE:** "link prediction / bridge-path sampling over the LitKG producing
SPECULATIVE-by-construction candidate hypotheses with their evidential paths; path-based
methods first, embeddings behind a port (GX5); candidates never evidence." No concrete
sampling algorithm specified.

**PROPOSED RULE:** the path-based method is an annealed Metropolis kernel operating over
the feasible-candidate set at a graph node (feasibility pre-filtered by
`GraphValidationService`, GR1/GR5). Proposal density: `P(candidate_j | C_t) ∝
f(candidate_j, C_t) · exp(−cost(candidate_j)/T_t)`, renormalized over the feasible set.
`T_t` follows a **reheat-on-graph-mutation** schedule (proposed default; open question,
§6 below): reset to a high value whenever the feasible-candidate set at a node changes
(new snapshot admitted, contradiction resolved, schema amended), then anneal within that
sub-search. The kernel's *only* output is a ranked-by-generation-order candidate set
(not a single winner) passed to `ActionEvaluator` for final ranking. The kernel never
calls `apply_intent` directly (§8, single mutation path preserved) — GraphHypothesisService
remains a proposal generator, as GR4 already specifies.

**OWNER:** `GraphHypothesisService` (generation only). `ActionEvaluator` / IDR-019
(selection, unchanged — no modification to IDR-019 proposed).

**DATA MODEL:** no new tables. Candidate tuples are transient projection objects (same
status as `GraphDiagnostics` per §5's `ActionEvaluator` row — "never persisted as
evidence, never a gate input"), unless one is promoted through the *existing* SPECULATIVE
hypothesis pathway (§10.2), in which case ordinary hypothesis-artifact rules apply
unchanged.

**EVENT MODEL:** zero new events. Reheat trigger subscribes to whatever event already
signals graph-fabric regeneration (candidate: a new LitKG/claim-graph snapshot admission
or a `ContradictionResolved`-class event — **the designing agent should confirm the exact
event name; I have not verified this against source and am inferring from GR1's
"regenerable... snapshot artifact" framing and GX2's supersede pattern**).

**PROVENANCE:** every candidate tuple carries its evidential path (source artifact refs
behind every edge, per GR1/GR2's existing rule — "span refs; source refs behind every
triple"). No change to provenance rules.

**MODEL BOUNDARY:** no LLM in the sampler, in the feasibility gate, or in the final
selection. An LLM may *interpret* a selected candidate in a schema'd downstream task
(consistent with principle 1) — it does not compute cost, feasibility, or ranking.

**AUTHORITY LIMIT:** the kernel is never an authority. It cannot mark anything evidence
(inherits GR4's "candidates never evidence" + PA2's "never evidence" rule, restated at
§2 principle 3). It cannot bypass `ActionEvaluator`. It cannot mutate the graph (GX2).

**DETERMINISM / REPLAY:** the kernel's RNG must be seeded and the seed captured alongside
the `ModelClient` transcript (§5, "record/replay for regression testing"). Without this,
`GraphHypothesisService` tests are flaky or vacuous under the existing CI discipline —
proposed as a **hard acceptance-test precondition**, not optional polish.

**FALSIFIABILITY:** every generated candidate must carry a stated falsification condition
before it is eligible for downstream promotion, per the existing GX3 constraint ("no
falsifiability surface → no gate it can pass"). This is not new — GR4 already inherits it;
stated here explicitly because the annealed sampler makes it easy to forget on a losing
branch that never gets inspected.

**TRIGGER:** a graph node's feasible-candidate set changes (new snapshot, contradiction
resolved/introduced, schema amendment) — reuses whatever mechanism already fires for
graph-fabric regeneration; no new trigger surface proposed.

**PHASE:** P7, same as the rest of GR1–GR9 (unimplemented as of v6; this proposal targets
the still-open "path-based methods first" design gap, not a change to shipped code).

**ACCEPTANCE TESTS (draft, incomplete — for the designing agent to extend):**
1. Given a node with N feasible + M infeasible candidates, the sampler's output set
   contains only feasible candidates (feasibility gate is upstream, not learned).
2. Two runs with the same seed produce identical candidate sets and identical generation
   order (determinism).
3. `ActionEvaluator`'s final ranking is provably independent of `T_t`'s value or schedule
   — i.e., swapping the annealing schedule changes *which candidates exist to rank*, never
   *how ranking among a fixed candidate set is decided* (the generation/selection boundary
   is the thing under test, not the algorithm's tuning).
4. No candidate tuple is reachable from any `Validation`/evidence path without passing
   through the ordinary hypothesis pipeline (§10.2) first.
5. A candidate with no stated falsification condition is rejected before entering the
   output set (GX3).

**DEFERRED PARTS:** embedding-based cost/feasibility estimation (GX5, opt-in port,
unchanged — this proposal is path-based only, per GR4's existing "path-based methods
first" ordering); multi-node coupled search (if a decision at one node constrains
feasibility at another — e.g. sequential/dependent candidates) is explicitly **out of
scope** for this proposal and would need its own review, since it starts to look like
an MDP/MCTS problem rather than single-node bridge-path sampling, which is a materially
different authority question.

## 5. Open questions for the designing agent

1. **Exact reheat-trigger event.** I inferred a plausible hook (graph snapshot admission /
   contradiction resolution) from GR1's "regenerable... snapshot artifact" language and
   GX2's supersede pattern, but I have not verified against the actual snapshot/event
   schema. Needs source confirmation before this leaves draft.
2. **Where `T_t`'s schedule parameters live.** As a `SchemaRecord`-governed config (GR5
   pattern, engineering-plane admitted) or a per-project tunable? Global vs. per-project
   has the same curation-invariant question raised at §27 item 32/36 for LitKG scope.
3. **Bound on candidate-set size.** GR4 doesn't currently cap output cardinality; an
   annealed sampler run for many iterations could produce an unbounded candidate stream.
   Proposed: reuse PA2's bounded-continuation pattern (turn/iteration caps) rather than
   inventing a new limit — but this should be argued explicitly, not assumed.
4. **Does this actually belong in P7, or does Hermes need it sooner?** GR4 is scoped to
   literature/hypothesis graphs. If Ace's actual near-term use case (per Hermes's current
   Phase 4/5 stub state) is closer to a `ResearchProgram`/`ActionEvaluation` search than a
   literature-path search, this proposal may be premature relative to what's actually
   being built next — worth checking against the real Phase 4/5 backlog before scoping
   acceptance tests further.
5. **Is "reheat" the right default, or should it be argued against a global-cooling
   alternative (§ discussion in the design conversation this proposal originated from)?**
   Reheat trades convergence guarantees for per-state exploratory breadth; global cooling
   trades exploratory breadth (after early graph mutations) for a cleaner stopping rule.
   The designing agent should treat this as a live decision, not a settled default —
   this draft picked reheat but did not run it through adversarial review.

---

*This document is an input to a Part 1 protest review, not a substitute for one. It
should be attacked on: (a) whether the generation/selection split actually holds under
adversarial pressure, (b) whether "path-based methods first" in GR4 was ever intended to
mean something this specific, (c) whether P7 phase placement is right, and (d) anything
in §5's open questions.*
