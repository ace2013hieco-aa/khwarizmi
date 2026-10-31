# OPS-18 — the project index, implemented

| Item | Value |
| --- | --- |
| Slice | OPS-18, phase 2 |
| Base | `main` at `ba61179` |
| Branch | `slice/ops-18-read-port` |
| Design gate | `docs/idr/LIVE-PROJECT-INDEX.md` — approved with corrections C1/C2 and rulings R1–R6 |
| Date | 2026-10-25 |

The design note is the decision record; this note records the implementation,
the live measurement and the evidence.

## 1. The two corrections, as recorded

### C1 — chain nodes come from the store, not SQL

`SubstrateStore.nodes` is an in-memory dict (`methodology/substrate.py:522-536`).
The durable half of the index is exactly three `SELECT`s + three `COUNT`s over
`tasks`, `artifacts` and `scope_briefs`. The chain half is obtained from the
driver's own `store = SubstrateStore()` (`methodology_driver.py:507`),
populated by `write_node` after each successful stage. Before each stage the
driver passes `ProjectIndexChainNode(project_id, node_id, kind)` for every
node in the store; the adapter filters on `project_id` and sorts by id.

A fresh process has an empty store, so the `chain_node` section is empty. That
is B-5 working-state discipline, not a missing read. An `mnode_` is a per-run,
in-memory identifier; a task id is durable. The index labels chain nodes
`"<KIND> chain node (not a task id)"` and lists durable `task` entries as the
legal dependency targets.

If the provider is absent (non-live callers and existing tests), no envelope is
appended. In the live composition it is always supplied.

### C2 — the live database exists and was measured

`D:/New folder/hermes-live.db`, `sars-covid-10`:

| Table | Rows |
| --- | ---: |
| `tasks` | 12 |
| `artifacts` | 0 |
| `scope_briefs` | 0 |
| chain nodes (fresh process) | 0 |

The real index is **12 task entries / 1,108 bytes**. The 40-entry cap is
retained because 1,108 is below the R6 3,000-byte re-measurement threshold.

## 2. Implementation map

| Piece | File |
| --- | --- |
| Read-only durable projection (3 `SELECT` + 3 `COUNT`, project-bound, no transaction) | `src/hermes/persistence/project_index.py` |
| Origin, entry/view/chain-node types, pure bounded envelope renderer | `src/hermes/agents/runtime/assembly.py` |
| Adapter: labels, order, 40-entry cap, chain-node project filter | `src/hermes/research/project_index.py` |
| One call per stage, after the previous stage, before `wiring.run` | `src/hermes/research/task_handlers/methodology_driver.py` |
| Provider threading | `src/hermes/research/task_handlers/__init__.py` |
| Live composition injection | `src/hermes/composition.py` |
| Tests | `tests/test_ops18_project_index.py` |

No controller change, no new intent, event, table, durable field or write.
The provider is injected as a callable; the handler package still imports no
persistence. The reader only runs `SELECT`/`COUNT` and never issues
`BEGIN`/`COMMIT`/`ROLLBACK`.

## 3. The live envelope, printed

```
{"entries":[{"id":"meth-sars-10","kind":"task","label":"SUCCEEDED AGENT_TASK"},{"id":"seq-sars-covid-10-91a4ad30a1a5db4550a2bb455016063c","kind":"task","label":"CANCELLED TOOL_TASK"},{"id":"seq-sars-covid-10-c9516f66e11b2726c828b5708e6cf742","kind":"task","label":"PENDING TOOL_TASK"},{"id":"task_0d5aa9322e204c3ffd37bdda3e54d1a7","kind":"task","label":"PENDING AGENT_TASK"},{"id":"task_0eb91344edc7808a3f33ae8d24a59be1","kind":"task","label":"PENDING AGENT_TASK"},{"id":"task_17fe118a32966727d0c4ae2d50b3e3f8","kind":"task","label":"PENDING AGENT_TASK"},{"id":"task_5d383a8a1914fce5b8304736c6fe9816","kind":"task","label":"PENDING AGENT_TASK"},{"id":"task_6209d24c56245c62866252e5b5d4a881","kind":"task","label":"PENDING AGENT_TASK"},{"id":"task_bca372588063b54d75cd3f5db429b5c9","kind":"task","label":"PENDING AGENT_TASK"},{"id":"task_c802bb06d81813a476992c4f54dbde47","kind":"task","label":"PENDING AGENT_TASK"},{"id":"task_f0647cc8cc5355b17f00de6638b35363","kind":"task","label":"PENDING AGENT_TASK"},{"id":"task_f0b8f4d38b7b7bb8fc09fea43982ed96","kind":"task","label":"PENDING AGENT_TASK"}],"omitted":0}
```

Origin `runtime.project_index`; ref `sars-covid-10:project_index`; 1,108 bytes;
12 entries; `omitted: 0`. The canonical empty document is
`{"entries":[],"omitted":0}` (26 bytes).

## 4. The tests that carry the claim

- **Cross-project:** `test_another_projects_rows_with_overlapping_prefixes_never_appear`
  seeds P1/P2 with overlapping `task-00-shared-prefix-…`,
  `evidence-00-shared-prefix-…` and `sb-00-shared-prefix-…` ids plus P1/P2
  chain nodes; the P1 index contains no P2 id, and every shown entry resolves
  in P1 or is a P1 chain node. Result: pass.
- **Transaction count:** `test_the_stage_transaction_count_is_identical_with_and_without_the_index`
  traces a one-stage methodology with and without the reader. The
  `BEGIN`/`COMMIT`/`ROLLBACK` lists are both empty and equal. Result: pass.
- **Content:** `test_the_envelope_carries_no_content_and_no_admissibility_wording`
  seeds a task spec, artifact metadata and scope text with sentinel strings,
  then asserts the envelope's top-level keys are exactly
  `{"entries","omitted"}`, every entry's keys are exactly
  `{"id","kind","label"}`, the sentinels are absent, and no
  `available`/`valid`/`approved` wording appears (R3). Result: pass.
- **Live-shaped citation:** `test_a_task_id_cited_from_the_index_no_longer_refuses_missing_dependency`
  and `test_an_evidence_ref_cited_from_the_index_no_longer_refuses_not_in_project`
  run a scripted model that reads the index, cites a shown id, and reaches the
  real gateway; the dependency/artifact resolves and is admitted. Result: pass.
- **Prompt/empty/cap/freshness/fail-loud/live composition:** the remaining
  OPS-18 tests; all pass.

The cap/byte-cap test seeds 50 tasks (40 shown, `omitted: 10`) and 40
long-id artifacts (the 4 KiB cap drops the tail, `omitted` equals total minus
shown). The freshness test proves one provider call per stage and shows the
first stage's `QUESTION` node in the second stage's index.

## 5. Invariants

- No new event, durable field, write or transaction. Census unchanged:
  124 / 28 (19/5/4) / 1 / 15 / 0.
- The LOOP baseline does not move; M1 moves only in live methodology prompts,
  by the envelope bytes (+1,108 on the live project today).
- Drain-only unchanged; B4 stays 24. Governed docs untouched.
- No key material, no cross-project rows.
- The index is untrusted data with its own origin; labels are closed-vocabulary
  derivations, never free content.

## 6. The mnode fallback (R2)

If run 11 still produces `dependency mnode_… does not exist` after the model
sees the `TASK` entries and the `not a task id` chain label, the next gate is a
contract sentence that `dependencies` accepts only task ids. OPS-18 does not
add that sentence.

## 7. Gates

- Targeted: the new test file, `test_ops7_input_projection`,
  `test_loop_baseline`, `test_loop_observations`, `test_ops1_live_cli`,
  `test_b4_ref_graphs`, `test_census_check` — pending.
- Full suite under the heavy-gate lock — pending.
- Suite stamp / `--check` — pending.
- Census — pending.
- Ruff / pyright src / pyright tests — pending.

License: Apache-2.0 (LICENSE).
