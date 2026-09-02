from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .document_identity import DocumentIdentity

EntityType = Literal["university", "college", "department", "program", "course", "unknown"]
ScopeType = Literal["global", "university", "college", "department", "program", "unknown"]
ReferenceStatus = Literal["resolved", "ambiguous", "unresolved"]


class KnowledgeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: DocumentIdentity
    source_pdf: str
    builder_version: str = "0.1.0"
    schema_version: Literal["0.6"] = "0.6"
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

    @property
    def document_id(self) -> str:
        """Compatibility view of the exact-edition ID from the sole identity authority."""

        return self.identity.document_id

    @property
    def pdf_sha256(self) -> str:
        """Compatibility view of the reviewed exact PDF binding."""

        return self.identity.source_pdf_sha256


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
    model_config = ConfigDict(extra="forbid")

    manifest: KnowledgeManifest
    entities: list[KnowledgeEntity] = Field(default_factory=list)
    facts: list[ScopedFact] = Field(default_factory=list)
    retrieval_units: list[RetrievalUnit] = Field(default_factory=list)
    diagnostics: BuildDiagnostics = Field(default_factory=BuildDiagnostics)


class DocumentKnowledgeBaseError(Exception):
    """Raised when a KB or explicit legacy migration fails closed."""


class LegacyKnowledgeManifestV05(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    source_pdf: str
    pdf_sha256: str
    builder_version: str = "0.1.0"
    schema_version: Literal["0.5"] = "0.5"
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


class LegacyDocumentKnowledgeBaseV05(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: LegacyKnowledgeManifestV05
    entities: list[KnowledgeEntity] = Field(default_factory=list)
    facts: list[ScopedFact] = Field(default_factory=list)
    retrieval_units: list[RetrievalUnit] = Field(default_factory=list)
    diagnostics: BuildDiagnostics = Field(default_factory=BuildDiagnostics)


def migrate_document_kb_v05(
    legacy: LegacyDocumentKnowledgeBaseV05,
    identity: DocumentIdentity,
) -> DocumentKnowledgeBase:
    """Migrate one validated v0.5 KB using caller-reviewed identity metadata."""

    try:
        validated_legacy = LegacyDocumentKnowledgeBaseV05.model_validate(
            legacy.model_dump(mode="json")
        )
        validated_identity = DocumentIdentity.model_validate(identity.model_dump(mode="json"))
        if (
            validated_legacy.manifest.document_id != validated_identity.document_id
            or validated_legacy.manifest.pdf_sha256 != validated_identity.source_pdf_sha256
        ):
            raise ValueError
        manifest_payload = validated_legacy.manifest.model_dump(mode="json")
        for field in ("document_id", "pdf_sha256", "schema_version"):
            manifest_payload.pop(field)
        return DocumentKnowledgeBase(
            manifest=KnowledgeManifest(identity=validated_identity, **manifest_payload),
            entities=validated_legacy.entities,
            facts=validated_legacy.facts,
            retrieval_units=validated_legacy.retrieval_units,
            diagnostics=validated_legacy.diagnostics,
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise DocumentKnowledgeBaseError(
            "legacy KB migration input is invalid or inconsistent"
        ) from None


def migrate_document_kb_v05_bytes(
    raw_bytes: bytes,
    identity: DocumentIdentity,
) -> DocumentKnowledgeBase:
    """Parse and explicitly migrate canonical-compatible v0.5 JSON bytes."""

    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        legacy = LegacyDocumentKnowledgeBaseV05.model_validate(payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValidationError,
        ValueError,
    ):
        raise DocumentKnowledgeBaseError("legacy KB bytes are invalid or unsupported") from None
    return migrate_document_kb_v05(legacy, identity)


def canonical_document_kb_bytes(kb: DocumentKnowledgeBase) -> bytes:
    try:
        validated = DocumentKnowledgeBase.model_validate(kb.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise DocumentKnowledgeBaseError("document KB is invalid or unsupported") from None
    return f"{serialized}\n".encode("utf-8")


def load_document_kb_bytes(raw_bytes: bytes) -> DocumentKnowledgeBase:
    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        return DocumentKnowledgeBase.model_validate(payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValidationError,
        ValueError,
    ):
        raise DocumentKnowledgeBaseError("document KB bytes are invalid or unsupported") from None


def load_document_kb(path_value: str | Path) -> DocumentKnowledgeBase:
    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError
        raw_bytes = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise DocumentKnowledgeBaseError("document KB file is unavailable or unsafe") from None
    return load_document_kb_bytes(raw_bytes)


def _reject_constant(_: str) -> Any:
    raise ValueError("non-finite JSON numbers are unsupported")
