"""S1 fixture recorder — two separate-process conversions per paper, then fixtures.

For each vendored paper this script:

1. spawns ``scripts/s1_docling_convert.py`` **twice in fresh processes** with an
   explicit environment allowlist (PATH/SYSTEMROOT/TEMP/PYTHONIOENCODING plus
   the in-worktree model cache dirs) — no secret- or vault-bearing variable is
   passed, and the process reads only the given PDF;
2. compares the two run records (structure digest + payload hash) — the
   "re-running gives identical structure for identical input" S1 evidence;
3. selects claim surrogates deterministically (documented rules below — no
   cherry-picking, no LLM in the loop) and records their expected
   page/bbox/charspan from the provider's own index;
4. writes ``tests/fixtures/s1_docling/<paper>.json`` and
   ``tests/fixtures/s1_docling/MANIFEST.json``.

Run from the repo root inside the spike venv:

    .venv/Scripts/python.exe scripts/s1_docling_record.py \
        --source-root "D:\\Software\\Research-agent-improvement"

Exits non-zero if any paper's two runs disagree.
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
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "s1_docling"
PAPERS_DIR = FIXTURE_DIR / "papers"
CONVERTER = ROOT / "scripts" / "s1_docling_convert.py"

# The vendored capture set: fixture filename -> path relative to --source-root.
SOURCE_PATHS = {
    "2305.10601v2.pdf": "papers/2305.10601v2.pdf",
    "2506.05109v1.pdf": "papers/2506.05109v1.pdf",
    "2603.24639v2.pdf": "papers/2603.24639v2.pdf",
    "2510.02557v1.pdf": "papers2/2510.02557v1.pdf",
}

QUOTE_LIMITS = {"first_page": 240, "middle_page": 240, "last_page": 240,
                "document": 320}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _process_env() -> dict[str, str]:
    """Explicit allowlist environment — no secret/vault variables inherited."""
    allow = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP",
             "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS",
             "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
    env = {name: os.environ[name] for name in allow if name in os.environ}
    env.update({
        "PYTHONIOENCODING": "utf-8",
        "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
        # scratch model caches live under the ignored .venv/ (no repo clutter)
        "DOCLING_CACHE_DIR": str(ROOT / ".venv" / ".s1-models"),
        "HF_HOME": str(ROOT / ".venv" / ".s1-hf"),
    })
    return env


def _run_converter(pdf: Path, source_ref: str, out: Path) -> dict:
    try:
        result = subprocess.run(
            [sys.executable, str(CONVERTER),
             "--pdf", str(pdf), "--source-ref", source_ref, "--out", str(out)],
            cwd=str(ROOT), env=_process_env(), check=True,
            capture_output=True, text=True, encoding="utf-8")
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or "", file=sys.stderr)
        raise
    return json.loads(result.stdout.strip().splitlines()[-1])


def _sentence_quote(payload: str, start: int, end: int, limit: int) -> str:
    """Quote from a span: leading slice to a sentence boundary within limit."""
    window = payload[start:min(end, start + limit)]
    cut = window.find(". ")
    if cut >= 40:
        return window[:cut + 1]
    cut = window.find(".\n")
    if cut >= 40:
        return window[:cut + 1]
    return window


def _longest_text_span(spans: list[dict], page: int) -> dict | None:
    candidates = [s for s in spans
                  if s["kind"] == "text" and s["page"] == page]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s["char_end"] - s["char_start"])


def _diff_value(value):
    """Bounded representation of a differing value (long strings → hash)."""
    if isinstance(value, str) and len(value) > 200:
        return {"sha256": _sha256(value.encode("utf-8")), "len": len(value)}
    return value


def _record_diff(a, b, path: str = "") -> list[dict]:
    """Deterministic field-level diff between two raw run records."""
    out: list[dict] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if path == "" and key in ("digest", "payload_sha256"):
                continue  # compared separately
            out.extend(_record_diff(a.get(key), b.get(key), f"{path}.{key}"))
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(_record_diff(x, y, f"{path}[{i}]"))
    elif a != b:
        out.append({"path": path.lstrip("."), "a": _diff_value(a),
                    "b": _diff_value(b)})
    return out


def _positive_claims(record: dict) -> list[dict]:
    """Deterministic claim surrogates (documented rules, no model extraction).

    - first_page: longest text span on the first page that carries text;
    - middle_page: longest text span on the median page carrying text;
    - last_page: longest text span on the last page carrying text;
    - document: longest text span overall;
    - table_cell: longest table-cell text between 8 and 200 chars (if any).
    """
    payload = record["content"]["text"]
    spans = record["spans"]
    text_spans = [s for s in spans if s["kind"] == "text"]
    pages = sorted({s["page"] for s in text_spans})
    claims: list[dict] = []
    if not pages:
        return claims

    picks = [("first_page", pages[0]), ("middle_page", pages[len(pages) // 2]),
             ("last_page", pages[-1])]
    seen: set[str] = set()
    for name, page in picks:
        span = _longest_text_span(spans, page)
        if span is None:
            continue
        quote = _sentence_quote(payload, span["char_start"], span["char_end"],
                                QUOTE_LIMITS[name])
        if not quote or quote in seen:
            continue
        seen.add(quote)
        claims.append({"id": name, "rule": f"longest text span on page {page}",
                       "quote": quote,
                       "span": {"page": span["page"], "bbox": span["bbox"],
                                "coord_origin": span["coord_origin"],
                                "kind": span["kind"]}})

    span = max(text_spans, key=lambda s: s["char_end"] - s["char_start"]) \
        if text_spans else None
    if span is not None:
        quote = _sentence_quote(payload, span["char_start"], span["char_end"],
                                QUOTE_LIMITS["document"])
        if quote and quote not in seen:
            seen.add(quote)
            claims.append({"id": "document",
                           "rule": "longest text span overall", "quote": quote,
                           "span": {"page": span["page"],
                                    "bbox": span["bbox"],
                                    "coord_origin": span["coord_origin"],
                                    "kind": span["kind"]}})

    cells = [s for s in spans if s["kind"] == "table_cell"
             and 8 <= s["char_end"] - s["char_start"] <= 200]
    if cells:
        span = max(cells, key=lambda s: s["char_end"] - s["char_start"])
        quote = payload[span["char_start"]:span["char_end"]]
        claims.append({"id": "table_cell",
                       "rule": "longest table cell (8..200 chars)",
                       "quote": quote,
                       "span": {"page": span["page"], "bbox": span["bbox"],
                                "coord_origin": span["coord_origin"],
                                "kind": span["kind"]}})
    return claims


def _negative_claims(record: dict, positives: list[dict]) -> list[dict]:
    """One fabricated quote + one block-boundary quote; both verified unroutable."""
    payload = record["content"]["text"]
    spans = record["spans"]
    negatives: list[dict] = []

    if positives:
        quote = positives[0]["quote"]
        replacement = "Q" if not quote.startswith("Q") else "R"
        mutated = replacement + quote[1:]
        method = "first character replaced"
        if payload.find(mutated) != -1:
            mutated = quote[:-1] + replacement
            method = "last character replaced"
        if payload.find(mutated) != -1:
            mutated = quote + "\u0001"
            method = "sentinel appended"
        negatives.append({"id": "fabricated", "rule": method,
                          "quote": mutated, "reason": "fabricated"})

    adjacent = sorted(
        (s for s in spans if s["kind"] == "text"),
        key=lambda s: s["char_start"])
    for left, right in zip(adjacent, adjacent[1:]):
        if right["char_start"] - left["char_end"] != 2:
            continue  # not a "\n\n" block boundary
        if left["char_start"] < 3:
            continue
        quote = payload[left["char_end"] - 3:right["char_start"] + 3]
        if len(quote) >= 6:
            negatives.append({"id": "block_boundary",
                              "rule": "quote spanning two payload blocks",
                              "quote": quote, "reason": "block_boundary"})
            break
    return negatives


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", default="",
                        help="root the vendored papers were copied from")
    args = parser.parse_args()

    papers = sorted(PAPERS_DIR.glob("*.pdf"))
    if not papers:
        print(f"no papers under {PAPERS_DIR}", file=sys.stderr)
        return 2

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    scratch = FIXTURE_DIR / ".runs"
    scratch.mkdir(exist_ok=True)

    manifest: list[dict] = []
    mismatches: list[str] = []
    summary: list[dict] = []
    for pdf in papers:
        raw = pdf.read_bytes()
        source_ref = f"source_payload:s1-docling/{pdf.name}"
        source_rel = SOURCE_PATHS.get(pdf.name, pdf.name)
        source_path = (str((Path(args.source_root) / source_rel).resolve())
                       if args.source_root else source_rel)
        run_a = _run_converter(pdf, source_ref, scratch / f"{pdf.stem}.a.json")
        run_b = _run_converter(pdf, source_ref, scratch / f"{pdf.stem}.b.json")
        record_a = _read_json(scratch / f"{pdf.stem}.a.json")
        record_b = _read_json(scratch / f"{pdf.stem}.b.json")
        identical = (run_a["digest"] == run_b["digest"]
                     and run_a["payload_sha256"] == run_b["payload_sha256"])
        if not identical:
            mismatches.append(pdf.name)
        raw_differences = _record_diff(record_a, record_b)

        record = record_a  # identical by assertion; record_a is the fixture
        positives = _positive_claims(record)
        negatives = _negative_claims(record, positives)
        fixture = {
            "fixture_version": "s1-docling-fixture/1",
            "paper": {
                "filename": pdf.name,
                "sha256": _sha256(raw),
                "bytes": len(raw),
                "source_path_at_capture": source_path,
                "source_note": "vendored local fixture; not for redistribution",
            },
            "runs": {
                "digest_a": run_a["digest"],
                "digest_b": run_b["digest"],
                "payload_sha256_a": run_a["payload_sha256"],
                "payload_sha256_b": run_b["payload_sha256"],
                "rerun_identical": identical,
                "raw_record_equal": not raw_differences,
                "raw_difference_count": len(raw_differences),
                "raw_differences": raw_differences[:64],
                "raw_difference_note": (
                    "structure_digest quantizes coordinates to 0.001 pt "
                    "(docling model-level float variance observed in S1); "
                    "raw docling floats are kept in record"),
                "spans": run_a["spans"],
                "tables": run_a["tables"],
                "payload_chars": run_a["payload_chars"],
            },
            "record": record,
            "claims": positives,
            "negative_claims": negatives,
        }
        fixture_path = FIXTURE_DIR / f"{pdf.stem}.json"
        fixture_path.write_text(
            json.dumps(fixture, ensure_ascii=False, sort_keys=True, indent=1),
            encoding="utf-8")
        manifest.append({
            "fixture": fixture_path.name,
            "paper": pdf.name,
            "sha256": _sha256(raw),
            "bytes": len(raw),
            "source_path_at_capture": source_path,
            "pages": record["provenance"]["page_count"],
            "tables": record["provenance"]["table_count"],
            "spans": record["provenance"]["span_count"],
            "claims": len(positives),
            "negative_claims": len(negatives),
            "digest": run_a["digest"],
            "rerun_identical": identical,
            "raw_record_equal": not raw_differences,
            "raw_difference_count": len(raw_differences),
        })
        summary.append({
            "paper": pdf.name,
            "convert": "2x separate process",
            "digest": run_a["digest"][:16],
            "payload_sha256": run_a["payload_sha256"][:16],
            "payload_chars": run_a["payload_chars"],
            "spans": run_a["spans"],
            "tables": run_a["tables"],
            "claims": len(positives),
            "negatives": len(negatives),
            "identical": identical,
        })

    (FIXTURE_DIR / "MANIFEST.json").write_text(
        json.dumps({"papers": manifest}, ensure_ascii=False, sort_keys=True,
                   indent=1),
        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=1))
    if mismatches:
        print(f"RERUN MISMATCH for {mismatches}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
