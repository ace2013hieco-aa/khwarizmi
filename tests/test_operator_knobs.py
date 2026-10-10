"""R-3 operator knobs: the deadline + rate caps read from operator config.

Parked item (``docs/archive/CERT_GATE_RERUN_CERTIFICATION_2026-10-04.md`` §6,
"operator knobs" row): the narrow-only builders and the ``[autonomy_caps]``
schema existed, but no production caller handed the loaded config in — so the
300 s dispatch deadline (``SourcePolicy``) and the D5 rate profiles were
effectively code-pinned on the operator surface. The CLI is that handoff
(``cli._run`` → ``Controller(autonomy_operator=cfg.autonomy_caps)``); the
live-fetch wiring reads the same section for the D5 rate profiles.

The narrow-only matrix is pinned here END TO END over a REAL hermes.toml:

* tighten — applies (observable at the CLI and at the limiter),
* widen — refused loudly with the named code ``KNOB_WIDEN_REFUSED``,
* absent — byte-identical to the code-owned defaults (golden).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hermes.artifacts.store import ArtifactStore
from hermes.cli import main
from hermes.config import AutonomyCapsConfig, default_config, load_config
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ArtifactRepository, ProjectRepository
from hermes.research.autonomy_caps import (
    DEFAULT_OVERALL_DISPATCH_DEADLINE_S,
    KNOB_WIDEN_REFUSED,
    build_envelope,
    build_loop_threshold,
    build_rate_profiles,
    build_retry_caps,
    build_wallclock,
)
from hermes.research.controller import Controller
from hermes.research.live_fetch import (
    build_live_fetch_wiring,
    rate_profiles_from_autonomy,
    source_policy_from_autonomy,
)

CLOCK = "2026-01-01T00:00:00+00:00"
REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_CONFIG = REPO_ROOT / "config" / "hermes.toml"

_BUILDERS = (
    build_envelope,
    build_wallclock,
    build_retry_caps,
    build_loop_threshold,
    build_rate_profiles,
)


def _seed_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "hermes.db"
    conn = connect(str(db_path))
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create("p1", "Test")
    conn.close()
    return db_path


def _write_config(tmp_path: Path, autonomy: str = "", *,
                  name: str = "hermes.toml") -> Path:
    """Write a REAL hermes.toml; ``autonomy`` is the [autonomy_caps] body."""
    body = ("[sqlite]\n"
            f'database_path = "{(tmp_path / "hermes.db").as_posix()}"\n')
    if autonomy:
        body += "[autonomy_caps]\n" + autonomy
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _public_resolve(_host: str) -> tuple[str, ...]:
    return ("93.184.216.34",)


# ── tighten: the operator value reaches the production surfaces ──


def test_tightened_deadline_applies_at_the_cli(tmp_path, capsys, monkeypatch):
    """The config value rides the CLI handoff into the controller's wallclock."""
    _seed_db(tmp_path)
    cfg_path = _write_config(tmp_path, "overall_deadline_seconds = 30.0\n")
    seen: dict[str, object] = {}

    def capture(self, *args, **kwargs):
        seen["deadline_s"] = self._wallclock.dispatch_deadline_s
        seen["per_tick_wall_s"] = self._wallclock.per_tick_wall_s
        return []

    monkeypatch.setattr(Controller, "run", capture)
    rc = main(["--config", str(cfg_path), "run", "p1", "--ticks", "1"])
    capsys.readouterr()
    assert rc == 0
    assert seen["deadline_s"] == 30.0
    assert seen["per_tick_wall_s"] == 600.0  # untouched knob = code default


def test_tightened_rate_knobs_reach_the_live_fetch_limiter(tmp_path):
    """The same section feeds the D5 rate profiles the limiter enforces."""
    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create("p1", "Test")
    store = ArtifactStore(
        str(tmp_path / "store"), ArtifactRepository(conn, lambda: CLOCK),
        clock=lambda: CLOCK)
    cfg = load_config(_write_config(
        tmp_path, "openalex_burst = 2\nopenalex_daily_cap = 2\n"))
    try:
        tightened = build_live_fetch_wiring(
            conn, store, lambda: CLOCK, autonomy_caps=cfg.autonomy_caps,
            dns_resolve=_public_resolve)
        for _ in range(2):
            granted, reason = tightened.limiter.acquire("openalex")
            assert granted and reason == ""
            tightened.limiter.release("openalex")
        granted, reason = tightened.limiter.acquire("openalex")
        # The operator's cap=2 is the one that fired: two grants then the
        # no-retry hard stop (the code-owned default is 1000).
        assert not granted and reason == "daily_cap_exhausted"

        defaulted = build_live_fetch_wiring(
            conn, store, lambda: CLOCK,
            autonomy_caps=default_config().autonomy_caps,
            dns_resolve=_public_resolve)
        for _ in range(5):  # the code-owned burst of 5 still grants
            granted, reason = defaulted.limiter.acquire("openalex")
            assert granted and reason == ""
            defaulted.limiter.release("openalex")
    finally:
        conn.close()


# ── widen: refused loudly with the named code ──


def test_widened_deadline_is_refused_at_the_cli_with_the_named_code(
        tmp_path, capsys):
    _seed_db(tmp_path)
    cfg_path = _write_config(tmp_path, "overall_deadline_seconds = 600.0\n")
    # The FILE is accepted (config only range-checks > 0) — the ceiling
    # check belongs to the knob builder, so the refusal is named, never a
    # parse error and never a silent clamp to 300.
    loaded = load_config(cfg_path).autonomy_caps
    assert loaded.overall_deadline_seconds == 600.0
    rc = main(["--config", str(cfg_path), "run", "p1", "--ticks", "1"])
    out = capsys.readouterr().out
    assert rc == 1
    assert KNOB_WIDEN_REFUSED in out
    assert "overall_deadline_seconds" in out


def test_widened_rate_knobs_are_refused_with_the_named_code(tmp_path):
    cfg = load_config(_write_config(
        tmp_path, "openalex_rps = 50.0\n", name="rate-widen.toml"))
    with pytest.raises(ValueError) as excinfo:
        rate_profiles_from_autonomy(cfg.autonomy_caps)
    assert KNOB_WIDEN_REFUSED in str(excinfo.value)
    assert "openalex_rps" in str(excinfo.value)

    cfg = load_config(_write_config(
        tmp_path, "pubmed_daily_cap = 100000\n", name="cap-widen.toml"))
    with pytest.raises(ValueError) as excinfo:
        build_rate_profiles(cfg.autonomy_caps)
    assert KNOB_WIDEN_REFUSED in str(excinfo.value)

    cfg = load_config(_write_config(
        tmp_path, "overall_deadline_seconds = 3600.0\n",
        name="deadline-widen.toml"))
    with pytest.raises(ValueError) as excinfo:
        source_policy_from_autonomy(cfg.autonomy_caps)
    assert KNOB_WIDEN_REFUSED in str(excinfo.value)


def test_tightened_knobs_beside_a_widened_one_are_not_clamped(tmp_path):
    """Per-knob discipline: the refusal is the widened knob's, and the
    neighbouring tightenings still read their operator values (no silent
    clamp, no cross-talk)."""
    cfg = load_config(_write_config(
        tmp_path,
        "openalex_rps = 1.0\npubmed_daily_cap = 10\n"
        "overall_deadline_seconds = 45.0\n", name="mixed.toml"))
    profiles = rate_profiles_from_autonomy(cfg.autonomy_caps)
    assert profiles["openalex"].rps == 1.0
    assert profiles["pubmed"].daily_cap == 10
    assert source_policy_from_autonomy(
        cfg.autonomy_caps).overall_deadline_seconds == 45.0

    widened = load_config(_write_config(
        tmp_path, "openalex_burst = 6\npubmed_daily_cap = 10\n",
        name="mixed-widen.toml"))
    with pytest.raises(ValueError) as excinfo:
        build_rate_profiles(widened.autonomy_caps)
    assert KNOB_WIDEN_REFUSED in str(excinfo.value)
    assert "openalex_burst" in str(excinfo.value)


# ── absent: byte-identical to the code-owned defaults ──


def test_absent_autonomy_section_is_byte_identical_to_code_defaults(tmp_path):
    cfg = load_config(_write_config(tmp_path))  # no [autonomy_caps] section
    assert cfg.autonomy_caps == AutonomyCapsConfig()
    for build in _BUILDERS:
        assert build(cfg.autonomy_caps) == build(None)
        assert build(default_config().autonomy_caps) == build(None)
    assert (build_wallclock(None).dispatch_deadline_s
            == DEFAULT_OVERALL_DISPATCH_DEADLINE_S)

    conn = connect(":memory:")
    migrate_to_latest(conn)
    ProjectRepository(conn, lambda: CLOCK).create("p1", "Test")
    try:
        plain = Controller(conn, project_id="p1", clock=lambda: CLOCK)
        absent = Controller(conn, project_id="p1", clock=lambda: CLOCK,
                            autonomy_operator=cfg.autonomy_caps)
        defaulted = Controller(conn, project_id="p1", clock=lambda: CLOCK,
                               autonomy_operator=default_config().autonomy_caps)
        for configured in (absent, defaulted):
            assert configured._wallclock == plain._wallclock
            assert configured._budget.envelope == plain._budget.envelope
            assert (configured._loops.repeat_threshold
                    == plain._loops.repeat_threshold)
    finally:
        conn.close()


def test_cli_runs_the_real_loop_at_defaults_without_the_section(
        tmp_path, capsys, monkeypatch):
    _seed_db(tmp_path)
    cfg_path = _write_config(tmp_path)
    seen: dict[str, object] = {}
    real_run = Controller.run

    def capture(self, *args, **kwargs):
        seen["deadline_s"] = self._wallclock.dispatch_deadline_s
        seen["per_tick_steps"] = self._budget.envelope.per_tick_steps
        return real_run(self, *args, **kwargs)

    monkeypatch.setattr(Controller, "run", capture)
    rc = main(["--config", str(cfg_path), "run", "p1", "--ticks", "2"])
    out = capsys.readouterr().out
    assert rc == 0
    # The REAL loop ran (an idle project stops after its first tick — the
    # claim here is the knobs, not the tick count).
    assert "tick(s) for project p1" in out
    assert "dispatched" in out
    assert seen["deadline_s"] == DEFAULT_OVERALL_DISPATCH_DEADLINE_S
    assert seen["per_tick_steps"] == 8


def test_shipped_operator_config_is_narrow_and_builds():
    """The shipped operational config must stay inside the code-owned caps."""
    cfg = load_config(SHIPPED_CONFIG)
    for build in _BUILDERS:
        assert build(cfg.autonomy_caps) == build(None)
