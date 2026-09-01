from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError, replace
from typing import Sequence

import numpy as np
import pytest

from jgrad_admission_rag.retrieval.embedding import EmbeddingIdentity
from jgrad_admission_rag.retrieval.hybrid_search import (
    CHANNEL_ORDER,
    DEFAULT_HYBRID_CANDIDATE_K,
    HYBRID_FUSION_VERSION,
    LEXICAL_CHANNEL_WEIGHT,
    RRF_K,
    VECTOR_CHANNEL_WEIGHT,
    HybridFusionError,
    HybridInputError,
    fuse_ranked_hits,
    resolve_candidate_depth,
    search_hybrid_index,
)
from jgrad_admission_rag.retrieval.lexical_search import LexicalSearchHit
from jgrad_admission_rag.retrieval.local_index import LocalVectorIndex
from jgrad_admission_rag.retrieval.vector_search import VectorSearchHit
from jgrad_admission_rag.schemas.index import IndexManifest, IndexPayload


class CountingProvider:
    identity = EmbeddingIdentity("deterministic-fake", "sha256-counter-v1", None, 2)

    def __init__(self) -> None:
        self.query_calls: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise AssertionError("hybrid search must not embed documents")

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return [1.0, 0.0]


def _payload(row: int, text: str | None = None) -> IndexPayload:
    return IndexPayload(
        row_index=row,
        document_id="sample-document",
        unit_id=f"unit:{row:05d}",
        fact_id=f"fact:{row:05d}",
        text=text or f"row {row} 出願資格",
        source_pages=[row + 1],
        section_path=["募集要項", f"section {row}"],
        fact_type="eligibility",
        scope_type="department" if row == 0 else "global",
        scope_targets=["情報工学系"] if row == 0 else [],
        parent_college="情報理工学院" if row == 0 else None,
        metadata={"nested": {"labels": [f"row-{row}"]}},
    )


def _index(count: int = 4) -> LocalVectorIndex:
    payloads = tuple(_payload(row) for row in range(count))
    vectors = np.zeros((count, 2), dtype="<f4")
    if count:
        vectors[:, 0] = 1.0
    vectors.setflags(write=False)
    return LocalVectorIndex(
        manifest=IndexManifest(
            source_kb_schema_version="0.5",
            document_id="sample-document",
            source_kb_sha256="a" * 64,
            source_pdf_sha256="b" * 64,
            payload_count=count,
            vector_count=count,
            embedding_dimension=2 if count else 0,
            vectors_normalized=True,
            embedding_provider="deterministic-fake",
            embedding_model="sha256-counter-v1",
            payloads_sha256="c" * 64,
            vectors_sha256="d" * 64,
        ),
        payloads=payloads,
        vectors=vectors,
    )


def _evidence(payload: IndexPayload) -> dict[str, object]:
    return {
        "row_index": payload.row_index,
        "document_id": payload.document_id,
        "unit_id": payload.unit_id,
        "fact_id": payload.fact_id,
        "text": payload.text,
        "source_pages": tuple(payload.source_pages),
        "section_path": tuple(payload.section_path),
        "fact_type": payload.fact_type,
        "scope_type": payload.scope_type,
        "scope_targets": tuple(payload.scope_targets),
        "parent_college": payload.parent_college,
        "metadata": payload.metadata,
    }


def _vector_hit(payload: IndexPayload, rank: int, score: float = 0.5) -> VectorSearchHit:
    return VectorSearchHit(rank=rank, score=score, **_evidence(payload))


def _lexical_hit(payload: IndexPayload, rank: int, score: float = 2.0) -> LexicalSearchHit:
    return LexicalSearchHit(rank=rank, score=score, matched_terms=("出願",), **_evidence(payload))


def test_rrf_constants_overlap_union_and_hand_calculated_scores() -> None:
    index = _index()
    vector_hits = (_vector_hit(index.payloads[0], 1), _vector_hit(index.payloads[1], 2))
    lexical_hits = (_lexical_hit(index.payloads[1], 1), _lexical_hit(index.payloads[2], 2))

    result = fuse_ranked_hits(index, vector_hits, lexical_hits, top_k=3, candidate_k=3)

    assert HYBRID_FUSION_VERSION == "rrf-v1"
    assert RRF_K == 60
    assert VECTOR_CHANNEL_WEIGHT == LEXICAL_CHANNEL_WEIGHT == 1.0
    assert CHANNEL_ORDER == ("vector", "lexical")
    assert [hit.row_index for hit in result.hits] == [1, 0, 2]
    assert [hit.fused_score for hit in result.hits] == pytest.approx(
        [1 / 62 + 1 / 61, 1 / 61, 1 / 62], rel=0.0, abs=1e-15
    )
    assert result.hits[0].matched_channels == ("vector", "lexical")
    assert result.hits[1].matched_channels == ("vector",)
    assert result.hits[2].matched_channels == ("lexical",)


def test_raw_score_rescaling_cannot_change_fused_order() -> None:
    index = _index()
    vector_hits = (_vector_hit(index.payloads[0], 1, 0.01), _vector_hit(index.payloads[1], 2, 0.99))
    lexical_hits = (_lexical_hit(index.payloads[1], 1, 1e-9),)
    first = fuse_ranked_hits(index, vector_hits, lexical_hits, top_k=2, candidate_k=2)
    rescaled = fuse_ranked_hits(
        index,
        (replace(vector_hits[0], score=-999.0), replace(vector_hits[1], score=1e30)),
        (replace(lexical_hits[0], score=1e200),),
        top_k=2,
        candidate_k=2,
    )

    assert [hit.row_index for hit in first.hits] == [hit.row_index for hit in rescaled.hits]
    assert [hit.fused_score for hit in first.hits] == [hit.fused_score for hit in rescaled.hits]


def test_exact_rrf_ties_use_row_index_and_top_k_applies_after_union() -> None:
    index = _index()
    result = fuse_ranked_hits(
        index,
        (_vector_hit(index.payloads[2], 1), _vector_hit(index.payloads[3], 2)),
        (_lexical_hit(index.payloads[0], 1), _lexical_hit(index.payloads[1], 2)),
        top_k=2,
        candidate_k=2,
    )

    assert result.vector_candidate_count == result.lexical_candidate_count == 2
    assert [hit.row_index for hit in result.hits] == [0, 2]
    assert len(result.hits) == 2


def test_candidate_depth_defaults_explicit_values_and_errors() -> None:
    assert DEFAULT_HYBRID_CANDIDATE_K == 50
    assert resolve_candidate_depth(5) == 50
    assert resolve_candidate_depth(80) == 80
    assert resolve_candidate_depth(5, 12) == 12
    for value in (0, -1, True, 1.5, "5"):
        with pytest.raises(HybridInputError, match="positive non-bool"):
            resolve_candidate_depth(value)  # type: ignore[arg-type]
        with pytest.raises(HybridInputError, match="positive non-bool"):
            resolve_candidate_depth(5, value)  # type: ignore[arg-type]
    with pytest.raises(HybridInputError, match="greater than or equal"):
        resolve_candidate_depth(5, 4)


def test_empty_valid_corpus_returns_no_hits() -> None:
    result = fuse_ranked_hits(_index(0), (), (), top_k=5)

    assert result.hits == ()
    assert result.candidate_k_requested is None
    assert result.candidate_k_resolved == 50
    assert result.vector_candidate_count == result.lexical_candidate_count == 0


@pytest.mark.parametrize(
    ("channel", "mutation", "message"),
    [
        ("vector", lambda hit: replace(hit, rank=2), "ranks must be contiguous"),
        ("lexical", lambda hit: replace(hit, rank=0), "ranks must be contiguous"),
        ("vector", lambda hit: replace(hit, score=math.inf), "non-finite"),
        ("lexical", lambda hit: replace(hit, score=math.nan), "non-finite"),
        ("vector", lambda hit: replace(hit, row_index=99), "outside the payload corpus"),
        ("lexical", lambda hit: replace(hit, text="wrong evidence"), "does not match"),
    ],
)
def test_malformed_channel_hits_fail_closed(channel, mutation, message) -> None:
    index = _index()
    vector_hits = (_vector_hit(index.payloads[0], 1),)
    lexical_hits = (_lexical_hit(index.payloads[0], 1),)
    if channel == "vector":
        vector_hits = (mutation(vector_hits[0]),)
    else:
        lexical_hits = (mutation(lexical_hits[0]),)

    with pytest.raises(HybridFusionError, match=message):
        fuse_ranked_hits(index, vector_hits, lexical_hits)


def test_duplicate_rows_wrong_types_and_excess_depth_fail_closed() -> None:
    index = _index()
    duplicate = (
        _vector_hit(index.payloads[0], 1),
        _vector_hit(index.payloads[0], 2),
    )
    with pytest.raises(HybridFusionError, match="duplicate row_index"):
        fuse_ranked_hits(index, duplicate, (), top_k=2, candidate_k=2)
    with pytest.raises(HybridFusionError, match="wrong hit type"):
        fuse_ranked_hits(index, (_lexical_hit(index.payloads[0], 1),), ())  # type: ignore[arg-type]
    with pytest.raises(HybridFusionError, match="exceeds candidate_k"):
        fuse_ranked_hits(index, duplicate, (), top_k=1, candidate_k=1)


def test_hybrid_hit_preserves_complete_immutable_detached_evidence() -> None:
    index = _index()
    result = fuse_ranked_hits(
        index,
        (_vector_hit(index.payloads[0], 1),),
        (_lexical_hit(index.payloads[0], 1),),
    )
    hit = result.hits[0]
    payload_before = index.payloads[0].model_dump(mode="json")
    serialized = hit.to_dict()
    result_serialized = result.to_dict()

    assert hit.fusion_version == "rrf-v1"
    assert hit.vector_rank == hit.lexical_rank == 1
    assert hit.vector_score == 0.5
    assert hit.lexical_score == 2.0
    assert serialized["text"] == index.payloads[0].text
    assert serialized["source_pages"] == index.payloads[0].source_pages
    assert serialized["section_path"] == index.payloads[0].section_path
    assert serialized["scope_targets"] == index.payloads[0].scope_targets
    serialized["metadata"]["nested"]["labels"].append("changed")  # type: ignore[index,union-attr]
    result_serialized["manifest"]["document_id"] = "changed"  # type: ignore[index]
    result_serialized["hits"][0]["metadata"]["nested"]["labels"].append("changed")  # type: ignore[index,union-attr]
    assert hit.to_dict()["metadata"] == {"nested": {"labels": ["row-0"]}}
    assert result.to_dict()["manifest"]["document_id"] == "sample-document"
    assert result.to_dict()["hits"][0]["metadata"] == {"nested": {"labels": ["row-0"]}}
    assert index.payloads[0].model_dump(mode="json") == payload_before
    with pytest.raises(FrozenInstanceError):
        hit.rank = 99  # type: ignore[misc]
    with pytest.raises(TypeError):
        hit.metadata["new"] = "value"  # type: ignore[index]


def test_repeated_and_equivalent_inputs_are_value_and_json_stable() -> None:
    first_index = _index()
    second_index = _index()
    first = fuse_ranked_hits(
        first_index,
        (_vector_hit(first_index.payloads[0], 1),),
        (_lexical_hit(first_index.payloads[1], 1),),
    )
    second = fuse_ranked_hits(
        second_index,
        (_vector_hit(second_index.payloads[0], 1),),
        (_lexical_hit(second_index.payloads[1], 1),),
    )

    assert first == second
    assert json.dumps([hit.to_dict() for hit in first.hits], sort_keys=True) == json.dumps(
        [hit.to_dict() for hit in second.hits], sort_keys=True
    )


def test_orchestration_embeds_query_once_and_does_not_mutate_index() -> None:
    index = _index(3)
    provider = CountingProvider()
    vectors_before = index.vectors.copy()
    payloads_before = [payload.model_dump(mode="json") for payload in index.payloads]

    result = search_hybrid_index(
        index,
        "情報工学系の出願資格",
        provider,
        top_k=2,
        candidate_k=3,
    )

    assert provider.query_calls == ["情報工学系の出願資格"]
    assert result.top_k_requested == 2
    assert result.candidate_k_requested == 3
    assert result.candidate_k_resolved == 3
    assert result.vector_candidate_count == 3
    assert 0 < result.lexical_candidate_count <= 3
    assert len(result.hits) == 2
    assert np.array_equal(index.vectors, vectors_before)
    assert [payload.model_dump(mode="json") for payload in index.payloads] == payloads_before
