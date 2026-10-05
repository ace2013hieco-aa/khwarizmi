# GR3-P3-reconcile — ADVERSARY AUDIT (project khwarizmi-research, program mainline)

Status: **REJECT** — of the rendered decision (`docs/gr3-b4/P3-reconciliation.md` §D3, `REDESIGN`). The
record's Context / evidence sections independently verify and are
ACCEPT-grade on their own (§3 below); the decision does not follow from
them, and one of its load-bearing claims is falsified by the record's own
cited evidence and by execution. Audited commit: `gr3-b4/p3` =
`168afd719c63a309cb9d06c1d92f0146626369a0`, base
`gr3-b4/p2-fix` = `da79dfdbee3587b0271cb6cc211ccdb0f300edda`
(`git rev-parse`, verified). Audit branch: `gr3-b4/p3-audit` from the p3
tip. **NO remote push** (standing local-only order).

Artifacts audited, by content hash:

| artifact | sha256 |
|---|---|
| `docs/gr3-b4/P3-reconciliation.md` | `4ed9c18e22e401ac86968423c13de29f0ce2d3c7687af5da1ec509caab2b5d29` |
| `tests/texp_p3_reconcile_probe.py` | `065fb6b1aa964609c33ea5a78b830b40b3b52bf1aa13b5542de5c6651acc5457` |

Adversary artifact (this audit's own, independently written):
`tests/texp_p3_audit_checks.py` — B4 admissibility, the two enumeration
conventions, and the step-convention comparison.

Method: every number in the record was **re-measured by execution
against live source**, never read off the record; every claim was
re-read at its cited source; every cross-branch fact was re-derived with
`git merge-base` / `git show`. Where the record's claim depends on
`src/`, the live `src/` at `168afd7` was read.

## 1. What reproduces (the record is numerically honest where it makes numbers public)

`tests/texp_p3_reconcile_probe.py` re-run at `168afd7` reproduces **every**
published figure exactly (runtime 0.27 s; two runs byte-identical,
stdout sha256 `3d6a30fef0562022867d2e1dc83f5d30…`):

| claim in the record | re-measured | verdict |
|---|---|---|
| B4 table: 6/12/8/4 sources, 5/19/10/5 edges, max out-deg 3, mean 0.83/1.58/1.25/1.25, 0 admissible single-edge paths each | identical | PASS |
| alphabet 14, sequence table 10, `cites_in_alphabet=False` | identical (`validator.py:29-44`, `:50-62`) | PASS |
| space 53 / 142 / 258 / 4600 by length 22+31, 40+102, 77+181, 521+4079 | identical | PASS |
| tie class 31 / 102 / 181 / 4079; interval [23,53] [41,142] [78,258] [522,4600]; luck 0.258/0.078/0.044/0.002 | identical | PASS |
| coverage (B=150/300/600) 283.0/334.0, 105.6/140.1, 58.1/78.3, 3.26/4.44 | identical | PASS |
| PILOT-seed space 4600/3470/3875/4579/4502/4937, mean 4327.2 | identical | PASS |
| pin energy = `float(len(path))` (`energy.py:66`) ⇒ rank undefined, tie class only | confirmed | PASS |
| twin suite 97 collected / 97 passed; B4 read-path + ref-graphs 36 passed; whole repo 2176 passed; `pyright` unavailable here; probe not collected by pytest | 97 / 36 / 2176 / absent / "no tests ran" | PASS |

The three premise corrections are all verified against live branches
(§3). The probe is deterministic, writes nothing
(`grep -nE "open\(|\.write|hermes|import os|import time|uuid"` → none),
mutates no state, and is not collected by pytest (name has no `test_`
prefix) — so its presence cannot perturb the certified suites, which
pass at 2176.

## 2. Findings

### F1 — MAJOR (decision): the coverage ratio is NOT "the only quantity that currently predicts the F2 outcome"; the record's own cited grid is a counterexample

`P3-reconciliation.md:431` (inside R1) asserts coverage "is the *only*
quantity that currently predicts the F2 outcome", and `:432-437` builds
the whole redesign on it. Three independent pieces of the record's own
evidence contradict it.

**(a) The record's own primary source says the opposite.**
`texp-001/p4-repilot:experiments/texp-001/P4-repilot-report.md:122-125`  (cited by the record at `:83-118`):

> energy places it at rank 137–516 of ~700, far outside top-8. So even
> perfecting coverage at this B cannot produce a hit without a ranking
> change: the finding narrows the n=48/rationale's "coverage ratio
> candidate" to *coverage AND rank*, at spec scale.

So the cited source's finding is *coverage AND rank* — coverage is a
necessary condition, explicitly not sufficient. The record reproduces
that split at §Context (i) and then, at `:431`, promotes one half of it
to the sole predictor.

**(b) The p4b micro grid the record aligns with is non-monotone in n.**
Re-read at `texp-001/p4b-reaudit:experiments/texp-001/P4b-report.md`
(§"reading: ranked_pool"): the `F2` cells are

```
n24/B150/K4..K8  red  red  red
n24/B300/K4..K8  red  red  red
n32/B150/K4..K8  GREEN GREEN GREEN
n32/B300/K4..K8  GREEN GREEN GREEN
n48/B150/K4..K8  red  red  red
n48/B300/K4..K8  red  red  red
green cells (ranked_pool): 6/18
```

A **green band at n=32**, red on both sides. The record's §Context
(iii) quotes only the 32→48 boundary ("flips F2 from green (all six n=32
cells) to red (all six n=48 cells)"). Coverage, by contrast, is monotone
decreasing in n (more space, fixed budget). A monotone curve cannot
produce a non-monotone outcome, so the record's own cited grid refutes
coverage-as-single-predictor — and the p4b source gives the n=24 red its
own cause: the *rank* term. `P4b-report.md:164-165` attributes it to the
"per-scale sign flip of the degree term (anti-planted at n=24 where the
planted nodes are hub-like at 1.97x the mean degree)".

**(c) Measured directly, coverage does not order F2.** Under the twin's
own harness convention (§F2), at B=150: n=24 coverage = **117.6 %** and
F2 = 3/3 red; n=32 coverage = **51.4 %** and F2 = 3/3 GREEN. Less
coverage, better outcome. Whatever explains the n=32 green band, it is
not coverage.

Consequence: `:432-437`'s "control coverage, not n" does not follow, and —
because `coverage = E/W` with `E ≤ min(budget, steps+4)` — holding
coverage near 100 % by `B ∝ W` is an intervention on *budget and scale*,
not on coverage. The redesign as scoped cannot isolate the mechanism it
claims to test.

### F2 — MAJOR (claim falsified): the probe's step budget is not the twin's harness convention, and the record's "crossing at both budgets" plus the direction of its own caveat are both wrong

The record's chains run **`steps = 200` constant**
(`tests/texp_p3_reconcile_probe.py:233`). The twin's own harnesses do not:

- `texp-001/p4b-reaudit:experiments/texp-001/micropilot.py:80-81` —
  `collect_ranked_candidates(mk, kw, inst.graph, (aseed,), b, b // 2, energy_fn=energy_fn)`
- `texp-001/p4:experiments/texp-001/pilot.py:90-91` and `:135-136` —
  `collect_k_paths(mk, kw, inst.graph, (aseed,), k, b, b // 2)`

and the signatures confirm the trailing positional is `steps`
(`fixtures.py` pin: `collect_k_paths(..., k, budget, steps, l_max=2)`;
`p4b-reaudit fixtures.py:106-109`: `collect_ranked_candidates(..., budget, steps, l_max=2, ...)`).
Every twin harness therefore uses **`steps = budget // 2`**. `steps = 200`
appears nowhere in the twin.

Measured under `steps = budget // 2` (my own counter loop, A1, seed
1000, algo 1010, against the true admissible space — §F4):

| budget | steps | n=24 | n=32 | n=48 | n=120 |
|---|---|---|---|---|---|
| B=150 | 75 | E=60 → **117.6 %** | E=72 → **51.4 %** | E=76 → 29.7 % | E=76 → 1.7 % |
| B=300 | 150 | E=136 → 266.7 % | E=142 → **101.4 %** | E=148 → 57.8 % | E=152 → 3.3 % |

Under the twin's convention the **B=150 crossing is between n=24 and
n=32**, not (32,48). The record claims otherwise at `:158`: "the 100 %
crossing sits between n=32 and n=48 **at both budgets**". That is true
only for the probe's own `steps=200`, which pushes `steps` above the
budget at B=150 and thereby makes the B=150 row budget-capped where the
twin's harness is step-capped. Since the entire point of the crossing is
to align with a p4b/p4-repilot F2 flip measured *with the twin's*
harness, the aligned crossing does not exist at B=150.

The caveat at `:164-171` is wrong in **direction**:

> the B=300 and B=600 rows are therefore **step-capped …** and read as
> lower bounds on the coverage a larger `steps` would produce. … This
> does not affect the direction or the crossing (both hold at B=150)

At B=150 and B=300 the twin's real `steps` (75, 150) are *smaller* than
the probe's 200, so the probe's evaluations (150, 198-204) *exceed* the
twin's (60-76, 136-152) — the probe's figures are **upper** bounds there,
i.e. they favour the record's own conclusion, not the lower bounds the
caveat claims. And the crossing is not steps-invariant: at B=300 with
`steps=400` it moves to **(48,120)** (E=300 → 117.2 % at n=48), directly
falsifying `:170`'s "This does not affect the direction or the crossing".

Net: the record's alignment claim survives only at B=300, only under a
harness constant that the twin never uses.

### F3 — MODERATE (decision): the falsification trigger cannot refute the redesign and is asymmetric in its own favour

`:462-468`:

> If the coverage-controlled sweep of R2 holds coverage at ≈100 % and F2
> is **still** red, then the diagnosis is not coverage … the correct
> action is to shelve texp-001 — i.e. **BANK**

Three defects.

1. **It cannot discriminate.** Under R2's design (`B ∝ W`, `:432-437`),
   coverage is `min(B, steps+4)/W`; "holding coverage at ≈100 %" *is* the
   budget/scale manipulation. A green result is equally explained by
   coverage, by budget, or by scale, so the trigger's green branch ("the
   diagnosis is *confirmed as scale*", `:435-437`) is not evidence for the
   mechanism named in R1.
2. **The record already holds evidence that it fires.** F1(a) quotes the
   record's own source: "even perfecting coverage at this B cannot
   produce a hit without a ranking change". Deferring to a future sweep
   whose outcome the record's own citations predict is deferral, not
   discipline. The same numbers support **BANK-now**, or a redesign aimed
   at the *rank* half (137–516 of ~700).
3. **Asymmetry.** There is no branch in which REDESIGN's R1/R2 is shown
   unnecessary; green confirms, red shelves. The tripwire therefore
   protects the redesign from the refutation already on file rather than
   exposing it.

Note the vocabulary: `:462` calls this a trigger that "reverts the
verdict to BANK" — but a trigger whose firing condition is already
supported by cited evidence is a *deferred* verdict, not a falsification
test.

### F4 — MINOR (artifact honesty): the probe mislabels its own enumeration and misdescribes itself

- `tests/texp_p3_reconcile_probe.py:118` claims it "Count SIMPLE directed
  paths (no repeated node)". It does not: the visit test at `:135-136`
  gates recursion only, so a counted 2-path may close a 2-cycle. The twin's
  generator emits both directions of every background edge, so this is
  not hypothetical: at n=24 the true simple space is **31** and the probe
  reports **53**. (The probe is in fact measuring the *walk* space, which
  is the more defensible denominator, since `kernel.propose:114-141` has
  no cycle check and can propose revisiting paths — it is the label that
  is wrong, not the choice.)
- `:129-131` counts every member of `PREFIXES`, i.e. every *prefix* of a
  table sequence. Length-1 prefixes include `("refines",)` and
  `("analogous_to",)`, which `validate_path` refuses as
  `INADMISSIBLE_SEQUENCE` (`validator.py:102-113`). The probe's
  length-1 counts are therefore inflated: 22/40/77/521 vs the true
  20/38/75/518, totals 53/142/258/4600 vs the true walk space
  **51/140/256/4597** and the true simple space **31/102/182/4086**.
  Direction: the record's coverage figures are **understated** by ≤3.8 %
  at n=24 and ≤0.07 % at n=120 — conservative, not flattering — but the
  record's "Method agreement" paragraph (`:177-182`) compares its 521
  against p4-repilot's 551 while calling them the same quantity, when at
  minimum the two are differently-defined sets.
- `:252` emits `"micro_scale_only": True` while `B_coverage` runs real
  chains at **n=120** (`:258-259`, via `coverage_report`) — the PILOT scale, on the PILOT seed
  band, with the PILOT budget levels — and `:20` says "short chains at
  budget B=150" while `BUDGETS = (150, 300, 600)` (`:60`). The record's
  prose discloses the n=120 rows honestly (`:48-52`, `:285-286`), but the
  artifact's machine-readable self-description is false. A reader who
  trusts the flag would mis-scope the probe's own constraint compliance.
- `ENUM_CAP` (`:61`) never binds (max 4,937 ≪ 400,000) and is reported in
  a sibling key, so no impact — but its failure mode is the one cap whose
  bias would *favour* the record (a capped `W` shrinks the denominator and
  inflates coverage), and it degrades silently rather than refusing.

### F5 — COSMETIC: two presentational numbers are not independent measurements

- §Context (iii)'s "admissible space" totals (53/142/258/4600) are 2-3
  above the true validator-admissible space (F4). No conclusion moves.
- §"What B4 actually is" presents `documents touched` beside `governed
  sources`; they are equal by construction for all four fixtures
  (6/6, 12/12, 8/8, 4/4) because `source_set` ⊇ every cited endpoint. A
  definitionally-equal column reads as a second measurement.

### F6 — CONDITION (governance): leaving `ROADMAP.md` unedited keeps the workflow's own tracker wrong

`docs/gr3-b4/ROADMAP.md:40` charters the branch **this task consumed**:

> | P3 contradiction flags | `gr3-b4/p3` (TBD, charter first) | Graph-structural contradiction flagging … | P2 accepted; §19/N1/N9 gate review | …

The record's §Constraints records the collision and declines to edit,
reasoning that "re-slotting a chartered phase is a director action". That
justifies not **re-slotting**; it does not justify leaving the tracker
silent about a branch whose contents contradict its charter — and
`docs/gr3-b4/` is this task's own write surface. Two aggravating facts:
(a) `P2-audit` is **ACCEPT WITH CONDITIONS (C1, C2, C3)** on
`gr3-b4/p2@761a35f`, and `da79dfd` addresses them but has **no audit
branch**, so the P2 seat's entry condition ("P2 accepted") is itself
open — a tracker line is the cheapest place to say so; (b) the record's
`Status` frames the omission as "no other file is added, edited, or
deleted", i.e. as a consequence of a self-imposed write limit rather than
as a decision about traceability. A one-line `Notes` annotation (or a
recorded director ruling) closes this; silence does not.

## 3. Verified passes (the record earns these; they are not in dispute)

- **Premise correction (i)** — the quoted diagnosis is verbatim
  `texp-001/p4-repilot:experiments/texp-001/P4-repilot-report.md:117-125`
  and `docs/texp-001/CHANGELOG.md:28`; "~700" is the **pooled candidate
  set** (`pooled=696,725,702,708,689,704,656,687,685,706,716,706`), not the
  walk space; the 6 % half is verbatim `texp-001/p4:experiments/texp-001/P4-report.md:19`
  ("4,622 admissible walks at n=120 vs ~300 evals/run (6% coverage)"); and
  `git diff --stat da79dfd texp-001/p4 -- experiments/texp-001/energy.py`
  is empty, with the rich energy arriving only at p4b
  (`git diff --stat texp-001/p4 texp-001/p4b -- …/energy.py` = +263/−29).
  All confirmed.
- **Premise correction (ii)** — `a927c7a` is **not** an ancestor of
  `texp-001/p4`; `texp-001/p4` is **not** an ancestor of `gr3-b4/p3`;
  `git merge-base texp-001/p4 gr3-b4/p3` = `faf018d3bf0c1b1a13f5d926665629ed68748e6a`
  = `texp-001/s5b` tip. `B4 SOURCE` / `b4_reference_graphs` occurrences in
  `experiments/texp-001/fixtures.py`: `gr3-b4/p3` = 1 / 3; `texp-001/p4`,
  `texp-001/p4-repilot`, `texp-001/p4b-reaudit`, `texp-001/s6-audit` = 0 / 0.
  "Never coexisted in one tree" holds.
- **Premise correction (iii)** — B4 max 12 documents / 19 edges / max
  out-degree 3; the twin's smallest declared stratum is n=24
  (`strata_stats.MICRO_STRATA = (24, 32, 48)`, `PILOT_SCALE = 120`) with
  28 directed edges at seed 1000. B4 is below the twin's floor. Holds.
- **B4 ⇒ zero admissible paths, independently** — every one of the 39
  edges across the four fixtures is `cites` (`all_edges_cites=true` each);
  `cites` is not a member of the 14-class `EDGE_ALPHABET`
  (`validator.py:29-44`); all 39 single-edge `validate_path` calls are
  refused; and **no** table-shaped length-2 chain exists at all
  (`length2_table_chains_tried = 0`). D1 and D2 stand.
- **S6 / DG-5 / constraint surface** — `git diff --stat da79dfd 168afd7 -- src`
  empty; none of `arms`, `energy`, `generator`, `kernel`, `fixtures`,
  `validator` imports `hermes` at module scope (0 each); the probe writes
  nothing and uses no clock/RNG-outside-seed; the twin pin is byte-
  unchanged (`git diff --stat a927c7a da79dfd -- experiments/texp-001` =
  +181/0 and +165/0). No PILOT/TUNE/EVAL/HOLD grid was executed by the
  audited probe — though see F4 on the `n=120` chains and the false
  `micro_scale_only` flag.

## 4. Verdict

**REJECT** of the rendered decision (§D3, `REDESIGN`), on F1, F2 and F3.

The reasoning the record offers for REDESIGN is: coverage is the sole
current predictor of F2 (F1 — contradicted by the record's own cited
grid and its own cited source), the probe's coverage series places the
100 % crossing on the F2 boundary (F2 — an artifact of a `steps` constant
the twin never uses; it fails at B=150 under the twin's own convention),
and the trigger would catch a wrong call (F3 — it cannot discriminate and
is predicted to fire). With those three removed, the same numbers support
**BANK-now**, or a REDESIGN aimed at the *rank* half that the record's
own primary source names ("*coverage AND rank*").

Everything in §1 and §3 stands: the B4 findings, the honesty limit, the
three premise corrections, the constraint compliance and the suite
results are correct, independently reproduced, and genuinely useful.
This is a rejection of the inference, not of the work.

**Repair path (minimal, in `docs/gr3-b4/P3-reconciliation.md`):**

1. **C1.** Restate D3 against the record's own sources: coverage is a
   *necessary, not sufficient* condition (`P4-repilot-report.md:122-125`),
   and the p4b grid is non-monotone (green band at n=32), so coverage
   cannot be "the only quantity that predicts F2". Either re-render the
   decision as **BANK-now** with the coverage/rank evidence recorded, or
   re-scope the redesign to test the **rank** half (e.g. the degree-term
   sign the cited source already fingers at n=24).
2. **C2.** Fix the probe's step convention to the twin's `steps = budget // 2`
   (or justify `steps = 200` against a twin artefact), re-run, and state
   the crossing per budget under that convention — including that at
   B=150 it is (24,32).
3. **C3.** Correct the caveat's direction (the probe's figures are
   *upper* bounds at B=150/300 under the twin's convention) and drop the
   claim that `steps` does not affect the crossing.
4. **C4.** Fix the probe's self-description (walk vs simple; the
   `micro_scale_only` flag; the `B=150` docstring) and either count
   table-membership rather than prefixes or state the prefix convention.
5. **C5.** Surface the `gr3-b4/p3` branch-name collision where the
   workflow tracks it (a `ROADMAP.md` Notes line naming the chartered P3
   as unstarted), or obtain a recorded director ruling.

## 5. Relation to baseline

- Audited `gr3-b4/p3@168afd7` — additive over `da79dfd`: exactly
  `docs/gr3-b4/P3-reconciliation.md` and `tests/texp_p3_reconcile_probe.py`
  (`git diff --stat da79dfd 168afd7` = 564 + 275 lines).
- This audit adds only `docs/gr3-b4/P3-audit.md` and
  `tests/texp_p3_audit_checks.py` on `gr3-b4/p3-audit`. No `src/`
  change, no fixture change, no twin-lineage change, no ROADMAP edit, no
  push.
- Certified-number movement: none. Acquisition owners stay 18; the
  governed corpus is untouched; `test_corpus_admission.py`,
  `test_gr3_edges.py`, `test_b4_ref_graphs.py` are byte-identical and
  green; whole-repo 2176 passed either way.
