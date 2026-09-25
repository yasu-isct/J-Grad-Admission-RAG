"""Optional OpenAI Responses adapter. Importing this module performs no network work."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable

from .contracts import (
    GENERATION_PROMPT_VERSION,
    GenerationDraft,
    GenerationProviderIdentity,
    GenerationRequest,
)
from .provider import GenerationError, GenerationErrorCode
from .responses_common import GROUNDING_SYSTEM_PROMPT, contains_refusal


@dataclass(frozen=True, slots=True)
class OpenAIResponsesConfig:
    model: str
    timeout_seconds: float = 30.0
    max_output_tokens: int = 2_000
    max_retries: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model or self.model != self.model.strip():
            raise ValueError("model must be a non-empty trimmed string")
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


class OpenAIResponsesGenerationProvider:
    """OpenAI Structured Outputs adapter with bounded SDK retries and privacy-safe failures."""

    def __init__(
        self,
        config: OpenAIResponsesConfig,
        *,
        _client_factory: Callable[..., Any] | None = None,
    ) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise GenerationError(GenerationErrorCode.MISSING_API_KEY)
        self._config = config
        self._identity = GenerationProviderIdentity(
            provider="openai-responses",
            model=config.model,
            revision=None,
            prompt_version=GENERATION_PROMPT_VERSION,
        )
        if _client_factory is None:
            imported_factory: Callable[..., Any] | None = None
            try:
                from openai import OpenAI
            except (ImportError, ModuleNotFoundError):
                pass
            else:
                imported_factory = OpenAI
            if imported_factory is None:
                raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE) from None
            _client_factory = imported_factory
        client: Any | None = None
        try:
            client = _client_factory(
                api_key=api_key,
                timeout=float(config.timeout_seconds),
                max_retries=config.max_retries,
            )
        except Exception:
            pass
        if client is None:
            raise GenerationError(GenerationErrorCode.PROVIDER_UNAVAILABLE) from None
        self._client = client

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
        provider_error: GenerationErrorCode | None = None
        response: Any | None = None
        try:
            response = self._client.responses.parse(
                model=self._config.model,
                input=[
                    {"role": "system", "content": GROUNDING_SYSTEM_PROMPT},
                    {"role": "user", "content": payload},
                ],
                text_format=GenerationDraft,
                max_output_tokens=self._config.max_output_tokens,
                store=False,
            )
        except Exception as error:
            name = type(error).__name__
            if name in {"APITimeoutError", "TimeoutException", "ReadTimeout", "ConnectTimeout"}:
                provider_error = GenerationErrorCode.PROVIDER_TIMEOUT
            elif name in {"LengthFinishReasonError"}:
                provider_error = GenerationErrorCode.INCOMPLETE_RESPONSE
            elif name in {"ContentFilterFinishReasonError"}:
                provider_error = GenerationErrorCode.PROVIDER_REFUSAL
            elif name in {"ValidationError", "JSONDecodeError"}:
                provider_error = GenerationErrorCode.MALFORMED_OUTPUT
            else:
                provider_error = GenerationErrorCode.PROVIDER_UNAVAILABLE
        if provider_error is not None:
            raise GenerationError(provider_error) from None

        if contains_refusal(response):
            raise GenerationError(GenerationErrorCode.PROVIDER_REFUSAL)
        if getattr(response, "status", None) != "completed":
            raise GenerationError(GenerationErrorCode.INCOMPLETE_RESPONSE)
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise GenerationError(GenerationErrorCode.MALFORMED_OUTPUT)
        draft: GenerationDraft | None = None
        try:
            draft = GenerationDraft.model_validate(
                parsed.model_dump(mode="json") if hasattr(parsed, "model_dump") else parsed
            )
        except Exception:
            pass
        if draft is None:
            raise GenerationError(GenerationErrorCode.MALFORMED_OUTPUT) from None
        return draft
