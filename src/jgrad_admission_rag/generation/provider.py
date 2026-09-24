"""Provider boundary, deterministic fake, and fail-closed output checks."""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from .contracts import (
    GENERATION_SCHEMA_VERSION,
    ClaimKind,
    GenerationDraft,
    GenerationProviderIdentity,
    GenerationRequest,
    GenerationResult,
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
    for claim in output.claims:
        if claim.kind is not ClaimKind.REVIEWED_RULE:
            continue
        cited_findings = tuple(findings_by_id[item] for item in claim.finding_ids)
        supported_evidence = {
            evidence_id for finding in cited_findings for evidence_id in finding.evidence_ids
        }
        if not set(claim.evidence_ids) <= supported_evidence:
            raise GenerationError(GenerationErrorCode.UNSUPPORTED_CLAIM)
        pending = tuple(
            finding
            for finding in cited_findings
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

    return GenerationResult(
        schema_version=GENERATION_SCHEMA_VERSION,
        request_id=checked_request.request_id,
        provider=identity,
        output=output,
    )


class DeterministicFakeGenerationProvider:
    """Offline default that returns a fixed conservative result or a test-supplied draft."""

    def __init__(self, draft: GenerationDraft | None = None) -> None:
        self._identity = GenerationProviderIdentity(
            provider="deterministic-fake",
            model="grounded-static-v1",
            revision=None,
        )
        self._draft = draft or GenerationDraft(
            answer="",
            limitations=("deterministic-fake provider; no language model was called",),
            needs_review=True,
            refused=False,
        )

    @property
    def identity(self) -> GenerationProviderIdentity:
        return self._identity

    def generate(self, request: GenerationRequest) -> GenerationDraft:
        del request
        return GenerationDraft.model_validate(self._draft.model_dump(mode="json"))
