# MERGE-AUDIT-FETCH-ADDENDUM — D1 + M1-fix advance of `merge/fetch`

Closes the audit loop opened by `docs/MERGE-AUDIT-FETCH.md` (FAIL on MUST-FIX
M1) and `docs/DELTA-AUDIT-FETCH-M1.md` (M1 closure PASS, D-1 hardening
MUST-FIX). Advances the `merge/fetch` leg to the fix line's tip and re-derives
both closures. Findings only. Counts and `file:line`.

| Field | Value |
| --- | --- |
| Repo | `D:\New folder\research-agent` |
| Branch | `merge/fetch` (isolated worktree `C:\Users\Ali Zoghi\AppData\Local\Temp\opencode\mergefetch`) |
| Base tip | `8e6f1b05a27d88acb8062c2301e5d084cdb224ca` (merge/fetch before this task) |
| Advanced tip | `8b4ef7fed5d5cdf55af0c4de4189bfdf217fd1b3` (fix/fetch-d1, local-only) |
| Fix line | `8e6f1b0 → ceb3deec69f415f3651b6ed3631e7f01eff9ee61 (M1) → 8b4ef7f (D-1)` |
| Audit basis | `audit/fetch-m1-delta@9f670e7` (`docs/DELTA-AUDIT-FETCH-M1.md`), `merge/fetch@8e6f1b0` (`docs/MERGE-AUDIT-FETCH.md`) |
| `main` (local == remote) | `e5f06a72370ed4af02903b6504bad6c848c1fc4a` — unmoved, never touched |
| Push | **none — STOP BEFORE PUSH honored**; `merge/fetch` does not exist on the remote |
| Verdict | **PASS** |

## Topology and advance receipt

The fix line was built linearly on top of the audited merge tip — `ceb3dee`'s
only parent is `8e6f1b0` and `8b4ef7f`'s only parent is `ceb3dee` (verified
with `git rev-list --parents`). Neither fix was already contained in
`merge/fetch` before this task (`git merge-base --is-ancestor ceb3dee
merge/fetch` → exit 1), so the advance is a **strict-descendant fast-forward
from the current tip**, not a divergent integration:

```
$ git merge --ff-only 8b4ef7f
Updating 8e6f1b0..8b4ef7f
Fast-forward
 src/hermes/research/controller.py                |  16 +-
 src/hermes/tools/providers/docling_provider.py   | 136 ++++++++++++-----
 tests/test_fetch_m1_docling_controller_wiring.py | 183 +++++++++++++++++++++++
 3 files changed, 290 insertions(+), 45 deletions(-)
```

No `--no-ff` merge commit was needed or created: there was no divergent leg to
merge, and the FF preserves every cited hash (`bf7c34f`, `670e643`, `8acb887`,
`8e6f1b0`, `ceb3dee`, `8b4ef7f` are all still reachable from the new tip).
Zero conflicts. The integrator authored **no `src/` or `tests/` change** — the
only delta is the fix line itself, already director-verified.

Disclosure (pre-existing, carried from `docs/MERGE-AUDIT-FETCH.md`): the FF
again logged `error: failed to delete 'D:/New folder/research-agent/.git/worktrees/step-4': Permission denied`
while pruning a stale worktree admin directory unrelated to this line. The
advance landed correctly (parents/trees verified immediately). The gitignored
`.venv` junction was created in the worktree so `scripts/run_tests.py` can
resolve site-packages — same pattern as every prior gate worktree.

## Gates — raw, at `8b4ef7f` (uncontended, suite alone)

```
$ PYTHONDONTWRITEBYTECODE=1 HERMES_SKIP_LIVE_FETCH=1 \
  PYTHONPATH=<wt>/src .venv/Scripts/python.exe scripts/run_tests.py -v -p no:cacheprovider
platform win32 -- Python 3.14.1, pytest-9.1.1, pluggy-1.6.0
collected 2509 items
2505 passed, 4 skipped, 12 warnings in 565.32s (0:09:25)   # EXIT=0

$ uvx ruff check src tests
All checks passed!                                          # exit 0

$ PYTHONPATH=<wt>/src uvx pyright src
0 errors, 0 warnings, 0 informations                        # exit 0

$ PYTHONPATH=<wt>/src uvx pyright --pythonpath "D:/New folder/research-agent/.venv/Scripts/python.exe" \
    --project pyrightconfig.tests.json
0 errors, 1 warning, 0 informations                         # exit 0
  tests/test_research_program.py:144:23 (pre-existing, same as every prior run)
```

Import proof: `hermes.__file__ = …\mergefetch\src\hermes\__init__.py`. The 4
skips are the live-egress tests under `HERMES_SKIP_LIVE_FETCH=1`.

This is the **first complete full-suite run over the fix line** — the
delta-audit's attempt exceeded its 600 s budget and was stopped. It completes
in 565.32 s here with zero failures, so M1's and D-1's tests are certified by
a complete suite, not only by their own file.

## D-1 closure — re-derived (PASS)

D-1 (`docs/DELTA-AUDIT-FETCH-M1.md` §D): `resolver_for_store_key` checked only
the `source_payload:` prefix, so a direct call with a bare non-addressable
alias returned `True`. The fix (`8b4ef7f`) mirrors the store's shape rule at
`docling_provider.py:613-622`:

```
613  def resolve(source_ref: str, span_ref: str) -> bool:
614      if (not isinstance(source_ref, str)
615              or not source_ref.startswith("source_payload:")):
616          return False
617      digest = source_ref[len("source_payload:"):]
618      if len(digest) != 64 or not all(
619              c in "0123456789abcdef" for c in digest):
620          return False  # never trust a truncated alias as a key (SD2-04/§18)
```

mirroring `read_payload_bytes`' rule (`source_outcomes.py:394-424`, shape at
`:411-415`). Independent probe (`probe_d1_bare_alias.py`, md5
`cea88a74d4242f0db63ce9132c4e4836`, token recomputed from record fields with
the canonical recipe, not via the fixer's helpers):

```
{"probe": "full_shape_key_admits",         "result": true}
{"probe": "bare_own_alias_refuses",        "result": false}   # the D-1 case
{"probe": "bare_x_pdf_refuses",            "result": false}
{"probe": "short_63hex_refuses",           "result": false}
{"probe": "long_65hex_refuses",            "result": false}
{"probe": "uppercase_hex_refuses",         "result": false}
{"probe": "empty_digest_refuses",          "result": false}
{"probe": "no_prefix_refuses",             "result": false}
{"probe": "none_src_refuses",              "result": false}
{"probe": "bare_substring_span_refuses",   "result": false}
{"probe": "D1_CLOSURE", "verdict": "PASS", "mismatches": {}}
```

The delta-audit's own probe, re-run at the tip
(`probe_fetch_m1_delta.py` md5 `8d54c9681a2ffdd551b3263fd7d33ecb`, unchanged
from the recorded audit):

```
{"probe": "resolver_for_store_key(matrix)", "result": {"alias_bare_nonhex": false,
 "alias_ownref": false, "no_source_payload_prefix": false, "none_src": false,
 "storekey_bare": false, "storekey_forged_charspan": false, "storekey_valid": true}}
{"probe": "controller/alias_inner_ref", "result": {"claim_rows": 0, "status": "RETRYING"}}
```

`resolver_for` strictness is unchanged: the 205-case deterministic battery
(`ab_resolver_battery.py` md5 `bc7dc2ee51cc3c0d806fded617fad672`) re-run at
the tip is **byte-identical** to the recorded target output — 205 lines, md5
`6a00a7b1b0038b34bb2b9def3602427a` (matches `battery-target.out`).

**D-1 verdict: CLOSED.**

## M1 closure — carries (PASS)

The M1 closure is cited from `docs/DELTA-AUDIT-FETCH-M1.md` (PASS: red→green
re-derived independently; no model-reachable laundering path) and re-run here:

```
$ PYTHONPATH=<wt>/src .venv/Scripts/python.exe -m pytest \
    tests/test_fetch_m1_docling_controller_wiring.py -v -p no:cacheprovider
collected 6 items
tests\test_fetch_m1_docling_controller_wiring.py ......   [100%]
6 passed in 0.95s                                          # exit 0
```

The file holds M1's five tests (`test_docling_store_key_digest_token_admits_end_to_end`,
`…_bare_substring_refuses`, `…_forged_charspan_refuses`,
`test_spliced_provenance_ref_refuses`, `test_plain_payload_substring_path_unchanged`)
plus D-1's direct-call test. The end-to-end closure is also reproduced by the
independent probe at the tip:

```
{"probe": "controller/valid_token",   "result": {"claim_rows": 1, "status": "SUCCEEDED"}}
{"probe": "controller/bare_substring","result": {"claim_rows": 0, "status": "RETRYING"}}
{"probe": "controller/spliced_provenance", "result": {"claim_rows": 0, "status": "RETRYING"}}
{"probe": "controller/plain_payload", "result": {"claim_rows": 1, "status": "SUCCEEDED"}}
```

Admission now flows through `controller.py:4680-4683` →
`resolver_for_store_key` (`docling_provider.py:585-623`) → `span_token_resolves`
(`docling_provider.py:518`). The carried R-1/R-2 residuals are pre-existing
(identical on base and target in the delta audit) and are not touched by this
advance.

**M1 verdict: CLOSED (delta-audit PASS carries; re-run green at the tip).**

## S4-condition survival (re-checked at the tip)

| Condition | Evidence |
| --- | --- |
| `NOTICE` | `git diff --exit-code 8de7f22 8b4ef7f -- NOTICE` — empty, byte-identical to H2's tip |
| Pins | `tomllib` parse: `{'docling': ['docling==2.131.0'], 'crawl4ai': ['crawl4ai==0.9.4']}` |
| `live_fetch` marker | present (`pyproject.toml:40`) |
| `uv.lock` | byte-identical to `8de7f22` (`git diff --exit-code` empty) |

## Count lineage (to the advanced tip)

| Figure | Derivation |
| --- | --- |
| 2325 | `main` — `total_collected=2325` |
| 2358 | `bf7c34f` — live-fetch file 23 (`0298b4e`) → 33 (measured) |
| 2470 | `8de7f22` — 2325 + 145 (50 docling + 47 crawl4ai + 48 egress) |
| 2503 | `merge/fetch@8acb887` (M2) — 2325 + 33 + 145 |
| 2508 | `ceb3dee` (M1) — +5 (the new wiring file); the director-verified figure carried in `docs/DELTA-AUDIT-FETCH-M1.md` |
| **2509** | `8b4ef7f` (D-1) — +1 (the direct-call refusal test); **re-derived here**: `2505 passed + 4 skipped = 2509 collected` |

## Forbidden-topic scan

`git diff 8e6f1b0 8b4ef7f | grep -inE "backtest_audit|\bSDA\b|\bTSE\b|Optimize-my-strategy"`
— **0 hits**. No STOP condition on scope.

## Post-audit integrity checks

- `git rev-parse HEAD` in the worktree: `8b4ef7fed5d5cdf55af0c4de4189bfdf217fd1b3`;
  `git symbolic-ref --short HEAD` → `merge/fetch`.
- `git status --porcelain --untracked-files=all` before this doc was written:
  **empty** — no stray tracked modification, no src change made by this audit.
- `main` local == `main` remote == `e5f06a72370ed4af02903b6504bad6c848c1fc4a`,
  checked before the advance, after it, and again at the close.
  `git ls-remote origin refs/heads/main` → `e5f06a72370ed4af02903b6504bad6c848c1fc4a`.
  `main` was never checked out, reset, rebased, committed to, or pushed.
- `git ls-remote origin refs/heads/merge/fetch` → **empty**: `merge/fetch` has
  never been pushed. **No `git push` of any ref was performed — STOP BEFORE
  PUSH honored.** D9 remains lapsed.
- The shared checkout (`D:\New folder\research-agent`, branch
  `intake/improve-A` with its own staged state) was never touched; all work
  happened in the isolated worktree.

## Verdict

**PASS.** The `merge/fetch` leg advances by clean fast-forward to `8b4ef7f`
(all input hashes preserved), all four gates are green at the advanced tip
(`2505 passed, 4 skipped = 2509 collected`), D-1 is closed by direct probe,
M1's closure carries with a complete suite behind it, S4 survives, and the
count lineage reconciles `2325 → 2358 → 2470 → 2503 → 2508 → 2509`. No push;
`main` unmoved.

## Addendum — gates re-run at the final tip `f4f59ed`

The §Gates table is at the advance tip `8b4ef7f`. Committing this document
moved the tip, and per AGENTS.md a docs-only change still requires the full
suite green, so all four gates were re-run at `f4f59ed` (the tip including
this document), uncontended, suite alone:

```
$ git diff --exit-code 8b4ef7f f4f59ed -- src tests
(no output — IDENTICAL, exit 0)
```

| Gate | Result at `f4f59ed` |
| --- | --- |
| full suite (alone) | `collected 2509 items` → `2505 passed, 4 skipped, 12 warnings in 551.78s (0:09:11)` — exit 0 |
| lint (C3) | `All checks passed!` — exit 0 |
| strict types | `0 errors, 0 warnings, 0 informations` — exit 0 |
| tests types | `0 errors, 1 warning, 0 informations` — exit 0 (same pre-existing `tests/test_research_program.py:144:23`) |

Because this docs commit changes no `src/` or `tests/` byte, the findings
and gates above hold unchanged at the final tip.
