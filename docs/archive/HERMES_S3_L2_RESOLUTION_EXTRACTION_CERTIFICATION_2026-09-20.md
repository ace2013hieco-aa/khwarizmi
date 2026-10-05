# HERMES S-3 — Gateway L2 Upstream-Reference Extraction — Certification

**Date:** 2026-09-20
**Report path:** `docs/archive/HERMES_S3_L2_RESOLUTION_EXTRACTION_CERTIFICATION_2026-09-20.md`
**Authorizing gate:** `docs/archive/HERMES_DG3B_GATEWAY_STRUCTURAL_DESIGN_GATE_2026-09-20.md`
(commit `65e82c0`, verdict `DG-3B — GATEWAY DESIGN GATE PASSED / IMPLEMENTATION AUTHORIZED`)

---

## §0 Executive verdict

```text
S-3 — CERTIFIED / GATEWAY L2 EXTRACTION SUCCESSFUL
```

One seam. One implementation commit (`df57650`). One certification commit (this
document). The L2 upstream-reference resolution family that `gateway.py`
defined inline at `950-1103` now lives in the internal module
`src/hermes/research/l2_resolution.py`; the gateway keeps a single import and
its one call site is textually unchanged. No behavior moved with it: no
transaction, no write, no refusal, no authority check, no identity generation,
no journal effect, no project-filter change.

---

## §1 Baseline

| Item | Value |
|---|---|
| Repository | `https://github.com/ace2013hieco-aa/khwarizmi-research.git` |
| Branch | `main` |
| Certified baseline (S-2) | `6e1458c042b907dfa511e557d2cb269ab98060b9` |
| DG-3B gate commit (parent of the implementation) | `65e82c00f242c25fe2e9c49d646982fb41ea9771` |
| Implementation commit | `df5765082eb3b782177a0e2acc41af45193b85d8` |
| Implementation parent | `65e82c00f242c25fe2e9c49d646982fb41ea9771` (verified: `git rev-parse HEAD^` before push) |
| `origin/main` at certification | `df5765082eb3b782177a0e2acc41af45193b85d8` |
| Working tree | clean — no tracked modification; only the five known untracked items (`IDEA.md`, `Prompts/`, `orci.json`, `orhead.json`, `ortree.json`) |
| S-2 ancestry | verified (`git merge-base --is-ancestor 6e1458c HEAD` → yes) |
| Certification commit | the commit that contains this file (a commit cannot embed its own hash) |

Gates run at `HEAD == origin/main == df57650`: full suite, Ruff, Pyright (src),
`profiled_gate.sh`, `git diff --check`, and the six-slice matrix.

---

## §2 Authorized scope

DG-3B §18 authorized **exactly one** seam, quoted verbatim:

> **Identity.** The L2 upstream-reference resolution family, `gateway.py:950-1103`:
> comment preamble `950-974`, `_L2_HASH_TYPED_PREFIXES:975-982`,
> `_l2_lookup_artifact_by_hash:985-997`, `_l2_resolve_ref_to_artifacts:1000-1027`,
> `_l2_task_spec_refs:1030-1054`, `_l2_task_outputs:1057-1063`,
> `_l2_resolve_upstream:1066-1103`.
>
> **Proposed location.** `src/hermes/research/l2_resolution.py` — INTERNAL, no
> `__all__`, docstring naming the ratified gate and stating explicitly that it
> opens no transaction, performs no write, raises no refusal, and that project
> isolation is enforced at emission.

Explicitly **not** authorized (DG-3B §18 last paragraph, §22): any second seam,
the §17 YELLOW rows, the C-01a in-file step-helper refactors, the large-validator
splits, refusal-machinery relocation, transaction relocation, persistence-write
relocation, DG-5 inversion work, DG-6 invariant work, DG-4, and gateway
modernization. **None was performed.**

DG-3B §24 prerequisites 1-10 were all honored: characterization pins first
(§12), byte-identical contract (§4), no import re-export stabilization, no
behavior "fixes", transaction ownership frozen (§6), no scope extension (§3),
one commit, re-run-and-certify (§11), stop conditions evaluated (§13), no second
seam.

---

## §3 Physical diff

`git show --stat df57650` / `git diff --numstat 65e82c0 HEAD`:

| File | +/− | Purpose |
|---|---|---|
| `src/hermes/research/gateway.py` | `+1 / −156` | the single import insertion (line 73) and the contiguous removal of the L2 preamble comment + constant + five functions (baseline `950-1105`, i.e. the family plus its two trailing boundary blank lines) |
| `src/hermes/research/l2_resolution.py` | `+184 / −0` | **new** internal module: docstring, `from __future__ import annotations`, `from typing import Any`, the moved preamble comment, `_L2_HASH_TYPED_PREFIXES`, and the five functions verbatim |
| `tests/test_s5_l2_resolution.py` | `+134 / −2` | the one authorized import retarget, the stale docstring pointer update, and the three additive DG-3B §19 pins |

**Nothing else changed.** No Controller, no persistence, no `core/`, no intent
or event definition, no schema, no migration, no configuration, no dependency,
no S-2 (`verdict_decisions.py` untouched), no N9 logic. `git status --porcelain`
after the commit lists only the three authorized paths as tracked results of the
commit.

### Line-shift proof that the two gateway edits are the *only* gateway edits

A mechanical position audit over both revisions: gateway file length delta
`−155`; **all 35 module-level symbols before the removed block shifted by exactly
`+1`** (the inserted import line 73) and **all 28 symbols after it shifted by
exactly `−155`**; **0 shift anomalies**. Combined with the AST node-sequence
comparison of §4, this proves the change is one insertion plus one contiguous
156-line deletion — no scattered edits.

---

## §4 Semantic equivalence

The claim is precisely scoped: *semantic/AST-equivalent implementation with only
module-ownership/import-context changes* — not "byte-identical file".

**AST comparison** (`ast.dump(..., include_attributes=False)`, i.e. ignoring line
numbers, of baseline `gateway.py` vs the new module):

| Symbol | AST-identical | Docstring identical |
|---|---|---|
| `_L2_HASH_TYPED_PREFIXES` | ✅ | — |
| `_l2_lookup_artifact_by_hash` | ✅ | ✅ |
| `_l2_resolve_ref_to_artifacts` | ✅ | ✅ |
| `_l2_task_spec_refs` | ✅ | ✅ |
| `_l2_task_outputs` | ✅ | ✅ |
| `_l2_resolve_upstream` | ✅ | ✅ |

**Signatures preserved exactly** (parameter names, order, defaults):

```text
_l2_lookup_artifact_by_hash(conn, content_hash, artifact_type) -> str | None
_l2_resolve_ref_to_artifacts(conn, value) -> set[str]
_l2_task_spec_refs(conn, task_id) -> tuple[list[str], bool]
_l2_task_outputs(conn, task_id) -> set[str]
_l2_resolve_upstream(conn, value, edge_type, _memo=None) -> set[str]
```

**Everything the contract text names is intact:** `_memo=None` and its
per-`(value, edge_type)` traversal-memo semantics; `edge_type` dispatch
(`derived_from` → task inputs, `used_as_input` → task outputs, `cites` → both);
the fixed rule precedence artifact-identity → recognized typed form → task hop →
unresolved; `evidence:` handled as a bare id; the six-entry
`_L2_HASH_TYPED_PREFIXES` frozenset; the three SQL statements byte-identical; the
`ORDER BY created_at LIMIT 1` deterministic-selection idiom; fail-safe
`None`/empty-set returns (never an exception); exact-match-only behavior (no
prefix guessing, no truncation, no fuzzy matching); task-hop single-level
expansion. Every docstring moved with its function.

**Runtime identity:** `gateway._l2_resolve_upstream is
l2_resolution._l2_resolve_upstream` → `True`. The gateway's call site
(`gateway.py:1219-1222`, baseline `1374-1378`) is **textually unchanged** —
`_l2_resolve_upstream(conn, r["upstream_id"], r["edge_type"], _l2_memo)` now
binds to the imported object through the same bare name, so no adapter, wrapper,
shim, re-export, or duplicate exists.

---

## §5 Import graph

`l2_resolution` top-level imports, measured by AST:

```text
from __future__ import annotations      (line 27)
from typing import Any                  (line 29)
```

Plus the function-local `import json as _json` inside `_l2_task_spec_refs`
(line 132) — carried over verbatim from the baseline, not a new dependency.

Proof of direction (fresh interpreter, `import hermes.research.l2_resolution`
only):

```text
hermes.research.gateway loaded by l2 import: False
hermes.persistence      loaded by l2 import: False
```

So the graph is `gateway → l2_resolution → stdlib`, with **no**
`l2_resolution → gateway`, `→ persistence`, `→ controller`, `→ provider`, and no
cycle. Nothing in `persistence/`, `core/`, or `tools/` imports the new module.

---

## §6 Transaction proof

Source-level token scan of `l2_resolution.py` with strings and comments excluded
(`tokenize`): banned tokens `BEGIN`, `COMMIT`, `ROLLBACK`, `INSERT`, `UPDATE`,
`DELETE` → **NONE as code**. The only SQL verbs present in string literals are
`SELECT` (**6** occurrences). The module contains **0 `BEGIN`, 0 `COMMIT`,
0 `ROLLBACK`, 0 writes.**

Runtime proof: DG-3B §19 pin 2 (§12) drives all four rule carriers through a
recording connection proxy and asserts every statement is `SELECT` and that no
transaction-control verb is issued.

The five gateway-owned `BEGIN IMMEDIATE` sites remain in `gateway.py`, owned by
unchanged functions, all shift-explained:

| Owner | Baseline | Post-move | Shift |
|---|---|---|---|
| `_decision_append_transactional` | 519 | 520 | +1 (before the block) |
| `_validate_retract_source` | 1275 | 1120 | −155 |
| `_validate_curate_knowledge` | 2188 | 2033 | −155 |
| `_validate_record_contradiction` | 2546 | 2391 | −155 |
| `_validate_contradiction_resolution` | 2779 | 2624 | −155 |

The extraction neither opens, participates in, observes, nor closes a
transaction: `BEGIN → HumanDecision → gateway → commit` ownership is untouched.

---

## §7 Authority proof

No authority artifact moved. Verified mechanically: `l2_resolution.py` contains
no `GatewayRejection`, no `IntentRejected`, no `HumanDecision` /
`HUMAN_DECISION_RECEIVED`, no role/operator/credential check, and no `_reject`
call (zero occurrences as code tokens). The module raises no refusal — the task's
own contract requires it to never raise on malformed input, and it returns
`None`/empty sets instead.

Caller-side authority is untouched: the gateway still reads
`HumanDecisionReceived` in its own `SELECT`s inside `_validate_retract_source`,
the four credential gates and the dispatch ladder are unchanged, and
`_reject`/`GatewayRejection`/`IntentResult`/`apply_intent` were not edited. The
S-2 seam was **not** duplicated or moved: `record_human_decision_once` remains
the only HumanDecision writer, and the new module writes no event of any kind
(§9).

---

## §8 Identity proof

The module consumes identifiers and authors none. Token scan (code only, strings
and comments excluded) finds **no** `UUID`, `HASHLIB`, `RANDOM`, `TIME`,
`DATETIME` identifier, and the AST shows no import of `uuid`, `hashlib`,
`secrets`, `random`, `time`, or `datetime`. No hashing, no canonicalization, no
content/command/correlation/decision identity is created. The moved code only
reads `artifacts.artifact_id`, `artifacts.content_hash`,
`artifacts.task_id`, and `tasks.spec_json`, and returns sets of already-existing
`artifact_id` values.

---

## §9 Journal/replay proof

The module contains **no** `EventType`, `IntentApplied`, `IntentRejected`, event
construction, journal append, or `_append_event_to_db` reference (zero
occurrences as code tokens). It issues only `SELECT`s, so it cannot mutate state,
change journal ordering, or alter replay determinism. Replay evidence is carried
by the re-run slices (§11): `test_s5_retraction.py::test_event_ordering_and_causality`,
`test_deterministic_correlation_key`, `test_identical_repeat_is_duplicate_with_zero_effects`,
`test_mid_cascade_failure_writes_nothing`, the S6 event-capacity L2-integration
sections, and `test_s5_l2_resolution.py`'s `test_14_repeated_resolution_deterministic`,
`test_29_replay_deterministic`, `test_a5_replay_identical`, `test_a11_cycle_terminates`
— all green before and after.

---

## §10 Project isolation

The ratified contract is preserved exactly as designed, and deliberately **not**
"fixed":

```text
global-by-key resolution  →  caller-side project-scoped emission
```

* The resolver takes no `project_id` and no project filter was added; the
  pre-move and post-move emission query text is byte-identical
  (`gateway.py:1207-1211`, baseline `1362-1366`, shift −155):
  `JOIN artifacts a ON a.artifact_id = e.artifact_id WHERE a.project_id = ?`.
* DG-3B §19 pin 3 asserts directly that a `p2` artifact id resolves by key from
  the resolver (there is no project argument to supply) and that a `p1`
  retraction never emits a `p2` dependent row that references the same key —
  i.e. isolation comes from the caller's emission JOIN, not from the resolver.
* Existing isolation pins remain green: `test_a7_cross_project_collision`,
  `test_21_cross_project_isolation`, `test_20_sibling_production_excluded`,
  `test_s5_retraction.py::test_cross_project_source_rejected`.

---

## §11 Test evidence

All runs at `HEAD == origin/main == df57650`, on the frozen working tree.

| Gate | Command | Result |
|---|---|---|
| L2 slice (post-move) | `python -m pytest tests/test_s5_l2_resolution.py -q` | **59 passed** (56 existing + 3 pins), exit 0 |
| L2 slice (pre-move) | same, before the production edit | **59 passed**, exit 0 |
| S5 retraction | `tests/test_s5_retraction.py` | **34 passed** |
| S6 event capacity | `tests/test_s6_event_capacity.py` | **45 passed** |
| Step-7 curated registry | `tests/test_step7_curated_registry.py` | **68 passed** |
| N9 retraction admission | `tests/test_n9_retraction_admission.py` | **21 passed** |
| Gateway slice | `tests/test_gateway.py` | **35 passed** |
| Six-slice total | the six files together | **262 passed, exit 0 — identical to the pre-move run's 262** |
| Full suite | `.venv/Scripts/python.exe scripts/run_tests.py -q` | 100% progress, **0 FAILED/ERROR markers, exit code 0** |
| Collected count | `python -m pytest --collect-only -q` | **2054 tests** (2051 certified baseline + 3 additive pins), identical before and after the move |
| Ruff | `uvx ruff check src tests` | `All checks passed!` |
| Pyright (source profile, strict) | `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| Certified validation profile | `./scripts/profiled_gate.sh` | `profiled typecheck + walking-skeleton smoke: OK` (exit 0); tests-profile `0 errors, 1 warning` — the pre-existing `tests/test_research_program.py:141` `reportSelfClsParameterName` warning, present on the certified baseline and in an untouched file |
| Whitespace | `git diff --check` | clean |
| Working tree | `git status --porcelain=v1` | only the five known untracked items; 0 tracked modifications |

Count reconciliation: DG-3B §18/§24 estimated S6 at 44 and gateway at 33; the
measured current counts are **45** and **35**. These are the *same* counts before
and after the extraction — the estimates were approximations, not a change
introduced here. No test was weakened, deleted, skipped, or reinterpreted; the
absolute collection total moved only by the three additive pins (2051 → 2054),
exactly as expected.

Note on the pytest summary line: `scripts/run_tests.py` documents a host-venv
session-teardown crash that suppresses the final summary line even when every
test passes; the suite was therefore validated by **exit code 0 + zero
FAILED/ERROR markers + the independently measured collection count (2054)**, the
same method recorded in the DG-3B and S-2 reports.

---

## §12 Three new characterization pins

All three were added **before** the production edit and were green against the
pre-move tree (the pre-move L2 run was 59 passed with the family still defined in
`gateway.py`), satisfying DG-3B §24.1.

| Pin | Test | Proves |
|---|---|---|
| 1 | `test_pin1_module_boundary_single_implementation` (`:889`) | Ownership and no-duplicate: pre-move, the family is defined exactly once and gateway-owned; post-move, all five functions resolve from `l2_resolution`, the gateway's call site uses the **identical imported function object** (`gw._l2_resolve_upstream is l2._l2_resolve_upstream`), and **no `def _l2_…` remains in the gateway source**. This is what prevents a copy-paste relocation from silently creating a second implementation. |
| 2 | `test_pin2_resolver_reads_only_opens_no_transaction` (`:916`) | Purity: a `_RecordingConn` proxy captures every statement the resolver issues across all four rule carriers (bare hit, typed `<type>:<hash>`, `evidence:` form, task hop via `derived_from`/`used_as_input`/`cites`); every statement must start with `SELECT`, and none may contain `INSERT`/`UPDATE`/`DELETE`/`BEGIN`/`COMMIT`/`ROLLBACK`. Turns "read-only, transaction-free" into a property rather than an observation. |
| 3 | `test_pin3_global_by_key_caller_side_isolation` (`:950`) | Scope-by-design: a `p2` artifact id resolves by key (the resolver has no project parameter), and a `p1` retraction still never emits a `p2` dependent row referencing the same key — so isolation is provably the caller's emission JOIN. Pins the behavior that must **not** be "corrected" during a move. |

The pins carry no production hook, no `monkeypatch` of production code, and no
new test dependency; the only test-file support additions are the local
`_RecordingConn`/`_RecordingCursor` proxies and the `_L2_SYMBOLS` constant.

---

## §13 Adversarial review

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Was any second implementation left in Gateway? | **PASS — no** | `def _l2_` count in `gateway.py` = 0 for all five names; pin 1 asserts it; `gw` exposes exactly one of them (the imported `_l2_resolve_upstream`, identity-true) |
| 2 | Did any transaction move? | **PASS — no** | 0 `BEGIN`/`COMMIT`/`ROLLBACK` in the module; the five `BEGIN IMMEDIATE` sites stay in `gateway.py` under unchanged owners (§6) |
| 3 | Did any write move? | **PASS — no** | module SQL literals are 6 × `SELECT` only; runtime spy pin asserts it |
| 4 | Did any refusal move? | **PASS — no** | no `_reject`, no `GatewayRejection`, no refusal code in the module; refusal machinery and 16 codes untouched |
| 5 | Did any authority check move? | **PASS — no** | no credential/operator/role/`HumanDecision` reference in the module; caller-side gates unchanged |
| 6 | Did any identity generation move? | **PASS — no** | no `uuid`/`hashlib`/`secrets`/`random`/`time`/`datetime` import or token; module consumes ids only |
| 7 | Did project filtering change? | **PASS — no** | emission JOIN byte-identical (`1207-1211` vs `1362-1366`); pin 3 pins global-by-key on purpose |
| 8 | Did L2 precedence change? | **PASS — no** | AST-identical bodies; precedence 1→2→3→4 unchanged; precedence tests (`test_13`, `test_a6`, `test_5`, `test_8`) green |
| 9 | Did `_memo` semantics change? | **PASS — no** | `_memo=None` default, per-`(value, edge_type)` keying, `set(...)` copy-on-read all AST-identical |
| 10 | Did replay behavior change? | **PASS — no** | read-only; determinism/replay pins green (§9) |
| 11 | Did journal ordering change? | **PASS — no** | no event/journal token in the module; `test_event_ordering_and_causality` and `test_mid_cascade_failure_writes_nothing` green |
| 12 | Did a circular import appear? | **PASS — no** | importing `l2_resolution` loads neither `gateway` nor `persistence`; module imports stdlib only (§5) |
| 13 | Did a public API change? | **PASS — no** | `gateway.__all__` still `["GatewayRejection", "IntentResult", "apply_intent"]`; new module is INTERNAL with no `__all__` assignment and is not exported from the package; no Controller signature touched |
| 14 | Did the test suite get weakened? | **PASS — no** | 2051 → 2054 collected (additive only); 262 pre-move = 262 post-move on the six slices; the two test edits are one import retarget, one stale docstring pointer, and three new pins — no assertion deleted, relaxed, skipped, or reinterpreted |
| 15 | Did anything outside DG-3B scope change? | **PASS — no** | diff is exactly 3 files, all authorized (§3); the line-shift audit proves the gateway change is one import + one contiguous deletion |

Corollary scope check: the two seams DG-3B marked YELLOW/RED (contradiction
fact pair, transaction-owning validators), the C-01a in-file step helpers, DG-5,
DG-6, DG-4, and any further gateway extraction remain untouched.

---

## §14 Known limitations

Preserved deliberately; **not** fixed here (DG-3B §22/§24.4):

* **L2 is global-by-key.** The resolver has no project predicate; isolation is
  supplied by the caller's emission JOIN. Pin 3 exists so a future agent cannot
  "helpfully" add a filter and change matched-cone semantics.
* **The L2 identifier-form defect** (documented in the S5 L2 design gate) is
  unchanged and is now owned by `l2_resolution.py`.
* **The F-01 STALE wart** remains exactly as it was.
* **All DG-3B RED / YELLOW / NOT-A-SEAM rows remain untouched**, including
  `_decision_append_transactional`, `_resolve_ratified_proposal`, the four
  transaction-owning validators, the contradiction validators, and the refusal
  machinery.
* **Multi-owner transaction reality** recorded by DG-3B §3d (repositories,
  the gateway's five sites, and the Controller) is unchanged by this
  extraction — it is precisely why those seams remain ineligible.
* **Cosmetic debt is retained**: the moved preamble comment, the mixed
  `str | None` style, and the lazy function-local `import json as _json` all move
  verbatim rather than being modernized.

---

## §15 Final certification

```text
S-3 — CERTIFIED / GATEWAY L2 EXTRACTION SUCCESSFUL
```

Verified: baseline `65e82c0` matched exactly; DG-3B authorization followed
precisely; characterization pins established and green *before* the production
extraction; only the shared L2 upstream-reference resolution family moved; the
four verdict surfaces, the gateway's transaction owners, authority ordering,
identity generation, journal/`IntentApplied`, project-isolation contract, and N9
protection are all unchanged; L2 59 / S5 34 / S6 45 / Step-7 68 / N9 21 /
gateway 35 all green (262 total, identical pre- and post-move); full suite exit 0
with 0 failures and 0 errors over **2054** collected tests; Ruff clean; Pyright
source profile `0 errors, 0 warnings`; `profiled_gate.sh` OK with only the
pre-existing warning; `git diff --check` clean; adversarial review 15/15 PASS
with zero blockers; implementation (`df57650`) and certification are separate
commits; `HEAD == origin/main`.

Final architecture:

```text
Gateway
  └── imports _l2_resolve_upstream, calls it from the unchanged call site

l2_resolution (internal, no __all__)
  └── pure / read-only resolution, 6 × SELECT, 0 writes, 0 transactions
      └── stdlib only (typing; function-local json, verbatim)
```
