"""R-3 proxy-path E2E: a guarded fetch ignores HTTPS_PROXY (env proxies).

Parked item (``docs/archive/CERT_GATE_RERUN_CERTIFICATION_2026-10-04.md`` §6,
"proxy-path" row): "Opener pinned (``test_guarded_opener_ignores_https_proxy``);
live E2E bypass-proof absent". That existing test inspects the opener's
handler list — a construction claim. This module closes the E2E with socket
ACCOUNTING: the env proxy is pointed at a loopback listener that counts every
connection it receives, and the guarded fetch (``ProviderHTTPTransport`` →
the module opener) is proven to dial the ORIGIN instead. Every assertion is
about where a connection LANDED, never about which handlers exist.

Legs (each with the env proxy configured):

* ``test_env_proxy_is_honored_by_default_machinery…`` — TEETH: a fresh,
  unguarded opener routes the https request into the proxy listener, so a
  silent proxy in the guarded legs cannot be an artefact of a dead listener.
* ``test_guarded_http_fetch…`` — a real loopback origin returns 200 through
  the guarded transport; the proxy stays silent.
* ``test_guarded_https_fetch…`` — the guarded https fetch's TCP connection
  lands on the origin listener; the proxy stays silent; an unresolvable
  ORIGIN reports a DNS failure of that origin (a live proxy authority would
  have dialed the proxy instead, as the teeth leg shows).

Note on DNS mediation: the origin is reached by patching ``getaddrinfo`` for
the test host only — DNS is not the property under test, the routing decision
is. (The FIX-D pin is deliberately NOT used: on this Python the opener's
dispatcher chain still consults the default ``HTTPSHandler`` first, so the
pinned dial is not the code path a plain request takes; that observation is
reported separately and is not part of R-3's diff.)
"""
from __future__ import annotations

import contextlib
import http.server
import socket
import threading
import time
import urllib.request
from typing import Any

import pytest

from hermes.tools.providers.base import RequestSpec
from hermes.tools.providers.http import ProviderHTTPTransport
from hermes.tools.research_sources import ProviderError

PROXY_HOST = "proxy-e2e.invalid"
UNRESOLVABLE_HOST = "proxy-e2e.unresolvable.invalid"


class _ConnCounter:
    """A loopback TCP listener that counts every accepted connection."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self.port = int(self._sock.getsockname()[1])
        self.hits = 0
        self._closed = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._closed:
            try:
                conn, _addr = self._sock.accept()
            except OSError:
                return
            self.hits += 1
            with contextlib.suppress(OSError):
                conn.close()

    def wait_for(self, count: int, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.hits >= count:
                return True
            time.sleep(0.01)
        return self.hits >= count

    def close(self) -> None:
        self._closed = True
        with contextlib.suppress(OSError):
            self._sock.close()
        self._thread.join(timeout=2.0)


class _OriginHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        body = b"guarded-ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        # stdlib signature (http.server.BaseHTTPRequestHandler) -- the
        # name `format` is required for the override to stay compatible.
        return None


def _proxy_env(monkeypatch, proxy: _ConnCounter) -> None:
    url = f"http://127.0.0.1:{proxy.port}"
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.setenv(name, url)


def _settle(seconds: float = 0.25) -> None:
    """Give any proxied dial time to land before asserting silence."""
    time.sleep(seconds)


def test_env_proxy_is_honored_by_default_machinery(monkeypatch):
    """TEETH: the very same env proxy IS a live route for the unguarded
    default machinery — so the guarded legs' silence is a fact, not a
    dead-listener artefact."""
    proxy = _ConnCounter()
    _proxy_env(monkeypatch, proxy)
    try:
        opener = urllib.request.build_opener()
        # The CONNECT is the measured fact; the tunnelled handshake
        # may legitimately fail against this listener.
        with contextlib.suppress(Exception):
            opener.open("https://proxy-e2e.invalid/", timeout=2.0)
        assert proxy.wait_for(1), (
            "the env proxy was never contacted — the listener is dead, so a "
            "silent guarded leg would prove nothing")
    finally:
        proxy.close()


def test_guarded_http_fetch_reaches_the_origin_with_a_proxy_configured(
        monkeypatch):
    """A REAL guarded fetch (200 + body) with HTTP_PROXY set: the connection
    lands on the origin server and never on the proxy."""
    proxy = _ConnCounter()
    _proxy_env(monkeypatch, proxy)
    origin = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OriginHandler)
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    try:
        port = int(origin.server_address[1])
        resp = ProviderHTTPTransport(timeout=2.0).request(
            RequestSpec(url=f"http://127.0.0.1:{port}/ok", params={},
                        headers_meta={}))
        assert resp.status == 200
        assert resp.body == b"guarded-ok"
        _settle()
        assert proxy.hits == 0, (
            "the guarded fetch routed through the env proxy")
    finally:
        origin.shutdown()
        origin.server_close()
        proxy.close()


def test_guarded_https_fetch_dials_the_origin_never_the_proxy(monkeypatch):
    """The guarded https fetch's TCP connection lands on the ORIGIN, with a
    working env proxy configured and the origin host resolvable to loopback.
    An unresolvable ORIGIN then reports a DNS failure OF THE ORIGIN — a live
    proxy authority would never have needed to resolve it (see the teeth
    leg, where the proxy is dialed instead)."""
    proxy = _ConnCounter()
    origin = _ConnCounter()  # raw TCP: the dial fact, no TLS server needed
    _proxy_env(monkeypatch, proxy)
    real_getaddrinfo = socket.getaddrinfo

    def mediated(host, port, *args, **kwargs):
        if host == UNRESOLVABLE_HOST:
            raise socket.gaierror(11001, "getaddrinfo failed")
        target = "127.0.0.1" if host == PROXY_HOST else host
        return real_getaddrinfo(target, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", mediated)
    try:
        with pytest.raises(ProviderError):
            # The origin is raw TCP: the dial lands, the TLS handshake
            # cannot — a typed provider error, never a silent success.
            ProviderHTTPTransport(timeout=2.0).request(RequestSpec(
                url=f"https://{PROXY_HOST}:{origin.port}/", params={},
                headers_meta={}))
        assert origin.wait_for(1), (
            "the guarded fetch never dialed the origin — it did not reach "
            "the origin host")
        _settle()
        assert proxy.hits == 0, (
            "the guarded fetch opened a connection to the env proxy")

        proxy_before = proxy.hits
        with pytest.raises(ProviderError):
            ProviderHTTPTransport(timeout=2.0).request(RequestSpec(
                url=f"https://{UNRESOLVABLE_HOST}/", params={},
                headers_meta={}))
        _settle()
        assert proxy.hits == proxy_before, (
            "an unresolvable origin was routed through the env proxy instead "
            "of failing at the origin's own resolution")
    finally:
        proxy.close()
        origin.close()
