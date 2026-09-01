from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .category_router import categorize_chunk
from .chunker import TextChunk
from ..utils import ensure_dir

KANJI_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

ITEM_ANCHOR_RE = re.compile(
    r"(?m)^\s*[\(\uFF08]([0-9\uFF10-\uFF19一二三四五六七八九十]+)[\)\uFF09]"
)
SECTION_ANCHOR_RE = re.compile(r"(?m)^\s*([0-9\uFF10-\uFF19]+)[\.\uFF0E\u3001]\s*([^\n]{1,80})")
REFERENCE_RE = re.compile(
    r"(?P<context>下記|上記|前記|次の各号|各号|別紙|附録|付録|表|第)"
    r"\s*(?:[\(\uFF08]?(?P<number>[0-9\uFF10-\uFF19一二三四五六七八九十]+)[\)\uFF09]?)?"
)
PAREN_REFERENCE_RE = re.compile(
    r"(?P<context>下記|上記|前記)\s*[\(\uFF08](?P<number>[0-9\uFF10-\uFF19一二三四五六七八九十]+)[\)\uFF09]"
)


@dataclass
class Anchor:
    label: str
    kind: str
    key: str
    position: int


@dataclass
class Reference:
    label: str
    kind: str
    key: str
    direction: str
    position: int


@dataclass
class IndexedChunk:
    chunk_id: int
    pdf_name: str
    pages: list[int]
    title: str
    category: str
    text: str
    text_preview: str
    anchors: list[Anchor]
    references: list[Reference]
    section_path: list[str] = field(default_factory=list)
    oversize_reason: str | None = None


def normalize_number(value: str | None) -> str:
    if not value:
        return ""
    value = value.translate(FULLWIDTH_DIGITS).strip()
    if value.isdigit():
        return str(int(value))
    if value in KANJI_NUMBERS:
        return str(KANJI_NUMBERS[value])
    if value.startswith("十") and len(value) == 2 and value[1] in KANJI_NUMBERS:
        return str(10 + KANJI_NUMBERS[value[1]])
    if value.endswith("十") and len(value) == 2 and value[0] in KANJI_NUMBERS:
        return str(KANJI_NUMBERS[value[0]] * 10)
    if "十" in value:
        left, right = value.split("十", 1)
        tens = KANJI_NUMBERS.get(left, 1) if left else 1
        ones = KANJI_NUMBERS.get(right, 0) if right else 0
        return str(tens * 10 + ones)
    return value


def _anchor_key(kind: str, number: str) -> str:
    return f"{kind}:{normalize_number(number)}"


def _line_start(text: str, position: int) -> int:
    return text.rfind("\n", 0, position) + 1


def _direction(context: str) -> str:
    if context == "下記":
        return "forward"
    if context in {"上記", "前記"}:
        return "backward"
    return "any"


def extract_anchors(text: str, title: str = "") -> list[Anchor]:
    combined = f"{title}\n{text}" if title else text
    anchors: list[Anchor] = []
    seen: set[tuple[str, int]] = set()

    for match in SECTION_ANCHOR_RE.finditer(combined):
        number = normalize_number(match.group(1))
        label = match.group(0).strip()
        key = _anchor_key("section", number)
        marker = (key, _line_start(combined, match.start()))
        if marker not in seen:
            anchors.append(Anchor(label=label, kind="section", key=key, position=match.start()))
            seen.add(marker)

    for match in ITEM_ANCHOR_RE.finditer(combined):
        number = normalize_number(match.group(1))
        label = match.group(0).strip()
        key = _anchor_key("item", number)
        marker = (key, _line_start(combined, match.start()))
        if marker not in seen:
            anchors.append(Anchor(label=label, kind="item", key=key, position=match.start()))
            seen.add(marker)

    return sorted(anchors, key=lambda item: item.position)


def extract_references(text: str, title: str = "") -> list[Reference]:
    combined = f"{title}\n{text}" if title else text
    references: list[Reference] = []
    seen: set[tuple[str, int]] = set()

    for pattern in (PAREN_REFERENCE_RE, REFERENCE_RE):
        for match in pattern.finditer(combined):
            context = match.group("context")
            number = normalize_number(match.groupdict().get("number"))
            if context in {"下記", "上記", "前記"} and not number:
                continue
            if context in {"別紙", "附録", "付録", "表", "第"} and not number:
                continue
            kind = "item" if context in {"下記", "上記", "前記", "次の各号", "各号"} else "named"
            key = _anchor_key(kind, number) if number else f"context:{context}"
            marker = (match.group(0), match.start())
            if marker in seen:
                continue
            references.append(
                Reference(
                    label=match.group(0).strip(),
                    kind=kind,
                    key=key,
                    direction=_direction(context),
                    position=match.start(),
                )
            )
            seen.add(marker)

    return sorted(references, key=lambda item: item.position)


def build_document_index(chunks: list[TextChunk]) -> list[IndexedChunk]:
    indexed: list[IndexedChunk] = []
    for chunk_id, chunk in enumerate(chunks):
        compact = " ".join(chunk.text.split())
        indexed.append(
            IndexedChunk(
                chunk_id=chunk_id,
                pdf_name=chunk.pdf_name,
                pages=chunk.page_numbers,
                title=chunk.title,
                category=categorize_chunk(chunk),
                text=chunk.text,
                text_preview=compact[:300],
                anchors=extract_anchors(chunk.text, chunk.title),
                references=extract_references(chunk.text, chunk.title),
                section_path=list(chunk.section_path),
                oversize_reason=chunk.oversize_reason,
            )
        )
    return indexed


def index_to_dict(index: list[IndexedChunk]) -> list[dict[str, Any]]:
    return [asdict(item) for item in index]


def load_chunks(path: str | Path) -> list[TextChunk]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [TextChunk(**item) for item in payload]


def load_document_index(path: str | Path) -> list[IndexedChunk]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        IndexedChunk(
            chunk_id=int(item["chunk_id"]),
            pdf_name=item.get("pdf_name", ""),
            pages=item.get("pages", []),
            title=item.get("title", ""),
            category=item.get("category", "general"),
            text=item.get("text", ""),
            text_preview=item.get("text_preview", ""),
            anchors=[Anchor(**anchor) for anchor in item.get("anchors", [])],
            references=[Reference(**reference) for reference in item.get("references", [])],
            section_path=item.get("section_path", []),
            oversize_reason=item.get("oversize_reason"),
        )
        for item in payload
    ]


def write_document_index(index: list[IndexedChunk], output: str | Path) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(index_to_dict(index), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a lightweight full-text document index for chunks."
    )
    parser.add_argument("chunks_json")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    chunks = load_chunks(args.chunks_json)
    index = build_document_index(chunks)
    chunks_path = Path(args.chunks_json)
    output = (
        Path(args.output) if args.output else ensure_dir(chunks_path.parent) / "document_index.json"
    )
    write_document_index(index, output)
    print(
        json.dumps(
            {
                "chunks": len(index),
                "anchors": sum(len(item.anchors) for item in index),
                "references": sum(len(item.references) for item in index),
                "output": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
