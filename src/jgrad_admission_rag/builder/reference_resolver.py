from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .document_index import (
    IndexedChunk,
    Reference,
    build_document_index,
    load_chunks,
    load_document_index,
)
from ..schemas.document_kb import ReferenceDiagnostic
from ..utils import ensure_dir


@dataclass
class ReferenceLink:
    source_chunk_id: int
    target_chunk_id: int
    reference: str
    reference_key: str
    target_anchor: str
    direction: str
    confidence: float
    reason: str


@dataclass
class ReferenceResolution:
    links: list[ReferenceLink]
    claims: list[ReferenceDiagnostic]
    raw_occurrence_count: int


def _anchor_lookup(index: list[IndexedChunk]) -> dict[str, list[tuple[int, str]]]:
    lookup: dict[str, list[tuple[int, str]]] = {}
    for item in index:
        for anchor in item.anchors:
            lookup.setdefault(anchor.key, []).append((item.chunk_id, anchor.label))
    return lookup


def _direction_ok(source_id: int, target_id: int, direction: str) -> bool:
    if direction == "forward":
        return target_id > source_id
    if direction == "backward":
        return target_id < source_id
    return target_id != source_id


def _candidate_score(
    source: IndexedChunk,
    target: IndexedChunk,
    reference: Reference,
    anchor_label: str,
) -> tuple[float, str]:
    distance = abs(target.chunk_id - source.chunk_id)
    score = 1.0 / (distance + 1)
    reasons = [f"distance={distance}"]

    if source.title and source.title == target.title:
        score += 0.4
        reasons.append("same_title")
    if set(source.pages) & set(target.pages):
        score += 0.3
        reasons.append("same_page")
    if source.category == target.category:
        score += 0.2
        reasons.append("same_category")
    if _direction_ok(source.chunk_id, target.chunk_id, reference.direction):
        score += 0.5
        reasons.append(reference.direction)
    else:
        score -= 1.0
        reasons.append("direction_mismatch")
    if anchor_label in target.title:
        score += 0.2
        reasons.append("anchor_in_title")

    return score, ",".join(reasons)


def _scored_targets(
    index_by_id: dict[int, IndexedChunk],
    candidates: list[tuple[int, str]],
    source: IndexedChunk,
    reference: Reference,
) -> list[tuple[float, int, str, str]]:
    scored: list[tuple[float, int, str, str]] = []
    for target_id, anchor_label in sorted(set(candidates)):
        if target_id == source.chunk_id:
            continue
        target = index_by_id[target_id]
        score, reason = _candidate_score(source, target, reference, anchor_label)
        if score <= 0:
            continue
        scored.append((score, target_id, anchor_label, reason))
    return sorted(
        scored,
        key=lambda item: (-item[0], abs(item[1] - source.chunk_id), item[1], item[2]),
    )


def _fact_id(chunk_id: int) -> str:
    return f"fact:{chunk_id:05d}"


def classify_reference_claims(
    index: list[IndexedChunk], ambiguity_margin: float = 0.1
) -> ReferenceResolution:
    if ambiguity_margin < 0:
        raise ValueError("ambiguity_margin must be non-negative")

    anchors = _anchor_lookup(index)
    index_by_id = {item.chunk_id: item for item in index}
    links: list[ReferenceLink] = []
    claims: list[ReferenceDiagnostic] = []
    seen_claims: set[tuple[int, str, str, str]] = set()
    raw_occurrence_count = sum(len(item.references) for item in index)

    for source in index:
        for reference in source.references:
            claim_key = (
                source.chunk_id,
                reference.label,
                reference.key,
                reference.direction,
            )
            if claim_key in seen_claims:
                continue
            seen_claims.add(claim_key)
            scored = _scored_targets(
                index_by_id,
                anchors.get(reference.key, []),
                source,
                reference,
            )
            candidate_ids = list(dict.fromkeys(_fact_id(item[1]) for item in scored))
            top_score = round(scored[0][0], 6) if scored else None
            score_margin = round(scored[0][0] - scored[1][0], 6) if len(scored) > 1 else None

            if not scored:
                status = "unresolved"
                selected_target_id = None
                reason = "no_positive_candidate"
            elif len(scored) > 1 and score_margin is not None and score_margin <= ambiguity_margin:
                status = "ambiguous"
                selected_target_id = None
                reason = "top_candidates_within_ambiguity_margin"
            else:
                status = "resolved"
                selected_target_id = _fact_id(scored[0][1])
                reason = (
                    "single_positive_candidate"
                    if len(scored) == 1
                    else "top_candidate_exceeds_ambiguity_margin"
                )

            claim = ReferenceDiagnostic(
                source_fact_id=_fact_id(source.chunk_id),
                label=reference.label,
                reference_key=reference.key,
                direction=reference.direction,
                status=status,
                selected_target_fact_id=selected_target_id,
                candidate_target_fact_ids=candidate_ids,
                top_score=top_score,
                score_margin=score_margin,
                reason=reason,
            )
            claims.append(claim)
            if status != "resolved":
                continue

            score, target_id, anchor_label, score_reason = scored[0]
            links.append(
                ReferenceLink(
                    source_chunk_id=source.chunk_id,
                    target_chunk_id=target_id,
                    reference=reference.label,
                    reference_key=reference.key,
                    target_anchor=anchor_label,
                    direction=reference.direction,
                    confidence=min(round(score, 6), 1.0),
                    reason=score_reason,
                )
            )

    return ReferenceResolution(
        links=links,
        claims=claims,
        raw_occurrence_count=raw_occurrence_count,
    )


def resolve_references(index: list[IndexedChunk]) -> list[ReferenceLink]:
    return classify_reference_claims(index).links


def links_to_dict(links: list[ReferenceLink]) -> list[dict[str, Any]]:
    return [asdict(link) for link in links]


def load_reference_links(path: str | Path) -> list[ReferenceLink]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [ReferenceLink(**item) for item in payload]


def write_reference_links(links: list[ReferenceLink], output: str | Path) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(links_to_dict(links), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve intra-document references between indexed chunks."
    )
    parser.add_argument("input_json", help="Either chunks JSON or a document_index JSON.")
    parser.add_argument("--input-kind", choices=["chunks", "index"], default="chunks")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    if args.input_kind == "index":
        index = load_document_index(args.input_json)
    else:
        index = build_document_index(load_chunks(args.input_json))
    links = resolve_references(index)
    input_path = Path(args.input_json)
    output = (
        Path(args.output) if args.output else ensure_dir(input_path.parent) / "reference_links.json"
    )
    write_reference_links(links, output)
    print(
        json.dumps(
            {
                "chunks": len(index),
                "links": len(links),
                "output": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
