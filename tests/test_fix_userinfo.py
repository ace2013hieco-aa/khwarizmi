"""FIX-USERINFO — the live-fetch egress gate must read the host the way
``urlsplit`` reads it (``parts.hostname``), never by slicing ``netloc``.

Audited bypass: ``netloc.split(":")[0]`` reads ``"api.openalex.org"`` out
of::

    https://api.openalex.org:foo@evil.example/works

— the userinfo prefix is mistaken for the host — while the URL's actual
host is ``evil.example``. The rogue URL therefore passed the allowlist and
was DNS-vetted and PINNED under the WRONG host (``api.openalex.org``, which
resolves publicly): the verdict was keyed on a name that is not the URL's
host. Measured on the base gate, that URL never reached ``evil.example`` —
the shipped transport's own parser refuses it pre-connect (``InvalidURL``,
no connect attempted); the LIVE row is the sibling spelling below, where the
same slicing truncated a non-default explicit port off the allowlisted host
(``netloc`` cut at the first ``:``) and base dialed the non-allowlisted
origin unpinned. The fix refuses BOTH pre-connect: userinfo with
``CREDENTIALS_IN_URL``, a different origin with ``ORIGIN_NOT_ALLOWLISTED``.

The gate is now a thin adapter over the ONE rule layer,
``hermes.security.egress.EgressPolicy.vet`` (scheme, userinfo, origin+port,
DNS, public-address rule) and re-raises the layer's named code inside the
gate's ``ProviderValidationError``. These tests pin the audit URL, the
port/userinfo variants, the adapter passthrough chain, and the legitimate
fetches that must stay green.
"""
from __future__ import annotations

import urllib.request
from types import SimpleNamespace

import pytest

import hermes.tools.providers.http as http_module
from hermes.research.live_fetch import ALLOWLIST_HOSTS, _AllowlistedTransport
from hermes.tools.providers.adapters.openalex import OpenalexAdapter
from hermes.tools.providers.base import RequestSpec, TransportResponse
from hermes.tools.research_sources import ProviderValidationError

PUBLIC_IP = "93.184.216.34"

# The audited URL, verbatim. ``urlsplit`` reads host ``evil.example`` and
# userinfo ``api.openalex.org:foo``; the old gate read host
# ``api.openalex.org`` and vetted/pinned the request under that name (the
# shipped transport refuses this URL pre-connect — see the module docstring).
AUDIT_URL = "https://api.openalex.org:foo@evil.example/works"

# Every URL here must be refused BEFORE any I/O and before any resolution.
REFUSED_URLS: tuple[tuple[str, str, str], ...] = (
    # (url, expected named code, expected host in the refusal)
    (AUDIT_URL, "CREDENTIALS_IN_URL", "evil.example"),
    # userinfo variants — userinfo is never allowed, whichever side it sits
    ("https://api.openalex.org@evil.example/works",
     "CREDENTIALS_IN_URL", "evil.example"),
    ("https://evil.example@api.openalex.org/works",
     "CREDENTIALS_IN_URL", "api.openalex.org"),
    ("https://api.openalex.org:foo@api.openalex.org/works",
     "CREDENTIALS_IN_URL", "api.openalex.org"),
    ("https://user:pass@api.openalex.org/works",
     "CREDENTIALS_IN_URL", "api.openalex.org"),
    # non-default explicit port on an allowlisted host — the origin is
    # ``https://host:8443``, which is not the allowlisted origin
    ("https://api.openalex.org:8443/works",
     "ORIGIN_NOT_ALLOWLISTED", "api.openalex.org"),
    ("https://api.openalex.org:8080/works",
     "ORIGIN_NOT_ALLOWLISTED", "api.openalex.org"),
    ("https://api.openalex.org:22/works",
     "ORIGIN_NOT_ALLOWLISTED", "api.openalex.org"),
    ("https://eutils.ncbi.nlm.nih.gov:8443/entrez/eutils/esearch.fcgi",
     "ORIGIN_NOT_ALLOWLISTED", "eutils.ncbi.nlm.nih.gov"),
    # an unparseable port is malformed, not silently defaulted
    ("https://api.openalex.org:notaport/works",
     "MALFORMED_URL", "api.openalex.org"),
    # host / scheme refusals (unchanged behavior, pinned here as neighbors)
    ("https://evil.example/works", "ORIGIN_NOT_ALLOWLISTED", "evil.example"),
    # https-only surface: the gate's allowlist holds https origins only, so a
    # non-https URL is refused as an unallowlisted origin (fail-closed before
    # any I/O — ``EgressPolicy``'s own scheme rule admits http for callers
    # that allowlist it, which this gate never does)
    ("http://api.openalex.org/works", "ORIGIN_NOT_ALLOWLISTED",
     "api.openalex.org"),
    # a host that merely *contains* an allowlisted name is not allowlisted
    ("https://api.openalex.org.evil.example/works",
     "ORIGIN_NOT_ALLOWLISTED", "api.openalex.org.evil.example"),
)

# Legitimate fetches: the full code-owned D5 provider surface, unchanged.
ALLOWED_URLS: tuple[tuple[str, str], ...] = (
    ("https://api.openalex.org/works", "api.openalex.org"),
    ("https://openalex.org/W2060313932", "openalex.org"),
    ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
     "eutils.ncbi.nlm.nih.gov"),
    ("https://pubmed.ncbi.nlm.nih.gov/12345678/",
     "pubmed.ncbi.nlm.nih.gov"),
)


class _RecordingInner:
    """Inner transport: records the URL it was asked to dial."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def request(self, spec: RequestSpec) -> TransportResponse:
        self.seen.append(spec.url)
        return TransportResponse(status=200, body=b"{}", headers={},
                                 content_type="application/json")


class _RecordingResolver:
    """Injected DNS: records every host it was asked to resolve."""

    def __init__(self, address: str = PUBLIC_IP) -> None:
        self.address = address
        self.calls: list[str] = []

    def __call__(self, host: str) -> tuple[str, ...]:
        self.calls.append(host)
        return (self.address,)


def _gate(inner=None, resolver=None,
          allowlist=ALLOWLIST_HOSTS) -> tuple[_AllowlistedTransport,
                                             _RecordingInner,
                                             _RecordingResolver]:
    inner = inner or _RecordingInner()
    resolver = resolver or _RecordingResolver()
    return (_AllowlistedTransport(inner, allowlist=allowlist, resolve=resolver),
            inner, resolver)


def _spec(url: str) -> RequestSpec:
    return RequestSpec(url=url, params={}, headers_meta={})


# ═══════════ 1. the audited bypass and its variants are refused ═══════════


@pytest.mark.parametrize(("url", "code", "host"), REFUSED_URLS)
def test_bypass_url_refused_before_any_io_or_resolution(url, code, host):
    gate, inner, resolver = _gate()
    with pytest.raises(ProviderValidationError) as excinfo:
        gate.request(_spec(url))
    message = str(excinfo.value)
    assert code in message, f"expected named code {code!r} in {message!r}"
    # the refusal names the host the URL actually points at
    assert host in message, f"expected host {host!r} in {message!r}"
    # fail-closed: nothing was dialed, nothing was resolved
    assert inner.seen == []
    assert resolver.calls == []


def test_audit_url_refusal_names_the_effective_host_not_the_userinfo():
    """The userinfo prefix is never mistaken for the host again."""
    gate, inner, resolver = _gate()
    with pytest.raises(ProviderValidationError) as excinfo:
        gate.request(_spec(AUDIT_URL))
    message = str(excinfo.value)
    assert "evil.example" in message
    # the pinned lookup key must not be the attacker-planted userinfo host
    assert http_module._lookup_pin("api.openalex.org") is None
    assert http_module._lookup_pin("evil.example") is None
    assert inner.seen == []
    assert resolver.calls == []


def test_audit_url_never_reaches_the_wiring_gate_allowlist():
    """``EgressPolicy.vet`` is the gate's single authority (not a re-check)."""
    from hermes.research.live_fetch import _AllowlistedTransport as gate_cls

    gate = gate_cls(_RecordingInner(), allowlist=ALLOWLIST_HOSTS,
                    resolve=_RecordingResolver())
    # the policy the gate consults is the canonicalizing rule layer: the
    # code-owned host surface is represented as https origins
    assert set(gate._policy.allowlist) == {
        f"https://{host}" for host in ALLOWLIST_HOSTS}


# ═══════════ 2. legitimate fetches stay green ═══════════


@pytest.mark.parametrize(("url", "host"), ALLOWED_URLS)
def test_allowlisted_fetch_still_passes(url, host):
    gate, inner, resolver = _gate()
    resp = gate.request(_spec(url))
    assert resp.status == 200
    assert inner.seen == [url]
    # DNS was asked about the allowlisted host only — never a userinfo string
    assert resolver.calls == [host]


def test_explicit_default_port_is_the_same_origin():
    """``:443`` canonicalizes onto the allowlisted https origin (EgressPolicy).

    The refusal is for a NON-default port (a different origin); the explicit
    default port is the same origin, so it stays a legitimate fetch.
    """
    gate, inner, _resolver = _gate()
    resp = gate.request(_spec("https://api.openalex.org:443/works"))
    assert resp.status == 200
    assert inner.seen == ["https://api.openalex.org:443/works"]


@pytest.mark.parametrize(("url", "dial_host"), [
    # urllib lowercases the host when it builds the request
    ("https://API.OPENALEX.ORG/works", "api.openalex.org"),
    # a trailing root dot is the same DNS name, and urllib keeps the dot
    ("https://api.openalex.org./works", "api.openalex.org."),
    # FIX-PIN-PORT — an explicit default port is the SAME origin, and urllib
    # KEEPS it in the authority it hands the opener, so the pin key must fold
    # it the same way (``EgressPolicy``'s canonical origin does). Otherwise
    # this accepted spelling looks up a key nobody published and dials the
    # NAME: a second resolution, i.e. the rebinding window the pin shuts.
    ("https://api.openalex.org:443/works", "api.openalex.org:443"),
    ("https://api.openalex.org:0443/works", "api.openalex.org:0443"),
])
def test_host_form_variants_are_accepted_and_pinned_for_the_dial_host(
        url, dial_host):
    """An accepted spelling must still dial the VETTED address.

    The pin table and ``EgressPolicy`` canonicalise the host the same way,
    so check-time identity survives case, root-dot and explicit-default-port
    spelling — otherwise the gate would vet ``api.openalex.org`` and then dial
    it unpinned. The lookup key is urllib's OWN derivation for the URL (what
    ``PinnedHTTPSHandler.https_open`` passes as ``req.host``), never a
    hand-written guess, so the test cannot pass by agreeing with itself.
    """
    pins: list[str | None] = []

    class Inner:
        def request(self, spec: RequestSpec) -> TransportResponse:
            pins.append(http_module._lookup_pin(
                urllib.request.Request(spec.url).host))
            return TransportResponse(status=200, body=b"{}", headers={},
                                     content_type="application/json")

    gate = _AllowlistedTransport(Inner(), allowlist=ALLOWLIST_HOSTS,
                                 resolve=_RecordingResolver())
    resp = gate.request(_spec(url))
    assert resp.status == 200
    assert pins == [PUBLIC_IP], "the vetted address must be the dialed address"
    # the pin is withdrawn after the request (single-request scope)
    assert http_module._lookup_pin(dial_host) is None


# ═══════════ 3. the DNS address rule is still enforced by the gate ═══════════


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.5", "192.168.1.10", "169.254.169.254", "::1",
])
def test_private_resolution_is_refused_with_the_address_code(address):
    gate = _AllowlistedTransport(
        _RecordingInner(), allowlist=ALLOWLIST_HOSTS,
        resolve=lambda host, address=address: (address,))
    with pytest.raises(ProviderValidationError) as excinfo:
        gate.request(_spec("https://api.openalex.org/works"))
    assert "ADDRESS_BLOCKED" in str(excinfo.value)


def test_mixed_public_private_answer_set_is_refused_as_a_whole():
    gate = _AllowlistedTransport(
        _RecordingInner(), allowlist=ALLOWLIST_HOSTS,
        resolve=lambda host: (PUBLIC_IP, "10.0.0.5"))
    with pytest.raises(ProviderValidationError) as excinfo:
        gate.request(_spec("https://api.openalex.org/works"))
    assert "ADDRESS_BLOCKED" in str(excinfo.value)


def test_resolution_failure_refuses_with_the_dns_code():
    def _boom(host: str) -> tuple[str, ...]:
        raise OSError("no such host")

    gate = _AllowlistedTransport(_RecordingInner(), allowlist=ALLOWLIST_HOSTS,
                                 resolve=_boom)
    with pytest.raises(ProviderValidationError) as excinfo:
        gate.request(_spec("https://api.openalex.org/works"))
    assert "DNS_FAILURE" in str(excinfo.value)


class _ResolverBoom(Exception):
    """A resolver-defined exception outside the built-in families."""


@pytest.mark.parametrize("raiser", [
    OSError,        # the production family (socket.gaierror, timeout …)
    ValueError,     # a bad name (UnicodeError, JSONDecodeError …)
    RuntimeError,   # a wrapper / NotImplementedError resolver
    KeyError,       # a table-backed resolver
    TypeError,      # a resolver returning a non-iterable
    _ResolverBoom,  # anything else a callable raises — still a refusal
], ids=lambda raiser: raiser.__name__)
def test_every_resolver_exception_class_refuses_with_the_dns_code(raiser):
    """AUDIT-USERINFO SF-2 — the injected resolver's full Exception family
    maps to the named refusal, never a bare exception.

    The resolver is an INJECTED seam (``build_live_fetch_wiring(dns_resolve=
    …)``, tests), and the base gate refused EVERY exception it raised with a
    typed ``ProviderValidationError``; the rule layer's catch had narrowed to
    ``OSError``, so ValueError / RuntimeError / KeyError escaped ``vet``
    untyped. Fail closed: one row per class, the class name kept in the
    refusal for diagnosability.
    """

    def _boom(host: str) -> tuple[str, ...]:
        raise raiser("resolver exploded")

    inner = _RecordingInner()
    gate = _AllowlistedTransport(inner, allowlist=ALLOWLIST_HOSTS,
                                 resolve=_boom)
    with pytest.raises(ProviderValidationError) as excinfo:
        gate.request(_spec("https://api.openalex.org/works"))
    message = str(excinfo.value)
    assert "DNS_FAILURE" in message
    assert raiser.__name__ in message
    assert inner.seen == []  # refused before any dial


# ═══════════ 4. the audited chain: a third-party source_url ═══════════


def test_third_party_source_url_from_a_search_result_is_refused():
    """``build_fetch_request`` copies a third-party ``source_url`` through.

    The adapter is a thin declarer (PS-01) and is not the place to filter —
    but the URL it declares must die at the gate, before any dial.
    """
    adapter = OpenalexAdapter()
    spec = adapter.build_fetch_request(SimpleNamespace(source_url=AUDIT_URL))
    assert spec.url == AUDIT_URL  # passthrough, by contract

    gate, inner, resolver = _gate()
    with pytest.raises(ProviderValidationError) as excinfo:
        gate.request(spec)
    assert "CREDENTIALS_IN_URL" in str(excinfo.value)
    assert inner.seen == []
    assert resolver.calls == []


def test_third_party_source_url_with_a_non_default_port_is_refused():
    adapter = OpenalexAdapter()
    spec = adapter.build_fetch_request(SimpleNamespace(
        source_url="https://api.openalex.org:8443/works/W1"))
    gate, inner, resolver = _gate()
    with pytest.raises(ProviderValidationError) as excinfo:
        gate.request(spec)
    assert "ORIGIN_NOT_ALLOWLISTED" in str(excinfo.value)
    assert inner.seen == []
    assert resolver.calls == []


# ═══════════ 6. the operator allowlist reader parses hosts too ═══════════


def test_config_entry_with_userinfo_is_refused_loudly():
    """``allowlist_from_config`` reads hosts by parsing, never by slicing.

    ``https://api.openalex.org:foo@evil.example`` must not be silently
    reinterpreted as its userinfo prefix (which happens to be a D5 host).
    """
    from hermes.config import SandboxPolicy
    from hermes.research.live_fetch import allowlist_from_config

    with pytest.raises(ProviderValidationError) as excinfo:
        allowlist_from_config(SandboxPolicy(network_egress_allowlist=[
            "https://api.openalex.org:foo@evil.example"]))
    assert "userinfo" in str(excinfo.value)
    with pytest.raises(ProviderValidationError):
        allowlist_from_config(SandboxPolicy(
            network_egress_allowlist=["api.openalex.org@evil.example"]))


# ═══════════ 5. the gate never string-slices netloc ═══════════


def test_gate_source_never_reads_netloc():
    """The parsing bug is structural: pin the source, not just the behavior.

    A future edit that reintroduces a hand-rolled ``netloc`` host extraction
    fails here even if it happens to pass the URL cases above. Checked on
    the AST, so the prose recording the bug does not count as the bug.
    """
    import ast
    from pathlib import Path

    import hermes.research.live_fetch as live_fetch

    tree = ast.parse(Path(live_fetch.__file__).read_text(encoding="utf-8"))
    attributes = {node.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Attribute)}
    assert "netloc" not in attributes, (
        "live_fetch must read hosts via parts.hostname, never netloc")
    assert "hostname" in attributes
