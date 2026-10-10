"""Model sidecar seam — an out-of-process local model runtime as an R2 provider.

Contract: ``ADOPTION_AUDIT_R2.md`` §7 (the IDR skeleton for the sidecar
boundary). This module is the *seam* only: one `ModelProvider`
(`router.py` ``ModelProvider`` — ``provider_id`` / ``describe`` / ``invoke`` /
``stream``) whose bytes come from a separate process spoken to over stdio
JSON-RPC. Nothing here registers itself anywhere; a composition root hands a
constructed `SidecarProvider` to ``bind_model_port(providers=...)``.

What the seam guarantees
------------------------
- **Untrusted bytes, never authority.** The sidecar's answer is parsed into a
  RAW `ModelResponse` (text + usage + finish reason) and nothing else. The
  router envelopes it into a proposal; no field the sidecar returns can name a
  verdict, an intent or a transition. Decision-shaped keys refuse `PROPOSAL`,
  any undeclared key refuses `MALFORMED_PAYLOAD`, and tool calls are refused at
  this seam altogether (`ROLE`).
- **Local runtimes only (B1 narrowing).** The runtime is checked against an
  allowlist the composition root injects (this module names no runtime and no
  vendor). A call naming any other runtime, a cloud-routing option, or a
  response that reports a non-local route refuses `ROLE` *before* a byte is
  sent (or before the answer is accepted). Cloud vendors stay first-party
  providers behind the same router.
- **One process per project.** A provider is bound to exactly one
  ``project_id`` at construction; its transport must be bound to the same
  project; a second live provider for the same project, or a transport reused
  across providers, refuses `ROLE`. ``ModelRequest`` carries no project id, so
  isolation is enforced by process shape, and the sidecar must echo the project
  back (a mismatched echo refuses `ROLE`).
- **Credentials are resolved once and held.** They travel only in
  ``RequestSpec.headers_meta`` (never recorded by `RecordedTransport`) and are
  written as a frame header on the child's stdin. They never appear in argv,
  the environment, a request body, a recorded interaction, a fixture, an error
  message or a log line; a live value seen in any of those is a loud
  `ModelPlaneInvariantError` (``SECRET_LEAK``), never a tidy refusal.
- **Every byte is recorded.** Requests and responses pass through
  `RecordedTransport`; replay serves fixtures and is constructible only over a
  `RefusingSidecarTransport`, so a replay can never start a process.
- **Bounded execution.** Each request runs one child with a deadline; on expiry
  the child is killed and reaped and the attempt raises a transient error.

Refusals use only the frozen model-plane subset (`router.REFUSAL_CODES`);
transport failures are raised through the existing provider error hierarchy.

Import direction: ``hermes.tools.*`` and stdlib only (``subprocess``,
``threading``, ``weakref``); no ``research``, ``core`` or ``persistence``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import threading
import weakref
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from hermes.tools.models.router import (
    CREDENTIAL_ONLY_POLICY,
    DECISION_SHAPED_KEYS,
    MALFORMED_PAYLOAD,
    PROPOSAL,
    REFUSAL_CODES,
    ROLE,
    ChunkKind,
    Credential,
    CredentialResolver,
    ModelCall,
    ModelPlaneInvariantError,
    ModelProfile,
    ModelResponse,
    ModelSettings,
    ProviderChunk,
    TokenUsage,
)
from hermes.tools.providers.base import RequestSpec, TransportResponse
from hermes.tools.providers.replay import (
    FixtureRecord,
    RecordedInteraction,
    RecordedTransport,
)
from hermes.tools.research_sources import (
    PermanentProviderError,
    ProviderError,
    TransientProviderError,
)

__all__ = [
    "BODY_PARAM",
    "DEFAULT_SIDECAR_TIMEOUT_SECONDS",
    "LOCAL_ROUTE",
    "SIDECAR_ADAPTER_VERSION",
    "SIDECAR_MAX_RESPONSE_BYTES",
    "SIDECAR_METHOD",
    "SIDECAR_PROTOCOL",
    "SIDECAR_REFUSAL_CODES",
    "RefusingSidecarTransport",
    "SidecarProcessTransport",
    "SidecarProvider",
    "SidecarRefusal",
    "SidecarTransport",
    "release_all_claims_for_tests",
]

#: The declared stdio protocol. A real binary that does not speak it needs a
#: protocol shim; the seam refuses rather than guesses.
SIDECAR_PROTOCOL = "hermes-sidecar/1"
SIDECAR_ADAPTER_VERSION = "1"
SIDECAR_METHOD = "inference.prompt"
#: The one request parameter the recorded form carries (the canonical JSON-RPC
#: body). Its name is not credential-class under `CREDENTIAL_ONLY_POLICY`.
BODY_PARAM = "jsonrpc_body"
LOCAL_ROUTE = "local"
DEFAULT_SIDECAR_TIMEOUT_SECONDS = 60.0
SIDECAR_MAX_RESPONSE_BYTES = 1 << 20
#: How long a killed child is given to be reaped.
KILL_REAP_SECONDS = 5.0

#: The subset of the frozen plane vocabulary this seam emits.
SIDECAR_REFUSAL_CODES: frozenset[str] = frozenset({MALFORMED_PAYLOAD, PROPOSAL, ROLE})
assert SIDECAR_REFUSAL_CODES <= REFUSAL_CODES

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+-]{0,127}\Z")
_RESPONSE_KEYS = frozenset({"jsonrpc", "id", "result"})
_RESULT_KEYS = frozenset({"text", "usage", "finish_reason", "route", "project_id"})
_REQUIRED_RESULT_KEYS = frozenset({"text", "route", "project_id"})
_USAGE_KEYS = frozenset({"input_tokens", "output_tokens"})
_FINISH_REASONS = frozenset({"stop", "length"})
#: Option names that would re-route a call away from the local runtime.
_ROUTING_OPTION_KEYS = frozenset({
    "provider", "endpoint", "base_url", "api_base", "route", "host", "url",
    "remote",
})
_HEADER_AUTHORIZATION = "authorization"
_HEADER_DEADLINE = "x-hermes-deadline-seconds"
_BEARER = "Bearer "
#: Environment variables a child may inherit by default. Everything else —
#: including any credential a parent process happens to hold — is withheld.
_DEFAULT_ENV_KEYS = ("PATH", "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "LANG",
                     "LC_ALL")
_HAZARD_FOR_CODE = {
    MALFORMED_PAYLOAD: "MALFORMED_200",
    PROPOSAL: "MALFORMED_200",
    ROLE: "MALFORMED_REQUEST",
}


class SidecarRefusal(PermanentProviderError):
    """A refusal raised at the seam, carrying a frozen plane code.

    It is a `PermanentProviderError`, so the router never retries it on the
    same candidate (`router.py` ``_run_chain``). The message names fields and
    sizes only — never sidecar output, never a credential.
    """

    def __init__(self, code: str, detail: str, *, provider_id: str = "") -> None:
        if code not in SIDECAR_REFUSAL_CODES:
            raise ValueError(f"{code!r} is not a sidecar refusal code")
        super().__init__(f"{code}: {detail}", provider_id=provider_id,
                         hazard_class=_HAZARD_FOR_CODE[code], recordable=False)
        self.code = code
        self.detail = detail


class SidecarTransport(Protocol):
    """A `Transport` bound to exactly one project."""

    project_id: str

    def request(self, spec: RequestSpec) -> TransportResponse: ...


PopenFactory = Callable[..., "subprocess.Popen[bytes]"]


# ── guards (module level, one implementation each) ──


def _require_same_project(expected: str, actual: object, *, where: str,
                          provider_id: str = "") -> None:
    """`ROLE` unless ``actual`` is exactly the bound project."""
    if not isinstance(actual, str) or actual != expected:
        raise SidecarRefusal(
            ROLE,
            f"{where} is bound to a different project than {expected!r} — one "
            f"sidecar process serves one project, and bytes never cross "
            f"projects",
            provider_id=provider_id)


def _refuse_secret_in(secret: str, *blobs: object, where: str) -> None:
    """Loud invariant breach if a held credential value appears in any blob.

    Blobs are scanned as text: bytes are decoded leniently, containers are
    serialised, everything else goes through ``repr``. The value is never named.
    """
    if not secret:
        return
    for blob in blobs:
        if isinstance(blob, bytes):
            text = blob.decode("utf-8", errors="replace")
        elif isinstance(blob, str):
            text = blob
        else:
            try:
                text = json.dumps(blob, sort_keys=True, default=repr)
            except (TypeError, ValueError):
                text = repr(blob)
        if secret in text:
            raise ModelPlaneInvariantError(
                f"a live credential appeared in {where} — refusing to send or "
                f"record it (the value is never named)",
                hazard_class="SECRET_LEAK", recordable=False)


def _kill_process(proc: subprocess.Popen[bytes]) -> None:
    """Kill an expired child and reap it."""
    with contextlib.suppress(OSError):
        proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired, OSError, ValueError):
        proc.communicate(timeout=KILL_REAP_SECONDS)


def _require_project_id(project_id: object) -> str:
    if not isinstance(project_id, str) or not _PROJECT_ID_RE.match(project_id):
        raise SidecarRefusal(
            MALFORMED_PAYLOAD,
            "project_id must be a non-empty identifier ([A-Za-z0-9_.-], "
            "at most 128 characters)")
    return project_id


def _require_name(value: object, what: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise SidecarRefusal(
            MALFORMED_PAYLOAD,
            f"{what} must be a non-empty name without ':' '/' or whitespace")
    return value


def _sidecar_url(provider_id: str, project_id: str) -> str:
    return f"sidecar://{provider_id}/{project_id}/{SIDECAR_METHOD}"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _held_secret(headers_meta: Mapping[str, str]) -> str:
    value = headers_meta.get(_HEADER_AUTHORIZATION, "")
    return value[len(_BEARER):] if value.startswith(_BEARER) else value


# ── the process transport ──


class SidecarProcessTransport:
    """Stdio JSON-RPC to a child process: one child per request, one project.

    Each request writes one frame to the child's stdin::

        X-Hermes-Sidecar-Protocol: hermes-sidecar/1
        Authorization: Bearer <held credential>      (only when one is held)
        Content-Length: <n>

        <canonical JSON-RPC request body>

    and reads the child's whole stdout as the JSON-RPC response. stderr is
    discarded (it is never surfaced, so it cannot leak). A child that outlives
    its deadline is killed and reaped. Requests are serialised: at most one
    child per transport is ever alive.
    """

    def __init__(
        self,
        *,
        argv: Sequence[str],
        project_id: str,
        state_dir: str,
        timeout_seconds: float = DEFAULT_SIDECAR_TIMEOUT_SECONDS,
        env: Mapping[str, str] | None = None,
        max_response_bytes: int = SIDECAR_MAX_RESPONSE_BYTES,
        popen: PopenFactory | None = None,
    ) -> None:
        self.project_id = _require_project_id(project_id)
        if (isinstance(argv, str) or not argv
                or not all(isinstance(part, str) and part for part in argv)):
            raise SidecarRefusal(
                MALFORMED_PAYLOAD,
                "argv must be a non-empty sequence of non-empty strings (no "
                "shell string)")
        if not isinstance(state_dir, str) or not state_dir:
            raise SidecarRefusal(MALFORMED_PAYLOAD,
                                 "state_dir must name a per-project directory")
        if not timeout_seconds > 0:
            raise SidecarRefusal(MALFORMED_PAYLOAD,
                                 "timeout_seconds must be positive")
        self._argv = tuple(argv)
        self._state_dir = state_dir
        self._timeout = float(timeout_seconds)
        if env is None:
            env = {key: os.environ[key] for key in _DEFAULT_ENV_KEYS
                   if key in os.environ}
        self._env = {str(key): str(value) for key, value in env.items()}
        self._max_response_bytes = int(max_response_bytes)
        self._popen: PopenFactory = popen if popen is not None else subprocess.Popen
        self._lock = threading.Lock()
        self.processes_spawned = 0

    @property
    def timeout_seconds(self) -> float:
        return self._timeout

    def request(self, spec: RequestSpec) -> TransportResponse:
        _require_same_project(self.project_id, _url_project(spec.url),
                              where="the request URL")
        body = spec.params.get(BODY_PARAM) if isinstance(spec.params, dict) else None
        if not isinstance(body, str) or not body:
            raise SidecarRefusal(MALFORMED_PAYLOAD,
                                 f"request carries no {BODY_PARAM!r} parameter")
        headers = spec.headers_meta if isinstance(spec.headers_meta, dict) else {}
        secret = _held_secret(headers)
        _refuse_secret_in(secret, list(self._argv), where="the sidecar argv")
        _refuse_secret_in(secret, sorted(self._env.values()),
                          where="the sidecar environment")
        _refuse_secret_in(secret, body, where="a sidecar request body")
        frame = _frame(body, headers)
        timeout = _effective_timeout(self._timeout, headers)
        with self._lock:
            try:
                proc = self._popen(
                    list(self._argv), stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    cwd=self._state_dir, env=dict(self._env), shell=False)
            except OSError:
                raise PermanentProviderError(
                    "the sidecar process could not be started",
                    hazard_class="UNAVAILABLE", recordable=True) from None
            self.processes_spawned += 1
            try:
                out, _ = proc.communicate(frame, timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_process(proc)
                raise TransientProviderError(
                    f"the sidecar exceeded its {timeout:g}s deadline; the "
                    f"process was killed",
                    hazard_class="TRANSIENT", recordable=True) from None
        if proc.returncode != 0:
            raise PermanentProviderError(
                f"the sidecar exited with status {proc.returncode}",
                hazard_class="UNAVAILABLE", recordable=True)
        if len(out) > self._max_response_bytes:
            raise SidecarRefusal(
                MALFORMED_PAYLOAD,
                f"sidecar output is {len(out)} bytes, over the "
                f"{self._max_response_bytes}-byte cap")
        _refuse_secret_in(secret, out, where="sidecar output")
        return TransportResponse(status=200, body=out, headers={},
                                 content_type="application/json")


class RefusingSidecarTransport:
    """The replay-mode inner transport: it never starts anything.

    `RecordedTransport` in replay mode never calls its inner transport; this
    class makes that structural (a call raises and is counted, so a test can
    prove zero contact).
    """

    def __init__(self, *, project_id: str) -> None:
        self.project_id = _require_project_id(project_id)
        self.calls = 0

    def request(self, spec: RequestSpec) -> TransportResponse:
        self.calls += 1
        raise ProviderError(
            "replay mode reached the sidecar transport — refused (no process is "
            "ever started in replay)",
            hazard_class="REPLAY_UNAVAILABLE", recordable=False)


def _url_project(url: object) -> str:
    if not isinstance(url, str) or not url.startswith("sidecar://"):
        return ""
    parts = url[len("sidecar://"):].split("/")
    return parts[1] if len(parts) >= 3 else ""


def _frame(body: str, headers: Mapping[str, str]) -> bytes:
    payload = body.encode("utf-8")
    lines = [f"X-Hermes-Sidecar-Protocol: {SIDECAR_PROTOCOL}"]
    authorization = headers.get(_HEADER_AUTHORIZATION, "")
    if authorization:
        lines.append(f"Authorization: {authorization}")
    lines.append(f"Content-Length: {len(payload)}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8") + payload


def _effective_timeout(ceiling: float, headers: Mapping[str, str]) -> float:
    raw = headers.get(_HEADER_DEADLINE, "")
    try:
        requested = float(raw) if raw else ceiling
    except ValueError:
        requested = ceiling
    if not requested > 0:
        requested = ceiling
    return min(ceiling, requested)


# ── project claims (one live provider per project) ──

_CLAIMS_LOCK = threading.Lock()
_PROJECT_CLAIMS: dict[str, int] = {}
_ATTACHED_TRANSPORTS: dict[int, int] = {}


def _claim(project_id: str, token: int, transport_key: int) -> None:
    with _CLAIMS_LOCK:
        if project_id in _PROJECT_CLAIMS:
            raise SidecarRefusal(
                ROLE,
                f"a live sidecar provider already serves project "
                f"{project_id!r} — one sidecar process per project")
        if transport_key in _ATTACHED_TRANSPORTS:
            raise SidecarRefusal(
                ROLE,
                "this sidecar transport is already attached to another "
                "provider — a transport is never shared")
        _PROJECT_CLAIMS[project_id] = token
        _ATTACHED_TRANSPORTS[transport_key] = token


def _release(project_id: str, token: int, transport_key: int) -> None:
    with _CLAIMS_LOCK:
        if _PROJECT_CLAIMS.get(project_id) == token:
            del _PROJECT_CLAIMS[project_id]
        if _ATTACHED_TRANSPORTS.get(transport_key) == token:
            del _ATTACHED_TRANSPORTS[transport_key]


def release_all_claims_for_tests() -> None:
    """Drop every project claim (test isolation helper; never used in src)."""
    with _CLAIMS_LOCK:
        _PROJECT_CLAIMS.clear()
        _ATTACHED_TRANSPORTS.clear()


_TOKENS = iter(range(1, 1 << 62))
_TOKENS_LOCK = threading.Lock()


def _next_token() -> int:
    with _TOKENS_LOCK:
        return next(_TOKENS)


# ── the provider ──


class SidecarProvider:
    """A `ModelProvider` whose model runs in a sidecar process.

    Construction validates everything that can be validated without a call
    and claims the project; ``close()`` (or garbage collection) releases it.
    """

    def __init__(
        self,
        *,
        provider_id: str,
        project_id: str,
        runtime: str,
        model: str,
        local_runtimes: frozenset[str],
        transport: SidecarTransport,
        clock: Any,
        mode: str = "record",
        sink: Callable[[RecordedInteraction, bytes | None], None] | None = None,
        fixtures: Mapping[str, FixtureRecord] | None = None,
        credentials: CredentialResolver | None = None,
        context_window_tokens: int = 8192,
        max_output_tokens: int = 2048,
        tiers: tuple[str, ...] = (),
        timeout_seconds: float = DEFAULT_SIDECAR_TIMEOUT_SECONDS,
    ) -> None:
        self.provider_id = _require_name(provider_id, "provider_id")
        self.project_id = _require_project_id(project_id)
        self._runtime = _require_name(runtime, "runtime")
        self._model = _require_name(model, "model")
        allowed = frozenset(str(name) for name in local_runtimes)
        if not allowed:
            raise SidecarRefusal(
                MALFORMED_PAYLOAD,
                "local_runtimes must declare at least one local runtime")
        if self._runtime not in allowed:
            raise SidecarRefusal(
                ROLE,
                f"runtime {self._runtime!r} is not a declared local runtime — "
                f"cloud vendors stay first-party providers, never this seam",
                provider_id=self.provider_id)
        self._local_runtimes = allowed
        _require_same_project(self.project_id,
                              getattr(transport, "project_id", None),
                              where="the sidecar transport",
                              provider_id=self.provider_id)
        if mode not in ("record", "replay"):
            raise SidecarRefusal(MALFORMED_PAYLOAD,
                                 f"unknown sidecar mode {mode!r}")
        if mode == "replay" and not isinstance(transport, RefusingSidecarTransport):
            raise SidecarRefusal(
                MALFORMED_PAYLOAD,
                "replay mode requires a RefusingSidecarTransport — a replay "
                "must be structurally unable to start a process")
        if not timeout_seconds > 0:
            raise SidecarRefusal(MALFORMED_PAYLOAD,
                                 "timeout_seconds must be positive")
        self.model_id = f"{self._runtime}/{self._model}"
        self._mode = mode
        self._timeout = float(timeout_seconds)
        self._profile = ModelProfile(
            provider_id=self.provider_id,
            model_id=self.model_id,
            context_window_tokens=int(context_window_tokens),
            max_output_tokens=int(max_output_tokens),
            supports_streaming=False,
            supports_tool_calls=False,
            supports_structured_output=False,
            tiers=tuple(tiers),
            settings=ModelSettings(timeout_seconds=self._timeout),
        )
        credential: Credential | None = (
            credentials.resolve(self.provider_id) if credentials is not None
            else None)
        self._credential = credential
        self._caller_sink = sink
        self._token = _next_token()
        transport_key = id(transport)
        _claim(self.project_id, self._token, transport_key)
        self._finalizer = weakref.finalize(
            self, _release, self.project_id, self._token, transport_key)
        self._transport = transport
        self._url = _sidecar_url(self.provider_id, self.project_id)
        self._recorded = RecordedTransport(
            transport,
            provider_id=self.provider_id,
            adapter_version=SIDECAR_ADAPTER_VERSION,
            parser_version=SIDECAR_PROTOCOL,
            clock=clock,
            mode=mode,
            sink=self._guarded_sink if sink is not None else None,
            fixtures=fixtures,
            max_body_bytes=SIDECAR_MAX_RESPONSE_BYTES,
            redaction_policy=CREDENTIAL_ONLY_POLICY,
        ).bound(project_id=self.project_id)

    # ── lifecycle ──

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def closed(self) -> bool:
        return not self._finalizer.alive

    def close(self) -> None:
        """Release the project claim; a closed provider refuses every call."""
        self._finalizer()

    def __enter__(self) -> SidecarProvider:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── ModelProvider ──

    def describe(self) -> tuple[ModelProfile, ...]:
        """Declared metadata only — never contacts the sidecar."""
        return (self._profile,)

    def invoke(self, call: ModelCall) -> ModelResponse:
        if self.closed:
            raise SidecarRefusal(MALFORMED_PAYLOAD,
                                 "the sidecar provider is closed",
                                 provider_id=self.provider_id)
        self._require_in_remit(call)
        body, request_id = self._request_body(call)
        _refuse_secret_in(self._secret(), body, where="a sidecar request body")
        spec = RequestSpec(url=self._url, params={BODY_PARAM: body},
                           headers_meta=self._headers(call))
        response = self._recorded.request(spec)
        return _parse_response(response.body, request_id=request_id,
                               project_id=self.project_id,
                               provider_id=self.provider_id)

    def stream(self, call: ModelCall) -> tuple[ProviderChunk, ...]:
        """The one-shot answer as a chunk sequence (the profile does not
        advertise streaming, so the router never selects this path)."""
        response = self.invoke(call)
        return (ProviderChunk(kind=ChunkKind.DELTA, text=response.text),
                ProviderChunk(kind=ChunkKind.USAGE, usage=response.usage),
                ProviderChunk(kind=ChunkKind.END))

    # ── internals ──

    def _secret(self) -> str:
        return self._credential.reveal() if self._credential is not None else ""

    def _refuse(self, code: str, detail: str) -> SidecarRefusal:
        return SidecarRefusal(code, detail, provider_id=self.provider_id)

    def _require_in_remit(self, call: ModelCall) -> None:
        if call.provider_id != self.provider_id:
            raise self._refuse(
                MALFORMED_PAYLOAD,
                f"call names provider {call.provider_id!r}, this seam is "
                f"{self.provider_id!r}")
        runtime, _, model = call.model_id.partition("/")
        if runtime not in self._local_runtimes:
            raise self._refuse(
                ROLE,
                f"call routes to runtime {runtime!r}, which is not a declared "
                f"local runtime — cloud-routed requests are refused at this seam")
        if call.model_id != self.model_id or not model:
            raise self._refuse(
                MALFORMED_PAYLOAD,
                f"model {call.model_id!r} is not the one model this sidecar "
                f"advertises ({self.model_id!r})")
        options = {str(key).strip().lower() for key in call.options}
        routing = sorted(options & _ROUTING_OPTION_KEYS)
        if routing:
            raise self._refuse(
                ROLE,
                f"routing option(s) {routing} would send the call away from the "
                f"local runtime")
        credential_named = sorted(
            options & CREDENTIAL_ONLY_POLICY.credential_aliases)
        if credential_named:
            raise self._refuse(
                MALFORMED_PAYLOAD,
                f"credential-class option name(s) {credential_named} may not be "
                f"supplied — credentials are injected at the transport edge")
        payload = call.payload if isinstance(call.payload, Mapping) else {}
        if payload.get("tools"):
            raise self._refuse(
                ROLE,
                "tool calls are outside this seam's remit — the sidecar never "
                "acts, it only answers")
        if call.output_contract is not None:
            raise self._refuse(
                MALFORMED_PAYLOAD,
                "this sidecar does not advertise structured output")

    def _request_body(self, call: ModelCall) -> tuple[str, str]:
        payload = call.payload if isinstance(call.payload, Mapping) else {}
        params = {
            "protocol": SIDECAR_PROTOCOL,
            "project_id": self.project_id,
            "runtime": self._runtime,
            "model": self._model,
            "prompt": payload.get("prompt") or [],
            "rationale": payload.get("rationale") or "",
            "max_tokens": int(call.max_output_tokens),
            "options": {str(key): str(value) for key, value in call.options.items()},
        }
        try:
            canonical_params = _canonical(params)
        except (TypeError, ValueError):
            raise self._refuse(
                MALFORMED_PAYLOAD,
                "the call payload is not JSON-serialisable") from None
        request_id = "rq_" + hashlib.sha256(
            canonical_params.encode("utf-8")).hexdigest()[:24]
        body = _canonical({"jsonrpc": "2.0", "id": request_id,
                           "method": SIDECAR_METHOD, "params": params})
        return body, request_id

    def _headers(self, call: ModelCall) -> dict[str, str]:
        deadline = min(self._timeout, float(call.timeout_seconds))
        headers = {_HEADER_DEADLINE: f"{deadline:g}"}
        secret = self._secret()
        if secret:
            headers[_HEADER_AUTHORIZATION] = _BEARER + secret
        return headers

    def _guarded_sink(self, interaction: RecordedInteraction,
                      body: bytes | None) -> None:
        """Defence in depth at the record boundary: nothing carrying a held
        credential reaches the caller's sink (and so no event, artifact or
        fixture)."""
        _refuse_secret_in(self._secret(), repr(interaction),
                          body if body is not None else b"",
                          where="a recorded sidecar interaction")
        if self._caller_sink is not None:
            self._caller_sink(interaction, body)


# ── response parsing (closed schema) ──


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite JSON constant {name}")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def _parse_response(raw: bytes, *, request_id: str, project_id: str,
                    provider_id: str) -> ModelResponse:
    """Parse sidecar output into a RAW `ModelResponse`, or refuse.

    The output is untrusted: it must be one UTF-8 JSON-RPC 2.0 response object
    for *this* request, with a closed result schema. Refusal details name keys
    and sizes, never the bytes themselves.
    """

    def refuse(code: str, detail: str) -> SidecarRefusal:
        return SidecarRefusal(code, detail, provider_id=provider_id)

    if len(raw) > SIDECAR_MAX_RESPONSE_BYTES:
        raise refuse(MALFORMED_PAYLOAD,
                     f"sidecar output is {len(raw)} bytes, over the cap")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise refuse(MALFORMED_PAYLOAD, "sidecar output is not UTF-8") from None
    try:
        document: object = json.loads(text, object_pairs_hook=_unique_pairs,
                                      parse_constant=_reject_constant)
    except ValueError:
        raise refuse(MALFORMED_PAYLOAD,
                     "sidecar output is not a single JSON document with unique "
                     "keys") from None
    if not isinstance(document, dict):
        raise refuse(MALFORMED_PAYLOAD, "sidecar output is not a JSON object")
    doc: dict[str, Any] = document
    if "error" in doc:
        error: object = doc.get("error")
        code: object = error.get("code") if isinstance(error, dict) else None
        shown = code if isinstance(code, int) and not isinstance(code, bool) else "?"
        raise PermanentProviderError(
            f"the sidecar answered with a JSON-RPC error (code {shown})",
            provider_id=provider_id, hazard_class="UNAVAILABLE", recordable=True)
    unknown = sorted(set(doc) - _RESPONSE_KEYS)
    if unknown:
        raise refuse(MALFORMED_PAYLOAD, f"undeclared response keys {unknown}")
    if doc.get("jsonrpc") != "2.0":
        raise refuse(MALFORMED_PAYLOAD, "response is not JSON-RPC 2.0")
    if doc.get("id") != request_id:
        raise refuse(MALFORMED_PAYLOAD,
                     "response id does not answer this request")
    result_obj: object = doc.get("result")
    if not isinstance(result_obj, dict):
        raise refuse(MALFORMED_PAYLOAD, "response result is not an object")
    result: dict[str, Any] = result_obj
    decision = sorted(set(result) & DECISION_SHAPED_KEYS)
    if decision:
        raise refuse(PROPOSAL,
                     f"sidecar output carries decision-shaped key(s) {decision} "
                     f"— its output is proposal content, never authority")
    unknown_result = sorted(set(result) - _RESULT_KEYS)
    if unknown_result:
        raise refuse(MALFORMED_PAYLOAD,
                     f"undeclared result keys {unknown_result}")
    missing = sorted(_REQUIRED_RESULT_KEYS - set(result))
    if missing:
        raise refuse(MALFORMED_PAYLOAD, f"result is missing {missing}")
    if result.get("route") != LOCAL_ROUTE:
        raise refuse(ROLE,
                     "the sidecar reports a non-local route — cloud-routed "
                     "answers are refused at this seam")
    _require_same_project(project_id, result.get("project_id"),
                          where="the sidecar response", provider_id=provider_id)
    answer: object = result.get("text")
    if not isinstance(answer, str):
        raise refuse(MALFORMED_PAYLOAD, "result.text is not a string")
    usage = _parse_usage(result.get("usage"), refuse)
    finish: object = result.get("finish_reason", "stop")
    if not isinstance(finish, str) or finish not in _FINISH_REASONS:
        raise refuse(MALFORMED_PAYLOAD,
                     f"result.finish_reason must be one of {sorted(_FINISH_REASONS)}")
    return ModelResponse(text=answer, usage=usage, finish_reason=finish,
                         tool_calls_raw="")


def _parse_usage(value: object,
                 refuse: Callable[[str, str], SidecarRefusal]) -> TokenUsage:
    if value is None:
        return TokenUsage()
    if not isinstance(value, dict):
        raise refuse(MALFORMED_PAYLOAD, "result.usage is not an object")
    usage: dict[str, Any] = value
    unknown = sorted(set(usage) - _USAGE_KEYS)
    if unknown:
        raise refuse(MALFORMED_PAYLOAD, f"undeclared usage keys {unknown}")
    counts: dict[str, int] = {}
    for key in _USAGE_KEYS:
        count: object = usage.get(key, 0)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise refuse(MALFORMED_PAYLOAD,
                         f"result.usage.{key} must be a non-negative integer")
        counts[key] = count
    return TokenUsage(input_tokens=counts["input_tokens"],
                      output_tokens=counts["output_tokens"])
