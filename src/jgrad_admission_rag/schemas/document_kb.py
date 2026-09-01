from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

EntityType = Literal["university", "college", "department", "program", "course", "unknown"]
ScopeType = Literal["global", "university", "college", "department", "program", "unknown"]


class KnowledgeManifest(BaseModel):
    document_id: str
    source_pdf: str
    pdf_sha256: str
    builder_version: str = "0.1.0"
    schema_version: str = "0.3"
    input_chunk_count: int = 0
    chunk_count: int
    dropped_chunk_count: int = 0
    dropped_chunk_reasons: dict[str, int] = Field(default_factory=dict)
    merged_heading_count: int = 0
    reference_link_count: int = 0


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


class DocumentKnowledgeBase(BaseModel):
    manifest: KnowledgeManifest
    entities: list[KnowledgeEntity] = Field(default_factory=list)
    facts: list[ScopedFact] = Field(default_factory=list)
    retrieval_units: list[RetrievalUnit] = Field(default_factory=list)
