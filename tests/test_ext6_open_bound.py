"""EXT-6 / R4 — cumulative OPEN-contradiction ceiling tests.

Pins the EXT-6 bound on the contradiction lifecycle: once a project's
OPEN contradiction set reaches ``MAX_OPEN_CONTRADICTIONS`` the gateway
refuses a NET-NEW ``RECORD_CONTRADICTION`` fail-closed with the named
code ``CONTRADICTION_BACKLOG`` (refusal-as-data — never a silent drop),
leaving existing OPEN rows untouched.

Three properties are proven here:

1. **Flood-proof** — driving N+1 real recordings, the Nth+1 refuses
   with data (code + operator guidance), no row is written, and the
   project's OPEN set stays exactly at N.
2. **The drain stays open** — the ratified human verdict
   (``CONTRADICTION_RESOLUTION``) is the only resolution path and keeps
   working at/over the ceiling; a freed slot re-admits.
3. **Net-zero / idempotent paths are not gated** — head-only
   supersession retires one OPEN row in the same transaction, and an
   idempotent replay of an already-recorded pair has zero effects; both
   stay admissible at the ceiling.

The ceiling is exercised at a small pinned value via ``monkeypatch``
(the gateway reads the module attribute at call time) so the flood
proof drives N+1 recordings rather than the production 1000.
"""
from __future__ import annotations

import json

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
)
from hermes.research import contradictions as cx
from hermes.research.contradictions import (
    CONTRADICTION_DETECTOR_VERSION,
    DEFAULT_MAX_PAIRS,
    MAX_OPEN_CONTRADICTIONS,
    contradiction_id_of,
)
from hermes.research.controller import Controller
from hermes.research.evidence_ladder import classification_content_hash
from hermes.research.gateway import (
    CONTRADICTION_BACKLOG,
    GatewayRejection,
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
                     content_hash=None, project="p1", meta=None):
    db.execute(
        """INSERT INTO artifacts
           (artifact_id, project_id, task_id, artifact_type,
            content_hash, size_bytes, storage_path, producer,
            metadata_json, created_at)
           VALUES (?, ?, NULL, ?, ?, 1, 'x', 't', ?, ?)""",
        (artifact_id, project, artifact_type,
         content_hash or f"ch-{artifact_id}",
         json.dumps(meta) if meta is not None else None, CLOCK))


def _insert_classification(db, *, cls_art, project="p1", program_ref="rp-1",
                           hypothesis_ref="h1",
                           failure_class="DECLARED_CONSTRAINT_VIOLATION",
                           evidence_hash=None):
    """One digest-valid classification artifact sharing ``evidence_hash``."""
    from hermes.research.failure_classification import (
        ACTION_MAP,
        FailureClass,
    )
    if evidence_hash is None:
        evidence_hash = f"evhash-{project}"
    permitted = sorted(
        a.value for a in ACTION_MAP[FailureClass(failure_class)])
    refs = [f"evidence:{evidence_hash}"]
    meta = {
        "schema_version": "1",
        "failure_class": failure_class,
        "hypothesis_ref": hypothesis_ref,
        "program_ref": program_ref,
        "classification_id": cls_art,
        "classifier_version": "1.0",
        "contributing_factors": [],
        "evidence_refs": list(refs),
        "constraint_ref": f"hypothesis:{hypothesis_ref}:falsification_condition",
        "failed_mechanism_ref": None,
        "regime_ref": None,
        "resource_gap": None,
        "scope_brief_ref": None,
        "scope_brief_field": None,
        "explanation": f"ext6 test {cls_art}",
        "proposed_by": "DIRECTOR",
        "falsifying_evidence_refs": list(refs),
        "permitted_actions": permitted,
    }
    content_hash = classification_content_hash(meta, project)
    _insert_artifact(db, cls_art, artifact_type="failure_classification",
                     content_hash=content_hash, project=project, meta=meta)
    return cls_art


def _insert_evidence(db, artifact_id, *, content_hash, project="p1"):
    _insert_artifact(db, artifact_id, artifact_type="evidence",
                     content_hash=content_hash, project=project)


def _group(db, n, *, project="p1"):
    """``n`` digest-valid classifications in ONE (program, hypothesis)
    group, alternating failure class, all sharing one evidence artifact.

    Returns their ids ``["<project>-fc-0", "<project>-fc-1", ...]``.
    Every consecutive pair ``(fc-2i, fc-2i+1)`` is therefore a distinct
    valid contradiction candidate (different failure class, non-empty
    evidence overlap). Ids are project-scoped (artifact_id is the PK).
    """
    evidence_hash = f"evhash-{project}"
    _insert_evidence(db, f"{project}-art-ev1", content_hash=evidence_hash,
                     project=project)
    ids = []
    for i in range(n):
        cls = f"{project}-fc-{i}"
        failure_class = ("DECLARED_CONSTRAINT_VIOLATION" if i % 2 == 0
                         else "IMPLEMENTATION_FAILURE")
        _insert_classification(db, cls_art=cls, project=project,
                               failure_class=failure_class,
                               evidence_hash=evidence_hash)
        ids.append(cls)
    return ids


def _record(db, party_a, party_b, *, supersedes_ref="", project="p1"):
    return apply_intent(db, Intent(
        kind=IntentKind.RECORD_CONTRADICTION, proposed_by="DETERMINISTIC",
        project_id=project, justification="ext6 bound test",
        payload={"party_a": party_a, "party_b": party_b,
                 "detector_version": CONTRADICTION_DETECTOR_VERSION,
                 "supersedes_ref": supersedes_ref}))


def _resolve(db, contradiction_id, *, project="p1"):
    return _make(db, project=project).record_contradiction_resolution(
        contradiction_id=contradiction_id,
        operator_id=OP_ID, operator_token=OP_TOKEN)


def _open_rows(db, project="p1"):
    return db.execute(
        "SELECT contradiction_id, status FROM contradictions "
        "WHERE project_id = ? AND status = 'OPEN' "
        "ORDER BY contradiction_id ASC", (project,)).fetchall()


def _pin_ceiling(monkeypatch, value):
    monkeypatch.setattr(cx, "MAX_OPEN_CONTRADICTIONS", value)
    return value


# ═══════════════════════ ceiling constant ═══════════════════════


class TestCeilingConstant:
    def test_ceiling_is_the_documented_value(self):
        # The cumulative ceiling is pinned at exactly 2x the per-pass pair
        # cap: a maximal pass from an OPEN set at or below the cap cannot
        # trip it (see the arithmetic on the constant's own comment).
        assert MAX_OPEN_CONTRADICTIONS == 1000
        assert MAX_OPEN_CONTRADICTIONS == 2 * DEFAULT_MAX_PAIRS

    def test_ceiling_is_exported(self):
        assert "MAX_OPEN_CONTRADICTIONS" in cx.__all__


# ═══════════════════════ flood proof ═══════════════════════


class TestFloodProof:
    def test_n_plus_1_recording_refuses_with_data(self, db, monkeypatch):
        _pin_ceiling(monkeypatch, 3)
        ids = _group(db, 8)
        recorded = []
        for i in range(3):
            result = _record(db, ids[2 * i], ids[2 * i + 1])
            assert result.duplicate is False
            recorded.append(result.entity_id)

        with pytest.raises(GatewayRejection) as excinfo:
            _record(db, ids[6], ids[7])
        rejection = excinfo.value
        assert rejection.code == CONTRADICTION_BACKLOG
        # Operator guidance travels with the refusal (refusal-as-data).
        detail = str(rejection)
        assert "OPEN contradictions" in detail
        assert "ceiling" in detail
        assert "human-verdict path" in detail

    def test_refusal_writes_nothing_and_leaves_existing_rows_untouched(
            self, db, monkeypatch):
        _pin_ceiling(monkeypatch, 3)
        ids = _group(db, 8)
        for i in range(3):
            _record(db, ids[2 * i], ids[2 * i + 1])
        before = {(r["contradiction_id"], r["status"]) for r in _open_rows(db)}

        refused_cid = contradiction_id_of(ids[6], ids[7])
        with pytest.raises(GatewayRejection):
            _record(db, ids[6], ids[7])
        # The rejection handler rolled the write transaction back: the
        # connection is not left mid-transaction (the refusal adds no
        # transaction-control call of its own).
        assert db.in_transaction is False

        after = {(r["contradiction_id"], r["status"]) for r in _open_rows(db)}
        assert after == before, "a refusal must not touch existing rows"
        assert len(after) == 3
        assert refused_cid not in {cid for cid, _ in after}
        # The refused pair produced no row and no CONTRADICTION_DETECTED.
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions WHERE contradiction_id = ?",
            (refused_cid,)).fetchone()["c"] == 0
        assert db.execute(
            "SELECT COUNT(*) c FROM events WHERE event_type = ?",
            (EventType.CONTRADICTION_DETECTED.value,)).fetchone()["c"] == 3

    def test_active_reader_agrees_with_the_bound(self, db, monkeypatch):
        _pin_ceiling(monkeypatch, 2)
        ids = _group(db, 6)
        _record(db, ids[0], ids[1])
        _record(db, ids[2], ids[3])
        with pytest.raises(GatewayRejection):
            _record(db, ids[4], ids[5])
        active = ContradictionRepository(db).open_contradictions("p1")
        assert len(active) == 2


# ═══════════════════════ the drain stays open ═══════════════════════


class TestResolutionNeverBlocked:
    def test_human_verdict_works_at_the_ceiling(self, db, monkeypatch):
        _pin_ceiling(monkeypatch, 2)
        ids = _group(db, 6)
        cid_a = _record(db, ids[0], ids[1]).entity_id
        _record(db, ids[2], ids[3])
        with pytest.raises(GatewayRejection):
            _record(db, ids[4], ids[5])   # at the ceiling

        verdict = _resolve(db, cid_a)
        assert verdict.get("rejected") is not True, verdict
        assert verdict["duplicate"] is False
        assert db.execute(
            "SELECT status FROM contradictions WHERE contradiction_id = ?",
            (cid_a,)).fetchone()["status"] == "RESOLVED"

    def test_resolving_frees_a_slot_for_a_new_recording(self, db, monkeypatch):
        _pin_ceiling(monkeypatch, 2)
        ids = _group(db, 6)
        cid_a = _record(db, ids[0], ids[1]).entity_id
        _record(db, ids[2], ids[3])
        with pytest.raises(GatewayRejection):
            _record(db, ids[4], ids[5])

        assert _resolve(db, cid_a)["rejected"] is False
        # One slot freed -> the previously refused recording now admits.
        result = _record(db, ids[4], ids[5])
        assert result.duplicate is False
        assert len(_open_rows(db)) == 2


# ═══════════════════════ net-zero / idempotent paths ═══════════════════════


class TestNetZeroPathsNotGated:
    def test_idempotent_replay_is_not_refused_at_the_ceiling(
            self, db, monkeypatch):
        _pin_ceiling(monkeypatch, 2)
        ids = _group(db, 6)
        cid_a = _record(db, ids[0], ids[1]).entity_id
        _record(db, ids[2], ids[3])
        with pytest.raises(GatewayRejection):
            _record(db, ids[4], ids[5])

        replay = _record(db, ids[0], ids[1])
        assert replay.duplicate is True
        assert replay.entity_id == cid_a
        assert len(_open_rows(db)) == 2

    def test_head_only_supersession_is_not_gated_at_the_ceiling(
            self, db, monkeypatch):
        _pin_ceiling(monkeypatch, 2)
        ids = _group(db, 6)
        cid_a = _record(db, ids[0], ids[1]).entity_id
        _record(db, ids[2], ids[3])
        with pytest.raises(GatewayRejection):
            _record(db, ids[4], ids[5])

        # Supersession retires one OPEN row in the same transaction: the
        # OPEN set does not grow, so it stays admissible at the ceiling.
        result = _record(db, ids[4], ids[5], supersedes_ref=cid_a)
        assert result.duplicate is False
        statuses = dict(db.execute(
            "SELECT contradiction_id, status FROM contradictions "
            "WHERE project_id = 'p1'").fetchall())
        assert statuses[cid_a] == "SUPERSEDED"
        assert len(_open_rows(db)) == 2


# ═══════════════════════ scoping ═══════════════════════


class TestBoundScoping:
    def test_ceiling_is_project_scoped(self, db, monkeypatch):
        _pin_ceiling(monkeypatch, 1)
        p1_ids = _group(db, 4, project="p1")
        _record(db, p1_ids[0], p1_ids[1])
        # A second VALID pair in p1 is refused: p1 is at its ceiling.
        with pytest.raises(GatewayRejection) as excinfo:
            _record(db, p1_ids[2], p1_ids[3])
        assert excinfo.value.code == CONTRADICTION_BACKLOG

        # p2 has its own, independent ceiling.
        p2_ids = _group(db, 2, project="p2")
        assert _record(db, p2_ids[0], p2_ids[1],
                       project="p2").duplicate is False
        assert len(_open_rows(db, "p2")) == 1

    def test_below_the_ceiling_recording_is_unaffected(self, db, monkeypatch):
        _pin_ceiling(monkeypatch, 5)
        ids = _group(db, 8)
        for i in range(4):
            assert _record(db, ids[2 * i], ids[2 * i + 1]).duplicate is False
        assert len(_open_rows(db)) == 4


# ═══════════════════════ refusal-as-data through the loop ═══════════════════


class TestRefusalSurfacesAsData:
    def test_detector_reports_backlog_refusal_as_data(self, db, monkeypatch):
        _pin_ceiling(monkeypatch, 1)
        # Three classifications [A, B, A] in one group -> two candidate
        # pairs (fc-0,fc-1) and (fc-1,fc-2). With a ceiling of 1, the
        # first admits and the second is refused with data.
        _group(db, 3)
        out = _make(db).detect_contradictions()
        assert out["rejected"] is False
        assert len(out["recorded"]) == 1
        assert len(out["refused"]) == 1
        refusal = out["refused"][0]
        assert refusal["code"] == CONTRADICTION_BACKLOG
        assert "human-verdict path" in refusal["detail"]
        assert len(_open_rows(db)) == 1


# ══════════════════ the SHIPPED height (production ceiling) ══════════════════


def _eligible_pairs(ids):
    """Distinct valid pairs in deterministic order for a ``_group`` build.

    ``_group`` alternates the failure class by index, so two ids
    contradict iff their indices have different parity (different failure
    class) — every such pair shares the group's one evidence artifact.
    """
    return [(ids[i], ids[j])
            for i in range(len(ids))
            for j in range(i + 1, len(ids))
            if (i % 2) != (j % 2)]


class TestShippedHeight:
    """The shipped ceiling's own behaviour AT its own height.

    Every other behavioural pin drives a monkeypatched ceiling (1-5), so
    the constant's own height was never exercised in-suite (audit
    SHOULD-FIX-2). This drives the SHIPPED value end-to-end through the
    gateway: fill to the ceiling, the (ceiling + 1)th refusal with data,
    the drain, and re-admission. Measured ~1.1 s (~0.66 ms/record) — far
    inside the suite's wall-time budget.

    The arithmetic it pins, with K = OPEN at pass start: one maximal pass
    admits min(500, ceiling - K) and refuses the remainder, so a maximal
    pass trips the ceiling iff K > 500 — the 2x height buys one pass of
    headroom from empty, and refusal past it is correct fail-closed
    behaviour, not a defect.
    """

    def test_shipped_height_fill_refuse_drain_readmit(self, db):
        ceiling = MAX_OPEN_CONTRADICTIONS
        # 64 alternating-class classifications in one group -> 32 x 32 =
        # 1024 eligible pairs, enough for the ceiling plus one.
        ids = _group(db, 64)
        pairs = _eligible_pairs(ids)
        assert len(pairs) >= ceiling + 1

        # Fill to the shipped ceiling through the single mutation path.
        for party_a, party_b in pairs[:ceiling]:
            assert _record(db, party_a, party_b).duplicate is False
        assert len(_open_rows(db)) == ceiling
        # The canonical active reader agrees at the shipped height.
        assert len(ContradictionRepository(db).open_contradictions("p1")) \
            == ceiling

        # The (ceiling + 1)th net-new admission refuses with data.
        refused_a, refused_b = pairs[ceiling]
        refused_cid = contradiction_id_of(refused_a, refused_b)
        with pytest.raises(GatewayRejection) as excinfo:
            _record(db, refused_a, refused_b)
        assert excinfo.value.code == CONTRADICTION_BACKLOG
        assert db.in_transaction is False
        # The ceiling is never exceeded and nothing was written.
        assert len(_open_rows(db)) == ceiling
        assert db.execute(
            "SELECT COUNT(*) c FROM contradictions WHERE contradiction_id = ?",
            (refused_cid,)).fetchone()["c"] == 0

        # The drain (the only resolution path) still works at the height.
        drained = _open_rows(db)[0]["contradiction_id"]
        verdict = _resolve(db, drained)
        assert verdict.get("rejected") is not True, verdict
        assert verdict["duplicate"] is False
        assert len(_open_rows(db)) == ceiling - 1

        # The freed slot re-admits the previously refused pair.
        assert _record(db, refused_a, refused_b).duplicate is False
        assert len(_open_rows(db)) == ceiling
