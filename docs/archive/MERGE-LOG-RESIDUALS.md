# MERGE-LOG-RESIDUALS — integrate R-1+harden, R-2, R-3+pin-fix, R-4+docfix + four audit docs (LOCAL-ONLY)

Merge integrator record for task **MERGE-RESIDUALS**.
**Outcome: all seven line tips + all four audit docs integrated on
`merge/residuals`; full gates green; `main` NOT advanced, NOT pushed —
D9 lapsed; merge + verification only. STOPPED BEFORE PUSH.**
Precedent: MERGE-SCANFIX / MERGE-CFIX3 patch-exactness invariants +
refusal re-scan (refusal re-scan = the four re-proof batteries in
`MERGE-AUDIT-RESIDUALS.md`).

## Inputs

| Input | Value |
| --- | --- |
| Repository | `D:\New folder\research-agent` (`ace2013hieco-aa/khwarizmi-research`) |
| Worktree | `D:\New folder\merge-residuals-wt` (isolated, branch `merge/residuals`) |
| `main` local at task start | `a8f018068e3c04b3160891ebd56cfd95d3590c95` (verified == BASE) |
| `main` remote (read-only `git ls-remote origin refs/heads/main`) | `e4b276db7880cb8c0e17e1239e03c589138541ae` — NOT touched |
| R-1a `fix/vault-manifest` | `fccfd80bb7ad` |
| R-1b `fix/r1-harden-v2` | `6c010393e8c2` (linear pair child of R-1a) |
| R-2 `fix/b3-producer-ref` | `dbdca786babf` (audit PASS) |
| R-3a `fix/operator-knobs` | `51a4a99d2eea` |
| R-3b `fix/pin-dispatch` | `2bc645635038fd3d2e026e4afdae5609a84ac7ba` |
| R-4a `slice/fault-harness` | `2758515e10ea` |
| R-4b `fix/r4-docfix` | `c499474eca3c` (linear pair child of R-4a) |
| audit-R1 `audit/r1-manifest` | `953c8d930a9d` (carries `AUDIT_R1_MANIFEST.md`) |
| audit-R2 `audit/r2-producer` | `1989bc94d0c6` (carries `AUDIT-R2-PRODUCER.md`) |
| audit-R3 `audit/r3-knobs` | `d299512bd1d2` (carries `AUDIT-R3-KNOBS-PROXY.md`) |
| audit-R4 `audit/r4-harness` | `7188797943e5` (carries `AUDIT-R4-HARNESS-REDTEAM.md`) |
| Human approval | none — **D9 lapsed; no push under any circumstance** |

Topology (verified, not assumed):
`git merge-base main <line>` == `a8f018068e3c` and
`git merge-base --is-ancestor main <line>` TRUE for all seven line tips
(every line descends directly from the BASE). The two pairs are linear:
`fccfd80` is an ancestor of `6c01039`; `2758515` is an ancestor of
`c499474`. R-3a/R-3b are independent branches off BASE (neither is an
ancestor of the other) — the KNOWN `http.py` overlap is therefore a
cross-line merge, not a pair. Platform line (`main` local, unpushed
platform-session commits): never rebased, never touched, never pushed.

## Merge hashes

| Step | What | Result |
| --- | --- | --- |
| create | `git worktree add -b merge/residuals <wt> main` | `a8f0180` |
| 1 | FF `--ff-only 6c01039` (R-1 pair; R-1b subsumes R-1a) | `a8f0180..6c01039` |
| 2 | `--no-ff dbdca78` (R-2) | merge `bb5ef55b7849` |
| 3 | `--no-ff 51a4a99` (R-3a; `cli.py` auto-merged) | merge `66e872225c16` |
| 4 | `--no-ff 2bc6456` (R-3b/FIX-PIN; `http.py` auto-merged) | merge `26717d3d00ae` |
| 5 | `--no-ff c499474` (R-4 pair) | merge `fb412d508e52` |
| 6 | `--no-ff 953c8d9` (audit-R1 doc; add/add resolved to hardened ours) | merge `1970b3d9072c` |
| 7 | `--no-ff 1989bc9` (audit-R2 doc) | merge `d9beae5b4aff` |
| 8 | `--no-ff d299512` (audit-R3 doc) | merge `38a53cdf7330` |
| 9 | `--no-ff 7188797` (audit-R4 doc) | merge `bafa728a60c4` |
| — | `merge/residuals` tip pre-doc-commits | **`bafa728a60c42a97285c3a2939f0986c45d52fd9`** |
| — | `main` old → new | `a8f0180` → **unchanged** |

All seven line tips and all four audit tips are ancestors of the tip:
`fccfd80`, `6c01039`, `dbdca78`, `51a4a99`, `2bc6456`, `2758515`,
`c499474`, `953c8d9`, `1989bc9`, `d299512`, `7188797` — verified with
`git merge-base --is-ancestor <tip> HEAD` = TRUE for each.

## Patch-exactness per line

Per-line `git diff main..<tip> --numstat` (R-1a/R-4a are subsumed by
their pair children and are shown for the pair record):

| Line | File | insert/delete |
| --- | --- | --- |
| R-1a `fccfd80` | `src/hermes/cli.py` | 104/1 |
| R-1a | `src/hermes/vault/manifest.py` | 683/0 (new) |
| R-1a | `src/hermes/vault/projection.py` | 263/107 |
| R-1a | `tests/test_vault_manifest.py` | 543/0 (new) |
| R-1b `6c01039` | `src/hermes/cli.py` | 104/1 |
| R-1b | `src/hermes/vault/manifest.py` | 726/0 (new) |
| R-1b | `src/hermes/vault/projection.py` | 263/107 |
| R-1b | `tests/test_vault_manifest.py` | 617/0 (new) |
| R-2 `dbdca78` | `src/hermes/research/gateway.py` | 9/0 |
| R-2 | `tests/test_b3_producer_ref.py` | 303/0 (new) |
| R-3a `51a4a99` | `src/hermes/cli.py` | 11/1 |
| R-3a | `src/hermes/research/autonomy_caps.py` | 20/8 |
| R-3a | `src/hermes/tools/providers/http.py` | 10/7 (comment-only) |
| R-3a | `tests/test_operator_knobs.py` | 262/0 (new) |
| R-3a | `tests/test_proxy_path_e2e.py` | 204/0 (new) |
| R-3b `2bc6456` | `src/hermes/tools/providers/http.py` | 17/0 (dispatch purge) |
| R-3b | `tests/test_p_auto_4_fix.py` | 104/0 (added to existing file) |
| R-4a `2758515` | `tests/fault_injection/__init__.py` | 11/0 (new) |
| R-4a | `tests/fault_injection/kills.py` | 192/0 (new) |
| R-4a | `tests/fault_injection/plugin.py` | 40/0 (new) |
| R-4a | `tests/test_r4_fault_harness.py` | 141/0 (new) |
| R-4b `c499474` | `tests/fault_injection/__init__.py` | 11/0 |
| R-4b | `tests/fault_injection/kills.py` | 196/0 |
| R-4b | `tests/fault_injection/plugin.py` | 40/0 |
| R-4b | `tests/test_r4_fault_harness.py` | 143/0 |

Merged `git diff main..HEAD --numstat` is the exact union:

- **Overlap `src/hermes/cli.py`**: R-1b 104/1 + R-3a 11/1 = **115/2** == merged 115/2.
  Regions are disjoint (R-1b adds `_vault_project`/`_vault_verify` +
  dispatch at `cli.py:667/705/909/911`; R-3a adds the R-3 docstring +
  `autonomy_operator=cfg.autonomy_caps` at `cli.py:503`); git auto-merged,
  zero conflict markers.
- **Overlap `src/hermes/tools/providers/http.py`**: R-3a 10/7 (docstring
  rewrite of `_build_opener`) + R-3b 17/0 (dispatch-chain purge after
  `add_handler`) = **27/7** == merged 27/7. Regions are disjoint
  (`:163-176` vs `:203-221`); git auto-merged. Both changes are present
  in the merged blob: R-3's named-outcome docstring (`http.py:173`) AND
  FIX-PIN's `handle_open["https"]` purge (`http.py:203-221`).
- **Every other file is single-writer and byte-identical to its line
  blob** (verified `git rev-parse <ref>:<path>` equality):
  `manifest.py a09b4d5`, `projection.py a0fec92`, `test_vault_manifest.py 3901526`,
  `gateway.py 35f9396`, `test_b3_producer_ref.py d55eeff`,
  `autonomy_caps.py 7680e36`, `test_operator_knobs.py dd05210`,
  `test_proxy_path_e2e.py 204ad0d`, `test_p_auto_4_fix.py d39dea1`,
  `fault_injection/kills.py 4d0a271`, `fault_injection/plugin.py a31dcfb`,
  `fault_injection/__init__.py 0783dfe`, `test_r4_fault_harness.py f825d81`.

`src/` changes on the merge branch: exactly the five line blobs above —
**no `src/` change beyond the R1-audit-merge conflict repair**, and that
repair was a no-op resolution (`--ours` = the hardened R-1b blob, so the
audit merge contributed only its `.md` doc).

## Audit docs carried (byte-identical)

| Doc | Source ref | Blob (merged == source) |
| --- | --- | --- |
| `AUDIT_R1_MANIFEST.md` (FAIL, 156 lines) | `audit/r1-manifest@953c8d9` | `2e0cde726a03c976194f685f21d7fbc2e6df6df9` |
| `AUDIT-R2-PRODUCER.md` (PASS, 175 lines) | `audit/r2-producer@1989bc9` | `1c86eac04cbad4cf98044812f72de67a610a66c3` |
| `AUDIT-R3-KNOBS-PROXY.md` (FAIL→pin-fix, 159 lines) | `audit/r3-knobs@d299512` | `7a6a6a6eb64a473f62c7a0c82a53fb42de1970a0` |
| `AUDIT-R4-HARNESS-REDTEAM.md` (FAIL→docfix, 278 lines) | `audit/r4-harness@7188797` | `727c4799765c0fbd9248e936d76d6f2cd783bac1` |

## Conflict record

| # | Merge | Shape | Resolution |
| --- | --- | --- | --- |
| 1 | audit-R1 (step 6) | add/add on `src/hermes/vault/manifest.py` + `tests/test_vault_manifest.py` (audit branch snapshots the PRE-harden R-1a content `2fed821`/`33ba8ca`; the merged line already carries the hardened R-1b content `a09b4d5`/`3901526`) | `--ours` (hardened R-1b) — mechanical, no content authored; hash equality re-verified post-resolution |
| 2 | R-3a + R-1 (cli.py) | none — git auto-merged disjoint hunks | union verified by numstat arithmetic + hunk presence |
| 3 | R-3a + R-3b (http.py) | none — git auto-merged disjoint hunks (comment-only vs dispatch purge); **pin behavior wins** by construction (both preserved) | union verified by numstat arithmetic + hunk presence |

Zero conflict markers anywhere (`grep -rn '^<<<<<<<|^=======$|^>>>>>>>' src tests` = empty).
No semantic conflict encountered → no STOP triggered (STOP conditions
re-scanned: NOT-topics `backtest_audit`/`SDA`/`TSE`/`Optimize-my-strategy`
absent from every diff; platform line undisturbed; no push).

## Diffstat `main..merge/residuals` (pre-doc)

4 audit docs + 15 integration files:
`AUDIT-R2-PRODUCER.md 175/0`, `AUDIT-R3-KNOBS-PROXY.md 159/0`,
`AUDIT-R4-HARNESS-REDTEAM.md 278/0`, `AUDIT_R1_MANIFEST.md 156/0`,
`src/hermes/cli.py 115/2`, `src/hermes/research/autonomy_caps.py 20/8`,
`src/hermes/research/gateway.py 9/0`,
`src/hermes/tools/providers/http.py 27/7`,
`src/hermes/vault/manifest.py 726/0`, `src/hermes/vault/projection.py 263/107`,
`tests/fault_injection/__init__.py 11/0`, `tests/fault_injection/kills.py 196/0`,
`tests/fault_injection/plugin.py 40/0`, `tests/test_b3_producer_ref.py 303/0`,
`tests/test_operator_knobs.py 262/0`, `tests/test_p_auto_4_fix.py 104/0`,
`tests/test_proxy_path_e2e.py 204/0`, `tests/test_r4_fault_harness.py 143/0`,
`tests/test_vault_manifest.py 617/0`
= 19 files, 4312 insertions, 123 deletions, 0 renames.

## Count lineage

- BASE `main@a8f0180` live `--collect-only` (temp worktree
  `D:\New folder\merge-residuals-base-wt`, read-only): **3686** tests.
- Merged tip: **3746** tests (+60), decomposed per file:
  `test_vault_manifest.py` +25 (new), `test_b3_producer_ref.py` +10 (new),
  `test_operator_knobs.py` +8 (new), `test_proxy_path_e2e.py` +3 (new),
  `test_r4_fault_harness.py` +13 (new), `test_p_auto_4_fix.py` +1
  (existing file 12 → 13; the FIX-PIN test).
  25+10+8+3+13+1 = **60** = 3746 − 3686 — reconciles exactly, zero skips.
- Full-suite JUnit at the tip: `tests=3746 errors=0 failures=0 skipped=0`,
  `EXIT:0` (raw gates in `MERGE-AUDIT-RESIDUALS.md`).

## Gates (pointer)

Full suite + ruff + both pyright projects are green at the tip; raw
commands, raw outputs, all four re-proof batteries and the audit verdict
are in `MERGE-AUDIT-RESIDUALS.md` (separate commit, one file).

## Residuals carried (documented, not hidden)

- R-2 NOTE: `artifact_ids_json` has no independent size check at the
  persistence boundary (transitively bounded by the ≤4 KiB admission
  payload) — pre-existing boundary gap.
- R-4 S1/S2 (expected-red-count pin, static-vs-static seam line pins) —
  unfixed by the R-4 docfix; declared scope, recorded in
  `AUDIT-R4-HARNESS-REDTEAM.md`.
- R-3 port-form nuance observed during the pin re-probe: the production
  publisher keys the bare hostname (`live_fetch.py:136`) while
  `_lookup_pin` receives `req.host` (netloc); a port-bearing URL misses
  the pin and falls back to the DNS path (allowlist gate still applies).
  Pre-existing to FIX-PIN (FIX-D wiring), noted in the audit doc.
