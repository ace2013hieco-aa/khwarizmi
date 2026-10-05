# HERMES RESEARCH — OPERATOR CONTROL-PLANE ADVERSARIAL REVIEW

**Scope:** the entire operator control plane as a COMPOSED system — CLI →
credential verification → human-gate resolution → controller → lease/fence →
task-state transition → event journal → operator-visible result — plus the
backup/restore, recovery, heartbeat, and epistemic crossover surfaces.

**Date:** 2026-08-16
**Reviewer:** independent adversarial review (Codebuff)

---

## A. Baseline

| Item | Value |
|---|---|
| HEAD | `1a7fc09` (`git rev-parse HEAD`, working tree clean apart from `.freebuff/`) |
| Suite | **1386 tests collected, 0 failures** (after this review's 9 new probes; 1377 before) |
| pyright (src strict) | **0 errors, 0 warnings** |
| ruff (src + tests) | **clean** |
| CI (origin/main) | last three runs **all six jobs green** (Tests / Local smoke / Typecheck / Profiled gate / Security / Lint) |
| README security status | "constant-work operator burn" section current; three documented local run paths |

The brief's assumed HEAD (`12fdc2f`) is 20+ commits behind; the closure work
(F2 constant-work family, F4 parse-bound, F14 one-verdict, forged-journal,
profiled-gate CI) landed in `12fdc2f..1a7fc09`. Every property below was
reproduced against `1a7fc09`, not assumed from prior reports.

---

## B. Attack surface

```
CLI (gate resolve / operator register / pause / resume / run / status / audit /
     events / doctor / backup / restore)
  → argument parsing (argparse; required --operator/--token on gate resolve)
  → OperatorCredentialRepository.verify  (PBKDF2-HMAC-SHA256, bounds)
  → Controller.resolve_human_gate        (verdict → rationale → verify → lock →
                                          project → gate-type → status → journal)
  → lease / scheduler_lock (single-row, CHECK id=0, generation-fenced)
  → fenced transaction (WAITING_HUMAN→RUNNING→terminal + GatePassed/GateFailed
                        + HumanGateResolved, atomic)
  → mode re-derivation + journal
```

The precedence is **documented and deterministic** (see C/G).

---

## C. F2 constant-work — repository / gate / lock / CLI

Established baseline (reproduced this review): exactly **one** PBKDF2 per
`verify` and per `resolve_human_gate` outcome at the repository, the gate
surface, the LOCK path, both ingestion surfaces (`record_operator_decision`,
`record_scope_review_decision`), the register surface, the CLI entry, and the
operator's actual `hermes gate resolve` entry point. The parse-bound lens
(O(512) shape check before any split/int/fromhex) and the token-length bound
(`_OPERATOR_TOKEN_MAX_LENGTH`, checked at register AND verify before hashing)
were reproduced via the counting patch and the instrumented sqlite
`text_factory`.

**New this review — error-precedence matrix**
(`test_20_error_precedence_matrix_deterministic`): the full failure order is

| # | Path | Code | KDF |
|---|---|---|---|
| 1 | malformed verdict | `VERDICT` | **0** |
| 2 | oversized rationale | `RATIONALE` | **0** |
| 3 | invalid operator | `OPERATOR` | 1 |
| 4 | held lease | `LOCK` | 1 |
| 5 | task in another project | `NOT_FOUND` | 1 |
| 6 | task not a HUMAN_GATE | `NOT_HUMAN_GATE` | 1 |
| 7 | already-resolved status | `NOT_WAITING` | 1 |
| 8 | tampered status back to WAITING_HUMAN | `ALREADY_RESOLVED` | 1 |

Rows 1–2 are the ONLY pre-auth paths, and they fire on the **attacker's own
input** (a malformed verdict string or an oversized rationale they supplied) —
the fast path reveals nothing about operator validity, gate existence, or lease
state. Rows 3–8 all pay exactly one KDF. The precedence is stable: a bad
operator is always refused `OPERATOR` before any task/lease state is consulted
(no pre-auth task-existence probe), and the project check precedes the
type/status checks.

**Honest limitations:** wall-clock equality is NOT claimed (per §35). The
claims are equal logical work, no cheap secret-dependent branch, bounded KDF,
and no early exit based on credential validity. The two input-validity fast
paths are a deliberate, documented input-dependence — never a protected-fact
oracle.

---

## D. Authentication

| Attack | Expected | Actual | Severity |
|---|---|---|---|
| unknown vs known operator_id at repo/controller/gate/CLI | parity, one KDF each | HOLDS (F2 family; refusal text byte-identical across token shapes) | — |
| wrong token vs right token | one KDF each, accept/refuse only discriminator | HOLDS | — |
| tampered stored hash (digest flip) | refused OPERATOR, same shape as wrong token, no content leak | HOLDS (`test_gate_resolve_output_echoes_only_attacker_input`) | — |
| operator existence oracle via register | idempotent re-register = one KDF, no token oracle | HOLDS (re-register probe) | — |
| replay of valid verdict | deterministic NOT_WAITING / ALREADY_RESOLVED | HOLDS | — |

Canary audit (`test_canary_token_never_leaks_any_surface`): a 22-char canary
token never appears in the event journal, audit --json, status --json,
doctor --json, the events CLI, the backup snapshot bytes, the raw DB bytes
(only the PBKDF2 hash is stored), or any gate-resolve output. HOLDS.

---

## E. Authorization

| Attack | Expected | Actual | Severity |
|---|---|---|---|
| operator resolves gate through a controller bound to ANOTHER project | refused NOT_FOUND, no state/events | HOLDS (`test_20_cross_project_gate_resolution_refused`, `test_cli_cross_project_gate_resolution`) | — |
| CLI --project p2 on a p1 gate | NOT_FOUND, gate untouched, zero events | HOLDS | — |
| CLI without --project | resolves through the task's OWN project (derived from the row) | HOLDS | — |
| pause/resume/run without a credential | succeed — unauthenticated local machinery by design | DOCUMENTED boundary (`test_verdict_requires_credential_operational_surfaces_do_not`) | OBSERVATION |
| gate verdict without a ratified credential | refused OPERATOR, one KDF | HOLDS | — |

**Finding (documented design, not a bug):** the operator credential is
**system-wide** — one ratified operator may resolve a gate in any project; the
PROJECT scoping lives in the controller binding, and the verdict surface is the
ONLY authority the credential gates. `pause`/`resume`/`run`/`backup`/`restore`/
`project create` are unauthenticated local commands: the DB file itself is the
local trust boundary (a multi-user login on the operator's machine already
shares that boundary, and backup/restore are file operations by design). This is
a coherent, explicit authorization model — recorded, not changed.

---

## F. Timing / side-channel

Reproduced this review: no observable difference in KDF count, SQL shape, lock
interaction, error class, or output length between unknown operator / wrong
token / right token / held lease / wrong project / already-resolved across the
repository, the gate surface, the LOCK path, the CLI, both ingestion surfaces,
and the register surface. The output-size lens (audit/status/events/doctor),
backup-size lens, cold-start lens, and the human-table/JSON-shape lenses all
hold. The only measurable input-dependent fast paths are the two
attacker-input validity checks (C) and the CLI's pre-auth task-existence check,
which reveals only **public** task existence (task ids are listed by
`status`/`audit`).

---

## G. Human gate — full authorization path

`test_20_error_precedence_matrix_deterministic` + `test_20_journal_coherence_each_outcome_exact_events`
reproduce the complete flow: verdict validity → rationale bound → credential
verify (one KDF) → lease → project check → gate-type check → status check →
**journal check** → one fenced atomic transaction. The final decision is based
on CURRENT authoritative state (mutable status AND the append-only journal);
stored state cannot upgrade authority (status tampered back to WAITING_HUMAN is
still refused `ALREADY_RESOLVED` by the journal truth).

---
## H. Lock / fencing

Verify precedes `_acquire_lock`; a held lease is refused `LOCK` after exactly
one KDF (never a cheap fast LOCK that skips the burn); the lease is released in
`finally` on every post-acquisition path; the scheduler lock is schema-constrained
to a single row (`CHECK id = 0`) and generation-fenced. Stale-controller writes
are rejected at the fence (existing F15/lease probes). HOLDS.

---

## I. Replay

| Attack | Expected | Actual | Severity |
|---|---|---|---|
| repeated identical verdict | NOT_WAITING, one verdict total | HOLDS | — |
| replay after restore | the restored journal still refuses (NOT_WAITING, or ALREADY_RESOLVED under status tamper), exactly one HumanGateResolved row | HOLDS (`test_20_replay_after_restore_one_verdict_survives`) | — |
| replay after lease/generation change | same one-verdict outcome | HOLDS (F14 composition) | — |

---

## J. Concurrency

Two operators / two controllers resolving the same gate: exactly one winning
verdict, exactly one coherent transition, matching events — covered by the F14
one-verdict suite and the F15 lease/race probes; the F15 live-worker test race
found during this review's CI verification was hardened (lease gate on B's
start, `1a7fc09`). HOLDS.

---

## K. Credential storage

PBKDF2-HMAC-SHA256, fixed algorithm/digest, min+max token length, min+max
iteration bounds, O(512) shape check before parse, fail-closed legacy branch
(64-hex validated via fromhex), never raises, never persists plaintext. F4
corpus fuzz reproduced: every malformed shape refuses with zero KDF and zero
parse calls. HOLDS.

---

## L. Journal / audit integrity

`test_20_journal_coherence_each_outcome_exact_events`: the one legal success
writes exactly one GatePassed + one HumanGateResolved + two TaskStatusChanged
hops atomically; **every** refusal path (VERDICT, RATIONALE, OPERATOR, LOCK,
NOT_FOUND, NOT_HUMAN_GATE, NOT_WAITING, ALREADY_RESOLVED) writes ZERO events.
No event-without-state, no state-without-event, no duplicate. The F9
HumanGateResolved index gap remains a **recorded FUTURE design** — the
application-level defense (journal check before every resolve + atomic verdict
transaction) is sufficient; no schema change was warranted (per §25).
---

## M. Backup / restore

Backup is an exhaustive Online-Backup-API copy (backup bytes == source bytes;
size-proportional, content-independent); restore is an atomic fsync + rename
with lease check and WAL cleanup; replay-after-restore preserves the one-verdict
rule (I). A restore resurrects state **faithfully** — it never resurrects a
second verdict or an old token's authority beyond the stored hash. HOLDS.

---

## N. Heartbeat / recovery

Operator-loop recovery, heartbeat refresh/horizon, and stale-lease reclaim are
covered by the existing F15 probes (live-worker protection, hung-worker
recovery after horizon, late-handler cliff discard) plus the F2 tick-loop lens
(zero PBKDF2, never reads credentials). The only race found in this review was
the F15 **test** acquire race, hardened at `1a7fc09` (product logic was
correct — the task still landed SUCCEEDED once). HOLDS.

---

## O. Q-05 / Q-02 / Q-04 crossover

Operator resolution acts through the controller's ratified edge and the gateway
(`apply_intent` for proposal decisions); no operator path bypasses the
proposal/ladder authority model. The directive-#2 probe (wrong-classification
inputs can only gate, never mutate) and the Q-series tests pin the epistemic
boundary. No crossover mutation found. HOLDS.

---

## P. CI / verification pipeline

The local-gate job enforces `uvx pyright src` (strict) + `uvx ruff check src
tests`; the profiled-gate job runs the tests-profile pyright plus the
walking-skeleton smoke in one command (`scripts/profiled_gate.sh`); the
security probes are regular suite tests (never one-off developer commands).
Documented commands match CI. HOLDS.

---

## Q. Diagram consistency

The red-team reconciliation figure now reflects HEAD `1a7fc09` / **1386 tests**
with the composed-audit probes in the F2 (latest) manifest (rendering verified
in the Preview tab; single clean `<svg>`). No other diagram was made stale by
the operator additions.
---

## R. New adversarial tests (this review)

| Probe | Surface | What it pins |
|---|---|---|
| `test_20_error_precedence_matrix_deterministic` | controller | deterministic 8-step precedence, 0/1 KDF per path, journal-truth rule |
| `test_20_cross_project_gate_resolution_refused` | controller | project check precedes type/status; no state/events |
| `test_20_journal_coherence_each_outcome_exact_events` | controller | success = exactly one verdict; every refusal writes zero events |
| `test_20_replay_after_restore_one_verdict_survives` | backup/restore | one verdict survives restore; replay refused |
| `test_events_cli_untruncated_fields_but_strict_subset` | CLI | events lines: min-width mirror of tamperer's own values, strict subset of audit, hidden-state invariant |
| `test_gate_resolve_output_echoes_only_attacker_input` | CLI | only attacker-supplied ids echoed; tampered hash refused with same shape as wrong token; ghost task = 0 KDF, public-only |
| `test_verdict_requires_credential_operational_surfaces_do_not` | CLI | verdicts require the credential (1 KDF); pause/resume are unauthenticated local machinery (0 KDF) |
| `test_cli_cross_project_gate_resolution` | CLI | --project p2 refused NOT_FOUND; auto-project resolves |
| `test_canary_token_never_leaks_any_surface` | all outputs | canary token never leaks anywhere (incl. backup + raw DB bytes) |

Plus this review's CI verification hardening: the F15 live-worker **test** race
(lease-acquire between A's thread and B's first tick) gated deterministically at
`1a7fc09` — 10/10 local passes pre-fix, CI flaked once, 5/5 post-fix.

---

## S. Findings

- **P0 BLOCKER:** none found.
- **P1 MUST FIX:** none found.
- **P2 SHOULD FIX:** none found.
- **P3 IMPROVEMENT:**
  1. The two 0-KDF input-validity paths (`VERDICT`, `RATIONALE`) could be made
     one-KDF-uniform for absolute timing parity, but they fire on attacker-known
     input and reveal no protected fact — currently a documented
     input-dependence, not a leak.
  2. The operator credential is system-wide (no per-project operator binding).
     Project scoping lives in the controller binding; a per-project operator
     binding would be a feature, not a defect.
- **OBSERVATION:**
  1. The local trust boundary: `pause`/`resume`/`run`/`backup`/`restore`/
     `project create` are unauthenticated local commands; the credential gates
     only verdicts (and ingestion decisions). Coherent with the local-tool
     model; a multi-user login shares the boundary.
  2. Commits remain unsigned (governance improvement candidate — signed
     closure tags / verification manifests; not implemented because no existing
     signing path was in place, per §34).
  3. The CLI task-not-found fast path (0 KDF) reveals only public task
     existence (status/audit list all task ids).
---

## T. Final verdict

**CLEAN — READY FOR CLOSURE**

The four closing questions, answered directly:

1. **Can an attacker who does NOT know a valid operator credential distinguish,
   through timing, output, errors, lock behavior, replay behavior, or state
   transitions, any protected fact Hermes intends to hide?**
   **No.** Every post-auth path pays exactly one KDF with identical SQL/lock/
   error shape; the only pre-auth fast paths are attacker-input-dependent
   (malformed verdict/rationale) or public (task existence). No operator
   validity, gate existence, lock state, or authorization status is
   distinguishable.

2. **Can a valid operator with legitimate gate-resolution authority obtain
   authority they do not explicitly possess?**
   **No.** The credential authorizes exactly the verdict (and proposal-decision)
   surfaces; cross-project resolution is refused; there is no role layer to
   escalate through (a single authority class by design); operational
   plumbing is unauthenticated local machinery that writes no research
   outcomes.

3. **Can a stale controller or replayed operator decision produce a state or
   event the current controller would not accept if constructed from scratch?**
   **No.** The one-verdict rule (mutable status AND journal truth), the
   generation-fenced lease, and the atomic verdict transaction reject every
   stale/replayed/stale-generation write; replay-after-restore is refused.

4. **Can the operator control plane's interaction with the epistemic loop
   produce a false REFUTED/SUPPORTED state or execute an unratified proposal?**
   **No.** Operator resolution flows through the controller's ratified edge and
   the gateway; the directive-#2 and Q-series probes pin the epistemic
   boundary; no bypass path was found.

**Residuals:** two P3 improvements and three observations recorded above; no
blockers, no must-fixes. The composed chain holds: CLI → verification →
authorization → current lease → current generation → current task/gate state →
current proposal semantics → atomic state + event → reproducible result.
