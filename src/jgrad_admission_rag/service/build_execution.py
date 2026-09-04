"""Shared synchronous build and response assembly for service entry points."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..builder.kb_builder import build_document_kb
from ..schemas.document_identity import DocumentIdentity
from ..schemas.document_kb import BuildQualityThresholds, DocumentKnowledgeBase
from .contracts import BuildOptions, BuildResponse, BuildSummary

BuildFunction = Callable[..., DocumentKnowledgeBase]


def build_response(
    pdf_path: str | Path,
    identity: DocumentIdentity,
    options: BuildOptions,
    *,
    source_pdf: str,
    builder: BuildFunction = build_document_kb,
) -> BuildResponse:
    """Build one detached KB response with a privacy-safe source label."""

    if source_pdf not in {"source.pdf", "uploaded.pdf"}:
        raise ValueError("service build source label is invalid")
    reviewed_identity = DocumentIdentity.model_validate(identity.model_dump(mode="json"))
    reviewed_options = BuildOptions.model_validate(options.model_dump(mode="json"))
    kb = builder(
        Path(pdf_path),
        reviewed_identity,
        max_chars=reviewed_options.max_chars,
        short_fact_threshold=reviewed_options.short_fact_threshold,
        reference_ambiguity_margin=reviewed_options.reference_ambiguity_margin,
        quality_thresholds=BuildQualityThresholds.model_validate(
            reviewed_options.quality_thresholds.model_dump()
        ),
    )
    detached = DocumentKnowledgeBase.model_validate(kb.model_dump(mode="json"))
    detached.manifest.source_pdf = source_pdf
    passed = detached.diagnostics.quality_gate.passed
    return BuildResponse(
        status="quality_passed" if passed else "quality_failed",
        accepted_for_indexing=passed,
        knowledge_base=detached,
        summary=build_summary(detached),
    )


def build_summary(kb: DocumentKnowledgeBase) -> BuildSummary:
    diagnostics = kb.diagnostics
    return BuildSummary(
        document_id=kb.manifest.document_id,
        kb_schema_version=kb.manifest.schema_version,
        chunks=kb.manifest.chunk_count,
        facts=len(kb.facts),
        retrieval_units=len(kb.retrieval_units),
        dropped_chunks=diagnostics.dropped_chunk_count,
        dropped_chunk_reasons=dict(diagnostics.dropped_chunk_reasons),
        missing_source_pages=len(diagnostics.missing_source_page_fact_ids),
        missing_section_paths=len(diagnostics.missing_section_path_fact_ids),
        empty_or_noninformative=len(diagnostics.empty_or_noninformative_fact_ids),
        short_facts=len(diagnostics.short_fact_ids),
        unknown_scopes=len(diagnostics.unknown_scope_fact_ids),
        max_chunk_chars=diagnostics.max_chunk_chars,
        oversized_facts=len(diagnostics.oversized_fact_ids),
        reference_links=kb.manifest.reference_link_count,
        reference_status_counts=dict(diagnostics.reference_status_counts),
        quality_gate_passed=diagnostics.quality_gate.passed,
        quality_gate_violations=tuple(
            {
                "metric": item.metric,
                "actual": item.actual,
                "limit": item.limit,
                "related_id_count": len(item.related_ids),
                "related_claim_count": len(item.related_claims),
            }
            for item in diagnostics.quality_gate.violations
        ),
    )


__all__ = ["BuildFunction", "build_response", "build_summary"]
