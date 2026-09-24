"""Strict transport contracts for the natural-language grounded-answer endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..generation.grounded_rag import GroundedAnswer
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


__all__ = ["GroundedAnswerRequest", "GroundedAnswerResponse"]
