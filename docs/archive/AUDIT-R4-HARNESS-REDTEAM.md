# AUDIT-R4-HARNESS-REDTEAM — tests-only promotion review + default-OFF proof

- **Target**: diff `a8f0180...2758515` = `2758515e10eae03b6a844cc80fc869468e0fc75f`
  "test(autonomy): commit the opt-in fault registry behind HERMES_FAULT_KILL" —
  **4 new test files, +384/−0, zero `src/`** (`tests/fault_injection/__init__.py` +11,
  `tests/fault_injection/kills.py` +192, `tests/fault_injection/plugin.py` +40,
  `tests/test_r4_fault_harness.py` +141). Subject sits directly on main
  (`--is-ancestor a8f0180 2758515` TRUE; branch `slice/fault-harness`).
- **Base**: local `main` tip **`a8f018068e3c04b3160891ebd56cfd95d3590c95`**
  (recorded; note `origin/main` = `e4b276d7880cb8c0e17e1239e03c589138541ae` differs —
  local-only lineage used, no fetch performed).
- **Method replaced**: P-AUTO-6 temp-only red legs (`%TEMP%/p6` `red_quarantine.py`
  no-op `observe_failure`, `red_deadline.py` null `_dispatch_deadline`) plus the
  P-AUTO-6 audit's independent rebuilds (`rq.py` `build_loop_threshold→10**9`,
  `rd.py` `_deadline_expired→False`), per `AUDIT-P-AUTO-6-REDTEAM.md` F1.
- **NOT-topics**: `backtest_audit` / `SDA` / `TSE` / `Optimize-my-strategy` —
  **0 hits** in the diff (word-boundary regex; the only raw substring hit was
  "it**self**" ≙ `tse`, rejected).
- **Branch**: `audit/r4-harness` (from `main`, LOCAL-ONLY, NO PUSH), isolated
  worktree `C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\r4-harness-wt`;
  audited files materialized read-only (`git checkout 2758515 -- tests/...`),
  never committed on this branch.
- **Host**: Windows, Python 3.14.1, pytest 9.1.1, ruff 0.16.10, `PYTHONPATH=<wt>/src`.

## Verdict: **FAIL — 1 MUST-FIX, 2 SHOULD-FIX, 4 NOTE**

The mechanism is sound (default-OFF double-fenced and re-derived below; registry
closed; per-kill red legs reproduce the P-AUTO-6 audit's exact failure sets), but
**two of the diff's own three documented run commands silently do nothing** —
executed literally they exit 0 all-green while the docstring promises reddening
(M1). That is the false-green failure class R-4 exists to catch.

| Section | Adjudication |
|---|---|
| A — default-OFF proof re-derived | **PASS** — unset full suite 3699 green (exit 0); `=all`+`-p` full suite reddens exactly the 4 claim legs (4 failed / 3695 passed, exit 1); bare `=all` without `-p` inert (no leakage either way) |
| B — registry closure + envelope coverage | **PASS for declared scope** + NOTE N2 — unknown names refuse before any test; 4/4 P-AUTO-6 claim envelopes killable; 12 of the 15 ratified P-AUTO-4/6 envelopes have no seam (declared in `kills.py:5-10`) |
| C — `-p` vs conftest deviation | **PASS (sound)** + M1/N1/N3 — no collection-order dependence found; deviation is deliberate and double-fences default-OFF; cost is per-invocation arming (false-green docs) |
| D — kill-seam drift | **MIXED → M1/S1/S2** — attribute rename LOUD; line drift SILENT; call-site/namespace drift SILENT + armed run exits 0 (unkilleable, unprovable without expected-count check) |

## A — default-OFF proof (re-derived on my own runs) — PASS

Full suite, both ways, isolated worktree, same interpreter:

```
$ $env:PYTHONPATH=<wt>/src; (HERMES_FAULT_KILL unset); python -m pytest tests -p no:cacheprovider
EXIT=0
3699 passed, 12 warnings in 757.65s (0:12:37)          # zero FAILED lines (grep count 0)

$ $env:HERMES_FAULT_KILL="all"; python -m pytest -p tests.fault_injection.plugin tests -p no:cacheprovider
EXIT=1
FAILED tests/test_p_auto_6_loop.py::test_poison_task_quarantined_never_retried_silently
FAILED tests/test_p_auto_6_loop.py::test_loop_pattern_trips_detector_at_threshold_and_quarantines
FAILED tests/test_p_auto_6_loop.py::test_hung_fetch_deadline_fires_typed_transient_no_hang
FAILED tests/test_p_auto_6_loop.py::test_recovery_after_quarantine_legit_work_proceeds_and_idle_is_named
4 failed, 3695 passed, 12 warnings in 594.40s (0:09:54) # FAILED lines = 4, all in claim file;
                                                        # r4-guard failures inside =all run = 0
```

- **Exactly the 4 claims redden**: the FAILED set equals `QUARANTINE_RED_LEGS`
  (3, `kills.py:41-45`) + `DEADLINE_RED_LEGS` (1, `kills.py:46-48`); 4 + 3695 =
  3699 = the unset count, so nothing outside the claim file was touched.
- **Double-fenced OFF**: the plugin is not loaded without `-p` (session header
  lists only `Faker, cov`), and `apply()` additionally refuses without the env
  opt-in (`FAULT_KILL_NOT_ENABLED`, `kills.py:142-159`). Control run, flag set,
  no `-p`, claim file: `6 passed, EXIT=0` → a leaked `HERMES_FAULT_KILL` cannot
  arm a plain suite.
- **13 guards, both ways**: unset → `13 passed in 0.79s` (exit 0), including
  `kills._PATCH is None` (`test_r4_fault_harness.py:51`); armed (`=all`+`-p`)
  → `13 passed in 0.20s` (exit 0) — the battery is flag-independent (guards
  self-manage the flag via `flag_off`, `:37-43`, and are outside `CLAIM` scoping).

## B — registry closure + seam coverage vs P-AUTO-4/6 — PASS (declared scope) + N2

Closure probes (all mine):

| Probe | Result |
|---|---|
| `HERMES_FAULT_KILL=bogus` + `-p` on `pytest tests` | `ValueError: UNKNOWN_FAULT_KILL: ['bogus'] ... known kills: ['deadline','loop_threshold','quarantine']` raised in `plugin.py:30 pytest_configure` → **exit 3, 0 tests collected/run** (refuses before a single test) |
| `HERMES_FAULT_KILL=all,quarantine` | refuses too (`'all'` is not a kill name outside the exact `["all"]` list) — exit 3, no silent "treat as all" |
| `HERMES_FAULT_KILL="  "` (blank) | inert, `6 passed`, exit 0 (`selected()` empty, `kills.py:129-140`) |
| parsing/case/pin guards | `test_selection_parsing` (`:74`), `test_registry_is_closed_and_pinned` (`:83-92`: `known()==('deadline','loop_threshold','quarantine')`, `claim_file==CLAIM`, every `red_leg` starts with `CLAIM + "::"`) — green |

Seam coverage vs the **P-AUTO-6 claim envelope** (the F1 scope): **4/4 complete**.
Per-kill runs reproduce the P-AUTO-6 audit's original red legs exactly:

```
HERMES_FAULT_KILL=quarantine + -p → 3 failed, 3 passed  (the same 3 quarantine legs)
HERMES_FAULT_KILL=deadline   + -p → 1 failed, 5 passed  (assert at test_p_auto_6_loop.py:549, contacted 1==0 —
                                                          same line the P-AUTO-6 audit's rd.py hit)
HERMES_FAULT_KILL=loop_threshold + -p → 3 failed, 3 passed (audit rq.py rebuild)
```

Seam targets verified against `src` today: `autonomy_caps.py:424
def observe_failure` ✓, `paginate.py:181 def _deadline_expired` ✓,
`controller.py:760 repeat_threshold=build_loop_threshold(...)` ✓ (call site; the
def lives at `autonomy_caps.py:743`, re-imported `controller.py:90` — the kill
patches the `controller` namespace binding, which is what `:760` reads).

**vs the full P-AUTO-4/6 ratified envelope list (MERGE-LOG-P-AUTO-4 D6 table): 3 of
15 have a registered seam** (`loop_repeat_threshold`, quarantine family, D1
dispatch-deadline check site). No seam exists for: per-task/tick/run **steps**
(3), per-task/tick/run **tokens** (3), **tick/run wall** (2), **retry backoff**,
**daily-cap hard stop**, **admission_wait_bound**, **provider rate limits**
(2) → **12 envelopes unkilleable** — plus all 33 claims in
`tests/test_p_auto_4_caps.py` / `test_p_auto_4_fix.py` are structurally
unreachable because `Kill.claim_file` is one string and `scoped()`
(`kills.py:162-165`) + the guard pin (`test_r4_fault_harness.py:91`) require
every red leg to live in `tests/test_p_auto_6_loop.py`. This is **declared
scope** (`kills.py:5-10`: "the same seams the P-AUTO-6 temp plugins used … the
same 3 + 1 failures"), and extension fails LOUDLY at the guard, not silently →
NOTE N2, not a MUST/SHOULD.

## C — conftest deviation soundness (explicit `-p` vs conftest hook) — PASS + M1/N1/N3

The deviation from F1's primary proposal (`tests/conftest.py` wiring,
`AUDIT-P-AUTO-6-REDTEAM.md:129`) to explicit `-p tests.fault_injection.plugin`
is deliberate and documented (`plugin.py:3-5`), and corroborated: the human's
main checkout carries an **uncommitted rewrite of `tests/conftest.py`** (the
committed version is a 5-line stub), i.e. exactly the "another change is
rewriting" conflict `plugin.py` cites.

**Collection-order dependence: none found.**

- Hook window is per-item (`pytest_runtest_setup`/`teardown`,
  `plugin.py:33-40`): patch applied at setup, undone at teardown, `_PATCH`
  cleared (`kills.py:169-192`). Red legs fire ⇒ patches precede fixture/test
  logic; a `-p`-registered plugin runs before the runner's `item.setup()`.
- In-session order: claim file (p…) collects before guards (r…); in the full
  `=all` run the 4 claim tests fail while **0 guard tests fail** (grep), and
  guards also pass standalone under `=all` (`13 passed`) — failure of one test
  does not leak `_PATCH` into the next (asserted `_PATCH is None` guard `:51`).
- Invocation order/cwd: scoping keys on the **rootdir-relative** nodeid.
  Verified `--collect-only` yields `tests/test_p_auto_6_loop.py: 6` both from
  the repo root and from `cwd=tests/`, and `=all`+`-p` reddens 4/6 from
  `cwd=tests/` as well (control without `-p` from the same cwd: 6 passed).
  Direct `scoped()` probe: prefix → True; no-prefix / other-file / guard-file →
  False.

Cost of the deviation (the reason it is not an unqualified PASS):

- **M1** below: arming is per-invocation, so every documented command must carry
  `-p`; two of three do not.
- **N1**: the unknown-name refusal only exists when the plugin is loaded, and it
  surfaces as `INTERNALERROR` (exit 3) rather than a clean `UsageError` — loud
  and before any test, but crash-shaped (and it suppresses the
  `PYTEST-SUMMARY` line of the in-flight conftest rewrite).
- **N3**: nodeid-prefix scoping assumes rootdir = repo root (the `pyproject.toml`
  inifile). A future `tests/pytest.ini` would move rootdir, drop the `tests/`
  prefix, and disarm kills **silently** (guards would stay green).

## D — kill-seam drift risk (src renames a seam: silent skip or loud failure?) — MIXED

Three mutation probes run on my own copy of the tree; each reverted
(`git status src` clean afterwards), no code committed.

| Probe (src mutation) | Default (unset) guard battery | Armed red-leg run | Verdict |
|---|---|---|---|
| **D1 rename**: `LoopDetector.observe_failure` → `observe_failure_renamed` (`autonomy_caps.py:424`) | **2 failed, 11 passed**, exit 1 — `AttributeError … has no attribute 'observe_failure'` at `kills.py:55` + direct-call guard | n/a | **LOUD** (attribute/module renames break `setattr`/import inside the guards, which run on every default run) |
| **D2 line drift**: +3 blank lines at top of `autonomy_caps.py` (def moves 424→427) | **13 passed**, exit 0 | n/a | **SILENT** — `SEAMS` (`test_r4_fault_harness.py:32-36`) vs `kills.py:91/99/107` are static strings compared to each other (`:83-92`), never to `src` |
| **D3 call-site drift**: `controller.py:760` rewired to read `autonomy_caps.build_loop_threshold` directly (controller-namespace name becomes unread) | **13 passed**, exit 0 (patch still "takes" — guard `:101-108` only asserts the attribute was replaced) | `HERMES_FAULT_KILL=loop_threshold`+`-p` on claim file: **6 passed, exit 0** (baseline 3 failed) | **SILENT + unkillable** — `apply()` returns success, red legs stop firing, and an armed run looks GREEN |

Residual: no gate anywhere runs `HERMES_FAULT_KILL` (repo grep: only the diff
files + the two historical P-AUTO-6 docs mention it), so D3-class drift is
detected only by a human who both arms the plugin **and** checks the expected
red count. D1-class drift IS caught today on the default suite; D2/D3 are not.

## Findings

### MUST-FIX (1)

- **M1 — two of the diff's documented commands are false-green.**
  `tests/fault_injection/kills.py:16-18` promises
  "``HERMES_FAULT_KILL=quarantine python -m pytest tests`` reddens exactly that
  file's envelope tests" and `tests/test_r4_fault_harness.py:12-13` says
  "``HERMES_FAULT_KILL=all pytest tests`` can only redden the claims" —
  **neither mentions `-p tests.fault_injection.plugin`** (`kills.py` never
  contains `-p` at all). Executed literally (env set, no `-p`): claim file
  `6 passed`, **exit 0** — while with `-p` the same command gives
  `3 failed, 3 passed`, exit 1. Only `plugin.py:5-15` documents `-p` correctly;
  the accepted repo record `AUDIT-P-AUTO-6-REDTEAM.md:130` ("expect 3 failed",
  no `-p`) is now also false. This defeats the slice's stated purpose (F1:
  red-to-green as operating contract, not oral tradition): an operator following
  the registry's own docstring gets a green run and concludes the envelopes are
  defended. **Minimal fix (docs-only):** add `-p tests.fault_injection.plugin`
  to both examples — or load the plugin from `addopts` in `pyproject.toml`
  (default-OFF is preserved: the env gate in `apply()` still fences every patch,
  and unknown-name refusal would then fire on every run).

### SHOULD-FIX (2)

- **S1 — nothing pins the expected red counts, so an unkilleable envelope exits 0.**
  D3 above: guards green + armed claim run `6 passed, exit 0`. The guard battery
  proves "the attribute was patched", not "the call site still reads it".
  Add a wrapper/meta-check asserting the documented counts per kill
  (quarantine → 3 failed, loop_threshold → 3 failed, deadline → 1 failed) so
  seam-liveness drift turns a would-be green armed run into a loud failure.
- **S2 — `SEAMS` line pins are static-vs-static and drift silently.**
  `test_r4_fault_harness.py:32-36` vs `kills.py:91/99/107` are checked only by
  substring containment (`:87`); D2 moved the real def 424→427 with all 13
  guards green. Resolve the line from `src` at test time (or assert symbol+file
  only) so a moved seam fails loudly instead of leaving stale documentation.

### NOTE (4)

- **N1** — refusal shape: unknown names raise bare `ValueError` from
  `plugin.py:30` → pytest `INTERNALERROR`, exit 3 (loud, 0 tests, correctly
  named) but crash-styled; a `pytest.UsageError` would fail closed with a clean
  usage message. Refusal also exists only when `-p` is passed (by design).
- **N2** — envelope scope: 3/15 ratified P-AUTO-4/6 envelopes have seams; the
  12 cap envelopes (D6 step/token/wall/retry/daily/admission/rate-limit) and all
  33 P-AUTO-4 claim tests are unreachable through the single `claim_file` pin.
  Scope is declared (`kills.py:5-10`) and extension trips the guard loudly —
  record the boundary in the R4 hand-off (or extend `Kill.claim_file` to a tuple
  when P-AUTO-4 wants kills).
- **N3** — scoping depends on rootdir-relative nodeids starting with
  `tests/` (`kills.py:38,162-165`); true today for root and `cwd=tests`
  invocations (verified), but a second inifile inside `tests/` would silently
  disarm kills while guards stay green. Consider matching the claim basename
  (`"/test_p_auto_6_loop.py::" in nodeid`) instead of a rootdir-relative prefix.
- **N4** — `_PATCH` global (`kills.py:169-192`): if a teardown is ever skipped
  (session interrupt), `begin()`'s `_PATCH is not None` early-return
  (`:180`) would silently skip kills for the remainder of the session.
  Theoretical; per-item teardown held in every run here.

## Raw gates (own runs, isolated worktree)

```
# 13 guards, unset (default suite)
$ python -m pytest tests/test_r4_fault_harness.py -v -p no:cacheprovider
collected 13 items
tests\test_r4_fault_harness.py .............                             [100%]
13 passed in 0.79s                                                       (exit 0)

# full suite, HERMES_FAULT_KILL unset
3699 passed, 12 warnings in 757.65s (0:12:37)                            (exit 0, 0 FAILED)

# full suite, HERMES_FAULT_KILL=all + -p tests.fault_injection.plugin
4 failed, 3695 passed, 12 warnings in 594.40s (0:09:54)                   (exit 1)
FAILED ...::test_poison_task_quarantined_never_retried_silently
FAILED ...::test_loop_pattern_trips_detector_at_threshold_and_quarantines
FAILED ...::test_hung_fetch_deadline_fires_typed_transient_no_hang
FAILED ...::test_recovery_after_quarantine_legit_work_proceeds_and_idle_is_named

# unknown name refuses before any test
$ HERMES_FAULT_KILL=bogus python -m pytest -p tests.fault_injection.plugin tests
INTERNALERROR> ValueError: UNKNOWN_FAULT_KILL: ['bogus'] are not in the closed
registry - known kills: ['deadline', 'loop_threshold', 'quarantine']      (exit 3, 0 tests)

# false-green control (M1): flag set, no -p
$ HERMES_FAULT_KILL=all python -m pytest tests/test_p_auto_6_loop.py
6 passed in 1.58s                                                         (exit 0)  <-- promised red

# per-kill red legs with -p
quarantine     → 3 failed, 3 passed  (exit 1)
deadline       → 1 failed, 5 passed  (exit 1)   # :549 contacted 1 == 0
loop_threshold → 3 failed, 3 passed  (exit 1)
guards under =all → 13 passed       (exit 0)

# drift probes (all reverted after)
D1 rename attr     → 2 failed, 11 passed (exit 1, AttributeError kills.py:55)
D2 +3 lines        → 13 passed (exit 0; pin 424 stale vs actual 427)
D3 call-site rewired → guards 13 passed (exit 0) AND armed claim run 6 passed (exit 0)

# lint gate
$ ruff check src tests         # ruff 0.16.10 from project venv
All checks passed!                                                    (exit 0)
```

## Limits

- Full suite run once per arm (both ways) on my own runs, as required; per-kill
  and probe runs are claim-file/guard-file scoped (1-2 s each).
- `pyright` not run (not in the R4 gate list; diff is test-only, ruff gate
  green). Offline: `uvx` avoided; pinned-equivalent tools taken from the
  project venv (pytest 9.1.1 matches prior gate records).
- src mutations were probe-only and reverted; this branch carries the audit doc
  alone (the audited diff stays on `slice/fault-harness@2758515`).
- No push, no fetch, no NOT-topic content; local `main` tip recorded above.
