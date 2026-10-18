"""CRES-DIGEST-1 (P3-17) — resolution rationale digest binding.

Pins the human design-gate ruling R8: resolving a contradiction
POPULATES ``contradictions.resolution_rationale_digest`` by recomputing
the content digest of the rationale held on the BOUND
``HumanDecisionReceived`` row — never from the resolution command
payload (whose key set stays exactly {contradiction_id,
human_decision_ref, operator_id}), inside the existing resolution
transaction.

Pinned policy (decided in-slice):

- ``rationale`` is a string (including the empty string): the column
  stores ``sha256(utf-8 bytes).hexdigest()`` — the RETRACT_SOURCE
  reason-binding convention, full 64-hex digest.
- ``rationale`` key absent, or present but not a string: the bound row
  carries no rationale text — the column stays NULL (no new refusal;
  the existing decision-binding validation remains the admission
  gate).
- ``rationale`` is a string that cannot be canonically encoded (a
  corrupt journaled payload): the resolution refuses fail-closed
  (PROPOSAL) and nothing is written.

Covers: digest population + readback (repository), different
rationale → different digest, replay idempotency (no double effects,
never re-digested), unchanged PROPOSAL/STALE refusal paths,
append-only journal, and the closed command-payload key set.
"""
from __future__ import annotations

import hashlib
import json
from unittest import mock

import pytest

from hermes.core import frozen_clock
from hermes.core.events import EventType
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    ContradictionRepository,
    OperatorCredentialRepository,
    ProjectRepository,
    _append_event_to_db,
)
from hermes.research.contradictions import (
    CONTRADICTION_DETECTOR_VERSION,
    contradiction_id_of,
)
from hermes.research.controller import Controller
from hermes.research.evidence_ladder import classification_content_hash
from hermes.research.gateway import (
    MALFORMED_PAYLOAD,
    PROPOSAL,
    STALE,
    GatewayRejection,
    _contradiction_resolution_id,
    apply_intent,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"
OP_ID = "op-1"
OP_TOKEN = "op-token-1"


# ═══════════════════════ fixtures ═══════════════════════


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p1", "Test")
    ProjectRepository(conn, frozen_clock(CLOCK)).create("p2", "Other")
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, OP_TOKEN, "Test Operator")
    yield conn
    conn.close()


def _make(db, project="p1"):
    return Controller(db, project_id=project, clock=frozen_clock(CLOCK))


def _insert_artifact(db, artifact_id, *, artifact_type="source_result",
                     content_hash=None, project="p1", task_id=None,
                     meta=None):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, ?, ?, ?, 1, 'x', 't', ?, ?)""",
        (artifact_id, project, task_id, artifact_type,
         content_hash or f"ch-{artifact_id}",
         json.dumps(meta) if meta is not None else None, CLOCK))


def _insert_classification(db, *, cls_art="fc-1", project="p1",
                           program_ref="rp-1", hypothesis_ref="h1",
                           failure_class="DECLARED_CONSTRAINT_VIOLATION",
                           falsifying_refs=None):
    """A digest-valid classification artifact. Returns artifact_id."""
    if falsifying_refs is None:
        falsifying_refs = ["evidence:evhash1"]
    from hermes.research.failure_classification import (
        ACTION_MAP,
        FailureClass,
    )
    permitted = sorted(
        a.value for a in ACTION_MAP[FailureClass(failure_class)])
    meta = {
        "schema_version": "1",
        "failure_class": failure_class,
        "hypothesis_ref": hypothesis_ref,
        "program_ref": program_ref,
        "classification_id": cls_art,
        "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": list(falsifying_refs),
        "constraint_ref": f"hypothesis:{hypothesis_ref}:falsification_condition",
        "failed_mechanism_ref": None,
        "regime_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": f"cres-digest test {cls_art}",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": list(falsifying_refs),
        "permitted_actions": permitted,
    }
    content_hash = classification_content_hash(meta, project)
    _insert_artifact(db, cls_art, artifact_type="failure_classification",
                     content_hash=content_hash, project=project, meta=meta)
    return cls_art


def _insert_evidence(db, artifact_id="art-ev1", *, content_hash="evhash1",
                     project="p1"):
    _insert_artifact(db, artifact_id, artifact_type="evidence",
                     content_hash=content_hash, project=project)


def _conflicting_pair(db, *, project="p1", program_ref="rp-1",
                      hypothesis_ref="h1", evidence_hash="evhash1",
                      evidence_id="art-ev1", cls_a="fc-a", cls_b="fc-b"):
    """Two digest-valid classifications, same target, different classes,
    sharing one evidence artifact. Returns (id_a, id_b)."""
    _insert_evidence(db, evidence_id, content_hash=evidence_hash,
                     project=project)
    _insert_classification(
        db, cls_art=cls_a, project=project, program_ref=program_ref,
        hypothesis_ref=hypothesis_ref,
        failure_class="DECLARED_CONSTRAINT_VIOLATION",
        falsifying_refs=[f"evidence:{evidence_hash}"])
    _insert_classification(
        db, cls_art=cls_b, project=project, program_ref=program_ref,
        hypothesis_ref=hypothesis_ref,
        failure_class="IMPLEMENTATION_FAILURE",
        falsifying_refs=[f"evidence:{evidence_hash}"])
    return cls_a, cls_b


def _record(db, party_a, party_b, *, supersedes_ref="", project="p1"):
    return apply_intent(db, Intent(
        kind=IntentKind.RECORD_CONTRADICTION, proposed_by="DETERMINISTIC",
        project_id=project, justification="cres digest test",
        payload={"party_a": party_a, "party_b": party_b,
                 "detector_version": CONTRADICTION_DETECTOR_VERSION,
                 "supersedes_ref": supersedes_ref}))


def _resolve(db, contradiction_id, *, rationale="", project="p1"):
    return _make(db, project).record_contradiction_resolution(
        contradiction_id=contradiction_id, rationale=rationale,
        operator_id=OP_ID, operator_token=OP_TOKEN)


def _second_pair(db):
    """A second, independent conflicting pair (fresh evidence + classes).

    Returns the RECORD_CONTRADICTION result for the pair."""
    _insert_evidence(db, "art-e2", content_hash="evhash2")
    _insert_classification(
        db, cls_art="fc-c", failure_class="DECLARED_CONSTRAINT_VIOLATION",
        falsifying_refs=["evidence:evhash2"])
    _insert_classification(
        db, cls_art="fc-d", failure_class="IMPLEMENTATION_FAILURE",
        falsifying_refs=["evidence:evhash2"])
    return _record(db, "fc-c", "fc-d")


def _digest(db, contradiction_id):
    row = db.execute(
        "SELECT resolution_rationale_digest FROM contradictions "
        "WHERE contradiction_id = ?",
        (contradiction_id,)).fetchone()
    return row["resolution_rationale_digest"]


def _status(db, contradiction_id):
    row = db.execute(
        "SELECT status FROM contradictions WHERE contradiction_id = ?",
        (contradiction_id,)).fetchone()
    return row["status"] if row else None


def _canonical_digest(rationale: str) -> str:
    """The pinned convention: sha256 over the UTF-8 rationale bytes."""
    return hashlib.sha256(rationale.encode("utf-8")).hexdigest()


def _events(db):
    return db.execute(
        "SELECT event_id, event_type, project_id, correlation_id, "
        "caused_by, reason, payload_json, created_at "
        "FROM events ORDER BY event_id").fetchall()


_CONTRADICTION_COLUMNS = (
    "contradiction_id", "project_id", "type", "party_a", "party_b",
    "evidence_overlap_json", "status", "detector_version", "detected_at",
    "detection_event_ref", "resolution_event_ref",
    "resolution_rationale_digest", "supersedes_ref", "created_at")


def _row_snapshot(db, contradiction_id):
    row = db.execute(
        "SELECT * FROM contradictions WHERE contradiction_id = ?",
        (contradiction_id,)).fetchone()
    return {key: row[key] for key in _CONTRADICTION_COLUMNS}


def _bound_decision_payload(cid, **extra):
    payload = {"decision": "CONTRADICTION_RESOLUTION",
               "resolution_id": _contradiction_resolution_id(cid),
               "contradiction_id": cid}
    payload.update(extra)
    return payload


def _record_decision(db, cid, *, ref, payload, project="p1"):
    _append_event_to_db(
        db, frozen_clock(CLOCK),
        EventType.HUMAN_DECISION_RECEIVED.value,
        project_id=project, correlation_id=ref, caused_by="operator",
        reason="operator decision", payload=payload)
    return ref


def _resolve_intent(db, cid, ref, *, project="p1"):
    return apply_intent(db, Intent(
        kind=IntentKind.CONTRADICTION_RESOLUTION,
        proposed_by="DETERMINISTIC", project_id=project,
        justification="cres digest test",
        payload={"contradiction_id": cid, "human_decision_ref": ref,
                 "operator_id": OP_ID}))


# ═══════════════════════ digest population ═══════════════════════


class TestDigestPopulation:
    def test_resolution_stores_digest_of_bound_rationale(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        note = "closes the pair: party A holds under the constraint"
        out = _resolve(db, r.entity_id, rationale=note)
        assert out["rejected"] is False
        stored = _digest(db, r.entity_id)
        assert stored == _canonical_digest(note)
        assert len(stored) == 64
        assert stored == stored.lower()
        # A digest of the rationale, never the rationale text itself.
        assert note not in stored

    def test_empty_rationale_digests_empty_string(self, db):
        # The controller default (and the live test-suite shape) is an
        # empty-string rationale — a present string digests as b"".
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        out = _resolve(db, r.entity_id)
        assert out["rejected"] is False
        assert _digest(db, r.entity_id) == _canonical_digest("")
        assert _digest(db, r.entity_id) == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    def test_different_rationale_different_digest(self, db):
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b)
        r2 = _second_pair(db)
        _resolve(db, r1.entity_id, rationale="first verdict note")
        _resolve(db, r2.entity_id, rationale="second verdict note")
        d1 = _digest(db, r1.entity_id)
        d2 = _digest(db, r2.entity_id)
        assert d1 == _canonical_digest("first verdict note")
        assert d2 == _canonical_digest("second verdict note")
        assert d1 != d2

    def test_same_rationale_same_digest_across_contradictions(self, db):
        # The digest is content identity of the rationale — not salted
        # by the contradiction identity.
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b)
        r2 = _second_pair(db)
        note = "same operator wording for both verdicts"
        _resolve(db, r1.entity_id, rationale=note)
        _resolve(db, r2.entity_id, rationale=note)
        assert _digest(db, r1.entity_id) == _digest(db, r2.entity_id) \
            == _canonical_digest(note)

    def test_readback_via_repository_returns_digest(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        note = "readback verdict note"
        out = _resolve(db, r.entity_id, rationale=note)
        repo = ContradictionRepository(db)
        entry = repo.entry("p1", r.entity_id)
        assert entry is not None
        assert entry["status"] == "RESOLVED"
        assert entry["resolution_event_ref"] == out["resolution_id"]
        assert entry["resolution_rationale_digest"] == \
            _canonical_digest(note)
        listed = [e for e in repo.all_entries("p1")
                  if e["contradiction_id"] == r.entity_id]
        assert len(listed) == 1
        assert listed[0]["resolution_rationale_digest"] == \
            _canonical_digest(note)
        # Project isolation: the same id does not resolve in another
        # project's readback.
        assert repo.entry("p2", r.entity_id) is None


# ═══════════════════════ NULL-safe / fail-closed policy ═══════════════


class TestRationalePolicy:
    def test_absent_rationale_stores_null_without_new_refusal(self, db):
        # The bound row legitimately lacks rationale text: the digest
        # column stays NULL and the existing decision-binding validation
        # remains the only admission gate (no new refusal).
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        ref = _record_decision(
            db, r.entity_id, ref="hd-no-note",
            payload=_bound_decision_payload(r.entity_id, operator_id=OP_ID))
        out = _resolve_intent(db, r.entity_id, ref)
        assert out.duplicate is False
        assert _status(db, r.entity_id) == "RESOLVED"
        assert _digest(db, r.entity_id) is None

    def test_non_string_rationale_stores_null(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        ref = _record_decision(
            db, r.entity_id, ref="hd-typed-note",
            payload=_bound_decision_payload(
                r.entity_id, operator_id=OP_ID, rationale=123))
        out = _resolve_intent(db, r.entity_id, ref)
        assert out.duplicate is False
        assert _status(db, r.entity_id) == "RESOLVED"
        assert _digest(db, r.entity_id) is None

    def test_unencodable_rationale_refused_fail_closed(self, db):
        # A corrupt journaled payload (lone surrogate) cannot be written
        # through the certified event writer; when present in the journal
        # it must refuse fail-closed, never raise raw and never record an
        # unverifiable digest.
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        ref = f"hd-{r.entity_id}"
        payload_json = json.dumps(
            _bound_decision_payload(
                r.entity_id, operator_id=OP_ID, rationale="\ud800"),
            ensure_ascii=True)  # ASCII-escaped, storable
        db.execute(
            "INSERT INTO events (event_type, project_id, correlation_id, "
            "caused_by, reason, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (EventType.HUMAN_DECISION_RECEIVED.value, "p1", ref, "operator",
             "corrupt fixture", payload_json, CLOCK))
        with pytest.raises(GatewayRejection) as exc:
            _resolve_intent(db, r.entity_id, ref)
        assert exc.value.code == PROPOSAL
        assert _status(db, r.entity_id) == "OPEN"
        assert _digest(db, r.entity_id) is None


# ═══════════════════════ replay idempotency ═══════════════════════


class TestReplayIdempotency:
    def test_replay_returns_duplicate_and_keeps_digest(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        note = "the one binding verdict note"
        first = _resolve(db, r.entity_id, rationale=note)
        assert first["rejected"] is False
        snapshot = _row_snapshot(db, r.entity_id)
        resolved_events = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_RESOLVED.value,)).fetchone()["c"]
        decision_events = db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ? "
            "AND correlation_id = ?",
            (EventType.HUMAN_DECISION_RECEIVED.value,
             first["decision_ref"])).fetchone()["c"]

        second = _resolve(db, r.entity_id, rationale=note)

        assert second["duplicate"] is True
        assert second["rejected"] is False
        assert _row_snapshot(db, r.entity_id) == snapshot
        assert _digest(db, r.entity_id) == _canonical_digest(note)
        assert db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_RESOLVED.value,)).fetchone()["c"] == \
            resolved_events
        assert db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ? "
            "AND correlation_id = ?",
            (EventType.HUMAN_DECISION_RECEIVED.value,
             first["decision_ref"])).fetchone()["c"] == decision_events

    def test_replay_with_different_rationale_never_redigests(self, db):
        # The decision ref is deterministic per contradiction, so a later
        # resolution attempt with different wording finds the FIRST bound
        # decision — the stored digest stays the first rationale's.
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        first = _resolve(db, r.entity_id, rationale="first wording")
        second = _resolve(db, r.entity_id, rationale="second wording")
        assert second["duplicate"] is True
        assert second["resolution_id"] == first["resolution_id"]
        assert _digest(db, r.entity_id) == _canonical_digest("first wording")
        assert _digest(db, r.entity_id) != \
            _canonical_digest("second wording")


# ═══════════════════════ refusal paths unchanged ═══════════════════════


class TestRefusalPathsUnchanged:
    def test_fabricated_decision_still_proposal(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        with pytest.raises(GatewayRejection) as exc:
            _resolve_intent(db, r.entity_id, "hd-ghost")
        assert exc.value.code == PROPOSAL
        assert _status(db, r.entity_id) == "OPEN"
        assert _digest(db, r.entity_id) is None

    def test_superseded_target_still_stale(self, db):
        a, b = _conflicting_pair(db)
        r1 = _record(db, a, b)
        _insert_evidence(db, "art-e2", content_hash="evhash2")
        _insert_classification(
            db, cls_art="fc-c",
            failure_class="DECLARED_CONSTRAINT_VIOLATION",
            falsifying_refs=["evidence:evhash2"])
        _insert_classification(
            db, cls_art="fc-d", failure_class="IMPLEMENTATION_FAILURE",
            falsifying_refs=["evidence:evhash2"])
        linked = _record(db, "fc-c", "fc-d", supersedes_ref=r1.entity_id)
        assert linked.duplicate is False
        assert _status(db, r1.entity_id) == "SUPERSEDED"
        out = _resolve(db, r1.entity_id, rationale="too late")
        assert out["rejected"] is True
        assert out["code"] == STALE
        assert _status(db, r1.entity_id) == "SUPERSEDED"
        assert _digest(db, r1.entity_id) is None
        assert _status(db, linked.entity_id) == "OPEN"


# ═══════════════════════ command payload key set ═══════════════════════


class TestCommandPayloadClosed:
    def test_extra_rationale_key_refused(self, db):
        # The command payload NEVER carries the rationale: the closed key
        # set {contradiction_id, human_decision_ref, operator_id} is
        # enforced fail-closed, so the digest can never be smuggled in.
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.CONTRADICTION_RESOLUTION,
                proposed_by="DETERMINISTIC", project_id="p1",
                justification="cres digest test",
                payload={"contradiction_id": r.entity_id,
                         "human_decision_ref": "hd-ghost",
                         "operator_id": OP_ID,
                         "rationale": "smuggled wording"}))
        assert exc.value.code == MALFORMED_PAYLOAD
        assert _status(db, r.entity_id) == "OPEN"
        assert _digest(db, r.entity_id) is None

    def test_controller_submits_exactly_three_keys(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        import hermes.research.gateway as gw
        seen = {}
        real = gw.apply_intent

        def spy(conn, intent, **kw):
            seen["payload"] = dict(intent.payload)
            return real(conn, intent, **kw)

        with mock.patch.object(gw, "apply_intent", spy):
            out = _resolve(db, r.entity_id, rationale="binding note")
        assert out["rejected"] is False
        assert set(seen["payload"]) == {
            "contradiction_id", "human_decision_ref", "operator_id"}
        # The stored digest is recomputed from the BOUND row; the
        # rationale never traveled through the command payload.
        assert _digest(db, r.entity_id) == _canonical_digest("binding note")


# ═══════════════════════ append-only journal ═══════════════════════


class TestAppendOnly:
    def test_event_prefix_and_row_history_preserved(self, db):
        a, b = _conflicting_pair(db)
        r = _record(db, a, b)
        cid = r.entity_id
        before_events = _events(db)
        before_row = _row_snapshot(db, cid)

        out = _resolve(db, cid, rationale="append-only note")
        assert out["rejected"] is False

        after_events = _events(db)
        assert len(after_events) > len(before_events)
        # Append-only: every pre-resolution event row survives
        # byte-identically as an exact prefix of the journal.
        assert after_events[:len(before_events)] == before_events

        after_row = _row_snapshot(db, cid)
        changed = {key for key in before_row
                   if before_row[key] != after_row[key]}
        # Only the chartered resolution columns moved; identity,
        # parties, overlap and detection provenance are untouched.
        assert changed == {"status", "resolution_event_ref",
                           "resolution_rationale_digest"}
        assert after_row["status"] == "RESOLVED"
        assert after_row["resolution_rationale_digest"] == \
            _canonical_digest("append-only note")

        resolved = [e for e in after_events
                    if e["event_type"]
                    == EventType.CONTRADICTION_RESOLVED.value]
        assert len(resolved) == 1
        assert resolved[0]["correlation_id"] == out["resolution_id"]
        payload = json.loads(resolved[0]["payload_json"])
        assert payload["contradiction_id"] == cid
        assert payload["human_decision_ref"] == out["decision_ref"]


# ═══════════════════════ identity cross-check ═══════════════════════


def test_contradiction_identity_recomputed(db):
    # Guard pin: the digest work touches no identity rule — the row id
    # is still the recomputed content hash of the canonical pair.
    a, b = _conflicting_pair(db)
    r = _record(db, b, a)
    assert r.entity_id == contradiction_id_of(a, b)
    out = _resolve(db, r.entity_id, rationale="identity note")
    assert out["rejected"] is False
    repo = ContradictionRepository(db)
    entry = repo.entry("p1", contradiction_id_of(b, a))
    assert entry is not None
    assert entry["contradiction_id"] == contradiction_id_of(a, b)
