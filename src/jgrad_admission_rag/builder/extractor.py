from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re

import fitz
import pdfplumber

from ..utils import INTERMEDIATE_DIR

REPEATABLE_BODY_SECTION_HEADINGS = frozenset(
    {
        "【英語外部試験のスコアシートの取扱い】",
        "【外部英語試験のスコアシートの取扱い】",
        "【英語試験】",
    }
)
DEPARTMENT_PAGE_BANNER_RE = re.compile(
    r"^(?:\S+学院)\s+[^\n]+(?:系|専門職学位課程)$",
    re.MULTILINE,
)
APPENDIX_HEADING_RE = re.compile(
    r"^附録[0-9０-９一二三四五六七八九十]+[\.．、]\s*[^\n]*英語外部試験[^\n]*換算基準$",
    re.MULTILINE,
)


@dataclass
class ExtractedPage:
    page: int
    markdown: str
    char_count: int
    table_count: int
    scanned: bool


def table_to_markdown(table: list[list[str | None]]) -> str:
    rows = [[(cell or "").replace("\n", " ").strip() for cell in row] for row in table if row]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header = rows[0]
    separator = ["---"] * width
    body = rows[1:] if len(rows) > 1 else []

    def fmt(row: list[str]) -> str:
        return "| " + " | ".join(row) + " |"

    return "\n".join([fmt(header), fmt(separator), *[fmt(row) for row in body]])


def _clean_appendix_table_duplicates(markdown: str) -> str:
    """Keep one prose copy and the structured tables for appendix table pages."""

    table_start = markdown.find("\n\n### Table 1\n")
    if table_start < 0 or APPENDIX_HEADING_RE.search(markdown[:table_start]) is None:
        return markdown

    prose = markdown[:table_start]
    table_block = markdown[table_start + 2 :]
    table_cells = {
        cell.strip()
        for line in table_block.splitlines()
        if line.startswith("|") and "---" not in line
        for cell in line.strip("|").split("|")
        if cell.strip()
    }
    page_marker = re.match(r"## Page (?P<number>[0-9]+)", prose)
    page_number = page_marker.group("number") if page_marker is not None else None
    retained: list[str] = []
    seen_lines: set[str] = set()
    for raw_line in prose.splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line:
            if retained and retained[-1]:
                retained.append("")
            continue
        tokens = line.split()
        if page_number is not None and line == page_number:
            continue
        if tokens and all(token in table_cells for token in tokens):
            continue
        if line in seen_lines:
            continue
        seen_lines.add(line)
        retained.append(line)
    while retained and not retained[-1]:
        retained.pop()
    retained_text = "\n".join(retained)
    return f"{retained_text}\n\n{table_block}"


def detect_repeated_lines(page_texts: list[str], min_count: int = 2) -> set[str]:
    counts: Counter[str] = Counter()
    for text in page_texts:
        seen = {line.strip() for line in text.splitlines() if line.strip()}
        counts.update(seen)
    return {line for line, count in counts.items() if count >= min_count and len(line) <= 80}


def _protected_structural_lines(blocks: list[tuple]) -> set[str]:
    """Keep repeated body clauses when an explicit section heading owns them."""

    protected: set[str] = set()
    block_lines = [
        [" ".join(line.split()).strip() for line in block[4].splitlines() if line.strip()]
        for block in blocks
    ]
    for index, lines in enumerate(block_lines):
        matching_heading = next(
            (line for line in lines if line in REPEATABLE_BODY_SECTION_HEADINGS), None
        )
        if matching_heading is None:
            continue
        for owned_lines in block_lines[index:]:
            protected.update(owned_lines)
            if any(line.startswith("試験区分 試験日 試験内容等") for line in owned_lines):
                break
    return protected


def clean_text(
    text: str,
    repeated_lines: set[str],
    protected_lines: set[str] | None = None,
) -> str:
    protected = protected_lines or set()
    retained_protected_repeats: set[str] = set()
    lines = []
    for raw in text.splitlines():
        line = " ".join(raw.split()).strip()
        if not line:
            continue
        if line in protected:
            if line in retained_protected_repeats:
                continue
            retained_protected_repeats.add(line)
        elif line in repeated_lines:
            continue
        lines.append(line)
    return "\n".join(lines)


def _page_text_source(plumber_text: str, fitz_text: str) -> str:
    """Avoid duplicate department pages when both extractors found the same banner."""

    plumber_banners = _top_page_banners(plumber_text)
    fitz_banners = _top_page_banners(fitz_text)
    if plumber_banners & fitz_banners:
        return fitz_text
    return f"{plumber_text}\n{fitz_text}"


def _top_page_banners(text: str, max_line_index: int = 10) -> set[str]:
    return {
        match.group(0)
        for match in DEPARTMENT_PAGE_BANNER_RE.finditer(text)
        if text.count("\n", 0, match.start()) <= max_line_index
    }


def ocr_page(image_path: str | Path) -> str:
    """Reserved OCR hook. Later connect Tesseract or cloud OCR here."""
    return ""


def extract_pdf(pdf_path: str | Path, pages: list[int] | None = None) -> list[ExtractedPage]:
    pdf_path = Path(pdf_path)
    doc = fitz.open(pdf_path)
    selected_indexes = {page - 1 for page in pages} if pages else set(range(len(doc)))
    fitz_texts = [doc[i].get_text("text") or "" for i in selected_indexes]
    repeated = detect_repeated_lines(fitz_texts)
    extracted: list[ExtractedPage] = []

    with pdfplumber.open(pdf_path) as plumber_pdf:
        for idx, fitz_page in enumerate(doc):
            if idx not in selected_indexes:
                continue
            page_no = idx + 1
            plumber_page = plumber_pdf.pages[idx]
            plumber_text = plumber_page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            raw_blocks = fitz_page.get_text("blocks")
            fitz_blocks = "\n".join(block[4].strip() for block in raw_blocks if block[4].strip())
            text = clean_text(
                _page_text_source(plumber_text, fitz_blocks),
                repeated,
                _protected_structural_lines(raw_blocks),
            )
            tables = []
            for table in plumber_page.extract_tables() or []:
                markdown = table_to_markdown(table)
                if markdown:
                    tables.append(markdown)
            table_block = "\n\n".join(
                f"### Table {i + 1}\n{table}" for i, table in enumerate(tables)
            )
            markdown = f"## Page {page_no}\n\n{text}".strip()
            if table_block:
                markdown += "\n\n" + table_block
                markdown = _clean_appendix_table_duplicates(markdown)
            char_count = len(text.strip())
            scanned = char_count < 50 and not tables and len(fitz_page.get_images(full=True)) > 0
            extracted.append(ExtractedPage(page_no, markdown, char_count, len(tables), scanned))
    return extracted


def extract_pdf_to_markdown(
    pdf_path: str | Path,
    output: str | Path,
    pages: list[int] | None = None,
) -> str:
    extracted = extract_pdf(pdf_path, pages)
    body = "\n\n---\n\n".join(page.markdown for page in extracted)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(body, encoding="utf-8")
    return body


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("--output", default=str(INTERMEDIATE_DIR / "clean.md"))
    parser.add_argument("--pages", nargs="*", type=int)
    args = parser.parse_args()
    extract_pdf_to_markdown(args.pdf, args.output, args.pages)
    print(args.output)


if __name__ == "__main__":
    main()
