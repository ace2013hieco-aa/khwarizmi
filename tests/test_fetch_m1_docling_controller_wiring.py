"""FETCH-FIX-M1 — the docling span seam admits through the REAL controller.

The M1 finding (docs/MERGE-AUDIT-FETCH.md on merge/fetch@8e6f1b0): the
controller's docling branch required ``source_ref == doc.content.ref`` while
``repos.read_payload`` only resolves content-addressed
``source_payload:<sha256-64>`` keys — an inner ref inside the hashed bytes
can never equal that hash (fixed point), so a valid digest token was refused
(RETRYING / 0 claims) and the promoted S1 wiring was inert.

These tests pin the fix: the store key plus the record's own ref/digest
chain admit; bare substrings, forged tokens and spliced records refuse; the
plain-payload substring path is unchanged. The digest-token admission test
is the red-on-8e6f1b0 / green-with-the-fix leg.
"""
from __future__ import annotations

import json
import pathlib

import pytest

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
from hermes.research.controller import Controller
from hermes.research.extraction import (
    build_extract_task_payload,
    extraction_draft_from_mapping,
)
from hermes.research.gateway import apply_intent
from hermes.tools.providers.docling_provider import (
    DoclingDocument,
    resolver_for_store_key,
)

FIXTURE = (pathlib.Path(__file__).parent / "fixtures" / "s1_docling"
           / "2305.10601v2.json")
CLOCK = "2026-10-02T00:00:00.000000+00:00"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test One")
    yield conn
    conn.close()


@pytest.fixture
def store(tmp_path, db):
    return ArtifactStore(tmp_path / "artifacts", ArtifactRepository(db))


def _record_and_token(*, splice_provenance_ref: str | None = None):
    """The promoted fixture record (optionally spliced) + a genuine token."""
    wrapper = json.loads(FIXTURE.read_text(encoding="utf-8"))
    record = wrapper["record"]
    if splice_provenance_ref is not None:
        record["provenance"]["source_ref"] = splice_provenance_ref
    doc = DoclingDocument.from_record(record)
    token = doc.span_ref_for(wrapper["claims"][0]["quote"])
    return record, token


def _run_extract(db, store, *, payload: bytes, span_ref: str):
    """Store the payload, admit an EXTRACT task citing its store key, run
    the real ``Controller._execute_extract``, return (status, claim rows)."""
    meta = store.write(payload, "source_payload", producer="test",
                       project_id="p1")
    source_ref = "source_payload:" + meta["content_hash"]
    task_id = apply_intent(db, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload=build_extract_task_payload(source_ref, "both"))).entity_id
    task_repo = TaskRepository(db)
    task_repo.transition_status(task_id, TaskStatus.READY, caused_by="test")
    task_repo.transition_status(task_id, TaskStatus.RUNNING, caused_by="test")
    draft = extraction_draft_from_mapping({
        "source_ref": source_ref,
        "claims": [{
            "ref": "c1",
            "statement": "A docling-backed claim.",
            "source_ref": source_ref,
            "support_state": "INFERRED",
            "span_ref": span_ref,
            "claim_type": "causal",
            "context_tags": {},
            "assumption_refs": [],
        }],
        "assumptions": [],
        "extracted_by": "model_ref:c-tier-1",
        "schema_version": "2",
    })
    ctrl = Controller(db, project_id="p1",
                      extract_fn=lambda task, untrusted: draft,
                      artifact_store=store, clock=lambda: CLOCK)
    assert ctrl._acquire_lock() is True
    try:
        ctrl._execute_extract(task_id)
    finally:
        ctrl._release_lock()
    claims = db.execute(
        "SELECT COUNT(*) c FROM research_claims").fetchone()["c"]
    return task_repo.get_status(task_id), claims


def test_docling_store_key_digest_token_admits_end_to_end(db, store):
    """RED on merge/fetch@8e6f1b0 (RETRYING, 0 rows) — GREEN with the fix."""
    record, token = _record_and_token()
    status, claims = _run_extract(
        db, store, payload=json.dumps(record, ensure_ascii=False).encode(),
        span_ref=token)
    assert status is TaskStatus.SUCCEEDED
    assert claims == 1


def test_docling_store_key_bare_substring_refuses(db, store):
    """The A1 tightening survives: a bare token present in the bytes never
    admits a docling record (the digest chain, not the substring, decides)."""
    record, _ = _record_and_token()
    status, claims = _run_extract(
        db, store, payload=json.dumps(record, ensure_ascii=False).encode(),
        span_ref="section_header")
    assert status is not TaskStatus.SUCCEEDED
    assert claims == 0


def test_docling_store_key_forged_charspan_refuses(db, store):
    record, token = _record_and_token()
    parts = token.split(":")
    forged = f"span:{parts[1]}:{int(parts[2]) + 1}:{parts[3]}"
    status, claims = _run_extract(
        db, store, payload=json.dumps(record, ensure_ascii=False).encode(),
        span_ref=forged)
    assert status is not TaskStatus.SUCCEEDED
    assert claims == 0


def test_spliced_provenance_ref_refuses(db, store):
    """The record's own ref chain must agree (content.ref ==
    provenance.source_ref): a spliced record fails closed rather than having
    its inner ref trusted."""
    record, token = _record_and_token(
        splice_provenance_ref="source_payload:s1-docling/other.pdf")
    status, claims = _run_extract(
        db, store, payload=json.dumps(record, ensure_ascii=False).encode(),
        span_ref=token)
    assert status is not TaskStatus.SUCCEEDED
    assert claims == 0


def test_store_key_resolver_refuses_bare_alias_directly():
    """D-1 (DELTA-AUDIT-M1): the seam itself enforces the full
    ``source_payload:<64-hex>`` store-key shape. A DIRECT call with the
    record's bare non-addressable alias refuses even though the record's
    own ref chain and the span token are genuine — no ``read_payload``
    refusal sits in front of it."""
    record, token = _record_and_token()
    doc = DoclingDocument.from_record(record)
    resolve = resolver_for_store_key(doc)
    # a full-shape key still admits (the guard tests shape, not provenance)
    assert resolve("source_payload:" + "0" * 64, token) is True
    for bare in (record["provenance"]["source_ref"],
                 "source_payload:x.pdf",
                 "source_payload:" + "0" * 63):
        assert resolve(bare, token) is False, bare


def test_plain_payload_substring_path_unchanged(db, store):
    """No semantics change for non-docling payloads (certified HR-05/M3)."""
    status, claims = _run_extract(
        db, store, payload=b"alpha beta gamma section of text",
        span_ref="beta")
    assert status is TaskStatus.SUCCEEDED
    assert claims == 1
