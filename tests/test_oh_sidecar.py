"""Model sidecar seam tests (ADOPTION_AUDIT_R2 §7; `tools/models/sidecar.py`).

No real model binary is required: provider-level tests drive a scripted fake
transport, and process-level tests spawn the *test interpreter* running a tiny
fake-sidecar script, so the timeout/kill and header-delivery paths are real.

Pinned shapes:

- **timeout kill** — an expired child is killed and reaped; the attempt raises
  a transient error and is still recorded;
- **credential absence** — a held credential reaches the child only as a stdin
  frame header: never argv, environment, request body, recorded interaction,
  fixture, exception text or log line; a leak is a loud invariant breach;
- **replay byte-identity** — recorded bytes replay identically over a refusing
  inner transport that is never contacted;
- **project-mismatch refusal** — construction, URL and response echo;
- **malformed-binary-output refusal** — closed response schema;
- **cloud-route refusal** — B1 narrowing at the seam;
- **neutralization** — each of the timeout/redaction/project pins is shown to
  fail when its guard is disabled, so none of them is vacuous.

Nothing asserted here lets sidecar output decide a transition: its answer is a
raw `ModelResponse` the router envelopes into a proposal.
"""

from __future__ import annotations

import ast
import gc
import hashlib
import json
import logging
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest

import hermes.tools.models.sidecar as sidecar_module
from hermes.security.boundaries import UntrustedContent
from hermes.tools.models.router import (
    DECISION_SHAPED_KEYS,
    MALFORMED_PAYLOAD,
    PROPOSAL,
    REFUSAL_CODES,
    ROLE,
    Credential,
    ModelCall,
    ModelPlaneInvariantError,
    ModelPlanePolicy,
    ModelProposal,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelRouter,
    TokenUsage,
)
from hermes.tools.models.sidecar import (
    BODY_PARAM,
    SIDECAR_PROTOCOL,
    SIDECAR_REFUSAL_CODES,
    RefusingSidecarTransport,
    SidecarProcessTransport,
    SidecarProvider,
    SidecarRefusal,
    release_all_claims_for_tests,
)
from hermes.tools.providers.base import RequestSpec, TransportResponse
from hermes.tools.providers.replay import (
    FixtureRecord,
    RecordedInteraction,
    RecordedTransport,
    ReplayUnavailableError,
    dump_fixtures,
    interaction_to_fixture,
    load_fixtures,
)
from hermes.tools.research_sources import (
    PermanentProviderError,
    ProviderUnavailableError,
    TransientProviderError,
)

SECRET = "sk-local-sidecar-DO-NOT-RECORD-9f8e7d6c"
PROVIDER = "sidecar-local"
PROJECT = "proj-a"
OTHER_PROJECT = "proj-b"
RUNTIME = "rt-a"
MODEL = "m1"
MODEL_ID = f"{RUNTIME}/{MODEL}"
LOCAL = frozenset({RUNTIME, "rt-b"})
CLOCK_STAMP = "2026-01-01T00:00:00.000000+00:00"

Reply = Callable[[RequestSpec], bytes]


# ─────────────────────────── fakes ───────────────────────────


class FakeClock:
    def now_utc(self) -> str:
        return CLOCK_STAMP

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, seconds: float) -> None:
        return None


def _request_of(spec: RequestSpec) -> dict[str, Any]:
    return json.loads(spec.params[BODY_PARAM])


def ok_reply(spec: RequestSpec, **result_overrides: Any) -> bytes:
    request = _request_of(spec)
    result: dict[str, Any] = {
        "text": "a proposal-shaped answer",
        "route": "local",
        "project_id": request["params"]["project_id"],
        "usage": {"input_tokens": 11, "output_tokens": 7},
        "finish_reason": "stop",
    }
    result.update(result_overrides)
    return json.dumps({"jsonrpc": "2.0", "id": request["id"],
                       "result": result}).encode("utf-8")


class FakeSidecar:
    """A scripted sidecar transport bound to one project; records every spec."""

    def __init__(self, project_id: str = PROJECT, reply: Reply = ok_reply) -> None:
        self.project_id = project_id
        self.specs: list[RequestSpec] = []
        self._reply = reply

    def request(self, spec: RequestSpec) -> TransportResponse:
        self.specs.append(spec)
        return TransportResponse(status=200, body=self._reply(spec),
                                 content_type="application/json")


class Resolver:
    def __init__(self, secret: str = SECRET) -> None:
        self.calls = 0
        self._secret = secret

    def resolve(self, provider_id: str) -> Credential | None:
        self.calls += 1
        return Credential(name="sidecar_token", _value=self._secret)


class Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[RecordedInteraction, bytes | None]] = []

    def __call__(self, interaction: RecordedInteraction, body: bytes | None) -> None:
        self.rows.append((interaction, body))


class CapturingPopen:
    """Real `subprocess.Popen`, with every child and its kwargs captured."""

    def __init__(self) -> None:
        self.procs: list[subprocess.Popen[bytes]] = []
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        proc = cast("subprocess.Popen[bytes]", subprocess.Popen(*args, **kwargs))
        self.procs.append(proc)
        self.calls.append((args, kwargs))
        return proc


@pytest.fixture(autouse=True)
def _isolated_claims() -> Iterator[None]:
    release_all_claims_for_tests()
    yield
    release_all_claims_for_tests()


def build(transport: Any = None, **overrides: Any) -> SidecarProvider:
    fields: dict[str, Any] = {
        "provider_id": PROVIDER,
        "project_id": PROJECT,
        "runtime": RUNTIME,
        "model": MODEL,
        "local_runtimes": LOCAL,
        "transport": transport if transport is not None else FakeSidecar(),
        "clock": FakeClock(),
    }
    fields.update(overrides)
    return SidecarProvider(**fields)


def make_call(**overrides: Any) -> ModelCall:
    fields: dict[str, Any] = {
        "provider_id": PROVIDER,
        "model_id": MODEL_ID,
        "payload": {
            "prompt": [{"origin": "task.context", "ref": "r1", "text": "hello"}],
            "rationale": "why",
            "tools": [],
            "profile": "researcher",
        },
        "options": {},
        "timeout_seconds": 30.0,
    }
    fields.update(overrides)
    return ModelCall(**fields)


# ── fake sidecar processes (run by the test interpreter) ──

ECHO_SIDECAR = r'''
import json, os, sys
raw = sys.stdin.buffer.read()
head, _, body = raw.partition(b"\r\n\r\n")
headers = {}
for line in head.decode("utf-8").split("\r\n"):
    name, _, value = line.partition(": ")
    headers[name.lower()] = value
report = {"argv": sys.argv, "env": dict(os.environ), "headers": headers,
          "body": body.decode("utf-8")}
with open("seen.json", "w", encoding="utf-8") as handle:
    json.dump(report, handle)
mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
if mode == "garbage":
    sys.stdout.buffer.write(b"\x00\xff\xfe binary \x9c\x80")
elif mode == "exit3":
    sys.exit(3)
else:
    request = json.loads(body.decode("utf-8"))
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"],
        "result": {"text": "answer from child", "route": "local",
                   "project_id": request["params"]["project_id"],
                   "usage": {"input_tokens": 3, "output_tokens": 4},
                   "finish_reason": "stop"}}))
'''

SLEEP_SIDECAR = "import time\ntime.sleep(60)\n"


def _script(tmp_path: Path, name: str, source: str) -> str:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return str(path)


def _process_transport(tmp_path: Path, script: str, *extra: str,
                       project_id: str = PROJECT, timeout: float = 20.0,
                       popen: CapturingPopen | None = None,
                       **kwargs: Any) -> SidecarProcessTransport:
    state = tmp_path / f"state-{project_id}"
    state.mkdir(exist_ok=True)
    return SidecarProcessTransport(
        argv=[sys.executable, script, *extra], project_id=project_id,
        state_dir=str(state), timeout_seconds=timeout, popen=popen, **kwargs)


def _spec_for(project_id: str = PROJECT, body: str = '{"x":1}',
              headers: dict[str, str] | None = None) -> RequestSpec:
    return RequestSpec(url=f"sidecar://{PROVIDER}/{project_id}/inference.prompt",
                       params={BODY_PARAM: body}, headers_meta=headers or {})


# ─────────────────────────── the port ───────────────────────────


class TestPort:
    def test_satisfies_the_r2_model_provider_protocol(self) -> None:
        provider: ModelProvider = build()
        assert provider.provider_id == PROVIDER
        profiles = provider.describe()
        assert len(profiles) == 1
        profile = profiles[0]
        assert (profile.provider_id, profile.model_id) == (PROVIDER, MODEL_ID)
        # The seam never acts: no tool calls, no structured verdicts, no stream.
        assert not profile.supports_tool_calls
        assert not profile.supports_structured_output
        assert not profile.supports_streaming

    def test_describe_is_declared_metadata_and_contacts_nothing(self) -> None:
        transport = FakeSidecar()
        build(transport).describe()
        assert transport.specs == []

    def test_invoke_returns_raw_response_only(self) -> None:
        transport = FakeSidecar()
        response = build(transport).invoke(make_call())
        assert response == ModelResponse(
            text="a proposal-shaped answer",
            usage=TokenUsage(input_tokens=11, output_tokens=7),
            finish_reason="stop", tool_calls_raw="")
        assert len(transport.specs) == 1
        request = _request_of(transport.specs[0])
        assert request["jsonrpc"] == "2.0"
        assert request["params"]["protocol"] == SIDECAR_PROTOCOL
        assert request["params"]["project_id"] == PROJECT

    def test_stream_is_the_one_shot_answer_as_chunks(self) -> None:
        chunks = build().stream(make_call())
        assert "".join(chunk.text for chunk in chunks) == "a proposal-shaped answer"

    def test_output_is_proposal_content_through_the_router(self) -> None:
        provider = build()
        router = ModelRouter(
            providers=[provider],
            policy=ModelPlanePolicy(tier_refs={"s": f"{PROVIDER}:{MODEL_ID}"}),
            clock=FakeClock(), sleep=lambda seconds: None,
            jitter_source=lambda low, high: 1.0)
        result = router.invoke(ModelRequest(
            tier="s", profile="researcher", lease_generation="g1",
            prompt=(UntrustedContent("hello", "task.context", "r1"),),
            rationale="why"))
        assert isinstance(result, ModelProposal)
        assert isinstance(result.content, UntrustedContent)
        assert result.content.text == "a proposal-shaped answer"
        assert result.structured == {}
        assert result.tool_calls == ()
        router.verify_accounting()

    def test_decision_shaped_output_never_reaches_the_router_as_a_proposal(self) -> None:
        provider = build(FakeSidecar(reply=lambda spec: ok_reply(spec, verdict="x")))
        router = ModelRouter(
            providers=[provider],
            policy=ModelPlanePolicy(tier_refs={"s": f"{PROVIDER}:{MODEL_ID}"}),
            clock=FakeClock(), sleep=lambda seconds: None,
            jitter_source=lambda low, high: 1.0)
        with pytest.raises(ProviderUnavailableError):
            router.invoke(ModelRequest(
                tier="s", profile="researcher", lease_generation="g1",
                prompt=(UntrustedContent("hello", "task.context", "r1"),)))
        router.verify_accounting()


# ─────────────────────────── timeout kill ───────────────────────────


def _expire(tmp_path: Path) -> tuple[CapturingPopen, float]:
    popen = CapturingPopen()
    transport = _process_transport(
        tmp_path, _script(tmp_path, "sleep.py", SLEEP_SIDECAR), timeout=1.0,
        popen=popen)
    started = time.monotonic()
    with pytest.raises(TransientProviderError) as raised:
        transport.request(_spec_for())
    assert raised.value.hazard_class == "TRANSIENT"
    assert "killed" in str(raised.value)
    return popen, time.monotonic() - started


class TestTimeoutKill:
    def test_expired_child_is_killed_and_reaped(self, tmp_path: Path) -> None:
        popen, elapsed = _expire(tmp_path)
        assert len(popen.procs) == 1
        assert popen.procs[0].poll() is not None, "expired child left running"
        assert elapsed < 20.0

    def test_spawn_is_argv_only_never_a_shell(self, tmp_path: Path) -> None:
        popen, _ = _expire(tmp_path)
        args, kwargs = popen.calls[0]
        assert kwargs["shell"] is False
        assert isinstance(args[0], list)
        assert kwargs["stderr"] is subprocess.DEVNULL

    def test_provider_timeout_is_transient_and_still_recorded(
            self, tmp_path: Path) -> None:
        sink = Sink()
        transport = _process_transport(
            tmp_path, _script(tmp_path, "sleep.py", SLEEP_SIDECAR), timeout=1.0)
        provider = build(transport, sink=sink)
        with pytest.raises(TransientProviderError):
            provider.invoke(make_call())
        assert [row[0].outcome_kind for row in sink.rows] == ["RECORDED_FAILURE"]
        assert sink.rows[0][1] is None

    def test_deadline_is_the_tighter_of_seam_and_call(self, tmp_path: Path) -> None:
        transport = FakeSidecar()
        build(transport, timeout_seconds=5.0).invoke(
            make_call(timeout_seconds=2.0))
        assert transport.specs[0].headers_meta["x-hermes-deadline-seconds"] == "2"

    def test_neutralizing_the_kill_breaks_the_pin(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sidecar_module, "_kill_process", lambda proc: None)
        popen, _ = _expire(tmp_path)
        try:
            assert popen.procs[0].poll() is None, (
                "with the kill neutralized the child must still be alive — "
                "otherwise the kill pin proves nothing")
        finally:
            popen.procs[0].kill()
            popen.procs[0].communicate(timeout=10)


# ─────────────────────────── credentials ───────────────────────────


class TestCredentialAbsence:
    def test_resolved_once_and_held(self) -> None:
        resolver = Resolver()
        provider = build(credentials=resolver)
        for _ in range(3):
            provider.invoke(make_call())
        assert resolver.calls == 1

    def test_credential_travels_only_as_a_header(
            self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG)
        transport, sink = FakeSidecar(), Sink()
        provider = build(transport, credentials=Resolver(), sink=sink)
        response = provider.invoke(make_call())
        spec = transport.specs[0]
        assert spec.headers_meta["authorization"] == f"Bearer {SECRET}"
        assert SECRET not in spec.url
        assert SECRET not in json.dumps(spec.params)
        assert SECRET not in repr(response)
        # The recorded "event" rows and the fixtures built from them.
        assert sink.rows
        for interaction, body in sink.rows:
            assert SECRET not in repr(interaction)
            assert SECRET not in (body or b"").decode("utf-8")
            fixture = interaction_to_fixture(interaction, body, status=200)
            assert SECRET not in json.dumps(fixture.to_mapping())
        assert SECRET not in caplog.text
        assert SECRET not in repr(provider.__dict__.get("_credential"))

    def test_child_receives_it_in_the_frame_header_only(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HERMES_PARENT_SECRET", SECRET)
        transport = _process_transport(
            tmp_path, _script(tmp_path, "echo.py", ECHO_SIDECAR), "ok")
        provider = build(transport, credentials=Resolver())
        response = provider.invoke(make_call())
        assert response.text == "answer from child"
        seen = json.loads(
            (tmp_path / f"state-{PROJECT}" / "seen.json").read_text("utf-8"))
        assert seen["headers"]["authorization"] == f"Bearer {SECRET}"
        assert seen["headers"]["x-hermes-sidecar-protocol"] == SIDECAR_PROTOCOL
        assert SECRET not in json.dumps(seen["argv"])
        assert SECRET not in json.dumps(seen["env"]), (
            "a parent credential must never be inherited by the child")
        assert SECRET not in seen["body"]

    def test_echoed_credential_is_a_loud_breach_and_never_recorded(self) -> None:
        sink = Sink()
        provider = build(FakeSidecar(reply=lambda spec: ok_reply(spec, text=SECRET)),
                         credentials=Resolver(), sink=sink)
        with pytest.raises(ModelPlaneInvariantError) as raised:
            provider.invoke(make_call())
        assert raised.value.hazard_class == "SECRET_LEAK"
        assert SECRET not in str(raised.value)
        assert sink.rows == []

    def test_credential_in_a_request_body_is_refused_before_sending(self) -> None:
        transport = FakeSidecar()
        provider = build(transport, credentials=Resolver())
        call = make_call(payload={"prompt": [{"origin": "o", "ref": "r",
                                              "text": f"leak {SECRET}"}],
                                  "rationale": "", "tools": [], "profile": "p"})
        with pytest.raises(ModelPlaneInvariantError) as raised:
            provider.invoke(call)
        assert SECRET not in str(raised.value)
        assert transport.specs == []

    def test_credential_in_argv_or_env_refuses_before_spawn(
            self, tmp_path: Path) -> None:
        script = _script(tmp_path, "echo.py", ECHO_SIDECAR)
        headers = {"authorization": f"Bearer {SECRET}"}
        argv_leak = _process_transport(tmp_path, script, SECRET)
        with pytest.raises(ModelPlaneInvariantError):
            argv_leak.request(_spec_for(headers=headers))
        assert argv_leak.processes_spawned == 0
        env_leak = _process_transport(tmp_path, script,
                                      env={"TOKEN_FOR_CHILD": SECRET})
        with pytest.raises(ModelPlaneInvariantError):
            env_leak.request(_spec_for(headers=headers))
        assert env_leak.processes_spawned == 0

    def test_credential_class_option_names_are_refused(self) -> None:
        transport = FakeSidecar()
        with pytest.raises(SidecarRefusal) as raised:
            build(transport).invoke(make_call(options={"api_key": "x"}))
        assert raised.value.code == MALFORMED_PAYLOAD
        assert transport.specs == []

    def test_neutralizing_redaction_breaks_the_pin(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sidecar_module, "_refuse_secret_in",
                            lambda secret, *blobs, where: None)
        sink = Sink()
        provider = build(FakeSidecar(reply=lambda spec: ok_reply(spec, text=SECRET)),
                         credentials=Resolver(), sink=sink)
        provider.invoke(make_call())
        leaked = any(SECRET in (body or b"").decode("utf-8")
                     for _, body in sink.rows)
        assert leaked, ("with redaction neutralized the secret must reach the "
                        "sink — otherwise the redaction pin proves nothing")


# ─────────────────────────── replay ───────────────────────────


def _record_one(**overrides: Any) -> tuple[FixtureRecord, bytes, RequestSpec,
                                           ModelResponse]:
    transport, sink = FakeSidecar(), Sink()
    provider = build(transport, sink=sink, **overrides)
    response = provider.invoke(make_call())
    provider.close()
    interaction, body = sink.rows[-1]
    assert body is not None
    return (interaction_to_fixture(interaction, body, status=200), body,
            transport.specs[0], response)


class TestReplay:
    def test_replay_is_byte_identical_and_never_contacts_the_sidecar(self) -> None:
        fixture, recorded_body, spec, live = _record_one()
        refusing = RefusingSidecarTransport(project_id=PROJECT)
        replayed = build(refusing, mode="replay",
                         fixtures={fixture.fixture_id: fixture}).invoke(make_call())
        assert replayed == live
        assert refusing.calls == 0
        # Transport-level byte identity over the same recorded corpus.
        raw = RecordedTransport(
            RefusingSidecarTransport(project_id=PROJECT), provider_id=PROVIDER,
            adapter_version=sidecar_module.SIDECAR_ADAPTER_VERSION,
            parser_version=SIDECAR_PROTOCOL, clock=FakeClock(), mode="replay",
            fixtures={fixture.fixture_id: fixture},
            redaction_policy=sidecar_module.CREDENTIAL_ONLY_POLICY,
        ).request(RequestSpec(url=spec.url, params=dict(spec.params),
                              headers_meta={}))
        assert raw.body == recorded_body
        assert fixture.body_hash == hashlib.sha256(recorded_body).hexdigest()

    def test_fixture_file_round_trip_replays_identically(self, tmp_path: Path) -> None:
        fixture, _, _, live = _record_one()
        path = tmp_path / "sidecar_fixtures.json"
        dump_fixtures([fixture], str(path))
        loaded = load_fixtures(str(path))
        replayed = build(RefusingSidecarTransport(project_id=PROJECT),
                         mode="replay", fixtures=loaded).invoke(make_call())
        assert replayed == live

    def test_credential_is_not_part_of_fixture_identity(self) -> None:
        fixture, _, _, live = _record_one(credentials=Resolver())
        replayed = build(RefusingSidecarTransport(project_id=PROJECT),
                         mode="replay",
                         fixtures={fixture.fixture_id: fixture}).invoke(make_call())
        assert replayed == live

    def test_missing_fixture_is_replay_unavailable_with_zero_contact(self) -> None:
        refusing = RefusingSidecarTransport(project_id=PROJECT)
        with pytest.raises(ReplayUnavailableError):
            build(refusing, mode="replay", fixtures={}).invoke(make_call())
        assert refusing.calls == 0

    def test_replay_over_a_live_transport_is_refused_at_construction(self) -> None:
        with pytest.raises(SidecarRefusal) as raised:
            build(FakeSidecar(), mode="replay")
        assert raised.value.code == MALFORMED_PAYLOAD


# ─────────────────────────── project isolation ───────────────────────────


class TestProjectIsolation:
    def test_transport_bound_to_another_project_is_refused(self) -> None:
        with pytest.raises(SidecarRefusal) as raised:
            build(FakeSidecar(project_id=OTHER_PROJECT))
        assert raised.value.code == ROLE

    def test_response_for_another_project_is_refused(self) -> None:
        provider = build(FakeSidecar(
            reply=lambda spec: ok_reply(spec, project_id=OTHER_PROJECT)))
        with pytest.raises(SidecarRefusal) as raised:
            provider.invoke(make_call())
        assert raised.value.code == ROLE

    def test_one_live_provider_per_project(self) -> None:
        first = build()
        with pytest.raises(SidecarRefusal) as raised:
            build()
        assert raised.value.code == ROLE
        # Other projects are unaffected; closing releases the claim.
        build(FakeSidecar(project_id=OTHER_PROJECT), project_id=OTHER_PROJECT)
        first.close()
        assert first.closed
        build()

    def test_a_transport_is_never_shared(self) -> None:
        transport = FakeSidecar()
        first = build(transport)
        first.close()
        second = build(transport)  # released, so re-attachment is fine
        with pytest.raises(SidecarRefusal) as raised:
            build(transport, project_id=PROJECT)
        assert raised.value.code == ROLE
        assert not second.closed

    def test_a_dropped_provider_releases_its_claim(self) -> None:
        build()  # not kept: garbage collection runs the finalizer
        gc.collect()
        assert not build().closed

    def test_a_closed_provider_refuses_calls(self) -> None:
        provider = build()
        provider.close()
        with pytest.raises(SidecarRefusal):
            provider.invoke(make_call())

    def test_process_transport_refuses_another_projects_url(
            self, tmp_path: Path) -> None:
        transport = _process_transport(
            tmp_path, _script(tmp_path, "echo.py", ECHO_SIDECAR))
        with pytest.raises(SidecarRefusal) as raised:
            transport.request(_spec_for(project_id=OTHER_PROJECT))
        assert raised.value.code == ROLE
        assert transport.processes_spawned == 0

    def test_neutralizing_the_project_guard_breaks_the_pin(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sidecar_module, "_require_same_project",
                            lambda expected, actual, **kwargs: None)
        provider = build(FakeSidecar(
            project_id=OTHER_PROJECT,
            reply=lambda spec: ok_reply(spec, project_id=OTHER_PROJECT)))
        response = provider.invoke(make_call())
        assert response.text, ("with the guard neutralized cross-project bytes "
                               "must be accepted — otherwise the pin proves "
                               "nothing")


# ─────────────────────────── malformed output ───────────────────────────


def _with_id(build_doc: Callable[[str], Any]) -> Reply:
    def reply(spec: RequestSpec) -> bytes:
        return json.dumps(build_doc(_request_of(spec)["id"])).encode("utf-8")
    return reply


def _good_result(**overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"text": "t", "route": "local", "project_id": PROJECT}
    result.update(overrides)
    return result


MALFORMED: dict[str, Reply] = {
    "binary": lambda spec: b"\x00\xff\xfe\x9c binary",
    "not_json": lambda spec: b"definitely not json",
    "array": lambda spec: b"[]",
    "two_documents": lambda spec: ok_reply(spec) + ok_reply(spec),
    "nan_constant": lambda spec: b'{"jsonrpc":"2.0","id":NaN,"result":{}}',
    "duplicate_keys": lambda spec: (
        b'{"jsonrpc":"2.0","jsonrpc":"2.0","id":"x","result":{}}'),
    "extra_top_level": _with_id(lambda rid: {
        "jsonrpc": "2.0", "id": rid, "result": _good_result(), "intent": {}}),
    "wrong_version": _with_id(lambda rid: {
        "jsonrpc": "1.0", "id": rid, "result": _good_result()}),
    "wrong_id": _with_id(lambda rid: {
        "jsonrpc": "2.0", "id": "rq_other", "result": _good_result()}),
    "result_not_object": _with_id(lambda rid: {
        "jsonrpc": "2.0", "id": rid, "result": "text"}),
    "missing_text": _with_id(lambda rid: {
        "jsonrpc": "2.0", "id": rid,
        "result": {"route": "local", "project_id": PROJECT}}),
    "text_not_string": _with_id(lambda rid: {
        "jsonrpc": "2.0", "id": rid, "result": _good_result(text=["t"])}),
    "undeclared_result_key": _with_id(lambda rid: {
        "jsonrpc": "2.0", "id": rid, "result": _good_result(transition="x")}),
    "negative_usage": _with_id(lambda rid: {
        "jsonrpc": "2.0", "id": rid,
        "result": _good_result(usage={"input_tokens": -1})}),
    "boolean_usage": _with_id(lambda rid: {
        "jsonrpc": "2.0", "id": rid,
        "result": _good_result(usage={"output_tokens": True})}),
    "bad_finish": _with_id(lambda rid: {
        "jsonrpc": "2.0", "id": rid, "result": _good_result(finish_reason="x")}),
}


class TestMalformedOutput:
    @pytest.mark.parametrize("shape", sorted(MALFORMED))
    def test_malformed_output_is_refused(self, shape: str) -> None:
        sink = Sink()
        provider = build(FakeSidecar(reply=MALFORMED[shape]), sink=sink)
        with pytest.raises(SidecarRefusal) as raised:
            provider.invoke(make_call())
        assert raised.value.code == MALFORMED_PAYLOAD
        # The untrusted bytes are recorded for audit; they are never echoed.
        assert len(sink.rows) == 1
        assert "binary" not in str(raised.value)

    @pytest.mark.parametrize("key", sorted(DECISION_SHAPED_KEYS))
    def test_decision_shaped_output_refuses_proposal(self, key: str) -> None:
        provider = build(FakeSidecar(
            reply=lambda spec: ok_reply(spec, **{key: True})))
        with pytest.raises(SidecarRefusal) as raised:
            provider.invoke(make_call())
        assert raised.value.code == PROPOSAL

    def test_json_rpc_error_is_a_transport_failure_without_echo(self) -> None:
        def reply(spec: RequestSpec) -> bytes:
            return json.dumps({"jsonrpc": "2.0", "id": _request_of(spec)["id"],
                               "error": {"code": -32000,
                                         "message": "UNTRUSTED-ECHO"}}).encode()
        with pytest.raises(PermanentProviderError) as raised:
            build(FakeSidecar(reply=reply)).invoke(make_call())
        assert not isinstance(raised.value, SidecarRefusal)
        assert "UNTRUSTED-ECHO" not in str(raised.value)
        assert "-32000" in str(raised.value)

    def test_real_child_emitting_binary_garbage_is_refused(
            self, tmp_path: Path) -> None:
        transport = _process_transport(
            tmp_path, _script(tmp_path, "echo.py", ECHO_SIDECAR), "garbage")
        with pytest.raises(SidecarRefusal) as raised:
            build(transport).invoke(make_call())
        assert raised.value.code == MALFORMED_PAYLOAD

    def test_real_child_nonzero_exit_is_a_permanent_failure(
            self, tmp_path: Path) -> None:
        transport = _process_transport(
            tmp_path, _script(tmp_path, "echo.py", ECHO_SIDECAR), "exit3")
        with pytest.raises(PermanentProviderError) as raised:
            build(transport).invoke(make_call())
        assert "status 3" in str(raised.value)

    def test_oversized_output_is_refused(self) -> None:
        big = b'{"pad":"' + b"x" * (sidecar_module.SIDECAR_MAX_RESPONSE_BYTES) + b'"}'
        transport = FakeSidecar(reply=lambda spec: big)
        provider = build(transport)
        with pytest.raises(Exception) as raised:
            provider.invoke(make_call())
        # Refused at the record boundary (RecordTooLargeError) or the seam.
        assert "cap" in str(raised.value)


# ─────────────────────────── B1 narrowing ───────────────────────────


class TestCloudRouteRefusal:
    def test_cloud_routed_model_is_refused_before_any_byte(self) -> None:
        transport = FakeSidecar()
        with pytest.raises(SidecarRefusal) as raised:
            build(transport).invoke(make_call(model_id="hosted-vendor/big-model"))
        assert raised.value.code == ROLE
        assert transport.specs == []

    @pytest.mark.parametrize("option", ["endpoint", "base_url", "provider", "route"])
    def test_routing_options_are_refused(self, option: str) -> None:
        transport = FakeSidecar()
        with pytest.raises(SidecarRefusal) as raised:
            build(transport).invoke(make_call(options={option: "https://x"}))
        assert raised.value.code == ROLE
        assert transport.specs == []

    def test_non_local_runtime_cannot_be_constructed(self) -> None:
        with pytest.raises(SidecarRefusal) as raised:
            build(runtime="hosted-vendor")
        assert raised.value.code == ROLE

    def test_non_local_route_in_the_answer_is_refused(self) -> None:
        provider = build(FakeSidecar(reply=lambda spec: ok_reply(spec, route="cloud")))
        with pytest.raises(SidecarRefusal) as raised:
            provider.invoke(make_call())
        assert raised.value.code == ROLE

    def test_tool_calls_are_outside_the_remit(self) -> None:
        transport = FakeSidecar()
        call = make_call(payload={"prompt": [], "rationale": "",
                                  "tools": ["search"], "profile": "p"})
        with pytest.raises(SidecarRefusal) as raised:
            build(transport).invoke(call)
        assert raised.value.code == ROLE
        assert transport.specs == []


# ─────────────────────────── vocabulary + discipline ───────────────────────────


SIDECAR_SOURCE = Path(sidecar_module.__file__).read_text(encoding="utf-8")


class TestDiscipline:
    def test_refusal_codes_are_the_frozen_plane_subset(self) -> None:
        assert SIDECAR_REFUSAL_CODES <= REFUSAL_CODES
        assert {MALFORMED_PAYLOAD, PROPOSAL, ROLE} == SIDECAR_REFUSAL_CODES
        with pytest.raises(ValueError):
            SidecarRefusal("NEW_CODE", "never")

    def test_every_refusal_site_uses_a_frozen_code(self) -> None:
        allowed = {"MALFORMED_PAYLOAD", "PROPOSAL", "ROLE", "code"}
        sites = 0
        for node in ast.walk(ast.parse(SIDECAR_SOURCE)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in {"SidecarRefusal", "refuse"}
                    and node.args):
                first = node.args[0]
                assert isinstance(first, ast.Name) and first.id in allowed, (
                    ast.unparse(node))
                sites += 1
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_refuse" and node.args):
                first = node.args[0]
                assert isinstance(first, ast.Name) and first.id in allowed
                sites += 1
        assert sites > 10

    def test_imports_stay_inside_the_tools_layer(self) -> None:
        modules: set[str] = set()
        for node in ast.walk(ast.parse(SIDECAR_SOURCE)):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
        hermes_modules = {m for m in modules if m.startswith("hermes")}
        assert hermes_modules <= {
            "hermes.tools.models.router", "hermes.tools.providers.base",
            "hermes.tools.providers.replay", "hermes.tools.research_sources"}
        assert "logging" not in modules
        assert not {"requests", "httpx", "urllib.request", "socket"} & modules

    def test_names_no_vendor_and_never_uses_a_shell(self) -> None:
        lowered = SIDECAR_SOURCE.lower()
        for vendor in ("openai", "anthropic", "claude", "gemini", "ollama",
                       "mistral", "llama", "gpt-", "openhuman"):
            assert vendor not in lowered, vendor
        assert "shell=true" not in lowered
        assert "print(" not in SIDECAR_SOURCE
