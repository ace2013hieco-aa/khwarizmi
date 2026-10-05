"""Golden tests for the B4 reference graphs (GR3-P2-b4fixtures, IDR-043).

Proves, against real SQLite + a real ArtifactStore + the REAL governed
documents read from disk:

1. the B4 reference cohort is a named, disjoint, bounded cohort inside
   the GOVERNED allowlist, while the P1a constant stays frozen;
2. the cohort's selection rule re-derives from the P1a six (every B4
   member is DIRECTLY cited by a member of the P1a six — no hand-picks);
3. the cohort enters governance ONLY through ``CorpusRepository``
   (real admission, byte round-trip, idempotent re-admission, no event);
4. every packaged fixture is content-addressed: regenerating from live
   bytes reproduces the committed file name (sha256) and bytes exactly;
5. the strict reader is closed (unknown keys, count drift, digest
   mismatch, self-edge, non-governed source, non-SIMULATED all refuse);
6. the baseline fixture reproduces the certified P1b graph exactly;
7. building is pure — the module holds no write path (no DB, no sqlite).
"""
from __future__ import annotations

import dataclasses
import hashlib
import sqlite3
from pathlib import Path

import pytest

from hermes.artifacts.store import ArtifactStore
from hermes.core.node import NodeContract
from hermes.core.task_status import TaskStatus
from hermes.persistence import corpus as pc
from hermes.persistence.corpus import CorpusRepository
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ArtifactRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.persistence.source_outcomes import SourceOutcomeRepository
from hermes.research import ref_graphs as rg
from hermes.research.corpus import (
    CORPUS_B4_COHORT_REFS,
    CORPUS_MAX_BYTES,
    CORPUS_REFS,
    GOVERNED_CORPUS_REFS,
    CorpusDraftError,
    build_corpus_admit_task_payload,
    load_corpus_bytes,
)
from hermes.research.graph_edges import (
    GR3_EXTRACTOR_VERSION,
    extract_cites_mentions,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / rg.B4_FIXTURES_DIRNAME

P1A_SIX = frozenset({
    "AGENTS.md",
    "docs/API.md",
    "docs/ARCHITECTURE.md",
    "docs/STATE.md",
    "docs/idr/IDR-024.md",
    "docs/idr/IDR-028.md",
})

#: The certified P1b v0 graph over the P1a six (tests/test_gr3_edges.py).
CERTIFIED_BASELINE = (
    ("AGENTS.md", "docs/API.md", "cites"),
    ("AGENTS.md", "docs/ARCHITECTURE.md", "cites"),
    ("AGENTS.md", "docs/STATE.md", "cites"),
    ("docs/API.md", "AGENTS.md", "cites"),
    ("docs/STATE.md", "docs/ARCHITECTURE.md", "cites"),
)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── fixtures ──

@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "B4")
    ProjectRepository(conn).create("p2", "Other")
    yield conn
    conn.close()


@pytest.fixture
def store(db, tmp_path):
    return ArtifactStore(tmp_path / "artifacts", ArtifactRepository(db))


@pytest.fixture
def corpus(db, store):
    return CorpusRepository(db, store)


# ── builders ──

def running_corpus_task(db: sqlite3.Connection, ref: str) -> str:
    payload = build_corpus_admit_task_payload(ref)
    tid = payload["task_id"]
    TaskRepository(db).create(NodeContract(
        task_id=tid,
        project_id="p1",
        task_type="TOOL_TASK",
        profile=payload["profile"],
        idempotency_key=tid,
        spec={"template": payload["spec"]["template"],
              "template_version": payload["spec"]["template_version"],
              "corpus_ref": ref}))
    TaskRepository(db).transition_status(tid, TaskStatus.READY)
    TaskRepository(db).transition_status(tid, TaskStatus.RUNNING)
    return tid


def admit(corpus: CorpusRepository, ref: str, task_id: str) -> dict:
    content = load_corpus_bytes(REPO_ROOT, ref)
    return corpus.record("p1", task_id, {
        "corpus_ref": ref,
        "content_hash": sha256_hex(content),
        "size_bytes": len(content),
    }, content)


def artifact_count(db: sqlite3.Connection) -> int:
    return db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]


def committed_graphs() -> tuple[rg.B4ReferenceGraph, ...]:
    return rg.build_all_reference_graphs(REPO_ROOT)


# ── 1. cohort shape + agreement ──

def test_p1a_constant_is_frozen_and_cohorts_are_disjoint():
    assert CORPUS_REFS == P1A_SIX, "P1a's certified corpus must not move"
    assert pc.CORPUS_REFS == CORPUS_REFS
    assert CORPUS_B4_COHORT_REFS, "the B4 cohort must not be empty"
    assert not (CORPUS_REFS & CORPUS_B4_COHORT_REFS), "cohorts overlap"
    assert GOVERNED_CORPUS_REFS == CORPUS_REFS | CORPUS_B4_COHORT_REFS
    assert pc.GOVERNED_CORPUS_REFS == GOVERNED_CORPUS_REFS
    assert pc.CORPUS_B4_COHORT_REFS == CORPUS_B4_COHORT_REFS
    assert len(GOVERNED_CORPUS_REFS) == 12


def test_cohort_members_are_real_bounded_documents():
    for ref in sorted(CORPUS_B4_COHORT_REFS):
        data = load_corpus_bytes(REPO_ROOT, ref)
        assert 0 < len(data) <= CORPUS_MAX_BYTES, ref


def test_selection_rule_rederives_from_the_p1a_six():
    """Every B4 member is DIRECTLY cited by a P1a-six document, and the
    direct-target set equals the cohort exactly — no hand-picked refs."""
    governed = tuple(sorted(GOVERNED_CORPUS_REFS))
    direct: set[str] = set()
    for ref in sorted(CORPUS_REFS):
        text = load_corpus_bytes(REPO_ROOT, ref).decode("utf-8")
        cited, _ = extract_cites_mentions(ref, text, governed)
        direct.update(cited)
    assert direct - CORPUS_REFS == set(CORPUS_B4_COHORT_REFS)


# ── 2. governed admission (the ONLY way a document enters) ──

def test_unlisted_ref_refuses_at_both_layers(db, corpus):
    outside = "docs/idr/IDR-040.md"
    assert outside not in GOVERNED_CORPUS_REFS
    with pytest.raises(CorpusDraftError):
        load_corpus_bytes(REPO_ROOT, outside)
    # Persistence layer: a hand-built task row that bypasses the
    # template is still refused by the boundary's own closed check.
    TaskRepository(db).create(NodeContract(
        task_id="hand-built", project_id="p1", task_type="TOOL_TASK",
        profile="DETERMINISTIC", idempotency_key="hand-built",
        spec={"template": "corpus_admit", "template_version": "1",
              "corpus_ref": outside}))
    TaskRepository(db).transition_status("hand-built", TaskStatus.READY)
    TaskRepository(db).transition_status("hand-built", TaskStatus.RUNNING)
    before = artifact_count(db)
    with pytest.raises(pc.CorpusIntegrityError):
        corpus.record("p1", "hand-built", {
            "corpus_ref": outside,
            "content_hash": sha256_hex(b"x"),
            "size_bytes": 1,
        }, b"x")
    assert artifact_count(db) == before


def test_b4_cohort_admits_through_corpus_repository(db, corpus, store):
    for ref in sorted(CORPUS_B4_COHORT_REFS):
        tid = running_corpus_task(db, ref)
        summary = admit(corpus, ref, tid)
        assert summary["decision"] == "NEW"
        assert summary["corpus_ref"] == ref
        assert len(summary["artifacts_written"]) == 1

    rows = db.execute(
        "SELECT artifact_id, artifact_type, content_hash FROM artifacts"
    ).fetchall()
    assert len(rows) == len(CORPUS_B4_COHORT_REFS)
    assert {r["artifact_type"] for r in rows} == {"source_payload"}
    edges = db.execute(
        "SELECT COUNT(*) FROM provenance_edges WHERE edge_type = "
        "'derived_from'").fetchone()[0]
    assert edges == len(CORPUS_B4_COHORT_REFS)
    # Admission is rows + edges only: no new event type appears.
    assert db.execute(
        "SELECT COUNT(*) FROM events WHERE event_type LIKE '%Corpus%'"
    ).fetchone()[0] == 0

    # Admitted bytes round-trip through the governed resolver to the
    # exact file on disk — the B4 build input. This is what makes each
    # fixture's recorded source_hash trustworthy.
    outcomes = SourceOutcomeRepository(db, store)
    for ref in sorted(CORPUS_B4_COHORT_REFS):
        content = load_corpus_bytes(REPO_ROOT, ref)
        ref_str = f"source_payload:{sha256_hex(content)}"
        assert outcomes.dereference_ref("p1", ref_str)
        assert outcomes.read_payload_bytes(ref_str) == content


def test_b4_readmission_is_idempotent(db, corpus):
    ref = sorted(CORPUS_B4_COHORT_REFS)[0]
    tid = running_corpus_task(db, ref)
    first = admit(corpus, ref, tid)
    before = artifact_count(db)
    second = admit(corpus, ref, tid)
    assert second["decision"] == "IDENTICAL"
    assert second["artifact_id"] == first["artifact_id"]
    assert second["artifacts_written"] == []
    assert artifact_count(db) == before


# ── 3. packaged fixtures are content-addressed + reproducible ──

def test_fixture_regeneration_reproduces_committed_bytes():
    assert FIXTURES_DIR.is_dir(), f"missing {rg.B4_FIXTURES_DIRNAME}"
    expected = {rg.fixture_filename(g) for g in committed_graphs()}
    on_disk = {p.name for p in FIXTURES_DIR.glob("*.json")}
    assert on_disk == expected, (
        "committed fixtures differ from regeneration — regenerate "
        "deliberately (docs/gr3-b4/b4-fixtures/README.md)")
    for graph in committed_graphs():
        path = FIXTURES_DIR / rg.fixture_filename(graph)
        data = path.read_bytes()
        assert rg.reference_graph_bytes(graph) == data
        assert path.stem == sha256_hex(data)
        assert path.stem == rg.reference_graph_digest(graph)


def test_fixture_build_is_deterministic():
    first = committed_graphs()
    second = committed_graphs()
    assert [(g.fixture_id, g.edges, g.sources, g.skipped)
            for g in first] == [(g.fixture_id, g.edges, g.sources,
                                 g.skipped) for g in second]


def test_every_fixture_records_extraction_version_and_markers():
    for graph in committed_graphs():
        assert graph.extraction_version == GR3_EXTRACTOR_VERSION == "1"
        assert graph.fixture_schema_version == "1"
        assert graph.namespace == "texp-001-twin"
        assert graph.consumption == "SIMULATED"
        assert graph.authority == "ADVISORY"


def test_every_fixture_source_set_is_governed_and_bounded():
    for graph in committed_graphs():
        refs = [s.corpus_ref for s in graph.sources]
        assert refs == sorted(refs)
        assert set(refs) <= GOVERNED_CORPUS_REFS
        for source in graph.sources:
            data = load_corpus_bytes(REPO_ROOT, source.corpus_ref)
            assert source.content_hash == sha256_hex(data)
            assert source.size_bytes == len(data)


def test_baseline_fixture_reproduces_the_certified_p1b_graph():
    baseline = next(g for g in committed_graphs()
                    if g.fixture_id == "b4-c1-p1a-baseline")
    assert baseline.edges == CERTIFIED_BASELINE
    assert {s.corpus_ref for s in baseline.sources} == P1A_SIX


def test_expanded_cohort_fixture_is_the_governed_graph():
    expanded = next(g for g in committed_graphs()
                    if g.fixture_id == "b4-c2-expanded-cohort")
    assert {s.corpus_ref for s in expanded.sources} == GOVERNED_CORPUS_REFS
    assert len(expanded.edges) == 19
    refs = GOVERNED_CORPUS_REFS
    for citing, cited, etype in expanded.edges:
        assert citing in refs and cited in refs and citing != cited
        assert etype == "cites"
    baseline = next(g for g in committed_graphs()
                    if g.fixture_id == "b4-c1-p1a-baseline")
    assert set(baseline.edges) <= set(expanded.edges)


def test_b4_strict_reader_round_trips_every_committed_fixture():
    for graph in committed_graphs():
        data = (FIXTURES_DIR / rg.fixture_filename(graph)).read_bytes()
        parsed = rg.parse_reference_graph(
            data, expected_digest=rg.reference_graph_digest(graph))
        assert rg.reference_graph_body(parsed) == rg.reference_graph_body(
            graph)


# ── 4. the reader fails closed ──

def _fixture_bytes(fixture_id: str) -> bytes:
    graph = next(g for g in committed_graphs()
                 if g.fixture_id == fixture_id)
    return (FIXTURES_DIR / rg.fixture_filename(graph)).read_bytes()


def test_reader_refuses_digest_mismatch():
    data = _fixture_bytes("b4-c1-p1a-baseline")
    with pytest.raises(rg.B4FixtureError):
        rg.parse_reference_graph(data, expected_digest="0" * 64)


def test_reader_refuses_unknown_keys():
    data = _fixture_bytes("b4-c1-p1a-baseline")
    doctored = data.replace(b'"edges":', b'"smuggled": 1, "edges":')
    with pytest.raises(rg.B4FixtureError):
        rg.parse_reference_graph(doctored)


def test_reader_refuses_count_drift():
    data = _fixture_bytes("b4-c1-p1a-baseline")
    doctored = data.replace(b'"edges":5', b'"edges":4')
    with pytest.raises(rg.B4FixtureError):
        rg.parse_reference_graph(doctored)


def test_reader_refuses_non_governed_source():
    data = _fixture_bytes("b4-c1-p1a-baseline")
    doctored = data.replace(
        b'"corpus_ref":"AGENTS.md"',
        b'"corpus_ref":"docs/idr/IDR-040.md"')
    with pytest.raises(rg.B4FixtureError):
        rg.parse_reference_graph(doctored)


def test_reader_refuses_non_simulated_consumption():
    data = _fixture_bytes("b4-c1-p1a-baseline")
    doctored = data.replace(
        b'"consumption":"SIMULATED"', b'"consumption":"PRODUCTION"')
    with pytest.raises(rg.B4FixtureError):
        rg.parse_reference_graph(doctored)


def test_reader_refuses_foreign_namespace():
    data = _fixture_bytes("b4-c1-p1a-baseline")
    doctored = data.replace(
        b'"namespace":"texp-001-twin"', b'"namespace":"mainline"')
    with pytest.raises(rg.B4FixtureError):
        rg.parse_reference_graph(doctored)


def test_reader_refuses_self_edge():
    data = _fixture_bytes("b4-c1-p1a-baseline")
    doctored = data.replace(
        b'"cited_ref":"docs/API.md"', b'"cited_ref":"AGENTS.md"', 1)
    with pytest.raises(rg.B4FixtureError):
        rg.parse_reference_graph(doctored)


# ── 5. build contract: closed source set, pure module ──

def test_builder_refuses_missing_and_unlisted_sources():
    spec = rg.B4_FIXTURE_SPECS[0]
    refs = list(spec.source_refs)
    payload = {ref: load_corpus_bytes(REPO_ROOT, ref)
               for ref in refs[:-1]}
    with pytest.raises(rg.B4FixtureError):
        rg.build_reference_graph(spec, payload)
    payload[refs[-1]] = load_corpus_bytes(REPO_ROOT, refs[-1])
    payload["docs/idr/IDR-040.md"] = b"outside the source set"
    with pytest.raises(rg.B4FixtureError):
        rg.build_reference_graph(spec, payload)


def test_builder_refuses_an_ungoverned_spec():
    bad = dataclasses.replace(rg.B4_FIXTURE_SPECS[0],
                              source_refs=("docs/idr/IDR-040.md",))
    with pytest.raises(rg.B4FixtureError):
        rg.build_reference_graph(bad, {bad.source_refs[0]: b"x"})


def test_build_path_holds_no_write_surface():
    """Pure substrate: no persistence import, no SQL, no transaction."""
    source = Path(rg.__file__).read_text(encoding="utf-8")
    assert "hermes.persistence" not in source
    assert "sqlite3" not in source
    assert "BEGIN IMMEDIATE" not in source


def test_fixture_specs_have_unique_ids_and_governed_sources():
    ids = [s.fixture_id for s in rg.B4_FIXTURE_SPECS]
    assert len(ids) == len(set(ids)) >= 3
    for spec in rg.B4_FIXTURE_SPECS:
        assert set(spec.source_refs) <= GOVERNED_CORPUS_REFS
