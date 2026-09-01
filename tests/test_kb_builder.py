from jgrad_admission_rag.builder.chunker import SourcePage, chunk_pages
from jgrad_admission_rag.builder.document_index import IndexedChunk
from jgrad_admission_rag.builder.kb_builder import (
    fact_to_retrieval_unit,
    infer_scope,
    indexed_chunk_to_fact,
)


def test_chunk_pages_preserves_page_without_visible_marker() -> None:
    chunks = chunk_pages(
        [SourcePage(page_number=7, text="[出願資格]\n本文")],
        "sample.pdf",
    )

    assert [chunk.page_numbers for chunk in chunks] == [[7]]


def test_chunk_pages_preserves_page_across_title_boundaries() -> None:
    chunks = chunk_pages(
        [SourcePage(page_number=9, text="## Page 9\n\n[第一項]\n本文\n\n[第二項]\n本文")],
        "sample.pdf",
    )

    assert [chunk.title for chunk in chunks] == ["[第一項]", "[第二項]"]
    assert [chunk.page_numbers for chunk in chunks] == [[9], [9]]


def test_chunk_pages_tracks_cross_page_character_splits() -> None:
    pages = [
        SourcePage(page_number=11, text="[共通事項]\n" + "A" * 20),
        SourcePage(page_number=12, text="B" * 20),
    ]

    cross_page_chunk = chunk_pages(pages, "sample.pdf")[0]
    chunks = chunk_pages(
        pages,
        "sample.pdf",
        max_chars=18,
    )

    assert cross_page_chunk.page_numbers == [11, 12]
    assert chunks[0].page_numbers == [11]
    assert chunks[1].page_numbers == [12]


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
    retrieval_unit = fact_to_retrieval_unit(fact)
    assert fact.fact_id == "fact:00002"
    assert fact.scope_type == "global"
    assert "english_requirements" in fact.embedding_text
    assert retrieval_unit.source_pages == fact.source_pages == [15]
