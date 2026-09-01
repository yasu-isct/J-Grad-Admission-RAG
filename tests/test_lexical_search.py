from __future__ import annotations

import json
import math
from dataclasses import replace
from types import MappingProxyType

import numpy as np
import pytest

from jgrad_admission_rag.retrieval.lexical_search import (
    BM25_B,
    BM25_K1,
    JAPANESE_NGRAM_LENGTHS,
    LEXICAL_SCORING_VERSION,
    LEXICAL_TOKENIZER_VERSION,
    LexicalCorpusError,
    LexicalInputError,
    LexicalScoreError,
    _bm25_term_score,
    build_lexical_projection,
    build_lexical_searcher,
    search_lexical,
    tokenize_lexical,
)
from jgrad_admission_rag.retrieval.local_index import LocalVectorIndex
from jgrad_admission_rag.schemas.index import IndexManifest, IndexPayload

HASH = "a" * 64


def _payload(row: int, text: str, **changes) -> IndexPayload:
    values = {
        "row_index": row,
        "document_id": "sample-document",
        "unit_id": f"unit:{row:05d}",
        "fact_id": f"fact:{row:05d}",
        "text": text,
        "source_pages": [row + 1],
        "section_path": ["募集要項", "出願手続"],
        "fact_type": "documents",
        "scope_type": "department",
        "scope_targets": ["情報工学系"],
        "parent_college": "情報理工学院",
        "metadata": {"nested": {"items": [row]}},
    }
    values.update(changes)
    return IndexPayload(**values)


def _manifest(count: int) -> IndexManifest:
    return IndexManifest(
        source_kb_schema_version="0.5",
        document_id="sample-document",
        source_kb_sha256=HASH,
        source_pdf_sha256="b" * 64,
        payload_count=count,
        vector_count=count,
        embedding_dimension=2 if count else 0,
        vectors_normalized=True,
        embedding_provider="test",
        embedding_model="test-model",
        payloads_sha256="c" * 64,
        vectors_sha256="d" * 64,
    )


def test_tokenizer_version_constants_and_frozen_examples() -> None:
    assert LEXICAL_TOKENIZER_VERSION == "nfkc-casefold-ja23-v1"
    assert JAPANESE_NGRAM_LENGTHS == (2, 3)
    assert tokenize_lexical("情報工学系") == (
        "情報",
        "情報工",
        "報工",
        "報工学",
        "工学",
        "工学系",
        "学系",
    )
    assert tokenize_lexical("TOEFL-PBT / TOEFL PBT") == (
        "toefl",
        "pbt",
        "toefl",
        "pbt",
        "toeflpbt",
    )
    assert tokenize_lexical("TOEIC L&R") == ("toeic", "l", "r", "lr")
    assert tokenize_lexical("30,000円") == ("30000",)
    assert tokenize_lexical("2026年9月28日") == ("2026", "9", "28")
    assert tokenize_lexical("出願資格（9）") == (
        "出願",
        "出願資",
        "願資",
        "願資格",
        "資格",
        "9",
    )
    assert tokenize_lexical("...！？") == ()


def test_tokenizer_nfkc_connector_variants_and_multiplicity_are_deterministic() -> None:
    assert tokenize_lexical("ＴＯＥＦＬ－ＰＢＴ") == ("toefl", "pbt", "toeflpbt")
    assert {"toefl", "pbt"}.issubset(tokenize_lexical("TOEFL PBT"))
    assert tokenize_lexical("材料 材料") == ("材料", "材料")
    assert tokenize_lexical("30,000 30000") == ("30000", "30000")
    with pytest.raises(TypeError, match="Python string"):
        tokenize_lexical(123)  # type: ignore[arg-type]


def test_projection_includes_canonical_text_and_explicit_structured_fields() -> None:
    payload = _payload(0, "本文には対象語がない")

    projection = build_lexical_projection(payload)

    assert projection.startswith(payload.text)
    for value in (
        payload.document_id,
        payload.unit_id,
        payload.fact_id,
        *payload.section_path,
        payload.fact_type,
        payload.scope_type,
        *payload.scope_targets,
        payload.parent_college,
    ):
        assert value in projection
    with pytest.raises(TypeError, match="IndexPayload"):
        build_lexical_projection(object())  # type: ignore[arg-type]


def test_searchable_structured_scope_can_produce_a_candidate() -> None:
    searcher = build_lexical_searcher([_payload(0, "本文には対象語がない")])

    result = searcher.search("情報工学系", top_k=5)

    assert [hit.fact_id for hit in result.hits] == ["fact:00000"]
    assert "情報" in result.hits[0].matched_terms


def test_corpus_statistics_freeze_term_multiplicity_document_frequency_and_length() -> None:
    searcher = build_lexical_searcher(
        [_payload(0, "alpha alpha"), _payload(1, "alpha beta"), _payload(2, "gamma")]
    )

    assert searcher.corpus_size == 3
    assert searcher.term_frequencies[0]["alpha"] == 2
    assert searcher.document_frequency["alpha"] == 2
    assert searcher.document_frequency["gamma"] == 1
    assert searcher.document_lengths == tuple(
        sum(frequencies.values()) for frequencies in searcher.term_frequencies
    )
    assert searcher.average_document_length == pytest.approx(
        math.fsum(searcher.document_lengths) / 3
    )


def test_bm25_constants_and_positive_idf_formula_are_frozen() -> None:
    assert LEXICAL_SCORING_VERSION == "bm25-v1"
    assert BM25_K1 == 1.2
    assert BM25_B == 0.75

    score = _bm25_term_score(
        term_frequency=2,
        document_frequency=1,
        document_length=4,
        average_document_length=3.0,
        corpus_size=3,
    )
    idf = math.log1p((3 - 1 + 0.5) / (1 + 0.5))
    expected = idf * (2 * (BM25_K1 + 1.0)) / (2 + BM25_K1 * (1.0 - BM25_B + BM25_B * (4 / 3.0)))
    assert score == pytest.approx(expected)
    assert score > 0.0


def test_higher_term_frequency_in_same_length_document_scores_higher() -> None:
    searcher = build_lexical_searcher(
        [_payload(0, "alpha alpha filler"), _payload(1, "alpha filler filler")]
    )

    result = searcher.search("alpha", top_k=2)

    assert [hit.row_index for hit in result.hits] == [0, 1]
    assert result.hits[0].score > result.hits[1].score


def test_rarer_term_has_higher_idf_and_shorter_document_is_favored() -> None:
    rarity = build_lexical_searcher(
        [_payload(0, "common"), _payload(1, "common"), _payload(2, "rare")]
    ).search("common rare", top_k=3)
    assert rarity.hits[0].row_index == 2

    length = build_lexical_searcher(
        [
            _payload(0, "alpha"),
            _payload(1, "alpha " + " ".join(f"filler{index}" for index in range(20))),
        ]
    ).search("alpha", top_k=2)
    assert [hit.row_index for hit in length.hits] == [0, 1]
    assert length.hits[0].score > length.hits[1].score


def test_query_term_multiplicity_scales_score_deterministically() -> None:
    searcher = build_lexical_searcher([_payload(0, "alpha")])

    single = searcher.search("alpha").hits[0].score
    repeated = searcher.search("alpha alpha").hits[0].score

    assert repeated == pytest.approx(2 * single)


def test_exact_score_ties_use_row_index_and_zero_scores_are_excluded() -> None:
    searcher = build_lexical_searcher(
        [_payload(0, "alpha"), _payload(1, "alpha"), _payload(2, "unrelated")]
    )

    result = searcher.search("alpha", top_k=10)

    assert [hit.row_index for hit in result.hits] == [0, 1]
    assert result.hits[0].score == result.hits[1].score
    assert all(hit.score > 0 for hit in result.hits)


def test_top_k_limits_positive_matches_and_large_top_k_returns_all_matches() -> None:
    searcher = build_lexical_searcher(
        [_payload(0, "alpha"), _payload(1, "alpha beta"), _payload(2, "alpha gamma")]
    )

    assert len(searcher.search("alpha", top_k=1).hits) == 1
    assert len(searcher.search("alpha", top_k=99).hits) == 3


@pytest.mark.parametrize("query", ["", "   ", "...！？"])
def test_blank_or_tokenless_query_uses_typed_input_error(query: str) -> None:
    searcher = build_lexical_searcher([_payload(0, "alpha")])

    with pytest.raises(LexicalInputError):
        searcher.search(query)


@pytest.mark.parametrize("top_k", [0, -1, True, 1.5, "5"])
def test_invalid_top_k_uses_typed_input_error(top_k) -> None:
    searcher = build_lexical_searcher([_payload(0, "alpha")])

    with pytest.raises(LexicalInputError, match="positive non-bool"):
        searcher.search("alpha", top_k=top_k)


def test_empty_valid_corpus_returns_no_hits() -> None:
    searcher = build_lexical_searcher(())

    result = searcher.search("出願資格")

    assert result.hits == ()
    assert result.tokenizer_version == LEXICAL_TOKENIZER_VERSION
    assert result.scoring_version == LEXICAL_SCORING_VERSION


@pytest.mark.parametrize(
    ("payloads", "message"),
    [
        ([_payload(1, "alpha")], "contiguous"),
        (
            [_payload(0, "alpha"), _payload(1, "beta", unit_id="unit:00000")],
            "duplicate",
        ),
        (
            [_payload(0, "alpha"), _payload(1, "beta", document_id="other")],
            "mixes document",
        ),
        ([_payload(0, "alpha"), object()], "non-IndexPayload"),
    ],
)
def test_malformed_payload_corpora_use_typed_errors(payloads, message) -> None:
    with pytest.raises(LexicalCorpusError, match=message):
        build_lexical_searcher(payloads)

    with pytest.raises(LexicalCorpusError, match="source must"):
        build_lexical_searcher("payloads")  # type: ignore[arg-type]


def test_non_finite_and_inconsistent_internal_statistics_are_rejected() -> None:
    searcher = build_lexical_searcher([_payload(0, "alpha")])

    with pytest.raises(LexicalScoreError, match="average document length is invalid"):
        replace(searcher, average_document_length=float("nan")).search("alpha")
    with pytest.raises(LexicalScoreError, match="term frequencies do not match"):
        replace(searcher, document_lengths=(searcher.document_lengths[0] + 1,)).search("alpha")
    with pytest.raises(LexicalScoreError, match="document frequencies do not match"):
        replace(searcher, document_frequency=MappingProxyType({"alpha": 1})).search("alpha")


def test_hits_preserve_complete_detached_immutable_payload_evidence() -> None:
    payload = _payload(0, "出願資格 TOEFL-PBT")
    before = payload.model_dump(mode="json")
    searcher = build_lexical_searcher([payload])

    result = searcher.search("TOEFL PBT", top_k=5)
    hit = result.hits[0]

    assert hit.rank == 1
    assert hit.row_index == payload.row_index
    assert hit.document_id == payload.document_id
    assert hit.unit_id == payload.unit_id
    assert hit.fact_id == payload.fact_id
    assert hit.text == payload.text
    assert hit.source_pages == tuple(payload.source_pages)
    assert hit.section_path == tuple(payload.section_path)
    assert hit.fact_type == payload.fact_type
    assert hit.scope_type == payload.scope_type
    assert hit.scope_targets == tuple(payload.scope_targets)
    assert hit.parent_college == payload.parent_college
    assert hit.to_dict()["metadata"] == payload.metadata
    assert payload.model_dump(mode="json") == before

    payload.metadata["nested"]["items"].append(999)
    assert hit.to_dict()["metadata"]["nested"]["items"] == [0]
    with pytest.raises(TypeError):
        hit.metadata["new"] = "value"  # type: ignore[index]

    thawed = hit.to_dict()
    thawed["metadata"]["nested"]["items"].append(123)
    assert hit.to_dict()["metadata"]["nested"]["items"] == [0]


def test_repeated_and_independently_built_searchers_return_stable_values() -> None:
    first_payloads = [_payload(0, "検定料 30,000円"), _payload(1, "出願資格")]
    second_payloads = [payload.model_copy(deep=True) for payload in first_payloads]
    first = build_lexical_searcher(first_payloads)
    second = build_lexical_searcher(second_payloads)

    first_result = first.search("検定料 30000", top_k=5)
    repeated = first.search("検定料 30000", top_k=5)
    independent = second.search("検定料 30000", top_k=5)

    assert first_result == repeated == independent
    assert json.dumps(
        [hit.to_dict() for hit in first_result.hits],
        ensure_ascii=False,
        sort_keys=True,
    ) == json.dumps(
        [hit.to_dict() for hit in independent.hits],
        ensure_ascii=False,
        sort_keys=True,
    )


def test_local_vector_index_is_accepted_without_using_or_mutating_vectors() -> None:
    payloads = (_payload(0, "alpha"), _payload(1, "beta"))
    vectors = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    vectors.setflags(write=False)
    local_index = LocalVectorIndex(
        manifest=_manifest(2),
        payloads=payloads,
        vectors=vectors,
    )
    before = vectors.tobytes()

    searcher = build_lexical_searcher(local_index)
    result = search_lexical(searcher, "alpha", top_k=5)

    assert [hit.row_index for hit in result.hits] == [0]
    assert vectors.tobytes() == before
    assert vectors.flags.writeable is False
