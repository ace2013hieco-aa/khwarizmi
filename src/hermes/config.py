"""Typed configuration schema (foundation decision §8).

stdlib tomllib + dataclasses — no heavyweight config framework (§5).
Validates operator-controlled values; secrets never enter the config file.
"""
from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

# ── errors ──


class ConfigError(Exception):
    """Raised when config is missing, unparseable, or violates a constraint."""


# ── typed schema ──


@dataclass(frozen=True, slots=True)
class HeartbeatPolicy:
    interval_seconds: int = 30
    lease_multiplier: int = 3  # lease = interval × multiplier

    def lease_seconds(self) -> int:
        return self.interval_seconds * self.lease_multiplier


@dataclass(frozen=True, slots=True)
class GateTTLs:
    hypothesis_days: int = 7
    pre_compute_days: int = 7
    pre_live_days: int = 7


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_retries: int = 3
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 300.0


@dataclass(frozen=True, slots=True)
class SQLiteConfig:
    database_path: str = "hermes.db"
    wal_mode: bool = True
    backup_dir: str = "backups"
    retain_last_n: int = 5


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    enabled: bool = False  # Phase 0 default: unavailable (§10 — OPTIONAL/NOT CONFIGURED)
    runner: str = ""  # e.g. "docker", "podman", "nsjail"
    cpu_limit_seconds: int = 600
    memory_limit_mb: int = 2048
    network_egress_allowlist: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ArtifactStoreConfig:
    artifact_root: str = "artifacts"
    cache_enabled: bool = True
    cache_max_entries: int = 1000


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    workspace_root: str = "workspace"
    per_experiment_isolation: bool = True


@dataclass(frozen=True, slots=True)
class BudgetClasses:
    s: int = 100  # strong tier — tokens/day
    m: int = 50  # mid
    c: int = 20  # cheap


@dataclass(frozen=True, slots=True)
class ModelTierConfig:
    s: str = ""  # model ref string, or empty = not configured
    m: str = ""
    c: str = ""


@dataclass(frozen=True, slots=True)
class AutonomyCapsConfig:
    """P-AUTO-4 operator knobs (narrow-only; code defaults are the ceiling).

    Every field defaults to the D6 proposed value (the code-owned ceiling).
    Operator config may only TIGHTEN a cap — a looser value is refused loudly
    at wiring time (never silently clamped), mirroring
    ``sandbox.network_egress_allowlist`` narrowing. Absent config is the
    code-owned floor (existing behaviour unchanged).
    """

    overall_deadline_seconds: float = 300.0
    per_tick_wall_seconds: float = 600.0
    per_run_wall_seconds: float = 3600.0
    per_task_steps: int = 5
    per_tick_steps: int = 8
    per_run_steps: int = 1000
    per_task_tokens: int = 250
    per_tick_tokens: int = 1000
    per_run_tokens: int = 10000
    retry_max_retries: int = 3
    retry_base_delay_seconds: float = 1.0
    retry_max_delay_seconds: float = 30.0
    loop_repeat_threshold: int = 3
    openalex_rps: float = 5.0
    openalex_burst: int = 5
    openalex_daily_cap: int = 1000
    pubmed_rps: float = 3.0
    pubmed_burst: int = 3
    pubmed_daily_cap: int = 1000


@dataclass(frozen=True, slots=True)
class HermesConfig:
    sqlite: SQLiteConfig = field(default_factory=SQLiteConfig)
    artifacts: ArtifactStoreConfig = field(default_factory=ArtifactStoreConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    heartbeat: HeartbeatPolicy = field(default_factory=HeartbeatPolicy)
    gate_ttls: GateTTLs = field(default_factory=GateTTLs)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    budgets: BudgetClasses = field(default_factory=BudgetClasses)
    model_tiers: ModelTierConfig = field(default_factory=ModelTierConfig)
    sandbox: SandboxPolicy = field(default_factory=SandboxPolicy)
    autonomy_caps: AutonomyCapsConfig = field(default_factory=AutonomyCapsConfig)
    provider_config_dir: str = "providers"


# ── loading + validation ──


def _dataclass_from_dict(cls: type, data: dict[str, Any]) -> Any:
    """Populate a frozen dataclass from a dict, ignoring unknown keys (forward compat)."""
    field_names = {f.name for f in fields(cls)}
    valid = {k: v for k, v in data.items() if k in field_names}
    try:
        return cls(**valid)
    except TypeError as e:
        raise ConfigError(f"Bad config values for {cls.__name__}: {e}") from e


def load_config(path: Path) -> HermesConfig:
    """Read a TOML config file and return a validated HermesConfig.

    Missing keys default to dataclass defaults. Unknown keys are ignored.
    Secrets must come from environment variables, never the config file.
    """
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("rb") as fh:
        parsed = tomllib.load(fh)
    sections = {
        "sqlite": SQLiteConfig,
        "artifacts": ArtifactStoreConfig,
        "workspace": WorkspaceConfig,
        "heartbeat": HeartbeatPolicy,
        "gate_ttls": GateTTLs,
        "retry": RetryPolicy,
        "budgets": BudgetClasses,
        "model_tiers": ModelTierConfig,
        "sandbox": SandboxPolicy,
        "autonomy_caps": AutonomyCapsConfig,
    }
    kwargs: dict[str, Any] = {}
    for key, cls in sections.items():
        section_data = parsed.get(key, {})
        if not isinstance(section_data, dict):
            raise ConfigError(f"[{key}] must be a table, got {type(section_data).__name__}")
        kwargs[key] = _dataclass_from_dict(cls, section_data)
    kwargs["provider_config_dir"] = parsed.get("provider_config_dir", "providers")
    cfg = HermesConfig(**kwargs)
    _validate_ranges(cfg)
    return cfg


def _validate_ranges(cfg: HermesConfig) -> None:
    """B4 — range-check the operator-affecting config values. The frozen
    dataclasses only reject wrong TYPES; a typo like retain_last_n = 0 or a
    negative heartbeat interval must be rejected loudly instead of silently
    deleting every backup or disabling liveness."""
    if cfg.sqlite.retain_last_n < 1:
        raise ConfigError(
            f"sqlite.retain_last_n must be >= 1, got {cfg.sqlite.retain_last_n} "
            f"(0 would delete every backup, the fresh one included)")
    if cfg.heartbeat.interval_seconds <= 0:
        raise ConfigError(
            f"heartbeat.interval_seconds must be > 0, "
            f"got {cfg.heartbeat.interval_seconds}")
    if cfg.heartbeat.lease_multiplier <= 0:
        raise ConfigError(
            f"heartbeat.lease_multiplier must be > 0, "
            f"got {cfg.heartbeat.lease_multiplier}")
    caps = cfg.autonomy_caps
    for name in (
            "overall_deadline_seconds", "per_tick_wall_seconds",
            "per_run_wall_seconds", "retry_base_delay_seconds",
            "retry_max_delay_seconds", "openalex_rps", "pubmed_rps"):
        if float(getattr(caps, name)) <= 0:
            raise ConfigError(
                f"autonomy_caps.{name} must be > 0, "
                f"got {getattr(caps, name)!r}")
    for name in (
            "per_task_steps", "per_tick_steps", "per_run_steps",
            "per_task_tokens", "per_tick_tokens", "per_run_tokens",
            "retry_max_retries", "loop_repeat_threshold",
            "openalex_burst", "openalex_daily_cap",
            "pubmed_burst", "pubmed_daily_cap"):
        if int(getattr(caps, name)) <= 0:
            raise ConfigError(
                f"autonomy_caps.{name} must be > 0, "
                f"got {getattr(caps, name)!r}")


def default_config() -> HermesConfig:
    """Phase 0: return a config with all defaults (no file needed)."""
    return HermesConfig()


def config_to_string(cfg: HermesConfig) -> str:
    """Format config as a readable string (for `hermes doctor`)."""
    d = asdict(cfg)
    lines: list[str] = []
    for section, values in d.items():
        if isinstance(values, dict):
            lines.append(f"  {section}:")
            for k, v in values.items():
                lines.append(f"    {k}: {v}")
        else:
            # scalar field (e.g. provider_config_dir)
            lines.append(f"  {section}: {values}")
    return "\n".join(lines)
