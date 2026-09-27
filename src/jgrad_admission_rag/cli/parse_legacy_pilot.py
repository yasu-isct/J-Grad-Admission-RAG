"""Explicit offline invocation for the experimental legacy parser adapter."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import time

from pydantic import ValidationError

from jgrad_admission_rag.parsing import (
    ExactSource,
    LegacyAdapterError,
    ParseRequest,
    canonical_normalized_document_bytes,
    parse_legacy_pdf,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wrap one locked local PDF with the experimental legacy parser adapter."
    )
    parser.add_argument("--source-lock", required=True, type=Path)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pages", nargs="+", type=int)
    args = parser.parse_args()

    try:
        lock_entry = _load_source_lock_entry(args.source_lock, args.source_id)
        request = (
            ParseRequest(selection="pages", pages=tuple(args.pages))
            if args.pages is not None
            else ParseRequest(selection="all")
        )
        source = ExactSource(
            path=args.pdf,
            source_id=lock_entry["source_id"],
            expected_sha256=lock_entry["sha256"],
            expected_physical_page_count=lock_entry["physical_page_count"],
        )
        started = time.perf_counter()
        document = parse_legacy_pdf(source, request)
        payload = canonical_normalized_document_bytes(document)
        _publish_new_file(args.output, payload)
        elapsed = time.perf_counter() - started
    except (LegacyAdapterError, ValidationError, ValueError, OSError) as error:
        parser.error(str(error))

    print(
        json.dumps(
            {
                "output": str(args.output),
                "run_id": document.run_id,
                "output_digest": document.output_digest,
                "pages": document.coverage.returned_pages,
                "elapsed_seconds": round(elapsed, 3),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _load_source_lock_entry(path: Path, source_id: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("source lock is missing, unreadable, or unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        sources = payload["sources"]
        matches = [entry for entry in sources if entry.get("source_id") == source_id]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
        raise ValueError("source lock is invalid or unsupported") from None
    if len(matches) != 1:
        raise ValueError("source lock must contain exactly one matching source_id")
    entry = matches[0]
    if (
        not isinstance(entry.get("source_id"), str)
        or not isinstance(entry.get("sha256"), str)
        or not isinstance(entry.get("physical_page_count"), int)
        or isinstance(entry.get("physical_page_count"), bool)
    ):
        raise ValueError("source lock entry is invalid or unsupported")
    return entry


def _publish_new_file(output: Path, payload: bytes) -> None:
    """Publish complete bytes without overwriting an existing path."""

    parent = output.parent
    if output.is_symlink() or output.exists():
        raise FileExistsError("output path already exists; refusing to overwrite")
    if not parent.is_dir():
        raise FileNotFoundError("output parent directory must already exist")
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
