from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Sequence

import pytest

from jgrad_admission_rag.retrieval.embedding import (
    EmbeddingIdentity,
    EmbeddingOutputError,
    EmbeddingProviderError,
)
from jgrad_admission_rag.retrieval.local_index import (
    IndexLoadError,
    build_local_index,
)
from jgrad_admission_rag.retrieval.vector_search import (
    ProviderIdentityMismatchError,
    QueryVectorError,
    SearchInputError,
    search_local_index,
)
from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    QualityGateResult,
    RetrievalUnit,
    ScopedFact,
)

PDF_HASH = "b" * 64


class StaticProvider:
    def __init__(
        self,
        *,
        identity: EmbeddingIdentity | None = None,
        document_vectors: list[list[float]] | None = None,
        query_vector: list[float] | None = None,
        query_error: Exception | None = None,
    ) -> None:
        self.identity = identity or EmbeddingIdentity("static", "axes", "r1", 2)
        self.document_vectors = document_vectors or [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]
        self.query_vector = query_vector or [1.0, 0.0]
        self.query_error = query_error
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls.append(list(texts))
        return [list(vector) for vector in self.document_vectors]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        if self.query_error is not None:
            raise self.query_error
        return self.query_vector


class IdentityExplodesProvider:
    @property
    def identity(self):
        raise AssertionError("provider identity must not load for an invalid index")

    def embed_documents(self, texts):
        raise AssertionError

    def embed_query(self, text):
        raise AssertionError


def _knowledge_base(*, empty: bool = False) -> DocumentKnowledgeBase:
    facts = []
    units = []
    if not empty:
        for row, text in enumerate(("row zero", "row one", "row two")):
            fact = ScopedFact(
                fact_id=f"fact:{row:05d}",
                fact_type="eligibility" if row != 1 else "fees",
                scope_type="department" if row == 0 else "global",
                scope_targets=["情報工学系"] if row == 0 else [],
                parent_college="情報理工学院" if row == 0 else None,
                title=text,
                text=f"evidence {row}",
                source_pages=[row + 10],
                section_path=["募集要項", text],
                embedding_text=f"canonical {text}",
                metadata={"embedding_text_version": "1", "nested": {"labels": [text]}},
            )
            facts.append(fact)
            units.append(
                RetrievalUnit(
                    unit_id=f"unit:{row:05d}",
                    fact_id=fact.fact_id,
                    text=fact.embedding_text,
                    source_pages=list(fact.source_pages),
                    section_path=list(fact.section_path),
                    metadata=dict(fact.metadata),
                )
            )
    return DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            document_id="sample-document",
            source_pdf="sample.pdf",
            pdf_sha256=PDF_HASH,
            chunk_count=len(facts),
        ),
        facts=facts,
        retrieval_units=units,
        diagnostics=BuildDiagnostics(quality_gate=QualityGateResult(passed=True)),
    )


def _write_kb(path: Path, *, empty: bool = False) -> None:
    path.write_text(
        json.dumps(
            _knowledge_base(empty=empty).model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
        newline="",
    )


def _build_index(
    tmp_path: Path,
    *,
    empty: bool = False,
    provider: StaticProvider | None = None,
) -> tuple[Path, StaticProvider]:
    kb_path = tmp_path / "document_kb.json"
    _write_kb(kb_path, empty=empty)
    index_dir = tmp_path / "index"
    selected_provider = provider or StaticProvider()
    if empty:
        selected_provider.document_vectors = []
    build_local_index(kb_path, index_dir, selected_provider)
    return index_dir, selected_provider


def test_cosine_ranking_ties_and_hits_preserve_exact_payload_evidence(tmp_path: Path) -> None:
    index_dir, _ = _build_index(tmp_path)
    provider = StaticProvider(query_vector=[2.0, 0.0])

    result = search_local_index(index_dir, "出願資格", provider, top_k=2)

    assert [hit.row_index for hit in result.hits] == [0, 2]
    assert [hit.rank for hit in result.hits] == [1, 2]
    assert [hit.score for hit in result.hits] == pytest.approx([1.0, 1.0])
    first = result.hits[0]
    assert first.document_id == "sample-document"
    assert first.unit_id == "unit:00000"
    assert first.fact_id == "fact:00000"
    assert first.text == "canonical row zero"
    assert first.source_pages == (10,)
    assert first.section_path == ("募集要項", "row zero")
    assert first.fact_type == "eligibility"
    assert first.scope_type == "department"
    assert first.scope_targets == ("情報工学系",)
    assert first.parent_college == "情報理工学院"
    assert first.to_dict()["metadata"] == {
        "embedding_text_version": "1",
        "nested": {"labels": ["row zero"]},
    }
    assert provider.query_calls == ["出願資格"]


def test_hit_is_immutable_and_serialized_values_are_detached(tmp_path: Path) -> None:
    index_dir, _ = _build_index(tmp_path)
    hit = search_local_index(index_dir, "query", StaticProvider(), top_k=1).hits[0]

    with pytest.raises(FrozenInstanceError):
        hit.rank = 3
    with pytest.raises(TypeError):
        hit.metadata["new"] = "value"
    serialized = hit.to_dict()
    serialized["source_pages"].append(999)
    serialized["metadata"]["nested"]["labels"].append("changed")

    assert hit.source_pages == (10,)
    assert hit.to_dict()["metadata"]["nested"]["labels"] == ["row zero"]


def test_top_k_overflow_returns_all_rows_and_normalized_scores(tmp_path: Path) -> None:
    index_dir, _ = _build_index(tmp_path)

    result = search_local_index(
        index_dir,
        "query",
        StaticProvider(query_vector=[3.0, 4.0]),
        top_k=99,
    )

    assert [hit.row_index for hit in result.hits] == [1, 0, 2]
    assert [hit.score for hit in result.hits] == pytest.approx([0.8, 0.6, 0.6])


def test_empty_index_returns_empty_after_checked_query_embedding(tmp_path: Path) -> None:
    index_dir, _ = _build_index(tmp_path, empty=True)
    provider = StaticProvider(document_vectors=[], query_vector=[1.0, 0.0])

    result = search_local_index(index_dir, "query", provider, top_k=5)

    assert result.hits == ()
    assert provider.query_calls == ["query"]


@pytest.mark.parametrize("query", ["", " ", None, 3])
def test_blank_or_non_string_query_is_rejected_before_index_access(query) -> None:
    with pytest.raises(SearchInputError, match="non-blank"):
        search_local_index("missing-index", query, StaticProvider())


@pytest.mark.parametrize("top_k", [0, -1, True, 1.5, "2"])
def test_invalid_top_k_is_rejected_before_index_access(top_k) -> None:
    with pytest.raises(SearchInputError, match="positive non-bool"):
        search_local_index("missing-index", "query", StaticProvider(), top_k=top_k)


@pytest.mark.parametrize(
    ("identity", "field"),
    [
        (EmbeddingIdentity("other", "axes", "r1", 2), "provider"),
        (EmbeddingIdentity("static", "other", "r1", 2), "model"),
        (EmbeddingIdentity("static", "axes", "r2", 2), "revision"),
        (EmbeddingIdentity("static", "axes", "r1", 3), "dimension"),
    ],
)
def test_identity_mismatch_fails_before_query_embedding(
    tmp_path: Path, identity: EmbeddingIdentity, field: str
) -> None:
    index_dir, _ = _build_index(tmp_path)
    provider = StaticProvider(identity=identity)

    with pytest.raises(ProviderIdentityMismatchError, match=field):
        search_local_index(index_dir, "SENTINEL-QUERY", provider)

    assert provider.query_calls == []


def test_corrupt_index_fails_before_provider_identity_load(tmp_path: Path) -> None:
    index_dir = tmp_path / "corrupt-index"
    index_dir.mkdir()
    (index_dir / "manifest.json").write_text("not-json", encoding="utf-8")

    with pytest.raises(IndexLoadError):
        search_local_index(index_dir, "query", IdentityExplodesProvider())


@pytest.mark.parametrize(
    ("query_vector", "error_type"),
    [
        ([0.0, 0.0], QueryVectorError),
        ([1e40, 0.0], QueryVectorError),
        ([float("nan"), 0.0], EmbeddingOutputError),
        ([1.0], EmbeddingOutputError),
    ],
)
def test_invalid_query_vectors_are_rejected(
    tmp_path: Path, query_vector: list[float], error_type: type[Exception]
) -> None:
    index_dir, _ = _build_index(tmp_path)

    with pytest.raises(error_type):
        search_local_index(index_dir, "query", StaticProvider(query_vector=query_vector))


def test_provider_error_is_preserved(tmp_path: Path) -> None:
    index_dir, _ = _build_index(tmp_path)
    cause = EmbeddingProviderError("safe provider failure")

    with pytest.raises(EmbeddingProviderError, match="safe provider failure"):
        search_local_index(index_dir, "query", StaticProvider(query_error=cause))


def test_search_does_not_mutate_index_files_or_provider_vector(tmp_path: Path) -> None:
    index_dir, _ = _build_index(tmp_path)
    before = {path.name: path.read_bytes() for path in index_dir.iterdir()}
    query_vector = [3.0, 4.0]
    provider = StaticProvider(query_vector=query_vector)

    search_local_index(index_dir, "query", provider, top_k=3)

    after = {path.name: path.read_bytes() for path in index_dir.iterdir()}
    assert after == before
    assert query_vector == [3.0, 4.0]
