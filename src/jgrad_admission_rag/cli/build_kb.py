from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..builder.kb_builder import build_document_kb, write_document_kb


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a RAG-ready admission document KB.")
    parser.add_argument("pdf", help="Source admission guideline PDF.")
    parser.add_argument("--output", default=None, help="Output document_kb.json path.")
    parser.add_argument("--max-chars", type=int, default=6000, help="Max characters per chunk.")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    output = (
        Path(args.output)
        if args.output
        else Path("outputs") / "kb" / pdf_path.stem / "document_kb.json"
    )
    kb = build_document_kb(pdf_path, max_chars=args.max_chars)
    write_document_kb(kb, output)
    print(
        json.dumps(
            {
                "output": str(output),
                "chunks": kb.manifest.chunk_count,
                "facts": len(kb.facts),
                "retrieval_units": len(kb.retrieval_units),
                "reference_links": kb.manifest.reference_link_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
