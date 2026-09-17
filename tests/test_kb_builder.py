import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

import jgrad_admission_rag.builder.kb_builder as kb_builder_module
from jgrad_admission_rag.builder.chunk_filter import classify_chunk, filter_chunks
from jgrad_admission_rag.builder.chunker import SourcePage, TextChunk, chunk_pages
from jgrad_admission_rag.builder.document_index import (
    IndexedChunk,
    build_document_index,
    load_chunks,
    load_document_index,
    write_document_index,
)
from jgrad_admission_rag.builder.kb_builder import (
    DocumentBuildError,
    build_document_kb,
    fact_to_retrieval_unit,
    infer_scope,
    indexed_chunk_to_fact,
    propagate_department_context,
    summarize_chunk_sizes,
)
from tests.identity_helpers import make_document_identity


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
    assert (
        classify_chunk(
            _text_chunk(
                "（１）我が国において、大学を卒業した者",
                title="（１）我が国において、大学を卒業した者",
            )
        )
        == "informative"
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
    assert all(len(chunk.text) <= 18 for chunk in chunks)
    assert all(chunk.page_numbers == [11] for chunk in chunks[:3])
    assert all(chunk.page_numbers == [12] for chunk in chunks[3:])


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


def test_chunk_pages_starts_a_new_root_for_appendix_headings() -> None:
    chunks = chunk_pages(
        [
            SourcePage(page_number=15, text="７．合格後の手続きについて\n本文"),
            SourcePage(page_number=16, text="附録３．英語外部試験の換算基準\n換算式"),
        ],
        "sample.pdf",
    )

    appendix = next(chunk for chunk in chunks if chunk.page_numbers == [16])
    assert appendix.title == "附録３．英語外部試験の換算基準"
    assert appendix.section_path == ["附録３．英語外部試験の換算基準"]


def test_department_page_context_resets_heading_stack_and_scopes_atomic_rule() -> None:
    chunks = chunk_pages(
        [
            SourcePage(page_number=18, text="10．前の系の質問\n本文"),
            SourcePage(
                page_number=19,
                text=(
                    "物質理工学院 応用化学系\n"
                    "【英語外部試験のスコアシートの取扱い】\n"
                    "スコアシートは出願時に提出してください。\n"
                    "試験区分 試験日 試験内容等 備考\n"
                    "口述試験 7月10日"
                ),
            ),
        ],
        "admission.pdf",
    )

    rule = next(chunk for chunk in chunks if chunk.title.startswith("【英語外部試験"))
    assert rule.text.endswith("スコアシートは出願時に提出してください。")
    assert rule.section_path == [
        "物質理工学院 応用化学系",
        "【英語外部試験のスコアシートの取扱い】",
    ]
    assert "前の系の質問" not in rule.section_path


def test_department_context_propagates_on_index_without_changing_chunk_identity() -> None:
    index = build_document_index(
        [
            _text_chunk(
                "工学院 電気電子系\n出願上の注意",
                page=33,
                section_path=["工学院 電気電子系"],
            ),
            _text_chunk(
                "試験区分 試験日 試験内容等\n英語（英語外部試験）150点",
                title="試験区分 試験日 試験内容等",
                page=34,
            ),
            _text_chunk("口頭試問受験資格者", page=34),
            _text_chunk("研究分野一覧\n教員情報", page=35),
            _text_chunk("Ⅲ 清華大学との合同プログラム\n共通本文", page=36),
        ]
    )

    propagate_department_context(index)

    assert [item.chunk_id for item in index] == [0, 1, 2, 3, 4]
    assert index[1].section_path[0] == "工学院 電気電子系"
    assert index[2].section_path[0] == "工学院 電気電子系"
    assert "工学院 電気電子系" not in index[3].section_path
    assert "工学院 電気電子系" not in index[4].section_path


def test_chunk_pages_keeps_single_line_numbered_clause() -> None:
    chunks = chunk_pages(
        [
            SourcePage(
                page_number=7,
                text=(
                    "3. Eligibility\nintro\n"
                    "（１）我が国において、大学を卒業した者\n"
                    "（２）大学評価・学位授与機構から学士の学位を授与された者\ncontinued"
                ),
            )
        ],
        "sample.pdf",
    )

    assert chunks[1].text == "（１）我が国において、大学を卒業した者"
    assert chunks[1].page_numbers == [7]
    assert chunks[1].section_path[-1] == "（１）我が国において、大学を卒業した者"


def test_chunk_pages_does_not_split_parenthesized_range_in_body() -> None:
    notice = (
        "[Special notice]\n"
        "9月28日～9月30日の間に上記\n"
        "（１）～（６）の出願資格を満たす者は、入試課へお知らせください。"
    )

    chunks = chunk_pages([SourcePage(page_number=8, text=notice)], "sample.pdf")

    assert len(chunks) == 1
    assert chunks[0].text == notice


def test_semantic_marker_parenthesized_clauses_start_new_sections() -> None:
    markdown = (
        "3. Eligibility\n"
        "（５）指定施設の課程を修了した者\n"
        "◆（６）認証を受けた外国学校の課程を修了した者\n"
        "（８）文部科学大臣の指定した者\n"
        "★（９）個別審査の対象者"
    )

    chunks = chunk_pages([SourcePage(page_number=7, text=markdown)], "admission.pdf")

    assert [chunk.title for chunk in chunks] == [
        "（５）指定施設の課程を修了した者",
        "◆（６）認証を受けた外国学校の課程を修了した者",
        "（８）文部科学大臣の指定した者",
        "★（９）個別審査の対象者",
    ]
    assert chunks[1].section_path == [
        "3. Eligibility",
        "◆（６）認証を受けた外国学校の課程を修了した者",
    ]
    assert chunks[2].text == "（８）文部科学大臣の指定した者"


def test_semantic_marker_does_not_turn_number_ranges_into_titles() -> None:
    markdown = "（５）条件本文\n◆（１）～（６）の条件に関する注意"

    chunks = chunk_pages([SourcePage(page_number=7, text=markdown)], "admission.pdf")

    assert len(chunks) == 1
    assert chunks[0].text == markdown


def test_layout_subheadings_and_department_clauses_create_atomic_sections() -> None:
    markdown = (
        "４．出願手続\n"
        "（３）出願書類\n"
        "◆スコアシートの要件\n共通の提出方法。\n"
        "・数学系は、英語の筆答試験を行うため、外部スコアは不要です。\n詳細を確認する。\n"
        "◆英語外部試験の種類と受験時期について\nTOEFL iBT。\n"
        "※TOEIC L&Rの場合：\nQRコードを確認する。"
    )

    chunks = chunk_pages([SourcePage(page_number=11, text=markdown)], "admission.pdf")

    assert [chunk.title for chunk in chunks] == [
        "（３）出願書類",
        "◆スコアシートの要件",
        "・数学系は、英語の筆答試験を行うため、外部スコアは不要です。",
        "◆英語外部試験の種類と受験時期について",
        "※TOEIC L&Rの場合：",
    ]
    assert chunks[2].section_path == [
        "４．出願手続",
        "（３）出願書類",
        "・数学系は、英語の筆答試験を行うため、外部スコアは不要です。",
    ]
    assert chunks[4].section_path[-1] == "※TOEIC L&Rの場合："


def test_fullwidth_bracketed_notice_starts_a_new_section() -> None:
    markdown = (
        "★（11）個別審査の対象者\n［2026年9月入学希望者への注意］\n事前に入試課へ知らせてください。"
    )

    chunks = chunk_pages([SourcePage(page_number=8, text=markdown)], "admission.pdf")

    assert [chunk.title for chunk in chunks] == [
        "★（11）個別審査の対象者",
        "［2026年9月入学希望者への注意］",
    ]
    assert chunks[1].section_path == ["［2026年9月入学希望者への注意］"]


def test_numbered_single_line_statement_is_not_dropped_as_heading_only() -> None:
    statement = "２．本学に2年間在学した時点でGPTが3.00以上かつ90単位以上であること。"

    chunks = chunk_pages([SourcePage(page_number=8, text=statement)], "admission.pdf")

    filtered, summary = filter_chunks(chunks)

    assert len(filtered) == 1
    assert filtered[0].title == statement
    assert filtered[0].text == statement
    assert filtered[0].page_numbers == [8]
    assert summary.dropped_chunk_count == 0


def test_numbered_single_line_section_heading_is_still_dropped() -> None:
    chunks = chunk_pages([SourcePage(page_number=8, text="２．出願資格")], "admission.pdf")

    assert chunks == []


def test_section_path_survives_marker_free_pages_and_character_splits() -> None:
    chunks = chunk_pages(
        [
            SourcePage(page_number=1, text="3. Eligibility\n" + "A" * 20),
            SourcePage(page_number=2, text="B" * 20),
        ],
        "sample.pdf",
        max_chars=18,
    )

    assert all(len(chunk.text) <= 18 for chunk in chunks)
    assert [chunk.page_numbers for chunk in chunks] == [[1], [1], [1], [2], [2]]
    assert all(chunk.section_path == ["3. Eligibility"] for chunk in chunks)


def test_chunk_pages_rejects_non_positive_size_limit() -> None:
    pages = [SourcePage(page_number=1, text="content")]

    for max_chars in (0, -1):
        with pytest.raises(ValueError, match="positive integer"):
            chunk_pages(pages, "sample.pdf", max_chars=max_chars)


def test_chunk_pages_uses_deterministic_safe_boundary_priority() -> None:
    paragraphs = chunk_pages(
        [SourcePage(page_number=1, text="alpha\n\nbeta")],
        "sample.pdf",
        max_chars=6,
    )
    lines = chunk_pages(
        [SourcePage(page_number=1, text="1) item one\n2) item two")],
        "sample.pdf",
        max_chars=12,
    )
    words = chunk_pages(
        [SourcePage(page_number=1, text="alpha beta gamma")],
        "sample.pdf",
        max_chars=10,
    )
    japanese = chunk_pages(
        [SourcePage(page_number=1, text="出願資格審査結果通知")],
        "sample.pdf",
        max_chars=5,
    )

    assert [chunk.text for chunk in paragraphs] == ["alpha", "beta"]
    assert [chunk.text for chunk in lines] == ["1) item one", "2) item two"]
    assert [chunk.text for chunk in words] == ["alpha", "beta gamma"]
    assert [chunk.text for chunk in japanese] == ["出願資格審", "査結果通知"]


def test_chunk_pages_isolates_table_and_marks_only_indivisible_exception() -> None:
    normal_table = "### Table 1\n| h |\n| --- |\n| v |"
    chunks = chunk_pages(
        [SourcePage(page_number=3, text=f"preceding text\n\n{normal_table}")],
        "sample.pdf",
        max_chars=len(normal_table),
    )
    oversized_table = "### Table 2\n| heading |\n| --- |\n| " + ("value" * 10) + " |"
    exception = chunk_pages(
        [SourcePage(page_number=4, text=oversized_table)],
        "sample.pdf",
        max_chars=30,
    )

    assert [chunk.text for chunk in chunks] == ["preceding text", normal_table]
    assert all(chunk.oversize_reason is None for chunk in chunks)
    assert len(exception) == 1
    assert exception[0].text == oversized_table
    assert exception[0].oversize_reason == "indivisible_table"
    assert exception[0].page_numbers == [4]


def test_chunk_pages_isolates_tables_with_semantic_subheadings() -> None:
    table = "### Table 1\n| h |\n| --- |\n| ◆英語外部試験の種類\n本文 |"

    chunks = chunk_pages(
        [SourcePage(page_number=3, text=f"preceding text\n\n{table}")],
        "sample.pdf",
        max_chars=6000,
    )

    assert [chunk.text for chunk in chunks] == ["preceding text", table]
    assert all(chunk.oversize_reason is None for chunk in chunks)


def test_chunk_splitting_conserves_canonical_content() -> None:
    source = "first paragraph\n\n- first item\n- second item\n\n日本語連続文字列"
    chunks = chunk_pages(
        [SourcePage(page_number=5, text=source)],
        "sample.pdf",
        max_chars=14,
    )

    canonical_source = re.sub(r"\s+", "", source)
    canonical_chunks = "".join(re.sub(r"\s+", "", chunk.text) for chunk in chunks)
    assert canonical_chunks == canonical_source
    assert all(0 < len(chunk.text) <= 14 for chunk in chunks)


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


def test_common_eligibility_section_infers_global_scope_without_target() -> None:
    item = IndexedChunk(
        chunk_id=0,
        pdf_name="sample.pdf",
        pages=[7],
        title="（１）大学を卒業した者",
        text="（１）大学を卒業した者",
        section_path=["３．出願資格", "（１）大学を卒業した者"],
        category="eligibility",
        anchors=[],
        references=[],
        text_preview="（１）大学を卒業した者",
    )

    assert infer_scope(item) == ("global", [], None, 0.7)


def test_appendix_conversion_scope_does_not_leak_to_following_page_content() -> None:
    heading = "附録３．本学が定める英語外部試験の換算基準"
    appendix = IndexedChunk(
        chunk_id=0,
        pdf_name="sample.pdf",
        pages=[16],
        title=heading,
        text=f"{heading}\n換算式",
        section_path=[heading],
        category="english",
        anchors=[],
        references=[],
        text_preview="換算式",
    )
    inherited = replace(appendix, chunk_id=1, pages=[17], text="附録４．別の基準")

    assert infer_scope(appendix) == ("global", [], None, 0.7)
    assert infer_scope(inherited) == ("unknown", [], None, 0.45)


def test_path9_numbered_university_requirement_infers_global_scope() -> None:
    item = IndexedChunk(
        chunk_id=90,
        pdf_name="sample.pdf",
        pages=[8],
        title="２．本学に2年間在学した時点においてGPTが3.00以上",
        text="２．本学に2年間在学した時点においてGPTが3.00以上であり、かつ、原則として90単位以上を修得していること。",
        section_path=["２．本学に2年間在学した時点においてGPTが3.00以上"],
        category="general",
        anchors=[],
        references=[],
        text_preview="GPTが3.00以上",
    )

    assert infer_scope(item) == ("global", [], None, 0.7)


def test_path10_whole_rule_is_global_despite_mot_subclause() -> None:
    text = (
        "★（10）本学大学院において、個別の出願資格審査により、大学を卒業した者と"
        "同等以上の学力があると認めた者であって、技術経営専門職学位課程志願者のみ"
    )
    item = IndexedChunk(
        chunk_id=69,
        pdf_name="sample.pdf",
        pages=[7],
        title="★（10）本学大学院において、個別の出願資格審査により、",
        text=text,
        section_path=["３．出願資格"],
        category="general",
        anchors=[],
        references=[],
        text_preview=text,
    )

    assert infer_scope(item) == ("global", [], None, 0.7)


def test_common_application_procedure_section_infers_global_scope() -> None:
    item = IndexedChunk(
        chunk_id=99,
        pdf_name="sample.pdf",
        pages=[9],
        title="（１）出願期間",
        text="2026年6月4日～6月10日（必着）",
        section_path=["４．出願手続", "（１）出願期間"],
        category="periods",
        anchors=[],
        references=[],
        text_preview="2026年6月4日～6月10日（必着）",
    )

    assert infer_scope(item) == ("global", [], None, 0.7)


@pytest.mark.parametrize(
    "section_path,text",
    [
        (["stale heading", "（３）受験上の特別な配慮が必要な場合の対応"], "数学系"),
        (["stale heading", "（６）外国籍および海外在住の志願者への注意"], "数学系"),
        (["stale heading", "（１）出願時に日本に在住していること"], "数学系"),
        (
            [
                "stale heading",
                "（２）2026年9月28日まで有効であり、長期滞在が可能な在留資格を有していること",
            ],
            "数学系",
        ),
        (
            ["４．出願手続", "【外国籍の志願者のみ提出する書類】"],
            "【外国籍の志願者のみ提出する書類】\n数学系",
        ),
        (["５．選抜試験", "（１）英語試験（Ａ日程及びＢ日程どちらも必須）"], "数学系以外"),
    ],
)
def test_global_preapplication_sections_override_incidental_department_text(
    section_path, text
) -> None:
    item = IndexedChunk(
        chunk_id=106,
        pdf_name="sample.pdf",
        pages=[11],
        title=section_path[-1],
        text=text,
        section_path=section_path,
        category="general",
        anchors=[],
        references=[],
        text_preview=text,
    )

    assert infer_scope(item) == ("global", [], None, 0.7)


def test_application_procedure_parent_does_not_override_department_scope() -> None:
    item = IndexedChunk(
        chunk_id=105,
        pdf_name="sample.pdf",
        pages=[11],
        title="（３）出願書類",
        text="数学系は英語の筆答試験を行う",
        section_path=["４．出願手続", "（３）出願書類"],
        category="english",
        anchors=[],
        references=[],
        text_preview="数学系は英語の筆答試験を行う",
    )

    assert infer_scope(item) == ("department", ["数学系"], "理学院", 0.75)


def test_department_page_context_is_authoritative_for_scope() -> None:
    item = IndexedChunk(
        chunk_id=106,
        pdf_name="sample.pdf",
        pages=[46],
        title="【英語外部試験のスコアシートの取扱い】",
        text="スコアシートは出願時に提出する。",
        section_path=[
            "物質理工学院 応用化学系",
            "【英語外部試験のスコアシートの取扱い】",
        ],
        category="english",
        anchors=[],
        references=[],
        text_preview="スコアシートは出願時に提出する。",
    )

    assert infer_scope(item) == ("department", ["応用化学系"], "物質理工学院", 0.9)


def test_longer_department_name_does_not_also_match_embedded_short_name() -> None:
    item = IndexedChunk(
        chunk_id=107,
        pdf_name="sample.pdf",
        pages=[46],
        title="英語外部試験",
        text="応用化学系の志願者はスコアシートを提出する。",
        section_path=["英語外部試験"],
        category="english",
        anchors=[],
        references=[],
        text_preview="応用化学系の志願者",
    )

    assert infer_scope(item) == ("department", ["応用化学系"], "物質理工学院", 0.75)


def test_professional_degree_page_context_uses_program_scope() -> None:
    item = IndexedChunk(
        chunk_id=108,
        pdf_name="sample.pdf",
        pages=[73],
        title="【英語外部試験のスコアシートの取扱い】",
        text="スコアシートは出願時に提出する。",
        section_path=[
            "環境・社会理工学院 技術経営専門職学位課程",
            "【英語外部試験のスコアシートの取扱い】",
        ],
        category="english",
        anchors=[],
        references=[],
        text_preview="スコアシートは出願時に提出する。",
    )

    assert infer_scope(item) == (
        "program",
        ["技術経営専門職学位課程"],
        "環境・社会理工学院",
        0.9,
    )


def test_department_exclusion_is_not_a_positive_department_scope() -> None:
    item = IndexedChunk(
        chunk_id=105,
        pdf_name="sample.pdf",
        pages=[12],
        title="（１）英語試験",
        text="数学系以外は指定された英語外部試験のスコアシートを提出する。",
        section_path=["５．選抜試験", "（１）英語試験"],
        category="english",
        anchors=[],
        references=[],
        text_preview="数学系以外は指定された英語外部試験のスコアシートを提出する。",
    )

    assert infer_scope(item) == ("unknown", [], None, 0.45)


def test_document_index_roundtrip_preserves_section_path(tmp_path: Path) -> None:
    chunk = chunk_pages(
        [SourcePage(page_number=7, text="3. Eligibility\nrule")],
        "sample.pdf",
    )[0]
    output = tmp_path / "document_index.json"

    write_document_index(build_document_index([chunk]), output)
    restored = load_document_index(output)

    assert restored[0].section_path == ["3. Eligibility"]


def test_oversize_reason_propagates_through_index_and_fact(tmp_path: Path) -> None:
    table = "### Table 1\n| heading |\n| --- |\n| " + ("value" * 10) + " |"
    chunk = chunk_pages(
        [SourcePage(page_number=7, text=table)],
        "sample.pdf",
        max_chars=30,
    )[0]
    indexed = build_document_index([chunk])[0]
    fact = indexed_chunk_to_fact(indexed)
    output = tmp_path / "document_index.json"

    write_document_index([indexed], output)
    restored = load_document_index(output)

    assert indexed.oversize_reason == "indivisible_table"
    assert restored[0].oversize_reason == "indivisible_table"
    assert fact.metadata["oversize_reason"] == "indivisible_table"
    assert "oversize_reason" not in fact_to_retrieval_unit(fact).metadata

    legacy_payload = json.loads(output.read_text(encoding="utf-8"))
    legacy_payload[0].pop("oversize_reason")
    output.write_text(json.dumps(legacy_payload), encoding="utf-8")
    assert load_document_index(output)[0].oversize_reason is None

    legacy_chunk_output = tmp_path / "chunks.json"
    legacy_chunk_output.write_text(
        json.dumps(
            [
                {
                    "pdf_name": "sample.pdf",
                    "page_numbers": [1],
                    "title": "",
                    "text": "legacy",
                }
            ]
        ),
        encoding="utf-8",
    )
    assert load_chunks(legacy_chunk_output)[0].oversize_reason is None


def test_chunk_size_summary_enforces_exception_invariants() -> None:
    ordinary = _text_chunk("bounded")
    table_exception = _text_chunk("x" * 20)
    table_exception.oversize_reason = "indivisible_table"

    assert summarize_chunk_sizes([ordinary, table_exception], 10) == (
        20,
        1,
        {"indivisible_table": 1},
    )

    with pytest.raises(ValueError, match="must be marked"):
        summarize_chunk_sizes([_text_chunk("x" * 20)], 10)
    ordinary.oversize_reason = "indivisible_table"
    with pytest.raises(ValueError, match="cannot carry"):
        summarize_chunk_sizes([ordinary], 10)


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


def test_build_document_kb_verifies_reviewed_hash_before_extraction(
    monkeypatch, tmp_path: Path
) -> None:
    pdf_path = tmp_path / "same-name.pdf"
    pdf_path.write_bytes(b"reviewed exact PDF bytes")
    extraction_calls: list[Path] = []

    def fake_extract(path: Path):
        extraction_calls.append(path)
        return []

    monkeypatch.setattr(kb_builder_module, "extract_pdf", fake_extract)
    mismatched = make_document_identity(document_id="reviewed-id", pdf_sha256="b" * 64)
    with pytest.raises(DocumentBuildError, match="invalid or inconsistent"):
        build_document_kb(pdf_path, mismatched)
    assert extraction_calls == []

    actual_hash = kb_builder_module.sha256_file(pdf_path)
    identity = make_document_identity(document_id="reviewed-id", pdf_sha256=actual_hash)
    kb = build_document_kb(pdf_path, identity)
    assert extraction_calls == [pdf_path]
    assert kb.manifest.document_id == "reviewed-id"
    assert kb.manifest.pdf_sha256 == actual_hash
    assert kb.manifest.source_pdf == str(pdf_path)


def test_build_document_kb_revalidates_copied_identity(tmp_path: Path) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"pdf")
    invalid = make_document_identity().model_copy(update={"source_pdf_sha256": "secret"})
    with pytest.raises(DocumentBuildError, match="invalid or inconsistent") as error:
        build_document_kb(pdf_path, invalid)
    assert "secret" not in str(error.value)
    assert str(pdf_path) not in str(error.value)
