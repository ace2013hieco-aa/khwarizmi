# MERGE-AUDIT-SCANFIX — delta audit of `merge/scanfix@6f186d9`

Delta audit of the FIX-NOTES-DEDUP + FIX-FENCE-CLASSIFIER integration as
merged into `merge/scanfix`. Findings, counts and `file:line`. Executed in an
isolated worktree (`scanfix-merge-wt`); `main` and the two owning worktrees
were opened read-only and never written.

The audited integration tip is `6f186d9` (merge 2). The two docs commits that
follow — `0181f16` (MERGE-LOG) and this file's commit — add `docs/` only:
`git diff --exit-code 6f186d9 HEAD -- src tests` → exit 0, so every finding
below holds at the final tip.

## Inputs receipt (all readable, no STOP)

| Input | Value | State |
| --- | --- | --- |
| `main` (local) | `6a5b69f3f0662411abcae9b5ec74aed9aa0cd3a1` | read, never touched |
| `main` (remote, `git ls-remote origin refs/heads/main`) | `6a5b69f3f0662411abcae9b5ec74aed9aa0cd3a1` | identical — unmoved before **and** after |
| `fix/notes-dedup` tip | `96308567714f52407a7ecb3c65612e9d495c2109` | read-only |
| `fix/fence-classifier` tip | `6d6a194589468e07cba8194b1017cd8b263c20e5` | read-only |
| `merge/scanfix` entry tip | `6a5b69f…` | new branch off `main` |
| merge 1 | `1255e32481d324fd7179b2eef052c2ba89173106` | zero conflicts |
| merge 2 (integration tip) | `6f186d97bafa9669b118a8cdc1861dea96d7ae95` | zero conflicts, `ort` auto-merged `controller.py` |
| `merge/scanfix` on the remote | **absent** (`git ls-remote origin 'refs/heads/merge/scanfix'` → empty) | never pushed |

Forbidden-topic scan (`backtest_audit`, `SDA`, `TSE`,
`Optimize-my-strategy`) over the integrated code:
`git grep -i -n -E "backtest_audit|optimize-my-strategy" HEAD -- src tests` →
**0 hits**. The two long-form terms are the greppable ones; the short
acronyms were excluded as false-positive-prone and the four changed files
(`git diff --name-only main..HEAD`) are exactly the two lines' declared sets.
**No STOP condition fired.**

## Integration integrity

| # | Claim | Command | Result |
| --- | --- | --- | --- |
| INV1 | merged tip vs fence tip is exactly the notes patch | `git diff --stat fix/fence-classifier HEAD` | 2 files, 261/22 — the notes commit's stat exactly |
| INV2 | merged tip vs notes tip is exactly the fence patch | `git diff --stat fix/notes-dedup HEAD` | 3 files, 560/55 — the fence commit's stat exactly |
| INV3/4 | merge 2's own deltas vs each parent equal the other line | `git diff --stat HEAD^1 HEAD` / `HEAD^2 HEAD` | 560/55 / 261/22 |
| INV5 | no conflict markers | `grep -rn "^<<<<<<<\|^>>>>>>>\|^=======$" src tests` | NONE |
| INV6 | merge parents | `git rev-list --parents -n 1 HEAD` | `6f186d9 1255e32 6d6a194` |
| INV7 | docs commits leave src+tests byte-identical | `git diff --exit-code 6f186d9 HEAD -- src tests` | exit 0 |

Hunk-disjointness (verified, not assumed): fence's single hunk landed at
merged lines **134–409** (`_FencedConnection`); notes' eight hunks at merged
lines **757, 1605, 2220, 4244, 4272, 4288, 4304, 4685**. No src change was
authored by the integrator.

## Refusal-narrowing re-scan — no existing refusal flipped

**Byte-level proof.** The four fenced-connection refusals were AST-extracted
(`ast.get_source_segment` over the `_FencedConnection` class body) from
`git show <rev>:src/hermes/research/controller.py` for `main`,
`fix/fence-classifier` and the merged tip, and compared:

| Method | Verdict |
| --- | --- |
| `executescript` | **BYTE-IDENTICAL** across main / fence tip / merged tip |
| `cursor` | **BYTE-IDENTICAL** |
| `commit` | **BYTE-IDENTICAL** |
| `rollback` | **BYTE-IDENTICAL** |
| `execute` / `executemany` | IDENTICAL — the widening lives solely in `_is_write` (and its scan helpers), never in the call-surface |

**Behavioral proof at the merged tip** —
`pytest tests/test_fence_classifier.py tests/test_notes_dedup.py` →
**57 passed in 1.25s**, exit 0:

- 54-test fence battery: 27 fenced rows (DML; CTE writes incl. paren-in-
  literal/comment/quoted-identifier/bracket/escaped-quote shapes;
  `CREATE`/`DROP`/`ALTER`/`PRAGMA`/`ATTACH`/`DETACH`/`VACUUM`/`REINDEX`/
  `ANALYZE`; comment-prefixed DDL; unknown verb; malformed unterminated
  literal/comment — fail closed), 15 free rows (reads + CTE reads +
  recursive CTE + comment-prefixed reads + control verbs), 2 F-01 db-level
  (`LockLostError`, no landing), 6 F-02 db-level (`LockLostError`, no
  landing), 1 valid-lease positive control (DDL/PRAGMA/literal-CTE write
  pass), 1 refusal-surface test (`test_refusal_surface_unchanged` —
  `TypeError` for `executescript`/`cursor`/`commit`/`rollback`), 2 B-F-04
  transaction-durability tests.
- The free battery passing pins the other direction: no read flipped **to**
  fenced, so semantics widened only.

## Notes observability — healthy-path `ctrl.notes` assertions green

All three FIX-NOTES-DEDUP tests pass at the merged tip
(`tests/test_notes_dedup.py`):
`test_active_ticks_produce_distinct_notes_only` (:156 — three ACTIVE ticks;
`len(ctrl.notes) == len(set(ctrl.notes))` **and** the distinct conditions
survive: `contradiction detection:` and `Q-04: dispatch blocked by failure
cone of task A`), `test_parked_gate_ticks_produce_distinct_notes_only` (:179
— parked ticks dedupe while the INVALIDATED-dep note survives),
`test_resolve_surface_does_not_duplicate_the_tick_note` (:200 — the verdict
surface refreshes the tick note and still returns `rejected: False`).
`_note_once` pre-exists on `main` (`controller.py:498`; merged tip `:705`) —
the change routes raw append sites through it; no gate/observable logic moved.

## Gates (measured on `6f186d9`)

| Gate | Command | Result |
| --- | --- | --- |
| Full suite (DG-4 §16 named command) | `.venv/Scripts/python.exe scripts/run_tests.py -q` | **exit 0**, `[100%]`, **2566** test dots, zero `F`/`E` |
| Lint | `.venv/Scripts/ruff.exe check src tests` | `All checks passed!` — exit 0 |
| Types (src, strict) | `.venv/Scripts/pyright.exe --pythonpath <abs worktree venv python> src` | `0 errors, 0 warnings, 0 informations` |
| Types (tests) | same `--pythonpath`, `--project pyrightconfig.tests.json` | `0 errors, 1 warning` — pre-existing `tests/test_research_program.py:144` |
| Census | `.venv/Scripts/python.exe scripts/check_census.py` | `PASS` — 121/18/5/4/27/1/15/0 reproduced exactly |

Count lineage: 2509 (`main` baseline) → 2512 (notes tip, reported by its
task) → 2563 (fence tip, reported by its task) → **2566 measured here**
(2509 + 54 + 3), matching exactly. Self-contained proof of "no loss": the
57-test targeted run is 54 + 3; the suite gained exactly those 57 over the
fence tip's 2563.

## Counts + `file:line` at the merged tip

- `src/hermes/research/controller.py` — fence: `_scan_statement` :184,
  `_cte_statement_keyword` :276, `_is_write` :383, `execute` :408,
  `executemany` :413, refusals :418/:428/:440/:450; notes: `_note_once` :705,
  contradiction note `key="contradiction-detection"` :2228,
  `_cone_blocked_dispatch_notes` :4247,
  `_parked_gate_invalidated_dep_notes` :4283. 297/71.
- `src/hermes/persistence/database.py` — `acquire_writer_lock` :94
  (`begun` :112, `BEGIN IMMEDIATE` :114, shared refusal rollback :138–139).
  18/6, census-neutral.
- `tests/test_fence_classifier.py` 286/0 (sections :78 FENCED, :121 FREE,
  tests :146/:152/:164/:183/:204/:227/:248/:266); `tests/test_notes_dedup.py`
  220/0 (tests :156/:179/:200).

## Verdict: PASS — cleared for a fresh D9 push decision

No MUST-FIX and no SHOULD-FIX raised by this delta. No existing refusal
flipped (byte-identical bodies + refusal-surface test green). Fence semantics
widened only (free battery green). Notes emission deduped with all
healthy-path assertions green. All gates green at the integration tip; the
census figures are unchanged.

`main` was **not** advanced and **not** pushed; `merge/scanfix` is **absent
from the remote**. D9 is lapsed — the push decision is the director's, on a
fresh D9.
