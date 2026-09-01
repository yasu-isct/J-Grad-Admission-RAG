from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .chunker import SourcePage, TextChunk, chunk_pages
from .chunk_filter import filter_chunks
from .document_index import IndexedChunk, build_document_index
from .extractor import extract_pdf
from .reference_resolver import resolve_references
from ..schemas.document_kb import (
    DocumentKnowledgeBase,
    KnowledgeEntity,
    KnowledgeManifest,
    RetrievalUnit,
    ScopedFact,
)
from ..utils import ensure_dir, sha256_file, write_json

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


def pages_to_markdown(pages: list) -> str:
    return "\n\n".join(page.text for page in pages_to_source_pages(pages))


def pages_to_source_pages(pages: list) -> list[SourcePage]:
    return [
        SourcePage(
            page_number=page.page,
            text=f"## Page {page.page}\n\n{page.markdown}",
        )
        for page in pages
    ]


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
            entities.append(
                KnowledgeEntity(
                    entity_id=f"department:{department}",
                    name=department,
                    entity_type="department",
                    parent_id=college_id,
                    source_pages=sorted(page_map[department]),
                )
            )
    return entities


def infer_scope(item: IndexedChunk) -> tuple[str, list[str], str | None, float]:
    haystack = f"{item.title}\n{item.text}"
    matched_departments = [
        department
        for departments in COLLEGE_DEPARTMENTS.values()
        for department in departments
        if department in haystack
    ]
    if matched_departments:
        parent = next(
            college
            for college, departments in COLLEGE_DEPARTMENTS.items()
            if matched_departments[0] in departments
        )
        return "department", matched_departments, parent, 0.75

    matched_colleges = [college for college in COLLEGE_DEPARTMENTS if college in haystack]
    if matched_colleges:
        return "college", matched_colleges, None, 0.7

    if any(token in haystack for token in ["全学院", "全系", "共通", "全志願者"]):
        return "global", [], None, 0.65

    return "unknown", [], None, 0.45


def indexed_chunk_to_fact(item: IndexedChunk) -> ScopedFact:
    scope_type, scope_targets, parent_college, confidence = infer_scope(item)
    evidence = [item.text_preview] if item.text_preview else []
    title = item.title.strip() or f"Chunk {item.chunk_id}"
    embedding_text = "\n".join(
        part
        for part in [
            f"category: {item.category}",
            f"scope: {scope_type} {' '.join(scope_targets)}",
            f"section_path: {' > '.join(item.section_path)}" if item.section_path else "",
            f"title: {title}",
            item.text_preview or item.text[:500],
        ]
        if part
    )
    return ScopedFact(
        fact_id=f"fact:{item.chunk_id:05d}",
        fact_type=item.category,
        scope_type=scope_type,
        scope_targets=scope_targets,
        parent_college=parent_college,
        title=title,
        text=item.text,
        source_pages=item.pages,
        section_path=item.section_path,
        evidence=evidence,
        confidence=confidence,
        embedding_text=embedding_text,
        metadata={
            "chunk_id": item.chunk_id,
            "pdf_name": item.pdf_name,
            "anchors": [asdict(anchor) for anchor in item.anchors],
            "references": [asdict(reference) for reference in item.references],
            **(
                {"oversize_reason": item.oversize_reason}
                if item.oversize_reason is not None
                else {}
            ),
        },
    )


def fact_to_retrieval_unit(fact: ScopedFact) -> RetrievalUnit:
    scope = " / ".join(fact.scope_targets) if fact.scope_targets else fact.scope_type
    text = f"[{fact.fact_type}] [{scope}] {fact.title}\n{fact.embedding_text}"
    return RetrievalUnit(
        unit_id=f"unit:{fact.fact_id.removeprefix('fact:')}",
        fact_id=fact.fact_id,
        text=text,
        source_pages=fact.source_pages,
        section_path=fact.section_path,
        metadata={"scope_type": fact.scope_type, "scope_targets": fact.scope_targets},
    )


def summarize_chunk_sizes(
    chunks: list[TextChunk], max_chars: int
) -> tuple[int, int, dict[str, int]]:
    reasons: dict[str, int] = {}
    for chunk in chunks:
        is_oversized = len(chunk.text) > max_chars
        if is_oversized and chunk.oversize_reason != "indivisible_table":
            raise ValueError("oversized chunks must be marked as indivisible_table")
        if not is_oversized and chunk.oversize_reason is not None:
            raise ValueError("ordinary chunks cannot carry an oversize reason")
        if chunk.oversize_reason:
            reasons[chunk.oversize_reason] = reasons.get(chunk.oversize_reason, 0) + 1
    return max((len(chunk.text) for chunk in chunks), default=0), sum(reasons.values()), reasons


def build_document_kb(pdf_path: str | Path, max_chars: int = 6000) -> DocumentKnowledgeBase:
    pdf_path = Path(pdf_path)
    pages = extract_pdf(pdf_path)
    input_chunks: list[TextChunk] = chunk_pages(
        pages_to_source_pages(pages),
        pdf_path.name,
        max_chars=max_chars,
    )
    chunks, filter_summary = filter_chunks(input_chunks)
    index = build_document_index(chunks)
    links = resolve_references(index)
    facts = [indexed_chunk_to_fact(item) for item in index]
    max_chunk_chars, oversized_chunk_count, oversized_reasons = summarize_chunk_sizes(
        chunks, max_chars
    )

    manifest = KnowledgeManifest(
        document_id=pdf_path.stem,
        source_pdf=str(pdf_path),
        pdf_sha256=sha256_file(pdf_path),
        input_chunk_count=filter_summary.input_chunk_count,
        chunk_count=len(chunks),
        dropped_chunk_count=filter_summary.dropped_chunk_count,
        dropped_chunk_reasons=filter_summary.dropped_chunk_reasons,
        merged_heading_count=filter_summary.merged_heading_count,
        reference_link_count=len(links),
        chunk_size_limit=max_chars,
        max_chunk_chars=max_chunk_chars,
        oversized_chunk_count=oversized_chunk_count,
        oversized_chunk_reasons=oversized_reasons,
    )
    return DocumentKnowledgeBase(
        manifest=manifest,
        entities=build_entities(index),
        facts=facts,
        retrieval_units=[fact_to_retrieval_unit(fact) for fact in facts],
    )


def write_document_kb(kb: DocumentKnowledgeBase, output: str | Path) -> Path:
    output_path = Path(output)
    ensure_dir(output_path.parent)
    write_json(output_path, kb.model_dump(mode="json"))
    return output_path
