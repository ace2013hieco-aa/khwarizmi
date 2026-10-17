# MERGE-LOG-RETRACT-1 — the decision-bound retraction (P0-3)

## Provenance

| Item | Value |
| --- | --- |
| Task | RETRACT-1-MERGE (merge gate; the origin fast-forward was pushed under the human's explicit D9 hash-pin; this log commit and the mirror sync are drafted, NOT pushed) |
| Base (`main` before) | `51cb10b59dd60a27bf3d38adc95676a8f62b627a` |
| Slice | `slice/retract-1-binding@9fe7d5fc5c9c4f763faa3c5fd664444439fbd56a` |
| Slice commits | `b002db1` (payload binding + canonicalised fixtures + 6 pins) + `9fe7d5f` (restamp 4655 → 4661) |
| Landed tip (FF'd to) | `9fe7d5f` — tree `558e385d99214fce4fee3c418edf8c866c803c47` |
| Gate worktree (gates re-run live) | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/retract-1-wt` |
| Merge worktree (FF + this log) | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` |
| Merge method | **fast-forward** — `git merge --ff-only` in the main-bound house worktree (exit 0) |
| FF evidence | `merge-base(main, 9fe7d5f)` == `main` (`51cb10b`); the chain is single-parent end-to-end (`b002db1` parent `51cb10b`, `9fe7d5f` parent `b002db1`) — **no merge commit** |
| Rebase / merge commit / force | **none** — FF only, linear single-parent chain (D1 respected: no rebase) |
| Origin push (leg 1) | `51cb10b..9fe7d5f  main -> main` under the human D9 pin; re-verified live: `origin/main` == `9fe7d5f` |

## Scope

11 files, **+265/−54**. Production diff is **one** file — `src/hermes/research/gateway.py`; everything
else is fixture canonicalisation, the pins, and the stamp:

```
docs/SUITE-COUNT.md                   |   6 +-   (restamp 4655 -> 4661)
src/hermes/research/gateway.py        |  63 ++   (decision binding in _validate_retract_source)
tests/test_b3_producer_ref.py         |   6 +-   (fixture canonicalisation)
tests/test_chg1_contradictions.py     |  13 +-
tests/test_n9_retraction_admission.py |   8 +-
tests/test_p6_classification.py       |  13 +-
tests/test_s1_detector_rows.py        |   7 +-
tests/test_s5_l2_resolution.py        |  11 +-
tests/test_s5_retraction.py           | 136 ++-  (bound helper + 6 pins: TestDecisionBinding)
tests/test_s6_event_capacity.py       |  15 +-
tests/test_step7_curated_registry.py  |  41 +-
```

`_validate_retract_source` now SELECTs the decision's `payload_json` (deterministic `ORDER BY rowid`)
and requires the recorded `HumanDecisionReceived` payload to **BIND this exact command** — decision
kind `RETRACT_SOURCE`, the same `source_ref`, and `reason_digest == sha256(reason)`. Corrupt or
non-dict payloads and every mismatch refuse `PROPOSAL` — the certified "recorded decision does not
ratify this command" code already used by the sibling classification/contradiction/curation
validators, so no code vocabulary changed. Every refusal happens **before** `_s5_source_artifact_id`
and before the cascade transaction: a refused binding writes nothing. Existence is not authority: a
decision recorded for another intent (e.g. a classification verdict) or another source/reason never
authorizes a retraction. Matching decisions behave identically (the untouched S6a producer path
re-ran green 20/20 during the slice). Fixture canonicalisation changed payloads only, no assertion.
Stamp delta is self-consistent: base `Collected: 4655` → landed `Collected: 4661` = **+6** = the six
new binding pins (`tests/test_s5_retraction.py` collects 43, was 37).

No other `src/` file is touched; no transaction owners were added — census re-derived live below
(121 calls / 27 owners 18-5-4 / 1 rollback / 15 imports, unchanged). The single mutation path
(`apply_intent`) is otherwise untouched.

## HARD RULE — audit duty (carried, not adjudicated)

No FAIL audit exists on the landing range `51cb10b..9fe7d5f`. The input document is
`AUDIT-GAP-1-TRIAGE.md` (`audit/gap-1-triage@1a812f0`), which adjudicated **P0-3 VALID** on the
pre-slice tree — an input triage, not a FAIL verdict on the slice. The slice record is `b002db1`'s
commit message and the `AUDIT-GAP-1-TRIAGE.md` P0-3 section.

Per the HARD RULE this gate does not adjudicate any audit. It re-derives the load-bearing claims
live on the landed tip:

| Claim (slice record) | This gate's re-derivation |
| --- | --- |
| Pre-fix: a classification verdict authorized a retraction | carried (reproduced in the triage; re-reproduced by the slice on base) |
| Post-fix: every mismatch refuses `PROPOSAL`, no writes | re-derived live: `TestDecisionBinding` **6/6** (classification / kind / source / digest / unbound refusals + bound positive control) |
| Matching decisions behave identically | re-derived live: `test_n9_retraction_admission.py` **21 passed**; the full suite below includes the untouched S6a producer path |
| Full suite green | re-derived live: **4658 passed, 3 skipped, 0 failed** (red set empty) |
| Stamp 4661 self-consistent | re-derived live: `--check` OK |
| Census unchanged (no new transaction owner) | re-derived live: PASS (121/27/1/15) |
| B4 byte-identical | re-derived live: **24 passed**; `git diff 51cb10b..9fe7d5f -- docs/gr3-b4/` empty |
| ruff + pyrights at the 0-error standard | re-derived live: ruff pass; pyright src 0/0/0; pyright tests 0 errors + 1 pre-existing warning |

Carried disclosure (from the slice record): `scripts/adversarial_probe_s5.py` retains a bare
(unbound) decision payload — ad-hoc, explicitly not collected, path-pinned to the shared checkout.
Flagged, not edited; it is not part of the collected suite and not an authority anywhere.

**No OTHER FAIL audit exists on the range.** The GAP-2 triage (`audit/gap-2-triage@ab9ff74`) covers
different items and does not touch this range. **HARD RULE satisfied — no unadjudicated FAIL audit;
not a STOP.**

## Gates (raw, on the landed tip `9fe7d5f`, `PYTHONPATH=<wt>/src`, no extra `-q`)

Interpreter for every gate below:
`D:/New folder/research-agent/.venv/Scripts/python.exe` (**Test-Path: True**; Python 3.14.1). The
gate worktree `retract-1-wt` was clean at `9fe7d5f` when the gates ran.

- **Collect** — via the stamp's own live collect: 4661.
- **Stamp `--check`** (`scripts/stamp_suite_count.py --check`) →
  `OK: docs\SUITE-COUNT.md collected=4661 matches the live collect` (exit 0). Note: the first attempt
  with the 8.3 short path (`ALIZOG~1`) was refused by the script's own PYTHONPATH guard — the guard
  works; the full-path re-run is the recorded result.
- **Census** (`scripts/check_census.py`) → `PASS - every certified figure is reproduced exactly.`
  (exit 0; 121 calls / 27 owners 18-5-4 / 1 rollback / 15 imports).
- **Ruff** (`uvx ruff check src tests`) → `All checks passed!` (exit 0).
- **Pyright src** (`uvx pyright --pythonpath "<repo-venv>" src`) →
  `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests-config** (`uvx pyright --pythonpath "<repo-venv>" --project pyrightconfig.tests.json`)
  → `0 errors, 1 warning, 0 informations` (exit 0), the only warning being the pre-existing
  `tests/test_research_program.py:144:23 reportSelfClsParameterName` (not in the range diff).
- **B4** (`pytest tests/test_b4_ref_graphs.py`) → `24 passed` = **24/24**; fixtures byte-identical
  (`git diff 51cb10b..9fe7d5f -- docs/gr3-b4/` empty).
- **Decision binding** (`pytest tests/test_s5_retraction.py -k DecisionBinding`) → `6 passed` = 6/6.
- **N9 admission** (`pytest tests/test_n9_retraction_admission.py`) → `21 passed` = 21/21.
- **Full suite** (`scripts/run_tests.py -v`, **alone on an idle machine**) →
  `4658 passed, 3 skipped in 508.66s (0:08:28)`; pass + skip = 4658 + 3 = **4661** == collect.

## Red set: EMPTY (subset of the baseline-5, delta ≤ 0)

`0 failed` — none of the documented baseline-5 flakes fired (the four readonly-DB concurrency races
and the Windows symlink refusal all passed this run; they are flaky by nature, unchanged baseline).
The documented `eval_plane` timing flake did not fire, so no isolation proof was required. The
suite ran alone; no static gate ran concurrently.

## NOT-list scan: PASS (no functional coupling)

Binding rule: the four terms bar DOING WORK in those domains; clearance prose asserting absence is
NOT a hit; only functional coupling stops the gate. The canonical four: `backtest_audit`, `SDA`,
`TSE`, `Optimize-my-strategy`.

- Range diff (`git diff 51cb10b..9fe7d5f`), case-insensitive → **0 hits**.
- Whole landed tree (`git grep -inE 'backtest_audit|optimize-my-strategy|\bSDA\b|\bTSE\b' 9fe7d5f -- src tests config`) → **0 hits**.
- Commit subjects + bodies over the range → **0 hits**.

**No hit = no functional coupling. Scan PASSES; no STOP.**

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 in diff, tree, commit bodies |
| `main` moved before the FF | **PASS** — local `main` unmoved at `51cb10b`, `origin/main` verified `9fe7d5f` (the pinned push) immediately pre-FF; `--ff-only` exit 0 |
| FF-ability | **PASS** — `merge-base(main, 9fe7d5f)` == `main`; single-parent chain end-to-end; no merge commit; rebase prohibited (D1) and not used |
| dirty main-bound worktree / concurrent merge gate | **PASS** — exactly one main-bound worktree (`met-1-merge-wt`), clean at `51cb10b` pre-FF; no other merge gate in flight |
| red set superset of baseline-5 | **PASS** — empty, a subset; `eval_plane` did not fire |
| `--check` drift | **PASS** — collected 4661 == stamp |
| FAIL audit on the landing range | **PASS** — none exists; the input triage is not a FAIL verdict |
| stale main-bound worktree left behind | **PASS** — house worktree clean, bound to `main` at the final tip |
| push without a human hash-pin | origin leg 1 executed **under** the human D9 pin (`I verify`); this log commit and the mirror sync **not pushed** — pins pending |

## Worktree hygiene

- **House main-bound worktree** (`C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt`):
  bound to `main@51cb10b`, clean → FF'd **in place** to `9fe7d5f` → then FF'd in place again to this
  log commit; ends bound to `main` at the final tip, clean.
- **`retract-1-wt`** (the gate re-runs ran here): clean at `9fe7d5f`.
- `slice/retract-1-binding` and the triage branches left as found. The shared checkout, `.hermes/`,
  and other worktrees were not touched. The slice's transient edit of the shared checkout's
  `gateway.py` (relative path) was reverted before landing; the shared checkout holds **zero tracked
  modifications** at gate time (verified). The known stale `step-4` worktree record was pruned by the
  operator; `git fetch` no longer errors.

## Dual push plans — drafted, NOT executed (D8/D9)

No push was performed by this gate. Both plans require a human hash-pin.

1. **`origin` plain-push** (`https://github.com/ace2013hieco-aa/khwarizmi-research`): push **this log
   commit**:refs/heads/main, single refspec, no force, no tags, after re-verifying live `origin/main`
   == `9fe7d5f` (strict ancestor). (The slice FF push `51cb10b..9fe7d5f` already executed under the
   earlier pin.)
2. **public mirror orphan-sync** (`https://github.com/ace2013hieco-aa/khwarizmi`): build a sync commit
   whose tree is **this log commit's tree** and whose parent is the live mirror HEAD `f446b5a` (the
   orphan convention — `merge-base` must be empty), re-read the live mirror pin first, push
   exact-hash with **no force** (rule #5).

## Prohibited-claims discipline

This gate certifies a merge (one validator's additive refusal — decision kind + source_ref +
reason_digest binding — plus the fixtures and pins that claim to cover it). It makes no claim about
the validity of any content, no reproducibility claim, and no admissibility claim for any source.
The "fail-closed" legs are statements about the gateway's own refusal behavior, never about the
truth of anything observed.

License: Apache-2.0 (LICENSE).
