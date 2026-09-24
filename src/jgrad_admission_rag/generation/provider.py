"""Provider boundary, deterministic fake, and fail-closed output checks."""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from .contracts import (
    GENERATION_SCHEMA_VERSION,
    ApplicantFact,
    ClaimKind,
    GeneratedClaim,
    GenerationDraft,
    GenerationEvidence,
    GenerationLimitation,
    GenerationProviderIdentity,
    GenerationRequest,
    GenerationResult,
    GenerationRuleFinding,
    assemble_generation_answer,
)


class GenerationErrorCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    MISSING_API_KEY = "missing_api_key"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_REFUSAL = "provider_refusal"
    INCOMPLETE_RESPONSE = "incomplete_response"
    MALFORMED_OUTPUT = "malformed_output"
    UNKNOWN_REFERENCE = "unknown_reference"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    STATE_MISMATCH = "state_mismatch"


_SAFE_MESSAGES = {
    GenerationErrorCode.INVALID_INPUT: "generation input is invalid",
    GenerationErrorCode.MISSING_API_KEY: "generation provider credentials are unavailable",
    GenerationErrorCode.PROVIDER_UNAVAILABLE: "generation provider is unavailable",
    GenerationErrorCode.PROVIDER_TIMEOUT: "generation provider timed out",
    GenerationErrorCode.PROVIDER_REFUSAL: "generation provider refused the request",
    GenerationErrorCode.INCOMPLETE_RESPONSE: "generation provider returned an incomplete response",
    GenerationErrorCode.MALFORMED_OUTPUT: "generation provider returned malformed output",
    GenerationErrorCode.UNKNOWN_REFERENCE: "generation output contains an unknown reference",
    GenerationErrorCode.UNSUPPORTED_CLAIM: "generation output contains an unsupported claim",
    GenerationErrorCode.STATE_MISMATCH: "generation output conflicts with reviewed state",
}


class GenerationError(Exception):
    """Privacy-safe error with a stable code and no caller/provider payload."""

    def __init__(self, code: GenerationErrorCode) -> None:
        self.code = code
        super().__init__(_SAFE_MESSAGES[code])


@runtime_checkable
class GenerationProvider(Protocol):
    @property
    def identity(self) -> GenerationProviderIdentity: ...

    def generate(self, request: GenerationRequest) -> GenerationDraft: ...


def generate_checked(provider: GenerationProvider, request: GenerationRequest) -> GenerationResult:
    """Validate both sides of a provider call and reject all unbound references."""

    try:
        checked_request = GenerationRequest.model_validate(request.model_dump(mode="json"))
    except Exception:
        raise GenerationError(GenerationErrorCode.INVALID_INPUT) from None
    try:
        identity = GenerationProviderIdentity.model_validate(
            provider.identity.model_dump(mode="json")
        )
    except Exception:
        raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE) from None

    try:
        raw_output = provider.generate(checked_request)
    except GenerationError:
        raise
    except Exception:
        raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE) from None

    try:
        output = GenerationDraft.model_validate(raw_output.model_dump(mode="json"))
    except Exception:
        raise GenerationError(GenerationErrorCode.MALFORMED_OUTPUT) from None

    if output.refused:
        raise GenerationError(GenerationErrorCode.PROVIDER_REFUSAL)

    known_evidence = {item.evidence_id for item in checked_request.evidence}
    known_findings = {item.finding_id for item in checked_request.rule_findings}
    known_applicant_facts = {item.field_path for item in checked_request.applicant_facts}
    if any(
        set(claim.evidence_ids) - known_evidence
        or set(claim.finding_ids) - known_findings
        or set(claim.applicant_fact_paths) - known_applicant_facts
        for claim in output.claims
    ):
        raise GenerationError(GenerationErrorCode.UNKNOWN_REFERENCE)

    findings_by_id = {item.finding_id: item for item in checked_request.rule_findings}
    evidence_by_id = {item.evidence_id: item for item in checked_request.evidence}
    applicant_facts_by_path = {item.field_path: item for item in checked_request.applicant_facts}
    cited_finding_ids: list[str] = []
    for claim in output.claims:
        if claim.kind is ClaimKind.OFFICIAL_FACT and len(claim.evidence_ids) != 1:
            raise GenerationError(GenerationErrorCode.UNSUPPORTED_CLAIM)
        if claim.kind is ClaimKind.APPLICANT_STATEMENT and len(claim.applicant_fact_paths) != 1:
            raise GenerationError(GenerationErrorCode.UNSUPPORTED_CLAIM)
        if claim.kind is ClaimKind.REVIEWED_RULE:
            if len(claim.finding_ids) != 1:
                raise GenerationError(GenerationErrorCode.UNSUPPORTED_CLAIM)
            finding = findings_by_id[claim.finding_ids[0]]
            if claim.evidence_ids != finding.evidence_ids:
                raise GenerationError(GenerationErrorCode.UNSUPPORTED_CLAIM)
            cited_finding_ids.extend(claim.finding_ids)

    if output.claims and tuple(sorted(cited_finding_ids)) != tuple(sorted(known_findings)):
        raise GenerationError(GenerationErrorCode.STATE_MISMATCH)

    pending = tuple(
        finding
        for finding in checked_request.rule_findings
        if finding.status in {"needs_information", "needs_review", "not_covered"}
    )
    if pending and not output.needs_review:
        raise GenerationError(GenerationErrorCode.STATE_MISMATCH)
    required_missing = {
        field_path
        for finding in pending
        if finding.status == "needs_information"
        for field_path in finding.missing_fields
    }
    if not required_missing <= set(output.missing_information):
        raise GenerationError(GenerationErrorCode.STATE_MISMATCH)

    known_missing = {
        field_path
        for finding in checked_request.rule_findings
        for field_path in finding.missing_fields
    }
    if set(output.missing_information) - known_missing:
        raise GenerationError(GenerationErrorCode.UNKNOWN_REFERENCE)

    hydrated_claims = tuple(
        GeneratedClaim.model_validate(
            {
                **claim.model_dump(mode="json"),
                "text": _render_claim_text(
                    claim,
                    evidence_by_id=evidence_by_id,
                    findings_by_id=findings_by_id,
                    applicant_facts_by_path=applicant_facts_by_path,
                ),
            }
        )
        for claim in output.claims
    )
    hydrated_output = GenerationDraft(
        answer=assemble_generation_answer(hydrated_claims),
        claims=hydrated_claims,
        missing_information=output.missing_information,
        limitations=output.limitations,
        needs_review=output.needs_review,
        refused=False,
        refusal_reason=None,
    )

    return GenerationResult(
        schema_version=GENERATION_SCHEMA_VERSION,
        request_id=checked_request.request_id,
        provider=identity,
        output=hydrated_output,
    )


class DeterministicFakeGenerationProvider:
    """Offline default that returns a fixed conservative result or a test-supplied draft."""

    def __init__(self, draft: GenerationDraft | None = None) -> None:
        self._identity = GenerationProviderIdentity(
            provider="deterministic-fake",
            model="grounded-static-v1",
            revision=None,
        )
        self._draft = draft

    @property
    def identity(self) -> GenerationProviderIdentity:
        return self._identity

    def generate(self, request: GenerationRequest) -> GenerationDraft:
        if self._draft is not None:
            return GenerationDraft.model_validate(self._draft.model_dump(mode="json"))
        missing = tuple(
            sorted(
                {
                    field_path
                    for finding in request.rule_findings
                    if finding.status == "needs_information"
                    for field_path in finding.missing_fields
                }
            )
        )
        return GenerationDraft(
            answer="",
            missing_information=missing,
            limitations=(GenerationLimitation.PROVIDER_NOT_CALLED,),
            needs_review=True,
            refused=False,
        )


def _render_claim_text(
    claim: GeneratedClaim,
    *,
    evidence_by_id: dict[str, GenerationEvidence],
    findings_by_id: dict[str, GenerationRuleFinding],
    applicant_facts_by_path: dict[str, ApplicantFact],
) -> str:
    if claim.kind is ClaimKind.OFFICIAL_FACT:
        return "\n".join(
            f"Official evidence {evidence_id}: {evidence_by_id[evidence_id].text}"
            for evidence_id in claim.evidence_ids
        )
    if claim.kind is ClaimKind.REVIEWED_RULE:
        finding = findings_by_id[claim.finding_ids[0]]
        return f"Reviewed finding {finding.finding_id} [{finding.status}]: {finding.statement}"
    return "\n".join(
        f"Applicant-provided {field_path}: {applicant_facts_by_path[field_path].value}"
        for field_path in claim.applicant_fact_paths
    )
