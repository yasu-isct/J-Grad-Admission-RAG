from jgrad_admission_rag.builder.document_index import IndexedChunk
from jgrad_admission_rag.builder.kb_builder import infer_scope, indexed_chunk_to_fact


def test_infer_scope_detects_environment_college() -> None:
    item = IndexedChunk(
        chunk_id=1,
        pdf_name="sample.pdf",
        pages=[60],
        title="環境・社会理工学院",
        category="department_guidance",
        text="環境・社会理工学院 建築学系 土木・環境工学系",
        text_preview="環境・社会理工学院 建築学系 土木・環境工学系",
        anchors=[],
        references=[],
    )

    scope_type, targets, parent, confidence = infer_scope(item)
    assert scope_type == "department"
    assert "建築学系" in targets
    assert parent == "環境・社会理工学院"
    assert confidence > 0.7


def test_indexed_chunk_to_fact_builds_embedding_text() -> None:
    item = IndexedChunk(
        chunk_id=2,
        pdf_name="sample.pdf",
        pages=[15],
        title="英語外部試験",
        category="english_requirements",
        text="全系 TOEIC L&R のスコアを提出する。",
        text_preview="全系 TOEIC L&R のスコアを提出する。",
        anchors=[],
        references=[],
    )

    fact = indexed_chunk_to_fact(item)
    assert fact.fact_id == "fact:00002"
    assert fact.scope_type == "global"
    assert "english_requirements" in fact.embedding_text
