from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from ..evaluation.retrieval_evaluation import (
    EvaluationBenchmarkError,
    EvaluationReportError,
    RetrievalEvaluationError,
    canonical_retrieval_evaluation_bytes,
    evaluate_retrieval,
    load_evaluation_benchmark,
)
from ..retrieval.embedding import EmbeddingError
from ..retrieval.evidence_pack import build_evidence_pack
from ..retrieval.hybrid_search import HybridInputError, resolve_candidate_depth
from ..retrieval.index_freshness import (
    CurrentKbInputError,
    StaleIndexError,
    load_fresh_index_context,
)
from ..retrieval.local_index import IndexLoadError, load_local_index
from ..retrieval.metadata_search import (
    MetadataFilter,
    MetadataInputError,
    MetadataSearchError,
    ScopePreference,
    search_metadata_index,
)
from ..retrieval.reference_expansion import ReferenceExpansionError, expand_references
from ..schemas.evidence_pack import EvidencePackError
from .provider_config import (
    CliConfigurationError,
    add_provider_arguments,
    create_provider,
    positive_int,
    resolve_provider_configuration,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate ranked primary retrieval against a validated benchmark."
    )
    parser.add_argument("index", help="Validated local index directory.")
    parser.add_argument("--current-kb", required=True, help="Current trusted document_kb.json.")
    parser.add_argument("--benchmark", required=True, help="Versioned retrieval benchmark JSON.")
    parser.add_argument("--retrieval-mode", choices=("hybrid",), default="hybrid")
    parser.add_argument("--top-k", type=positive_int, default=10)
    parser.add_argument("--candidate-k", type=positive_int, default=50)
    add_provider_arguments(parser)
    return parser


def _write_error(kind: str, message: str, provider: str) -> None:
    print(
        json.dumps(
            {"error": message, "kind": kind, "provider": provider},
            ensure_ascii=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        if args.allow_model_download:
            raise CliConfigurationError("retrieval evaluation never permits model downloads")
        if args.top_k < 10:
            raise CliConfigurationError("--top-k must be at least 10 for evaluation")
        try:
            resolve_candidate_depth(args.top_k, args.candidate_k)
        except HybridInputError as error:
            raise CliConfigurationError(str(error)) from error
        configuration = resolve_provider_configuration(args)
        index = load_local_index(args.index, mmap=True)
        context = load_fresh_index_context(index, args.current_kb, configuration.identity)
        benchmark = load_evaluation_benchmark(args.benchmark)
        provider = create_provider(configuration)
        packs = []
        for query in benchmark.queries:
            result = search_metadata_index(
                index,
                query.query,
                provider,
                metadata_filter=MetadataFilter(),
                scope_preference=ScopePreference(),
                top_k=args.top_k,
                candidate_k=args.candidate_k,
            )
            expansion = expand_references(index, context, result.hits)
            packs.append(build_evidence_pack(query.query, result, expansion))
        report = evaluate_retrieval(benchmark, context.knowledge_base, index, tuple(packs))
        output = canonical_retrieval_evaluation_bytes(report)
    except CliConfigurationError as error:
        _write_error("configuration_error", str(error), args.provider)
        raise SystemExit(2) from None
    except IndexLoadError as error:
        _write_error("index_load_error", str(error), args.provider)
        raise SystemExit(2) from None
    except CurrentKbInputError as error:
        _write_error("current_kb_error", str(error), args.provider)
        raise SystemExit(2) from None
    except StaleIndexError as error:
        _write_error("stale_index", "index is stale: " + ", ".join(error.mismatches), args.provider)
        raise SystemExit(2) from None
    except EvaluationBenchmarkError as error:
        _write_error("benchmark_error", str(error), args.provider)
        raise SystemExit(2) from None
    except MetadataInputError as error:
        _write_error("configuration_error", str(error), args.provider)
        raise SystemExit(2) from None
    except MetadataSearchError as error:
        _write_error("search_error", str(error), args.provider)
        raise SystemExit(2) from None
    except ReferenceExpansionError as error:
        _write_error("reference_expansion_error", str(error), args.provider)
        raise SystemExit(2) from None
    except EvidencePackError as error:
        _write_error("evidence_pack_error", str(error), args.provider)
        raise SystemExit(2) from None
    except EvaluationReportError as error:
        _write_error("report_error", str(error), args.provider)
        raise SystemExit(2) from None
    except RetrievalEvaluationError as error:
        _write_error("evaluation_error", str(error), args.provider)
        raise SystemExit(2) from None
    except EmbeddingError as error:
        _write_error("embedding_error", str(error), args.provider)
        raise SystemExit(2) from None

    sys.stdout.write(output.decode("utf-8"))


if __name__ == "__main__":
    main()
