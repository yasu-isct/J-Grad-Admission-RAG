from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from ..retrieval.embedding import EmbeddingError
from ..retrieval.index_freshness import (
    CurrentKbInputError,
    IndexFreshnessReport,
    StaleIndexError,
    check_index_freshness,
)
from ..retrieval.local_index import IndexLoadError, load_local_index
from ..retrieval.vector_search import (
    VectorSearchError,
    VectorSearchResult,
    search_loaded_index,
    validate_search_inputs,
)
from .provider_config import (
    FAKE_PROVIDER_NAME,
    CliConfigurationError,
    add_provider_arguments,
    create_provider,
    positive_int,
    resolve_provider_configuration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search a validated local vector index for evidence candidates."
    )
    parser.add_argument("index", help="Validated local index directory.")
    parser.add_argument("--current-kb", required=True, help="Current trusted document_kb.json.")
    parser.add_argument("--query", required=True, help="Non-blank retrieval query.")
    parser.add_argument("--top-k", type=positive_int, default=5)
    add_provider_arguments(parser)
    return parser


def _success_summary(
    result: VectorSearchResult,
    index: Path,
    top_k_requested: int,
    freshness: IndexFreshnessReport,
) -> dict[str, object]:
    manifest = result.manifest
    return {
        "index": str(index),
        "document_id": manifest.document_id,
        "source_kb_sha256": manifest.source_kb_sha256,
        "source_pdf_sha256": manifest.source_pdf_sha256,
        "index_schema_version": manifest.index_schema_version,
        "embedding_provider": manifest.embedding_provider,
        "embedding_model": manifest.embedding_model,
        "embedding_revision": manifest.embedding_revision,
        "embedding_dimension": manifest.embedding_dimension,
        "distance_metric": manifest.distance_metric,
        "semantic": manifest.embedding_provider != FAKE_PROVIDER_NAME,
        "top_k_requested": top_k_requested,
        "result_count": len(result.hits),
        "results": [hit.to_dict() for hit in result.hits],
        "freshness": {
            "fresh": freshness.fresh,
            "current_kb_sha256": freshness.current_kb_sha256,
            "checked_fields": list(freshness.checked_fields),
        },
    }


def _write_json(value: dict[str, object], *, stream) -> None:
    print(json.dumps(value, ensure_ascii=True, separators=(",", ":")), file=stream)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        configuration = resolve_provider_configuration(args)
        validate_search_inputs(args.query, args.top_k)
        index = load_local_index(args.index, mmap=True)
        freshness = check_index_freshness(index, args.current_kb, configuration.identity)
        provider = create_provider(configuration)
        result = search_loaded_index(index, args.query, provider, top_k=args.top_k)
    except CliConfigurationError as error:
        _write_json(
            {"error": str(error), "kind": "configuration_error", "provider": args.provider},
            stream=sys.stderr,
        )
        raise SystemExit(2) from None
    except IndexLoadError as error:
        _write_json(
            {"error": str(error), "kind": "index_load_error", "provider": args.provider},
            stream=sys.stderr,
        )
        raise SystemExit(2) from None
    except CurrentKbInputError as error:
        _write_json(
            {"error": str(error), "kind": "current_kb_error", "provider": args.provider},
            stream=sys.stderr,
        )
        raise SystemExit(2) from None
    except StaleIndexError as error:
        _write_json(
            {
                "error": "index is stale",
                "kind": "stale_index",
                "provider": args.provider,
                "mismatches": list(error.mismatches),
            },
            stream=sys.stderr,
        )
        raise SystemExit(2) from None
    except VectorSearchError as error:
        _write_json(
            {"error": str(error), "kind": "search_error", "provider": args.provider},
            stream=sys.stderr,
        )
        raise SystemExit(2) from None
    except EmbeddingError as error:
        _write_json(
            {"error": str(error), "kind": "embedding_error", "provider": args.provider},
            stream=sys.stderr,
        )
        raise SystemExit(2) from None

    _write_json(
        _success_summary(result, Path(args.index), args.top_k, freshness),
        stream=sys.stdout,
    )


if __name__ == "__main__":
    main()
