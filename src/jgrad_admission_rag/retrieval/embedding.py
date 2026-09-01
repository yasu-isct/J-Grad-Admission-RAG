from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from numbers import Real
from typing import Protocol, Sequence, runtime_checkable


class EmbeddingError(Exception):
    """Base class for errors at the embedding provider boundary."""


class EmbeddingInputError(EmbeddingError):
    """Raised when caller-supplied text violates the embedding contract."""


class EmbeddingProviderError(EmbeddingError):
    """Raised when an embedding implementation or backend fails."""


class EmbeddingOutputError(EmbeddingError):
    """Raised when an embedding implementation returns malformed output."""


@dataclass(frozen=True, slots=True)
class EmbeddingIdentity:
    """Stable provider identity recorded by the derived index manifest."""

    provider: str
    model: str
    revision: str | None
    dimension: int

    def __post_init__(self) -> None:
        for field_name in ("provider", "model"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{field_name} must be a non-empty trimmed string")
        if self.revision is not None and (
            not isinstance(self.revision, str)
            or not self.revision
            or self.revision != self.revision.strip()
        ):
            raise ValueError("revision must be None or a non-empty trimmed string")
        if (
            isinstance(self.dimension, bool)
            or not isinstance(self.dimension, int)
            or self.dimension <= 0
        ):
            raise ValueError("dimension must be a positive integer")


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Synchronous structural boundary implemented by embedding adapters."""

    @property
    def identity(self) -> EmbeddingIdentity: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def embed_documents_checked(
    provider: EmbeddingProvider,
    texts: Sequence[str],
) -> list[list[float]]:
    """Validate a document batch, call the provider, and validate/copy its vectors."""

    if isinstance(texts, (str, bytes)) or not isinstance(texts, Sequence):
        raise EmbeddingInputError("embed_documents input must be a sequence of strings")
    for row, text in enumerate(texts):
        _validate_text(text, operation="embed_documents", row=row)
    if not texts:
        return []

    provider_input = tuple(texts)
    try:
        vectors = provider.embed_documents(provider_input)
    except EmbeddingError:
        raise
    except Exception as error:
        raise EmbeddingProviderError("embed_documents provider call failed") from error
    return validate_document_embeddings(vectors, len(texts), provider.identity.dimension)


def embed_query_checked(provider: EmbeddingProvider, text: str) -> list[float]:
    """Validate one query, call the provider, and validate/copy its vector."""

    _validate_text(text, operation="embed_query")
    try:
        vector = provider.embed_query(text)
    except EmbeddingError:
        raise
    except Exception as error:
        raise EmbeddingProviderError("embed_query provider call failed") from error
    return validate_query_embedding(vector, provider.identity.dimension)


def validate_document_embeddings(
    vectors: object,
    expected_count: int,
    dimension: int,
) -> list[list[float]]:
    """Validate and detach document vectors returned by an adapter."""

    if not _is_sequence(vectors):
        raise EmbeddingOutputError("embed_documents output must be a sequence of vectors")
    if len(vectors) != expected_count:
        raise EmbeddingOutputError(
            "embed_documents output row count mismatch: "
            f"expected {expected_count}, observed {len(vectors)}"
        )
    return [
        _validate_vector(vector, dimension, operation="embed_documents", row=row)
        for row, vector in enumerate(vectors)
    ]


def validate_query_embedding(vector: object, dimension: int) -> list[float]:
    """Validate and detach one query vector returned by an adapter."""

    return _validate_vector(vector, dimension, operation="embed_query")


class DeterministicFakeEmbeddingProvider:
    """Offline contract-test provider; it does not model semantic similarity.

    Each SHA-256 block hashes a fixed domain, a four-byte big-endian counter, and the exact UTF-8
    text. Consecutive eight-byte words map to ``[-1, 1)`` before L2 normalization. Counter expansion
    freezes behavior for dimensions larger than the four coordinates in one digest.
    """

    def __init__(self, dimension: int = 8) -> None:
        self._identity = EmbeddingIdentity(
            provider="deterministic-fake",
            model="sha256-counter-v1",
            revision=None,
            dimension=dimension,
        )

    @property
    def identity(self) -> EmbeddingIdentity:
        return self._identity

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        coordinates: list[float] = []
        text_bytes = text.encode("utf-8")
        counter = 0
        while len(coordinates) < self.identity.dimension:
            digest = hashlib.sha256(
                b"jgrad-deterministic-fake-v1\x00"
                + counter.to_bytes(4, byteorder="big")
                + text_bytes
            ).digest()
            for offset in range(0, len(digest), 8):
                word = int.from_bytes(digest[offset : offset + 8], byteorder="big")
                coordinates.append((word / (1 << 63)) - 1.0)
                if len(coordinates) == self.identity.dimension:
                    break
            counter += 1

        norm = math.sqrt(sum(coordinate * coordinate for coordinate in coordinates))
        if norm == 0.0:
            coordinates[0] = 1.0
            norm = 1.0
        return [coordinate / norm for coordinate in coordinates]


def _validate_text(text: object, *, operation: str, row: int | None = None) -> None:
    if isinstance(text, str) and text.strip():
        return
    location = f" row {row}" if row is not None else ""
    raise EmbeddingInputError(f"{operation}{location} must be a non-blank Python string")


def _validate_vector(
    vector: object,
    dimension: int,
    *,
    operation: str,
    row: int | None = None,
) -> list[float]:
    location = f" row {row}" if row is not None else ""
    if not _is_sequence(vector):
        raise EmbeddingOutputError(f"{operation}{location} vector must be a sequence")
    if len(vector) != dimension:
        raise EmbeddingOutputError(
            f"{operation}{location} dimension mismatch: expected {dimension}, observed {len(vector)}"
        )

    copied: list[float] = []
    for coordinate, value in enumerate(vector):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise EmbeddingOutputError(
                f"{operation}{location} coordinate {coordinate} must be a real non-bool number"
            )
        float_value = float(value)
        if not math.isfinite(float_value):
            raise EmbeddingOutputError(
                f"{operation}{location} coordinate {coordinate} must be finite"
            )
        copied.append(float_value)
    return copied


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
