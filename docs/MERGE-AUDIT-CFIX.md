# MERGE-AUDIT-CFIX — delta audit of `merge/cfix@7bea35e`

Delta audit of the FIX-FENCE-DELEGATION + FIX-VAULT-NOTES integration as merged
into `merge/cfix`. Findings, counts and `file:line`. Executed in an isolated
worktree (`D:\New folder\research-agent-merge-cfix-wt`); `main` and the two
owning worktrees were opened read-only and never written.

The audited integration tip is `7bea35e` (merge 2). The two docs commits that
follow — `017b95f` (MERGE-LOG) and this file's commit — add `docs/` only:
`git diff --exit-code 7bea35e HEAD -- src tests` → exit 0, so every finding
below holds at the final tip.

## Inputs receipt (all readable, no STOP)

| Input | Value | State |
| --- | --- | --- |
| `main` (local) | `0c711417e8dccd359f11b7e1ec20e2d135d84dd2` | read, never touched |
| `main` (remote, `git ls-remote origin refs/heads/main`) | `0c711417e8dccd359f11b7e1ec20e2d135d84dd2` | identical — unmoved before **and** after integration |
| `fix/fence-delegation` tip | `c24ab9a1c3dfeec45f8de66b5f1e0d1c9c252859` (4 files, +251/−20) | read-only |
| `fix/vault-notes` tip | `afbaaf29fa80d446acdf22233760890c73d9c8df` (2 commits, 4 files, +329/−30) | read-only; shape verified against the task inputs before merging |
| `merge/cfix` entry tip | `0c71141…` | new branch off `main`, clean worktree |
| merge 1 | `8ae9ad46bfefa862b2b7d0c57b1c11353bcfc368` | zero conflicts |
| merge 2 (integration tip) | `7bea35e2c07a05b79298765a01571398005ced37` | zero conflicts; `ort` auto-merged `controller.py` |
| `merge/cfix` on the remote | **absent** (`git ls-remote origin refs/heads/merge/cfix` → empty; `@{u}` → exit 128) | never pushed |

Forbidden-topic scan (`backtest_audit`, `Optimize-my-strategy`) over the
integrated code:
`git grep -i -n -E "backtest_audit|optimize-my-strategy" HEAD -- src tests` →
**0 hits** (exit 1, no output). Changed files `git diff --name-only main..HEAD`
are exactly the two lines' declared sets:

```
src/hermes/persistence/database.py
src/hermes/research/controller.py
src/hermes/vault/projection.py
tests/test_fence_classifier.py
tests/test_notes_dedup.py
tests/test_p_auto_5_vault_production_shapes.py
tests/test_phase1_acceptance.py
```

**No STOP condition fired.**

## Integration integrity (patch-exactness invariants)

| # | Claim | Command | Result |
| --- | --- | --- | --- |
| INV1 | merged tip vs fence tip is exactly the vault patch | `git diff --stat fix/fence-delegation HEAD` | 4 files, 329/30 — vault's stat exactly |
| INV2 | merged tip vs vault tip is exactly the fence patch | `git diff --stat fix/vault-notes HEAD` | 4 files, 251/20 — fence's stat exactly |
| INV3 | merge 2's own deltas vs each parent equal the other line | `git diff --stat HEAD^1 HEAD` / `HEAD^2 HEAD` | 329/30 (vault) / 251/20 (fence) |
| INV4 | non-shared files byte-identical to their owning tip | `git diff --exit-code HEAD <tip> -- <files>` | exit 0 for all 6: fence → `database.py`, `test_fence_classifier.py`, `test_phase1_acceptance.py`; vault → `projection.py`, `test_notes_dedup.py`, `test_p_auto_5_vault_production_shapes.py` |
| INV5 | deterministic merge | `git rev-parse HEAD^{tree}` vs dry-run `merge-tree` tree | both `e2d11b011b7ddea68ec88b7047aa457db16dbe68` |
| INV6 | byte-level patch composition | `patch -p1` in a scratch sandbox | vault controller + fence patch == merged == fence controller + vault patch, byte-identical; sha256 `cf9062cbf179d76a02072755dc78fc8e869fa05f3ff7ab356f0e57d00d4df858`; vault patch applied to the fence file with a uniform +65-line offset, zero fuzz, zero failed hunks |

Hunk disjointness on `src/hermes/research/controller.py` (old-file lines):
fence changed lines 151–152, 477–478 (hunk spans 148–481,
`_FencedConnection`); vault changed lines 923–5350 (12 hunks, `Controller`
body). Gap 478 → 923 (445 lines). `git diff fix/fence-delegation HEAD --
src/hermes/research/controller.py` = vault's 12 hunks (new-side ≥ 985);
`git diff fix/vault-notes HEAD -- src/hermes/research/controller.py` = fence's
3 hunks (148–545). No overlapping changed line; no reordering; no manual hunk.

## Refusal re-scan — no existing refusal flipped (byte-level)

1. **Refusal bytes preserved.** Since merged = fence tip + vault patch (INV6)
   and every differing hunk lies in the vault region (new-side line ≥ 985),
   the fence refusal surface is byte-identical to the certified `c24ab9a`
   implementation: `_FencedConnection._REFUSED_DELEGATIONS`
   (`src/hermes/research/controller.py:499`), `in_transaction` passthrough
   (:514), fail-closed `__getattr__` (:524, refusal at :533), and the
   `release_writer_lock` guard (`src/hermes/persistence/database.py:151`;
   refusal at :198, owner-row check at :208, single shared COMMIT at :225).
2. **Fence battery green at the merged tip** (`fence_fix_probe.py`, exit 0):
   all 11 delegation methods `REFUSED-TypeError` — load_extension,
   enable_load_extension, create_function, create_aggregate, backup, serialize,
   deserialize, set_authorizer, set_progress_handler, set_trace_callback,
   interrupt; `close` / `row_factory` / unknown `REFUSED-AttributeError`;
   udf, serialize, backup all refused; read surface intact
   (`in_transaction False`, `SELECT 42` → 42); foreign-transaction release
   `REFUSED-DatabaseLockError`, in-tx left open, foreign row stays invisible
   (`foreign-999-visible: 0`); acquire → release chain: unasserted release
   refused, asserted release OK (`row: 0`), re-acquire OK.
3. **Classifier battery green** (22 shapes verbatim from the scan's `p4`):
   0 mismatches; `EXPLAIN INSERT` executes nothing (rows stay 1).
4. **No refusal loosened.** The only behavioral flip in this delta is
   permissive → refusing (a strengthening): `p5` (raw pre-fix probe) now
   raises `DatabaseLockError` at `src/hermes/persistence/database.py:199`
   where pre-fix it COMMITted the foreign transaction. The documented
   stale-owner recovery path (fresh connection, `begun=True` at :180/:183)
   is unchanged: unconditional DELETE as before.
   `tests/test_phase1_acceptance.py` only **adds** `owner_id=` assertions
   (7 call sites: :143, :145, :152, :155, :186, :194, :776); the one remaining
   unasserted call at :179 is the fresh-recovery-connection surface, which
   needs no assertion. No assertion was removed or weakened.
5. **Refusal-surface slices green**: `test_fence_classifier.py` 71 passed,
   `test_phase1_acceptance.py` 28 passed, `test_database.py` 22 passed,
   `test_controller.py` 109 passed.

## Vault separation re-proof (seeded counter-proof green at merged tip)

- New gate file `tests/test_p_auto_5_vault_production_shapes.py` (5 tests,
  exit 0) pins the production payload shapes and the type-scoped subject keys
  added by `fix/vault-notes@8b7c050` —
  `src/hermes/vault/projection.py:96-103` (`_CURATED_SUBJECT_TYPES`,
  `_CONTRADICTION_SUBJECT_TYPES`, `_LADDER_SUBJECT_TYPES`,
  `_SOURCE_ARTIFACT_SUBJECT_TYPES`), gated on `row.get("event_type")` at :340
  (`curated:` :345, `contradiction:` :346-349, `ladder:` :350-360,
  `artifact:` :361-365).
- `tests/test_p_auto_5_vault.py` (24 tests) unchanged and green at the merged
  tip.
- Seeded end-to-end counter-proof (`p1.py`, exit 0) at the merged tip, 8 notes
  projected from production-shaped events: `evt-000002-curated-knowledge-admitted.md
  … superseded=True` (the admitted fact is retired by the following
  CuratedKnowledgeInvalidated rather than staying authoritative),
  `evt-000004-contradiction-resolved.md` and
  `evt-000005-contradiction-superseded.md` `superseded=True`,
  `evt-000008-task-invalidated.md authoritative: false`.
  `evt-000006-evidence-transition-applied.md` remains
  `authoritative: true/currently_valid: true` — documented design (no
  production invalidator carries the ladder key today; the fact is at least
  recognized, per the code comment at `projection.py:75-93`), not a leak.
- Note on the probe's first section: it prints `subjects=[]` for hand-built
  rows that carry **no `event_type`** (the type gate at :340 is deliberate);
  those prints are not a counter-proof in either direction. The end-to-end
  section above is the separation evidence.
- Out of scope, unchanged: `_rejects` still reads `payload["verdict"]`
  (C-F-02 is not addressed by this integration; no claim is made).

## Notes healthy-path re-proof

- `tests/test_notes_dedup.py` green (4 passed; +1 test over `main`'s 3).
- `p2.py` at the merged tip: notes bounded per read call — 0 → 1 → 1 across
  two `pending_classification_proposals()` calls on a corrupt event, and
  2 → 2 across two `retracted_source_review_candidates()` calls (stable
  condition keys; C-F-04 held).

## Count lineage

- Full suite at the merged tip: **2693 passed**, 0 failed, exit 0 (567.43s).
- No test deleted or renamed: `git diff --name-status main HEAD -- tests` =
  3×M + 1×A. Delta over the fence-only suite recorded at `c24ab9a`
  (2687 passed) = +6 = new production-shapes file (5 tests) + one new
  notes-dedup test (`main` 3 → merged 4).
- Cross-checks: three fence slices on `fix/fence-delegation` = 121 passed =
  71 + 28 + 22 (identical to merged); `test_database.py` = 22 on `main`
  (untouched); all commands used the shared venv
  with `PYTHONPATH="D:/New folder/research-agent-merge-cfix-wt/src"` and the
  import origin was printed before the gates
  (`…research-agent-merge-cfix-wt\src\hermes\__init__.py`).
- Certified census at the merged tip (raw):
  `executed transaction-control calls 121 (BEGIN 28, COMMIT 27, ROLLBACK 66);
  owners 18 persistence / 5 gateway / 4 Controller (27 total); rollback-only
  participants 1; persistence→research imports 15; control calls outside
  certified layers 0` —
  `PASS - every certified figure is reproduced exactly.` (exit 0).
- Diff lineage: 580/50 overall = fence 251/20 + vault 329/30;
  `controller.py` 112/31 = fence 69/4 + vault 43/27.

## Verdict

**PASS.**

Both tips integrated with zero conflicts and deterministic tree equality;
byte-level patch composition exact; no existing refusal flipped (the only flip
is permissive → refusing, C-F-08, plus the new delegation refusals); vault
separation re-proof and notes healthy-path green at the merged tip; full suite
+ ruff + both pyrights + census green; `main` unmoved before and after;
branch never pushed. No STOP conditions fired.

## Limitations

- `pytest --pythonpath` is not supported by the shared venv's pytest
  (`unrecognized arguments`); the absolute worktree `PYTHONPATH` was used
  instead and the import origin was asserted before every gate.
- `git ls-remote` requires network; it responded at both checks (outputs
  pasted above).
- The C-F-02 refusal-filter finding (`_rejects` reading `payload["verdict"]`)
  is untouched by this integration and remains open; it is not part of this
  delta.
