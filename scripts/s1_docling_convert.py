"""S1 separate-process converter — one PDF in, one deterministic JSON run record out.

This is the separate-process unit of adoption-proposal §4 rule 5: model
inference runs here, in a fresh process, and the process is given only
``--pdf``/``--source-ref``/``--out``. It holds no credentials, consults no
config or vault directory, and is spawned by ``s1_docling_record.py`` with an
explicit environment allowlist (no secret-bearing variables). The control
plane never imports docling (the provider module is the only importer).

Usage (from the repo root, inside the spike venv):

    .venv/Scripts/python.exe scripts/s1_docling_convert.py \
        --pdf tests/fixtures/s1_docling/papers/<paper>.pdf \
        --source-ref source_payload:s1-docling/<paper>.pdf \
        --out <run record>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hermes.tools.providers.docling_provider import convert_pdf  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    document = convert_pdf(args.pdf, source_ref=args.source_ref)
    out = Path(args.out)
    out.write_text(
        json.dumps(document.to_record(), ensure_ascii=False, sort_keys=True,
                   indent=1),
        encoding="utf-8")
    print(json.dumps({
        "digest": document.structure_digest(),
        "payload_sha256": document.payload_sha256(),
        "payload_chars": len(document.payload),
        "spans": len(document.spans),
        "tables": len(document.tables),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
