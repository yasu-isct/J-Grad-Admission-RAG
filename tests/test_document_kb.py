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
            )
        ],
    )

    payload = kb.model_dump(mode="json")
    restored = DocumentKnowledgeBase.model_validate(payload)
    assert restored.facts[0].title == "検定料"
    assert restored.retrieval_units[0].fact_id == "fact:00001"
