from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Sequence

from ..retrieval.embedding import (
    DeterministicFakeEmbeddingProvider,
    EmbeddingIdentity,
    EmbeddingProvider,
)
from ..retrieval.sentence_transformer import (
    SentenceTransformerConfig,
    SentenceTransformerEmbeddingProvider,
)

FAKE_PROVIDER_NAME = "deterministic-fake"
SENTENCE_TRANSFORMERS_PROVIDER_NAME = "sentence-transformers"
PROVIDER_NAMES = (FAKE_PROVIDER_NAME, SENTENCE_TRANSFORMERS_PROVIDER_NAME)


class CliConfigurationError(ValueError):
    """Raised when provider-specific CLI arguments are incomplete or incompatible."""


@dataclass(frozen=True, slots=True)
class DeclaredProviderConfiguration:
    identity: EmbeddingIdentity
    sentence_transformer_config: SentenceTransformerConfig | None = None


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def add_provider_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", required=True, choices=PROVIDER_NAMES)
    parser.add_argument("--dimension", type=positive_int)
    parser.add_argument("--model")
    parser.add_argument("--revision")
    parser.add_argument("--batch-size", type=positive_int)
    parser.add_argument("--cache-folder")
    parser.add_argument("--allow-model-download", action="store_true")


def resolve_provider_configuration(args: argparse.Namespace) -> DeclaredProviderConfiguration:
    try:
        if args.provider == FAKE_PROVIDER_NAME:
            _require(args, ("dimension",))
            _reject(
                args,
                ("model", "revision", "batch_size", "cache_folder", "allow_model_download"),
            )
            return DeclaredProviderConfiguration(
                identity=EmbeddingIdentity(
                    provider=FAKE_PROVIDER_NAME,
                    model="sha256-counter-v1",
                    revision=None,
                    dimension=args.dimension,
                )
            )

        _require(args, ("model", "revision", "dimension"))
        config = SentenceTransformerConfig(
            model_name=args.model,
            revision=args.revision,
            expected_dimension=args.dimension,
            batch_size=args.batch_size if args.batch_size is not None else 8,
            cache_folder=args.cache_folder,
            allow_download=args.allow_model_download,
        )
        return DeclaredProviderConfiguration(
            identity=EmbeddingIdentity(
                provider=SENTENCE_TRANSFORMERS_PROVIDER_NAME,
                model=config.model_name,
                revision=config.revision,
                dimension=config.expected_dimension,
            ),
            sentence_transformer_config=config,
        )
    except CliConfigurationError:
        raise
    except ValueError as error:
        raise CliConfigurationError(str(error)) from error


def create_provider(configuration: DeclaredProviderConfiguration) -> EmbeddingProvider:
    if configuration.identity.provider == FAKE_PROVIDER_NAME:
        return DeterministicFakeEmbeddingProvider(dimension=configuration.identity.dimension)
    assert configuration.sentence_transformer_config is not None
    return SentenceTransformerEmbeddingProvider(configuration.sentence_transformer_config)


def build_provider(args: argparse.Namespace) -> EmbeddingProvider:
    """Preserve the IDX-06 convenience API for immediate provider construction."""

    return create_provider(resolve_provider_configuration(args))


def _require(args: argparse.Namespace, names: Sequence[str]) -> None:
    missing = [f"--{name.replace('_', '-')}" for name in names if getattr(args, name) is None]
    if missing:
        raise CliConfigurationError(f"missing required option(s): {', '.join(missing)}")


def _reject(args: argparse.Namespace, names: Sequence[str]) -> None:
    incompatible = []
    for name in names:
        value = getattr(args, name)
        if value is not None and value is not False:
            incompatible.append(f"--{name.replace('_', '-')}")
    if incompatible:
        raise CliConfigurationError(
            f"option(s) incompatible with provider {args.provider!r}: {', '.join(incompatible)}"
        )
