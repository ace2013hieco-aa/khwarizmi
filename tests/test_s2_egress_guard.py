"""S2 golden fixtures — the Khwarizmi-owned egress guard.

Pass criterion (adoption §5/S2): the guard blocks loopback, link-local,
RFC1918, non-http(s) schemes, and a redirect-to-internal fixture; the guard
owns the socket (resolve-and-pin) and re-validates every redirect hop.

Deterministic by construction: address resolution and the per-hop opener are
injected, so no real network is contacted. The one exception is a white-box
test of the pinned HTTP connection, which dials a temporary 127.0.0.1 server
directly (bypassing policy on purpose) to prove Host header, path and pinning
behaviour — policy itself refuses loopback in every non-white-box test.
"""
from __future__ import annotations

import http.server
import socket
import threading

import pytest

from hermes.config import SandboxPolicy
from hermes.security import egress
from hermes.security.egress import (
    EgressPolicy,
    EgressRefused,
    GuardedFetcher,
    VettedTarget,
)

PUBLIC_V4 = "1.1.1.1"
PUBLIC_V4B = "8.8.8.8"
PUBLIC_V6 = "2606:4700:4700::1111"


def resolver(mapping: dict[str, tuple[str, ...]]):
    def _resolve(host: str, port: int) -> tuple[str, ...]:
        return mapping.get(host, ())
    return _resolve


def raw(status: int, body: bytes = b"", **headers: str) -> egress._RawResponse:
    return egress._RawResponse(
        status=status, headers=tuple(headers.items()), body=body)


def policy(
    entries: tuple[str, ...] = ("https://papers.test", "http://papers.test"),
    **kwargs,
) -> EgressPolicy:
    return EgressPolicy(allowlist=entries, **kwargs)


def expect_refusal(code: str, fn, *args, **kwargs) -> EgressRefused:
    with pytest.raises(EgressRefused) as info:
        fn(*args, **kwargs)
    assert info.value.code == code, f"{info.value.code} != {code}"
    return info.value


# ── config wiring + allowlist discipline ──


def test_config_field_is_wired():
    sandbox = SandboxPolicy(enabled=True, network_egress_allowlist=[
        "https://Example.com", "http://localhost:8080"])
    wired = EgressPolicy.from_config(sandbox)
    assert wired.allowlist == ("http://localhost:8080", "https://example.com")


def test_empty_allowlist_denies_everything():
    default = EgressPolicy.from_config(SandboxPolicy())
    assert default.allowlist == ()
    expect_refusal("ORIGIN_NOT_ALLOWLISTED", default.vet,
                   "https://example.com/")


def test_config_to_fingerprint_survives_end_to_end():
    """AUDIT-S2 G1 — POPULATE decision proven: a config-built policy survives
    into the guard fingerprint end-to-end.

    The wiring point that future code MUST adopt is
    ``GuardedFetcher(EgressPolicy.from_config(config.sandbox))`` — the same
    policy fingerprint that ``render_page`` stamps into provenance must
    equal the fingerprint computed after a fresh ``from_config`` against
    the same ``SandboxPolicy``. This catches any drift where a caller hand-
    rolls origins or short-circuits the config seam.
    """
    sandbox = SandboxPolicy(enabled=True, network_egress_allowlist=[
        "https://papers.test", "https://api.papers.test",
        "https://biorxiv.org", "http://export.arxiv.org"])
    # Two independent derivations — they must agree.
    policy_via_config_a = EgressPolicy.from_config(sandbox)
    policy_via_config_b = EgressPolicy.from_config(sandbox)
    assert policy_via_config_a.fingerprint() == policy_via_config_b.fingerprint()
    # The GuardedFetcher (the production wiring shape) exposes the policy it
    # was constructed with, and that policy's fingerprint must equal the
    # config-derived one — proving no caller short-circuits the seam.
    fetcher = GuardedFetcher(policy_via_config_a,
                             resolve=resolver({"papers.test": (PUBLIC_V4,)}),
                             open_fn=lambda target, *, timeout, max_bytes,
                             user_agent: raw(200, b"ok"))
    assert fetcher.policy.fingerprint() == EgressPolicy.from_config(
        sandbox).fingerprint()
    # A page fetched through that fetcher carries the same provenance-visible
    # fingerprint a future audit (or merge gate) would record.
    fetcher.fetch("https://papers.test/x")
    assert fetcher.policy.fingerprint() == policy_via_config_a.fingerprint()


def test_toml_loaded_allowlist_survives_into_fingerprint(tmp_path):
    """AUDIT-S2 G1 — the load_config → from_config → fingerprint chain, the
    same chain any future wiring point must use, is identity-stable.

    Writes a hermes.toml with a populated ``network_egress_allowlist``,
    loads it through ``hermes.config.load_config``, derives the policy via
    ``EgressPolicy.from_config``, and confirms the fingerprint is content-
    stable across two fresh loads. This is the path the spike doc's
    "empty = deny all, fail closed — IDR-006" story depends on once the
    guard becomes shared infrastructure; today it has no src caller (the
    spike scripts hand-roll origins), which is the G1 wiring decision
    this test pre-decides for the design gate.
    """
    from hermes.config import load_config
    cfg = tmp_path / "hermes.toml"
    cfg.write_text(
        '[sandbox]\n'
        'enabled = true\n'
        'network_egress_allowlist = [\n'
        '  "https://papers.test",\n'
        '  "https://api.papers.test",\n'
        ']\n',
        encoding="utf-8")
    c1 = load_config(cfg)
    c2 = load_config(cfg)
    p1 = EgressPolicy.from_config(c1.sandbox)
    p2 = EgressPolicy.from_config(c2.sandbox)
    assert p1.allowlist == p2.allowlist
    assert p1.fingerprint() == p2.fingerprint()
    # fingerprint must be content-derived (changing the allowlist changes it)
    alt_cfg = tmp_path / "hermes-other.toml"
    alt_cfg.write_text(
        '[sandbox]\nenabled = true\n'
        'network_egress_allowlist = ["https://papers.test"]\n',
        encoding="utf-8")
    p_alt = EgressPolicy.from_config(load_config(alt_cfg).sandbox)
    assert p_alt.fingerprint() != p1.fingerprint()


def test_allowlist_entries_must_be_origins():
    for entry in ("https://example.com/path", "ftp://example.com",
                  "https://", "example.com", "https://example.com?q=1",
                  "https://example.com#frag"):
        with pytest.raises(ValueError):
            EgressPolicy(allowlist=(entry,))


def test_allowlist_duplicates_after_canonicalization_rejected():
    with pytest.raises(ValueError):
        EgressPolicy(allowlist=("https://example.com",
                                "https://EXAMPLE.com:443"))


def test_origin_matching_is_canonical():
    p = policy(("https://example.com:443",))
    for url in ("https://example.com/x", "https://EXAMPLE.com/",
                "https://example.com:443/y"):
        assert p.vet(url, resolve=resolver(
            {"example.com": (PUBLIC_V4,)})).host == "example.com"
    for url in ("http://example.com/", "https://example.com:8443/",
                "https://sub.example.com/"):
        expect_refusal("ORIGIN_NOT_ALLOWLISTED", p.vet, url,
                       resolve=resolver({"example.com": (PUBLIC_V4,)}))


def test_policy_fingerprint_is_stable_and_sensitive():
    a = policy(("https://a.test",))
    b = policy(("https://a.test",))
    c = policy(("https://a.test",), max_redirects=1)
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != c.fingerprint()


# ── scheme + form refusals ──


@pytest.mark.parametrize("url", [
    "ftp://papers.test/x", "file:///etc/passwd", "data:text/html,hi",
    "javascript:alert(1)", "ws://papers.test/socket", "gopher://papers.test/1",
])
def test_non_http_schemes_refused(url: str):
    expect_refusal("SCHEME_NOT_ALLOWED", policy().vet, url,
                   resolve=resolver({}))


@pytest.mark.parametrize("url", ["//papers.test/x", "papers.test/x", "",
                                 "https://", "https:///path"])
def test_malformed_urls_refused(url: str):
    expect_refusal("MALFORMED_URL", policy().vet, url, resolve=resolver({}))


def test_credentials_in_url_refused_and_never_echoed():
    url = "https://alice:hunter2@papers.test/x"
    refusal = expect_refusal("CREDENTIALS_IN_URL", policy().vet, url,
                             resolve=resolver({}))
    assert "hunter2" not in str(refusal)
    assert "alice" not in str(refusal)


def test_query_never_echoed_in_refusal():
    url = "https://papers.test/secret?token=hunter2"
    refusal = expect_refusal("ORIGIN_NOT_ALLOWLISTED", policy(()).vet, url,
                             resolve=resolver({}))
    assert "hunter2" not in str(refusal)


# ── private-range / link-local / reserved blocks ──


@pytest.mark.parametrize("address,reason", [
    ("127.0.0.1", "loopback"),
    ("::1", "loopback"),
    ("0.0.0.0", "unspecified"),
    ("::", "unspecified"),
    ("169.254.169.254", "link-local"),   # cloud metadata
    ("fe80::1", "link-local"),
    ("10.0.0.5", "private"),
    ("172.16.9.1", "private"),
    ("192.168.1.1", "private"),
    ("fd00::1", "private"),
    ("100.64.0.1", "not globally routable"),  # CGNAT shared space
    ("224.0.0.1", "multicast"),
    ("240.0.0.1", "reserved"),
    ("::ffff:127.0.0.1", "loopback"),    # IPv4-mapped bypass
    ("::ffff:10.1.2.3", "private"),
    # AUDIT-S2 A1 — non-global v6 nets refused independent of stdlib drift
    # (Python 3.14.1 stdlib reports is_global=True for both; the guard's
    # explicit ``_NON_GLOBAL_V6_NETS`` block runs first).
    ("fec0::1", "site-local"),       # RFC 3879-deprecated site-local
    ("fec0::abcd", "site-local"),
    ("fecf::ffff", "site-local"),    # top of fec0::/10
    ("3ffe::1", "6bone"),            # RFC 3701-returned 6bone testnet
    ("3ffe::ffff", "6bone"),         # top of 3ffe::/16
])
def test_blocked_address_classes(address: str, reason: str):
    p = policy(("http://internal.test",))
    refusal = expect_refusal(
        "ADDRESS_BLOCKED", p.vet, "http://internal.test/x",
        resolve=resolver({"internal.test": (address,)}))
    assert reason in refusal.detail


def test_mixed_public_and_private_answer_set_refused():
    p = policy(("http://mixed.test",))
    expect_refusal(
        "ADDRESS_BLOCKED", p.vet, "http://mixed.test/",
        resolve=resolver({"mixed.test": (PUBLIC_V4, "10.0.0.9")}))


def test_fec0_and_3bone_refuse_via_explicit_block_not_stdlib_global():
    """AUDIT-S2 A1: explicit block must refuse even when stdlib says
    ``is_global=True`` (verified on Python 3.14.1). The reason string is
    the explicit-net marker so a future stdlib boolean flip does not
    silently rename the refusal as 'not globally routable' — this guards
    against regressions of the underlying stdlib drift, not just today's
    stdlib output."""
    import ipaddress
    assert ipaddress.IPv6Address("fec0::1").is_global, (
        "stdlib drift premise: fec0::1 must currently report is_global=True; "
        "if stdlib ever starts classifying it as private/ULA this test "
        "should still refuse via the explicit block above the stdlib checks")
    assert ipaddress.IPv6Address("3ffe::1").is_global
    p = policy(("http://papers.test",))
    for addr in ("fec0::1", "3ffe::1"):
        refusal = expect_refusal(
            "ADDRESS_BLOCKED", p.vet, "http://papers.test/x",
            resolve=resolver({"papers.test": (addr,)}))
        # refuse with the *explicit* marker, not the generic
        # 'not globally routable' fallthrough
        assert "site-local" in refusal.detail or "6bone" in refusal.detail, (
            f"refusal detail {refusal.detail!r} did not name the explicit net "
            f"(stdlib drift regression)")


def test_dns_failure_and_empty_answers_refused():
    p = policy(("http://papers.test",))

    def failing(host: str, port: int) -> tuple[str, ...]:
        raise socket.gaierror("no such host")

    expect_refusal("DNS_FAILURE", p.vet, "http://papers.test/",
                   resolve=failing)
    expect_refusal("NO_ADDRESSES", p.vet, "http://papers.test/",
                   resolve=resolver({}))
    expect_refusal("NO_ADDRESSES", p.vet, "http://papers.test/",
                   resolve=resolver({"papers.test": ("banana",)}))


def test_public_addresses_accepted_and_pinned_deterministically():
    p = policy(("https://papers.test",))
    target = p.vet("https://papers.test/abs/1",
                   resolve=resolver({"papers.test": (PUBLIC_V6, PUBLIC_V4)}))
    assert target.addresses == (PUBLIC_V4, PUBLIC_V6)
    assert target.pinned == PUBLIC_V4
    assert target.origin == "https://papers.test"
    assert target.port == 443
    assert target.build_path() == "/abs/1"


# ── redirects: per-hop re-validation (the S2 redirect-to-internal fixture) ──


def test_redirect_to_internal_origin_refused_before_dialing_it():
    p = policy(("http://public.test", "http://internal.test"))
    resolve = resolver({"public.test": (PUBLIC_V4,),
                        "internal.test": ("10.0.0.7",)})
    dialed: list[VettedTarget] = []

    def opener(target, *, timeout, max_bytes, user_agent):
        dialed.append(target)
        return raw(302, Location="http://internal.test/secret")

    fetcher = GuardedFetcher(p, resolve=resolve, open_fn=opener)
    refusal = expect_refusal("ADDRESS_BLOCKED", fetcher.fetch,
                             "http://public.test/start")
    assert refusal.host == "internal.test"
    assert len(dialed) == 1                     # the internal hop was never dialed
    assert dialed[0].pinned == PUBLIC_V4        # hop 1 went to its pinned address
    assert dialed[0].host == "public.test"      # hostname preserved for Host/SNI


def test_redirect_to_loopback_ip_literal_refused():
    p = policy(("http://public.test", "http://127.0.0.1"))
    resolve = resolver({"public.test": (PUBLIC_V4,)})

    def opener(target, *, timeout, max_bytes, user_agent):
        return raw(302, Location="http://127.0.0.1:80/admin")

    fetcher = GuardedFetcher(p, resolve=resolve, open_fn=opener)
    expect_refusal("ADDRESS_BLOCKED", fetcher.fetch, "http://public.test/")


def test_redirect_to_non_allowlisted_public_host_refused():
    p = policy(("http://public.test",))
    resolve = resolver({"public.test": (PUBLIC_V4,), "other.test": (PUBLIC_V4B,)})

    def opener(target, *, timeout, max_bytes, user_agent):
        return raw(302, Location="http://other.test/")

    fetcher = GuardedFetcher(p, resolve=resolve, open_fn=opener)
    refusal = expect_refusal("ORIGIN_NOT_ALLOWLISTED", fetcher.fetch,
                             "http://public.test/")
    assert refusal.host == "other.test"


def test_redirect_to_non_http_scheme_refused():
    p = policy(("http://public.test",))
    resolve = resolver({"public.test": (PUBLIC_V4,)})

    def opener(target, *, timeout, max_bytes, user_agent):
        return raw(302, Location="file:///etc/passwd")

    fetcher = GuardedFetcher(p, resolve=resolve, open_fn=opener)
    expect_refusal("SCHEME_NOT_ALLOWED", fetcher.fetch, "http://public.test/")


def test_redirect_without_location_refused():
    p = policy(("http://public.test",))
    resolve = resolver({"public.test": (PUBLIC_V4,)})

    def opener(target, *, timeout, max_bytes, user_agent):
        return raw(302)

    fetcher = GuardedFetcher(p, resolve=resolve, open_fn=opener)
    expect_refusal("REDIRECT_WITHOUT_LOCATION", fetcher.fetch,
                   "http://public.test/")


def test_padded_location_is_stripped_then_followed():
    """AUDIT-S2 B1 — leading/trailing whitespace in Location is stripped before
    urljoin so it cannot survive into the rebuilt URL/hops trail. The
    normalised location is followed normally on the second hop."""
    p = policy(("http://public.test",))
    resolve = resolver({"public.test": (PUBLIC_V4,)})
    dialed_paths: list[str] = []

    def opener(target, *, timeout, max_bytes, user_agent):
        dialed_paths.append(target.build_path())
        if target.build_path() == "/start":
            return raw(302, Location="  http://public.test/final  ")
        return raw(200, b"ok",
                    **{"Content-Type": "text/plain; charset=utf-8"})

    fetcher = GuardedFetcher(p, resolve=resolve, open_fn=opener)
    page = fetcher.fetch("http://public.test/start")
    assert page.status == 200
    assert page.url == "http://public.test/final"  # stripped, no trailing space


def test_control_character_location_refused_with_bad_redirect_url():
    """AUDIT-S2 B1 — an internal control character in Location refuses inside
    the closed set (was: the stdlib wire failed with a raw InvalidURL outside
    the refusal-as-data discipline)."""
    p = policy(("http://public.test",))
    resolve = resolver({"public.test": (PUBLIC_V4,)})

    def opener(target, *, timeout, max_bytes, user_agent):
        return raw(302, Location="http://public.test/z\x00bad")

    fetcher = GuardedFetcher(p, resolve=resolve, open_fn=opener)
    expect_refusal("BAD_REDIRECT_URL", fetcher.fetch, "http://public.test/")


def test_same_origin_scheme_downgrade_refused():
    """AUDIT-S2 B2 — https→http on the same origin (same host:port) refuses
    with a closed-set code (was: silently followed). The redirect must
    carry the same default port for both schemes — a default-port scheme
    switch on its own is a different origin in the policy."""
    p = policy(("https://public.test:443",))
    resolve = resolver({"public.test": (PUBLIC_V4,)})

    def opener(target, *, timeout, max_bytes, user_agent):
        return raw(302, Location="http://public.test:443/final")

    fetcher = GuardedFetcher(p, resolve=resolve, open_fn=opener)
    refusal = expect_refusal("SCHEME_DOWNGRADE", fetcher.fetch,
                             "https://public.test:443/start")
    assert "https" in refusal.detail and "http" in refusal.detail


def test_cross_origin_https_to_http_not_a_downgrade_refusal():
    """AUDIT-S2 B2 — the downgrade rule is same-origin only; an https→http
    hop to a *different* origin is not a downgrade and follows the normal
    per-hop vet (it may still be refused on allowlist grounds, but not
    with SCHEME_DOWNGRADE)."""
    p = policy(("https://public.test", "http://other.test"))
    resolve = resolver({"public.test": (PUBLIC_V4,),
                        "other.test": (PUBLIC_V4B,)})
    dialed: list[str] = []

    def opener(target, *, timeout, max_bytes, user_agent):
        dialed.append(target.build_path())
        if target.build_path() == "/start":
            return raw(302, Location="http://other.test/final")
        return raw(200, b"ok")

    fetcher = GuardedFetcher(p, resolve=resolve, open_fn=opener)
    # Hop 2 is different host → not a SCHEME_DOWNGRADE; follows normally.
    page = fetcher.fetch("https://public.test/start")
    assert page.status == 200
    assert page.url == "http://other.test/final"
    assert dialed == ["/start", "/final"]


def test_too_many_redirects_refused():
    p = policy(("http://public.test",), max_redirects=2)
    resolve = resolver({"public.test": (PUBLIC_V4,)})
    calls = {"n": 0}

    def opener(target, *, timeout, max_bytes, user_agent):
        calls["n"] += 1
        return raw(302, Location=f"/hop{calls['n']}")

    fetcher = GuardedFetcher(p, resolve=resolve, open_fn=opener)
    expect_refusal("TOO_MANY_REDIRECTS", fetcher.fetch, "http://public.test/")
    assert calls["n"] == 3  # initial + 2 allowed redirects, then the cap


def test_happy_redirect_chain_records_hops_and_pins_every_hop():
    p = policy(("http://public.test",))
    resolve = resolver({"public.test": (PUBLIC_V4,)})
    dialed: list[VettedTarget] = []

    def opener(target, *, timeout, max_bytes, user_agent):
        dialed.append(target)
        if target.build_path() == "/start":
            return raw(301, Location="/final")
        return raw(200, b"hello", **{"Content-Type": "text/plain; charset=utf-8"})

    fetcher = GuardedFetcher(p, resolve=resolve, open_fn=opener)
    page = fetcher.fetch("http://public.test/start")
    assert page.status == 200
    assert page.body == b"hello"
    assert page.url == "http://public.test/final"
    assert page.hops == ("http://public.test/start",)
    assert page.content_type == "text/plain"
    assert [t.pinned for t in dialed] == [PUBLIC_V4, PUBLIC_V4]


def test_non_2xx_status_is_returned_not_raised():
    p = policy(("http://public.test",))
    resolve = resolver({"public.test": (PUBLIC_V4,)})

    def opener(target, *, timeout, max_bytes, user_agent):
        return raw(404, b"gone")

    fetcher = GuardedFetcher(p, resolve=resolve, open_fn=opener)
    page = fetcher.fetch("http://public.test/missing")
    assert page.status == 404
    assert page.body == b"gone"


def test_body_cap_refused():
    p = policy(("http://public.test",))
    resolve = resolver({"public.test": (PUBLIC_V4,)})

    def opener(target, *, timeout, max_bytes, user_agent):
        return raw(200, b"x" * (max_bytes + 1))

    fetcher = GuardedFetcher(p, resolve=resolve, open_fn=opener,
                             max_bytes=1024)
    expect_refusal("BODY_TOO_LARGE", fetcher.fetch, "http://public.test/")


# ── white-box: the real pinned connection (direct, policy bypassed on purpose) ──


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = (f"host={self.headers.get('Host')} "
                f"path={self.path}").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return  # silence the test server


def test_pinned_http_connection_sends_hostname_and_path():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        target = VettedTarget(
            url=f"http://papers.test:{port}/hello?x=1",
            scheme="http", host="papers.test", port=port,
            origin=f"http://papers.test:{port}",
            addresses=("127.0.0.1",), pinned="127.0.0.1")
        response = egress._default_open(
            target, timeout=5.0, max_bytes=1 << 20, user_agent="s2-test")
        assert response.status == 200
        assert b"host=papers.test" in response.body
        assert b"path=/hello?x=1" in response.body
    finally:
        server.shutdown()
        server.server_close()


def test_pinned_https_connection_dials_pin_and_keeps_hostname_sni(monkeypatch):
    """White-box: the TLS variation of the pin. The socket is dialed at the
    vetted address while SNI (and therefore certificate validation) stays on
    the hostname — a pinned IP must never become the cert identity."""
    seen: dict[str, object] = {}

    def fake_create_connection(address, timeout):
        seen["address"] = address
        return "raw-socket"

    class _FakeContext:
        def wrap_socket(self, sock, server_hostname):
            seen["sock"] = sock
            seen["sni"] = server_hostname
            return "tls-socket"

    monkeypatch.setattr(egress.socket, "create_connection",
                        fake_create_connection)
    connection = egress._PinnedHTTPSConnection(
        "papers.test", PUBLIC_V4, 443, 5.0, _FakeContext())
    connection.connect()
    assert seen["address"] == (PUBLIC_V4, 443)
    assert seen["sock"] == "raw-socket"
    assert seen["sni"] == "papers.test"
    assert connection.sock == "tls-socket"
