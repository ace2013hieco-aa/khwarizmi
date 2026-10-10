# MERGE-AUDIT-DETECT — independent verification of MERGE-DETECT

**Target:** `merge/detect` @ `50c3fdc0d54e7051ff968f5f50bcdc518cbf99cb` (local-only).
**Base:** local `main` @ `ac1860a5b3500bcc970833e426120af4233b49af`.
**Integration record:** `docs/MERGE-LOG-DETECT.md`.
**Precedent:** `docs/MERGE-AUDIT-SCANFIX.md`.
**Authority window:** D9 **LAPSED** — merge + audit only. **Nothing was pushed.**

## Verdict

# **PASS**

All three lines integrated with zero conflicts and zero integrator-authored `src/`
change; every gate green; both mandated re-proofs (timing, fairness) green; the
census anchor green; the three prior audit findings dispositioned with evidence.
Two STOP-condition classes were actively tested and did not fire (no semantic
conflict, no red re-proof). Local `main` and `origin/main` are unmoved.

## 1. Method and scope

Verification was performed **in the isolated worktree** `D:/tmp/merge-detect-wt`
(branch `merge/detect`), never in the host checkout. Every gate and probe was run
with an absolute `PYTHONPATH=D:/tmp/merge-detect-wt/src`, and both pyright
invocations additionally passed an absolute `--pythonpath`. Import provenance was
asserted rather than assumed:

```
python: 3.14.1
hermes: D:\tmp\merge-detect-wt\src\hermes\__init__.py
```

Lineage counts for the input refs were taken in **throwaway detached worktrees**
(`D:/tmp/md-base` @ `ac1860a`, `D:/tmp/md-detex` @ `4d1513b`, `D:/tmp/md-fair` @
`33e0083`, `D:/tmp/md-census` @ `843c281`) so that no input ref was ever checked
out inside the integration worktree and no ref was moved. The behavioural probe
(`D:/tmp/md-probe/probe_detect.py`) was deliberately kept **outside** every worktree
so the integration tree stays patch-exact and the repository is not polluted with
scratch files.

Audit inputs were read from the branches that own them, because none of the three
audit documents exists at the merged tip:

| Audit doc | Owner branch | Commit |
|---|---|---|
| `docs/AUDIT-DET-EXPRESS.md` | `audit/det-express` | `18ab403` (target `4d1513b`) |
| `docs/AUDIT-CLAIM-GROUND.md` | `audit/claim-ground` | `94cacd1` (target `921f0c8`) |
| `docs/AUDIT-DOC-DRIFT2.md` | `audit/doc-drift2` | `55a7bc0` (target `020579f`) |

## 2. Inputs receipt

| Item | Value | Verified by |
|---|---|---|
| BASE local `main` | `ac1860a5b3500bcc970833e426120af4233b49af` | `git rev-parse main` |
| `origin/main` | `e4b276db7880cb8c0e17e1239e03c589138541ae` | `git rev-parse origin/main`, `git ls-remote origin` |
| `main` ahead of `origin/main` | **14 / 0 behind** | `git rev-list --left-right --count origin/main...main` → `0  14` |
| `fix/det-express` | `4d1513b30fcca4b09f564f528226114146cd7823` | `git log --format="%H %P"` → parent `a8f0180` |
| `fix/high04-fairness` | `33e00838f73e25def6a511ce29b92aa5fa827dd7` | parent `4d1513b` — **linear pair confirmed** |
| `fix/census-sweep` | `843c28122828021d0edafa163c4b83dd43c7735d` | parent `ac1860a` — **separate line confirmed** |
| `merge/detect` on remote | **ABSENT** | `git ls-remote origin refs/heads/main refs/heads/merge/detect` returns only `refs/heads/main` |

Merge-bases, independently: `merge-base(main, det-express)` = `a8f0180`;
`merge-base(det-express, fairness)` = `4d1513b` (i.e. fairness sits directly on
det-express); `merge-base(main, census)` = `ac1860a` (census sits directly on the
current base). This is exactly the topology the brief describes.

## 3. Patch-exactness — independently re-derived

The log's INV-A…INV-G were re-run from scratch. Raw results:

```
=== INV-A det-express own delta (main..b35373d) ===
 scripts/replay_diff.py                | 266 ++++++++++++++++++++++++++++++++++
 src/hermes/research/contradictions.py |  93 ++++++++----
 src/hermes/research/controller.py     |  15 +-
 tests/test_replay_diff.py             |  95 ++++++++++++
 4 files changed, 442 insertions(+), 27 deletions(-)
--- authored (a8f0180..4d1513b) ---
 scripts/replay_diff.py                | 266 ++++++++++++++++++++++++++++++++++
 src/hermes/research/contradictions.py |  93 ++++++++----
 src/hermes/research/controller.py     |  15 +-
 tests/test_replay_diff.py             |  95 ++++++++++++
 4 files changed, 442 insertions(+), 27 deletions(-)

=== INV-B fairness own delta (b35373d..54b0a6e) ===
 src/hermes/research/contradictions.py | 165 +++++++++++++++++++++++++++++-----
 src/hermes/research/controller.py     |   5 +-
 tests/test_replay_diff.py             |  96 +++++++++++++++++++-
 3 files changed, 238 insertions(+), 28 deletions(-)
--- authored (4d1513b..33e0083) ---
 src/hermes/research/contradictions.py | 165 +++++++++++++++++++++++++++++-----
 src/hermes/research/controller.py     |   5 +-
 tests/test_replay_diff.py             |  96 +++++++++++++++++++-
 3 files changed, 238 insertions(+), 28 deletions(-)

=== INV-C census own delta (54b0a6e..50c3fdc) ===
 src/hermes/eval/ops.py                  |   8 +-
 src/hermes/research/programs.py         |   4 +-
 src/hermes/tools/capabilities/invoke.py |   2 +-
 src/hermes/tools/providers/hazards.py   |   2 +-
 src/hermes/tools/providers/normalize.py |   8 +-
 tests/test_census_anchor.py             | 165 ++++++++++++++++++++++++++++++++
 6 files changed, 177 insertions(+), 12 deletions(-)
--- authored (ac1860a..843c281) ---
 src/hermes/eval/ops.py                  |   8 +-
 src/hermes/research/programs.py         |   4 +-
 src/hermes/tools/capabilities/invoke.py |   2 +-
 src/hermes/tools/providers/hazards.py   |   2 +-
 src/hermes/tools/providers/normalize.py |   8 +-
 tests/test_census_anchor.py             | 165 ++++++++++++++++++++++++++++++++
 6 files changed, 177 insertions(+), 12 deletions(-)

=== INV-D fairness-owned files byte-identical to fairness tip ===
IDENTICAL (exit 0)

=== INV-E census-owned files byte-identical to census tip ===
IDENTICAL (exit 0)

=== INV-F precise conflict-marker scan ===
PRECISE_MARKER_EXIT=1 (1 = zero true markers)

=== INV-G controller.py merged delta == authored delta ===
merged +/- lines : 18
authored +/- lines: 18
IDENTICAL (exit 0)
```

**Per-merge own-delta equals authored delta** for all three merges, row for row, and
**every exclusively-owned file is byte-identical to its owning tip**. The strongest
single result is INV-G: `git diff main HEAD -- src/hermes/research/controller.py`
carries exactly the same 18 `+`/`−` lines as `git diff a8f0180 33e0083` on the same
file. Base `main`'s W4 hunks cancel out of the comparison because they are already
present on both sides — which simultaneously proves the merge preserved them and that
the integrator authored nothing there.

Two-sided confirmation that W4 survived verbatim, at the merged tip:

| Provenance | Merged-tip lines |
|---|---|
| base `main` W4 | `controller.py:3115` `binder = getattr(entry, "bind_controller", None)`; `:3163` `if getattr(entry, "wiring_template", False):`; `:3173`/`:3181` `recorded_no = …`; `:3186` `f"{recorded_no} — zero-row "` |
| lines 1+2 detector | `controller.py:2425` `DETECTOR_TRUNCATED,`; `:2430` `diagnostics: dict = {}`; `:2434` `rows, diagnostics=diagnostics)`; `:2442` `truncated = diagnostics.get(DETECTOR_TRUNCATED)`; `:2448` `f"{DETECTOR_TRUNCATED}: pair cap "` |

## 4. Re-proofs

### 4.1 HIGH-04 timing re-proof — the `n=500` number

**What was required.** The HIGH-04 triage record (`.hermes/PHASE2_TRIAGE.md:19`,
`:51-69`, `:131`, on branch `audit/r1-manifest` — *not* on `main`, and therefore not
present at the merged tip) states the finding as "Contradiction detector DoS
(O(n²))" with verdict "⚠️ **UNPROVEN — needs repro first**", and imposes the
condition: *"Required before a brief: a reproduction that constructs a realistic
candidate row count and measures wall-time / memory… If neither can be produced, this
closes as unsubstantiated. Do not write a performance 'fix' against an unmeasured
baseline."* That is the measurement performed here.

**Shape.** One dense group (`p1/prog/hyp`), all rows mutually eligible, cap fixed at
`DEFAULT_MAX_PAIRS = 500` (`contradictions.py:57`), wall-clock of the detector pass
over n = 100 → 1600 candidate rows.

At the merged tip (`CONTRADICTION_DETECTOR_VERSION = "cx-detect-v3"`,
`contradictions.py:65`):

```
HIGH-04 TIMING RE-PROOF (single dense group, cap 500)
  n rows  eligible-ish  emitted    wall_s  truncated
     100          4950      500    0.0058       True
     200         19900      500    0.0060       True
     400         79800      500    0.0056       True
     500        124750      500    0.0056       True
     800        319600      500    0.0060       True
    1600       1279200      500    0.0061       True

>>> n=500 headline: emitted=500 wall=0.0058s truncated=True
    max_pairs=500 groups=1 truncated_groups=['p1/prog/hyp']
    keys=['emitted', 'groups', 'max_pairs', 'per_group', 'truncated_groups']
```

Baseline `fix/det-express` @ `4d1513b` (`cx-detect-v2`), same probe:

```
detector version: cx-detect-v2
  n rows  eligible-ish  emitted    wall_s  truncated
     100          4950      500    0.0030       True
     200         19900      500    0.0035       True
     400         79800      500    0.0029       True
     500        124750      500    0.0029       True
     800        319600      500    0.0031       True
    1600       1279200      500    0.0033       True
>>> n=500 headline: emitted=500 wall=0.0029s truncated=True
    keys=['emitted', 'max_pairs']
```

**The `n=500` number: emitted = 500, wall = 0.0056–0.0058 s, truncated = True,
max_pairs = 500, groups = 1, truncated_groups = `['p1/prog/hyp']`.**

**Reading.** Eligible pairs grow from 4,950 to 1,279,200 — a factor of **258×** —
while wall time moves from 0.0058 s to 0.0061 s, a factor of **1.05×**, i.e. flat
inside measurement noise. The pass is bounded by the cap, not by the candidate
count. v2 is flat too (0.0030 → 0.0033 s, 1.10×). v3 costs roughly **1.9×** v2's
constant factor at n=500 (0.0056 vs 0.0029 s) — the price of round-robin scheduling
plus the exact-fit re-scan — and remains in the single-digit-millisecond range.

**Consequence for HIGH-04.** No quadratic (or worse) wall-time blowup is reproducible
at either version. Per the triage's own closure rule, HIGH-04 **closes as
unsubstantiated** at the merged tip: the DoS premise required an unbounded pass, and
the pass is capped and flat. This is recorded as a *measurement*, not as a claim
about scientific validity, and not as a performance improvement — the fairness line
changed **pair-selection order**, not complexity class, and it did not need a
performance justification to be correct.

### 4.2 Cap-fairness distribution — det-express finding (A)

**Shape.** The exact configuration recorded as Probe S7 in
`docs/AUDIT-DET-EXPRESS.md` finding (A) (`audit/det-express` @ `18ab403`): cap = 50,
one dense group `prog-c` (40 rows, 400 eligible, sorts **first**) and one small group
`prog-d` (3 rows, 2 eligible, sorts **last**).

At the merged tip (v3):

```
CAP FAIRNESS DISTRIBUTION (audit Probe S7 shape, cap=50)
total emitted   : 50 (cap 50)
group prog-c    : 48 pairs  (400 eligible, dense, sorts FIRST)
group prog-d    : 2 pairs  (2 eligible, sorts LAST)
DETECTOR_TRUNCATED: max_pairs=50 emitted=50 groups=2
  truncated_groups: ['p1/prog-c/hyp-c']
  per_group[p1/prog-c/hyp-c] = {'emitted': 48, 'truncated': True}
  per_group[p1/prog-d/hyp-d] = {'emitted': 2, 'truncated': False}
```

At `4d1513b` (v2), same probe:

```
total emitted   : 50 (cap 50)
group prog-c    : 50 pairs  (400 eligible, dense, sorts FIRST)
group prog-d    : 0 pairs  (2 eligible, sorts LAST)
DETECTOR_TRUNCATED: max_pairs=50 emitted=50 groups=None
  truncated_groups: None
  per_group: ABSENT (this detector version does not report per-group emission)
```

**Delta.**

| Group | v2 (`4d1513b`) | v3 (merged tip) | Audit's recorded expectation |
|---|---|---|---|
| `prog-c` (dense, sorts first) | **50** | **48** | 50 |
| `prog-d` (small, sorts last) | **0 — STARVED** | **2 — NOT starved** | 0 |
| `DETECTOR_TRUNCATED` keys | `['emitted','max_pairs']` | `['emitted','groups','max_pairs','per_group','truncated_groups']` | — |
| per-group emission reported | **no** | **yes** | — |
| starved/truncated groups named | **no** | **yes** (`truncated_groups`) | — |

v2 reproduces the audit's Probe S7 result exactly (`prog-c` 50 / `prog-d` 0), which
confirms the probe is measuring the same thing the auditor measured. v3 removes the
starvation. Finding (A)'s MUST-FIX offered three acceptable remedies — a per-group
cap, round-robin, **or** reporting starved groups; v3 implements round-robin **and**
reports per-group emission **and** names the truncated groups, so it satisfies the
finding on all three limbs rather than one.

**No regression in the neighbouring invariants**, measured at v3:

```
EXACT-FIT CAP (eligible == max_pairs must not report TRUNCATED)
  cap=3: emitted=3 truncated_flag=True      (4 eligible, 3 emitted -> genuinely truncated)
  cap=4: emitted=4 truncated_flag=False     (exact fit -> correctly silent)
  cap=5: emitted=4 truncated_flag=False     (over-provisioned cap -> correctly silent)

ORDER INDEPENDENCE (shuffled input -> identical output)
  5 shuffles identical to unshuffled: True
```

The exact-fit block is byte-identical between v2 and v3, so the fairness rewrite did
not disturb the cap-boundary semantics the det-express audit had already marked PASS
(cap boundary exact, shuffle-invariance). The exact-fit behaviour is pinned by
`tests/test_replay_diff.py:163` and order-independence by `:89` and `:173`.

### 4.3 Anchor green

```
$ PYTHONPATH=D:/tmp/merge-detect-wt/src .venv/Scripts/python.exe \
      scripts/run_tests.py tests/test_census_anchor.py -v
============================== 3 passed in 1.45s ==============================
ANCHOR_EXIT=0

$ … scripts/check_census.py
PASS - every certified figure is reproduced exactly.
CHECK_CENSUS_EXIT=0
```

Both agree at the merged tip: the anchor test (new, `tests/test_census_anchor.py:
165` lines, 3 tests) and the certified-census checker (8/8 figures OK — 121
transaction-control calls; owners persistence 18 / gateway 5 / Controller 4 = 27;
1 rollback-only; 15 persistence→research statements; 0 control calls outside
certified layers). **Anchor green.**

### 4.4 Detector tests and differential-replay harness

```
$ … scripts/run_tests.py tests/test_replay_diff.py -v
============================= 14 passed in 1.16s ==============================

$ … scripts/replay_diff.py
PASS run_twice_equal[n=5]
PASS journal_reproduces_derived[n=5]
PASS fan_out_bounded[n=100]
HARNESS_EXIT=0
```

The harness's own `FAN_OUT_BOUND = 500` (`scripts/replay_diff.py:47`) is asserted to
be ≥ the detector's `DEFAULT_MAX_PAIRS = 500`, so the bounded-fan-out check cannot
silently pass by being looser than the cap it claims to bound.

### 4.5 Full suite, lint, types

| Gate | Result |
|---|---|
| Full suite | `3800 passed, 12 warnings in 619.11s (0:10:19)` — exit 0 |
| `uvx ruff check src tests` | `All checks passed!` — exit 0 |
| `uvx pyright --pythonpath <abs> src` | **0 errors, 0 warnings, 0 informations** |
| `uvx pyright --pythonpath <abs> --project pyrightconfig.tests.json` | **0 errors, 1 warning, 0 informations** |

Suite count is corroborated three independent ways: 3800 progress-outcome characters,
all `.` (census `{'.': 3800}`, no `F`/`E`/`s`/`x`); 3800 collected
(`--collect-only`, 100 test files); and the pytest summary line above.

Method note: the summary line was absent from the first run because
`pyproject.toml:38 addopts = "-q …"` combined with a command-line `-q` yields
double-quiet, which suppresses it. A canonical re-run at the same worktree and HEAD
(no extra `-q`) produced `3800 passed, 12 warnings in 619.11s (0:10:19)`,
`FULLSUITE_EXIT=0`. The count therefore rests on the printed summary, not only on
inferred outcome characters.

The one pyright-tests warning is `tests/test_research_program.py:144:23 -
reportSelfClsParameterName`. That file is not in the changed-file set and the warning
is inherited from base `main`. It is a warning, not an error; the gate exits 0.

## 5. Audit dispositions

### 5.1 `docs/AUDIT-DET-EXPRESS.md` finding (A) — cap fairness/starvation → **PROVEN-CLOSED**

Evidence: §4.2. The audit's own Probe S7 shape is reproduced at v2 (`prog-d` = 0,
starved) and shown fixed at v3 (`prog-d` = 2, not starved), with per-group emission
and named truncated groups now in the `DETECTOR_TRUNCATED` payload. All three of the
finding's acceptable MUST-FIX remedies are satisfied simultaneously.

**Finding (B) — version-bump honesty (SHOULD-FIX) → CLOSED on its version limb;
PARTIALLY ADDRESSED on its truncation-visibility limb (residual noted).**

*Version limb — CLOSED.* The selection change is versioned and the version comment
states the semantic reason, not just the number: `contradictions.py:63-64` reads
`# v3: pair selection changed from sorted-group sequential (first groups starve later
ones under the cap) to sorted-group round-robin fairness.` above
`CONTRADICTION_DETECTOR_VERSION = "cx-detect-v3"` (`:65`). Identity is still
content-hash over the canonical pair, and the comment at `:60-62` pins the separation
explicitly (`identity is unaffected (version is provenance, not identity)`), so the
bump is provenance only and is not smuggled into identity.
`tests/test_replay_diff.py:101` (`test_detector_version_bumped_for_selection_change`)
pins it.

*Truncation-visibility limb — PARTIALLY ADDRESSED, not closed.* The payload is now
materially richer: `DETECTOR_TRUNCATED` carries `max_pairs`, `emitted`, `groups`,
`truncated_groups` and `per_group` (`contradictions.py:294-295`), where v2 carried
only `max_pairs` and `emitted`. It is also threaded out of the detector pass as
`"truncated": truncated` (`controller.py:2491`) and rendered into a condition-keyed
note (`controller.py:2448`, `key="contradiction:detector-truncated"`).

But the audit's specific objection — that truncation is **in-memory only** — still
holds on the automatic path:

- the note is recorded via `_note_once` (`controller.py:907`), which appends to
  `self._notes: list[str]` (`:815`, exposed read-only at `:846`) — process-local, never
  journaled, so it does not survive a controller restart and leaves no append-only
  record;
- the automatic tick call site **discards the return value** entirely:
  `controller.py:1048` is a bare `self._detect_contradictions_pass()` statement, so the
  `"truncated"` payload at `:2491` is observable only on the operator-facing wrapper
  (`:2405` `return self._detect_contradictions_pass()`), not on the every-ACTIVE-tick
  path where truncation would actually go unnoticed.

Recording this as a **residual** rather than a closure: the fairness fix improved what
is *reported* but did not change *where it is recorded*. Making truncation durable
would mean a journal row, which is a behaviour change outside this integration's
"no `src/` changes beyond conflict repair" constraint and belongs to the owning line.

**Finding (C) — harness blind spots (NOTE) → CLOSED.** The four coverage gaps the
audit named (shuffle, starvation, cap-boundary, version replay) are now pinned:
`test_cap_is_order_independent:89`, `test_multigroup_cap_is_order_independent:173`,
`test_round_robin_late_groups_get_pairs:131`, `test_per_group_truncation_recorded:147`,
`test_exact_fit_reports_no_truncation:163`, `test_uncapped_multigroup_emits_full_set:180`,
`test_detector_version_bumped_for_selection_change:101`, `test_rejects_non_positive_cap:96`.
That is the +5-test delta from `4d1513b` → `33e0083` (9 → 14 methods).

### 5.2 `docs/AUDIT-CLAIM-GROUND.md` finding (C) — experiment-gate false refusals → **OUT OF SCOPE FOR THIS INTEGRATION** (downgraded; gate-doc landed elsewhere)

The finding's subject code **does not exist at the merged tip**:

```
$ git grep -n "_experiment_admitted" HEAD -- src tests scripts
  ZERO HITS at merged tip
$ git grep -n "experiment_resolver|unverified_experiment_ref" HEAD -- src
  (no output)
```

The code lives on `fix/claim-ground` @ `921f0c8` (`def _experiment_admitted` at
`controller.py:5372`, wired as `experiment_resolver=` at `controller.py:5398`, in that
ref's numbering). `921f0c8` is **not an ancestor of `main`**
(`git merge-base --is-ancestor 921f0c8 ac1860a` → NO; `merge-base` = `a8f0180`), so
the claim-ground line is not part of BASE and was not one of the three lines this task
was scoped to integrate.

The remediation the brief refers to ("downgraded → gate-doc landed") is
`05c3217` — `docs(claim-ground): record causal DIRECT/PARTIAL structural
inadmissibility + pin (finding C, res. b)` — on branch
**`fix/experiment-gate-doc-v2`**, touching `docs/ARCHITECTURE.md` (+7),
`docs/STATE.md` (+13), `tests/test_experiment_gate_pin_v2.py` (+71). Verified:

```
on main?        NO   (git merge-base --is-ancestor 05c3217 ac1860a -> NO)
in merge/detect? NO   (git merge-base --is-ancestor 05c3217 50c3fdc -> NO)
branches containing 05c3217: fix/experiment-gate-doc-v2
```

**Disposition: recorded, not integrated.** This merge neither carries nor needs the
gate-doc; the finding and its resolution (b) travel with the claim-ground /
experiment-gate lines. Stating this explicitly rather than silently omitting it, so
the closure is not mistaken for something this integration proved. No claim is made
here about whether resolution (b) is the right remedy — that belongs to the owning
line's gate.

### 5.3 `docs/AUDIT-DOC-DRIFT2.md` finding (B) — dormant wire → **CARRIED OPEN** (unchanged by this integration)

Checked at the merged tip rather than assumed. `README.md:160` still presents both
symbols as the live AR-03 hardening feature:

> `* AR-03 hardening (S1 empty-result artifact): migration 6→7 empty_result_artifacts, EmptyResultArtifactRepository, and validate_thesis_evidence (src/hermes/research/thesis.py) — a NONE_FOUND counter-search must dereference to a persisted artifact whose recorded terms cover the declared terms; 16 fixtures in tests/test_thesis_ar03.py.`

Caller census at the merged tip:

| Symbol | `src/` hits | `src/` **callers** | Call sites |
|---|---|---|---|
| `EmptyResultArtifactRepository` | 1 — `src/hermes/persistence/repositories.py:2499` (`class` definition) | **0** | `tests/test_thesis_ar03.py` only (16 refs) |
| `validate_thesis_evidence` | 3 — `src/hermes/research/thesis.py:12` (docstring), `:39` (`__all__`), `:98` (`def`) | **0** | `tests/test_thesis_ar03.py` only (16 refs) |

So the substance of finding (B) is **confirmed**: both symbols are reachable only from
their own tests, while the README presents them as a shipped feature. The one
sub-claim in that bullet which *is* accurate: `tests/test_thesis_ar03.py` contains
exactly **16** test functions (`grep -c "def test_"` → 16).

**Not introduced or worsened here.** `README.md`, `src/hermes/persistence/repositories.py`
and `src/hermes/research/thesis.py` are all absent from the changed-file set
(MERGE-LOG §4), and every one of the three integrated lines leaves them untouched.
The finding is inherited from BASE `main` and passes through this merge unmodified.

**Instrumentation caveat, stated plainly.** The audit's own checking machinery is not
available at the merged tip:

```
$ ls scripts/doc_pin_check.py
ls: cannot access 'scripts/doc_pin_check.py': No such file or directory
$ grep -n "EmptyResultArtifactRepository|validate_thesis_evidence" tests/test_dormant_registry.py
grep: tests/test_dormant_registry.py: No such file or directory
```

Both exist only on the doc-drift2 line's base (`020579f`). The finding was therefore
re-verified by **direct caller census** (the table above) rather than by re-running
`doc_pin_check.py` or reading the dormant registry — a weaker instrument, disclosed as
such. Findings (A) and (C) of that audit (pins PASS-with-NOTE; B4 byte-identity
PASS-with-NOTE) are likewise inherited and not re-litigated here; neither is in this
integration's changed surface.

**Owner:** the doc-drift2 line. **Status: OPEN — CARRIED.**

## 6. Counts and `file:line` at the merged tip

| Figure | Certified | Measured | Status |
|---|---|---|---|
| executed transaction-control calls | 121 | 121 | OK |
| acquisition owners — persistence | 18 | 18 | OK |
| acquisition owners — gateway | 5 | 5 | OK |
| acquisition owners — Controller | 4 | 4 | OK |
| acquisition owners — total | 27 | 27 | OK |
| rollback-only participants | 1 | 1 | OK |
| persistence→research import statements | 15 | 15 | OK |
| control calls outside certified layers | 0 | 0 | OK |
| statement breakdown | — | BEGIN 28, COMMIT 27, ROLLBACK 66 | recorded |
| test files / collected / passed | — | 100 / 3800 / 3800 | green |

Load-bearing citations at the merged tip:

| Claim | Location |
|---|---|
| pair cap | `src/hermes/research/contradictions.py:57` `DEFAULT_MAX_PAIRS = 500` |
| truncation diagnostic code | `contradictions.py:58` `DETECTOR_TRUNCATED = "DETECTOR_TRUNCATED"` |
| version bump + honest reason | `contradictions.py:63-65` → `CONTRADICTION_DETECTOR_VERSION = "cx-detect-v3"` |
| detector entry point | `contradictions.py:128` `def detect_classification_conflicts(` |
| per-group emission accounting | `contradictions.py:188` `per_emitted`, `:235-236` increment + progress flag |
| round-robin scheduling | `contradictions.py:204` `progress_in_round = False`, `:209`/`:225`/`:270` `capped = True`, `:242` `if not progress_in_round:` |
| truncated-group reporting | `contradictions.py:251` `truncated_groups`, `:276` append, `:280-295` `per_group` payload |
| controller diagnostics pass | `controller.py:2425`, `:2430`, `:2434`, `:2442`, `:2448` |
| W4 hunks preserved | `controller.py:3115`, `:3163`, `:3173`, `:3181`, `:3186` |
| harness fan-out bound | `scripts/replay_diff.py:47` `FAN_OUT_BOUND = 500` |
| census anchor | `tests/test_census_anchor.py` (165 lines, 3 tests) |
| dormant-wire finding | `README.md:160`; `src/hermes/persistence/repositories.py:2499`; `src/hermes/research/thesis.py:12,39,98` |

The triage record cited in §4.1 (`.hermes/PHASE2_TRIAGE.md:19,51-69,131`) is on
branch `audit/r1-manifest`, not on `main`; its `controller.py:2409`/`:2430-2438`
numbering predates the W-series and corresponds to `controller.py:2425-2495` at the
merged tip.

## 7. Documentation commits are `src`/`tests` neutral

`docs/MERGE-LOG-DETECT.md` and `docs/MERGE-AUDIT-DETECT.md` are committed
**separately, one file per commit**. After both:

```
$ git diff --exit-code 50c3fdc HEAD -- src tests scripts
(exit 0 — no output)
```

The integration tip's code content is therefore bit-for-bit unchanged by the
documentation deliverable.

## 8. Forbidden-topic scan

```
$ git grep -i -n -E "backtest_audit|optimize-my-strategy|\bSDA\b|\bTSE\b" HEAD -- src tests
SCAN_EXIT=1 (zero hits)
```

**Zero hits across `src` and `tests`.** No forbidden topic was introduced, and none of
the integrated lines touches one. Repo-wide, the same pattern matches only inherited
**negative** disclaimers already present on BASE `main`:

| Location | Text (truncated) | On `ac1860a`? |
|---|---|---|
| `README.md:185` | "`backtest_audit`, `ResearchFeatureEngine`, and the Statistical Engine are **external**. They are not implemented in this repo…" | yes (1 hit) |
| `docs/ARCHITECTURE.md:19` | "…run external engines in-repo (`backtest_audit`, feature/statistical…" | yes (1 hit) |

Both are statements that these systems are *out of scope*, not work on them, and both
pre-date this integration (`git grep -c` on `ac1860a` returns 1 hit for each file).
Remaining repo-wide matches are inside historical `docs/MERGE-*.md` / `audits/` records
of the same "NOT these projects" form. **No STOP condition fired.**

## 9. Platform integrity and no-push proof

```
$ git rev-parse main
ac1860a5b3500bcc970833e426120af4233b49af        <- UNMOVED (== BASE)

$ git rev-parse origin/main
e4b276db7880cb8c0e17e1239e03c589138541ae        <- UNMOVED

$ git ls-remote origin refs/heads/main refs/heads/merge/detect
e4b276db7880cb8c0e17e1239e03c589138541ae	refs/heads/main
                                                <- merge/detect ABSENT from remote

$ git rev-list --left-right --count origin/main...main
0	14                                          <- 14 unpushed platform commits intact

$ git rev-parse audit/r1-manifest
1918dad58452b0d5db4af177c5a8f71a968c8e4c        <- host checkout UNMOVED
```

- Local `main` was never checked out, rebased, amended, reset, or fast-forwarded; the
  integration ran entirely on `merge/detect` inside `D:/tmp/merge-detect-wt`.
- The **14 unpushed platform commits** (`efff4fd` … `ac1860a`) are untouched: `main`
  is still exactly 14 ahead / 0 behind `origin/main`.
- The remote was **read-only**: `ls-remote` and `rev-parse` only. No `push`, no
  `push --force`, no `push --tags`, no PR, no remote branch creation, no remote delete.
  `refs/heads/merge/detect` does not exist on `origin`.
- The host working branch `audit/r1-manifest` (`1918dad`) is unmoved, including its
  untracked `.hermes/reports/*` and `.hermes/briefs/*` files.
- **STOPPED BEFORE PUSH**, as required by a lapsed D9.

## 10. Residual notes (non-blocking)

1. **`doc-drift2` finding (B) stays open** and cannot be closed from this branch —
   its remediation belongs to the owning line, and the checking instruments
   (`scripts/doc_pin_check.py`, `tests/test_dormant_registry.py`) are absent here.
2. **`claim-ground` finding (C) is unverified by this merge**, by construction: the
   subject code and its gate-doc remediation are both outside the integrated set. If
   `fix/claim-ground` is later merged, finding (C) must be re-audited at that tip.
3. **v3 costs ~1.9× v2's constant factor** at n=500 (0.0056 s vs 0.0029 s) from
   round-robin scheduling plus the exact-fit re-scan. Flat and millisecond-scale, so
   accepted; recorded so the trade is visible rather than implied.
4. **The stale `.git/worktrees/step-4` admin entry** still cannot be pruned on this
   host (Windows file lock). It is cosmetic and pre-existing; see MERGE-LOG §7.
5. **Detector truncation is still in-memory on the automatic tick path.** The
   `DETECTOR_TRUNCATED` payload is richer at v3 (per-group emission, named truncated
   groups) and is returned as `"truncated"` (`controller.py:2491`), but the
   every-ACTIVE-tick call site (`controller.py:1048`) discards that return and the note
   lands in `self._notes` (`:815`) via `_note_once` (`:907`) — process-local, never
   journaled. This is the un-closed limb of det-express finding (B); see §5.1.
6. **`agents.md` cites "full suite (2101)"**, which is far below the measured 3800.
   That is pre-existing documentation drift on BASE `main`, outside this integration's
   changed surface, and is noted only so the discrepancy is not mistaken for a
   measurement error here.

## 11. Verdict

**PASS.** Integration is patch-exact (INV-A…INV-G), all gates are green with counts
(3800 passed / ruff clean / pyright 0+0 errors / census 8-of-8 / anchor 3 /
replay harness 3-of-3), both mandated re-proofs are green (timing flat at
n=500 → 0.0056 s under a 258× growth in eligible pairs; fairness `prog-d` 0 → 2),
and all three audit findings are dispositioned with evidence — det-express (A)
**PROVEN-CLOSED**, claim-ground (C) **out of scope / recorded**, doc-drift2 (B)
**CARRIED OPEN**. Nothing was pushed; local `main`, `origin/main`, and the host
checkout are all unmoved.
