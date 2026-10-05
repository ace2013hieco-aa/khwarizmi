# MERGE-AUDIT-045 — adversarial audit of `merge/idr045@e5d4fb1`

**Role:** Adversary, fresh independent session.
**Audited branch:** `merge/idr045` @ `e5d4fb191688fce0271a1075d680fcb5db605693`
**Merge commit:** `779d25fb10ab3961ef86901e3f872b2f4961cc6d` (parents `c2c8fa9` + `34dd717`)
**Live baseline:** `main` @ `c2c8fa990a56d2ca4b980fb62680dc058f294b94`
**Audit branch:** `merge/audit-045` (from `e5d4fb1`), local-only, no push.

## Inputs — receipt confirmed

| # | Input | State |
|---|---|---|
| 1 | `merge/idr045@e5d4fb1` full file list (read from the repo) | read — 11 files, listed in §1 |
| 2 | `MERGE-LOG-045.md` at `e5d4fb1` | read (65 lines) |
| 3 | live `main@c2c8fa9` baselines for every touched file | read — diffed per file |

No STOP condition on input receipt. `main` was **not** modified: all work ran in a
throwaway `git worktree` at `%LOCALAPPDATA%\Temp\opencode\audit045`, so no `src/`,
`tests/`, or `docs/` file in any checkout was edited. This file is the only addition.

**Forbidden-topic scan** (`backtest_audit|SDA|TSE|Optimize-my-strategy`) over
`git log -p main..merge/idr045`: no hits. Nothing to report.

## VERDICT: **FAIL**

Not because the merge was done badly — **it was done perfectly** (§1, byte-exact),
and every gate is green (§3). It fails on two things:

1. **The merged payload introduces a post-commit refusal/audit hole into the single
   mutation path** and the record describes it as the opposite (§2.1, §2.2), plus
   five silent swallow points that make plan-admission failure invisible (§2.3).
2. **The IDR-045 record is not trustworthy as merged**: two unfilled placeholders, a
   claimed code change that never landed, a falsified "pure inverse" claim, three
   cited evidence artifacts absent from the tree, and a ratified Q-answer recorded
   only in `ROADMAP.md` (§5).

Ships-to-main should be blocked until the two `FAIL` items are dispositioned.

---

## 1 — Merge fidelity: **PASS** (independently replayed, not taken from the log)

**Replay.** `git merge-base e5d4fb1 main` = `c2c8fa9` = `main` HEAD ⇒ `main` is an
**ancestor** of `e5d4fb1`; the integration is a single `--no-ff` of the line tip
`34dd717` into the fork point.

```
34dd717^{tree} = 0608124c37b26b4fc29a916f885f2d8e2fd23501
779d25f^{tree} = 0608124c37b26b4fc29a916f885f2d8e2fd23501   <- identical
git diff 34dd717 779d25f  ->  empty
git diff 779d25f  e5d4fb1  ->  docs/MERGE-LOG-045.md only (+65)
```

The merge commit's tree is **byte-identical to the line tip**. There is therefore
**no room for a hand-edit, a resolution choice, or a dropped hunk** — the claim
"zero conflicts, zero resolutions" is true and stronger than stated: there were no
merge decisions to make. `e5d4fb1` adds only the log file.

Line history is strictly linear on top of the baseline: `96c52e7` (feat) →
`7695c0c` (impl audit) → `34dd717` (roadmap closeout) → `779d25f` (merge) →
`e5d4fb1` (log).

**Changed-file list (11), verified against `git diff --stat c2c8fa9 e5d4fb1`:**

| File | Δ | Note |
|---|---|---|
| `ROADMAP.md` | +6/-0 | closeout note + Catalyst entry + open-decisions |
| `docs/IDR45-impl-audit.md` | +105 | new |
| `docs/MERGE-LOG-045.md` | +65 | new (at `e5d4fb1`) |
| `docs/idr/IDR-045.md` | +231 | new |
| `src/hermes/core/intents.py` | +52/-7 | D2 provenance fields + `__post_init__` |
| `src/hermes/persistence/repositories.py` | +19 | `current_primary` |
| `src/hermes/research/controller.py` | +103 | `_plan_admission_pass` + 2 DIRECTOR origin sites |
| `src/hermes/research/gateway.py` | +52/-6 | C5 length guard + conditional provenance append |
| `src/hermes/research/programs.py` | +76 | `program_from_dict` |
| `src/hermes/research/task_plan.py` | +10/-2 | docstrings |
| `tests/test_idr045_plan_admission_and_provenance.py` | +665 | new, 26 tests |

The list in `MERGE-LOG-045.md` matches exactly (10 line files + the log = 11). No
file added, dropped, or renamed relative to the log.

**Finding F0 (cosmetic, content — not merge-induced).** The merged tree carries
encoding rot the log does not record: `src/hermes/research/task_plan.py` has **3**
mojibake em-dashes (U+00E2 U+0080 U+0094 — 6 C1 control chars) at lines 9 and 264,
where U+2014 was intended.

```
worktree clean (git status --porcelain empty)
worktree blob  = e52589bd54e6ece2ab2d9054007c329daa6f48c9
committed blob  = e52589bd54e6ece2ab2d9054007c329daa6f48c9   <- in the commit
main@c2c8fa9    = 9e1cf61a96cbe49ba39d4a86add363de999a19c7   (C1 count = 0)
```

Introduced at `96c52e7`, carried through unchanged. Confined to this one file (all
other 10 touched files: 0 C1 chars). Comment/docstring only, so no behavioural
effect — but it is shipped source rot that four green gates do not catch.

---

## 2 — Cross-cutting interactions

### 2.1 Ordering: plan pass vs ladder / dispatch / tick — **claim right, rationale invented**

`controller.py:574` `self._plan_admission_pass()` sits exactly where D1.1 says:

| Line | Gate |
|---|---|
| 509 | `_recovery_pass` (every mode) |
| 516–559 | AWAITING_HUMAN self-heal / ACTIVE self-heal (early `return` at 556) |
| 560–564 | `if mode is not OperationalMode.ACTIVE: return` ← **ACTIVE-only confirmed** |
| **574** | **`_plan_admission_pass()`** |
| 579 / 592 / 599 | `_apply_evidence_ladder_pass` / `_detect_contradictions_pass` / `_dispatch_pass` |

Inside the already-fenced tick, after self-heal, before ladder and dispatch. Correct.

**Finding F1 — the stated *reason* cites a mechanism that does not exist.** IDR
D1.1: "before the evidence-ladder / dispatch passes, **so plan tasks exist as PENDING
when readiness is computed**." There is no readiness computation in `tick()`:

```
$ git grep -n "readiness" -- src
src/hermes/core/graph.py:27   """Result of a readiness check for a task node."""
src/hermes/core/graph.py:45   """Determine readiness for a task given its dependencies' statuses.
src/hermes/research/controller.py:4059  plan tasks exist as PENDING when readiness is computed.  <- the new docstring itself
```

`readiness` occurs **once** in `controller.py` — in the docstring this change
introduced. The placement is defensible on its own terms; the justification is not
real and should not be inherited by later IDRs that cite D1.

### 2.2 D2 provenance vs the existing gateway: **FAIL — new post-commit refusal hole**

**Finding F2 (headline).** The C5 per-field length guard added at
`gateway.py:_append_audit_event` is the **only** enforcement point that produces a
`GatewayRejection`, and it runs **after the durable write**, not before.

`_validate_insert_task` performs the write (`task_repo.create(node)`,
`gateway.py:3919`) inside the admission `try`. Only then does `apply_intent` call
`_append_audit_event(conn, clock, intent, applied=True)` at `gateway.py:4064`.

Executed probe (read-only, outside the repo; defeats `__post_init__` the same way
`docs/IDR45-impl-audit.md` §4 documents):

```
escaped GatewayRejection: code='MALFORMED_PAYLOAD'
  reason=Intent rejected (ADMIT_TASK): origin_ref exceeds max length 64: 65
  [after oversized refusal]
    task row committed      : True
    IntentApplied rows      : 0
    IntentRejected rows      : 0
    TaskCreated rows        : 1
```

A durable task row is committed, **`TaskCreated` is written, and *no* `IntentApplied`
or `IntentRejected` row exists** — the caller is told the intent was refused. This is
a durable mutation with no journal record, surfaced as a refusal.

Both escapes are silent for the operator: the `except GatewayRejection:` handler at
4057 calls `_append_audit_event(applied=False)`, but the raise originates *inside*
`_append_audit_event`, so that handler is never reached.

The record and the code comment both claim the opposite:

- `docs/idr/IDR-045.md:127-129` — "an oversized field **refuses before** the 4 KiB
  check"; "Keeps the 4 KiB event cap (S6)". It refuses *after* the write.
- `gateway.py:4083-4085` — "enforced here pre-`validate_payload_size` so an oversized
  field is refused … rather than a generic size error." Pre-*size-check*, yes;
  not pre-*write*.
- `AGENTS.md` (non-negotiable) — "oversized verdicts refuse with `RATIONALE`
  **before any write**." The new guard does not.

**Honest scoping.** The *class* of post-commit raise pre-exists: the 4 KiB
`validate_payload_size` (`event_validation.py:150`) is likewise reached only from the
post-commit audit append. The merge therefore does not invent the hazard — but it
(a) **adds a new instance of it inside the single mutation path**, and (b) ships a
record that mischaracterises its own guard as pre-write, so a later reader will
believe the write is protected when it is not. The guard belongs in `apply_intent`
before dispatch to the validator (or in `__post_init__` only, where it already is).

**Also note the guard's stated threat model does not type-check.** The comment says
it exists "for callers that bypass that path (e.g. a manually constructed dict)".
`_append_audit_event` takes an `Intent`, and `apply_intent:3988` raises
`TypeError` for a non-`Intent`. The only real bypass is frozen-dataclass
`object.__setattr__`. `docs/IDR45-impl-audit.md` §57 correctly found *that* path and
verified the refusal fires — but did not check the ordering, which is why F2 slipped
through both audits.

### 2.3 `_plan_admission_pass` swallows every outcome — **FAIL**

`controller.py` gains **5** new swallow points (baseline `main` had 14
`except Exception` in this file; merged has 18):

| Line | Handler | Records anything? |
|---|---|---|
| 4081 | `except Exception: return []` (row→dict) | no |
| 4085 | `except Exception: return []` (`program_from_dict`) | no |
| 4094 | `except Exception: return []` (obligation derivation) | no |
| 4113 | `except GatewayRejection: continue` | code + reason **discarded** |
| 4123 | `except Exception: continue` (around `apply_intent`) | no |

The 14 pre-existing handlers are annotated `fail-closed`, `audit, never silent`,
`detector failure`, `task vanished mid-recovery` — several explicitly record. The
four new ones are annotated "plan admission never crashes the tick" and record
**nothing**. This is a deliberate fail-open posture that is nowhere documented as a
hazard and is inconsistent with the surrounding file.

**Executed evidence — invisible failure (P3).** Corrupt the primary head's
`hypotheses` JSON so it cannot be parsed, then run the pass:

```
admitted ids returned      : []
tasks in DB                : 0
journal rows before/after  : 1 / 1        <- unchanged
refusal recorded anywhere  : False
NOTE appended              : []
```

Zero journal rows, zero notes. A persistently corrupt primary head yields an
indefinitely idle, silently-failing system.

**Executed evidence — internal errors are indistinguishable from refusals (P4c).**
Raise a plain `KeyError` inside the per-payload `apply_intent` call at position 3:
**zero trace** — no row, no note, no counter. The pass cannot distinguish
*refused* / *crashed* / *done*.

**Correction to the obvious claim (P4b) — and the real finding.** A
`GatewayRejection` raised *by* `apply_intent` **is** journalled, by `apply_intent`
itself. A deterministic mid-pass refusal at position 3 of 9 yields:

```
admitted ids returned : 2
tasks in DB           : 2      (clean plan = 9)
IntentApplied rows    : 3
IntentRejected rows   : 6      <- 1 root + 5 dependency consequences
controller notes      : []
outward tick() result : TickResult(idle='waiting_human',
                      dispatched=['rp-65d70305-gate-hypothesis'], ...)
```

So the journal is *not* empty. The defect is the **aggregate**: a permanently
partial 2/9 DAG whose outward tick result is *indistinguishable from a healthy wave
parked at a human gate*. `TickResult` carries no field for "plan admission fell
short", no note is emitted, and each subsequent tick re-emits the same 6
`IntentRejected` rows — an append-only journal that grows without converging. IDR
D1.5's "observable no-op" and D1.2's "uncompiled → observable no-op" do not hold
for any of these paths.

**Dangling-comment inconsistency.** The docstring promises "Returns the admitted
task_ids **for observability**", the caller at line 574 discards the return value,
and the same docstring then says "callers read recovery/task state via the DB, not
this return". Three mutually cancelling statements about the same return value.

### 2.4 The compiler-fence checks half of what it claims

**Finding F3.** IDR D1.2: eligibility requires the head "is a compiler-derived
program (its `evidence_requirements` re-derive from its `hypotheses` via
`derive_program_obligations`)". `derive_program_obligations` returns **both**
obligations; `controller.py:4090-4093` compares only the first and discards
`expected_gates`. `gate_requirements` is not cosmetic — `task_plan.py:130-131`
selects the gates from it:

```python
human_gates     = [g for g in MANDATORY if g in program.gate_requirements]
integrity_gates = sorted(set(program.gate_requirements) - set(MANDATORY))
```

Executed: tampering `gate_requirements` to `('NOT-A-REAL-GATE',)` still passes the
fence (`evidence fence still passes: True`), so a divergent `gate_requirements`
yields a different admitted DAG without detection.

**Mitigation, stated fairly:** `repositories.py:1376-1379` validates *both*
obligations on write, so repository-written rows are consistent and the live path is
protected. The exposure is precisely the fence's stated purpose — hand-written /
fixture rows that never went through the repository. A one-line fix
(`or rt.gate_requirements != expected_gates`) closes it.

### 2.5 `current_primary` has **zero production callers**

**Finding F4.** `repositories.py:1711` `current_primary` is referenced only by
`tests/test_idr045_plan_admission_and_provenance.py` (7 sites). The production path
is an **inline duplicate of the same SQL** at `controller.py:4073-4077`:

```
SELECT * FROM research_programs WHERE project_id = ?
AND parent_program_id IS NULL ORDER BY version DESC LIMIT 1
```

So the commit message's "C1 via `ResearchProgramRepository.current_primary`" and
`ROADMAP.md:56`'s "via `current_primary`" are both **false for the production
path**; the new repository method is test-only surface. The logic is correct
(C1 genuinely holds — verified by the impl audit's live run and by the 26 tests), but
the duplication means the two copies can drift, and the public helper the record
cites as the mechanism is not the mechanism.

Credit where due: `docs/IDR45-impl-audit.md:20` is the *only* document that states
this accurately ("inline query … same literal, not `current()`"). The overclaim is
in the commit message, the IDR (D1.2, which offers both), and ROADMAP.

### 2.6 `program_from_dict` is **not** the inverse of `program_to_dict`

**Finding F5.** `docs/idr/IDR-045.md:216-217`: "`programs.program_from_dict` **is the
pure inverse** of `program_to_dict` at the same trust boundary." Executed round-trip
on a real compiler-produced program:

```
roundtrip(from row) == roundtrip(program_to_dict) : False
  program_id   'rp_65d70305b768fed783cdf894'  DRIFT -> ''
  project_id   'p1'                           DRIFT -> ''
  (all 20 other fields OK; hypotheses/predictions/evidence/gates round-trip)
```

`program_to_dict` excludes `program_id`/`project_id` (identity metadata, kept out of
the content hash), and `program_from_dict` silently defaults both to `''` rather than
failing closed.

**Latent hazard, not a live bug.** Production feeds
`_research_program_row_to_dict(row)`, which *does* carry both, so the live path is
correct. But `task_plan.py:102-109` `_identity` hashes `program.program_id`:

```python
return sha256_hex(canonical_json({"program_id": program.program_id, "plan_role": role, ...}))
```

A `program_to_dict` → `program_from_dict` round-trip therefore yields plan task_ids
hashed over `""` — **identical across every project and program**, i.e. a
cross-project task-id collision. The IDR's "pure inverse" claim is precisely what
would license a future caller to write that. Falsified as written; fix by
`program_id`/`project_id` being required keys (raise, not default).

### 2.7 D2 additive fields vs existing validators / repositories / tests — **PASS**

- `Intent` gains 6 fields, all `str | None = None`, appended after existing fields;
  11 construction sites in `src` (10 pre-existing + the new one at `controller.py:4103`).
  Positional compatibility preserved.
- `_require_role` reads `proposed_by` only; the new fields are not consulted by any
  validator, repository, or dispatch path. V1 "records, never authority" holds.
- Default-constructed `IntentApplied` payload is byte-identical
  (`{intent_kind, proposed_by, project_id, justification}`) — conditional insert works.
- Oversize in `tests/…:559-562` accepts `(ValueError, GatewayRejection)` but only
  ever constructs an `Intent`; `GatewayRejection` is impossible from a bare
  constructor, so the tuple is decorative and the test cannot distinguish the two
  layers. The gateway path is genuinely covered — but **out of band**, by
  `docs/IDR45-impl-audit.md` §4, not by the suite IDR D2 §4.6.3 cites.
- `programs.py:1610-1612` has **3** blank lines before `program_from_dict` (PEP 8: 2).
  ruff's default rule set omits E303, so the lint gate passes over it.

---

## 3 — Gate integrity: **all four re-run by me**

Executed in a throwaway worktree at `e5d4fb1` (identical tree to the merge result,
per §1), with the venv junctioned in. `PYTHONPATH` pinned to the worktree `src` and
verified (`hermes.__file__` under the worktree) before every run.

| Gate | MERGE-LOG-045 claim | My result | Agree |
|---|---|---|---|
| `scripts/run_tests.py -v` (full) | 2247 passed (389.68s) | **2247 passed in 441.64s, 0 failed** | ✅ |
| `uvx ruff check src tests` | `All checks passed!` | `All checks passed!` | ✅ |
| `uvx pyright src` | 0 errors, 0 warnings, 0 informations | **0 errors, 0 warnings, 0 informations** | ✅ |
| `uvx pyright --project pyrightconfig.tests.json` | 0 errors, 1 warning | **0 errors, 1 warning** (`test_research_program.py:144` `reportSelfClsParameterName`) | ✅ |

The single tests-project warning is genuinely pre-existing, and I verified it by a
stronger argument than the log used: `tests/test_research_program.py` is **not in
the merge diff at all**, so it is byte-identical to `main@c2c8fa9` and the warning is
inherited by construction.

**Disclosure — a failed run I had to discard.** My first full-suite run reported
`16 failed, 2231 passed`. I did **not** treat that as a merge defect: the errors were
`ImportError: cannot import name 'program_from_dict' from 'hermes.research.programs'
(D:\New folder\research-agent\src\...)` — the venv's editable install resolved
`hermes` to the **main** checkout (at `c2c8fa9`, without the IDR-045 code) instead of
the worktree. Total collected (2247) matched the log exactly, confirming collection
was fine and only the imported package was wrong. Re-run with `PYTHONPATH` pinned →
2247 passed. Recording this because the first result would have been a false FAIL.

**Finding F6 — a gate the merge record omits.** `scripts/check_census.py` (the
certified-census oracle added at `bd9cafd`, the commit immediately preceding the merge
base) was **not run** by `MERGE-LOG-045.md`, despite the merge adding a raw
`conn.execute` to `Controller` and touching persistence. I ran it:

```
executed transaction-control calls      121 / 121  OK
acquisition owners (persistence)         18 / 18   OK
acquisition owners (gateway)              5 / 5    OK
acquisition owners (Controller)           4 / 4    OK
rollback-only participants                1 / 1    OK
persistence->research import statements  15 / 15   OK
PASS - every certified figure is reproduced exactly.
```

The gate is green. The finding is the **record gap**: the merge log's gate table is
presented as complete when a certified invariant oracle on `main` went unrun.

---

## 4 — S6 / DG-5 / single-mutation-path on mainline reading: **PASS**

- **Single mutation path (P1).** `_plan_admission_pass` performs exactly one class of
  durable write, through `apply_intent` (`controller.py:4111`). Its only direct SQL is
  a `SELECT` (line 4074). No `TaskRepository` import, no `INSERT`/`UPDATE`, no
  `BEGIN`/`COMMIT` in the pass. `scripts/check_census.py` confirms the acquisition-owner
  counts are unchanged (Controller still 4). The structural purity probe
  (`TestD1StructuralNoWriteImport`) agrees. **Holds.**
- **Append-only / archive-not-delete.** `git diff c2c8fa9 e5d4fb1` introduces **no**
  `DELETE` in `src/` (the only `DELETE` matches in the diff are prose in the docs
  asserting the invariant). **Holds.**
- **DG-5 (persistence→research inversion).** 15 import statements, unchanged. The
  `repositories.py` hunk adds a method and **no** imports. Controller gains a
  *downward* dependency on persistence, which is permitted. **Holds.**
- **S6 (4 KiB bounded payload).** The conditional provenance append adds ≤ ~440 bytes
  (13+64+128+64+32+32 value bytes + key names + JSON overhead) to an audit payload
  that is otherwise four short fields; the impl audit measured 237 bytes for a
  non-default payload. No realistic 4 KiB pressure introduced. **Holds** — with the
  caveat that the *guard* for it is misplaced (F2), not the sizing.
- **Lease-fenced single writer.** The pass runs inside the already-fenced tick; it
  acquires no lock of its own and adds no `lock_lost` surface. **Holds.**
- **Content-hash identity / N1 / N9.** Untouched by this diff — no `fc_`/`cx_`/
  `cres_`/`fx_`/`retract_` producer changed. **Holds.**
- **Nit (encapsulation, not a violation).** `controller.py:4080` imports the
  **private** `_research_program_row_to_dict` from persistence. Downward, so allowed;
  but it bypasses the encapsulation boundary that the same change created
  (`current_primary`), and duplicates row→dict logic the new public helper owns.

---

## 5 — The IDR-045 record's own consistency: **FAIL**

Eight defects, all independently checkable.

**F7 — the Acceptance section is an unfilled template.** `docs/idr/IDR-045.md`
carries **two literal placeholders** in a record whose Status is "Decided +
implemented + tested":

```
171: All green at `idr-045/implement@<this commit>`, local-only (no push):
173: - Full suite: **`<count> passed, 0 failed`** via
```

`<this commit>` and `<count>` were never filled in. The record states no test count
and no commit. (`docs/IDR45-impl-audit.md` and `MERGE-LOG-045.md` both filled
their equivalents — the IDR is the outlier. The true values are
`96c52e7` and `2247 passed`.)

**F8 — all three cited evidence artifacts are absent from the merged tree.** The
record's Context (IDR:27-31) and Evidence bundle (IDR:229-231) cite:

| Cited | Exists at | In merged tree? |
|---|---|---|
| `docs/IDR45-audit5.md` (170 lines, PASS WITH CONDITIONS C1–C6) | `idr-045/audit5@92ba005` | **NO** |
| `docs/IDR45-Q37-evidence.md` | `idr-045/qpass-narrow@e077898` | **NO** |
| `IDR-045-plan-admission-and-intent-provenance.md` (draft v1.1) | untracked working-tree file | **NO** |

```
$ git ls-files | grep -i "IDR45\|IDR-045"
docs/IDR45-impl-audit.md
docs/idr/IDR-045.md
```

Consequence: **C1–C6 cannot be independently verified from the merged tree.** The
record asserts (IDR:202) that "each closed **with code**, not by recording" — but
the audit that *defined* C1–C6, and the Q-evidence that ratified them, are not
present. Only the post-implementation audit was brought across. A reviewer landing
this on `main` cannot check the conditions it claims to close.

**F9 — IDR D1.6 claims a code change that never landed.** IDR:107-109:

> "**Plan header/docstring freshness:** `gateway.py:6` header **now reads** 'the
> plan-admission scheduler (Controller._plan_admission_pass, IDR-045) is the
> P3-general-runtime proposer (D1).'"

It does not. Actual `gateway.py:6-8`:

```
6: path (AC-05/10/12; walking skeleton). ``ADMIT_TASK`` (internal-only) is wired
7: with DETERMINISTIC-only enforcement; the scheduler that proposes it is
8: P3-general-runtime, deferred.
```

`gateway.py` was not edited in the header region (the only hunk is `_append_audit_event`
at 4078+). So this is a **false claim of a completed edit**, and the shipped header
still asserts the ADMIT_TASK scheduler is "deferred" — now false, since
`_plan_admission_pass` ships it. Both the record and the code are wrong.

**F10 — the "pure inverse" claim is falsified.** See §2.6 / F5. IDR:216-217 states
`program_from_dict` *is* the pure inverse of `program_to_dict`; the round-trip drops
`program_id` and `project_id`. The same false claim is repeated in
`docs/IDR45-impl-audit.md:79`.

**F11 — a ratified Q-answer is recorded only in ROADMAP.** `ROADMAP.md:56` asserts
"Q-pass follow-ups: none — **Q3**/Q7 closed (Q3: no test asserts exact 4-key
`IntentApplied` payload — V2/V3 byte-identical holds; Q7: …)". The IDR has **no Q3
entry anywhere** — the ratified set is recorded as `D1-A, D2-A, Q1=plan-once,
Q7=keyed-otherwise` in both the IDR Context (IDR:28) and `ROADMAP.md:45`. A ratified
decision's answer therefore lives in a ROADMAP bullet rather than the decision
record, and the record that is supposed to carry Q3's closure does not mention it.
Q1 is likewise asserted "decided (C2)" (IDR:221-222) by reference to the out-of-scope
list of a draft that is not in the tree (F8).

**F12 — ROADMAP overclaims the C1 mechanism and adds a dangling reference.**
`ROADMAP.md:56` says the B3C filtered head is handled "**via `current_primary`**" —
production uses an inline duplicate; `current_primary` has no production caller
(F4). And `ROADMAP.md:55` cites `CATALYST-ALIGNMENT-ROADMAP-ADDENDUM.md`, which is
**not tracked** at `e5d4fb1` (`git ls-tree e5d4fb1 CATALYST-ALIGNMENT-ROADMAP-ADDENDUM.md`
returns nothing) — it exists only as an untracked scratch file, so the ROADMAP entry
added by this merge points at a file no reader of the repo can open.

**F13 — stale counts in a shipped code comment.** `src/hermes/core/intents.py:167`
and IDR D2.1 both say "the **10** src + **175** test ``Intent(`` sites":

```
$ git grep -n "Intent(" -- src/hermes/research/controller.py   -> 11 construction sites
                                                                (1133 1200 1496 1574 1714 1854 1939 2069 2210 3499 4103)
$ git grep -c "Intent(" -- tests | (sum of last field)           -> 186
$ git grep -c "Intent(" c2c8fa9 -- tests | (sum)                 -> 175
```

175 was correct for `tests/` **on the baseline**; the merge's own new test file moved
it to 186, and the merge's new `Intent(` moved `src` from 10 to 11. The comment that
ships inside `intents.py` is off by one in `src/` and by eleven in `tests/`, and is
the stated evidence for V2.

**F14 — citation drift throughout the record.** Verified line-by-line:

| IDR claim | Actual | Status |
|---|---|---|
| `intents.py:202` `__post_init__` | line 202 | ✅ exact |
| `repositories.py:1711` `current_primary` | line 1711 | ✅ exact |
| `task_plan.py:84` "`ordered` semantics" | line 84 is **blank**; `ordered` is at 86 | ❌ |
| `gateway.py:4085` "sole builder" | line 4085 is a **docstring** line; payload literal ≈ 4124 | ❌ |
| `gateway.py:3890` "missing-dep rejection" | line 3890 is a **docstring**; the `DEPENDENCY` reject is at 3920-3925 | ❌ |
| `apply_intent:4057` "each apply_intent is its own transaction" | line 4057 is `except GatewayRejection:` | ❌ |
| `gateway.py:6` header text | unchanged (F9) | ❌ |
| `gateway.py:3906` `duplicate=True` | 3906 starts the `get`; the return is 3909-3917 | ~ |

`docs/IDR45-impl-audit.md:33` cites `controller.py:tick:75,89,91,114`; `tick()` is at
`controller.py:486`. Most of the record's line anchors point at docstrings or blank
lines, which is what let F2 (the post-commit ordering) pass two adversarial audits
unnoticed.

**Also: "observable no-op" is asserted for paths that emit nothing.** IDR D1.2
("uncompiled → observable no-op, not a tick failure") and D1.5 ("an **observable
no-op**"). §2.3 shows the unparseable path writes no journal row and no note and
returns an ordinary tick. Observable only in the vacuous sense that no rows were
added.

---

## 6 — Conditions for a `PASS`

Ordered; items 1–3 are the blockers.

1. **F2 (blocking).** Move the C5 length enforcement to a pre-write position in
   `apply_intent` (before validator dispatch), or drop the `_append_audit_event`
   copy and rely solely on `__post_init__`. Correct IDR D2.2 and the `gateway.py:4083`
   comment to describe the real ordering, and state the residual post-commit
   4 KiB-guard hazard explicitly rather than implying it is covered.
2. **§2.3 (blocking).** Give `_plan_admission_pass` refusal-as-data semantics: record
   each refusal (code + reason) — a note and/or a per-tick counter on `TickResult` —
   and stop swallowing non-`GatewayRejection` exceptions silently. At minimum,
   narrow the four bare `except Exception` blocks to the specific parse/derivation
   failures they claim to handle, and make the catch-all auditable. Reconcile the
   "for observability" docstring with the discarded return value.
3. **F7/F8/F9 (blocking).** Fill `<this commit>` → `96c52e7` and `<count>` → `2247`;
   merge `docs/IDR45-audit5.md` and `docs/IDR45-Q37-evidence.md` (or amend the
   record to cite only in-tree evidence) so C1–C6 are verifiable; either make the
   `gateway.py:6` header edit the record claims, or strike D1.6 and correct the now
   false "deferred" header sentence.
4. **F5 / IDR:216.** Stop claiming `program_from_dict` is the pure inverse; make
   `program_id`/`project_id` required keys that raise, removing the `''`-default
   collision hazard in `_identity`.
5. **F6.** Add `scripts/check_census.py` to the merge gate table (it passes).
6. **F4, F3, F1.** Route eligibility through the public `current_primary` (or drop it
   and fix the commit message + ROADMAP); extend the fence to `gate_requirements`;
   delete the "readiness is computed" rationale.
7. **F0, F13, F14, F12, F11.** Repair the 3 mojibake em-dashes in `task_plan.py`; fix
   the `10`/`175` counts in `intents.py:167` and IDR D2.1; re-anchor the drifted line
   citations; track or drop the Catalyst addendum reference; move Q3's answer into
   the IDR.
8. **§2.6 test.** Make `test_oversized_field_refused` layer-specific, or add the
   gateway-boundary case to the suite (it is currently only covered out of band).

## 7 — Method and self-checks

- Merge replayed from the object database, not from the log: `merge-base`, `^{tree}`
  equality, `git diff` between merge-base / line tip / merge commit / branch tip.
- All four documented gates re-run by me on the merged tree, plus the fifth
  (`check_census.py`) the log omits. One discarded run disclosed in §3 with its root
  cause.
- Findings F2, F3, F5, F0 and the §2.3 behaviours were produced by **executed**
  read-only probes run outside the repo against the worktree, not by reading code.
  Probe scripts live in `%LOCALAPPDATA%\Temp\opencode\probe045{,b,c}.py`; they import
  the worktree and write nothing to it.
- `main` untouched throughout; `git worktree` used so no checkout's tracked files were
  modified. No `src/`, `tests/`, or `docs/` edit. Nothing pushed. This file is the
  only change on `merge/audit-045`.
- Every finding above is stated with a command, a line number, or probe output; where
  I initially suspected something and the evidence contradicted it (P4b's journal rows,
  the gateway guard's reachability, the 16 "failures"), the correction is recorded
  rather than quietly dropped.
