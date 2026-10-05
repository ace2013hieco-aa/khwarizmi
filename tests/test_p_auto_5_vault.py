"""P-AUTO-5 vault projection gate batteries (deterministic, offline).

Determinism battery (same journal → byte-identical notes; scratch ==
incremental; re-runs change zero bytes), guard-attack battery (traversal,
absolute, symlink, case tricks, human-owned areas), authoritative-vs-
process separation proof (seeded counter-proof: unverified content never
enters the authoritative graph).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hermes.vault.projection import (
    AUTHORITATIVE_EVENT_TYPES,
    HUMAN_OWNED_NAMES,
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


def _emit(conn, event_type, task_id=None, from_state=None, to_state=None,
          caused_by="test", reason="", payload=None, artifacts=None):
    if task_id is not None:
        # FK posture: journal rows reference real task rows (as production
        # writes do through the repositories).
        conn.execute(
            "INSERT OR IGNORE INTO tasks (task_id, project_id, task_type, "
            "idempotency_key, created_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, "p1", "AGENT_TASK", str(task_id) + "-key", CLOCK),
        )
    row = conn.execute(
        "INSERT INTO events (event_type, project_id, task_id, from_state, "
        "to_state, caused_by, reason, artifact_ids_json, payload_json, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_type, "p1", task_id, from_state, to_state, caused_by, reason,
         json.dumps(artifacts) if artifacts is not None else None,
         json.dumps(payload, sort_keys=True) if payload is not None else None,
         CLOCK),
    )
    conn.commit()
    return row.lastrowid


def _seed_standard(conn, start=0, stop=None):
    steps = [
        ("TaskCreated", {"task_id": "t-1"}),
        ("TaskStatusChanged", {"task_id": "t-1",
                               "from_state": "READY", "to_state": "RUNNING"}),
        ("IntentApplied", {"task_id": "t-1", "reason": "admitted"}),
        ("HumanDecisionReceived", {"task_id": "gate-1", "reason": "APPROVED",
                                  "payload": {"verdict": "APPROVED"}}),
        ("EvidenceTransitionApplied", {"task_id": "t-1",
                                      "reason": "obligation met",
                                      "payload": {"rung": "supported"}}),
        ("IntentRejected", {"task_id": "t-2", "reason": "MALFORMED_PAYLOAD"}),
    ]
    for event_type, kwargs in steps[start:stop]:
        _emit(conn, event_type, **kwargs)


def _hashes(root):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).glob("*.md"))}


def _count(conn):
    return conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]


# ── determinism battery ──


def test_same_journal_byte_identical(db, tmp_path):
    _seed_standard(db)
    total = _count(db)
    new_cursor, written = project(db, "p1", str(tmp_path / "a"), cursor=0)
    assert new_cursor == total and len(written) == total

    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ProjectRepository

    conn2 = connect(":memory:")
    migrate_to_latest(conn2)
    ProjectRepository(conn2, lambda: CLOCK).create("p1", "Test")
    _seed_standard(conn2)
    project(conn2, "p1", str(tmp_path / "b"), cursor=0)
    conn2.close()
    assert _hashes(tmp_path / "a") == _hashes(tmp_path / "b")


def test_scratch_equals_incremental_catch_up(db, tmp_path):
    from hermes.persistence.database import connect
    from hermes.persistence.migrations import migrate_to_latest
    from hermes.persistence.repositories import ProjectRepository

    # Grown journal: 3 rows, project, 3 more rows, catch up.
    _seed_standard(db, start=0, stop=3)
    grown, _ = project(db, "p1", str(tmp_path / "inc"), cursor=0)
    assert grown == _count(db)
    _seed_standard(db, start=3, stop=6)
    caught, _ = project(db, "p1", str(tmp_path / "inc"), cursor=grown)
    assert caught == _count(db)
    # Scratch journal: identical rows and ids, projected in one run.
    conn2 = connect(":memory:")
    migrate_to_latest(conn2)
    ProjectRepository(conn2, lambda: CLOCK).create("p1", "Test")
    _seed_standard(conn2)
    project(conn2, "p1", str(tmp_path / "full"), cursor=0)
    conn2.close()
    assert _hashes(tmp_path / "inc") == _hashes(tmp_path / "full")


def test_rerun_changes_zero_bytes(db, tmp_path):
    _seed_standard(db)
    root = str(tmp_path / "v")
    project(db, "p1", root, cursor=0)
    before = _hashes(root)
    total = _count(db)
    cursor2, written2 = project(db, "p1", root, cursor=0)
    assert cursor2 == total and len(written2) == total
    assert _hashes(root) == before


def test_cursor_advances_and_empty_window_is_noop(db, tmp_path):
    _seed_standard(db)
    root = str(tmp_path / "v")
    cursor, _ = project(db, "p1", root, cursor=0)
    assert cursor == _count(db)
    cursor2, written2 = project(db, "p1", root, cursor=cursor)
    assert (cursor2, written2) == (cursor, [])


def test_cursor_file_roundtrip(tmp_path):
    root = str(tmp_path / "v")
    init_vault_root(root)
    write_cursor(root, 41)
    assert read_cursor(root) == 41
    with pytest.raises(ProjectionRefused):
        write_cursor(root, -1)


# ── guard-attack battery ──


def test_vault_root_must_be_absolute(tmp_path):
    with pytest.raises(ProjectionRefused) as exc:
        init_vault_root("relative/vault")
    assert exc.value.code == "VAULT_ROOT_NOT_ABSOLUTE"


@pytest.mark.parametrize("name", list(HUMAN_OWNED_NAMES) + ["OBSIDIAN-VAULT",
                                                             "Reports"])
def test_human_owned_areas_never_written(tmp_path, name):
    target = tmp_path / name / "sub"
    with pytest.raises(ProjectionRefused) as exc:
        init_vault_root(str(target))
    assert exc.value.code == "VAULT_ROOT_HUMAN_OWNED"
    assert not target.exists()


def test_init_creates_clean_root(tmp_path):
    root = init_vault_root(str(tmp_path / "new-vault"))
    assert Path(root).is_dir()


def test_note_filename_rejects_bad_ids():
    with pytest.raises(ProjectionRefused):
        note_filename(0, "TaskCreated")
    with pytest.raises(ProjectionRefused):
        note_filename(-3, "TaskCreated")
    assert note_filename(7, "TaskCreated") == "evt-000007-task-created.md"
    assert note_filename(1234567, "GatePassed") == "evt-1234567-gate-passed.md"


def test_join_refuses_traversal_and_absolute(tmp_path):
    from hermes.vault.projection import _join_note

    root = init_vault_root(str(tmp_path / "v"))
    for hostile in ("../evil.md", "/etc/passwd", "sub/../../evil.md",
                    "..\\evil.md", "evt-000001-x.md/../../evil.md"):
        with pytest.raises(ProjectionRefused) as exc:
            _join_note(root, hostile)
        assert exc.value.code == "PATH_ESCAPE"


def test_join_refuses_symlink_and_directory(tmp_path, monkeypatch):
    import os as _os

    from hermes.vault.projection import _join_note

    root = init_vault_root(str(tmp_path / "v"))
    outside = tmp_path / "outside.txt"
    outside.write_text("planted", encoding="utf-8")
    link = Path(root) / "evt-000001-task-created.md"
    try:
        link.symlink_to(outside)
        real_link = True
    except OSError:
        real_link = False  # no privilege: simulate the planted link below
    if not real_link:
        real_islink = _os.path.islink
        real_lexists = _os.path.lexists
        monkeypatch.setattr(
            _os.path, "islink",
            lambda p: True if _os.path.basename(p) == link.name
            else real_islink(p))
        monkeypatch.setattr(
            _os.path, "lexists",
            lambda p: True if _os.path.basename(p) == link.name
            else real_lexists(p))
    with pytest.raises(ProjectionRefused) as exc:
        _join_note(root, "evt-000001-task-created.md")
    assert exc.value.code == "SYMLINK_ESCAPE"
    assert outside.read_text(encoding="utf-8") == "planted"
    (Path(root) / "adir.md").mkdir()
    with pytest.raises(ProjectionRefused) as exc:
        _join_note(root, "adir.md")
    assert exc.value.code == "PATH_CONFLICT"


def test_projection_never_touches_human_dirs(db, tmp_path, monkeypatch):
    _seed_standard(db)
    human = tmp_path / "obsidian-vault"
    human.mkdir()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ProjectionRefused):
        project(db, "p1", str(human), cursor=0)
    assert list(human.iterdir()) == []


# ── separation proof (seeded counter-proof) ──


def test_authoritative_graph_holds_only_ratified_facts(db, tmp_path):
    ratified = _emit(db, "HumanDecisionReceived", task_id="gate-9",
                     reason="APPROVED",
                     payload={"verdict": "APPROVED", "gate": "gate-9"})
    _emit(db, "IntentRejected", task_id="t-unverified",
          reason="UNVERIFIED-CLAIM-XYZ proposal without ratification")
    _emit(db, "ClassificationActionProposed", task_id="t-unverified",
          reason="proposed action, never decided")
    _emit(db, "CuratedKnowledgeAdmitted", task_id="t-k",
          reason="admitted", payload={"entry_id": "k-1"})
    doomed = _emit(db, "EvidenceTransitionApplied", task_id="t-doom",
                   reason="applied, later invalidated")
    _emit(db, "TaskInvalidated", task_id="t-doom",
          reason="invalidated downstream")
    _emit(db, "GateFailed", task_id="t-unverified", reason="gate failed")
    root = str(tmp_path / "v")
    cursor, written = project(db, "p1", root, cursor=0)
    assert cursor == doomed + 2 and len(written) == 8

    authoritative = []
    for name in sorted((Path(root)).glob("*.md")):
        text = name.read_text(encoding="utf-8")
        if "authoritative: true" in text:
            authoritative.append(name.name)
    # Only the live ratified facts — never the rejected, the proposed-only,
    # the gate verdict, nor the invalidated application.
    assert authoritative == [
        note_filename(ratified, "HumanDecisionReceived"),
        note_filename(ratified + 3, "CuratedKnowledgeAdmitted"),
    ]
    for name in (Path(root)).glob("*.md"):
        text = name.read_text(encoding="utf-8")
        if "authoritative: true" in text:
            assert "currently_valid: true" in text
            assert "UNVERIFIED-CLAIM-XYZ" not in text
        else:
            assert "authoritative: false" in text
    doomed_note = (Path(root) / note_filename(doomed, "EvidenceTransitionApplied"))
    doomed_text = doomed_note.read_text(encoding="utf-8")
    assert "authoritative: false" in doomed_text
    assert "superseded by" in doomed_text


def test_late_invalidation_rewrites_victim_identically(db, tmp_path):
    live = _emit(db, "EvidenceTransitionApplied", task_id="t-late",
                 reason="applied")
    root = str(tmp_path / "v")
    project(db, "p1", root, cursor=0)
    before = (Path(root) / note_filename(live, "EvidenceTransitionApplied"))
    assert "authoritative: true" in before.read_text(encoding="utf-8")
    killer = _emit(db, "TaskInvalidated", task_id="t-late", reason="struck")
    cursor, _ = project(db, "p1", root, cursor=live)
    assert cursor == killer
    after_text = (Path(root) / note_filename(live, "EvidenceTransitionApplied"))
    assert "authoritative: false" in after_text.read_text(encoding="utf-8")
    snapshot = {p.name: p.read_bytes() for p in Path(root).glob("*.md")}
    project(db, "p1", root, cursor=0)  # scratch re-run over everything
    assert {p.name: p.read_bytes() for p in Path(root).glob("*.md")} == snapshot


# ── wikilinks, bounds, forward compat ──


def test_wikilinks_are_alias_form_with_stable_targets(db, tmp_path):
    _seed_standard(db)
    project(db, "p1", str(tmp_path / "v"), cursor=0)
    import re as _re

    for note in (Path(tmp_path / "v")).glob("*.md"):
        for target, alias in _re.findall(r"\[\[([^|\]]+)\|([^]]+)\]\]",
                                         note.read_text(encoding="utf-8")):
            assert " " not in target, f"unstable target {target!r}"
            assert target.startswith("evt-")
            assert alias and alias != target


def test_task_notes_link_their_creation_note(db, tmp_path):
    created = _emit(db, "TaskCreated", task_id="t-link")
    moved = _emit(db, "TaskStatusChanged", task_id="t-link",
                  from_state="READY", to_state="RUNNING")
    project(db, "p1", str(tmp_path / "v"), cursor=0)
    text = (Path(tmp_path / "v")
            / note_filename(moved, "TaskStatusChanged")).read_text(
                encoding="utf-8")
    assert f"[[evt-{created:06d}-task-created|task t-link]]" in text


def test_reason_bounded_at_4kib(db, tmp_path):
    row_id = _emit(db, "IntentRejected", task_id="t-big", reason="x" * 9000)
    project(db, "p1", str(tmp_path / "v"), cursor=0)
    text = (Path(tmp_path / "v")
            / note_filename(row_id, "IntentRejected")).read_text(
                encoding="utf-8")
    assert "[truncated: field exceeded 4096 chars]" in text
    assert len(text) < 9000


def test_unknown_event_type_projects_as_process(db, tmp_path):
    row_id = _emit(db, "FutureTotallyUnknownKind", task_id="t-f")
    project(db, "p1", str(tmp_path / "v"), cursor=0)
    text = (Path(tmp_path / "v")
            / note_filename(row_id, "FutureTotallyUnknownKind")).read_text(
                encoding="utf-8")
    assert "authoritative: false" in text
    assert "Event recorded" in text


def test_bad_cursor_and_project_refused(db, tmp_path):
    with pytest.raises(ProjectionRefused):
        project(db, "p1", str(tmp_path / "v"), cursor=-1)
    with pytest.raises(ProjectionRefused):
        project(db, "", str(tmp_path / "v"), cursor=0)


def test_authoritative_set_matches_contract():
    assert set(AUTHORITATIVE_EVENT_TYPES) == {
        "HumanDecisionReceived", "HumanGateResolved",
        "EvidenceTransitionApplied", "CuratedKnowledgeAdmitted",
        "ContradictionResolved",
    }
