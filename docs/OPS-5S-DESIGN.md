# OPS-5S — the 4 KiB cap a model cannot see

| Item | Value |
| --- | --- |
| Slice | OPS-5S |
| Base | `main` at `8eac365` |
| Branch | `slice/ops-5s-payload-cap` |
| Date | 2026-10-27 |
| Status | Implemented on this branch |
| Census at base | 124 / 28 (19/5/4) / 1 / 15 / 0 — `scripts/check_census.py` PASS on this tree |

The question is whether 4 KiB is the right bound for a model-authored proposal,
and the answer is that the bound was never about the proposal at all:

> **4 KiB was the journal's number, adopted by analogy, and it was measured
> against the wrong object.** The proposal envelope charged the rationale twice,
> so the cap the model was told (4096 bytes) was about twice the largest reply
> that could fit (~2.3 KB). The bound is now 8192 bytes of proposal, measured
> once; the journal's 4096 did not move, because a proposal is not a journal row.

Two changes, and they are separable:

1. **`MAX_PROPOSAL_BYTES` 4096 → 8192**, with the rationale counted once
   (`router.py:220`, `router.py:719`, `router.py:2067`). This is the fix.
2. **The contract states both bounds, in a unit a model can estimate**
   (`cloud.py:301-327`, `run.py:395-404`). This is what makes the bound visible.

The audit half of the charter's recommendation (C, wire the overflow port) is
**refused** in this slice, with the reasoning in §7. It does not unblock a run,
and it would add a live write path that a refused model output can drive.

---

## 1. Why 4 KiB, and what the new bound is

### 1.1 The number was a copy of a different number

`MAX_PROPOSAL_BYTES` was introduced with this comment:

```python
#: The event-payload cap (§3.3, `event_validation.py`). A model proposal is an
#: event-payload-shaped crossing, so it inherits the same bound.
MAX_PROPOSAL_BYTES = 4096
```

The antecedent — the journal's cap — is real and has a stated source:

| Bound | Value | Source |
| --- | ---: | --- |
| Event payload (application) | 4096 | `event_validation.py:23` — "4 KiB (v4 §8.1, S6, §27 item 10/12)" |
| Event payload (database) | 4096 | `migrations.py:178` — `CHECK (length(CAST(payload_json AS BLOB)) <= 4096)` |
| Model proposal | 4096 | the comment above — *by analogy*, not by requirement |

The analogy is false in the direction that matters: **a proposal is never a
journal row.** What reaches the journal is the *intent payload* derived from it,
and that is checked where a payload exists (`run.py:1027-1047`), against
`MAX_PAYLOAD_BYTES`, before anything is emitted. The proposal itself is parsed,
validated and dropped; only a digest of the drafted intent is recorded.

OPS-17 then made the analogy load-bearing. It rendered the cap into every
contract, and pinned the equality:

```python
# before this slice
def test_the_two_cap_constants_agree() -> None:
    assert MAX_PAYLOAD_BYTES == MAX_PROPOSAL_BYTES == DEFAULT_PAYLOAD_MAX_BYTES
```

That test is why the defect survived: the *reason* for the equality was gone,
the *test* kept the number in place, and the number was being applied to the
wrong object.

### 1.2 What the cap actually measured

The body the plane measures is the canonical form of three keys:

```python
body = _canonical_bytes({
    "structured": structured,      # the parsed reply — which contains the rationale
    "rationale": rationale_text,   # the same rationale, read back out of structured
    "tool_calls": [...],
})
```

When a contract declares `rationale_field`, `rationale_text` is read *out of*
`structured` — so the prose is serialised twice. Measured through the real
router with a run-33-shaped reply:

```
reply text bytes            :   2288
rationale bytes (once)      :   2178
body before OPS-5S          :   4504     # 1.97 x the reply
body after  OPS-5S          :   2311     # reply + 23 bytes of envelope
```

4356 of the 4504 bytes were the same 2178-byte rationale. The envelope tax is
23 bytes (`"rationale":` plus its quotes, minus the key removed from
`structured`).

This is the answer to the run-33 report. The model did not write 4.6–5.7 KB
proposals; it wrote **~2.3–2.9 KB replies**, and the ruler doubled the part it
spends most of its budget on. The prompt said 4096; the largest reply that could
actually fit was ~2.3 KB. A statement that is off by a factor of two is not a
bound a model can comply with — and it did not.

### 1.3 What each bound protects, and what 8 KiB does to it

| Object | Where it lands | Bound | Effect of 8 KiB |
| --- | --- | ---: | --- |
| Proposal body | nowhere durable — parsed, then dropped | **8192** | the only bound that moves |
| Intent payload | `events.payload_json` (a journal row) | 4096 | **unchanged** — checked per draft before emit |
| Justification (the rationale echo) | the audit row's `payload_json` | 4096 total; 1024-char echo fallback, marked `audit_bounded` (`gateway.py:5166-5178`) | unchanged in kind; the echo may be bounded more often, and the row still writes |
| Checkpoint | derived run state | none | unchanged |
| Artifact | only if a port is wired — none is | none | nothing |

The journal's cost at 8 KiB is **zero rows and zero bytes**: the journal never
sees a proposal. The two things it does see are already bounded independently —
the payload at 4096 before emit, the justification echo at 1024 with a marker —
so a larger proposal changes neither the row's size nor its fate. What it can
change is the *frequency* of the `audit_bounded` marker on a long rationale,
which is a graceful degradation the audit path already performs today.

### 1.4 The new number, with arithmetic

```
8192 = 4096  (the largest intent payload the journal will take)
     + 4096  (a rationale as large as the payload it justifies)
```

That is the shape a methodology stage writes: a handful of structured keys and a
long prose justification. The number is a sum of two named quantities, not a
doubling of the old one.

Measured against run 33:

| Quantity | Bytes |
| --- | ---: |
| Largest observed body (run 33) | 5666 |
| New bound | 8192 |
| Headroom over the worst case | 2526 |
| Worst case as a fraction of the new bound | 69.2 % |
| Twice the new bound — still an overflow | 16384 |

The bound still refuses. `len(body) > max_proposal_bytes` is unchanged, the
refusal is unchanged in shape, and a proposal at twice the bound overflows
exactly as before (`test_a_proposal_at_twice_the_new_bound_still_refuses`).

---

## 2. Whole payload, or the rationale?

**It is the whole proposal, counted once** — and "once" is the change.

The charter asks whether a verbose rationale spends the budget the structure
needs. Before this slice it did, and it spent it twice: the rationale was
serialised inside `structured` and again beside it. After the fix the body is
the reply, and the reply's own composition is the model's business.

They are **not** bounded separately at the proposal edge, deliberately:

- The falsifier requires a 5 KB proposal to be accepted. A fixed rationale
  allowance (say 2 KiB) would refuse a 5 KB proposal whose rationale is 4.8 KB —
  which is exactly run 33's shape, and exactly the failure this slice exists to
  remove. Two enforced bounds on one reply is two ways to fail one act.
- A second enforced number is a second number the model must hit blind. The
  charter's own standard — "a bound a model cannot see is a trap" — argues for
  fewer enforced bounds, not more.

They **are** bounded separately where the objects are genuinely different, and
that is where the separation already lived:

| Object | Bound | Enforced at |
| --- | ---: | --- |
| The reply | 8192 | `router.py:2067` (plane) → `run.py:980` (runtime refusal) |
| One proposal's payload | 4096 | `run.py:1028` (draft) and `run.py:1200-1210` (derived) |
| The rationale echo in the audit row | 1024 chars | `gateway.py:5171` |

Three objects, three bounds, each at the boundary that owns it. The defect was
never that there were too few bounds — it was that two different objects shared
one number and one message shape, so a reader (and a test) could not tell them
apart.

---

## 3. What a model can do about it

The honest answer used to be "write less", and the contract did say so — OPS-17
added the sentence to every profile. It did not work, for a reason this slice
found: **the sentence was false.**

### 3.1 Where it is said now

`render_system` (`cloud.py:301-327`) states two bounds, both generated from the
runtime's constants:

> The whole reply must be at most 8192 bytes — about 8192 characters of English
> text, and fewer if you use non-ASCII characters. A proposal over the cap is
> refused, and no artifact overflow port is wired today, so an over-cap body is
> neither preserved nor parsed.

> Each proposal's payload must fit the journal's 4096-byte cap on its own; the
> runtime derives the identity keys after that, so leave room for them. A
> payload over the cap refuses that proposal.

The second sentence is new, and it closes a bound that was never stated at all.
A reply can pass the first sentence and still have every draft refused, because
the payload — not the reply — is what the journal has to hold. That bound has
been enforced since before OPS-17 and had never been in a contract.

### 3.2 How it knows it is close

Bytes are not countable while writing; characters approximately are. The
sentence therefore gives the bound in both units and names the exception
(non-ASCII costs up to 4 bytes per character), so a model that budgets roughly
8,000 characters is inside 8,192 bytes by construction.

The measured body is not *exactly* the reply: the envelope adds its own keys
(`structured`, `rationale`, `tool_calls`), a fixed 23 bytes on the shape above.
That is why the sentence says "about" rather than naming an exact character
count — a model that aims at the stated number rather than at the round number
below it is refused by 0.3 %, not by a factor of two. The 4096 defect this
slice removes was the factor of two.

This is guidance, and the contract is explicit that the check is elsewhere. It
is also the *only* signal available before a call: the refusal is what would
tell a model it overshot, and the refusal ends the tick (see §4). So the
statement has to be true in advance, which is why the measurement fix is part of
the fix and not a separate concern.

### 3.3 What it still cannot see

The per-draft payload bound is stated in bytes with no character proxy, because
the payload's shape is JSON, not prose — a character budget would be a worse
estimate than the byte count for a structured object. The clause tells the model
which object the bound applies to and that the derived keys come after; the
count is its own to make.

---

## 4. The two sites

### 4.1 Why they behave differently

They bound **different objects**, and that is the whole of it:

| | Site A — whole proposal | Site B — intent payload |
| --- | --- | --- |
| Code | `run.py:980-997` | `run.py:1027-1047`, `run.py:1199-1210` |
| Object | the model's reply | one draft's payload |
| Bound | 8192 | 4096 |
| Disposition | **terminal** — `FAILED` / `MODEL_REFUSED` | **that draft refused**, the run continues |
| Why | `structured` is emptied on overflow: there is nothing to draft from, so the tick produced nothing | the payload is the only thing over; the tick's other drafts are unaffected |

The dispositions are not in tension; they follow from what survives. A draft
that breaks the journal's bound is one refused proposal. A reply that breaks the
reply's bound leaves no proposal at all.

`test_a_payload_refusal_does_not_end_the_run_but_an_overflow_does` pins the
contrast directly, because it is the fact that makes the two messages
distinguishable rather than merely differently worded.

### 4.2 Which is authoritative

Each is authoritative for its own object, and neither is a re-implementation of
the other. That is the correction this slice makes to the code's own
self-description: the two sites were described as one rule with two arms, and
they were never that. Site B is the journal's bound and keeps the journal's
number. Site A is the reply's bound and now has its own.

### 4.3 The overflow path that never fires

Both sites have an artifact arm, and neither fires in the live composition:

- `build_methodology_handler(..., artifacts: Any = None)`
  (`task_handlers/__init__.py:256`) defaults to `None`, and `build_controller`
  (`composition.py:872-881`) does not pass one.
- So `RuntimeWiring(artifacts=None)` → `AgentRuntime(artifacts=None)`, and
  `run.py:983`, `run.py:1031` and `run.py:1203` take the "no artifact overflow
  port is wired" arm every time.

**A correction to the charter's §2.** The charter says "`result.overflow` is
never populated". It is: the refusal interpolates `result.overflow.size_bytes`,
which is how the message can print `(4656 bytes)`. What is never populated is
`self._artifacts`. The conclusion is unaffected — wiring the port would preserve
the body and still refuse the proposal, because the refusal does not depend on
the reference — but the mechanism is the artifact port, not the overflow object.

---

## 5. What did not change

1. **No new event kind, write path or transaction.** Census 124 / 28 (19/5/4) /
   1 / 15 / 0, reproduced by `scripts/check_census.py`.
2. **The substrate's content rules, the gateway's checks, the capability
   grants** — untouched. No file under `persistence/` or `research/` changed.
3. **Drain-only byte-identical. B4 24. LOOP baseline unchanged. Governed docs
   untouched.**
4. **The act-key, `proposable_kinds`, `max_ticks`, objectives** — untouched.
5. **A runaway proposal still refuses.** The check is the same comparison; only
   the number and the measurement moved.
6. **No key material.**

The journal's own bound is untouched at every layer: the constant, the
application validator, and the `CHECK` constraint are all still 4096.

---

## 6. Falsifiers, by name

| Falsifier (charter §6) | Test |
| --- | --- |
| A proposal at 5 KB is accepted | `TestTheFalsifiers::test_a_proposal_at_5_kb_is_accepted` |
| …and one at twice the new bound still refuses | `TestTheFalsifiers::test_a_proposal_at_twice_the_new_bound_still_refuses` |
| The refusal names the actual size and the bound | `TestTheFalsifiers::test_the_refusal_names_the_actual_size_and_the_bound` |
| The refusal still fails the run | `TestTheFalsifiers::test_an_over_cap_proposal_still_fails_the_run` |
| The message says which happened (preserved / not) | `TestTheFalsifiers::test_the_message_says_which_happened` |
| The rationale is charged once | `TestWhatTheCapMeasures::test_the_body_carries_the_rationale_once`, `…test_a_verbose_rationale_does_not_spend_the_structures_budget_twice` |
| The body is the reply, not twice a part of it | `TestWhatTheCapMeasures::test_the_body_is_the_reply_plus_the_envelope_tax` |
| The payload bound still bites under the new reply cap | `TestThePayloadBound::test_a_reply_under_the_new_cap_can_still_refuse_its_payload` |
| The derived-payload arm still refuses | `TestThePayloadBound::test_the_derived_payload_arm_still_refuses_too` |
| The two sites keep different dispositions | `TestThePayloadBound::test_a_payload_refusal_does_not_end_the_run_but_an_overflow_does` |
| The model is told both bounds, from the constants | `TestWhatTheModelCanSee` (5 tests) |
| Baseline and census unchanged | `test_loop_baseline`, `test_census_check`, `scripts/check_census.py` |

The C-specific falsifier ("an overflowed body is preserved as an artifact **and**
the proposal still refuses") is not claimed, because C did not land — see §7.

---

## 7. Refused

### 7.1 C — the overflow port is not wired

The charter recommends it as an audit improvement. It is refused here for three
reasons, in order of weight:

1. **It is a new live write path, and §5.1 forbids one.** `ArtifactStore`
   (`artifacts/store.py`) has no `store`/`dereference` pair; it is not an
   `ArtifactOverflowPort`. Wiring it means writing an adapter, threading it
   through `build_controller` → `build_methodology_handler` → `RuntimeWiring`,
   and making a *run* write artifact rows it does not write today. That is a
   durable effect where there was none.
2. **It lets a refused model output drive a durable write.** An over-cap body is
   untrusted bytes the model chose to produce. With the port wired, a model can
   write 8 KiB per refusal, per tick, per retry, with no quota — a refusal path
   that a model can aim at the artifact store. A quota is a design question, not
   a rider on this slice.
3. **It buys nothing for the failure at hand.** §2 of the charter is right that
   it does not unblock a run, and after this slice run 33's replies (~2.3–2.9 KB)
   are well inside the bound — the bodies that would be preserved are ones that
   no longer occur at the observed shape.

What is *not* refused is the diagnosis: the port exists, is declared, and is
called at three sites; what is missing is a live adapter and a quota. That is a
slice of its own, and it should carry the quota.

### 7.2 The overflow refusal is not made retryable

The plane marks the same condition retryable when overflow is unavailable
(`router.py:2068-2077`, `retryable=True`), and the runtime's overflow branch is
outside the supervisor loop, so the two disagree on disposition. They are left
disagreeing, deliberately:

- The plane's retryable marker applies to the branch where the plane still holds
  the body and can say more; the runtime's branch holds nothing — `structured`
  is empty, so there is no partial draft a retry would improve on.
- A retry spends a model call to be told the same thing. The signal that would
  help is the *bound*, and that is now in the prompt before the first call
  (§3.2) rather than in a second prompt after a failure.

If a later slice wants the retry, the seam is `attempt_request` in
`_model_phase` (`run.py:915-930`): converting an overflowing proposal into a
`ModelRefusal(RATIONALE, contract_feedback=True)` there would route it through
OPS-15's informed re-prompt with no other change. It is named here so the next
gate can choose it knowingly.

### 7.3 The payload cap is not raised

`MAX_PAYLOAD_BYTES` stays 4096. It is the journal's number, the `CHECK`
constraint enforces it, and raising it would change what a row costs — which
§5.1 and §5.2 forbid and which no observed failure asks for.

---

## 8. Gates

Raw lines, run on this tree (`PYTHONPATH=<worktree>/src`, Python 3.14.1).

**1. Targeted** — the new file plus every suite the charter names:

```
381 passed in 10.38s
```

**2. Full suite** — `scripts/run_tests.py`:

```
5 failed, 5516 passed, 3 skipped, 1 warning in 665.26s (0:11:05)
```

The five are pre-existing and environmental, not this slice's: they fail
identically on the base tree with this branch's changes stashed —

```
FAILED tests/test_concurrency.py::TestCompetingTransitions::test_two_writers_different_tasks_both_succeed
FAILED tests/test_concurrency.py::TestDuplicateIdempotency::test_concurrent_event_append_succeeds
FAILED tests/test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory
FAILED tests/test_phase1_acceptance.py::TestForcedConcurrencyRace::test_concurrent_different_tasks_both_succeed
FAILED tests/test_q05_ratification_consumers.py::test_f6_one_verdict_race_closed
```

Four are `sqlite3.OperationalError: attempt to write a readonly database` under
threaded writers, one is a Windows symlink/directory join. None touches the
model plane or the runtime's payload checks.

**3. Suite-count stamp:**

```
Stamped docs\SUITE-COUNT.md: collected=5524
OK: docs\SUITE-COUNT.md collected=5524 matches the live collect
```

(5497 at base; +26 new tests, +1 from splitting the cap-equality pin in two.)

**4. Census** — `scripts/check_census.py`:

```
executed transaction-control calls                 124       124  OK
acquisition owners (persistence)                    19        19  OK
acquisition owners (gateway)                         5         5  OK
acquisition owners (Controller)                      4         4  OK
acquisition owners (total)                          28        28  OK
rollback-only participants                           1         1  OK
persistence->research import statements             15        15  OK
control calls outside certified layers               0         0  OK

PASS - every certified figure is reproduced exactly.
```

**5. Lint and types:**

```
uvx ruff check src tests scripts        →  All checks passed!
uvx pyright src                         →  0 errors, 0 warnings, 0 informations
uvx pyright --project pyrightconfig.tests.json
                                        →  0 errors, 1 warning
```

The single warning is the pre-existing one OPS-17 recorded:
`test_research_program.py:144` (`reportSelfClsParameterName`), untouched here.

