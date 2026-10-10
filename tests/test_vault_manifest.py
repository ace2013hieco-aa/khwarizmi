"""R-1 vault manifest battery: the derived-view claim and its verifier.

Closes the P-AUTO-5 D2/G silence-by-design findings: a cursor restored ahead
of the vault (D2: dangling stable-ID link), a gapped/backfilled/lost range
and a tampered note (G: silent skips) are each detected and *named* by
``hermes vault verify`` with a refusing report, while a clean vault verifies
OK. The manifest is a derived view — these tests prove the verifier
recomputes the claim from the journal instead of trusting the file (a
manifest tampered to match a tampered note is still refused by
recomputation), and that the journal is never written by either surface.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pytest

from hermes.vault.manifest import (
    FINDING_CODES,
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    read_manifest,
    verify_manifest,
)
from hermes.vault.projection import (
    ProjectionRefused,
    init_vault_root,
    note_filename,
    project,
    read_cursor,
    write_cursor,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"


@pytest.fixture
def db():
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ProjectRepository

    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create("p1", "Test")
    yield conn
    conn.close()


def _emit(conn, event_type, task_id=None, event_id=None, payload=None,
          reason=""):
    """One journal row; returns its event_id (explicit ids for backfills)."""
    if task_id is not None:
        conn.execute(
            "INSERT OR IGNORE INTO tasks (task_id, project_id, task_type, "
            "idempotency_key, created_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, "p1", "AGENT_TASK", str(task_id) + "-key", CLOCK))
    cols = ["event_type", "project_id", "task_id", "caused_by", "reason",
            "payload_json", "created_at"]
    vals = [event_type, "p1", task_id, "test", reason,
            json.dumps(payload) if payload is not None else None, CLOCK]
    if event_id is not None:
        cols = ["event_id", *cols]
        vals = [event_id, *vals]
    marks = ", ".join("?" for _ in vals)
    row = conn.execute(
        f"INSERT INTO events ({', '.join(cols)}) VALUES ({marks})", vals)
    conn.commit()
    return row.lastrowid


def _project(conn, root, cursor=0):
    """Project + persist the cursor (the production run pair)."""
    new_cursor, written = project(conn, "p1", root, cursor=cursor)
    write_cursor(root, new_cursor)
    return new_cursor, written


def _codes(report):
    return [finding.code for finding in report.findings]


def _finding(report, code):
    for finding in report.findings:
        if finding.code == code:
            return finding
    return None


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _vault_snapshot(root):
    return {path.name: path.read_bytes() for path in sorted(Path(root).iterdir())
            if path.is_file()}


# ── the claim ──

def test_manifest_records_range_digests_and_head(db, tmp_path):
    for _ in range(3):
        _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    cursor, written = _project(db, root, cursor=0)
    assert cursor == 4 and len(written) == 4

    manifest = read_manifest(root)
    assert manifest["manifest"] == MANIFEST_VERSION
    assert "never authority" in manifest["authority"]
    assert manifest["project_id"] == "p1"
    assert (manifest["cursor_before"], manifest["cursor_after"]) == (0, 4)
    assert manifest["covered"] == "(0, 4]"
    assert manifest["journal_head"]["event_id"] == 4
    assert len(manifest["notes"]) == 4
    for entry in manifest["notes"]:
        path = Path(root) / entry["filename"]
        assert path.exists()
        assert entry["sha256"] == _sha256_file(path)
    assert read_cursor(root) == 4


def test_verify_ok_and_scratch_equals_incremental_claim(db, tmp_path):
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ProjectRepository

    _emit(db, "TaskStatusChanged")
    grown, _ = _project(db, str(tmp_path / "inc"), cursor=0)
    _emit(db, "TaskStatusChanged")
    incremental, _ = _project(db, str(tmp_path / "inc"), cursor=grown)

    conn2 = connect(":memory:")
    migrate_to_latest(conn2)
    ProjectRepository(conn2, lambda: CLOCK).create("p1", "Test")
    _emit(conn2, "TaskStatusChanged")
    _emit(conn2, "TaskStatusChanged")
    scratch, _ = _project(conn2, str(tmp_path / "full"), cursor=0)
    conn2.close()
    assert (incremental, scratch) == (3, 3)

    inc_manifest = read_manifest(str(tmp_path / "inc"))
    full_manifest = read_manifest(str(tmp_path / "full"))
    assert inc_manifest["notes"] == full_manifest["notes"]
    assert inc_manifest["cursor_after"] == full_manifest["cursor_after"]
    assert inc_manifest["journal_head"] == full_manifest["journal_head"]

    for root in (str(tmp_path / "inc"), str(tmp_path / "full")):
        report = verify_manifest(db, "p1", root)
        assert report.ok, report.lines()
        assert report.counts == {}
        assert report.covered_notes == 3


def test_manifest_rerun_is_byte_identical(db, tmp_path):
    _emit(db, "TaskStatusChanged")
    _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    _project(db, root, cursor=0)
    first = (Path(root) / MANIFEST_FILENAME).read_bytes()
    _project(db, root, cursor=0)
    assert (Path(root) / MANIFEST_FILENAME).read_bytes() == first


# ── D2: restored cursors, unwritten notes, dangling links ──

def test_restored_cursor_names_unwritten_ids_and_dangling_link(
        db, tmp_path, caplog):
    created = _emit(db, "TaskCreated", task_id="t-1")
    root = str(tmp_path / "v")
    write_cursor(root, created)          # restored ahead of the vault
    later = _emit(db, "TaskStatusChanged", task_id="t-1")
    with caplog.at_level(logging.WARNING, logger="hermes.vault.projection"):
        cursor, written = project(db, "p1", root, cursor=created)
    write_cursor(root, cursor)
    assert written == [note_filename(later, "TaskStatusChanged")]
    assert any("absent from the vault" in record.getMessage()
               for record in caplog.records)

    report = verify_manifest(db, "p1", root)
    assert not report.ok
    assert set(_codes(report)) <= set(FINDING_CODES)
    missing = _finding(report, "MISSING_NOTE")
    assert missing is not None
    assert missing.event_ids == (1, created)
    dangling = _finding(report, "DANGLING_LINK")
    assert dangling is not None
    target = note_filename(created, "TaskCreated")[:-3]
    assert any(f"evt-{later:06d}-" in name and name.endswith(target)
               for name in dangling.filenames)
    assert not (Path(root) / note_filename(created, "TaskCreated")).exists()


def test_cursor_beyond_journal_head_is_named(db, tmp_path):
    _emit(db, "TaskStatusChanged")
    _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    cursor, _ = _project(db, root, cursor=0)
    assert cursor == 3
    _project(db, root, cursor=53)        # restored way beyond the head
    report = verify_manifest(db, "p1", root)
    assert not report.ok
    ahead = _finding(report, "CURSOR_RESTORED_AHEAD")
    assert ahead is not None
    assert ahead.event_ids[0] == 4
    assert "4-35" in ahead.line()        # capped window, still named
    assert _finding(report, "MISSING_NOTE") is None
    assert _finding(report, "GAP_RANGE") is None


# ── G: gaps, backfills, lost rows ──

def test_gapped_range_is_named(db, tmp_path, caplog):
    _emit(db, "TaskStatusChanged")
    lost = _emit(db, "TaskStatusChanged")
    _emit(db, "TaskStatusChanged")
    db.execute("DELETE FROM events WHERE event_id = ?", (lost,))
    db.commit()
    root = str(tmp_path / "v")
    with caplog.at_level(logging.WARNING, logger="hermes.vault.projection"):
        _project(db, root, cursor=0)
    assert any("journal hole" in record.getMessage()
               for record in caplog.records)
    assert read_manifest(root)["gap_event_ids"] == [lost]

    report = verify_manifest(db, "p1", root)
    assert not report.ok
    gap = _finding(report, "GAP_RANGE")
    assert gap is not None and gap.event_ids == (lost,)
    assert _finding(report, "MISSING_NOTE") is None


def test_backfilled_range_is_named(db, tmp_path):
    _emit(db, "TaskStatusChanged")
    hole = _emit(db, "TaskStatusChanged")
    _emit(db, "TaskStatusChanged")
    db.execute("DELETE FROM events WHERE event_id = ?", (hole,))
    db.commit()
    root = str(tmp_path / "v")
    cursor, _ = _project(db, root, cursor=1)
    assert cursor == 4
    _emit(db, "TaskStatusChanged", event_id=hole)   # backfill below cursor
    assert not (Path(root) / note_filename(
        hole, "TaskStatusChanged")).exists()

    report = verify_manifest(db, "p1", root)
    assert not report.ok
    backfilled = _finding(report, "BACKFILLED_RANGE")
    assert backfilled is not None and backfilled.event_ids == (hole,)
    assert "event_ids" in backfilled.line()


def test_lost_range_is_named(db, tmp_path):
    _emit(db, "TaskStatusChanged")
    lost = _emit(db, "TaskStatusChanged")
    _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    _project(db, root, cursor=1)
    db.execute("DELETE FROM events WHERE event_id = ?", (lost,))
    db.commit()
    report = verify_manifest(db, "p1", root)
    assert not report.ok
    lost_finding = _finding(report, "LOST_RANGE")
    assert lost_finding is not None and lost_finding.event_ids == (lost,)
    assert _finding(report, "GAP_RANGE").event_ids == (lost,)
    assert _finding(report, "TAMPERED_NOTE") is None


# ── tampering: note bytes and the manifest itself ──

def test_tampered_note_is_named(db, tmp_path):
    _emit(db, "TaskStatusChanged")
    tampered = _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    _project(db, root, cursor=0)
    note = Path(root) / note_filename(tampered, "TaskStatusChanged")
    note.write_text(note.read_text(encoding="utf-8") + "OUTSIDE EDIT\n",
                    encoding="utf-8")
    report = verify_manifest(db, "p1", root)
    assert not report.ok
    assert report.counts == {"TAMPERED_NOTE": 1}
    finding = _finding(report, "TAMPERED_NOTE")
    assert finding.event_ids == (tampered,)
    assert finding.filenames == (note.name,)


def test_tampered_manifest_is_caught_by_recomputation(db, tmp_path):
    _emit(db, "TaskStatusChanged")
    row = _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    _project(db, root, cursor=0)
    note = Path(root) / note_filename(row, "TaskStatusChanged")
    note.write_bytes(note.read_bytes() + b"OUTSIDE EDIT\n")
    # Forge the manifest so the tampered bytes look approved.
    manifest = read_manifest(root)
    for entry in manifest["notes"]:
        if entry["event_id"] == row:
            entry["sha256"] = _sha256_file(note)
    (Path(root) / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")

    report = verify_manifest(db, "p1", root)
    assert not report.ok
    diverged = _finding(report, "NOTE_DIGEST_DIVERGES")
    assert diverged is not None and diverged.event_ids == (row,)
    assert _finding(report, "TAMPERED_NOTE") is None  # disk == forged manifest


def test_invented_note_is_named(db, tmp_path):
    _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    _project(db, root, cursor=0)
    (Path(root) / "evt-000999-planted-event.md").write_text(
        "---\nplanted: true\n---\n", encoding="utf-8", newline="\n")
    report = verify_manifest(db, "p1", root)
    assert not report.ok
    invented = _finding(report, "INVENTED_NOTE")
    assert invented is not None and invented.event_ids == (999,)
    assert invented.filenames == ("evt-000999-planted-event.md",)


# ── cursor posture + manifest shape ──

def test_cursor_missing_and_mismatch_are_named(db, tmp_path):
    _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    project(db, "p1", root, cursor=0)    # manifest written, cursor not
    report = verify_manifest(db, "p1", root)
    assert _codes(report) == ["CURSOR_MISSING"]

    write_cursor(root, 1)
    report = verify_manifest(db, "p1", root)
    assert not report.ok
    mismatch = _finding(report, "CURSOR_MISMATCH")
    assert mismatch is not None
    assert "live cursor 1" in mismatch.detail


def test_manifest_missing_unreadable_and_foreign(db, tmp_path):
    _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    init_vault_root(root)
    report = verify_manifest(db, "p1", root)
    assert _codes(report) == ["MANIFEST_MISSING"]

    (Path(root) / MANIFEST_FILENAME).write_text("not json", encoding="utf-8")
    report = verify_manifest(db, "p1", root)
    assert _codes(report) == ["MANIFEST_UNREADABLE"]

    cursor, _ = _project(db, root, cursor=0)
    manifest = read_manifest(root)
    manifest["project_id"] = "p2"
    (Path(root) / MANIFEST_FILENAME).write_text(
        json.dumps(manifest), encoding="utf-8")
    report = verify_manifest(db, "p1", root)
    assert _codes(report) == ["MANIFEST_PROJECT_MISMATCH"]
    assert cursor == 2 and read_cursor(root) == 2


def test_verify_is_read_only_and_the_manifest_is_a_derived_view(db, tmp_path):
    _emit(db, "TaskStatusChanged")
    _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    _project(db, root, cursor=0)
    journal_before = [dict(row) for row in db.execute(
        "SELECT * FROM events ORDER BY event_id").fetchall()]
    vault_before = _vault_snapshot(root)

    report = verify_manifest(db, "p1", root)
    assert report.ok
    assert [dict(row) for row in db.execute(
        "SELECT * FROM events ORDER BY event_id").fetchall()] == journal_before
    assert _vault_snapshot(root) == vault_before
    manifest = read_manifest(root)
    assert manifest["authority"].endswith("never authority")


# ── CLI surface ──

def _file_db(path):
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ProjectRepository

    conn = connect(str(path))
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create("p1", "Test")
    return conn


def _config(tmp_path, db_path):
    cfg = tmp_path / "hermes.toml"
    cfg.write_text("[sqlite]\ndatabase_path = \"" + db_path.as_posix()
                   + "\"\n", encoding="utf-8")
    return str(cfg)


def test_cli_vault_project_then_verify_ok(tmp_path, capsys):
    from hermes.cli import main

    db_path = tmp_path / "hermes.db"
    conn = _file_db(db_path)
    _emit(conn, "TaskStatusChanged")
    conn.close()
    cfg = _config(tmp_path, db_path)
    root = str(tmp_path / "v")
    rc = main(["--config", cfg, "vault", "project", "p1",
               "--vault-root", root])
    out = capsys.readouterr()
    assert rc == 0, out.out
    assert "manifest .projection-manifest.json written" in out.out

    rc = main(["--config", cfg, "vault", "verify", "p1",
               "--vault-root", root])
    out = capsys.readouterr()
    assert rc == 0, out.out
    assert "manifest verify p1: OK" in out.out


def test_cli_vault_verify_refuses_with_named_ids(tmp_path, capsys):
    from hermes.cli import main

    db_path = tmp_path / "hermes.db"
    conn = _file_db(db_path)
    row = _emit(conn, "TaskStatusChanged")
    conn.close()
    cfg = _config(tmp_path, db_path)
    root = str(tmp_path / "v")
    assert main(["--config", cfg, "vault", "project", "p1",
                 "--vault-root", root]) == 0
    capsys.readouterr()
    note = Path(root) / note_filename(row, "TaskStatusChanged")
    note.write_bytes(note.read_bytes() + b"OUTSIDE EDIT\n")

    rc = main(["--config", cfg, "vault", "verify", "p1",
               "--vault-root", root])
    out = capsys.readouterr()
    assert rc == 1
    assert "[TAMPERED_NOTE]" in out.out
    assert f"event_ids=[{row}]" in out.out
    assert "refused" in out.err

    rc = main(["--config", cfg, "vault", "verify", "p1",
               "--vault-root", root, "--json"])
    out = capsys.readouterr()
    assert rc == 1
    document = json.loads(out.out)
    assert document["ok"] is False
    assert document["counts"] == {"TAMPERED_NOTE": 1}
    assert document["findings"][0]["code"] == "TAMPERED_NOTE"
    assert document["findings"][0]["event_ids"] == [row]


def test_cli_vault_verify_refuses_guard_errors(tmp_path, capsys):
    from hermes.cli import main

    db_path = tmp_path / "hermes.db"
    conn = _file_db(db_path)
    conn.close()
    cfg = _config(tmp_path, db_path)
    rc = main(["--config", cfg, "vault", "verify", "p1",
               "--vault-root", str(tmp_path / "reports")])
    out = capsys.readouterr()
    assert rc == 1
    assert "VAULT_ROOT_HUMAN_OWNED" in out.out


def test_bad_project_id_still_refuses(tmp_path):
    root = str(tmp_path / "v")
    with pytest.raises(ProjectionRefused) as excinfo:
        verify_manifest(None, "", root)
    assert excinfo.value.code == "BAD_PROJECT_ID"


# ── journal-head anchor ──

def test_journal_head_rewrite_is_caught(db, tmp_path):
    _emit(db, "TaskStatusChanged")
    head = _emit(db, "IntentApplied", reason="original")
    root = str(tmp_path / "v")
    _project(db, root, cursor=0)
    db.execute("UPDATE events SET reason = ? WHERE event_id = ?",
               ("REWRITTEN", head))
    db.commit()
    report = verify_manifest(db, "p1", root)
    assert not report.ok
    changed = _finding(report, "JOURNAL_HEAD_CHANGED")
    assert changed is not None and changed.event_ids == (head,)
    assert _finding(report, "NOTE_DIGEST_DIVERGES").event_ids == (head,)
    assert _finding(report, "TAMPERED_NOTE") is None


def test_journal_head_regression_is_named(db, tmp_path):
    _emit(db, "TaskStatusChanged")
    head = _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    _project(db, root, cursor=0)
    db.execute("DELETE FROM events WHERE event_id = ?", (head,))
    db.commit()
    report = verify_manifest(db, "p1", root)
    assert not report.ok
    regressed = _finding(report, "JOURNAL_HEAD_REGRESSED")
    assert regressed is not None and regressed.event_ids == (head,)
    assert _finding(report, "LOST_RANGE").event_ids == (head,)


def test_note_beyond_cursor_is_named(db, tmp_path):
    _emit(db, "TaskStatusChanged")
    _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    _project(db, root, cursor=0)
    saved = (Path(root) / MANIFEST_FILENAME).read_bytes()
    _emit(db, "TaskStatusChanged")
    cursor, written = _project(db, root, cursor=3)
    assert cursor == 4 and len(written) == 1
    (Path(root) / MANIFEST_FILENAME).write_bytes(saved)   # rolled back
    report = verify_manifest(db, "p1", root)
    assert not report.ok
    beyond = _finding(report, "NOTE_BEYOND_CURSOR")
    assert beyond is not None and beyond.event_ids == (4,)
    assert _finding(report, "CURSOR_MISMATCH") is not None


# ── R1-HARDEN: verifier-completeness (M1 forged gaps, M2 renames) ──

def _rewrite_manifest(root, mutate):
    manifest = read_manifest(root)
    mutate(manifest)
    (Path(root) / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")


def test_forged_gap_event_ids_are_named(db, tmp_path):
    """M1 — a clean vault verifies OK; forging gap_event_ids is refused."""
    _emit(db, "TaskStatusChanged")
    _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    _project(db, root, cursor=0)
    honest = verify_manifest(db, "p1", root)
    assert honest.ok, honest.lines()
    assert honest.counts == {}

    _rewrite_manifest(root, lambda m: m.update(gap_event_ids=[5]))
    report = verify_manifest(db, "p1", root)
    assert not report.ok
    mismatch = _finding(report, "GAP_MANIFEST_MISMATCH")
    assert mismatch is not None and mismatch.event_ids == (5,)
    assert _finding(report, "GAP_RANGE") is None  # no real holes


def test_hidden_gaps_name_both_the_hole_and_the_mismatch(db, tmp_path, caplog):
    """M1 — clearing gap_event_ids over a real hole names the mismatch too."""
    _emit(db, "TaskStatusChanged")
    lost = _emit(db, "TaskStatusChanged")
    _emit(db, "TaskStatusChanged")
    db.execute("DELETE FROM events WHERE event_id = ?", (lost,))
    db.commit()
    root = str(tmp_path / "v")
    with caplog.at_level(logging.WARNING, logger="hermes.vault.projection"):
        _project(db, root, cursor=0)
    assert read_manifest(root)["gap_event_ids"] == [lost]

    _rewrite_manifest(root, lambda m: m.update(gap_event_ids=[]))
    report = verify_manifest(db, "p1", root)
    assert not report.ok
    assert _finding(report, "GAP_RANGE").event_ids == (lost,)
    mismatch = _finding(report, "GAP_MANIFEST_MISMATCH")
    assert mismatch is not None and mismatch.event_ids == (lost,)


def test_non_canonical_filename_is_named(db, tmp_path):
    """M2 — a renamed note with the manifest edited to agree is refused."""
    _emit(db, "TaskStatusChanged")
    row = _emit(db, "TaskStatusChanged")
    root = str(tmp_path / "v")
    _project(db, root, cursor=0)
    honest = verify_manifest(db, "p1", root)
    assert honest.ok, honest.lines()

    canonical = note_filename(row, "TaskStatusChanged")
    forged_name = f"evt-{row:06d}-renamed-slug.md"
    assert forged_name != canonical
    (Path(root) / canonical).rename(Path(root) / forged_name)

    def forge(manifest):
        for entry in manifest["notes"]:
            if entry["event_id"] == row:
                entry["filename"] = forged_name
    _rewrite_manifest(root, forge)
    report = verify_manifest(db, "p1", root)
    assert not report.ok
    renamed = _finding(report, "NON_CANONICAL_FILENAME")
    assert renamed is not None and renamed.event_ids == (row,)
    assert renamed.filenames == (forged_name,)


# ── closed-set drift guard ──

def test_every_emitted_finding_code_is_in_the_closed_set():
    """The verifier's refusals are refusal-as-data: every code it can emit
    must be declared in FINDING_CODES (source-level drift guard)."""
    import inspect
    import re

    from hermes.vault import manifest as module

    finding_call = re.escape('_finding(findings, "') + r'([A-Z_]+)"'
    emitted = set(re.findall(finding_call, inspect.getsource(module)))
    refusal = re.escape("ProjectionRefused(") + r'\s*"([A-Z_]+)"'
    emitted |= set(re.findall(refusal, inspect.getsource(module.read_manifest)))
    assert emitted, "structural probe found no codes — stale pattern"
    assert emitted <= set(FINDING_CODES), sorted(emitted - set(FINDING_CODES))
