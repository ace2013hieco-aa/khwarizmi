# MERGE-LOG-CHG-DEDUP-1 — the upstream recorded-pair skip (P1-9)

## Provenance

| Item | Value |
| --- | --- |
| Task | CHG-DEDUP-1-MERGE (merge gate; local FF — the push is bundled with the three sibling slices under one human D9 pin) |
| Base (`main` before) | `2b0228decc853f480f30755582c35eaa04ff70d8` |
| Slice | `slice/chg-dedup-1@fbd649ee43c2c6ca71a43730c5c5ad1773d115bf` |
| Slice commits | `12d66d8` (fix) + `2f5713b` (9 pins) + `fbd649e` (re-stamp 4678) |
| Landed tip (FF'd to) | `fbd649e` — tree `7a16ce70d1524a01f3f3dc6333360efaefeb28c6` |
| Merge worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` |
| Merge method | **fast-forward** — `git merge --ff-only` (exit 0); single-parent chain; no rebase |
| Push | drafted, **NOT executed** — bundled with CX-OVERLAP-1 / CRES-DIGEST-1 / RESOLVER-PARITY-1 under one human D9 pin |

## Scope

4 files, **+530/−3** — the source diff is **pure additions (73 insertions, 0 deletions)**:

```
src/hermes/research/contradiction_candidates.py |  41 +   (new read-only `recorded_pair_keys` helper)
src/hermes/research/controller.py               |  32 +   (skip in `_detect_contradictions_pass`)
tests/test_chg_dedup_tick_skip.py               | 454 +   (9 pins, new)
docs/SUITE-COUNT.md                             |   3 +-  (4669 -> 4678)
```

**The fix (P1-9).** Before an intent is built in `_detect_contradictions_pass`, each candidate's
pair identity — recomputed via `contradiction_id_of` (content-hash discipline; never the stored
`contradiction_id` column) — is checked against the project's recorded contradictions and
already-recorded pairs are skipped, counted in `duplicates` (the count the gateway would have
reported). The gateway/journal are untouched: resubmission previously appended one `IntentApplied`
audit row per ACTIVE tick with zero mutation, so a stable recorded pair grew the journal once per
tick. Direct-submission replay duplicates still append their audit rows (pins green).

**Design decisions.** Status predicate = **any row** (OPEN / RESOLVED / SUPERSEDED): the gateway's
duplicate lookup is status-blind (existing row ⇒ `duplicate=True`, zero mutation, audit row only),
and retraction-driven supersession invalidates the parties in-transaction with no un-retract, so a
superseded pair can never legitimately need re-recording — justified and pinned. The read
delegates to the certified any-status read (`ContradictionRepository.all_entries`) — **no new
SQL, no new transaction, no acquisition owner** (census unchanged); project-scoped; unkeyable
rows fall through to the gateway's fail-closed validation. `detector_candidate_rows` /
`detect_classification_conflicts` unchanged (HR8-1 completion parity intact).

## The 9 pins (`tests/test_chg_dedup_tick_skip.py`, +454)

`test_stable_pair_records_once_then_zero_journal_growth` ·
`test_recorded_open_pair_skipped_new_pair_still_recorded` · `test_resolved_pair_not_resubmitted` ·
`test_superseded_pair_stays_skipped` · `test_retraction_superseded_pair_not_redetected` ·
`test_repeated_passes_append_delete_rewrite_nothing` · `test_direct_replay_still_appends_audit_row` ·
`test_fresh_conflict_still_denies_completion_exactly_once` · `test_project_scoped_and_recomputed_never_trusted`.

## Fail-on-base (agent-run, scratch at `2b0228d` + the new test file)

**7 failed, 2 passed** (exit 1): the growth/skip/snapshot pins fail behaviourally on base (journal
grows per tick; stored-pair resubmission appends audit rows; helper import absent) — the 2
base-passes are the intended behaviour-preserving pins (retraction-superseded pair, direct-replay
audit row). Scratch worktree removed.

## Gates (raw)

Agent run (slice tip): combined battery `115 passed`; `tests/test_controller.py` `109 passed`;
full suite `4675 passed, 3 skipped` (4678 collect, exit 0); stamp OK 4678; census PASS; B4 24/24;
ruff pass; pyright src 0/0/0; pyright tests 0 errors + 1 pre-existing warning.

Director landing re-derivation (live on the FF tip): stamp `--check` OK **4678**; census PASS;
B4 `24 passed`; battery (`test_chg_dedup_tick_skip` + `test_chg1_contradictions`) `63 passed`;
ruff `All checks passed!`; NOT-list scan (range diff) **0 hits**.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `2b0228d` |
| dirty main-bound worktree | **PASS** — clean pre-FF and post-FF |
| `--check` drift | **PASS** — 4678 (4669 + 9) |
| census / B4 drift | **PASS** — unchanged (no new SQL/transaction; read-only helper) |
| HR8-1 / chg1 / replay-duplicate pins | **PASS** — all green |
| push without a human hash-pin | **none performed** |

## Bundled push plan (drafted, NOT executed)

One human D9 pin covers the single final tree (this landing + CX-OVERLAP-1 + CRES-DIGEST-1 +
RESOLVER-PARITY-1 + all merge logs): origin fast-forward `2b0228d → <final tip>`; public mirror
orphan-sync with tree = `<final tip>^{tree}`, parent = live mirror HEAD, exact-hash push, no force
(rule #5).

## Prohibited-claims discipline

This gate certifies a controller-side submission-skip with pinned journal-growth semantics. It
makes no validity, reproducibility, or admissibility claim.

License: Apache-2.0 (LICENSE).
