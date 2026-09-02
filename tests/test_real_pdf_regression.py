from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from jgrad_admission_rag.cli import build_index as build_index_cli
from jgrad_admission_rag.cli import evaluate_retrieval as evaluate_retrieval_cli
from jgrad_admission_rag.cli import search as search_cli
from jgrad_admission_rag.builder.chunk_filter import classify_chunk
from jgrad_admission_rag.builder.chunker import chunk_pages
from jgrad_admission_rag.builder.extractor import ExtractedPage, extract_pdf
from jgrad_admission_rag.builder.kb_builder import build_document_kb, pages_to_source_pages
from jgrad_admission_rag.evaluation.retrieval_queries import load_retrieval_benchmark
from jgrad_admission_rag.evaluation.retrieval_evaluation import (
    canonical_retrieval_evaluation_bytes,
    evaluate_retrieval,
    load_retrieval_evaluation_bytes,
)
from jgrad_admission_rag.retrieval.embedding import (
    DeterministicFakeEmbeddingProvider,
    embed_documents_checked,
    embed_query_checked,
)
from jgrad_admission_rag.retrieval.embedding_text import EMBEDDING_TEXT_VERSION
from jgrad_admission_rag.retrieval.evidence_pack import build_evidence_pack
from jgrad_admission_rag.retrieval.hybrid_search import (
    fuse_ranked_hits,
    search_hybrid_index,
)
from jgrad_admission_rag.retrieval.local_index import build_local_index, load_local_index
from jgrad_admission_rag.retrieval.index_freshness import load_fresh_index_context
from jgrad_admission_rag.retrieval.lexical_search import build_lexical_searcher
from jgrad_admission_rag.retrieval.metadata_search import (
    MetadataFilter,
    ScopePreference,
    derive_eligible_rows,
    search_metadata_index,
)
from jgrad_admission_rag.retrieval.vector_search import search_loaded_index, search_local_index
from jgrad_admission_rag.retrieval.reference_expansion import expand_references
from jgrad_admission_rag.reasoning.applicability import (
    ApplicabilityRule,
    OfficialEvidenceBinding,
    evaluate_applicability,
)
from jgrad_admission_rag.reasoning.applicant_profile import ApplicantProfile
from jgrad_admission_rag.reasoning.query_intent import (
    DiagnosticCode,
    QueryIntent,
    RequestedScope,
)
from jgrad_admission_rag.schemas.document_kb import DocumentKnowledgeBase
from jgrad_admission_rag.schemas.evidence_pack import (
    EvidenceCounts,
    EvidenceMetadataFilter,
    canonical_evidence_pack_bytes,
    EvidencePack,
    EvidenceRequest,
    EvidenceRuntime,
    EvidenceScopePreference,
    PrimaryEvidence,
    load_evidence_pack_bytes,
)
from jgrad_admission_rag.schemas.index import derive_index_payloads
from jgrad_admission_rag.utils import sha256_file

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "tests" / "fixtures" / "real_pdf_manifest.json"
RETRIEVAL_BENCHMARK_PATH = REPO_ROOT / "tests" / "fixtures" / "retrieval_queries_v1.json"
APPLICABILITY_FIXTURE_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "applicability_real_scenarios_v1.json"
)
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


def test_real_pdf_reviewed_applicability_scenarios(
    real_document_kb: DocumentKnowledgeBase,
) -> None:
    fixture = json.loads(APPLICABILITY_FIXTURE_PATH.read_text(encoding="utf-8"))
    fact_fixture = fixture["fact"]
    fact = next(
        candidate
        for candidate in real_document_kb.facts
        if candidate.fact_id == fact_fixture["fact_id"]
    )
    assert fact.source_pages == fact_fixture["source_pages"]
    assert (
        hashlib.sha256(fact.embedding_text.encode("utf-8")).hexdigest()
        == fact_fixture["fact_text_sha256"]
    )

    query = "出願資格審査の年齢条件"
    intent = QueryIntent(
        schema_version="1.0",
        parser_version="lexical-ja-v1",
        catalog_version="real-fixture-v1",
        query=query,
        requested_categories=(),
        requested_scope=RequestedScope(
            department_or_program_targets=(),
            parent_college_values=(),
            target_degree_level=None,
            intake_year=None,
            intake_month=None,
        ),
        matched_mentions=(),
        diagnostics=(DiagnosticCode.NO_RECOGNIZED_INTENT,),
    )
    pack = _real_applicability_pack(query, real_document_kb, fact, fixture)
    binding = OfficialEvidenceBinding(
        document_id=fixture["document_id"],
        source_kb_sha256=fixture["source_kb_sha256"],
        source_pdf_sha256=fixture["source_pdf_sha256"],
        fact_id=fact.fact_id,
        source_pages=tuple(fact.source_pages),
        fact_text_sha256=fact_fixture["fact_text_sha256"],
    )
    rule = ApplicabilityRule.model_validate(
        {
            **fixture["rule"],
            "schema_version": "1.0",
            "evidence_bindings": [binding.model_dump(mode="json")],
        }
    )

    actual = {}
    for scenario in fixture["scenarios"]:
        profile = _real_applicability_profile(
            scenario["age_at_enrollment"], fixture["rule"]["scope"]
        )
        decision = evaluate_applicability(profile, intent, pack, rule)
        actual[scenario["scenario_id"]] = {
            "status": decision.status.value,
            "diagnostics": [value.value for value in decision.diagnostics],
            "pages": [list(reference.source_pages) for reference in decision.official_evidence],
        }

    assert actual == {
        scenario["scenario_id"]: {
            "status": scenario["expected_status"],
            "diagnostics": scenario["expected_diagnostics"],
            "pages": [fact_fixture["source_pages"]],
        }
        for scenario in fixture["scenarios"]
    }


def _real_applicability_profile(age: int | None, scope: dict[str, Any]) -> ApplicantProfile:
    return ApplicantProfile.model_validate(
        {
            "schema_version": "1.0",
            "target_application": {
                "graduate_school_or_college": scope["parent_college"],
                "department_or_program": scope["scope_targets"][0],
                "requested_degree_level": "professional",
                "intake_year": 2027,
                "intake_month": 4,
                "application_route": "individual eligibility review",
            },
            "citizenship_and_residence": {
                "citizenship_country_codes": None,
                "current_residence_country_code": None,
                "residence_status_category": None,
            },
            "academic_credentials": None,
            "eligibility_facts": {
                "age_at_enrollment": age,
                "professional_experience_months": None,
                "research_experience_months": None,
                "individual_review_status": "completed",
                "individual_review_requested": True,
                "individual_review_completed": True,
            },
            "language_test_results": None,
        }
    )


def _real_applicability_pack(
    query: str,
    kb: DocumentKnowledgeBase,
    fact: Any,
    fixture: dict[str, Any],
) -> EvidencePack:
    fact_index = int(fact.fact_id.split(":")[1])
    primary = PrimaryEvidence(
        primary_rank=1,
        ranking_score=2 / 61,
        fused_score=2 / 61,
        scope_boost_total=0.0,
        fusion_version="rrf-v1",
        vector_rank=1,
        vector_score=1.0,
        lexical_rank=1,
        lexical_score=1.0,
        matched_channels=("vector", "lexical"),
        row_index=fact_index,
        document_id=fixture["document_id"],
        unit_id=f"unit:{fact_index:05d}",
        fact_id=fact.fact_id,
        text=fact.embedding_text,
        source_pages=tuple(fact.source_pages),
        section_path=tuple(fact.section_path),
        fact_type=fact.fact_type,
        scope_type=fact.scope_type,
        scope_targets=tuple(fact.scope_targets),
        parent_college=fact.parent_college,
        metadata={"embedding_text_version": "1"},
    )
    runtime = EvidenceRuntime(
        document_id=fixture["document_id"],
        source_kb_sha256=fixture["source_kb_sha256"],
        source_pdf_sha256=fixture["source_pdf_sha256"],
        index_schema_version="0.1",
        source_kb_schema_version="0.5",
        payloads_sha256="c" * 64,
        vectors_sha256="d" * 64,
        index_builder_version="0.1.0",
        embedding_provider="deterministic-fake",
        embedding_model="sha256-counter-v1",
        embedding_dimension=8,
        distance_metric="cosine",
        semantic=False,
        lexical_tokenizer_version="nfkc-casefold-ja23-v1",
        lexical_scoring_version="bm25-v1",
        fusion_version="rrf-v1",
        rrf_k=60,
        metadata_filter_version="exact-metadata-v1",
        scope_rerank_version="scope-match-v1",
        scope_target_match_boost=0.0,
        parent_college_match_boost=0.0,
        reference_expansion_version="reference-one-hop-v1",
        reference_expansion_depth=1,
        corpus_row_count=len(kb.facts),
        eligible_row_count=len(kb.facts),
        vector_candidate_count=1,
        lexical_candidate_count=1,
    )
    return EvidencePack(
        request=EvidenceRequest(
            query=query,
            top_k_requested=1,
            candidate_k_requested=1,
            candidate_k_resolved=1,
            metadata_filter=EvidenceMetadataFilter(),
            scope_preference=EvidenceScopePreference(),
        ),
        runtime=runtime,
        primary_evidence=(primary,),
        attached_reference_evidence=(),
        resolved_relations=(),
        reference_warnings=(),
        counts=EvidenceCounts(
            primary_evidence_count=1,
            attached_evidence_count=0,
            resolved_relation_count=0,
            warning_count=0,
            warning_status_counts={"ambiguous": 0, "unresolved": 0},
            unique_evidence_count=1,
        ),
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


def test_real_pdf_fake_hybrid_plumbing_is_stable_and_cli_equivalent(
    tmp_path: Path,
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
    benchmark_bytes = RETRIEVAL_BENCHMARK_PATH.read_bytes()
    kb_bytes = kb_path.read_bytes()
    index_dir = tmp_path / "fake-index"
    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    build_local_index(kb_path, index_dir, provider)
    index_bytes = {path.name: path.read_bytes() for path in index_dir.iterdir()}
    index = load_local_index(index_dir, mmap=True)
    vectors_before = np.array(index.vectors, copy=True)
    payloads_before = [payload.model_dump(mode="json") for payload in index.payloads]
    lexical_searcher = build_lexical_searcher(index)
    benchmark = load_retrieval_benchmark(RETRIEVAL_BENCHMARK_PATH)
    characterization: list[dict[str, object]] = []
    aggregate: dict[str, dict[str, list[int]]] = {"style": {}, "category": {}}
    first_hybrid = None

    for query in benchmark.queries:
        vector = search_loaded_index(index, query.query, provider, top_k=50)
        lexical = lexical_searcher.search(query.query, top_k=50)
        hybrid = fuse_ranked_hits(
            index,
            vector.hits,
            lexical.hits,
            top_k=10,
            candidate_k=50,
        )
        if first_hybrid is None:
            first_hybrid = hybrid
        gold = set(query.relevant_fact_ids)

        row: dict[str, object] = {"query_id": query.query_id}
        for channel, hits in (
            ("vector", vector.hits),
            ("lexical", lexical.hits),
            ("hybrid", hybrid.hits),
        ):
            top_five = [hit.fact_id for hit in hits[:5] if hit.fact_id in gold]
            top_ten = [hit.fact_id for hit in hits[:10] if hit.fact_id in gold]
            row[f"{channel}_top5"] = top_five
            row[f"{channel}_top10"] = top_ten
            for dimension, value in (
                ("style", query.query_style),
                ("category", query.category),
            ):
                counts = aggregate[dimension].setdefault(f"{value}:{channel}", [0, 0, 0])
                counts[0] += 1
                counts[1] += bool(top_five)
                counts[2] += bool(top_ten)
        characterization.append(row)

        assert hybrid.fusion_version == "rrf-v1"
        assert hybrid.rrf_k == 60
        assert hybrid.candidate_k_resolved == 50
        assert hybrid.vector_candidate_count == 50
        assert 0 < hybrid.lexical_candidate_count <= 50
        assert all(hit.source_pages and hit.section_path for hit in hybrid.hits)

    characterization_sha256 = hashlib.sha256(
        json.dumps(characterization, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    aggregate_sha256 = hashlib.sha256(
        json.dumps(aggregate, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert characterization_sha256 == (
        "27a3e6c783af2ea373b3fb0b304cd20d065e5bd3183e613f085bbe34d17d5689"
    )
    assert aggregate_sha256 == ("1579c88ad3ffa30eafb8e28778f9df1b360e98f8cdd0e927cecf070dffeba4a2")

    first_query = benchmark.queries[0]
    search_cli.main(
        [
            str(index_dir),
            "--current-kb",
            str(kb_path),
            "--query",
            first_query.query,
            "--top-k",
            "10",
            "--retrieval-mode",
            "hybrid",
            "--candidate-k",
            "50",
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
    assert summary["results"] == [hit.to_dict() for hit in first_hybrid.hits]
    assert np.array_equal(index.vectors, vectors_before)
    assert [payload.model_dump(mode="json") for payload in index.payloads] == payloads_before
    assert kb_path.read_bytes() == kb_bytes
    assert RETRIEVAL_BENCHMARK_PATH.read_bytes() == benchmark_bytes
    assert {path.name: path.read_bytes() for path in index_dir.iterdir()} == index_bytes


def test_real_pdf_metadata_inventory_and_hard_filter_examples(
    real_document_kb: DocumentKnowledgeBase,
) -> None:
    payloads = derive_index_payloads(real_document_kb)
    fact_type_counts: dict[str, int] = {}
    scope_type_counts: dict[str, int] = {}
    target_counts: dict[str, int] = {}
    college_counts: dict[str, int] = {}
    for payload in payloads:
        fact_type_counts[payload.fact_type] = fact_type_counts.get(payload.fact_type, 0) + 1
        scope_type_counts[payload.scope_type] = scope_type_counts.get(payload.scope_type, 0) + 1
        for target in payload.scope_targets:
            target_counts[target] = target_counts.get(target, 0) + 1
        college = payload.parent_college or "<none>"
        college_counts[college] = college_counts.get(college, 0) + 1

    assert len(payloads) == 298
    assert fact_type_counts == {
        "documents": 17,
        "english": 27,
        "exams": 73,
        "fees": 13,
        "general": 150,
        "methods": 8,
        "periods": 10,
    }
    assert scope_type_counts == {"department": 126, "global": 2, "unknown": 170}
    assert target_counts == {
        "システム制御系": 18,
        "化学系": 22,
        "土木・環境工学系": 12,
        "地球惑星科学系": 9,
        "建築学系": 14,
        "応用化学系": 17,
        "情報工学系": 14,
        "情報通信系": 10,
        "技術経営専門職学位課程": 15,
        "数学系": 19,
        "数理・計算科学系": 13,
        "材料系": 26,
        "機械系": 18,
        "物理学系": 11,
        "生命理工学系": 24,
        "社会・人間科学系": 13,
        "経営工学系": 13,
        "融合理工学系": 25,
        "電気電子系": 21,
    }
    assert college_counts == {
        "<none>": 172,
        "工学院": 33,
        "情報理工学院": 6,
        "物質理工学院": 13,
        "理学院": 41,
        "環境・社会理工学院": 23,
        "生命理工学院": 10,
    }

    examples = (
        (MetadataFilter(fact_types=("english",)), 27),
        (MetadataFilter(scope_types=("department",)), 126),
        (MetadataFilter(scope_targets=("情報工学系",)), 14),
        (MetadataFilter(parent_colleges=("情報理工学院",)), 6),
        (
            MetadataFilter(
                fact_types=("english",),
                scope_types=("department",),
                scope_targets=("情報工学系",),
                parent_colleges=("情報理工学院",),
            ),
            1,
        ),
        (MetadataFilter(fact_types=("not-present",)), 0),
    )
    for metadata_filter, expected_count in examples:
        rows = derive_eligible_rows(payloads, metadata_filter)
        assert len(rows) == expected_count
        for row in rows:
            payload = payloads[row]
            assert not metadata_filter.fact_types or payload.fact_type in metadata_filter.fact_types
            assert (
                not metadata_filter.scope_types or payload.scope_type in metadata_filter.scope_types
            )
            assert not metadata_filter.scope_targets or set(payload.scope_targets).intersection(
                metadata_filter.scope_targets
            )
            assert not metadata_filter.parent_colleges or (
                payload.parent_college in metadata_filter.parent_colleges
            )


def test_real_pdf_metadata_no_filter_and_scope_sensitive_characterization(
    tmp_path: Path,
    real_document_kb: DocumentKnowledgeBase,
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
    index_dir = tmp_path / "fake-index"
    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    build_local_index(kb_path, index_dir, provider)
    index = load_local_index(index_dir, mmap=True)
    lexical = build_lexical_searcher(index)
    benchmark = load_retrieval_benchmark(RETRIEVAL_BENCHMARK_PATH)
    all_rows = tuple(range(len(index.payloads)))
    scope_outcomes: list[dict[str, object]] = []

    hard_filter_examples = (
        (MetadataFilter(fact_types=("english",)), 27),
        (MetadataFilter(scope_types=("department",)), 126),
        (MetadataFilter(scope_targets=("情報工学系",)), 14),
        (MetadataFilter(parent_colleges=("情報理工学院",)), 6),
        (
            MetadataFilter(
                fact_types=("english",),
                scope_types=("department",),
                scope_targets=("情報工学系",),
                parent_colleges=("情報理工学院",),
            ),
            1,
        ),
        (MetadataFilter(fact_types=("not-present",)), 0),
    )
    for metadata_filter, expected_eligible in hard_filter_examples:
        filtered = search_metadata_index(
            index,
            "出願資格",
            provider,
            metadata_filter=metadata_filter,
            top_k=10,
            candidate_k=50,
        )
        assert filtered.eligible_row_count == expected_eligible
        for hit in filtered.hits:
            assert not metadata_filter.fact_types or hit.fact_type in metadata_filter.fact_types
            assert not metadata_filter.scope_types or hit.scope_type in metadata_filter.scope_types
            assert not metadata_filter.scope_targets or set(hit.scope_targets).intersection(
                metadata_filter.scope_targets
            )
            assert not metadata_filter.parent_colleges or (
                hit.parent_college in metadata_filter.parent_colleges
            )

    full_preference = search_metadata_index(
        index,
        "出願資格",
        provider,
        scope_preference=ScopePreference(
            preferred_scope_targets=("情報工学系",),
            preferred_parent_colleges=("情報理工学院",),
        ),
        top_k=298,
        candidate_k=298,
    )
    assert len(full_preference.hits) == 298
    assert full_preference.eligible_row_count == 298
    both = next(
        hit
        for hit in full_preference.hits
        if hit.matched_preferences == ("scope_target", "parent_college")
    )
    college_only = next(
        hit for hit in full_preference.hits if hit.matched_preferences == ("parent_college",)
    )
    global_hit = next(hit for hit in full_preference.hits if hit.scope_type == "global")
    unknown_hit = next(hit for hit in full_preference.hits if hit.scope_type == "unknown")
    assert both.scope_boost_total == pytest.approx(1.5 / 61)
    assert college_only.scope_boost_total == pytest.approx(0.5 / 61)
    assert global_hit.scope_boost_total == unknown_hit.scope_boost_total == 0.0
    assert global_hit.ranking_score == global_hit.fused_score
    assert unknown_hit.ranking_score == unknown_hit.fused_score

    for query in benchmark.queries:
        vector_base = search_loaded_index(index, query.query, provider, top_k=50)
        vector_all = search_loaded_index(
            index, query.query, provider, top_k=50, eligible_rows=all_rows
        )
        lexical_base = lexical.search(query.query, top_k=50)
        lexical_all = lexical.search(query.query, top_k=50, eligible_rows=all_rows)
        hybrid_base = search_hybrid_index(index, query.query, provider, top_k=10, candidate_k=50)
        metadata_base = search_metadata_index(
            index, query.query, provider, top_k=10, candidate_k=50
        )

        assert [hit.to_dict() for hit in vector_all.hits] == [
            hit.to_dict() for hit in vector_base.hits
        ]
        assert [hit.to_dict() for hit in lexical_all.hits] == [
            hit.to_dict() for hit in lexical_base.hits
        ]
        assert [hit.row_index for hit in metadata_base.hits] == [
            hit.row_index for hit in hybrid_base.hits
        ]
        assert [hit.fused_score for hit in metadata_base.hits] == [
            hit.fused_score for hit in hybrid_base.hits
        ]
        assert [hit.vector_score for hit in metadata_base.hits] == [
            hit.vector_score for hit in hybrid_base.hits
        ]
        assert [hit.lexical_score for hit in metadata_base.hits] == [
            hit.lexical_score for hit in hybrid_base.hits
        ]

        if not query.scope_sensitive:
            continue
        preferred_targets = tuple(
            sorted(
                {target for evidence in query.gold_evidence for target in evidence.scope_targets}
            )
        )
        assert preferred_targets
        preferred = search_metadata_index(
            index,
            query.query,
            provider,
            scope_preference=ScopePreference(preferred_scope_targets=preferred_targets),
            top_k=10,
            candidate_k=50,
        )
        gold = set(query.relevant_fact_ids)
        scope_outcomes.append(
            {
                "query_id": query.query_id,
                "preferred_scope_targets": preferred_targets,
                "base_top5": [hit.fact_id for hit in hybrid_base.hits[:5] if hit.fact_id in gold],
                "base_top10": [hit.fact_id for hit in hybrid_base.hits if hit.fact_id in gold],
                "preferred_top5": [
                    hit.fact_id for hit in preferred.hits[:5] if hit.fact_id in gold
                ],
                "preferred_top10": [hit.fact_id for hit in preferred.hits if hit.fact_id in gold],
                "boosted": [
                    {
                        "fact_id": hit.fact_id,
                        "before_rank": next(
                            (
                                base_hit.rank
                                for base_hit in hybrid_base.hits
                                if base_hit.fact_id == hit.fact_id
                            ),
                            None,
                        ),
                        "after_rank": hit.rank,
                        "scope_boost_total": hit.scope_boost_total,
                    }
                    for hit in preferred.hits
                    if hit.scope_boost_total > 0
                ],
            }
        )

    assert len(scope_outcomes) == 9
    outcome_sha256 = hashlib.sha256(
        json.dumps(scope_outcomes, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert outcome_sha256 == ("63435b491631a3af506e8b17e70ef6248e4302e75a02b2e4a26cfb1c505aeee4")


def test_real_pdf_reference_expansion_preserves_authoritative_diagnostics(
    tmp_path: Path,
    real_document_kb: DocumentKnowledgeBase,
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
    index_dir = tmp_path / "fake-index"
    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    build_local_index(kb_path, index_dir, provider)
    index = load_local_index(index_dir, mmap=True)
    context = load_fresh_index_context(index, kb_path, provider.identity)

    all_hits = search_metadata_index(
        index,
        "出願資格",
        provider,
        top_k=298,
        candidate_k=298,
    ).hits
    all_expansion = expand_references(index, context, all_hits)

    assert all_expansion.authoritative_claim_count == 141
    assert all_expansion.authoritative_status_counts == {
        "resolved": 7,
        "ambiguous": 6,
        "unresolved": 128,
    }
    assert all_expansion.expanded_claim_count == 141
    assert all_expansion.expanded_status_counts == all_expansion.authoritative_status_counts
    assert all_expansion.disposition_counts == {
        "attached_target": 0,
        "already_primary": 7,
        "ambiguous": 6,
        "unresolved": 128,
    }
    assert all_expansion.resolved_relation_count == 7
    assert all_expansion.unique_expanded_target_count == 0
    assert all_expansion.expanded_targets == ()
    visible_claims = [
        claim for candidate in all_expansion.candidate_expansions for claim in candidate.claims
    ]
    assert len(visible_claims) == 141
    assert all(
        claim.target_row_index is None and claim.already_primary_rank is None
        for claim in visible_claims
        if claim.status != "resolved"
    )

    source_fact_ids = ("fact:00057", "fact:00064")
    source_hits = tuple(
        replace(next(hit for hit in all_hits if hit.fact_id == fact_id), rank=rank)
        for rank, fact_id in enumerate(source_fact_ids, start=1)
    )
    query_expansion = expand_references(index, context, source_hits)
    assert [target.fact_id for target in query_expansion.expanded_targets] == [
        "fact:00058",
        "fact:00059",
        "fact:00065",
        "fact:00066",
    ]
    resolved_pairs = {
        (claim.source_fact_id, claim.selected_target_fact_id)
        for candidate in query_expansion.candidate_expansions
        for claim in candidate.claims
        if claim.status == "resolved"
    }
    assert ("fact:00057", "fact:00059") in resolved_pairs
    assert ("fact:00064", "fact:00066") in resolved_pairs


def test_real_pdf_builds_34_canonical_evidence_packs_with_official_evidence(
    tmp_path: Path,
    real_document_kb: DocumentKnowledgeBase,
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
    index_dir = tmp_path / "fake-index"
    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    build_local_index(kb_path, index_dir, provider)
    index = load_local_index(index_dir, mmap=True)
    context = load_fresh_index_context(index, kb_path, provider.identity)
    benchmark = load_retrieval_benchmark(RETRIEVAL_BENCHMARK_PATH)
    payload_by_fact = {payload.fact_id: payload for payload in index.payloads}
    ordered_bytes: list[bytes] = []
    kb_before = real_document_kb.model_dump(mode="json")
    benchmark_before = RETRIEVAL_BENCHMARK_PATH.read_bytes()
    index_before = {path.name: path.read_bytes() for path in index_dir.iterdir()}

    for query in benchmark.queries:
        preference = ScopePreference()
        if query.scope_sensitive:
            preference = ScopePreference(
                preferred_scope_targets=tuple(
                    sorted(
                        {
                            target
                            for evidence in query.gold_evidence
                            for target in evidence.scope_targets
                        }
                    )
                )
            )
        result = search_metadata_index(
            index,
            query.query,
            provider,
            scope_preference=preference,
            top_k=10,
            candidate_k=50,
        )
        expansion = expand_references(index, context, result.hits)
        result_before = result.to_dict()
        expansion_before = expansion.to_dict()
        pack = build_evidence_pack(query.query, result, expansion)
        canonical = canonical_evidence_pack_bytes(pack)
        repeated = canonical_evidence_pack_bytes(
            build_evidence_pack(query.query, result, expansion)
        )

        assert canonical == repeated
        assert canonical_evidence_pack_bytes(load_evidence_pack_bytes(canonical)) == canonical
        assert result.to_dict() == result_before
        assert expansion.to_dict() == expansion_before
        assert pack.counts.primary_evidence_count == len(result.hits)
        assert pack.counts.attached_evidence_count == len(expansion.expanded_targets)
        assert pack.counts.resolved_relation_count == expansion.resolved_relation_count
        assert pack.counts.warning_count == (
            expansion.expanded_status_counts["ambiguous"]
            + expansion.expanded_status_counts["unresolved"]
        )
        for evidence in (*pack.primary_evidence, *pack.attached_reference_evidence):
            payload = payload_by_fact[evidence.fact_id]
            assert (
                evidence.row_index,
                evidence.document_id,
                evidence.unit_id,
                evidence.text,
                evidence.source_pages,
                evidence.section_path,
                evidence.fact_type,
                evidence.scope_type,
                evidence.scope_targets,
                evidence.parent_college,
                evidence.metadata,
            ) == (
                payload.row_index,
                payload.document_id,
                payload.unit_id,
                payload.text,
                tuple(payload.source_pages),
                tuple(payload.section_path),
                payload.fact_type,
                payload.scope_type,
                tuple(payload.scope_targets),
                payload.parent_college,
                payload.metadata,
            )
        ordered_bytes.append(canonical)

    assert len(ordered_bytes) == 34
    aggregate_sha256 = hashlib.sha256(b"".join(ordered_bytes)).hexdigest()
    assert aggregate_sha256 == "0c2b10c1a68496a9154c9bdf8cf209d2cd0e22507f1c1a9bb7c92383af974f6f"
    assert real_document_kb.model_dump(mode="json") == kb_before
    assert RETRIEVAL_BENCHMARK_PATH.read_bytes() == benchmark_before
    assert {path.name: path.read_bytes() for path in index_dir.iterdir()} == index_before
    assert index.vectors.flags.writeable is False


def test_real_pdf_fake_retrieval_evaluation_is_deterministic_and_independently_scored(
    tmp_path: Path,
    real_document_kb: DocumentKnowledgeBase,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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
    index_dir = tmp_path / "fake-index"
    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    build_local_index(kb_path, index_dir, provider)
    index = load_local_index(index_dir, mmap=True)
    context = load_fresh_index_context(index, kb_path, provider.identity)
    benchmark = load_retrieval_benchmark(RETRIEVAL_BENCHMARK_PATH)
    kb_before = real_document_kb.model_dump(mode="json")
    benchmark_before = RETRIEVAL_BENCHMARK_PATH.read_bytes()
    index_before = {path.name: path.read_bytes() for path in index_dir.iterdir()}
    packs = []

    for query in benchmark.queries:
        result = search_metadata_index(
            index,
            query.query,
            provider,
            metadata_filter=MetadataFilter(),
            scope_preference=ScopePreference(),
            top_k=10,
            candidate_k=50,
        )
        expansion = expand_references(index, context, result.hits)
        packs.append(build_evidence_pack(query.query, result, expansion))

    report = evaluate_retrieval(benchmark, context.knowledge_base, index, tuple(packs))
    canonical = canonical_retrieval_evaluation_bytes(report)
    loaded = load_retrieval_evaluation_bytes(canonical)

    assert len(report.queries) == 34
    assert report.quality.semantic_evaluation is False
    assert report.quality.quality_eligible is False
    assert report.quality.gate_status == "not_evaluated"
    assert canonical_retrieval_evaluation_bytes(loaded) == canonical
    assert canonical_retrieval_evaluation_bytes(report) == canonical

    for query, result in zip(report.queries, benchmark.queries, strict=True):
        ranked = [item.fact_id for item in query.ranked_primary_facts]
        gold = set(result.relevant_fact_ids)
        relevant_ranks = [rank for rank, fact_id in enumerate(ranked, start=1) if fact_id in gold]
        expected_first = min(relevant_ranks) if relevant_ranks else None
        assert query.first_relevant_rank == expected_first
        assert query.reciprocal_rank == (1.0 / expected_first if expected_first else 0.0)
        for depth, actual in zip((1, 3, 5, 10), query.recall.ordered(), strict=True):
            assert actual == len(gold.intersection(ranked[:depth])) / len(gold)

    assert hashlib.sha256(canonical).hexdigest() == (
        "0fef7dfa6bdc7e43eccad6cb1c3b3f5f90e187416fdf12993fc699a6d77e4c75"
    )

    class RecordingProvider:
        def __init__(self) -> None:
            self.delegate = DeterministicFakeEmbeddingProvider(dimension=8)
            self.query_texts: list[str] = []

        @property
        def identity(self):
            return self.delegate.identity

        def embed_query(self, text: str):
            self.query_texts.append(text)
            return self.delegate.embed_query(text)

    recording_provider = RecordingProvider()
    loads = {"index": 0, "freshness": 0, "benchmark": 0, "provider": 0}
    original_load_index = evaluate_retrieval_cli.load_local_index
    original_load_freshness = evaluate_retrieval_cli.load_fresh_index_context
    original_load_benchmark = evaluate_retrieval_cli.load_evaluation_benchmark

    def load_index_once(path, *, mmap):
        loads["index"] += 1
        return original_load_index(path, mmap=mmap)

    def load_freshness_once(loaded_index, path, identity):
        loads["freshness"] += 1
        return original_load_freshness(loaded_index, path, identity)

    def load_benchmark_once(path):
        loads["benchmark"] += 1
        return original_load_benchmark(path)

    def create_provider_once(configuration):
        loads["provider"] += 1
        assert configuration.identity == recording_provider.identity
        return recording_provider

    monkeypatch.setattr(evaluate_retrieval_cli, "load_local_index", load_index_once)
    monkeypatch.setattr(
        evaluate_retrieval_cli,
        "load_fresh_index_context",
        load_freshness_once,
    )
    monkeypatch.setattr(
        evaluate_retrieval_cli,
        "load_evaluation_benchmark",
        load_benchmark_once,
    )
    monkeypatch.setattr(evaluate_retrieval_cli, "create_provider", create_provider_once)

    evaluate_retrieval_cli.main(
        [
            str(index_dir),
            "--current-kb",
            str(kb_path),
            "--benchmark",
            str(RETRIEVAL_BENCHMARK_PATH),
            "--provider",
            "deterministic-fake",
            "--dimension",
            "8",
        ]
    )
    captured = capsys.readouterr()

    assert captured.err == ""
    assert captured.out.encode("utf-8") == canonical
    assert loads == {"index": 1, "freshness": 1, "benchmark": 1, "provider": 1}
    assert recording_provider.query_texts == [query.query for query in benchmark.queries]
    assert real_document_kb.model_dump(mode="json") == kb_before
    assert RETRIEVAL_BENCHMARK_PATH.read_bytes() == benchmark_before
    assert {path.name: path.read_bytes() for path in index_dir.iterdir()} == index_before
    assert index.vectors.flags.writeable is False


def test_real_pdf_rq0012_evidence_pack_exposes_resolved_targets_without_answers(
    tmp_path: Path,
    real_document_kb: DocumentKnowledgeBase,
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
    index_dir = tmp_path / "fake-index"
    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    build_local_index(kb_path, index_dir, provider)
    index = load_local_index(index_dir, mmap=True)
    context = load_fresh_index_context(index, kb_path, provider.identity)
    benchmark = load_retrieval_benchmark(RETRIEVAL_BENCHMARK_PATH)
    query = next(query for query in benchmark.queries if query.query_id == "rq:0012")
    full = search_metadata_index(
        index,
        query.query,
        provider,
        top_k=298,
        candidate_k=298,
    )
    source_fact_ids = ("fact:00057", "fact:00064")
    source_hits = tuple(
        replace(next(hit for hit in full.hits if hit.fact_id == fact_id), rank=rank)
        for rank, fact_id in enumerate(source_fact_ids, start=1)
    )
    result = replace(full, top_k_requested=2, hits=source_hits)
    expansion = expand_references(index, context, result.hits)
    pack = build_evidence_pack(query.query, result, expansion)

    assert [evidence.fact_id for evidence in pack.primary_evidence] == list(source_fact_ids)
    assert [evidence.fact_id for evidence in pack.attached_reference_evidence] == [
        "fact:00058",
        "fact:00059",
        "fact:00065",
        "fact:00066",
    ]
    relation_pairs = {
        (relation.source_fact_id, relation.selected_target_fact_id)
        for relation in pack.resolved_relations
    }
    assert ("fact:00057", "fact:00059") in relation_pairs
    assert ("fact:00064", "fact:00066") in relation_pairs
    assert not hasattr(pack, "answer")
    assert not hasattr(pack, "applicant_profile")
