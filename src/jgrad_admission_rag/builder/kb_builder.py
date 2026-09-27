from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from pydantic import ValidationError

from .chunker import SourcePage, TextChunk, chunk_pages
from .chunk_filter import classify_chunk, filter_chunks
from .document_index import IndexedChunk, build_document_index
from .extractor import extract_pdf
from .reference_resolver import ReferenceResolution, classify_reference_claims
from ..schemas.document_kb import (
    BuildDiagnostics,
    BuildQualityThresholds,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    QualityGateResult,
    QualityGateViolation,
    ReferenceDiagnostic,
    RetrievalUnit,
    ScopedFact,
)
from ..schemas.document_identity import DocumentIdentity
from ..retrieval.embedding_text import EMBEDDING_TEXT_VERSION, build_embedding_text
from ..utils import ensure_dir, sha256_file, write_json

# Historical helper imports remain available to existing callers and tests.
# All three policy functions and constants have one implementation in legacy_isct_v1.
from .legacy_isct_v1 import (
    APPENDIX_CONVERSION_HEADING_RE as APPENDIX_CONVERSION_HEADING_RE,
    COLLEGE_DEPARTMENTS as COLLEGE_DEPARTMENTS,
    DEPARTMENT_CONTEXT_END_RE as DEPARTMENT_CONTEXT_END_RE,
    DEPARTMENT_CONTEXT_RE as DEPARTMENT_CONTEXT_RE,
    PAGE_MARKER_RE as PAGE_MARKER_RE,
    PATH10_ELIGIBILITY_RE as PATH10_ELIGIBILITY_RE,
    PATH9_UNIVERSITY_REQUIREMENT_RE as PATH9_UNIVERSITY_REQUIREMENT_RE,
    PROGRAMS as PROGRAMS,
    TSINGHUA_JOINT_PROGRAM as TSINGHUA_JOINT_PROGRAM,
    TSINGHUA_PROGRAM_COVER_RE as TSINGHUA_PROGRAM_COVER_RE,
    _is_tsinghua_program_cover as _is_tsinghua_program_cover,
    build_entities as build_entities,
    infer_scope as infer_scope,
    propagate_department_context as propagate_department_context,
)


class DocumentBuildError(Exception):
    """Raised when reviewed identity and source PDF cannot be bound safely."""


class DocumentBuildProfileError(DocumentBuildError):
    """Stable, path-free diagnosis for an explicit profile selection failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


LEGACY_ISCT_PROFILE_ID = "legacy-isct-v1"
_LEGACY_ISCT_IDENTITY = (
    "isct",
    "isct-master-admission-guidelines",
    "2027-april-2026-september",
    "isct_2027_4_2026_9_master",
    ("master",),
    ((2026, 9), (2027, 4)),
)


def build_document_kb_with_profile(
    pdf_path: str | Path,
    identity: DocumentIdentity,
    *,
    profile_id: str,
    max_chars: int = 6000,
    source_pdf_label: str | None = None,
    short_fact_threshold: int = 100,
    reference_ambiguity_margin: float = 0.1,
    quality_thresholds: BuildQualityThresholds | None = None,
) -> DocumentKnowledgeBase:
    """Guard a selected legacy profile before any PDF I/O or extraction.

    New onboarding code must use this explicit entry. The old entry below keeps
    historical behavior for CLI, Demo, service and existing synthetic callers.
    """

    if type(profile_id) is not str or profile_id != LEGACY_ISCT_PROFILE_ID:
        raise DocumentBuildProfileError("unknown_profile")
    try:
        if not isinstance(identity, DocumentIdentity):
            raise TypeError
        validated_identity = DocumentIdentity.model_validate(identity.model_dump(mode="json"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise DocumentBuildProfileError("invalid_identity") from None
    identity_key = (
        validated_identity.institution_id,
        validated_identity.document_family_id,
        validated_identity.edition_id,
        validated_identity.document_id,
        tuple(level.value for level in validated_identity.degree_levels),
        tuple((term.year, term.month) for term in validated_identity.intake_terms),
    )
    if identity_key != _LEGACY_ISCT_IDENTITY:
        raise DocumentBuildProfileError("profile_identity_mismatch")
    return build_document_kb(
        pdf_path,
        validated_identity,
        max_chars=max_chars,
        source_pdf_label=source_pdf_label,
        short_fact_threshold=short_fact_threshold,
        reference_ambiguity_margin=reference_ambiguity_margin,
        quality_thresholds=quality_thresholds,
    )


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


def indexed_chunk_to_fact(item: IndexedChunk) -> ScopedFact:
    scope_type, scope_targets, parent_college, confidence = infer_scope(item)
    evidence = [item.text_preview] if item.text_preview else []
    title = item.title.strip() or f"Chunk {item.chunk_id}"
    fact = ScopedFact(
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
        embedding_text="",
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
            "embedding_text_version": EMBEDDING_TEXT_VERSION,
        },
    )
    return fact.model_copy(update={"embedding_text": build_embedding_text(fact)})


def fact_to_retrieval_unit(fact: ScopedFact) -> RetrievalUnit:
    return RetrievalUnit(
        unit_id=f"unit:{fact.fact_id.removeprefix('fact:')}",
        fact_id=fact.fact_id,
        text=build_embedding_text(fact),
        source_pages=list(fact.source_pages),
        section_path=list(fact.section_path),
        metadata={
            "scope_type": fact.scope_type,
            "scope_targets": list(fact.scope_targets),
            "embedding_text_version": EMBEDDING_TEXT_VERSION,
        },
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


def evaluate_quality_gates(
    diagnostics: BuildDiagnostics,
    thresholds: BuildQualityThresholds,
) -> QualityGateResult:
    metrics: list[tuple[str, int | None, list[str], list[ReferenceDiagnostic]]] = [
        (
            "missing_source_pages",
            thresholds.max_missing_source_pages,
            diagnostics.missing_source_page_fact_ids,
            [],
        ),
        (
            "missing_section_paths",
            thresholds.max_missing_section_paths,
            diagnostics.missing_section_path_fact_ids,
            [],
        ),
        (
            "empty_or_noninformative_facts",
            thresholds.max_empty_or_noninformative_facts,
            diagnostics.empty_or_noninformative_fact_ids,
            [],
        ),
        (
            "unexplained_oversized_facts",
            thresholds.max_unexplained_oversized_facts,
            diagnostics.unexplained_oversized_fact_ids,
            [],
        ),
        (
            "unknown_scope_facts",
            thresholds.max_unknown_scope_facts,
            diagnostics.unknown_scope_fact_ids,
            [],
        ),
        (
            "unresolved_references",
            thresholds.max_unresolved_references,
            [],
            [claim for claim in diagnostics.reference_claims if claim.status == "unresolved"],
        ),
        (
            "ambiguous_references",
            thresholds.max_ambiguous_references,
            [],
            [claim for claim in diagnostics.reference_claims if claim.status == "ambiguous"],
        ),
    ]
    violations: list[QualityGateViolation] = []
    for metric, limit, related_ids, related_claims in metrics:
        actual = len(related_ids) if related_ids else len(related_claims)
        if limit is not None and actual > limit:
            violations.append(
                QualityGateViolation(
                    metric=metric,
                    actual=actual,
                    limit=limit,
                    related_ids=related_ids,
                    related_claims=related_claims,
                )
            )
    return QualityGateResult(passed=not violations, violations=violations)


def build_diagnostics(
    facts: list[ScopedFact],
    manifest: KnowledgeManifest,
    reference_resolution: ReferenceResolution,
    *,
    short_fact_threshold: int = 100,
    reference_ambiguity_margin: float = 0.1,
    quality_thresholds: BuildQualityThresholds | None = None,
) -> BuildDiagnostics:
    if short_fact_threshold <= 0:
        raise ValueError("short_fact_threshold must be positive")

    missing_pages = [fact.fact_id for fact in facts if not fact.source_pages]
    missing_paths = [fact.fact_id for fact in facts if not fact.section_path]
    noninformative: list[str] = []
    for fact in facts:
        chunk = TextChunk(
            pdf_name=str(fact.metadata.get("pdf_name", "")),
            page_numbers=fact.source_pages,
            title=fact.title,
            text=fact.text,
            section_path=fact.section_path,
            oversize_reason=fact.metadata.get("oversize_reason"),
        )
        if classify_chunk(chunk) != "informative":
            noninformative.append(fact.fact_id)

    oversized = [fact for fact in facts if len(fact.text) > manifest.chunk_size_limit]
    oversized_reasons: dict[str, int] = {}
    for fact in oversized:
        reason = fact.metadata.get("oversize_reason")
        if reason:
            oversized_reasons[reason] = oversized_reasons.get(reason, 0) + 1
    status_counts = {status: 0 for status in ("resolved", "ambiguous", "unresolved")}
    for claim in reference_resolution.claims:
        status_counts[claim.status] += 1

    thresholds = quality_thresholds or BuildQualityThresholds()
    diagnostics = BuildDiagnostics(
        input_chunk_count=manifest.input_chunk_count,
        emitted_chunk_count=manifest.chunk_count,
        dropped_chunk_count=manifest.dropped_chunk_count,
        dropped_chunk_reasons=manifest.dropped_chunk_reasons,
        merged_heading_count=manifest.merged_heading_count,
        missing_source_page_fact_ids=missing_pages,
        missing_section_path_fact_ids=missing_paths,
        empty_or_noninformative_fact_ids=noninformative,
        short_fact_threshold=short_fact_threshold,
        short_fact_ids=[
            fact.fact_id for fact in facts if 0 < len(fact.text) < short_fact_threshold
        ],
        unknown_scope_fact_ids=[fact.fact_id for fact in facts if fact.scope_type == "unknown"],
        chunk_size_limit=manifest.chunk_size_limit,
        max_chunk_chars=max((len(fact.text) for fact in facts), default=0),
        oversized_fact_ids=[fact.fact_id for fact in oversized],
        unexplained_oversized_fact_ids=[
            fact.fact_id
            for fact in oversized
            if fact.metadata.get("oversize_reason") != "indivisible_table"
        ],
        oversized_reasons=oversized_reasons,
        raw_reference_occurrence_count=reference_resolution.raw_occurrence_count,
        reference_claim_count=len(reference_resolution.claims),
        reference_ambiguity_margin=reference_ambiguity_margin,
        reference_status_counts=status_counts,
        reference_claims=reference_resolution.claims,
        quality_thresholds=thresholds,
    )
    diagnostics.quality_gate = evaluate_quality_gates(diagnostics, thresholds)
    _validate_diagnostics(diagnostics, manifest, facts, len(reference_resolution.links))
    return diagnostics


def _validate_diagnostics(
    diagnostics: BuildDiagnostics,
    manifest: KnowledgeManifest,
    facts: list[ScopedFact],
    reference_link_count: int,
) -> None:
    if diagnostics.emitted_chunk_count != manifest.chunk_count or manifest.chunk_count != len(
        facts
    ):
        raise ValueError("diagnostic emitted count does not reconcile with manifest and Facts")
    if diagnostics.input_chunk_count != (
        diagnostics.emitted_chunk_count
        + diagnostics.dropped_chunk_count
        + diagnostics.merged_heading_count
    ):
        raise ValueError("diagnostic chunk counts do not balance")
    if diagnostics.max_chunk_chars != manifest.max_chunk_chars:
        raise ValueError("diagnostic max chunk size does not match manifest")
    if len(diagnostics.oversized_fact_ids) != manifest.oversized_chunk_count:
        raise ValueError("diagnostic oversized count does not match manifest")
    if diagnostics.oversized_reasons != manifest.oversized_chunk_reasons:
        raise ValueError("diagnostic oversized reasons do not match manifest")
    if diagnostics.reference_claim_count != sum(diagnostics.reference_status_counts.values()):
        raise ValueError("reference claim status counts do not balance")
    if diagnostics.reference_status_counts["resolved"] != reference_link_count:
        raise ValueError("resolved reference claims do not match emitted links")


def build_document_kb(
    pdf_path: str | Path,
    identity: DocumentIdentity,
    max_chars: int = 6000,
    *,
    source_pdf_label: str | None = None,
    short_fact_threshold: int = 100,
    reference_ambiguity_margin: float = 0.1,
    quality_thresholds: BuildQualityThresholds | None = None,
) -> DocumentKnowledgeBase:
    try:
        pdf_path = Path(pdf_path)
        validated_identity = DocumentIdentity.model_validate(identity.model_dump(mode="json"))
        actual_pdf_sha256 = sha256_file(pdf_path)
        if actual_pdf_sha256 != validated_identity.source_pdf_sha256:
            raise ValueError
        if source_pdf_label is not None and (
            not source_pdf_label
            or source_pdf_label != source_pdf_label.strip()
            or Path(source_pdf_label).name != source_pdf_label
            or "/" in source_pdf_label
            or "\\" in source_pdf_label
            or not source_pdf_label.lower().endswith(".pdf")
        ):
            raise ValueError
    except (AttributeError, OSError, TypeError, ValidationError, ValueError):
        raise DocumentBuildError(
            "source PDF and reviewed document identity are invalid or inconsistent"
        ) from None
    pages = extract_pdf(pdf_path)
    input_chunks: list[TextChunk] = chunk_pages(
        pages_to_source_pages(pages),
        pdf_path.name,
        max_chars=max_chars,
    )
    chunks, filter_summary = filter_chunks(input_chunks)
    index = build_document_index(chunks)
    propagate_department_context(index)
    reference_resolution = classify_reference_claims(index, reference_ambiguity_margin)
    facts = [indexed_chunk_to_fact(item) for item in index]
    max_chunk_chars, oversized_chunk_count, oversized_reasons = summarize_chunk_sizes(
        chunks, max_chars
    )

    manifest = KnowledgeManifest(
        identity=validated_identity,
        source_pdf=source_pdf_label if source_pdf_label is not None else str(pdf_path),
        input_chunk_count=filter_summary.input_chunk_count,
        chunk_count=len(chunks),
        dropped_chunk_count=filter_summary.dropped_chunk_count,
        dropped_chunk_reasons=filter_summary.dropped_chunk_reasons,
        merged_heading_count=filter_summary.merged_heading_count,
        reference_link_count=len(reference_resolution.links),
        chunk_size_limit=max_chars,
        max_chunk_chars=max_chunk_chars,
        oversized_chunk_count=oversized_chunk_count,
        oversized_chunk_reasons=oversized_reasons,
    )
    diagnostics = build_diagnostics(
        facts,
        manifest,
        reference_resolution,
        short_fact_threshold=short_fact_threshold,
        reference_ambiguity_margin=reference_ambiguity_margin,
        quality_thresholds=quality_thresholds,
    )
    return DocumentKnowledgeBase(
        manifest=manifest,
        entities=build_entities(index),
        facts=facts,
        retrieval_units=[fact_to_retrieval_unit(fact) for fact in facts],
        diagnostics=diagnostics,
    )


def write_document_kb(kb: DocumentKnowledgeBase, output: str | Path) -> Path:
    output_path = Path(output)
    ensure_dir(output_path.parent)
    write_json(output_path, kb.model_dump(mode="json"))
    return output_path
