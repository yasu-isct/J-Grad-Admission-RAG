from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from ..retrieval.embedding import EmbeddingError
from ..retrieval.evidence_pack import build_evidence_pack
from ..retrieval.index_freshness import (
    CurrentKbInputError,
    IndexFreshnessReport,
    StaleIndexError,
    check_index_freshness,
    load_fresh_index_context,
)
from ..retrieval.reference_expansion import ReferenceExpansionError, expand_references
from ..retrieval.hybrid_search import (
    HybridInputError,
    HybridSearchError,
    HybridSearchResult,
    resolve_candidate_depth,
    search_hybrid_index,
)
from ..retrieval.local_index import IndexLoadError, load_local_index
from ..retrieval.metadata_search import (
    MetadataFilter,
    MetadataInputError,
    MetadataSearchError,
    MetadataSearchResult,
    ScopePreference,
    search_metadata_index,
)
from ..retrieval.vector_search import (
    VectorSearchError,
    VectorSearchResult,
    search_loaded_index,
    validate_search_inputs,
)
from ..schemas.evidence_pack import EvidencePackError, canonical_evidence_pack_bytes
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
    parser.add_argument("--retrieval-mode", choices=("vector", "hybrid"), default="vector")
    parser.add_argument("--output-format", choices=("search", "evidence-pack"), default="search")
    parser.add_argument("--expand-references", action="store_true")
    parser.add_argument("--candidate-k", type=positive_int)
    parser.add_argument("--filter-fact-type", action="append")
    parser.add_argument("--filter-scope-type", action="append")
    parser.add_argument("--filter-scope-target", action="append")
    parser.add_argument("--filter-parent-college", action="append")
    parser.add_argument("--prefer-scope-target", action="append")
    parser.add_argument("--prefer-parent-college", action="append")
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


def _hybrid_success_summary(
    result: HybridSearchResult,
    index: Path,
    freshness: IndexFreshnessReport,
) -> dict[str, object]:
    manifest = result.manifest
    return {
        "index": str(index),
        "retrieval_mode": "hybrid",
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
        "fusion_version": result.fusion_version,
        "rrf_k": result.rrf_k,
        "top_k_requested": result.top_k_requested,
        "candidate_k_requested": result.candidate_k_requested,
        "candidate_k_resolved": result.candidate_k_resolved,
        "vector_candidate_count": result.vector_candidate_count,
        "lexical_candidate_count": result.lexical_candidate_count,
        "result_count": len(result.hits),
        "results": [hit.to_dict() for hit in result.hits],
        "freshness": {
            "fresh": freshness.fresh,
            "current_kb_sha256": freshness.current_kb_sha256,
            "checked_fields": list(freshness.checked_fields),
        },
    }


def _metadata_success_summary(
    result: MetadataSearchResult,
    index: Path,
    freshness: IndexFreshnessReport,
) -> dict[str, object]:
    manifest = result.manifest
    diagnostics = result.to_dict()
    diagnostics.pop("manifest")
    hits = diagnostics.pop("hits")
    return {
        "index": str(index),
        "retrieval_mode": "hybrid",
        "metadata_aware": True,
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
        **diagnostics,
        "results": hits,
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
        metadata_requested = any(
            getattr(args, name) is not None
            for name in (
                "filter_fact_type",
                "filter_scope_type",
                "filter_scope_target",
                "filter_parent_college",
                "prefer_scope_target",
                "prefer_parent_college",
            )
        )
        if args.retrieval_mode == "vector" and args.candidate_k is not None:
            raise CliConfigurationError("--candidate-k requires --retrieval-mode hybrid")
        if args.retrieval_mode == "vector" and metadata_requested:
            raise CliConfigurationError("metadata options require --retrieval-mode hybrid")
        if args.retrieval_mode == "vector" and args.expand_references:
            raise CliConfigurationError("--expand-references requires --retrieval-mode hybrid")
        if args.output_format == "evidence-pack" and args.retrieval_mode != "hybrid":
            raise CliConfigurationError("evidence-pack output requires --retrieval-mode hybrid")
        if args.output_format == "evidence-pack" and args.expand_references:
            raise CliConfigurationError("evidence-pack output already includes reference expansion")
        metadata_filter = None
        scope_preference = None
        if args.retrieval_mode == "hybrid":
            try:
                resolve_candidate_depth(args.top_k, args.candidate_k)
                if metadata_requested:
                    metadata_filter = MetadataFilter(
                        fact_types=tuple(args.filter_fact_type or ()),
                        scope_types=tuple(args.filter_scope_type or ()),
                        scope_targets=tuple(args.filter_scope_target or ()),
                        parent_colleges=tuple(args.filter_parent_college or ()),
                    )
                    scope_preference = ScopePreference(
                        preferred_scope_targets=tuple(args.prefer_scope_target or ()),
                        preferred_parent_colleges=tuple(args.prefer_parent_college or ()),
                    )
            except (HybridInputError, MetadataInputError) as error:
                raise CliConfigurationError(str(error)) from error
        index = load_local_index(args.index, mmap=True)
        fresh_context = None
        if args.expand_references or args.output_format == "evidence-pack":
            fresh_context = load_fresh_index_context(index, args.current_kb, configuration.identity)
            freshness = fresh_context.freshness
        else:
            freshness = check_index_freshness(index, args.current_kb, configuration.identity)
        provider = create_provider(configuration)
        if args.retrieval_mode == "vector":
            result = search_loaded_index(index, args.query, provider, top_k=args.top_k)
        elif not metadata_requested and args.output_format == "search":
            result = search_hybrid_index(
                index,
                args.query,
                provider,
                top_k=args.top_k,
                candidate_k=args.candidate_k,
            )
        else:
            result = search_metadata_index(
                index,
                args.query,
                provider,
                metadata_filter=metadata_filter,
                scope_preference=scope_preference,
                top_k=args.top_k,
                candidate_k=args.candidate_k,
            )
        reference_expansion = None
        if args.expand_references or args.output_format == "evidence-pack":
            assert fresh_context is not None
            reference_expansion = expand_references(index, fresh_context, result.hits)
        evidence_pack_bytes = None
        if args.output_format == "evidence-pack":
            assert reference_expansion is not None
            evidence_pack_bytes = canonical_evidence_pack_bytes(
                build_evidence_pack(args.query, result, reference_expansion)
            )
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
    except HybridSearchError as error:
        _write_json(
            {"error": str(error), "kind": "fusion_error", "provider": args.provider},
            stream=sys.stderr,
        )
        raise SystemExit(2) from None
    except MetadataSearchError as error:
        _write_json(
            {"error": str(error), "kind": "metadata_search_error", "provider": args.provider},
            stream=sys.stderr,
        )
        raise SystemExit(2) from None
    except ReferenceExpansionError as error:
        _write_json(
            {"error": str(error), "kind": "reference_expansion_error", "provider": args.provider},
            stream=sys.stderr,
        )
        raise SystemExit(2) from None
    except EvidencePackError as error:
        _write_json(
            {"error": str(error), "kind": "evidence_pack_error", "provider": args.provider},
            stream=sys.stderr,
        )
        raise SystemExit(2) from None
    except EmbeddingError as error:
        _write_json(
            {"error": str(error), "kind": "embedding_error", "provider": args.provider},
            stream=sys.stderr,
        )
        raise SystemExit(2) from None

    if evidence_pack_bytes is not None:
        sys.stdout.write(evidence_pack_bytes.decode("utf-8"))
        return
    if args.retrieval_mode == "vector":
        summary = _success_summary(result, Path(args.index), args.top_k, freshness)
    elif not metadata_requested:
        summary = _hybrid_success_summary(result, Path(args.index), freshness)
    else:
        summary = _metadata_success_summary(result, Path(args.index), freshness)
    if reference_expansion is not None:
        summary["reference_expansion"] = reference_expansion.to_dict()
    _write_json(summary, stream=sys.stdout)


if __name__ == "__main__":
    main()
