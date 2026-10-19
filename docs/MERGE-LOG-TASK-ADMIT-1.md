# MERGE-LOG-TASK-ADMIT-1 — task admission fail-closed on content/project (GAP-1 P1-6)

## Provenance

| Item | Value |
| --- | --- |
| Task | TASK-ADMIT-1-MERGE (merge gate; local FF — the push is bundled with the sibling GAP-1 slices under one human D9 pin) |
| Base (`main` before) | `8cb9d94` (ROLE-EXH-1 landing + its merge log) |
| Slice | `slice/task-admit-1@3f3f346`; **restacked** as `slice/task-admit-1-restacked@f2b6cae` (cherry-pick of `a4f9f24` + `65bfe18`; the slice's own re-stamp dropped and re-created for the combined count — **no rebase**, no merge commit) |
| Landed tip (FF'd to) | `f2b6cae` — tree `ae0f4f441cba53d573c7f61391764e84baee9164` |
| Merge worktree | `C:/Users/Ali Zoghi/AppData/Local/Temp/opencode/met-1-merge-wt` |
| Merge method | **fast-forward** — `git merge --ff-only` (exit 0); single-parent chain |
| Push | drafted, **NOT executed** — bundled with the GAP-1 fleet under one human D9 pin |

## Scope

```
src/hermes/research/gateway.py                |  89 +  4 -   (_validate_insert_task fail-closed compare)
tests/test_task_admit_1_duplicate_content.py  | 289 +  0 -   (14 pins, new)
tests/test_cli.py                             |  35 + 16 -   (F2 fixture repair, no assertion weakened)
tests/test_wiring_w4.py                       |  20 +  4 -   (BIND-1 intended-delta, see below)
docs/SUITE-COUNT.md                           |   3 +  3 -   (4759 -> 4773)
```

`_validate_insert_task` returned the existing row with `duplicate=True` on ANY
`task_id` match — no content or project comparison. A differing proposal looked
admitted; a foreign-project row could be returned as "yours". The fix returns
`duplicate=True` only for an exact content replay **in the same project**;
a differing proposal and a foreign-project row refuse fail-closed with
`IDEMPOTENCY_CONFLICT` (project checked before content), refusals-as-data.

## Canonical byte domain (the pinned identity)

`_TASK_CONTENT_FIELDS` = the 13 admission content fields (`task_type`,
`profile`, `idempotency_key`, `iteration`, `parent_task_id`, `spec`, `inputs`,
`outputs`, `dependencies`, `provenance`, `cost_class`, `concurrency_group`,
`max_retries`). Runtime state (`attempt`/`status`/timestamps/heartbeat) is
excluded — a requeue or dispatch must not turn an exact replay into a refusal.
Comparison is `json.dumps(sort_keys=True, separators=(",",":"),
ensure_ascii=False)` over **parsed structures on both sides** (intent payload
dict vs `TaskRepository.get` row), so key-order / JSON-formatting / tuple-vs-
list / default-expansion variants of one logical command compare equal — pinned
by tests (no false refusals). `dependencies` normalizes to sorted order (edges
are a set; readback order is a query-plan artifact); JSON arrays elsewhere are
order-sensitive content and a reorder refuses. Non-serialisable content refuses
`MALFORMED_PAYLOAD` (fail-closed). Comparison validator-side; repository API
unchanged.

## Intended delta on the certified W4 slice (flag for the human)

`tests/test_wiring_w4.py::test_a_re_emitted_observation_is_idempotent` (BIND-1)
previously pinned the second (re-emitted) observation as `completed`. Under the
approved D3-A rule, the re-emitted record carries its own emission bookkeeping
(`replayed=True` + replay journal note), so it is a **differing proposal**; the
gateway now refuses it as data — `failed_typed`, reason contains
`IDEMPOTENCY_CONFLICT`, `outcome_recorded is False` — while the substantive
pins hold: exactly one child row, the port executed once. `WIRING_DESIGN`
BIND-1 sanctions exactly this boundary answer: *"re-emit is idempotent
(`IDEMPOTENCY_CONFLICT` or duplicate-same-row per boundary)"*. The exact-replay
`duplicate=True` path is pinned by the 14 new tests. Recorded here as an
intended, sanctioned consequence of D3-A — **not** an unnoticed pin change.

## CLI F2 fixtures

Four `tests/test_cli.py` probes seeded p2 task_ids/idempotency_keys colliding
with p1 — previously swallowed by the ID-only duplicate path; now refused
fail-closed, which surfaced the clashing seeds. Repaired to distinct ids;
count literals 403->405 events, 408->410 union (docstring + one human-table
assertion). No assertion weakened; probes still pin the hidden-state invariant
on truthful seeds.

## Fail-on-base

Agent run at base `c368886` with the fix stashed and the new test file present:
**7 passed, 7 failed** — exactly the seven refusal-expecting pins. W4 pin at
base: `F....` (the re-emit pin fails under fail-on-open, the four repaired CLI
tests pass). Fix restored; intended-delta direction proven both ways.

## Gates (raw)

Agent run (slice tip): full suite `4754 passed, 3 skipped, 0 failed` (532.03s);
stamp OK 4757 (own branch); census PASS; B4 24/24; ruff pass; pyright src 0/0/0;
pyright tests 0 errors + 1 pre-existing warning.

Director re-derivation (restacked tip `f2b6cae`): stamp `--check` OK **4773**;
census **PASS** (121/27/1/15 unchanged); B4 `24 passed`; battery
(`test_task_admit_1_duplicate_content` + `test_wiring_w4` + `test_cli` +
`test_role_exhaustiveness`) all green; ruff `All checks passed!`; NOT-list scan
of the restack range diff **0 hits**.

## STOP-condition checks

| Condition | Result |
| --- | --- |
| NOT-list hit (functional coupling) | **PASS** — 0 hits |
| canonical domain undefined/loose | **PASS** — defined, pinned, false-refusal variants tested |
| replay determinism (exact replay) | **PASS** — `duplicate=True` byte-compatible shape pinned |
| refusal-as-data | **PASS** — `IDEMPOTENCY_CONFLICT` / `MALFORMED_PAYLOAD` with rationale, never silent |
| FF-ability / main unmoved | **PASS** — `--ff-only` exit 0 from `8cb9d94` |
| `--check` drift | **PASS** — 4773 (4759 + 14) |
| census / B4 drift | **PASS** — unchanged |
| certified-pin change undisclosed | **none** — W4 delta recorded above, design-sanctioned |
| push without a human hash-pin | **none performed** |

## Prohibited-claims discipline

This gate certifies a fail-closed admission boundary over task identity and
project scope. It makes no validity, reproducibility, or admissibility claim.

License: Apache-2.0 (LICENSE).
