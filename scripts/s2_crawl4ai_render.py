"""S2 render unit — ONE fixture page through the guard + pinned crawl4ai.

Run by ``scripts/s2_crawl4ai_record.py`` in two fresh processes per page (the
stability evidence). Uses the real :class:`GuardedFetcher` — allowlist, resolve
and pin — with an injected opener that serves the vendored fixture bytes, so
the whole provider path runs (guard vet → pinned dial decision → crawl4ai
transform → untrusted payload + provenance) while no socket is ever opened.

The fetched page's ``Content-Type`` is ``text/html; charset=utf-8`` and the
body is the fixture file byte-for-byte, so ``source_sha256`` in the record is
the fixture hash.

Usage (inside the S2 spike venv):

    python scripts/s2_crawl4ai_render.py --page <fixture.html> \
        --url <fixture-url> --source-ref <ref> --out <record.json>

Prints one line of JSON (summary) to stdout; the full record goes to --out.
Exits non-zero on refusal (``EgressRefused`` / ``Crawl4aiProviderError``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hermes.security.egress import (  # noqa: E402  (path set up above)
    EgressPolicy,
    GuardedFetcher,
    _RawResponse,
)
from hermes.tools.providers.crawl4ai_provider import (  # noqa: E402
    RECORD_VERSION,
    render_page,
)

FIXTURE_HOST = "fixtures.test"
PINNED_ADDRESS = "1.1.1.1"  # deterministic label; no socket is dialed


def fixture_resolver(host: str, port: int) -> tuple[str, ...]:
    if host != FIXTURE_HOST:
        return ()
    return (PINNED_ADDRESS,)


def make_fetcher(page_path: Path) -> GuardedFetcher:
    """The real guard with an injected opener serving vendored fixture bytes."""
    body = page_path.read_bytes()

    def open_fixture(target, *, timeout: float, max_bytes: int,
                     user_agent: str) -> _RawResponse:
        return _RawResponse(
            status=200,
            headers=(("Content-Type", "text/html; charset=utf-8"),
                     ("X-Spike-Fetcher", "vendored-fixture-opener")),
            body=body,
        )

    return GuardedFetcher(
        EgressPolicy(allowlist=(f"https://{FIXTURE_HOST}",)),
        resolve=fixture_resolver,
        open_fn=open_fixture,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    page_path = Path(args.page).resolve()
    fetcher = make_fetcher(page_path)
    result = render_page(args.url, fetcher=fetcher,
                         source_ref=args.source_ref)
    record = result.to_record()
    record_text = json.dumps(record, ensure_ascii=False, sort_keys=True,
                             indent=1)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(record_text, encoding="utf-8")

    provenance = record["provenance"]
    summary = {
        "record_version": record["record_version"],
        "record_sha256": hashlib.sha256(record_text.encode("utf-8")).hexdigest(),
        "markdown_sha256": provenance["markdown_sha256"],
        "markdown_chars": len(record["content"]["text"]),
        "source_sha256": provenance["source_sha256"],
        "source_bytes": provenance["source_bytes"],
        "guard_hops": provenance["guard_hops"],
        "provenance_bytes": len(json.dumps(
            provenance, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")),
    }
    assert record["record_version"] == RECORD_VERSION
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
