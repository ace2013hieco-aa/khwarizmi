# MERGE-LOG-DECISION-PACKETS — precomputed read-only operator decision packets (GAP-1 D11-A, verify then land)

## Provenance

| Item | Value |
| --- | --- |
| Task | DECISION-PACKETS-MERGE (merge gate; local FF — the push is bundled with the wave-2 fleet under one human D9 pin) |
| Base (`main` before) | `d86ceeb` (EXPERIMENT-MERGE landing + its merge log) |
| Artifact | `slice/decision-packets@eee771c` (single commit, authored before wave 1) |
| Slice | verified as `slice/decision-packets-restacked@e05b87e`; **restacked** as `slice/decision-packets-final@c4f084c` (cherry-pick `90aa115` + re-stamp) |
| Landed tip (FF'd to) | `c4f084ced16bee08f96b32f530a5d94c1e1cdd53` |
| Merge method | **fast-forward** |
| Push | drafted, **NOT executed** — bundled with the wave-2 fleet under one human D9 pin |

## Scope

```
src/hermes/research/decision_packets.py | +726    (new; read-only packet assembly)
tests/test_decision_packets.py          | +424    (12 collected tests)
docs/SUITE-COUNT.md                     |  +3 -3   (4917 -> 4929)
```

## What was certified (D11-A: read-only precomputation; authority boundary unchanged)

- **Read-only**: full 726-line audit found ZERO mutation-capable calls — no
  `INSERT/UPDATE/DELETE`, no `.commit(`, no `executescript`, no `BEGIN`, no
  `apply_intent`, no gateway/controller/provider/credential-store import.
  Every external call is a SELECT or a pure function; mutation absence is
  additionally pinned by tests (tests:365-424).
- **Authority**: view-only. `required_authority` is a coordinate string; no
  ratifying field, operator identity, or decision execution exists. A
  negative test proves the existing human gate still refuses (`OPERATOR`,
  `VERDICT`) and that no ratification event appears; no API surface is
  exposed (tests:407-411).
- **Layering**: stdlib + `hermes.persistence.failure_classifications`
  constants + `hermes.research.completion` / `failure_classification`; no
  provider adapters; no new persistence→research edges (census 15 imports
  unchanged).
- **Isolation**: every data-bearing read is project-filtered. Three
  identity-keyed lookups (decision by `correlation_id`, gate by `task_id`,
  provenance by `artifact_id`) lack a project predicate, but all keys are
  globally unique by construction (PKs / content-addressed ids), and
  `assemble_packet` rejects foreign verdicts — no cross-project bytes can
  enter a packet.
- **Determinism**: no clock/random/fs; every query ORDER BY; cone/queue
  sorted; canonical `sort_keys` JSON; hashes recomputed; byte-pin and
  input-order-independence tests.
- **Bounds**: cone capped (`MAX_CONE_DEPTH=4`, `MAX_CONE_NODES=64`); no
  event writes, so the 4 KiB event-payload discipline does not apply.

## Gates (raw)

Agent verification at slice tip: new tests **12 passed**; **FULL suite
4870 passed, 3 skipped, 0 failed** (912.05s); pyright 0/0/0 + 0/1; ruff
pass; census PASS; B4 24; NOT-list 0.

Director re-derivation at final restacked tip `c4f084c`: battery
(`test_decision_packets.py`) **12 passed**; stamp `--check` OK **4929**
(4917 + 12); census PASS; B4 **24 passed**; ruff `All checks passed!`;
pyright src 0/0/0; NOT-list **0 hits** (word-boundary).

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| any mutation/authority/LLM/SQL capability | **none found** — read-only audit + negative tests |
| project-isolation leak | **none** — keys globally unique; foreign verdicts rejected |
| nondeterministic output | **none** — ordering + byte pins |
| census shift | **none** — 124 / 28 / 15 unchanged |
| B4 governed corpora | **PASS** — 24/24; no governed-doc edits |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `d86ceeb` |
| push without a human hash-pin | **none performed** |

## Residuals (recorded, not blockers)

- No explicit two-project isolation test (structurally sound; a cross-project
  packet test is a sensible follow-up).
- Per-packet diffs are bounded by recorded rows (cone itself is capped).
- A gate task with unparseable `spec_json` reports `blocking_completion=False`
  though completion still denies it.
- The cherry-picked commit message preserves the source author's footer
  verbatim (no footer was added by the landing).

## Prohibited-claims discipline

This gate certifies a read-only precomputation surface whose outputs are
advisory packets, never authority, validity, or admissibility claims.

License: Apache-2.0 (LICENSE).
