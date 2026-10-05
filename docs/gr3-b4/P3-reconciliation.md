# GR3-P3-reconcile — grounded sweep / bank / redesign decision for TEXP-001, against the B4 fixtures (project khwarizmi-research, program mainline)

Status: P3-reconcile **IMPLEMENTER-DRAFT — no director verdict issued; acceptance rests with audit** — branch `gr3-b4/p3`, cut from
`gr3-b4/p2-fix` = `da79dfdbee3587b0271cb6cc211ccdb0f300edda`
(verified with `git rev-parse` before cutover, as required) and carrying
the additive twin merge at the pin `texp-001/s6-audit` =
`a927c7a7900eb63e4b6e781637ac0dc24d7cca79`. Analysis + decision only.
**NO remote push** (standing local-only order; no explicit human override
presented).

**AMENDED at `gr3-b4/p3-repair`** (from the adversary audit
`gr3-b4/p3-audit` = `d383be246094f04f317b2ed2704c36c42f6dcbf5`): audit items
**C1–C5** are applied. §D3 is re-rendered as **BANK-now**; the
coverage-as-single-predictor claim is **deleted everywhere** and replaced
by the *coverage AND rank* conjunction the cited sources state; the
probe's step convention, enumeration convention and self-description are
corrected (C2–C4); and the `gr3-b4/p3` branch-name collision is surfaced
**in** `docs/gr3-b4/ROADMAP.md` (C5). Per-item correction log:
`docs/gr3-b4/P3-repair.md`.

IDR: **no IDR is claimed, written, or advanced by this task.** `IDR-043`
stays the VOID provisional text record of P2-b4fixtures (`docs/gr3-b4/P2-b4fixtures.md` §D6);
`IDR-042` stays RESERVED for P1a. No `docs/idr/` file is written. Nothing
here decrees a number.

Human authority: **no human verdict was consumed as authority.** No
`HumanDecisionReceived` journal row and no other recorded human verdict
artifact arrived for this task. The task framing entered in-session as a
brief; because it is not a recorded artifact it binds nothing, and every
decision below is recorded on its own stated merits as an IMPLEMENTER
decision.

Untrusted content: the B4 fixture bodies are untrusted text. They entered
**only** as `UntrustedContent` through the twin's own read path, which
re-derives each fixture's sha256 from its bytes and refuses a
name/digest mismatch, a foreign namespace, a non-`SIMULATED`
consumption, unknown keys, and self-edges (`experiments/texp-001/fixtures.py`,
`B4 SOURCE`). No fixture text is quoted as instruction and no fixture is
presented as authority.

## Status

- **One new analysis script (read-only probe):**
  `tests/texp_p3_reconcile_probe.py` — consumes the B4 fixtures through
  the twin read path and measures the twin's own coverage/rank quantities
  on the pinned machinery. No `test_*` prefix, so it is not collected by
  pytest; deterministic; stdlib + twin modules only.
- **One new record (this file).** No other file is added, edited, or
  deleted.
- **`src/` is byte-untouched.** `git diff --stat da79dfd -- src` is empty
  (verified). No migration, no new table, no new intent kind, no new
  event type, no new authority, no new persistence transaction owner.
  Persistence acquisition owners stay at 18.
- **The TEXP line is read-only and untouched.** `git diff --stat a927c7a da79dfd -- experiments/texp-001`
  is `fixtures.py +181 / test_b4_source.py +165`, **0 deletions** — i.e.
  the only twin delta in this tree is the P2-inherited additive `B4 SOURCE`
  append plus its test file. This task adds nothing to either lineage.
- **No PILOT/TUNE/EVAL/HOLD execution.** Only micro-scale probes, fully
  disclosed in §Acceptance (instance generation, path-space enumeration,
  and short budget-capped chains at `B ∈ {150, 300, 600}` on the already-consumed
  PILOT seed band 1000–1005).
- No model call anywhere on the path. No writes.

## Context

### What B4 actually is (measured, not recalled)

The B4 handoff is four content-addressed `cites` graphs packaged by
P2-b4fixtures over the governed corpus (6 → 12 documents). Consumed
through the twin's own read path they measure as:

| `fixture_id` | governed sources | `cites` edges | documents touching an edge | max out-degree | mean out-degree | validator-admissible single-edge paths |
|---|---|---|---|---|---|---|
| `b4-c1-p1a-baseline` | 6 | 5 | 4 | 3 | 0.83 | **0** |
| `b4-c2-expanded-cohort` | 12 | 19 | 12 | 3 | 1.58 | **0** |
| `b4-c3-idr-design-chain` | 8 | 10 | 8 | 3 | 1.25 | **0** |
| `b4-c4-authority-spine` | 4 | 5 | 4 | 3 | 1.25 | **0** |

*Correction (P3-audit F5). The first pass printed a `documents touched`
column computed as `(edge endpoints) ∪ source_set`, which equals
`governed sources` **by construction** — the twin reader refuses a
non-governed source, so the union can never exceed the source set — i.e.
a tautology shown as a measurement. The column now carries the genuinely
independent count, `documents touching an edge` (4 / 12 / 8 / 4), and the
probe reports the tautology explicitly as
`documents_equals_sources_by_construction`.*

The twin's alphabet holds 14 classes and its admissible-sequence table 10
entries; `cites` is a member of neither (`cites_in_alphabet = false`,
asserted by
`experiments/texp-001/test_b4_source.py::test_b4_edge_type_is_not_a_twin_alphabet_member`).
Every fixture is refused by the twin's S1 validator on its very first
edge, so the admissible-path count contributed by B4 is exactly **0**.

### The decision to render

The task is the sweep / bank / redesign call for texp-001 *now that B4
exists instead of an assumed stratum*. It must be rendered against the
pinned-twin state. Three things had to be established first, and two of
them are corrections to the premise.

### (i) The quoted diagnosis is real — and it is not the pin's

The diagnosis quoted in the brief (6 % coverage; rank 137–516/700) is
**verbatim a `texp-001/p4-repilot` record**, not a pin record and not the
P4 NO-GO record:

- `texp-001/p4-repilot:experiments/texp-001/P4-repilot-report.md:122` —
  *"energy places it at rank 137–516 of ~700, far outside top-8"*;
- `:117` — *"~260 distinct candidates per run against ~3,900–4,700
  admissible walks (~6 % per run; ~15–18 % pooled over three runs;
  25,348 walks total over the six graphs), which is the same candidate
  the P4 report flagged as the open mechanism (P4 recorded 4,622 vs ~300
  evals, 6 %)"*;
- `texp-001/p4-repilot:docs/texp-001/CHANGELOG.md:28` and
  `docs/texp-001/ROADMAP.md:19` restate it.
- The **6 %** half also stands alone in the P4 record it cites:
  `texp-001/p4:experiments/texp-001/P4-report.md:19` —
  *"4,622 admissible walks at n=120 vs ~300 evals/run (6% coverage)"*.

Two definitional points matter and are easy to conflate:

1. **The two denominators are different.** "~6 %" is evaluated distinct
   candidates ÷ **admissible walks** (≈260 ÷ ≈3,900–4,700). The "~700" is
   the **pooled candidate set** (`pooled= 656…725` across the twelve
   rows), not the walk space. Rank is the planted bridge's position by
   energy **within that pooled candidate set**. So the diagnosis has two
   parts — *coverage* (is the bridge ever evaluated?) and *rank* (when it
   is, does the energy put it in the top-8?) — and the p4-repilot probe
   says both fail.
2. **`energy.py` is byte-identical between the pin and `texp-001/p4`**
   (`git diff --stat da79dfd texp-001/p4 -- experiments/texp-001/energy.py`
   is empty). So the P4 half of the diagnosis *is* comparable to the pin;
   the rich five-term energy arrives only at `p4b` (`62b8853`), and the
   rank half therefore is **not** comparable to the pin's minimal
   energy.

### (ii) The "pinned-twin state" named in the premise has never existed as a tree

This is the load-bearing correction. The premise names the state as
"S6-audit@a927c7a + P4 NO-GO record". Those are **two sibling lineages**,
not one commit:

- `git merge-base --is-ancestor a927c7a texp-001/p4` → **NO**;
  `git merge-base --is-ancestor texp-001/p4 da79dfd` → **NO**;
  `git merge-base texp-001/p4 gr3-b4/p2-fix` = `faf018d` (`texp-001/s5b`).
- The S6 line runs `s5b → s6 → s6-audit(a927c7a)`; the P4 line runs
  `s5b → 385f16f → 63a6d25 → 047cb58 (P4 lock/report, NO-GO) → p4b → p4b-fix → p4b-correct → {p4-repilot, p4b-reaudit}`.
- Consequence, checked directly: the **B4 read path exists only on the S6
  side** (`gr3-b4/p2-fix` carries it; a927c7a itself does not, it is the
  P2-inherited append), and **the diagnostic harness that produced the
  quoted numbers exists only on the P4 side**, which has **zero**
  occurrences of `B4 SOURCE` / `b4_reference_graphs` in its `fixtures.py`
  (grep-verified). **The B4 handoff and the texp-001 diagnostic have
  never coexisted in one tree.**
- The task's "line tip" is therefore the S6 pin, and "P4 NO-GO record" is
  a *side-car artifact* from a divergent line — which is why this record
  cites the pin for the read path and the P4/p4-repilot branch for the
  diagnosis, and never presents them as one state.

### (iii) What the reconciliation measured on the pinned machinery

`tests/texp_p3_reconcile_probe.py` re-derives the diagnosis's *mechanism*
on the pin alone (len-energy, `l_max = 2`, seed band 1000–1005). Two
conventions are now reported side by side, because the sampler can reach
both spaces and the difference is large [P3-audit F4]:

- **walks** — revisits permitted. This is the space the twin's sampler
  can actually reach and evaluate: `kernel.propose` has no cycle check
  (`kernel.py:114-141`). **Primary denominator.**
- **simple** — no repeated node. Deterministic, but *not* what the
  sampler draws from.

A path counts iff its **full** edge-type tuple is a member of
`ADMISSIBLE_SEQUENCES` — not merely a prefix of one; table
*prefixes* are used only to prune, never to count (`analogous_to`,
`refines` and other singletons the validator refuses are thereby
excluded — `validator.py:102-113`) [P3-audit F4]:

| n | admissible **walks** (1-edge + 2-edge = total) | node-**simple** paths (total) | planted bridge = 1 of (walks) | planted tie class (pinned len-energy) | rank interval (1-indexed) | K=8 luck ratio |
|---|---|---|---|---|---|---|
| 24 | 20 + 31 = **51** | 31 | 51 | 31 | [21, 51] | 0.258 |
| 32 | 38 + 102 = **140** | 102 | 140 | 102 | [39, 140] | 0.078 |
| 48 | 75 + 181 = **256** | 182 | 256 | 181 | [76, 256] | 0.044 |
| 120 | 518 + 4079 = **4597** | 4086 | 4597 | 4079 | [519, 4597] | 0.002 |

- **Coverage falls with scale** (evaluations ÷ admissible walks) under
  the **twin's own** step convention, `steps = budget // 2` — which is
  what `micropilot.py:80-81` and `pilot.py:90-91` / `:135-136` all pass
  [P3-audit C2]:

  | budget | steps | n=24 | n=32 | n=48 | n=120 |
  |---|---|---|---|---|---|
  | B=150 | 75 | 133.3 % | 52.1 % | 27.7 % | 1.65 % |
  | B=300 | 150 | 249.0 % | 102.9 % | 57.4 % | 3.31 % |
  | B=600 | 300 | 505.9 % | 210.0 % | 115.2 % | 6.61 % |

- **The 100 % crossing MOVES with the budget and with `steps`.** Under
  the twin's convention it sits at **(24, 32) for B=150**, (32, 48) for
  B=300, and (48, 120) for B=600. The first pass claimed the crossing
  sat "between n=32 and n=48 at both budgets": that is **withdrawn** —
  it was an artifact of a `steps = 200` constant no twin harness uses
  [P3-audit F2]. The `steps` dependence is reported directly
  (§`B_step_sensitivity`): at B=300, `steps = 400` puts the crossing at
  (48, 120) while `steps = 200` puts it at (32, 48). **No crossing
  statement in this record is harness-independent**, and the previous
  claim that `steps` "does not affect … the crossing" is deleted.
- The space grows as **W ≈ n^2.8** (51 → 4,597 across n 24 → 120; ×90.1
  for ×5 in n). With a fixed step cap the fall in coverage is therefore
  arithmetic, not a discovery: `coverage = E/W` with `E ≲ steps + 4`,
  so coverage falls as the space grows. What is measured here is the
  **space**; the coverage ratio is its reciprocal consequence.
- **Coverage does NOT order the F2 outcome — the very grid this record
  cites is the counterexample.** The p4b micro grid is **non-monotone**
  in n: at both budgets the `F2` cells are all-red at n=24, all-green at
  n=32, all-red at n=48
  (`texp-001/p4b-reaudit:experiments/texp-001/P4b-report.md`, "reading:
  ranked_pool" — `green cells (ranked_pool): 6/18`, all six at n=32).
  Coverage, by contrast, is monotone *decreasing* in n. At B=150 the
  grid's all-red n=24 sits at **133 %** coverage while its all-green
  n=32 sits at **52 %**: less coverage, better outcome. The cited source
  gives the n=24 red its own cause — the per-scale sign flip of the
  degree term, i.e. a **rank** cause (`P4b-report.md`: *"the over-chasing
  case … consistent with the per-scale sign flip of the degree term
  (anti-planted at n=24 where the planted nodes are hub-like at 1.97x
  the mean degree)"*). The mechanism is the **coverage AND rank
  conjunction**, never coverage alone — exactly what
  `P4-repilot-report.md:122-125` states (§Context (i)).
- **Honest scope of these figures.** Every row is **step-capped**
  (`steps // 4` per segment + 4 initial evaluations): B=150 → ≤ 76
  evaluations, B=300 → ≤ 152, B=600 → ≤ 304. These are therefore *what
  the twin's own harness actually spends* at those budgets — not bounds
  in either direction. The first pass's "lower bounds on the coverage a
  larger `steps` would produce" is **withdrawn as inverted**: the twin's
  `steps` are *smaller* than the old constant 200 at B=150 and B=300, so
  those old figures were upper bounds there [P3-audit F2].
- **Enumeration cap fails closed.** `ENUM_CAP` (400,000) never binds
  (max observed 4,933), and the probe now **raises** rather than
  reporting a truncated space — the old behaviour would have shrunk the
denominator and inflated coverage, the one failure mode whose bias
  favoured this record's thesis [P3-audit F4].
- The pinned energy is `float(len(path))` (`energy.py:66`), so the
  planted bridge has **no rank at all — only a tie class** (4,079 of
  4,597 walks at n=120). A K=8 output sorted by it can return the bridge
  only by luck inside the tie (≈0.2 %). This is why "rank 137–516/700"
  is a *p4b+* number: it is a property of the rich energy, not of the
  pin.
- **Method agreement with the P4 side**: p4-repilot reports
  `1-edge=3306 2-edge=22042` over its six n=120 graphs (means 551/3674);
  the repaired pin-side probe measures `518 + 4079 = 4597` at seed 1000
  and 3,466–4,933 over seeds 1000–1005 (mean 4,323), counting
  table-admissible walks. Same order, same shape — the 4,622 committed
  at P4 sits inside that range and the diagnosis **replicates at the
  level of the space**. The two sides are deliberately **not** called
  one quantity: different seeds, and the census convention is now
  *stated* rather than implied (the first pass compared its
  prefix-inflated 53/142/258/4600 against p4-repilot's totals as if they
  were the same measurement) [P3-audit F4].

### (iv) B4's scale, against the twin's strata

| | nodes / documents | directed edges | max out-degree | mean out-degree |
|---|---|---|---|---|
| B4 (all four fixtures) | 4–12 | 5–19 | 3 | 0.83–1.58 |
| twin n=24 (seed 1000) | 24 | 28 | — | — |
| twin n=120 (seed 1000) | 120 | 534 | — | — |

B4's *entire* reference corpus is smaller than the twin's **smallest**
tested stratum (12 < 24 documents; 19 ≪ 28 edges), and ~1.5 orders below
PILOT scale. The twin's `StrataParams` docstring says its knobs are
*"placeholders per spec (real scale pending B4)"*
(`experiments/texp-001/generator.py` at the pin). B4 does not fill that
slot upward — **it resolves the placeholder downward**, below the twin's
own floor. Reconciled with the measured space growth, the twin's own
budget at B4's scale would leave coverage at order **2×10³ %** (an
order-of-magnitude extrapolation of `n^-2.8` from the measured 3.31 % at
n=120, B=300, stated as such): at B4-like scale the twin's "admissible
walks are barely sampled" problem **does not exist** — which is itself a
sign that the twin's stratum sizes, not B4, are the unanchored object.

## Constraints

- **S6 non-negotiable invariants — verbatim, `AGENTS.md:12-64`** (12
  bullets; the owning certification slices P6/N9/P7/tick-loop are
  untouched by this task):

  > ## Non-negotiable architectural invariants
  >
  > These are certified and enforced in code. Do not weaken them; changes
  > near them need a design gate plus the owning certification slice
  > re-run (P6/N9/P7/tick-loop records live in `docs/archive/`).
  >
  > - Determinism owns control. No LLM/model output may decide a
  >   transition; models are routed behind ports, never authorities
  >   (`src/hermes/research/evaluation.py`, deterministic libraries only).
  > - Single mutation path: `apply_intent`
  >   (`src/hermes/research/gateway.py:3961`). Never write durable state
  >   around it — no direct repository writes from orchestration, no
  >   direct SQL mutation outside certified transaction boundaries:
  >   25 acquisition owners across persistence (16), gateway (5), and
  >   Controller (4), plus one rollback-only participant (DG-4/DG-6;
  >   details in `docs/ARCHITECTURE.md` §3.10). Most boundaries own a
  >   `BEGIN IMMEDIATE` transaction; a few intentional plain-`BEGIN`
  >   cases exist (repository creates, event-retry path, migrations,
  >   Controller floor/ladder/human-gate paths).
  > - Append-only journal (`src/hermes/core/events.py`; writer
  >   `src/hermes/persistence/repositories.py`). No DELETE exists in
  >   `src/`; supersession/invalidation are new rows/events, history is
  >   never rewritten.
  > - Replay determinism: provider bytes replay identically through
  >   `RecordedTransport` (`src/hermes/tools/providers/replay.py`);
  >   replay proves byte/evidence determinism only — never scientific
  >   validity, and never admissibility of retracted sources (N9).
  > - Human-authority fail-closed boundary: `CONTRADICTION_RESOLUTION`,
  >   `RECORD_CLASSIFICATION`, `RETRACT_SOURCE` and 6 more kinds are
  >   `internal_only` (`src/hermes/core/intents.py:144`); LLM-proposable
  >   kinds are listed at `intents.py:124`. A missing/unbound
  >   `HumanDecisionReceived` journal row refuses the command
  >   (`gateway.py`, `PROPOSAL`).
  > - Bounded payload discipline (4 KiB): event payloads are size-checked
  >   (`src/hermes/persistence/event_validation.py`); oversized verdicts
  >   refuse with `RATIONALE` before any write.
  > - Project isolation: every resolver, detector row, validator, and
  >   retraction predicate is project-scoped; cross-project citation
  >   fails closed (`EVIDENCE_DOES_NOT_RESOLVE`).
  > - Prohibited-claims discipline: never claim scientific
  >   reproducibility, never present replay as validity, never present a
  >   digest/derived view as authority.
  > - Archive-not-delete; head-only supersession (a second supersede
  >   link on one row is refused); refusal-as-data (rejections return
  >   data with codes from `gateway.py:93-109`, never silent success).
  > - Lease-fenced single writer: controller surfaces acquire the
  >   scheduler lock (`controller.py:2336`); contention returns `LOCK`;
  >   mid-tick loss aborts to `lock_lost` with rollback.
  > - Content-hash identity: `fc_`/`cx_`/`cres_`/`fx_`/`retract_` IDs are
  >   recomputed, never trusted (`contradictions.py:75`,
  >   N1 pair rule `:106`, N9 predicate
  >   `source_outcomes.py:159`).
  > - N1 contradiction semantics and N9 retraction fencing are frozen:
  >   same project/program/hypothesis, different failure class, neither
  >   party invalidated, non-empty currently-valid evidence overlap.

  Only the text above is the invariant section and only it is called
  "verbatim". What this task actually exercises is the *non-adjacency*:
  no intent kind, no event type, no authority, no mutation path, no
  persistence boundary is touched. The probe reads files and computes
  numbers; it writes nothing but stdout.
- **DG-5.** No `src/hermes/research/*` module is edited; in particular
  `ref_graphs.py` and both `corpus.py` layers are byte-unchanged. The
  probe imports the twin's experiment modules (`arms`, `energy`,
  `generator`, `kernel`, `fixtures`, `validator`) — none of which imports
  `hermes.*` at module scope — and never imports `src/`.
- **No `src/` changes in this task** — analysis + decision only.
  `git diff --stat da79dfd -- src` is empty.
- **TEXP line untouched (read-only; the twin stays pinned).** The only
  twin delta in this tree is the P2-inherited additive `B4 SOURCE` append
  (+181/0) and its test file; this task edits neither lineage, neither
  the pin nor the P4 line.
- **No PILOT/TUNE/EVAL/HOLD execution.** What ran: instance generation,
  bounded admissible-path enumeration, and chains with
  `budget ∈ {150, 300, 600}`, the twin's `steps = budget // 2`
  (plus the disclosed `steps ∈ {200, 400}` sensitivity policies), and
  `l_max = 2`, on the already-consumed PILOT seed band 1000–1005. What did **not** run: the PILOT grid, TUNE, EVAL or HOLD.
  The n=120 rows are space counts plus one bounded chain per budget on
  one graph and one algorithm seed — never a pilot result. The probe now
  states this in its own machine-readable output
  (`scale_scope`, `pilot_grid_executed: false`) instead of the previous
  false `micro_scale_only: true` flag [P3-audit F4].
- **S6 / DG-5 / no pushes** as above. Local commit only.
- **Governance collision, recorded not resolved:** `docs/gr3-b4/ROADMAP.md`
  charters the `gr3-b4/p3` slot for *"Graph-structural contradiction
  flagging … (TBD, charter first)"*, with N1/N9 preserved verbatim. This
  task consumes that branch name for a TEXP reconciliation that the
  ROADMAP does not describe, and **no charter for the contradiction-flags
  P3 was presented.** Recorded here as an open governance discrepancy for
  the director, and (C5, repair pass) now surfaced **in the tracker
  itself**: `docs/gr3-b4/ROADMAP.md` is amended so the `gr3-b4/p3` row
  states what it actually contains and the chartered
  contradiction-flagging phase is **re-pointed to a freshly reserved
  branch name**. That is a tracker correction, not a charter: the
  chartered phase remains **UNSTARTED** and still needs its own charter
  and its own gate review, and changing the phase's *substance* is still
  a director action.

## Decisions

### D1 — B4 does not change the coverage-vs-rank diagnosis. Not partly, not directionally: not at all.

Stated with numbers, in the three quantities the diagnosis is made of:

1. **Coverage denominator.** Coverage = (evaluated distinct candidates) ÷
   (admissible walks). B4 contributes **0** admissible walks: all four
   fixtures together hold 39 `cites` edges, and every one of them is
   refused by the S1 validator (`cites ∉ EDGE_ALPHABET`, 14 classes;
   sequence table 10 entries; measured `admissible_single_edge_paths = 0`
   for all four fixtures). So W is unchanged, numerator unchanged,
   **coverage unchanged by construction** — B4 cannot even move the
   number the diagnosis is about.
2. **Rank numerator (energy).** The planted bridge's rank is a property
   of the twin's *energy over its own synthetic instance*. B4 supplies no
   path, no edge type, no admissible sequence, and no node set that the
   energy can score (`SearchContext` is label-free and reads only the
   path). Rank is unchanged.
3. **Strata scale.** B4's four graphs are 4–12 documents / 5–19 edges /
   max out-degree 3; the twin's strata are n=24–120 nodes / 28–534
   directed edges. B4's real reference structure is **below the twin's
   smallest stratum**, and B4 provides no basis for any stratum size the
   twin tests. So B4 cannot re-scale the grid either.

Verdict for (1): **No change.** The measured state on the pinned
machinery (twin step convention) is: admissible **walk** space
3,466–4,933 at n=120 (mean 4,323; P4 recorded 4,622, p4-repilot
3,900–4,700 — the same quantity, three measurements, consistent);
coverage **3.31 % at n=120, B=300** (P4 6 % at ~300 evals; p4-repilot
~6 %/run); and under the pinned energy the planted bridge is one of
**4,597** walks with a tie class of 4,079 — i.e. **the pinned energy
makes the rank undefined**, while the rich p4b+ energy puts it at
137–516 of a ~700 pooled set. B4 moves none of those numbers, and it
moves neither half of the conjunction: coverage needs admissible walks
(B4 contributes 0) and rank needs an energy over admissible paths (B4
supplies 0).

An inversion worth recording, because it changes what "the diagnosis"
means: B4 resolves the twin's `"real scale pending B4"` placeholder
**downward**. Combined with the measured space growth (`W ≈ n^2.8`), the
twin's n=120 PILOT scale is ~1.5 orders above the only real reference
scale on offer, and the failure there is a *coverage AND rank* statement
about an **unanchored stratum** — not, on this evidence, a capability
finding about any particular sampler. That is a finding about the twin's
*chosen scale*, and it is not something a better sampler alone fixes.

### D2 — The honesty limit, stated plainly: **nothing can be calibrated against B4 today.**

Asked directly, and answered in the same order the brief asks it:

- **Generator family resemblance — not calibratable.** The only
  resemblance is qualitative and was already stipulated: both are sparse,
  directed, typed, hub-ish graphs. B4's unit is a **governed document**
  (4–12 of them, ≤19 `cites` edges, max out-degree 3, mean 0.83–1.58);
  the twin's unit is an **entity node** in a DCSBM-lite synthetic graph
  (n = 24…120, 28–534 directed edges, planted bridge + hubs + warp
  decoys). B4 falsifies nothing the generator claims and measures nothing
  it uses. No quantity transfers: not a degree distribution that the
  twin's degree term can be conditioned on (different unit, different
  sparsity by ~1.5 orders), not a type prevalence the type term can be
  aligned to (`cites` is not in the alphabet, so it has no prevalence in
  the twin's table at all).
- **Strata scale orders — not calibratable, and adverse.** B4 is *below*
  the twin's floor (12 < 24 documents; 19 < 28 edges at n=24). The twin's
  smallest stratum is already an extrapolation past the real reference
  graph. There is no "order" B4 can supply other than "smaller than
  anything you tested".
- **Nothing yet — plainly.** B4 contributes 0 admissible paths, 0
  admissible sequences, 0 scored paths, 0 instances. The twin's primary
  metric is recall@K over **planted admissible bridges**; B4 contains no
  admissible bridge, so **no B4 number can enter the calibration grid at
  all**. What B4 is good for today is exactly what P2 recorded and no
  more: reference *structure*, with provenance, for a consumer that wants
  to cite which bytes produced which graph. It is fidelity evidence for a
  simulation, never a stratum.

Two things the reconciliation *did* establish that are usable — both from
the twin, neither from B4:

1. the admissible **space** grows as `W ≈ n^2.8`, and under the twin's own
   harness the coverage ratio (`E/W`, `E ≲ steps + 4`) falls with scale,
   moving its 100 % crossing from (24, 32) at B=150 to (48, 120) at
   B=600. Coverage is a **necessary condition** (a K-output cannot return
   what was never evaluated) and a *ceiling* — **not** a predictor: the
   grid this record cites is non-monotone in n (all-red n=24 at 133 %
   coverage, all-green n=32 at 52 %), and the cited p4-repilot finding is
   *coverage AND rank*; and
2. the B4 handoff and the diagnostic harness **have never coexisted in one
   tree**, so "B4-grounded" twin work is impossible in principle until a
   charter unifies them (§Context (ii)).

### D3 — The decision: **BANK-now** (negative result recorded; shelve conditions stated).

Rendered as BANK, with the reasoning recorded rather than the letter. This
replaces the REDESIGN rendered in the first pass, which rested on a
coverage-as-single-predictor claim the record's own cited evidence
contradicts [P3-audit F1–F3; correction log §C1].

**Why not SWEEP.** The option is a *grounded* sweep — re-run the B-sweep
against B4-**derived** scales, with the crippled-sampler control at every
B level. Every element of that premise fails on the evidence:

- There are no B4-derived scales to sweep. B4's content is 4/6/8/12
  documents with 5/19/10/5 `cites` edges; the twin's grid is indexed by
  `n_nodes` over an admissible-edge alphabet. To obtain "B4-derived
  scales" one would have to *stipulate* a documents→nodes mapping and an
  admissible edge class — i.e. substitute a **new assumption** for the
  assumed strata the task exists to retire. That is precisely the failure
  P2 already named ("five edges cannot replace an assumption").
- The sweep would be blind: B4 adds 0 to W, so every B level's coverage
  ratio is identical with and without B4. A sweep that cannot move its
  own headline number is not a test.
- The control seam is degenerate where it matters: the crippled policy
  exists structurally (F7, the K1-amended same-budget degraded policy),
  but at the PILOT scale it sits at the 0.000 recall floor (p4-repilot:
  *"F7 not measurable at the 0.000 floor (crippled == A1)"*), so the
  control cannot discriminate for the same reason the arms cannot.
- And structurally, no tree carries both the B4 read path and the
  diagnostic harness (§Context (ii)). A "grounded sweep" would have to
  run on a tree that has never existed.

So SWEEP is not *rejected on preference* — its **premise is false today**.
Running it would produce an ungrounded sweep wearing B4's name, which is
worse than no sweep.

**Why not REDESIGN-now.** The first pass drew a redesign from a
correlation between a coverage series measured on the **pin** (len
energy) and an F2 flip measured on the **p4b line** (rich energy, a
different harness, different seeds). That evidence is now withdrawn or
narrowed: coverage does not order F2 in the very grid cited (§Context
(iii)); the 100 % crossing is budget- and `steps`-dependent rather than a
harness-free boundary; and the cited source already states the
conjunction, not coverage alone. A redesign is therefore *not* the
smallest licensed move — the licensed move is to **shelve**, and to state
the conditions under which the question reopens.

**The negative result (recorded).**

- **Double NO-GO, on the twin's own terms.** `texp-001/p4` records
  **NO-GO for EVAL**: *"pilot-gate red (F2 …); (2) σ_d = 0.0 gives no
  sizing basis (N=18 degenerate); (3) open BLOCKERs B3/B4/B6"*
  (`P4-report.md`, §"GO/NO-GO for EVAL: NO-GO"). `texp-001/p4-repilot`
  re-pilots on **fresh** seeds at spec scale and fails again: *"all 18
  calibration cells 0.000 and pilot-gate FAIL (F2 red, bar unreached) …
  σ_d = 0.0 → N = 18/18 degenerate"*, with **EVAL/HOLD NO-GO**
  (`P4-repilot-report.md`, §2–§4). Two independent passes, both at the
  0.000 recall floor.
- **B4 supplies nothing the twin can ingest.** Through the twin's own
  read path B4 contributes **0 admissible paths** (all 39 edges are
  `cites`; `cites` is in neither the 14-class alphabet nor the 10-entry
  sequence table; 0 admissible single-edge paths per fixture), **0
  admissible sequences**, **0 scorable instances**, and a reference scale
  (4–12 documents, 5–19 edges) *below* the twin's smallest stratum
  (n=24). §D2.
- **The mechanism as measured, not as proposed.** Under the twin's own
  step convention the admissible **walk** space is 51 / 140 / 256 /
  **4,597** at n = 24/32/48/120, and the sampled budget covers
  133 % / 52 % / 28 % (B=150) at n = 24/32/48 and 1.65 % / 3.3 % at n=120
  (B=150 / B=300) of it; the 100 % crossing moves
  with B and with `steps`. The planted bridge is 1 of 4,597 and, under
  the **pinned** len-energy, has no rank at all — only a tie class of
  4,079. The rich p4b+ energy puts it at **137–516 of a ~700 pooled
  set**. The measured mechanism is therefore a **conjunction: coverage
  AND rank** (`P4-repilot-report.md:122-125`), and the p4b grid's
  non-monotone green band at n=32 (all-red n=24 at *higher* coverage)
  falsifies coverage as the sole predictor [P3-audit F1].
- **No B4-grounded work is expressible today.** The B4 read path and the
  diagnostic harness **have never coexisted in one tree** (§Context (ii)),
  so a "grounded sweep against B4-derived scales" has no tree to run on,
  and "B4-derived scales" would have to be *stipulated* — substituting a
  new assumption for the assumed strata the task exists to retire.

**Shelve conditions (revisit iff *any one* holds).**

1. **A B4-scale grounding exists.** Concretely: a reference graph whose
   edge type is a member of the twin's 14-class alphabet, **or** a
   chartered, explicit mapping (documents→nodes, `cites`→an alphabet
   class) that admits the B4 graphs as benchmark instances — the mapping
   being the *chartered* object, not a silent stipulation. Either makes
   B4 supply real admissible structure at a real scale.
2. **A production sampler exists.** The twin's arms are *stipulated*
   reference implementations (`arms.py`: *"STIPULATED reference behavior
   throughout (no production sampler exists — B1)"*), so today the
   coverage half is a property of a stand-in harness. A shipped sampler
   would make the budget/step/space arithmetic a measurement of the real
   object.
3. **A rank-side design arrives with its own pre-registered protocol.**
   The rank half is the half this reconciliation did **not** settle: the
   pinned energy is `len(path)` and cannot rank a tie class, and the
   cited candidate for the n=24 red is the per-scale degree-term sign
   flip. A design that changes the *ranking* signal must arrive with a
   pre-registered protocol — declared seeds, declared metric, declared
   decision rule — before any grid is re-run; a fresh run without one
   repeats the error this repair exists to correct.

Until then: **texp-001 stays pre-EVAL**, its PILOT/TUNE records stay
disqualified by the red gate, and the B4 fixtures remain what P2 declared
them — advisory reference *structure*.

**Falsification note — what evidence would reopen.**

- Any of the three shelve conditions above, in writing, with the
  artifact.
- **Against this verdict:** a re-measurement showing the walk space is
  *not* the binding constraint — specifically the twin's harness reaching
  F2 green at a coverage ratio well below 100 %, or F2 red at a ratio
  well above it. (The p4b n=32 band already shows the first at B=150:
  52 % coverage, all-green.) Either would refute the coverage half of the
  conjunction and move the whole question to rank.
- **For the mechanism:** a rank-side signal that, at fixed coverage,
  moves the planted bridge from rank 137–516 of ~700 into the top-K —
  that would establish rank as sufficient and coverage as the only
  remaining bound.
- **Not evidence either way:** any further B4 fixture whose edge type
  remains `cites`; any chain run at a fixed budget with no declared
  `steps` policy; any comparison between a coverage series and an F2
  series measured on different harnesses (§Context (iii)).

### D4 — What is explicitly NOT claimed

- No scientific-validity, reproducibility, or external-validity claim.
  The probe is a read-only measurement of the twin's own synthetic
  machinery plus four packaged document graphs.
- No claim that B4 is wrong, useless, or mis-scoped. P2 delivered what it
  said it delivered, under its own recorded honest limit; this task
  agrees with that limit and prices it.
- No calibration, no operating point, no N, no bar. No PILOT result is
  claimed from a micro probe, and the n=120 rows here are counts plus one
  seed's bounded chain.
- No governance act beyond tracker truth: the `gr3-b4/p3` collision is
  now surfaced **in** `docs/gr3-b4/ROADMAP.md` (C5) as a branch-name
  re-point, which is an implementer-side tracker correction, not a
  charter decision — the chartered contradiction-flagging phase remains
  **UNSTARTED** and still needs its own charter. No IDR is claimed.

## Acceptance

- **Probe (the evidence chain), deterministic, read-only:**

  ```
  .venv/Scripts/python.exe tests/texp_p3_reconcile_probe.py
  ```

  Produces the B4 handoff table (sources / edges / documents-touching /
  out-degrees and the per-fixture admissible-path count of 0), the
  walk-and-simple space and tie-class tables at n ∈ {24, 32, 48, 120},
  the coverage table under the **twin** step convention at
  B ∈ {150, 300, 600}, the `steps`-sensitivity table, and the
  six-PILOT-seed n=120 space counts. All numbers quoted in §Context
  (iii)–(iv) and §Decisions come from this one command.
- **Repair verification (P3-audit C1–C5):** each audit finding is closed
  in `docs/gr3-b4/P3-repair.md` with its own evidence and its own
  correction id. The audit's independently written
  `tests/texp_p3_audit_checks.py` re-runs and agrees with the repaired
  probe on both spaces to the digit (walks 51 / 140 / 256 / 4,597;
  simple 31 / 102 / 182 / 4,086), which is the cross-implementation check
  that the repaired counts are not an artifact of one traversal.
- **Twin suite green at the pin + B4 wiring:** `97 tests collected`, all
  pass (`pytest experiments/texp-001`), unchanged from the P2 baseline.
- **Read path green cross-namespace:** `experiments/texp-001/test_b4_source.py`
  + `tests/test_b4_ref_graphs.py` → **36 passed**.
- **Whole-repo suite:** **2176 passed** (`pytest -o addopts="" -q`),
  identical to the P2-b4fixtures baseline. This task's test-side additions
  are two scripts that are deliberately **not collected** (neither has a
  `test_` prefix; `pytest <script>` reports "no tests ran"), so they
  cannot perturb the certified suites.
- **Lint:** `ruff check tests/texp_p3_reconcile_probe.py tests/texp_p3_audit_checks.py`
  → all checks passed (the repo's ruff 0.16.8, py314 target). `pyright` is
  not available in this environment; no `src/` file is touched, so the
  pinned src gates are unaffected by construction and were not re-run.
- **Boundary audit:** `git diff --stat da79dfd -- src` empty on every
  branch of this work (`gr3-b4/p3`, `gr3-b4/p3-audit`, `gr3-b4/p3-repair`);
  `git diff --stat a927c7a da79dfd -- experiments/texp-001` =
  `+181/0` and `+165/0` (the P2-inherited additive append and its test,
  unchanged by this task); `docs/gr3-b4/` deltas across the three
  branches are this record, `P3-audit.md`, `P3-repair.md`, the amended
  `ROADMAP.md`, and `tests/texp_p3_*.py`. No fixture changes.
- **Fixtures re-verified, not trusted:** the twin read path re-derives
  each fixture's sha256 from its bytes during every probe run; the four
  digests read are `749bf192…37e5` (c1), `82ea9ec8…524b` (c2),
  `eef41946…664e` (c3), `2249067c…2c16` (c4) — the p2-fix digests.

## Relation-to-baseline

- Baseline chain `main@c0b5777` + P0 (`547d5f6`) + P0-audit (`3dbcf32`) +
  P1a (`e5f01d3`) + P1a-audit (`6ce52ee`) + P1b (`13565f8`) +
  P1b-audit2 (`1a051e4`) + P2 (`325292d` → `05842f2` → `6be95ab` →
  `761a35f`, twin merge `18ac780`) + P2-fix (`da79dfd`): **untouched.** No
  gate record, no `docs/STATE.md` entry, no P1a/P1b/P2 test file and no
  fixture is modified. `tests/test_corpus_admission.py`,
  `tests/test_gr3_edges.py`, `tests/test_b4_ref_graphs.py` are
  byte-identical and green.
- **Additive inventory.** `gr3-b4/p3` (first pass): 1 new probe script
  (`tests/texp_p3_reconcile_probe.py`) + this record. `gr3-b4/p3-audit`:
  the adversary audit (`P3-audit.md`) + `tests/texp_p3_audit_checks.py`.
  `gr3-b4/p3-repair`: the corrected probe, this amended record,
  `P3-repair.md`, and the `ROADMAP.md` tracker correction. Nothing else.
- **Certified-number movement: none.** Acquisition owners stay 18;
  governed corpus stays 6 + 6 (the named B4 cohort); no migration, no new
  intent kind, event type, table, or authority; `CORPUS_REFS` and
  `GOVERNED_CORPUS_REFS` byte-unchanged; the twin pin is unchanged and
  referenced, never edited.
- **Side-car artifacts referenced, not merged:** `texp-001/p4` (`047cb58`,
  P4 lock/report, NO-GO), `texp-001/p4-repilot` (`9d327f2`, the quoted
  6 % / 137–516-of-~700 diagnosis + lock v2), `texp-001/p4b-reaudit`
  (`5b86494`, the ruled K reading, 6/18 ranked-pool headline). They are
  cited as recorded artifacts of a **divergent** line and are **not**
  ancestors of this branch or of the pin.
- **Forward links:** (i) texp-001 is **shelved pre-EVAL** under §D3's
  three conditions — nothing here authorizes a sweep, a rank experiment,
  a twin-state unification, or any `src/` or twin edit; (ii) the
  `gr3-b4/p3` slot now records the reconciliation in `ROADMAP.md`, with
  the chartered contradiction-flagging phase **re-pointed to a freshly
  reserved branch name** and still needing its own charter; (iii)
  re-running `tests/texp_p3_reconcile_probe.py` is the first check that
  any future twin-state change leaves the measured spaces intact.
