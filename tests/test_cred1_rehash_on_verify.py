"""CRED-1 (GAP-1 P1-3 companion): legacy SHA-256 credential rows are
re-hashed to salted PBKDF2-HMAC-SHA256 on a SUCCESSFUL verification — the
one moment the plaintext token is provably in hand. Transparent storage
upgrade, no authority event (the credential itself is unchanged: same
operator, same token, same ratified state).

Pins:

- successful verify through the CLI upgrades the stored row to
  ``pbkdf2$sha256$...``; a second verify keeps verifying (same token);
- failed auth NEVER upgrades (the wrong token proves nothing);
- non-legacy rows and unknown operators are no-ops (zero writes);
- the upgrade writes NO journal event (storage format is not authority).
"""
from __future__ import annotations

import hashlib

import pytest

from hermes.core import frozen_clock
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import (
    OperatorCredentialRepository,
    ProjectRepository,
)

OP_ID = "op-legacy"
OP_TOKEN = "legacy-token-123456"
CLOCK = "2026-01-01T00:00:00.000000+00:00"


def _legacy_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@pytest.fixture
def db():
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    yield conn
    conn.close()


def _seed_legacy(db, token: str = OP_TOKEN, operator_id: str = OP_ID) -> str:
    """A pre-P2 #1 bare-hex SHA-256 row, exactly as the migration would
    have left it."""
    legacy = _legacy_hash(token)
    db.execute(
        "INSERT INTO operator_credentials "
        "(operator_id, token_hash, name, created_at) VALUES (?, ?, ?, ?)",
        (operator_id, legacy, "Legacy Operator", CLOCK))
    return legacy


def _stored(db, operator_id: str = OP_ID) -> str:
    return db.execute(
        "SELECT token_hash FROM operator_credentials WHERE operator_id = ?",
        (operator_id,)).fetchone()["token_hash"]


def _event_count(db) -> int:
    return db.execute("SELECT COUNT(*) n FROM events").fetchone()["n"]


class TestDirectUpgrade:
    def test_upgrade_rehashes_legacy_row_and_keeps_verifying(self, db):
        legacy = _seed_legacy(db)
        repo = OperatorCredentialRepository(db)
        assert _stored(db) == legacy

        assert repo.upgrade_legacy_hash(OP_ID, OP_TOKEN) is True

        stored = _stored(db)
        assert stored.startswith("pbkdf2$sha256$")
        assert stored != legacy
        # the SAME token verifies before and after; a wrong one never does
        assert repo.verify(OP_ID, OP_TOKEN) is True
        assert repo.verify(OP_ID, "wrong-token-123456") is False

    def test_upgrade_wrong_token_is_a_noop(self, db):
        legacy = _seed_legacy(db)
        assert OperatorCredentialRepository(db).upgrade_legacy_hash(
            OP_ID, "wrong-token-123456") is False
        assert _stored(db) == legacy

    def test_upgrade_unknown_operator_is_a_noop(self, db):
        assert OperatorCredentialRepository(db).upgrade_legacy_hash(
            "ghost-op", OP_TOKEN) is False

    def test_upgrade_modern_row_is_a_noop(self, db):
        OperatorCredentialRepository(db, frozen_clock(CLOCK)).register(
            OP_ID, OP_TOKEN, "Modern Operator")
        before = _stored(db)
        assert before.startswith("pbkdf2$sha256$")
        assert OperatorCredentialRepository(db).upgrade_legacy_hash(
            OP_ID, OP_TOKEN) is False
        assert _stored(db) == before

    def test_upgrade_revoked_row_is_a_noop(self, db):
        legacy = _seed_legacy(db)
        db.execute(
            "UPDATE operator_credentials SET revoked_at = ? "
            "WHERE operator_id = ?", (CLOCK, OP_ID))
        assert OperatorCredentialRepository(db).upgrade_legacy_hash(
            OP_ID, OP_TOKEN) is False
        assert _stored(db) == legacy

    def test_upgrade_writes_no_journal_event(self, db):
        _seed_legacy(db)
        before = _event_count(db)
        assert OperatorCredentialRepository(db).upgrade_legacy_hash(
            OP_ID, OP_TOKEN) is True
        assert _event_count(db) == before


def _seed_gate_db(tmp_path):
    """Project p1 + a parked HUMAN_GATE; returns (db_path, cfg_path, gate_id)."""
    from hermes.core.intents import Intent, IntentKind
    from hermes.research.gateway import apply_intent

    db_path = tmp_path / "hermes.db"
    conn = connect(str(db_path))
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    res = apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        payload={
            "task_id": "gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "k1",
            "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    gate_id = res.entity_id
    conn.close()
    cfg_path = tmp_path / "hermes.toml"
    cfg_path.write_text("[sqlite]" + chr(10) + "database_path = "
                        + chr(34) + db_path.as_posix() + chr(34) + chr(10))
    return str(db_path), str(cfg_path), gate_id


class TestCliUpgradeOnSuccess:
    def test_cli_success_upgrades_legacy_hash(self, tmp_path, capsys):
        from hermes.cli import main

        db_path, cfg_path, gate_id = _seed_gate_db(tmp_path)
        assert main(["--config", cfg_path, "run", "p1", "--ticks", "3"]) == 0
        conn = connect(db_path)
        try:
            _seed_legacy(conn)
        finally:
            conn.close()

        rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
                   "--verdict", "APPROVED", "--operator", OP_ID,
                   "--token", OP_TOKEN])
        captured = capsys.readouterr()
        assert rc == 0, captured.out
        assert "resolved: APPROVED" in captured.out
        assert OP_TOKEN not in captured.out

        conn = connect(db_path)
        try:
            stored = _stored(conn)
            assert stored.startswith("pbkdf2$sha256$"), (
                "a successful verify must upgrade the legacy row")
            assert OperatorCredentialRepository(conn).verify(
                OP_ID, OP_TOKEN) is True
        finally:
            conn.close()

    def test_cli_failed_auth_does_not_upgrade(self, tmp_path, capsys):
        from hermes.cli import main

        db_path, cfg_path, gate_id = _seed_gate_db(tmp_path)
        assert main(["--config", cfg_path, "run", "p1", "--ticks", "3"]) == 0
        conn = connect(db_path)
        try:
            legacy = _seed_legacy(conn)
        finally:
            conn.close()

        rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
                   "--verdict", "APPROVED", "--operator", OP_ID,
                   "--token", "wrong-token-123456"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "OPERATOR" in captured.out

        conn = connect(db_path)
        try:
            assert _stored(conn) == legacy, (
                "a failed auth must never re-hash the credential")
        finally:
            conn.close()

        # CRED-1 C — the SAME credential still works afterwards, and the
        # successful retry (only it) is the upgrade moment.
        rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
                   "--verdict", "APPROVED", "--operator", OP_ID,
                   "--token", OP_TOKEN])
        assert rc == 0, capsys.readouterr().out
        conn = connect(db_path)
        try:
            assert _stored(conn).startswith("pbkdf2$sha256$"), (
                "the successful retry upgrades the legacy row")
        finally:
            conn.close()
