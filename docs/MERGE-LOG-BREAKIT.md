# MERGE-LOG-BREAKIT — promoting the B1 break-it harness

**Task ID:** MERGE-BREAKIT. **Role:** merge integrator (advance, verify).
**Precedent:** `docs/MERGE-LOG-DETECT.md` (linear advance + re-gated tip).
**Authority window:** D9 **LAPSED** — merge + verify ONLY. **Nothing was pushed.**
Local `main` was **not advanced, not checked out, not rebased, not amended**; no
other branch was touched. This document is the integration record.

## 1. Outcome

The promoted harness line was advanced onto a **local-only** branch `merge/breakit`
cut from local `main` in an **isolated worktree** (`D:/New folder/merge-breakit-wt`).
Topology is linear (`main@2e0af03` → `feat/breakit-promote@734f83c`), so the
advance was a **fast-forward**, verified before it was performed: the branch tip is
`734f83cad1488a45aed3507ca7f1724bf06f0f7d`, **hash-preserved** — no merge commit
was authored and not one byte of the input line was rewritten.

All gates were re-run **on the merged tip** (not inherited from the branch): the
break-it harness is **8/8 PASS** (`BREAKIT_EXIT=0`), `ruff` is clean on the file and
on `src`+`tests`, and byte identity is re-confirmed — the committed blob is
`756c462f95dce795351f6bdad2d95f7c089fd5f6` (sha256
`7765b807d5a0bd473126a68bcd446ceb10366403fa3c3ee46db7037b420450aa`), exactly the
canonical audited revision. No STOP condition fired.

## 2. Inputs (receipts)

| Item | Value |
|---|---|
| Repo | `D:\New folder\research-agent` |
| GitHub | `ace2013hieco-aa/khwarizmi-research` (`origin`) |
| BASE `main` (verified unmoved first) | `2e0af034ec15983447b156bed673ac23d82d3a71` |
| `origin/main` (read-only probe) | `2e0af034ec15983447b156bed673ac23d82d3a71` |
| Line | `feat/breakit-promote` @ `734f83cad1488a45aed3507ca7f1724bf06f0f7d` (parent `2e0af03` — **single additive commit**) |
| Canonical source of the artifact | `catalyst/b1-breakit` @ `288ffeb0f18a4d49610082fc31ee8541290240c7`, `scripts/break_it.py` blob `756c462f…` / sha256 `7765b807…` |
| Integration branch | `merge/breakit` — **LOCAL-ONLY, NO PUSH** |
| Worktree | `D:/New folder/merge-breakit-wt` (isolated) |
| Interpreter | Python **3.14.1** (host project venv, worktree `src/` first on `PYTHONPATH`) |
| Import provenance | `hermes -> D:\New folder\merge-breakit-wt\src\hermes\__init__.py` (worktree tree, not the host tree) |
| Harness encoding | `PYTHONUTF8=1` (cp1252 console is cosmetic only) |

Remote read-only probe (`git ls-remote origin main`) before any write:

```
2e0af034ec15983447b156bed673ac23d82d3a71	refs/heads/main
```

## 3. Linear-advance validity (verified, then performed)

```
merge-base main..734f83c : 2e0af034ec15983447b156bed673ac23d82d3a71  (== base)
--is-ancestor main 734f83c : TRUE                                   (FF-valid)
734f83c^                 : 2e0af034ec15983447b156bed673ac23d82d3a71  (single parent)
git branch --list merge/breakit : (empty)                           (no collision)
```

```
$ git worktree add "D:/New folder/merge-breakit-wt" -b merge/breakit main
HEAD is now at 2e0af03 security(manifest-anchor): \Z end-anchors for the vault manifest filename/sha256 grammars

$ git merge --ff-only 734f83cad1488a45aed3507ca7f1724bf06f0f7d
Updating 2e0af03..734f83c
Fast-forward
 scripts/break_it.py | 707 ++++++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 707 insertions(+)
 create mode 100644 scripts/break_it.py
MERGE_EXIT=0

$ git rev-list --parents -1 HEAD
734f83cad1488a45aed3507ca7f1724bf06f0f7d 2e0af034ec15983447b156bed673ac23d82d3a71
```

No conflict, no rename, no mode change, no side commit, no implicit rebase.

## 4. Hash chain

```
main                        2e0af034ec15983447b156bed673ac23d82d3a71   (untouched)
  └─ feat/breakit-promote   734f83cad1488a45aed3507ca7f1724bf06f0f7d   (1 file, +707/-0)
       └─ merge/breakit     734f83cad1488a45aed3507ca7f1724bf06f0f7d   (FF: same object)
            scripts/break_it.py
              blob   756c462f95dce795351f6bdad2d95f7c089fd5f6
              sha256 7765b807d5a0bd473126a68bcd446ceb10366403fa3c3ee46db7037b420450aa
              == canonical catalyst/b1-breakit@288ffeb blob (byte-identical, re-confirmed)
```

The artifact hash chain is closed: branch tip object == input line tip object, and
the committed blob hash is the hash that was audited (`756c462f…` / `7765b807…`).

## 5. Changed files (`git diff --numstat main HEAD`)

```
707	0	scripts/break_it.py
```

Two entries exist in the merged tree but only one counted above, because the base
is `main` and the diff therefore counts the **input line** delta only. This record
(`docs/MERGE-LOG-BREAKIT.md`, itself the single follow-on commit) is documentation;
it touches no source, test, config, or script file.

## 6. Gate battery — re-run on the merged tip

```
=== import provenance ===
hermes -> D:\New folder\merge-breakit-wt\src\hermes\__init__.py
3.14.1 (tags/v3.14.1:57e0d17, Dec  2 2025, 14:05:07) [MSC v.1944 64 bit (AMD64)]

=== harness on merged tip (PYTHONUTF8=1) ===
BREAKIT_EXIT=0
summary: 8/8 scenarios matched their reference-test assertions
  S1: PASS   S2: PASS   S3: PASS   S4: PASS
  S5: PASS   S6: PASS   S7: PASS   S8: PASS
(full transcript: /d/tmp/merge_breakit_harness.log)

=== ruff: file ===
All checks passed!            RUFF_FILE_EXIT=0

=== ruff: src+tests ===
All checks passed!            RUFF_GATE_EXIT=0

=== byte-identity re-confirm ===
blob  : 756c462f95dce795351f6bdad2d95f7c089fd5f6
sha256: 7765b807d5a0bd473126a68bcd446ceb10366403fa3c3ee46db7037b420450aa
wc    : 707 lines
```

`scripts/break_it.py:1-707` is the whole delta: 8 scenarios (S1–S8) each asserting
that a refusal path fires with its expected code.

## 7. No-push / window evidence

* Advance was local-only: the branch existed nowhere on `origin` (no matching ref
  in `git ls-remote --heads origin`).
* `main` and every other branch were read, never written:
  `rebase/detect-refresh 2e0af03` · `fix/manifest-anchor 88ea2f3` ·
  `rebase/detect` & `fix/sidecar-anchor bc96366` · `oh/o1-sidecar d1241a1` ·
  `catalyst/b1-breakit 288ffeb`.
* Nothing was deleted: the harness's dev-branch copy on `catalyst/b1-breakit`
  remains where it was; the promotion is additive on top of `main`.

## 8. Verdict

**DONE** — DONE WHEN met: 8/8 green on the merged tip (pasted above), blob hash
re-confirmed (`756c462f…` / `7765b807…`), ruff clean. No STOP condition fired;
in particular the advance was clean and the artifact hash matched the audited
revision, so the "blob mismatch" stop was never approached.

**Limitations:** verification is local and hash-level; the served remote was not
contacted beyond a read-only `ls-remote` probe, and nothing was pushed by design
(landing remains the operator's decision). The known pre-existing
`.git/worktrees/step-4` administrative entry still emits a harmless prune notice
on worktree creation (`error: failed to delete ... Permission denied`, stderr only,
exit codes unaffected). A pre-`288ffeb` scratch copy of the harness still sits
untracked at the dev checkout root; it was not promoted, not adapted, and not
deleted (not this task's artifact to remove).
