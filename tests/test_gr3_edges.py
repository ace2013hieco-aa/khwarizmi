"""Golden tests for the P1b GR3 v0 cites extraction (fully deterministic).

Proves against real SQLite, on the REAL six corpus documents:
1. end-to-end cites extraction per document with anchored expectations
   (AGENTS→3, API→1, STATE→1, ARCH/IDR-024/IDR-028→EMPTY no-op);
2. determinism (same bytes ⇒ same sets, twice);
3. hallucinated or dropped edges ⇒ INVALID ⇒ record refuses, zero writes;
4. unknown/out-of-scope edge types (supports, entails, derived_from,
   used_as_input, …) fail closed at the mapping layer and the write path;
5. re-extraction idempotent (IDENTICAL, counts frozen, same triples);
6. unbound batches refuse (missing task, non-RUNNING, wrong template,
   spec mismatch) with zero writes;
7. dangling cited endpoints and ref→hash substitution refuse the whole
   batch with zero writes;
8. extraction emits no event; research/persistence agreement constants
   are byte-identical; self-mentions never become self-edges.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from hermes.artifacts.store import ArtifactStore
from hermes.core.node import NodeContract
from hermes.core.task_status import TaskStatus
from hermes.persistence.corpus import CorpusRepository
from hermes.persistence.database import connect
from hermes.persistence.graph_edges import GR3_EDGE_SCHEMA_VERSION as P_SCHEMA
from hermes.persistence.graph_edges import (
    GR3_EDGE_TYPES as P_EDGE_TYPES,
)
from hermes.persistence.graph_edges import GR3_EXTRACT_TEMPLATE as P_TEMPLATE
from hermes.persistence.graph_edges import GR3_EXTRACTOR_VERSION as P_XVERSION
from hermes.persistence.graph_edges import GR3_TEMPLATE_VERSION as P_TVERSION
from hermes.persistence.graph_edges import (
    GraphEdgeBindingError,
    GraphEdgeIntegrityError,
    GraphEdgeRepository,
)
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ArtifactRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.research import graph_edges as rgedges
from hermes.research.corpus import (
    CORPUS_REFS,
    build_corpus_admit_task_payload,
    load_corpus_bytes,
)
from hermes.research.graph_edges import (
    GR3_EDGE_TYPES,
    GR3EdgeError,
    build_gr3_extract_task_payload,
    extract_cites_mentions,
    gr3_edge_draft_from_mapping,
    mention_forms_for,
    validate_gr3_extraction,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ALL_REFS = sorted(CORPUS_REFS)

AGENTS = "AGENTS.md"
API = "docs/API.md"
ARCH = "docs/ARCHITECTURE.md"
STATE = "docs/STATE.md"
IDR24 = "docs/idr/IDR-024.md"
IDR28 = "docs/idr/IDR-028.md"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── fixtures ──

@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Graph")
    ProjectRepository(conn).create("p2", "Other")
    yield conn
    conn.close()


@pytest.fixture
def store(db, tmp_path):
    return ArtifactStore(tmp_path / "artifacts", ArtifactRepository(db))


@pytest.fixture
def corpus(db, store):
    return CorpusRepository(db, store)


@pytest.fixture
def edges(db):
    return GraphEdgeRepository(db)


# ── builders ──

def _running(db: sqlite3.Connection, node: NodeContract) -> str:
    TaskRepository(db).create(node)
    TaskRepository(db).transition_status(node.task_id, TaskStatus.READY)
    TaskRepository(db).transition_status(node.task_id, TaskStatus.RUNNING)
    return node.task_id


def admit_doc(db, corpus, ref, *, project="p1", suffix=""):
    payload = build_corpus_admit_task_payload(ref)
    tid = _running(db, NodeContract(
        task_id=payload["task_id"] + suffix,
        project_id=project, task_type="TOOL_TASK",
        profile=payload["profile"],
        idempotency_key=payload["idempotency_key"] + suffix,
        spec={"template": payload["spec"]["template"],
              "template_version": "1", "corpus_ref": ref}))
    content = load_corpus_bytes(REPO_ROOT, ref)
    summary = corpus.record(project, tid, {
        "corpus_ref": ref, "content_hash": sha256_hex(content),
        "size_bytes": len(content)}, content)
    return content, summary["artifact_id"]


def gr3_task(db, ref, *, project="p1", status="RUNNING",
             template="gr3_extract", spec_ref=None, suffix="",
             task_type="TOOL_TASK"):
    payload = build_gr3_extract_task_payload(ref)
    node = NodeContract(
        task_id=payload["task_id"] + suffix,
        project_id=project, task_type=task_type,
        profile=payload["profile"],
        idempotency_key=payload["idempotency_key"] + suffix,
        spec={"template": template, "template_version": "1",
              "corpus_ref": ref if spec_ref is None else spec_ref})
    TaskRepository(db).create(node)
    if status in ("READY", "RUNNING", "SUCCEEDED"):
        TaskRepository(db).transition_status(node.task_id, TaskStatus.READY)
    if status in ("RUNNING", "SUCCEEDED"):
        TaskRepository(db).transition_status(node.task_id, TaskStatus.RUNNING)
    if status == "SUCCEEDED":
        TaskRepository(db).transition_status(node.task_id, TaskStatus.SUCCEEDED)
    return node.task_id


def extract_batch(ref, admitted):
    """Pure extraction over real bytes; ``admitted`` maps ref → hash."""
    content = load_corpus_bytes(REPO_ROOT, ref)
    cited, skipped = extract_cites_mentions(ref, content.decode("utf-8"),
                                            tuple(ALL_REFS))
    claimed = [{"citing_ref": ref, "cited_ref": c, "edge_type": "cites"}
               for c in cited]
    result = validate_gr3_extraction(
        ref, content, claimed,
        {c: admitted[c] for c in cited}, tuple(ALL_REFS))
    assert result.verdict == "ADMITTED", result.errors
    return content, result, skipped


def edge_counts(db):
    n = db.execute(
        "SELECT COUNT(*) FROM provenance_edges "
        "WHERE edge_type = 'cites'").fetchone()[0]
    triples = db.execute(
        "SELECT artifact_id, upstream_id FROM provenance_edges "
        "WHERE edge_type = 'cites' ORDER BY artifact_id, upstream_id"
    ).fetchall()
    return n, [(r["artifact_id"], r["upstream_id"]) for r in triples]


# ── agreement + template shape ──

def test_agreement_constants_byte_identical():
    assert P_TEMPLATE == rgedges.GR3_EXTRACT_TEMPLATE
    assert P_TVERSION == rgedges.GR3_TEMPLATE_VERSION
    assert P_XVERSION == rgedges.GR3_EXTRACTOR_VERSION
    assert P_SCHEMA == rgedges.GR3_EDGE_SCHEMA_VERSION
    assert P_EDGE_TYPES == GR3_EDGE_TYPES == frozenset({"cites"})


def test_task_payload_is_gateway_shaped():
    from hermes.research.gateway import _TASK_PAYLOAD_KEYS

    for ref in ALL_REFS:
        payload = build_gr3_extract_task_payload(ref)
        assert set(payload) <= _TASK_PAYLOAD_KEYS
        assert payload["task_type"] == "TOOL_TASK"
        assert payload["profile"] == "DETERMINISTIC"
        assert payload["spec"]["template"] == "gr3_extract"
        assert payload["spec"]["corpus_ref"] == ref


def test_mention_forms():
    assert "docs/ARCHITECTURE.md" in mention_forms_for(ARCH)
    assert "ARCHITECTURE.md" in mention_forms_for(ARCH)
    assert "IDR-024" in mention_forms_for(IDR24)
    assert "IDR-028" in mention_forms_for(IDR28)
    assert "IDR-024" not in mention_forms_for(ARCH)


def test_idr_tag_mechanism_synthetic():
    cited, _ = extract_cites_mentions(
        STATE, "see IDR-024 and docs/API.md for detail", tuple(ALL_REFS))
    assert cited == (API, IDR24)


# ── end-to-end on real files ──

def test_e2e_all_six(db, corpus, edges):
    admitted: dict[str, str] = {}
    ids: dict[str, str] = {}
    for ref in ALL_REFS:
        content, aid = admit_doc(db, corpus, ref)
        admitted[ref] = sha256_hex(content)
        ids[ref] = aid

    # Anchored expectations, verified against the live documents.
    expanded: dict[str, dict] = {}
    for ref in ALL_REFS:
        tid = gr3_task(db, ref)
        content, result, skipped = extract_batch(ref, admitted)
        summary = edges.record(
            "p1", tid,
            {"verdict": result.verdict, "citing_ref": result.citing_ref,
             "citing_hash": result.citing_hash,
             "extractor_version": result.extractor_version,
             "edges": [{"citing_ref": e.citing_ref,
                        "cited_ref": e.cited_ref,
                        "edge_type": e.edge_type} for e in result.edges],
             "skipped": list(result.skipped), "errors": []},
            content, {c: admitted[c] for c in ALL_REFS})
        expanded[ref] = {"summary": summary, "skipped": skipped}

    assert expanded[AGENTS]["summary"]["decision"] == "NEW"
    assert expanded[AGENTS]["summary"]["edges_written"] == 3
    assert expanded[API]["summary"]["decision"] == "NEW"
    assert expanded[API]["summary"]["edges_written"] == 1
    assert expanded[STATE]["summary"]["decision"] == "NEW"
    assert expanded[STATE]["summary"]["edges_written"] == 1
    for ref in (ARCH, IDR24, IDR28):
        assert expanded[ref]["summary"]["decision"] == "EMPTY"
        assert expanded[ref]["summary"]["edges_written"] == 0

    n, triples = edge_counts(db)
    assert n == 5
    by_citing: dict[str, set[str]] = {}
    for a, u in triples:
        assert a != u  # no self-edge anywhere
        by_citing.setdefault(a, set()).add(u)
    assert by_citing[ids[AGENTS]] == {ids[API], ids[ARCH], ids[STATE]}
    assert by_citing[ids[API]] == {ids[AGENTS]}
    assert by_citing[ids[STATE]] == {ids[ARCH]}

    # Outside-world references are observed, never edges.
    assert "IDR-018" in expanded[ARCH]["skipped"]
    for ref in ALL_REFS:
        for s in expanded[ref]["skipped"]:
            assert s not in ALL_REFS
            for form_set in (mention_forms_for(r) for r in ALL_REFS):
                assert s not in form_set


def test_determinism_twice(db):
    content = load_corpus_bytes(REPO_ROOT, AGENTS)
    text = content.decode("utf-8")
    first = extract_cites_mentions(AGENTS, text, tuple(ALL_REFS))
    second = extract_cites_mentions(AGENTS, text, tuple(ALL_REFS))
    assert first == second


# ── INVALID writes nothing ──

def _result_mapping(result, admitted):
    return {
        "verdict": result.verdict, "citing_ref": result.citing_ref,
        "citing_hash": result.citing_hash,
        "extractor_version": result.extractor_version,
        "edges": [{"citing_ref": e.citing_ref, "cited_ref": e.cited_ref,
                   "edge_type": e.edge_type} for e in result.edges],
        "skipped": list(result.skipped),
        "errors": list(result.errors),
    }


def test_hallucinated_edge_invalid_zero_writes(db, corpus, edges):
    admitted, content = {}, load_corpus_bytes(REPO_ROOT, AGENTS)
    for ref in ALL_REFS:
        c, _ = admit_doc(db, corpus, ref)
        admitted[ref] = sha256_hex(c)
    tid = gr3_task(db, AGENTS)
    cited, _ = extract_cites_mentions(
        AGENTS, content.decode("utf-8"), tuple(ALL_REFS))
    forged = [{"citing_ref": AGENTS, "cited_ref": c, "edge_type": "cites"}
              for c in cited] + [{"citing_ref": AGENTS,
                                  "cited_ref": IDR24,
                                  "edge_type": "cites"}]
    result = validate_gr3_extraction(
        AGENTS, content, forged, admitted, tuple(ALL_REFS))
    assert result.verdict == "INVALID"
    assert any("hallucinated" in e for e in result.errors)
    before = edge_counts(db)
    with pytest.raises(GraphEdgeIntegrityError):
        edges.record("p1", tid, _result_mapping(result, admitted),
                     content, admitted)
    assert edge_counts(db) == before


def test_dropped_edge_invalid_zero_writes(db, corpus, edges):
    admitted, content = {}, load_corpus_bytes(REPO_ROOT, API)
    for ref in ALL_REFS:
        c, _ = admit_doc(db, corpus, ref)
        admitted[ref] = sha256_hex(c)
    tid = gr3_task(db, API)
    result = validate_gr3_extraction(
        API, content, [], admitted, tuple(ALL_REFS))
    assert result.verdict == "INVALID"
    assert any("dropped" in e for e in result.errors)
    before = edge_counts(db)
    with pytest.raises(GraphEdgeIntegrityError):
        edges.record("p1", tid, _result_mapping(result, admitted),
                     content, admitted)
    assert edge_counts(db) == before


@pytest.mark.parametrize("bad_type", ["supports", "entails", "derived_from",
                                      "used_as_input", "justifies",
                                      "supersedes", "contradicts", ""])
def test_unknown_edge_types_fail_closed(bad_type):
    with pytest.raises(GR3EdgeError):
        gr3_edge_draft_from_mapping({
            "citing_ref": AGENTS, "cited_ref": API,
            "edge_type": bad_type})


def test_unknown_type_in_batch_invalid(db, corpus, edges):
    admitted, content = {}, load_corpus_bytes(REPO_ROOT, STATE)
    for ref in ALL_REFS:
        c, _ = admit_doc(db, corpus, ref)
        admitted[ref] = sha256_hex(c)
    tid = gr3_task(db, STATE)
    result = validate_gr3_extraction(
        STATE, content,
        [{"citing_ref": STATE, "cited_ref": ARCH,
          "edge_type": "supports"}],
        admitted, tuple(ALL_REFS))
    assert result.verdict == "INVALID"
    before = edge_counts(db)
    with pytest.raises(GraphEdgeIntegrityError):
        edges.record("p1", tid, _result_mapping(result, admitted),
                     content, admitted)
    assert edge_counts(db) == before


# ── idempotency ──

def test_reextraction_idempotent(db, corpus, edges):
    admitted: dict[str, str] = {}
    for ref in ALL_REFS:
        c, _ = admit_doc(db, corpus, ref)
        admitted[ref] = sha256_hex(c)
    tid = gr3_task(db, AGENTS)
    content, result, _ = extract_batch(AGENTS, admitted)
    mapping = _result_mapping(result, admitted)
    first = edges.record("p1", tid, mapping, content, admitted)
    assert first["decision"] == "NEW"
    assert first["edges_written"] == 3
    assert first["edges_reused"] == 0
    before = edge_counts(db)
    second = edges.record("p1", tid, mapping, content, admitted)
    assert second["decision"] == "IDENTICAL"
    assert second["edges_written"] == 0
    assert second["edges_reused"] == 3
    assert second["triples"] == first["triples"]
    assert edge_counts(db) == before


# ── binding ──

def test_unbound_missing_task(db, corpus, edges):
    admitted: dict[str, str] = {}
    for ref in ALL_REFS:
        c, _ = admit_doc(db, corpus, ref)
        admitted[ref] = sha256_hex(c)
    content, result, _ = extract_batch(API, admitted)
    with pytest.raises(GraphEdgeBindingError):
        edges.record("p1", "task-missing", _result_mapping(result, admitted),
                     content, admitted)
    assert edge_counts(db) == (0, [])


@pytest.mark.parametrize("status", ["PENDING", "READY", "SUCCEEDED"])
def test_unbound_non_running(db, corpus, edges, status):
    admitted: dict[str, str] = {}
    for ref in ALL_REFS:
        c, _ = admit_doc(db, corpus, ref)
        admitted[ref] = sha256_hex(c)
    tid = gr3_task(db, API, status=status)
    content, result, _ = extract_batch(API, admitted)
    with pytest.raises(GraphEdgeBindingError):
        edges.record("p1", tid, _result_mapping(result, admitted),
                     content, admitted)
    assert edge_counts(db) == (0, [])


def test_unbound_wrong_template(db, corpus, edges):
    admitted: dict[str, str] = {}
    for ref in ALL_REFS:
        c, _ = admit_doc(db, corpus, ref)
        admitted[ref] = sha256_hex(c)
    tid = gr3_task(db, API, template="corpus_admit")
    content, result, _ = extract_batch(API, admitted)
    with pytest.raises(GraphEdgeBindingError):
        edges.record("p1", tid, _result_mapping(result, admitted),
                     content, admitted)
    assert edge_counts(db) == (0, [])


def test_unbound_spec_mismatch(db, corpus, edges):
    admitted: dict[str, str] = {}
    for ref in ALL_REFS:
        c, _ = admit_doc(db, corpus, ref)
        admitted[ref] = sha256_hex(c)
    tid = gr3_task(db, API, spec_ref=STATE)
    content, result, _ = extract_batch(API, admitted)
    with pytest.raises(GraphEdgeBindingError):
        edges.record("p1", tid, _result_mapping(result, admitted),
                     content, admitted)
    assert edge_counts(db) == (0, [])


# ── endpoint governance ──

def test_dangling_cited_refuses(db, corpus, edges):
    # Only the citing doc is admitted; cited docs dangle.
    content, _ = admit_doc(db, corpus, AGENTS)
    admitted = {r: sha256_hex(load_corpus_bytes(REPO_ROOT, r))
                for r in ALL_REFS}
    tid = gr3_task(db, AGENTS)
    _, result, _ = extract_batch(AGENTS, admitted)
    assert result.verdict == "ADMITTED"  # pure layer cannot see the DB
    with pytest.raises(GraphEdgeIntegrityError):
        edges.record("p1", tid, _result_mapping(result, admitted),
                     content, admitted)
    assert edge_counts(db) == (0, [])


def test_hash_substitution_refused(db, corpus, edges):
    admitted: dict[str, str] = {}
    for ref in ALL_REFS:
        c, _ = admit_doc(db, corpus, ref)
        admitted[ref] = sha256_hex(c)
    tid = gr3_task(db, STATE)
    content, result, _ = extract_batch(STATE, admitted)
    assert result.verdict == "ADMITTED"
    swapped = dict(admitted)
    swapped[ARCH] = admitted[API]  # lie: ARCH's bytes are API's
    with pytest.raises(GraphEdgeIntegrityError):
        edges.record("p1", tid, _result_mapping(result, admitted),
                     content, swapped)
    assert edge_counts(db) == (0, [])


def test_cross_project_cited_refuses(db, corpus, edges):
    # Citing admitted in p1, cited only in p2 → cross-project refusal.
    citing_content, _ = admit_doc(db, corpus, AGENTS, project="p1")
    p2hashes: dict[str, str] = {}
    for ref in ALL_REFS:
        c, _ = admit_doc(db, corpus, ref, project="p2", suffix="-p2")
        p2hashes[ref] = sha256_hex(c)
    tid = gr3_task(db, AGENTS, project="p1", suffix="-x")
    _, result, _ = extract_batch(AGENTS, p2hashes)
    with pytest.raises(GraphEdgeIntegrityError):
        edges.record("p1", tid, _result_mapping(result, p2hashes),
                     citing_content, p2hashes)
    assert edge_counts(db) == (0, [])


def test_extraction_emits_no_event(db, corpus, edges):
    admitted: dict[str, str] = {}
    for ref in ALL_REFS:
        c, _ = admit_doc(db, corpus, ref)
        admitted[ref] = sha256_hex(c)
    tid = gr3_task(db, API, suffix="-ev")
    before = {r[0] for r in db.execute(
        "SELECT DISTINCT event_type FROM events").fetchall()}
    content, result, _ = extract_batch(API, admitted)
    edges.record("p1", tid, _result_mapping(result, admitted),
                 content, admitted)
    after = {r[0] for r in db.execute(
        "SELECT DISTINCT event_type FROM events").fetchall()}
    assert after == before
