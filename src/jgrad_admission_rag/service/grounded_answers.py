"""Strict transport contracts for the natural-language grounded-answer endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..generation.contracts import ClaimKind
from ..generation.grounded_rag import GroundedAnswer
from ..generation.question_analysis import QuestionAnalysis, QuestionSubquestion
from .demo_requirements import (
    DemoApplicantInput,
    DemoEvidence,
    DemoModel,
    DemoTargetRequest,
    DemoTargetSummary,
)


class GroundedAnswerRequest(DemoModel):
    schema_version: Literal["1.0"] = "1.0"
    question: str = Field(min_length=1, max_length=1000)
    target: DemoTargetRequest
    applicant: DemoApplicantInput

    @field_validator("question")
    @classmethod
    def question_must_be_safe_text(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("question must be trimmed printable text")
        return value


class GroundedAnswerResponse(DemoModel):
    schema_version: Literal["1.0"] = "1.0"
    target: DemoTargetSummary
    reviewed_scope_statement: str = Field(min_length=1, max_length=500)
    official_source_url: str
    local_pdf_url: str | None = None
    answer: GroundedAnswer
    evidence: tuple[DemoEvidence, ...]

    @model_validator(mode="after")
    def evidence_must_cover_every_citation(self) -> GroundedAnswerResponse:
        facts = {(item.document_id, item.fact_id, item.pages) for item in self.evidence}
        if any(
            (item.document_id, item.fact_id, item.source_pages) not in facts
            for item in self.answer.citation_inventory
        ):
            raise ValueError("response evidence does not cover answer citations")
        if self.answer.document_id != self.target_document_id:
            raise ValueError("answer and evidence target do not reconcile")
        return self

    @property
    def target_document_id(self) -> str:
        if self.evidence:
            return self.evidence[0].document_id
        return self.answer.document_id


class GenerationStatusResponse(DemoModel):
    schema_version: Literal["1.0"] = "1.0"
    provider: Literal["reviewed-state-offline", "openai-responses", "deepseek-responses"]
    model: str
    mode: Literal["offline_rules", "online_model"]
    configured: bool
    label: str
    request_timeout_seconds: int = Field(gt=0, le=3_600, strict=True)


class NaturalLanguageSubanswer(DemoModel):
    schema_version: Literal["1.0"] = "1.0"
    subquestion: QuestionSubquestion
    status: Literal[
        "answered", "interpreted", "no_clear_evidence", "needs_clarification", "unsupported"
    ]
    message: str = Field(min_length=1, max_length=1_000)
    claim_ids: tuple[str, ...] = ()


class PublicGroundedCitation(DemoModel):
    document_id: str
    fact_id: str
    source_pages: tuple[int, ...]
    role: Literal["primary", "reference"]


class PublicGroundedClaim(DemoModel):
    claim_id: str
    kind: ClaimKind
    text: str = Field(min_length=1, max_length=25_000)
    citations: tuple[PublicGroundedCitation, ...] = ()


class PublicGroundedAnswer(DemoModel):
    answer: str = Field(max_length=200_000)
    claims: tuple[PublicGroundedClaim, ...] = ()
    needs_review: bool
    missing_information: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def answer_must_match_claims(self) -> PublicGroundedAnswer:
        if self.answer != "\n".join(item.text for item in self.claims):
            raise ValueError("public answer must equal its ordered claim projection")
        return self


class PublicGroundedResult(DemoModel):
    target: DemoTargetSummary
    reviewed_scope_statement: str = Field(min_length=1, max_length=500)
    official_source_url: str
    local_pdf_url: str | None = None
    answer: PublicGroundedAnswer
    evidence: tuple[DemoEvidence, ...]

    @model_validator(mode="after")
    def evidence_must_cover_every_public_citation(self) -> PublicGroundedResult:
        evidence_keys = {(item.document_id, item.fact_id, item.pages) for item in self.evidence}
        citation_keys = {
            (citation.document_id, citation.fact_id, citation.source_pages)
            for claim in self.answer.claims
            for citation in claim.citations
        }
        document_ids = {key[0] for key in citation_keys}
        if (
            citation_keys != evidence_keys
            or (citation_keys and len(document_ids) != 1)
            or any(
                claim.kind not in {ClaimKind.APPLICANT_STATEMENT, ClaimKind.REVIEWED_DISPOSITION}
                and not claim.citations
                for claim in self.answer.claims
            )
            or any(
                claim.kind is ClaimKind.REVIEWED_DISPOSITION and claim.citations
                for claim in self.answer.claims
            )
        ):
            raise ValueError("public evidence must exactly cover answer citations")
        return self


class NaturalLanguageDeliveryMetadata(DemoModel):
    source: Literal["live", "cache_hit", "offline"]
    generation_ms: int | None = Field(default=None, ge=0, strict=True)
    validation_ms: int = Field(ge=0, strict=True)
    knowledge_base_version: str = Field(pattern=r"^kb-[0-9a-f]{12}$")
    cache_scope: Literal["process_memory"] = "process_memory"
    cache_cleared_on_restart: Literal[True] = True
    cache_ttl_seconds: int = Field(ge=1, le=3_600, strict=True)


class NaturalLanguageAnswerResponse(DemoModel):
    schema_version: Literal["1.0"] = "1.0"
    mode: GenerationStatusResponse
    analysis: QuestionAnalysis
    summary: str = Field(min_length=1, max_length=1_000)
    subanswers: tuple[NaturalLanguageSubanswer, ...]
    result: PublicGroundedResult | None = None
    delivery: NaturalLanguageDeliveryMetadata
    missing_context: tuple[str, ...] = ()
    unsupported_parts: tuple[str, ...] = ()

    @model_validator(mode="after")
    def subanswers_must_cover_analysis(self) -> NaturalLanguageAnswerResponse:
        if tuple(item.subquestion for item in self.subanswers) != self.analysis.subquestions:
            raise ValueError("subanswers must preserve every analyzed subquestion in order")
        if self.missing_context != self.analysis.missing_context:
            raise ValueError("missing context must be analysis-owned")
        if self.unsupported_parts != self.analysis.unsupported_parts:
            raise ValueError("unsupported parts must be analysis-owned")
        answered_claims = {claim_id for item in self.subanswers for claim_id in item.claim_ids}
        result_claims = (
            {claim.claim_id for claim in self.result.answer.claims}
            if self.result is not None
            else set()
        )
        if answered_claims != result_claims:
            raise ValueError("subanswer claim mapping must cover the public result")
        if (self.result is not None) != bool(result_claims):
            raise ValueError("a public result must contain at least one claim")
        return self


__all__ = [
    "GenerationStatusResponse",
    "GroundedAnswerRequest",
    "GroundedAnswerResponse",
    "NaturalLanguageAnswerResponse",
    "NaturalLanguageDeliveryMetadata",
    "NaturalLanguageSubanswer",
    "PublicGroundedAnswer",
    "PublicGroundedCitation",
    "PublicGroundedClaim",
    "PublicGroundedResult",
]
