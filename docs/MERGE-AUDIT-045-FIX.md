# MERGE-AUDIT-045-FIX — adversarial audit of `merge/idr045-fix@b52dd9c`

**Role:** Adversary, fresh independent session. Falsify, do not confirm.
**Audited:** `merge/idr045-fix@b52dd9c6ca4c14bf9e44fc02b07505c2ab1295b2`
(merge `beed3cf` + `docs/MERGE-LOG-045-FIX.md`)
**Audit's branch:** `merge/audit-fix045` (from the integration tip), local-only, no push.
**Baseline:** `main@c2c8fa990a56d2ca4b980fb62680dc058f294b94`
**Prior FAIL verdict being re-tested:** `docs/MERGE-AUDIT-045.md` @ `84665d2`

## Inputs — receipt confirmed, all readable

| # | Input | Hash | Read |
|---|---|---|---|
| 1 | `merge/idr045-fix` tip (merge + `MERGE-LOG-045-FIX.md`) | `b52dd9c` | yes — 7 files, incl. the 11 856-byte log |
| 2 | `merge/fix-045` (the fix) | `87af69682131c208faae1dcd24a298e1299ab815` | yes |
| 3 | `docs/MERGE-AUDIT-045.md` (prior FAIL) | `84665d22788c443f9c3b68079a570aa301f191e6` | yes — 31 686 bytes |
| 4 | `main@c2c8fa9` live baseline | `c2c8fa990a56d2ca4b980fb62680dc058f294b94` | yes |

**No STOP condition on receipt.**

**Forbidden-topic scan** (`backtest_audit|SDA|TSE|Optimize-my-strategy`) over
`git log -p c2c8fa9..b52dd9c`: no hits. Nothing to report.

## VERDICT: **PASS WITH CONDITIONS**

Both named blockers are **closed**, proven by executed probes I wrote and ran
against the audited tree — not by reading the fix commit message, the IDR, or
`MERGE-LOG-045-FIX.md`. Merge fidelity is exact, every gate reproduces, and no
certified invariant is weakened.

The conditions are a **residual of the first blocker's own defect class**, found
by attacking the new code rather than the old: the pre-write bounds check is
**length-only**, so a provenance value that is within its length bound but is not
a `str` still reproduces the *exact* original F2 signature — durable row, zero
`IntentApplied`, zero `IntentRejected`, an error surfaced to the caller instead
of a refusal. One line closes it. This is why the verdict is not a clean PASS,
and why it is not a FAIL either (§5 explains the boundary).

---

## 0 — Import-resolution proof (the trap has bitten twice; recorded as required)

**The trap is live in this repo, not hypothetical.** The shared
`D:\New folder\research-agent\.venv` carries an editable install pointing at
`D:\New folder\research-agent\src`. Running any Python from a worktree without
`PYTHONPATH` silently imports the *root checkout's* code, not the worktree's.

**Isolation:** a dedicated worktree at a **fresh** path
(`%LOCALAPPDATA%\Temp\opencode\auditfix045`), so no `__pycache__` from any prior
session could be reused. `PYTHONPATH` pinned to that worktree's `src` for every
command. The discriminator below is the audited function itself.

```
A) TRAP DEMO — cwd = worktree, PYTHONPATH NOT set:
     hermes    : D:\New folder\research-agent\src\hermes\__init__.py
     gateway   : D:\New folder\research-agent\src\hermes\research\gateway.py
     has _require_provenance_bounds: False        <-- audited code ABSENT

B) With PYTHONPATH = <worktree>/src:
     hermes    : ...\auditfix045\src\hermes\__init__.py
     gateway   : ...\auditfix045\src\hermes\research\gateway.py
     controller: ...\auditfix045\src\hermes\research\controller.py
     has _require_provenance_bounds: True
```

**Stale-bytecode elimination.** After (B) the tree held 39 `.pyc` / 7
`__pycache__` entries. All were purged (→ 0) and the audited probes were then run
with `python -B`, so no compiled artefact could mask a source difference.

**Source/audit-commit equality** (authoritative — bytecode cannot change these):
every audited file's worktree blob equals its blob at `b52dd9c`:

| File | Blob | Status |
|---|---|---|
| `src/hermes/research/gateway.py` | `441a24b8958a…` | MATCH |
| `src/hermes/research/controller.py` | `ef636ff6c4df…` | MATCH |
| `src/hermes/research/programs.py` | `5aeaeb9d9f62…` | MATCH |
| `src/hermes/core/intents.py` | `d9037376543d…` | MATCH |
| `tests/test_idr045_merge_audit_045.py` | `acb0f2a05d88…` | MATCH |

`git status --porcelain` clean. No ambiguity remains.

---

## 1 — BLOCKER RE-PROBE 1: F2, bounds enforced pre-write — **CLOSED**

Re-ran the original `MERGE-AUDIT-045` probe shape (a `__post_init__`-bypassing
`Intent`, the same precondition the audit used).

| | `e5d4fb1` (defect) | `b52dd9c` (audited) |
|---|---|---|
| task row committed | **True** | **False** |
| `TaskCreated` | 1 | **0** |
| `IntentApplied` | 0 | **0** |
| `IntentRejected` | **0** | **1** |
| escaped | `GatewayRejection(MALFORMED_PAYLOAD)` | `GatewayRejection(MALFORMED_PAYLOAD)` |

Escaped refusal, verbatim:
`Intent rejected (ADMIT_TASK): origin_ref exceeds max length 64: 65`

All five bounded fields, each with zero rows and exactly one journalled
rejection:

```
origin_ref               lim=64   GatewayRejection  MALFORMED_PAYLOAD  rows=0 TC=0 IA=0 IR=1
model_ref                lim=128  GatewayRejection  MALFORMED_PAYLOAD  rows=0 TC=0 IA=0 IR=1
run_id                   lim=64   GatewayRejection  MALFORMED_PAYLOAD  rows=0 TC=0 IA=0 IR=1
prompt_template_version  lim=32   GatewayRejection  MALFORMED_PAYLOAD  rows=0 TC=0 IA=0 IR=1
charter_version          lim=32   GatewayRejection  MALFORMED_PAYLOAD  rows=0 TC=0 IA=0 IR=1
```

Control (in-bounds `origin_kind`/`origin_ref`): `TaskCreated=1`,
`IntentApplied=1` — the guard did not over-reject.

**The defect site is gone, not merely supplemented.**
`test_no_post_write_bounds_guard_remains` asserts `_append_audit_event` contains
neither `ORIGIN_REF_MAX_LENGTH` nor `MALFORMED_PAYLOAD`. I confirmed the ordering
mechanically: the bounds call is at `gateway.py:4060`, the first validator
dispatch at `:4071` — the check precedes every validator, so no validator can
commit a row first.

**F2 as named is closed. The class is not — see C1.**

## 2 — BLOCKER RE-PROBE 2: plan-pass failure discipline — **CLOSED**

All three mandatory cases constructed and executed, with the original silent
signatures beside the new ones.

| Case | `e5d4fb1` (silent) | `b52dd9c` (audited) |
|---|---|---|
| corrupt primary head | 0 notes, journal unchanged | **1 note** naming the head, the exception type and the value |
| `KeyError` in gateway at payload 3 | **zero trace** | **1 note**, `FAULT KeyError` — distinct from a refusal |
| deterministic refusal at payload 3 | silent 2/9 DAG | **1 note**: `2 of 9 … 7 refused [… DEPENDENCY …]` |

Verbatim notes:

```
plan admission skipped: primary head rp_65d70305b768fed783cdf894 does not parse as a
  compiled program (ValueError: 'NOT_A_LADDER_TARGET' is not a valid LadderTarget) — the
  plan is unavailable until the head is repaired

plan admission INCOMPLETE for program rp_65d70305b768fed783cdf894: 2 of 9 plan task(s)
  newly admitted, 7 refused [rp-65d70305-gate-adversarial -> FAULT KeyError: …]
```

The `KeyError` case is recorded as `FAULT`, not as a refusal — so "refused" can
never be read as "crashed". Confirmed: `FAULT recorded distinctly: True`.

**Negative controls — a note always means a failure:**

| Path | Admitted | Notes |
|---|---|---|
| clean admission | 9/9 | **0** |
| idempotent 2nd pass | 0 new | **0** |
| cold start (no program) | 0 new | **0** |

**Adversarial — are the notes a dead channel?** The prior defect's force came
from being invisible. `Controller.notes` has exactly one consumer outside the
class: `cli.py:495` `notes = list(ctrl.notes)` → `cli.py:511-512` prints each as
`note: <text>`, on the `hermes run` path that calls `ctrl.run()` → `tick()`. I
checked for a daemon/loop that would run `tick()` while dropping notes: there is
**no** daemon, loop, service or runner module, and `tick()` has exactly one
caller (`controller.py:636`, inside `run()`). The only other `Controller` use is
`cli.py:609 resolve_human_gate`, which does not run plan admission. **The notes
reach the operator on every path that can produce them.**

**Adversarial — can a still-silent outcome survive?** I probed the boundaries of
the new try-blocks:

- the `row = conn.execute(...)` head read is **not** guarded → a DB failure
  propagates out of the pass and out of the tick. That is **fail-closed**
  (loud), not silent, and it is unchanged from `e5d4fb1`. Not a finding.
- `plan_to_payloads(...)` is **not** guarded → same: fail-closed, unchanged.
- the per-payload `Intent(...)` construction is outside the loop's `try` → same:
  fail-closed, unchanged.

So the only unguarded paths crash, and crashing is the safe direction.

**Blocker 2 is closed.** Its growth guard is incomplete — see C4.

## 3 — Merge fidelity: **PASS** (mechanically replayed)

```
c2c8fa9 (baseline)  tree 5428ab75482c6a4753f3fe2176a5d24c2f391112
87af696 (integrand) tree c94a303f4b3866c6de78b81dc49ba04f3076d5bb
beed3cf (merge)     tree c94a303f4b3866c6de78b81dc49ba04f3076d5bb   <- identical
b52dd9c (tip)       tree ffcc835f96129ba140135332a5cb3fd1e20fa5d2
```

- `git diff beed3cf 87af696` → **empty**: the merge commit's tree is
  byte-identical to the integrand. There is no room for a hand-edit, a dropped
  hunk, or a resolution choice.
- `b52dd9c` adds exactly one file: `docs/MERGE-LOG-045-FIX.md` (+224). No code,
  no test, no `src/`.
- `merge-base(c2c8fa9, 87af696) == c2c8fa9`, so the integrand is a strict
  descendant — the zero-resolution claim is structurally true, not merely asserted.
- The zero-resolution claim in `MERGE-LOG-045-FIX.md` is **honest**, and I
  re-derived it rather than accepting it. The 7 integrated commits are
  `96c52e7`, `7695c0c`, `34dd717`, `779d25f`, `e5d4fb1`, `84665d2`, `87af696`.

**Honesty check on the log's own claims.** `MERGE-LOG-045-FIX.md` states the
`test_research_program.py` warning is pre-existing. That file *is* inside the
integrated set, so non-inclusion would not have sufficed; the log instead proves
it by an empty diff. I re-verified independently: `git diff c2c8fa9 87af696 --
tests/test_research_program.py` is empty and line 144 is byte-identical in both
revisions. The claim holds, and it was made honestly.

## 4 — Cross-line interactions

**Intent fields × validators / repositories — one real behaviour change.**

The pre-write check sits between `_require_project` (`gateway.py:4055`) and
`budget_check` (`:4064`), so **refusal-code precedence changed**. Executed:

| Intent | `e5d4fb1` | `b52dd9c` |
|---|---|---|
| oversized **and** budget-rejected | `BUDGET` | **`MALFORMED_PAYLOAD`** |
| budget-rejected only | `BUDGET` | `BUDGET` (unchanged) |

Not a defect — refusing a malformed intent before spending a budget hook is
defensible, and no code regresses — but it is an **undocumented, untested
refusal-code precedence change** on the certified single mutation path. See C3.

**Plan pass × ladder / dispatch / tick — unchanged.** Ordering on the integration
tip is byte-identical to `e5d4fb1` (`git diff` over those call sites is empty):

```
573: if mode is not OperationalMode.ACTIVE:      <- ACTIVE-only gate
587: self._plan_admission_pass()
592: self._apply_evidence_ladder_pass()
605: self._detect_contradictions_pass()
612: result = self._dispatch_pass()
```

Still after the mode gate, still before ladder and dispatch. Correct.

**V1 ("provenance never authority") — re-verified independently, not trusted.**
The fix widened the grep-guard's allowlist to admit its new
`_require_provenance_bounds` reader. A widened allowlist is exactly the kind of
change that silently disarms a security guard, so I re-ran the non-vacuity test
myself rather than believing the prior session's claim:

```
readers now           : ['<module>', '_append_audit_event', '_require_provenance_bounds']
within allowlist      : True
+ injected 4th reader : [ …, '_sneaky_reader' ]
negative still caught : True
```

A fourth `origin_*` reader still fails the guard. The allowlist is exact, not a
blanket. V1 holds.

## 5 — Gate integrity: all four re-run by me, plus census

Every gate executed on the audited worktree with the §0 import proof in force.

| Gate | Result |
|---|---|
| `scripts/run_tests.py -v` (full) | `2267 passed in 373.01s (0:06:13)` |
| `uvx ruff check src tests` | `All checks passed!` |
| `uvx pyright src` | `0 errors, 0 warnings, 0 informations` |
| `uvx pyright --project pyrightconfig.tests.json` | `0 errors, 1 warning` — `test_research_program.py:144` `reportSelfClsParameterName` |
| `scripts/check_census.py` | `PASS - every certified figure is reproduced exactly` |

Census: 121/121 control calls · owners 18/5/4 = 27 · rollback-only 1 ·
persistence→research imports 15/15 · control calls outside certified layers 0.

**Nothing was trusted from the fix report or the integration log.** The full
suite reproduces the 2267 the integration claimed, from an independent tree, with
independent import resolution.

**Architectural invariants re-checked on the mainline reading:** single mutation
path holds (the pass writes only via `apply_intent`; its only direct SQL is a
`SELECT`); no `DELETE` introduced; DG-5 census unchanged; S6 payload discipline
intact for the bounded fields; lease fence untouched (the pass adds no lock
surface and runs inside the already-fenced tick); content-hash identity and
N1/N9 fencing untouched.

## 6 — F3 / F4 carry-forward: honest, and findable

Neither open item was buried. Five independent surfaces, all verified present:

| Where | What |
|---|---|
| `docs/idr/IDR-045.md:97` | `**Known gap, not closed here (F3):**` — the fence compares only `evidence_requirements` |
| `docs/idr/IDR-045.md:80` | `but it has **no production caller**` — F4 |
| `docs/idr/IDR-045.md:370` | response table: `F3 … **Open, recorded**` |
| `docs/idr/IDR-045.md:369` | response table: `F4 … **Corrected, not refactored**` |
| `src/hermes/research/controller.py:4128` | code comment at `_expected_gates`, i.e. **where a maintainer editing the fence will hit it** |
| `ROADMAP.md:56` | the open-decisions bullet |

The last one matters most for discoverability: an open item documented only in
prose is easy to miss, but F3 is annotated in the source at the exact line where
the unused `expected_gates` value is destructured, so the next person to touch
the fence meets it. `MERGE-AUDIT-045.md:501` retains the original finding.

F3's own record states the one-clause fix. I verified the surrounding facts
independently: `task_plan.py:130-131` selects gates from
`program.gate_requirements`, and `repositories.py:1376-1379` validates both
obligations on write — so only hand-written rows are exposed, and C1/Q7
filtered-head semantics are unaffected either way.

**Neither F3 nor F4 is a blocker**, and I agree with leaving them open: both are
eligibility/de-duplication changes, not correctness defects, and closing them
here would have been scope absorption.

---

## 7 — Conditions

Ordered; **C1 is the one that should be dispositioned before this reaches main.**

**C1 (high) — the pre-write guard is length-only, so the F2 defect class
survives in a new form.** `_require_provenance_bounds` calls `len(value)` with
no `isinstance` check. A value inside its bound but not a `str` passes the guard
and reaches the post-commit audit append. Executed proof — a `Sized` object
(`__len__() == 4`, within `run_id`'s bound of 64, not JSON-serialisable):

```
outcome        : TypeError: Object of type Sized is not JSON serializable
task row       : COMMITTED
TaskCreated / IntentApplied / IntentRejected : 1 / 0 / 0
>>> F2 SHAPE (durable row, no IntentApplied): True
```

That is the original signature reproduced: a durable mutation, **no** journal
audit row at all, and an error surfaced to the caller instead of a refusal. The
reachability precondition is identical to the one the fix explicitly hardened
against (`__post_init__` bypass), so the hardening does not actually cover its
own stated threat model.

*Fix (one line, mirrors what `Intent.__post_init__` already does):* add
`if not isinstance(value, str): raise _reject(…, MALFORMED_PAYLOAD, …)` to
`_require_provenance_bounds`, ahead of the length test. Then extend
`TestF2BoundsArePreWrite` with a non-`str` case. I confirmed none of the fix's
17 test functions covers a type case — the suite exercises oversized lengths only.

**C2 (medium) — non-`str`, JSON-serialisable values are applied unvalidated.**
`model_ref={'k':'v'}` and `origin_ref=['a']` both **apply with a row written**
(`rows=1, IntentApplied=1, no refusal`): `len()` is 1, well inside the bound, and
the type is never checked. A container lands in the `IntentApplied` payload. The
4 KiB and secret scans still apply so this is contained, but it is the same
missing type check as C1 and is fixed by the same line.

**C3 (medium-low) — non-`str` without `__len__` raises a bare `TypeError` out of
`apply_intent`.** `origin_ref=12345` → `TypeError: object of type 'int' has no
len()`, not a `GatewayRejection`. Every documented caller pattern is
`except GatewayRejection`, so this escapes the structured-refusal contract on the
single mutation path. Same one-line fix as C1.

**C4 (low-medium) — the note growth guard is message-keyed and defeatable.**
`_note_once` suppresses *identical* strings, and `Controller._notes` is never
cleared. A persistent fault whose message varies per tick therefore grows `_notes`
without bound. Executed: 200 ticks of **one** fault whose message embeds a CPython
object address (`TypeError: unsupported operand: <Sized object at 0x…>`, a very
common real shape) → `notes = 200`, `unique = 200`. A stable fault (corrupt head)
correctly stays at 1 note over 50 ticks. The fix's own
`test_notes_are_not_duplicated_across_ticks` only exercises the stable-message
case, so it gives false assurance that growth is bounded — the record's phrase
"`_note_once` prevents unbounded growth" is true only for stable messages.
*Fix:* key the dedup on a condition identifier (e.g. the program id + failure
kind) rather than the full rendered text, or cap/round-robin the list.

**C5 (low) — undocumented refusal-code precedence change.** C-item detail in §4:
`MALFORMED_PAYLOAD` now precedes `BUDGET`. Defensible, but it should be recorded
in the IDR and pinned by a test, not discovered later.

**C6 (informational) — two unguarded steps in the pass.** The head read and
`plan_to_payloads` are outside any `try`, and the per-payload `Intent(...)` is
outside the loop's `try`. All three **propagate** — fail-closed and unchanged
from `e5d4fb1` — so this is not a silent-swallow regression. Recorded only so the
next reader does not assume the pass is total.

### Why PASS WITH CONDITIONS and not FAIL, and not clean PASS

Not a FAIL: both blockers the FAIL audit named are demonstrably closed with
executed proof; no gate is red; merge fidelity is exact; no certified invariant
is violated; nothing is worse than `e5d4fb1` on any reachable production path.
Not a clean PASS: C1 shows the *class* behind blocker 1 — a durable mutation with
no journal record, surfaced as an error — is still open through the same
precondition the fix hardened, and the fix's own suite cannot see it. That is a
material, cheap-to-close gap, and it should be dispositioned rather than merged
on the strength of the narrower test.

## 8 — Method, and what I did *not* trust

- Both blockers re-probed with probes I wrote and ran here, against the audited
  tree: `reprobe1.py` (F2, incl. all five fields), `reprobe2.py` (three mandatory
  plan-pass cases + 3 negative controls + 5 adversarial probes),
  `reprobe2a.py` (C4), `reprobe3.py` (precedence + non-`str`),
  `reprobe4.py` (C1/C2/C3). All live in `%LOCALAPPDATA%\Temp\opencode\`, all run
  with `python -B` and a pinned `PYTHONPATH`; each prints its own import proof.
- Merge fidelity derived from the object database (`^{tree}` equality, diffs), not
  from `MERGE-LOG-045-FIX.md`.
- The V1 guard's non-vacuity re-tested by injecting a fourth reader myself,
  rather than relying on the prior session's assertion that it had done so.
- Not trusted: the fix commit message, `docs/MERGE-LOG-045-FIX.md`'s gate table,
  `docs/IDR45-impl-audit.md`'s PASS, and the F-closure table in the IDR. Every one
  of those claims that I re-derived held up — including the honest
  `test_research_program.py` proof — but they were re-derived, not believed.
- Constraints honoured: read-only except this file. No `src/`, `tests/`, or other
  `docs/` edit. No push. Isolation via a dedicated worktree at a fresh path.
  Other sessions' worktrees, branches and checkouts were read-only; the root
  checkout belongs to another session and was not touched. `main` and
  `origin/main` both verified still `c2c8fa9` after all work.
