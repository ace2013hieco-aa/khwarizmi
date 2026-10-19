# MERGE-LOG-CRED-1 — operator-credential revoke/rotate + legacy rehash + token stdin (GAP-1 P1-3/P1-4, rulings D7-A)

## Provenance

| Item | Value |
| --- | --- |
| Task | CRED-1-MERGE (merge gate; local FF — the push is bundled with the sibling GAP-1 slices under one human D9 pin) |
| Base (`main` before) | `02013b8` (TAMPER-1 landing + its merge log) |
| Slice | `slice/cred-1@9bd0558`; **restacked** as `slice/cred-1-restacked@b989b6d0` (cherry-picks of `b9230d3` + `1473c60` + `a7e3b90` + `447acfd` + `09a4508` + `034452c`; the slice's own re-stamp dropped and re-created — **no rebase**, no merge commit) |
| Landed tip (FF'd to) | `b989b6d0` — tree `95be9fba61e7fd95e73bc2a3b341080ede53ea08` |
| Merge worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` (holder) |
| Merge method | **fast-forward** — `git merge --ff-only` (exit 0); single-parent chain |
| Push | drafted, **NOT executed** — bundled with the GAP-1 fleet under one human D9 pin |

## The restack (migration-number collision with TAMPER-1)

Both slices originally claimed migration **20 → 21**; TAMPER-1 landed first. On
restack, CRED-1's migration was renumbered **21 → 22** in the conflict
resolution: `_migrate_20_to_21` stays TAMPER-1's (triggers) and `_migrate_21_to_22`
carries `operator_credentials.revoked_at`; `SUPPORTED_VERSION = 22`,
`len(_MIGRATIONS) == 22`. All schema-version pins and rewind sets across the
suite were brought to the combined truth (files: `tests/test_claims_write_path.py`,
`test_database.py` incl. both rewind lists, `test_q05_evidence_ladder.py`,
`test_research_program.py`, `test_thesis_ar03.py`, `test_c1_slot_ref.py`,
`test_claim_ground.py`, `test_journal_append_only_triggers.py`), and the three
raw conflicts were resolved to keep **both** sides: TAMPER's triggers intact in
`_migrate_20_to_21`, plus the renamed CRED migration. Two extra resolution
commits are part of the restacked branch: `120829e` (align the TAMPER-1 trigger
pins with the 21 → 22 chain; its fresh-DB pin renamed to `..._to_latest_...`)
and `b989b6d` (docs-truth pass, below).

## Scope

```
src/hermes/core/intents.py          |  +2 intent kinds (REVOKE/ROTATE_OPERATOR_CREDENTIAL, director_only)
src/hermes/core/events.py           |  +2 event types
src/hermes/persistence/migrations.py|  +migration 21 -> 22 (revoked_at, nullable, no backfill)
src/hermes/persistence/repositories.py | revocation state + one new acquisition owner
src/hermes/research/gateway.py      |  validator + dispatch for the two director-only kinds
src/hermes/cli.py                   |  revoke/rotate verbs, --token-stdin (mutually exclusive with --token)
scripts/check_census.py             |  constants 121/27/persistence 18 -> 124/28/19
AGENTS.md, docs/ARCHITECTURE.md     |  census figures updated truthfully
docs/API.md                         |  intent vocabulary + token channels
tests/test_cred1_credential_lifecycle.py | 19 pins
tests/test_cred1_rehash_on_verify.py     |  8 pins
tests/test_cred1_token_stdin.py          |  4 pins
tests/test_census_check.py, tests/test_cli_output_scrub.py, B4 fixtures/README | aligned
docs/SUITE-COUNT.md                 | 4807 -> 4838
```

## What was certified

- **A — revoke/rotate through `apply_intent` only.** Two new director-only
  intent kinds; ONE new acquisition owner (`_apply_credential_mutation`);
  revoke is terminal and archive-not-delete; replay of an exact command returns
  `duplicate=True`. Revoked credentials refuse everywhere (`verify()` /
  `exists()`).
- **B — `--token-stdin`.** Token accepted on stdin, never argv; no env-var
  channel; mutually exclusive with `--token`.
- **C — legacy rehash.** `upgrade_legacy_hash` re-verifies then CAS-updates to
  PBKDF2 on a **successful resolve only** (`_gate_resolve`); a failed auth
  never upgrades; no journal event (the credential row is unchanged in
  identity terms; the hash upgrade is transparent).
- **Census delta (ruling-critical, verified, not gamed):** 121 → **124**
  transaction-control calls, 27 → **28** acquisition owners (persistence
  18 → **19**), rollback-only participant and the 15 imports unchanged.
  `scripts/check_census.py` reproduces exactly; AGENTS.md and
  `docs/ARCHITECTURE.md` §3.10 carry the same figures.
- **Docs-truth pass (`b989b6d`)** while landing: corrected two stale figures in
  the `docs/ARCHITECTURE.md` layer table row (schema v19 → **v22**; persistence
  acquisition owners 18 → **19**) and one in the body (schema v19 → **v22**),
  then regenerated the three affected B4 fixtures per the documented
  §Regenerating procedure: `2cf0464e… → 1727860b…`, `cf54f4c5… → 0551a2a6…`,
  `a7ddd5a2… → be83b607…` (b4-c3 unchanged; edge sets, counts, and skipped
  lists identical — only the ARCHITECTURE.md source identity moved). README
  table updated; regen record appended. This is the same governance pattern as
  the recorded O2 census and GATE-DOC-REGEN regenerations.

## Fail-on-base

Fix reverted (base `9bd0558`-parent without the three fix commits), new tests
present: **all 31 fail** (30 `AttributeError`/`SystemExit` + 1 strengthened
negative; 0 passed) — log `cred-1-fail-on-base.log`. Fix restored; only
intended deltas remained.

## Gates (raw)

Agent run (slice tip): full suite `4774 passed, 3 skipped, 0 failed`; own-branch
stamp 4774; census PASS; B4 24/24; ruff pass; pyright src 0/0/0; pyright tests
0 errors + 1 pre-existing warning.

Director re-derivation (restacked tip `b989b6d0`): battery — `test_cred1_credential_lifecycle`
+ `test_cred1_rehash_on_verify` + `test_cred1_token_stdin` + `test_operator_knobs`
+ `test_journal_append_only_triggers` + `test_database` + `test_claims_write_path`
+ `test_q05_evidence_ladder` + `test_research_program` + `test_thesis_ar03` +
`test_c1_slot_ref` + `test_claim_ground` + `test_census_check` +
`test_cli_output_scrub` + `test_b4_ref_graphs` → **399 passed**; stamp `--check`
OK **4838** (4807 + 31); census **PASS**; B4 **24 passed**; ruff
`All checks passed!`; NOT-list scan of the restack range **0 hits** with a
word-boundary pattern (a first substring pass produced two false positives on
"i**tse**lf" in prose — recorded here for honesty; boundary rerun clean).

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits (boundary pattern; substring noise recorded above) |
| migration collision with TAMPER-1 | **resolved** — renumbered 21 → 22; triggers intact; pins and rewind sets carry 21 and 22 |
| census shift | **+3 calls / +1 owner (persistence 19)** — truthful, constants+docs+literals consistent, check_census PASS |
| rotate token handling | **PASS** — `new_token` returned at the CLI boundary only; never in payloads/events/logs |
| B4 governed corpora | **PASS** — deliberate regen with recorded digests; b4-c3 untouched |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `02013b8` |
| `--check` drift | **PASS** — 4838 (4807 + 31) |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies the credential-lifecycle commands operate through the
single intent gateway with the recorded census delta, that legacy hashes
upgrade only on successful verification, and that tokens are accepted via
stdin. It makes no validity, reproducibility, or admissibility claim.

License: Apache-2.0 (LICENSE).
