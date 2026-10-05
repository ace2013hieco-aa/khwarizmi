"""Hermes first run: init -> doctor -> project -> run -> status -> audit.

Uses ONLY the public CLI surface (hermes.cli.main) against a temporary
config/database. No persistence internals, no intents constructed by
hand, no network. Deterministic: an empty project runs zero ticks of
work and every command exits 0.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

from hermes.cli import main


def run(argv: list[str]) -> int:
    rc = main(argv)
    print(f"$ hermes {' '.join(argv[-2:])}  -> exit {rc}")
    assert rc == 0, argv
    return rc


def run_capture(argv: list[str]) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(argv)
    print(f"$ hermes {' '.join(argv[-2:])}  -> exit {rc} (captured)")
    assert rc == 0, argv
    return buf.getvalue()


def main_example() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="hermes_first_run_"))
    cfg = tmp / "hermes.toml"
    cfg.write_text(
        "[sqlite]\n"
        f'database_path = "{(tmp / "hermes.db").as_posix()}"\n'
        "[artifacts]\n"
        f'artifact_root = "{(tmp / "artifacts").as_posix()}"\n',
        encoding="utf-8",
    )
    conf = ["--config", str(cfg)]
    run([*conf, "init"])
    run([*conf, "doctor", "--json"])
    run([*conf, "project", "create", "demo"])
    # `project create <name>` mints a UUID id (cli.py); resolve it via
    # the stable status --json schema — still the public CLI surface.
    status_doc = json.loads(run_capture([*conf, "status", "--json"]))
    project_id = status_doc["projects"][0]["project_id"]
    print(f"resolved project id: {project_id}")
    run([*conf, "project", "show", project_id])
    run([*conf, "run", project_id])
    run([*conf, "status", "--json"])
    run([*conf, "audit", "--project", project_id, "--json"])
    print(f"workspace: {tmp} (safe to delete)")


if __name__ == "__main__":
    sys.exit(main_example())
