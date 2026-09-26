"""First-party DeepSeek Responses adapters with a fixed privacy boundary."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

from .contracts import (
    GENERATION_PROMPT_VERSION,
    GenerationDraft,
    GenerationProviderIdentity,
    GenerationRequest,
)
from .deepseek_schema import (
    DeepSeekSchemaProjection,
    build_deepseek_schema_projection,
)
from .provider import GenerationError, GenerationErrorCode
from .question_analysis import (
    ALLOWED_CANONICAL_TERMS,
    ANALYSIS_SYSTEM_PROMPT,
    DeterministicQuestionUnderstandingProvider,
    QuestionAnalysis,
    analysis_matches_server_constraints,
)
from .responses_common import GROUNDING_SYSTEM_PROMPT, contains_refusal
from .simple_qa import (
    SIMPLE_QA_SYSTEM_PROMPT,
    SimpleQaDraft,
    SimpleQaRequest,
)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL_NAMES = ("deepseek-flash", "deepseek-v4-pro")
DEEPSEEK_DEFAULT_TIMEOUT_SECONDS = 90.0
DEEPSEEK_DEFAULT_MAX_OUTPUT_TOKENS = 8_000
_DEEPSEEK_GROUNDING_SYSTEM_PROMPT = (
    GROUNDING_SYSTEM_PROMPT
    + """
For this DeepSeek wire schema, every array field must be a JSON array, never null; use an empty
array when that field does not apply. missing_information contains only sorted, unique, safe
identifier paths for genuinely absent inputs, never explanatory prose; otherwise return an empty
array. Number claim_id values contiguously as claim:0001, claim:0002, and so on. answer must be
exactly the claim text values joined in that same order with one newline and no added heading,
bullet, prefix, suffix, or explanation. For an ordinary non-refusal set refused=false and
refusal_reason=null. For a refusal return no claims and an empty answer with a non-empty
refusal_reason. If there are no claims for a non-refusal, set needs_review=true and return at least
one canonical missing_information value or limitation. Keep limitations sorted and unique."""
)

_SchemaModel = TypeVar("_SchemaModel", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class DeepSeekResponsesConfig:
    """Closed DeepSeek configuration; the endpoint and credential source are not configurable."""

    model: str
    timeout_seconds: float = DEEPSEEK_DEFAULT_TIMEOUT_SECONDS
    max_output_tokens: int = DEEPSEEK_DEFAULT_MAX_OUTPUT_TOKENS
    max_retries: int = 1

    def __post_init__(self) -> None:
        if self.model not in DEEPSEEK_MODEL_NAMES:
            raise ValueError("DeepSeek model must be one of: " + ", ".join(DEEPSEEK_MODEL_NAMES))
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not 0 < float(self.timeout_seconds) <= 120
        ):
            raise ValueError("timeout_seconds must be in (0, 120]")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or not 128 <= self.max_output_tokens <= 16_384
        ):
            raise ValueError("max_output_tokens must be in [128, 16384]")
        if (
            isinstance(self.max_retries, bool)
            or not isinstance(self.max_retries, int)
            or not 0 <= self.max_retries <= 2
        ):
            raise ValueError("max_retries must be in [0, 2]")


class DeepSeekResponsesGenerationProvider:
    """Non-streaming DeepSeek Responses adapter with server-validated citations."""

    def __init__(
        self,
        config: DeepSeekResponsesConfig,
        *,
        _client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._identity = GenerationProviderIdentity(
            provider="deepseek-responses",
            model=config.model,
            revision=None,
            prompt_version=GENERATION_PROMPT_VERSION,
        )
        self._schema_projection = _projection_for(GenerationDraft)
        self._simple_qa_projection = _projection_for(SimpleQaDraft)
        self._client = _create_client(config, _client_factory)

    @property
    def identity(self) -> GenerationProviderIdentity:
        return self._identity

    def generate(self, request: GenerationRequest) -> GenerationDraft:
        payload = json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return _request_structured_output(
            self._client,
            config=self._config,
            system_prompt=_DEEPSEEK_GROUNDING_SYSTEM_PROMPT,
            payload=payload,
            schema=GenerationDraft,
            schema_name="generation_draft",
            projection=self._schema_projection,
            reasoning_effort="none",
        )

    def answer_simple(self, request: SimpleQaRequest) -> SimpleQaDraft:
        payload = json.dumps(
            request.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return _request_structured_output(
            self._client,
            config=self._config,
            system_prompt=SIMPLE_QA_SYSTEM_PROMPT,
            payload=payload,
            schema=SimpleQaDraft,
            schema_name="simple_qa_answer",
            projection=self._simple_qa_projection,
            reasoning_effort="none",
        )


class DeepSeekResponsesQuestionUnderstandingProvider:
    """DeepSeek question analysis constrained by deterministic server semantics."""

    provider_name = "deepseek-responses"

    def __init__(
        self,
        config: DeepSeekResponsesConfig,
        *,
        _client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self.model_name = config.model
        self._schema_projection = _projection_for(QuestionAnalysis)
        self._client = _create_client(config, _client_factory)

    def analyze(self, question: str) -> QuestionAnalysis:
        anchor = DeterministicQuestionUnderstandingProvider().analyze(question)
        payload = json.dumps(
            {
                "question": question,
                "allowed_canonical_terms": ALLOWED_CANONICAL_TERMS,
                "server_constraints": anchor.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        analysis = _request_structured_output(
            self._client,
            config=self._config,
            system_prompt=ANALYSIS_SYSTEM_PROMPT,
            payload=payload,
            schema=QuestionAnalysis,
            schema_name="question_analysis",
            projection=self._schema_projection,
        )
        if not analysis_matches_server_constraints(question, analysis, anchor):
            raise GenerationError(GenerationErrorCode.MALFORMED_OUTPUT)
        return analysis


def _create_client(
    config: DeepSeekResponsesConfig,
    client_factory: Callable[..., Any] | None,
) -> Any:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise GenerationError(GenerationErrorCode.MISSING_API_KEY)
    if client_factory is None:
        imported_factory: Callable[..., Any] | None = None
        try:
            from openai import OpenAI
        except (ImportError, ModuleNotFoundError):
            pass
        else:
            imported_factory = OpenAI
        if imported_factory is None:
            raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE) from None
        client_factory = imported_factory
    client: Any | None = None
    try:
        client = client_factory(
            api_key=api_key,
            base_url=DEEPSEEK_BASE_URL,
            timeout=float(config.timeout_seconds),
            max_retries=config.max_retries,
        )
    except Exception:
        pass
    if client is None:
        raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE) from None
    return client


def _request_structured_output(
    client: Any,
    *,
    config: DeepSeekResponsesConfig,
    system_prompt: str,
    payload: str,
    schema: type[_SchemaModel],
    schema_name: str,
    projection: DeepSeekSchemaProjection,
    reasoning_effort: str | None = None,
) -> _SchemaModel:
    failure: GenerationErrorCode | None = None
    response: Any | None = None
    try:
        request_options: dict[str, object] = {
            "model": config.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": payload},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": projection.schema,
                }
            },
            "max_output_tokens": config.max_output_tokens,
            "store": False,
        }
        if reasoning_effort is not None:
            request_options["reasoning"] = {"effort": reasoning_effort}
        response = client.responses.create(
            **request_options,
        )
    except Exception as error:
        name = type(error).__name__
        if name in {"APITimeoutError", "TimeoutException", "ReadTimeout", "ConnectTimeout"}:
            failure = GenerationErrorCode.PROVIDER_TIMEOUT
        else:
            failure = GenerationErrorCode.PROVIDER_UNAVAILABLE
    if failure is not None:
        raise GenerationError(failure) from None
    if response is None:
        raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE)
    inspection_failed = False
    refused = False
    status: object | None = None
    raw_output: object | None = None
    try:
        refused = contains_refusal(response)
        status = getattr(response, "status", None)
        raw_output = getattr(response, "output_text", None)
    except Exception:
        inspection_failed = True
    if inspection_failed:
        raise GenerationError(GenerationErrorCode.MALFORMED_OUTPUT) from None
    if refused:
        raise GenerationError(GenerationErrorCode.PROVIDER_REFUSAL)
    if status != "completed":
        raise GenerationError(GenerationErrorCode.INCOMPLETE_RESPONSE)
    if not isinstance(raw_output, str) or not raw_output.strip():
        raise GenerationError(GenerationErrorCode.MALFORMED_OUTPUT)
    validated: _SchemaModel | None = None
    try:
        decoded = json.loads(raw_output)
        validated = schema.model_validate(decoded)
    except Exception:
        pass
    if validated is None:
        raise GenerationError(GenerationErrorCode.MALFORMED_OUTPUT) from None
    return validated


def _projection_for(schema: type[BaseModel]) -> DeepSeekSchemaProjection:
    projection: DeepSeekSchemaProjection | None = None
    try:
        projection = build_deepseek_schema_projection(schema.model_json_schema())
    except Exception:
        pass
    if projection is None:
        raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE) from None
    return projection


__all__ = [
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_DEFAULT_MAX_OUTPUT_TOKENS",
    "DEEPSEEK_DEFAULT_TIMEOUT_SECONDS",
    "DEEPSEEK_MODEL_NAMES",
    "DeepSeekResponsesConfig",
    "DeepSeekResponsesGenerationProvider",
    "DeepSeekResponsesQuestionUnderstandingProvider",
]
