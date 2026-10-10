"""P-AUTO-3 live fetch wiring — OpenAlex + PubMed (D5).

Instantiates the two keyless adapters behind the ratified handler path:
adapters (openalex, pubmed) → ProviderRateLimiter (in-memory, resets on
restart — acceptable per slice) → ProviderHTTPTransport (per-call timeouts,
sanitized egress) → RecordedTransport:record (journaled provider_interaction
via the existing make_persisting_sink) → handlers (make_source_*_handler) →
Controller tick → UntrustedContent envelope + journal.

No credentials in tree. No new deps. Sanitized egress is scheme+host
allowlisted to the two APIs inside the transport; redirects are re-vetted
at every hop (same-origin https only — A1). Each search/fetch dispatch
carries an overall wall-clock deadline (D1 — the SourcePolicy default),
so a hung provider cannot hold a controller tick open past its budget.

Every fetch is journaled as a provider_interaction (RecordedTransport's
sink); live runs convert those interactions to replay fixtures (the
corpus under tests/fixtures/p_auto_3_live/), which replay hermetically.
Egress is narrowed-only by ``sandbox.network_egress_allowlist``
(``allowlist_from_config``): operator config can remove D5 hosts, never add.

FIX-USERINFO: hosts are read the way ``urlsplit`` reads them
(``parts.hostname``), never by slicing ``netloc`` — the audited bypass read
``api.openalex.org`` (the userinfo prefix) as the host of
``https://api.openalex.org:foo@evil.example/works``, whose actual host is
``evil.example``: the allowlist verdict and the FIX-D pin were keyed on a
name that is not the URL's host. Measured on the base gate, that URL never
reached a dial — the shipped transport's own parser refuses it pre-connect
(``InvalidURL``); the LIVE row is the non-default port, where base dialed
``api.openalex.org:8443`` — outside the vetted origin — with the pin keyed
on the bare host. The gate is a thin adapter over the ONE rule layer
(``hermes.security.egress.EgressPolicy.vet``) and only re-raises its named
refusal code; it no longer re-implements any rule.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any

from hermes.persistence.provider_interactions import make_persisting_sink
from hermes.research.autonomy_caps import (
    build_rate_profiles,
    build_wallclock,
)
from hermes.security.egress import EgressPolicy, EgressRefused
from hermes.tools.providers.adapters.openalex import OpenalexAdapter
from hermes.tools.providers.adapters.pubmed import PubmedAdapter
from hermes.tools.providers.base import RateProfile, RequestSpec, TransportResponse
from hermes.tools.providers.hazards import load_hazard_spec
from hermes.tools.providers.http import (
    ProviderHTTPTransport,
    clear_pinned_host,
    pin_host_for_request,
)
from hermes.tools.providers.ratelimit import ProviderRateLimiter
from hermes.tools.providers.replay import RecordedTransport, provider_resolver_for
from hermes.tools.research_sources import ProviderValidationError

__all__ = [
    "ALLOWLIST_HOSTS",
    "DEFAULT_PER_CALL_TIMEOUT_SECONDS",
    "RATE_LIMITER_PERSISTENCE",
    "LiveFetchWiring",
    "allowlist_from_config",
    "build_live_fetch_wiring",
    "default_dns_resolve",
    "rate_profiles_from_autonomy",
    "source_policy_from_autonomy",
]

# (c) Rate-limiter persistence decision: in-memory, resets on restart.
# ACCEPTABLE for this slice (the roadmap says "in-memory resets on restart
# — acceptable or fixed here"). Stated here, tested in the live-fetch tests.
RATE_LIMITER_PERSISTENCE = "in-memory (resets on restart; acceptable per P-AUTO-3)"

# (d) Sanitized egress — scheme/host allowlist for the two APIs only (D5:
# OpenAlex + PubMed). Each provider's canonical content host (where its
# record source_url points — the honest fetch target for SOURCE_FETCH)
# is part of the same provider's API surface; no third-party egress.
ALLOWLIST_HOSTS: tuple[str, ...] = (
    "api.openalex.org",
    "openalex.org",
    "eutils.ncbi.nlm.nih.gov",
    "pubmed.ncbi.nlm.nih.gov",
)
DEFAULT_PER_CALL_TIMEOUT_SECONDS = 10.0


class _AllowlistedTransport:
    """Sanitized egress gate: a thin adapter over ``EgressPolicy.vet``.

    Wraps any Transport. Refuses anything else fail-closed before any I/O.
    The allowlist is the code-owned D5 provider surface, optionally NARROWED
    by operator config (never widened — see ``allowlist_from_config``).

    FIX-USERINFO — the rule layer has exactly ONE implementation. The gate
    used to re-derive the host with ``netloc.lower().split(":")[0]``, which
    reads ``"api.openalex.org"`` out of
    ``https://api.openalex.org:foo@evil.example/works`` (the userinfo
    prefix) while the URL's actual host is ``evil.example``: the userinfo
    prefix was mistaken for the host, the non-default port was truncated
    away, and both the DNS vetting and the FIX-D pin were keyed on the
    wrong host — a rogue URL passed the allowlist under an allowlisted
    NAME that is not its host. Measured on the base gate: the userinfo URL
    never reached a dial (``urllib``'s own parser refuses it pre-connect
    with ``InvalidURL``); the LIVE row is the non-default port, where base
    dialed ``api.openalex.org:8443`` — outside the vetted origin —
    unpinned. Every rule now comes from ``EgressPolicy.vet``, which parses
    the host with
    ``urlsplit(...).hostname``: scheme (``SCHEME_NOT_ALLOWED``), userinfo
    (``CREDENTIALS_IN_URL``), origin including an explicit non-default port
    (``ORIGIN_NOT_ALLOWLISTED``), an unparseable port (``MALFORMED_URL``),
    resolution (``DNS_FAILURE``/``NO_ADDRESSES``) and the public-address
    rule (``ADDRESS_BLOCKED``). The gate does not re-check any of them — it
    re-raises the layer's NAMED code inside the lifecycle's refusal type.

    P-AUTO-4 DNS-rebinding guard: the allowlisted host is resolved and EVERY
    address must be public (S2 pin mechanics, D5 scope) — a private /
    loopback / link-local answer (or a mixed set) is refused before the inner
    transport is touched. FIX-D — the vetted address is PINNED for the
    dial: the lexicographically-first vetted address is published to the
    guarded opener's pin table for exactly this request (restored after),
    so the checked address is the dialed address (check-time == dial-time).
    """

    def __init__(self, inner: Any,
                 allowlist: tuple[str, ...] = ALLOWLIST_HOSTS,
                 resolve: Any | None = None) -> None:
        self._inner = inner
        self._allowlist = tuple(allowlist)
        self._resolve = resolve or default_dns_resolve
        if not self._allowlist:
            raise ProviderValidationError(
                "live fetch egress refused: an EMPTY host allowlist is "
                "incoherent (no request could ever be issued) — the D5 "
                "provider surface is the floor")
        # The ONE rule layer: the code-owned host surface expressed as the
        # https origins ``vet`` allowlists (the explicit-port form is a
        # different origin and is therefore refused there).
        self._policy = EgressPolicy(
            allowlist=tuple(f"https://{host}" for host in self._allowlist))

    def _resolve_for_vet(self, host: str, port: int) -> tuple[str, ...]:
        """Bridge the gate's injected ``resolve(host)`` to ``vet``'s
        ``resolve(host, port)`` shape (https-only, so ``port`` is always the
        scheme default the gate's resolver has always assumed)."""
        return tuple(self._resolve(host))

    def request(self, spec: RequestSpec) -> TransportResponse:
        try:
            target = self._policy.vet(spec.url, resolve=self._resolve_for_vet)
        except EgressRefused as exc:
            raise ProviderValidationError(
                f"live fetch egress refused [{exc.code}] "
                f"{exc.host or '<no host>'}: {exc.detail}") from None
        # FIX-D — pin the vetted address for exactly this request: the
        # guarded opener dials the pinned address (Host header / TLS SNI
        # keep the hostname), so a resolver flip between vet and dial
        # cannot redirect the connection.
        pin_host_for_request(target.host, target.pinned)
        try:
            return self._inner.request(spec)  # type: ignore[attr-defined]
        finally:
            clear_pinned_host(target.host, target.pinned)


def default_dns_resolve(host: str) -> tuple[str, ...]:
    """Production DNS resolution (socket.getaddrinfo, deterministic sort)."""
    import socket as _socket

    infos = _socket.getaddrinfo(host, 443, type=_socket.SOCK_STREAM)
    return tuple(sorted({str(info[4][0]).partition("%")[0] for info in infos}))


def source_policy_from_autonomy(operator: Any | None = None) -> Any:
    """Build the dispatch ``SourcePolicy`` deadline from operator knobs.

    Narrow-only: absent config carries the 300s D5 default; a tighter
    operator value is honoured; a wider value is refused loudly (never
    silently clamped). Deferred import keeps this module's import surface
    minimal (no cycle with source_handlers at import time).
    """
    from hermes.research.source_handlers import SourcePolicy

    caps = build_wallclock(operator)
    return SourcePolicy(overall_deadline_seconds=caps.dispatch_deadline_s)


def rate_profiles_from_autonomy(
    operator: Any | None = None,
) -> dict[str, RateProfile]:
    """Build D5 ``RateProfile``s from operator knobs (narrow-only)."""
    from typing import cast

    raw = build_rate_profiles(operator)
    return {
        name: RateProfile(
            rps=float(cast(Any, spec["rps"])),
            burst=int(cast(Any, spec["burst"])),
            concurrency=int(cast(Any, spec["concurrency"])),
            daily_cap=int(cast(Any, spec["daily_cap"])))
        for name, spec in raw.items()
    }


def allowlist_from_config(policy: Any | None) -> tuple[str, ...]:
    """Narrow-only egress allowlist from ``SandboxPolicy.network_egress_allowlist``
    (config.py). The code-owned D5 provider surface is the FLOOR: operator
    config may only NARROW it. An entry outside the surface is refused
    loudly (never silently dropped, never widened); an empty/absent config
    yields the full D5 surface. Entries may be bare hosts or https URLs.
    """
    if policy is None:
        return ALLOWLIST_HOSTS
    configured = getattr(policy, "network_egress_allowlist", None) or ()
    if not configured:
        return ALLOWLIST_HOSTS
    narrowed: list[str] = []
    for entry in configured:
        raw = str(entry).strip()
        parsed = urllib.parse.urlsplit(raw if "://" in raw else f"//{raw}")
        if parsed.scheme and parsed.scheme != "https":
            raise ProviderValidationError(
                f"sandbox.network_egress_allowlist entry {entry!r} is not "
                f"https — the D5 egress surface is https-only")
        # FIX-USERINFO — parse the host, never slice ``netloc``: slicing
        # reads the userinfo prefix as the host, so
        # ``https://api.openalex.org:foo@evil.example`` would be silently
        # reinterpreted as the D5 host named in its userinfo. An entry is a
        # host, never a credential.
        try:
            host = (parsed.hostname or "").lower().rstrip(".")
        except ValueError as exc:
            raise ProviderValidationError(
                f"sandbox.network_egress_allowlist entry {entry!r} does not "
                f"parse as a host ({exc})") from None
        if parsed.username is not None or parsed.password is not None:
            raise ProviderValidationError(
                f"sandbox.network_egress_allowlist entry {entry!r} carries "
                f"userinfo — an entry names a host, never a credential")
        if host not in ALLOWLIST_HOSTS:
            raise ProviderValidationError(
                f"sandbox.network_egress_allowlist entry {entry!r} is "
                f"outside the D5 provider surface {sorted(ALLOWLIST_HOSTS)} "
                f"— config may only NARROW the code-owned allowlist, never "
                f"widen it")
        if host not in narrowed:
            narrowed.append(host)
    return tuple(narrowed)


@dataclass(frozen=True)
class LiveFetchWiring:
    """The wired handler path for the two keyless providers (D5)."""

    adapters: dict[str, Any]
    limiter: ProviderRateLimiter
    http_transport: ProviderHTTPTransport
    transport: RecordedTransport  # the boundary RecordedTransport:record
    hazard_specs: dict[str, Any]
    machinery: Any  # ProviderMachinery
    handlers: dict[str, Any]


def _pubmed_hazard_spec() -> Any:
    """Unshipped spec — PubMed has no shipped hazard_specs/*.json."""
    return load_hazard_spec(
        "pubmed",
        {
            "schema": "hermes-hazard-spec/v1",
            "provider_id": "pubmed",
            "version": "1.0.0",
            "markers": [],
            "empty_body_rule": "treat-as-failure",
            "error_field": None,
            "count_semantics": "exact",
            "counts_raw_rows": False,
            "required_fields": [],
            "cursor_rule": {"kind": "offset", "loop_guard": 100},
            "throttle_signature": [],
            "rewrite_suspect": [],
            "fetch": None,
            "valid_negative_statuses": [],
        },
    )


def _provider_clock(c: Any) -> Any:
    """Adapt a ``hermes.core`` clock (``Callable[[], str]`` or an object
    exposing ``now_utc``) into the provider Clock protocol (``now_utc`` +
    ``monotonic`` + optional ``sleep``). One adapter serves the limiter,
    the RecordedTransport, the machinery, and the sink.
    """

    class _AdaptedClock:
        def now_utc(self) -> str:
            try:
                v = c.now_utc()  # type: ignore[attr-defined]
                return str(v() if callable(v) else v)
            except AttributeError:
                return str(c())

        def monotonic(self) -> float:
            import time as _t

            return _t.monotonic()

        def sleep(self, delay: float) -> None:
            import time as _t

            _t.sleep(delay)

    return _AdaptedClock()


def build_live_fetch_wiring(
    conn: Any,
    store: Any,
    clock: Any,
    *,
    per_call_timeout_seconds: float = DEFAULT_PER_CALL_TIMEOUT_SECONDS,
    sandbox_policy: Any | None = None,
    autonomy_caps: Any | None = None,
    dns_resolve: Any | None = None,
    sink_conn: Any | None = None,
    sink_store: Any | None = None,
    sink_clock: Any | None = None,
) -> LiveFetchWiring:
    """Build the live handler path (record mode, journaled).

    The ``sink_*`` overrides let live tests bind the interaction sink to
    the same in-memory DB/store that records the task outcome (journaled).
    When absent they default to the supplied ``conn``/``store``/``clock``.
    ``autonomy_caps`` carries P-AUTO-4 narrow-only deadline/rate knobs
    (absent => code-owned D5 defaults); ``dns_resolve`` injects DNS for
    tests (default: real socket resolution).
    """
    if per_call_timeout_seconds <= 0:
        raise ValueError(
            "build_live_fetch_wiring: per_call_timeout_seconds must be > 0, "
            f"got {per_call_timeout_seconds!r}")
    allowlist = allowlist_from_config(sandbox_policy)
    operator = autonomy_caps if autonomy_caps is not None else sandbox_policy
    # ``sandbox_policy`` may itself carry autonomy fields (duck-typed) —
    # absent keys fall back to the code-owned D5 defaults inside the builders.
    rate_profiles = rate_profiles_from_autonomy(operator)
    adapters = {
        "openalex": OpenalexAdapter(),
        "pubmed": PubmedAdapter(),
    }
    sc = sink_conn if sink_conn is not None else conn
    ss = sink_store if sink_store is not None else store
    sk = _provider_clock(sink_clock if sink_clock is not None else clock)

    limiter = ProviderRateLimiter(
        rate_profiles,
        sk,  # type: ignore[arg-type]
    )

    # Per-call timeouts (D5: sandboxed egress with timeout discipline).
    # S11 caps stay on the transport; the task's size_cap is the evaluator's.
    http_inner = ProviderHTTPTransport(
        timeout=per_call_timeout_seconds,
        timeouts=dict.fromkeys(allowlist, per_call_timeout_seconds),
        size_cap_bytes=20 * 1024 * 1024,
    )
    inner_allowlisted: Any = _AllowlistedTransport(
        http_inner, allowlist=allowlist,
        resolve=dns_resolve or default_dns_resolve)
    sink = make_persisting_sink(sc, ss, sk)
    recorded = RecordedTransport(
        inner_allowlisted,
        resolve_provider=provider_resolver_for(adapters),
        clock=sk,
        mode="record",
        sink=sink,
    )
    # PubMed needs an unshipped hazard spec override (no shipped JSON).
    from hermes.tools.providers.paginate import _load_shipped_spec

    hazard_specs: dict[str, Any] = {
        "openalex": _load_shipped_spec("openalex"),
        "pubmed": _pubmed_hazard_spec(),
    }

    from hermes.research.source_handlers import (
        ProviderMachinery,
        make_source_fetch_handler,
        make_source_search_handler,
    )

    machinery = ProviderMachinery(
        adapters=adapters,
        transport=recorded,
        limiter=limiter,
        recorder=_NoopRecorder(),
        clock=sk,
        hazard_specs=hazard_specs,
    )
    # FIX-C1 — the narrowed operator deadline is INSTALLED into the live
    # handlers (building the policy object was never enough: the previous
    # wiring constructed handlers with defaults, so operator tightening
    # was silently ignored on the live path).
    dispatch_policy = source_policy_from_autonomy(operator)
    handlers = {
        "source_search": make_source_search_handler(
            machinery, policy=dispatch_policy),
        "source_fetch": make_source_fetch_handler(
            machinery, policy=dispatch_policy),
    }
    return LiveFetchWiring(
        adapters=adapters,
        limiter=limiter,
        http_transport=http_inner,
        transport=recorded,
        hazard_specs=hazard_specs,
        machinery=machinery,
        handlers=handlers,
    )


class _NoopRecorder:
    def record(self, log: Any) -> None:
        return None
