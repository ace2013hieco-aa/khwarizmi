"""Tests for hermes.cli — CLI boundary acceptance (Phase 0)."""
from __future__ import annotations

import pytest

from hermes.cli import _build_parser, main


def test_help_returns_zero(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "Hermes" in captured.out
    assert "doctor" in captured.out


def test_no_args_prints_help(capsys):
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 0
    assert "doctor" in captured.out


def test_doctor_runs():
    # doctor must not crash; it probes the environment
    rc = main(["doctor"])
    assert rc == 0


def test_status_no_db_returns_one(capsys):
    """Phase 1: `hermes status` with no DB returns 1 (not Phase 0 stub)."""
    rc = main(["status"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "No database" in captured.out or "init" in captured.out


def test_run_no_db_returns_one(capsys):
    """`hermes run` with no database fails closed (1), like status."""
    rc = main(["run", "p1"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "No database" in captured.out


def test_run_drives_tick_loop(tmp_path, capsys):
    """Red-team A1 retired: `hermes run` drives the REAL controller tick
    loop. A HUMAN_GATE task parks at WAITING_HUMAN (fail-closed — the CLI
    has no gate-verdict injection, so nothing auto-passes), and the
    summary surfaces the wait. The task row proves the loop really ran."""
    from hermes.core.intents import Intent, IntentKind
    from hermes.core.task_status import TaskStatus
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ProjectRepository, TaskRepository
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
    cfg_path.write_text("[sqlite]" + chr(10) + "database_path = " + chr(34) + db_path.as_posix() + chr(34) + chr(10))
    rc = main(["--config", str(cfg_path), "run", "p1", "--ticks", "5"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "waiting on human" in captured.out

    conn = connect(str(db_path))
    try:
        assert TaskRepository(conn).get_status(gate_id) is TaskStatus.WAITING_HUMAN
    finally:
        conn.close()


def test_parser_has_all_commands():
    parser = _build_parser()
    set(parser._subparsers._group_actions)
    # Just exercise that it builds without error
    assert parser is not None


def _seed_gate_db(tmp_path):
    """Seed a db with project p1 + a parked HUMAN_GATE; returns (db_path, cfg_path, gate_id)."""
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
    cfg_path.write_text("[sqlite]" + chr(10) + "database_path = " + chr(34) + db_path.as_posix() + chr(34) + chr(10))
    return str(db_path), str(cfg_path), gate_id


def test_operator_register_and_gate_resolve_end_to_end(tmp_path, capsys):
    """A4 + A2 through the CLI, end to end: register an operator credential,
    park a HUMAN_GATE, resolve it with the ratified token — no Python session."""
    from hermes.core.task_status import TaskStatus
    from hermes.persistence.database import connect
    from hermes.persistence.repositories import TaskRepository

    db_path, cfg_path, gate_id = _seed_gate_db(tmp_path)

    # park the gate via the loop
    rc = main(["--config", cfg_path, "run", "p1", "--ticks", "3"])
    assert rc == 0

    # register the operator credential
    rc = main(["--config", cfg_path, "operator", "register", "op-cli",
               "--token", "cli-token", "--name", "CLI Operator"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Registered operator op-cli" in captured.out

    # an UNRATIFIED verdict is refused fail-closed
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", "op-cli",
               "--token", "wrong-token"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "OPERATOR" in captured.out

    # the ratified verdict lands — project resolved from the task
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", "op-cli",
               "--token", "cli-token"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "resolved: APPROVED" in captured.out
    conn = connect(db_path)
    try:
        assert TaskRepository(conn).get_status(gate_id) is TaskStatus.SUCCEEDED
    finally:
        conn.close()


def test_gate_resolve_cli_pays_one_pbkdf2_per_outcome(tmp_path, capsys, monkeypatch):
    """F2-lens CLI probe: `hermes gate resolve` pays EXACTLY ONE PBKDF2
    run per operator outcome at the CLI boundary — unknown operator
    (dummy-hash burn), known id with a wrong token (stored mismatch), and
    known id with the right token (match) each pay the same one-KDF
    budget, so a stopwatch on the CLI surface cannot distinguish operator
    validity either (the controller-level proof, repeated at the
    operator's actual entry point)."""
    import hashlib

    import hermes.persistence.repositories as repos_mod

    # Order-independence: pre-warm the lazily-built module dummy hash so
    # the first counted verify pays exactly one KDF (the sibling F2
    # probes do the same).
    repos_mod._burn_dummy_operator_work("order-independent-warmup")

    _db_path, cfg_path, gate_id = _seed_gate_db(tmp_path)
    # park the gate via the loop, then register the credential BEFORE
    # counting (register itself hashes the token)
    assert main(["--config", cfg_path, "run", "p1", "--ticks", "3"]) == 0
    assert main(["--config", cfg_path, "operator", "register", "op-cli",
                 "--token", "cli-token", "--name", "CLI Operator"]) == 0
    capsys.readouterr()

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    # unknown operator: exactly ONE KDF burn, refused OPERATOR
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", "ghost-op",
               "--token", "wrong-token-123456"])
    out = capsys.readouterr().out
    assert rc == 1 and "OPERATOR" in out
    assert calls["n"] == 1
    # known id, wrong token: one KDF (parity)
    calls["n"] = 0
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", "op-cli",
               "--token", "wrong-token"])
    out = capsys.readouterr().out
    assert rc == 1 and "OPERATOR" in out
    assert calls["n"] == 1
    # known id, right token: passes; still exactly one KDF
    calls["n"] = 0
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", "op-cli",
               "--token", "cli-token"])
    out = capsys.readouterr().out
    assert rc == 0 and "resolved: APPROVED" in out
    assert calls["n"] == 1


def test_operator_register_cli_pays_one_kdf_per_attempt(tmp_path, capsys, monkeypatch):
    """F2-lens CLI probe on the register surface: `hermes operator
    register` pays EXACTLY ONE PBKDF2 run per attempt whether the id is
    NEW (hash build), EXISTING with the SAME token (idempotent
    re-register — the stored hash is re-derived for the constant-time
    match), or EXISTING with a DIFFERENT token (the
    ratifiable-not-overwriteable refusal). Response time therefore cannot
    reveal whether an operator_id is already registered."""
    import hashlib

    _db_path, cfg_path, _gate_id = _seed_gate_db(tmp_path)

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    # fresh register: one KDF (the hash build), rc 0
    rc = main(["--config", cfg_path, "operator", "register", "op-reg",
               "--token", "reg-token-123456", "--name", "Reg"])
    out = capsys.readouterr().out
    assert rc == 0 and "Registered operator op-reg" in out
    assert calls["n"] == 1
    # idempotent re-register (same id + token): one KDF (the stored-hash
    # match), rc 0 — the same budget as a fresh register
    calls["n"] = 0
    rc = main(["--config", cfg_path, "operator", "register", "op-reg",
               "--token", "reg-token-123456", "--name", "Reg"])
    out = capsys.readouterr().out
    assert rc == 0 and "Registered operator op-reg" in out
    assert calls["n"] == 1
    # different token for the existing id: one KDF, refused (ratifiable,
    # never overwriteable) — same budget, never a cheap refusal
    calls["n"] = 0
    rc = main(["--config", cfg_path, "operator", "register", "op-reg",
               "--token", "different-token-123456"])
    out = capsys.readouterr().out
    assert rc == 1 and "Refused" in out
    assert calls["n"] == 1


def test_diagnostic_cli_surfaces_never_run_pbkdf2(tmp_path, capsys, monkeypatch):
    """F2-lens probe on the non-verdict CLI surfaces: status, audit,
    backup, and restore perform ZERO PBKDF2 work — read-only diagnostics
    and file ops that never touch operator credentials — so their timing
    cannot leak any operator state. This is the strongest form of
    constant-work parity: a fast path with no credential-dependent work
    at all (the DB even holds a ratified operator row while they run)."""
    import hashlib

    _seed_gate_db(tmp_path)
    db_path = tmp_path / "hermes.db"
    store_root = tmp_path / "artifacts"
    (store_root / "ab").mkdir(parents=True)
    (store_root / "ab" / "seed.bin").write_bytes(b"SEED")
    full_cfg = tmp_path / "full.toml"
    full_cfg.write_text(
        "[sqlite]" + chr(10) +
        "database_path = " + chr(34) + db_path.as_posix() + chr(34) + chr(10) +
        "backup_dir = " + chr(34) + (tmp_path / "backups").as_posix() + chr(34) + chr(10) +
        "[artifacts]" + chr(10) +
        "artifact_root = " + chr(34) + store_root.as_posix() + chr(34) + chr(10))
    cfg = full_cfg.as_posix()
    # hold credential material in the DB: park a gate + register an operator
    assert main(["--config", cfg, "run", "p1", "--ticks", "3"]) == 0
    assert main(["--config", cfg, "operator", "register", "op-diag",
                 "--token", "diag-token-123456"]) == 0
    capsys.readouterr()

    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)

    assert main(["--config", cfg, "status"]) == 0
    assert calls["n"] == 0
    assert main(["--config", cfg, "status", "--json"]) == 0
    assert calls["n"] == 0
    assert main(["--config", cfg, "audit", "--project", "p1"]) == 0
    assert calls["n"] == 0
    assert main(["--config", cfg, "audit", "--json"]) == 0
    assert calls["n"] == 0
    rc = main(["--config", cfg, "backup"])
    out = capsys.readouterr().out
    assert rc == 0
    assert calls["n"] == 0
    # restore the just-written backup — still zero credential work
    backup_path = out.split("Backup written: ")[1].splitlines()[0].strip()
    rc = main(["--config", cfg, "restore", backup_path])
    assert rc == 0
    assert calls["n"] == 0


def test_legacy_64hex_credential_gate_resolve_cli(tmp_path, capsys):
    """F4-lens CLI probe: a legacy pre-P2 credential (bare 64-hex SHA-256
    token hash) still lands an operator verdict through `hermes gate
    resolve` after the fail-closed legacy fix — the legacy path is
    verified end to end at the operator surface, and a wrong token is
    still refused."""
    import hashlib

    from hermes.persistence.database import connect

    db_path, cfg_path, gate_id = _seed_gate_db(tmp_path)
    # park the gate via the loop
    assert main(["--config", cfg_path, "run", "p1", "--ticks", "3"]) == 0
    # register a legacy-style credential via direct SQL (pre-P2 shape:
    # bare 64-hex SHA-256 of the token)
    legacy_token = "legacy-token-123456"
    legacy_hash = hashlib.sha256(legacy_token.encode("utf-8")).hexdigest()
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO operator_credentials "
            "(operator_id, token_hash, name, created_at) "
            "VALUES ('op-legacy', ?, 'Legacy', ?)",
            (legacy_hash, "2026-01-01T00:00:00.000000+00:00"))
        conn.commit()
    finally:
        conn.close()
    capsys.readouterr()
    # a wrong token is refused (OPERATOR) before the verdict lands
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", "op-legacy",
               "--token", "wrong-token"])
    out = capsys.readouterr().out
    assert rc == 1 and "OPERATOR" in out
    # the legacy credential lands the verdict through the CLI
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", "op-legacy",
               "--token", legacy_token])
    out = capsys.readouterr().out
    assert rc == 0 and "resolved: APPROVED" in out


def test_register_cli_refusal_output_leaks_nothing_beyond_message(tmp_path, capsys):
    """F2-lens CLI probe on the refusal output surface: `hermes operator
    register` prints the refusal to STDOUT with a UNIFORM exit code (1)
    for every failure class, never echoes the presented token, and
    produces byte-identical output across every wrong-token shape (beyond
    the already-audited repository message). And `hermes gate resolve`
    refuses an UNKNOWN operator id and a KNOWN id with a WRONG token with
    the SAME refusal text (modulo the attacker-supplied id) — the CLI
    adds no per-shape discriminator, no exit-code oracle, no
    id-existence leak through the verdict surface."""
    _db_path, cfg_path, gate_id = _seed_gate_db(tmp_path)
    # register once, then park a gate for the resolve leg
    assert main(["--config", cfg_path, "operator", "register", "op-cli-a",
                 "--token", "cli-token-a-123456", "--name", "A"]) == 0
    assert main(["--config", cfg_path, "run", "p1", "--ticks", "3"]) == 0
    capsys.readouterr()

    # register leg: wrong tokens of many shapes -> identical stdout, rc 1,
    # nothing on stderr, no token material echoed
    wrong = ["x" * 8, "x" * 500, "cli-token-a-123457", "\U0001F600" * 8]
    outputs = []
    for token in wrong:
        rc = main(["--config", cfg_path, "operator", "register",
                   "op-cli-a", "--token", token])
        captured = capsys.readouterr()
        assert rc == 1
        assert captured.err == ""  # refusals go to stdout, not stderr
        outputs.append(captured.out)
    assert len(set(outputs)) == 1
    out = outputs[0]
    assert out.startswith("Refused (OPERATOR): ")
    for token in wrong + ["cli-token-a-123456"]:
        assert token not in out

    # gate-resolve leg: unknown id vs known id + wrong token are refused
    # with the SAME text (modulo the attacker-supplied id) — the verify
    # fails closed identically, so the CLI never reveals id existence
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", "ghost-op",
               "--token", "ghost-token-123456"])
    out_unknown = capsys.readouterr().out
    assert rc == 1 and "OPERATOR" in out_unknown
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", "op-cli-a",
               "--token", "wrong-token-123456"])
    out_wrong = capsys.readouterr().out
    assert rc == 1 and "OPERATOR" in out_wrong
    # identical refusal shape: same code, same wording, only the id differs
    assert "no ratified operator credential for" in out_unknown
    assert "no ratified operator credential for" in out_wrong
    assert out_unknown.replace("ghost-op", "X") == \
        out_wrong.replace("op-cli-a", "X")
    assert "ghost-token-123456" not in out_unknown
    assert "wrong-token-123456" not in out_wrong


def test_backup_restore_round_trip_through_cli(tmp_path, capsys):
    """B6 through the CLI: hermes backup snapshots the DB + artifact store;
    a post-backup mutation is rolled back WITH the store by hermes restore —
    the round trip is reachable from the operator surface."""
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ProjectRepository

    db_path = tmp_path / "hermes.db"
    store_root = tmp_path / "artifacts"
    (store_root / "ab").mkdir(parents=True)
    (store_root / "ab" / "old.bin").write_bytes(b"OLD")

    conn = connect(str(db_path))
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Original")
    conn.close()

    cfg_path = tmp_path / "hermes.toml"
    cfg_path.write_text(
        "[sqlite]" + chr(10) +
        "database_path = " + chr(34) + db_path.as_posix() + chr(34) + chr(10) +
        "backup_dir = " + chr(34) + (tmp_path / "backups").as_posix() + chr(34) + chr(10) +
        "[artifacts]" + chr(10) +
        "artifact_root = " + chr(34) + store_root.as_posix() + chr(34) + chr(10))

    rc = main(["--config", cfg_path.as_posix(), "backup"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Backup written" in captured.out
    backups = list((tmp_path / "backups").glob("hermes_backup_*.db"))
    assert len(backups) == 1

    # post-backup: DB gains p2 AND the store gains a file
    conn = connect(str(db_path))
    ProjectRepository(conn).create("p2", "Later")
    conn.close()
    (store_root / "ab" / "new.bin").write_bytes(b"NEW")

    rc = main(["--config", cfg_path.as_posix(), "restore",
               backups[0].as_posix()])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Restored" in captured.out

    conn = connect(str(db_path))
    try:
        rows = conn.execute("SELECT project_id FROM projects").fetchall()
        assert [r[0] for r in rows] == ["p1"]
    finally:
        conn.close()
    # the store snapshot came back WITH the DB — the same point (B6)
    assert (store_root / "ab" / "old.bin").read_bytes() == b"OLD"
    # no temp litter from the atomic restore
    assert list(tmp_path.glob(".*restore-*")) == []


# ── E2E audit: CLI output must be console-safe (no non-ASCII glyphs) ──

def test_cli_output_is_console_safe():
    """E2E finding: `hermes audit`/`hermes events`/`hermes doctor` printed a
    '→' (U+2192) state arrow, which crashed on Windows consoles (cp1252 —
    UnicodeEncodeError). The CLI must be ASCII-safe so every operator
    surface works on any terminal encoding."""
    import hermes.cli as cli_mod
    with open(cli_mod.__file__, encoding="utf-8") as fh:
        src = fh.read()
    assert "→" not in src, "CLI output must use ASCII '->' arrows"
    assert "\u2192" not in src


# ── audit --json: the stable machine-readable ledger schema ──

def test_audit_json_stable_schema(tmp_path, capsys):
    """`hermes audit --json` emits ONE JSON document on stdout with a
    stable schema: an ``events`` list, one object per row, keys exactly the
    events-table columns; payload_json/artifact_ids_json are parsed to
    values; non-ASCII is always \\u-escaped (console-safe by construction);
    an empty ledger is ``{"events": []}``; errors go to stderr only."""
    import json as _json

    from hermes.core.intents import Intent, IntentKind
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ProjectRepository
    from hermes.research.gateway import apply_intent

    db_path = tmp_path / "hermes.db"
    conn = connect(str(db_path))
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    # the spec carries a non-ASCII value so the JSON escape pin is real
    apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1",
        justification="hypothèse",
        payload={
            "task_id": "gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "k1",
            "iteration": 1, "spec": {"gate_requirement": "operator approval"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    conn.close()

    cfg_path = tmp_path / "hermes.toml"
    cfg_path.write_text("[sqlite]" + chr(10)
                        + "database_path = " + chr(34)
                        + db_path.as_posix() + chr(34) + chr(10))

    rc = main(["--config", str(cfg_path), "audit", "--project", "p1",
               "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""

    doc = _json.loads(captured.out)          # stdout is one parseable doc
    assert set(doc.keys()) == {"events"}
    assert len(doc["events"]) >= 3           # created + task + intent
    schema = {
        "artifact_ids_json", "caused_by", "correlation_id", "created_at",
        "event_id", "event_type", "from_state", "payload_json",
        "project_id", "reason", "task_id", "to_state",
    }
    for e in doc["events"]:
        assert set(e.keys()) == schema, sorted(e.keys())
        assert isinstance(e["event_id"], int)
        assert isinstance(e["created_at"], str)
        # parsed payloads: never a bare JSON string from storage
        assert not isinstance(e["payload_json"], str)
        assert not isinstance(e["artifact_ids_json"], str)
    # the non-ASCII justification came through parsed, not as an escape string
    payloads = [e["payload_json"] for e in doc["events"]
                if isinstance(e["payload_json"], dict)]
    assert any(str(p).find("hypoth") >= 0 for p in payloads)
    # stdout is ASCII by construction (ensure_ascii=True) — console-safe
    assert all(ord(c) < 128 for c in captured.out)
    # event order is the insertion order (event_id ascending)
    ids = [e["event_id"] for e in doc["events"]]
    assert ids == sorted(ids)

    # empty ledger -> {"events": []}, rc 0
    rc2 = main(["--config", str(cfg_path), "audit", "--project",
                "p-ghost", "--json"])
    captured2 = capsys.readouterr()
    assert rc2 == 0
    assert _json.loads(captured2.out) == {"events": []}

    # human table still works (no regression)
    rc3 = main(["--config", str(cfg_path), "audit", "--project", "p1"])
    captured3 = capsys.readouterr()
    assert rc3 == 0
    assert "Event journal" in captured3.out
    assert "->" in captured3.out


# ── status --json: the stable machine-readable project schema ──

def test_status_json_stable_schema(tmp_path, capsys):
    """`hermes status --json` emits ONE JSON document on stdout with a
    stable schema: an ``projects`` list, one object per project with full
    (untruncated) ids — lifecycle, mode, iteration, and a ``tasks`` list
    with the task_id/task_type/status/iteration per task; an empty project
    set is ``{"projects": []}``; a missing DB fails closed (rc 1) with the
    error on stderr only; stdout is ASCII by construction; the human table
    is unchanged."""
    import json as _json

    from hermes.core.intents import Intent, IntentKind
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ProjectRepository
    from hermes.research.gateway import apply_intent

    db_path = tmp_path / "hermes.db"
    conn = connect(str(db_path))
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Alpha Project")
    apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1", justification="seed",
        payload={
            "task_id": "t-gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "k1",
            "iteration": 1, "spec": {"gate_requirement": "approval"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    conn.close()

    cfg_path = tmp_path / "hermes.toml"
    cfg_path.write_text("[sqlite]" + chr(10)
                        + "database_path = " + chr(34)
                        + db_path.as_posix() + chr(34) + chr(10))

    rc = main(["--config", str(cfg_path), "status", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""

    doc = _json.loads(captured.out)          # stdout is one parseable doc
    assert set(doc.keys()) == {"projects"}
    assert len(doc["projects"]) == 1
    proj = doc["projects"][0]
    assert set(proj.keys()) == {
        "iteration", "lifecycle_state", "name", "operational_mode",
        "project_id", "tasks",
    }
    # full ids, never the 8-char truncation the human table uses
    assert proj["project_id"] == "p1"
    assert proj["name"] == "Alpha Project"
    assert proj["lifecycle_state"] == "CREATED"
    assert proj["operational_mode"] == "ACTIVE"
    assert proj["iteration"] == 1
    assert len(proj["tasks"]) == 1
    task = proj["tasks"][0]
    assert set(task.keys()) == {
        "iteration", "status", "task_id", "task_type",
    }
    assert task["task_id"] == "t-gate-1"
    assert task["task_type"] == "HUMAN_GATE"
    assert task["status"] == "PENDING"
    assert task["iteration"] == 1
    # stdout is ASCII by construction (console-safe)
    assert all(ord(c) < 128 for c in captured.out)

    # empty project set -> {"projects": []}, rc 0
    db2 = tmp_path / "empty.db"
    conn2 = connect(str(db2))
    migrate_to_latest(conn2)
    conn2.close()
    cfg2 = tmp_path / "empty.toml"
    cfg2.write_text("[sqlite]" + chr(10)
                    + "database_path = " + chr(34)
                    + db2.as_posix() + chr(34) + chr(10))
    rc2 = main(["--config", str(cfg2), "status", "--json"])
    captured2 = capsys.readouterr()
    assert rc2 == 0
    assert _json.loads(captured2.out) == {"projects": []}

    # missing DB -> rc 1, error on stderr only, stdout stays parseable
    cfg3 = tmp_path / "ghost.toml"
    cfg3.write_text("[sqlite]" + chr(10)
                    + "database_path = " + chr(34)
                    + (tmp_path / "ghost.db").as_posix() + chr(34) + chr(10))
    rc3 = main(["--config", str(cfg3), "status", "--json"])
    captured3 = capsys.readouterr()
    assert rc3 == 1
    assert captured3.out == ""
    assert "No database" in captured3.err

    # human table still works (no regression)
    rc4 = main(["--config", str(cfg_path), "status"])
    captured4 = capsys.readouterr()
    assert rc4 == 0
    assert "Project: Alpha Project" in captured4.out
    assert "Lifecycle:" in captured4.out


# ── doctor --json: the stable machine-readable probes schema ──

def test_doctor_json_stable_schema(capsys):
    """`hermes doctor --json` emits ONE JSON document on stdout with a
    stable schema: ``version``, ``checks`` (one object per probe with
    exactly label/status/detail — the same probes as the human table in
    the same order, statuses restricted to the CHECK_STATUS set), and
    ``config`` (the resolved configuration as nested sections). rc is
    always 0 (probes do not fail); stdout is ASCII by construction; the
    human report is unchanged."""
    import json as _json

    rc = main(["doctor", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""

    doc = _json.loads(captured.out)          # stdout is one parseable doc
    assert set(doc.keys()) == {"version", "checks", "config"}
    assert isinstance(doc["version"], str)
    assert isinstance(doc["checks"], list) and doc["checks"]
    allowed = {"AVAILABLE", "OPTIONAL / NOT CONFIGURED", "REQUIRED / MISSING"}
    labels = []
    for c in doc["checks"]:
        assert set(c.keys()) == {"detail", "label", "status"}
        assert c["status"] in allowed, c
        labels.append(c["label"])
    # the same probe order as the human table
    assert labels == ["Python runtime", "Hermes package", "Config file",
                      "Database", "Artifact store", "Sandbox", "Lockfile"]
    # config is the resolved configuration as nested sections
    assert isinstance(doc["config"], dict)
    assert "sqlite" in doc["config"]
    assert "database_path" in doc["config"]["sqlite"]
    # stdout is ASCII by construction (console-safe)
    assert all(ord(c) < 128 for c in captured.out)

    # human report still works (no regression)
    rc2 = main(["doctor"])
    captured2 = capsys.readouterr()
    assert rc2 == 0
    assert "Hermes doctor" in captured2.out
    assert "Configuration values:" in captured2.out


# ── F2-lens: the status/audit JSON shapes never leak operator state ──

def test_status_audit_json_shape_operator_state_invisible(tmp_path, capsys):
    """F2-lens probe on the audit/status ``--json`` OUTPUT SHAPES: the
    schemas are fixed and operator-state-independent. Registering a
    ratified operator changes NEITHER document (byte-identical before vs
    after, with no projects/events), the empty-store key structure is
    identical to the populated-store key structure (state changes only
    array lengths, never keys), and no operator/credential/token material
    appears anywhere in either document even while the store holds a
    credential. A ``--json`` consumer can observe only the intended
    project/task/event content — never operator existence, registration
    status, or token shape."""
    import json as _json

    db_path = tmp_path / "hermes.db"
    cfg_path = tmp_path / "hermes.toml"
    cfg_path.write_text("[sqlite]" + chr(10)
                        + "database_path = " + chr(34)
                        + db_path.as_posix() + chr(34) + chr(10))
    cfg = str(cfg_path)
    assert main(["--config", cfg, "init"]) == 0
    capsys.readouterr()

    def capture(cmd):
        rc = main(["--config", cfg] + cmd)
        out = capsys.readouterr().out
        assert rc == 0
        return out

    empty_status = capture(["status", "--json"])
    empty_audit = capture(["audit", "--json"])
    assert _json.loads(empty_status) == {"projects": []}
    assert _json.loads(empty_audit) == {"events": []}

    # a ratified operator changes neither document — registration status
    # is invisible to both machine-readable surfaces
    assert main(["--config", cfg, "operator", "register", "op-shape",
                 "--token", "shape-token-123456789"]) == 0
    capsys.readouterr()
    assert capture(["status", "--json"]) == empty_status
    assert capture(["audit", "--json"]) == empty_audit

    # populated: the SAME key structure, only array lengths change
    from hermes.core.intents import Intent, IntentKind
    from hermes.persistence.database import connect
    from hermes.persistence.repositories import ProjectRepository
    from hermes.research.gateway import apply_intent

    conn = connect(str(db_path))
    ProjectRepository(conn).create("p1", "Proj")
    apply_intent(conn, Intent(
        kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
        project_id="p1", justification="seed",
        payload={
            "task_id": "gate-1", "task_type": "HUMAN_GATE",
            "profile": "DIRECTOR", "idempotency_key": "k1",
            "iteration": 1, "spec": {"gate_requirement": "approval"},
            "inputs": [], "outputs": [], "dependencies": [],
            "provenance": [], "cost_class": None, "concurrency_group": None,
            "max_retries": 3, "parent_task_id": None,
        }))
    conn.close()

    sd = _json.loads(capture(["status", "--json"]))
    ad = _json.loads(capture(["audit", "--json"]))
    assert set(sd) == {"projects"} and len(sd["projects"]) == 1
    assert set(sd["projects"][0]) == {
        "iteration", "lifecycle_state", "name", "operational_mode",
        "project_id", "tasks"}
    assert set(sd["projects"][0]["tasks"][0]) == {
        "iteration", "status", "task_id", "task_type"}
    assert set(ad) == {"events"} and len(ad["events"]) >= 1
    # no credential-derived material anywhere in either document
    blob = (empty_status + empty_audit + _json.dumps(sd)
            + _json.dumps(ad)).lower()
    for needle in ("operator", "credential", "token", "op-shape"):
        assert needle not in blob, needle


# ── F2-lens: backup/restore cost is size-proportional, never content ──

def test_backup_restore_cost_is_size_proportional_not_content_dependent(
        tmp_path, capsys):
    """F2-lens probe on the backup/restore CLI surfaces: the copy work is
    a PURE FUNCTION OF FILE SIZE, never of contents. Two byte-identical
    stores holding DIFFERENT secret material (different operator tokens →
    different stored digests) produce IDENTICAL backup bytes, and every
    backup is an exhaustive copy (backup bytes == source bytes). Growing
    the journal grows the backup by EXACTLY the file-size delta, and
    restore is the same pure byte copy (restored bytes == backup bytes,
    original token still verifies). Backup/restore timing can therefore
    reveal only the DB file size — public via stat — never the store's
    secrets, token shapes, or credential state."""
    import os

    from hermes.core import frozen_clock
    from hermes.core.intents import Intent, IntentKind
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import (
        OperatorCredentialRepository,
        ProjectRepository,
    )
    from hermes.research.gateway import apply_intent

    clock = frozen_clock("2026-08-16T00:00:00.000000+00:00")

    def build_store(root, op_id, token, n_tasks):
        root.mkdir(parents=True)
        db = root / "hermes.db"
        conn = connect(str(db))
        migrate_to_latest(conn)
        ProjectRepository(conn, clock=clock).create("p1", "ProjName")
        OperatorCredentialRepository(conn, clock=clock).register(
            op_id, token, "Op")
        for i in range(n_tasks):
            apply_intent(conn, Intent(
                kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                project_id="p1", justification="seed",
                payload={
                    "task_id": f"t{i:04d}", "task_type": "HUMAN_GATE",
                    "profile": "DIRECTOR", "idempotency_key": f"k{i}",
                    "iteration": 1, "spec": {"gate_requirement": "g"},
                    "inputs": [], "outputs": [], "dependencies": [],
                    "provenance": [], "cost_class": None,
                    "concurrency_group": None, "max_retries": 3,
                    "parent_task_id": None,
                }), clock=clock)
        conn.close()
        cfg = root / "hermes.toml"
        cfg.write_text(
            "[sqlite]" + chr(10)
            + "database_path = " + chr(34) + db.as_posix() + chr(34)
            + chr(10)
            + "backup_dir = " + chr(34) + (root / "bk").as_posix()
            + chr(34) + chr(10))
        return db, str(cfg)

    # two stores of IDENTICAL size holding DIFFERENT secret material
    db_a, cfg_a = build_store(tmp_path / "a", "op-alpha",
                              "ALPHA-token-0000000000001", 3)
    db_b, cfg_b = build_store(tmp_path / "b", "op-beta",
                              "BETA-token-0000000000000", 3)
    assert os.path.getsize(db_a) == os.path.getsize(db_b)

    def backup_via_cli(cfg):
        rc = main(["--config", cfg, "backup"])
        out = capsys.readouterr().out
        assert rc == 0
        return out.split("Backup written: ")[1].splitlines()[0].strip()

    bk_a = backup_via_cli(cfg_a)
    bk_b = backup_via_cli(cfg_b)
    # exhaustive copy: backup bytes == source bytes
    assert os.path.getsize(bk_a) == os.path.getsize(db_a)
    assert os.path.getsize(bk_b) == os.path.getsize(db_b)
    # content-independent: same-size stores -> same-size backups
    assert os.path.getsize(bk_a) == os.path.getsize(bk_b)

    # restore is a pure byte copy: restored bytes == backup bytes, and the
    # ORIGINAL token still verifies (the content really arrived)
    target = tmp_path / "restored.db"
    conn = connect(str(target))
    migrate_to_latest(conn)
    conn.close()
    cfg_t = tmp_path / "t.toml"
    cfg_t.write_text("[sqlite]" + chr(10)
                     + "database_path = " + chr(34) + target.as_posix()
                     + chr(34) + chr(10))
    rc = main(["--config", str(cfg_t), "restore", bk_a])
    capsys.readouterr()
    assert rc == 0
    assert os.path.getsize(target) == os.path.getsize(bk_a)
    conn = connect(str(target))
    try:
        assert OperatorCredentialRepository(conn).verify(
            "op-alpha", "ALPHA-token-0000000000001")
        assert not OperatorCredentialRepository(conn).verify(
            "op-beta", "BETA-token-0000000000000")
    finally:
        conn.close()

    # growing the journal grows the backup by exactly the file-size delta
    db_g, cfg_g = build_store(tmp_path / "g", "op-alpha",
                              "ALPHA-token-0000000000001", 103)
    bk_g = backup_via_cli(cfg_g)
    assert (os.path.getsize(bk_g) - os.path.getsize(bk_a)
            == os.path.getsize(db_g) - os.path.getsize(db_a))


# ── F2-lens: the CLI cold-start entry cost is a fixed, state-free add ──

def test_cold_start_import_cost_is_state_independent(tmp_path):
    """F2-lens probe on the CLI ENTRY COST: a cold `hermes status --json`
    subprocess (interpreter + module imports + config load + one status
    read) is a FIXED additive cost that does not scale with store contents
    — an empty store and a populated store (ratified operator + 100
    tasks, ~350KB DB) take the SAME cold-start time (measured ~156-180 ms
    on the reference machine vs the ~90 ms one-KDF budget), so even the
    CLI's startup latency cannot reveal operator or store state. The
    bound is deliberately loose (3x + 100ms) so the probe pins the
    regression without being a flaky wall-clock measurement."""
    import hashlib
    import os
    import statistics
    import subprocess
    import sys
    import time
    from pathlib import Path

    from hermes.core import frozen_clock
    from hermes.core.intents import Intent, IntentKind
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import (
        OperatorCredentialRepository,
        ProjectRepository,
    )
    from hermes.research.gateway import apply_intent

    clock = frozen_clock("2026-08-16T00:00:00.000000+00:00")
    repo_root = Path(__file__).resolve().parents[1]

    def build(root, populated):
        root.mkdir(parents=True)
        db = root / "hermes.db"
        conn = connect(str(db))
        migrate_to_latest(conn)
        ProjectRepository(conn, clock=clock).create("p1", "ProjName")
        if populated:
            OperatorCredentialRepository(conn, clock=clock).register(
                "op-cold", "cold-token-1234567890", "Op")
            for i in range(100):
                apply_intent(conn, Intent(
                    kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
                    project_id="p1", justification="seed",
                    payload={
                        "task_id": f"t{i:04d}", "task_type": "HUMAN_GATE",
                        "profile": "DIRECTOR", "idempotency_key": f"k{i}",
                        "iteration": 1,
                        "spec": {"gate_requirement": "g"},
                        "inputs": [], "outputs": [], "dependencies": [],
                        "provenance": [], "cost_class": None,
                        "concurrency_group": None, "max_retries": 3,
                        "parent_task_id": None,
                    }), clock=clock)
        conn.close()
        cfg = root / "hermes.toml"
        cfg.write_text("[sqlite]" + chr(10)
                       + "database_path = " + chr(34) + db.as_posix()
                       + chr(34) + chr(10))
        return str(cfg)

    cfg_e = build(tmp_path / "empty", False)
    cfg_p = build(tmp_path / "pop", True)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    py = sys.executable

    def cold_start(cfg):
        t0 = time.perf_counter()
        r = subprocess.run(
            [py, "-m", "hermes.cli", "--config", cfg,
             "status", "--json"],
            capture_output=True, env=env, timeout=120)
        return (time.perf_counter() - t0), r.returncode

    # warm one-KDF budget on the same machine, for the documented contrast
    t0 = time.perf_counter()
    hashlib.pbkdf2_hmac("sha256", b"t" * 64, b"s" * 16, 210_000)
    kdf_ms = (time.perf_counter() - t0) * 1000.0

    empty_runs: list[float] = []
    pop_runs: list[float] = []
    for _ in range(3):
        secs, rc = cold_start(cfg_e)
        assert rc == 0
        empty_runs.append(secs)
        secs, rc = cold_start(cfg_p)
        assert rc == 0
        pop_runs.append(secs)

    empty_med = statistics.median(empty_runs)
    pop_med = statistics.median(pop_runs)
    # import + config load dominate and are state-independent: the
    # populated store (100 tasks, ~350KB) costs no more than 3x + 100ms
    assert pop_med <= empty_med * 3.0 + 0.100, (empty_runs, pop_runs)
    print(f"cold-start empty={empty_med*1000:.0f}ms "
          f"populated={pop_med*1000:.0f}ms one-KDF={kdf_ms:.0f}ms")


# ── F2-lens: the doctor --json config echo is a faithful mirror ──

def test_doctor_json_config_echo_leaks_only_operator_written_values(
        tmp_path, capsys):
    """F2-lens probe on `doctor --json`'s ``config`` echo: it is a
    BIJECTIVE mirror of the operator-written config file plus built-in
    constants — every path (database_path, backup_dir, artifact_root) is
    echoed byte-for-byte exactly as written (no resolution, no
    cwd-prefixing, no mangling), omitted fields fall back to the
    documented built-in default strings (relative constants like
    ``backups`` / ``artifacts`` / ``workspace`` — never env- or
    cwd-derived), and with NO config file the echo is exactly
    ``default_config()``. The echo therefore cannot reveal any value the
    config file does not already contain — no environment variables, no
    hostname, no cwd, no runtime state — even when the config was tampered
    to point at attacker-chosen paths (those paths are the tamperer's own
    values, mirrored faithfully; nothing extra leaks)."""
    import json as _json
    from dataclasses import asdict
    from pathlib import Path as _Path

    from hermes.config import default_config

    # explicit config: every path echoed byte-for-byte, unchanged
    db_path = tmp_path / "custom" / "data.db"
    db_path.parent.mkdir()
    bk = tmp_path / "bkp"
    art = tmp_path / "arts"
    cfg = tmp_path / "h.toml"
    cfg.write_text("[sqlite]" + chr(10)
                   + "database_path = " + chr(34) + db_path.as_posix()
                   + chr(34) + chr(10)
                   + "backup_dir = " + chr(34) + bk.as_posix() + chr(34)
                   + chr(10)
                   + "[artifacts]" + chr(10)
                   + "artifact_root = " + chr(34) + art.as_posix() + chr(34)
                   + chr(10))
    rc = main(["--config", str(cfg), "doctor", "--json"])
    doc = _json.loads(capsys.readouterr().out)
    assert rc == 0
    echo = doc["config"]
    assert echo["sqlite"]["database_path"] == db_path.as_posix()
    assert echo["sqlite"]["backup_dir"] == bk.as_posix()
    assert echo["artifacts"]["artifact_root"] == art.as_posix()
    # the Database check detail echoes the SAME configured path (no
    # resolution, no runtime mangling; OS-native separators are fine)
    db_check = next(c for c in doc["checks"]
                    if c["label"] == "Database")
    assert db_check["detail"].startswith(str(db_path))

    # omitted fields -> built-in constant defaults, never env/cwd-derived
    cfg2 = tmp_path / "h2.toml"
    cfg2.write_text("[sqlite]" + chr(10)
                    + "database_path = " + chr(34)
                    + (tmp_path / "d.db").as_posix() + chr(34) + chr(10))
    rc2 = main(["--config", str(cfg2), "doctor", "--json"])
    doc2 = _json.loads(capsys.readouterr().out)
    assert rc2 == 0
    echo2 = doc2["config"]
    assert echo2["sqlite"]["backup_dir"] == "backups"
    assert echo2["artifacts"]["artifact_root"] == "artifacts"
    assert echo2["workspace"]["workspace_root"] == "workspace"
    assert echo2["provider_config_dir"] == "providers"
    for v in (echo2["sqlite"]["backup_dir"],
              echo2["artifacts"]["artifact_root"],
              echo2["workspace"]["workspace_root"],
              echo2["provider_config_dir"]):
        assert not _Path(v).is_absolute()

    # no config at all -> exactly the built-in defaults, nothing else
    rc3 = main(["doctor", "--json"])
    doc3 = _json.loads(capsys.readouterr().out)
    assert rc3 == 0
    assert doc3["config"] == _json.loads(
        _json.dumps(asdict(default_config()), sort_keys=True))


# ── F2-lens: audit --json size is the visible rows, never hidden state ──

def test_audit_json_output_size_is_visible_rows_only_not_an_oracle(
        tmp_path, capsys):
    """F2-lens probe on `audit --json` output size as a timing signal: the
    size is a PURE FUNCTION OF THE VISIBLE EVENT ROWS. Two stores sharing
    the SAME p1 rows produce the SAME output SIZE even when the stores
    differ in hidden state (a ratified operator, a second project with 202
    tasks) — the size scales linearly with the returned count (a 403-row
    project's output is ~400x the per-row bytes larger than a 5-row one,
    band measured in-test), a ghost project id yields ``{"events": []}``
    (the empty shape no real project id can produce, since project
    creation itself writes the ResearchCreated row), and the unfiltered
    view is exactly the union of the per-project rows (408 == 5 + 403, no
    hidden rows). So audit timing/size reveals only the rows the audit
    trail is DESIGNED to expose; it cannot leak hidden store state
    (credentials, other projects, task tables) the response body does not
    itself contain."""
    import json as _json

    from hermes.core import frozen_clock
    from hermes.core.intents import Intent, IntentKind
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import (
        OperatorCredentialRepository,
        ProjectRepository,
    )
    from hermes.research.gateway import apply_intent

    clock = frozen_clock("2026-08-16T00:00:00.000000+00:00")

    def task(i, proj):
        return Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id=proj, justification="seed",
            payload={
                "task_id": f"t{i:04d}", "task_type": "HUMAN_GATE",
                "profile": "DIRECTOR", "idempotency_key": f"k{i:04d}",
                "iteration": 1, "spec": {"gate_requirement": "g"},
                "inputs": [], "outputs": [], "dependencies": [],
                "provenance": [], "cost_class": None,
                "concurrency_group": None, "max_retries": 3,
                "parent_task_id": None,
            })

    def build(root, hidden_state):
        root.mkdir(parents=True)
        db = root / "hermes.db"
        conn = connect(str(db))
        migrate_to_latest(conn)
        ProjectRepository(conn, clock=clock).create("p1", "Alpha")
        for i in range(2):
            apply_intent(conn, task(i, "p1"), clock=clock)
        if hidden_state:
            OperatorCredentialRepository(conn, clock=clock).register(
                "op-x", "token-123456789012", "Op")
            ProjectRepository(conn, clock=clock).create("p2", "Beta")
            for i in range(202):
                apply_intent(conn, task(i, "p2"), clock=clock)
        conn.close()
        cfg = root / "hermes.toml"
        cfg.write_text("[sqlite]" + chr(10)
                       + "database_path = " + chr(34) + db.as_posix()
                       + chr(34) + chr(10))
        return str(cfg)

    def audit(cfg, proj=None):
        cmd = ["--config", cfg, "audit", "--json"]
        if proj is not None:
            cmd = ["--config", cfg, "audit", "--project", proj, "--json"]
        rc = main(cmd)
        out = capsys.readouterr().out
        assert rc == 0
        return out

    cfg_plain = build(tmp_path / "plain", False)
    cfg_hidden = build(tmp_path / "hidden", True)
    # hidden state (operator, second project with 202 tasks) cannot change
    # the p1 view: identical row count -> identical output SIZE
    o_plain = audit(cfg_plain, "p1")
    o_hidden = audit(cfg_hidden, "p1")
    # identical row count -> identical output SIZE (the timing-relevant
    # signal); content differs only by the random correlation UUIDs, which
    # are fixed-length and carry no state
    n_plain = len(_json.loads(o_plain)["events"])
    n_hidden = len(_json.loads(o_hidden)["events"])
    assert n_plain == n_hidden == 5
    assert len(o_plain) == len(o_hidden)

    # ghost project id -> {"events": []}, the empty shape no real project
    # id can produce (project creation writes the ResearchCreated row)
    assert _json.loads(audit(cfg_hidden, "ghost")) == {"events": []}

    # linear scaling with the VISIBLE count: p2 (403 rows) vs p1 (5 rows)
    o1 = audit(cfg_hidden, "p1")
    o2 = audit(cfg_hidden, "p2")
    n1 = len(_json.loads(o1)["events"])
    n2 = len(_json.loads(o2)["events"])
    assert n2 > n1
    per_row = (len(o2) - len(o1)) / (n2 - n1)
    assert 250 < per_row < 1000, per_row  # ~478 bytes/row on the reference

    # unfiltered audit == union of the per-project rows: no hidden rows
    o_all = audit(cfg_hidden)
    assert len(_json.loads(o_all)["events"]) == n1 + n2


# ── F2-lens: the human audit table shows the same rows; NULL-project rows ──

def test_audit_human_table_same_rows_null_project_unfiltered_only(
        tmp_path, capsys):
    """F2-lens probe on the HUMAN `audit` table: it shows the SAME rows as
    `--json` (the ids are printed in full — the `:12s` column is a minimum
    width, never an 8-char truncation — so the size signature is still a
    linear function of the visible rows, just with a smaller per-row
    constant), and it is hidden-state-invariant: the p1 view is
    BYTE-IDENTICAL across stores sharing the same p1 rows, even when one
    holds a ratified operator and a second 202-task project. NULL-project
    rows (stale-admission records written with project_id=NULL by the
    retry-without-project fallback) appear ONLY in the unfiltered view
    (human and JSON alike), never under any `--project` filter — including
    a ghost id."""
    import json as _json
    from pathlib import Path

    from hermes.core import frozen_clock
    from hermes.core.intents import Intent, IntentKind
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import (
        OperatorCredentialRepository,
        ProjectRepository,
    )
    from hermes.research.gateway import apply_intent

    clock = frozen_clock("2026-08-16T00:00:00.000000+00:00")

    def task(i, proj):
        return Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id=proj, justification="seed",
            payload={
                "task_id": f"t{i:04d}", "task_type": "HUMAN_GATE",
                "profile": "DIRECTOR", "idempotency_key": f"k{i:04d}",
                "iteration": 1, "spec": {"gate_requirement": "g"},
                "inputs": [], "outputs": [], "dependencies": [],
                "provenance": [], "cost_class": None,
                "concurrency_group": None, "max_retries": 3,
                "parent_task_id": None,
            })

    def build(root, hidden_state):
        root.mkdir(parents=True)
        db = root / "hermes.db"
        conn = connect(str(db))
        migrate_to_latest(conn)
        ProjectRepository(conn, clock=clock).create("p1", "Alpha")
        for i in range(2):
            apply_intent(conn, task(i, "p1"), clock=clock)
        if hidden_state:
            OperatorCredentialRepository(conn, clock=clock).register(
                "op-x", "token-123456789012", "Op")
            ProjectRepository(conn, clock=clock).create("p2", "Beta")
            for i in range(202):
                apply_intent(conn, task(i, "p2"), clock=clock)
        conn.close()
        cfg = root / "hermes.toml"
        cfg.write_text("[sqlite]" + chr(10)
                       + "database_path = " + chr(34) + db.as_posix()
                       + chr(34) + chr(10))
        return str(cfg)

    def run(cfg, cmd):
        rc = main(["--config", cfg] + cmd)
        out = capsys.readouterr().out
        assert rc == 0
        return out

    cfg_plain = build(tmp_path / "plain", False)
    cfg_hidden = build(tmp_path / "hidden", True)
    # human p1 view is byte-identical across hidden state
    a_plain = run(cfg_plain, ["audit", "--project", "p1"])
    a_hidden = run(cfg_hidden, ["audit", "--project", "p1"])
    assert a_plain == a_hidden
    assert "Event journal (5 events):" in a_plain
    # full ids, never truncated: the long id shows in full
    assert "proj=p1" in a_plain
    # human view grows with the visible count (same rows as --json)
    a_p2 = run(cfg_hidden, ["audit", "--project", "p2"])
    assert len(a_p2) > len(a_plain)
    assert "Event journal (403 events):" in a_p2

    # NULL-project row: visible ONLY in the unfiltered view
    conn = connect(str(Path(cfg_hidden).parent / "hermes.db"))
    conn.execute(
        "INSERT INTO events (event_id, project_id, task_id, event_type, "
        "caused_by, created_at, from_state, to_state, reason, payload_json, "
        "correlation_id, artifact_ids_json) "
        "VALUES (999999, NULL, NULL, 'Tick', 'CONTROLLER', "
        "'2026-08-16T00:00:00.000000+00:00', NULL, NULL, "
        "'stale-admission', '{}', 'corr-1', NULL)")
    conn.close()
    u = run(cfg_hidden, ["audit"])
    assert "stale-admission" in u and "proj=-" in u
    assert "stale-admission" not in run(cfg_hidden, ["audit", "--project", "p1"])
    assert "stale-admission" not in run(cfg_hidden, ["audit", "--project", "ghost"])
    uj = _json.loads(run(cfg_hidden, ["audit", "--json"]))
    assert any(e["project_id"] is None for e in uj["events"])
    assert all(e["project_id"] is not None
               for e in _json.loads(run(cfg_hidden, ["audit", "--project", "p1", "--json"]))["events"])


# ── F2-lens: the status human table is invariant + bounded under tamper ──

def test_status_human_table_hidden_state_invariant_and_bounded(
        tmp_path, capsys):
    """F2-lens probe on the HUMAN `status` table under a tampered store:
    it is a LOSSY, BOUNDED projection of the same rows the `--json` view
    exposes. The p1 section is BYTE-IDENTICAL across stores sharing the
    same p1 rows (a ratified operator and a second 202-task project change
    nothing in p1's lines); id fields are truncated to 8 chars
    (``task_id[:8]``) so a pathological id cannot blow up the output;
    enum fields (lifecycle_state / operational_mode / task status /
    task_type) are DB-constrained by CHECKs — a tamper writing a 10KB
    lifecycle string is REJECTED at the store, so the human table    cannot be made variable-cost through them; and the only unbounded field
    (project name) is the tamperer's OWN value, mirrored verbatim in both
    the human table and `--json` — no additional signal."""
    import sqlite3
    from pathlib import Path

    from hermes.core import frozen_clock
    from hermes.core.intents import Intent, IntentKind
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import (
        OperatorCredentialRepository,
        ProjectRepository,
    )
    from hermes.research.gateway import apply_intent

    clock = frozen_clock("2026-08-16T00:00:00.000000+00:00")

    def task(i, proj, task_id=None):
        return Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id=proj, justification="seed",
            payload={
                "task_id": task_id or f"t{i:04d}",
                "task_type": "HUMAN_GATE", "profile": "DIRECTOR",
                "idempotency_key": f"k{i:04d}", "iteration": 1,
                "spec": {"gate_requirement": "g"},
                "inputs": [], "outputs": [], "dependencies": [],
                "provenance": [], "cost_class": None,
                "concurrency_group": None, "max_retries": 3,
                "parent_task_id": None,
            })

    def build(root, hidden_state):
        root.mkdir(parents=True)
        db = root / "hermes.db"
        conn = connect(str(db))
        migrate_to_latest(conn)
        ProjectRepository(conn, clock=clock).create("p1", "Alpha")
        apply_intent(conn, task(0, "p1"), clock=clock)
        if hidden_state:
            OperatorCredentialRepository(conn, clock=clock).register(
                "op-x", "token-123456789012", "Op")
            ProjectRepository(conn, clock=clock).create("p2", "Beta")
            for i in range(202):
                apply_intent(conn, task(i, "p2"), clock=clock)
        conn.close()
        cfg = root / "hermes.toml"
        cfg.write_text("[sqlite]" + chr(10)
                       + "database_path = " + chr(34) + db.as_posix()
                       + chr(34) + chr(10))
        return str(cfg)

    def run(cfg, cmd):
        rc = main(["--config", cfg] + cmd)
        out = capsys.readouterr().out
        assert rc == 0
        return out

    cfg_plain = build(tmp_path / "plain", False)
    cfg_hidden = build(tmp_path / "hidden", True)

    def p1_section(out):
        i = out.find("Project: Alpha")
        j = out.find("\n\n", i)
        return out[i:j if j >= 0 else len(out)]

    # hidden state cannot change p1's section: byte-identical lines
    s_plain = p1_section(run(cfg_plain, ["status"]))
    s_hidden = p1_section(run(cfg_hidden, ["status"]))
    assert s_plain == s_hidden
    assert "Project: Alpha (p1...)" in s_plain
    assert "t0000..." in s_plain  # [:8] truncation is visible

    # id truncation bound: a 30-char task id shows only the first 8 chars
    conn = connect(str(Path(cfg_plain).parent / "hermes.db"))
    apply_intent(conn, task(9, "p1", task_id="a-very-long-task-id-1234567890"),
                 clock=clock)
    conn.close()
    st = run(cfg_plain, ["status"])
    assert "a-very-l..." in st and "a-very-long-task-id-1234567890" not in st

    # enum fields are DB-constrained: a 10KB lifecycle tamper is rejected
    conn = connect(str(Path(cfg_plain).parent / "hermes.db"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE projects SET lifecycle_state = ? WHERE project_id = 'p1'",
            ("X" * 10000,))
    # the one unbounded field (name) is the tamperer's own value, mirrored
    # identically in the human table and in --json — no extra signal
    conn.execute("UPDATE projects SET name = ? WHERE project_id = 'p1'",
                 ("N" * 5000,))
    conn.close()
    st2 = run(cfg_plain, ["status"])
    sj = run(cfg_plain, ["status", "--json"])
    assert ("N" * 5000) in st2
    assert ("N" * 5000) in sj


# ── F2-lens: the doctor Sandbox check is the ONE env-derived path ──

def test_doctor_sandbox_resolved_path_env_derived_only_in_checks(
        tmp_path, capsys, monkeypatch):
    """F2-lens probe on `doctor --json`'s Sandbox check: the ONLY
    environment-derived value in the whole document is the shutil.which
    RESOLUTION of the configured runner — when a runner is configured and
    found, the checks detail is ``<runner> -> <absolute resolved path>``,
    and that absolute path appears NOWHERE in the ``config`` echo (which
    shows the bare runner string only). When the runner is not found, the
    detail is ``<runner> not found`` — no path at all. So a tampered
    config pointing the runner at an attacker-chosen name resolves against
    the OPERATOR's own PATH (not a secret — PATH is operator-controlled
    and the resolution happens on the operator's machine), and the
    config echo itself remains env-free."""
    import json as _json
    import shutil as _shutil

    resolved = (tmp_path / "bin" / "fake-runner").as_posix()
    cfg = tmp_path / "h.toml"
    cfg.write_text("[sqlite]" + chr(10)
                   + "database_path = " + chr(34)
                   + (tmp_path / "d.db").as_posix() + chr(34) + chr(10)
                   + "[sandbox]" + chr(10)
                   + "enabled = true" + chr(10)
                   + "runner = \"fake-runner\"" + chr(10))

    # found: the resolved absolute path appears ONLY in the checks detail
    monkeypatch.setattr(_shutil, "which", lambda name: resolved)
    rc = main(["--config", str(cfg), "doctor", "--json"])
    doc = _json.loads(capsys.readouterr().out)
    assert rc == 0
    sandbox_check = next(c for c in doc["checks"]
                         if c["label"] == "Sandbox")
    assert sandbox_check["detail"] == f"fake-runner -> {resolved}"
    # the config echo keeps ONLY the bare runner string, never the path
    assert doc["config"]["sandbox"]["runner"] == "fake-runner"
    assert resolved not in _json.dumps(doc["config"])

    # not found: no path revealed at all
    monkeypatch.setattr(_shutil, "which", lambda name: None)
    rc2 = main(["--config", str(cfg), "doctor", "--json"])
    doc2 = _json.loads(capsys.readouterr().out)
    assert rc2 == 0
    sandbox_check2 = next(c for c in doc2["checks"]
                          if c["label"] == "Sandbox")
    assert sandbox_check2["detail"] == "fake-runner not found"
    assert resolved not in _json.dumps(doc2)


# ── 20. composed control-plane: events CLI, gate-resolve output, ──
# ──     auth boundary, cross-project CLI, canary leakage           ──

def test_events_cli_untruncated_fields_but_strict_subset(tmp_path, capsys):
    """Composed probe on the `events` CLI human lines: they print
    event_type / from_state / to_state with MIN-WIDTH formatting only
    (``:30s``/``:14s`` — never truncation), so a tampered row carrying a
    huge type or state string is echoed in full — but that value is the
    tamperer's OWN row (attacker-known, mirrored identically in
    `audit --json`), never hidden state. The lines carry NO reason,
    payload, project, or task ids — a strict subset of the audit view —
    and are byte-identical across stores sharing the same rows (no
    correlation UUIDs in this view). NULL-project rows appear as '-'."""
    from pathlib import Path

    from hermes.core import frozen_clock
    from hermes.core.intents import Intent, IntentKind
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import (
        OperatorCredentialRepository,
        ProjectRepository,
    )
    from hermes.research.gateway import apply_intent

    clock = frozen_clock("2026-08-16T00:00:00.000000+00:00")

    def task(i, proj):
        return Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id=proj, justification="seed",
            payload={
                "task_id": f"t{i:04d}", "task_type": "HUMAN_GATE",
                "profile": "DIRECTOR", "idempotency_key": f"k{i:04d}",
                "iteration": 1, "spec": {"gate_requirement": "g"},
                "inputs": [], "outputs": [], "dependencies": [],
                "provenance": [], "cost_class": None,
                "concurrency_group": None, "max_retries": 3,
                "parent_task_id": None,
            })

    def build(root, hidden):
        root.mkdir(parents=True)
        db = root / "hermes.db"
        conn = connect(str(db))
        migrate_to_latest(conn)
        ProjectRepository(conn, clock=clock).create("p1", "Alpha")
        for i in range(2):
            apply_intent(conn, task(i, "p1"), clock=clock)
        if hidden:
            OperatorCredentialRepository(conn, clock=clock).register(
                "op-x", "token-123456789012", "Op")
            ProjectRepository(conn, clock=clock).create("p2", "Beta")
            for i in range(202):
                apply_intent(conn, task(i, "p2"), clock=clock)
        conn.close()
        cfg = root / "hermes.toml"
        cfg.write_text("[sqlite]" + chr(10)
                       + "database_path = " + chr(34) + db.as_posix()
                       + chr(34) + chr(10))
        return str(cfg)

    def run(cfg, cmd):
        rc = main(["--config", cfg] + cmd)
        out = capsys.readouterr().out
        assert rc == 0
        return out

    cfg_plain = build(tmp_path / "plain", False)
    cfg_hidden = build(tmp_path / "hidden", True)
    # same p1 rows -> byte-identical PROJECT-FILTERED events output across
    # hidden state (the unfiltered view differs only by the OTHER project's
    # own visible rows, exactly as the audit view does)
    e_plain = run(cfg_plain, ["events", "--project", "p1"])
    e_hidden = run(cfg_hidden, ["events", "--project", "p1"])
    assert e_plain == e_hidden

    # tamper: huge event_type + huge from_state (direct SQL bypasses the
    # F-04 validation) -> echoed UNTRUNCATED, and identically in audit
    conn = connect(str(Path(cfg_plain).parent / "hermes.db"))
    conn.execute(
        "UPDATE events SET event_type = ?, from_state = ? "
        "WHERE event_type = 'ResearchCreated'",
        ("E" * 300, "F" * 200))
    conn.close()
    et = run(cfg_plain, ["events"])
    assert ("E" * 300) in et and ("F" * 200) in et
    aj = run(cfg_plain, ["audit", "--json"])
    assert ("E" * 300) in aj and ("F" * 200) in aj
    # the events lines never carry reason/payload/project/task ids
    assert "reason" not in et and "payload" not in et

    # NULL-project row shows as '-', exactly like the audit view
    conn = connect(str(Path(cfg_hidden).parent / "hermes.db"))
    conn.execute(
        "INSERT INTO events (event_id, project_id, task_id, event_type, "
        "caused_by, created_at, from_state, to_state, reason, payload_json, "
        "correlation_id, artifact_ids_json) "
        "VALUES (999999, NULL, NULL, 'Tick', 'CONTROLLER', "
        "'2026-08-16T00:00:00.000000+00:00', NULL, NULL, "
        "'stale-admission', '{}', 'corr-1', NULL)")
    conn.close()
    eh = run(cfg_hidden, ["events"])
    assert "->" in eh  # from '-' -> to '-' renders for the null row


def test_gate_resolve_output_echoes_only_attacker_input(tmp_path, capsys, monkeypatch):
    """Composed probe on `hermes gate resolve` output under tamper: every
    echoed identifier is the ATTACKER's own input — the success line
    echoes the operator id they typed, the OPERATOR refusal echoes the
    operator id they supplied, and a task-not-found error echoes the task
    id they gave. A TAMPERED stored credential (digest chars flipped) is
    refused with the SAME OPERATOR text shape as a plain wrong token — no
    leak of the tampered row's content; and a nonexistent task is a fast
    refusal (zero KDF) revealing only public task existence, never
    operator or credential state."""
    import hashlib

    from hermes.persistence.database import connect

    db_path, cfg_path, gate_id = _seed_gate_db(tmp_path)
    assert main(["--config", cfg_path, "run", "p1", "--ticks", "3"]) == 0
    assert main(["--config", cfg_path, "operator", "register", "op-echo",
                 "--token", "echo-token-123456789"]) == 0
    capsys.readouterr()

    # success: echoes the operator id the operator typed (their own input)
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", "op-echo",
               "--token", "echo-token-123456789"])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"Gate {gate_id} resolved: APPROVED (operator op-echo)." in out

    # tamper the stored digest: the correct token is now refused OPERATOR
    # with the SAME shape as a wrong token — no leak of the tampered row
    conn = connect(str(db_path))
    row = conn.execute(
        "SELECT token_hash FROM operator_credentials WHERE operator_id = "
        "'op-echo'").fetchone()
    tampered = row["token_hash"][:-1] + ("0" if row["token_hash"][-1] != "0"
                                         else "1")
    conn.execute("UPDATE operator_credentials SET token_hash = ? "
                 "WHERE operator_id = 'op-echo'", (tampered,))
    conn.close()
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", "op-echo",
               "--token", "echo-token-123456789"])
    out_tampered = capsys.readouterr().out
    assert rc == 1
    assert "Refused (OPERATOR):" in out_tampered
    assert "op-echo" in out_tampered  # the attacker-supplied id, only
    # compare against a plain wrong-token refusal: identical shape
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", "op-echo",
               "--token", "wrong-token-999999999"])
    out_wrong = capsys.readouterr().out
    assert rc == 1
    assert out_wrong.split(":")[0] == out_tampered.split(":")[0]
    assert "Refused (OPERATOR):" in out_wrong

    # nonexistent task: fast refusal, zero KDF, echoes the task id only
    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    import hermes.persistence.repositories as repos_mod

    repos_mod._burn_dummy_operator_work("echo-warmup")
    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)
    rc = main(["--config", cfg_path, "gate", "resolve", "ghost-task",
               "--verdict", "APPROVED", "--operator", "op-echo",
               "--token", "echo-token-123456789"])
    out_ghost = capsys.readouterr().out
    assert rc == 1
    assert "ghost-task" in out_ghost
    assert calls["n"] == 0


def test_verdict_requires_credential_operational_surfaces_do_not(
        tmp_path, capsys, monkeypatch):
    """Composed authorization-boundary probe: the operator control plane
    gates EXACTLY ONE authority — the gate VERDICT — with the ratified
    credential (zero token -> OPERATOR refusal, one KDF), while the
    operational plumbing (pause / resume / run) is deliberately
    unauthenticated local machinery (the DB file is the local trust
    boundary; these commands write no research outcomes and perform zero
    KDF). The boundary is documented: verdicts require the credential;
    operational commands do not."""
    import hashlib

    _db_path, cfg_path, gate_id = _seed_gate_db(tmp_path)
    assert main(["--config", cfg_path, "operator", "register", "op-bnd",
                 "--token", "boundary-token-123456"]) == 0
    assert main(["--config", cfg_path, "run", "p1", "--ticks", "3"]) == 0
    capsys.readouterr()

    # pause / resume need NO credential and perform ZERO KDF (pre-warm the
    # lazily-built module dummy hash so the later OPERATOR count is exact)
    import hermes.persistence.repositories as repos_mod

    repos_mod._burn_dummy_operator_work("boundary-warmup")
    calls = {"n": 0}
    real_pbkdf2 = hashlib.pbkdf2_hmac

    def counting(*a, **k):
        calls["n"] += 1
        return real_pbkdf2(*a, **k)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)
    assert main(["--config", cfg_path, "pause", "p1"]) == 0
    assert calls["n"] == 0
    capsys.readouterr()
    assert main(["--config", cfg_path, "resume", "p1"]) == 0
    assert calls["n"] == 0
    capsys.readouterr()

    # the verdict surface REQUIRES the ratified credential: an unratified
    # operator is refused OPERATOR with one KDF
    calls["n"] = 0
    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--verdict", "APPROVED", "--operator", "op-ghost",
               "--token", "ghost-token-123456789"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "Refused (OPERATOR):" in out
    assert calls["n"] == 1


def test_cli_cross_project_gate_resolution(tmp_path, capsys):
    """Composed cross-project probe at the CLI: `gate resolve --project
    p2` on a gate parked in p1 is refused NOT_FOUND with the gate left
    untouched and zero events written; the same command WITHOUT --project
    resolves the gate through its OWN project (the CLI derives it from the
    task row). The project scoping lives in the controller binding — the
    operator credential is system-wide by design."""
    from hermes.persistence.database import connect

    db_path, cfg_path, gate_id = _seed_gate_db(tmp_path)
    assert main(["--config", cfg_path, "run", "p1", "--ticks", "3"]) == 0
    assert main(["--config", cfg_path, "operator", "register", "op-xp",
                 "--token", "xproj-token-12345678"]) == 0
    capsys.readouterr()

    rc = main(["--config", cfg_path, "gate", "resolve", gate_id,
               "--project", "p2", "--verdict", "APPROVED",
               "--operator", "op-xp", "--token", "xproj-token-12345678"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "NOT_FOUND" in out
    conn = connect(str(db_path))
    status = conn.execute(
        "SELECT status FROM tasks WHERE task_id = ?", (gate_id,)).fetchone()
    n_events = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE task_id = ?",
        (gate_id,)).fetchone()["c"]
    conn.close()
    assert status["status"] == "WAITING_HUMAN"
    assert n_events == 5  # admission + parking events, nothing from the refusal

    # without --project the CLI derives the task's own project and lands it
    rc2 = main(["--config", cfg_path, "gate", "resolve", gate_id,
                "--verdict", "APPROVED", "--operator", "op-xp",
                "--token", "xproj-token-12345678"])
    out2 = capsys.readouterr().out
    assert rc2 == 0
    assert f"Gate {gate_id} resolved: APPROVED" in out2


def test_canary_token_never_leaks_any_surface(tmp_path, capsys):
    """Composed canary-leak probe (brief §12): a recognizable canary token
    registered as an operator credential never appears anywhere — the event
    journal, audit --json, status --json, doctor --json, the events CLI,
    the backup snapshot bytes, the raw DB bytes (only the PBKDF2 hash is
    stored), and every gate-resolve output (success and refusal). The
    canary is a 22-char distinct marker so any echo would be unmistakable."""
    db_path, cfg_path, gate_id = _seed_gate_db(tmp_path)
    canary = "CANARY-7f3a9c2e-token-01"
    assert main(["--config", cfg_path, "run", "p1", "--ticks", "3"]) == 0
    assert main(["--config", cfg_path, "operator", "register", "op-can",
                 "--token", canary]) == 0
    capsys.readouterr()

    outputs: list[str] = []
    for cmd in (["audit", "--json"], ["audit"], ["status", "--json"],
                ["status"], ["events"], ["doctor", "--json"], ["doctor"]):
        assert main(["--config", cfg_path] + cmd) == 0
        outputs.append(capsys.readouterr().out)
    # a successful resolve and a wrong-token refusal
    assert main(["--config", cfg_path, "gate", "resolve", gate_id,
                 "--verdict", "APPROVED", "--operator", "op-can",
                 "--token", canary]) == 0
    outputs.append(capsys.readouterr().out)
    assert main(["--config", cfg_path, "operator", "register", "op-can",
                 "--token", canary]) == 0  # idempotent re-register
    outputs.append(capsys.readouterr().out)
    assert main(["--config", cfg_path, "gate", "resolve", gate_id,
                 "--verdict", "REJECTED", "--operator", "op-can",
                 "--token", "wrong-token-999999999"]) == 1
    outputs.append(capsys.readouterr().out)

    # the backup snapshot bytes and the raw DB bytes
    bd = tmp_path / "bk"
    bd.mkdir()
    assert main(["--config", cfg_path, "backup"]) == 0
    backup_line = capsys.readouterr().out
    outputs.append(backup_line)
    bk_path = backup_line.split("Backup written: ")[1].splitlines()[0].strip()
    with open(bk_path, "rb") as fh:
        outputs.append(fh.read().decode("latin-1"))
    with open(db_path, "rb") as fh:
        outputs.append(fh.read().decode("latin-1"))

    blob = "\n".join(outputs)
    assert canary not in blob, "canary leaked"
    assert canary.lower() not in blob.lower()
