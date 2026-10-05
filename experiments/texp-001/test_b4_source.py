"""TEXP-001 B4 SOURCE — read-path tests for the GR3 reference graphs.

ADDITIVE (GR3-P2-b4fixtures): this is a NEW file; the synthetic F1–F7
fixture suite (`test_fixtures.py`) is untouched and unmodified.

These tests DEMONSTRATE the single read path the B4 task asks for —
consuming a packaged reference graph from the twin side — and prove that
read is fail-closed. No experiment is executed: no arm, no kernel, no
energy function, no validator run, no production import. Reading a B4
fixture yields data only.

The B4 handoff is a mainline artifact (`docs/gr3-b4/b4-fixtures/`). When
it is absent (a twin-only branch) the whole module skips, so the twin's
own suite stays green rather than failing on a missing cross-namespace
dependency.

Run: .venv/Scripts/python.exe -m pytest experiments/texp-001/test_b4_source.py -q
"""

import hashlib
import json
from pathlib import Path

import pytest
from fixtures import (
    B4_NAMESPACE,
    B4FixtureError,
    _b4_parse,
    b4_available,
    b4_fixture_ids,
    b4_reference_graph,
    b4_reference_graphs,
)
from validator import EDGE_ALPHABET

pytestmark = pytest.mark.skipif(
    not b4_available(),
    reason="B4 mainline handoff (docs/gr3-b4/b4-fixtures) is absent; "
           "the twin consumes it only when present")

#: The certified P1b v0 graph over the P1a six (tests/test_gr3_edges.py).
BASELINE_EDGES = (
    ("AGENTS.md", "docs/API.md", "cites"),
    ("AGENTS.md", "docs/ARCHITECTURE.md", "cites"),
    ("AGENTS.md", "docs/STATE.md", "cites"),
    ("docs/API.md", "AGENTS.md", "cites"),
    ("docs/STATE.md", "docs/ARCHITECTURE.md", "cites"),
)


def _fixture_file(fixture_id: str) -> Path:
    from fixtures import b4_fixtures_dir
    directory = b4_fixtures_dir()
    assert directory is not None
    graph = b4_reference_graph(fixture_id)
    return Path(directory) / f"{graph.digest}.json"


# ── the read path ──

def test_b4_source_exposes_the_packaged_handful():
    ids = b4_fixture_ids()
    assert "b4-c1-p1a-baseline" in ids
    assert "b4-c2-expanded-cohort" in ids
    assert len(ids) == len(set(ids)) >= 3


def test_read_baseline_fixture_returns_the_certified_graph():
    graph = b4_reference_graph("b4-c1-p1a-baseline")
    assert graph.fixture_id == "b4-c1-p1a-baseline"
    assert graph.twin_ref == "texp001:b4/b4-c1-p1a-baseline"
    assert graph.namespace == B4_NAMESPACE
    assert graph.consumption == "SIMULATED"
    assert graph.authority == "ADVISORY"
    assert graph.extraction_version == "1"
    assert len(graph.digest) == 64
    assert len(graph.sources) == 6
    assert graph.edges == BASELINE_EDGES


def test_read_expanded_cohort_fixture():
    graph = b4_reference_graph("b4-c2-expanded-cohort")
    assert len(graph.sources) == 12
    assert len(graph.edges) == 19
    assert all(etype == "cites" for _, _, etype in graph.edges)
    assert all(citing != cited for citing, cited, _ in graph.edges)


def test_read_binding_is_the_file_digest():
    graph = b4_reference_graph("b4-c2-expanded-cohort")
    data = _fixture_file("b4-c2-expanded-cohort").read_bytes()
    assert hashlib.sha256(data).hexdigest() == graph.digest


def test_every_available_fixture_reads_and_verifies():
    graphs = b4_reference_graphs()
    assert len(graphs) >= 3
    for graph in graphs:
        assert len(graph.digest) == 64
        assert graph.namespace == B4_NAMESPACE
        assert graph.consumption == "SIMULATED"


def test_read_path_returns_data_only():
    """No executable payload: reading never hands the twin a callable."""
    graph = b4_reference_graph("b4-c2-expanded-cohort")
    for field in type(graph).__slots__:
        assert not callable(getattr(graph, field))


def test_b4_edge_type_is_not_a_twin_alphabet_member():
    """Honest limit, recorded: B4 graphs are reference structure, not yet
    admissible sequences — `cites` is outside the twin's 14-class
    alphabet, so nothing here is runnable as a benchmark instance."""
    graph = b4_reference_graph("b4-c2-expanded-cohort")
    assert {etype for _, _, etype in graph.edges} == {"cites"}
    assert "cites" not in EDGE_ALPHABET


# ── the read fails closed ──

def test_read_unknown_fixture_id_refuses():
    with pytest.raises(B4FixtureError):
        b4_reference_graph("b4-does-not-exist")


def test_read_refuses_edited_bytes():
    graph = b4_reference_graph("b4-c1-p1a-baseline")
    data = _fixture_file("b4-c1-p1a-baseline").read_bytes()
    with pytest.raises(B4FixtureError):
        _b4_parse(data + b" ", graph.digest)


def test_read_refuses_non_simulated_consumption():
    data = _fixture_file("b4-c1-p1a-baseline").read_bytes()
    doctored = data.replace(b'"consumption":"SIMULATED"',
                            b'"consumption":"PRODUCTION"')
    digest = hashlib.sha256(doctored).hexdigest()
    with pytest.raises(B4FixtureError):
        _b4_parse(doctored, digest)


def test_read_refuses_foreign_namespace():
    data = _fixture_file("b4-c1-p1a-baseline").read_bytes()
    doctored = data.replace(b'"namespace":"texp-001-twin"',
                            b'"namespace":"mainline"')
    digest = hashlib.sha256(doctored).hexdigest()
    with pytest.raises(B4FixtureError):
        _b4_parse(doctored, digest)


def test_read_refuses_unknown_keys_and_self_edges():
    data = _fixture_file("b4-c1-p1a-baseline").read_bytes()
    body = json.loads(data.decode("utf-8"))
    body["smuggled"] = 1
    doctored = (json.dumps(body, sort_keys=True,
                           separators=(",", ":")) + "\n").encode("utf-8")
    with pytest.raises(B4FixtureError):
        _b4_parse(doctored, hashlib.sha256(doctored).hexdigest())
    body.pop("smuggled")
    body["edges"][0]["cited_ref"] = body["edges"][0]["citing_ref"]
    doctored = (json.dumps(body, sort_keys=True,
                           separators=(",", ":")) + "\n").encode("utf-8")
    with pytest.raises(B4FixtureError):
        _b4_parse(doctored, hashlib.sha256(doctored).hexdigest())
