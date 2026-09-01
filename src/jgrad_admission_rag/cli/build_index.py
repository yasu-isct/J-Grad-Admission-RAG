from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from ..retrieval.embedding import EmbeddingError
from ..retrieval.local_index import (
    MANIFEST_FILENAME,
    IndexBuildError,
    build_local_index,
)
from ..schemas.index import IndexManifest
from .provider_config import (
    CliConfigurationError,
    add_provider_arguments,
    build_provider as _build_provider,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a validated local vector index from a trusted document KB."
    )
    parser.add_argument("kb", help="Trusted document_kb.json path.")
    parser.add_argument("--output", required=True, help="New index directory (must be absent).")
    add_provider_arguments(parser)
    return parser


def _success_summary(manifest: IndexManifest, output: Path) -> dict[str, object]:
    return {
        "output": str(output),
        "document_id": manifest.document_id,
        "source_kb_sha256": manifest.source_kb_sha256,
        "source_pdf_sha256": manifest.source_pdf_sha256,
        "index_schema_version": manifest.index_schema_version,
        "payload_count": manifest.payload_count,
        "vector_count": manifest.vector_count,
        "embedding_dimension": manifest.embedding_dimension,
        "embedding_provider": manifest.embedding_provider,
        "embedding_model": manifest.embedding_model,
        "embedding_revision": manifest.embedding_revision,
        "distance_metric": manifest.distance_metric,
        "vectors_normalized": manifest.vectors_normalized,
        "payloads_sha256": manifest.payloads_sha256,
        "vectors_sha256": manifest.vectors_sha256,
        "artifacts": {
            "manifest": MANIFEST_FILENAME,
            "payloads": manifest.payloads_filename,
            "vectors": manifest.vectors_filename,
        },
        "semantic": manifest.embedding_provider != "deterministic-fake",
    }


def _write_json(value: dict[str, object], *, stream) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), file=stream)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        provider = _build_provider(args)
        manifest = build_local_index(args.kb, args.output, provider)
    except CliConfigurationError as error:
        _write_json(
            {"error": str(error), "kind": "configuration_error", "provider": args.provider},
            stream=sys.stderr,
        )
        raise SystemExit(2) from None
    except EmbeddingError as error:
        _write_json(
            {"error": str(error), "kind": "embedding_error", "provider": args.provider},
            stream=sys.stderr,
        )
        raise SystemExit(2) from None
    except IndexBuildError as error:
        _write_json(
            {"error": str(error), "kind": "index_build_error", "provider": args.provider},
            stream=sys.stderr,
        )
        raise SystemExit(2) from None

    _write_json(_success_summary(manifest, Path(args.output)), stream=sys.stdout)


if __name__ == "__main__":
    main()
