from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .chunker import TextChunk
from .document_index import load_chunks
from .reference_resolver import ReferenceLink, load_reference_links
from ..utils import ensure_dir


@dataclass
class ExpansionRecord:
    source_chunk_id: int
    target_chunk_id: int
    reference: str
    depth: int
    confidence: float
    reason: str


def _chunk_key(chunk: TextChunk) -> tuple[Any, ...]:
    return (chunk.pdf_name, tuple(chunk.page_numbers), chunk.title, chunk.text)


def _index_by_identity(all_chunks: list[TextChunk]) -> dict[tuple[Any, ...], int]:
    return {_chunk_key(chunk): index for index, chunk in enumerate(all_chunks)}


def expand_chunk_indexes(
    selected_indexes: list[int],
    links: list[ReferenceLink],
    max_depth: int = 1,
) -> tuple[list[int], list[ExpansionRecord]]:
    if max_depth <= 0:
        return sorted(dict.fromkeys(selected_indexes)), []

    links_by_source: dict[int, list[ReferenceLink]] = {}
    for link in links:
        links_by_source.setdefault(link.source_chunk_id, []).append(link)

    final = set(selected_indexes)
    frontier = set(selected_indexes)
    records: list[ExpansionRecord] = []

    for depth in range(1, max_depth + 1):
        next_frontier: set[int] = set()
        for source_id in sorted(frontier):
            for link in links_by_source.get(source_id, []):
                target_id = link.target_chunk_id
                if target_id in final:
                    continue
                final.add(target_id)
                next_frontier.add(target_id)
                records.append(
                    ExpansionRecord(
                        source_chunk_id=source_id,
                        target_chunk_id=target_id,
                        reference=link.reference,
                        depth=depth,
                        confidence=link.confidence,
                        reason=link.reason,
                    )
                )
        if not next_frontier:
            break
        frontier = next_frontier

    return sorted(final), records


def expand_chunks_by_references(
    all_chunks: list[TextChunk],
    selected_chunks: list[TextChunk],
    links: list[ReferenceLink],
    max_depth: int = 1,
) -> tuple[list[TextChunk], list[ExpansionRecord]]:
    id_by_key = _index_by_identity(all_chunks)
    selected_indexes = [
        id_by_key[_chunk_key(chunk)] for chunk in selected_chunks if _chunk_key(chunk) in id_by_key
    ]
    expanded_indexes, records = expand_chunk_indexes(selected_indexes, links, max_depth=max_depth)
    return [all_chunks[index] for index in expanded_indexes], records


def expansion_to_dict(records: list[ExpansionRecord]) -> list[dict[str, Any]]:
    return [asdict(record) for record in records]


def write_reference_expansion(
    records: list[ExpansionRecord],
    output: str | Path,
    base_selected_count: int | None = None,
    final_selected_count: int | None = None,
) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "base_selected": base_selected_count,
                "expanded": len(records),
                "final_selected": final_selected_count,
                "records": expansion_to_dict(records),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Expand selected chunks through resolved reference links."
    )
    parser.add_argument("chunks_json")
    parser.add_argument("selected_chunks_json")
    parser.add_argument("--links", required=True)
    parser.add_argument("--max-depth", type=int, default=1)
    parser.add_argument("--output", default=None)
    parser.add_argument("--records-output", default=None)
    args = parser.parse_args()

    all_chunks = load_chunks(args.chunks_json)
    selected_chunks = load_chunks(args.selected_chunks_json)
    links = load_reference_links(args.links)
    expanded_chunks, records = expand_chunks_by_references(
        all_chunks,
        selected_chunks,
        links,
        max_depth=args.max_depth,
    )
    chunks_path = Path(args.selected_chunks_json)
    output = (
        Path(args.output)
        if args.output
        else ensure_dir(chunks_path.parent) / "reference_expanded_chunks.json"
    )
    records_output = (
        Path(args.records_output)
        if args.records_output
        else ensure_dir(chunks_path.parent) / "reference_expansion.json"
    )
    output.write_text(
        json.dumps([asdict(chunk) for chunk in expanded_chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_reference_expansion(
        records,
        records_output,
        base_selected_count=len(selected_chunks),
        final_selected_count=len(expanded_chunks),
    )
    print(
        json.dumps(
            {
                "base_selected": len(selected_chunks),
                "expanded": len(records),
                "final_selected": len(expanded_chunks),
                "output": str(output),
                "records_output": str(records_output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
