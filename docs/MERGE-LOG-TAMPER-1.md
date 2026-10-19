# MERGE-LOG-TAMPER-1 — append-only journal triggers, stage S (GAP-1 P1-1, ruling D1-A)

## Provenance

| Item | Value |
| --- | --- |
| Task | TAMPER-1-MERGE (merge gate; local FF — the push is bundled with the sibling GAP-1 slices under one human D9 pin) |
| Base (`main` before) | `ee09c7d` (TASK-ADMIT-1 landing + its merge log) |
| Slice | `slice/tamper-1@002135c`; **restacked** as `slice/tamper-1-restacked@1556706` (cherry-pick of `5876f01` + `223e975` + `a6d8fc4`; the slice's own re-stamp dropped and re-created for the combined count — **no rebase**, no merge commit) |
| Landed tip (FF'd to) | `1556706` — tree `69e27a7f62cdba567ea8d30eb3155eacafde7256` |
| Merge worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` |
| Merge method | **fast-forward** — `git merge --ff-only` (exit 0); single-parent chain |
| Push | drafted, **NOT executed** — bundled with the GAP-1 fleet under one human D9 pin |

## Scope

Stage S only (per ruling D1-A): append-only abort triggers + the pre-existing
design record. **No hash chain, no re-chain tool** — that is TAMPER-2,
chartered-deferred, not dropped.

```
docs/idr/TAMPER-EVIDENT-JOURNAL.md |  25 +  2 -   (design record landed + residual-honesty addendum)
src/hermes/persistence/migrations.py | 54 +  1 -  (triggers helper; _migrate_20_to_21; rebuild re-creation)
tests/journal_tamper.py            |  62 +  0 -   (the one tamper-simulation helper)
tests/test_journal_append_only_triggers.py | 261 + 0 - (9 pins)
15 consumer/pin test files         | adaptations + version pins 20 -> 21
docs/SUITE-COUNT.md                |   3 +  3 -   (4773 -> 4807)
```

## What was certified

- `BEFORE UPDATE` / `BEFORE DELETE` triggers on `events` raise
  `HERMES_JOURNAL_IMMUTABLE_UPDATE` / `HERMES_JOURNAL_IMMUTABLE_DELETE`
  (IDR TAMPER-EVIDENT-JOURNAL §2.1). INSERT is untouched — the single journal
  writer and every raw-insert fixture keep working.
- Migration `20 -> 21` (`SUPPORTED_VERSION` 21) adds the triggers on upgrade;
  `_migrate_2_to_3` re-creates them after its rebuild (the §3.1 rebuild rule —
  a table rebuild destroys triggers). This **absorbs GAP-1 P3-5**.
- No src code UPDATEs/DELETEs `events` (grep empty), so no production path
  meets the trigger; the refusal surface is raw-SQL tamper, exactly the threat.
- The pin test compares the shipped trigger SQL to the reference prover DDL
  verbatim (modulo whitespace; SQLite stores the text with `IF NOT EXISTS`
  stripped — empirically verified), so the design is not weakened.
- **Residual honesty (in the IDR):** triggers deter in-DB UPDATE/DELETE only;
  DB-file-level swap or `DROP TRIGGER` is NOT covered — TAMPER-2 territory,
  chartered-deferred, not dropped.

## Test adaptations (24 sites, one helper discipline)

All 24 deliberate tamper simulations (14 `UPDATE events` + 10 `DELETE FROM
events`) across 9 test files now route through `tests/journal_tamper.py::
tamper_events`, which FIRST asserts the shipped trigger refuses with the named
error, then drops/restores both triggers (from captured `sqlite_master` DDL)
to perform the mutation. Every adapted site therefore proves **both** the
refusal and the consumer's fail-closed behavior; a stale no-op tamper fails
loudly. Version pins moved 20 -> 21 across the schema-pin files. Not adapted
(justified): `test_database.py:270` raw DELETE — runs against a hand-built v2
fixture before `_migrate_2_to_3`; no triggers exist there.

## Fail-on-base

Fix reverted (base `SUPPORTED_VERSION=20`), new tests present:
`tests/test_journal_append_only_triggers.py` → **9 failed, 0 passed**
(`assert 20 == 21`, `DID NOT RAISE IntegrityError`, `assert set() ==
{trg_...}`, `no such trigger`). Supplementary consumer probe
(`test_vault_manifest.py -k "gapped or journal_head_regression"`) → 2 failed,
`DID NOT RAISE IntegrityError` at `tests/journal_tamper.py:46`. Fix restored;
only intended deltas remained.

## Gates (raw)

Agent run (slice tip): full suite `4774 passed, 3 skipped, 0 failed` (490.37s);
stamp OK 4777 (own branch); census PASS; B4 24/24; ruff pass; pyright src
0/0/0; pyright tests 0 errors + 1 pre-existing warning.

Director re-derivation (restacked tip `1556706`): stamp `--check` OK **4807**;
census **PASS** (121/27/1/15 unchanged — trigger SQL adds no acquisition
owner); B4 `24 passed`; battery (`journal_append_only_triggers` + `archive` +
`vault_manifest` + `step7_curated_registry` + `q04_gate_replay` + `database` +
`cli`) all green; ruff `All checks passed!`; NOT-list scan of the restack
range diff **0 hits**.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| src writes UPDATE/DELETE on events | **none** — append-only invariant intact |
| census shift | **none** — 121/27/1/15 unchanged |
| rebuild path covered | **PASS** — trigger re-creation in `_migrate_2_to_3`, pinned |
| adapted tests weakened | **none** — assert-refusal-first helper; version pins only |
| D10 interlock | **noted** — "SQL bypass covered by D1(A)" is now real for in-DB writers; the structural lifecycle-edge pin is a separate queued item |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `ee09c7d` |
| `--check` drift | **PASS** — 4807 (4773 + 34) |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies an SQL-layer append-only refusal for in-DB mutations of
the event journal. It makes no validity, reproducibility, or admissibility
claim, and explicitly does not cover out-of-DB journal substitution
(TAMPER-2, chartered-deferred).

License: Apache-2.0 (LICENSE).
