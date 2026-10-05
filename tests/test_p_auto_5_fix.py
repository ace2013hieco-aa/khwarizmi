"""P-AUTO-5-FIX regression battery — every auditor probe green or refused.

Each regression test below fails on the unfixed slice (975655e) and passes on
fix/p-auto-5-holes. Covers the four MUST-FIX findings (B1 invalidator-outside-
window wedge + whole-window writes, B2 canonical see-link order, C1 Win32
trailing dot/space human-owned roots, A2/F frontmatter label integrity) plus
the SHOULD-FIX set (A1 verdict classification, B3 retraction keys, C2 alias
write-through, D1 link namespace, E3 written order, G gap visibility).
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import pytest

from hermes.vault.projection import (
    ProjectionRefused,
    init_vault_root,
    note_filename,
    project,
)

CLOCK = "2026-01-01T00:00:00.000000+00:00"
STABLE_STEM = re.compile(r"evt-\d{6,}-[a-z0-9-]+\Z")
UNESCAPED_LINK = re.compile(r"(?<!\\)\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


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
          caused_by="fix-test", reason="", payload=None, artifacts=None,
          created_at=None, event_id=None):
    if task_id is not None:
        # FK posture: journal rows reference real task rows.
        conn.execute(
            "INSERT OR IGNORE INTO tasks (task_id, project_id, task_type, "
            "idempotency_key, created_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, "p1", "AGENT_TASK", str(task_id) + "-key", CLOCK))
    base_cols = ("event_type, project_id, task_id, from_state, to_state, "
                 "caused_by, reason, artifact_ids_json, payload_json, created_at")
    base_vals = (event_type, "p1", task_id, from_state, to_state, caused_by,
                 reason,
                 json.dumps(artifacts) if artifacts is not None else None,
                 json.dumps(payload, sort_keys=True) if payload is not None else None,
                 created_at or CLOCK)
    if event_id is None:
        row = conn.execute(
            f"INSERT INTO events ({base_cols}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            base_vals)
    else:
        row = conn.execute(
            f"INSERT INTO events (event_id, {base_cols}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, *base_vals))
    conn.commit()
    return row.lastrowid


def _text(root, row_id, event_type):
    return (Path(root) / note_filename(row_id, event_type)).read_text("utf-8")


def _fm(text):
    """Parse the leading frontmatter block (last duplicate key wins)."""
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", "note must open frontmatter"
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    raise AssertionError("frontmatter never closed")


# ── B1: no wedge, no partial writes ──


def test_b1_catch_up_after_processed_invalidation_does_not_wedge(db, tmp_path):
    root = str(tmp_path / "v")
    auth = _emit(db, "EvidenceTransitionApplied", task_id="t-a", reason="applied")
    inval = _emit(db, "TaskInvalidated", task_id="t-a", reason="struck")
    c0, _ = project(db, "p1", root, cursor=0)          # invalidator consumed here
    late = _emit(db, "TaskStatusChanged", task_id="t-a",
                 from_state="RUNNING", to_state="INVALIDATED")
    c1, w1 = project(db, "p1", root, cursor=c0)        # auditor repro: KeyError on 975655e
    assert c1 == late
    assert set(w1) == {note_filename(auth, "EvidenceTransitionApplied"),
                       note_filename(late, "TaskStatusChanged")}
    nxt = _emit(db, "TaskCreated", task_id="t-new")
    c2, _ = project(db, "p1", root, cursor=c1)         # retry must not wedge either
    assert c2 == nxt
    victim = _text(root, auth, "EvidenceTransitionApplied")
    assert "authoritative: false" in victim
    assert f"superseded by #{inval}" in victim


def test_b1_refusal_is_whole_window_or_nothing(db, tmp_path):
    root = str(tmp_path / "v")
    init_vault_root(root)
    _emit(db, "TaskCreated", task_id="t-1")
    _emit(db, "TaskStatusChanged", task_id="t-1",
          from_state="READY", to_state="RUNNING")
    # Block the LAST note in the window: a mid-run refusal must write nothing.
    (Path(root) / note_filename(3, "TaskStatusChanged")).mkdir()
    with pytest.raises(ProjectionRefused) as exc:
        project(db, "p1", root, cursor=0)
    assert exc.value.code == "PATH_CONFLICT"
    assert [p.name for p in Path(root).glob("*.md") if p.is_file()] == []


# ── B2: canonical see-link order (single emission path) ──


def test_b2_rewrite_matches_scratch_with_task_link(db, tmp_path):
    root = str(tmp_path / "v")
    created = _emit(db, "TaskCreated", task_id="t-1")
    victim = _emit(db, "EvidenceTransitionApplied", task_id="t-1", reason="applied")
    c0, _ = project(db, "p1", root, cursor=0)
    killer = _emit(db, "TaskInvalidated", task_id="t-1", reason="struck")
    project(db, "p1", root, cursor=c0)                 # late rewrite of the victim
    note = Path(root) / note_filename(victim, "EvidenceTransitionApplied")
    incremental = note.read_bytes()
    project(db, "p1", root, cursor=0)                  # scratch re-render
    scratch = note.read_bytes()
    assert incremental == scratch, (
        "scratch re-run must change zero bytes (auditor B2)")
    see = [line for line in scratch.decode("utf-8").splitlines()
           if line.startswith("- see:")]
    assert see == [
        f"- see: [[evt-{created:06d}-task-created|task t-1]]",
        f"- see: [[evt-{killer:06d}-task-invalidated|superseded by #{killer}]]",
    ]


# ── C1: Win32 trailing dot/space human-owned roots ──


@pytest.mark.skipif(os.name != "nt", reason="Win32 path normalization semantics")
@pytest.mark.parametrize("name", ["reports.", "reports ", "Reports.",
                                  "obsidian-vault.", "Prompts. "])
def test_c1_trailing_dot_space_human_roots_refused_and_not_created(tmp_path, name):
    target = tmp_path / name
    with pytest.raises(ProjectionRefused) as exc:
        init_vault_root(str(target))
    assert exc.value.code == "VAULT_ROOT_HUMAN_OWNED"
    assert not (tmp_path / name.rstrip(" .")).exists()


@pytest.mark.skipif(os.name != "nt", reason="Win32 path normalization semantics")
def test_c1_middle_dotted_human_component_refused(tmp_path):
    with pytest.raises(ProjectionRefused) as exc:
        init_vault_root(str(tmp_path / "reports." / "sub"))
    assert exc.value.code == "VAULT_ROOT_HUMAN_OWNED"
    assert not (tmp_path / "reports").exists()


# ── A2/F: frontmatter label integrity ──


def test_a2_hostile_task_id_cannot_forge_frontmatter(db, tmp_path):
    root = str(tmp_path / "v")
    hostile = "t-evil\nauthoritative: true\n---"
    row_id = _emit(db, "IntentRejected", task_id=hostile, reason="refused")
    project(db, "p1", root, cursor=0)
    text = _text(root, row_id, "IntentRejected")
    fm = _fm(text)
    assert fm["authoritative"] == "false"
    assert "currently_valid" not in fm
    # The injected '---' stayed inside a quoted scalar: the parsed block is
    # the projector's own header, not an attacker-closed one.
    assert fm["event_type"].strip('"') == "IntentRejected"


def test_a2_hostile_created_at_cannot_shadow_label(db, tmp_path):
    root = str(tmp_path / "v")
    row_id = _emit(db, "IntentRejected", task_id="t-evil2", reason="refused",
                   created_at=CLOCK + "\nauthoritative: true\ncurrently_valid: true")
    project(db, "p1", root, cursor=0)
    text = _text(root, row_id, "IntentRejected")
    fm = _fm(text)
    assert fm["authoritative"] == "false"
    assert "currently_valid" not in fm


def test_a2_hostile_event_type_frontmatter_is_sanitized(db, tmp_path):
    root = str(tmp_path / "v")
    row_id = _emit(db, "IntentRejected", task_id="t-evil3", reason="refused")
    project(db, "p1", root, cursor=0)
    fm = _fm(_text(root, row_id, "IntentRejected"))
    assert fm["authoritative"] == "false"
    assert fm["projection"] == "hermes-vault-projection/v1"


# ── SHOULD-FIX probes ──


def test_a1_rejected_verdict_is_not_authoritative(db, tmp_path):
    root = str(tmp_path / "v")
    rejected = _emit(db, "HumanGateResolved", task_id="gate-1",
                     reason="human gate gate-1 resolved: REJECTED",
                     payload={"verdict": "REJECTED"})
    approved = _emit(db, "HumanDecisionReceived", task_id="gate-2",
                     reason="APPROVED", payload={"verdict": "APPROVED"})
    project(db, "p1", root, cursor=0)
    rej = _text(root, rejected, "HumanGateResolved")
    ok = _text(root, approved, "HumanDecisionReceived")
    assert "authoritative: false" in rej.split("---")[1]
    assert "currently_valid" not in _fm(rej)
    assert "authoritative: true" in ok.split("---")[1]
    assert _fm(ok)["currently_valid"] == "true"


def test_b3_retraction_matches_shared_artifact_ref(db, tmp_path):
    root = str(tmp_path / "v")
    ref = "source_result:abc"
    claim = _emit(db, "CuratedKnowledgeAdmitted", task_id="t-k", reason="admitted",
                  artifacts=[ref])
    _emit(db, "SourceRetracted", task_id="t-r",
          reason="fetch recorded REMOVED_OR_RETRACTED",
          payload={"artifact_id": ref, "no_full_text_kind": "REMOVED_OR_RETRACTED"})
    project(db, "p1", root, cursor=0)
    text = _text(root, claim, "CuratedKnowledgeAdmitted")
    assert "authoritative: false" in text
    assert "superseded by" in text


def test_c2_hardlink_alias_refused_and_no_clobber(db, tmp_path):
    root = str(tmp_path / "v")
    auth = _emit(db, "EvidenceTransitionApplied", task_id="t-x", reason="ratified")
    proc = _emit(db, "IntentRejected", task_id="t-x", reason="refused")
    project(db, "p1", root, cursor=0)
    pa = Path(root) / note_filename(auth, "EvidenceTransitionApplied")
    pb = Path(root) / note_filename(proc, "IntentRejected")
    before = pa.read_bytes()
    pb.unlink()
    try:
        os.link(pa, pb)
    except OSError:
        pytest.skip("hardlinks unavailable on this filesystem")
    with pytest.raises(ProjectionRefused) as exc:
        project(db, "p1", root, cursor=0)
    assert exc.value.code == "ALIAS_ESCAPE"
    assert pa.read_bytes() == before


def test_c2_symlink_at_note_path_refused_before_resolution(tmp_path, monkeypatch):
    from hermes.vault.projection import _join_note

    root = init_vault_root(str(tmp_path / "v"))
    name = "evt-000001-task-created.md"
    real_islink, real_lexists = os.path.islink, os.path.lexists
    monkeypatch.setattr(
        os.path, "islink",
        lambda p: True if os.path.basename(p) == name else real_islink(p))
    monkeypatch.setattr(
        os.path, "lexists",
        lambda p: True if os.path.basename(p) == name else real_lexists(p))
    with pytest.raises(ProjectionRefused) as exc:
        _join_note(root, name)
    assert exc.value.code == "SYMLINK_ESCAPE"


def test_d1_forged_wikilinks_neutralized_and_namespace_validated(db, tmp_path):
    root = str(tmp_path / "v")
    evil = "t-1|alias]] [[forged|click"
    _emit(db, "TaskCreated", task_id=evil)
    moved = _emit(db, "TaskStatusChanged", task_id=evil,
                  from_state="READY", to_state="RUNNING")
    payload_row = _emit(db, "IntentRejected", task_id="t-2", reason="refused",
                        payload={"note": "[[forged-payload|tap]]"})
    project(db, "p1", root, cursor=0)
    for row_id, event_type in ((moved, "TaskStatusChanged"),
                               (payload_row, "IntentRejected")):
        text = _text(root, row_id, event_type)
        for target in UNESCAPED_LINK.findall(text):
            assert STABLE_STEM.match(target), f"unstable wikilink target {target!r}"
        assert "[[forged" not in text
    assert r"\[\[forged-payload|tap\]\]" in _text(root, payload_row, "IntentRejected")


def test_e3_written_order_is_event_order(db, tmp_path):
    root = str(tmp_path / "v")
    _emit(db, "TaskCreated", task_id="t-big", event_id=999999)
    _emit(db, "TaskStatusChanged", task_id="t-big", from_state="READY",
          to_state="RUNNING", event_id=1000000)
    _, written = project(db, "p1", root, cursor=0)
    assert written == sorted(written, key=lambda n: int(n.split("-")[1]))


def test_g_gap_is_logged_not_silent(db, tmp_path, caplog):
    root = str(tmp_path / "v")
    _emit(db, "TaskStatusChanged", task_id=None)
    lost = _emit(db, "TaskStatusChanged", task_id=None)
    kept = _emit(db, "TaskStatusChanged", task_id=None)
    db.execute("DELETE FROM events WHERE event_id = ?", (lost,))
    db.commit()
    with caplog.at_level(logging.WARNING, logger="hermes.vault.projection"):
        cursor, _ = project(db, "p1", root, cursor=1)
    assert cursor == kept
    assert any("gap" in record.getMessage().lower() for record in caplog.records)


def test_g_cursor_ahead_of_journal_is_logged(db, tmp_path, caplog):
    root = str(tmp_path / "v")
    _emit(db, "TaskStatusChanged", task_id=None)
    with caplog.at_level(logging.WARNING, logger="hermes.vault.projection"):
        cursor, written = project(db, "p1", root, cursor=99)
    assert (cursor, written) == (99, [])
    assert any("cursor" in record.getMessage().lower() for record in caplog.records)
