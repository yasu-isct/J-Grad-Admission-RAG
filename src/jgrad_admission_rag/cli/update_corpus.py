from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Sequence

from ..corpus import (
    CorpusBuildError,
    CorpusCommitStateError,
    CorpusConcurrentUpdateError,
    CorpusPublicationError,
    CorpusRegistration,
    CorpusUpdateError,
    update_corpus_manifest,
)


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        _write_json(
            {"error": "invalid command arguments", "kind": "argument_error"},
            stream=sys.stderr,
        )
        raise SystemExit(2)


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description="Atomically add or replace one explicit corpus manifest registration."
    )
    parser.add_argument("manifest", help="Existing canonical CorpusManifest JSON file.")
    parser.add_argument("--corpus-root", required=True, help="Absolute corpus artifact root.")
    parser.add_argument("--action", required=True, choices=("add", "replace"))
    parser.add_argument("--kb", required=True, help="Corpus-root-relative POSIX KB path.")
    parser.add_argument("--index", help="Optional corpus-root-relative POSIX index directory.")
    parser.add_argument("--replace-document-id", help="Exact current document ID for replace.")
    return parser


def _error_kind(error: CorpusUpdateError) -> tuple[str, int]:
    if isinstance(error, CorpusConcurrentUpdateError):
        return "concurrent_update_error", 3
    if isinstance(error, CorpusPublicationError):
        return "publication_error", 4
    if isinstance(error, CorpusCommitStateError):
        return "commit_state_error", 5
    return "validation_error", 2


def _write_json(value: dict[str, object], *, stream) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), file=stream)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        candidate = CorpusRegistration(kb_path=args.kb, index_path=args.index)
        result = update_corpus_manifest(
            args.corpus_root,
            args.manifest,
            action=args.action,
            candidate=candidate,
            replace_document_id=args.replace_document_id,
        )
    except (CorpusUpdateError, CorpusBuildError) as error:
        kind, exit_code = (
            _error_kind(error) if isinstance(error, CorpusUpdateError) else ("validation_error", 2)
        )
        _write_json({"error": str(error), "kind": kind}, stream=sys.stderr)
        raise SystemExit(exit_code) from None

    _write_json(asdict(result), stream=sys.stdout)


if __name__ == "__main__":
    main()
