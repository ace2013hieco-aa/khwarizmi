"""Golden tests for the P1a corpus-admission write path (GR3 v0, IDR-042).

Proves against real SQLite + a real ArtifactStore, on the REAL six
corpus documents read from disk:
1. end-to-end admission of every corpus member (row + edge +
   source_payload:<hash> resolution + byte round-trip);
2. re-admission is idempotent (same content → same artifact_id, no
   duplicate row/edge);
3. cross-task global reuse (same bytes, second task → same row + new
   edge, nothing rewritten);
4. unbound admission refuses (missing task, wrong project, non-RUNNING,
   non-TOOL_TASK, wrong template, corpus_ref mismatch) with zero writes;
5. INVALID drafts/bytes write nothing (bad hash, size mismatch,
   unknown keys, unlisted ref, oversize, empty, type confusion);
6. divergent re-admission under one task is refused (one-shot);
7. admission emits no event (type set unchanged);
8. research/persistence agreement constants are byte-identical.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from hermes.artifacts.store import ArtifactStore
from hermes.core.node import NodeContract
from hermes.core.task_status import TaskStatus
from hermes.persistence.corpus import (
    CORPUS_ADMIT_TEMPLATE as P_CORPUS_ADMIT_TEMPLATE,
)
from hermes.persistence.corpus import CORPUS_MAX_BYTES as P_MAX_BYTES
from hermes.persistence.corpus import CORPUS_REFS as P_CORPUS_REFS
from hermes.persistence.corpus import CORPUS_SCHEMA_VERSION as P_SCHEMA
from hermes.persistence.corpus import CORPUS_TEMPLATE_VERSION as P_TVERSION
from hermes.persistence.corpus import (
    CorpusBindingError,
    CorpusConflictError,
    CorpusError,
    CorpusIntegrityError,
    CorpusRepository,
)
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ArtifactRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.persistence.source_outcomes import SourceOutcomeRepository
from hermes.research import corpus as rcorpus
from hermes.research.corpus import (
    CORPUS_ADMIT_TEMPLATE,
    CORPUS_MAX_BYTES,
    CORPUS_REFS,
    CorpusDraftError,
    build_corpus_admit_task_payload,
    corpus_admission_from_mapping,
    load_corpus_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

ALL_REFS = sorted(CORPUS_REFS)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── fixtures ──

@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Corpus")
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

def make_task(
    db: sqlite3.Connection,
    ref: str,
    *,
    project: str = "p1",
    status: str = "RUNNING",
    task_type: str = "TOOL_TASK",
    template: str = CORPUS_ADMIT_TEMPLATE,
    spec_ref: str | None = None,
    task_id: str | None = None,
    key_suffix: str = "",
) -> str:
    """Create a corpus-admit task and drive it to ``status``."""
    payload = build_corpus_admit_task_payload(ref)
    tid = task_id or payload["task_id"]
    node = NodeContract(
        task_id=tid,
        project_id=project,
        task_type=task_type,
        profile=payload["profile"],
        idempotency_key=payload["idempotency_key"] + key_suffix,
        spec={
            "template": template,
            "template_version": payload["spec"]["template_version"],
            "corpus_ref": ref if spec_ref is None else spec_ref,
        },
    )
    TaskRepository(db).create(node)
    if status in ("READY", "RUNNING", "SUCCEEDED", "FAILED"):
        TaskRepository(db).transition_status(tid, TaskStatus.READY)
    if status in ("RUNNING", "SUCCEEDED", "FAILED"):
        TaskRepository(db).transition_status(tid, TaskStatus.RUNNING)
    if status == "SUCCEEDED":
        TaskRepository(db).transition_status(tid, TaskStatus.SUCCEEDED)
    if status == "FAILED":
        TaskRepository(db).transition_status(tid, TaskStatus.FAILED)
    return tid


def draft_for(ref: str, content: bytes) -> dict:
    return {
        "corpus_ref": ref,
        "content_hash": sha256_hex(content),
        "size_bytes": len(content),
    }


def admit(
    corpus: CorpusRepository, ref: str, task_id: str, *,
    project: str = "p1", content: bytes | None = None,
) -> dict:
    data = content if content is not None else load_corpus_bytes(
        REPO_ROOT, ref)
    return corpus.record(project, task_id, draft_for(ref, data), data)


def counts(db: sqlite3.Connection) -> tuple[int, int, int]:
    n_art = db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    n_edge = db.execute(
        "SELECT COUNT(*) FROM provenance_edges").fetchone()[0]
    n_evt = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    return (n_art, n_edge, n_evt)


# ── agreement + template shape ──

def test_agreement_constants_byte_identical():
    assert P_CORPUS_ADMIT_TEMPLATE == CORPUS_ADMIT_TEMPLATE
    assert P_TVERSION == rcorpus.CORPUS_TEMPLATE_VERSION
    assert P_MAX_BYTES == CORPUS_MAX_BYTES
    assert P_SCHEMA == rcorpus.CORPUS_SCHEMA_VERSION
    assert P_CORPUS_REFS == CORPUS_REFS


def test_task_payload_is_gateway_shaped():
    from hermes.research.gateway import _TASK_PAYLOAD_KEYS

    for ref in ALL_REFS:
        payload = build_corpus_admit_task_payload(ref)
        assert set(payload) <= _TASK_PAYLOAD_KEYS
        assert payload["task_type"] == "TOOL_TASK"
        assert payload["profile"] == "DETERMINISTIC"
        assert payload["spec"]["template"] == CORPUS_ADMIT_TEMPLATE
        assert payload["spec"]["corpus_ref"] == ref


def test_draft_mapping_closed():
    with pytest.raises(CorpusDraftError):
        corpus_admission_from_mapping({
            "corpus_ref": ALL_REFS[0],
            "content_hash": "0" * 64,
            "size_bytes": 1,
            "smuggled": True,
        })
    with pytest.raises(CorpusDraftError):
        corpus_admission_from_mapping({
            "corpus_ref": "docs/UNLISTED.md",
            "content_hash": "0" * 64,
            "size_bytes": 1,
        })


# ── end-to-end on real files ──

def test_admit_real_corpus_end_to_end(db, corpus, store):
    assert len(ALL_REFS) == 6
    admitted: dict[str, dict] = {}
    for ref in ALL_REFS:
        tid = make_task(db, ref)
        summary = admit(corpus, ref, tid)
        assert summary["decision"] == "NEW"
        assert summary["corpus_ref"] == ref
        assert summary["task_id"] == tid
        assert summary["project_id"] == "p1"
        assert len(summary["artifacts_written"]) == 1
        admitted[ref] = summary

    rows = db.execute(
        "SELECT artifact_id, artifact_type, content_hash FROM artifacts "
        "ORDER BY artifact_id").fetchall()
    assert len(rows) == 6
    assert {r["artifact_type"] for r in rows} == {"source_payload"}

    # Every admission resolves through the governed resolver surface and
    # round-trips its exact bytes (P1b's future read path, proven now).
    outcomes = SourceOutcomeRepository(db, store)
    for ref in ALL_REFS:
        content = load_corpus_bytes(REPO_ROOT, ref)
        digest = sha256_hex(content)
        assert outcomes.dereference_ref("p1", f"source_payload:{digest}")
        assert outcomes.read_payload_bytes(
            f"source_payload:{digest}") == content
        edge = db.execute(
            "SELECT 1 FROM provenance_edges WHERE artifact_id = ? "
            "AND upstream_id = ? AND edge_type = 'derived_from'",
            (admitted[ref]["artifact_id"],
             admitted[ref]["task_id"])).fetchone()
        assert edge is not None


def test_readmission_idempotent(db, corpus):
    ref = ALL_REFS[0]
    tid = make_task(db, ref)
    first = admit(corpus, ref, tid)
    before = counts(db)
    second = admit(corpus, ref, tid)
    assert second["decision"] == "IDENTICAL"
    assert second["artifact_id"] == first["artifact_id"]
    assert second["artifacts_written"] == []
    assert second["artifacts_reused"] == [first["artifact_id"]]
    assert counts(db) == before


def test_cross_task_global_reuse(db, corpus):
    ref = ALL_REFS[1]
    tid_a = make_task(db, ref)
    first = admit(corpus, ref, tid_a)
    tid_b = make_task(db, ref, task_id=first["task_id"] + "-b",
                      key_suffix="-b")
    second = admit(corpus, ref, tid_b)
    assert second["artifact_id"] == first["artifact_id"]
    assert second["artifacts_written"] == []
    edge = db.execute(
        "SELECT 1 FROM provenance_edges WHERE artifact_id = ? "
        "AND upstream_id = ? AND edge_type = 'derived_from'",
        (first["artifact_id"], tid_b)).fetchone()
    assert edge is not None
    n_art = db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    assert n_art == 1


def test_divergent_readmission_refused(db, corpus):
    ref = ALL_REFS[2]
    tid = make_task(db, ref)
    admit(corpus, ref, tid)
    before = counts(db)
    doctored = load_corpus_bytes(REPO_ROOT, ref) + b"\n"
    with pytest.raises(CorpusConflictError):
        admit(corpus, ref, tid, content=doctored)
    assert counts(db) == before


# ── unbound refusals write nothing ──

def test_unbound_missing_task_refuses(db, corpus):
    ref = ALL_REFS[0]
    before = counts(db)
    with pytest.raises(CorpusBindingError):
        admit(corpus, ref, "task-does-not-exist")
    assert counts(db) == before


def test_unbound_wrong_project_refuses(db, corpus):
    ref = ALL_REFS[0]
    tid = make_task(db, ref, project="p1")
    before = counts(db)
    with pytest.raises(CorpusBindingError):
        admit(corpus, ref, tid, project="p2")
    assert counts(db) == before


@pytest.mark.parametrize("status", ["PENDING", "READY", "SUCCEEDED", "FAILED"])
def test_unbound_non_running_refuses(db, corpus, status):
    ref = ALL_REFS[0]
    tid = make_task(db, ref, status=status)
    before = counts(db)
    with pytest.raises(CorpusBindingError):
        admit(corpus, ref, tid)
    assert counts(db) == before


def test_unbound_non_tool_task_refuses(db, corpus):
    ref = ALL_REFS[0]
    tid = make_task(db, ref, task_type="AGENT_TASK")
    before = counts(db)
    with pytest.raises(CorpusBindingError):
        admit(corpus, ref, tid)
    assert counts(db) == before


def test_unbound_wrong_template_refuses(db, corpus):
    ref = ALL_REFS[0]
    tid = make_task(db, ref, template="source_search")
    before = counts(db)
    with pytest.raises(CorpusBindingError):
        admit(corpus, ref, tid)
    assert counts(db) == before


def test_unbound_corpus_ref_mismatch_refuses(db, corpus):
    # Task bound to doc A cannot admit doc B (one task, one document).
    tid = make_task(db, ALL_REFS[0])
    before = counts(db)
    with pytest.raises(CorpusBindingError):
        admit(corpus, ALL_REFS[1], tid)
    assert counts(db) == before


# ── INVALID writes nothing ──

def test_invalid_forged_hash_writes_nothing(db, corpus):
    ref = ALL_REFS[0]
    tid = make_task(db, ref)
    content = load_corpus_bytes(REPO_ROOT, ref)
    forged = {
        "corpus_ref": ref,
        "content_hash": "f" * 64,
        "size_bytes": len(content),
    }
    before = counts(db)
    with pytest.raises(CorpusIntegrityError):
        corpus.record("p1", tid, forged, content)
    assert counts(db) == before


def test_invalid_size_mismatch_writes_nothing(db, corpus):
    ref = ALL_REFS[0]
    tid = make_task(db, ref)
    content = load_corpus_bytes(REPO_ROOT, ref)
    wrong = {
        "corpus_ref": ref,
        "content_hash": sha256_hex(content),
        "size_bytes": len(content) + 1,
    }
    before = counts(db)
    with pytest.raises(CorpusIntegrityError):
        corpus.record("p1", tid, wrong, content)
    assert counts(db) == before


def test_invalid_oversize_writes_nothing(db, corpus):
    ref = ALL_REFS[0]
    tid = make_task(db, ref)
    big = b"x" * (CORPUS_MAX_BYTES + 1)
    oversized = {
        "corpus_ref": ref,
        "content_hash": sha256_hex(big),
        "size_bytes": len(big),
    }
    before = counts(db)
    with pytest.raises(CorpusIntegrityError):
        corpus.record("p1", tid, oversized, big)
    assert counts(db) == before


def test_invalid_empty_writes_nothing(db, corpus):
    ref = ALL_REFS[0]
    # Empty bytes can never form a valid draft (size must be positive).
    with pytest.raises(CorpusDraftError):
        corpus_admission_from_mapping({
            "corpus_ref": ref,
            "content_hash": sha256_hex(b""),
            "size_bytes": 0,
        })
    # And bytes that disagree with a well-formed draft are refused.
    tid = make_task(db, ref)
    before = counts(db)
    with pytest.raises(CorpusIntegrityError):
        corpus.record(
            "p1", tid,
            {"corpus_ref": ref, "content_hash": sha256_hex(b""),
             "size_bytes": 1},
            b"")
    assert counts(db) == before


def test_invalid_type_confusion_writes_nothing(db, corpus):
    """Same bytes already stored under a different artifact type are
    refused (R02 analog) — never reused as a source_payload."""
    ref = ALL_REFS[3]
    content = load_corpus_bytes(REPO_ROOT, ref)
    digest = sha256_hex(content)
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type, content_hash,
            size_bytes, storage_path, producer, metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("preexisting-other-type", "p1", None, "evidence", digest,
         len(content), "inline://test", "test", "{}", "2026-01-01T00:00:00"),
    )
    db.commit()
    tid = make_task(db, ref)
    before = counts(db)
    with pytest.raises(CorpusIntegrityError):
        admit(corpus, ref, tid)
    # The only row for the hash is still the pre-existing other-type row.
    rows = db.execute(
        "SELECT artifact_type FROM artifacts "
        "WHERE content_hash = ?", (digest,)).fetchall()
    assert [r["artifact_type"] for r in rows] == ["evidence"]
    assert counts(db) == before


def test_no_store_writes_nothing(db):
    bare = CorpusRepository(db, None)
    ref = ALL_REFS[0]
    tid = make_task(db, ref)
    before = counts(db)
    with pytest.raises(CorpusError):
        admit(bare, ref, tid)
    assert counts(db) == before


def test_admission_emits_no_event(db, corpus):
    ref = ALL_REFS[4]
    tid = make_task(db, ref)
    before_types = {r[0] for r in db.execute(
        "SELECT DISTINCT event_type FROM events").fetchall()}
    admit(corpus, ref, tid)
    after_types = {r[0] for r in db.execute(
        "SELECT DISTINCT event_type FROM events").fetchall()}
    assert after_types == before_types
