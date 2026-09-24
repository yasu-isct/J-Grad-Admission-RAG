"""Provider-neutral grounded-generation boundary."""

from .contracts import (
    GENERATION_PROMPT_VERSION,
    GENERATION_SCHEMA_VERSION,
    ApplicantFact,
    ClaimKind,
    EvidenceRole,
    GeneratedClaim,
    GenerationDraft,
    GenerationEvidence,
    GenerationEvidenceMaterial,
    GenerationProviderIdentity,
    GenerationRequest,
    GenerationResult,
    GenerationRuleFinding,
    GenerationTarget,
    assign_generation_evidence_ids,
    canonical_generation_result_bytes,
)
from .openai_responses import OpenAIResponsesConfig, OpenAIResponsesGenerationProvider
from .provider import (
    DeterministicFakeGenerationProvider,
    GenerationError,
    GenerationErrorCode,
    GenerationProvider,
    generate_checked,
)

__all__ = [
    "GENERATION_PROMPT_VERSION",
    "GENERATION_SCHEMA_VERSION",
    "ApplicantFact",
    "ClaimKind",
    "DeterministicFakeGenerationProvider",
    "EvidenceRole",
    "GeneratedClaim",
    "GenerationDraft",
    "GenerationError",
    "GenerationErrorCode",
    "GenerationEvidence",
    "GenerationEvidenceMaterial",
    "GenerationProvider",
    "GenerationProviderIdentity",
    "GenerationRequest",
    "GenerationResult",
    "GenerationRuleFinding",
    "GenerationTarget",
    "OpenAIResponsesConfig",
    "OpenAIResponsesGenerationProvider",
    "assign_generation_evidence_ids",
    "canonical_generation_result_bytes",
    "generate_checked",
]
