"""OPS-1 — the CLI composes the live controller only when configured.

The regression guard is the first test: with no `[model_tiers]` ref the run's
stdout, stderr and exit code are byte-identical to the pre-OPS-1 CLI, and the
model plane is never built. Every other test covers one refusal or one live
falsifier from the design gate (`docs/idr/LIVE-CLI-COMPOSITION.md`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

import hermes.composition as composition
import hermes.tools.models.cloud as cloud_module
from hermes.cli import main
from hermes.composition import (
    _MODEL_REGISTRY,
    CloudModelSpec,
    CompositionError,
    build_live_composition,
    specs_from_tiers,
    tier_refs_from_config,
)
from hermes.config import HermesConfig, ModelTierConfig
from hermes.core.intents import Intent, IntentKind
from hermes.core.task_status import TaskStatus
from hermes.methodology.workflows import LITERATURE_REVIEW_DOCUMENT
from hermes.persistence.database import connect
from hermes.persistence.migrations import migrate_to_latest
from hermes.persistence.repositories import ProjectRepository, TaskRepository
from hermes.research.gateway import apply_intent
from hermes.tools.providers.base import RequestSpec, TransportResponse

KEY = "sk-test-0123456789abcdefghijklmnop"
ENV = {"ANTHROPIC_API_KEY": KEY}

#: Today's `hermes run` output for the fixture project — captured from the
#: pre-OPS-1 CLI and pinned here. Any added line fails this test.
DRAIN_ONLY_OUTPUT = (
    "Ran 1 tick(s) for project p1: 1 dispatched, 0 succeeded, "
    "1 waiting on human, 0 failed, 0 unhandled.\n"
    "  note: contradiction detection: 0 recorded, 0 duplicates, 0 refused\n"
)

# ── fixtures ──


def _payload(task_id: str, task_type: str, profile: str, spec: dict) -> dict:
    return {
        "task_id": task_id, "task_type": task_type, "profile": profile,
        "idempotency_key": f"k-{task_id}", "iteration": 1, "spec": spec,
        "inputs": [], "outputs": [], "dependencies": [],
        "provenance": [], "cost_class": None, "concurrency_group": None,
        "max_retries": 3, "parent_task_id": None,
    }


def _project(tmp_path: Any, *tasks: tuple[str, str, str, dict]) -> Any:
    db = tmp_path / "hermes.db"
    conn = connect(str(db))
    migrate_to_latest(conn)
    ProjectRepository(conn).create("p1", "Test")
    for task_id, task_type, profile, spec in tasks:
        apply_intent(conn, Intent(
            kind=IntentKind.INSERT_TASK, proposed_by="DIRECTOR",
            project_id="p1",
            payload=_payload(task_id, task_type, profile, spec)))
    conn.close()
    return db


def _config(tmp_path: Any, db: Any, tiers: Mapping[str, str] | None = None) -> Any:
    cfg = tmp_path / "hermes.toml"
    body = f'[sqlite]\ndatabase_path = "{db.as_posix()}"\n'
    if tiers:
        body += "[model_tiers]\n" + "".join(
            f'{tier} = "{ref}"\n' for tier, ref in tiers.items())
    cfg.write_text(body, encoding="utf-8")
    return cfg


def _gate_task() -> tuple[str, str, str, dict]:
    return ("gate-1", "HUMAN_GATE", "DIRECTOR", {"gate_requirement": "hypothesis"})


def _methodology_task() -> tuple[str, str, str, dict]:
    # One stage: this fixture exercises the live CLI path, not the chain. OPS-5D
    # makes a full chain require an admitted evidence transition, which this
    # scripted INSERT_TASK reply is not.
    document = dict(LITERATURE_REVIEW_DOCUMENT)
    document["stages"] = [dict(document["stages"][0])]
    document["termination"] = {**dict(document["termination"]),
                               "max_stages": 1}
    return ("meth-1", "AGENT_TASK", "RESEARCHER", {
        "template": "methodology_run",
        "methodology": document,
        "inputs": {"question": "does it hold?"},
    })


class _ScriptedTransport:
    """Replies from a queue; repeats the last response once exhausted."""

    def __init__(self, *responses: TransportResponse) -> None:
        self.specs: list[RequestSpec] = []
        self._responses = list(responses)

    def request(self, spec: RequestSpec) -> TransportResponse:
        self.specs.append(spec)
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def _anthropic_reply(text: str) -> TransportResponse:
    body = {
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }
    return TransportResponse(status=200, body=json.dumps(body).encode("utf-8"),
                             content_type="application/json")


def _proposal_reply() -> str:
    """The single-proposal wire form.

    The live path uses the single-proposal form because the contract's
    ``kind_field`` prompts the model for a top-level kind
    (``tools/models/cloud.py``). The multi-proposal form is **not** reachable
    through the live path (OPS-5I): the plane refuses a reply that omits the
    top-level kind, and the runtime refuses one that carries it, so every
    multi-form reply fails one of the two. An earlier revision of this
    docstring said the form was reachable because the runtime refuses only when
    *both* forms appear; that reading looked at the runtime alone and missed the
    plane's kind check. Whether to make the form work or remove it is its own
    decision.
    """
    return json.dumps({
        "rationale": "one ordinary task",
        "kind": "INSERT_TASK",
        "payload": {"spec": {"goal": "stage output"}},
        "delegations": [],
    })


class _NoPin:
    """The pinning transport without DNS: the scripted transport is the edge."""

    def __init__(self, inner: Any, *, host: str, resolve: Any = None) -> None:
        self._inner = inner

    def request(self, spec: RequestSpec) -> TransportResponse:
        return self._inner.request(spec)


def _install_transport(monkeypatch: Any, transport: Any) -> None:
    monkeypatch.setattr(cloud_module, "HostPinnedTransport", _NoPin)
    monkeypatch.setattr(composition, "ProviderHTTPTransport",
                        lambda **_: transport)


def _journal_rows(db: Any) -> int:
    conn = connect(str(db))
    try:
        return int(conn.execute(
            "SELECT COUNT(*) AS c FROM events").fetchone()["c"])
    finally:
        conn.close()


def _status(db: Any, task_id: str) -> str:
    conn = connect(str(db))
    try:
        status = TaskRepository(conn).get_status(task_id)
        return status.value if status is not None else ""
    finally:
        conn.close()


# ── 1–2. drain-only is byte-identical ──


def test_no_tiers_is_byte_identical(tmp_path, capsys, monkeypatch) -> None:
    """The regression guard: the pre-OPS-1 output, byte for byte."""
    monkeypatch.setattr(
        composition, "ProviderHTTPTransport",
        lambda **_: pytest.fail("the model plane was constructed"))
    db = _project(tmp_path, _gate_task(), _methodology_task())
    cfg = _config(tmp_path, db)

    rc = main(["--config", str(cfg), "run", "p1", "--ticks", "5"])
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out == DRAIN_ONLY_OUTPUT
    assert captured.err == ""


def test_drain_only_with_tiers_is_byte_identical(
        tmp_path, capsys, monkeypatch) -> None:
    """Tiers configured + `--drain-only` prints exactly the no-tier bytes."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        composition, "ProviderHTTPTransport",
        lambda **_: pytest.fail("the model plane was constructed"))
    db = _project(tmp_path, _gate_task(), _methodology_task())
    cfg = _config(tmp_path, db, {"m": "anthropic:test-model"})

    rc = main(["--config", str(cfg), "run", "p1", "--ticks", "5",
               "--drain-only"])
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out == DRAIN_ONLY_OUTPUT


# ── 3–5. refusals, before the database is touched ──


def test_missing_key_refuses_before_the_first_tick(tmp_path, capsys,
                                                   monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db = _project(tmp_path, _methodology_task())
    cfg = _config(tmp_path, db, {"m": "anthropic:test-model"})
    rows = _journal_rows(db)

    rc = main(["--config", str(cfg), "run", "p1"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "environment variable ANTHROPIC_API_KEY is not set" in captured.out
    assert "Hint: re-run with --drain-only" in captured.out
    assert "Ran " not in captured.out
    assert _journal_rows(db) == rows
    assert _status(db, "meth-1") == TaskStatus.PENDING.value


def test_unknown_provider_refuses_and_names_the_ref(tmp_path, capsys,
                                                    monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    db = _project(tmp_path, _methodology_task())
    cfg = _config(tmp_path, db, {"m": "gemini:x"})

    rc = main(["--config", str(cfg), "run", "p1"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "tier 'm': provider 'gemini' is not in the model registry" in captured.out
    # Derived from the registry, not typed: a new provider must not break this,
    # and a missing one must. (A literal "anthropic, openai" used to pass on a
    # substring until a third provider was inserted between them.)
    assert "known: " + ", ".join(sorted(composition._MODEL_REGISTRY)) in captured.out


def test_malformed_ref_refuses(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    db = _project(tmp_path, _methodology_task())
    cfg = _config(tmp_path, db, {"m": "anthropic"})

    rc = main(["--config", str(cfg), "run", "p1"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "tier 'm': model ref must be 'provider:model', got 'anthropic'" in captured.out


# ── 6. the live path, end to end ──


def test_live_run_executes_a_methodology_stage(tmp_path, capsys,
                                               monkeypatch) -> None:
    """Tiers + a scripted transport: a stage runs, a proposal is admitted."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    transport = _ScriptedTransport(_anthropic_reply(_proposal_reply()))
    _install_transport(monkeypatch, transport)
    db = _project(tmp_path, _methodology_task())
    cfg = _config(tmp_path, db, {"m": "anthropic:test-model"})
    rows = _journal_rows(db)

    rc = main(["--config", str(cfg), "run", "p1", "--ticks", "2"])
    captured = capsys.readouterr()

    assert rc == 0
    assert "Model plane: live (tiers: m=anthropic:test-model)" in captured.out
    # OPS-5Z4 supplied the falsification trio, which also shrinks the
    # withheld set from ten declarations to six.
    assert "Capability plane: 5 supplied" in captured.out
    assert "in-process (no sandbox)" in captured.out
    assert "withheld 6 declaration(s)" in captured.out
    assert "succeeded" in captured.out
    assert "  model call 1: tier=m provider=anthropic model=test-model OK" \
        in captured.out
    assert "vector: runs=" in captured.out
    assert "M2(calls=0,repeat=0.000)" in captured.out
    assert "M2=n/a" not in captured.out
    assert _status(db, "meth-1") == TaskStatus.SUCCEEDED.value
    assert _journal_rows(db) > rows
    assert transport.specs, "the live run never reached the transport"


def test_live_run_still_parks_human_gate(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    _install_transport(monkeypatch, _ScriptedTransport(
        _anthropic_reply(_proposal_reply())))
    db = _project(tmp_path, _gate_task())
    cfg = _config(tmp_path, db, {"m": "anthropic:test-model"})

    rc = main(["--config", str(cfg), "run", "p1", "--ticks", "5"])
    captured = capsys.readouterr()

    assert rc == 0
    assert "waiting on human" in captured.out
    assert "Model plane: live" in captured.out
    assert _status(db, "gate-1") == TaskStatus.WAITING_HUMAN.value


def test_the_collector_failure_does_not_change_the_exit_code(
        tmp_path, capsys, monkeypatch) -> None:
    """R3: a collector defect prints `unavailable`, never fails the run."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    _install_transport(monkeypatch, _ScriptedTransport(
        _anthropic_reply(_proposal_reply())))
    monkeypatch.setattr(
        composition.LiveVector, "_render",
        lambda self: (_ for _ in ()).throw(RuntimeError("probe")))
    db = _project(tmp_path, _methodology_task())
    cfg = _config(tmp_path, db, {"m": "anthropic:test-model"})

    rc = main(["--config", str(cfg), "run", "p1", "--ticks", "2"])
    captured = capsys.readouterr()

    assert rc == 0
    assert "vector: unavailable (RuntimeError: probe)" in captured.out


# ── 7. the registry itself ──


def test_every_registry_entry_is_loadable() -> None:
    for provider_id, (dialect, api_key_env) in _MODEL_REGISTRY.items():
        CloudModelSpec(provider_id=provider_id, dialect=dialect,
                       model_id="m", api_key_env=api_key_env)


def test_a_bad_registry_entry_is_refused_naming_the_provider(
        monkeypatch) -> None:
    monkeypatch.setitem(composition._MODEL_REGISTRY, "bad", ("mystery", "BAD_KEY"))
    cfg = HermesConfig(model_tiers=ModelTierConfig(m="bad:x"))
    with pytest.raises(CompositionError) as info:
        specs_from_tiers(cfg, environ={"BAD_KEY": "k"})
    assert "provider 'bad' declares an unusable spec" in str(info.value)
    assert "unknown dialect" in str(info.value)


def test_refs_dedupe_to_one_spec_per_provider_model() -> None:
    cfg = HermesConfig(model_tiers=ModelTierConfig(
        s="anthropic:test-model", m="anthropic:test-model", c="openai:gpt"))
    specs = specs_from_tiers(cfg, environ={
        "ANTHROPIC_API_KEY": KEY, "OPENAI_API_KEY": KEY + "-o"})
    assert sorted((spec.provider_id, spec.model_id) for spec in specs) == [
        ("anthropic", "test-model"), ("openai", "gpt")]


def test_oxionai_resolves_to_the_gateway_host_and_its_own_key_variable() -> None:
    """The reviewed gateway entry targets its own host and reads its own key."""
    cfg = HermesConfig(model_tiers=ModelTierConfig(
        m="oxionai:claude-opus-5.5"))
    assert tier_refs_from_config(cfg) == {"m": "oxionai:claude-opus-5.5"}

    specs = specs_from_tiers(cfg, environ={"OXIONAI_API_KEY": KEY})

    assert len(specs) == 1
    spec = specs[0]
    assert (spec.provider_id, spec.model_id) == ("oxionai", "claude-opus-5.5")
    assert (spec.dialect, spec.host) == ("openai", "oxionai.com")
    assert spec.api_key_env == "OXIONAI_API_KEY"
    assert spec.make_dialect().host == "oxionai.com"


def test_the_gateway_key_is_never_satisfied_by_the_openai_key() -> None:
    cfg = HermesConfig(model_tiers=ModelTierConfig(
        m="oxionai:claude-opus-5.5"))
    with pytest.raises(CompositionError, match="OXIONAI_API_KEY is not set"):
        specs_from_tiers(cfg, environ={"OPENAI_API_KEY": KEY})
    spec = specs_from_tiers(
        cfg, environ={"OXIONAI_API_KEY": KEY, "OPENAI_API_KEY": KEY})[0]
    assert spec.api_key_env == "OXIONAI_API_KEY"


def test_an_unknown_provider_is_refused_naming_the_tier_ref() -> None:
    cfg = HermesConfig(model_tiers=ModelTierConfig(m="nowhere:model"))
    with pytest.raises(CompositionError) as info:
        specs_from_tiers(cfg, environ={})
    assert ("tier 'm': provider 'nowhere' is not in the model registry"
            in str(info.value))


def test_a_gateway_without_a_code_owned_endpoint_refuses(monkeypatch) -> None:
    """A non-canonical provider can never silently inherit the vendor host."""
    monkeypatch.setitem(composition._MODEL_REGISTRY, "unbound",
                        ("openai", "UNBOUND_API_KEY"))
    cfg = HermesConfig(model_tiers=ModelTierConfig(m="unbound:model"))
    with pytest.raises(CompositionError) as info:
        specs_from_tiers(cfg, environ={"UNBOUND_API_KEY": "k"})
    assert "no code-owned endpoint binding" in str(info.value)


def test_no_tiers_resolves_to_no_specs() -> None:
    """Empty means 'not configured'; the live builder is what refuses."""
    assert specs_from_tiers(HermesConfig(), environ={}) == ()
    with pytest.raises(CompositionError, match="declares no tier"):
        build_live_composition(
            HermesConfig(), None, project_id="p1", specs=(), environ={})
