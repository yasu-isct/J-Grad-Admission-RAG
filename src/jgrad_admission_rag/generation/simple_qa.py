"""One-call presentation layer over bounded local admission records."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from .contracts import GenerationProviderIdentity
from .provider import GenerationError, GenerationErrorCode

SIMPLE_QA_SCHEMA_VERSION = "1.0"
SIMPLE_QA_PROMPT_VERSION = "simple-local-qa-v1"
MAX_SIMPLE_QA_SOURCES = 16
MAX_SIMPLE_QA_SOURCE_CHARACTERS = 60_000

SIMPLE_QA_SYSTEM_PROMPT = """Answer the user's graduate-admission question using only the
bounded local records supplied by the server. The records were extracted locally from the selected
admission document. Write one concise, directly readable answer in the user's language. If the
records do not establish part of the answer, say that it was not found in the supplied local
records; do not turn absence into rejection, exemption, or an admission guarantee. Do not mention
internal source IDs, implementation details, hidden reasoning, local paths, hashes, or JSON. Do not
claim to have searched the web. Return only the required schema."""


class SimpleQaModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SimpleQaSource(SimpleQaModel):
    source_id: str = Field(pattern=r"^source:[0-9]{4}$")
    text: str = Field(min_length=1, max_length=20_000)
    scope_label: str | None = Field(default=None, max_length=1_000)


class SimpleQaRequest(SimpleQaModel):
    schema_version: str = SIMPLE_QA_SCHEMA_VERSION
    question: str = Field(min_length=1, max_length=4_000)
    target_label: str = Field(min_length=1, max_length=1_000)
    sources: tuple[SimpleQaSource, ...] = Field(min_length=1, max_length=MAX_SIMPLE_QA_SOURCES)


class SimpleQaDraft(SimpleQaModel):
    answer: str = Field(min_length=1, max_length=25_000)


class SimpleQaResult(SimpleQaModel):
    answer: str
    provider: GenerationProviderIdentity


@runtime_checkable
class SimpleQaProvider(Protocol):
    @property
    def identity(self) -> GenerationProviderIdentity: ...

    def answer_simple(self, request: SimpleQaRequest) -> SimpleQaDraft: ...


def answer_simple_checked(provider: SimpleQaProvider, request: SimpleQaRequest) -> SimpleQaResult:
    """Validate a minimal answer without asking the model to reproduce provenance metadata."""

    try:
        checked_request = SimpleQaRequest.model_validate(request.model_dump(mode="json"))
    except Exception:
        raise GenerationError(GenerationErrorCode.INVALID_INPUT) from None
    if sum(len(item.text) for item in checked_request.sources) > MAX_SIMPLE_QA_SOURCE_CHARACTERS:
        raise GenerationError(GenerationErrorCode.INVALID_INPUT)
    try:
        identity = GenerationProviderIdentity.model_validate(
            provider.identity.model_dump(mode="json")
        )
    except Exception:
        raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE) from None
    try:
        raw = provider.answer_simple(checked_request)
    except GenerationError as error:
        raise GenerationError(error.code) from None
    except Exception:
        raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE) from None
    draft: SimpleQaDraft | None = None
    try:
        draft = SimpleQaDraft.model_validate(raw.model_dump(mode="json"))
    except Exception:
        pass
    if draft is None:
        raise GenerationError(GenerationErrorCode.MALFORMED_OUTPUT) from None
    return SimpleQaResult(answer=draft.answer, provider=identity)


__all__ = [
    "MAX_SIMPLE_QA_SOURCE_CHARACTERS",
    "MAX_SIMPLE_QA_SOURCES",
    "SIMPLE_QA_PROMPT_VERSION",
    "SIMPLE_QA_SCHEMA_VERSION",
    "SIMPLE_QA_SYSTEM_PROMPT",
    "SimpleQaDraft",
    "SimpleQaProvider",
    "SimpleQaRequest",
    "SimpleQaResult",
    "SimpleQaSource",
    "answer_simple_checked",
]
