from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import fitz
import pdfplumber

from ..utils import INTERMEDIATE_DIR


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


def detect_repeated_lines(page_texts: list[str], min_count: int = 2) -> set[str]:
    counts: Counter[str] = Counter()
    for text in page_texts:
        seen = {line.strip() for line in text.splitlines() if line.strip()}
        counts.update(seen)
    return {line for line, count in counts.items() if count >= min_count and len(line) <= 80}


def clean_text(text: str, repeated_lines: set[str]) -> str:
    lines = []
    for raw in text.splitlines():
        line = " ".join(raw.split()).strip()
        if not line or line in repeated_lines:
            continue
        lines.append(line)
    return "\n".join(lines)


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
            fitz_blocks = "\n".join(
                block[4].strip() for block in fitz_page.get_text("blocks") if block[4].strip()
            )
            text = clean_text(plumber_text + "\n" + fitz_blocks, repeated)
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
