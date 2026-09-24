"""Narrow, pinned embedding choices supported by the formal local Demo."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .retrieval.embedding import (
    DeterministicFakeEmbeddingProvider,
    EmbeddingIdentity,
    EmbeddingProvider,
    EmbeddingProviderError,
)
from .retrieval.sentence_transformer import (
    SentenceTransformerConfig,
    SentenceTransformerEmbeddingProvider,
)

FAKE_DEMO_PROVIDER = "deterministic-fake"
BGE_M3_DEMO_PROVIDER = "bge-m3"
DEMO_PROVIDER_NAMES = (FAKE_DEMO_PROVIDER, BGE_M3_DEMO_PROVIDER)

BGE_M3_MODEL = "BAAI/bge-m3"
BGE_M3_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
BGE_M3_DIMENSION = 1024
_FAKE_DIMENSION = 8


class DemoEmbeddingConfigurationError(ValueError):
    """Raised when the formal Demo embedding selection is unsafe or unsupported."""


@dataclass(frozen=True, slots=True)
class DemoEmbeddingConfiguration:
    provider_name: str
    identity: EmbeddingIdentity
    cache_folder: Path | None = None

    @property
    def semantic(self) -> bool:
        return self.provider_name == BGE_M3_DEMO_PROVIDER


def resolve_demo_embedding_configuration(
    provider_name: str = FAKE_DEMO_PROVIDER,
    cache_folder: str | Path | None = None,
) -> DemoEmbeddingConfiguration:
    if provider_name not in DEMO_PROVIDER_NAMES:
        raise DemoEmbeddingConfigurationError(
            f"embedding provider must be one of: {', '.join(DEMO_PROVIDER_NAMES)}"
        )
    if provider_name == FAKE_DEMO_PROVIDER:
        if cache_folder is not None:
            raise DemoEmbeddingConfigurationError(
                "--embedding-cache is only valid with --embedding-provider bge-m3"
            )
        return DemoEmbeddingConfiguration(
            provider_name=provider_name,
            identity=EmbeddingIdentity(
                provider=FAKE_DEMO_PROVIDER,
                model="sha256-counter-v1",
                revision=None,
                dimension=_FAKE_DIMENSION,
            ),
        )

    resolved_cache = _resolve_cache_folder(cache_folder) if cache_folder is not None else None
    return DemoEmbeddingConfiguration(
        provider_name=provider_name,
        identity=EmbeddingIdentity(
            provider="sentence-transformers",
            model=BGE_M3_MODEL,
            revision=BGE_M3_REVISION,
            dimension=BGE_M3_DIMENSION,
        ),
        cache_folder=resolved_cache,
    )


def create_demo_embedding_provider(
    configuration: DemoEmbeddingConfiguration,
) -> EmbeddingProvider:
    if configuration.provider_name == FAKE_DEMO_PROVIDER:
        return DeterministicFakeEmbeddingProvider(configuration.identity.dimension)
    return SentenceTransformerEmbeddingProvider(
        SentenceTransformerConfig(
            model_name=BGE_M3_MODEL,
            revision=BGE_M3_REVISION,
            expected_dimension=BGE_M3_DIMENSION,
            batch_size=8,
            cache_folder=configuration.cache_folder,
            allow_download=False,
        )
    )


def demo_embedding_failure_message(
    configuration: DemoEmbeddingConfiguration,
    error: EmbeddingProviderError,
) -> str:
    if configuration.provider_name != BGE_M3_DEMO_PROVIDER:
        return "embedding provider is unavailable"
    if "not installed" in str(error):
        return (
            "BGE-M3 requires the embedding extra; run: python -m pip install -e "
            '".[service,embedding]"'
        )
    return (
        "fixed BGE-M3 cache is unavailable or incomplete; no download was attempted; "
        f"prepare {BGE_M3_MODEL} revision {BGE_M3_REVISION} in a reviewed cache and retry"
    )


def _resolve_cache_folder(value: str | Path) -> Path:
    try:
        requested = Path(value)
        if not requested.is_absolute() or requested.is_symlink() or not requested.is_dir():
            raise OSError
        resolved = requested.resolve(strict=True)
        if resolved != requested:
            raise OSError
        return resolved
    except (OSError, RuntimeError, TypeError, ValueError):
        raise DemoEmbeddingConfigurationError(
            "--embedding-cache must be a canonical absolute directory"
        ) from None


__all__ = [
    "BGE_M3_DEMO_PROVIDER",
    "BGE_M3_DIMENSION",
    "BGE_M3_MODEL",
    "BGE_M3_REVISION",
    "DEMO_PROVIDER_NAMES",
    "FAKE_DEMO_PROVIDER",
    "DemoEmbeddingConfiguration",
    "DemoEmbeddingConfigurationError",
    "create_demo_embedding_provider",
    "demo_embedding_failure_message",
    "resolve_demo_embedding_configuration",
]
