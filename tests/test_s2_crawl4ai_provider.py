"""S2 golden fixtures — the crawl4ai provider behind the egress guard (spike).

Pass criterion (adoption §5/S2): the guard blocks loopback, link-local,
RFC1918, non-http(s) schemes and a redirect-to-internal fixture, and the
pinned crawl4ai provider *ships only behind that guard*: every output is an
``UntrustedContent`` envelope and the fetch leg never leaves the guard.

Evidence layout, mirroring S1:

- ``tests/fixtures/s2_crawl4ai/`` holds ten HTML pages (eight vendored copies
  of this repository's ``docs/diagrams/*.html`` plus two synthetic pages) and
  one recorded provider record per page. Each record was written by **two
  fresh processes** (``scripts/s2_crawl4ai_record.py``); the two records are
  compared byte-for-byte and the fixture carries that identity claim.
- The live leg replays each fixture through the real guard (injected opener,
  no socket) and the pinned crawl4ai transform, then demands **exact record
  equality**. It skips with a reason when the exact pin is not installed —
  a different version never substitutes.

What is stubbed where: refusal and provenance-bound tests monkeypatch the
generator class so they run without crawl4ai installed; they exercise the
provider's own logic (guard-first ordering, refusal codes, envelope, 4 KiB
bound) and are labelled as such. crawl4ai's own transform behaviour is only
ever proven by the fixture battery above.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hermes.security.boundaries import UntrustedContent
from hermes.security.egress import (
    EgressPolicy,
    EgressRefused,
    GuardedFetcher,
    _RawResponse,
)
from hermes.tools.providers import crawl4ai_provider
from hermes.tools.providers.crawl4ai_provider import (
    CRAWL4AI_PIN,
    MAX_PROVENANCE_BYTES,
    RECORD_VERSION,
    Crawl4aiConfig,
    Crawl4aiPage,
    Crawl4aiProviderError,
    Crawl4aiUnavailableError,
    render_markdown,
    render_page,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "s2_crawl4ai"
PAGES_DIR = FIXTURE_DIR / "pages"
FIXTURE_FILES = sorted(
    path for path in FIXTURE_DIR.glob("*.json")
    if path.name != "MANIFEST.json")
FIXTURE_IDS = [path.stem for path in FIXTURE_FILES]

FIXTURE_HOST = "fixtures.test"
PINNED_ADDRESS = "1.1.1.1"
PUBLIC_V4 = "1.1.1.1"
PUBLIC_V4B = "8.8.8.8"

HTML_HEADERS = (("Content-Type", "text/html; charset=utf-8"),
                ("X-Spike-Fetcher", "vendored-fixture-opener"))


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pinned_crawl4ai_available() -> bool:
    try:
        return importlib.metadata.version("crawl4ai") == CRAWL4AI_PIN
    except importlib.metadata.PackageNotFoundError:
        return False


LIVE = pytest.mark.skipif(
    not _pinned_crawl4ai_available(),
    reason=f"pinned crawl4ai {CRAWL4AI_PIN} not installed "
           f"(live leg runs in the S2 spike venv)")


def _resolver(mapping: dict[str, tuple[str, ...]]):
    def _resolve(host: str, port: int) -> tuple[str, ...]:
        return mapping.get(host, ())
    return _resolve


def _raw(status: int, body: bytes = b"", **headers: str) -> _RawResponse:
    return _RawResponse(status=status, headers=tuple(headers.items()),
                        body=body)


def _fixture_fetcher(body: bytes) -> GuardedFetcher:
    """The exact guard configuration used when recording the fixtures."""
    def _open(target, *, timeout: float, max_bytes: int,
              user_agent: str) -> _RawResponse:
        return _RawResponse(status=200, headers=HTML_HEADERS, body=body)

    return GuardedFetcher(
        EgressPolicy(allowlist=(f"https://{FIXTURE_HOST}",)),
        resolve=_resolver({FIXTURE_HOST: (PINNED_ADDRESS,)}),
        open_fn=_open,
    )


def _no_transform(monkeypatch) -> None:
    """Fail the test if the transform runs at all (guard-first proof)."""
    def _explode(*args, **kwargs):
        raise AssertionError("transform ran before the guard refused")
    monkeypatch.setattr(crawl4ai_provider, "render_markdown", _explode)


class _StubGenerator:
    """Minimal stand-in for the pinned generator class (logic tests only)."""

    def __init__(self, options: Any = None) -> None:
        self.options = options

    def generate_markdown(self, *, input_html: str, base_url: str,
                          citations: bool) -> Any:
        raw = f"# stub\n{input_html}\n"
        return SimpleNamespace(raw_markdown=raw,
                               markdown_with_citations=f"{raw}(cited)",
                               references_markdown="\n## References\n")


def _stub_transform(monkeypatch) -> None:
    """Replace the generator resolution and the version read (hermetic)."""
    monkeypatch.setattr(crawl4ai_provider, "_load_generator_class",
                        lambda: _StubGenerator)
    real_version = importlib.metadata.version
    monkeypatch.setattr(
        importlib.metadata, "version",
        lambda name: CRAWL4AI_PIN if name == "crawl4ai" else real_version(name))


# ── boundary discipline ──


def test_pin_is_an_exact_version():
    assert CRAWL4AI_PIN == "0.9.4"
    assert re.fullmatch(r"\d+\.\d+\.\d+", CRAWL4AI_PIN)


def test_provider_module_is_the_only_crawl4ai_importer():
    """Adoption §4 rule 1: the library lives in one module, imported nowhere
    else in ``src/`` — and that module never imports it statically (the
    resolution is lazy and version-checked)."""
    src = Path(__file__).resolve().parents[1] / "src"
    provider_rel = Path("hermes/tools/providers/crawl4ai_provider.py")
    offenders: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src)
        text = path.read_text(encoding="utf-8")
        if rel != provider_rel:
            if re.search(r"^\s*(?:from|import)\s+crawl4ai\b", text, re.M):
                offenders.append(str(rel))
            if "crawl4ai_provider" in text:
                offenders.append(f"{rel} (imports the provider module)")
    assert offenders == []
    provider_text = (src / provider_rel).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(?:from|import)\s+crawl4ai\b", provider_text,
                         re.M)


def test_provider_is_not_in_the_adapter_registry():
    """A spike module, not a ratified provider: absent from the allowlist
    registry, so no core path can reach it yet."""
    from hermes.tools.providers.adapters import PROVIDER_REGISTRY
    assert all("crawl4ai" not in provider_id
               for provider_id in PROVIDER_REGISTRY)
    assert all("crawl4ai" not in getattr(adapter, "__module__", "")
               for adapter in PROVIDER_REGISTRY.values())


def test_provider_module_has_no_core_or_persistence_surface():
    provider = (Path(__file__).resolve().parents[1] / "src" / "hermes" /
                "tools" / "providers" / "crawl4ai_provider.py")
    text = provider.read_text(encoding="utf-8")
    for forbidden in ("hermes.research", "hermes.persistence", "sqlite3",
                      "apply_intent", "http.client", "import socket"):
        assert forbidden not in text


def test_absent_crawl4ai_fails_closed(monkeypatch):
    real_version = importlib.metadata.version
    monkeypatch.setattr(
        importlib.metadata, "version",
        lambda name: (_ for _ in ()).throw(
            importlib.metadata.PackageNotFoundError(name))
        if name == "crawl4ai" else real_version(name))
    with pytest.raises(Crawl4aiUnavailableError):
        render_markdown("<p>never transformed</p>")


def test_mismatched_crawl4ai_fails_closed(monkeypatch):
    real_version = importlib.metadata.version
    monkeypatch.setattr(
        importlib.metadata, "version",
        lambda name: "0.0.0-not-the-pin" if name == "crawl4ai"
        else real_version(name))
    with pytest.raises(Crawl4aiUnavailableError):
        render_markdown("<p>never transformed</p>")


# ── the guard refuses before the transform ever runs ──


def test_non_allowlisted_url_is_refused_before_transform(monkeypatch):
    _no_transform(monkeypatch)
    fetcher = _fixture_fetcher(b"<p>x</p>")
    with pytest.raises(EgressRefused) as info:
        render_page("https://elsewhere.test/page.html", fetcher=fetcher)
    assert info.value.code == "ORIGIN_NOT_ALLOWLISTED"


def test_redirect_to_internal_address_is_blocked_and_never_dialed(monkeypatch):
    """The S2-mandated fixture: an allowlisted host redirecting to an internal
    address. The redirect target is refused by address and the opener is never
    called for it."""
    _no_transform(monkeypatch)
    calls: list[str] = []

    def redirect_open(target, *, timeout: float, max_bytes: int,
                      user_agent: str) -> _RawResponse:
        calls.append(target.url)
        return _raw(302, Location="https://internal.test/admin",
                    **dict(HTML_HEADERS))

    fetcher = GuardedFetcher(
        EgressPolicy(allowlist=(f"https://{FIXTURE_HOST}",
                                "https://internal.test")),
        resolve=_resolver({FIXTURE_HOST: (PUBLIC_V4,),
                           "internal.test": ("10.0.0.5",)}),
        open_fn=redirect_open)
    with pytest.raises(EgressRefused) as info:
        render_page(f"https://{FIXTURE_HOST}/page.html", fetcher=fetcher)
    assert info.value.code == "ADDRESS_BLOCKED"
    assert calls == [f"https://{FIXTURE_HOST}/page.html"]  # internal never dialed


def test_redirect_to_loopback_ip_literal_is_blocked(monkeypatch):
    _no_transform(monkeypatch)

    def redirect_open(target, *, timeout: float, max_bytes: int,
                      user_agent: str) -> _RawResponse:
        return _raw(301, Location="http://127.0.0.1:8080/internal",
                    **dict(HTML_HEADERS))

    fetcher = GuardedFetcher(
        EgressPolicy(allowlist=(f"https://{FIXTURE_HOST}",
                                "http://127.0.0.1:8080")),
        resolve=_resolver({FIXTURE_HOST: (PUBLIC_V4,)}),
        open_fn=redirect_open)
    with pytest.raises(EgressRefused) as info:
        render_page(f"https://{FIXTURE_HOST}/page.html", fetcher=fetcher)
    assert info.value.code == "ADDRESS_BLOCKED"


@pytest.mark.parametrize("status", [404, 410, 500, 503])
def test_non_2xx_fetch_is_refused_with_code(status, monkeypatch):
    _no_transform(monkeypatch)

    def status_open(target, *, timeout: float, max_bytes: int,
                    user_agent: str) -> _RawResponse:
        return _RawResponse(status=status, headers=HTML_HEADERS, body=b"<p>x</p>")

    fetcher = GuardedFetcher(
        EgressPolicy(allowlist=(f"https://{FIXTURE_HOST}",)),
        resolve=_resolver({FIXTURE_HOST: (PUBLIC_V4,)}), open_fn=status_open)
    with pytest.raises(Crawl4aiProviderError) as info:
        render_page(f"https://{FIXTURE_HOST}/page.html", fetcher=fetcher)
    assert info.value.code == "FETCH_STATUS"
    assert info.value.url == f"https://{FIXTURE_HOST}/page.html"


@pytest.mark.parametrize("content_type", ["application/pdf", "text/plain",
                                          "application/octet-stream", None])
def test_non_html_content_is_refused_with_code(content_type, monkeypatch):
    _no_transform(monkeypatch)

    def typed_open(target, *, timeout: float, max_bytes: int,
                   user_agent: str) -> _RawResponse:
        headers = () if content_type is None else (
            ("Content-Type", content_type),)
        return _RawResponse(status=200, headers=headers, body=b"%PDF-1.7")

    fetcher = GuardedFetcher(
        EgressPolicy(allowlist=(f"https://{FIXTURE_HOST}",)),
        resolve=_resolver({FIXTURE_HOST: (PUBLIC_V4,)}), open_fn=typed_open)
    with pytest.raises(Crawl4aiProviderError) as info:
        render_page(f"https://{FIXTURE_HOST}/page.html", fetcher=fetcher)
    assert info.value.code == "NOT_HTML"


def test_guard_body_cap_refusal_propagates(monkeypatch):
    _no_transform(monkeypatch)
    fetcher = GuardedFetcher(
        EgressPolicy(allowlist=(f"https://{FIXTURE_HOST}",)),
        resolve=_resolver({FIXTURE_HOST: (PUBLIC_V4,)}),
        open_fn=lambda target, **kwargs: _RawResponse(
            status=200, headers=HTML_HEADERS, body=b"x" * 4096),
        max_bytes=1024)
    with pytest.raises(EgressRefused) as info:
        render_page(f"https://{FIXTURE_HOST}/page.html", fetcher=fetcher)
    assert info.value.code == "BODY_TOO_LARGE"


# ── provider logic (stub transform; crawl4ai's own behaviour is the fixtures) ──


def test_render_page_wraps_output_in_untrusted_envelope(monkeypatch):
    _stub_transform(monkeypatch)
    page = render_page(f"https://{FIXTURE_HOST}/page.html",
                       fetcher=_fixture_fetcher(b"<p>secret prose</p>"))
    assert isinstance(page, Crawl4aiPage)
    assert isinstance(page.content, UntrustedContent)
    assert not isinstance(page.content, str)
    assert page.content.origin == "crawl4ai.markdown"
    assert page.payload  # the deliberate .text unwrap
    assert "secret prose" in page.payload
    assert "secret prose" not in str(page.content)
    assert "secret prose" not in repr(page.content)


def test_provenance_records_guard_trail_and_transform_identity(monkeypatch):
    _stub_transform(monkeypatch)
    body = b"<p>provenance</p>"
    fetcher = _fixture_fetcher(body)
    page = render_page(f"https://{FIXTURE_HOST}/page.html", fetcher=fetcher,
                       source_ref="source_payload:s2-crawl4ai/test.html")
    prov = page.provenance
    assert prov.library == "crawl4ai"
    assert prov.version == CRAWL4AI_PIN
    assert prov.config_fingerprint == prov.config.fingerprint
    assert prov.source_ref == "source_payload:s2-crawl4ai/test.html"
    assert prov.requested_url == f"https://{FIXTURE_HOST}/page.html"
    assert prov.final_url == prov.requested_url
    assert prov.status == 200
    assert prov.content_type == "text/html"
    assert prov.encoding == "utf-8"
    assert prov.source_sha256 == _sha256(body)
    assert prov.source_bytes == len(body)
    assert prov.markdown_sha256 == _sha256(page.payload.encode("utf-8"))
    assert prov.guard_policy_fingerprint == fetcher.policy.fingerprint()
    assert prov.guard_hops == ((prov.requested_url, PINNED_ADDRESS),)
    assert prov.redirect_hops == ()
    assert prov.size_bytes() <= MAX_PROVENANCE_BYTES


def test_provenance_size_cap_refuses_rather_than_overflow(monkeypatch):
    _stub_transform(monkeypatch)
    monkeypatch.setattr(crawl4ai_provider, "MAX_PROVENANCE_BYTES", 64)
    with pytest.raises(Crawl4aiProviderError) as info:
        render_page(f"https://{FIXTURE_HOST}/page.html",
                    fetcher=_fixture_fetcher(b"<p>cap</p>"))
    assert info.value.code == "PROVENANCE_TOO_LARGE"


def test_redirect_chain_records_every_vetted_hop(monkeypatch):
    _stub_transform(monkeypatch)
    responses = {
        f"https://{FIXTURE_HOST}/a.html": _raw(
            302, Location=f"https://{FIXTURE_HOST}/b.html", **dict(HTML_HEADERS)),
        f"https://{FIXTURE_HOST}/b.html": _raw(
            301, Location=f"https://{FIXTURE_HOST}/c.html", **dict(HTML_HEADERS)),
        f"https://{FIXTURE_HOST}/c.html": _raw(200, b"<p>end</p>",
                                               **dict(HTML_HEADERS)),
    }

    def chain_open(target, *, timeout: float, max_bytes: int,
                   user_agent: str) -> _RawResponse:
        return responses[target.url]

    fetcher = GuardedFetcher(
        EgressPolicy(allowlist=(f"https://{FIXTURE_HOST}",)),
        resolve=_resolver({FIXTURE_HOST: (PUBLIC_V4B, PUBLIC_V4)}),
        open_fn=chain_open)
    page = render_page(f"https://{FIXTURE_HOST}/a.html", fetcher=fetcher)
    prov = page.provenance
    assert prov.status == 200
    assert prov.final_url == f"https://{FIXTURE_HOST}/c.html"
    assert prov.redirect_hops == (f"https://{FIXTURE_HOST}/a.html",
                                  f"https://{FIXTURE_HOST}/b.html")
    assert tuple(target for target, _ in prov.guard_hops) == (
        f"https://{FIXTURE_HOST}/a.html", f"https://{FIXTURE_HOST}/b.html",
        f"https://{FIXTURE_HOST}/c.html")
    # deterministic pin: the sorted-first address of the vetted set
    assert {pinned for _, pinned in prov.guard_hops} == {
        min(PUBLIC_V4, PUBLIC_V4B)}


def test_render_page_refuses_non_guarded_fetcher():
    """AUDIT-S2 E1 — seal provenance to the real GuardedFetcher: a duck-typed
    fetcher with a hand-rolled hops trail cannot launder guard-anchored
    provenance through render_page. The render_page entry point refuses
    any object that is not a hermes.security.egress.GuardedFetcher, so
    the API-shape hazard documented in AUDIT-S2 E1 cannot regress in
    caller-side code."""
    class _LyingFetcher:
        policy = EgressPolicy(allowlist=(f"https://{FIXTURE_HOST}",))
        def fetch(self, url: str):  # pragma: no cover - never reached
            raise AssertionError("LyingFetcher.fetch must not be reached")

    with pytest.raises(TypeError) as info:
        render_page(f"https://{FIXTURE_HOST}/page.html",
                    fetcher=_LyingFetcher())  # type: ignore[arg-type]
    assert "GuardedFetcher" in str(info.value)


def test_record_round_trip_and_version_refusal(monkeypatch):
    _stub_transform(monkeypatch)
    page = render_page(f"https://{FIXTURE_HOST}/page.html",
                       fetcher=_fixture_fetcher(b"<p>round trip</p>"))
    record = page.to_record()
    assert record["record_version"] == RECORD_VERSION
    assert Crawl4aiPage.from_record(record) == page
    broken = dict(record, record_version="s2-crawl4ai/999")
    with pytest.raises(ValueError):
        Crawl4aiPage.from_record(broken)


def test_config_fingerprint_is_order_independent_and_round_trips():
    a = Crawl4aiConfig(html2text_options=(("body_width", 0),
                                          ("ignore_emphasis", True)))
    b = Crawl4aiConfig(html2text_options=(("ignore_emphasis", True),
                                          ("body_width", 0)))
    assert a == b
    assert a.fingerprint == b.fingerprint
    assert Crawl4aiConfig.from_mapping(a.to_mapping()) == a
    assert Crawl4aiConfig(citations=False).fingerprint != a.fingerprint


# ── fixtures: identity, then exact live replay ──


def test_manifest_covers_every_page():
    manifest = json.loads(
        (FIXTURE_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["fixture_version"] == "s2-crawl4ai-manifest/1"
    listed = sorted(entry["page"] for entry in manifest["pages"])
    assert len(listed) == 10
    assert listed == sorted(path.name for path in PAGES_DIR.glob("*.html"))
    assert sorted(entry["fixture"] for entry in manifest["pages"]) == (
        sorted(path.name for path in FIXTURE_FILES))


@pytest.mark.parametrize("fixture_path", FIXTURE_FILES, ids=FIXTURE_IDS)
def test_fixture_identity_and_record_bounds(fixture_path: Path):
    fixture = load_fixture(fixture_path)
    assert fixture["fixture_version"] == "s2-crawl4ai-fixture/1"
    page = fixture["page"]
    raw = (PAGES_DIR / page["filename"]).read_bytes()
    assert _sha256(raw) == page["sha256"]
    assert len(raw) == page["bytes"]
    assert page["url"] == f"https://{FIXTURE_HOST}/{page['filename']}"

    runs = fixture["runs"]
    assert runs["rerun_identical"] is True
    assert runs["record_diff"] == ""
    assert runs["record_sha256_a"] == runs["record_sha256_b"]
    assert runs["markdown_sha256_a"] == runs["markdown_sha256_b"]
    assert runs["processes"] == 2

    record = fixture["record"]
    rebuilt = Crawl4aiPage.from_record(record)
    assert rebuilt.to_record() == record
    assert rebuilt.content.origin == "crawl4ai.markdown"
    assert rebuilt.content.ref == page["url"]
    prov = rebuilt.provenance
    assert prov.version == CRAWL4AI_PIN
    assert prov.config_fingerprint == prov.config.fingerprint
    assert prov.source_ref == page["source_ref"]
    assert prov.source_sha256 == page["sha256"]
    assert prov.source_bytes == page["bytes"]
    assert prov.markdown_sha256 == _sha256(
        rebuilt.payload.encode("utf-8"))
    assert prov.size_bytes() <= MAX_PROVENANCE_BYTES
    assert prov.redirect_hops == ()
    assert prov.guard_hops, "the guard trail is what proves the guard fetched"
    for url, pinned in prov.guard_hops:
        assert url == page["url"]
        assert pinned == PINNED_ADDRESS
        assert pinned != FIXTURE_HOST
    assert not isinstance(rebuilt.content, str)


@pytest.mark.parametrize("fixture_path", FIXTURE_FILES, ids=FIXTURE_IDS)
@LIVE
def test_live_replay_reproduces_the_recorded_record_exactly(fixture_path: Path):
    fixture = load_fixture(fixture_path)
    page = fixture["page"]
    raw = (PAGES_DIR / page["filename"]).read_bytes()
    replayed = render_page(page["url"], fetcher=_fixture_fetcher(raw),
                           source_ref=page["source_ref"])
    assert replayed.to_record() == fixture["record"]


@LIVE
def test_transform_cannot_open_a_socket_even_importing_crawl4ai():
    """Guard-bypass check: with ``socket.socket``/``create_connection``/
    ``getaddrinfo`` blocked *before* crawl4ai is imported, the whole transform
    (package import included) must still succeed. crawl4ai's
    ``content_scraping_strategy`` defines a ``requests.head`` image-size helper
    — an unguarded-dial hazard — but its only would-be call site is commented
    out; this test turns "the markdown path never dials" into an enforced
    property instead of a reading of the source."""
    fixture = load_fixture(FIXTURE_FILES[0])
    page = fixture["page"]
    page_path = PAGES_DIR / page["filename"]
    src = Path(__file__).resolve().parents[1] / "src"
    code = f"""
import hashlib, socket, sys

def _blocked(*args, **kwargs):
    raise RuntimeError("egress attempted: " + repr(args))

class _BlockedSocket(socket.socket):
    connect = _blocked
    connect_ex = _blocked
    sendto = _blocked

socket.socket = _BlockedSocket
socket.create_connection = _blocked
socket.getaddrinfo = _blocked
sys.path.insert(0, {str(src)!r})
from hermes.tools.providers.crawl4ai_provider import render_markdown
html = open({str(page_path)!r}, "rb").read().decode("utf-8", errors="replace")
render = render_markdown(html, base_url={page["url"]!r})
print(hashlib.sha256(render.raw.text.encode("utf-8")).hexdigest())
"""
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    offline_digest = result.stdout.strip().splitlines()[-1]
    html = page_path.read_bytes().decode("utf-8", errors="replace")
    online_digest = hashlib.sha256(
        render_markdown(html, base_url=page["url"]).raw.text.encode(
            "utf-8")).hexdigest()
    assert offline_digest == online_digest


@LIVE
def test_render_markdown_is_deterministic_across_calls():
    largest = max(PAGES_DIR.glob("*.html"), key=lambda path: path.stat().st_size)
    html = largest.read_bytes().decode("utf-8", errors="replace")
    first = render_markdown(html, base_url=f"https://{FIXTURE_HOST}/x.html")
    second = render_markdown(html, base_url=f"https://{FIXTURE_HOST}/x.html")
    assert first.raw.text == second.raw.text
    assert first.cited.text == second.cited.text
    assert first.references.text == second.references.text
