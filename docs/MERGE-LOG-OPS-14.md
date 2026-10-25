# MERGE-LOG-OPS-14 — `profile` and `inputs` stated; the chain reaches eight stages

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-14: the `profile` value set and the `inputs` shape |
| Base (`main` before) | `528a72c` → landed on `253dfe8` by **cherry-pick** (OPS-14 branched before the OPS-13 log) |
| Landed tip | `1097276` |

```
 docs/OPS-14-NOTES.md                   | 128 ++
 src/hermes/composition.py              |  37 +-
 src/hermes/research/gateway.py         |  32 +-  (profile values, INTENT_PAYLOAD_SHAPES)
 src/hermes/tools/models/cloud.py       |  22 ++
 src/hermes/tools/models/router.py      |  15 +-
 tests/test_ops14_profile_and_inputs.py | 360 ++
```

## What landed

```
For INSERT_TASK, the payload key "profile" is optional (omitting it takes the runtime's default);
when supplied it must be one of: ADVERSARY, DETERMINISTIC, DIRECTOR, IMPLEMENTER, RESEARCHER.
Any other value is refused.

For INSERT_TASK, the payload key "inputs" is optional (omitting it admits an empty list);
when supplied it must be a list of strings. Any other value is refused.
```

Two different defaults, stated differently and correctly: `_derive_payload` does
`setdefault("profile", spec.agent_profile)` (so the runtime supplies one), while `inputs` is not
defaulted at the draft surface — the validator reads `payload.get("inputs", [])`, so omission admits
an empty list at admission. The agent read both sites and worded each to match its own mechanism
rather than reusing one sentence for both. That is the distinction OPS-13 established, applied
twice.

## The drift guard, demonstrated three ways

1. Removing `"profile": _PROFILE_VALUES` makes the rendered sentence disappear and the test fail —
   proving the line is generated, not written once.
2. Replacing the derived set with a hand-typed list fails on `DETERMINISTIC`, the one member the
   typed list omitted.
3. Renaming the enum member moves the rendered line, with both sides following — which is the
   property that matters.

## What it changed — run 8

```
Ran 3 tick(s): 2 dispatched, 1 succeeded, 7 unhandled
vector: runs=9 admitted=7 … mix=SUCCEEDED:7/OTHER:2   M1 595–2,406
```

**Eight stages reached:** QUESTION → HYPOTHESIS → PREDICTION → EXPERIMENT → OBSERVATION →
EVIDENCE → CLAIM → **CRITIQUE**, which failed on `kind None`. Nine stage runs, seven admissions.
The `profile` refusal is gone entirely.

## What the remaining refusals are — a change of class

| Code | Count | Detail |
| --- | --- | --- |
| `ROLE` | 2 | `kind None` (QUESTION attempt 1, CRITIQUE) |
| `MALFORMED_PAYLOAD` | 1 | both proposal forms |
| `MALFORMED_PAYLOAD` | 1 | `payload.provenance must be a list of strings` |
| `PROPOSAL` | 1 | `dependency mnode_… does not exist (FK)` |
| `PROPOSAL` | 1 | `evidence artifact 'synthetic-sars8/literature-review-v1' not in project` |
| `PROPOSAL` | 1 | `scope brief 'claim:…' not governed: ScopeBrief not …` |

Three of the six are now **semantic**: the model invents node ids, artifact refs and scope briefs
because it cannot see what exists in the project. That is no longer a contract-shape gap and no
amount of prompt text fixes it — it needs a **read port**, so the model can ask what is there
before citing it. This is OPS-5C, and it has moved from "nice to have" to the binding constraint.

The other three are the known shape gaps (`kind None` variance, both forms, `provenance` shape).

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted | **77 passed**; Director re-ran **66** at the merged tip |
| Full suite | **5166 passed / 3 skipped / 0 failed** (tracked tree) |
| `stamp_suite_count.py --check` | `collected=5169` |
| `check_census.py` | **PASS** — unchanged |
| B4 / baseline | **24** / unchanged |
| `ruff` / `pyright` | clean / **0/0/0** |

The agent again set aside an untracked stale probe (`tests/test_audit_e1_prompt_probe.py`) and
proved its two failures pre-existing at base. Reported, not concealed.

License: Apache-2.0 (LICENSE).
