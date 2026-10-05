"""P1b-audit2 independent probes (audit evidence, not part of product).

Written against the live API surface only; expectations are asserted
explicitly as counts (not codes).
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")

from hermes.artifacts.store import ArtifactStore
from hermes.core.node import NodeContract
from hermes.core.task_status import TaskStatus
from hermes.persistence.corpus import CorpusRepository
from hermes.persistence.database import connect
from hermes.persistence.graph_edges import GraphEdgeRepository
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ArtifactRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.research.corpus import (
    CORPUS_REFS,
    build_corpus_admit_task_payload,
    load_corpus_bytes,
)
from hermes.research.graph_edges import (
    extract_cites_mentions,
    gr3_edge_draft_from_mapping,
    validate_gr3_extraction,
)

ROOT = Path(__file__).resolve().parent.parent
ALL_REFS = sorted(CORPUS_REFS)

# Anchored expectations, independent of P1b-extraction.md's table:
# verified by direct read of the live documents before writing them here.
EXPECT_CITED = {
    "AGENTS.md": {"docs/API.md", "docs/ARCHITECTURE.md", "docs/STATE.md"},
    "docs/API.md": {"AGENTS.md"},
    "docs/STATE.md": {"docs/ARCHITECTURE.md"},
    "docs/ARCHITECTURE.md": set(),
    "docs/idr/IDR-024.md": set(),
    "docs/idr/IDR-028.md": set(),
}
EXPECT_TRIPLES = 5


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Graph")
    ProjectRepository(conn).create("p2", "Other")
    with tempfile.TemporaryDirectory() as td:
        store = ArtifactStore(Path(td), ArtifactRepository(conn))
        yield conn, store


def running_task(conn, payload, *, project="p1", suffix=""):
    node = NodeContract(
        task_id=payload["task_id"] + suffix, project_id=project,
        task_type="TOOL_TASK", profile=payload["profile"],
        idempotency_key=payload["idempotency_key"] + suffix,
        spec=payload["spec"])
    TaskRepository(conn).create(node)
    TaskRepository(conn).transition_status(node.task_id, TaskStatus.READY)
    TaskRepository(conn).transition_status(node.task_id, TaskStatus.RUNNING)
    return node.task_id


def cites_rows(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM provenance_edges WHERE edge_type = 'cites'"
    ).fetchone()[0]


def main() -> int:
    failures: list[str] = []

    # -- probe 1: extractor over the real corpus, independent expectations --
    for conn, store in make_db():
        corpus = CorpusRepository(conn, store)
        admitted: dict[str, str] = {}
        aids: dict[str, str] = {}
        for ref in ALL_REFS:
            payload = build_corpus_admit_task_payload(ref)
            tid = running_task(conn, payload)
            content = load_corpus_bytes(ROOT, ref)
            summary = corpus.record("p1", tid, {
                "corpus_ref": ref, "content_hash": sha(content),
                "size_bytes": len(content)}, content)
            admitted[ref] = sha(content)
            aids[ref] = summary["artifact_id"]

        print("probe 1: extractor on six real documents")
        for ref in ALL_REFS:
            content = load_corpus_bytes(ROOT, ref)
            cited, skipped = extract_cites_mentions(
                ref, content.decode("utf-8"), tuple(ALL_REFS))
            want = EXPECT_CITED[ref]
            ok = set(cited) == want
            if not ok:
                failures.append(f"{ref}: cited {set(cited)} != {want}")
            print(f"  {ref}: cited={sorted(cited)} skipped={sorted(skipped)}"
                  f" {'OK' if ok else 'MISMATCH'}")
        n = sum(len(v) for v in EXPECT_CITED.values())
        if n != EXPECT_TRIPLES:
            failures.append(f"expected total {n} != {EXPECT_TRIPLES}")

        # -- probe 2: validator determinism, byte-identical reruns --
        print("probe 2: validator determinism (ADMITTED twice, identical)")
        for ref in ALL_REFS:
            content = load_corpus_bytes(ROOT, ref)
            cited, _ = extract_cites_mentions(
                ref, content.decode("utf-8"), tuple(ALL_REFS))
            claimed = [{"citing_ref": ref, "cited_ref": c,
                        "edge_type": "cites"} for c in cited]
            hashes = {c: admitted[c] for c in cited}
            r1 = validate_gr3_extraction(
                ref, content, tuple(claimed), hashes, tuple(ALL_REFS))
            r2 = validate_gr3_extraction(
                ref, content, tuple(claimed), hashes, tuple(ALL_REFS))
            if str(r1) != str(r2):
                failures.append(f"{ref}: rerun differs")
            if r1.verdict.value != "ADMITTED":
                failures.append(f"{ref}: verdict {r1.verdict}")

        # -- probe 3: forgery battery, count-based zero writes --
        print("probe 3: forgery battery (each must refuse; rows frozen)")

        def forge_case(name, ref, claimed, hashes_map):
            before = cites_rows(conn)
            content = load_corpus_bytes(ROOT, ref)
            result = validate_gr3_extraction(
                ref, content, tuple(claimed), hashes_map, tuple(ALL_REFS))
            tid = running_task(conn, build_corpus_admit_task_payload(ref),
                               suffix="-forge-" + name)
            # NOTE: producing task for the record call must match template;
            # use the gr3-style spec so binding passes and we test the
            # integrity path specifically.
            node = TaskRepository(conn)
            # Build a proper gr3 task for this ref.
            from hermes.research.graph_edges import (
                build_gr3_extract_task_payload,
            )
            payload = build_gr3_extract_task_payload(ref)
            gr3_node = NodeContract(
                task_id=payload["task_id"] + "-forge-" + name,
                project_id="p1", task_type="TOOL_TASK",
                profile=payload["profile"],
                idempotency_key=payload["idempotency_key"] + "-forge-" + name,
                spec=payload["spec"])
            TaskRepository(conn).create(gr3_node)
            TaskRepository(conn).transition_status(
                gr3_node.task_id, TaskStatus.READY)
            TaskRepository(conn).transition_status(
                gr3_node.task_id, TaskStatus.RUNNING)
            mapping = {
                "verdict": result.verdict.value,
                "citing_ref": result.citing_ref,
                "citing_hash": result.citing_hash,
                "extractor_version": result.extractor_version,
                "edges": [{"citing_ref": e.citing_ref,
                           "cited_ref": e.cited_ref,
                           "edge_type": e.edge_type}
                          for e in result.edges],
                "skipped": list(result.skipped),
                "errors": list(result.errors),
            }
            refused = False
            try:
                GraphEdgeRepository(conn).record(
                    "p1", gr3_node.task_id, mapping, content, hashes_map)
            except Exception:
                refused = True
            after = cites_rows(conn)
            if not refused:
                # Only acceptable if the verdict was already INVALID and the
                # mapping carries a non-ADMITTED verdict.
                if result.verdict.value == "ADMITTED":
                    failures.append(f"{name}: forged ADMITTED batch wrote")
                elif after != before:
                    failures.append(f"{name}: rows changed {before}->{after}")
            elif after != before:
                failures.append(f"{name}: refuse but rows {before}->{after}")
            print(f"  {name}: verdict={result.verdict.value} "
                  f"refused={refused} rows {before}->{after}")

        ag = "AGENTS.md"
        content_ag = load_corpus_bytes(ROOT, ag)
        cited_ag, _ = extract_cites_mentions(
            ag, content_ag.decode("utf-8"), tuple(ALL_REFS))
        base_claim = [{"citing_ref": ag, "cited_ref": c,
                       "edge_type": "cites"} for c in cited_ag]

        # (1) forge one mention
        forge_case("forge-one", ag,
                   base_claim + [{"citing_ref": ag, "cited_ref": "docs/idr/IDR-024.md",
                                  "edge_type": "cites"}],
                   dict(admitted))
        # (2) drop one mention
        forge_case("drop-one", ag, base_claim[:-1], dict(admitted))
        # (3) unknown type
        from hermes.research.graph_edges import GR3EdgeError
        try:
            gr3_edge_draft_from_mapping(
                {"citing_ref": ag, "cited_ref": "docs/API.md",
                 "edge_type": "derived_from"})
            failures.append("unknown-type: mapper accepted")
        except GR3EdgeError:
            print("  unknown-type: mapper refused (GR3EdgeError)")
        # (4) dangle an endpoint (cited not admitted in p1)
        p1_only = {ag: admitted[ag]}
        forge_case("dangle", ag, base_claim, p1_only)
        # (5) substitute metadata (swap ARCH's hash for API's)
        lied = dict(admitted)
        lied["docs/ARCHITECTURE.md"] = admitted["docs/API.md"]
        forge_case("substitute", ag, base_claim, lied)
        # (6) cross-project: citing admitted in p1, cited docs ONLY in p2.
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM provenance_edges")
        conn.execute("DELETE FROM artifacts")
        conn.execute("DELETE FROM tasks")
        conn.execute("PRAGMA foreign_keys=ON")
        corpus2 = CorpusRepository(conn, store)
        # p1: citing doc only
        p_ag = build_corpus_admit_task_payload(ag)
        t_ag = running_task(conn, p_ag, suffix="-cp1")
        corpus2.record("p1", t_ag, {"corpus_ref": ag,
                                    "content_hash": sha(content_ag),
                                    "size_bytes": len(content_ag)},
                       content_ag)
        # p2: all six
        p2hashes = {}
        for r in ALL_REFS:
            p = build_corpus_admit_task_payload(r)
            t = running_task(conn, p, project="p2", suffix="-cp2")
            c = load_corpus_bytes(ROOT, r)
            corpus2.record("p2", t, {"corpus_ref": r,
                                     "content_hash": sha(c),
                                     "size_bytes": len(c)}, c)
            p2hashes[r] = sha(c)
        cited_ag, _ = extract_cites_mentions(
            ag, content_ag.decode("utf-8"), tuple(ALL_REFS))
        base_claim = [{"citing_ref": ag, "cited_ref": c,
                       "edge_type": "cites"} for c in cited_ag]
        # integrity layer must refuse: cited hashes resolve only in p2
        before = cites_rows(conn)
        from hermes.research.graph_edges import build_gr3_extract_task_payload
        p = build_gr3_extract_task_payload(ag)
        t = running_task(conn, p, suffix="-cp3")
        result = validate_gr3_extraction(
            ag, content_ag, tuple(base_claim), p2hashes, tuple(ALL_REFS))
        mapping = {
            "verdict": result.verdict.value, "citing_ref": result.citing_ref,
            "citing_hash": result.citing_hash,
            "extractor_version": result.extractor_version,
            "edges": [{"citing_ref": e.citing_ref, "cited_ref": e.cited_ref,
                       "edge_type": e.edge_type} for e in result.edges],
            "skipped": list(result.skipped), "errors": list(result.errors),
        }
        refused = False
        try:
            GraphEdgeRepository(conn).record(
                "p1", t, mapping, content_ag, p2hashes)
        except Exception:
            refused = True
        after = cites_rows(conn)
        print(f"  cross-project: verdict={result.verdict.value} "
              f"refused={refused} rows {before}->{after}")
        if result.verdict.value != "ADMITTED" or not refused \
                or after != before:
            failures.append("cross-project: did not refuse at the boundary")

        # baseline sanity: admit all six in p1, honest batch writes exactly 3
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM provenance_edges")
        conn.execute("DELETE FROM artifacts")
        conn.execute("DELETE FROM tasks")
        conn.execute("PRAGMA foreign_keys=ON")
        admitted = {}
        for r in ALL_REFS:
            pp = build_corpus_admit_task_payload(r)
            tt = running_task(conn, pp, suffix="-r3")
            cc = load_corpus_bytes(ROOT, r)
            corpus2.record("p1", tt, {"corpus_ref": r,
                                      "content_hash": sha(cc),
                                      "size_bytes": len(cc)}, cc)
            admitted[r] = sha(cc)
        cited_ag, _ = extract_cites_mentions(
            ag, content_ag.decode("utf-8"), tuple(ALL_REFS))
        base_claim = [{"citing_ref": ag, "cited_ref": c,
                       "edge_type": "cites"} for c in cited_ag]
        before = cites_rows(conn)
        p = build_gr3_extract_task_payload(ag)
        t = running_task(conn, p, suffix="-honest")
        result = validate_gr3_extraction(
            ag, content_ag, tuple(base_claim), dict(admitted), tuple(ALL_REFS))
        mapping = {
            "verdict": result.verdict.value, "citing_ref": result.citing_ref,
            "citing_hash": result.citing_hash,
            "extractor_version": result.extractor_version,
            "edges": [{"citing_ref": e.citing_ref, "cited_ref": e.cited_ref,
                       "edge_type": e.edge_type} for e in result.edges],
            "skipped": list(result.skipped), "errors": list(result.errors),
        }
        s = GraphEdgeRepository(conn).record(
            "p1", t, mapping, content_ag, dict(admitted))
        after = cites_rows(conn)
        print(f"  honest-baseline: wrote {s['edges_written']} "
              f"rows {before}->{after}")
        if s["edges_written"] != 3 or after - before != 3:
            failures.append("honest baseline did not write exactly 3")

    print()
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("ALL PROBES HELD")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
