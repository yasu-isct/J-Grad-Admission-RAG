"""Retrieval utilities for admission RAG knowledge bases."""

from .embedding import (
    DeterministicFakeEmbeddingProvider,
    EmbeddingError,
    EmbeddingIdentity,
    EmbeddingInputError,
    EmbeddingOutputError,
    EmbeddingProvider,
    EmbeddingProviderError,
    embed_documents_checked,
    embed_query_checked,
    validate_document_embeddings,
    validate_query_embedding,
)

__all__ = [
    "DeterministicFakeEmbeddingProvider",
    "EmbeddingError",
    "EmbeddingIdentity",
    "EmbeddingInputError",
    "EmbeddingOutputError",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "embed_documents_checked",
    "embed_query_checked",
    "validate_document_embeddings",
    "validate_query_embedding",
]
