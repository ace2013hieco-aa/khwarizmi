"""Final end-to-end operator-loop verification of the shipped CLI loop.

Drives the SHIPPED CLI surfaces only:
  init -> project create -> run -> operator register -> gate resolve
  -> backup -> pause (post-backup mutation) -> restore -> audit

Every step asserts the ledger/mode/task state it must produce. The ONE
step the CLI cannot express is task ADMISSION (gateway-only by design —
the CLI exposes task *show*, never admission); that single intent is
seeded via the gateway and flagged explicitly.
"""
import os
import re
import sqlite3
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERMES = os.path.join(ROOT, ".venv", "Scripts", "hermes.exe")
SRC = os.path.join(ROOT, "src")

tmp = tempfile.mkdtemp(prefix="hermes_e2e_")
db = os.path.join(tmp, "hermes.db")
art = os.path.join(tmp, "artifacts")
bkp = os.path.join(tmp, "backups")
toml = os.path.join(tmp, "hermes.toml")

NL = chr(10)
FS = chr(47)  # forward slash — TOML-safe on Windows paths


def toml_path(p):
    return p.replace(chr(92), FS)


with open(toml, "w", encoding="utf-8") as fh:
    fh.write(
        "[sqlite]" + NL
        + 'database_path = "' + toml_path(db) + '"' + NL
        + 'backup_dir = "' + toml_path(bkp) + '"' + NL
        + "retain_last_n = 5" + NL
        + "[artifacts]" + NL
        + 'artifact_root = "' + toml_path(art) + '"' + NL)
print("# scratch: " + tmp + NL)


def cli(*args, expect=0):
    r = subprocess.run([HERMES, "--config", toml, *args],
                       capture_output=True, text=True, timeout=120)
    out = (r.stdout or "") + (r.stderr or "")
    tag = "OK" if r.returncode == expect else "FAIL"
    print("$ hermes " + " ".join(args) + "   [" + tag + " rc="
          + str(r.returncode) + "]")
    for line in out.strip().splitlines():
        print("    " + line)
    print()
    assert r.returncode == expect, (args, r.returncode, out)
    return out


# ── 1. init ─────────────────────────────────────────────────────────────
out = cli("init")
assert "schema v" in out, out
assert os.path.exists(db)
assert os.path.isdir(art)

# ── 2. project create ───────────────────────────────────────────────────
out = cli("project", "create", "E2E Test")
m = re.search(r"id: ([0-9a-f-]{36})", out)
assert m, out
project_id = m.group(1)
print("# project_id = " + project_id + NL)

# ── 3. seed the HUMAN_GATE task (gateway-only admission; flagged) ────────
sys.path.insert(0, SRC)
from hermes.core.intents import Intent, IntentKind  # noqa: E402
from hermes.persistence.database import connect  # noqa: E402
from hermes.research.gateway import apply_intent  # noqa: E402

conn = connect(db)
res = apply_intent(conn, Intent(
    kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
    project_id=project_id,
    payload={
        "task_id": "e2e-gate-1", "task_type": "HUMAN_GATE",
        "profile": "DIRECTOR", "idempotency_key": "e2e-gate-1-key",
        "iteration": 1, "spec": {"gate_requirement": "hypothesis"},
        "inputs": [], "outputs": [], "dependencies": [],
        "provenance": [], "cost_class": None, "concurrency_group": None,
        "max_retries": 3, "parent_task_id": None,
    }))
conn.close()
task_id = res.entity_id
print("# seeded task_id = " + task_id
      + " (gateway admission — the one step the CLI cannot express)" + NL)

# ── 4. run — parks the gate, project flips AWAITING_HUMAN ───────────────
out = cli("run", project_id, "--ticks", "1")
assert "waiting on human" in out, out
out = cli("project", "show", project_id)
assert "AWAITING_HUMAN" in out, out
out = cli("task", "show", task_id)
assert "WAITING_HUMAN" in out, out
print("# LEDGER: gate parked at WAITING_HUMAN, project AWAITING_HUMAN" + NL)

# ── 5. operator register (A4 bootstrap) ─────────────────────────────────
cli("operator", "register", "op-1", "--token", "e2e-token",
    "--name", "E2E Operator")

# ── 6. gate resolve — unratified first (fail closed), then ratified ──────
out = cli("gate", "resolve", task_id, "--verdict", "APPROVED",
          "--operator", "op-1", "--token", "wrong-token", expect=1)
assert "OPERATOR" in out, out
print("# LEDGER: unratified verdict refused (OPERATOR)" + NL)

out = cli("gate", "resolve", task_id, "--verdict", "APPROVED",
          "--operator", "op-1", "--token", "e2e-token")
assert "resolved" in out, out
out = cli("task", "show", task_id)
assert "SUCCEEDED" in out, out
out = cli("project", "show", project_id)
assert "ACTIVE" in out, out
print("# LEDGER: gate SUCCEEDED, project back to ACTIVE" + NL)

# ── 7. backup (B6: DB + artifact-store snapshot) ─────────────────────────
out = cli("backup")
m = re.search(r"Backup written: (.+)", out)
assert m, out
backup_path = m.group(1).strip()
assert os.path.exists(backup_path), backup_path
print("# backup = " + backup_path + NL)

# ── 8. post-backup mutation: pause the project ───────────────────────────
cli("pause", project_id)
out = cli("project", "show", project_id)
assert "PAUSED" in out, out
print("# LEDGER: project PAUSED after backup" + NL)

# ── 9. restore — atomic swap; DB + ledger roll back to the snapshot ──────
cli("restore", backup_path)
out = cli("project", "show", project_id)
assert "ACTIVE" in out, out
print("# LEDGER: restore rolled the project back to ACTIVE (pre-pause)" + NL)

# ── 10. audit — the append-only journal tells the story ──────────────────
out = cli("audit", "--project", project_id)
assert "HumanGateResolved" in out, out
assert "GatePassed" in out, out
assert "ModeChanged" in out, out
assert "ProjectResumed" in out, out
# the pause happened AFTER the backup; the restored ledger must not
# contain it — the rollback is real, not just a status refresh
assert "-> PAUSED" not in out, out
assert "PAUSED" not in out, out
print("# LEDGER: audit shows HumanGateResolved + GatePassed + lifecycle;" + NL
      + "#         the post-backup pause event is absent — restore rolled" + NL
      + "#         the journal back too" + NL)

# ── 11. restore under a live lease is refused (F16) ──────────────────────
from hermes.core import utc_now  # noqa: E402

lease_conn = sqlite3.connect(db)
lease_conn.execute(
    "INSERT OR REPLACE INTO scheduler_lock "
    "(id, owner, locked_at, generation) VALUES (0, 'controller-e2e', ?, 0)",
    (utc_now(),))
lease_conn.commit()
out = cli("restore", backup_path, expect=1)
assert "live scheduler lease" in out, out
lease_conn.close()
print("# LEDGER: restore refused under a live lease (F16)" + NL)

print("E2E OPERATOR-LOOP SCENARIO PASSED")
