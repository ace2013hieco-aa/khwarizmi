"""Tests for hermes.config — typed, validated TOML loading."""
from __future__ import annotations

from pathlib import Path

from hermes.config import (
    ConfigError,
    HermesConfig,
    default_config,
    load_config,
)


def test_default_config_loads():
    cfg = default_config()
    assert isinstance(cfg, HermesConfig)
    assert cfg.heartbeat.interval_seconds == 30
    assert cfg.heartbeat.lease_seconds() == 90
    assert cfg.retry.max_retries == 3


def test_missing_file_raises():
    try:
        load_config(Path("/nonexistent/path/hermes.toml"))
        raise AssertionError("Should have raised ConfigError")
    except ConfigError:
        pass


def test_shipped_config_parses():
    repo_config = Path(__file__).resolve().parent.parent / "config" / "hermes.toml"
    if repo_config.exists():
        cfg = load_config(repo_config)
        assert cfg.sqlite.wal_mode is True
        assert cfg.heartbeat.interval_seconds == 30


# ── B4 audit: operator-affecting config values are range-validated ──

def _write_config(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "hermes.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_retain_last_n_zero_rejected(tmp_path):
    """B4 — retain_last_n = 0 (would delete every backup) is rejected."""
    p = _write_config(tmp_path, "[sqlite]\nretain_last_n = 0\n")
    try:
        load_config(p)
        raise AssertionError("Should have raised ConfigError")
    except ConfigError as e:
        assert "retain_last_n" in str(e)


def test_negative_heartbeat_interval_rejected(tmp_path):
    """B4 — a negative heartbeat interval (would break liveness) is rejected."""
    p = _write_config(tmp_path, "[heartbeat]\ninterval_seconds = -5\n")
    try:
        load_config(p)
        raise AssertionError("Should have raised ConfigError")
    except ConfigError as e:
        assert "interval_seconds" in str(e)


def test_valid_ranges_still_load(tmp_path):
    """B4 — the shipped defaults and sane values still parse."""
    cfg = load_config(_write_config(tmp_path, "[sqlite]\nretain_last_n = 7\n"))
    assert cfg.sqlite.retain_last_n == 7
