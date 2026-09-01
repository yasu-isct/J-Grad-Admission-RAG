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
from .embedding_text import EMBEDDING_TEXT_VERSION, build_embedding_text
from .sentence_transformer import (
    SentenceTransformerConfig,
    SentenceTransformerEmbeddingProvider,
)

__all__ = [
    "DeterministicFakeEmbeddingProvider",
    "EmbeddingError",
    "EmbeddingIdentity",
    "EmbeddingInputError",
    "EmbeddingOutputError",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "EMBEDDING_TEXT_VERSION",
    "SentenceTransformerConfig",
    "SentenceTransformerEmbeddingProvider",
    "build_embedding_text",
    "embed_documents_checked",
    "embed_query_checked",
    "validate_document_embeddings",
    "validate_query_embedding",
]
