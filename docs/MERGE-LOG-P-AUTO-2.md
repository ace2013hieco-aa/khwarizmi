# MERGE-LOG-P-AUTO-2 — integration of the P-AUTO-2 prompts line onto `main`

Merge integrator record for the P-AUTO-2 slice: deterministic
RESEARCHER-on-EXTRACT assembler plus `ModelClient` stub
(`slice/p-auto-2-prompts@98dd664`). Follows the
`MERGE-LOG-FETCH` / `MERGE-LOG-SCANFIX` pattern.

**Outcome: slice integrated and verified on `merge/p-auto-2`; redteam audit
PASS (`AUDIT-P-AUTO-2-REDTEAM.md` on `audit/p-auto-2-redteam@e0fe0bc`).
`main` NOT advanced and NOT pushed — D9 lapsed, merge + verification only.**

## Inputs

| Input | Value |
| --- | --- |
| Repository | `D:\New folder\research-agent` (`ace2013hieco-aa/khwarizmi-research`) |
| `main` at task start (local) | `32dfa0600c81131bfc8c3dacba35aabe3336983e` |
| `main` at task start (remote) | `32dfa0600c81131bfc8c3dacba35aabe3336983e` (`git ls-remote origin refs/heads/main`) |
| `slice/p-auto-2-prompts` tip | `98dd66435630a1488a4b50bbef52f1d571763371` (2 files, +652/-0) |
| audit tip | `e0fe0bc9b6297779ee0af80b72f9736b39758254` (`AUDIT-P-AUTO-2-REDTEAM.md` at repo root) |
| Human approval banked | none — **D9 lapsed; no push under any circumstance** |

Audit result: **PASS — 0 MUST-FIX, 0 SHOULD-FIX, 4 NOTEs** (carried below).
NOT-topics (`backtest_audit`, `SDA`, `TSE`, `Optimize-my-strategy`):
audit-side scan of both slice files → 0 hits; no STOP triggered.

## Merge hashes

| Ref | Hash |
| --- | --- |
| `merge-base main slice/p-auto-2-prompts` | `c6076d5f978a4c4b49574d1af6f02cafd63750f5` |
| `main` (pre/post) | `32dfa0600c81131bfc8c3dacba35aabe3336983e` → **unchanged** |
| `merge/p-auto-2` tip | `3f0c5191eb30a9ae5132a13eb85ae99d95c0c64d` |
| parents | `32dfa06` (main), `98dd664` (slice tip, hash preserved) |

Topology: NOT a clean fast-forward — the slice branched at `c6076d5` while
`main` advanced to `32dfa06` (merge/fetch, merge/scanfix, docs). Per task
rules (never rebase cited tips), integrated via `--no-ff` ort merge
(`git merge --no-ff slice/p-auto-2-prompts`). Zero conflicts: the slice's
entire delta vs its base is two new files, and `main` never touched those
paths. Diffstat of the merge: 2 files, +652/-0 —
`src/hermes/research/prompt_assembly.py` (+339),
`tests/test_p_auto_2_prompts.py` (+313). No file outside the declared set.

## Base drift statement

The slice was authored on `c6076d5`; `main` is at `32dfa06`. The audit
(`audit/p-auto-2-redteam@e0fe0bc`, itself a child of `32dfa06`) re-derived
the slice onto `32dfa06` live and found the diff applies cleanly with no
promise invalidated (its check (F): base-drift PASS). The merge reproduces
exactly that state: tree = `main@32dfa06` + the two slice files, and the
slice tests re-pass unmodified (16/16). No rebasing of the cited tip
`98dd664` was performed; its hash is a merge parent.

## Gates (run on the merge worktree, Python 3.14.1)

| Gate | Result |
| --- | --- |
| Slice tests | `pytest tests/test_p_auto_2_prompts.py -q` → 16 passed |
| Full suite | `scripts/run_tests.py` → **2566 passed, 16 skipped in 431.35s** |
| Ruff | `uvx ruff check src tests` → All checks passed! |
| Pyright (src) | `uvx pyright src` → 0 errors, 0 warnings, 0 informations |
| Pyright (tests) | `uvx pyright --pythonpath .venv/Scripts/python.exe --project pyrightconfig.tests.json` (with `PYTHONPATH=<worktree>/src`) → 0 errors, 1 warning (`tests/test_research_program.py:144:23` `reportSelfClsParameterName`, pre-existing on mainline), 0 informations |

## Carried NOTEs (from `AUDIT-P-AUTO-2-REDTEAM.md` @ e0fe0bc)

- NOTE-1 (marker-substring fragility, trusted-input boundary): program
  obligations / allowlist metadata / `task_id` / `source_ref` render raw, so a
  party controlling those trusted inputs can forge a marker-like line.
  `truncated` stays `False` in that case. Consumers of `prompt.text` MUST
  decide truncation from the `truncated` flag (+ exact trailing-line check),
  never from substring grep. Inside the slice's threat model (those inputs
  are chartered trusted) this is not a break — recorded so the consumer
  contract is explicit.
- NOTE-2 (degenerate custom tier): direct `BudgetClass` construction with
  `max_prompt_chars < len(TRUNCATION_MARKER)+2` (e.g. 5) yields a prompt
  longer than the nominal budget (417 chars observed) — still within the 4
  KiB hard bound. `from_cost_class` tiers are the only advertised path and
  are exact; the constructor is a trusted-caller surface. Not a break.
- NOTE-3 (silent empty-ref drop): envelopes with `ref=""` are filtered from
  markers without refusal or accounting (`prompt_assembly.py:196-201`).
  Only reachable by hand-constructed envelopes (`fetched_text` always sets
  `ref`); fail-loud would be stricter but nothing in the gate requires it.
- NOTE-4 (by-design length oracle): goldens pin `len=19` in the marker — the
  marker reveals payload length + origin + ref. This is the ratified M3
  envelope behavior, not a leak introduced by the slice.

## Verdict

P-AUTO-2 prompts line integrated intact; all gates green; NOTEs carried;
`main` unmoved; no push performed.
