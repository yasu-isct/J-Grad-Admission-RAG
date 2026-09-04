"""Versioned HTTP transport contracts without a FastAPI dependency."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..corpus_search import CorpusSearchRequest, CorpusSearchResult
from ..schemas.corpus_version import CorpusSelectionRequest
from ..schemas.document_kb import DocumentKnowledgeBase


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ErrorEnvelope(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    code: str
    message: str
    details: dict[str, Any] | None = None


class HealthResponse(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["live", "ready", "not_ready"]
    ready: bool = Field(strict=True)


class BuildQualityOptions(ApiModel):
    max_missing_source_pages: int | None = Field(default=0, ge=0, strict=True)
    max_missing_section_paths: int | None = Field(default=0, ge=0, strict=True)
    max_empty_or_noninformative_facts: int | None = Field(default=0, ge=0, strict=True)
    max_unexplained_oversized_facts: int | None = Field(default=0, ge=0, strict=True)
    max_unknown_scope_facts: int | None = Field(default=None, ge=0, strict=True)
    max_unresolved_references: int | None = Field(default=None, ge=0, strict=True)
    max_ambiguous_references: int | None = Field(default=None, ge=0, strict=True)


class BuildOptions(ApiModel):
    max_chars: int = Field(default=6000, gt=0, strict=True)
    short_fact_threshold: int = Field(default=100, gt=0, strict=True)
    reference_ambiguity_margin: float = Field(default=0.1, ge=0, strict=True)
    quality_thresholds: BuildQualityOptions = Field(default_factory=BuildQualityOptions)


class QualityViolationSummary(ApiModel):
    metric: str
    actual: int = Field(ge=0, strict=True)
    limit: int = Field(ge=0, strict=True)
    related_id_count: int = Field(ge=0, strict=True)
    related_claim_count: int = Field(ge=0, strict=True)


class BuildSummary(ApiModel):
    document_id: str
    kb_schema_version: str
    chunks: int = Field(ge=0, strict=True)
    facts: int = Field(ge=0, strict=True)
    retrieval_units: int = Field(ge=0, strict=True)
    dropped_chunks: int = Field(ge=0, strict=True)
    dropped_chunk_reasons: dict[str, int]
    missing_source_pages: int = Field(ge=0, strict=True)
    missing_section_paths: int = Field(ge=0, strict=True)
    empty_or_noninformative: int = Field(ge=0, strict=True)
    short_facts: int = Field(ge=0, strict=True)
    unknown_scopes: int = Field(ge=0, strict=True)
    max_chunk_chars: int = Field(ge=0, strict=True)
    oversized_facts: int = Field(ge=0, strict=True)
    reference_links: int = Field(ge=0, strict=True)
    reference_status_counts: dict[str, int]
    quality_gate_passed: bool = Field(strict=True)
    quality_gate_violations: tuple[QualityViolationSummary, ...]


class BuildResponse(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["quality_passed", "quality_failed"]
    accepted_for_indexing: bool = Field(strict=True)
    knowledge_base: DocumentKnowledgeBase
    summary: BuildSummary

    @model_validator(mode="after")
    def status_must_match_quality_gate(self) -> BuildResponse:
        passed = self.knowledge_base.diagnostics.quality_gate.passed
        if self.accepted_for_indexing != passed or self.summary.quality_gate_passed != passed:
            raise ValueError("build acceptance must match the knowledge-base quality gate")
        expected_status = "quality_passed" if passed else "quality_failed"
        if self.status != expected_status:
            raise ValueError("build status must match the knowledge-base quality gate")
        return self


class CorpusQueryRequest(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    selection: CorpusSelectionRequest
    search: CorpusSearchRequest


BUILD_ERROR_RESPONSES = {status: {"model": ErrorEnvelope} for status in (409, 413, 415, 422, 500)}
HEALTH_ERROR_RESPONSES = {500: {"model": ErrorEnvelope}}
QUERY_ERROR_RESPONSES = {
    status: {"model": ErrorEnvelope} for status in (404, 409, 415, 422, 500, 503)
}


__all__ = [
    "BuildOptions",
    "BuildQualityOptions",
    "BuildResponse",
    "BuildSummary",
    "BUILD_ERROR_RESPONSES",
    "CorpusQueryRequest",
    "CorpusSearchResult",
    "ErrorEnvelope",
    "HEALTH_ERROR_RESPONSES",
    "HealthResponse",
    "QUERY_ERROR_RESPONSES",
    "QualityViolationSummary",
]
