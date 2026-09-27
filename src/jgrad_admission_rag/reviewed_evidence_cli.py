"""Non-production local evidence preview; writes only stdout (redirect if desired)."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from pydantic import ValidationError

from jgrad_admission_rag.reviewed_source_evidence import (
    EvidenceError,
    Trust,
    canonical_json_bytes,
    inspect_evidence,
    parse_json,
    render_markdown,
)


def _write_utf8(stream, content: str) -> None:
    # Binary stdout preserves canonical UTF-8/LF even on Windows. String-only
    # streams remain useful to callers embedding the CLI (and capture fixtures).
    if hasattr(stream, "buffer"):
        stream.buffer.write(content.encode("utf-8"))
    else:
        stream.write(content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target-contract", type=Path, required=True)
    parser.add_argument(
        "--trust",
        type=Path,
        required=True,
        help="explicit repository-reviewed pin; never derive from input at runtime",
    )
    parser.add_argument(
        "--request", type=Path, required=True, help="JSON with complete target and source_set"
    )
    parser.add_argument("--topic", required=True)
    parser.add_argument("--source", action="append", default=[], metavar="ID=PATH")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args(argv)
    try:
        paths = {}
        for item in args.source:
            source_id, separator, path = item.partition("=")
            if not separator or not source_id or not path or source_id in paths:
                raise EvidenceError(
                    "invalid_request", "sources require unique explicit ID=PATH pairs"
                )
            paths[source_id] = Path(path)
        trust = Trust.model_validate(parse_json(args.trust.read_bytes()))
        request = parse_json(args.request.read_bytes())
        if not isinstance(request, dict) or set(request) != {"target", "source_set"}:
            raise EvidenceError("not_covered", "request requires complete target and source_set")
        preview = inspect_evidence(
            args.bundle.read_bytes(),
            manifest_bytes=args.manifest.read_bytes(),
            target_contract_bytes=args.target_contract.read_bytes(),
            trust=trust,
            target=request["target"],
            source_set=request["source_set"],
            topic_id=args.topic,
            source_paths=paths,
        )
        output = (
            canonical_json_bytes(preview).decode("utf-8")
            if args.format == "json"
            else render_markdown(preview)
        )
    except (EvidenceError, OSError, ValueError, ValidationError) as exc:
        code = (
            exc.code
            if isinstance(exc, EvidenceError)
            else ("input_unavailable" if isinstance(exc, OSError) else "invalid_request")
        )
        # Do not leak excerpts, private filesystem paths or a partly verified preview.
        _write_utf8(sys.stderr, canonical_json_bytes({"status": code, "preview": None}).decode())
        return 2
    _write_utf8(sys.stdout, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
