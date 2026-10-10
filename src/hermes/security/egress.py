"""egress — the Khwarizmi-owned network egress guard (adoption §4 / Spike S2).

Deterministic, stdlib-only. The guard exists because crawl4ai "deliberately has
no egress policy of its own" (`crawl4ai/egress_policy.py` at 0.9.4) and because
URL safety for a library used as a library is the caller's responsibility.
That same library docstring records why a validator hook is insufficient — a
validator "resolves the name, checks it and then throws the address away — the
client re-resolves when it dials, which is the DNS-rebinding window". This
module therefore owns the socket:

- :class:`EgressPolicy` — the rule layer. Reads the operator allowlist from
  ``SandboxPolicy.network_egress_allowlist`` (config.py:60; empty = deny all,
  fail closed — IDR-006). Rules: http/https only, credentials in the URL
  refused, origin must be allowlisted, the host must resolve, and **every**
  resolved address must be public (loopback, link-local, RFC1918, CGNAT
  shared space, multicast, unspecified, reserved and IPv4-mapped bypasses all
  refused — a mixed public/private answer set is refused as a whole).
- :class:`GuardedFetcher` — the enforcement layer. Each hop is re-vetted and
  dialed at the **pinned** address (Host header / TLS SNI keep the hostname),
  so the address that was checked is the address that is dialed. Redirects are
  followed manually, at most ``max_redirects`` times, with a fresh vet per hop:
  a redirect to an internal address is refused, never followed.

Scope: this module is new deterministic security code and is imported by the
S2 spike provider only. It is not wired into ``ProviderHTTPTransport`` (the
certified PS-03 single HTTP entry point) — that reconciliation is a design-gate
decision recorded in S2-EGRESS-CRAWL4AI-SPIKE.md.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable

from hermes.config import SandboxPolicy

__all__ = [
    "EgressPolicy",
    "EgressRefused",
    "FetchedPage",
    "GuardedFetcher",
    "VettedTarget",
]

ALLOWED_SCHEMES = ("http", "https")
_DEFAULT_PORTS = {"http": 80, "https": 443}
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_NO_BODY_STATUSES = frozenset({204, 304})

# Non-global IPv6 nets the guard must refuse regardless of stdlib drift.
# These classes are not globally routable but Python's ``ipaddress`` may
# still report ``is_global=True`` (verified on the pinned 3.14.1):
#   - fec0::/10  — RFC 3879-deprecated site-local (obsolete, must refuse)
#   - 3ffe::/16  — RFC 3701-returned 6bone testnet (obsolete, must refuse)
# The membership check runs *before* the ``is_global`` fallthrough so the
# core promise does not inherit stdlib drift on these nets. (AUDIT-S2 A1.)
_NON_GLOBAL_V6_NETS: tuple[ipaddress.IPv6Network, ...] = (
    ipaddress.IPv6Network("fec0::/10"),
    ipaddress.IPv6Network("3ffe::/16"),
)


class EgressRefused(Exception):
    """A refusal with a closed-set code — refusal-as-data, never silent."""

    def __init__(self, code: str, host: str, detail: str) -> None:
        self.code = code
        self.host = host
        self.detail = detail
        super().__init__(f"egress refused [{code}] {host or '<no host>'}: "
                         f"{detail}")


@dataclass(frozen=True, slots=True)
class VettedTarget:
    """A URL that passed every rule, plus the address the fetch must dial."""

    url: str
    scheme: str
    host: str          # hostname as written (Host header / TLS SNI)
    port: int
    origin: str        # canonical origin ("scheme://host[:port]")
    addresses: tuple[str, ...]  # all resolved addresses, sorted
    pinned: str        # the address to dial (first of the sorted set)

    def build_path(self) -> str:
        parts = urllib.parse.urlsplit(self.url)
        path = parts.path or "/"
        return f"{path}?{parts.query}" if parts.query else path


def _host_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return ""


def _is_ip_literal(host: str) -> str | None:
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def _blocked_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """The named reason an address may not be dialed, or '' when it is public."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _blocked_reason(ip.ipv4_mapped)  # never let ::ffff:127.0.0.1 pass
    # Explicit non-global v6 net check (AUDIT-S2 A1) — runs before any
    # stdlib boolean so fec0::/10 (site-local, RFC 3879 deprecated) and
    # 3ffe::/16 (6bone, RFC 3701 returned) cannot leak past on stdlib drift.
    if isinstance(ip, ipaddress.IPv6Address):
        for net in _NON_GLOBAL_V6_NETS:
            if ip in net:
                if net.network_address == ipaddress.IPv6Address("fec0::"):
                    return "site-local (fec0::/10, deprecated RFC 3879)"
                return "6bone (3ffe::/16, returned RFC 3701)"
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_multicast:
        return "multicast"
    if ip.is_reserved:
        return "reserved"
    if ip.is_private:
        return "private (RFC1918/ULA)"
    if not ip.is_global:
        return "not globally routable"
    return ""


def _default_resolve(host: str, port: int) -> tuple[str, ...]:
    """All addresses for ``host`` (socket.getaddrinfo, deterministic sort)."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = {str(info[4][0]).partition("%")[0] for info in infos}
    return tuple(sorted(addresses))


def _canonical_origin(scheme: str, host: str, port: int) -> str:
    if _DEFAULT_PORTS.get(scheme) == port:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _parse_origin(entry: str) -> str:
    """Validate one operator allowlist entry; return its canonical origin."""
    parts = urllib.parse.urlsplit(entry)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise ValueError(
            f"egress allowlist entry {entry!r}: scheme must be one of "
            f"{ALLOWED_SCHEMES}")
    if not parts.hostname:
        raise ValueError(f"egress allowlist entry {entry!r}: missing host")
    if parts.path or parts.query or parts.fragment:
        raise ValueError(
            f"egress allowlist entry {entry!r}: must be an origin "
            f"(scheme://host[:port]), not a URL with path/query/fragment")
    try:
        port = parts.port if parts.port is not None else _DEFAULT_PORTS[parts.scheme]
    except ValueError as exc:
        raise ValueError(
            f"egress allowlist entry {entry!r}: invalid port") from exc
    return _canonical_origin(parts.scheme, parts.hostname.lower(), port)


@dataclass(frozen=True, slots=True)
class EgressPolicy:
    """The rule layer: scheme allowlist, origin allowlist, public-address rule."""

    allowlist: tuple[str, ...] = ()
    max_redirects: int = 5

    def __post_init__(self) -> None:
        canonical = tuple(_parse_origin(entry) for entry in self.allowlist)
        if len(set(canonical)) != len(canonical):
            raise ValueError("egress allowlist contains duplicate origins")
        if self.max_redirects < 0:
            raise ValueError("max_redirects must be >= 0")
        object.__setattr__(self, "allowlist", tuple(sorted(canonical)))

    @classmethod
    def from_config(cls, sandbox: SandboxPolicy) -> "EgressPolicy":
        """Wire ``SandboxPolicy.network_egress_allowlist`` (config.py:60).

        The field's documented default is empty — fail closed until an operator
        configures an origin (IDR-006).
        """
        return cls(allowlist=tuple(sandbox.network_egress_allowlist))

    def fingerprint(self) -> str:
        payload = json.dumps(
            {"allowlist": list(self.allowlist),
             "max_redirects": self.max_redirects},
            sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def vet(
        self,
        url: str,
        *,
        resolve: Callable[[str, int], tuple[str, ...]] | None = None,
    ) -> VettedTarget:
        """Validate one URL and pin the address to dial, or refuse with a code."""
        host = _host_of(url)
        try:
            parts = urllib.parse.urlsplit(url)
            port = parts.port
        except ValueError as exc:
            raise EgressRefused("MALFORMED_URL", host,
                                f"unparseable URL ({exc})") from None
        if not parts.scheme:
            raise EgressRefused("MALFORMED_URL", host,
                                "an absolute URL is required")
        if parts.username is not None or parts.password is not None:
            raise EgressRefused("CREDENTIALS_IN_URL", parts.hostname or host,
                                "userinfo is refused; credentials never enter "
                                "a fetched URL")
        if parts.scheme not in ALLOWED_SCHEMES:
            raise EgressRefused("SCHEME_NOT_ALLOWED", parts.hostname or host,
                                f"scheme {parts.scheme!r} is not one of "
                                f"{ALLOWED_SCHEMES}")
        if not parts.hostname:
            raise EgressRefused("MALFORMED_URL", host,
                                "an absolute http(s) URL is required")
        if port is None:
            port = _DEFAULT_PORTS[parts.scheme]
        canonical_host = parts.hostname.lower().rstrip(".")
        origin = _canonical_origin(parts.scheme, canonical_host, port)
        if origin not in self.allowlist:
            raise EgressRefused(
                "ORIGIN_NOT_ALLOWLISTED", canonical_host,
                f"{origin!r} is not in the operator egress allowlist "
                f"(add it to sandbox.network_egress_allowlist)")

        literal = _is_ip_literal(canonical_host)
        if literal is not None:
            addresses = (literal,)
        else:
            resolver = resolve or _default_resolve
            try:
                addresses = tuple(resolver(canonical_host, port))
            except Exception as exc:  # noqa: BLE001 — rejection is data, never bare
                # AUDIT-USERINFO SF-2: the resolver is an INJECTED seam
                # (``build_live_fetch_wiring(dns_resolve=…)``, tests), and its
                # contract permits the whole Exception family — the OSError /
                # socket.gaierror pair from ``socket.getaddrinfo``, ValueError
                # (a bad name; UnicodeError, JSONDecodeError), RuntimeError
                # (incl. NotImplementedError), KeyError (a table-backed
                # resolver), TypeError, and any resolver-defined class. EVERY
                # one is a resolution failure, and the base gate refused them
                # all with a typed error; fail closed the same way here:
                # refusals are data with a code, never a bare exception. The
                # class name stays in the detail for diagnosability.
                raise EgressRefused(
                    "DNS_FAILURE", canonical_host,
                    f"resolution failed ({type(exc).__name__})") from None
        if not addresses:
            raise EgressRefused("NO_ADDRESSES", canonical_host,
                                "resolution returned no addresses")
        # Sorting is the provider's own determinism rule (independent of
        # resolver ordering): pin the lexicographically first address.
        addresses = tuple(sorted(set(addresses)))
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                raise EgressRefused(
                    "NO_ADDRESSES", canonical_host,
                    f"resolver returned a non-address {address!r}") from None
            reason = _blocked_reason(ip)
            if reason:
                raise EgressRefused(
                    "ADDRESS_BLOCKED", canonical_host,
                    f"resolved address {address} is {reason}")
        return VettedTarget(
            url=url,
            scheme=parts.scheme,
            host=canonical_host,
            port=port,
            origin=origin,
            addresses=tuple(addresses),
            pinned=addresses[0],
        )


@dataclass(frozen=True, slots=True)
class _RawResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


@dataclass(frozen=True, slots=True)
class FetchedPage:
    """One guarded fetch: status/headers/body plus the full guard trail."""

    requested_url: str
    url: str
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes
    hops: tuple[str, ...]
    vetted: tuple[VettedTarget, ...] = ()  # one per dialed hop (pinned address)

    def header(self, name: str) -> str | None:
        lowered = name.lower()
        for key, value in self.headers:
            if key.lower() == lowered:
                return value
        return None

    @property
    def content_type(self) -> str | None:
        raw = self.header("Content-Type")
        return raw.split(";", 1)[0].strip().lower() if raw else None


def _read_limited(response: Any, max_bytes: int, url: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise EgressRefused(
                "BODY_TOO_LARGE", _host_of(url),
                f"response exceeded the {max_bytes}-byte fetch cap")
        chunks.append(chunk)
    return b"".join(chunks)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTPconnection that dials ``pinned_ip`` while keeping the hostname."""

    def __init__(self, host: str, pinned_ip: str, port: int,
                 timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection dialing ``pinned_ip`` with the hostname's SNI/cert."""

    def __init__(self, host: str, pinned_ip: str, port: int, timeout: float,
                 context: ssl.SSLContext) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._pinned_ip = pinned_ip
        self._ssl_context = context

    def connect(self) -> None:
        sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout)
        self.sock = self._ssl_context.wrap_socket(
            sock, server_hostname=self.host)


def _default_open(
    target: VettedTarget,
    *,
    timeout: float,
    max_bytes: int,
    user_agent: str,
) -> _RawResponse:
    """The real pinned connection (http or https) for one hop."""
    if target.scheme == "https":
        connection: http.client.HTTPConnection = _PinnedHTTPSConnection(
            target.host, target.pinned, target.port, timeout,
            ssl.create_default_context())
    else:
        connection = _PinnedHTTPConnection(
            target.host, target.pinned, target.port, timeout)
    try:
        connection.request(
            "GET", target.build_path(),
            headers={"User-Agent": user_agent, "Accept": "*/*"})
        response = connection.getresponse()
        body = (b"" if response.status in _NO_BODY_STATUSES
                else _read_limited(response, max_bytes, target.url))
        return _RawResponse(
            status=int(response.status),
            headers=tuple(response.getheaders()),
            body=body)
    finally:
        connection.close()


class GuardedFetcher:
    """The enforcement layer: per-hop vetting + pinned dialing.

    ``open_fn`` is injectable so the redirect/re-validation behaviour is
    unit-tested deterministically with canned responses; the default is the
    stdlib pinned connection above.
    """

    def __init__(
        self,
        policy: EgressPolicy,
        *,
        resolve: Callable[[str, int], tuple[str, ...]] | None = None,
        open_fn: Callable[..., _RawResponse] | None = None,
        timeout: float = 30.0,
        max_bytes: int = 5 * 1024 * 1024,
        user_agent: str = "khwarizmi-research-egress/0.1 (guarded fetch)",
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be > 0")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be > 0")
        self._policy = policy
        self._resolve = resolve
        self._open = open_fn or _default_open
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._user_agent = user_agent

    @property
    def policy(self) -> EgressPolicy:
        return self._policy

    def fetch(self, url: str) -> FetchedPage:
        """Fetch ``url``, re-vetting and re-pinning every hop."""
        current = url
        hops: list[str] = []
        vetted: list[VettedTarget] = []
        for _ in range(self._policy.max_redirects + 1):
            target = self._policy.vet(current, resolve=self._resolve)
            vetted.append(target)
            response = self._open(
                target, timeout=self._timeout, max_bytes=self._max_bytes,
                user_agent=self._user_agent)
            if len(response.body) > self._max_bytes:
                raise EgressRefused(
                    "BODY_TOO_LARGE", target.host,
                    f"response exceeded the {self._max_bytes}-byte fetch cap")
            if response.status in _REDIRECT_STATUSES:
                location = None
                for key, value in response.headers:
                    if key.lower() == "location":
                        location = value
                        break
                if not location:
                    raise EgressRefused(
                        "REDIRECT_WITHOUT_LOCATION", target.host,
                        f"HTTP {response.status} without a Location header")
                # AUDIT-S2 B1 — normalize Location before urljoin so whitespace
                # padding + control characters refuse inside the closed set
                # (was: only the stdlib wire closed-set; padded URLs reached the
                # rebuilt URL and bypassed the trail discipline).
                location = location.strip()
                if any(ord(c) < 0x20 or ord(c) == 0x7f for c in location):
                    raise EgressRefused(
                        "BAD_REDIRECT_URL", target.host,
                        "Location contains control characters")
                hops.append(current)
                try:
                    current = urllib.parse.urljoin(current, location)
                except ValueError as exc:
                    raise EgressRefused(
                        "BAD_REDIRECT_URL", target.host,
                        f"unparseable redirect target ({exc})") from None
                # AUDIT-S2 B2 — refuse same-origin scheme downgrade (https→http on
                # the same host:port). The operator allowlist is scheme-
                # scoped; shedding TLS on a redirect the server chooses is
                # not a policy we want to silently accept.
                next_parts = urllib.parse.urlsplit(current)
                if (target.scheme == "https"
                        and next_parts.scheme == "http"
                        and (next_parts.hostname or "") == target.host
                        and (next_parts.port
                             or _DEFAULT_PORTS["http"]) == target.port):
                    raise EgressRefused(
                        "SCHEME_DOWNGRADE", target.host,
                        "redirect shed TLS: https→http on the same origin")
                continue
            return FetchedPage(
                requested_url=url,
                url=current,
                status=response.status,
                headers=response.headers,
                body=response.body,
                hops=tuple(hops),
                vetted=tuple(vetted),
            )
        raise EgressRefused(
            "TOO_MANY_REDIRECTS", _host_of(url),
            f"more than {self._policy.max_redirects} redirects")
