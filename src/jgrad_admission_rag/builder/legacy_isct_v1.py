"""The sole authoritative implementation of historical ISCT build policy.

This module is intentionally unsuitable for other institutions. Keep exact order,
confidence and catalog values when maintaining the legacy profile.
"""

from __future__ import annotations

import re

from .document_index import IndexedChunk
from ..schemas.document_kb import KnowledgeEntity

COLLEGE_DEPARTMENTS = {
    "理学院": ["数学系", "物理学系", "化学系", "地球惑星科学系"],
    "工学院": ["機械系", "システム制御系", "電気電子系", "情報通信系", "経営工学系"],
    "物質理工学院": ["材料系", "応用化学系"],
    "情報理工学院": ["数理・計算科学系", "情報工学系"],
    "生命理工学院": ["生命理工学系"],
    "環境・社会理工学院": [
        "建築学系",
        "土木・環境工学系",
        "融合理工学系",
        "社会・人間科学系",
        "技術経営専門職学位課程",
    ],
}
PROGRAMS = {"技術経営専門職学位課程"}
TSINGHUA_JOINT_PROGRAM = "東京科学大学・清華大学 大学院合同プログラム"
DEPARTMENT_CONTEXT_RE = re.compile(r"^(?P<college>\S+学院)\s+(?P<unit>.+(?:系|専門職学位課程))$")
TSINGHUA_PROGRAM_COVER_RE = re.compile(
    r"Ⅲ\s+清華大学（中国）との大学院\s*合同プログラム入学試験案内"
)
APPENDIX_CONVERSION_HEADING_RE = re.compile(
    r"^附録[0-9０-９一二三四五六七八九十]+[\.．、][^\n]*英語外部試験[^\n]*換算基準"
)

PATH9_UNIVERSITY_REQUIREMENT_RE = re.compile(
    r"^[１２３]\．(?:2027年3月31日において、大学在学期間|本学に2年間在学した時点|本学大学院入学までに)"
)
PATH10_ELIGIBILITY_RE = re.compile(r"^★（10）本学大学院において、個別の出願資格審査により、")
DEPARTMENT_CONTEXT_END_RE = re.compile(
    r"^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\s+|附録|入学者受入れの方針|"
    r"東京科学大学「教育理念」|■\s*東京科学大学)"
)
PAGE_MARKER_RE = re.compile(r"^## Page \d+$")


def build_entities(index: list[IndexedChunk]) -> list[KnowledgeEntity]:
    page_map: dict[str, set[int]] = {college: set() for college in COLLEGE_DEPARTMENTS}
    for departments in COLLEGE_DEPARTMENTS.values():
        for department in departments:
            page_map[department] = set()

    for item in index:
        haystack = f"{item.title}\n{item.text}"
        for name in page_map:
            if name in haystack:
                page_map[name].update(item.pages)

    program_page_map = {
        TSINGHUA_JOINT_PROGRAM: {
            page
            for item in index
            if TSINGHUA_JOINT_PROGRAM in item.section_path
            for page in item.pages
        }
    }

    entities: list[KnowledgeEntity] = []
    for college, departments in COLLEGE_DEPARTMENTS.items():
        college_id = f"college:{college}"
        entities.append(
            KnowledgeEntity(
                entity_id=college_id,
                name=college,
                entity_type="college",
                source_pages=sorted(page_map[college]),
            )
        )
        for department in departments:
            entity_type = "program" if department in PROGRAMS else "department"
            entities.append(
                KnowledgeEntity(
                    entity_id=f"{entity_type}:{department}",
                    name=department,
                    entity_type=entity_type,
                    parent_id=college_id,
                    source_pages=sorted(page_map[department]),
                )
            )
    for program, pages in program_page_map.items():
        if not pages:
            continue
        entities.append(
            KnowledgeEntity(
                entity_id=f"program:{program}",
                name=program,
                entity_type="program",
                source_pages=sorted(pages),
            )
        )
    return entities


def infer_scope(item: IndexedChunk) -> tuple[str, list[str], str | None, float]:
    haystack = f"{item.title}\n{item.text}"
    if (
        item.section_path
        and APPENDIX_CONVERSION_HEADING_RE.match(item.section_path[0])
        and item.text.lstrip().startswith(item.section_path[0])
    ):
        return "global", [], None, 0.7

    if TSINGHUA_JOINT_PROGRAM in item.section_path or _is_tsinghua_program_cover(item):
        return "program", [TSINGHUA_JOINT_PROGRAM], None, 0.9
    if item.pages == [7] and PATH10_ELIGIBILITY_RE.match(item.text):
        return "global", [], None, 0.7

    if item.section_path and item.section_path[-1].startswith(
        (
            "（３）受験上の特別な配慮が必要な場合の対応",
            "（６）外国籍および海外在住の志願者への注意",
            "（１）出願時に日本に在住していること",
            "（２）2026年9月28日まで有効であり、長期滞在が可能な在留資格を有していること",
            "（１）英語試験（Ａ日程及びＢ日程どちらも必須）",
        )
    ):
        return "global", [], None, 0.7

    if (
        item.section_path
        and item.section_path[-1].startswith("【外国籍の志願者のみ提出する書類】")
        and item.title
        and item.text.lstrip().startswith(item.title)
    ):
        return "global", [], None, 0.7

    for heading in item.section_path:
        context = DEPARTMENT_CONTEXT_RE.fullmatch(heading.strip())
        if context is None:
            continue
        college = context.group("college")
        unit = context.group("unit")
        if unit in COLLEGE_DEPARTMENTS.get(college, []):
            scope_type = "program" if unit in PROGRAMS else "department"
            return scope_type, [unit], college, 0.9

    matched_departments: list[str] = []
    occupied_spans: list[tuple[int, int]] = []
    departments = sorted(
        (department for values in COLLEGE_DEPARTMENTS.values() for department in values),
        key=len,
        reverse=True,
    )
    for department in departments:
        if haystack.count(department) <= haystack.count(f"{department}以外"):
            continue
        matches = list(re.finditer(re.escape(department), haystack))
        unoccupied_matches = [
            match
            for match in matches
            if all(match.end() <= start or end <= match.start() for start, end in occupied_spans)
        ]
        if not unoccupied_matches:
            continue
        matched_departments.append(department)
        occupied_spans.extend(match.span() for match in unoccupied_matches)
    if matched_departments:
        parent = next(
            college
            for college, departments in COLLEGE_DEPARTMENTS.items()
            if matched_departments[0] in departments
        )
        scope_type = (
            "program"
            if len(matched_departments) == 1 and matched_departments[0] in PROGRAMS
            else "department"
        )
        return scope_type, matched_departments, parent, 0.75

    matched_colleges = [college for college in COLLEGE_DEPARTMENTS if college in haystack]
    if matched_colleges:
        return "college", matched_colleges, None, 0.7

    if item.section_path and item.section_path[0].startswith(
        ("２．入学時期", "３．出願資格", "４．出願手続")
    ):
        return "global", [], None, 0.7

    if item.pages == [8] and PATH9_UNIVERSITY_REQUIREMENT_RE.match(item.text):
        return "global", [], None, 0.7

    if any(token in haystack for token in ["全学院", "全系", "共通", "全志願者"]):
        return "global", [], None, 0.65

    return "unknown", [], None, 0.45


def propagate_department_context(index: list[IndexedChunk]) -> None:
    """Carry reviewed department or program banners to an explicit top-level boundary."""

    active_context: str | None = None
    for item in index:
        lines = (line.strip() for line in item.text.splitlines())
        first_line = next(
            (line for line in lines if line and not PAGE_MARKER_RE.fullmatch(line)), ""
        )
        if DEPARTMENT_CONTEXT_END_RE.match(first_line):
            active_context = None
        explicit_program = TSINGHUA_JOINT_PROGRAM if _is_tsinghua_program_cover(item) else None
        explicit_context = next(
            (
                heading
                for heading in item.section_path
                if DEPARTMENT_CONTEXT_RE.fullmatch(heading.strip())
            ),
            None,
        )
        if explicit_program is not None:
            active_context = explicit_program
            if explicit_program not in item.section_path:
                item.section_path = [explicit_program, *item.section_path]
        elif explicit_context is not None:
            active_context = explicit_context
        elif active_context is not None and not DEPARTMENT_CONTEXT_END_RE.match(first_line):
            if active_context not in item.section_path:
                item.section_path = [active_context, *item.section_path]


def _is_tsinghua_program_cover(item: IndexedChunk) -> bool:
    """Recognize the reviewed cover without treating earlier contents mentions as a banner."""

    return item.pages == [75] and TSINGHUA_PROGRAM_COVER_RE.search(item.text) is not None
