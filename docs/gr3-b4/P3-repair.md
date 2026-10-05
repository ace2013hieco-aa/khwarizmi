# GR3-P3-repair — repair report (project khwarizmi-research, program mainline)

Status: GR3-P3-repair **IMPLEMENTER-DRAFT — no director verdict issued; acceptance rests with audit** — branch
`gr3-b4/p3-repair`, cut from `gr3-b4/p3-audit` =
`d383be246094f04f317b2ed2704c36c42f6dcbf5` (verified with `git rev-parse`
before cutover). Applies the binding adversary-audit items **C1–C5** from
`docs/gr3-b4/P3-audit.md` (verdict: **REJECT** of the first pass's §D3).
**NO remote push** (standing local-only order).

Human authority: **no human verdict was consumed as authority.** The task
briefing entered in-session and is not a recorded artifact; every change
below is recorded on its own stated merits as an IMPLEMENTER repair of an
recorded audit. Untrusted text (the B4 fixture bodies) entered only as
`UntrustedContent` through the twin's own read path, which re-derives each
fixture's sha256 from its bytes.

Deliverables in this pass:

| file | change |
|---|---|
| `docs/gr3-b4/P3-reconciliation.md` | §D3 re-rendered as **BANK-now**; the coverage-as-single-predictor claim deleted everywhere; the measured tables, crossing statement and caveat corrected; the `documents touched` tautology removed |
| `tests/texp_p3_reconcile_probe.py` | twin step convention; table-membership enumeration; walk/simple stated; fail-closed cap; truthful scale metadata |
| `docs/gr3-b4/ROADMAP.md` | tracker correction: what `gr3-b4/p3` actually holds; the chartered phase re-pointed to a reserved name |
| `tests/texp_p3_audit_checks.py` | status note only (its historical `steps = 200` contrast is marked as the audit's evidence, not current state) |

Constraint compliance: **no `src/` change** (`git diff --stat da79dfd -- src`
empty), **TEXP line untouched** (no edit to either twin lineage; the pin
`texp-001/s6-audit@a927c7a` is unchanged), **no PILOT/TUNE/EVAL/HOLD
execution** (only the probe's micro-scale generation, bounded enumeration
and bounded chains — the PILOT grid was never run), **S6/DG-5** honoured
(the probe imports no `hermes.*` module at import time and writes nothing),
**no pushes**. Every count quoted here comes from a run performed on this
branch.

## C1 — §D3 re-rendered as **BANK-now**; the coverage-as-single-predictor claim deleted

**What was wrong.** The first pass rendered `REDESIGN` on the claim that
coverage is the sole current predictor of F2 (`:431`). The audit showed
that claim is contradicted by (a) the record's own primary source —
`texp-001/p4-repilot:experiments/texp-001/P4-repilot-report.md:122-125`,
*"even perfecting coverage at this B cannot produce a hit without a
ranking change … *coverage AND rank*"* — and (b) the very p4b grid the
record aligns with, which is **non-monotone** in n: at both budgets
`F2` is all-red at n=24, all-green at n=32, all-red at n=48
(`texp-001/p4b-reaudit:experiments/texp-001/P4b-report.md`, "reading:
ranked_pool"; `green cells (ranked_pool): 6/18`).

**What was done.**

- The `REDESIGN` heading and its intro are replaced by **BANK-now**, with
  an explicit note that it supersedes the first pass and why.
- The `R1`–`R4` redesign block, the "New evidence … (any one flips
  REDESIGN → a real ground)" list and the old `Falsification trigger`
  are **deleted**. In their place §D3 now carries, in the audit's required
  order:
  1. **the negative result** — the double NO-GO (`P4-report.md`
     §"GO/NO-GO for EVAL: NO-GO" and `P4-repilot-report.md` §2–§4: all 18
     calibration cells 0.000, σ_d = 0.0, N = 18/18 degenerate, EVAL/HOLD
     NO-GO), B4's two zero-contributions, and **the mechanism as
     measured** — a coverage **AND** rank conjunction, with the crossing's
     budget/`steps` dependence stated;
  2. **the shelve conditions** — revisit iff *any one* holds: (i) a
     B4-scale grounding exists (a typed edge class inside the 14-class
     alphabet, or a chartered documents→nodes / `cites`→class mapping),
     (ii) a production sampler exists (the arms are stipulated, `arms.py`:
     *"no production sampler exists — B1"*), or (iii) a rank-side design
     arrives **with its own pre-registered protocol** (declared seeds,
     metric, decision rule);
  3. **the falsification note** — what would reopen, what would refute
     this verdict (F2 green at coverage far below 100 %), and what is
     **not** evidence either way (further `cites` fixtures; a fixed-budget
     run with no declared `steps`; a coverage series compared against an
     F2 series from a different harness).
- The conjunction wording now appears everywhere the deleted claim used
  to: §Context (iii) ("the mechanism is the **coverage AND rank
  conjunction**, never coverage alone"), §D1 ("it moves neither half of
  the conjunction"), §D2 item 1 ("a **necessary condition** … and a
  *ceiling* — **not** a predictor"), §D3.

**Why BANK is the licensed move, recorded rather than asserted.** The
first pass's redesign rested on a correlation between a coverage series
measured on the **pin** (len energy) and an F2 flip measured on the
**p4b line** (rich energy, different harness, different seeds). The audit
showed that correlation does not survive: coverage does not order F2 in
the cited grid, and the crossing is not a harness-free boundary. With the
grounding withdrawn, the smallest licensed move is to shelve and state
the reopening conditions — which is what §D3 now does. The `SWEEP`
rejection is retained verbatim because it was not challenged and is
independently grounded (B4 adds 0 to the walk space, so a B4 sweep cannot
move its own headline number).

## C2 — probe step convention corrected to the twin's `steps = budget // 2`

**What was wrong.** The probe hard-coded `steps=200`, a constant no twin
harness uses; `micropilot.py:80-81` and `pilot.py:90-91` / `:135-136` all
pass `b // 2` (signatures confirm the trailing positional is `steps`:
`collect_k_paths(..., k, budget, steps, l_max=2)`;
`collect_ranked_candidates(..., budget, steps, l_max=2, …)`).

**What was done and measured.** The probe now passes the twin's
convention and emits `"step_convention": "budget // 2"`. Under it, with
the corrected walk space (C4):

| budget | steps | n=24 | n=32 | n=48 | n=120 |
|---|---|---|---|---|---|
| B=150 | 75 | 133.33 % | 52.14 % | 27.73 % | 1.65 % |
| B=300 | 150 | 249.02 % | 102.86 % | 57.42 % | 3.31 % |
| B=600 | 300 | 505.88 % | 210.00 % | 115.23 % | 6.61 % |

**Honest crossing statement (the `:158` claim withdrawn).** The 100 %
crossing **moves**: **(24, 32) at B=150**, (32, 48) at B=300, (48, 120) at
B=600. The first pass's "between n=32 and n=48 **at both budgets**" is
**withdrawn** in the record as an artifact of the non-twin `steps = 200`.
The record now also prints the `steps` dependence directly
(§`B_step_sensitivity`): at B=300, `steps = 400` puts the crossing at
(48, 120) while `steps = 200` puts it at (32, 48). The claim that `steps`
"does not affect … the crossing" is **deleted**.

## C3 — caveat direction corrected (the old figures were UPPER bounds, not lower)

**What was wrong.** The first pass wrote that the B=300/B=600 rows "read
as **lower bounds** on the coverage a larger `steps` would produce". The
twin's real `steps` (75, 150) are *smaller* than the old constant 200, so
the old figures were **upper** bounds at B=150 and B=300 — the caveat
inverted the comparison, in the direction that favoured the record.

**What was done.** The caveat is replaced by a scope statement that is
true of the repaired probe: every row is step-capped (`steps // 4` per
segment + 4 initial evaluations → ≤76 / ≤152 / ≤304 evaluations at
B=150/300/600), so the figures are *what the twin's own harness actually
spends*, not bounds in either direction. The old wording is marked
withdrawn-as-inverted with the reason, and the `:170`-class sentence is
gone (grep-verified below).

## C4 — probe self-description corrected, and the F5 items with it

| item | before | after |
|---|---|---|
| enumeration label | *"Count SIMPLE directed paths (no repeated node)"* — false (the visit test gated recursion only, so counted 2-paths closed 2-cycles) | counts **walks** (revisits permitted — `kernel.propose:114-141` has no cycle check) as the primary space, and reports **simple** paths beside them; at n=24 that is 51 vs 31, so the mislabel was material |
| length-1 counting | counted every `PREFIXES` member, admitting `refines` / `analogous_to` singletons the validator refuses (`validator.py:102-113`) | counts only tuples whose **full** sequence is in `ADMISSIBLE_SEQUENCES`; prefixes are used **only** to prune |
| totals | 53 / 142 / 258 / 4600 | **walks** 51 / 140 / 256 / **4597**; **simple** 31 / 102 / 182 / 4086 |
| scale metadata | `"micro_scale_only": True` while running n=120 PILOT-scale chains | `"scale_scope"` (explicit) + `"pilot_grid_executed": false` |
| docstring | "short chains at budget B=150" vs `BUDGETS=(150,300,600)` | states the twin convention and the three budgets |
| `ENUM_CAP` | reported a truncated space in a sibling key — a truncated denominator **inflates** coverage, the one bias that favoured this record | the probe **raises** `EnumerationCapExceeded` instead; the cap never binds (max 4,933 ≪ 400,000) |
| F5 tautology | the record's B4 table showed `documents touched` computed as `endpoints ∪ source_set`, i.e. equal to `sources` by construction | the record's column is now `documents touching an edge` (4 / 12 / 8 / 4) and the probe emits `documents_equals_sources_by_construction` so the tautology is visible instead of implied |

**Cross-implementation check.** The audit's independently written
`tests/texp_p3_audit_checks.py` and the repaired probe now agree on both
spaces to the digit — `{24: (51, 31), 32: (140, 102), 48: (256, 182),
120: (4597, 4086)}` for (walks, simple) — so the repaired counts are not
an artifact of one traversal.

## C5 — the `gr3-b4/p3` branch-name collision is surfaced in the tracker

`docs/gr3-b4/ROADMAP.md` is amended (tracker correction, not a charter):

- the phase table now has a row recording that **`gr3-b4/p3` actually
  holds** the TEXP-001 reconcile (`p3` → `p3-audit` → `p3-repair`), with
  the BANK-now outcome and its exit evidence;
- the chartered **"P3 contradiction flags"** row is re-pointed to the
  newly **reserved** name **`gr3-b4/p3-contradiction`**, marked
  UNSTARTED / charter-first, with its entry and exit conditions unchanged;
- §Notes records three things the tracker previously left wrong: the
  branch-name correction itself; that `gr3-b4/p2`'s seat is
  **ACCEPT WITH CONDITIONS (C1–C3)** with `da79dfd` applying them but
  **no audit of `p2-fix`**, so "P2 accepted" is *not* earned; and that
  texp-001 is **shelved pre-EVAL** with the twin still pinned and
  read-only.

The status line states explicitly that this is tracking truth, that the
chartered phase's substance is unchanged, and that chartering/re-scoping
remains a director action.

## Verification (all counts emitted by runs on this branch)

```
.venv/Scripts/python.exe tests/texp_p3_reconcile_probe.py     # the evidence chain
.venv/Scripts/python.exe tests/texp_p3_audit_checks.py        # cross-implementation check
ruff check tests/texp_p3_reconcile_probe.py tests/texp_p3_audit_checks.py
.venv/Scripts/python.exe -m pytest experiments/texp-001 -o addopts="" -q
.venv/Scripts/python.exe -m pytest experiments/texp-001/test_b4_source.py tests/test_b4_ref_graphs.py -o addopts="" -q
.venv/Scripts/python.exe -m pytest tests/test_corpus_admission.py tests/test_gr3_edges.py -o addopts="" -q
.venv/Scripts/python.exe -m pytest -o addopts="" -q
```

| check | result |
|---|---|
| probe determinism | stdout byte-identical across runs |
| probe / audit cross-implementation | agree to the digit on walks and simple spaces |
| `ruff` | all checks passed (repo ruff 0.16.8, py314) |
| twin suite | **97 collected / 97 passed** (unchanged) |
| B4 read path + ref graphs | **36 passed** |
| certified P1a/P1b slices | **51 passed** (files byte-unchanged) |
| whole repo | **2176 passed** (identical to the P2 baseline) |
| probe scripts collected by pytest | **no** — `pytest <script>` → "no tests ran" |
| `src/` diff vs `da79dfd` | empty |
| TEXP twin diff vs `a927c7a`→`da79dfd` | `+181/0`, `+165/0` (P2 only; untouched here) |
| `pyright` | unavailable in this environment (no `src/` touched) |

## Sentence-level correction log (every audit-listed defect)

| audit | the defective sentence | disposition |
|---|---|---|
| F1 | `:431` — "it is the *only* quantity that currently predicts the F2 outcome" | **deleted**; R1 removed; replaced by the coverage-AND-rank conjunction in §Context (iii), §D1, §D2, §D3 |
| F1 | §Context (iii) — the crossing "lining up with the observed F2 green→red flip" | **replaced** by the non-monotone counterexample (all-red n=24 at 133 % coverage vs all-green n=32 at 52 %) |
| F1 | §D3 grounding of `REDESIGN` | **re-rendered** as BANK-now with negative result, shelve conditions and falsification note (C1) |
| F2 | `:158` — "the 100 % crossing sits between n=32 and n=48 **at both budgets**" | **withdrawn**; replaced by the per-budget crossing table — (24,32) / (32,48) / (48,120) |
| F2 | `:164-171` — the B=300/B=600 rows are "**lower bounds** on the coverage a larger `steps` would produce" | **withdrawn as inverted**; replaced by the step-cap scope statement |
| F2 | `:170` — "This does not affect the direction or the crossing" | **deleted**; replaced by the explicit `steps`-sensitivity table |
| F2 | `:177-182` — method-agreement figures presented as one quantity | **reworded**: walks 3,466–4,933 (mean 4,323) vs p4-repilot's totals, different seeds, convention stated, no longer called the same measurement |
| F3 | `:462-468` — the `REDESIGN` falsification trigger | **deleted**; replaced by §D3's falsification note, which names what would refute *this* verdict |
| F4 | probe `:118` — "Count SIMPLE directed paths" | **corrected** to walks (primary) + simple (reported), with the materiality (51 vs 31 at n=24) stated |
| F4 | probe `:129-131` — counting every `PREFIXES` member | **corrected** to full table membership; prefixes prune only |
| F4 | probe `:20` — "short chains at budget B=150" | **corrected** to the twin convention and the three budgets |
| F4 | probe `:252` — `"micro_scale_only": True` | **replaced** by `scale_scope` + `pilot_grid_executed: false` |
| F4 | `ENUM_CAP`'s coverage-inflating failure mode | **corrected**: the probe raises instead of publishing a truncated denominator |
| F5 | record's B4 table — `documents touched` (a tautology) | **replaced** by `documents touching an edge` (4/12/8/4) + an explicit note |
| F5 | record's "admissible space" totals 53/142/258/4600 | **corrected** to walks 51/140/256/4597 (simple 31/102/182/4086) |
| F6 | the collision recorded only inside the record | **surfaced in the tracker** (`ROADMAP.md`, C5) |

## Relation-to-baseline

- Chain: `gr3-b4/p3-audit@d383be2` (verified) → `gr3-b4/p3-repair`. The
  audited first pass remains at `gr3-b4/p3@168afd7`; this branch amends
  only the four files listed at the top.
- **Certified-number movement: none.** Persistence acquisition owners
  stay 18; the governed corpus is untouched; `CORPUS_REFS` /
  `GOVERNED_CORPUS_REFS` byte-unchanged; no migration, no new intent
  kind, event type, table or authority; `test_corpus_admission.py`,
  `test_gr3_edges.py` and `test_b4_ref_graphs.py` are byte-identical and
  green.
- **What is not done here:** the chartered contradiction-flagging phase is
  not chartered or started; no sweep, rank experiment or twin-state
  unification is authorized; texp-001 stays shelved pre-EVAL.
