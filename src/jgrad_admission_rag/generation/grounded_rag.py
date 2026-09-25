"""Fail-closed orchestration from reviewed evidence to authoritative grounded citations."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from ..reasoning.applicability import ApplicabilityStatus, EvidenceRole as ReviewedEvidenceRole
from ..reasoning.cited_answer import CitedAnswer, ReportStatus, RuleFinding
from ..schemas.evidence_pack import AttachedReferenceEvidence, EvidencePack, PrimaryEvidence
from .contracts import (
    ApplicantFact,
    ClaimKind,
    EvidenceRole,
    GeneratedClaim,
    GenerationEvidence,
    GenerationLimitation,
    GenerationProviderIdentity,
    GenerationRequest,
    GenerationRuleFinding,
    GenerationTarget,
)
from .provider import GenerationError, GenerationErrorCode, GenerationProvider, generate_checked

GROUNDED_RAG_SCHEMA_VERSION = "1.0"
MAX_GROUNDED_EVIDENCE_RECORDS = 16
MAX_GROUNDED_EVIDENCE_CHARACTERS = 60_000
_SAFE_ID = re.compile(r"^[^\W][\w.:/-]*$", re.UNICODE)


class GroundedRagErrorCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EVIDENCE_MISMATCH = "evidence_mismatch"
    RULE_STATE_MISMATCH = "rule_state_mismatch"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_REFUSAL = "provider_refusal"
    INCOMPLETE_RESPONSE = "incomplete_response"
    MALFORMED_OUTPUT = "malformed_output"
    INVALID_CITATION = "invalid_citation"
    UNSUPPORTED_CLAIM = "unsupported_claim"


_SAFE_MESSAGES = {
    GroundedRagErrorCode.INVALID_INPUT: "grounded generation input is invalid",
    GroundedRagErrorCode.INSUFFICIENT_EVIDENCE: "grounded generation has insufficient evidence",
    GroundedRagErrorCode.EVIDENCE_MISMATCH: "grounded generation evidence does not reconcile",
    GroundedRagErrorCode.RULE_STATE_MISMATCH: "grounded generation rule state does not reconcile",
    GroundedRagErrorCode.PROVIDER_UNAVAILABLE: "grounded generation provider is unavailable",
    GroundedRagErrorCode.PROVIDER_TIMEOUT: "grounded generation provider timed out",
    GroundedRagErrorCode.PROVIDER_REFUSAL: "grounded generation provider refused the request",
    GroundedRagErrorCode.INCOMPLETE_RESPONSE: "grounded generation provider response is incomplete",
    GroundedRagErrorCode.MALFORMED_OUTPUT: "grounded generation provider output is malformed",
    GroundedRagErrorCode.INVALID_CITATION: "grounded generation citation validation failed",
    GroundedRagErrorCode.UNSUPPORTED_CLAIM: "grounded generation contains an unsupported claim",
}


class GroundedRagError(Exception):
    """Stable public failure that never retains caller, evidence, or provider payloads."""

    def __init__(self, code: GroundedRagErrorCode) -> None:
        self.code = code
        super().__init__(_SAFE_MESSAGES[code])


class GroundedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GroundedRagTarget(GroundedModel):
    document_id: str
    application_label: str = Field(min_length=1, max_length=500)
    scope_targets: tuple[str, ...] = ()
    parent_college: str | None = Field(default=None, max_length=500)

    @field_validator("document_id")
    @classmethod
    def document_id_must_be_safe(cls, value: str) -> str:
        _validate_identifier(value)
        return value

    @field_validator("application_label")
    @classmethod
    def label_must_be_trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("application label must be trimmed")
        return value

    @field_validator("scope_targets")
    @classmethod
    def scopes_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))) or any(
            not value or value != value.strip() for value in values
        ):
            raise ValueError("scope targets must be sorted, unique, non-empty, and trimmed")
        return values

    @field_validator("parent_college")
    @classmethod
    def parent_college_must_be_trimmed(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != value.strip()):
            raise ValueError("parent college must be None or a non-empty trimmed string")
        return value

    def generation_target(self) -> GenerationTarget:
        return GenerationTarget(
            application_label=self.application_label,
            scope_targets=self.scope_targets,
            parent_college=self.parent_college,
        )


class GroundedCitation(GroundedModel):
    evidence_id: str
    document_id: str
    fact_id: str
    source_pages: tuple[int, ...]
    role: EvidenceRole
    source_kb_sha256: str
    source_pdf_sha256: str

    @field_validator("document_id", "fact_id")
    @classmethod
    def identifiers_must_be_safe(cls, value: str) -> str:
        _validate_identifier(value)
        return value

    @field_validator("evidence_id")
    @classmethod
    def evidence_id_must_be_opaque(cls, value: str) -> str:
        if re.fullmatch(r"evidence:[0-9]{4}", value) is None:
            raise ValueError("citation evidence ID must be opaque")
        return value

    @field_validator("source_pages")
    @classmethod
    def pages_must_be_canonical(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value or value != tuple(sorted(set(value))) or any(page <= 0 for page in value):
            raise ValueError("citation pages must be positive, sorted, unique, and non-empty")
        return value

    @field_validator("source_kb_sha256", "source_pdf_sha256")
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("citation hashes must be lowercase SHA-256 values")
        return value


class GroundedClaim(GroundedModel):
    claim_id: str
    kind: ClaimKind
    text: str = Field(min_length=1, max_length=25_000)
    citations: tuple[GroundedCitation, ...] = ()
    finding_ids: tuple[str, ...] = ()
    applicant_fact_paths: tuple[str, ...] = ()

    @field_validator("claim_id")
    @classmethod
    def claim_id_must_be_safe(cls, value: str) -> str:
        _validate_identifier(value)
        return value

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim text must be non-blank")
        return value

    @field_validator("finding_ids", "applicant_fact_paths")
    @classmethod
    def identifiers_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("claim identifiers must be sorted and unique")
        for value in values:
            _validate_identifier(value)
        return values

    @model_validator(mode="after")
    def grounding_must_match_kind(self) -> GroundedClaim:
        if self.citations != tuple(sorted(set(self.citations), key=_citation_key)):
            raise ValueError("claim citations must be sorted and unique")
        if self.kind is ClaimKind.OFFICIAL_FACT:
            if len(self.citations) != 1 or self.finding_ids or self.applicant_fact_paths:
                raise ValueError("official claims require one citation only")
        elif self.kind is ClaimKind.REVIEWED_RULE:
            if not self.citations or len(self.finding_ids) != 1 or self.applicant_fact_paths:
                raise ValueError("reviewed claims require citations and one finding only")
        elif self.citations or self.finding_ids or len(self.applicant_fact_paths) != 1:
            raise ValueError("applicant claims require one applicant path only")
        return self


class GroundedAnswer(GroundedModel):
    schema_version: Literal["1.0"] = GROUNDED_RAG_SCHEMA_VERSION
    request_id: str
    document_id: str
    source_kb_sha256: str
    source_pdf_sha256: str
    provider: GenerationProviderIdentity
    reviewed_state: CitedAnswer
    answer: str = Field(max_length=200_000)
    claims: tuple[GroundedClaim, ...] = ()
    citation_inventory: tuple[GroundedCitation, ...] = ()
    missing_information: tuple[str, ...] = ()
    limitations: tuple[GenerationLimitation, ...] = ()
    needs_review: StrictBool

    @field_validator("request_id", "document_id")
    @classmethod
    def identifiers_must_be_safe(cls, value: str) -> str:
        _validate_identifier(value)
        return value

    @field_validator("source_kb_sha256", "source_pdf_sha256")
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("answer hashes must be lowercase SHA-256 values")
        return value

    @field_validator("missing_information")
    @classmethod
    def missing_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("missing information must be sorted and unique")
        for value in values:
            _validate_identifier(value)
        return values

    @field_validator("limitations")
    @classmethod
    def limitations_must_be_canonical(
        cls, values: tuple[GenerationLimitation, ...]
    ) -> tuple[GenerationLimitation, ...]:
        if values != tuple(sorted(set(values), key=lambda item: item.value)):
            raise ValueError("limitations must be sorted and unique")
        return values

    @model_validator(mode="after")
    def answer_must_be_self_auditing(self) -> GroundedAnswer:
        if tuple(claim.claim_id for claim in self.claims) != tuple(
            f"claim:{index:04d}" for index in range(1, len(self.claims) + 1)
        ):
            raise ValueError("claim IDs must be contiguous and ordered")
        if self.answer != "\n".join(claim.text for claim in self.claims):
            raise ValueError("answer must equal the ordered claim projection")
        expected_inventory = tuple(
            sorted(
                {citation for claim in self.claims for citation in claim.citations},
                key=_citation_key,
            )
        )
        if self.citation_inventory != expected_inventory:
            raise ValueError("citation inventory does not reconcile")
        if any(
            citation.document_id != self.document_id
            or citation.source_kb_sha256 != self.source_kb_sha256
            or citation.source_pdf_sha256 != self.source_pdf_sha256
            for citation in self.citation_inventory
        ):
            raise ValueError("citation source identity does not reconcile")
        if (
            self.reviewed_state.document_id != self.document_id
            or self.reviewed_state.source_kb_sha256 != self.source_kb_sha256
            or self.reviewed_state.source_pdf_sha256 != self.source_pdf_sha256
        ):
            raise ValueError("reviewed state source identity does not reconcile")
        reviewed_missing = tuple(
            sorted({item.field_path for item in self.reviewed_state.missing_information})
        )
        if self.missing_information != reviewed_missing:
            raise ValueError("reviewed missing-information state does not reconcile")
        if self.reviewed_state.report_status is not ReportStatus.COMPLETE and not self.needs_review:
            raise ValueError("reviewed report status requires review")
        if not self.claims and not self.needs_review:
            raise ValueError("an empty grounded answer must require review")
        return self


@dataclass(frozen=True, slots=True)
class _EvidenceBinding:
    evidence_id: str
    document_id: str
    fact_id: str
    source_pages: tuple[int, ...]
    role: EvidenceRole
    source_kb_sha256: str
    source_pdf_sha256: str
    text: str
    scope_label: str

    def citation(self) -> GroundedCitation:
        return GroundedCitation(
            evidence_id=self.evidence_id,
            document_id=self.document_id,
            fact_id=self.fact_id,
            source_pages=self.source_pages,
            role=self.role,
            source_kb_sha256=self.source_kb_sha256,
            source_pdf_sha256=self.source_pdf_sha256,
        )


@dataclass(frozen=True, slots=True)
class _PreparedRequest:
    request: GenerationRequest
    bindings_by_id: dict[str, _EvidenceBinding]
    finding_evidence_ids: dict[str, tuple[str, ...]]


def run_grounded_rag(
    provider: GenerationProvider,
    *,
    request_id: str,
    question: str | None = None,
    target: GroundedRagTarget,
    applicant_facts: tuple[ApplicantFact, ...],
    evidence_pack: EvidencePack,
    cited_answer: CitedAnswer,
) -> GroundedAnswer:
    """Generate once, then bind every factual claim to server-owned authoritative provenance."""

    validated_inputs: (
        tuple[GroundedRagTarget, tuple[ApplicantFact, ...], EvidencePack, CitedAnswer] | None
    )
    try:
        validated_inputs = (
            GroundedRagTarget.model_validate(target.model_dump(mode="json")),
            tuple(
                ApplicantFact.model_validate(item.model_dump(mode="json"))
                for item in applicant_facts
            ),
            EvidencePack.model_validate(evidence_pack.model_dump(mode="json")),
            CitedAnswer.model_validate(cited_answer.model_dump(mode="json")),
        )
        _validate_identifier(request_id)
    except Exception:
        validated_inputs = None
    if validated_inputs is None:
        raise GroundedRagError(GroundedRagErrorCode.INVALID_INPUT) from None

    checked_target, checked_facts, checked_pack, checked_answer = validated_inputs
    fact_paths = tuple(item.field_path for item in checked_facts)
    if fact_paths != tuple(sorted(set(fact_paths))):
        raise GroundedRagError(GroundedRagErrorCode.INVALID_INPUT)
    if not checked_pack.primary_evidence and not checked_pack.attached_reference_evidence:
        raise GroundedRagError(GroundedRagErrorCode.INSUFFICIENT_EVIDENCE)
    checked_records = checked_pack.primary_evidence + checked_pack.attached_reference_evidence
    if (
        len(checked_records) > MAX_GROUNDED_EVIDENCE_RECORDS
        or sum(len(item.text) + len(" / ".join(item.section_path)) for item in checked_records)
        > MAX_GROUNDED_EVIDENCE_CHARACTERS
    ):
        raise GroundedRagError(GroundedRagErrorCode.INSUFFICIENT_EVIDENCE)

    prepared: _PreparedRequest | None = None
    try:
        prepared = _prepare_request(
            request_id,
            question,
            checked_target,
            checked_facts,
            checked_pack,
            checked_answer,
        )
    except Exception:
        pass
    if prepared is None:
        raise GroundedRagError(GroundedRagErrorCode.EVIDENCE_MISMATCH) from None

    generation_result = None
    provider_error: GroundedRagErrorCode | None = None
    try:
        generation_result = generate_checked(provider, prepared.request)
    except GenerationError as error:
        provider_error = _map_generation_error(error.code)
    except Exception:
        provider_error = GroundedRagErrorCode.PROVIDER_UNAVAILABLE
    if provider_error is not None:
        raise GroundedRagError(provider_error) from None

    grounded: GroundedAnswer | None = None
    failure = GroundedRagErrorCode.INVALID_CITATION
    try:
        if generation_result.output.missing_information != tuple(
            sorted({item.field_path for item in checked_answer.missing_information})
        ):
            failure = GroundedRagErrorCode.RULE_STATE_MISMATCH
            raise ValueError
        if (
            checked_answer.report_status is not ReportStatus.COMPLETE
            and not generation_result.output.needs_review
        ):
            failure = GroundedRagErrorCode.RULE_STATE_MISMATCH
            raise ValueError
        claims = tuple(
            _ground_claim(
                claim,
                bindings_by_id=prepared.bindings_by_id,
                finding_evidence_ids=prepared.finding_evidence_ids,
            )
            for claim in generation_result.output.claims
        )
        inventory = tuple(
            sorted(
                {citation for claim in claims for citation in claim.citations},
                key=_citation_key,
            )
        )
        grounded = GroundedAnswer(
            request_id=request_id,
            document_id=checked_pack.runtime.document_id,
            source_kb_sha256=checked_pack.runtime.source_kb_sha256,
            source_pdf_sha256=checked_pack.runtime.source_pdf_sha256,
            provider=generation_result.provider,
            reviewed_state=checked_answer,
            answer="\n".join(claim.text for claim in claims),
            claims=claims,
            citation_inventory=inventory,
            missing_information=generation_result.output.missing_information,
            limitations=generation_result.output.limitations,
            needs_review=generation_result.output.needs_review,
        )
    except Exception:
        grounded = None
    if grounded is None:
        raise GroundedRagError(failure) from None
    return grounded


def canonical_grounded_answer_bytes(answer: GroundedAnswer) -> bytes:
    """Return stable audit bytes without performing retrieval or provider activity."""

    validated: GroundedAnswer | None = None
    try:
        validated = GroundedAnswer.model_validate(answer.model_dump(mode="json"))
    except Exception:
        pass
    if validated is None:
        raise GroundedRagError(GroundedRagErrorCode.INVALID_INPUT) from None
    return (
        json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _prepare_request(
    request_id: str,
    question: str | None,
    target: GroundedRagTarget,
    applicant_facts: tuple[ApplicantFact, ...],
    pack: EvidencePack,
    answer: CitedAnswer,
) -> _PreparedRequest:
    if target.document_id != pack.runtime.document_id:
        raise ValueError("selected target does not match retrieval document")
    filtered_scopes = pack.request.metadata_filter.scope_targets
    preferred_scopes = pack.request.scope_preference.preferred_scope_targets
    if filtered_scopes and filtered_scopes != target.scope_targets:
        raise ValueError("selected target does not match retrieval scope filter")
    if preferred_scopes and preferred_scopes != target.scope_targets:
        raise ValueError("selected target does not match retrieval scope preference")
    if target.scope_targets and not (filtered_scopes or preferred_scopes):
        raise ValueError("selected target is absent from retrieval scope")
    selected_colleges = (target.parent_college,) if target.parent_college is not None else ()
    filtered_colleges = pack.request.metadata_filter.parent_colleges
    preferred_colleges = pack.request.scope_preference.preferred_parent_colleges
    if filtered_colleges and filtered_colleges != selected_colleges:
        raise ValueError("selected parent college does not match retrieval filter")
    if preferred_colleges and preferred_colleges != selected_colleges:
        raise ValueError("selected parent college does not match retrieval preference")
    if selected_colleges and not (filtered_colleges or preferred_colleges):
        raise ValueError("selected parent college is absent from retrieval scope")
    if (
        answer.document_id != pack.runtime.document_id
        or answer.source_kb_sha256 != pack.runtime.source_kb_sha256
        or answer.source_pdf_sha256 != pack.runtime.source_pdf_sha256
    ):
        raise ValueError("source identity mismatch")

    records: tuple[PrimaryEvidence | AttachedReferenceEvidence, ...] = (
        pack.primary_evidence + pack.attached_reference_evidence
    )
    bindings = tuple(_binding(index, record, pack) for index, record in enumerate(records, start=1))
    by_fact_id = {binding.fact_id: binding for binding in bindings}
    if len(by_fact_id) != len(bindings):
        raise ValueError("ambiguous Fact identity")

    expected_citations = {
        (
            item.document_id,
            item.fact_id,
            item.source_pages,
            EvidenceRole.PRIMARY
            if item.role is ReviewedEvidenceRole.PRIMARY
            else EvidenceRole.REFERENCE,
        )
        for item in answer.citation_inventory
    }
    for document_id, fact_id, pages, role in expected_citations:
        binding = by_fact_id.get(fact_id)
        if binding is None or (
            binding.document_id,
            binding.fact_id,
            binding.source_pages,
            binding.role,
        ) != (document_id, fact_id, pages, role):
            raise ValueError("reviewed citation is outside the EvidencePack")

    missing_by_rule: dict[str, tuple[str, ...]] = {}
    for finding in answer.rule_findings:
        missing_by_rule[finding.rule_id] = tuple(
            item.field_path
            for item in answer.missing_information
            if item.rule_id == finding.rule_id
        )
    if set(answer.source_rule_ids) != {finding.rule_id for finding in answer.rule_findings}:
        raise ValueError("not every reviewed rule has citable evidence")
    if any(
        finding.original_status is not ApplicabilityStatus.NOT_APPLICABLE
        and not _finding_scope_matches_target(finding, target)
        for finding in answer.rule_findings
    ):
        raise ValueError("reviewed finding scope does not match selected target")

    rule_generation_findings = tuple(
        _generation_finding(finding, by_fact_id, missing_by_rule[finding.rule_id])
        for finding in answer.rule_findings
    )
    warning_generation_findings = tuple(
        GenerationRuleFinding(
            finding_id=f"finding:{warning.warning_id}",
            status="needs_review",
            statement=(
                f"warning_id={warning.warning_id}; kind={warning.kind}; "
                f"certainty={warning.certainty.value}; rules={','.join(warning.rule_ids)}"
            ),
            evidence_ids=tuple(
                sorted({by_fact_id[item.fact_id].evidence_id for item in warning.citations})
            ),
        )
        for warning in answer.interaction_warnings
    )
    generation_findings = tuple(
        sorted(
            rule_generation_findings + warning_generation_findings,
            key=lambda item: item.finding_id,
        )
    )
    finding_evidence_ids = {
        finding.finding_id: finding.evidence_ids for finding in generation_findings
    }
    generation_evidence = tuple(
        GenerationEvidence(
            evidence_id=binding.evidence_id,
            role=binding.role,
            text=binding.text,
            scope_label=binding.scope_label,
        )
        for binding in bindings
    )
    request = GenerationRequest(
        request_id=request_id,
        question=question or pack.request.query,
        target=target.generation_target(),
        applicant_facts=applicant_facts,
        rule_findings=generation_findings,
        evidence=generation_evidence,
    )
    return _PreparedRequest(
        request=request,
        bindings_by_id={binding.evidence_id: binding for binding in bindings},
        finding_evidence_ids=finding_evidence_ids,
    )


def _binding(
    index: int,
    record: PrimaryEvidence | AttachedReferenceEvidence,
    pack: EvidencePack,
) -> _EvidenceBinding:
    return _EvidenceBinding(
        evidence_id=f"evidence:{index:04d}",
        document_id=record.document_id,
        fact_id=record.fact_id,
        source_pages=record.source_pages,
        role=(
            EvidenceRole.PRIMARY if isinstance(record, PrimaryEvidence) else EvidenceRole.REFERENCE
        ),
        source_kb_sha256=pack.runtime.source_kb_sha256,
        source_pdf_sha256=pack.runtime.source_pdf_sha256,
        text=record.text,
        scope_label=" / ".join(record.section_path),
    )


def _finding_scope_matches_target(finding: RuleFinding, target: GroundedRagTarget) -> bool:
    scope = finding.scope
    if scope.scope_type == "global":
        return True
    if scope.scope_type == "college":
        expected_colleges = set(scope.scope_targets)
        if scope.parent_college is not None:
            expected_colleges.add(scope.parent_college)
        return target.parent_college in expected_colleges
    if scope.scope_targets and not set(scope.scope_targets).intersection(target.scope_targets):
        return False
    if scope.parent_college is not None and scope.parent_college != target.parent_college:
        return False
    return True


def _generation_finding(
    finding: RuleFinding,
    by_fact_id: dict[str, _EvidenceBinding],
    missing_fields: tuple[str, ...],
) -> GenerationRuleFinding:
    evidence_ids = tuple(
        sorted({by_fact_id[item.fact_id].evidence_id for item in finding.citations})
    )
    status = {
        ApplicabilityStatus.CONFIRMED: "confirmed",
        ApplicabilityStatus.NOT_APPLICABLE: "not_applicable",
        ApplicabilityStatus.NEEDS_INFORMATION: "needs_information",
    }[finding.original_status]
    scope_targets = ",".join(finding.scope.scope_targets) or "none"
    statement = (
        f"rule_id={finding.rule_id}; original_status={finding.original_status.value}; "
        f"disposition={finding.disposition.value}; subject={finding.subject_key}; "
        f"scope_type={finding.scope.scope_type}; scope_targets={scope_targets}"
    )
    return GenerationRuleFinding(
        finding_id=finding.finding_id,
        status=status,
        statement=statement,
        evidence_ids=evidence_ids,
        missing_fields=missing_fields,
    )


def _ground_claim(
    claim: GeneratedClaim,
    *,
    bindings_by_id: dict[str, _EvidenceBinding],
    finding_evidence_ids: dict[str, tuple[str, ...]],
) -> GroundedClaim:
    kind = claim.kind
    if kind is ClaimKind.OFFICIAL_FACT:
        citation_ids = claim.evidence_ids
    elif kind is ClaimKind.REVIEWED_RULE:
        citation_ids = finding_evidence_ids[claim.finding_ids[0]]
        if claim.evidence_ids != citation_ids:
            raise ValueError("reviewed claim citations changed")
    else:
        citation_ids = ()
    citations = tuple(
        sorted((bindings_by_id[item].citation() for item in citation_ids), key=_citation_key)
    )
    return GroundedClaim(
        claim_id=claim.claim_id,
        kind=kind,
        text=claim.text,
        citations=citations,
        finding_ids=claim.finding_ids,
        applicant_fact_paths=claim.applicant_fact_paths,
    )


def _map_generation_error(code: GenerationErrorCode) -> GroundedRagErrorCode:
    return {
        GenerationErrorCode.INVALID_INPUT: GroundedRagErrorCode.INVALID_INPUT,
        GenerationErrorCode.MISSING_API_KEY: GroundedRagErrorCode.PROVIDER_UNAVAILABLE,
        GenerationErrorCode.PROVIDER_UNAVAILABLE: GroundedRagErrorCode.PROVIDER_UNAVAILABLE,
        GenerationErrorCode.PROVIDER_TIMEOUT: GroundedRagErrorCode.PROVIDER_TIMEOUT,
        GenerationErrorCode.PROVIDER_REFUSAL: GroundedRagErrorCode.PROVIDER_REFUSAL,
        GenerationErrorCode.INCOMPLETE_RESPONSE: GroundedRagErrorCode.INCOMPLETE_RESPONSE,
        GenerationErrorCode.MALFORMED_OUTPUT: GroundedRagErrorCode.MALFORMED_OUTPUT,
        GenerationErrorCode.UNKNOWN_REFERENCE: GroundedRagErrorCode.INVALID_CITATION,
        GenerationErrorCode.UNSUPPORTED_CLAIM: GroundedRagErrorCode.UNSUPPORTED_CLAIM,
        GenerationErrorCode.STATE_MISMATCH: GroundedRagErrorCode.RULE_STATE_MISMATCH,
    }[code]


def _citation_key(citation: GroundedCitation) -> tuple[object, ...]:
    return (
        citation.document_id,
        citation.fact_id,
        citation.source_pages,
        citation.role.value,
        citation.evidence_id,
    )


def _validate_identifier(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or not _SAFE_ID.fullmatch(value)
    ):
        raise ValueError("unsafe identifier")
