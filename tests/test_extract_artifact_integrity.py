"""EXT-2-FIX (audit EXT-2-REDTEAM S1): the EXTRACT seam refuses a tampered
content-addressed artifact with a NAMED refusal (``ARTIFACT_INTEGRITY_REFUSED``)
instead of letting ``ArtifactIntegrityError`` escape ``tick()``/``run()``
uncaught.

Before this fix ``_execute_extract`` caught only ``ExtractionOutputRejected`` /
binding errors, so a post-admission byte swap under a live key propagated out
of the controller. These pins drive the REAL ``Controller._execute_extract``
over a real SQLite db and a real ``ArtifactStore``.
"""
from __future__ import annotations

from pathlib import Path

from hermes.artifacts.store import ArtifactStore
from hermes.core.intents import Intent, IntentKind
from hermes.core.task_status import TaskStatus
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ArtifactRepository,
    ProjectRepository,
    TaskRepository,
)
from hermes.research.controller import (
    ARTIFACT_INTEGRITY_REFUSED,
    Controller,
)
from hermes.research.extraction import (
    build_extract_task_payload,
    extraction_draft_from_mapping,
)
from hermes.research.gateway import apply_intent

CLOCK = "2026-10-02T00:00:00.000000+00:00"
DATA = b"the stored source text contains SPAN-A inside it"


def _fixture(tmp_path):
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    store = ArtifactStore(tmp_path / "artifacts", ArtifactRepository(conn))
    return conn, store


def _admit_running(conn, source_ref):
    task_id = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR", project_id="p1",
        payload=build_extract_task_payload(source_ref, "both"))).entity_id
    tr = TaskRepository(conn)
    tr.transition_status(task_id, TaskStatus.READY, caused_by="test")
    tr.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    return task_id, tr


def _draft(source_ref):
    return extraction_draft_from_mapping({
        "source_ref": source_ref,
        "claims": [{
            "ref": "c1",
            "statement": "A claim quoting SPAN-A from the source.",
            "source_ref": source_ref,
            "support_state": "INFERRED",
            "span_ref": "SPAN-A",
            "claim_type": "causal",
            "context_tags": {},
            "assumption_refs": [],
        }],
        "assumptions": [],
        "extracted_by": "model_ref:c-tier-1",
        "schema_version": "2",
    })


def _run(conn, store, task_id, extract_fn):
    ctrl = Controller(conn, project_id="p1", extract_fn=extract_fn,
                      artifact_store=store, clock=lambda: CLOCK)
    assert ctrl._acquire_lock() is True
    try:
        return ctrl._execute_extract(task_id)
    finally:
        ctrl._release_lock()


def _last_reason(conn):
    row = conn.execute(
        "SELECT reason FROM events WHERE event_type = 'TaskStatusChanged' "
        "ORDER BY rowid DESC LIMIT 1").fetchone()
    return (row["reason"] or "") if row else ""


def _claims(conn):
    return conn.execute(
        "SELECT COUNT(*) c FROM research_claims").fetchone()["c"]


def test_extract_refuses_tampered_payload_with_named_refusal(tmp_path):
    """A byte swap at the cited source_payload's canonical path yields a
    terminal FAILED task carrying the NAMED refusal — not an escape."""
    conn, store = _fixture(tmp_path)
    try:
        meta = store.write(DATA, "source_payload", "p1", project_id="p1")
        source_ref = "source_payload:" + meta["content_hash"]
        task_id, tr = _admit_running(conn, source_ref)
        draft = _draft(source_ref)
        (Path(store._root) / meta["storage_path"]).write_bytes(b"TAMPERED")
        out = _run(conn, store, task_id, lambda task, untrusted: draft)
        assert task_id in out.failed
        assert tr.get_status(task_id) is TaskStatus.FAILED
        assert ARTIFACT_INTEGRITY_REFUSED in _last_reason(conn)
        assert _claims(conn) == 0  # refusal-as-data: no partial write
    finally:
        conn.close()


def test_extract_refuses_tamper_on_the_model_read_path(tmp_path):
    """The same refusal covers a tampered read performed by the MODEL call
    (the untrusted view's payload reader), not only the acceptance path."""
    conn, store = _fixture(tmp_path)
    try:
        meta = store.write(DATA, "source_payload", "p1", project_id="p1")
        source_ref = "source_payload:" + meta["content_hash"]
        task_id, tr = _admit_running(conn, source_ref)
        draft = _draft(source_ref)

        def model_fn(task, untrusted):
            untrusted.fetched_text(source_ref)  # reads the tampered bytes
            return draft

        (Path(store._root) / meta["storage_path"]).write_bytes(b"TAMPERED")
        out = _run(conn, store, task_id, model_fn)
        assert task_id in out.failed
        assert tr.get_status(task_id) is TaskStatus.FAILED
        assert ARTIFACT_INTEGRITY_REFUSED in _last_reason(conn)
    finally:
        conn.close()


def test_extract_missing_payload_is_not_an_integrity_refusal(tmp_path):
    """The None contract is unchanged: an ABSENT payload stays an expected
    miss (the dangling-span refusal), never the integrity refusal."""
    conn, store = _fixture(tmp_path)
    try:
        meta = store.write(DATA, "source_payload", "p1", project_id="p1")
        source_ref = "source_payload:" + meta["content_hash"]
        task_id, tr = _admit_running(conn, source_ref)
        draft = _draft(source_ref)
        (Path(store._root) / meta["storage_path"]).unlink()
        out = _run(conn, store, task_id, lambda task, untrusted: draft)
        assert ARTIFACT_INTEGRITY_REFUSED not in _last_reason(conn)
        # absence follows the ordinary rejection/retry path, not the refusal
        assert task_id in (out.retried + out.failed)
        assert tr.get_status(task_id) in (TaskStatus.RETRYING, TaskStatus.FAILED)
        assert task_id not in out.succeeded
    finally:
        conn.close()
