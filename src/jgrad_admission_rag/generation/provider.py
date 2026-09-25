"""Provider boundary, deterministic fake, and fail-closed output checks."""

from __future__ import annotations

from enum import Enum
from collections.abc import Callable
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


ClaimTextValidator = Callable[[GeneratedClaim, GenerationRequest], bool]


def generate_checked(
    provider: GenerationProvider,
    request: GenerationRequest,
    *,
    claim_text_validator: ClaimTextValidator | None = None,
) -> GenerationResult:
    """Validate both sides of a provider call and reject all unbound references."""

    hydrated_output: GenerationDraft | None
    checked_request: GenerationRequest | None
    try:
        checked_request = GenerationRequest.model_validate(request.model_dump(mode="json"))
    except Exception:
        checked_request = None
    if checked_request is None:
        raise GenerationError(GenerationErrorCode.INVALID_INPUT) from None

    identity: GenerationProviderIdentity | None
    try:
        identity = GenerationProviderIdentity.model_validate(
            provider.identity.model_dump(mode="json")
        )
    except Exception:
        identity = None
    if identity is None:
        raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE) from None

    provider_error: GenerationErrorCode | None = None
    try:
        raw_output = provider.generate(checked_request)
    except GenerationError as error:
        provider_error = error.code
    except Exception:
        provider_error = GenerationErrorCode.PROVIDER_UNAVAILABLE
    if provider_error is not None:
        raise GenerationError(provider_error) from None

    output: GenerationDraft | None
    try:
        output = GenerationDraft.model_validate(raw_output.model_dump(mode="json"))
    except Exception:
        output = None
    if output is None:
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

    try:
        if claim_text_validator is not None:
            if any(not claim_text_validator(claim, checked_request) for claim in output.claims):
                raise ValueError
            hydrated_output = output
        else:
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
    except Exception:
        # Trusted evidence, applicant values, and validator internals stay behind the safe error.
        hydrated_output = None

    # Raise after leaving the handler so the sensitive validation exception is not retained in
    # either __context__ or __cause__ on the public error object.
    if hydrated_output is None:
        code = (
            GenerationErrorCode.UNSUPPORTED_CLAIM
            if claim_text_validator is not None
            else GenerationErrorCode.MALFORMED_OUTPUT
        )
        raise GenerationError(code) from None

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


class ReviewedStateGenerationProvider:
    """Offline demo provider that selects every reviewed finding without inventing prose."""

    def __init__(self) -> None:
        self._identity = GenerationProviderIdentity(
            provider="reviewed-state-offline",
            model="grounded-reviewed-v1",
            revision="1",
        )

    @property
    def identity(self) -> GenerationProviderIdentity:
        return self._identity

    def generate(self, request: GenerationRequest) -> GenerationDraft:
        claims = tuple(
            GeneratedClaim(
                claim_id=f"claim:{index:04d}",
                kind=ClaimKind.REVIEWED_RULE,
                text="reviewed finding",
                evidence_ids=finding.evidence_ids,
                finding_ids=(finding.finding_id,),
            )
            for index, finding in enumerate(request.rule_findings, start=1)
        )
        missing = tuple(
            sorted(
                {
                    path
                    for finding in request.rule_findings
                    if finding.status == "needs_information"
                    for path in finding.missing_fields
                }
            )
        )
        pending = any(
            finding.status in {"needs_information", "needs_review", "not_covered"}
            for finding in request.rule_findings
        )
        needs_review = pending or not claims
        limitations = (
            (GenerationLimitation.NEEDS_REVIEW,)
            if pending
            else ((GenerationLimitation.INSUFFICIENT_EVIDENCE,) if not claims else ())
        )
        return GenerationDraft(
            answer=assemble_generation_answer(claims),
            claims=claims,
            missing_information=missing,
            limitations=limitations,
            needs_review=needs_review,
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
