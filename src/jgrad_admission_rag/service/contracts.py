"""Versioned HTTP transport contracts without a FastAPI dependency."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..corpus_search import CorpusSearchRequest, CorpusSearchResult
from ..reasoning.applicant_profile import ApplicantProfile
from ..reasoning.applicant_report import ApplicantReport, render_applicant_report_markdown
from ..reasoning.query_intent import IntentCategory, QueryIntent
from ..schemas.corpus_version import CorpusSelectionRequest
from ..schemas.document_identity import DegreeLevel, DocumentIdentity, IntakeTerm
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


JobStateValue = Literal[
    "queued", "running", "cancel_requested", "succeeded", "quality_failed", "failed", "cancelled"
]
JobPhaseValue = Literal["waiting", "building", "cancelling", "finished"]
JobDiagnosticValue = Literal["worker_interrupted", "build_failed", "cancelled_by_request"]
_JOB_PHASE_BY_STATE = {
    "queued": "waiting",
    "running": "building",
    "cancel_requested": "cancelling",
    "succeeded": "finished",
    "quality_failed": "finished",
    "failed": "finished",
    "cancelled": "finished",
}
_JOB_RESULT_STATES = {"succeeded", "quality_failed"}
_JOB_TERMINAL_STATES = _JOB_RESULT_STATES | {"failed", "cancelled"}
_JOB_LEGAL_TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"cancel_requested", "succeeded", "quality_failed", "failed", "cancelled"},
    "cancel_requested": {"cancelled"},
    "succeeded": set(),
    "quality_failed": set(),
    "failed": set(),
    "cancelled": set(),
}


class BuildJobTransition(ApiModel):
    sequence: int = Field(ge=1, strict=True)
    from_state: JobStateValue | None
    to_state: JobStateValue
    phase: JobPhaseValue
    at: datetime
    diagnostic_code: JobDiagnosticValue | None = None

    @field_validator("at")
    @classmethod
    def transition_timestamp_must_be_utc(cls, value: datetime) -> datetime:
        return _utc_timestamp(value)

    @model_validator(mode="after")
    def transition_must_be_consistent(self) -> BuildJobTransition:
        if self.phase != _JOB_PHASE_BY_STATE[self.to_state]:
            raise ValueError("job transition phase is invalid")
        if self.from_state is None:
            if self.sequence != 1 or self.to_state != "queued":
                raise ValueError("initial job transition is invalid")
        elif self.to_state not in _JOB_LEGAL_TRANSITIONS[self.from_state]:
            raise ValueError("job transition is invalid")
        if self.to_state == "failed":
            if self.diagnostic_code not in {"build_failed", "worker_interrupted"}:
                raise ValueError("job failure diagnostic is invalid")
        elif self.to_state == "cancelled":
            if self.diagnostic_code != "cancelled_by_request":
                raise ValueError("job cancellation diagnostic is invalid")
        elif self.diagnostic_code is not None:
            raise ValueError("job diagnostic is invalid")
        return self


class BuildJobReceipt(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    job_id: UUID
    state: JobStateValue
    phase: JobPhaseValue
    attempt: int = Field(ge=1, strict=True)
    parent_job_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    result_available: bool = Field(strict=True)
    status_path: str
    result_path: str

    @field_validator("job_id", "parent_job_id", mode="before")
    @classmethod
    def job_ids_must_be_canonical(cls, value: object) -> object:
        if value is None or isinstance(value, UUID):
            return value
        if not isinstance(value, str):
            raise ValueError("job ID is invalid")
        try:
            parsed = UUID(value)
        except ValueError:
            raise ValueError("job ID is invalid") from None
        if str(parsed) != value:
            raise ValueError("job ID is invalid")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def receipt_timestamps_must_be_utc(cls, value: datetime) -> datetime:
        return _utc_timestamp(value)

    @model_validator(mode="after")
    def receipt_links_must_be_relative_and_consistent(self) -> BuildJobReceipt:
        job_id = str(self.job_id)
        if self.status_path != f"/v1/build-jobs/{job_id}":
            raise ValueError("job status path is invalid")
        if self.result_path != f"/v1/build-jobs/{job_id}/result":
            raise ValueError("job result path is invalid")
        if (self.attempt == 1) != (self.parent_job_id is None):
            raise ValueError("job attempt linkage is invalid")
        if self.phase != _JOB_PHASE_BY_STATE[self.state]:
            raise ValueError("job phase is invalid")
        if self.result_available != (self.state in _JOB_RESULT_STATES):
            raise ValueError("job result availability is invalid")
        if self.created_at > self.updated_at:
            raise ValueError("job timestamps are invalid")
        return self


class BuildJobStatus(BuildJobReceipt):
    started_at: datetime | None = None
    finished_at: datetime | None = None
    diagnostic_code: JobDiagnosticValue | None = None
    transitions: tuple[BuildJobTransition, ...]

    @field_validator("started_at", "finished_at")
    @classmethod
    def status_timestamps_must_be_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc_timestamp(value)

    @model_validator(mode="after")
    def status_must_match_history(self) -> BuildJobStatus:
        if not self.transitions or tuple(item.sequence for item in self.transitions) != tuple(
            range(1, len(self.transitions) + 1)
        ):
            raise ValueError("job transition sequence is invalid")
        if self.transitions[0].at != self.created_at:
            raise ValueError("job creation history is invalid")
        for previous, current in zip(self.transitions, self.transitions[1:]):
            if current.from_state != previous.to_state or current.at < previous.at:
                raise ValueError("job transition history is invalid")
        final = self.transitions[-1]
        if (
            final.to_state != self.state
            or final.phase != self.phase
            or final.at != self.updated_at
            or final.diagnostic_code != self.diagnostic_code
        ):
            raise ValueError("job status does not match history")
        if (self.state in _JOB_TERMINAL_STATES) != (self.finished_at is not None):
            raise ValueError("job finish timestamp is invalid")
        if self.state in {"running", "cancel_requested", "succeeded", "quality_failed", "failed"}:
            if self.started_at is None:
                raise ValueError("job start timestamp is missing")
        present = [
            value
            for value in (self.created_at, self.started_at, self.finished_at, self.updated_at)
            if value is not None
        ]
        if any(left > right for left, right in zip(present, present[1:])):
            raise ValueError("job timestamps are invalid")
        return self


def _utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("job timestamp must be timezone-aware UTC")
    return value


class CorpusQueryRequest(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    selection: CorpusSelectionRequest
    search: CorpusSearchRequest


class ApplicantReportRequest(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    report_id: str = Field(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
    profile: ApplicantProfile
    intent: QueryIntent
    selection: CorpusSelectionRequest


class ApplicantReportResponse(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    report: ApplicantReport
    markdown: str

    @model_validator(mode="after")
    def markdown_must_match_report(self) -> ApplicantReportResponse:
        if self.markdown != render_applicant_report_markdown(self.report):
            raise ValueError("applicant report Markdown does not reconcile")
        return self


class QueryIntentParseRequest(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    query: str = Field(min_length=1, max_length=1000)

    @field_validator("query")
    @classmethod
    def query_must_be_explicit(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("query must be explicit")
        return value


class ReviewedDocumentPublicIdentity(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    document_id: str
    document_family_id: str
    edition_id: str
    institution_id: str
    institution_name: str
    degree_levels: tuple[DegreeLevel, ...] = Field(min_length=1)
    intake_terms: tuple[IntakeTerm, ...] = Field(min_length=1)
    official_title: str
    official_source_url: str
    publication_date: date | None = None
    revision_date: date | None = None

    @model_validator(mode="after")
    def public_identity_must_remain_valid(self) -> ReviewedDocumentPublicIdentity:
        DocumentIdentity(
            **self.model_dump(mode="python"),
            source_pdf_sha256="0" * 64,
        )
        return self


class ReviewedDocumentCatalogItem(ApiModel):
    identity: ReviewedDocumentPublicIdentity
    version_classification: Literal["active", "historical"]
    plan_id: str = Field(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
    coverage_status: Literal["partial_reviewed_rules"]
    covered_categories: tuple[IntentCategory, ...] = Field(min_length=1)
    reviewed_coverage_statement: str = Field(min_length=1, max_length=500)
    limitation_statement: str = Field(min_length=1, max_length=500)

    @field_validator("covered_categories")
    @classmethod
    def categories_must_be_canonical(
        cls, values: tuple[IntentCategory, ...]
    ) -> tuple[IntentCategory, ...]:
        if values != tuple(sorted(set(values), key=lambda item: item.value)):
            raise ValueError("covered categories must be sorted and unique")
        return values


class ReviewedDocumentCatalogResponse(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    items: tuple[ReviewedDocumentCatalogItem, ...]

    @field_validator("items")
    @classmethod
    def items_must_be_canonical(
        cls, values: tuple[ReviewedDocumentCatalogItem, ...]
    ) -> tuple[ReviewedDocumentCatalogItem, ...]:
        document_ids = tuple(item.identity.document_id for item in values)
        plan_ids = tuple(item.plan_id for item in values)
        if document_ids != tuple(sorted(set(document_ids))) or len(plan_ids) != len(set(plan_ids)):
            raise ValueError("catalog items must be canonical and unique")
        return values


BUILD_ERROR_RESPONSES = {status: {"model": ErrorEnvelope} for status in (409, 413, 415, 422, 500)}
JOB_ERROR_RESPONSES = {
    status: {"model": ErrorEnvelope} for status in (404, 409, 413, 415, 422, 500, 503)
}
HEALTH_ERROR_RESPONSES = {500: {"model": ErrorEnvelope}}
QUERY_ERROR_RESPONSES = {
    status: {"model": ErrorEnvelope} for status in (404, 409, 415, 422, 500, 503)
}
REPORT_ERROR_RESPONSES = {
    status: {"model": ErrorEnvelope} for status in (404, 409, 415, 422, 500, 503)
}
INTENT_ERROR_RESPONSES = {status: {"model": ErrorEnvelope} for status in (415, 422, 500, 503)}
CATALOG_ERROR_RESPONSES = {status: {"model": ErrorEnvelope} for status in (500, 503)}


__all__ = [
    "BuildJobReceipt",
    "BuildJobStatus",
    "BuildJobTransition",
    "BuildOptions",
    "BuildQualityOptions",
    "BuildResponse",
    "BuildSummary",
    "ApplicantReportRequest",
    "ApplicantReportResponse",
    "QueryIntentParseRequest",
    "BUILD_ERROR_RESPONSES",
    "CorpusQueryRequest",
    "CorpusSearchResult",
    "ErrorEnvelope",
    "HEALTH_ERROR_RESPONSES",
    "HealthResponse",
    "JOB_ERROR_RESPONSES",
    "QUERY_ERROR_RESPONSES",
    "REPORT_ERROR_RESPONSES",
    "INTENT_ERROR_RESPONSES",
    "CATALOG_ERROR_RESPONSES",
    "ReviewedDocumentCatalogItem",
    "ReviewedDocumentCatalogResponse",
    "ReviewedDocumentPublicIdentity",
    "QualityViolationSummary",
]
