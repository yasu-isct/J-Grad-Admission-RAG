from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .embedding import (
    EmbeddingIdentity,
    EmbeddingInputError,
    EmbeddingProviderError,
    validate_document_embeddings,
)

_COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True, slots=True)
class SentenceTransformerConfig:
    """Reproducible, CPU-only Sentence Transformers adapter configuration."""

    model_name: str
    revision: str
    expected_dimension: int
    device: Literal["cpu"] = "cpu"
    batch_size: int = 8
    allow_download: bool = False
    cache_folder: str | Path | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.model_name, str)
            or not self.model_name
            or self.model_name != self.model_name.strip()
        ):
            raise ValueError("model_name must be a non-empty trimmed string")
        if (
            not isinstance(self.revision, str)
            or _COMMIT_SHA_PATTERN.fullmatch(self.revision) is None
        ):
            raise ValueError("revision must be a full lowercase 40-character commit SHA")
        if (
            isinstance(self.expected_dimension, bool)
            or not isinstance(self.expected_dimension, int)
            or self.expected_dimension <= 0
        ):
            raise ValueError("expected_dimension must be a positive integer")
        if self.device != "cpu":
            raise ValueError("device must be 'cpu'")
        if (
            isinstance(self.batch_size, bool)
            or not isinstance(self.batch_size, int)
            or self.batch_size <= 0
        ):
            raise ValueError("batch_size must be a positive integer")
        if not isinstance(self.allow_download, bool):
            raise ValueError("allow_download must be a boolean")
        if self.cache_folder is not None and not isinstance(self.cache_folder, (str, Path)):
            raise ValueError("cache_folder must be a string, Path, or None")


class SentenceTransformerEmbeddingProvider:
    """Pinned, offline-first Sentence Transformers implementation of the embedding boundary."""

    def __init__(
        self,
        config: SentenceTransformerConfig,
        *,
        _backend_factory: Callable[[SentenceTransformerConfig], Any] | None = None,
    ) -> None:
        self.config = config
        self._backend_factory = _backend_factory or _load_sentence_transformer
        self._backend: Any | None = None
        self._identity: EmbeddingIdentity | None = None
        self._max_seq_length: int | None = None

    @property
    def identity(self) -> EmbeddingIdentity:
        self._ensure_loaded()
        assert self._identity is not None
        return self._identity

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        copied_texts = list(texts)
        return self._encode(copied_texts, operation="documents")

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text], operation="query")[0]

    def _ensure_loaded(self) -> None:
        if self._backend is not None:
            return
        try:
            backend = self._backend_factory(self.config)
        except EmbeddingProviderError:
            raise
        except Exception as error:
            raise EmbeddingProviderError("sentence-transformers model loading failed") from error

        try:
            dimension = backend.get_sentence_embedding_dimension()
            max_seq_length = backend.max_seq_length
            tokenizer = backend.tokenizer
        except Exception as error:
            raise EmbeddingProviderError(
                "sentence-transformers model metadata is unavailable"
            ) from error
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
            raise EmbeddingProviderError("loaded model reported an invalid embedding dimension")
        if dimension != self.config.expected_dimension:
            raise EmbeddingProviderError(
                "loaded model embedding dimension mismatch: "
                f"expected {self.config.expected_dimension}, observed {dimension}"
            )
        if (
            isinstance(max_seq_length, bool)
            or not isinstance(max_seq_length, int)
            or max_seq_length <= 0
        ):
            raise EmbeddingProviderError("loaded model reported an invalid maximum sequence length")
        if not callable(tokenizer):
            raise EmbeddingProviderError("loaded model tokenizer is unavailable")

        self._backend = backend
        self._max_seq_length = max_seq_length
        self._identity = EmbeddingIdentity(
            provider="sentence-transformers",
            model=self.config.model_name,
            revision=self.config.revision,
            dimension=dimension,
        )

    def _encode(self, texts: list[str], *, operation: str) -> list[list[float]]:
        self._ensure_loaded()
        self._preflight(texts, operation=operation)
        assert self._backend is not None
        try:
            output = self._backend.encode(
                texts,
                batch_size=self.config.batch_size,
                show_progress_bar=False,
                output_value="sentence_embedding",
                precision="float32",
                convert_to_numpy=True,
                convert_to_tensor=False,
                device="cpu",
                normalize_embeddings=False,
            )
        except EmbeddingProviderError:
            raise
        except Exception as error:
            raise EmbeddingProviderError(f"{operation} embedding encode failed") from error

        try:
            plain_output = output.tolist() if hasattr(output, "tolist") else output
        except Exception as error:
            raise EmbeddingProviderError(
                f"{operation} embedding output conversion failed"
            ) from error
        return validate_document_embeddings(plain_output, len(texts), self.identity.dimension)

    def _preflight(self, texts: list[str], *, operation: str) -> None:
        counts = self._token_counts(texts, operation=operation)
        assert self._max_seq_length is not None
        for row, count in enumerate(counts):
            if count > self._max_seq_length:
                location = f" row {row}" if operation == "documents" else ""
                raise EmbeddingInputError(
                    f"{operation}{location} token count {count} exceeds model limit "
                    f"{self._max_seq_length}"
                )

    def _token_counts(self, texts: list[str], *, operation: str) -> list[int]:
        self._ensure_loaded()
        assert self._backend is not None
        try:
            tokenized = self._backend.tokenizer(
                texts,
                add_special_tokens=True,
                truncation=False,
                padding=False,
                return_attention_mask=False,
                return_token_type_ids=False,
            )
            input_ids = tokenized["input_ids"]
            if hasattr(input_ids, "tolist"):
                input_ids = input_ids.tolist()
            counts = [len(row) for row in input_ids]
        except Exception as error:
            raise EmbeddingProviderError(f"{operation} tokenization failed") from error
        if len(counts) != len(texts):
            raise EmbeddingProviderError(f"{operation} tokenization row count mismatch")
        return counts


def _load_sentence_transformer(config: SentenceTransformerConfig) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise EmbeddingProviderError(
            "sentence-transformers is not installed; run: pip install -e .[embedding]"
        ) from error

    try:
        return SentenceTransformer(
            config.model_name,
            revision=config.revision,
            device="cpu",
            cache_folder=str(config.cache_folder) if config.cache_folder is not None else None,
            local_files_only=not config.allow_download,
            trust_remote_code=False,
        )
    except Exception as error:
        raise EmbeddingProviderError("sentence-transformers model loading failed") from error
