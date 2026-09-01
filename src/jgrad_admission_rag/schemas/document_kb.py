from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

EntityType = Literal["university", "college", "department", "program", "course", "unknown"]
ScopeType = Literal["global", "university", "college", "department", "program", "unknown"]
ReferenceStatus = Literal["resolved", "ambiguous", "unresolved"]


class KnowledgeManifest(BaseModel):
    document_id: str
    source_pdf: str
    pdf_sha256: str
    builder_version: str = "0.1.0"
    schema_version: str = "0.5"
    input_chunk_count: int = 0
    chunk_count: int
    dropped_chunk_count: int = 0
    dropped_chunk_reasons: dict[str, int] = Field(default_factory=dict)
    merged_heading_count: int = 0
    reference_link_count: int = 0
    chunk_size_limit: int = 6000
    max_chunk_chars: int = 0
    oversized_chunk_count: int = 0
    oversized_chunk_reasons: dict[str, int] = Field(default_factory=dict)


class KnowledgeEntity(BaseModel):
    entity_id: str
    name: str
    entity_type: EntityType
    aliases: list[str] = Field(default_factory=list)
    parent_id: str | None = None
    source_pages: list[int] = Field(default_factory=list)


class ScopedFact(BaseModel):
    fact_id: str
    fact_type: str
    scope_type: ScopeType = "unknown"
    scope_targets: list[str] = Field(default_factory=list)
    parent_college: str | None = None
    title: str = ""
    text: str
    source_pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    embedding_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalUnit(BaseModel):
    unit_id: str
    fact_id: str
    text: str
    source_pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReferenceDiagnostic(BaseModel):
    source_fact_id: str
    label: str
    reference_key: str
    direction: str
    status: ReferenceStatus
    selected_target_fact_id: str | None = None
    candidate_target_fact_ids: list[str] = Field(default_factory=list)
    top_score: float | None = None
    score_margin: float | None = None
    reason: str


class QualityGateViolation(BaseModel):
    metric: str
    actual: int
    limit: int
    related_ids: list[str] = Field(default_factory=list)
    related_claims: list[ReferenceDiagnostic] = Field(default_factory=list)


class QualityGateResult(BaseModel):
    passed: bool = True
    violations: list[QualityGateViolation] = Field(default_factory=list)


class BuildQualityThresholds(BaseModel):
    max_missing_source_pages: int | None = 0
    max_missing_section_paths: int | None = 0
    max_empty_or_noninformative_facts: int | None = 0
    max_unexplained_oversized_facts: int | None = 0
    max_unknown_scope_facts: int | None = None
    max_unresolved_references: int | None = None
    max_ambiguous_references: int | None = None

    @field_validator("*")
    @classmethod
    def limits_must_be_non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("quality thresholds must be non-negative or None")
        return value


class BuildDiagnostics(BaseModel):
    input_chunk_count: int = 0
    emitted_chunk_count: int = 0
    dropped_chunk_count: int = 0
    dropped_chunk_reasons: dict[str, int] = Field(default_factory=dict)
    merged_heading_count: int = 0
    missing_source_page_fact_ids: list[str] = Field(default_factory=list)
    missing_section_path_fact_ids: list[str] = Field(default_factory=list)
    empty_or_noninformative_fact_ids: list[str] = Field(default_factory=list)
    short_fact_threshold: int = 100
    short_fact_ids: list[str] = Field(default_factory=list)
    unknown_scope_fact_ids: list[str] = Field(default_factory=list)
    chunk_size_limit: int = 6000
    max_chunk_chars: int = 0
    oversized_fact_ids: list[str] = Field(default_factory=list)
    unexplained_oversized_fact_ids: list[str] = Field(default_factory=list)
    oversized_reasons: dict[str, int] = Field(default_factory=dict)
    raw_reference_occurrence_count: int = 0
    reference_claim_count: int = 0
    reference_ambiguity_margin: float = 0.1
    reference_status_counts: dict[str, int] = Field(
        default_factory=lambda: {"resolved": 0, "ambiguous": 0, "unresolved": 0}
    )
    reference_claims: list[ReferenceDiagnostic] = Field(default_factory=list)
    quality_thresholds: BuildQualityThresholds = Field(default_factory=BuildQualityThresholds)
    quality_gate: QualityGateResult = Field(default_factory=QualityGateResult)


class DocumentKnowledgeBase(BaseModel):
    manifest: KnowledgeManifest
    entities: list[KnowledgeEntity] = Field(default_factory=list)
    facts: list[ScopedFact] = Field(default_factory=list)
    retrieval_units: list[RetrievalUnit] = Field(default_factory=list)
    diagnostics: BuildDiagnostics = Field(default_factory=BuildDiagnostics)
