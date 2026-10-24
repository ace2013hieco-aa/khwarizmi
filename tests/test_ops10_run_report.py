"""OPS-10 — a run report the operator can read (closes F2).

The report is written at the live run boundary, from the run's own surfaces:
stage results, the model ledger, refusals with bounded reply excerpts, notes,
and the exact vector line the CLI printed. It is a diagnostic artifact, never a
record. These tests pin the operator's four promises: the refusal says why, the
key is absent, drain-only writes nothing, and the file stays bounded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hermes.cli import main
from hermes.config import ConfigError, load_config
from hermes.run_report import write_run_report
from tests.test_ops1_live_cli import (
    DRAIN_ONLY_OUTPUT,
    KEY,
    _anthropic_reply,
    _gate_task,
    _install_transport,
    _methodology_task,
    _project,
    _proposal_reply,
    _ScriptedTransport,
)

RUN_DIR = "reports"


def _config(tmp_path: Path, db: Path, *,
            tiers: dict[str, str] | None = None,
            run_dir: Path | None = None) -> Path:
    cfg = tmp_path / "hermes.toml"
    body = f'[sqlite]\ndatabase_path = "{db.as_posix()}"\n'
    if tiers:
        body += "[model_tiers]\n" + "".join(
            f'{tier} = "{ref}"\n' for tier, ref in tiers.items())
    if run_dir is not None:
        body += f'[reporting]\nrun_dir = "{run_dir.as_posix()}"\n'
    cfg.write_text(body, encoding="utf-8")
    return cfg


def _both_forms_reply(echo: str = "") -> str:
    """A reply that drafts, then fails the runtime's mutually-exclusive rule."""
    rationale = "both forms" + (f" {echo}" if echo else "")
    return json.dumps({
        "kind": "INSERT_TASK",
        "rationale": rationale,
        "payload": {"spec": {"goal": "stage output"}},
        "proposals": [{
            "kind": "INSERT_TASK",
            "rationale": rationale,
            "payload": {"spec": {"goal": "stage output"}},
        }],
    })


def _report_files(run_dir: Path) -> list[Path]:
    return sorted(run_dir.glob("*.json"))


# ── 1. a failing run says why ──


def test_a_failing_live_run_writes_a_report_with_the_refusal(
        tmp_path: Path, capsys: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    _install_transport(monkeypatch, _ScriptedTransport(_anthropic_reply(
        _both_forms_reply(echo=KEY))))
    db = _project(tmp_path, _methodology_task())
    report_dir = tmp_path / RUN_DIR
    cfg = _config(tmp_path, db, tiers={"m": "anthropic:test-model"},
                  run_dir=report_dir)

    rc = main(["--config", str(cfg), "run", "p1", "--ticks", "5"])
    captured = capsys.readouterr()

    assert rc == 0
    assert "report: " in captured.out
    assert "report: unavailable" not in captured.out
    files = _report_files(report_dir)
    assert len(files) == 1

    raw = files[0].read_text(encoding="utf-8")
    report = json.loads(raw)

    # The header says what the file is (and is not).
    assert report["report"] == "diagnostic-run-report"
    assert report["not_a_record"] is True
    assert "never read back as authority" in report["disclaimer"]
    assert report["mode"] == "live"
    assert report["project_id"] == "p1"
    assert report["ticks"] >= 1

    # Stage and ledger surfaces are present.
    assert report["stages"]
    stage = report["stages"][0]
    assert stage["profile"] == "planner"
    assert stage["task_id"].endswith(":QUESTION")
    assert stage["admissions"] == 0
    assert report["model_attempts"]
    for row in report["model_attempts"]:
        assert set(row) >= {"tier", "provider", "model", "outcome",
                            "tokens_in", "tokens_out", "duration_ms"}

    # The thing that was missing: the code, the detail, and the reply excerpt.
    codes = [refusal["code"] for refusal in report["refusals"]]
    assert "MALFORMED_PAYLOAD" in codes
    details = " ".join(refusal["detail"] for refusal in report["refusals"])
    assert "both the single-proposal and the multi-proposal form" in details
    assert any(refusal["stage"] == "QUESTION"
               and refusal["profile"] == "planner"
               and refusal["tick"] >= 1
               and "proposals" in refusal["excerpt"]
               for refusal in report["refusals"])
    assert report["quarantine_reason"]
    assert report["terminal_state"] == "QUARANTINED"

    # The vector line is the CLI's, byte for byte.
    vector_line = next(
        line for line in captured.out.splitlines() if line.startswith("vector:"))
    assert report["vector"] == vector_line

    # The key-absence proof: the reply echoed the injected key; the report
    # redacted it, and the raw file never contains it.
    assert KEY not in raw
    assert "<redacted>" in raw


# ── 2. a report failure never fails the run ──


def test_an_unwritable_report_dir_prints_unavailable_and_keeps_the_run(
        tmp_path: Path, capsys: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    _install_transport(monkeypatch, _ScriptedTransport(
        _anthropic_reply(_proposal_reply())))
    db = _project(tmp_path, _methodology_task())
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    cfg = _config(tmp_path, db, tiers={"m": "anthropic:test-model"},
                  run_dir=blocker)

    rc = main(["--config", str(cfg), "run", "p1", "--ticks", "2"])
    captured = capsys.readouterr()

    assert rc == 0
    assert "Model plane: live" in captured.out
    assert "report: unavailable (" in captured.out
    assert "vector:" in captured.out


# ── 3. drain-only writes nothing and stays byte-identical ──


def test_drain_only_writes_no_report(
        tmp_path: Path, capsys: Any, monkeypatch: Any) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db = _project(tmp_path, _gate_task(), _methodology_task())
    report_dir = tmp_path / RUN_DIR
    cfg = _config(tmp_path, db, tiers={"m": "anthropic:test-model"},
                  run_dir=report_dir)

    rc = main(["--config", str(cfg), "run", "p1", "--ticks", "5",
               "--drain-only"])
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out == DRAIN_ONLY_OUTPUT
    assert not _report_files(report_dir)


# ── 4. the file is bounded and counted ──


def test_many_refusals_are_truncated_with_a_counted_marker(
        tmp_path: Path) -> None:
    report: dict[str, Any] = {
        "report": "diagnostic-run-report",
        "version": 1,
        "not_a_record": True,
        "disclaimer": "diagnostic",
        "run_id": "run_cap",
        "project_id": "p-cap",
        "started_at": "2026-10-24T00:00:00+00:00",
        "generated_at": "2026-10-24T00:00:01+00:00",
        "mode": "live",
        "ticks": 1,
        "terminal_state": "FAILED",
        "quarantine_reason": "poison task quarantined",
        "stages": [],
        "model_attempts": [],
        "refusals": [{
            "code": "MALFORMED_PAYLOAD",
            "detail": "x" * 500,
            "profile": "planner",
            "tick": 1,
            "stage": "QUESTION",
            "excerpt": "y" * 2_000,
        } for _ in range(1_000)],
        "notes": [],
        "vector": "vector: runs=1 admitted=0",
        "truncated": False,
        "stages_omitted": 0,
        "model_attempts_omitted": 0,
        "refusals_omitted": 0,
        "notes_omitted": 0,
    }

    path = write_run_report(tmp_path / "cap.json", report, max_bytes=4_096)
    raw = path.read_bytes()

    assert len(raw) <= 4_096
    fitted = json.loads(raw)
    assert fitted["truncated"] is True
    assert fitted["refusals_omitted"] > 0


# ── 5. the config path is absolute ──


def test_a_relative_report_dir_is_refused(tmp_path: Path) -> None:
    cfg = tmp_path / "hermes.toml"
    cfg.write_text('[reporting]\nrun_dir = "relative/reports"\n',
                   encoding="utf-8")
    with pytest.raises(ConfigError, match="absolute"):
        load_config(cfg)
