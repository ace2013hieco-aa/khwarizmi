# Hostile Audit — ADV-02 Generation Fence

**Scope:** attack the generation fencing shipped with the ADV-02 remediation
(`hermes_v6_adversarial_remediation_report.md`) for the same double-write classes:
(1) the write-verb interception in `_FencedConnection`, (2) the same-tick reclaim
path, (3) the cross-connection interleave. Every probe was run against the real
code (`probe_adv02_fence_audit.py` — removed after the run); deterministic clocks,
no sleeps.

**Baseline:** HEAD `9191710` + the F1–F3 hardening of this audit. Full suite
**802 passed**, `uvx pyright src` **0 errors**.

## Verdict: **MERGE WITH REMEDIATION — three latent bypasses found and closed; the interleave surfaces hold.**

---

## Probe P1–P3 — the write-verb interception (statement classifier)

The fence decides whether to run the generation check by classifying the SQL
statement. Pre-fix the classifier was first-token-only
(`sql.lstrip().upper().startswith(("INSERT","UPDATE","DELETE","REPLACE"))`).
All three statement-shape bypasses were **reproduced**, then **closed**:

| Probe | Attack | Pre-fix | Post-fix | Disposition |
|---|---|---|---|---|
| **F1** | `/* comment */ UPDATE …` / `-- comment\nDELETE …` | **BYPASS** — first token is `/*` / `--`, the write landed unfenced | `LockLostError` (fenced) | comment-stripping added before the first-keyword check |
| **F2** | `WITH t AS (SELECT 1) INSERT INTO …` | **BYPASS** — first token is `WITH`, the CTE write landed unfenced | `LockLostError` (fenced) | paren-depth token scan at depth 0 finds the statement verb; `WITH…SELECT` stays a read |
| **F3** | `executescript("INSERT …")` | **BYPASS** — `__getattr__` delegated to the raw connection, the write landed with no attribution at all | **rejected loudly** (`TypeError`, nothing lands) | `executescript` cannot be attributed per statement — fail-closed rejection, no current write path uses it |

Each of the three bypasses is **latent** — no write path in the controller (or in
`repositories.py`/`extraction.py`/`events.py`) uses SQL comments, CTE writes, or
`executescript` today (verified by grep before probing) — but the fence's contract
is "every authoritative write is attributed to the lease generation," and a future
write path using any of the three shapes would have silently re-opened the
stale-live-controller hole. The classifier is now deterministic over SQLite's
dialect and regression-pinned (F1–F3 fixtures + the positive-control fixture
proving the shapes still work while the generation matches and `WITH…SELECT`
reads pass unfenced).

Positive controls verified: plain `UPDATE` still raises on a stale generation
(control); all three shapes **pass** while the generation is valid (not
over-blocked).

## Probe P4 — cross-connection interleave (two real connections, shared file DB)

**SAFE.** Controller A (connection 1) acquires at generation 0; controller B
(connection 2, advanced clock) reclaims the stale lease (generation 1). A's next
authoritative write — inside a `BEGIN IMMEDIATE` transaction on connection 1 —
raises `LockLostError` and rolls back; **no row lands**. B's own fenced write on
connection 2 succeeds (B remains authoritative). SQLite serializes writers, so the
fence check inside A's write transaction cannot be interleaved by B's reclaim; B's
committed reclaim is visible to A's subsequent transaction. The same-connection
case was already pinned by `test_adv02_live_controller_write_fails_closed_after_
reclaim` / `test_adv02_stale_controller_repo_write_raises_lock_lost`; this probe
extends the evidence to separate connections.

## Probe P5 — same-tick RECOVERY-path reclaim

**SAFE.** A acquires; B reclaims mid-tick; A's `_recovery_pass` write (a stale-
RUNNING task → NO_SIGNAL via the fenced repository) raises `LockLostError`. The
task's state is **untouched** (still RUNNING, no NO_SIGNAL, no event) — the
recovery write failed closed, exactly as the dispatch-path writes do. The recovery
pass shares the same fenced repository/connection as the dispatch path, so the
attack surface is uniform.

## Probe P6 — release-in-finally after lock_lost

**SAFE.** After a `LockLostError`, `tick()`'s `finally: self._release_lock()` is a
**no-op** — the DELETE is owner-scoped (`WHERE owner = controller-A`), so A's
release neither raises nor deletes B's lock row (owner B, generation 1 intact).
B's fenced writes continue to work.

---

## What survives (probed, not assumed)

- The cross-connection interleave is airtight: the generation check inside the
  write transaction sees B's committed reclaim, and SQLite's write lock prevents
  any check/write interleave.
- The same-tick reclaim path fails closed uniformly across recovery and dispatch
  writes (single fenced connection for the whole tick).
- Release-after-loss is structurally harmless (owner-scoped delete).
- The classifier hardening does not over-block: valid-generation writes in all
  three statement shapes pass; reads (including `WITH…SELECT`) are unfenced by
  design.

## Changes

- `src/hermes/research/controller.py` — `_FencedConnection` gained
  `_is_write` (comment stripping + WITH-CTE paren-depth scan), the `execute`/
  `executemany` checks use it, and `executescript` is rejected loudly (F3).
- `tests/test_controller.py` — 4 regression fixtures:
  `test_fence_comment_prefixed_write_fails_closed`,
  `test_fence_with_cte_write_fails_closed`,
  `test_fence_executescript_rejected_loudly`,
  `test_fence_classified_shapes_work_while_lock_valid`.

**802 passed** (798 + 4), pyright 0 errors. The fence now survives this audit;
the documented residual (full PA7 fencing, deferred per v6 §22) is unchanged.
