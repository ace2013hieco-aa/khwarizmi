# B4 reference graphs — packaged fixtures (GR3-P2-b4fixtures)

Real typed-edge graphs extracted by the GR3 v0 `cites` extractor
(`src/hermes/research/graph_edges.py`) over the governed corpus, and
packaged for TEXP-001 twin consumption. Full decision record:
`docs/gr3-b4/P2-b4fixtures.md` (IDR-043).

## What a fixture is

One canonical-JSON file per reference graph. The FILE NAME is the
sha256 of the file's own bytes, so a fixture is addressed by its
content and any edit is detectable without a signature. Each body
records:

- `fixture_id` + `rationale` — which stratum this graph is;
- `fixture_schema_version`, `extraction_version` — the extractor rule
  that produced the edges (`1`, i.e. `GR3_EXTRACTOR_VERSION`);
- `namespace: "texp-001-twin"`, `consumption: "SIMULATED"`,
  `authority: "ADVISORY"` — twin-namespace markers. A B4 graph is
  fidelity evidence for a simulation; it is never production state and
  never authority for any transition;
- `source_set` — the governed documents used, each with its own
  `content_hash` (sha256) and `size_bytes`;
- `edges` — `(citing_ref, cited_ref, edge_type)` triples, all `cites`;
- `skipped` — document-looking mentions that resolved outside the
  source set (observed, never edges);
- `counts` — re-checked by the strict reader (count drift fails closed).

## The packaged set

| `fixture_id` | sources | edges | fixture file |
|---|---|---|---|
| `b4-c1-p1a-baseline` | 6 | 5 | `232fd00e97ba2a0c0d358d80905567d75b3dab728c35be6988d0aa7e8eee04f3.json` |
| `b4-c2-expanded-cohort` | 12 | 19 | `7ed0612ea0c615d12071b3b23c6805ecb89d51a622ce8e507a5e047f205a338d.json` |
| `b4-c3-idr-design-chain` | 8 | 10 | `eef419463e5201c415615b1a8e33b03f237283a43b40af2b5a6709b3b63b664e.json` |
| `b4-c4-authority-spine` | 4 | 5 | `948a0d8876b9d70e2064f178f81a024be3a86e5ff36dcd90d8c3a3bde4a522ca.json` |

> **Re-derivation (`merge/conditions`, `docs/MERGE-AUDIT.md` C1).** The census update to `AGENTS.md`
> and `docs/ARCHITECTURE.md` — both governed corpus members — moved those two documents' bytes, so
> `b4-c1` / `b4-c2` / `b4-c4` were regenerated deliberately per §Regenerating:
> `749bf192… → ffbdf93c…`, `82ea9ec8… → 8d2c74fa…`, `2249067c… → 4bc5dc28…`. `b4-c3` is unchanged (its
> stratum is IDR-only). Edge sets are identical (5 / 19 / 10 / 5) and each affected `skipped` list gains
> exactly one token (the new `IDR-044` mention), so the citation structure is invariant — only the pinned
> byte identities moved. The GR3 phase reports kept their as-of-then digests (records are not rewritten);
> this table is the live set.

> **Re-derivation (experiment-gate doc — `GATE-DOC-REGEN`).** The gate-doc
> commit (`fix/experiment-gate-doc-v2`, `05c3217`) edited two governed
> corpus members (`docs/ARCHITECTURE.md` +7, `docs/STATE.md` +13), so
> `b4-c1` / `b4-c2` / `b4-c4` were regenerated deliberately per §Regenerating:
> `ffbdf93c… → 0ee743f9…`, `8d2c74fa… → 3efc5422…`, `4bc5dc28… → 4feda75b…`. `b4-c3` is unchanged (its
> stratum is IDR-only).
> Edge sets, `counts`, and the `skipped` lists are identical
> (5 / 19 / 10 / 5) — only those two source identities moved, and this
> table is the regeneration's own output.

> **Re-derivation (REBASE-DET — `merge/claim` replayed onto platform `main` `d1241a1`).** The claim
> line's regeneration collided *rename/rename* with the platform line's own O2 census regeneration of the
> same content-addressed fixtures. The rebased corpus is the union (platform documents ∪ the claim
> gate-doc edits), so the fixtures were regenerated a third time per §Regenerating:
> `0ee743f9… → 232fd00e…`, `3efc5422… → 7ed0612e…`, `4feda75b… → 948a0d88…`. `b4-c3` is unchanged
> (IDR-only stratum). Edge sets, `counts`, and the `skipped` lists are identical (5 / 19 / 10 / 5); only
> the pinned byte identities moved, and this table is the live set.

`b4-c1` is the certified P1b baseline (the P1a six alone); `b4-c2` is
the reference graph (the expanded sample); `b4-c3` and `b4-c4` are
structurally distinct strata of the same real corpus. The set is
deliberately a handful — enough to replace the twin's "no real graph
exists — B4" assumption, not exhaustive.

## Regenerating

```
.venv/Scripts/python.exe -c "from pathlib import Path; \
from hermes.research.ref_graphs import build_all_reference_graphs, \
fixture_filename, reference_graph_bytes; [ \
(Path('docs/gr3-b4/b4-fixtures') / fixture_filename(g)).write_bytes( \
reference_graph_bytes(g)) for g in build_all_reference_graphs(Path('.').resolve())]"
```

`tests/test_b4_ref_graphs.py` asserts that this regeneration reproduces
the committed bytes exactly, so a fixture that no longer matches the
live documents fails the suite (regenerate deliberately, never silently).

## Consuming from the twin

`experiments/texp-001/fixtures.py` exposes a clearly-marked, additive
`B4 SOURCE` read path (`b4_reference_graph`, `b4_reference_graphs`,
`b4_available`). It reads these files, re-verifies the name/digest
binding, enforces the SIMULATED / twin-namespace / ADVISORY markers, and
returns a frozen, data-only graph. It imports nothing from production
and runs no experiment.

## Honest limits (recorded, not papered over)

- The only edge type is `cites` (`GR3_EDGE_TYPES`); the twin's 14-class
  alphabet (`EXPERIMENT` `validator.EDGE_ALPHABET`) has no `cites`
  member. A B4 graph is therefore reference **structure** for the twin
  today — not yet admissible to the S1 sequence validator, and not
  runnable as a twin benchmark instance.
- The sample is the governed repo corpus (max 20 KiB per document). It
  is real authored prose, not scientific evidence; it supports no
  reproducibility claim.

> **EOL note (p2-fix, P2-audit F1/C1):** fixture digests are the CRLF-normalized (LF) governed identity. The loader (`load_corpus_bytes`) normalizes `CRLF→LF` and all 12 governed documents are pinned `eol=lf`, so regeneration is stable on every checkout. Before this fix the three CRLF-typed sources (AGENTS.md etc.) produced mixed digests on some checkouts.
