"""CRED-1 (GAP-1 P2-13): ``--token-stdin`` — the operator token can be
fed on stdin instead of an argv value (which leaks through process
inspection / shell history). One line, one token; the two input channels
are mutually exclusive; the token is never echoed.

Both operator surfaces accept it (``operator register`` and
``gate resolve``). There is deliberately NO environment-variable channel.
"""
from __future__ import annotations

import io
import sys

import pytest

from hermes.cli import main

OP_NAME = "op-stdin"
OP_TOKEN = "stdin-token-123456"


def _seed_gate_db(tmp_path):
    """Project p1 + a parked HUMAN_GATE; returns (db_path, cfg_path, gate_id).

    (Same shape as ``tests/test_cli.py::_seed_gate_db``.)
    """
    from hermes.core.intents import Intent, IntentKind
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ProjectRepository
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


def test_operator_register_reads_token_from_stdin(tmp_path, capsys,
                                                  monkeypatch):
    db_path, cfg_path, _gate_id = _seed_gate_db(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(OP_TOKEN + "\n"))

    rc = main(["--config", cfg_path, "operator", "register", OP_NAME,
               "--token-stdin", "--name", "Stdin Operator"])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"Registered operator {OP_NAME}" in out
    assert OP_TOKEN not in out, "the token must never be echoed"

    from hermes.persistence.database import connect
    from hermes.persistence.repositories import OperatorCredentialRepository
    conn = connect(db_path)
    try:
        assert OperatorCredentialRepository(conn).verify(
            OP_NAME, OP_TOKEN) is True
    finally:
        conn.close()


def test_gate_resolve_reads_token_from_stdin(tmp_path, capsys, monkeypatch):
    from hermes.core.task_status import TaskStatus
    from hermes.persistence.database import connect
    from hermes.persistence.repositories import TaskRepository

    db_path, cfg_path, gate_id = _seed_gate_db(tmp_path)
    assert main(["--config", cfg_path, "run", "p1", "--ticks", "3"]) == 0
    assert main(["--config", cfg_path, "operator", "register", OP_NAME,
                 "--token", OP_TOKEN, "--name", "Stdin Operator"]) == 0
    capsys.readouterr()

    monkeypatch.setattr(sys, "stdin", io.StringIO(OP_TOKEN + "\n"))
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", OP_NAME,
               "--token-stdin"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "resolved: APPROVED" in out
    assert OP_TOKEN not in out, "the token must never be echoed"

    conn = connect(db_path)
    try:
        assert TaskRepository(conn).get_status(gate_id) is TaskStatus.SUCCEEDED
    finally:
        conn.close()


def test_token_channels_are_mutually_exclusive(tmp_path, capsys):
    _db_path, cfg_path, gate_id = _seed_gate_db(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["--config", cfg_path, "gate", "resolve", gate_id,
              "--verdict", "APPROVED", "--operator", OP_NAME,
              "--token", OP_TOKEN, "--token-stdin"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "not allowed with" in err or "mutually exclusive" in err


def test_empty_stdin_token_is_refused(tmp_path, capsys, monkeypatch):
    """An empty line on stdin is an empty token — refused fail-closed with
    OPERATOR, never treated as 'no credential needed'."""
    _db_path, cfg_path, gate_id = _seed_gate_db(tmp_path)
    assert main(["--config", cfg_path, "run", "p1", "--ticks", "3"]) == 0
    assert main(["--config", cfg_path, "operator", "register", OP_NAME,
                 "--token", OP_TOKEN, "--name", "Stdin Operator"]) == 0
    capsys.readouterr()

    monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", OP_NAME,
               "--token-stdin"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "OPERATOR" in out
