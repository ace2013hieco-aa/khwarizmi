# HERMES G-1 — SourceOutcomeRepository Proposed-Set Extraction Certification

**Date:** 2026-09-21
**Gate:** DG-4 G-1 (single authorized repository seam)
**Report:** this file (the only change in the certification commit)

---

## §0 Verdict

```text
G-1 — CERTIFIED / PROPOSED-SET EXTRACTION SUCCESSFUL
```

`SourceOutcomeRepository._proposed_set` is now the module-level private
`_proposed_set(outcome, outcome_kind)` in `src/hermes/persistence/source_outcomes.py`
at `184-200`. The executable body is AST-identical to the baseline, the single call site
moved from `self._proposed_set(...)` to `_proposed_set(...)` and still executes
**before** `BEGIN IMMEDIATE`, and no other symbol in the module changed.

---

## §1 Baseline and implementation identity

```text
repository            github.com/ace2013hieco-aa/khwarizmi-research
branch                main
DG-4 baseline         4b501e99d3e95a024ba1b72ef1b8032d60fb30b7   (DG-4 report commit)
implementation        b9a30a9d8d97cc806b2d0859285bacf53a64660f   refactor(persistence): extract proposed-set helper
implementation parent 4b501e99d3e95a024ba1b72ef1b8032d60fb30b7
origin/main           b9a30a9d8d97cc806b2d0859285bacf53a64660f   (HEAD == origin/main)
working tree          clean (no uncommitted diff vs HEAD)
untracked (pre-existing, untouched)
                      IDEA.md, Prompts/, logos/, orci.json, orhead.json, ortree.json
```

`git show --numstat b9a30a9`:

```text
20      14      src/hermes/persistence/source_outcomes.py
249     0       tests/test_provider_orchestration.py
```

Two files, exactly the authorized scope: the production module and the additive
characterization tests.

---

## §2 Exact source transformation

```text
baseline   source_outcomes.py:456-467    def _proposed_set(self, outcome: object,
                                                 outcome_kind: str) -> frozenset[str]
current    source_outcomes.py:184-200    def _proposed_set(outcome: object,
                                                 outcome_kind: str) -> frozenset[str]
```

```text
placement      module level, after source_artifact_retracted (ends 186) and before
               @dataclass(frozen=True) class SourceRepos (203)
class          SourceOutcomeRepository  248-1067  (no longer defines _proposed_set)
record         287-328
call site      line 311  proposed = _proposed_set(outcome, outcome_kind)
BEGIN IMMEDIATE line 313
```

The diff is three hunks and nothing else:

1. `+` the module-level helper (19 added lines: `def` + docstring + 7 executable lines);
2. `~` the caller line 311 (`self._proposed_set` → `_proposed_set`);
3. `−` the 12-line method removed from the class body.

**One deliberate, disclosed deviation.** The docstring is the baseline docstring
**extended by 4 documentation lines** naming the DG-4 ownership boundary (module-level,
pure, no connection/SQL/transaction/event/clock/identity, computed before
`BEGIN IMMEDIATE`). Its first three lines are byte-identical to the baseline. The
*executable* body is untouched (§3). This follows the S-4 precedent, whose extracted
`_s5_cone_closure` likewise carried a new one-line contract docstring.

---

## §3 AST equivalence

Mechanical comparison of `git show 4b501e9:src/hermes/persistence/source_outcomes.py`
against the current file (`ast.dump(..., include_attributes=False)`):

```text
=== EXECUTABLE BODY AST EQUIVALENCE ===
baseline statement hashes  e54aaf904c4392ce  bc9fb6a2d41e049c  29a61867516b0323
current  statement hashes  e54aaf904c4392ce  bc9fb6a2d41e049c  29a61867516b0323
IDENTICAL: True            (all three statements, including the nested for/if/else)
```

The three statements are, in order:

```text
s = {outcome_record_hash(outcome, outcome_kind)}
if outcome_kind == "search":
    for r in getattr(outcome, "per_provider", ()): s.add(r.content_hash)
else:
    for f in getattr(outcome, "per_source", ()):   s.add(f.artifact.content_hash)
return frozenset(s)
```

Signature comparison:

```text
baseline args  ['self', 'outcome', 'outcome_kind']   kwonly []   vararg None
current  args  [       'outcome', 'outcome_kind']    kwonly []   vararg None
annotations equal: True (outcome: object, outcome_kind: str)
returns equal:     True (frozenset[str])
defaults:          [] == []      kw_defaults: [] == []
docstring first 3 lines identical: True   (extended by 4 documentation lines)
```

**Only `self` was removed**, plus the docstring extension noted in §2. Whole-module AST
delta (every top-level symbol and every class method hashed):

```text
removed symbols  ['SourceOutcomeRepository._proposed_set']
added symbols    ['_proposed_set']
changed symbols  ['SourceOutcomeRepository', 'SourceOutcomeRepository.record']
                 (membership, and the single call line — nothing else)
unchanged        38 of 40
```

Methods verified byte-for-byte AST-identical after the move: `__init__`,
`_resolve_idempotency`, `_commit`, `_validate_task_binding`, `_verify_reused_row`,
`_prepare_search`, `_prepare_fetch`, `_source_artifact_resolves`,
`source_artifact_retracted`, `SourceRepos`.

---

## §4 Purity / containment proof

AST surface of the extracted helper's body (docstring excluded):

```text
names    ['f', 'frozenset', 'getattr', 'outcome', 'outcome_kind',
          'outcome_record_hash', 'r', 's']
attrs    ['add', 'artifact', 'content_hash']
calls    ['frozenset', 'getattr', 'outcome_record_hash', 's.add']
strings  ['per_provider', 'per_source', 'search']
banned tokens found: []      (conn, cursor, execute, commit, rollback, savepoint,
                              EventType, _append_event, _reject, clock, uuid, hashlib,
                              random, secrets, project_id, time)
```

* **no `self` reference** anywhere in the body (baseline and current both empty) — the
  mechanical justification DG-4 used to call this a seam;
* the only free name is `outcome_record_hash`, a deterministic pure derivation imported at
  `source_outcomes.py:45` from `hermes.tools.research_sources`; its own preimage builder
  (`_search_outcome_hash` / `_fetch_outcome_hash`) reads its argument and constructs dicts
  only — no mutation, no I/O;
* the only strings are the two `getattr` attribute names and the `"search"` branch literal;
* no import added, no module created, no `__all__` change, no package export.

The helper is a function of its two arguments plus one pure module-level function. This is
the property G1-2 pins as an executable test.

---

## §5 Pre-transaction ordering proof

```text
record (287-328):
    ... self._validate_identities(outcome, outcome_kind)      # pure, pre-transaction
  311   proposed = _proposed_set(outcome, outcome_kind)        # ← the helper
  313   self._conn.execute("BEGIN IMMEDIATE")                  # ← acquisition
```

* helper calls inside `record`: **1**, at line 311; `BEGIN IMMEDIATE` at 313 → call
  precedes acquisition;
* the call is a **top-level statement of `record`** (its own `Assign` to `proposed`), ahead
  of the `try` block that holds the transaction body — it cannot be reached only inside the
  transaction;
* module-wide `_proposed_set(` calls: **1**; `self._proposed_set` attribute calls
  remaining: **0**.

This is what G1-3 pins: the assertion is structural (statement order within `record`'s
body + line-order against the `BEGIN IMMEDIATE` call node), not a line-number literal, and
it fails if the call is moved below acquisition or into the transaction body.

**Why it matters:** because the SET is computed outside the transaction, no transaction
snapshot participates in it. `_resolve_idempotency` (line 296-…) later compares that
already-computed `frozenset` against the *in-transaction* read — the read stays where it
was, and the computation stays pure.

---

## §6 Transaction ownership

Transaction-control sequence inside `record`, order-preserved:

```text
baseline  [(294,'BEGIN IMMEDIATE'), (302,'COMMIT'), (305,'ROLLBACK'), (308,'ROLLBACK')]
current   [(313,'BEGIN IMMEDIATE'), (321,'COMMIT'), (324,'ROLLBACK'), (327,'ROLLBACK')]
verb SEQUENCE equal: True
```

Only the line numbers shift (+19, the size of the inserted helper and its two blank
lines). Recording base:

```text
SourceOutcomeRepository.record remains the module's transaction owner
  BEGIN IMMEDIATE 1 · COMMIT 1 · ROLLBACK 2          (unchanged verb multiset and order)
no SAVEPOINT / RELEASE anywhere                     (unchanged)
connection ownership unchanged (self._conn, one acquisition per record call)
rollback coverage unchanged: both `except SourceOutcomeError` and `except Exception`
```

The helper receives **no connection** and opens **no transaction**: it cannot participate
in, extend or shorten the atomic scope. `DG-4`'s transaction census is unaffected — the
repository still holds the same acquisition count it held at `4b501e9`.

---

## §7 Input mutation

G1-5 pins it, and the proof is structural rather than statistical: the body's only
mutating operations are `s.add(...)` on a **local** `frozenset`-backed set and
`getattr(...)` reads; `dataclasses.asdict(outcome)` is compared before/after for both a
search outcome (with two results) and a fetch outcome, and the `per_provider` /
`per_source` content-hash sequences are compared before/after as well. Both are equal, and
`outcome_kind` (a `str`) is unchanged.

No copy-in, no normalisation, no cache was added — the helper reads and returns.

---

## §8 Identity

| Check | Result |
| ----- | ------ |
| UUID / randomness | none in the helper (no `uuid`, `random`, `secrets` tokens) |
| hashing | none in the helper — it **consumes** `outcome_record_hash(...)` and the `content_hash` attributes; it computes no hash of its own |
| content identity authorship | unchanged — the same derivation (`outcome_record_hash`, per-result `content_hash`) at the same point |
| decision / idempotency identity | unchanged — `_resolve_idempotency`, `_commit`, `validation_verdict_id_of`-style authorship untouched (AST-identical methods) |
| correlation ids | untouched (`repositories.py` `uuid.uuid4()` sites not in this diff) |

Identity mode for this symbol is **CONSUME**, exactly as DG-4 classified it, so relocating
it moved no authorship.

---

## §9 Journal / events

* the helper contains no event construction and no `EventType`/`_append_event_to_db`
  reference (banned-token scan: empty);
* the module's event write path is unchanged: `source_outcomes.py:777-779`'s lazy
  `_append_event_to_db` import and call sit inside `record`'s transaction and are
  AST-identical (`record`'s only change is the one call line at 311);
* the `SourceRetracted` auto-emission ordering (`mutation → event → COMMIT`) is untouched —
  the transaction verb sequence is identical (§6).

`_append_event_to_db` itself (`repositories.py:92-128`) is not in this diff at all.

---

## §10 N9

```text
tests/test_n9_retraction_admission.py   →  21/21 passed   (pre-move and post-move)
```

Neither N9 predicate was touched:

```text
_source_artifact_resolves   AST hash 9214e6afc0a72193  (baseline == current)
source_artifact_retracted   AST hash 9a419511b4400c8e  (baseline == current)
```

`gateway.py:2262`, `failure_classifications.py:378/411` and
`contradiction_candidates.py:62` consume those predicates unchanged; `repositories.py:51`'s
eager import of `_source_artifact_resolves` and `source_outcomes.py`'s lazy import back are
untouched, so the persistence-internal cycle pair is exactly as it was. No retraction,
classification-admission, contradiction or supersession code is in the diff.

---

## §11 Project isolation

The helper takes no `project_id` and issues no query — verified by the banned-token scan
(`project_id` appears in neither the names, attributes, calls nor string literals of the
body). It was *not* given one: the project dimension continues to be supplied by the
caller (`_validate_task_binding`, `_validate_project`, the project-scoped INSERTs), exactly
as DG-4 §13 recorded for the global-by-key `ArtifactRepository.get_by_hash` model.

Isolation behaviour was exercised end-to-end by the repository slice including
`tests/test_provider_orchestration.py`'s cross-project cases (the global-content +
edge-carried-ownership tests) — all green post-move.

---

## §12 API surface

```text
SourceOutcomeRepository public methods   unchanged (no signature edits anywhere)
__all__                                  unchanged (module defines none; none added)
package export                           none added
Controller / Gateway / CLI surfaces      untouched (no file in this diff)
new public API                           none — the helper is module-private (`_`-prefixed)
class attribute removed                  SourceOutcomeRepository._proposed_set
                                         (private; zero importers existed)
```

The only name that changed visibility is a private helper with **no callers outside the
module** (verified: `grep -rn "_proposed_set" src/ tests/ scripts/` finds only the
definition, the one call site, and the new pins).

---

## §13 Tests

```text
tests/test_provider_orchestration.py
  before   63 tests   2442 lines
  after    68 tests   2691 lines   (+249 / −0)
  additive imports +4: `import ast`, `import pathlib`,
                      `from hermes.persistence import source_outcomes`,
                      `outcome_record_hash` (added to the existing
                      hermes.tools.research_sources import list)
```

Mechanical proof that the existing file is otherwise untouched: reconstructing the file up
to the new block and diffing it against `git show 4b501e9:tests/...` yields **0 deleted
lines** and only the 4 import additions (+2 spacing blank lines). `def test_` count:
59 → 64 (+5). Existing assertions were neither edited nor removed.

### The five additive pins

| Pin | Test | What it proves |
| --- | ---- | -------------- |
| G1-1 | `test_g1_1_proposed_set_semantics` | empty stream → singleton `{outcome_hash}`; singleton; multiple; duplicate results collapse (set, not multiset — asserted on the `content_hash` equality itself); observation-only change (access timestamp) leaves the SET identical; fetch branch uses per-source payload hashes; return type is `frozenset`; repeat calls equal |
| G1-2 | `test_g1_2_helper_containment_and_single_owner` | **exactly one** implementation exists (module-level xor method, never both), the runtime namespace agrees with the source, the last two params are `outcome, outcome_kind`, the body never names `self`, and the identifier/attribute/call/string surface is a subset of the pure allowlist with all 16 banned tokens absent (node-wise AST, so the docstring cannot mask or fake a hit) |
| G1-3 | `test_g1_3_helper_runs_before_transaction_acquisition` | one call site, one `BEGIN IMMEDIATE`, the call is a top-level statement of `record` ordered **before** acquisition, and exactly one production caller exists in the module |
| G1-4 | `test_g1_4_caller_equivalence_against_persisted_hashes` | through the real repository: the SET the helper computes equals the artifact content hashes persisted for the task; identical re-acceptance → `IDENTICAL` with no new rows; different content → `DIVERGENT` → `SourceOutcomeConflictError` |
| G1-5 | `test_g1_5_helper_does_not_mutate_its_inputs` | a search and a fetch outcome are `dataclasses.asdict`-equal before/after the call, and `outcome_kind` is unchanged |

**Pre-move green — the equivalence evidence.** All five pins were written and run
**before** the production edit, against the *method* form: `5 passed`. They then passed
again unchanged against the module-level form. The pins are written to assert the
*invariant*, not the shape (an ownership-tolerant accessor resolves the helper either way;
the shape is asserted separately by G1-2's single-owner check), so a green run on both
sides of the move is itself the equivalence proof — and confirms the pins expose no
pre-existing failure.

**Disclosed deviation.** These pins do read the private helper (through the module
namespace) and the shipped module source, whereas DG-4 noted that no existing test imported
this symbol. That is required by DG-4's own pin design (P-DG4-1 invokes the helper
directly; P-DG4-2/P-DG4-3 inspect module source) and is consistent with this repository's
nine pre-existing private-helper test imports (§16 of DG-4). The imported name is the
module, not the symbol, so the pre-move branch stays valid; after the move the module-level
lookup is the only branch taken.

---

## §14 Validation

| Gate | Command | Result |
| ---- | ------- | ------ |
| full suite (pre-commit) | `.venv/Scripts/python.exe scripts/run_tests.py -q` | **exit 0**, reached `[100%]`, zero `F`/`E` markers (the pytest summary line is suppressed by the documented host-venv teardown issue in `scripts/run_tests.py`, hence exit-code capture) |
| collected count | `python -m pytest --collect-only -q` (summed) | **2062 tests in 63 files** = 2057 baseline + **exactly 5** additive pins |
| slices | `-q tests/test_provider_orchestration.py tests/test_n9_retraction_admission.py tests/test_q05_persistence.py tests/test_repositories.py tests/test_chg2_providers.py tests/test_p4_wiring.py tests/test_hr04_source_identifier_capture.py` | 278 pre-move → **283** post-move, all green; N9 alone **21/21**; pins alone **5/5** |
| ruff | `uvx ruff check src tests` | `All checks passed!` |
| pyright | `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| profiled gate | `./scripts/profiled_gate.sh` | **exit 0** — `profiled typecheck + walking-skeleton smoke: OK`; only the pre-existing `tests/test_research_program.py:141:23` warning (unchanged file, also present at the DG-4 baseline) |
| diff hygiene | `git diff --check` | clean |
| post-commit re-verification | full suite **and** slices + ruff + pyright re-run on `b9a30a9` with a clean working tree | full suite **exit 0** again at `[100%]` (zero `F`/`E`); slices 283 green; ruff `All checks passed!`; pyright `0 errors, 0 warnings` (§1) |

No warning was suppressed, and no production code was changed to make a gate pass.

---

## §15 30-question adversarial review

| # | Question | Verdict | Evidence |
| - | -------- | ------- | -------- |
| 1 | Body AST-equivalent? | **PASS** | §3 — three statement hashes identical |
| 2 | Only `self` removed from the signature? | **PASS** | §3 — annotations/defaults/kwonly identical; docstring extended (documentation only, disclosed) |
| 3 | Exactly one production caller? | **PASS** | §5 — one module-wide call, 0 attribute calls |
| 4 | Caller still before `BEGIN IMMEDIATE`? | **PASS** | §5 — call 311 < BEGIN 313, top-level statement |
| 5 | Transaction acquisition unchanged? | **PASS** | §6 — one `BEGIN IMMEDIATE`, same position in the sequence |
| 6 | Commit/rollback unchanged? | **PASS** | §6 — identical verb sequence and multiset |
| 7 | Exception behaviour unchanged? | **PASS** | body AST-identical; the helper raises nothing itself and propagates exactly what `outcome_record_hash`/`getattr` raise, as before; both `except` arms in `record` untouched |
| 8 | Input mutation behaviour unchanged? | **PASS** | §7 + G1-5 |
| 9 | SQL unchanged? | **PASS** | no SQL in the helper (had none); module SQL AST-identical |
| 10 | Journal ordering unchanged? | **PASS** | §9 |
| 11 | Identity authorship unchanged? | **PASS** | §8 |
| 12 | Project isolation unchanged? | **PASS** | §11 |
| 13 | N9 behaviour unchanged? | **PASS** | §10 — predicates hash-identical, 21/21 |
| 14 | Authority behaviour unchanged? | **PASS** | no credential/HumanDecision/lease code in the diff; `repositories.py` and `database.py` untouched |
| 15 | Public API surfaces unchanged? | **PASS** | §12 |
| 16 | `__all__` unchanged? | **PASS** | §12 |
| 17 | `_verify_reused_row` untouched? | **PASS** | AST hash `519ac9636941e48a` before and after |
| 18 | All DG-4 rejected candidates untouched? | **PASS** | whole-module AST delta shows one moved symbol; no other file in the diff |
| 19 | Tests additive only? | **PASS** | +249/−0; reconstruction check shows 0 deleted lines |
| 20 | Helper has no persistence/I/O dependency? | **PASS** | §4 — banned-token scan empty; only pure `outcome_record_hash` |
| 21 | No hidden global dependency? | **PASS** | §4 — single free name, deterministic, no module state read |
| 22 | Pre-transaction placement structurally pinned? | **PASS** | G1-3 (statement ordering + call-node ordering, fails if moved below acquisition) |
| 23 | Full suite green? | **PASS** | §14 — exit 0 |
| 24 | Ruff and Pyright clean? | **PASS** | §14 |
| 25 | Diff minimal? | **PASS** | 2 files, 3 hunks, +20/−14 production, +249/−0 tests |
| 26 | No new module? | **PASS** | same file |
| 27 | No new abstraction? | **PASS** | one module-private function; no class, protocol, registry or indirection |
| 28 | No transaction boundary changed? | **PASS** | §6 |
| 29 | No API contract changed? | **PASS** | §12 |
| 30 | Revertible as one isolated commit? | **PASS** | `b9a30a9` is self-contained; reverting restores the method + caller exactly (no schema, data or migration surface) |

**No FAIL. No unresolved AMBIGUOUS.** The two items that required explicit disclosure —
the 4-line docstring extension (§2) and the pins' private-symbol access (§13) — are
behaviour-neutral and are classified here rather than left implicit.

---

## §16 Diff scope

```text
git diff --name-only 4b501e9                       → 2 files
git show --numstat b9a30a9
  20  14  src/hermes/persistence/source_outcomes.py
 249   0  tests/test_provider_orchestration.py
```

```text
production modules changed     1  (source_outcomes.py)
other persistence modules      0
Controller                     0
gateway                        0
persistence architecture       0 (no new module, no new layer, no new import)
schemas / migrations / config  0
documentation in impl commit   0
```

The certification commit adds only this report.

---

## §17 Residual DG-4 negative map (still prohibited)

Nothing below was touched, and each still requires its own gate:

* the sibling seam `_verify_reused_row` (`source_outcomes.py:800-861`) — YELLOW, deferred
  because it raises `SourceOutcomeIntegrityError` inside `_commit`'s transaction;
* the N9 predicates `_source_artifact_resolves` / `source_artifact_retracted` — RED
  (connection-taking reads, 4 consumer modules, part of cycle pair (a));
* `_append_event_to_db` and all event ordering — RED (journal owner);
* the 25 transaction acquisition owners (persistence 16 / gateway 5 / Controller 4) and the
  rollback-only participant `ClaimAssumptionRepository._validate_supersede_target` — RED;
* `program_obligations.py` / `provider_interactions.py` write paths — RED (transaction
  participants);
* the `_is_extract_spec` triplication across three layers
  (`repositories.py:1820`, `research/extraction.py:309`, `research/gateway.py:3231`) — RED
  for a repository gate; **DG-5**;
* the cross-layer private imports (`research/gateway.py:1487`,
  `research/completion.py:63`, `failure_classifications.py:448/476/497/555/584`) and all 16
  persistence→research inversion sites — **DG-5**;
* `ArtifactRepository.get_by_hash` global-by-key semantics — unchanged by design;
* the `docs/ARCHITECTURE.md:140` transaction-owner drift — still uncorrected (recommended
  for the DG-5 report, not authorised here);
* nothing in DG-4's forbidden list (class splits, interfaces, unit-of-work, event buses,
  ORM/CQRS/service layers) was introduced — the diff is one function move.

The five DG-4-baseline untracked items are untouched; a sixth (`logos/`) appeared in the
working tree during this task and was never read, staged or modified by this work.

---

## §18 Final certification

```text
G-1 — CERTIFIED / PROPOSED-SET EXTRACTION SUCCESSFUL
```

The extraction is exactly the small, pre-transaction, pure seam DG-4 authorized: one
private 12-line computation, moved verbatim (AST-identical) from a repository method to a
module-level private function in the same file, called from the same place before
`BEGIN IMMEDIATE`, with its semantics, transaction ownership, journal ordering, identity
mode, project isolation and N9 behaviour unchanged — and with purity and pre-transaction
placement now enforced by executable pins rather than by comment.

**Next authorized step: DG-5 — Persistence → Research Inversion Design Gate.** No further
repository seam is authorized by this certification.
