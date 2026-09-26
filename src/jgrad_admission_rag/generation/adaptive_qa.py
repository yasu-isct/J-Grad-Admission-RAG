"""Adaptive planning and final-answer contracts for the reference-only QA layer."""

from __future__ import annotations

from typing import Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contracts import GenerationProviderIdentity
from .provider import GenerationError, GenerationErrorCode
from .simple_qa import (
    MAX_SIMPLE_QA_SOURCE_CHARACTERS,
    MAX_SIMPLE_QA_SOURCES,
    SimpleQaDraft,
    SimpleQaSource,
)

_Model = TypeVar("_Model", bound=BaseModel)

ADAPTIVE_QA_SCHEMA_VERSION = "1.0"
ADAPTIVE_QA_PLANNING_PROMPT_VERSION = "adaptive-qa-planning-v1"
ADAPTIVE_QA_FINAL_PROMPT_VERSION = "adaptive-qa-final-v1"
MAX_ADAPTIVE_SEARCH_QUERIES = 6
MAX_ADAPTIVE_SEARCH_QUERY_CHARACTERS = 500

ADAPTIVE_QA_PLANNING_SYSTEM_PROMPT = """Plan a reference-only answer to the user's question.
Return a concise user-readable preliminary answer in the user's language, never hidden reasoning.
Set needs_local_lookup=true whenever the question asks about the selected university, programme,
year, eligibility, deadlines, required materials, fees, score conversion, accepted tests, or any
other official admission-specific conclusion. In that case provide a small set of focused search
queries for the selected local admission document. General definitions and general comparisons may
use needs_local_lookup=false and an empty search_queries array. Do not claim that an institution
accepts, rejects, requires, waives, or guarantees anything without local confirmation. Do not
mention JSON, internal implementation, paths, IDs, hashes, pages, or hidden reasoning. Return only
the required schema."""

ADAPTIVE_QA_FINAL_SYSTEM_PROMPT = """Write one natural reference-only answer in the user's
language. Combine the preliminary general explanation with the bounded results from the selected
local admission document. Clearly distinguish general background from school-specific information
confirmed by the supplied records. If retrieval_status is no_hits, explicitly state that the
selected local admission material did not confirm the school-specific point and advise checking
the structured features, official source, or the institution. Never turn missing material into
acceptance, rejection, exemption, eligibility, or an admission guarantee. Do not mention internal
source IDs, paths, hashes, pages, JSON, implementation details, or hidden reasoning. Do not claim
to have searched the web. Return only the required schema."""


class AdaptiveQaModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AdaptiveQaPlanningRequest(AdaptiveQaModel):
    schema_version: str = ADAPTIVE_QA_SCHEMA_VERSION
    question: str = Field(min_length=1, max_length=4_000)
    target_label: str = Field(min_length=1, max_length=1_000)


class AdaptiveQaPlanDraft(AdaptiveQaModel):
    draft_answer: str = Field(min_length=1, max_length=25_000)
    needs_local_lookup: bool
    search_queries: tuple[str, ...] = Field(max_length=MAX_ADAPTIVE_SEARCH_QUERIES)

    @field_validator("search_queries")
    @classmethod
    def queries_must_be_bounded_text(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            not query
            or query != query.strip()
            or len(query) > MAX_ADAPTIVE_SEARCH_QUERY_CHARACTERS
            or any(ord(character) < 32 for character in query)
            for query in value
        ):
            raise ValueError("search queries must be bounded printable text")
        if len(set(value)) != len(value):
            raise ValueError("search queries must be unique")
        return value

    @model_validator(mode="after")
    def lookup_flag_must_match_queries(self) -> AdaptiveQaPlanDraft:
        if self.needs_local_lookup != bool(self.search_queries):
            raise ValueError("lookup flag must match search queries")
        return self


class AdaptiveQaFinalRequest(AdaptiveQaModel):
    schema_version: str = ADAPTIVE_QA_SCHEMA_VERSION
    question: str = Field(min_length=1, max_length=4_000)
    target_label: str = Field(min_length=1, max_length=1_000)
    draft_answer: str = Field(min_length=1, max_length=25_000)
    retrieval_status: Literal["hits", "no_hits"]
    sources: tuple[SimpleQaSource, ...] = Field(max_length=MAX_SIMPLE_QA_SOURCES)

    @model_validator(mode="after")
    def retrieval_status_must_match_sources(self) -> AdaptiveQaFinalRequest:
        if (self.retrieval_status == "hits") != bool(self.sources):
            raise ValueError("retrieval status must match sources")
        if sum(len(item.text) for item in self.sources) > MAX_SIMPLE_QA_SOURCE_CHARACTERS:
            raise ValueError("source text exceeds the bounded request limit")
        return self


class AdaptiveQaPlanResult(AdaptiveQaModel):
    draft_answer: str
    needs_local_lookup: bool
    search_queries: tuple[str, ...]
    provider: GenerationProviderIdentity


class AdaptiveQaAnswerResult(AdaptiveQaModel):
    answer: str
    provider: GenerationProviderIdentity


@runtime_checkable
class AdaptiveQaProvider(Protocol):
    @property
    def identity(self) -> GenerationProviderIdentity: ...

    def plan_adaptive(self, request: AdaptiveQaPlanningRequest) -> AdaptiveQaPlanDraft: ...

    def answer_adaptive(self, request: AdaptiveQaFinalRequest) -> SimpleQaDraft: ...


def plan_adaptive_checked(
    provider: AdaptiveQaProvider, request: AdaptiveQaPlanningRequest
) -> AdaptiveQaPlanResult:
    checked_request = _checked_model(AdaptiveQaPlanningRequest, request)
    identity = _checked_identity(provider)
    try:
        raw = provider.plan_adaptive(checked_request)
    except GenerationError as error:
        raise GenerationError(error.code) from None
    except Exception:
        raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE) from None
    draft = _checked_model(AdaptiveQaPlanDraft, raw, output=True)
    return AdaptiveQaPlanResult(
        draft_answer=draft.draft_answer,
        needs_local_lookup=draft.needs_local_lookup,
        search_queries=draft.search_queries,
        provider=identity,
    )


def answer_adaptive_checked(
    provider: AdaptiveQaProvider, request: AdaptiveQaFinalRequest
) -> AdaptiveQaAnswerResult:
    checked_request = _checked_model(AdaptiveQaFinalRequest, request)
    identity = _checked_identity(provider)
    try:
        raw = provider.answer_adaptive(checked_request)
    except GenerationError as error:
        raise GenerationError(error.code) from None
    except Exception:
        raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE) from None
    draft = _checked_model(SimpleQaDraft, raw, output=True)
    return AdaptiveQaAnswerResult(answer=draft.answer, provider=identity)


def _checked_identity(provider: AdaptiveQaProvider) -> GenerationProviderIdentity:
    try:
        return GenerationProviderIdentity.model_validate(provider.identity.model_dump(mode="json"))
    except Exception:
        raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE) from None


def _checked_model(model: type[_Model], value: object, *, output: bool = False) -> _Model:
    checked = None
    try:
        payload = value.model_dump(mode="json")  # type: ignore[attr-defined]
        checked = model.model_validate(payload)
    except Exception:
        pass
    if checked is None:
        code = GenerationErrorCode.MALFORMED_OUTPUT if output else GenerationErrorCode.INVALID_INPUT
        raise GenerationError(code) from None
    return checked


__all__ = [
    "ADAPTIVE_QA_FINAL_PROMPT_VERSION",
    "ADAPTIVE_QA_FINAL_SYSTEM_PROMPT",
    "ADAPTIVE_QA_PLANNING_PROMPT_VERSION",
    "ADAPTIVE_QA_PLANNING_SYSTEM_PROMPT",
    "ADAPTIVE_QA_SCHEMA_VERSION",
    "MAX_ADAPTIVE_SEARCH_QUERIES",
    "MAX_ADAPTIVE_SEARCH_QUERY_CHARACTERS",
    "AdaptiveQaAnswerResult",
    "AdaptiveQaFinalRequest",
    "AdaptiveQaPlanDraft",
    "AdaptiveQaPlanResult",
    "AdaptiveQaPlanningRequest",
    "AdaptiveQaProvider",
    "answer_adaptive_checked",
    "plan_adaptive_checked",
]
