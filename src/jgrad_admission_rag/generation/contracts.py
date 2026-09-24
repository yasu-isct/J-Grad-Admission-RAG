"""Strict, provider-neutral contracts for grounded answer generation."""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

GENERATION_SCHEMA_VERSION = "1.0"
GENERATION_PROMPT_VERSION = "grounded-answer-v1"

_SAFE_ID = re.compile(r"^[^\W][\w.:/-]*$", re.UNICODE)
_EVIDENCE_ID = re.compile(r"^evidence:[0-9]{4}$")


class GenerationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceRole(str, Enum):
    PRIMARY = "primary"
    REFERENCE = "reference"


class ClaimKind(str, Enum):
    OFFICIAL_FACT = "official_fact"
    REVIEWED_RULE = "reviewed_rule"
    APPLICANT_STATEMENT = "applicant_statement"
    LIMITATION = "limitation"


class GenerationEvidence(GenerationModel):
    """Untrusted evidence text exposed to a model under an opaque server ID.

    Authoritative Fact IDs, document IDs, pages, hashes, and paths deliberately do not cross this
    boundary. The server-owned binding between this ID and provenance belongs to M9-03.
    """

    evidence_id: str
    role: EvidenceRole
    text: str = Field(min_length=1, max_length=20_000)
    scope_label: str | None = Field(default=None, max_length=500)

    @field_validator("evidence_id")
    @classmethod
    def evidence_id_must_be_opaque(cls, value: str) -> str:
        if not _EVIDENCE_ID.fullmatch(value):
            raise ValueError("evidence_id must use the opaque evidence:NNNN format")
        return value

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence text must be non-blank")
        return value

    @field_validator("scope_label")
    @classmethod
    def scope_label_must_be_trimmed(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != value.strip()):
            raise ValueError("scope_label must be None or a non-empty trimmed string")
        return value


class GenerationEvidenceMaterial(GenerationModel):
    """Evidence content before the server assigns an opaque ID."""

    role: EvidenceRole
    text: str = Field(min_length=1, max_length=20_000)
    scope_label: str | None = Field(default=None, max_length=500)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence text must be non-blank")
        return value

    @field_validator("scope_label")
    @classmethod
    def scope_label_must_be_trimmed(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != value.strip()):
            raise ValueError("scope_label must be None or a non-empty trimmed string")
        return value


class ApplicantFact(GenerationModel):
    """One caller-supplied fact; it is untrusted and never treated as official evidence."""

    field_path: str
    value: str = Field(max_length=4_000)

    @field_validator("field_path")
    @classmethod
    def path_must_be_safe(cls, value: str) -> str:
        _validate_identifier(value, "field_path")
        return value

    @field_validator("value")
    @classmethod
    def value_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("applicant fact value must be non-blank")
        return value


class GenerationTarget(GenerationModel):
    application_label: str = Field(min_length=1, max_length=500)
    scope_targets: tuple[str, ...] = ()

    @field_validator("application_label")
    @classmethod
    def label_must_be_trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("application_label must be trimmed")
        return value

    @field_validator("scope_targets")
    @classmethod
    def scopes_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_canonical_strings(values, "scope_targets")
        return values


class GenerationRuleFinding(GenerationModel):
    """A deterministic, reviewed finding supplied as context—not recomputed by the model."""

    finding_id: str
    status: Literal["confirmed", "not_applicable", "needs_information", "needs_review"]
    statement: str = Field(min_length=1, max_length=4_000)
    evidence_ids: tuple[str, ...]
    missing_fields: tuple[str, ...] = ()

    @field_validator("finding_id")
    @classmethod
    def finding_id_must_be_safe(cls, value: str) -> str:
        _validate_identifier(value, "finding_id")
        return value

    @field_validator("statement")
    @classmethod
    def statement_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("finding statement must be non-blank")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_canonical_ids(values, "finding evidence_ids", pattern=_EVIDENCE_ID)
        return values

    @field_validator("missing_fields")
    @classmethod
    def missing_fields_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_canonical_strings(values, "missing_fields")
        for value in values:
            _validate_identifier(value, "missing field")
        return values


class GenerationRequest(GenerationModel):
    schema_version: Literal["1.0"] = GENERATION_SCHEMA_VERSION
    request_id: str
    question: str = Field(min_length=1, max_length=8_000)
    target: GenerationTarget
    applicant_facts: tuple[ApplicantFact, ...] = ()
    rule_findings: tuple[GenerationRuleFinding, ...] = ()
    evidence: tuple[GenerationEvidence, ...]

    @field_validator("request_id")
    @classmethod
    def request_id_must_be_safe(cls, value: str) -> str:
        _validate_identifier(value, "request_id")
        return value

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must be non-blank")
        return value

    @model_validator(mode="after")
    def references_must_reconcile(self) -> GenerationRequest:
        expected = tuple(f"evidence:{index:04d}" for index in range(1, len(self.evidence) + 1))
        observed = tuple(item.evidence_id for item in self.evidence)
        if observed != expected:
            raise ValueError("evidence IDs must be contiguous and server ordered")
        fact_paths = tuple(item.field_path for item in self.applicant_facts)
        if fact_paths != tuple(sorted(set(fact_paths))):
            raise ValueError("applicant facts must be sorted and unique by field_path")
        finding_ids = tuple(item.finding_id for item in self.rule_findings)
        if finding_ids != tuple(sorted(set(finding_ids))):
            raise ValueError("rule findings must be sorted and unique by finding_id")
        evidence_ids = set(observed)
        if any(set(item.evidence_ids) - evidence_ids for item in self.rule_findings):
            raise ValueError("rule finding references unknown evidence")
        return self


class GeneratedClaim(GenerationModel):
    claim_id: str
    kind: ClaimKind
    text: str = Field(min_length=1, max_length=4_000)
    evidence_ids: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()

    @field_validator("claim_id")
    @classmethod
    def claim_id_must_be_safe(cls, value: str) -> str:
        _validate_identifier(value, "claim_id")
        return value

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim text must be non-blank")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_canonical_ids(values, "claim evidence_ids", pattern=_EVIDENCE_ID)
        return values

    @field_validator("finding_ids")
    @classmethod
    def finding_ids_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_canonical_ids(values, "claim finding_ids")
        return values

    @model_validator(mode="after")
    def grounding_must_match_kind(self) -> GeneratedClaim:
        if (
            self.kind in {ClaimKind.OFFICIAL_FACT, ClaimKind.REVIEWED_RULE}
            and not self.evidence_ids
        ):
            raise ValueError("official and reviewed-rule claims require evidence IDs")
        if self.kind is ClaimKind.REVIEWED_RULE and not self.finding_ids:
            raise ValueError("reviewed-rule claims require finding IDs")
        if self.kind in {ClaimKind.APPLICANT_STATEMENT, ClaimKind.LIMITATION} and (
            self.evidence_ids or self.finding_ids
        ):
            raise ValueError("applicant and limitation claims cannot cite official context")
        return self


class GenerationDraft(GenerationModel):
    schema_version: Literal["1.0"] = GENERATION_SCHEMA_VERSION
    answer: str = Field(max_length=20_000)
    claims: tuple[GeneratedClaim, ...] = ()
    missing_information: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    needs_review: StrictBool
    refused: StrictBool
    refusal_reason: str | None = Field(default=None, max_length=1_000)

    @field_validator("missing_information", "limitations")
    @classmethod
    def text_lists_must_be_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values) or len(set(values)) != len(values):
            raise ValueError("text list entries must be non-blank and unique")
        return values

    @field_validator("refusal_reason")
    @classmethod
    def refusal_reason_must_be_explicit(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("refusal_reason must be None or a non-empty trimmed string")
        return value

    @model_validator(mode="after")
    def disposition_must_reconcile(self) -> GenerationDraft:
        claim_ids = tuple(item.claim_id for item in self.claims)
        if claim_ids != tuple(f"claim:{index:04d}" for index in range(1, len(self.claims) + 1)):
            raise ValueError("claim IDs must be contiguous and ordered")
        if self.refused:
            if self.answer or self.claims or self.refusal_reason is None:
                raise ValueError("a refusal may only contain its explicit reason")
        elif not self.answer.strip() or self.refusal_reason is not None:
            raise ValueError("a non-refusal requires an answer and no refusal_reason")
        return self


class GenerationProviderIdentity(GenerationModel):
    provider: str
    model: str
    revision: str | None = None
    prompt_version: Literal["grounded-answer-v1"] = GENERATION_PROMPT_VERSION

    @field_validator("provider", "model")
    @classmethod
    def required_values_must_be_trimmed(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("provider identity values must be non-empty and trimmed")
        return value

    @field_validator("revision")
    @classmethod
    def revision_must_be_trimmed(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != value.strip()):
            raise ValueError("revision must be None or a non-empty trimmed string")
        return value


class GenerationResult(GenerationModel):
    schema_version: Literal["1.0"] = GENERATION_SCHEMA_VERSION
    request_id: str
    provider: GenerationProviderIdentity
    output: GenerationDraft

    @field_validator("request_id")
    @classmethod
    def request_id_must_be_safe(cls, value: str) -> str:
        _validate_identifier(value, "request_id")
        return value


def assign_generation_evidence_ids(
    materials: tuple[GenerationEvidenceMaterial, ...],
) -> tuple[GenerationEvidence, ...]:
    """Assign deterministic opaque IDs without accepting caller-selected identifiers."""

    return tuple(
        GenerationEvidence(
            evidence_id=f"evidence:{index:04d}",
            role=material.role,
            text=material.text,
            scope_label=material.scope_label,
        )
        for index, material in enumerate(materials, start=1)
    )


def canonical_generation_result_bytes(result: GenerationResult) -> bytes:
    """Serialize a validated result deterministically for audit artifacts."""

    validated = GenerationResult.model_validate(result.model_dump(mode="json"))
    return (
        json.dumps(validated.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def _validate_identifier(value: str, label: str) -> None:
    if not value or value != value.strip() or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{label} must be a safe non-empty identifier")


def _validate_canonical_strings(values: tuple[str, ...], label: str) -> None:
    if values != tuple(sorted(set(values))) or any(
        not value or value != value.strip() for value in values
    ):
        raise ValueError(f"{label} must be sorted, unique, non-empty, and trimmed")


def _validate_canonical_ids(
    values: tuple[str, ...], label: str, *, pattern: re.Pattern[str] | None = None
) -> None:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{label} must be sorted and unique")
    for value in values:
        _validate_identifier(value, label)
        if pattern is not None and not pattern.fullmatch(value):
            raise ValueError(f"{label} contains an invalid opaque ID")
