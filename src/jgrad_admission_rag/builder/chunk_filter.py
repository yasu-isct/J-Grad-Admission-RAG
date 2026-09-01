from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal, Sequence

from .chunker import TextChunk

ChunkClassification = Literal["whitespace_only", "page_only", "heading_only", "informative"]
DropReason = Literal["whitespace_only", "page_only", "heading_only_unmerged"]

PAGE_LINE_RE = re.compile(r"## Page \d+")
DROP_REASONS: tuple[DropReason, ...] = (
    "whitespace_only",
    "page_only",
    "heading_only_unmerged",
)


@dataclass(frozen=True)
class ChunkFilterSummary:
    input_chunk_count: int
    dropped_chunk_count: int
    dropped_chunk_reasons: dict[str, int]
    merged_heading_count: int


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _without_page_markers(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not PAGE_LINE_RE.fullmatch(line.strip()))


def classify_chunk(chunk: TextChunk) -> ChunkClassification:
    if not chunk.text.strip():
        return "whitespace_only"

    content = _normalize(_without_page_markers(chunk.text))
    if not content:
        return "page_only"

    title = _normalize(chunk.title)
    if title and content == title:
        return "heading_only"
    return "informative"


def _same_merge_metadata(left: TextChunk, right: TextChunk) -> bool:
    return (
        left.pdf_name == right.pdf_name
        and left.title == right.title
        and left.section_path == right.section_path
    )


def _contains_heading(text: str, title: str) -> bool:
    normalized_title = _normalize(title)
    return bool(normalized_title) and any(
        _normalize(line) == normalized_title for line in text.splitlines()
    )


def _merge_heading(
    target: TextChunk,
    heading: TextChunk,
    *,
    heading_precedes: bool,
) -> TextChunk:
    text = target.text
    title = heading.title.strip()
    if title and not _contains_heading(text, title):
        text = f"{title}\n\n{text}" if heading_precedes else f"{text}\n\n{title}"
    return replace(
        target,
        page_numbers=sorted({*target.page_numbers, *heading.page_numbers}),
        text=text,
        section_path=list(target.section_path),
    )


def filter_chunks(
    chunks: Sequence[TextChunk],
) -> tuple[list[TextChunk], ChunkFilterSummary]:
    classifications = [classify_chunk(chunk) for chunk in chunks]
    retained = {
        index: replace(
            chunk, page_numbers=list(chunk.page_numbers), section_path=list(chunk.section_path)
        )
        for index, (chunk, classification) in enumerate(zip(chunks, classifications, strict=True))
        if classification == "informative"
    }
    dropped_reasons = {reason: 0 for reason in DROP_REASONS}
    merged_heading_count = 0

    for index, (chunk, classification) in enumerate(zip(chunks, classifications, strict=True)):
        if classification == "informative":
            continue
        if classification in {"whitespace_only", "page_only"}:
            dropped_reasons[classification] += 1
            continue

        following = index + 1
        preceding = index - 1
        if (
            following < len(chunks)
            and classifications[following] == "informative"
            and _same_merge_metadata(chunk, chunks[following])
        ):
            retained[following] = _merge_heading(
                retained[following],
                chunk,
                heading_precedes=True,
            )
            merged_heading_count += 1
        elif (
            preceding >= 0
            and classifications[preceding] == "informative"
            and _same_merge_metadata(chunk, chunks[preceding])
        ):
            retained[preceding] = _merge_heading(
                retained[preceding],
                chunk,
                heading_precedes=False,
            )
            merged_heading_count += 1
        else:
            dropped_reasons["heading_only_unmerged"] += 1

    filtered = [retained[index] for index in sorted(retained)]
    dropped_chunk_count = sum(dropped_reasons.values())
    summary = ChunkFilterSummary(
        input_chunk_count=len(chunks),
        dropped_chunk_count=dropped_chunk_count,
        dropped_chunk_reasons=dropped_reasons,
        merged_heading_count=merged_heading_count,
    )
    if summary.input_chunk_count != len(filtered) + dropped_chunk_count + merged_heading_count:
        raise ValueError("chunk filtering counts do not balance")
    return filtered, summary
