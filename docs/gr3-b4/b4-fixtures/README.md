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
| `b4-c1-p1a-baseline` | 6 | 5 | `20204aaf0f01ee13ceb0bd1f36a63ee25e0bb48c76ca17add5fb03a6baba5181.json` |
| `b4-c2-expanded-cohort` | 12 | 19 | `3bbe04e61501c82d151576df39f111cc1f461619d38f635d268da54763cbf94f.json` |
| `b4-c3-idr-design-chain` | 8 | 10 | `eef419463e5201c415615b1a8e33b03f237283a43b40af2b5a6709b3b63b664e.json` |
| `b4-c4-authority-spine` | 4 | 5 | `c3fca6dc8d74377d83461cc35fa7b71b9a5dbc23e25b3504672a4c31f44ddfc9.json` |

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

> **Re-derivation (STATE-MD-PLATFORM-ENTRY — `fix/state-platform-entry`).** The governed edit adds the
> platform-line entry (R1–R7 / W0–W4 / O1–O5 status) to `docs/STATE.md`, a `CORPUS_REFS` member, so
> `b4-c1` / `b4-c2` / `b4-c4` were regenerated deliberately per §Regenerating:
> `232fd00e… → 06dea9db…`, `7ed0612e… → d1312f01…`, `948a0d88… → 550fcc00…`. `b4-c3` is unchanged (its
> stratum is IDR-only). Edge sets are identical (5 / 19 / 10 / 5) and the `sources` counts are unchanged
> (4 / 12 / 6 / 8); each affected `skipped` list gains exactly two tokens (the newly cited `IDR-046` and
> `ARCHITECTURE_DELTA`), so the citation structure is invariant — only the pinned byte identities moved.
> `ROADMAP.md` is not a governed-corpus member, so the sibling platform record there forced no regen.

> **Re-derivation (NUM-1 — `slice/num-1-counts`).** The count reconciliation
> points the two governed count lines at the generated single source of truth
> (`AGENTS.md` drops `(2101)` for `(collected count: docs/SUITE-COUNT.md,
> generated)`; `docs/STATE.md` drops `2101` for `green per docs/SUITE-COUNT.md`),
> so `b4-c1` / `b4-c2` / `b4-c4` were regenerated deliberately per §Regenerating:
> `550fcc00… → 35f4aca6…`, `06dea9db… → 75a1ac2b…`, `d1312f01… → f54a8f40…`.
> `b4-c3` is unchanged (IDR-only stratum). Edge sets are identical (5 / 19 / 10 / 5)
> and the `sources` counts are unchanged (6 / 12 / 8 / 4); each affected `skipped`
> list gains exactly one token (the new `docs/SUITE-COUNT.md` mention), so the
> citation structure is invariant — only the pinned byte identities moved, and
> this table is the live set.

> **Re-derivation (CRED-1 — `slice/cred-1`).** The credential-lifecycle slice
> edited three governed corpus members — `AGENTS.md` (DG census line: 27 → 28
> owners), `docs/API.md` (intent vocabulary 18 → 21 members; operator token
> channels), `docs/ARCHITECTURE.md` (§3.10 census: 121 → 124 calls / 27 → 28
> owners) — so `b4-c1` / `b4-c2` / `b4-c4` were regenerated deliberately per
> §Regenerating: `35f4aca6… → 2cf0464e…`, `75a1ac2b… → cf54f4c5…`,
> `f54a8f40… → a7ddd5a2…`. `b4-c3` is unchanged (IDR-only stratum). Edge sets,
> `counts`, and `skipped` lists are identical (5 / 19 / 10 / 5); only the three
> source identities moved, and this table is the regeneration's own output.

> **Re-derivation (CRED-1 restack — `slice/cred-1-restacked`).** The
> combined-tree truth pass corrected two stale figures in a governed corpus
> member — `docs/ARCHITECTURE.md` (layer table row: schema v19 → v22,
> persistence acquisition owners 18 → 19; body: schema v19 → v22) — adding no
> citation tokens, so `b4-c1` / `b4-c2` / `b4-c4` were regenerated
> deliberately per §Regenerating: `2cf0464e… → 1727860b…`, `cf54f4c5… →
> 0551a2a6…`, `a7ddd5a2… → be83b607…`. `b4-c3` is unchanged (IDR-only
> stratum). Edge sets, `counts`, and `skipped` lists are identical
> (5 / 19 / 10 / 5) — only the three source identities moved, and this
> table is the regeneration's own output.

> **Re-derivation (GAP1-RULINGS — `slice/rulings-gap1`).** The governed
> `docs/STATE.md` edit (GAP-1 wave-1 hardening entry + the D5-A
> document-and-accept entry) moved one governed source identity, so
> `b4-c1` / `b4-c2` / `b4-c4` were regenerated deliberately per
> §Regenerating: `1727860b… → 357b9ee3…`, `0551a2a6… → 03127be4…`,
> `be83b607… → b5b21189…`. `b4-c3` is unchanged (IDR-only stratum). Edge
> sets and `sources` counts are identical (5 / 19 / 10 / 5; 6 / 12 / 8 /
> 4); each affected `skipped` list gains exactly one token (the new
> `docs/GAP1-RULINGS.md` mention from `docs/STATE.md`), so the citation
> structure is invariant — only the pinned byte identities moved, and
> this table is the regeneration's own output.

> **Re-derivation (HYGIENE-1 — `slice/hygiene-1`).** Two governed corpus
> members moved — `AGENTS.md` (P3-1 honest DELETE census + P3-2 canonical
> script lint) and `docs/API.md` (P3-7 decision-conflict code + P3-11 LOCK
> retry rule) — so `b4-c1` / `b4-c2` / `b4-c4` were regenerated
> deliberately per §Regenerating: `357b9ee3… → 20204aaf…`,
> `03127be4… → 3bbe04e6…`, `b5b21189… → c3fca6dc…`. `b4-c3` is unchanged
> (IDR-only stratum). Edge sets, `sources` counts, and `skipped` lists are
> identical (5 / 19 / 10 / 5; 6 / 12 / 8 / 4; 21 / 28 / 15 / 18), so the
> citation structure is invariant — only the pinned byte identities
> moved, and this table is the regeneration's own output.

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
