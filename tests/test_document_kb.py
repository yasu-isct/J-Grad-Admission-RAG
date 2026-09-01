from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    BuildQualityThresholds,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    ReferenceDiagnostic,
    RetrievalUnit,
    ScopedFact,
)


def test_document_kb_schema_roundtrip() -> None:
    fact = ScopedFact(
        fact_id="fact:00001",
        fact_type="fees",
        scope_type="global",
        title="検定料",
        text="検定料は30,000円です。",
        source_pages=[10],
        section_path=["３．出願手続", "（１）検定料"],
        embedding_text="fees 検定料 30,000円",
    )
    kb = DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            document_id="sample",
            source_pdf="sample.pdf",
            pdf_sha256="abc",
            chunk_count=1,
        ),
        facts=[fact],
        retrieval_units=[
            RetrievalUnit(
                unit_id="unit:00001",
                fact_id=fact.fact_id,
                text=fact.embedding_text,
                source_pages=fact.source_pages,
                section_path=fact.section_path,
            )
        ],
    )

    payload = kb.model_dump(mode="json")
    restored = DocumentKnowledgeBase.model_validate(payload)
    assert restored.facts[0].title == "検定料"
    assert restored.manifest.schema_version == "0.5"
    assert restored.diagnostics == BuildDiagnostics()
    assert restored.facts[0].section_path == ["３．出願手続", "（１）検定料"]
    assert restored.retrieval_units[0].section_path == restored.facts[0].section_path
    assert restored.retrieval_units[0].fact_id == "fact:00001"


def test_document_kb_schema_reads_older_versions_without_filter_summary() -> None:
    payload = {
        "manifest": {
            "document_id": "legacy",
            "source_pdf": "legacy.pdf",
            "pdf_sha256": "abc",
            "schema_version": "0.2",
            "chunk_count": 1,
        },
        "facts": [
            {
                "fact_id": "fact:00001",
                "fact_type": "fees",
                "text": "legacy text",
                "embedding_text": "legacy embedding",
            }
        ],
        "retrieval_units": [
            {
                "unit_id": "unit:00001",
                "fact_id": "fact:00001",
                "text": "legacy embedding",
            }
        ],
    }

    for version in ("0.1", "0.2", "0.3", "0.4"):
        payload["manifest"]["schema_version"] = version
        restored = DocumentKnowledgeBase.model_validate(payload)
        assert restored.manifest.schema_version == version
        assert restored.manifest.input_chunk_count == 0
        assert restored.manifest.dropped_chunk_count == 0
        assert restored.manifest.dropped_chunk_reasons == {}
        assert restored.manifest.merged_heading_count == 0
        assert restored.manifest.chunk_size_limit == 6000
        assert restored.manifest.max_chunk_chars == 0
        assert restored.manifest.oversized_chunk_count == 0
        assert restored.manifest.oversized_chunk_reasons == {}
        assert restored.facts[0].section_path == []
        assert restored.retrieval_units[0].section_path == []
        assert restored.diagnostics.reference_claims == []


def test_quality_thresholds_reject_negative_limits() -> None:
    try:
        BuildQualityThresholds(max_unknown_scope_facts=-1)
    except ValueError as error:
        assert "non-negative" in str(error)
    else:
        raise AssertionError("negative quality threshold was accepted")


def test_diagnostics_roundtrip_preserves_reference_claim_order() -> None:
    claims = [
        ReferenceDiagnostic(
            source_fact_id=f"fact:{index:05d}",
            label=f"claim-{index}",
            reference_key="item:1",
            direction="forward",
            status="unresolved",
            reason="no_positive_candidate",
        )
        for index in (2, 1)
    ]
    kb = DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            document_id="sample",
            source_pdf="sample.pdf",
            pdf_sha256="abc",
            chunk_count=0,
        ),
        diagnostics=BuildDiagnostics(reference_claim_count=2, reference_claims=claims),
    )

    restored = DocumentKnowledgeBase.model_validate(kb.model_dump(mode="json"))

    assert [claim.source_fact_id for claim in restored.diagnostics.reference_claims] == [
        "fact:00002",
        "fact:00001",
    ]
    assert restored.diagnostics.quality_thresholds == BuildQualityThresholds()
