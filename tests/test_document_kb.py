from jgrad_admission_rag.schemas.document_kb import (
    DocumentKnowledgeBase,
    KnowledgeManifest,
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
    assert restored.manifest.schema_version == "0.3"
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

    for version in ("0.1", "0.2"):
        payload["manifest"]["schema_version"] = version
        restored = DocumentKnowledgeBase.model_validate(payload)
        assert restored.manifest.schema_version == version
        assert restored.manifest.input_chunk_count == 0
        assert restored.manifest.dropped_chunk_count == 0
        assert restored.manifest.dropped_chunk_reasons == {}
        assert restored.manifest.merged_heading_count == 0
        assert restored.facts[0].section_path == []
        assert restored.retrieval_units[0].section_path == []
