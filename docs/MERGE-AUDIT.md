# MERGE-AUDIT — `merge/pyright-scope@9dc63a0` (independent adversarial merge audit)

**Audit branch:** `merge/audit`, cut from `merge/pyright-scope@9dc63a0` (local-only; no pushes).
**Audited tree:** `9dc63a0` = `cbc95c3` (`merge/gr3b4-step4` tip) + one config-only commit.
**Lineage audited:** `main@c0b5777` → `945a6e8` (merge of `gr3-b4/closeout@f4d2be0`) → `c91ceb4` (merge of
`step-4/closeout@d614c1f`) → `cbc95c3` (MERGE-LOG) → `9dc63a0` (pyright-scope exclusion).
**Role:** Adversary (fresh session). Falsify, don't confirm. Read-only except this file; no `src/`, test,
or config edits; no pushes.
**Verdict:** **PASS WITH CONDITIONS** — see §8. No gate red, no cross-line interference, no fixture
collision, merge replay is bit-exact. Two record-integrity defects (C1, C2) and one test-strength
regression (C3) are owed before a mainline merge.

## 1. Inputs (receipt confirmed)

| Input | Status | Where read |
|---|---|---|
| Full file list of `9dc63a0` vs `main@c0b5777` (71 files, not ~70 — see §7 F5) | READ | `git diff --name-status c0b5777 9dc63a0`, `git diff --numstat` |
| `docs/MERGE-LOG.md` at `9dc63a0` | READ | working tree + `git show cbc95c3` |
| The pyright exclusion + director decision `MERGE/pyright-scope` | READ | `pyrightconfig.tests.json`, `git show 9dc63a0` |

No input was unreadable. Nothing in the repository referred to `backtest_audit`, `SDA`, `TSE`, or
`Optimize-my-strategy`; no stop condition was triggered.

## 2. Method (what was re-run vs trusted)

Everything below was **re-run in this session** unless a row says TRUSTED. Nothing about the audited
tree was taken from MERGE-LOG without independent reproduction.

- Full suite: `.venv/Scripts/python.exe scripts/run_tests.py` → **2209 passed in 413.37s**.
- `uvx ruff check src tests` → **All checks passed!**
- `uvx pyright src` → **0 errors, 0 warnings, 0 informations**.
- `uvx pyright --pythonpath .venv/Scripts/python.exe --project pyrightconfig.tests.json` → **0 errors, 1 warning**.
- Twin suite (not in the canonical gate): `scripts/run_tests.py experiments/texp-001` → **97 passed**.
- Both probe scripts executed directly (exit 0 each); both packaged fixtures rebuilt and byte-compared.
- Merge replay: `git merge-tree --write-tree` for both merges, compared against the recorded merge trees.
- TRUSTED (not re-derived): the S-R1/S-R2 adversarial audits' PASS verdicts recorded in
  `docs/idr/step4_s_r1_adversarial_audit.md` and IDR-044; the GR3 per-phase audits in `docs/gr3-b4/`.
  Those are the *lines'* own audits; this audit re-tested the claims that matter to the merge.

## 3. Attack 1 — cross-line interference (GR3 extraction × regime validation)

**Result: NO INTERFERENCE FOUND.** The two lines are file-disjoint, and no runtime input of either
substrate changed.

**(a) File disjointness (mechanical).** `comm -12` of the two lines' changed-file sets
(`git diff --name-only c0b5777 945a6e8` vs `git diff --name-only 945a6e8 c91ceb4`) is **empty**.
GR3 adds only files; step-4 modifies 3 source files + 5 test files. The single code-level coupling is
`hermes.research.{corpus,graph_edges,ref_graphs}` importing `canonical_json`/`sha256_hex` from
`hermes.research.programs` — a module step-4 *did* touch, but the step-4 hunk touches neither helper
(only the import block and the `target_regime` check). The new `programs → regimes` import introduces no
cycle: `regimes.py` imports only `collections.abc`, `dataclasses`, `enum`, `typing`.

**(b) Constructed case: regime-tagged doc through the extractor.** A governed corpus document
(`docs/idr/IDR-036.md`, the IDR that declared the regime resolver DEFERRED and that step-4 now wires) was
appended with both a registered and an unregistered regime tag and pushed through
`extract_cites_mentions` + `validate_gr3_extraction`:

```
[C1] cited: ('docs/idr/IDR-026.md',)
[C1] skipped: ('IDR-037', 'docs/idr/hermes_v6_authority_evidence_map.md', ... 6 more)
[C1] regime tag fabricated as edge? False | high-vol? False
[C1] verdict: ADMITTED edges: [('docs/idr/IDR-036.md', 'docs/idr/IDR-026.md')]
```

The injected regime tags produced **no** edge and no `skipped` token: the extractor's mention grammar
(`_MENTION_RE`: `*.md` paths and `IDR-\d+`) cannot see a `VERSION:id` tag, so the regime axis can never
masquerade as citation structure, and the presence of regime text does not perturb the derived set.

**(c) Extracted edge → regime resolver (both directions).** Every derived endpoint through
`resolve_regime(parse_regime_ref(...))`:

```
refused citing='docs/idr/IDR-036.md' -> UNVERSIONED_REGIME
refused cited='docs/idr/IDR-026.md'  -> UNVERSIONED_REGIME
```

A regime tag smuggled in as an edge endpoint refuses at the extraction gate as well:
`[C3] regime tag as cited_ref -> INVALID ["hallucinated: 'ICSS-v1:low-vol' not cited by the bytes",
"dropped: 'docs/idr/IDR-026.md' cited by the bytes but unclaimed"]`. Fail-closed in both directions; no
silent acceptance, no crash.

**(d) The regime side consumed the same channel correctly.** `evaluate_regime("ICSS-v1:low-vol", snap)`
→ `NOT_IN_REGIME` when the declared context carries an extracted document ref, `IN_REGIME` when it
carries the registered tag, and `derive_transition(...)` returned `IN_REGIME / SIMULATED` with
`authoritative_transition` passing it through. Registry size measured: **exactly
`{'ICSS-v1:low-vol'}`** (one entry, as IDR-044 D1 claims).

**(e) The decisive test — did the merge move the GR3 substrate's inputs?** No:

- All **12 governed corpus documents are untouched** by both lines:
  `git diff --name-only c0b5777 9dc63a0 -- <the 12 refs>` is empty.
- The `.gitattributes` eol pins match `GOVERNED_CORPUS_REFS` **exactly** (12 vs 12; both differences
  empty) — the C1 EOL-stability claim is structurally sound, not just asserted.
- All **4 packaged fixtures regenerate byte-identically from live bytes** (4/4, `bytes_equal=True`),
  i.e. the content-addressed B4 fixtures are invariant under this merge.

**(f) Reverse direction.** GR3 adds no intent kind (`src/hermes/core/intents.py` is untouched by both
lines), no event type, no migration, and its persistence modules import nothing from `hermes.research`
(verified by an import census, §7 F1). It therefore cannot alter regime validation.

## 4. Attack 2 — fixture/test collisions

**Result: NO COLLISION FOUND.**

- `tests/conftest.py` defines **no fixtures** (docstring + plugin-isolation only), so there is no shared
  fixture surface for the two lines to shadow.
- Both lines' test fixtures are module-local: GR3 files define 3/3/4 fixtures, `test_regimes.py` 0.
- Intersection of top-level `def`/`class` names between the GR3-added test files and the step-4
  added/modified test files is only `def db()` — a module-local helper in each, no shadowing.
- No test name is shared across the two lines. The only duplicate names in the whole suite
  (`test_agreement_constants_byte_identical`, `test_task_payload_is_gateway_shaped`) are **both from the
  GR3 line**, and they pin *different* pairs (`research.graph_edges` ⇄ `persistence.graph_edges` vs
  `research.corpus` ⇄ `persistence.corpus`), so they are not double-counts of one fact.
- Duplicated module-local constants (`REPO_ROOT`, `ALL_REFS`, `P1A_SIX`, `CERTIFIED_BASELINE`) are
  deliberate independent pins; the direction of failure is safe (drift turns a test red).
- One coverage note (see §7 F4): the twin's fourth copies of the B4 agreement constants are pinned only
  by `experiments/texp-001/test_b4_source.py`, which the canonical gate does not collect.

## 5. Attack 3 — honesty of the pyright exclusion

**Result: HONEST AND NARROW — PASS.** The comment's two claims were tested separately.

- *"probe scripts verified by execution"* — TRUE. Both were executed in this session and both completed
  cleanly: `python tests/texp_p3_reconcile_probe.py` → `EXIT=0` (emits its JSON reconciliation record,
  `"step_convention": "budget // 2"`, `"pilot_grid_executed": false`);
  `python tests/texp_p3_audit_checks.py` → `EXIT=0` (emits its JSON evidence, e.g.
  `"n": 120, "true_simple_space": 4086, "true_walk_space": 4597`).
- *"their sys.path imports are invisible to pyright"* — TRUE and narrowly so. The two files are
  scripts, not tests: neither contains any `def test_` and neither filename matches pytest's
  `python_files` patterns, so the exclusion hides **no collected test** (`--collect-only` reports
  0 `texp_p3` items; the suite's 2209 total is unaffected).
- *The exclusion is not masking type errors.* With the ignore removed for those paths (root project:
  `extraPaths=["src"]`, no ignore), the two files emit **exactly 12 errors, all
  `reportMissingImports`** — `arms`, `energy`, `fixtures`, `generator`, `kernel`, `validator` at
  `texp_p3_audit_checks.py:42-46,54` and `texp_p3_reconcile_probe.py:45-47,52-53,61` — and **nothing
  else**. The pre-fix tests project reported the same 12 (`12 errors, 1 warning`); post-fix, `0 errors,
  1 warning`. The 1 remaining warning is `tests/test_research_program.py:143`
  (`reportSelfClsParameterName`), pre-existing on the source branch and unrelated to the regime wiring.
- Residual risk (recorded, not a defect): pyright applies `ignore` even to explicitly-passed CLI paths
  (verified: passing both files by path under the tests project still reports `0 errors`), so those two
  files are unanalyzable *under that project* by construction. The bounded risk is documented by the
  measurement above.
- Scope honesty: the commit touches exactly one file with no `.py` change —
  `pyrightconfig.tests.json | 5 +++++` (`git show --stat 9dc63a0`), and the mechanism is the top-level
  `ignore` list (the config has neither `executionEnvironment` nor a pre-existing ignore list).

## 6. Attack 4 — merge fidelity

**Result: BIT-EXACT REPLAY — PASS.**

| Merge | Recorded parents | Replay | Recorded tree |
|---|---|---|---|
| `945a6e8` | `c0b5777` + `f4d2be0` | `git merge-tree --write-tree c0b5777 f4d2be0` → `56c48f66fad7123731359ec62b3307854fff9e33`, no conflict output | `56c48f66fad7123731359ec62b3307854fff9e33` |
| `c91ceb4` | `945a6e8` + `d614c1f` | `git merge-tree --write-tree 945a6e8 d614c1f` → `209c104889d459cd2ba1685128dc743063376537`, no conflict output | `209c104889d459cd2ba1685128dc743063376537` |

Each merge commit has exactly two parents, and its tree equals the automatic merge of those parents.
**This is proof, not testimony, of the zero-resolution claim**: any hand-edit during either merge — even
one that resolved nothing — would have produced a tree different from the mechanical merge. Both merges
were therefore purely additive unions, and no behaviour can have been smuggled in at a resolution point
(there were none). Line statistics also reproduce MERGE-LOG exactly: GR3 `55 files changed, 10545
insertions(+)`; step-4 `14 files changed, 1496 insertions(+), 56 deletions(-)`. The one config-only
commit (`9dc63a0`) touches `pyrightconfig.tests.json` alone.

## 7. Gate integrity, and the findings that survived

**Gates (all re-run here, on the audited tree): all green.**

| Gate | Result |
|---|---|
| `scripts/run_tests.py` (full suite) | **PASS — 2209 passed in 413.37s** (matches MERGE-LOG's 2209) |
| `uvx ruff check src tests` | **PASS** |
| `uvx pyright src` | **PASS — 0 errors, 0 warnings, 0 informations** |
| tests pyright project | **PASS — 0 errors, 1 warning** (warning pre-existing) |
| twin suite `experiments/texp-001` (out-of-band) | **PASS — 97 passed** |

### FINDINGS

**F1 — MODERATE. The DG-5 intentional-dependency census is stale: the merge adds 2 new
`persistence → research` import statements, and imports a research module DG-5 never classified.**
Measured census of module-level `from|import hermes.research...` statements under
`src/hermes/persistence/`:

| rev | failure_classifications | program_obligations | repositories | source_outcomes | total |
|---|---|---|---|---|---|
| `c0b5777` (main) | 1 | 2 | 9 | 1 | **13** |
| `9dc63a0` (merge) | 2 | 2 | 10 | 1 | **15** |

The new sites are `failure_classifications.py:65` and `repositories.py:64`, both
`from hermes.research.regimes import (...)`. `docs/ARCHITECTURE.md` §3.10 still states "A bounded set of
persistence→research runtime dependencies **(13 import statements)** remains by deliberate decision"
and "Do not extend this pattern; new upward dependencies need an explicit design gate"; `AGENTS.md`
line ~76 likewise still reads "No persistence→research imports beyond the existing intentional
exceptions … Do not add new upward dependencies without an explicit design gate". Neither file is
touched by the merge, and neither new site appears in the §3.10 classified list.
Mitigating: IDR-044's S-R2 addendum is a genuine design record that *decides* the wiring (A6/A7), so an
explicit design gate does exist on paper; what is missing is the recorded-dependency reconciliation.
Its claim "The recorded census (16/5/5+1) and recorded debt (`hazards.py:137`) are unchanged" does not
cover the 13-statement import census, which did change.

**F2 — MODERATE. The certified transaction census is stale by +2 persistence owners, and the tree
contradicts itself.** GR3 lands two new mutation boundaries in persistence —
`CorpusRepository.record` (`persistence/corpus.py:165`, `BEGIN IMMEDIATE`) and
`GraphEdgeRepository.record` (`persistence/graph_edges.py:142`, `BEGIN IMMEDIATE`) — and says so in its
own docstrings ("persistence 16 → 17 owners"; "persistence 17 → 18 owners") and reports
(`P1a-admission.md:137`, `P1b-audit2.md:65` "CONFIRMED", `P1b-extraction.md:174`,
`P3-reconciliation.md:53` "stay at 18"). But the certified statements the merge ships are untouched:
`AGENTS.md:23` "25 acquisition owners across persistence (16), gateway (5), and Controller (4)" and
`docs/ARCHITECTURE.md:144` "113 executed transaction-control calls held by 25 acquisition owners
… persistence 16". Both GR3 documents even *quote the stale text* (`P2-b4fixtures.md:121`,
`P3-reconciliation.md:300`) in the same document that records the movement. No code defect: the new
writers use the certified owner pattern (pre-transaction validation, in-transaction binding re-check,
single commit, rollback on any error), and no new authority/intent/event is introduced.

**F3 — MODERATE (test strength). The merge removes the only test of
`target_regime`-uniqueness in program identity.** The step-4 hunk deletes `r3`
(`target_regime="regime-B"`) and the assertion `r2.program.content_hash != r3.program.content_hash`
from `tests/test_research_program.py::test_parallel_regime_changed_target_regime_changes_identity`,
replacing that evidence with registered-tag-vs-`None`. With a single-entry registry, two *distinct*
registered `target_regime` values are not constructible (verified: registry is exactly
`{'ICSS-v1:low-vol'}`), so the "distinct regime ⇒ distinct identity" property is now **untestable**,
even though the raw value still enters the hash (`programs.py:1154`, `:1543`). Relatedly, two refusal
tests were loosened to expect **two** error codes (`PARTIAL_PARALLEL_REGIME_TEST_FIELDS` **and**
`UNVERSIONED_REGIME`; `UNRESOLVABLE_PARENT_PROGRAM` **and** `UNVERSIONED_REGIME`) because the fixture
value `"regime-A"` was left in place — those tests can no longer pass unless the regime is *also*
invalid, entangling the properties they were written to isolate.

**F4 — LOW (gate scope). The twin suite is green but out of band.** `experiments/texp-001` holds 97
passing tests (run here: `97 passed in 1.18s`) and holds the only pin of the twin's duplicate B4
agreement constants, yet `pyproject.toml` restricts `testpaths = ["tests"]` and MERGE-LOG's gate table
omits it — although GR3's own P2 acceptance criterion required "twin suite 97 passed". A future
regression in the twin or in its copy of the agreement constants would be invisible to the canonical
gate.

**F5 — LOW (doc accuracy).** (i) MERGE-LOG describes the step-4 line as "modifies `ROADMAP.md`"; on the
merged tree `ROADMAP.md` is an *addition* (`main@c0b5777` has no root `ROADMAP.md`; `step-4/closeout`
adds blob `74b8768`, the same blob as the merge tip), and the step-4 line's own stat is
`14 files, 1496 insertions(+), 56 deletions(-)` — its "no modifications of existing files" phrasing
applies to the GR3 line only, which is stated correctly. (ii) The merge's file count is 71, not the
"~70 files" of the task header; the 71st is the config commit. (iii) `IDR-036` (line 64) and `IDR-037`
(lines 142, 208) still declare the regime axis "does not exist yet / DEFERRED — fail closed"; nothing in
the merge annotates them as superseded by IDR-044's activation, so a mainline reader citing the corpus'
own IDR-036 is reading a stale prescription.

## 8. Mainline-readiness (S6 / DG-5 / single-mutation-path)

- **Single mutation path — HOLDS.** No new intent kind (`core/intents.py` untouched by both lines), no
  new event type, no new authority, no orchestration-side repository writes. Gateways/routers unchanged;
  GR3's writes ride the certified repository pattern and reach admission only through existing
  `INSERT_TASK`/`ADMIT_TASK` payloads; step-4's three wiring points are the existing certified mutation
  owners (IDR-044 A6/A7). Nothing in the 71 files creates a second mutation path.
- **S6 invariants — HOLD in code.** Determinism owns control (the new research modules are pure: no
  clock, no I/O, no model, no network); append-only journal and content-hash identity untouched;
  project isolation preserved (the new regime resolver ignores `project_id` because the registry is
  *global by design*, which IDR-044 discloses explicitly — recorded here as a disclosed design choice,
  not a defect); refusal-as-data preserved (all new refusals carry codes).
- **DG-5 — CONDITIONALLY HOLDS.** The *code* obeys the layering rules (GR3's persistence modules import
  no research module; the only new upward imports are step-4's two `regimes` imports, authorized by
  IDR-044). The *record* does not: F1 and F2 leave the certified census texts describing a tree that no
  longer exists. That is the sole reason this audit is not a plain PASS.

## 9. Verdict and conditions

**PASS WITH CONDITIONS.** The merge is mechanically faithful (bit-exact replay of both merge commits),
semantically disjoint (no cross-line interference in either direction; all shared inputs — governed
bytes, eol pins, packaged fixture digests — provably unchanged), free of fixture/test collisions, and
green on every gate plus the twin suite. The pyright exclusion is honest, narrow, and measured. The
conditions below are record-integrity and coverage debts, not code defects:

1. **C1 (F1 + F2).** Reconcile the certified census records before mainline: update `AGENTS.md:23`/`:76`
   and `docs/ARCHITECTURE.md` §3.10 for persistence owners 16 → 18 and import statements 13 → 15, and
   classify `hermes.research.regimes` in the intentional-dependency record (or record the owed DG-6
   re-run explicitly). If the reviewer holds that IDR-044 alone does not constitute the §3.10 design
   gate for a *new* upward dependency, this condition escalates: F1 becomes a FAIL-class finding, as no
   document in the merge claims otherwise.
2. **C2 (F3).** Restore identity-uniqueness coverage for `target_regime` (e.g. a synthetic
   two-entry registry fixture) or record explicitly that the property is untestable under a single-entry
   registry; and de-entangle the two refusal tests from the `"regime-A"` fixture value.
3. **C3 (F4).** Add the twin suite to the merge gate set (or record it as an out-of-band gate in
   MERGE-LOG with its command and result).
4. **C4 (F5).** Fix MERGE-LOG's `ROADMAP.md` wording, and annotate `IDR-036`/`IDR-037` D5 (or IDR-044)
   so the superseded DEFERRED stances are not cited as live.

Nothing found in the audited tree warrants a FAIL: no gate is red, no interference, no collision, no
mutation-path violation, no dishonest exclusion.
