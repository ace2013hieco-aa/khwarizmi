# CLEANUP/A3 — Certified-census checker

**Task:** CLEANUP/A3-census-checker · **Role:** implementer · **Date:** 2026-09-28
**Repository:** `D:\New folder\research-agent` (`khwarizmi-research`, Hermes research control plane)
**Branch:** `cleanup/a3-census`, cut from `main` @ `84b9a246d21a765ce47d0f303f0f8b6248065038` (local-only; no push)
**Inputs:** the census lines in `AGENTS.md`, `docs/ARCHITECTURE.md` §3.10, the DG-4 derivation method
(`docs/archive/HERMES_DG4_REPOSITORY_STRUCTURAL_DESIGN_GATE_2026-09-21.md` §4, re-run in DG-6 §5), and
the live `src/` tree. Nothing else.
**Deliverables:** `scripts/check_census.py` (new), `tests/test_census_check.py` (new), this record.

## 0. Invariants honoured

| Invariant | Status |
|---|---|
| Checker is read-only analysis; no `src/` modification by the tool | **HELD** — `src/` has zero diff; the tool only opens files for reading, and `tests/test_census_check.py::test_tool_is_read_only_and_stdlib_only` statically forbids write/delete/subprocess calls in its source |
| Figures are fixed; the tool must reproduce them | **HELD** — they are module constants, pinned as literals by a test, and a mismatch prints FAIL with the delta and exits 1 |
| stdlib-only | **HELD** — imports are `argparse`, `ast`, `dataclasses`, `pathlib`, `sys` (pinned by the same test) |
| Deterministic | **HELD** — sorted file walk, sorted owner/import tables, no clock, no network, no environment reads, no dict-iteration-order dependence in output |
| No push | **HELD** — one local commit on `cleanup/a3-census` |

## 1. The certified figures and where they come from

| Figure | Certified | Source (at `main`) |
|---|---|---|
| executed transaction-control calls | **121** | `docs/ARCHITECTURE.md` §3.10 ("121 executed transaction-control calls held by 27 acquisition owners plus one rollback-only participant"); `docs/MERGE-AUDIT.md` C1 records the re-derivation `113 -> 121` |
| acquisition owners — persistence | **18** | `AGENTS.md` ("27 acquisition owners across persistence (18), gateway (5), and Controller (4)"); §3.10 gives the file-level split (11 `repositories.py`, 2 `database.py`, 1 each in `failure_classifications.py`, `source_outcomes.py`, `corpus.py`, `graph_edges.py`, `migrations.py`) |
| acquisition owners — gateway | **5** | `AGENTS.md`; §3.10 (all `BEGIN IMMEDIATE`) |
| acquisition owners — Controller | **4** | `AGENTS.md`; §3.10 (lease acquire, human-gate resolve, floor, ladder) |
| acquisition owners — total | **27** | `AGENTS.md`; §3.10 |
| rollback-only participants | **1** | `AGENTS.md` ("plus one rollback-only participant"); DG-4 §4 names it (`ClaimAssumptionRepository._validate_supersede_target`) |
| persistence→research import statements | **15** | `AGENTS.md` (Change discipline, "15 statements, CERTIFIED INTENTIONAL ARCHITECTURE, NOT DEBT"); §3.10 ("A bounded set of persistence→research runtime dependencies (15 import statements)") |

## 2. Derivation rules implemented (DG-4 §4 provenance)

1. **Control-call rule** — an *executed* `‹expr›.execute(‹string literal›)` whose literal, stripped and
   upper-cased, starts with `BEGIN`, `COMMIT`, `ROLLBACK`, `SAVEPOINT` or `RELEASE`. Derived from the
   AST, so docstring/comment prose is excluded by construction (DG-4 §4 records prose at
   `repositories.py:798`, `gateway.py:512`, `database.py:108`). A non-literal first argument — a
   variable, an f-string, a concatenation — is not counted.
2. **Owner rule** — the enclosing function (class-qualified) of at least one *acquisition* call
   (`BEGIN`/`SAVEPOINT`) is an acquisition owner. A function issuing control calls but acquiring
   nothing is a *participant*; a participant whose only calls are `ROLLBACK` is a rollback-only
   participant (DG-4 §4b: transaction participation ≠ ownership).
3. **Layer rule** — owners are attributed by file: `src/hermes/persistence/` → persistence,
   `src/hermes/research/gateway.py` → gateway, `src/hermes/research/controller.py` → Controller.
   Control calls anywhere else are counted separately and **fail** the check, because the certified
   census has no other owner.
4. **Import rule** — every `import`/`from` statement inside `src/hermes/persistence/` whose target
   module is `hermes.research` or a submodule of it, at any nesting depth (module level or the
   lazy/function-level imports DG-4 §10 documents); each statement counts once.

The certified figures are **not** tuned to the tool: the rules above are DG-4's, and the tool reports
FAIL rather than adjusting. The observed per-owner counts reproduce DG-4's table row-for-row for every
owner that existed then (e.g. `ResearchProgramRepository.record` 1B/2C/6R,
`EventRepository.append_transactional` 2B/1C/2R, gateway `_validate_curate_knowledge` 8R,
`_validate_record_contradiction` 8R, Controller's four owners), which is independent evidence that the
implementation is the method DG-4 used rather than a coincidentally-equal count.

## 3. Current result — PASS

`python scripts/check_census.py --verbose` on `cleanup/a3-census` (exit code 0):

```text
certified census check - src/hermes (read-only)

figure                                       certified  measured  status
------------------------------------------------------------------------------
executed transaction-control calls                 121       121  OK
acquisition owners (persistence)                    18        18  OK
acquisition owners (gateway)                         5         5  OK
acquisition owners (Controller)                      4         4  OK
acquisition owners (total)                          27        27  OK
rollback-only participants                           1         1  OK
persistence->research import statements             15        15  OK
control calls outside certified layers               0         0  OK

control calls by statement: BEGIN 28, COMMIT 27, ROLLBACK 66
owners by layer: persistence 18, gateway 5, Controller 4

PASS - every certified figure is reproduced exactly.
```

**Cross-check against the documents, file by file.** The measured persistence split is
`repositories.py` 11, `database.py` 2, `failure_classifications.py` 1, `source_outcomes.py` 1,
`corpus.py` 1, `graph_edges.py` 1, `migrations.py` 1 = **18** — exactly the split `docs/ARCHITECTURE.md`
§3.10 states. The single participant is
`src/hermes/persistence/repositories.py:ClaimAssumptionRepository._validate_supersede_target`
(0B/0C/3R) — the participant DG-4 §4 names. `BEGIN 28` for 27 owners is the expected off-by-one:
`EventRepository.append_transactional` deliberately re-enters with a second, plain `BEGIN` for its
retry path (DG-4 §4a).

The 15 imports are module-level (`repositories.py:52/62/63/64/69`, `failure_classifications.py:53/65`,
`source_outcomes.py:41`) and lazy/function-level (`repositories.py:241/1302/1341/1422/2511`,
`program_obligations.py:55/169`).

## 4. Maintenance rule (binding for future census edits)

**The census is a certified invariant, and it now has an executable oracle.**

1. **Any change that can move a figure must run the checker.** A figure moves if a change adds or
   removes: an executed transaction-control call, a function that acquires a transaction, a
   persistence→research import statement, or control calls outside the three certified layers.
   That covers new repositories, new transaction boundaries, new gateway/Controller owners, new
   migrations, new lazy research imports from persistence, and any move of control flow between
   layers.
2. **Census edits require checker-green.** If a figure legitimately moves, the change is an
   architectural change: it needs its own design gate, the census sentence in `AGENTS.md` and
   `docs/ARCHITECTURE.md` §3.10 must be updated **in the same commit** as the code that moved it, and
   the checker's certified constants must be updated with a citation to that gate. The commit is not
   complete until `python scripts/check_census.py` prints PASS on the final tree.
3. **Never edit a constant to make a red tree green.** The constants encode a certified architecture;
   the tool's job is to prove the tree still matches. A red checker on unchanged figures means the
   change needs a gate, not a new number. `tests/test_census_check.py` pins the five constants as
   literals precisely so a silent loosening is impossible.
4. **Run it cheaply and often.** The checker is stdlib-only, reads ~80 files, and takes well under a
   second — it is a pre-commit-grade check. Suggested wiring (a separate, deliberately out-of-scope
   change): call it from `scripts/profiled_gate.sh` and/or CI next to `ruff`/`pyright`, and add
   `scripts/check_census.py` to the lint scope (`ruff check src tests scripts/check_census.py` is clean
   today; the canonical `ruff check src tests` does not cover `scripts/`).

## 5. The tests (`tests/test_census_check.py`, 11 cases)

| Case | What it pins |
|---|---|
| `test_live_tree_reproduces_every_certified_figure` | the live tree passes, with each figure asserted individually |
| `test_live_tree_owner_partition_matches_the_certified_split` | 27 = 18 + 5 + 4, no fourth layer, participant classified |
| `test_certified_constants_are_the_certified_figures` | the five constants are exactly the certified numbers (no loosening) |
| `test_cli_passes_on_the_live_tree` | the CLI exits 0 and prints PASS (subprocess, real entry point) |
| `test_rule_counts_only_executed_literal_control_calls` | literal-only rule; docstring prose, variables, f-strings and `executescript` are excluded |
| `test_rule_owner_versus_participant` | owner vs participant vs rollback-only participant |
| `test_rule_class_qualified_owner_names` | owner names are class-qualified (`Repo.Inner.nested`) |
| `test_rule_layer_attribution_and_foreign_detection` | the three layers, and foreign-layer control calls fail |
| `test_rule_counts_only_persistence_to_research_imports` | persistence-only, any nesting depth, research-only targets |
| `test_rule_reports_failures_instead_of_adjusting_figures` | an empty tree FAILs (renders FAIL, `compare()` non-empty) instead of silently passing |
| `test_tool_is_read_only_and_stdlib_only` | no write/delete/exec calls in the checker; stdlib imports only; ASCII-only source |

## 6. Gate evidence

Run on `cleanup/a3-census` on 2026-09-28, with the checker, its tests and this record in the tree:

```text
python scripts/check_census.py                        ->  PASS (exit 0)
.venv/Scripts/python.exe scripts/run_tests.py         ->  2221 passed in 419.24s (0:06:59)
uvx ruff check src tests scripts/check_census.py      ->  All checks passed!
uvx pyright src                                       ->  0 errors, 0 warnings, 0 informations
uvx pyright --project pyrightconfig.tests.json        ->  0 errors, 1 warning (pre-existing:
                                                          tests/test_research_program.py:144)
```

`2221 = 2210 + 11`: the suite count before this change was 2210, and the delta is exactly the eleven
cases in `tests/test_census_check.py` — no existing test changed behaviour. `src/` is byte-identical to
`main` (`git diff --stat main -- src/` is empty): the checker reads the tree and nothing writes to it.

Note on lint scope: `ruff check src tests scripts/check_census.py` is clean, but the canonical
`ruff check src tests` does not cover `scripts/`. Wiring `scripts/check_census.py` into the lint scope
is a deliberate, separate proposal (maintenance rule 4), not a change made here.

## 7. Usage

```text
python scripts/check_census.py             # figures table + PASS/FAIL (exit 0/1)
python scripts/check_census.py --verbose   # adds the per-owner, participant and import tables
python scripts/check_census.py --repo-root <path>   # measure a different checkout
```
