# AUDIT-PROGRAM-CLOSURE — GAP-1, GAP-2 and the LOOP track

**Written:** 2026-10-24, at `main@8269c01` (dev) / `efc0d7a` (mirror), tree `9022022`.
**Purpose:** the single entry point for the audit program's state. The per-slice merge logs
and the two rulings tables already record the details; this document records the **shape** —
what closed, what was accepted, what is parked, and what the system does *not* claim.

---

## 1. What "closed" means here

Every finding adjudicated by the GAP-1 and GAP-2 triages now has a **disposition**: landed,
ruled, documented-and-accepted, declined with reasons, or parked behind a named gate. None
is silently open.

**Closed does not mean proven.** Nothing in this program establishes that the system is
correct, secure, or good at research. It establishes that each *specific* finding was
examined, decided by a human where the decision was a judgement call, implemented or
documented, and recorded. The claim boundary is §5, and it is deliberately narrow.

## 2. GAP-1 — the primary gap adjudication

**Twelve Director rulings (D1–D12), all landed.** Rulings and evidence:
`docs/GAP1-RULINGS.md`; per-slice records: `docs/MERGE-LOG-*.md`.

| Ruling | Subject | Landed as |
| --- | --- | --- |
| D1 | Journal tamper-evidence | TAMPER-1 (`1556706`, triggers) → TAMPER-2 (`c110f94`, chain v23 + `journal verify`/`rechain`) |
| D2 | Experiment registry / declaration | EXPERIMENT-MERGE (`20e5d98`) — design record + fixture pins, implementation deferred |
| D3 | Task admission content blindness | TASK-ADMIT-1 (`f2b6cae`) |
| D4 | `condition_type` never set | COND-TYPE (`dc4c509`) — key + hash v2 |
| D5 | Credential boundary / key custody | CRED-1 (`b989b6d`) + the accepted boundary in `docs/STATE.md` |
| D6 | Declared-but-unwired kinds | WIRE-6 (`3df7dc8`) — pinned, zero `src` change |
| D7 | Credential lifecycle + token handling | CRED-1 (`b989b6d`) |
| D8 | License / hygiene remainder | D8-HYGIENE (wave 3a) |
| D9 | Windows-only CI | LINUX-CI |
| D10 | HR-08 single-edge guard | HR08-PIN-1 |
| D11 | Decision packets | DECISION-PACKETS |
| D12 | Audit event transaction | AUDIT-TXN (`5ef14f8`) — audit row fused into the mutation transaction |

**Two findings adjudicated outside the D-series, both after wave 3b:**

- **P2-2** — *any DB writer can forge a decision or intent.* **Ruled A: document-and-accept**
  (`7325c3f`). The boundary is recorded in `docs/STATE.md` beside D5: file write access is
  the trust boundary; `proposed_by` is a checked claim, not authorship; the chain evidences
  tampering, not forgery. No signing, no key custody.
- **P2-4** — *fixtures are self-attesting.* **Ruled C: document-and-accept** (`24daf18`,
  ruling recorded `abf349e`). Fixture integrity is **corruption-evident** (name = sha256 of
  bytes) and **regeneration-evident** (the suite rebuilds from the governed corpus), and is
  **not tamper-evident**. A journal pin was declined: its force depends on an out-of-band tip
  no ruling scoped, it inherits the DB writer's trust recorded in P2-2, and it fails open in
  CI and fresh clones.

**Other GAP-1 slices landed:** PROVIDER-1 (`8bfaf6f`), UNWRAP-AUDIT (`5def094`),
ASSERTS-1 (bare asserts — **0 remain in `src/`**), FENCE-FUZZ-1, plus the earlier
hygiene/portability batches. See `docs/MERGE-LOG-WAVE-3A.md` for the wave record.

## 3. GAP-2 — the Part-2 adjudication

Eighteen items; dispositions in `docs/GAP2-RULINGS.md`. **Every queued slice landed:**
CHG-DEDUP-1, HR8-1, CX-OVERLAP-1, RESOLVER-PARITY-1, CRES-DIGEST-1. The final open item,
**P2-16** (detector blind spots), was triaged and **ruled A** (`a275af2`): the closed
six-prefix recognition set is documented at **both coupling points** — the detector and the
admission check — with the obligation that the prefix set stays a subset of what admission
can produce. Its `GAP2-RULINGS.md` row now carries the disposition rather than
*NEEDS-INVESTIGATION*.

## 4. The LOOP track

LOOP-1..4 landed before this record (context assembly, retained feedback, review rounds,
deadline/retry). Two slices completed it:

- **LOOP-M** (`48b8ee2`) — the measured baseline. Eight scripted scenarios, a pinned vector,
  determinism asserted by a test that runs the corpus twice, and a test that **fails if a
  composite quality score is introduced**. It measures the loop from the outside; nothing
  under `agents/runtime/` was instrumented.
- **LOOP-5** (`bb26500`, ruling `d8b96fa`) — **E4 reclassified.** The ordering (proposals
  admitted before the sibling tool batch) is real; the inference *"the tools that justify
  them"* is false. `_tool_phase` reads no proposal state, and drafts and tool calls come from
  one model response. Ruled A: the ordering is correct and now documented in `_tick`'s
  docstring and pinned by a probe that asserts the documented behaviour. **B was declined on
  audit grounds** — it would suppress the record of a decision whenever a sibling tool failed.

**The baseline's one number worth remembering:** S6 (`TOOL_FAILED`) shows **1 admitted
proposal**, by design. S3 shows a **0.50 repeat-tool rate** — LOOP-2 converges after a
repeated call; it does not suppress it.

## 5. The claim boundary — what this system does not guarantee

Accumulated from the rulings; each row points at its record.

| Not claimed | Where recorded |
| --- | --- |
| Forgery resistance — a DB writer can forge a decision; the chain is unkeyed | P2-2, `docs/STATE.md` |
| Tamper-evidence for fixtures — a replaced file with a recomputed name is caught only by regeneration | P2-4, `docs/idr/FIXTURE-ANCHORING.md` |
| Tamper-evidence for the journal without an out-of-band tip | TAMPER-2, `docs/idr/TAMPER-EVIDENT-JOURNAL.md` |
| Detector completeness — six ref prefixes, seven candidate fields, silently dropped otherwise | P2-16, `docs/triage/P2-16-DETECTOR-BLIND-SPOTS.md` |
| Injection safety — the envelope is an accident barrier, not a security boundary | UNWRAP-AUDIT |
| Support for the spec-less providers — they refuse fail-closed, they are not supported | PROVIDER-1 |
| Research validity, reproducibility, or usefulness | LOOP-M, `docs/LOOP-BASELINE.md` |
| Any quality score | `test_baseline_has_no_composite_score` |

## 6. Parked, with the gate that unparks each

| Item | Blocked on |
| --- | --- |
| G5 — ordering adaptivity | outcome data the loop does not yet produce |
| G6 — hang preemption | a sandbox / process-control decision |
| G7 — durable working memory | a B-5 design decision |
| G3b — CLI entry that composes the runtime | a product decision (`hermes run` drains, does not execute) |
| Spec-less providers (8 specs / 18 adapters) | a product decision to support or keep refusing |
| Depth cap on gateway validation | a design gate; not currently binding |

## 7. Known environment condition

Five tests are **intermittent on this host**, not deterministic: four concurrency tests
(`BEGIN IMMEDIATE` → `attempt to write a readonly database`) and
`test_p_auto_5_vault.py::test_join_refuses_symlink_and_directory`. Consecutive runs have
produced 5, 4 and 0 failures. A clean run is not evidence of a code change, and a
five-failure run is not a regression. See `docs/MERGE-LOG-WAVE-3A.md` §Residuals.

## 8. Where to start next

The audit program is closed; further hardening has diminishing returns and the remaining
items are mostly product decisions. The open question is empirical: **is the research any
good?** That needs a real run, read against `docs/LOOP-BASELINE.md` — prompt payload bytes,
repeat-tool rate, evidence novelty, review rounds, termination mix. A real run is also what
unparks G5 and G7, both of which are blocked on outcome data that no slice can invent.

License: Apache-2.0 (LICENSE).
