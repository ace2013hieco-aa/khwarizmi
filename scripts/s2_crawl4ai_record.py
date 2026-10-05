"""S2 fixture recorder — two separate-process renders per page, then fixtures.

For each vendored HTML fixture this script:

1. spawns ``scripts/s2_crawl4ai_render.py`` **twice in fresh processes** with an
   explicit environment allowlist (no secret- or vault-bearing variable is
   passed; the child reads only the fixture page);
2. compares the two records — the S2 stability evidence: for identical input
   (guarded fetch of the vendored bytes + pinned crawl4ai transform) the
   provider is deterministic, and the byte-identical record proves it without
   quantisation;
3. writes ``tests/fixtures/s2_crawl4ai/<stem>.json`` and
   ``tests/fixtures/s2_crawl4ai/MANIFEST.json``.

The fixture pages are ten vendored HTML documents: eight copies of this
repository's ``docs/diagrams/*.html`` (captured 2026-10-01) and two synthetic
pages authored for this spike to add document-structure and malformed-HTML
breadth. No page was fetched from the network; the S2 record scripts never open
a socket (the guard's opener is injected and serves the vendored bytes).

Run from the repo root inside the S2 spike venv:

    .venv/Scripts/python.exe scripts/s2_crawl4ai_record.py

Exits non-zero if any page's two runs disagree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "s2_crawl4ai"
PAGES_DIR = FIXTURE_DIR / "pages"
RENDERER = ROOT / "scripts" / "s2_crawl4ai_render.py"
SCRATCH = ROOT / ".venv" / ".s2-runs"
FIXTURE_HOST = "fixtures.test"

# The vendored repo documents: fixture name -> repo-relative source at capture.
REPO_DOCS = {
    "authority_trust_boundary.html": "docs/diagrams/authority_trust_boundary.html",
    "digest_fold_adversarial.html": "docs/diagrams/digest_fold_adversarial.html",
    "horizon_cliff_late_handler.html": "docs/diagrams/horizon_cliff_late_handler.html",
    "ladder_refuted_drivers.html": "docs/diagrams/ladder_refuted_drivers.html",
    "one_verdict_gate_adversarial.html": "docs/diagrams/one_verdict_gate_adversarial.html",
    "provider_search_fetch_recovery.html": "docs/diagrams/provider_search_fetch_recovery.html",
    "redteam_reconciliation.html": "docs/diagrams/redteam_reconciliation.html",
    "research_os_loop.html": "docs/diagrams/research_os_loop.html",
}
SYNTHETIC = {
    "synthetic_document_structure.html": (
        "synthetic, authored for the S2 spike: headings, inline formatting, "
        "lists, blockquote, table, pre/code, entities, unicode, references"),
    "synthetic_malformed.html": (
        "synthetic, authored for the S2 spike: unclosed/uppercase/mismatched "
        "tags, unquoted attributes, stray '<', textarea/noscript/template"),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _process_env() -> dict[str, str]:
    """Explicit allowlist environment — no secret/vault variables inherited."""
    allow = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP",
             "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS",
             "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
    env = {name: os.environ[name] for name in allow if name in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _first_difference(a, b, path: str = "") -> str:
    """Path of the first differing field between two parsed records."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            found = _first_difference(a.get(key), b.get(key), f"{path}.{key}")
            if found:
                return found
        return ""
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path} (length {len(a)} != {len(b)})"
        for index, (left, right) in enumerate(zip(a, b)):
            found = _first_difference(left, right, f"{path}[{index}]")
            if found:
                return found
        return ""
    return "" if a == b else path.lstrip(".")


def _run_render(page: Path, url: str, source_ref: str, out: Path) -> dict:
    try:
        result = subprocess.run(
            [sys.executable, str(RENDERER),
             "--page", str(page), "--url", url,
             "--source-ref", source_ref, "--out", str(out)],
            cwd=str(ROOT), env=_process_env(), check=True,
            capture_output=True, text=True, encoding="utf-8")
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or "", file=sys.stderr)
        raise
    return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captured", default="2026-10-01",
                        help="capture date recorded in the manifest")
    args = parser.parse_args()

    pages = sorted(PAGES_DIR.glob("*.html"))
    if len(pages) < 10:
        print(f"expected 10 fixture pages, found {len(pages)} under "
              f"{PAGES_DIR}", file=sys.stderr)
        return 2
    SCRATCH.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    mismatches: list[str] = []
    summary: list[dict] = []
    for page in pages:
        name = page.name
        url = f"https://{FIXTURE_HOST}/{name}"
        source_ref = f"source_payload:s2-crawl4ai/{name}"
        raw = page.read_bytes()
        run_a = _run_render(page, url, source_ref, SCRATCH / f"{page.stem}.a.json")
        run_b = _run_render(page, url, source_ref, SCRATCH / f"{page.stem}.b.json")
        record_a = json.loads(
            (SCRATCH / f"{page.stem}.a.json").read_text(encoding="utf-8"))
        record_b = json.loads(
            (SCRATCH / f"{page.stem}.b.json").read_text(encoding="utf-8"))
        identical = record_a == record_b
        if not identical:
            mismatches.append(name)
        if name in REPO_DOCS:
            source_kind = "repo-doc-vendored"
            source_path = REPO_DOCS[name]
            docs_copy = (ROOT / source_path).read_bytes()
            source_note = "vendored copy of a repository document"
            docs_match = _sha256(docs_copy) == _sha256(raw)
        else:
            source_kind = "synthetic-authored"
            source_path = None
            source_note = SYNTHETIC[name]
            docs_match = None

        fixture = {
            "fixture_version": "s2-crawl4ai-fixture/1",
            "page": {
                "filename": name,
                "sha256": _sha256(raw),
                "bytes": len(raw),
                "url": url,
                "source_ref": source_ref,
                "source_kind": source_kind,
                "source_path_at_capture": source_path,
                "source_note": source_note,
                "repo_doc_copy_matches_at_record_time": docs_match,
            },
            "runs": {
                "processes": 2,
                "record_sha256_a": run_a["record_sha256"],
                "record_sha256_b": run_b["record_sha256"],
                "markdown_sha256_a": run_a["markdown_sha256"],
                "markdown_sha256_b": run_b["markdown_sha256"],
                "rerun_identical": identical,
                "record_diff": (
                    "" if identical
                    else _first_difference(record_a, record_b)),
            },
            "record": record_a,
        }
        fixture_path = FIXTURE_DIR / f"{page.stem}.json"
        fixture_path.write_text(
            json.dumps(fixture, ensure_ascii=False, sort_keys=True, indent=1),
            encoding="utf-8")
        manifest.append({
            "fixture": fixture_path.name,
            "page": name,
            "sha256": _sha256(raw),
            "bytes": len(raw),
            "url": url,
            "source_kind": source_kind,
            "source_note": source_note,
            "markdown_chars": run_a["markdown_chars"],
            "markdown_sha256": run_a["markdown_sha256"],
            "record_sha256": run_a["record_sha256"],
            "guard_hops": run_a["guard_hops"],
            "provenance_bytes": run_a["provenance_bytes"],
            "rerun_identical": identical,
        })
        summary.append({
            "page": name,
            "markdown_chars": run_a["markdown_chars"],
            "markdown_sha256": run_a["markdown_sha256"][:16],
            "record_sha256": run_a["record_sha256"][:16],
            "provenance_bytes": run_a["provenance_bytes"],
            "identical": identical,
        })

    (FIXTURE_DIR / "MANIFEST.json").write_text(
        json.dumps({
            "fixture_version": "s2-crawl4ai-manifest/1",
            "captured": args.captured,
            "pages": manifest,
        }, ensure_ascii=False, sort_keys=True, indent=1),
        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=1))
    if mismatches:
        print(f"RERUN MISMATCH for {mismatches}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
