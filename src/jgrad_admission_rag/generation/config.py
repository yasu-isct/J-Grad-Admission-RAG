"""Explicit generation-provider runtime configuration shared by service launchers."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from .openai_responses import OpenAIResponsesConfig, OpenAIResponsesGenerationProvider
from .provider import GenerationProvider, ReviewedStateGenerationProvider
from .question_analysis import (
    DeterministicQuestionUnderstandingProvider,
    OpenAIResponsesQuestionUnderstandingProvider,
    QuestionUnderstandingProvider,
)

GENERATION_PROVIDER_NAMES = ("reviewed-state-offline", "openai-responses")


@dataclass(frozen=True, slots=True)
class GenerationRuntimeConfiguration:
    provider: str = "reviewed-state-offline"
    model: str | None = None
    timeout_seconds: float = 30.0
    max_output_tokens: int = 2_000
    max_retries: int = 1

    def __post_init__(self) -> None:
        if self.provider not in GENERATION_PROVIDER_NAMES:
            raise ValueError("unsupported generation provider")
        if self.provider == "openai-responses" and (
            not isinstance(self.model, str) or not self.model or self.model != self.model.strip()
        ):
            raise ValueError("--generation-model is required for openai-responses")
        if self.provider == "reviewed-state-offline" and self.model is not None:
            raise ValueError("--generation-model is only valid for openai-responses")
        OpenAIResponsesConfig(
            model=self.model or "offline-validation-placeholder",
            timeout_seconds=self.timeout_seconds,
            max_output_tokens=self.max_output_tokens,
            max_retries=self.max_retries,
        )

    @property
    def is_online(self) -> bool:
        return self.provider == "openai-responses"


def add_generation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--generation-provider",
        choices=GENERATION_PROVIDER_NAMES,
        default="reviewed-state-offline",
        help="Natural-language generation mode (default: reviewed-state-offline).",
    )
    parser.add_argument(
        "--generation-model",
        help="OpenAI model name; required only with --generation-provider openai-responses.",
    )
    parser.add_argument("--generation-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--generation-max-output-tokens", type=int, default=2_000)
    parser.add_argument("--generation-max-retries", type=int, default=1)


def resolve_generation_configuration(args: Any) -> GenerationRuntimeConfiguration:
    return GenerationRuntimeConfiguration(
        provider=args.generation_provider,
        model=args.generation_model,
        timeout_seconds=args.generation_timeout_seconds,
        max_output_tokens=args.generation_max_output_tokens,
        max_retries=args.generation_max_retries,
    )


def create_generation_providers(
    configuration: GenerationRuntimeConfiguration,
) -> tuple[GenerationProvider, QuestionUnderstandingProvider]:
    if configuration.provider == "reviewed-state-offline":
        return ReviewedStateGenerationProvider(), DeterministicQuestionUnderstandingProvider()
    config = OpenAIResponsesConfig(
        model=configuration.model or "",
        timeout_seconds=configuration.timeout_seconds,
        max_output_tokens=configuration.max_output_tokens,
        max_retries=configuration.max_retries,
    )
    return (
        OpenAIResponsesGenerationProvider(config),
        OpenAIResponsesQuestionUnderstandingProvider(config),
    )


__all__ = [
    "GENERATION_PROVIDER_NAMES",
    "GenerationRuntimeConfiguration",
    "add_generation_arguments",
    "create_generation_providers",
    "resolve_generation_configuration",
]
