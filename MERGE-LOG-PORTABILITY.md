# MERGE-LOG-PORTABILITY — replay of `fix/portability` onto remote main

**Task:** MERGE-PORTABILITY. **Role:** merge integrator (replay + verify). **D9 LAPSED — merge + audit only.**
**Verdict:** **REPLAY VERIFIED, PATCH-EXACT — 2 gates RED, both proven PRE-EXISTING with ZERO merge delta.**
STOP condition ("any gate red — STOP, report") triggered and adjudicated per in-repo precedent
(`docs/MERGE-LOG.md` @ `cbc95c3`, gr3-b4/step-4): **report the pre-existing red, do not fix, do not push.**
Nothing was pushed. `main` is unmoved.

## 1. Lineage

| Item | Value |
| --- | --- |
| Repo | `D:\New folder\research-agent` (GitHub `ace2013hieco-aa/khwarizmi-research`) |
| BASE — remote main (verified) | `f6939129eb8429934c57db206a11480dab691ddb` |
| Source fix | `fix/portability` @ `be0ddba036c1c0bde0fbf2deacbcb129d6f65c01` (off old base `d106874`) |
| Source audit | `audit/portability` @ `f8675362d64759bd35b5dfc96b693c59901d2db0` |
| Integration branch | `merge/portability` (off `f693912`) |
| Replayed commit | `0e725452286a882cff42da41ced18662caaa274c` (`cherry-pick -x be0ddba`) |
| Isolated worktree | `D:\New folder\merge-portability-wt` |
| Changed files | `scripts/run_tests.py`, `src/hermes/eval/hostile.py`, `src/hermes/eval/matrix.py` — 3 files, +36 / −5 |
| Pushed? | **NO** — `git ls-remote origin refs/heads/merge/portability` → 0 lines |

Originals untouched (verified after the replay): `be0ddba`, `f867536`, `fix/portability`
and `audit/portability` all still resolve to their original hashes.

**Local main note.** The task stated local `main` carries unpushed platform commits. Observed:
local `main` == `origin/main` == `f693912` (identical). `main` was not touched either way.

## 2. Replay and patch-exactness

Pre-flight: the three files are byte-identical between the old base `d106874` and the new base
`f693912`, so no conflict was possible —

```
$ git diff --stat d106874 f693912 -- scripts/run_tests.py src/hermes/eval/hostile.py src/hermes/eval/matrix.py
(empty)
```

The cherry-pick applied with **no conflicts** (no STOP on semantic conflict). Exactness re-proofs:

**(a) blob-level — replayed tree vs original fix tree, all three identical:**

```
IDENTICAL  scripts/run_tests.py        a424e3308c717ea4fab61fca240e1647b11c49d3
IDENTICAL  src/hermes/eval/hostile.py  e4c150b2cf6c797251e3f2a3fcab0270b9236e18
IDENTICAL  src/hermes/eval/matrix.py   543c1073a3f328774fbc1edf332f65d5dec7b44c
```

**(b) patch-level — original patch vs replayed patch, byte-for-byte identical:**

```
$ git diff d106874 be0ddba -- <3 files> > /tmp/patch_orig.diff
$ git diff f693912 0e72545 -- <3 files> > /tmp/patch_replay.diff
$ diff -q /tmp/patch_orig.diff /tmp/patch_replay.diff
PATCH-IDENTICAL (byte-for-byte)
$ sha256sum /tmp/patch_orig.diff /tmp/patch_replay.diff
3d6f4cff74c2375e59cb6ee3a19ad6c6548970c1da18cdef11de9a5a67d9d298  /tmp/patch_orig.diff
3d6f4cff74c2375e59cb6ee3a19ad6c6548970c1da18cdef11de9a5a67d9d298  /tmp/patch_replay.diff
```

## 3. Environment pinning (per constraint: absolute `--pythonpath`, `PYTHONPATH=<worktree>/src`)

The worktree has no `.venv` of its own. Reusing the main repo's venv would import the **wrong tree**,
because its editable `.pth` points at the main repo. Verified both directions:

```
WITHOUT PYTHONPATH -> D:\New folder\research-agent\src\hermes\__init__.py        <-- WRONG tree
WITH  PYTHONPATH   -> D:\New folder\merge-portability-wt\src\hermes\__init__.py  <-- correct
```

All gates below were run with `PYTHONPATH=D:/New folder/merge-portability-wt/src` and
`--pythonpath D:/New folder/research-agent/.venv/Scripts/python.exe` (absolute).
Interpreter: CPython 3.14.1. Toolchain: ruff 0.16.10, pyright 1.1.414.

## 4. Gates (raw outputs, with counts)

| # | Gate | Result |
| --- | --- | --- |
| 1 | `ruff check src tests` | **PASS — All checks passed!** (exit 0) |
| 2 | `ruff check <3 touched files>` | **PASS — All checks passed!** (exit 0) |
| 3 | `pyright --pythonpath <abs> src` | **PASS — 0 errors, 0 warnings, 0 informations** |
| 4 | `pyright --pythonpath <abs> --project pyrightconfig.tests.json` | **RED — 107 errors, 1 warning** (pre-existing, zero delta — §5) |
| 5 | `scripts/run_tests.py` (full suite) | **RED — 5 failed, 4349 passed, 3 skipped, 1 warning** in 556.76s (pre-existing, zero delta — §6) |
| 6 | Touched-file suites (`test_eval_plane`, `test_governance_plane`, `test_provider_ratelimit`) | **PASS — 436 passed** in 88.11s (exit 0) |

```
$ ruff check src tests
All checks passed!

$ pyright --pythonpath <abs> src
0 errors, 0 warnings, 0 informations

$ scripts/run_tests.py tests/test_eval_plane.py tests/test_governance_plane.py tests/test_provider_ratelimit.py
436 passed in 88.11s (0:01:28)
EXIT=0
```

Gate 6 reproduces the source commit's own claim ("touched-file suites … 436 passed exit 0") exactly,
now on the replayed tree.

## 5. Gate 4 red — pre-existing, zero merge delta

All 107 errors are the same diagnostic — `Import "pytest" could not be resolved (reportMissingImports)`
in `tests/`. Root cause is environmental: in this sandbox pyright cannot enumerate the interpreter's
site-packages. Evidence: the interpreter resolves pytest fine
(`pytest 9.1.1`, `origin=…\.venv\Lib\site-packages\pytest\__init__.py`), pyright reports no interpreter
diagnostic, and forcing `venvPath`/`venv` makes pyright **hang** (>7 min, killed) — i.e. the
interpreter-query path is blocked, not merely misconfigured.

**Clean-baseline control.** The identical command on a clean checkout of `f693912`
(`audit-portability-wt`, whose `tests/` and `src/` are byte-identical to `f693912`) gives the
**same count and the same error set**:

```
baseline f693912 : 107 errors, 1 warning
merge  0e72545   : 107 errors, 1 warning
$ diff /tmp/py_base_true.txt /tmp/py_merge.txt
ERROR SETS IDENTICAL (byte-for-byte) -> zero merge delta
```

**Caveat on magnitude.** The in-repo precedent at `docs/MERGE-LOG.md` @ `cbc95c3` records this gate as
red with only **12** errors (unresolved `arms`/`energy`/… imports in the two `texp_p3` probe files,
which `pyrightconfig.tests.json` `ignore`s). The environment here is degraded relative to that run:
site-packages is invisible, so every `import pytest` in `tests/` also fails, inflating the count.
The *kind* of finding is the same (pre-existing static-resolution red, not merge-induced); the count
is not comparable across environments. Per the precedent's ruling and the task's stop condition, this
is **reported, not fixed** — amending `pyrightconfig.tests.json` would be a behaviour-adjacent change
beyond a mechanical replay.

## 6. Gate 5 red — pre-existing, zero merge delta

```
5 failed, 4349 passed, 3 skipped, 1 warning in 556.76s (0:09:16)
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

All five are concurrency-race or Windows-privilege failures, none touching the replayed files:

- `test_concurrency.py:121` — `AssertionError: Expected 2 successes, got 1`
- `test_concurrency.py:209` — `assert 1 == 5`
- `test_p_auto_5_vault.py` — `Failed: DID NOT RAISE ProjectionRefused` (symlink creation raised `OSError`)
- `test_phase1_acceptance.py:326` — `assert 1 == 2`
- `test_q05_ratification_consumers.py:216` — `assert (1 == 1 and 0 == 1)`
- plus `sqlite3.OperationalError: attempt to write a readonly database` in the run

They are **deterministic here, not a load flake** — re-run in isolation on the merge branch, all five
fail again. And the **clean baseline `f693912` fails the identical five**:

```
BASELINE (f693912 tests/src) — same 5 tests:
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

The replay changes one literal in `matrix.py`, one expression in `run_tests.py`, and a docstring in
`hostile.py`; it cannot affect these five. **Zero merge delta.**

## 7. Audit carried (byte-identical, not re-interpreted)

The audit `audit/portability@f867536` — verdict **PASS WITH SHOULD-FIX, 0 MUST-FIX, 2 SHOULD-FIX,
6 NOTE** — is carried here verbatim; its findings are **recorded, not implemented**.

**Path discrepancy (input vs actual).** The task cites `audits/AUDIT-PORTABILITY.md`; the file
actually lives at the repo **root** as `AUDIT-PORTABILITY.md` in `f867536`. The commit hash matches,
so the artifact is unambiguous; the path in the input was inaccurate.

**SHOULD-FIXes carried, NOT implemented:**

- **SF-1** — `scripts/run_tests.py` derives `our_venv` from the *running* interpreter with no venv
  guard. Launched by a non-venv interpreter, `our_venv` becomes that interpreter's site-packages and
  the scrub **keeps the host leak while stripping the project venv** — the exact failure the script
  exists to prevent. Bounded: every documented invocation (`README.md:217`, `AGENTS.md:91`,
  `ci.yml:33,97`) uses the project venv, and the docstring discloses the behaviour. Minimal
  hardening: assert/`warn` when `sys.prefix == sys.base_prefix`.
- **SF-2** — `hostile.py` docstring wording: the `_WORKTREE`/`_SRC_DIR` pairing is inverted (actual
  `_WORKTREE` = `…/Lib`, `_SRC_DIR` = `…/Lib/site-packages`; `…/Lib` is the *parent* of
  `site-packages`, not inside it), and the quoted exception text is stale for 3.14
  (actual: `No module named tests.test_agent_runtime`).

**NOTEs carried:** N-1 the 3 residual `"src;."` copies in `test_eval_plane.py:192,1048,2015` are
masked by the editable install and inert; N-2 `.pth` masking is cross-tree (observed in §3);
N-3 CI is Windows-only (6/6 `windows-latest`), so the POSIX path has no coverage; N-4 Windows-only
spellings remain in `scripts/profiled_gate.sh:11,16`, `README.md:217`, `AGENTS.md:91`;
N-5 landing status; N-6 the audit-time matrix flake.

## 8. POSIX-execution caveat

**No Linux host was available.** `wsl.exe` is blocked by this machine's program blacklist and the
Docker daemon is not running (`failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`);
the only shell is MINGW64/MSYS Git Bash, which is not POSIX-Linux. Every gate in this log therefore
ran on Windows only.

The POSIX correctness of the replayed patch is consequently **review-grade, not execution-verified** —
established by stdlib source review of the `posix_venv` scheme
(`sysconfig/__init__.py:82,105-107`, `_get_implementation()` → `'python'`, `:548`, `:565`) plus
template expansion, and by the location-independence A/B (old runner relocated →
`ModuleNotFoundError: No module named 'pytest'`; new runner relocated → collects 205 tests, exit 0).
The source commit's own message states the same simulation method. **No real-POSIX run exists for
this patch, from either the author or this audit.**

## 9. Verdict and remote state

- Replay: **patch-exact** (identical blobs, byte-identical patch, same sha256). Originals untouched.
- Gates: 4 of 6 green; gates 4 and 5 red, **both proven pre-existing with byte-identical baseline
  behaviour and zero merge delta**. No gate red is attributable to the replay.
- STOP condition "any gate red — STOP, report" was **triggered and honoured**: the reds are reported,
  not fixed; nothing was pushed.
- **STOP BEFORE PUSH reached. No push performed.**

```
$ git ls-remote origin refs/heads/main
f6939129eb8429934c57db206a11480dab691ddb	refs/heads/main
$ git ls-remote origin refs/heads/merge/portability | wc -l
0
```

Remote `main` verified unmoved at `f693912`. Local `main` untouched. Branch `merge/portability` is
local-only.
