"""Q-04 §5 extension — the artifact-layer blast radius: a forward
reachability query over ``provenance_edges`` so a retracted or superseded
source artifact surfaces every downstream artifact needing re-review.

The pure traversal lives in ``core/graph.py`` (artifact_blast_radius — the
artifact analog of change_blast_radius); the controller exposes it as a
read-only, version-bound, hashed advisory surface — the Q-04 §4 posture:
CANNOT retract, invalidate, or modify anything.
"""
from __future__ import annotations

import pytest

from hermes.core import utc_now
from hermes.core.graph import (
    GRAPH_QUERY_VERSION,
    ArtifactBlastEntry,
    artifact_blast_radius,
    graph_result_hash,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository
from hermes.research.controller import Controller

CLOCK = "2026-08-15T10:00:00Z"


def _edge_downstream():
    """upstream -> [(artifact_id, edge_type)] — the provenance_edges shape:
    the artifact cites/derives from the upstream."""
    return {
        "src-a": [("b1", "cites"), ("b2", "derived_from")],
        "b1": [("c1", "derived_from"), ("c2", "justifies")],
        "b2": [("c3", "used_as_input")],
    }


def _entry(artifact_id, via, edge_type):
    return ArtifactBlastEntry(artifact_id=artifact_id, reached_via=via,
                              edge_type=edge_type)


class TestPureArtifactBlastRadius:
    def test_transitive_closure_with_root_cause_label(self):
        """Every downstream artifact across 2 hops is surfaced, each labeled
        by the ROOT seed (the failure_cone convention: first ancestor)."""
        radius = artifact_blast_radius(["src-a"], _edge_downstream())
        assert radius == (
            _entry("b1", "src-a", "cites"),
            _entry("b2", "src-a", "derived_from"),
            _entry("c1", "src-a", "derived_from"),
            _entry("c2", "src-a", "justifies"),
            _entry("c3", "src-a", "used_as_input"),
        )

    def test_edge_type_is_carried(self):
        radius = artifact_blast_radius(["b1"], _edge_downstream())
        assert radius == (
            _entry("c1", "b1", "derived_from"),
            _entry("c2", "b1", "justifies"),
        )

    def test_seeds_are_origin_never_result(self):
        radius = artifact_blast_radius(["src-a"], {"src-a": [("src-a", "cites")]})
        # a self-edge is impossible (CHECK artifact_id != upstream_id) — and
        # even hand-inserted, the seed is never a result.
        assert radius == ()
        assert artifact_blast_radius(["src-a"], {"src-a": [("b1", "cites")]}) == (
            _entry("b1", "src-a", "cites"),)

    def test_cycle_terminates(self):
        down = {"a": [("b", "cites")], "b": [("a", "cites")]}
        assert artifact_blast_radius(["a"], down) == (_entry("b", "a", "cites"),)

    def test_unknown_seed_is_empty(self):
        assert artifact_blast_radius(["nope"], _edge_downstream()) == ()

    def test_deterministic_and_sorted(self):
        first = artifact_blast_radius(["src-a"], _edge_downstream())
        assert artifact_blast_radius(["src-a"], _edge_downstream()) == first
        assert [e.artifact_id for e in first] == sorted(
            e.artifact_id for e in first)

    def test_sorted_seed_order_does_not_change_result(self):
        down = {"s1": [("x", "cites")],
                "s2": [("x", "derived_from"), ("y", "cites")]}
        a = artifact_blast_radius(["s2", "s1"], down)
        b = artifact_blast_radius(["s1", "s2"], down)
        assert a == b
        # first-visit-wins is deterministic: sorted seeds -> s1 reaches x first.
        assert a == (
            _entry("x", "s1", "cites"),
            _entry("y", "s2", "cites"),
        )

    def test_result_hash_binds_version_and_kind(self):
        h1 = graph_result_hash("artifact_blast_radius", [{"artifact_id": "x"}])
        h2 = graph_result_hash("failure_cone", [{"artifact_id": "x"}])
        assert h1 != h2
        assert h1 == graph_result_hash("artifact_blast_radius",
                                       [{"artifact_id": "x"}])

    def test_no_write_sql_in_the_pure_module(self):
        """The extension keeps the AC-7 authority scan: no write surface in
        core/graph.py (the traversal is a derived view, nothing more)."""
        import ast
        import inspect

        import hermes.core.graph as graph
        tree = ast.parse(inspect.getsource(graph))
        for node in ast.walk(tree):
            if (isinstance(node, (ast.Module, ast.FunctionDef,
                                  ast.AsyncFunctionDef, ast.ClassDef))
                    and node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body = node.body[1:]
        src = ast.unparse(tree)
        for banned in ("INSERT INTO", "UPDATE ", "DELETE FROM",
                       "REPLACE INTO", "sqlite3", "conn.execute"):
            assert banned not in src, (
                f"write surface leaked into core/graph.py: {banned!r}")


@pytest.fixture
def db():
    conn = __import__("sqlite3").connect(":memory:")
    conn.row_factory = __import__("sqlite3").Row
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    ProjectRepository(conn).create("p2", "Other")
    yield conn
    conn.close()


def _artifact(conn, artifact_id, project_id="p1", *, task_id=None,
              artifact_type="evidence"):
    conn.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, 0, 'inline://test', 'test', NULL, ?)""",
        (artifact_id, project_id, task_id, artifact_type,
         "ch-" + artifact_id, CLOCK),
    )


def _edge(conn, artifact_id, upstream_id, edge_type="cites"):
    conn.execute(
        "INSERT INTO provenance_edges "
        "(artifact_id, upstream_id, edge_type, created_at) "
        "VALUES (?, ?, ?, ?)",
        (artifact_id, upstream_id, edge_type, CLOCK),
    )


def _make(conn, **kwargs):
    return Controller(conn, project_id="p1", clock=utc_now, **kwargs)


class TestControllerArtifactSurface:
    def test_surfaces_transitive_downstream_with_version_and_hash(self, db):
        conn = db
        _artifact(conn, "src-a")
        _artifact(conn, "b1")
        _artifact(conn, "c1")
        _edge(conn, "b1", "src-a", "derived_from")
        _edge(conn, "c1", "b1", "derived_from")
        out = _make(conn).artifact_blast_radius(["src-a"])
        assert out["version"] == GRAPH_QUERY_VERSION
        assert out["items"] == [{
            "artifact_id": "b1", "reached_via": "src-a",
            "edge_type": "derived_from",
        }, {
            "artifact_id": "c1", "reached_via": "src-a",
            "edge_type": "derived_from",
        }]
        assert out["content_hash"] == graph_result_hash(
            "artifact_blast_radius", out["items"])

    def test_project_scoped(self, db):
        conn = db
        # p1 seed; p1 downstream reached; p2 downstream excluded.
        _artifact(conn, "src-a", "p1")
        _artifact(conn, "b1", "p1")
        _artifact(conn, "b2", "p2")
        _edge(conn, "b1", "src-a", "cites")
        _edge(conn, "b2", "src-a", "cites")
        items = _make(conn).artifact_blast_radius(["src-a"])["items"]
        assert [i["artifact_id"] for i in items] == ["b1"]

    def test_never_writes(self, db):
        conn = db
        _artifact(conn, "src-a")
        _artifact(conn, "b1")
        _edge(conn, "b1", "src-a", "cites")
        ctrl = _make(conn)
        before_a = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        before_e = conn.execute(
            "SELECT COUNT(*) FROM provenance_edges").fetchone()[0]
        ctrl.artifact_blast_radius(["src-a"])
        assert conn.execute(
            "SELECT COUNT(*) FROM artifacts").fetchone()[0] == before_a
        assert conn.execute(
            "SELECT COUNT(*) FROM provenance_edges").fetchone()[0] == before_e
        # and the surface agrees with itself (determinism).
        assert ctrl.artifact_blast_radius(["src-a"]) ==             ctrl.artifact_blast_radius(["src-a"])
