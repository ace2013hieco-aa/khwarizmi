# MERGE-LOG-CFIX — integration of the fence-delegation + vault-notes lines onto `main`

Merge integrator record for the two C-line hardening branches: FIX-FENCE-DELEGATION
(`fix/fence-delegation@c24ab9a`, C-FIX-2) and FIX-VAULT-NOTES
(`fix/vault-notes@afbaaf2`, C-FIX-1 legs 1 + 2). Follows the
`MERGE-LOG-SCANFIX` / `MERGE-LOG-P-AUTO-1` pattern.

**Outcome: both lines were integrated with zero conflicts and verified on
`merge/cfix` (integration tip `7bea35e`); the delta audit returned PASS
(`docs/MERGE-AUDIT-CFIX.md`). `main` was NOT advanced and NOT pushed — D9 is
lapsed and this task is merge + audit only.**

## Inputs

| Input | Value |
| --- | --- |
| Repository | `D:\New folder\research-agent` (`ace2013hieco-aa/khwarizmi-research`) |
| `main` at task start (local) | `0c711417e8dccd359f11b7e1ec20e2d135d84dd2` |
| `main` at task start (remote) | `0c711417e8dccd359f11b7e1ec20e2d135d84dd2` (`git ls-remote origin refs/heads/main` — pasted) |
| `fix/fence-delegation` tip | `c24ab9a1c3dfeec45f8de66b5f1e0d1c9c252859` (4 files, +251/−20; owning gate DG-4 §14) |
| `fix/vault-notes` tip | `afbaaf29fa80d446acdf22233760890c73d9c8df` (2 commits, 4 files, +329/−30) |
| Human approval banked | none — **D9 lapsed; no push under any circumstance** |

Both tips branch directly off `main`:
`git merge-base fix/fence-delegation fix/vault-notes` =
`0c711417e8dccd359f11b7e1ec20e2d135d84dd2` (== `main`), verified at task start.

## Merge hashes

| Ref | Hash |
| --- | --- |
| `merge-base main HEAD` | `0c711417e8dccd359f11b7e1ec20e2d135d84dd2` (== `main`) |
| `merge/cfix` entry tip | `0c71141…` (created via `git worktree add "/d/New folder/research-agent-merge-cfix-wt" -b merge/cfix main`) |
| merge 1 — fence-delegation | `8ae9ad46bfefa862b2b7d0c57b1c11353bcfc368` |
| merge 2 — vault-notes (integration tip) | `7bea35e2c07a05b79298765a01571398005ced37` |
| `main` old → new | `0c71141…` → **unchanged** |

## Lines integrated (5 commits, `0c71141..7bea35e`)

| Commit | Subject |
| --- | --- |
| `c24ab9a` | fix(fence): close raw-connection delegation + foreign-COMMIT release (C-FIX-2) |
| `8b7c050` | fix(vault): align validity substrate with production payload keys (C-FIX-1 leg 1, local-only) |
| `afbaaf2` | fix(notes): route 13 direct appends through `_note_once` with stable keys (C-FIX-1 leg 2, local-only) |
| `8ae9ad4` | merge(fence-delegation): integrate `fix/fence-delegation` tip `c24ab9a` into `merge/cfix` (local-only) |
| `7bea35e` | merge(vault-notes): integrate `fix/vault-notes` tip `afbaaf2` into `merge/cfix` (local-only) |

Diffstat `main..7bea35e` — 7 files, 580 insertions, 50 deletions
(`git diff --numstat main HEAD`):

```
61/8    src/hermes/persistence/database.py
112/31  src/hermes/research/controller.py   (both lines)
59/3    src/hermes/vault/projection.py
110/0   tests/test_fence_classifier.py
35/0    tests/test_notes_dedup.py
192/0   tests/test_p_auto_5_vault_production_shapes.py
11/8    tests/test_phase1_acceptance.py
```

No file outside the two lines' declared sets (fence 4 files + vault 4 files,
`controller.py` shared = 7 distinct files). 580/50 equals fence (251/20) +
vault (329/30) exactly; `controller.py` 112/31 equals fence (69/4) + vault
(43/27) exactly.

## Conflicts and resolutions — zero conflicts, hunk-disjoint

Both lines edit `src/hermes/research/controller.py`. The dry run
(`git merge-tree --write-tree fix/fence-delegation fix/vault-notes`) returned
tree `e2d11b011b7ddea68ec88b7047aa457db16dbe68` with exit 0, and the two
sequential `ort` merges produced the **identical tree hash** — deterministic,
zero conflicts. `ort` auto-merged `controller.py`; no manual hunk was written
and no conflict marker ever existed.

Hunk disjointness on `controller.py` (old-file coordinates):

- fence side (`git diff main fix/fence-delegation`): changed old lines
  151–152 and 477–478; hunk spans 148–481 (the second hunk is a pure insertion
  around line 165). This is the `_FencedConnection` region only
  (`_REFUSED_DELEGATIONS` at `src/hermes/research/controller.py:499`,
  `in_transaction` :514, `__getattr__` :524).
- vault side (`git diff main fix/vault-notes`): 12 hunks, changed old lines
  923–5350; the `Controller` body only.
- 445-line separation between the last fence change (478) and the first vault
  change (923); zero shared hunks.
- `git diff fix/fence-delegation HEAD -- src/hermes/research/controller.py`
  = vault's 12 hunks (new-side line numbers all ≥ 985);
  `git diff fix/vault-notes HEAD -- src/hermes/research/controller.py`
  = fence's 3 hunks (148–545).

Byte-level patch composition (scratch sandbox, `patch -p1`):

- vault controller + fence patch → merged controller, byte-identical;
- fence controller + vault patch → merged controller, byte-identical
  (12 hunks applied with a uniform +65-line offset, zero fuzz, zero failed
  hunks);
- sha256 of all three resulting files:
  `cf9062cbf179d76a02072755dc78fc8e869fa05f3ff7ab356f0e57d00d4df858`.

No `src/` or `tests/` change exists on the merge branch beyond the two tips'
own patches; the merge commits introduce nothing of their own.

## Gates at the integration tip `7bea35e`

All commands run in the isolated worktree with
`PYTHONPATH="D:/New folder/research-agent-merge-cfix-wt/src"`; import origin
asserted first:
`IMPORT_ORIGIN D:\New folder\research-agent-merge-cfix-wt\src\hermes\__init__.py`.

| Gate | Command | Result |
| --- | --- | --- |
| Full suite | `pytest` | **2693 passed**, 0 failed, 12 warnings, 567.43s, exit 0 |
| Ruff (declared set) | `ruff check src tests` | `All checks passed!` exit 0 |
| Ruff (repo) | `ruff check .` | 79 errors — byte-identical distribution to `main`: 33 `scripts/adversarial_probe_s5.py`, 13 `scripts/p1b_audit2_probes.py`, 33 across `experiments/texp-001/*`; pre-existing, out of scope |
| Pyright (src) | `pyright -p pyrightconfig.json` | 0 errors, 0 warnings, 0 informations |
| Pyright (tests) | `pyright -p pyrightconfig.tests.json` | 0 errors, 1 warning (`tests/test_research_program.py:144` — the pre-existing `main` baseline warning) |
| Census | `python scripts/check_census.py` | PASS — every certified figure reproduced exactly |

Census raw output:

```
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

Slice runs (each exit 0):

```
tests/test_fence_classifier.py                  71 passed
tests/test_phase1_acceptance.py                 28 passed
tests/test_database.py                          22 passed
tests/test_controller.py                       109 passed
tests/test_notes_dedup.py                        4 passed
tests/test_p_auto_5_vault.py                    24 passed
tests/test_p_auto_5_vault_production_shapes.py   5 passed
tests/test_census_check.py                      11 passed
```

Count lineage: the vault line adds `tests/test_p_auto_5_vault_production_shapes.py`
(+5 tests, new file) and one new `test_notes_dedup.py` test (3 on `main` → 4 on
the merged tip) = +6 over the fence-only suite recorded at `c24ab9a`
(2687 passed) → 2693. No test was deleted or renamed:
`git diff --name-status main HEAD -- tests` = 3×M + 1×A. Cross-checks in
read-only worktrees: the three fence slices together on `fix/fence-delegation`
= 121 passed = 71 + 28 + 22 (identical to the merged tip); `test_database.py`
= 22 on `main` (file untouched, as expected); `test_notes_dedup.py` = 3 on
`main`.

## Probes at the merged tip

| Probe | What it exercises | Result |
| --- | --- | --- |
| `fence_fix_probe.py` | 11-method delegation inventory, udf/serialize/backup, read surface, C-F-08 chain | all 11 `REFUSED-TypeError`; `close`/`row_factory`/unknown `REFUSED-AttributeError`; udf/serialize/backup refused; `in_transaction False`, `SELECT 42` OK; foreign release `REFUSED-DatabaseLockError` (foreign row stays invisible: 0), asserted acquire→release chain OK, re-acquire OK |
| classifier battery (verbatim from scan `p4`) | 22-shape write classifier + `EXPLAIN INSERT` | 0 mismatches; `EXPLAIN INSERT` executes nothing (rows stay 1) |
| `p1.py` | vault validity end-to-end over production payload shapes | admitted curated knowledge superseded by its invalidation (`evt-000002-…-admitted.md superseded=True`), contradiction notes retired (`evt-000004`/`evt-000005` `superseded=True`), task invalidation retires (`evt-000008` `authoritative: false`); ladder note stays live by documented design |
| `p2.py` | notes growth per read call | bounded: 0 → 1 → 1 and 2 → 2 (no growth; stable keys) |
| `p5.py` (raw, pre-fix probe) | release over a foreign open transaction | now raises `DatabaseLockError` at `src/hermes/persistence/database.py:199` (pre-fix it COMMITted the foreign insert) |

Probe logs kept outside the repo (`/tmp/merge-cfix/probes/`).

## Docs commits

- this file (`docs/MERGE-LOG-CFIX.md`);
- `docs/MERGE-AUDIT-CFIX.md` (delta audit, verdict PASS).

Each is its own commit and adds exactly one file;
`git diff --exit-code 7bea35e HEAD -- src tests` → exit 0 at the final tip, so
every gate above holds at `HEAD`.

## D9 / push status

`merge/cfix` has **no upstream** (`git rev-parse --abbrev-ref merge/cfix@{u}`
→ exit 128) and the branch is absent on the remote
(`git ls-remote origin refs/heads/merge/cfix` → empty). `main` verified unmoved
before and after integration (local == remote == `0c71141…`). Nothing was
pushed.
