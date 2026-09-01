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
from .local_index import (
    INDEX_BUILDER_VERSION,
    IndexArtifactError,
    IndexBuildError,
    IndexLoadError,
    LocalVectorIndex,
    build_local_index,
    load_local_index,
)
from .vector_search import (
    ProviderIdentityMismatchError,
    QueryVectorError,
    SearchInputError,
    VectorSearchError,
    VectorSearchHit,
    VectorSearchResult,
    search_local_index,
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
    "INDEX_BUILDER_VERSION",
    "IndexArtifactError",
    "IndexBuildError",
    "IndexLoadError",
    "LocalVectorIndex",
    "ProviderIdentityMismatchError",
    "QueryVectorError",
    "SearchInputError",
    "SentenceTransformerConfig",
    "SentenceTransformerEmbeddingProvider",
    "VectorSearchError",
    "VectorSearchHit",
    "VectorSearchResult",
    "build_embedding_text",
    "build_local_index",
    "embed_documents_checked",
    "embed_query_checked",
    "load_local_index",
    "search_local_index",
    "validate_document_embeddings",
    "validate_query_embedding",
]
