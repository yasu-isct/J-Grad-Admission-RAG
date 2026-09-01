from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from ..retrieval.embedding import (
    DeterministicFakeEmbeddingProvider,
    EmbeddingError,
    EmbeddingProvider,
)
from ..retrieval.local_index import (
    MANIFEST_FILENAME,
    IndexBuildError,
    build_local_index,
)
from ..retrieval.sentence_transformer import (
    SentenceTransformerConfig,
    SentenceTransformerEmbeddingProvider,
)
from ..schemas.index import IndexManifest


class CliConfigurationError(ValueError):
    """Raised when provider-specific CLI arguments are incomplete or incompatible."""


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a validated local vector index from a trusted document KB."
    )
    parser.add_argument("kb", help="Trusted document_kb.json path.")
    parser.add_argument("--output", required=True, help="New index directory (must be absent).")
    parser.add_argument(
        "--provider",
        required=True,
        choices=("deterministic-fake", "sentence-transformers"),
    )
    parser.add_argument("--dimension", type=_positive_int)
    parser.add_argument("--model")
    parser.add_argument("--revision")
    parser.add_argument("--batch-size", type=_positive_int)
    parser.add_argument("--cache-folder")
    parser.add_argument("--allow-model-download", action="store_true")
    return parser


def _require(args: argparse.Namespace, names: Sequence[str]) -> None:
    missing = [f"--{name.replace('_', '-')}" for name in names if getattr(args, name) is None]
    if missing:
        raise CliConfigurationError(f"missing required option(s): {', '.join(missing)}")


def _reject(args: argparse.Namespace, names: Sequence[str]) -> None:
    incompatible = []
    for name in names:
        value = getattr(args, name)
        if value is not None and value is not False:
            incompatible.append(f"--{name.replace('_', '-')}")
    if incompatible:
        raise CliConfigurationError(
            f"option(s) incompatible with provider {args.provider!r}: {', '.join(incompatible)}"
        )


def _build_provider(args: argparse.Namespace) -> EmbeddingProvider:
    try:
        if args.provider == "deterministic-fake":
            _require(args, ("dimension",))
            _reject(
                args,
                ("model", "revision", "batch_size", "cache_folder", "allow_model_download"),
            )
            return DeterministicFakeEmbeddingProvider(dimension=args.dimension)

        _require(args, ("model", "revision", "dimension"))
        config = SentenceTransformerConfig(
            model_name=args.model,
            revision=args.revision,
            expected_dimension=args.dimension,
            batch_size=args.batch_size if args.batch_size is not None else 8,
            cache_folder=args.cache_folder,
            allow_download=args.allow_model_download,
        )
        return SentenceTransformerEmbeddingProvider(config)
    except CliConfigurationError:
        raise
    except ValueError as error:
        raise CliConfigurationError(str(error)) from error


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
