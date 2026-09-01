from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..builder.kb_builder import build_document_kb, write_document_kb
from ..schemas.document_kb import BuildQualityThresholds, DocumentKnowledgeBase


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _optional_non_negative_int(value: str) -> int | None:
    if value.lower() in {"none", "off", "disabled"}:
        return None
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative or 'none'")
    return parsed


def build_summary(kb: DocumentKnowledgeBase, output: Path) -> dict:
    diagnostics = kb.diagnostics
    return {
        "output": str(output),
        "schema_version": kb.manifest.schema_version,
        "chunks": kb.manifest.chunk_count,
        "facts": len(kb.facts),
        "retrieval_units": len(kb.retrieval_units),
        "dropped_chunks": diagnostics.dropped_chunk_count,
        "dropped_chunk_reasons": diagnostics.dropped_chunk_reasons,
        "missing_source_pages": len(diagnostics.missing_source_page_fact_ids),
        "missing_section_paths": len(diagnostics.missing_section_path_fact_ids),
        "empty_or_noninformative": len(diagnostics.empty_or_noninformative_fact_ids),
        "short_facts": len(diagnostics.short_fact_ids),
        "unknown_scopes": len(diagnostics.unknown_scope_fact_ids),
        "max_chunk_chars": diagnostics.max_chunk_chars,
        "oversized_facts": len(diagnostics.oversized_fact_ids),
        "reference_links": kb.manifest.reference_link_count,
        "reference_status_counts": diagnostics.reference_status_counts,
        "quality_gate_passed": diagnostics.quality_gate.passed,
        "quality_gate_violations": [
            {
                "metric": violation.metric,
                "actual": violation.actual,
                "limit": violation.limit,
                "related_id_count": len(violation.related_ids),
                "related_claim_count": len(violation.related_claims),
            }
            for violation in diagnostics.quality_gate.violations
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a RAG-ready admission document KB.")
    parser.add_argument("pdf", help="Source admission guideline PDF.")
    parser.add_argument("--output", default=None, help="Output document_kb.json path.")
    parser.add_argument("--max-chars", type=_positive_int, default=6000)
    parser.add_argument("--short-fact-threshold", type=_positive_int, default=100)
    parser.add_argument("--reference-ambiguity-margin", type=_non_negative_float, default=0.1)
    parser.add_argument("--max-missing-source-pages", type=_optional_non_negative_int, default=0)
    parser.add_argument("--max-missing-section-paths", type=_optional_non_negative_int, default=0)
    parser.add_argument(
        "--max-empty-or-noninformative-facts", type=_optional_non_negative_int, default=0
    )
    parser.add_argument(
        "--max-unexplained-oversized-facts", type=_optional_non_negative_int, default=0
    )
    parser.add_argument("--max-unknown-scope-facts", type=_optional_non_negative_int, default=None)
    parser.add_argument(
        "--max-unresolved-references", type=_optional_non_negative_int, default=None
    )
    parser.add_argument("--max-ambiguous-references", type=_optional_non_negative_int, default=None)
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    output = (
        Path(args.output)
        if args.output
        else Path("outputs") / "kb" / pdf_path.stem / "document_kb.json"
    )
    thresholds = BuildQualityThresholds(
        max_missing_source_pages=args.max_missing_source_pages,
        max_missing_section_paths=args.max_missing_section_paths,
        max_empty_or_noninformative_facts=args.max_empty_or_noninformative_facts,
        max_unexplained_oversized_facts=args.max_unexplained_oversized_facts,
        max_unknown_scope_facts=args.max_unknown_scope_facts,
        max_unresolved_references=args.max_unresolved_references,
        max_ambiguous_references=args.max_ambiguous_references,
    )
    kb = build_document_kb(
        pdf_path,
        max_chars=args.max_chars,
        short_fact_threshold=args.short_fact_threshold,
        reference_ambiguity_margin=args.reference_ambiguity_margin,
        quality_thresholds=thresholds,
    )
    write_document_kb(kb, output)
    print(json.dumps(build_summary(kb, output), ensure_ascii=False, indent=2))
    if not kb.diagnostics.quality_gate.passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
