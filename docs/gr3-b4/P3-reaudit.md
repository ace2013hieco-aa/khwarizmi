# GR3-P3-repair — ADVERSARY RE-AUDIT (project khwarizmi-research, program mainline)

Status: **ACCEPT WITH CONDITIONS (C-R1, C-R2 below)** — of the P3 repair
`gr3-b4/p3-repair@71c955d` ("P3-repair — apply audit C1–C5"). Every binding
audit item C1–C5 closes against **live source**, re-executed on this tree;
two doc-level defects survive, neither load-bearing, neither touching the
BANK-now decision. Re-audit branch: `gr3-b4/p3-reaudit` from `71c955d`
(`git rev-parse`, verified). **NO remote push** (standing local-only order).

Method: every number re-measured by execution (probe + audit-checks re-run,
byte-identical determinism check, full suite), every claim re-read at its
cited live location, every cross-branch fact re-derived with `git
rev-parse` / `git show` / `git diff --numstat`. A repair-report claim with
no verifiable live footing is recorded below as a finding, not a pass.
Rule applied throughout: grep-absence for deleted sentences, grep-presence
for required replacements, execution for numbers.

Chain verified: `gr3-b4/p3-repair` = `71c955d`, `gr3-b4/p3-audit` =
`d383be2`, `gr3-b4/p3` = `168afd7`, `gr3-b4/p2-fix` = `da79dfd` (all via
`git rev-parse`). Repair delta `d383be2..71c955d` is exactly five files
(`docs/gr3-b4/P3-reconciliation.md`, `docs/gr3-b4/P3-repair.md`,
`docs/gr3-b4/ROADMAP.md`, `tests/texp_p3_reconcile_probe.py`,
`tests/texp_p3_audit_checks.py`); `git diff --stat da79dfd 71c955d -- src`
is empty.

## 1. What reproduces (re-measured live on `71c955d`)

Probe re-run (`tests/texp_p3_reconcile_probe.py`, two runs byte-identical,
sha `2fe112b79fab49cb` both) emits exactly the repair's numbers:

| repair claim | re-measured live | verdict |
|---|---|---|
| `P3-repair.md:104-108` coverage table (B150: 133.33/52.14/27.73/1.65; B300: 249.02/102.86/57.42/3.31; B600: 505.88/210.00/115.23/6.61) | `B_coverage_twin_convention`: n24/32/48/120 = (75,68,133.333)/(75,73,52.143)/(75,71,27.734)/(75,76,1.653); (150,127,249.02)/(150,144,102.857)/(150,147,57.422)/(150,152,3.307); (300,258,505.882)/(300,294,210.0)/(300,295,115.234)/(300,304,6.613) | PASS |
| crossing triple `(24,32)/(32,48)/(48,120)` (`P3-repair.md:110-113`; record `P3-reconciliation.md:198-200`) | B150: 133.3% (n24) → 52.1% (n32) crosses (24,32); B300: 102.9% (n32) → 57.4% (n48) crosses (32,48); B600: 115.2% (n48) → 6.6% (n120) crosses (48,120) | PASS |
| `steps`-sensitivity (`P3-repair.md:114-117`; record §`B_step_sensitivity`) | at B300: `steps=200` → n32 142.14% / n48 76.56% (crossing 32,48); `steps=400` → n48 117.19% / n120 6.53% (crossing 48,120); old `:170` "does not affect crossing" falsified live | PASS |
| totals walks 51/140/256/4597, simple 31/102/182/4086 (`P3-repair.md:141`; record `:180-185`, `:541`) | `B_tie_class`: n24 `{1:20,2:31}=51` / simple `{1:20,2:11}=31`; n32 `38+102=140` / `38+64=102`; n48 `75+181=256` / `75+107=182`; n120 `518+4079=4597` / `518+3568=4086`; intervals [21,51]/[39,140]/[76,256]/[519,4597], luck 0.2581/0.0784/0.0442/0.002 | PASS |
| cross-implementation agreement (`P3-repair.md:147-151`) | `tests/texp_p3_audit_checks.py` `space_convention`: (51,31)/(140,102)/(256,182)/(4597,4086) with identical length splits — agrees with probe to the digit on both spaces | PASS (spaces only, as claimed; eval counters differ by harness — see §2 note — crossing positions agree) |
| B4 handoff (record `:72-77`) | sources 6/12/8/4, edges 5/19/10/5, touching 4/12/8/4, max-out 3, means 0.8333/1.5833/1.25/1.25, admissible 0 each; `cites_in_alphabet=false`, alphabet 14, table 10; digests `749bf192…`/`82ea9ec8…`/`eef41946…`/`2249067c…` (record `:662-665`) | PASS |
| pilot-seed range 3,466–4,933 mean 4,323 (record `:250-252`) | `B_pilot_seed_space`: 4597/3466/3872/4574/4498/4933, min 3466 max 4933 mean 4323.3 | PASS |
| step caps ≤76/≤152/≤304 (`P3-repair.md:127-133`; record `:229-231`) | measured evals B150 68–76, B300 127–152, B600 258–304; `arms.py` `make_a1(..., steps, n_segments=4)` → `steps_per_segment=max(1, steps // n_segments)` (live `HEAD:experiments/texp-001/arms.py`), plus 4 initial evals | PASS |
| twin edges 28 (n24) / 534 (n120) (record `:264-266`) | `B_tie_class` directed_edges: 28 / 534 | PASS |
| suites (`P3-repair.md:186-198`) | twin 97/97; B4+ref-graphs 36; P1a/P1b 51; whole repo **2176 passed**; `pytest <probe|audit>` → "no tests ran"; `ruff check` both scripts → all checks passed; probe determinism byte-identical | PASS |
| boundaries | `git diff --numstat da79dfd 71c955d -- src` empty; `a927c7a..da79dfd -- experiments/texp-001` = 181/0 + 165/0; certified `test_corpus_admission.py`/`test_gr3_edges.py`/`test_b4_ref_graphs.py` byte-unchanged (numstat empty) | PASS |

## 2. Findings (doc-level; decision unaffected)

### F-R1 — MINOR (mislabeled budget in D3's summary): `P3-reconciliation.md:542-543`

The negative-result summary reads: *"the sampled budget covers 133 % / 52 %
/ 28 % / **3.3 %** (B=150) of it"*. Live probe output: B=150 covers
133.333 / 52.143 / 27.734 / **1.653** % at n=24/32/48/120; **3.307** % at
n=120 is the **B=300** figure. The first three figures are B=150, the fourth
is B=300, under a single "(B=150)" label. The per-budget table at `:192-196`
is correct (B150 n120 = 1.65 %, B300 n120 = 3.31 %), as is D1's "3.31 % at
n=120, B=300" (`:414`), so the error is confined to this one summary line —
but it sits inside §D3's recorded mechanism, the decision section itself.
It does not move the inference (both 1.65 % and 3.3 % state the same
coverage collapse at n=120), which is why this is a condition, not a
rejection.

### F-R2 — COSMETIC (stale ENUM_CAP max): `P3-reconciliation.md:237-238`, `P3-repair.md:144`

Both state the cap "never binds (max observed / max 4,937)". The repaired
probe's `B_pilot_seed_space` max is **4,933** (seed 1005; §1 table above),
and the record itself states the corrected range 3,466–**4,933** at `:251`.
4,937 is the pre-repair prefix-inflated max (audit `P3-audit.md:43`:
4600/3470/3875/4579/4502/**4937**). Either figure is ≪ 400,000, so the
fail-closed conclusion is unaffected — but strictly read, the 4,937 did not
come from a run on this branch, contra `P3-repair.md:32-33` ("Every count
quoted here comes from a run performed on this branch").

### Note (not a finding): probe↔audit eval-counter offsets

At identical (n, budget, steps) the two harnesses report slightly different
evals (e.g. n24/B150/steps75: probe E=68 → 133.33 % vs audit E=60 → 117.65 %;
n24/B300/steps150: 127 vs 136). Expected: different RNG stream names
(`probe-` vs `audit-`) and different BudgetOverrun absorption
(`texp_p3_reconcile_probe.py:231-249` vs `texp_p3_audit_checks.py:156-180`).
The repair claims space agreement only (`P3-repair.md:149-151`), which holds
exactly — no overclaim. Crossing positions agree under both harnesses.

## 3. Per-item closure (C1–C5 against live source)

**(a) C1 — PASS with C-R1 noted.** §D3 is headed **BANK-now**
(`P3-reconciliation.md:477`), superseding REDESIGN with reason (`:479-482`);
carries the double NO-GO (P4 `GO/NO-GO for EVAL: NO-GO` with σ_d=0.0 N=18
degenerate + B3/B4/B6 — live `texp-001/p4:experiments/texp-001/P4-report.md`;
p4-repilot §2–§4 all-18-cells-0.000 + EVAL/HOLD NO-GO — live
`texp-001/p4-repilot:experiments/texp-001/P4-repilot-report.md`), B4's two
zero-contributions, and the measured AND-rank mechanism (`:522-555`); three
shelve conditions in the required order — B4-scale grounding (alphabet or
chartered mapping), production sampler (`arms.py`: *"STIPULATED reference
behavior throughout (no production sampler exists — B1)"*, live
`HEAD:experiments/texp-001/arms.py`), rank-side design with pre-registered
protocol (`:557-578`); falsification note naming reopen / refute (F2 green
far below 100 % or red far above; p4b n=32 at 52 % already exhibits the
first) / not-evidence (`:584-601`). Grep over `docs/gr3-b4/`: zero surviving
affirmative single-predictor sentences — hits are the audit's historical
quotes, the repair log, and the negation *"falsifies coverage as the sole
predictor"* (`:550`). The old `:431` "only quantity", `:432-437` "control
coverage", R1–R4 block, "New evidence" list and `:462-468` trigger are gone
(no `R[1-4]` decision block, no `Falsification trigger` outside history).
The conjunction stands everywhere the deleted claim stood: §Context (iii)
*"coverage AND rank conjunction, never coverage alone"* (`:226-228`,
citing `P4-repilot-report.md:122-125` — verified live: *"even perfecting
coverage at this B cannot produce a hit without a ranking change … coverage
AND rank"*); §D1 *"moves neither half of the conjunction"* (`:419-421`);
§D2 *"necessary condition … ceiling — not a predictor"* + *"coverage AND
rank"* (`:465-472`); §D3 *"conjunction: coverage AND rank"* (`:547-550`).
The cited p4b grid is non-monotone live
(`texp-001/p4b-reaudit:experiments/texp-001/P4b-report.md`, "reading:
ranked_pool": n24 red ×6, n32 GREEN ×6, n48 red ×6, `green cells: 6/18`,
n=24 cause *"per-scale sign flip of the degree term (anti-planted at n=24
… 1.97x the mean degree)"*). SWEEP rationale retained verbatim (diffed
`168afd7` vs `71c955d` identical).

**(b) C2 — PASS.** Probe convention proven from both sides: probe
`tests/texp_p3_reconcile_probe.py:71` (`TWIN_STEPS = "budget // 2"`),
`:273` + `:300` (`steps = budget // 2`), `:318` (`"step_convention"`), JSON
`"step_convention": "budget // 2"`; twin `micropilot.py:81`
(`collect_ranked_candidates(..., b, b // 2, ...)` — live
`texp-001/p4b-reaudit`), `pilot.py:91` / `:137` (`collect_k_paths(..., b, b
// 2)` / `(..., cb, cb // 2)` — live `texp-001/p4`), signatures
`collect_k_paths(..., budget, steps, l_max=2)` /
`collect_ranked_candidates(..., budget, steps, l_max=2, ...)` confirming the
trailing positional is `steps`. Crossing honestly restated per budget (§1
triple, re-run confirmed). Caveat direction correct: twin steps (75/150) <
old constant 200 at B150/300 while probe evals exceed twin evals there
(150 vs 68–76; 170–199 vs 127–152), so old figures were upper bounds; repair
withdraws "lower bounds" as inverted and the record replaces it with the
true step-cap scope statement (`:229-236`, evals verified §1). Old `:158`
"both budgets" and `:170` "does not affect crossing" appear only as
withdrawn/deleted history (`:198-207`).

**(c) C3/C4 — PASS with C-R2 noted.** Walks primary + simple beside, with
the sampler-reachability reason (`kernel.propose` `kernel.py:114-141` has no
cycle check — confirmed live, no `visited`/`cycle` gate), in probe
`:137-148` and record `:164-172`; materiality 51 vs 31 stated. Length-1
honesty: probe counts iff full tuple ∈ `ADMISSIBLE_SEQUENCES` (`:161-162`),
`PROPER_PREFIXES` (`:81-82`, strict prefixes only) prune only (`:168`);
live `HEAD:experiments/texp-001/validator.py` holds 14-class alphabet
(`:29-44`, incl. `refines`/`analogous_to` as alphabet members) but the
sequence table (`:50-62`) admits only `("supports",)` / `("entails",)` as
singletons — `("refines",)` / `("analogous_to",)` refused as
`INADMISSIBLE_SEQUENCE` (`:102-113`) — so the old every-prefix census is
correctly excluded. `micro_scale_only` has zero hits in the repaired probe;
`scale_scope` + `pilot_grid_executed: false` emitted (`:311-315`, in JSON).
Tautology gone: B4 table header is `documents touching an edge` with 4/12/8/4
(record `:72-77`); probe emits `documents_touching_an_edge` +
`documents_equals_sources_by_construction` (`:124-126`, JSON `true` each);
`documents touched` survives only inside the F5 correction note (`:79-86`).
`ENUM_CAP` raises (`:163-167`) instead of truncating; never binds (max 4,933
≪ 400,000 — figure corrected per C-R2).

**(d) C5 — PASS.** `docs/gr3-b4/ROADMAP.md:48` records P3-reconcile ACTUAL on
`gr3-b4/p3` (`p3 → p3-audit → p3-repair`) with BANK-now outcome and exit
evidence; `:49` re-points chartered contradiction flags to RESERVED
`gr3-b4/p3-contradiction` (TBD, charter first), substance byte-unchanged
(diff `d383be2..71c955d` shows only the row split + notes; no charter act);
`:54-71` notes record the correction, UNSTARTED status, P2-seat openness
(p2-audit `485f09a` is ACCEPT WITH CONDITIONS C1–C3, `da79dfd` un-audited —
no `gr3-b4/p2-fix-audit` branch exists, verified), and texp-001 shelved
pre-EVAL pinned at `a927c7a` read-only. No other row claims `gr3-b4/p3`
(grep: only forward reference `P1b-extraction.md:178`, no branch claim).
Reserved name correctly not created as a branch (`git rev-parse --verify
gr3-b4/p3-contradiction` fails).

**(e) Retained audit-checks — OPINION (not relitigated, not a condition).**
The repair's change is status-note only (docstring `:3-11`, `TWIN_STEPS`
comment `:63-67`; `git diff d383be2 71c955d` confirms no code change).
"Marked historical" is sufficient to pass: the header states the
`step_convention` contrast is the audit's evidence of the ORIGINAL
`steps=200` vs twin `budget // 2`, the numbered list is framed as the state
the audit found, and output keys are labeled `record_steps_eq_200_*` vs
`twin_steps_eq_B_over_2_*` — a careful reader cannot mistake the repaired
probe's convention, and `space_convention` remains a live digit-exact check
(§1). Fragility noted for the record: the `step_convention` block is still
*live code* recomputed each run with no per-output historical flag, so a
naive JSON consumer could lift a `record_steps_eq_200_*` cell as current. If
the file is ever re-touched, rename to `historical_record_steps_eq_200_*` or
add `"historical": true`; as retained evidence, leave verbatim.

**(f) S6/DG-5 + change surface — PASS.** Changed files are docs + two
non-collected scripts; no `src/` (numstat empty), no TEXP lineage edit, no
fixture change. `Select-String` over both scripts for
`hermes|open\(|\.write|import os|import time|uuid|HumanDecision|apply_intent`
→ zero hits; all six twin modules import no `hermes` at scope. The record's
invariant block quotes `AGENTS.md:12-64` and claims only non-adjacency
(read-only probe, stdout only); DG-5 statement (no `src/hermes/research/*`
edit, twin modules hermes-free) verified live. No PILOT/TUNE/EVAL/HOLD grid
executed (bounded chains + disclosed sensitivity policies only, n=120 rows
are counts plus bounded chains per the probe's own `scale_scope`).

## 4. Verdict

**ACCEPT WITH CONDITIONS.** C1–C5 close against live source; the P3 repair
may stand as the BANK-now record once two trivial doc fixes land (same
branch, docs-only, no re-execution beyond the probe already run):

- **C-R1:** `P3-reconciliation.md:542-543` — separate the budgets: e.g.
"133 % / 52 % / 28 % (B=150) … 3.3 % at n=120 (B=300)" (or append the B=150
n120 figure 1.65 % with correct labels).
- **C-R2:** `P3-reconciliation.md:238` + `P3-repair.md:144` — "max observed
4,937" → **4,933** (the repaired `B_pilot_seed_space` max, consistent with
`:251`); optionally soften `P3-repair.md:32-33` to exempt named historical
figures.

No REJECT ground: no surviving single-predictor sentence, no harness-free
crossing claim, no inverted caveat, no mislabeled space, no tautology
column, no tracker collision, no src/TEXP mutation. The BANK-now decision
with its three shelve conditions and falsification note is the licensed move
on the cited evidence.

## 5. Relation to baseline

- Re-audit of `gr3-b4/p3-repair@71c955d`; adds only this file
(`docs/gr3-b4/P3-reaudit.md`) on `gr3-b4/p3-reaudit`. No `src/`, no twin,
no fixture, no ROADMAP change; full suite 2176 green on this tree before
commit (docs-only delta cannot perturb it); no push.
- Certified-number movement: none. Acquisition owners 18; governed corpus
6+6; `CORPUS_REFS`/`GOVERNED_CORPUS_REFS` untouched; twin pin `a927c7a`
referenced, never edited.
