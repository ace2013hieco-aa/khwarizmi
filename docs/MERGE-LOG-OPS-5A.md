# MERGE-LOG-OPS-5A — the capability plane gets a supply (wave 4)

## Provenance

| Item | Value |
| --- | --- |
| Task | OPS-5A: `source_search` + `source_fetch`, the R5 flag correction, journaled egress |
| Base (`main` before) | `a4dbe17` (the OPS-5 design note) |
| Slice | `slice/ops-5-capabilities` — eight commits, **fast-forwarded** |
| Landed tip | `f37c11318fe0a7576bde665ac2230fbfa7447116` (tree `4e29e84a…`) |

```
 docs/idr/LIVE-CAPABILITY-PLANE.md         | 101 ++++  (the rulings + corrections)
 src/hermes/research/capability_supply.py  | 654 ++++  (the supply)
 src/hermes/research/live_fetch.py         |  86 +++- (the egress path)
 src/hermes/tools/capabilities/envelope.py |  10 +-   (`environment`, schema v2)
 src/hermes/tools/capabilities/invoke.py   |  34 +-   (R5 + the path-rule fix)
 src/hermes/tools/capabilities/types.py    |  15 +-   (the environment declaration)
 tests/test_capability_plane.py            |  84 +-   (the legality matrix)
 tests/test_ops5_capabilities.py           | 353 ++++  (the supply's pins)
```

## What landed

- **A supply exists.** Before this slice, zero of the ten declared capability ids had a `Tool`
  or an executor in `src/`. `capability_supply.py` supplies `source_search` and `source_fetch`
  over the shipped adapters and the code-owned allowlist — the two the `researcher` profile
  declares and the only two that can be supplied honestly.
- **R5 — `sandboxed` is a declaration of isolation, not a permission ticket.** `invoke.py:558`
  used to demand `sandboxed=True` from any side-effecting tool; a `TOOL`-kind capability may now
  declare network reach and run in-process with `sandboxed=False`, and the **envelope carries
  `environment="in-process (no sandbox)"`**. The `SANDBOX`-kind rule is untouched
  (`registry.py` has **0** changed files) — the distinction is *runs in-process and says so*
  versus *requires isolation and gets it*.
- **A real defect fixed on the only path `source_fetch` can take.** The sandbox boundary gate
  treated every URL as an absolute filesystem path, so `source_fetch` was uncallable before the
  egress gate could run. Path rules now apply only to tools declaring a `filesystem_scope`.
- **Journaled egress (R1).** A recorded search and a refused fetch both journal; the row carries
  `response_body_hash`, never a body, never a query value, and stays under 4 KiB. The capability
  path passes `retain_body=False`, so the fetched bytes are not persisted at all — stricter than
  the task-side search path.

## The inventory held

An intermediate full run went red:

```
FAILED test_hr04_source_identifier_capture.py::...::test_searchresult_construction_sites_closed_inventory
```

The fetch carrier had added a fourth `SearchResult(` construction site. **The inventory was not
widened and the test was not skipped.** The carrier now canonicalizes through
`canonicalize_identifiers` and assembles via the audited `search_result_from_mapping`
constructor. `tests/test_hr04_source_identifier_capture.py` has **0** changed files — the check
kept its teeth, which is the point of having it.

## Deviations from the design note (recorded, not forced)

1. **`provider_interactions.task_id` is NULL.** The note proposed deriving a task-shaped id from
   the idempotency key; the column is FK-bound to `tasks` and `ToolCallContext` carries no task
   id, so that would write an FK-invalid value. The row is project-scoped; the idempotency key
   rides the envelope.
2. **No ledger line yet.** The run ledger does not exist until 5B wires the runtime, so the
   `in-process (no sandbox)` fact lives in the envelope (v2) and the tool summary now; **5B must
   render it in the run's capability line.**
3. **A bounded page with no reported total is `PARTIAL`/`UNKNOWN`**, not `COMPLETE`. The
   capability returns the rows and the note rather than inventing an aggregate.

## Gates (raw, at `f37c113`)

| Gate | Result |
| --- | --- |
| Full suite | **5094 passed / 3 skipped / 0 failed** (5097 collected) |
| Supply + plane + HR-04 + B4 | **199 passed** (re-run by the Director at the tip) |
| `stamp_suite_count.py --check` | `collected=5097` (regenerated, never hand-edited) |
| `check_census.py` | **PASS** — 124 / 28 (19/5/4) / 1 / 15 / 0 |
| B4 ref graphs | **24 passed** |
| `ruff` / `pyright src` / tests | clean / **0/0/0** / **0 errors, 1 known warning** |
| No test excluded or deselected | confirmed |

## Debt carried into 5B

1. **Clock bases must match.** The driver compares the plane's `deadline_monotonic` against the
   provider machinery clock, which hardcodes `time.monotonic`. Production matches; a custom clock
   makes every call expire instantly. 5B must compose the invoker and the machinery from one clock.
2. **The process-construct scan still applies to every side-effecting tool** regardless of process
   reach — a URL containing `&&` would refuse. Conservative; recorded, not fixed.
3. **F6** — a later-stage `TOOL_FAILED` reporting `completed` at task level — untouched (R4).

## The ceiling, stated

After 5A/5B a live run can **search and fetch admitted sources**. It still cannot read the
project's own evidence: `ToolCallContext` deliberately carries no read port. That is **OPS-5C**,
and it is the difference between an agent that can look outward and one that can look inward.

License: Apache-2.0 (LICENSE).
