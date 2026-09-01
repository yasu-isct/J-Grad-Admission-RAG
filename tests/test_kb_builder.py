from pathlib import Path

from jgrad_admission_rag.builder.chunk_filter import classify_chunk, filter_chunks
from jgrad_admission_rag.builder.chunker import SourcePage, TextChunk, chunk_pages
from jgrad_admission_rag.builder.document_index import (
    IndexedChunk,
    build_document_index,
    load_document_index,
    write_document_index,
)
from jgrad_admission_rag.builder.kb_builder import (
    fact_to_retrieval_unit,
    infer_scope,
    indexed_chunk_to_fact,
)


def _text_chunk(
    text: str,
    *,
    title: str = "",
    page: int = 1,
    section_path: list[str] | None = None,
) -> TextChunk:
    return TextChunk(
        pdf_name="sample.pdf",
        page_numbers=[page],
        title=title,
        text=text,
        section_path=section_path or ([title] if title else []),
    )


def test_classify_chunk_uses_only_exact_non_informative_rules() -> None:
    assert classify_chunk(_text_chunk(" \n\t")) == "whitespace_only"
    assert classify_chunk(_text_chunk("## Page 7\n\n  ")) == "page_only"
    assert classify_chunk(_text_chunk("## Page 7\n\n[Documents]", title="[Documents]")) == (
        "heading_only"
    )
    for short_fact in ["目 次", "2027-04-01", "30,000円", "情報工学系"]:
        assert classify_chunk(_text_chunk(short_fact)) == "informative"


def test_filter_chunks_drops_noise_and_preserves_informative_order() -> None:
    chunks = [
        _text_chunk("first"),
        _text_chunk("## Page 2", page=2),
        _text_chunk(" \n", page=3),
        _text_chunk("30,000円", page=4),
    ]

    filtered, summary = filter_chunks(chunks)

    assert [chunk.text for chunk in filtered] == ["first", "30,000円"]
    assert summary.input_chunk_count == 4
    assert summary.dropped_chunk_count == 2
    assert summary.dropped_chunk_reasons == {
        "whitespace_only": 1,
        "page_only": 1,
        "heading_only_unmerged": 0,
    }
    assert summary.merged_heading_count == 0


def test_filter_chunks_merges_heading_with_following_exact_metadata() -> None:
    heading = _text_chunk("## Page 7\n\n[Documents]", title="[Documents]", page=7)
    body = _text_chunk("required forms", title="[Documents]", page=8)

    filtered, summary = filter_chunks([heading, body])

    assert len(filtered) == 1
    assert filtered[0].text == "[Documents]\n\nrequired forms"
    assert filtered[0].page_numbers == [7, 8]
    assert filtered[0].section_path == ["[Documents]"]
    assert summary.merged_heading_count == 1


def test_filter_chunks_merges_heading_backward_without_duplication() -> None:
    body = _text_chunk("[Documents]\nrequired forms", title="[Documents]", page=7)
    heading = _text_chunk("[Documents]", title="[Documents]", page=8)

    filtered, summary = filter_chunks([body, heading])

    assert filtered[0].text == "[Documents]\nrequired forms"
    assert filtered[0].page_numbers == [7, 8]
    assert summary.merged_heading_count == 1


def test_filter_chunks_prefers_following_exact_merge_target() -> None:
    preceding = _text_chunk("earlier body", title="[Documents]", page=6)
    heading = _text_chunk("[Documents]", title="[Documents]", page=7)
    following = _text_chunk("later body", title="[Documents]", page=8)

    filtered, summary = filter_chunks([preceding, heading, following])

    assert [chunk.text for chunk in filtered] == [
        "earlier body",
        "[Documents]\n\nlater body",
    ]
    assert filtered[0].page_numbers == [6]
    assert filtered[1].page_numbers == [7, 8]
    assert summary.merged_heading_count == 1


def test_filter_chunks_drops_heading_without_exact_adjacent_metadata() -> None:
    heading = _text_chunk("[Documents]", title="[Documents]", page=7)
    body = _text_chunk("required forms", title="[Other]", page=8)

    filtered, summary = filter_chunks([heading, body])

    assert [chunk.text for chunk in filtered] == ["required forms"]
    assert summary.dropped_chunk_reasons["heading_only_unmerged"] == 1


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


def test_chunk_pages_builds_deterministic_heading_stack() -> None:
    chunks = chunk_pages(
        [
            SourcePage(
                page_number=1,
                text=(
                    "3. Eligibility\nmajor\n\n"
                    "[Screening]\nbracketed\n\n"
                    "(1) First\nchild\n\n"
                    "(2) Second\npeer\n\n"
                    "[Documents]\nnew bracket\n\n"
                    "4. Examination\nnext major"
                ),
            )
        ],
        "sample.pdf",
    )

    assert [chunk.section_path for chunk in chunks] == [
        ["3. Eligibility"],
        ["3. Eligibility", "[Screening]"],
        ["3. Eligibility", "[Screening]", "(1) First"],
        ["3. Eligibility", "[Screening]", "(2) Second"],
        ["3. Eligibility", "[Documents]"],
        ["4. Examination"],
    ]


def test_section_path_survives_marker_free_pages_and_character_splits() -> None:
    chunks = chunk_pages(
        [
            SourcePage(page_number=1, text="3. Eligibility\n" + "A" * 20),
            SourcePage(page_number=2, text="B" * 20),
        ],
        "sample.pdf",
        max_chars=18,
    )

    assert [chunk.page_numbers for chunk in chunks] == [[1], [2]]
    assert [chunk.section_path for chunk in chunks] == [
        ["3. Eligibility"],
        ["3. Eligibility"],
    ]


def test_section_path_propagates_through_index_fact_and_retrieval_unit() -> None:
    chunk = chunk_pages(
        [SourcePage(page_number=7, text="3. Eligibility\nrule")],
        "sample.pdf",
    )[0]
    indexed = build_document_index([chunk])[0]
    fact = indexed_chunk_to_fact(indexed)
    retrieval_unit = fact_to_retrieval_unit(fact)

    assert indexed.section_path == chunk.section_path
    assert fact.section_path == indexed.section_path
    assert retrieval_unit.section_path == fact.section_path
    assert "section_path: 3. Eligibility" in fact.embedding_text
    assert "section_path: 3. Eligibility" in retrieval_unit.text


def test_document_index_roundtrip_preserves_section_path(tmp_path: Path) -> None:
    chunk = chunk_pages(
        [SourcePage(page_number=7, text="3. Eligibility\nrule")],
        "sample.pdf",
    )[0]
    output = tmp_path / "document_index.json"

    write_document_index(build_document_index([chunk]), output)
    restored = load_document_index(output)

    assert restored[0].section_path == ["3. Eligibility"]


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
