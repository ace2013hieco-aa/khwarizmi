"""VAULT-1 regression battery — the note body goes through the output boundary.

EXT-5 closed the operator's *terminal* lines (``src/hermes/output.py``) but
deliberately left vault note bodies raw: ``_single_line``/``_task_alias``
stripped newlines and wikilinks only, so an ANSI/OSC/C1/DEL/Bidi_Control byte
in a journal column reached the ``.md`` file — and therefore the terminal of
whoever opens that note. This battery pins the body boundary:

- every transcribed field is escaped visibly — never dropped, never refused
  (a derived note must always render);
- the alias of a see-link is escaped like any other body text;
- the journal row is never rewritten (a rendering boundary is not a write
  path — the single mutation path is untouched);
- the manifest digest is taken over the *escaped* body, so the journal and the
  derived view agree by construction, and a pre-VAULT-1 manifest is refused;
- benign content is byte-identical to the pre-boundary render (``scrub`` is a
  pure per-code-point map, so ordinary text moves zero digest bytes);
- the renderer census: both body renderers call the shared boundary and the
  boundary's fail-closed ``_guard`` is deliberately NOT used on the note path.

Prohibited-claims discipline: this pins a display transform. It makes no claim
about the validity of any content it displays.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from hermes.output import FORBIDDEN
from hermes.vault import projection as projection_module
from hermes.vault.manifest import (
    MANIFEST_FILENAME,
    manifest_bytes,
    read_manifest,
    verify_manifest,
)
from hermes.vault.projection import note_filename, project, write_cursor

CLOCK = "2026-01-01T00:00:00.000000+00:00"

# One of each forbidden class: C0 (ESC/BEL), a forged line via a real
# newline, an OSC title-set, plus C1, DEL and a Bidi_Control override.
ESC = "\x1b"
BEL = "\x07"
C1 = "\x9b"
DEL = "\x7f"
RLO = "\u202e"
HOSTILE = (ESC + "[31mRED" + BEL + "\n  Project: forged"
           + ESC + "]0;pwn" + BEL)


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
          caused_by="body-test", reason="", payload=None,
          raw_payload_json=None):
    """One journal row (raw ``payload_json`` lets a test store corrupt bytes)."""
    if task_id is not None:
        conn.execute(
            "INSERT OR IGNORE INTO tasks (task_id, project_id, task_type, "
            "idempotency_key, created_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, "p1", "AGENT_TASK", str(task_id) + "-key", CLOCK),
        )
    payload_json = raw_payload_json
    if payload_json is None and payload is not None:
        payload_json = json.dumps(payload, sort_keys=True)
    row = conn.execute(
        "INSERT INTO events (event_type, project_id, task_id, from_state, "
        "to_state, caused_by, reason, payload_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_type, "p1", task_id, from_state, to_state, caused_by, reason,
         payload_json, CLOCK),
    )
    conn.commit()
    return row.lastrowid


def _project(conn, root, cursor=0):
    """Project + persist the cursor (the production run pair)."""
    new_cursor, written = project(conn, "p1", root, cursor=cursor)
    write_cursor(root, new_cursor)
    return new_cursor, written


def _note(root, row_id, event_type):
    return (Path(root) / note_filename(row_id, event_type)).read_text("utf-8")


def _has_forbidden(text):
    """True when a single line carries a code point the boundary escapes."""
    return any(ord(char) in FORBIDDEN for char in text)


def _is_clean(text):
    """Every line of the note is free of forbidden code points.

    The body's own newlines are the projector's structure (the writer used
    ``newline="\n"``); a data-borne newline would surface as a forbidden
    code point inside a line instead.
    """
    return all(not _has_forbidden(line) for line in text.split("\n"))


def _vault_files(root):
    return {path.name: path.read_bytes()
            for path in sorted(Path(root).iterdir()) if path.is_file()}


# ── end to end: the note body ──

def test_hostile_reason_is_escaped_visibly_in_the_note(db, tmp_path):
    root = str(tmp_path / "v")
    row = _emit(db, "IntentRejected", reason=HOSTILE)
    project(db, "p1", root, cursor=0)
    text = _note(root, row, "IntentRejected")

    assert _is_clean(text)                      # no raw control byte survives
    assert "\\x1b[31mRED" in text                # escaped and visible instead
    assert "\\x07" in text
    assert "\\x1b]0;pwn" in text                # the OSC introducer as text
    # a real newline in the row stays ONE transcribed line (A2/F)
    assert not any(line.startswith("  Project:") for line in text.splitlines())


def test_every_transcribed_field_is_covered(db, tmp_path):
    root = str(tmp_path / "v")
    row = _emit(db, "TaskStatusChanged", task_id="t" + ESC + "[0m",
                from_state="A" + C1, to_state="B" + DEL,
                caused_by="cb" + RLO, reason="r" + ESC)
    project(db, "p1", root, cursor=0)
    text = _note(root, row, "TaskStatusChanged")

    assert _is_clean(text)
    for visible in ("\\x1b", "\\x9b", "\\x7f", "\\u202e"):
        assert visible in text


def test_corrupt_payload_text_is_escaped(db, tmp_path):
    """A payload that is not JSON is transcribed raw — and escaped like the rest."""
    root = str(tmp_path / "v")
    row = _emit(db, "IntentRejected", reason="refused",
                raw_payload_json="not-json " + ESC + "[2J")
    project(db, "p1", root, cursor=0)
    text = _note(root, row, "IntentRejected")

    assert _is_clean(text)
    assert "\\x1b[2J" in text


def test_hostile_task_alias_in_a_see_link_is_escaped(db, tmp_path):
    """The see-link alias is rendered text too (link syntax folded, bytes escaped)."""
    root = str(tmp_path / "v")
    hostile = "t-evil" + ESC + "[31m|alias]] [[forged|click"
    _emit(db, "TaskCreated", task_id=hostile)
    row = _emit(db, "TaskStatusChanged", task_id=hostile,
                from_state="READY", to_state="RUNNING")
    project(db, "p1", root, cursor=0)
    text = _note(root, row, "TaskStatusChanged")

    assert _is_clean(text)
    # the alias folds link syntax to spaces but keeps the escaped byte visible
    assert "\\x1b" in text and "31m" in text
    assert "[[forged" not in text
    assert "|task " in text


def test_hostile_body_never_refuses_the_note(db, tmp_path):
    """Escape visibly, never refuse: even a hostile event_type still renders."""
    root = str(tmp_path / "v")
    event_type = "Weird" + ESC + "[1m"
    row = _emit(db, event_type, task_id="t" + BEL, reason=HOSTILE)
    cursor, written = _project(db, root)
    assert cursor == row
    assert note_filename(row, event_type) in written

    text = _note(root, row, event_type)
    assert _is_clean(text)
    assert "\\x1b[1m" in text


# ── the boundary is a rendering surface, never a write path ──

def test_the_boundary_never_rewrites_the_journal(db, tmp_path):
    root = str(tmp_path / "v")
    _emit(db, "IntentRejected", task_id="t" + ESC, reason=HOSTILE)
    before = [dict(row) for row in db.execute(
        "SELECT * FROM events ORDER BY event_id").fetchall()]

    project(db, "p1", root, cursor=0)

    after = [dict(row) for row in db.execute(
        "SELECT * FROM events ORDER BY event_id").fetchall()]
    assert after == before
    stored = db.execute(
        "SELECT reason FROM events WHERE event_type = 'IntentRejected'"
    ).fetchone()["reason"]
    assert stored == HOSTILE                    # the row keeps its own bytes


# ── the manifest claims the ESCAPED bytes ──

def test_manifest_verifies_the_escaped_body(db, tmp_path):
    root = str(tmp_path / "v")
    row = _emit(db, "IntentRejected", task_id="t" + RLO, reason=HOSTILE)
    _project(db, root)

    note = Path(root) / note_filename(row, "IntentRejected")
    digest = hashlib.sha256(note.read_bytes()).hexdigest()
    manifest = read_manifest(root)
    entry = next(e for e in manifest["notes"] if e["event_id"] == row)
    assert entry["sha256"] == digest

    report = verify_manifest(db, "p1", root)
    assert report.ok, report.lines()
    assert report.counts == {}
    assert "NOTE_DIGEST_DIVERGES" not in report.counts


def test_manifest_digest_is_over_the_escaped_body(db, tmp_path):
    """A pre-VAULT-1 manifest digest (raw bytes) is refused, not accepted.

    The raw digest is obtained from the projector's own renderer with the
    boundary disabled — a sanctioned recomputation, never hand-written JSON.
    """
    root = str(tmp_path / "v")
    row = _emit(db, "IntentRejected", task_id="t" + ESC, reason=HOSTILE)
    _project(db, root)

    with pytest.MonkeyPatch.context() as unbounded:
        unbounded.setattr(projection_module, "scrub", lambda text: text)
        raw_bodies = {event_id: body for event_id, _name, body
                      in projection_module._plan_range(db, "p1", row)}
    raw_digest = hashlib.sha256(raw_bodies[row].encode("utf-8")).hexdigest()
    assert raw_digest != hashlib.sha256(
        (Path(root) / note_filename(row, "IntentRejected")).read_bytes()
    ).hexdigest()

    manifest = read_manifest(root)
    for entry in manifest["notes"]:
        if entry["event_id"] == row:
            entry["sha256"] = raw_digest
    (Path(root) / MANIFEST_FILENAME).write_bytes(manifest_bytes(manifest))

    report = verify_manifest(db, "p1", root)
    assert not report.ok
    diverged = [f for f in report.findings
                if f.code == "NOTE_DIGEST_DIVERGES"]
    assert diverged and diverged[0].event_ids == (row,)


# ── benign content moves zero bytes ──

def test_scrub_is_identity_on_benign_bodies(db, tmp_path):
    """Boundary on vs. off over ordinary rows: byte-identical vaults."""
    _emit(db, "TaskCreated", task_id="t-1")
    _emit(db, "TaskStatusChanged", task_id="t-1", from_state="READY",
          to_state="RUNNING")
    _emit(db, "HumanDecisionReceived", task_id="gate-1", reason="APPROVED",
          payload={"verdict": "APPROVED"})
    _emit(db, "IntentRejected", task_id="t-2", reason="MALFORMED_PAYLOAD")

    bounded_root = str(tmp_path / "bounded")
    project(db, "p1", bounded_root, cursor=0)

    with pytest.MonkeyPatch.context() as unbounded:
        unbounded.setattr(projection_module, "scrub", lambda text: text)
        raw_root = str(tmp_path / "raw")
        project(db, "p1", raw_root, cursor=0)

    assert _vault_files(raw_root) == _vault_files(bounded_root)


# ── the renderer census ──

def _enclosing_function(tree: ast.AST, target: ast.AST) -> str:
    """Name of the innermost function containing ``target`` ("<module>" else)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) \
                and any(child is target for child in ast.walk(node)):
            return node.name
    return "<module>"


def test_census_both_body_renderers_route_through_the_boundary():
    """The census drift guard: two body renderers, both on the boundary.

    A new renderer that transcribes journal bytes into a note body must be
    added here *and* routed through ``scrub`` — and the boundary's fail-closed
    ``_guard`` must never appear on the note path (a note always renders).
    """
    source = Path(projection_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported = {
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "hermes.output"
        for alias in node.names
    }
    assert imported == {"scrub"}

    scrub_callers = set()
    refusing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id == "scrub":
            scrub_callers.add(_enclosing_function(tree, node))
        if node.func.id in {"_guard", "emit", "emit_lines"}:
            refusing.append((node.func.id, node.lineno))

    assert scrub_callers == {"_single_line", "_task_alias"}
    # The boundary's fail-closed guard is deliberately off the note path:
    # notes escape visibly and always render.
    assert refusing == []
