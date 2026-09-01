from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from typing import Sequence

import numpy as np
import pytest

from jgrad_admission_rag.retrieval.embedding import EmbeddingIdentity
from jgrad_admission_rag.retrieval.eligible_rows import EligibleRowsError, validate_eligible_rows
from jgrad_admission_rag.retrieval.hybrid_search import HybridSearchHit, search_hybrid_index
from jgrad_admission_rag.retrieval.lexical_search import build_lexical_searcher
from jgrad_admission_rag.retrieval.local_index import LocalVectorIndex
from jgrad_admission_rag.retrieval.metadata_search import (
    METADATA_FILTER_VERSION,
    PARENT_COLLEGE_MATCH_BOOST,
    PREFERENCE_ORDER,
    SCOPE_RERANK_VERSION,
    SCOPE_TARGET_MATCH_BOOST,
    MetadataFilter,
    MetadataInputError,
    ScopePreference,
    derive_eligible_rows,
    rerank_hybrid_hits,
    search_metadata_index,
)
from jgrad_admission_rag.retrieval.vector_search import search_loaded_index
from jgrad_admission_rag.schemas.index import IndexManifest, IndexPayload


class StaticProvider:
    identity = EmbeddingIdentity("static", "metadata-axes", "r1", 2)

    def __init__(self) -> None:
        self.query_calls: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise AssertionError("search must not embed documents")

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return [1.0, 0.0]


def _payload(
    row: int,
    *,
    fact_type: str,
    scope_type: str,
    targets: list[str] | None = None,
    college: str | None = None,
) -> IndexPayload:
    return IndexPayload(
        row_index=row,
        document_id="doc",
        unit_id=f"unit:{row}",
        fact_id=f"fact:{row}",
        text=f"共通検索語 row {row}",
        source_pages=[row + 1],
        section_path=["募集要項", str(row)],
        fact_type=fact_type,
        scope_type=scope_type,
        scope_targets=targets or [],
        parent_college=college,
        metadata={"nested": {"row": row}},
    )


def _index() -> LocalVectorIndex:
    payloads = (
        _payload(0, fact_type="fees", scope_type="global"),
        _payload(
            1,
            fact_type="eligibility",
            scope_type="department",
            targets=["情報工学系", "数理・計算科学系"],
            college="情報理工学院",
        ),
        _payload(
            2,
            fact_type="eligibility",
            scope_type="department",
            targets=["機械系"],
            college="工学院",
        ),
        _payload(3, fact_type="documents", scope_type="unknown"),
    )
    vectors = np.asarray([[1.0, 0.0], [0.8, 0.6], [0.6, 0.8], [0.0, 1.0]], dtype="<f4")
    vectors.setflags(write=False)
    return LocalVectorIndex(
        manifest=IndexManifest(
            source_kb_schema_version="0.5",
            document_id="doc",
            source_kb_sha256="a" * 64,
            source_pdf_sha256="b" * 64,
            payload_count=4,
            vector_count=4,
            embedding_dimension=2,
            vectors_normalized=True,
            embedding_provider="static",
            embedding_model="metadata-axes",
            embedding_revision="r1",
            payloads_sha256="c" * 64,
            vectors_sha256="d" * 64,
        ),
        payloads=payloads,
        vectors=vectors,
    )


def _hybrid_hit(
    payload: IndexPayload,
    *,
    rank: int,
    fused_score: float,
) -> HybridSearchHit:
    return HybridSearchHit(
        rank=rank,
        row_index=payload.row_index,
        fused_score=fused_score,
        fusion_version="rrf-v1",
        vector_rank=rank,
        vector_score=0.5,
        lexical_rank=None,
        lexical_score=None,
        matched_channels=("vector",),
        document_id=payload.document_id,
        unit_id=payload.unit_id,
        fact_id=payload.fact_id,
        text=payload.text,
        source_pages=tuple(payload.source_pages),
        section_path=tuple(payload.section_path),
        fact_type=payload.fact_type,
        scope_type=payload.scope_type,
        scope_targets=tuple(payload.scope_targets),
        parent_college=payload.parent_college,
        metadata=payload.metadata,
    )


def test_exact_filter_truth_table_or_within_and_across_and_target_intersection() -> None:
    index = _index()

    assert derive_eligible_rows(index.payloads, MetadataFilter()) == (0, 1, 2, 3)
    assert derive_eligible_rows(
        index.payloads,
        MetadataFilter(fact_types=("fees", "documents")),
    ) == (0, 3)
    assert derive_eligible_rows(
        index.payloads,
        MetadataFilter(
            fact_types=("eligibility",),
            scope_types=("department",),
            scope_targets=("数理・計算科学系", "機械系"),
            parent_colleges=("情報理工学院",),
        ),
    ) == (1,)
    assert derive_eligible_rows(
        index.payloads,
        MetadataFilter(scope_targets=("情報工学系",)),
    ) == (1,)
    assert (
        derive_eligible_rows(
            index.payloads,
            MetadataFilter(parent_colleges=("存在しない学院",)),
        )
        == ()
    )


def test_filter_values_are_exact_sorted_immutable_and_fail_on_bad_inputs() -> None:
    value = MetadataFilter(fact_types=("fees", "eligibility"), scope_types=("unknown", "global"))
    assert value.fact_types == ("eligibility", "fees")
    assert value.scope_types == ("global", "unknown")
    assert value.to_dict() == {
        "fact_types": ["eligibility", "fees"],
        "scope_types": ["global", "unknown"],
        "scope_targets": [],
        "parent_colleges": [],
    }
    with pytest.raises(FrozenInstanceError):
        value.fact_types = ()  # type: ignore[misc]
    with pytest.raises(MetadataInputError, match="duplicate-free"):
        MetadataFilter(fact_types=("fees", "fees"))
    with pytest.raises(MetadataInputError, match="non-blank trimmed"):
        MetadataFilter(scope_targets=(" 情報工学系",))
    with pytest.raises(MetadataInputError, match="unsupported controlled"):
        MetadataFilter(scope_types=("course",))  # type: ignore[arg-type]
    with pytest.raises(MetadataInputError, match="finite collection"):
        ScopePreference(preferred_scope_targets="情報工学系")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "rows",
    ([0, 0], [True], [1.5], [-1], [4], "0"),
)
def test_malformed_eligible_rows_fail_closed_in_validator_and_channels(rows) -> None:
    index = _index()
    with pytest.raises(EligibleRowsError):
        validate_eligible_rows(4, rows)
    with pytest.raises(EligibleRowsError):
        search_loaded_index(index, "検索語", StaticProvider(), top_k=2, eligible_rows=rows)
    searcher = build_lexical_searcher(index)
    with pytest.raises(EligibleRowsError):
        searcher.search("検索語", top_k=2, eligible_rows=rows)


def test_hard_filter_applies_before_each_channel_candidate_truncation() -> None:
    index = _index()
    provider = StaticProvider()
    eligible = derive_eligible_rows(index.payloads, MetadataFilter(fact_types=("documents",)))

    vector = search_loaded_index(index, "共通検索語", provider, top_k=1, eligible_rows=eligible)
    lexical = build_lexical_searcher(index).search("共通検索語", top_k=1, eligible_rows=eligible)
    metadata = search_metadata_index(
        index,
        "共通検索語",
        provider,
        metadata_filter=MetadataFilter(fact_types=("documents",)),
        top_k=1,
        candidate_k=1,
    )

    assert [hit.row_index for hit in vector.hits] == [3]
    assert [hit.row_index for hit in lexical.hits] == [3]
    assert [hit.row_index for hit in metadata.hits] == [3]
    assert metadata.eligible_row_count == 1


def test_valid_zero_match_filter_returns_empty_deterministic_result() -> None:
    provider = StaticProvider()
    result = search_metadata_index(
        _index(),
        "検索語",
        provider,
        metadata_filter=MetadataFilter(fact_types=("not-present",)),
    )

    assert result.corpus_row_count == 4
    assert result.eligible_row_count == 0
    assert result.vector_candidate_count == result.lexical_candidate_count == 0
    assert result.hits == ()
    assert provider.query_calls == ["検索語"]

    with pytest.raises(MetadataInputError, match="must be a MetadataFilter"):
        search_metadata_index(_index(), "検索語", provider, metadata_filter=False)  # type: ignore[arg-type]
    with pytest.raises(MetadataInputError, match="must be a ScopePreference"):
        search_metadata_index(_index(), "検索語", provider, scope_preference=False)  # type: ignore[arg-type]


def test_scope_boost_constants_accumulate_once_and_preserve_base_scores() -> None:
    index = _index()
    base = (
        _hybrid_hit(index.payloads[0], rank=1, fused_score=0.030),
        _hybrid_hit(index.payloads[1], rank=2, fused_score=0.020),
        _hybrid_hit(index.payloads[2], rank=3, fused_score=0.018),
    )
    preference = ScopePreference(
        preferred_scope_targets=("情報工学系", "数理・計算科学系", "機械系"),
        preferred_parent_colleges=("情報理工学院", "工学院"),
    )

    result = rerank_hybrid_hits(base, preference, top_k=3)

    assert METADATA_FILTER_VERSION == "exact-metadata-v1"
    assert SCOPE_RERANK_VERSION == "scope-match-v1"
    assert SCOPE_TARGET_MATCH_BOOST == 1 / 61
    assert PARENT_COLLEGE_MATCH_BOOST == 0.5 / 61
    assert PREFERENCE_ORDER == ("scope_target", "parent_college")
    assert [hit.row_index for hit in result] == [1, 2, 0]
    assert result[0].matched_scope_targets == ("情報工学系", "数理・計算科学系")
    assert result[0].matched_preferences == ("scope_target", "parent_college")
    assert result[0].scope_boost_total == pytest.approx(1.5 / 61)
    assert result[0].ranking_score == pytest.approx(0.020 + 1.5 / 61)
    assert result[0].fused_score == 0.020
    assert result[0].vector_score == base[1].vector_score
    assert result[2].scope_boost_total == 0.0
    assert result[2].ranking_score == result[2].fused_score == 0.030


def test_no_preference_preserves_order_scores_and_candidates() -> None:
    index = _index()
    base = tuple(
        _hybrid_hit(payload, rank=rank, fused_score=0.04 - rank * 0.001)
        for rank, payload in enumerate(index.payloads, start=1)
    )

    result = rerank_hybrid_hits(base, ScopePreference(), top_k=4)

    assert [hit.row_index for hit in result] == [hit.row_index for hit in base]
    assert [hit.ranking_score for hit in result] == [hit.fused_score for hit in base]
    assert all(hit.scope_boost_total == 0.0 for hit in result)
    assert all(hit.matched_preferences == () for hit in result)


def test_no_filter_metadata_path_matches_ret03_hybrid_values() -> None:
    index = _index()
    provider = StaticProvider()
    base = search_hybrid_index(index, "共通検索語", provider, top_k=4, candidate_k=4)
    metadata = search_metadata_index(index, "共通検索語", provider, top_k=4, candidate_k=4)

    assert [hit.row_index for hit in metadata.hits] == [hit.row_index for hit in base.hits]
    assert [hit.fused_score for hit in metadata.hits] == [hit.fused_score for hit in base.hits]
    assert [hit.ranking_score for hit in metadata.hits] == [hit.fused_score for hit in base.hits]
    assert [hit.vector_score for hit in metadata.hits] == [hit.vector_score for hit in base.hits]
    assert [hit.lexical_score for hit in metadata.hits] == [hit.lexical_score for hit in base.hits]


def test_metadata_result_and_to_dict_are_detached_and_stable() -> None:
    index = _index()
    payloads_before = [payload.model_dump(mode="json") for payload in index.payloads]
    result = search_metadata_index(
        index,
        "共通検索語",
        StaticProvider(),
        metadata_filter=MetadataFilter(scope_types=("department",)),
        scope_preference=ScopePreference(preferred_scope_targets=("情報工学系",)),
        top_k=2,
        candidate_k=2,
    )
    first = result.to_dict()
    second = result.to_dict()

    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second, ensure_ascii=False, sort_keys=True
    )
    first["requested_filter"]["scope_types"].append("changed")  # type: ignore[index,union-attr]
    first["hits"][0]["metadata"]["nested"]["row"] = 999  # type: ignore[index,union-attr]
    assert result.to_dict() == second
    assert [payload.model_dump(mode="json") for payload in index.payloads] == payloads_before
    assert all(hit.scope_type == "department" for hit in result.hits)
