"""EXT-5 / triage item R3 — the CLI emit boundary, end to end.

Pins:

- a stored payload carrying ANSI/OSC bytes and a forged-line attempt
  reaches the terminal escaped and forges no line, while the stored row
  stays byte-identical (a display boundary never rewrites the journal);
- every column on the printed line is covered, not just `reason`;
- `--json` keeps its documented contract byte for byte;
- a line the boundary cannot prove safe refuses loudly instead of being
  written raw;
- the census: no operator-facing CLI module prints around the boundary.

Prohibited-claims discipline: these tests pin a display transform. They
make no claim about the validity of any displayed content.
"""
from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path

import pytest

from hermes import output
from hermes.cli import main
from hermes.output import FORBIDDEN, REFUSAL_TEXT

ESC = "\x1b"
BEL = "\x07"
# The hostile payload used end to end: an ANSI colour run, a BEL, a forged
# output line, and an OSC title-set — exactly the classes R3 names.
HOSTILE = ESC + "[31mRED" + BEL + "\n  Project: forged" + ESC + "]0;pwn" + BEL


def _has_forbidden(text: str) -> bool:
    """True when a single line carries a forbidden code point."""
    return any(ord(char) in FORBIDDEN for char in text)


def _output_is_clean(text: str) -> bool:
    """Terminal-safety of a whole capture: every emitted LINE is safe.

    Inter-line newlines are the CLI's own structure; a data-borne newline
    would show up as a forbidden code point inside a line.
    """
    return all(not _has_forbidden(line) for line in text.split("\n"))


def _config(tmp_path: Path, db_path: Path) -> Path:
    cfg = tmp_path / "hermes.toml"
    cfg.write_text(
        "\n".join(["[sqlite]", f'database_path = "{db_path.as_posix()}"', ""]),
        encoding="utf-8")
    return cfg


def _project(tmp_path: Path) -> tuple[Path, Path, str]:
    """A migrated DB with one project, built through the real CLI."""
    db_path = tmp_path / "hermes.db"
    cfg = _config(tmp_path, db_path)
    assert main(["--config", str(cfg), "init"]) == 0
    assert main(["--config", str(cfg), "project", "create", "p1"]) == 0
    conn = sqlite3.connect(str(db_path))
    try:
        project_id = conn.execute(
            "SELECT project_id FROM projects").fetchone()[0]
    finally:
        conn.close()
    return cfg, db_path, project_id


def _insert_event(db_path: Path, project_id: str, **fields: str) -> None:
    """Insert a journal row straight into the DB.

    `reason`/`caused_by` are NOT validated by `validate_event` (it checks
    event_type, payload size and secrets only), so this is how a payload
    carrying control bytes is produced — the R3 producer.
    """
    row: dict[str, str] = {
        "event_type": "HostileEvent",
        "project_id": project_id,
        "correlation_id": "",
        "created_at": "2026-01-01T00:00:00Z",
    }
    row.update(fields)
    columns = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            f"INSERT INTO events ({columns}) VALUES ({marks})",
            tuple(row.values()))
        conn.commit()
    finally:
        conn.close()


def _stored_reason(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT reason FROM events WHERE event_type='HostileEvent'"
        ).fetchone()[0]
    finally:
        conn.close()


# ── end to end: the CLI ──

def test_audit_escapes_a_stored_control_byte_payload(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The R3 residual: `reason` reaches the terminal escaped, never raw."""
    cfg, db_path, project_id = _project(tmp_path)
    _insert_event(db_path, project_id, reason=HOSTILE)
    capsys.readouterr()

    assert main(["--config", str(cfg), "audit"]) == 0
    out = capsys.readouterr().out

    assert ESC not in out and BEL not in out            # no raw emit
    assert "\\x1b[31mRED" in out                        # escaped and visible
    assert "\\x07" in out
    assert "\\x0a" in out
    assert _output_is_clean(out)
    # the forged line never becomes a line of the operator's output
    assert not any(line.startswith("  Project:") for line in out.split("\n"))
    # the stored bytes are untouched — display never rewrites the journal
    assert _stored_reason(db_path) == HOSTILE


def test_arabic_letter_mark_never_reaches_the_console_raw(
        tmp_path: Path, capfdbinary: pytest.CaptureFixture[bytes]) -> None:
    """EXT-5-FIX: U+061C (ALM) is escaped — its raw UTF-8 bytes never land.

    Byte-level proof on the real console file descriptor: the raw ALM
    encoding ``0xD8 0x9C`` must not appear anywhere in the captured
    output, while the visible ``\\u061c`` spelling must, and the stored
    row stays byte-identical (a display boundary never rewrites the
    journal).
    """
    cfg, db_path, project_id = _project(tmp_path)
    reason = "alm:\u061c:end"
    _insert_event(db_path, project_id, reason=reason)
    capfdbinary.readouterr()

    assert main(["--config", str(cfg), "audit"]) == 0
    raw = capfdbinary.readouterr().out

    assert b"\xd8\x9c" not in raw             # no raw ALM bytes on the console
    assert b"\\u061c" in raw                  # escaped and visible instead
    assert b"alm:" in raw and b":end" in raw
    assert _stored_reason(db_path) == reason  # display never rewrites the row


def test_audit_state_columns_are_scrubbed_too(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Every column on the printed line is covered, not just `reason`."""
    cfg, db_path, project_id = _project(tmp_path)
    _insert_event(db_path, project_id, reason="", from_state=f"A{ESC}[0m",
                  to_state=f"B{BEL}")
    capsys.readouterr()

    assert main(["--config", str(cfg), "audit"]) == 0
    out = capsys.readouterr().out
    assert _output_is_clean(out)
    assert "\\x1b[0m" in out and "\\x07" in out


def test_cli_refuses_loudly_when_a_line_cannot_be_proven_safe(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """With the scrubber broken, the CLI refuses instead of emitting raw."""
    cfg, db_path, project_id = _project(tmp_path)
    _insert_event(db_path, project_id, reason=f"hostile {ESC}[31m")
    capsys.readouterr()
    monkeypatch.setattr(output, "scrub", lambda text: text)

    assert main(["--config", str(cfg), "audit"]) == 1
    captured = capsys.readouterr()
    assert REFUSAL_TEXT in captured.err
    assert ESC not in captured.out
    # the safe lines before the offending one ARE emitted (no truncation of
    # the audit; the boundary refuses at the unsafe line, loudly)
    assert "Event journal (" in captured.out


def test_audit_json_keeps_the_documented_json_contract(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--json` was already escape-safe; the boundary must not change it."""
    cfg, db_path, project_id = _project(tmp_path)
    _insert_event(db_path, project_id, reason=f"e{ESC}[31m")
    capsys.readouterr()

    assert main(["--config", str(cfg), "audit", "--json"]) == 0
    out = capsys.readouterr().out
    assert _output_is_clean(out)
    doc = json.loads(out)  # still valid JSON
    assert "HostileEvent" in [e["event_type"] for e in doc["events"]]
    assert out == json.dumps(doc, indent=2, sort_keys=True) + "\n"


def test_status_and_doctor_keep_their_benign_output_shape(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Benign content is untouched: structure and em-dash survive."""
    cfg, _db, _pid = _project(tmp_path)
    capsys.readouterr()

    assert main(["--config", str(cfg), "status"]) == 0
    status_out = capsys.readouterr().out
    assert "Project: p1" in status_out
    assert _output_is_clean(status_out)

    assert main(["doctor"]) == 0
    doctor_out = capsys.readouterr().out
    assert "—" in doctor_out             # the CLI's own em-dash is untouched
    assert len(doctor_out.split("\n")) > 10  # multi-line table preserved
    assert _output_is_clean(doctor_out)


def test_platform_cli_output_goes_through_the_boundary(
        capsys: pytest.CaptureFixture[str]) -> None:
    """The second CLI (R7's separate operator entry) uses the same boundary."""
    from hermes.eval.platform_cli import main as platform_main

    rc = platform_main(["auth", "--actor", f"op{ESC}[31m", "--token", "a" * 32])
    out = capsys.readouterr().out
    assert rc in (0, 1)
    assert _output_is_clean(out)


# ── the census ──

# The R3 emit census: every operator-facing CLI module emits through the
# boundary. A new emit site is a deliberate census change — update the
# count here with it.
_EMIT_CENSUS = {
    "src/hermes/cli.py": 94,
    "src/hermes/eval/platform_cli.py": 15,
    "src/hermes/eval/matrix.py": 1,
}


@pytest.mark.parametrize("relative,expected", sorted(_EMIT_CENSUS.items()))
def test_census_no_cli_module_prints_around_the_boundary(
        relative: str, expected: int) -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)

    bare_prints = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]
    assert bare_prints == [], (
        f"{relative} writes around the boundary at line(s) {bare_prints}")

    sites = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"emit", "emit_lines"}
    ]
    assert len(sites) == expected, (
        f"{relative}: {len(sites)} boundary site(s), census says {expected}")
