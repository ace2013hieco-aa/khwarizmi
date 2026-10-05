# HERMES S-4 — S5 Cone Closure Extraction — Certification

**Date:** 2026-09-21
**Report path:** `docs/archive/HERMES_S4_S5_CONE_CLOSURE_EXTRACTION_CERTIFICATION_2026-09-21.md`
**Authorizing gate:** `docs/archive/HERMES_DG3C_TRANSACTION_PRESERVING_VALIDATOR_REDUCTION_GATE_2026-09-21.md`
(commit `03ff3e4`, verdict `DG-3C — DESIGN GATE PASSED / REDUCTION AUTHORIZED`, single target C-1)

---

## 1. Baseline identity

| Item | Value |
|---|---|
| Repository | `https://github.com/ace2013hieco-aa/khwarizmi-research.git` |
| Branch | `main` |
| Authorized baseline (DG-3C gate) | `03ff3e498c9cfdf78d7a7e937bbfea2b600301ab` |
| Verified `HEAD` at start | `03ff3e498c9cfdf78d7a7e937bbfea2b600301ab` |
| Verified `origin/main` at start | `03ff3e498c9cfdf78d7a7e937bbfea2b600301ab` |
| Implementation commit | `f54af568cba830896d2713b6f0e6e21fba75d42a` |
| Implementation parent | `03ff3e498c9cfdf78d7a7e937bbfea2b600301ab` (verified `git rev-parse HEAD^`) |
| Certification commit | the commit containing this file (a commit cannot embed its own hash) |
| Ancestry | `dffe907` (S-3 cert) and `03ff3e4` (DG-3C) both verified ancestors |
| Working tree at start | clean — only the five known untracked items (`IDEA.md`, `Prompts/`, `orci.json`, `orhead.json`, `ortree.json`), none touched |
| `core.autocrlf` | `true` (the repository stores LF; a CRLF working tree is clean — used for the EOL note in §4) |

Pre-existing untracked material was never modified, staged, deleted, renamed, or
reinterpreted.

---

## 2. DG-3C authorization verification

DG-3C §24 authorized exactly one target:

> * **Function:** `_validate_retract_source` (`src/hermes/research/gateway.py:1000-1445`)
> * **Region:** `src/hermes/research/gateway.py:1225-1235` — the S5 downstream transitive
>   closure (`cone` init, `seen`, `stack`, BFS `while`, `cone.sort()`)
> * **Destination:** one module-level private helper **inside `gateway.py`**
>   (`_s5_cone_closure(source_artifact_id: str, downstream: dict[str, list[str]]) -> list[str]`);
>   **no new file**, no new import, no `__all__` change, no package export
> * **Allowed caller change:** exactly one line …
> * **Allowed test changes:** the three additive pins … **no existing test may be modified,
>   weakened, renamed, or reinterpreted**

Verified against the delivered change:

| Authorization | Delivered | Evidence |
|---|---|---|
| Region `1225-1235` only | yes | diff is exactly `+32 / −11` (§4) |
| Module-level private helper in `gateway.py` | yes | `gateway.py:1000-1028` (§4) |
| No new file | yes | `git show --stat` lists 2 files, both pre-existing |
| No new import | yes | AST: helper has no `Import`/`ImportFrom`; module import block untouched |
| `__all__` unchanged | yes | still `["GatewayRejection", "IntentResult", "apply_intent"]` |
| One call site | yes | `gateway.py:1256`; `_s5_cone_closure` occurs exactly twice in the module (def + call) |
| No existing test modified | yes | test diff is `+129 / −0` (append-only) |
| Only the three pins added | yes | `tests/test_s5_retraction.py:620-745` |
| No second reduction | yes | nothing else in the diff |

**Discrepancy disclosed.** The task brief's §3 illustrated the block as
`cone = [] / seen = {source_artifact_id} / stack = [source_artifact_id] / …`. The **actual
source** at `1225-1235` (and the DG-3C §19 record, which is controlling) uses
`cone: list[str] = []` and `stack = sorted(downstream.get(source_artifact_id, ()))`. The
implementation moved the **real existing statements verbatim** and did **not** rewrite the
algorithm to match the brief's illustrative pseudocode. No semantic difference exists in
output between the two seeds-forms (a seed pushed onto `stack` is skipped by the `seen`
guard and immediately extends with the same sorted children), but the verbatim-move rule
required fidelity to the shipped code, so the shipped code is what moved.

---

## 3. Pre-move characterization result

Run **before** any production edit, on the untouched baseline `03ff3e4`:

```text
.venv/Scripts/python.exe -m pytest tests/test_s5_retraction.py tests/test_s5_l2_resolution.py \
  tests/test_s6_event_capacity.py tests/test_s6a_retraction_ingestion.py \
  tests/test_n9_retraction_admission.py tests/test_step7_curated_registry.py \
  tests/test_chg1_contradictions.py tests/test_gateway.py -q
→ 336 passed, exit 0
```

Coverage of the DG-3C §20 property list (all green pre-move, all still green post-move):

| Property | Test |
|---|---|
| direct children | `test_direct_dependent_invalidated` |
| multi-level chain | `test_multi_level_chain`, `test_17_task_input_cone` |
| branching | `test_branching_graph_multiple_branches` |
| diamond de-duplication | `test_shared_dependency_no_duplicate_invalidation`, `test_22_duplicate_aliases_single_invalidation`, `test_a10_duplicate_aliases` |
| duplicate aliases | same three |
| empty cone | `test_empty_cone`, `test_20_empty_cone_digest`, `test_25_empty_cone_reconstruction` |
| cycle termination | `test_23_cycle_terminates`, `test_a11_cycle_terminates` |
| seed exclusion | `test_a11_cycle_terminates` (seed reachable back through a cycle) |
| unreachable nodes | `test_unrelated_nodes_untouched`, `test_20_sibling_production_excluded` |
| non-dependency edges | `test_non_dependency_edge_never_propagates` |
| cross-project isolation | `test_21_cross_project_isolation`, `test_a7_cross_project_collision`, `test_cross_project_source_rejected` |
| determinism / replay | `test_14_repeated_resolution_deterministic`, `test_29_replay_deterministic`, `test_a5_replay_identical`, `test_a4_historical_graph` |
| large cones | `test_a12_large_cone`, `test_44_large_cone_no_rejection`, `test_46_10x_baseline_cone` |
| cone digest reproduction | `test_21_artifact_markers_reproduce_cone`, `test_22_task_records_reproduce_cone`, `test_23_curated_records_reproduce_cone`, `test_24_recalculated_digest_matches`, `test_18_duplicate_aliases_stable_digest` |
| mid-cascade rollback | `test_mid_cascade_failure_writes_nothing` |
| persistence-failure rollback | `test_27_persistence_failure_rolls_back` |
| event ordering | `test_event_ordering_and_causality`, `test_payload_carries_cascade_record` |
| authority fail-closed | `test_missing_human_decision_fail_closed`, `test_missing_decision_beats_source_resolution`, `test_retract_source_is_internal_only`, `test_agent_roles_rejected` |
| duplicate retraction semantics | `test_identical_repeat_is_duplicate_with_zero_effects`, `test_repeat_preserves_single_source_retracted_event`, `test_second_different_retraction_is_stale` |

No test was modified before the move, and none was modified after (append-only, §14).

---

## 4. Exact implementation diff

`git show --numstat f54af56`:

| File | +/− | Purpose |
|---|---|---|
| `src/hermes/research/gateway.py` | `+32 / −11` | the new module-level helper (`1000-1028`) and the one-line call-site substitution (`1256`) |
| `tests/test_s5_retraction.py` | `+129 / −0` | the three additive S-4 pins (`620-745`); **zero** existing lines removed or changed |

Gateway structural facts before → after:

| Fact | Baseline `03ff3e4` | `f54af56` | Delta |
|---|---|---|---|
| file length (line terminators) | 3713 | 3734 | +21 |
| module-level functions | 32 | 33 | +1 (`_s5_cone_closure`) |
| `_validate_retract_source` span | `1000-1445` (446 lines) | `1031-1466` (436 lines) | −10 |
| closure block | `1225-1235` (5 statements + `cone.sort()`) | replaced by one call at `1256` | −10 |
| `BEGIN IMMEDIATE` owners | `520, 1120, 2033, 2391, 2624` | `520, 1151, 2054, 2412, 2645` | same five functions, shift-explained (+31 above the insertion, −10 below) |

Added symbols (verbatim excerpt, CRLF in the file):

```python
def _s5_cone_closure(
    source_artifact_id: str,
    downstream: dict[str, list[str]],
) -> list[str]:
    """The deterministic downstream closure for one S5 source artifact.
    ... (contract docstring; 13 lines, 1004-1016)
    """
    cone: list[str] = []
    seen = {source_artifact_id}
    stack = sorted(downstream.get(source_artifact_id, ()))
    while stack:
        artifact_id = stack.pop(0)
        if artifact_id in seen:
            continue
        seen.add(artifact_id)
        cone.append(artifact_id)
        stack.extend(sorted(downstream.get(artifact_id, ())))
    cone.sort()
    return cone
```

Call site (`gateway.py:1256`), exactly as authorized:

```python
        cone = _s5_cone_closure(source_artifact_id, downstream)
```

Structural placement: the helper sits between `_s5_source_artifact_id` (ends `1002`) and
`_validate_retract_source` (now `1031`), i.e. inside the S5 section, immediately above its
single caller.

**EOL note (disclosed).** The edit tool rewrote `tests/test_s5_retraction.py` with LF line
endings; the working copy was normalized back to CRLF (746 CRLF, 0 bare LF) for consistency
with its siblings, in a following step. Because `core.autocrlf=true`, the repository blob is
LF either way and the diff is provably unaffected (`+129 / −0` both before and after the
normalization, `git status` clean apart from the two intended files). `gateway.py` remained
CRLF throughout (`3734` CRLF, 0 bare LF).

---

## 5. AST equivalence proof

Method: `ast.dump(..., include_attributes=False)` (source locations ignored) of the five
statements **as they were inside `_validate_retract_source`'s transaction `Try`** at
`03ff3e4:1225-1235`, compared with the first five statements of the new helper's body.

| # | Baseline statement | Baseline sha256(dump)[:16] | Delivered helper | Equal |
|---|---|---|---|---|
| 0 | `cone: list[str] = []` (AnnAssign) | `0f029e40c2a56484` | `0f029e40c2a56484` | ✅ |
| 1 | `seen = {source_artifact_id}` | `3ee0c75977907510` | `3ee0c75977907510` | ✅ |
| 2 | `stack = sorted(downstream.get(source_artifact_id, ()))` | `3b0a2802cd3509fc` | `3b0a2802cd3509fc` | ✅ |
| 3 | `while stack: …` (BFS body) | `ce10a5b00dad03d4` | `ce10a5b00dad03d4` | ✅ |
| 4 | `cone.sort()` | `6362d8eb5fbc2863` | `6362d8eb5fbc2863` | ✅ |

The helper body is exactly those five statements **plus** the sixth statement `return cone`
(`isinstance(helper.body[-1], ast.Return)` with `value.id == "cone"` → `True`). That is the
complete set of differences permitted by DG-3C §12: same statements, same order, enclosed in
a function, plus the return.

Explicitly preserved: `stack.pop(0)` (no deque/recursion/optimization), `stack = sorted(...)`
(no unsorted construct), `stack.extend(sorted(...))` (order-preserving extend), `cone.sort()`
final canonicalization, the `seen = {source_artifact_id}` seed guard (seed exclusion), and the
`continue`-based de-duplication.

Signature as delivered: `(source_artifact_id: str, downstream: dict[str, list[str]]) ->
list[str]` — parameter names and order exactly as authorized, no defaults, no extra
parameters.

---

## 6. Purity proof

AST-precise containment over the helper (`ast.walk` over the parsed function, not a raw
substring scan, so the contract docstring is never mistaken for code):

| Check | Result |
|---|---|
| Identifier names appearing in the helper | `['artifact_id', 'cone', 'dict', 'downstream', 'list', 'seen', 'sorted', 'source_artifact_id', 'stack', 'str']` |
| Attribute / call names | `['add', 'append', 'extend', 'get', 'pop', 'sort', 'sorted']` |
| Imports inside the helper | none |
| Banned identifiers present (`conn`, `execute`, `_reject`, `clock`, `hashlib`, `EventType`, `_append_event_to_db`, `append_event`, `GatewayRejection`, `sha256`, `uuid`, `random`, `time`, `datetime`, repository classes, `source_artifact_retracted`, `_cx_classification_facts`, `_l2_resolve_upstream`) | **NONE** |
| Banned attribute names present | **NONE** |
| String literals in the helper | exactly one — its own docstring (`literals == {ast.get_docstring(fn, clean=False)}`) |
| SQL / transaction tokens as code (`tokenize`, strings and comments excluded) | **NONE** |
| Input mutation | none: the only `downstream` access is `.get(...)`; no `setdefault`, no item assignment, no `pop`/`clear` on it |
| Determinism | output is `cone.sort()`-ed; traversal order affects only `seen` bookkeeping, so the result is a function of `(seed, adjacency)` alone |
| Output contract | sorted, de-duplicated, **seed excluded**, dangling nodes emitted as leaves (never `KeyError`) |

The helper therefore cannot reach a connection, a cursor, a transaction, a refusal, a clock,
a hash, an event, an identity helper, a repository, or provider state. This is the
"structurally incapable" property DG-3C §19 selected it for.

---

## 7. Transaction ownership proof

Order-sensitive scan of `_validate_retract_source` before (`03ff3e4`) and after (`f54af56`):

| | Transaction control sequence | Journal event sequence |
|---|---|---|
| before | `BEGIN, COMMIT, ROLLBACK, ROLLBACK, ROLLBACK, ROLLBACK` | `SOURCE_RETRACTED, TASK_INVALIDATED, CURATED_KNOWLEDGE_INVALIDATED, CONTRADICTION_SUPERSEDED` |
| after | `BEGIN, COMMIT, ROLLBACK, ROLLBACK, ROLLBACK, ROLLBACK` | identical |
| verdict | **IDENTICAL** | **IDENTICAL** |

Post-move line numbers (all still inside the validator, all owned by it):

```text
BEGIN IMMEDIATE   1151
ROLLBACK          1160   (duplicate path)
ROLLBACK          1190   (STALE path)
COMMIT            1445
ROLLBACK          1448   (except GatewayRejection — guarded by conn.in_transaction)
ROLLBACK          1452   (except Exception — guarded by conn.in_transaction)
```

The five gateway `BEGIN IMMEDIATE` owners remain: `_decision_append_transactional:520`,
`_validate_retract_source:1151`, `_validate_curate_knowledge:2054`,
`_validate_record_contradiction:2412`, `_validate_contradiction_resolution:2645`. The helper
receives no connection and opens none. The guarded rollback idiom is byte-identical.

---

## 8. Journal ordering proof

Event append sites inside `_validate_retract_source`, before → after (the shift is exactly
`+31` above the insertion and `−10` below it, consistent with §4):

| Event | Baseline | Delivered |
|---|---|---|
| `TaskInvalidated` | `1280` | `1301` |
| `CuratedKnowledgeInvalidated` | `1331` | `1352` |
| `ContradictionSuperseded` | `1371` | `1392` |
| `SourceRetracted` | `1406` | `1427` |

The order-sensitive event-name sequence comparison returns **IDENTICAL** (§7). The cascade
sequence is unchanged:

```text
artifact invalidation → task invalidation → curated follow-on
→ contradiction supersession → S6 digest + SourceRetracted → COMMIT
```

The helper contains no `EventType`, no `_append_event_to_db`, and no call that can append,
reject, or log; it cannot reorder anything because it has no effects at all.

---

## 9. Identity proof

Order-sensitive store-site scan of `_validate_retract_source`:

| | Identity authorship inside the validator |
|---|---|
| before | `['retraction_id', 'decision_artifact_id', 'decision_hash']` |
| after | `['retraction_id', 'decision_artifact_id', 'decision_hash']` |
| verdict | **IDENTICAL** |

`retraction_id` (canonical-command sha256), `decision_artifact_id` (`rd-…`),
`decision_hash` and the S6 `cone_digest` all remain in the validator, at the same points in
the same transaction. The helper authors no identity, computes no hash, and canonicalizes
nothing (`sha256` and `hashlib` are absent from its AST).

---

## 10. N9 proof

* `tests/test_n9_retraction_admission.py` — **21 passed** in isolation, post-move (was 21
  pre-move; no change).
* The N9 surfaces were not touched: the diff contains no change to
  `_cx_classification_facts` (`2246-2297` pre-move numbering), `_cx_resolve_evidence_ref`,
  `source_artifact_retracted`, the retraction predicate, or the in-transaction re-resolution
  inside `_validate_record_contradiction`.
* `git diff --name-only` = two files, neither of which is an N9 module (§14).
* Post-retraction admission behavior, same-project filtering, retraction outcome and
  classification admission are all exercised by the unchanged N9 suite, which is green.

---

## 11. Controller / persistence isolation proof

```text
git diff --name-only   →  src/hermes/research/gateway.py
                          tests/test_s5_retraction.py
```

No `controller.py`, no `persistence/*`, no `migrations/*`, no `schemas/*`, no `core/*`, no
`docs/*`, no configuration, no dependency file. The production diff contains exactly one
file: `src/hermes/research/gateway.py`.

---

## 12. New characterization tests

Appended (append-only, `+129 / −0`) to `tests/test_s5_retraction.py` as
`class TestS4ConeClosurePins` (`620-745`). Local imports are used inside each pin, matching
the file's existing precedent (`test_s5_cone_untouched_by_feature_binding`), so the module
import block is untouched.

| Pin | Line | Proves |
|---|---|---|
| `test_c_dg3c_1_pure_closure_semantics` | `623` | empty adjacency → `[]`; direct child; multi-level chain; diamond de-dup (`["l", "leaf", "r"]`); cycle terminates with the **seed excluded**; a dangling reference is emitted as a leaf (never `KeyError`); an unreachable component never appears; sorted output regardless of adjacency order; 5× repeat determinism |
| `test_c_dg3c_2_structural_purity` | `661` | signature is exactly `(source_artifact_id, downstream)` with no `conn`-like parameter; the adjacency input is **not mutated**; repeated invocation is equal; **AST-precise** containment — no `import`, and no banned identifier/attribute anywhere in the function (docstring-safe by construction); the only string literal is the function's own docstring |
| `test_c_dg3c_3_call_site_equivalence` | `701` | end-to-end: rebuild the in-transaction adjacency exactly as the cascade does (project-scoped `provenance_edges` JOIN `artifacts`, all three `_S5_DEPENDENCY_EDGE_TYPES`, shared `_l2_memo`), compute `_s5_cone_closure("src-a", downstream)`, run the real retraction, and assert `result.row["invalidated_artifacts"] == expected == ["d-task", "d-typed", "d1", "d2", "d3"]` — covering a bare edge, a typed `source_result:<hash>` edge, a task hop, a branch, and a diamond duplicate path |

`tests/test_s5_retraction.py` went from 34 to **37** collected tests; the whole slice from
336 to **339**; the repository total from **2054** to **2057**. All three pins pass, and all
three fail-closed properties they assert were already true of the pre-move code path (they
pin the extracted unit, not new behavior).

---

## 13. Full validation

All runs on the frozen implementation commit `f54af56` (`HEAD == origin/main`), working tree
clean.

| Gate | Command | Result |
|---|---|---|
| Cascade/closure slice | the eight files of §3 | **339 passed**, exit 0 (pre-move: 336) |
| S5 retraction alone | `tests/test_s5_retraction.py` | **37 passed** (34 + 3 pins) |
| N9 alone | `tests/test_n9_retraction_admission.py` | **21 passed** |
| Full suite | `.venv/Scripts/python.exe scripts/run_tests.py -q` | 100% progress, **0 FAILED/ERROR markers, exit code 0** |
| Collected count | `python -m pytest --collect-only -q` | **2057** = 2054 baseline + 3 pins (exactly as expected) |
| Ruff | `uvx ruff check src tests` | `All checks passed!` |
| Pyright (source profile, strict) | `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| Project validation profile | `./scripts/profiled_gate.sh` | `profiled typecheck + walking-skeleton smoke: OK` (exit 0); tests profile `0 errors, 1 warning` |
| Whitespace | `git diff --check` | clean |
| Working tree | `git status --porcelain=v1` | only the five known untracked items; 0 tracked modifications |

The single tests-profile warning is the pre-existing
`tests/test_research_program.py:141` `reportSelfClsParameterName` warning, present on the
certified baseline (documented in the S-2, DG-3B, S-3 and DG-3C records) in an untouched
file. It is not attributable to this work. Zero skipped tests were introduced. No tooling
configuration was modified, and no production code was changed to make anything green.

### 13b. Invariant checklist (§21)

| Invariant | Result |
|---|---|
| Determinism | **UNCHANGED** — pure function, sorted output, repeat-equal (pin 1) |
| Transaction ownership | **UNCHANGED** — §7, order-identical control sequence |
| Single mutation path | **UNCHANGED** — writes remain in the validators; helper has none |
| Journal ordering | **UNCHANGED** — §8, order-identical event sequence |
| Curation invariant | **UNCHANGED** — curated follow-on untouched; step-7 slice green (68) |
| Human authority | **UNCHANGED** — no authority code moved; fail-closed pins green |
| 4 KiB bounded payload | **UNCHANGED** — S6 cap handling and digest untouched |
| Project isolation | **UNCHANGED** — helper receives an already project-filtered adjacency; §10 of DG-3C |
| Prohibited-claims discipline | **UNCHANGED** — no claim/refusal surface touched |
| Archive-not-delete | **UNCHANGED** — invalidation markers still written by the validator |
| Head-only supersession | **UNCHANGED** — supersession ladders untouched |
| Refusal-as-data | **UNCHANGED** — 93 refusal sites untouched; helper raises nothing |
| Lease/fence | **UNCHANGED** — no fence/lease code in scope or in the diff |
| Content-hash identity | **UNCHANGED** — §9 |
| N9 retraction safety | **UNCHANGED** — §10 |
| S-2 HumanDecision seam | **UNTOUCHED** — no file change; `record_human_decision_once` unchanged |
| S-3 L2 seam | **UNTOUCHED** — `l2_resolution.py` unchanged; L2 slice green (59) |

No invariant reports a non-UNCHANGED result.

---

## 14. Diff-scope verification

```text
git diff --stat                → src/hermes/research/gateway.py | 43 ++++++----
                                 tests/test_s5_retraction.py   | 129 +++++++++++
                                 2 files changed, 161 insertions(+), 11 deletions(-)
git diff --numstat             → 32  11  src/hermes/research/gateway.py
                                 129 0   tests/test_s5_retraction.py
git diff --name-only           → the same two files, nothing else
git status --short             → M the same two files; the five known untracked items
```

* The test file diff removes **zero** lines (`129 0`): the change is strictly append-only, so
  no existing assertion was deleted, weakened, renamed, or reinterpreted.
* The production diff removes 11 lines and adds 32: 11 removed = the five moved statements
  plus their blank separator; 32 added = the helper (31 lines including docstring and two
  trailing blank lines) plus the single call line.
* The DG-3C report, the S-3 report, the S-2 report, and every other archived document were
  **not** modified.
* The five known untracked items remain untracked and byte-unchanged.

---

## 15. 30-question adversarial review

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Were the five closure statements copied exactly? | **PASS** | §5 — identical `ast.dump` hashes for all five |
| 2 | Did `.pop(0)` remain unchanged? | **PASS** | §5 statement 3 dump identical (`stack.pop(0)`) |
| 3 | Did sorting remain unchanged? | **PASS** | `sorted(...)` on both seed and extend, plus final `cone.sort()` — dumps 2/3/4 identical |
| 4 | Did seed exclusion remain unchanged? | **PASS** | `seen = {source_artifact_id}` dump identical; pin 1 asserts seed-exclusion on a cycle back to the seed |
| 5 | Did cycle behavior remain unchanged? | **PASS** | pin 1 (cycle case) + `test_23_cycle_terminates`, `test_a11_cycle_terminates` |
| 6 | Did duplicate suppression remain unchanged? | **PASS** | pin 1 diamond case + `test_shared_dependency_no_duplicate_invalidation` |
| 7 | Did missing adjacency behavior remain unchanged? | **PASS** | `.get(node, ())` preserved; pin 1 dangling-reference case returns the leaf instead of raising |
| 8 | Did the helper mutate `downstream`? | **PASS — no** | §6; pin 2 snapshots the dict before/after |
| 9 | Does the helper receive a connection? | **PASS — no** | signature `(source_artifact_id, downstream)`; pin 2 asserts it |
| 10 | Does it perform I/O? | **PASS — no** | §6 AST containment: no `conn`/`execute`/import/repository; pin 2 enforces it |
| 11 | Can it raise Gateway refusal? | **PASS — no** | `_reject`/`GatewayRejection` absent from its AST; it raises only built-in errors, which the caller's `except Exception → ROLLBACK` path already covers exactly as before |
| 12 | Can it alter transaction state? | **PASS — no** | no `BEGIN`/`COMMIT`/`ROLLBACK`/`conn`; §7 sequence identical |
| 13 | Can it alter journal state? | **PASS — no** | no `EventType`/`_append_event_to_db`; §8 sequence identical |
| 14 | Can it author identity? | **PASS — no** | no `sha256`/`hashlib`/`uuid`; §9 authorship set identical |
| 15 | Can it access the clock? | **PASS — no** | `clock` absent from parameters and AST |
| 16 | Can it access provider state? | **PASS — no** | no tools/provider import or call anywhere in the helper |
| 17 | Did `BEGIN IMMEDIATE` ownership change? | **PASS — no** | §7 — still `_validate_retract_source`, at `1151` |
| 18 | Did rollback ownership change? | **PASS — no** | §7 — four rollbacks, same order, same guarded idiom |
| 19 | Did commit ownership change? | **PASS — no** | §7 — `COMMIT` at `1445`, still in the validator |
| 20 | Did event ordering change? | **PASS — no** | §8 — order-sensitive event sequence identical |
| 21 | Did N9 re-resolution move? | **PASS — no** | §10 — N9 suite 21/21; no N9 symbol in the diff |
| 22 | Did project isolation change? | **PASS — no** | helper consumes the caller's already project-scoped adjacency; the emission JOIN is untouched |
| 23 | Did any Controller file change? | **PASS — no** | §14 — `git diff --name-only` |
| 24 | Did any persistence file change? | **PASS — no** | §14 |
| 25 | Did any public API change? | **PASS — no** | module-private helper; `apply_intent`/`GatewayRejection`/`IntentResult` untouched |
| 26 | Did `__all__` change? | **PASS — no** | still `['GatewayRejection', 'IntentResult', 'apply_intent']` |
| 27 | Did any new module appear? | **PASS — no** | 33 module-level functions in the same file; no new file |
| 28 | Did the full cascade slice remain green? | **PASS** | §13 — 339 passed (336 + 3) |
| 29 | Did the full suite remain green? | **PASS** | §13 — exit 0, 0 failures/errors, 2057 collected |
| 30 | Did the implementation exceed DG-3C's exact authorization? | **PASS — no** | §2 table; the one disclosed deviation is that the *brief's* illustrative pseudocode differed from the shipped statements, and the shipped statements were moved verbatim (never rewritten) |

All thirty resolve to **PASS**. No blocker, no unresolved item.

---

## 16. Final certification verdict

```text
S-4 — CERTIFIED / S5 CONE CLOSURE EXTRACTION SUCCESSFUL
```

The S5 downstream cone algorithm is now an explicitly pure, module-private unit
(`_s5_cone_closure`, `gateway.py:1000-1028`) that receives no connection and contains no SQL,
transaction control, refusal, clock, hash, event, identity helper, repository call, or import.
Its five moved statements are AST-identical to the certified baseline; the only additions are
the enclosing `def` and `return cone`.

The transaction owner, authority boundary, refusal semantics, identity authorship, journal
ordering, rollback behavior, project isolation, and N9 protection remain exactly where they
were — demonstrated by order-sensitive before/after scans (§7-§9), the unchanged emission
JOIN, and green post-move runs of the N9 suite, the cascade slice (339), the full suite
(exit 0, 2057 collected), Ruff, Pyright (src strict `0 errors, 0 warnings`),
`scripts/profiled_gate.sh`, and `git diff --check`.

Implementation (`f54af56`, parent `03ff3e4`) and certification are separate commits; the
implementation commit contains exactly the two authorized files; the certification commit
contains only this report.
