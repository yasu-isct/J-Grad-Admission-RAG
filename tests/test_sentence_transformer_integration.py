from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path

import pytest

from jgrad_admission_rag.builder.kb_builder import build_document_kb
from jgrad_admission_rag.cli import evaluate_retrieval as evaluate_retrieval_cli
from jgrad_admission_rag.evaluation.retrieval_evaluation import (
    load_retrieval_evaluation_bytes,
)
from jgrad_admission_rag.schemas.document_identity import load_document_identity
from jgrad_admission_rag.retrieval.embedding import embed_documents_checked, embed_query_checked
from jgrad_admission_rag.retrieval.sentence_transformer import (
    SentenceTransformerConfig,
    SentenceTransformerEmbeddingProvider,
)

pytestmark = pytest.mark.model_integration

BGE_M3_MODEL = "BAAI/bge-m3"
BGE_M3_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"


def test_explicit_sentence_transformer_model_against_real_projection() -> None:
    model_name = os.getenv("JGRAD_ST_MODEL")
    revision = os.getenv("JGRAD_ST_REVISION")
    pdf_path = os.getenv("JGRAD_REAL_PDF")
    if not model_name or not revision or not pdf_path:
        pytest.skip("set JGRAD_ST_MODEL, JGRAD_ST_REVISION, and JGRAD_REAL_PDF explicitly")

    allow_download = os.getenv("JGRAD_ALLOW_MODEL_DOWNLOAD") == "1"
    expected_dimension = int(os.getenv("JGRAD_ST_DIMENSION", "1024"))
    provider = SentenceTransformerEmbeddingProvider(
        SentenceTransformerConfig(
            model_name=model_name,
            revision=revision,
            expected_dimension=expected_dimension,
            allow_download=allow_download,
            cache_folder=os.getenv("JGRAD_ST_CACHE"),
        )
    )
    identity = load_document_identity(
        Path(__file__).resolve().parents[1]
        / "src/jgrad_admission_rag/demo_config/document_identity.json"
    )
    kb = build_document_kb(Path(pdf_path), identity)
    texts = [unit.text for unit in kb.retrieval_units]
    token_counts = provider._token_counts(texts, operation="documents")
    assert provider._max_seq_length is not None
    over_limit_ids = [
        unit.unit_id
        for unit, token_count in zip(kb.retrieval_units, token_counts, strict=True)
        if token_count > provider._max_seq_length
    ]
    assert over_limit_ids == []
    vectors = embed_documents_checked(provider, texts)

    assert len(vectors) == len(texts) == 391
    assert all(len(vector) == expected_dimension for vector in vectors)
    assert all(all(math.isfinite(value) for value in vector) for vector in vectors)
    assert all(any(value != 0.0 for value in vector) for vector in vectors)
    assert max(token_counts) <= provider._max_seq_length

    queries = ["情報工学系の英語試験要件", "検定料はいくらですか"]
    query_vectors = [embed_query_checked(provider, query) for query in queries]

    def cosine(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        return dot / (left_norm * right_norm)

    similarities = [
        cosine(query_vector, vectors[index]) for index, query_vector in enumerate(query_vectors)
    ]
    fingerprint = hashlib.sha256(
        json.dumps(vectors, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    assert all(len(query_vector) == expected_dimension for query_vector in query_vectors)
    sorted_counts = sorted(token_counts)
    p95 = sorted_counts[math.ceil(0.95 * len(sorted_counts)) - 1]
    print(
        {
            "identity": provider.identity,
            "sentence_transformers_version": importlib.metadata.version("sentence-transformers"),
            "device": provider.config.device,
            "max_seq_length": provider._max_seq_length,
            "token_count_min": min(token_counts),
            "token_count_median": sorted_counts[len(sorted_counts) // 2],
            "token_count_p95": p95,
            "token_count_max": max(token_counts),
            "over_limit_ids": over_limit_ids,
            "embedding_shape": [len(vectors), len(vectors[0])],
            "vector_fingerprint": fingerprint,
            "smoke_similarities": similarities,
            "allow_download": allow_download,
        }
    )


def test_pinned_bge_m3_cross_language_benchmark_is_cache_only_and_repeatable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cache = os.getenv("JGRAD_BGE_M3_CACHE")
    index = os.getenv("JGRAD_BGE_M3_INDEX")
    kb = os.getenv("JGRAD_BGE_M3_KB")
    if not cache or not index or not kb:
        pytest.skip("set JGRAD_BGE_M3_CACHE, JGRAD_BGE_M3_INDEX, and JGRAD_BGE_M3_KB explicitly")

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    benchmark = Path(__file__).parent / "fixtures" / "retrieval_queries_v1.json"
    args = [
        index,
        "--current-kb",
        kb,
        "--benchmark",
        str(benchmark),
        "--provider",
        "sentence-transformers",
        "--model",
        BGE_M3_MODEL,
        "--revision",
        BGE_M3_REVISION,
        "--dimension",
        "1024",
        "--batch-size",
        "8",
        "--cache-folder",
        cache,
    ]

    outputs: list[bytes] = []
    for _ in range(3):
        evaluate_retrieval_cli.main(args)
        captured = capsys.readouterr()
        assert "download" not in captured.err.casefold()
        outputs.append(captured.out.encode("utf-8"))

    assert outputs[0] == outputs[1] == outputs[2]
    report = load_retrieval_evaluation_bytes(outputs[0])
    assert report.runtime.embedding_model == BGE_M3_MODEL
    assert report.runtime.embedding_revision == BGE_M3_REVISION
    assert report.runtime.semantic is True
    assert report.benchmark.ordered_query_count == 38
    language_summaries = {
        breakdown.group: breakdown.summary
        for breakdown in report.aggregates.breakdowns
        if breakdown.dimension == "query_language"
    }
    assert language_summaries["ja"].query_count == 34
    assert language_summaries["zh"].query_count == 4
