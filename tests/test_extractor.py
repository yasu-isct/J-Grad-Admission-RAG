from __future__ import annotations

from jgrad_admission_rag.builder.extractor import (
    _clean_appendix_table_duplicates,
    _page_text_source,
    _protected_structural_lines,
    clean_text,
    detect_repeated_lines,
)


def test_appendix_table_cleanup_keeps_prose_and_one_structured_table() -> None:
    markdown = """## Page 16

附録３．英語外部試験の換算基準
換算式
120 677
附録３．英語外部試験の換算基準
換算式
120
677

### Table 1
| iBT | PBT |
| --- | --- |
| 120 | 677 |"""

    cleaned = _clean_appendix_table_duplicates(markdown)

    assert cleaned.count("附録３．英語外部試験の換算基準") == 1
    assert cleaned.count("換算式") == 1
    assert "120 677" not in cleaned
    assert "\n120\n" not in cleaned
    assert "| 120 | 677 |" in cleaned


def test_table_cleanup_does_not_rewrite_non_appendix_pages() -> None:
    markdown = """## Page 3

３．出願資格
120 677

### Table 1
| iBT | PBT |
| --- | --- |
| 120 | 677 |"""

    assert _clean_appendix_table_duplicates(markdown) == markdown


def test_repeated_body_rules_are_not_misclassified_as_page_furniture() -> None:
    heading = "【英語外部試験のスコアシートの取扱い】"
    body_rule = "スコアシートは必ず出願時に提出してください。"
    blocks = [
        (51.0, 300.0, 200.0, 310.0, heading, 0, 0),
        (61.0, 312.0, 400.0, 330.0, body_rule, 1, 0),
    ]
    repeated = detect_repeated_lines([f"Repeated header\n{heading}\n{body_rule}"] * 2)

    protected = _protected_structural_lines(blocks)
    cleaned = clean_text(
        f"Repeated header\n{heading}\n{body_rule}\n{heading}\n{body_rule}",
        repeated,
        protected,
    )

    assert protected == {heading, body_rule}
    assert cleaned == f"{heading}\n{body_rule}"


def test_protected_rule_is_deduplicated_even_when_not_global_page_furniture() -> None:
    heading = "【英語試験】"
    body_rule = "英語外部試験のスコアシート提出は不要です。"

    cleaned = clean_text(
        f"{heading}\n{body_rule}\n試験表\n{heading}\n{body_rule}",
        set(),
        {heading, body_rule},
    )

    assert cleaned.count(heading) == 1
    assert cleaned.count(body_rule) == 1


def test_department_page_uses_one_text_source_when_both_extractors_find_banner() -> None:
    banner = "物質理工学院 材料系"
    plumber = f"{banner}\nplumber layout"
    fitz = f"{banner}\nfitz layout"

    assert _page_text_source(plumber, fitz) == fitz
    assert _page_text_source("common page", "fitz fallback") == "common page\nfitz fallback"

    incidental = "\n".join(["common"] * 11 + [banner])
    assert _page_text_source(incidental, incidental) == f"{incidental}\n{incidental}"


def test_structural_protection_reaches_the_exam_table_boundary() -> None:
    heading = "【英語外部試験のスコアシートの取扱い】"
    rule = "スコアシートは出願時に提出する。"
    boundary = "試験区分 試験日 試験内容等 備考"
    blocks = [
        (0, 0, 1, 1, heading, 0, 0),
        (0, 1, 1, 2, rule, 1, 0),
        (0, 2, 1, 3, boundary, 2, 0),
        (0, 3, 1, 4, "試験本文", 3, 0),
    ]

    protected = _protected_structural_lines(blocks)

    assert {heading, rule, boundary}.issubset(protected)
    assert "試験本文" not in protected
