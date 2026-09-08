from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

from ..utils import INTERMEDIATE_DIR

TITLE_RE = re.compile(
    r"^(?:[【\[][^】\]]+[】\]]|[0-9０-９]+[\.．、]\s*.+|[（(][0-9０-９一二三四五六七八九十]+[）)](?![～〜~-])\s*.+)$",
    re.MULTILINE,
)
PAGE_RE = re.compile(r"^## Page (\d+)", re.MULTILINE)
MAJOR_TITLE_RE = re.compile(r"^[0-9０-９]+[\.．、]")
BRACKETED_TITLE_RE = re.compile(r"^(?:【.*】|\[.*\])$")
PARENTHESIZED_TITLE_RE = re.compile(r"^[（(][0-9０-９一二三四五六七八九十]+[）)]")
TABLE_DELIMITER_RE = re.compile(r"(?m)^\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*$")


@dataclass
class TextChunk:
    pdf_name: str
    page_numbers: list[int]
    title: str
    text: str
    section_path: list[str] = field(default_factory=list)
    oversize_reason: str | None = None


@dataclass(frozen=True)
class SourcePage:
    page_number: int
    text: str

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("page_number must be a positive physical PDF page number")


@dataclass(frozen=True)
class _TextSlice:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _ChunkSlice:
    text_slice: _TextSlice
    oversize_reason: str | None = None


@dataclass
class _HeadingStack:
    major: str | None = None
    bracketed: str | None = None
    parenthesized: str | None = None

    def update(self, title: str) -> list[str]:
        title = title.strip()
        if MAJOR_TITLE_RE.match(title):
            self.major = title
            self.bracketed = None
            self.parenthesized = None
        elif BRACKETED_TITLE_RE.match(title):
            self.bracketed = title
            self.parenthesized = None
        elif PARENTHESIZED_TITLE_RE.match(title):
            self.parenthesized = title
        else:
            return [title] if title else []

        path = [heading for heading in (self.major, self.bracketed, self.parenthesized) if heading]
        return [
            heading
            for index, heading in enumerate(path)
            if index == 0 or heading != path[index - 1]
        ]


def _page_numbers(text: str) -> list[int]:
    return sorted({int(match.group(1)) for match in PAGE_RE.finditer(text)})


def _strip_slice(text: str, start: int, end: int) -> _TextSlice | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start == end:
        return None
    return _TextSlice(text[start:end], start, end)


def _source_pages_for_slice(
    text_slice: _TextSlice,
    page_spans: Sequence[tuple[int, int, int]] | None,
) -> list[int]:
    if page_spans is None:
        return _page_numbers(text_slice.text)
    return sorted(
        {
            page_number
            for start, end, page_number in page_spans
            if start < text_slice.end and text_slice.start < end
        }
    )


def _append_slice(
    chunks: list[_ChunkSlice],
    text: str,
    start: int,
    end: int,
    source_offset: int,
    oversize_reason: str | None = None,
) -> None:
    chunk = _strip_slice(text, start, end)
    if chunk:
        chunks.append(
            _ChunkSlice(
                text_slice=_TextSlice(
                    chunk.text,
                    source_offset + chunk.start,
                    source_offset + chunk.end,
                ),
                oversize_reason=oversize_reason,
            )
        )


def _safe_split_position(text: str, start: int, limit: int) -> int:
    end = min(start + limit, len(text))
    if end == len(text):
        return end

    newline = text.rfind("\n", start + 1, end)
    if newline >= start:
        return newline + 1

    for position in range(end, start, -1):
        if text[position - 1].isspace():
            return position
    return end


def _split_ordinary_slice(text_slice: _TextSlice, max_chars: int) -> list[_ChunkSlice]:
    chunks: list[_ChunkSlice] = []
    start = 0
    while start < len(text_slice.text):
        while start < len(text_slice.text) and text_slice.text[start].isspace():
            start += 1
        if start == len(text_slice.text):
            break
        end = _safe_split_position(text_slice.text, start, max_chars)
        _append_slice(chunks, text_slice.text, start, end, text_slice.start)
        start = end
    return chunks


def _paragraph_slices(text_slice: _TextSlice) -> list[tuple[_TextSlice, bool]]:
    text = text_slice.text
    boundaries = list(re.finditer(r"\n\s*\n", text))
    paragraphs: list[tuple[_TextSlice, bool]] = []
    start = 0
    for boundary in [*boundaries, None]:
        end = boundary.start() if boundary else len(text)
        paragraph = _strip_slice(text, start, end)
        if paragraph:
            absolute = _TextSlice(
                paragraph.text,
                text_slice.start + paragraph.start,
                text_slice.start + paragraph.end,
            )
            is_table = paragraph.text.lstrip().startswith("|") or bool(
                TABLE_DELIMITER_RE.search(paragraph.text)
            )
            paragraphs.append((absolute, is_table))
        if boundary:
            start = boundary.end()
    return paragraphs


def _split_without_cutting_tables(text_slice: _TextSlice, max_chars: int) -> list[_ChunkSlice]:
    text = text_slice.text
    paragraphs = _paragraph_slices(text_slice)
    chunks: list[_ChunkSlice] = []
    current_start: int | None = None
    current_end = 0
    for paragraph, is_table in paragraphs:
        paragraph_start = paragraph.start - text_slice.start
        paragraph_end = paragraph.end - text_slice.start
        combined_size = (
            paragraph_end - current_start if current_start is not None else len(paragraph.text)
        )
        if current_start is not None and combined_size > max_chars:
            _append_slice(chunks, text, current_start, current_end, text_slice.start)
            current_start = None
        if is_table and len(paragraph.text) > max_chars:
            _append_slice(
                chunks,
                text,
                paragraph_start,
                paragraph_end,
                text_slice.start,
                oversize_reason="indivisible_table",
            )
            continue
        if not is_table and len(paragraph.text) > max_chars:
            chunks.extend(_split_ordinary_slice(paragraph, max_chars))
            continue
        if current_start is None:
            current_start = paragraph_start
        current_end = paragraph_end
    if current_start is not None:
        _append_slice(chunks, text, current_start, current_end, text_slice.start)
    return chunks


def _split_on_page_boundaries(text_slice: _TextSlice) -> list[_TextSlice]:
    text = text_slice.text
    matches = list(PAGE_RE.finditer(text))
    if len(matches) <= 1:
        stripped = _strip_slice(text, 0, len(text))
        if not stripped:
            return []
        return [
            _TextSlice(
                stripped.text,
                text_slice.start + stripped.start,
                text_slice.start + stripped.end,
            )
        ]

    parts: list[_TextSlice] = []
    first_start = matches[0].start()
    if first_start > 0:
        part = _strip_slice(text, 0, first_start)
        if part:
            parts.append(
                _TextSlice(
                    part.text,
                    text_slice.start + part.start,
                    text_slice.start + part.end,
                )
            )
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        part = _strip_slice(text, match.start(), end)
        if part:
            parts.append(
                _TextSlice(
                    part.text,
                    text_slice.start + part.start,
                    text_slice.start + part.end,
                )
            )
    return parts


def _chunk_markdown(
    markdown: str,
    pdf_name: str,
    max_chars: int,
    page_spans: Sequence[tuple[int, int, int]] | None,
) -> list[TextChunk]:
    if max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    matches = list(TITLE_RE.finditer(markdown))
    sections: list[tuple[str, list[str], _TextSlice]] = []
    if matches:
        heading_stack = _HeadingStack()
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
            section = _strip_slice(markdown, start, end)
            if section:
                title = match.group(0).strip()
                sections.append((title, heading_stack.update(title), section))
    else:
        section = _strip_slice(markdown, 0, len(markdown))
        sections = [("", [], section)] if section else []

    chunks: list[TextChunk] = []
    for title, section_path, section in sections:
        for page_part in _split_on_page_boundaries(section):
            if page_part.text == title and not PARENTHESIZED_TITLE_RE.match(title):
                continue
            for part in _split_without_cutting_tables(page_part, max_chars):
                chunks.append(
                    TextChunk(
                        pdf_name=pdf_name,
                        page_numbers=_source_pages_for_slice(part.text_slice, page_spans),
                        title=title,
                        text=part.text_slice.text,
                        section_path=list(section_path),
                        oversize_reason=part.oversize_reason,
                    )
                )
    return chunks


def chunk_markdown(markdown: str, pdf_name: str, max_chars: int = 6000) -> list[TextChunk]:
    return _chunk_markdown(markdown, pdf_name, max_chars, page_spans=None)


def chunk_pages(
    pages: Sequence[SourcePage],
    pdf_name: str,
    max_chars: int = 6000,
) -> list[TextChunk]:
    parts: list[str] = []
    page_spans: list[tuple[int, int, int]] = []
    offset = 0
    for page in pages:
        if parts:
            parts.append("\n\n")
            offset += 2
        start = offset
        parts.append(page.text)
        offset += len(page.text)
        page_spans.append((start, offset, page.page_number))
    return _chunk_markdown("".join(parts), pdf_name, max_chars, page_spans=page_spans)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown")
    parser.add_argument("--pdf-name", required=True)
    parser.add_argument("--output", default=str(INTERMEDIATE_DIR / "chunks.json"))
    parser.add_argument("--max-chars", type=int, default=6000)
    args = parser.parse_args()
    markdown = Path(args.markdown).read_text(encoding="utf-8")
    chunks = chunk_markdown(markdown, args.pdf_name, args.max_chars)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(
        json.dumps([asdict(chunk) for chunk in chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
