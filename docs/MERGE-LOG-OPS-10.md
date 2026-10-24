# MERGE-LOG-OPS-10 — a run report the operator can read (closes F2)

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-10: a bounded diagnostic report at the live run boundary |
| Base (`main` before) | stacked on the OPS-9 tip `3b19f19` (the charter's base did not resolve; the agent rebased onto OPS-9 and said so) |
| Landed tip | `b73d5c4` |

```
 docs/SUITE-COUNT.md                |   6 +-
 src/hermes/agents/runtime/run.py   |  27 +-
 src/hermes/agents/runtime/types.py |   7 +-
 src/hermes/cli.py                  |  73 +-
 src/hermes/config.py               |  30 +-  (the [reporting] key)
 src/hermes/eval/live_vector.py     |  37 +-
 src/hermes/run_report.py           | 275 ++  (new)
 src/hermes/tools/models/router.py  |  68 +-
 tests/test_ops10_run_report.py     | 234 ++
```

## The gap it closes

Three live runs failed with `admitted=0` and **none said why**. `MODEL_REFUSED` and
`PROPOSAL_REFUSED` are emitted to the supervisor trace (`run.py:796`, `projection.py:51-53`),
which dies with the process. Learning the reason took a hand-built in-process harness, twice.

## The decision that shaped it

**Journaling the refusals was rejected.** The journal is an intent/state record; a per-tick trace
log inside it would bloat it and dilute what TAMPER-2 and AUDIT-TXN made meaningful — and it would
become a second record competing with the journal's authority.

**A file at the run boundary instead**, with the constraint that makes it safe. Every report opens
with:

```json
"report": "diagnostic-run-report",
"not_a_record": true,
"disclaimer": "Diagnostic artifact, not a record. This file is never read back as authority,
               replayed, or consulted by a validator. The append-only journal remains the
               durable record of the run."
```

It carries what was missing: per-stage state/termination, the per-attempt ledger, every refusal's
**code, detail, profile, tick and stage**, and a **bounded excerpt of the model's raw reply**
(≤ 2 000 bytes) — because "malformed payload" without the offending text is half a diagnostic. The
demo report reproduces run 3's exact failure and shows the model emitting both forms in one object.

## Safety properties, pinned

- **The key never appears.** The test reply deliberately echoes the injected key in its rationale;
  the report shows `<redacted>`, and the assertion is `KEY not in raw` plus `"<redacted>" in raw`
  on the raw file — not an inspection.
- **Redaction runs recursively over every string**, before the size cap and before writing.
- **Drain-only writes nothing** — no directory, no file, byte-identical stdout.
- **A report failure never fails the run** — one `report: unavailable (<reason>)` line, exit code
  unchanged.
- **Bounded**: 1 MiB cap, truncation counted (`refusals_omitted`, `model_attempts_omitted`,
  `stages_omitted`, `notes_omitted`).
- **No repository path**: default is a `run-reports` directory beside the live DB; an explicit
  `[reporting] run_dir` must be absolute.
- **No DB write, no event, no transaction.** Certified census unchanged.

## Two deliberate widenings, both recorded

1. **The CLI emit census moved 124 → 126** (`tests/test_cli_output_scrub.py`) — two new
   operator-facing lines, incremented with an inline reason. This is the *emit-site* count, not the
   certified transaction census (which stayed 124 / 28 / 19/5/4 / 1 / 15 / 0).
2. **The model-ledger frozen surface gains `duration_ms`** (`tests/test_model_plane.py`) so the
   report can carry timing. The test still pins the exact key set, so any further addition fails —
   the widening is one key, bounded, and visible.

## Gates (raw)

| Gate | Result |
| --- | --- |
| Targeted | **65 passed** |
| Full suite | **5127 passed / 3 skipped / 0 failed** (the first run was red only on the emit census, fixed by the +2 with a reason) |
| `stamp_suite_count.py --check` | `collected=5130` |
| `check_census.py` | **PASS** — unchanged |
| B4 / drain-only | **24** / byte-identical, no report |
| `ruff` / `pyright` | clean / **0/0/0** |

## The acceptance test still to come

This slice's own tests prove a report is written and safe. What they cannot prove is that it
explains a **real** failure — that is run 4's job, and the standard is one sentence: **the next
failure explains itself, without a hand-built harness.**

License: Apache-2.0 (LICENSE).
