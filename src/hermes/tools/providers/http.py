"""ProviderHTTPTransport — the single HTTP client (blueprint §6.1a, §6.3).

Step 4 of the Part 3 implementation (IDR-030, §27 item 55 RESOLVED).
Remediated per the three hostile design gates
(`hermes_researchsourceprovider_ratelimit_review{,2,3}.md` — RT-01…RT-10,
RT2-01…RT2-06, RT3-01…RT3-05, all FOLDED IN 2026-08-14) and the fourth
gate on the shipped code (`hermes_researchsourceprovider_ratelimit_audit.md`
— TR-01/CAP-01/RL-01, FOLDED IN 2026-08-14).

The transport is the ONLY component that issues HTTP requests (PS-03 — the
only-entry-point invariant made structural by the driver's single call site)
and the ONLY component that raises provider errors (contract §7).

Exception class map (RT-02/RT2-01/RT2-06/RT3-01):

- raises ONLY `ProviderError` subclasses with a named `hazard_class` FOR
  TRANSPORT-LEVEL failures:
  - timeout/connection → `TransientProviderError(hazard_class="TIMEOUT")` —
    retryable per §6.3 (a bare `socket.timeout`/client exception is NEVER
    propagated);
  - the streaming download-abort → `PermanentProviderError(hazard_class=
    "PARTIAL_CONTENT")` — the S11 size-cap hard stop, firing ONLY on a 2xx
    status (RT3-01 (a)): an oversized 429/404 keeps its status for
    `evaluate_hazards`, the single status classifier. Never silent
    truncation of a good response.
- NEVER raises on an HTTP status (RT2-01): raising on 404 would kill the
  answered-lookup `VALID_NEGATIVE` (WS-01); raising on 429 would bypass
  `note_throttled`/Retry-After. All statuses flow to the evaluator.
- the redaction-`from None` discipline (PS-02/PS2-04/PS3-07): every
  exception message is built from the policy-redacted request form
  (`redact_url` + `redact_params`) and raised `from None` — a timeout or
  connection error can never leak a query-auth credential or a polite-pool
  email into a task output or event.
- a NON-`ProviderError` exception escaping this transport is a BUG — the
  driver's catch-all RE-RAISES it (RT2-06), never a `MALFORMED_200` schema
  verdict; every other failure inside is converted to a typed provider
  error here (a bare client-library exception is never propagated). The
  class map covers the BODY-READ phase as well as `urlopen` (TR-01,
  fourth gate): a mid-download read timeout / connection reset /
  `IncompleteRead` maps to `TransientProviderError(TIMEOUT)` — it can
  never escape bare and crash the walk; the size-abort
  `PermanentProviderError` passes through untouched.

S11 defaults (contract §11 / v6 §15): bounded downloads — timeouts + size
caps, scale classes `tiny → huge`. The completed-body size check and the
content-type check live in the EVALUATOR (`hazards.py`, RT2-04/RT3-01/04) —
this transport only surfaces the normalized media type via
`TransportResponse.content_type`. Stdlib-only (urllib) per the stdlib-first
policy; external SDKs stay behind ports.

`timeouts`/`size_caps` are per-netloc overrides (RequestSpec carries no
provider id — the netloc is the stable per-provider key) — config, not
code; operator-config validation remains at P7.

A1 (P-AUTO-3 redteam): the opener is the redirect authority — every 3xx
hop is re-vetted, only a same-origin https hop is followed, and every
other hop is refused by returning the 3xx status to the caller (never
chased, never raise-on-status; the evaluator classifies, the recorder
journals).
"""
from __future__ import annotations

import http.client
import socket
import threading as _threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, NoReturn

from hermes.tools.providers.base import RequestSpec, TransportResponse
from hermes.tools.providers.redact import DEFAULT_POLICY, RedactionPolicy, redact_url
from hermes.tools.research_sources import (
    PermanentProviderError,
    TransientProviderError,
)

__all__ = [
    "DEFAULT_SIZE_CAP_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "PinnedHTTPSHandler",
    "ProviderHTTPTransport",
    "clear_pinned_host",
    "pin_host_for_request",
]

# S11 shipped defaults (scale-class `medium`; config, not code — P7 makes
# them operator-configurable). A JATS full-text XML can exceed 10 MiB, so the
# completed-body cap is generous; the per-task `WalkRequest.size_cap_bytes`
# is the real bound the evaluator enforces.
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_SIZE_CAP_BYTES = 20 * 1024 * 1024  # 20 MiB

_READ_CHUNK = 64 * 1024


# ── A1 (P-AUTO-3 redteam MUST-FIX): every redirect hop is re-vetted ──
# urllib's default redirect handler follows every 3xx, including off-origin
# hops that never pass a caller's allowlist (the audited bypass: the
# one-shot allowlist check ran before `urlopen`, the chain after it did
# not). The transport's opener replaces the default handler with one that
# follows ONLY a same-origin https hop; every other hop is refused by
# returning None, which lets urllib surface the 3xx as an HTTPError that
# `request()` returns as a normal TransportResponse — never followed,
# never raise-on-status (RT2-01): the evaluator classifies the status and
# the recorder journals it (refuse-and-record).


def _origin_of(url: str) -> tuple[str, str, int] | None:
    """(scheme, host, effective port) of an https URL, else None.

    None covers every refusal case: non-https (a scheme downgrade or an
    http chain is never followable), a missing host, credentials smuggled
    into the URL, and unparseable ports.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or not host:
        return None
    if parts.username or parts.password:
        return None
    return (parts.scheme, host.lower(), port or 443)


def _same_origin_https(a: str, b: str) -> bool:
    """True iff both URLs share one https origin (scheme+host+port).

    The comparison is against the CURRENT hop's URL and only same-origin
    hops are followed, so the chain can never leave the origin the request
    was pointed at — and that origin already passed the caller's allowlist
    (the live wiring's `_AllowlistedTransport`), making a followed hop a
    strict subset of the allowlisted surface.
    """
    origin_a = _origin_of(a)
    return origin_a is not None and origin_a == _origin_of(b)


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow a 3xx only to the request's own https origin (A1).

    `build_opener` drops its default HTTPRedirectHandler when a subclass is
    supplied, so this is the single redirect authority for the opener. A
    refused hop returns None — `http_error_302` then does not open a new
    request, and urllib's default error path raises HTTPError, which the
    transport returns as a 3xx TransportResponse.
    """

    def redirect_request(self, req: urllib.request.Request,
                         fp: Any, code: int, msg: str, headers: Any,
                         newurl: str) -> urllib.request.Request | None:
        if not _same_origin_https(req.full_url, newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener(
    *extra: urllib.request.BaseHandler,
    pin_resolver: Any | None = None,
) -> urllib.request.OpenerDirector:
    """Build an opener whose redirect authority is the A1 handler.

    P-AUTO-4 proxy-path: the opener carries an EMPTY ``ProxyHandler({})``
    unless the caller supplies its own — guarded fetches never honor
    ``HTTPS_PROXY``/``HTTP_PROXY`` env proxies, so a proxy can never bypass
    the allowlist (the proxy would dial exfiltration the gate refused).
    (Audit NOTE: on this Python an empty mapping leaves no ProxyHandler in
    ``opener.handlers`` at all — the outcome is what matters: no proxy
    authority survives, env proxies are ignored.)

    FIX-D — ``pin_resolver`` (``host -> ip | None``): when given, the
    default exact-type ``HTTPSHandler`` is replaced with a
    ``PinnedHTTPSHandler`` that dials the resolver's address while keeping
    the hostname for Host/TLS-SNI. Subclass handlers supplied via ``extra``
    (e.g. scripted test doubles) are kept and still win the chain.
    """
    for handler in extra:
        if isinstance(handler, urllib.request.ProxyHandler):
            opener = urllib.request.build_opener(
                _SameOriginRedirectHandler(), *extra)
            break
    else:
        opener = urllib.request.build_opener(
            _SameOriginRedirectHandler(), urllib.request.ProxyHandler({}),
            *extra)
    if pin_resolver is not None:
        # OpenerDirector.handlers is runtime-visible but absent from
        # typeshed — getattr/setattr keep the strict gate green while the
        # behavior stays exact (drop only the default handler, keep every
        # subclass such as scripted test doubles).
        current = list(getattr(opener, "handlers", []))
        setattr(opener, "handlers", [
            h for h in current
            if type(h) is not urllib.request.HTTPSHandler
        ])
        opener.add_handler(PinnedHTTPSHandler(pin_for=pin_resolver))
    return opener


# ── FIX-D — pinned dial (S2 pin mechanics for the stdlib transport) ──
# The DNS gate vets an address; this layer dials exactly that address.
# Without the pin, the socket re-resolves the hostname and a flip between
# vet and dial redirects the connection (TOCTOU). Thread-local: concurrent
# walks each pin their own host; pins live for exactly one gate request
# (set/restore around the inner call) and never leak across requests.

_PINNED_TLS = _threading.local()


def _pinned_table() -> dict[str, str]:
    table = getattr(_PINNED_TLS, "hosts", None)
    if table is None:
        table = {}
        _PINNED_TLS.hosts = table
    return table


def pin_host_for_request(host: str, address: str) -> str | None:
    """Publish the vetted ``address`` for ``host``; returns the prior pin."""
    table = _pinned_table()
    prior = table.get(host)
    table[host] = address
    return prior


def clear_pinned_host(host: str, address: str | None = None) -> None:
    """Withdraw a request pin (restoring is unnecessary — pins are single
    request scoped; a stale entry for the same host would only ever hold
    an address that passed vetting seconds earlier, but clearing keeps the
    table exactly request-scoped)."""
    table = _pinned_table()
    if address is None or table.get(host) == address:
        table.pop(host, None)


def _lookup_pin(host: str) -> str | None:
    return _pinned_table().get(host)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection dialing ``pinned_ip`` with the hostname's SNI/cert.

    Mirrors the parent ``connect`` exactly (tunnel branch included) except
    the socket goes to the vetted address. Host header and TLS SNI keep the
    hostname — certificates verify as usual; only the dial target is pinned.
    """

    def __init__(self, *args: Any, pinned_ip: str | None = None,
                 **kwargs: Any) -> None:
        if not pinned_ip:
            raise ValueError(
                "PinnedHTTPSConnection: pinned_ip is required (fail-closed — "
                "an unpinned dial must never silently fall back to DNS)")
        self._pinned_ip = pinned_ip
        super().__init__(*args, **kwargs)

    def connect(self) -> None:
        sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout)
        # _tunnel_host/_context are set by the parent constructor (runtime
        # attributes beyond the typeshed stubs — getattr keeps strict
        # pyright green; a missing context fails loudly at wrap_socket).
        tunnel_host = getattr(self, "_tunnel_host", None)
        context = getattr(self, "_context")
        server_hostname = tunnel_host or self.host
        self.sock = context.wrap_socket(
            sock, server_hostname=server_hostname)


class PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """HTTPS opener handler that dials vetted pins (FIX-D).

    ``pin_for`` maps a hostname to its vetted address (or None). A pinned
    host opens through ``connection_cls`` (default
    ``_PinnedHTTPSConnection``, injectable for tests); an unpinned host
    takes the normal path — pinning is strictly additive, never a
    fallback, never a bypass.
    """

    def __init__(self, pin_for: Any | None = None,
                 connection_cls: Any | None = None) -> None:
        super().__init__()
        self._pin_for = pin_for or (lambda host: None)
        self._connection_cls = connection_cls or _PinnedHTTPSConnection

    def https_open(self, req: urllib.request.Request) -> Any:
        pin = self._pin_for(req.host)
        if pin is None:
            return super().https_open(req)
        connection_cls = self._connection_cls

        def _connect(host: str, **kwargs: Any) -> Any:
            return connection_cls(host, pinned_ip=pin, **kwargs)

        return self.do_open(
            _connect, req, context=getattr(self, "_context", None))


_OPENER: urllib.request.OpenerDirector = _build_opener(
    pin_resolver=_lookup_pin)


def _open_request(req: urllib.request.Request, timeout: float) -> Any:
    """The transport's ONE stdlib request call site (through `_OPENER`).

    Kept as a module-level seam: tests script responses here, production
    always routes through the redirect-refusing opener.
    """
    return _OPENER.open(req, timeout=timeout)


def _content_type_of(headers: dict[str, str]) -> str | None:
    """The normalized media type (``text/xml; charset=utf-8`` → ``text/xml``),
    or None when the header is absent. The evaluator compares this against
    the per-provider allowlist (RT-05/RT2-04)."""
    raw = headers.get("Content-Type") or headers.get("content-type")
    if not raw:
        return None
    return raw.split(";", 1)[0].strip().lower()


class ProviderHTTPTransport:
    """Implements the `Transport` protocol (base.py) with urllib.

    Constructed with the `RedactionPolicy` (contract §7 — the transport is
    the only component that raises provider errors; every message is
    redaction-safe). `timeouts`/`size_caps` override the S11 defaults per
    netloc.
    """

    def __init__(
        self,
        redaction: RedactionPolicy = DEFAULT_POLICY,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        size_cap_bytes: int = DEFAULT_SIZE_CAP_BYTES,
        timeouts: dict[str, float] | None = None,
        size_caps: dict[str, int] | None = None,
        user_agent: str = "khwarizmi-research-provider/0.1 (research-source-provider)",
    ) -> None:
        if timeout <= 0:
            raise ValueError(f"ProviderHTTPTransport: timeout must be > 0, got {timeout!r}")
        if size_cap_bytes <= 0:
            raise ValueError(
                f"ProviderHTTPTransport: size_cap_bytes must be > 0, got {size_cap_bytes!r}")
        self._policy = redaction
        self._timeout = timeout
        self._size_cap_bytes = size_cap_bytes
        self._timeouts = dict(timeouts or {})
        self._size_caps = dict(size_caps or {})
        self._user_agent = user_agent

    # ── the Transport protocol ──

    def request(self, spec: RequestSpec) -> TransportResponse:
        """Issue one GET and return the response — status + raw bytes +
        headers + the normalized media type.

        Raises ONLY for transport-level failures (RT-02/RT2-01/RT3-01) —
        never on an HTTP status. Timeout/connection → `TIMEOUT` transient;
        the streaming size-abort fires ONLY on a 2xx status →
        `PARTIAL_CONTENT` permanent.
        """
        url = self._build_url(spec)
        netloc = urllib.parse.urlsplit(url).netloc
        timeout = self._timeouts.get(netloc, self._timeout)
        cap = self._size_caps.get(netloc, self._size_cap_bytes)
        headers = {"User-Agent": self._user_agent}
        headers.update({k: v for k, v in spec.headers_meta.items() if v})
        req = urllib.request.Request(url, headers=headers)
        try:
            resp = _open_request(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            # RT2-01 — NEVER raise on an HTTP status: urllib surfaces every
            # non-2xx as HTTPError; it is RETURNED as a TransportResponse so
            # evaluate_hazards (the single status classifier) sees the
            # status — a 404 keeps its answered-lookup VALID_NEGATIVE, a
            # 429 keeps its THROTTLED/note_throttled/Retry-After path.
            status = int(exc.code)
            headers_out = dict(exc.headers.items())
            try:
                body = self._read_body(exc, status, cap, url)
            except PermanentProviderError:
                raise  # the size-abort class — intended, never swallowed
            except (TimeoutError, ConnectionError, OSError,
                    http.client.HTTPException):
                # TR-01 (fourth gate) — the class map covers the BODY-READ
                # phase too: a mid-download timeout/reset/IncompleteRead on
                # an error page is still a transport-level transient.
                self._raise_transient(url, "aborted response")
            except Exception as exc2:  # pragma: no cover — defensive  # noqa: BLE001
                self._raise_transient(url, f"transport error: {type(exc2).__name__}")
            finally:
                exc.close()
            return TransportResponse(
                status=status, body=body, headers=headers_out,
                content_type=_content_type_of(headers_out))
        except urllib.error.URLError as exc:
            # DNS / connection-refused (HTTPError is caught above — this is
            # the transport-level remainder).
            if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)):
                self._raise_timeout(url)
            self._raise_transient(url, "connection error")
        except TimeoutError:
            self._raise_timeout(url)
        except (ConnectionError, OSError):
            # socket.timeout is TimeoutError (3.10+); ConnectionReset etc.
            self._raise_transient(url, "connection error")
        except http.client.HTTPException:
            self._raise_transient(url, "incomplete/aborted response")
        except Exception as exc:  # pragma: no cover — defensive  # noqa: BLE001
            # A bare client-library exception is NEVER propagated (RT-02):
            # unknown transport failures are transient (retryable, bounded),
            # never a permanent schema verdict.
            self._raise_transient(url, f"transport error: {type(exc).__name__}")

        try:
            status = int(resp.status)
            headers_out = dict(resp.headers.items())
            # RT3-01 (a) — the streaming size-abort fires ONLY on a 2xx
            # status: a throttled or error response keeps its status for
            # evaluate_hazards (an oversized 429 is THROTTLED, never
            # PARTIAL_CONTENT — status evidence dominates).
            body = self._read_body(resp, status, cap, url)
            return TransportResponse(
                status=status, body=body, headers=headers_out,
                content_type=_content_type_of(headers_out))
        except PermanentProviderError:
            raise  # the size-abort class — intended, never swallowed
        except (TimeoutError, ConnectionError, OSError,
                http.client.HTTPException):
            # TR-01 (fourth gate) — the exception class map covers the
            # BODY-READ phase, not just `urlopen`: a mid-download read
            # timeout / connection reset / IncompleteRead is a transport-
            # level TRANSIENT (retryable per §6.3), NEVER a bare exception
            # that would escape the transport and crash the walk (the RT-02
            # "never propagated" promise, held at the read boundary).
            self._raise_transient(url, "aborted response")
        except Exception as exc:  # pragma: no cover — defensive  # noqa: BLE001
            self._raise_transient(url, f"transport error: {type(exc).__name__}")
        finally:
            resp.close()

    # ── internals ──

    def _build_url(self, spec: RequestSpec) -> str:
        """Merge the declared params into the URL query (deterministic sort —
        the recorder's fingerprint discipline, PS-06)."""
        parts = urllib.parse.urlsplit(spec.url)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        query.extend(sorted(spec.params.items()))
        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query),
             parts.fragment))

    def _read_body(self, resp: object, status: int, cap: int, url: str) -> bytes:
        """Stream the body in chunks; abort mid-download on a 2xx size-cap
        hit (RT3-01 (a) — permanent, never silent truncation). A NON-2xx
        oversized response is drained up to the cap and returned with its
        status (the evaluator classifies it; known throttle signatures are
        small, so the truncated body cannot hide a real signal — the status
        is the evidence)."""
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = resp.read(_READ_CHUNK)  # type: ignore[attr-defined]
            if not chunk:
                break
            total += len(chunk)
            if 200 <= status < 300 and total > cap:
                raise PermanentProviderError(
                    self._redacted_message(
                        url, f"response body exceeds the size cap ({cap} bytes)"),
                    hazard_class="PARTIAL_CONTENT",
                ) from None
            if total > cap:
                # non-2xx oversized — keep the status (the evaluator
                # classifies it); stop reading and return the first chunk
                chunks.append(chunk)
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def _redacted_message(self, url: str, detail: str) -> str:
        """Every exception message is built from the policy-redacted request
        form (PS-02/PS2-04/PS3-07) — a transport failure can never leak a
        credential or a polite identifier."""
        return f"{detail} for {redact_url(url, self._policy)}"

    def _raise_timeout(self, url: str) -> NoReturn:
        raise TransientProviderError(
            self._redacted_message(url, "request timed out"),
            hazard_class="TIMEOUT",
        ) from None

    def _raise_transient(self, url: str, detail: str) -> NoReturn:
        raise TransientProviderError(
            self._redacted_message(url, detail),
            hazard_class="TIMEOUT",
        ) from None
