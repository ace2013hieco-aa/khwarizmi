"""CRED-1 (GAP-1 P1-3): operator-credential REVOKE / ROTATE through the
single mutation path (``apply_intent``), with journal events.

Pins:

- ``REVOKE_OPERATOR_CREDENTIAL`` / ``ROTATE_OPERATOR_CREDENTIAL`` are
  Director-only (credential management is human authority; LLM profiles
  must never revoke/rotate) — the role gate refuses every other profile.
- Revocation is archive-not-delete: the row survives with ``revoked_at``
  set; ``verify()`` / ``exists()`` refuse it everywhere (repository,
  controller pre-verify, gateway A4 existence checks).
- Rotate mints a NEW token server-side and returns it through the intent
  result (``result.row["new_token"]``) — the plaintext token never enters
  an intent payload or a journal event.
- Replays: an identical revoke is idempotent (``duplicate=True``, ZERO new
  rows/events); rotate always mints a fresh token (each rotation kills the
  previous one).
"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from hermes.core import frozen_clock
from hermes.core.intents import Intent, IntentKind
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    OperatorCredentialRepository,
    ProjectRepository,
)
from hermes.research.controller import Controller
from hermes.research.gateway import (
    MALFORMED_PAYLOAD,
    OPERATOR,
    ROLE,
    GatewayRejection,
    apply_intent,
)

OP_ID = "op-cred"
OP_TOKEN = "cred-token-123456"
CLOCK = "2026-01-01T00:00:00.000000+00:00"


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    yield conn
    conn.close()


def _register(conn, token: str = OP_TOKEN) -> None:
    OperatorCredentialRepository(conn, frozen_clock(CLOCK)).register(
        OP_ID, token, "Cred Operator")


def _lifecycle_intent(kind_name: str, *, proposed_by: str = "DIRECTOR",
                      payload: dict | None = None) -> Intent:
    kind = getattr(IntentKind, kind_name)
    if payload is None:
        payload = ({"operator_id": OP_ID, "reason": "lost device"}
                   if kind_name == "REVOKE_OPERATOR_CREDENTIAL"
                   else {"operator_id": OP_ID})
    return Intent(kind=kind, proposed_by=proposed_by, project_id="p1",
                  justification="credential hygiene", payload=payload)


def _revoke_intent(*, proposed_by: str = "DIRECTOR",
                   payload: dict | None = None) -> Intent:
    return _lifecycle_intent("REVOKE_OPERATOR_CREDENTIAL",
                             proposed_by=proposed_by, payload=payload)


def _rotate_intent(*, proposed_by: str = "DIRECTOR") -> Intent:
    return _lifecycle_intent("ROTATE_OPERATOR_CREDENTIAL",
                             proposed_by=proposed_by)


def _token_hashes(conn) -> list[str]:
    return [r["token_hash"] for r in conn.execute(
        "SELECT token_hash FROM operator_credentials").fetchall()]


def _journal_text(conn) -> str:
    """Every journal row's payload as one blob — for token-leak scans."""
    return " ".join(
        (r["payload_json"] or "") + " " + (r["reason"] or "")
        for r in conn.execute(
            "SELECT payload_json, reason FROM events").fetchall())


class TestRevoke:
    def test_revoke_marks_row_and_refuses_everywhere(self, db):
        _register(db)
        repo = OperatorCredentialRepository(db)
        assert repo.verify(OP_ID, OP_TOKEN) is True
        assert repo.exists(OP_ID) is True

        result = apply_intent(db, _revoke_intent())

        assert result.entity_id == OP_ID
        assert result.duplicate is False
        assert result.event_type == "OperatorCredentialRevoked"
        # archive-not-delete: the row survives, revoked_at is stamped
        row = db.execute(
            "SELECT revoked_at FROM operator_credentials "
            "WHERE operator_id = ?", (OP_ID,)).fetchone()
        assert row is not None and row["revoked_at"] is not None
        # the SAME token now fails everywhere the credential is consulted
        assert repo.verify(OP_ID, OP_TOKEN) is False
        assert repo.exists(OP_ID) is False
        # the journal carries the revocation WITH its recorded reason
        payloads = [json.loads(r["payload_json"]) for r in db.execute(
            "SELECT payload_json FROM events WHERE event_type = ?",
            ("OperatorCredentialRevoked",)).fetchall()]
        assert payloads == [{"operator_id": OP_ID, "reason": "lost device"}]
        # ... and no plaintext token anywhere on the journal
        assert OP_TOKEN not in _journal_text(db)

    def test_revoked_operator_refused_at_controller_pre_verify(self, db):
        """The controller's proof-of-humanity check (pre-transaction) refuses
        a revoked credential even when the presented token still matches the
        stored hash — auth precedes any task/proposal lookup."""
        _register(db)
        apply_intent(db, _revoke_intent())
        out = Controller(db, project_id="p1").resolve_human_gate(
            task_id="no-such-task", verdict="APPROVED",
            operator_id=OP_ID, operator_token=OP_TOKEN)
        assert out["rejected"] is True
        assert out["code"] == "OPERATOR"

    def test_revoked_operator_refused_at_gateway_a4_check(self, db):
        """The gateway's A4 existence re-check (RESOLVE_CLASSIFICATION_
        PROPOSAL) refuses a revoked operator before any proposal is
        resolved."""
        _register(db)
        apply_intent(db, _revoke_intent())
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, Intent(
                kind=IntentKind.RESOLVE_CLASSIFICATION_PROPOSAL,
                proposed_by="DETERMINISTIC", project_id="p1",
                payload={"proposal_id": "prop-x", "decision": "APPROVED",
                         "rationale": "", "operator_id": OP_ID}))
        assert exc.value.code == OPERATOR
        # nothing was decided: no decision event, credential still revoked
        assert db.execute(
            "SELECT COUNT(*) n FROM events WHERE event_type = ?",
            ("ClassificationActionDecision",)).fetchone()["n"] == 0
        row = db.execute(
            "SELECT revoked_at FROM operator_credentials "
            "WHERE operator_id = ?", (OP_ID,)).fetchone()
        assert row["revoked_at"] is not None

    def test_revoke_replay_is_idempotent_zero_effects(self, db):
        _register(db)
        first = apply_intent(db, _revoke_intent())
        second = apply_intent(db, _revoke_intent(
            payload={"operator_id": OP_ID, "reason": "changed my mind"}))
        assert first.duplicate is False
        assert second.duplicate is True
        assert db.execute(
            "SELECT COUNT(*) n FROM events WHERE event_type = ?",
            ("OperatorCredentialRevoked",)).fetchone()["n"] == 1

    def test_revoke_unknown_operator_refused(self, db):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, _revoke_intent())
        assert exc.value.code == OPERATOR
        assert db.execute(
            "SELECT COUNT(*) n FROM events WHERE event_type = ?",
            ("OperatorCredentialRevoked",)).fetchone()["n"] == 0


class TestRotate:
    def test_rotate_mints_new_token_and_kills_old(self, db):
        _register(db)
        repo = OperatorCredentialRepository(db)

        result = apply_intent(db, _rotate_intent())

        new_token = result.row["new_token"]
        assert isinstance(new_token, str) and len(new_token) >= 8
        assert new_token != OP_TOKEN
        assert result.entity_id == OP_ID
        assert result.duplicate is False
        assert result.event_type == "OperatorCredentialRotated"
        # old token dead, new token alive, credential still ratified
        assert repo.verify(OP_ID, OP_TOKEN) is False
        assert repo.verify(OP_ID, new_token) is True
        assert repo.exists(OP_ID) is True
        # the event names the operator only — never a token/hash
        payloads = [json.loads(r["payload_json"]) for r in db.execute(
            "SELECT payload_json FROM events WHERE event_type = ?",
            ("OperatorCredentialRotated",)).fetchall()]
        assert payloads == [{"operator_id": OP_ID}]
        journal = _journal_text(db)
        assert new_token not in journal
        assert OP_TOKEN not in journal

    def test_rotate_twice_kills_first_new_token(self, db):
        _register(db)
        repo = OperatorCredentialRepository(db)
        token1 = apply_intent(db, _rotate_intent()).row["new_token"]
        token2 = apply_intent(db, _rotate_intent()).row["new_token"]
        assert token1 != token2
        assert repo.verify(OP_ID, token1) is False
        assert repo.verify(OP_ID, token2) is True
        assert db.execute(
            "SELECT COUNT(*) n FROM events WHERE event_type = ?",
            ("OperatorCredentialRotated",)).fetchone()["n"] == 2

    def test_rotate_after_revoke_refused_without_write(self, db):
        _register(db)
        apply_intent(db, _revoke_intent())
        before = _token_hashes(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, _rotate_intent())
        assert exc.value.code == OPERATOR
        assert _token_hashes(db) == before
        assert db.execute(
            "SELECT COUNT(*) n FROM events WHERE event_type = ?",
            ("OperatorCredentialRotated",)).fetchone()["n"] == 0

    def test_rotate_unknown_operator_refused(self, db):
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, _rotate_intent())
        assert exc.value.code == OPERATOR


class TestRolePartition:
    @pytest.mark.parametrize("kind_name", [
        "REVOKE_OPERATOR_CREDENTIAL", "ROTATE_OPERATOR_CREDENTIAL"])
    def test_declared_director_only(self, kind_name):
        kind = getattr(IntentKind, kind_name)
        assert kind in IntentKind.director_only()
        assert kind not in IntentKind.internal_only()
        assert kind not in IntentKind.llm_proposable()

    @pytest.mark.parametrize("profile", [
        "RESEARCHER", "IMPLEMENTER", "ADVERSARY", "DETERMINISTIC"])
    def test_non_director_profiles_refused(self, db, profile):
        """LLM profiles and the deterministic layer are refused by the role
        gate with code ROLE — and nothing is written (credential intact)."""
        _register(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, _revoke_intent(proposed_by=profile))
        assert exc.value.code == ROLE
        assert OperatorCredentialRepository(db).verify(OP_ID, OP_TOKEN) is True


class TestPayloadDiscipline:
    def test_unknown_keys_refused(self, db):
        _register(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, _revoke_intent(
                payload={"operator_id": OP_ID, "extra": "x"}))
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_reason_not_accepted_on_rotate(self, db):
        _register(db)
        intent = replace(_rotate_intent(), payload={
            "operator_id": OP_ID, "reason": "x"})
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, intent)
        assert exc.value.code == MALFORMED_PAYLOAD

    def test_oversized_reason_refused_pre_write(self, db):
        _register(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, _revoke_intent(
                payload={"operator_id": OP_ID, "reason": "r" * 1025}))
        assert exc.value.code == MALFORMED_PAYLOAD
        assert db.execute(
            "SELECT COUNT(*) n FROM events WHERE event_type = ?",
            ("OperatorCredentialRevoked",)).fetchone()["n"] == 0
        assert OperatorCredentialRepository(db).verify(OP_ID, OP_TOKEN) is True

    def test_empty_operator_id_refused(self, db):
        _register(db)
        with pytest.raises(GatewayRejection) as exc:
            apply_intent(db, _revoke_intent(
                payload={"operator_id": "", "reason": ""}))
        assert exc.value.code == MALFORMED_PAYLOAD
