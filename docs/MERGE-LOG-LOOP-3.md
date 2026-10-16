# MERGE-LOG-LOOP-3 — review-verdict consumption + bounded re-draft rounds

## Provenance

| Item | Value |
| --- | --- |
| Task | LOOP-3-MERGE (merge gate only — no push) |
| Base (`main` before) | `a76dd735eb0a320175051ca7a039173df833555e` |
| Slice (FF'd to) | `32e82a3fc9e1e2c4b8e890eb27b757c91b4a686a` |
| Slice commits | `06cf787` (consume the review verdict + re-drive drafting in bounded rounds) + `8442b1e` (12 pins) + `32e82a3` (restamp 4630 -> 4642) |
| Branch | `slice/loop-3-review` |
| Merge worktree (gate runs + this log) | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/loop-3-merge-wt` |
| Merge method | **fast-forward** — `git merge --ff-only` in the main-bound house worktree |
| FF evidence | `merge-base(main, slice)` == `main` (`a76dd73`); `main..slice` = 3, `slice..main` = 0; landed tip is single-parent (`32e82a3` parent `8442b1e`) — **no merge commit** |
| Rebase / merge commit / force | **none** — FF only, linear single-parent chain |
| Audit of record | `a92e91f` — `AUDIT-LOOP-3-REDTEAM.md`, verdict **PASS 0 MUST-FIX / 0 SHOULD-FIX / 2 Observations (O1-O2)** |

## Scope

5 files, +796/-67, **spine diff 0** (`git diff a76dd73..32e82a3 -- src/hermes/research/gateway.py
src/hermes/controller.py src/hermes/persistence/ src/hermes/events.py src/hermes/intents.py` is
empty — 0 lines):

```
docs/SUITE-COUNT.md                   |   6 +-    (restamp 4630 -> 4642)
src/hermes/agents/runtime/assembly.py |  48 ++++  (REVIEW_ORIGIN-marked verdict envelopes)
src/hermes/agents/runtime/run.py      | 260 ++-  (consume the verdict; two round bounds)
src/hermes/agents/runtime/types.py    |  78 ++-  (ReviewVerdict + evidence_digest)
tests/test_loop3_review_rounds.py     | 471 ++   (new, 12 tests)
```

The slice makes the review verdict **consequential without making it authoritative**: a review
child's own proposal set is derived into a `ReviewVerdict` (`passed` = raised-nothing,
`objections` = draft digests, `detail` = reviewer free text verbatim), retained on the run, rendered
as `REVIEW_ORIGIN`-marked data envelopes composed *after* the context port, and carried into the
next round. A failing verdict re-drives drafting inside exactly two bounds: the declared
`max_review_rounds` cap and verdict-evidence stability. The default cap is 1, so undeclared profiles
behave exactly as before (single-round equivalence re-proved byte-identical digests on both trees).
No file outside `src/hermes/agents/runtime/` is touched: the single mutation path (`apply_intent`,
`gateway.py`), the journal writers, persistence, and the research layers are untouched.

Stamp delta is self-consistent: base `Collected: 4630` -> landed `Collected: 4642` = **+12** = the new
battery (`tests/test_loop3_review_rounds.py` collects exactly 12). Per-commit: feat/test commits hold
4630 (code+tests, no stamp edit), the restamp moves 4630 -> 4642.

## HARD RULE — audit duty (carried, not adjudicated)

A PASS audit already exists on this exact range (`a92e91f`, AUDIT-LOOP-3-REDTEAM, on
`audit/loop-3-redteam`, cut from `main@a76dd73`). Per the HARD RULE this gate does not re-adjudicate
it; it is carried and independently spot-confirmed:

| Audit claim | This gate's re-derivation |
| --- | --- |
| Verdict PASS 0/0/2 (O1-O2) | carried as recorded |
| Authority **23/23** recording + **15/15** spine | carried; the authority legs are the shape the landed `12/12` battery + `11/11` probe re-run below exercise |
| Termination **15/15** (cap-5 exact, stability-trip at 2, default-cap-1 equivalence 7/7 both trees) | carried; pinned by the landed battery |
| Semantics **14/14**, Checkpoint **24/24** | carried verbatim |
| Spine diff 0 | re-derived live: empty (0 lines) |
| Stamp 4630 -> 4642 (+12) | re-derived live: `--check` OK 4642, pin count 12 |

### The 2 Observations (carried, no fix required)

- **O1 — verdict semantics are structural, not semantic:** a critic raising non-objection content
  fails the round (`passed = not objections`). Bounded by the cap, inert of authority (the spine
  still gates every draft), text carried verbatim. Pinned by the battery; no action demanded.
- **O2 — the round index is process-local:** a crash after a consumed verdict resumes *informed*
  (the verdict envelope is present) but never re-reviews the resumed round. The verdict survives
  durably; the round does not. S1 replays faithfully digest-equal; S2/S3 diverge honestly; the
  corrupt path is still loud. No authority or termination consequence; no action demanded.

## Authority-BLOCKED record (carried from `a92e91f`)

A review verdict can never approve/record/resolve/gate-override anything durable. The verdict type is
data-only by construction; the derivation never authors authority; the carry is `REVIEW_ORIGIN`-marked
data composed after the port; the close act re-drives drafting only — it never approves, records, or
resolves. Under full adversarial drive the boundary held — **23/23 recording legs + 15/15 spine legs**:

- **Exhausted rounds** end verdict-recorded + drafts unapproved: exactly 1 failing verdict on the run
  report AND the durable terminal checkpoint; the applier saw only `['ABANDON', 'INSERT_TASK']` —
  zero `RESOLVE_CLASSIFICATION_PROPOSAL` / `PROPOSE_GATE_OVERRIDE` / `RETRACT_SOURCE` /
  `RECORD_SCOPE_REVIEW_DECISION` / `CURATE_KNOWLEDGE`.
- **Reviewer drafts never enter the parent set:** one child emitting 2 drafts -> verdict carries
  exactly 2 objections; objection digests ∩ parent digests = ∅.
- **A PASS verdict does not bypass the human gate** — both fake-applier and real-`apply_intent` legs
  park at `PENDING_HUMAN_APPROVAL` with zero resolutions.
- **Hostile review text is inert** against an instruction-following stub: hostile bytes reach the next
  round in exactly 1 review-origin envelope; internal-only demands are refused as data at the
  authority boundary (never became proposals); the LLM-proposable demand reaches the spine exactly
  once as an ordinary proposal, where the spine itself refuses what is declared-but-unwired.

## Termination proofs (carried from `a92e91f`)

Two bounds, never one: the round cap (`_review_rounds`; unreviewed -> 1, else `max(1,
max_review_rounds)`) and evidence stability (verdict content digest unseen -> continue; seen -> stop).
`max_review_rounds` default 1.

| Scenario | Constructed run | Result |
|---|---|---|
| cap enforced at exactly `max_review_rounds` (cap 5, fresh objections) | 5 distinct objections | critic ran exactly 5×, all rounds failed, 5 distinct digests — the cap alone stopped the loop; the 6th scripted objection never consumed; run terminal |
| evidence-stability trip terminates recurring verdicts | same verdict ×5 under cap 5 | critic ran exactly 2×, 2 verdicts share one content identity — the stability trip fired; run terminal |
| default cap 1 preserves pre-LOOP-3 behavior | undeclared cap | parses to exactly 1; passing review -> critic 1×, lead drafted once, `SUCCEEDED/STOP_WHEN` |

Single-round equivalence: slice digest `5917bcbff66da5ba18949020fdf5269cfc09c9b183aef5e2ce4d550c29c58559`
== main digest `5917bcbff66da5ba18949020fdf5269cfc09c9b183aef5e2ce4d550c29c58559` (same proposals,
same `['INSERT_TASK']` applier traffic; the only delta is the inert recorded verdict vs absent).
**15/15 + 7/7 equivalence.**

## Gates (raw, on the landed tip `32e82a3`, `PYTHONPATH=<wt>/src`, no extra `-q`)

Interpreter for every gate below:
`C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/loop-3-merge-wt/.venv/Scripts/python.exe`
(a directory junction to the repo venv; **Test-Path: True** for both the repo venv
`D:/New folder/research-agent/.venv/Scripts/python.exe` and the junction, identical SHA-256
`22D89D728C105376D48ECD425EBA826C05F713A9962805B9B39924664A203076`; Python 3.14.1).

- **Collect** (`scripts/run_tests.py --collect-only`) -> `4642 tests collected in 6.44s` (== 4642).
- **Stamp `--check`** (`scripts/stamp_suite_count.py --check`) ->
  `OK: docs\SUITE-COUNT.md collected=4642 matches the live collect` (exit 0).
- **Census** (`scripts/check_census.py`) -> `PASS - every certified figure is reproduced exactly.`
  (exit 0; 121 control calls; owners 27 = 18+5+4; 1 rollback-only; 15 persistence->research imports;
  0 control calls outside certified layers).
- **Ruff** (`python -m ruff check src tests`) -> `All checks passed!` (exit 0).
- **Pyright src** (`python -m pyright src --pythonpath "<wt>/.venv/Scripts/python.exe"`) ->
  `0 errors, 0 warnings, 0 informations` (exit 0).
- **Pyright tests-config** (`python -m pyright --pythonpath "<wt>/.venv/Scripts/python.exe"
  --project pyrightconfig.tests.json`) -> `0 errors, 1 warning, 0 informations` (exit 0), the only
  warning being the pre-existing `tests/test_research_program.py:144:23 reportSelfClsParameterName`
  (that file is not in the slice diff). The repo-venv junction makes the venv discoverable to
  pyright, so the `--pythonpath` recording alone reaches the **0-error** standard.
- **B4** (`pytest tests/test_b4_ref_graphs.py`) -> `24 passed in 3.88s` = **24/24**.
- **Review battery** (`pytest tests/test_loop3_review_rounds.py`) -> `12 passed in 0.37s` = **12/12**.
- **Probe + assembly** (`pytest tests/test_loop0_e1_probe.py tests/test_loop1_context_assembly.py`)
  -> `11 passed in 0.45s` (**11/11**).
- **Feedback battery** (`pytest tests/test_loop2_feedback.py`) -> `20 passed in 0.47s` (**20/20**).
- **Full suite** (`scripts/run_tests.py tests --tb=short -rf`, **idle machine**) ->
  `5 failed, 4634 passed, 3 skipped, 1 warning in 592.76s (0:09:52)`.
  Pass + skip + failed = 4634 + 3 + 5 = **4642** == collect.

## Red set: EXACTLY baseline-5 (not a superset)

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

Environmental races (readonly-DB concurrency ×4) / Windows symlink privilege ×1 — flaky by nature,
unchanged from the documented baseline. **Delta = 0.** The documented `eval_plane` timing flake
(`tests/test_eval_plane.py::TestMatrixRunner::test_matrix_runner_runs_clean_against_the_frozen_tree`)
**did not fire** (0 occurrences in the log), so no isolation proof was required. The suite was run
**alone on an idle machine** — no static gate ran concurrently (lesson carried from
`MERGE-AUDIT-P-AUTO-1-RETRY`).

## NOT-list scan: PASS (no functional coupling)

Binding rule: the four terms bar DOING WORK in those domains; clearance prose asserting absence is
NOT a hit; only functional coupling stops the gate. The canonical four:
`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy` (external engines, per `docs/ARCHITECTURE.md`).

- Range diff (`git diff a76dd73..32e82a3`), word-boundary, case-insensitive -> **0 hits**.
- Whole landed tree (`git grep -inE "backtest_audit|optimize-my-strategy|\bSDA\b|\bTSE\b" 32e82a3 -- src tests config`)
  -> **0 hits**.
- Commit subjects + bodies over the range -> **0 hits**.
- Slice changed files content (`git diff a76dd73 32e82a3 -- src tests`) -> **0 hits**.

**No hit = no functional coupling. Scan PASSES; no STOP.**

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits, range + tree + commit bodies + changed files |
| `main` moved before the FF | **PASS** — re-verified unmoved at `a76dd73` (local == `origin/main`) immediately pre-FF |
| FF-ability | **PASS** — `merge-base(main, slice)` == `main`; `--ff-only` used, exit 0; `slice..main` = 0; no merge commit |
| dirty main-bound worktree | **PASS** — house worktree clean pre-FF and FF'd in place; clean post-FF |
| red set superset of baseline-5 | **PASS** — exactly the 5, delta 0 |
| `--check` drift | **PASS** — collected 4642 == stamp |
| FAIL audit on the landing range | **PASS** — none; `a92e91f` is PASS 0/0/2 |
| stale main-bound worktree left behind | **PASS** — house worktree clean at the final tip |
| push without a human hash-pin | **none performed** |

## Worktree hygiene

- **House main-bound worktree** (`C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt`,
  the arrangement carried from prior gates): bound to `main@a76dd73` and clean -> FF'd **in place**
  to `32e82a3` (the slice landing) -> then FF'd in place again to this log commit -> ends bound to
  `main` at the final tip, clean.
- **`loop-3-merge-wt`** (this gate's worktree): detached at the landed tip `32e82a3`; every gate ran
  here; this log was authored and committed here, then FF'd onto `main`.
- `slice/loop-3-review` worktree (`loop-3-wt`) and `audit/loop-3-redteam` worktree
  (`loop-3-audit-wt`) left as found. The shared checkout, `.hermes/`, `or*.json`, and other
  worktrees were not touched. (The FF logged a harmless
  `failed to delete .../worktrees/step-4: Permission denied` — the known stale-prune step; ignored,
  FF exit 0.)

## Dual push plans — drafted, NOT executed (D8/D9)

No push was performed by this gate. Both plans require a human hash-pin.

1. **`origin` plain-push** (`https://github.com/ace2013hieco-aa/khwarizmi-research`):
   push `<merge-gate-tip>:refs/heads/main`, single refspec, no force, no tags, after
   re-verifying live `origin/main` is a strict ancestor of the tip (FF).
2. **public mirror orphan-sync** (`https://github.com/ace2013hieco-aa/khwarizmi`):
   add a temp remote, `fetch --no-tags`, re-read the live mirror pin, build a sync commit
   whose tree is `<tip>^{tree}` and whose parent is the mirror HEAD (orphan convention —
   `merge-base` must be empty), push exact-hash with **no force** (rule #5), then remove
   the temp remote.

Neither plan is executed here. **No push without a human hash-pin.**

License: Apache-2.0 (LICENSE).
