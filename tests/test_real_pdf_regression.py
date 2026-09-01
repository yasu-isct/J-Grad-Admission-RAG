from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from jgrad_admission_rag.cli import build_index as build_index_cli
from jgrad_admission_rag.cli import search as search_cli
from jgrad_admission_rag.builder.chunk_filter import classify_chunk
from jgrad_admission_rag.builder.chunker import chunk_pages
from jgrad_admission_rag.builder.extractor import ExtractedPage, extract_pdf
from jgrad_admission_rag.builder.kb_builder import build_document_kb, pages_to_source_pages
from jgrad_admission_rag.evaluation.retrieval_queries import load_retrieval_benchmark
from jgrad_admission_rag.retrieval.embedding import (
    DeterministicFakeEmbeddingProvider,
    embed_documents_checked,
    embed_query_checked,
)
from jgrad_admission_rag.retrieval.embedding_text import EMBEDDING_TEXT_VERSION
from jgrad_admission_rag.retrieval.local_index import build_local_index, load_local_index
from jgrad_admission_rag.retrieval.lexical_search import build_lexical_searcher
from jgrad_admission_rag.retrieval.vector_search import search_local_index
from jgrad_admission_rag.schemas.document_kb import DocumentKnowledgeBase
from jgrad_admission_rag.schemas.index import derive_index_payloads
from jgrad_admission_rag.utils import sha256_file

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "tests" / "fixtures" / "real_pdf_manifest.json"
RETRIEVAL_BENCHMARK_PATH = REPO_ROOT / "tests" / "fixtures" / "retrieval_queries_v1.json"
REAL_PDF_ENV = "JGRAD_REAL_PDF"

pytestmark = pytest.mark.real_pdf


@pytest.fixture(scope="module")
def real_pdf_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real_pdf_path(real_pdf_manifest: dict[str, Any]) -> Path:
    filename = real_pdf_manifest["filename"]
    configured = os.getenv(REAL_PDF_ENV)
    configured_path = Path(configured).expanduser() if configured else None
    if configured_path and not configured_path.is_absolute():
        configured_path = REPO_ROOT / configured_path
    candidates = [
        configured_path,
        REPO_ROOT / "tests" / "fixtures" / "private" / filename,
        REPO_ROOT / "outputs" / "real_pdf" / filename,
    ]
    path = next((candidate for candidate in candidates if candidate and candidate.is_file()), None)
    if path is None:
        pytest.skip(
            f"real PDF fixture unavailable; set {REAL_PDF_ENV} or follow tests/fixtures/README.md"
        )

    actual_hash = sha256_file(path)
    assert actual_hash == real_pdf_manifest["sha256"], (
        f"real PDF fixture hash mismatch: expected {real_pdf_manifest['sha256']}, got {actual_hash}"
    )
    return path


@pytest.fixture(scope="module")
def extracted_pages(real_pdf_path: Path) -> list[ExtractedPage]:
    return extract_pdf(real_pdf_path)


@pytest.fixture(scope="module")
def real_document_kb(real_pdf_path: Path) -> DocumentKnowledgeBase:
    return build_document_kb(real_pdf_path)


def test_real_pdf_extraction_matches_baseline(
    real_pdf_manifest: dict[str, Any],
    extracted_pages: list[ExtractedPage],
) -> None:
    expected = real_pdf_manifest["expected"]
    assert len(extracted_pages) == expected["page_count"]
    assert [page.page for page in extracted_pages] == list(range(1, expected["page_count"] + 1))
    assert sum(page.table_count for page in extracted_pages) == expected["table_count"]
    assert sum(page.scanned for page in extracted_pages) == expected["scanned_page_count"]

    extracted_text = "\n".join(page.markdown for page in extracted_pages)
    for marker in real_pdf_manifest["text_markers"]:
        assert marker in extracted_text


def test_real_pdf_knowledge_base_matches_baseline(
    real_pdf_manifest: dict[str, Any],
    real_document_kb: DocumentKnowledgeBase,
) -> None:
    expected = real_pdf_manifest["expected"]
    manifest = real_document_kb.manifest
    assert manifest.schema_version == "0.5"
    assert manifest.input_chunk_count == expected["input_chunk_count"]
    assert manifest.pdf_sha256 == real_pdf_manifest["sha256"]
    assert manifest.chunk_count == expected["chunk_count"]
    assert manifest.dropped_chunk_count == expected["dropped_chunk_count"]
    assert manifest.dropped_chunk_reasons == expected["dropped_chunk_reasons"]
    assert manifest.merged_heading_count == expected["merged_heading_count"]
    assert manifest.input_chunk_count == (
        manifest.chunk_count + manifest.dropped_chunk_count + manifest.merged_heading_count
    )
    assert manifest.reference_link_count == expected["reference_link_count"]
    assert manifest.chunk_size_limit == expected["chunk_size_limit"]
    assert manifest.max_chunk_chars == expected["max_chunk_chars"]
    assert manifest.oversized_chunk_count == expected["oversized_chunk_count"]
    assert manifest.oversized_chunk_reasons == expected["oversized_chunk_reasons"]
    assert manifest.oversized_chunk_count == sum(manifest.oversized_chunk_reasons.values())
    assert len(real_document_kb.entities) == expected["entity_count"]
    assert len(real_document_kb.facts) == expected["fact_count"]
    assert len(real_document_kb.retrieval_units) == expected["retrieval_unit_count"]
    diagnostics = real_document_kb.diagnostics
    assert diagnostics.input_chunk_count == manifest.input_chunk_count
    assert diagnostics.emitted_chunk_count == manifest.chunk_count
    assert diagnostics.dropped_chunk_count == manifest.dropped_chunk_count
    assert diagnostics.dropped_chunk_reasons == manifest.dropped_chunk_reasons
    assert diagnostics.merged_heading_count == manifest.merged_heading_count
    assert diagnostics.missing_source_page_fact_ids == []
    assert diagnostics.missing_section_path_fact_ids == []
    assert diagnostics.empty_or_noninformative_fact_ids == []
    assert diagnostics.short_fact_threshold == expected["short_fact_threshold"]
    assert len(diagnostics.short_fact_ids) == expected["short_fact_count"]
    assert len(diagnostics.unknown_scope_fact_ids) == expected["unknown_scope_fact_count"]
    assert diagnostics.max_chunk_chars == manifest.max_chunk_chars
    assert diagnostics.oversized_fact_ids == []
    assert diagnostics.oversized_reasons == manifest.oversized_chunk_reasons
    assert diagnostics.raw_reference_occurrence_count == expected["raw_reference_occurrence_count"]
    assert diagnostics.reference_claim_count == expected["reference_claim_count"]
    assert diagnostics.reference_status_counts == expected["reference_status_counts"]
    assert diagnostics.reference_claim_count == len(diagnostics.reference_claims)
    assert diagnostics.reference_claim_count == sum(diagnostics.reference_status_counts.values())
    assert diagnostics.reference_status_counts["resolved"] == manifest.reference_link_count
    assert diagnostics.quality_gate.passed
    assert diagnostics.quality_gate.violations == []
    assert diagnostics.quality_thresholds.max_missing_source_pages == 0
    assert diagnostics.quality_thresholds.max_unknown_scope_facts is None
    fact_projection = [
        {
            "fact_id": fact.fact_id,
            "title": fact.title,
            "text": fact.text,
            "source_pages": fact.source_pages,
            "section_path": fact.section_path,
        }
        for fact in real_document_kb.facts
    ]
    fact_content_sha256 = hashlib.sha256(
        json.dumps(fact_projection, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert fact_content_sha256 == expected["fact_content_sha256"]

    assert all(fact.source_pages for fact in real_document_kb.facts)
    assert all(unit.source_pages for unit in real_document_kb.retrieval_units)
    assert all(fact.section_path for fact in real_document_kb.facts)
    assert all(unit.section_path for unit in real_document_kb.retrieval_units)
    assert all(len(fact.text) <= manifest.chunk_size_limit for fact in real_document_kb.facts)
    assert all("oversize_reason" not in fact.metadata for fact in real_document_kb.facts)
    assert all(
        1 <= page <= expected["page_count"]
        for fact in real_document_kb.facts
        for page in fact.source_pages
    )

    fact_ids = [fact.fact_id for fact in real_document_kb.facts]
    assert fact_ids == [f"fact:{index:05d}" for index in range(expected["fact_count"])]
    assert len(fact_ids) == len(set(fact_ids))
    assert {unit.fact_id for unit in real_document_kb.retrieval_units} == set(fact_ids)
    pages_by_fact = {fact.fact_id: fact.source_pages for fact in real_document_kb.facts}
    paths_by_fact = {fact.fact_id: fact.section_path for fact in real_document_kb.facts}
    assert all(
        unit.source_pages == pages_by_fact[unit.fact_id]
        for unit in real_document_kb.retrieval_units
    )
    assert all(
        unit.section_path == paths_by_fact[unit.fact_id]
        for unit in real_document_kb.retrieval_units
    )

    assert any(fact.scope_type == "department" for fact in real_document_kb.facts)
    assert any("情報工学系" in fact.scope_targets for fact in real_document_kb.facts)
    assert any(fact.metadata["anchors"] for fact in real_document_kb.facts)
    assert any(
        reference["label"].startswith("下記")
        for fact in real_document_kb.facts
        for reference in fact.metadata["references"]
    )


def test_real_pdf_page_only_positions_match_baseline(
    real_pdf_manifest: dict[str, Any],
    extracted_pages: list[ExtractedPage],
) -> None:
    chunks = chunk_pages(
        pages_to_source_pages(extracted_pages),
        real_pdf_manifest["filename"],
    )
    positions = [
        index for index, chunk in enumerate(chunks) if classify_chunk(chunk) == "page_only"
    ]

    assert positions == real_pdf_manifest["expected"]["page_only_positions"]


def test_real_pdf_kb05_split_mapping_is_content_balanced(
    real_pdf_manifest: dict[str, Any],
    real_document_kb: DocumentKnowledgeBase,
) -> None:
    expected = real_pdf_manifest["expected"]["kb05_split_transitions"]
    for page_text, (old_length, *child_lengths) in expected.items():
        page = int(page_text)
        page_facts = [fact for fact in real_document_kb.facts if fact.source_pages == [page]]
        actual_lengths = [len(fact.text) for fact in page_facts]

        assert actual_lengths == child_lengths
        assert old_length == sum(child_lengths) + 2 * (len(child_lengths) - 1)
        assert len({tuple(fact.section_path) for fact in page_facts}) == 1


def test_real_pdf_reference_diagnostics_are_traceable(
    real_pdf_manifest: dict[str, Any],
    real_document_kb: DocumentKnowledgeBase,
) -> None:
    claims = real_document_kb.diagnostics.reference_claims
    resolved = next(claim for claim in claims if claim.status == "resolved")
    ambiguous = next(claim for claim in claims if claim.status == "ambiguous")
    unresolved = next(claim for claim in claims if claim.status == "unresolved")

    assert resolved.selected_target_fact_id in resolved.candidate_target_fact_ids
    assert resolved.top_score is not None
    assert ambiguous.selected_target_fact_id is None
    assert ambiguous.score_margin is not None and ambiguous.score_margin <= 0.1
    assert len(ambiguous.candidate_target_fact_ids) >= 2
    assert unresolved.selected_target_fact_id is None
    assert unresolved.candidate_target_fact_ids == []
    assert unresolved.reason == "no_positive_candidate"

    expected = real_pdf_manifest["expected"]
    assert [
        [claim.source_fact_id, claim.label, claim.selected_target_fact_id]
        for claim in claims
        if claim.status == "resolved"
    ] == expected["resolved_reference_claims"]
    assert [
        [claim.source_fact_id, claim.label, claim.candidate_target_fact_ids[0]]
        for claim in claims
        if claim.status == "ambiguous"
    ] == expected["removed_ambiguous_links"]


def test_real_pdf_diagnostics_are_deterministic(
    real_pdf_path: Path,
    real_document_kb: DocumentKnowledgeBase,
) -> None:
    rebuilt = build_document_kb(real_pdf_path)

    assert rebuilt.diagnostics.model_dump(mode="json") == real_document_kb.diagnostics.model_dump(
        mode="json"
    )


def test_real_pdf_derives_traceable_index_payload_shape(
    real_pdf_manifest: dict[str, Any],
    real_document_kb: DocumentKnowledgeBase,
) -> None:
    payloads = derive_index_payloads(real_document_kb)
    expected_count = real_pdf_manifest["expected"]["retrieval_unit_count"]

    assert len(payloads) == expected_count == 298
    assert [payload.row_index for payload in payloads] == list(range(expected_count))
    assert len({payload.unit_id for payload in payloads}) == expected_count
    assert len({payload.fact_id for payload in payloads}) == expected_count
    assert all(payload.document_id == real_document_kb.manifest.document_id for payload in payloads)
    assert all(payload.source_pages for payload in payloads)
    assert all(payload.section_path for payload in payloads)
    assert all(
        payload.unit_id == unit.unit_id
        and payload.fact_id == unit.fact_id
        and payload.text == unit.text
        and payload.source_pages == unit.source_pages
        and payload.section_path == unit.section_path
        and payload.metadata == unit.metadata
        for payload, unit in zip(payloads, real_document_kb.retrieval_units, strict=True)
    )


def test_real_pdf_embedding_text_v1_is_complete_and_structure_preserving(
    real_pdf_manifest: dict[str, Any],
    real_document_kb: DocumentKnowledgeBase,
) -> None:
    expected = real_pdf_manifest["expected"]
    facts = real_document_kb.facts
    units = real_document_kb.retrieval_units
    projections = [unit.text for unit in units]

    assert len(facts) == len(units) == expected["retrieval_unit_count"] == 298
    assert all(fact.embedding_text == unit.text for fact, unit in zip(facts, units, strict=True))
    assert all(
        unit.text.endswith(f"text:\n{fact.text}") for fact, unit in zip(facts, units, strict=True)
    )
    assert all(fact.metadata["embedding_text_version"] == EMBEDDING_TEXT_VERSION for fact in facts)
    assert all(unit.metadata["embedding_text_version"] == EMBEDDING_TEXT_VERSION for unit in units)
    assert all(
        unit.text.endswith(fact.text) and fact.text[300:] in unit.text
        for fact, unit in zip(facts, units, strict=True)
        if len(fact.text) > 300
    )
    longest_fact = max(facts, key=lambda fact: len(fact.text))
    longest_unit = next(unit for unit in units if unit.fact_id == longest_fact.fact_id)
    assert len(longest_fact.text) == expected["max_chunk_chars"] == 5993
    assert longest_unit.text.endswith(f"text:\n{longest_fact.text}")

    projection_sha256 = hashlib.sha256(
        json.dumps(projections, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert projection_sha256 == expected["embedding_text_v1_sha256"]

    structure_projection = [
        {
            "fact_id": fact.fact_id,
            "unit_id": unit.unit_id,
            "source_pages": fact.source_pages,
            "section_path": fact.section_path,
            "scope_type": fact.scope_type,
            "scope_targets": fact.scope_targets,
            "parent_college": fact.parent_college,
        }
        for fact, unit in zip(facts, units, strict=True)
    ]
    structure_sha256 = hashlib.sha256(
        json.dumps(structure_projection, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    diagnostics_sha256 = hashlib.sha256(
        json.dumps(
            real_document_kb.diagnostics.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert structure_sha256 == expected["fact_structure_sha256"]
    assert diagnostics_sha256 == expected["diagnostics_sha256"]


def test_real_pdf_fake_embeddings_are_deterministic_without_mutating_kb(
    real_pdf_manifest: dict[str, Any],
    real_document_kb: DocumentKnowledgeBase,
) -> None:
    before = real_document_kb.model_dump(mode="json")
    unit_projection_before = [
        (
            unit.unit_id,
            unit.fact_id,
            unit.text,
            list(unit.source_pages),
            list(unit.section_path),
        )
        for unit in real_document_kb.retrieval_units
    ]
    texts = [unit.text for unit in real_document_kb.retrieval_units]
    provider = DeterministicFakeEmbeddingProvider(dimension=8)

    first = embed_documents_checked(provider, texts)
    second = embed_documents_checked(provider, texts)
    projection_sha256 = hashlib.sha256(
        json.dumps(first, separators=(",", ":")).encode("ascii")
    ).hexdigest()

    assert len(first) == real_pdf_manifest["expected"]["retrieval_unit_count"] == 298
    assert all(len(vector) == 8 for vector in first)
    assert first == second
    previous_projection_sha256 = "f0367234e3335e171fa067cdb1fef0dd3e132c5fc59035215450f010d19a1e2f"
    assert projection_sha256 != previous_projection_sha256
    assert (
        projection_sha256 == real_pdf_manifest["expected"]["embedding_text_v1_fake_vector_sha256"]
    )
    assert all(all(math.isfinite(value) for value in vector) for vector in first)
    assert all(any(value != 0.0 for value in vector) for vector in first)
    assert all(
        math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0) for vector in first
    )
    assert real_document_kb.manifest.pdf_sha256 == real_pdf_manifest["sha256"]
    assert real_document_kb.model_dump(mode="json") == before
    assert [
        (
            unit.unit_id,
            unit.fact_id,
            unit.text,
            list(unit.source_pages),
            list(unit.section_path),
        )
        for unit in real_document_kb.retrieval_units
    ] == unit_projection_before


def test_real_pdf_local_index_is_aligned_normalized_and_byte_deterministic(
    tmp_path: Path,
    real_pdf_manifest: dict[str, Any],
    real_document_kb: DocumentKnowledgeBase,
) -> None:
    kb_path = tmp_path / "document_kb.json"
    kb_bytes = (
        json.dumps(
            real_document_kb.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    kb_path.write_bytes(kb_bytes)
    first_dir = tmp_path / "first-index"
    second_dir = tmp_path / "second-index"
    provider = DeterministicFakeEmbeddingProvider(dimension=8)

    first_manifest = build_local_index(kb_path, first_dir, provider)
    second_manifest = build_local_index(
        kb_path,
        second_dir,
        DeterministicFakeEmbeddingProvider(dimension=8),
    )
    mapped = load_local_index(first_dir, mmap=True)
    memory = load_local_index(first_dir, mmap=False)
    expected = real_pdf_manifest["expected"]
    derived_payloads = derive_index_payloads(real_document_kb)

    assert first_manifest == second_manifest
    assert first_manifest.source_kb_sha256 == hashlib.sha256(kb_bytes).hexdigest()
    assert first_manifest.source_pdf_sha256 == real_pdf_manifest["sha256"]
    assert first_manifest.payload_count == first_manifest.vector_count == 298
    assert first_manifest.embedding_dimension == 8
    assert first_manifest.payloads_sha256 == expected["index_payloads_sha256"]
    assert first_manifest.vectors_sha256 == expected["index_fake_vectors_npy_sha256"]
    assert mapped.vectors.shape == (298, 8)
    assert mapped.vectors.dtype == np.dtype("<f4")
    assert isinstance(mapped.vectors, np.memmap)
    assert not mapped.vectors.flags.writeable
    assert np.isfinite(mapped.vectors).all()
    assert np.all(np.linalg.norm(mapped.vectors.astype(np.float64), axis=1) > 0)
    np.testing.assert_allclose(
        np.linalg.norm(mapped.vectors.astype(np.float64), axis=1),
        1.0,
        rtol=0.0,
        atol=1e-5,
    )
    np.testing.assert_array_equal(mapped.vectors, memory.vectors)
    assert [payload.model_dump(mode="json") for payload in mapped.payloads] == [
        payload.model_dump(mode="json") for payload in derived_payloads
    ]
    assert [payload.row_index for payload in mapped.payloads] == list(range(298))

    for filename in ("manifest.json", "payloads.jsonl", "embeddings.npy"):
        assert (first_dir / filename).read_bytes() == (second_dir / filename).read_bytes()


def test_real_pdf_build_index_cli_reports_frozen_fake_artifacts(
    tmp_path: Path,
    real_pdf_manifest: dict[str, Any],
    real_document_kb: DocumentKnowledgeBase,
    capsys,
) -> None:
    kb_path = tmp_path / "document_kb.json"
    kb_path.write_text(
        json.dumps(
            real_document_kb.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
        newline="",
    )
    output = tmp_path / "cli-index"

    build_index_cli.main(
        [
            str(kb_path),
            "--output",
            str(output),
            "--provider",
            "deterministic-fake",
            "--dimension",
            "8",
        ]
    )

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    loaded = load_local_index(output, mmap=True)
    expected = real_pdf_manifest["expected"]
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    assert summary["payload_count"] == summary["vector_count"] == 298
    assert summary["embedding_dimension"] == 8
    assert summary["payloads_sha256"] == expected["index_payloads_sha256"]
    assert summary["vectors_sha256"] == expected["index_fake_vectors_npy_sha256"]
    assert loaded.vectors.shape == (298, 8)
    assert loaded.manifest.payloads_sha256 == (
        "f1530da8b93f7ae0e816e43bbde0464c453b4d308743f28a2b03029ca0e4beb3"
    )
    assert loaded.manifest.vectors_sha256 == (
        "0b77bb53b6dcca385ce432febbcab74f07cef49963262b5d5026e86751117129"
    )


def test_real_pdf_vector_search_matches_independent_numpy_ranking_and_cli(
    tmp_path: Path,
    real_pdf_manifest: dict[str, Any],
    real_document_kb: DocumentKnowledgeBase,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_path = tmp_path / "document_kb.json"
    kb_path.write_text(
        json.dumps(
            real_document_kb.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
        newline="",
    )
    index_dir = tmp_path / "index"
    build_local_index(kb_path, index_dir, DeterministicFakeEmbeddingProvider(dimension=8))
    before = {path.name: path.read_bytes() for path in index_dir.iterdir()}
    query = "出願資格"

    result = search_local_index(
        index_dir,
        query,
        DeterministicFakeEmbeddingProvider(dimension=8),
        top_k=5,
    )
    loaded = load_local_index(index_dir, mmap=True)
    query_values = np.asarray(
        embed_query_checked(DeterministicFakeEmbeddingProvider(dimension=8), query),
        dtype="<f4",
    )
    query_values = np.asarray(
        query_values.astype(np.float64) / np.linalg.norm(query_values.astype(np.float64)),
        dtype="<f4",
    )
    independent_scores = np.asarray(loaded.vectors @ query_values, dtype="<f4")
    rows = np.arange(len(loaded.payloads), dtype=np.int64)
    expected_rows = np.lexsort((rows, -independent_scores.astype(np.float64)))[:5]
    expected = [loaded.payloads[int(row)] for row in expected_rows]

    assert result.manifest.payload_count == result.manifest.vector_count == 298
    assert (
        result.manifest.payloads_sha256 == (real_pdf_manifest["expected"]["index_payloads_sha256"])
    )
    assert (
        result.manifest.vectors_sha256
        == (real_pdf_manifest["expected"]["index_fake_vectors_npy_sha256"])
    )
    assert [hit.row_index for hit in result.hits] == [int(row) for row in expected_rows]
    assert [hit.score for hit in result.hits] == pytest.approx(
        [float(independent_scores[int(row)]) for row in expected_rows],
        rel=0.0,
        abs=1e-7,
    )
    assert [hit.row_index for hit in result.hits] == [209, 297, 53, 59, 66]
    assert [hit.score for hit in result.hits] == pytest.approx(
        [
            0.9264391660690308,
            0.8517074584960938,
            0.8401667475700378,
            0.7775591015815735,
            0.7775591015815735,
        ],
        rel=0.0,
        abs=1e-7,
    )
    assert [hit.scope_type for hit in result.hits] == [
        "department",
        "unknown",
        "department",
        "unknown",
        "unknown",
    ]
    assert [hit.source_pages for hit in result.hits] == [(44,), (85,), (6,), (7,), (7,)]
    assert all(
        hit.unit_id == payload.unit_id
        and hit.fact_id == payload.fact_id
        and hit.text == payload.text
        and list(hit.source_pages) == payload.source_pages
        and list(hit.section_path) == payload.section_path
        and hit.scope_type == payload.scope_type
        and list(hit.scope_targets) == payload.scope_targets
        for hit, payload in zip(result.hits, expected, strict=True)
    )
    assert all(hit.source_pages and hit.section_path for hit in result.hits)

    search_cli.main(
        [
            str(index_dir),
            "--current-kb",
            str(kb_path),
            "--query",
            query,
            "--top-k",
            "5",
            "--provider",
            "deterministic-fake",
            "--dimension",
            "8",
        ]
    )
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert captured.err == ""
    assert summary["semantic"] is False
    assert summary["result_count"] == 5
    assert summary["freshness"]["fresh"] is True
    assert summary["freshness"]["current_kb_sha256"] == summary["source_kb_sha256"]
    assert [hit["row_index"] for hit in summary["results"]] == [
        hit.row_index for hit in result.hits
    ]
    assert {path.name: path.read_bytes() for path in index_dir.iterdir()} == before

    stale_kb_path = tmp_path / "one-byte-stale.json"
    stale_kb_path.write_bytes(kb_path.read_bytes() + b" ")
    stale_before = stale_kb_path.read_bytes()
    monkeypatch.setattr(
        search_cli,
        "create_provider",
        lambda _configuration: (_ for _ in ()).throw(
            AssertionError("one-byte stale KB must fail before provider construction")
        ),
    )
    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(
            [
                str(index_dir),
                "--current-kb",
                str(stale_kb_path),
                "--query",
                "出願資格",
                "--provider",
                "deterministic-fake",
                "--dimension",
                "8",
            ]
        )
    stale_output = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert stale_output.out == ""
    assert json.loads(stale_output.err)["mismatches"] == ["source_kb_sha256"]
    assert stale_kb_path.read_bytes() == stale_before
    assert {path.name: path.read_bytes() for path in index_dir.iterdir()} == before


def test_real_pdf_retrieval_benchmark_gold_maps_to_authoritative_facts(
    real_pdf_manifest: dict[str, Any],
    real_document_kb: DocumentKnowledgeBase,
) -> None:
    benchmark = load_retrieval_benchmark(RETRIEVAL_BENCHMARK_PATH)
    expected = real_pdf_manifest["expected"]
    facts = real_document_kb.facts

    fact_content_projection = [
        {
            "fact_id": fact.fact_id,
            "title": fact.title,
            "text": fact.text,
            "source_pages": fact.source_pages,
            "section_path": fact.section_path,
        }
        for fact in facts
    ]
    fact_content_sha256 = hashlib.sha256(
        json.dumps(fact_content_projection, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    units_by_fact = {unit.fact_id: unit for unit in real_document_kb.retrieval_units}
    fact_structure_projection = [
        {
            "fact_id": fact.fact_id,
            "unit_id": units_by_fact[fact.fact_id].unit_id,
            "source_pages": fact.source_pages,
            "section_path": fact.section_path,
            "scope_type": fact.scope_type,
            "scope_targets": fact.scope_targets,
            "parent_college": fact.parent_college,
        }
        for fact in facts
    ]
    fact_structure_sha256 = hashlib.sha256(
        json.dumps(fact_structure_projection, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()

    assert real_document_kb.diagnostics.quality_gate.passed
    assert benchmark.document_id == real_document_kb.manifest.document_id
    assert benchmark.source_pdf_sha256 == real_document_kb.manifest.pdf_sha256
    assert benchmark.source_pdf_sha256 == real_pdf_manifest["sha256"]
    assert benchmark.expected_kb_schema_version == real_document_kb.manifest.schema_version
    assert benchmark.fact_content_sha256 == fact_content_sha256
    assert benchmark.fact_content_sha256 == expected["fact_content_sha256"]
    assert benchmark.fact_structure_sha256 == fact_structure_sha256
    assert benchmark.fact_structure_sha256 == expected["fact_structure_sha256"]

    facts_by_id = {fact.fact_id: fact for fact in facts}
    assert len(facts_by_id) == len(facts)
    for query in benchmark.queries:
        assert [evidence.fact_id for evidence in query.gold_evidence] == query.relevant_fact_ids
        for evidence in query.gold_evidence:
            fact = facts_by_id[evidence.fact_id]
            assert fact.source_pages
            assert evidence.source_pages == fact.source_pages
            assert evidence.scope_type == fact.scope_type
            assert evidence.scope_targets == fact.scope_targets
            assert all(1 <= page <= expected["page_count"] for page in evidence.source_pages)

    resolved_pairs = {
        (claim.source_fact_id, claim.selected_target_fact_id)
        for claim in real_document_kb.diagnostics.reference_claims
        if claim.status == "resolved"
    }
    for query in benchmark.queries:
        if query.requires_reference_expansion:
            gold_ids = set(query.relevant_fact_ids)
            assert any(
                source in gold_ids and target in gold_ids for source, target in resolved_pairs
            )


def test_real_pdf_lexical_retrieval_characterization(
    real_document_kb: DocumentKnowledgeBase,
) -> None:
    benchmark = load_retrieval_benchmark(RETRIEVAL_BENCHMARK_PATH)
    payloads = derive_index_payloads(real_document_kb)
    payload_snapshot = [payload.model_dump(mode="json") for payload in payloads]
    searcher = build_lexical_searcher(payloads)
    results = {
        query.query_id: searcher.search(query.query, top_k=10) for query in benchmark.queries
    }

    assert len(results) == 34
    top_five_hits = 0
    top_ten_hits = 0
    hits_by_style: dict[str, list[int]] = {}
    top_five_misses: list[str] = []
    for query in benchmark.queries:
        result = results[query.query_id]
        top_five_fact_ids = {hit.fact_id for hit in result.hits[:5]}
        top_ten_fact_ids = {hit.fact_id for hit in result.hits}
        hit_at_five = bool(top_five_fact_ids.intersection(query.relevant_fact_ids))
        hit_at_ten = bool(top_ten_fact_ids.intersection(query.relevant_fact_ids))
        top_five_hits += hit_at_five
        top_ten_hits += hit_at_ten
        style_counts = hits_by_style.setdefault(query.query_style, [0, 0, 0])
        style_counts[0] += 1
        style_counts[1] += hit_at_five
        style_counts[2] += hit_at_ten
        if not hit_at_five:
            top_five_misses.append(query.query_id)
        if query.query_style in {"exact_term", "identifier"}:
            assert hit_at_ten, query.query_id
        assert all(hit.source_pages and hit.section_path for hit in result.hits)
        assert all(hit.fact_id in {payload.fact_id for payload in payloads} for hit in result.hits)

    assert (top_five_hits, top_ten_hits) == (32, 34)
    assert hits_by_style == {
        "exact_term": [7, 6, 7],
        "identifier": [6, 5, 6],
        "paraphrase": [21, 21, 21],
    }
    assert top_five_misses == ["rq:0010", "rq:0019"]
    assert [payload.model_dump(mode="json") for payload in payloads] == payload_snapshot
