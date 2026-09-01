from __future__ import annotations

import copy
import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from ..schemas.document_kb import ScopeType
from ..schemas.index import IndexManifest, IndexPayload
from .embedding import EmbeddingIdentity, EmbeddingProvider, embed_query_checked
from .eligible_rows import validate_eligible_rows
from .local_index import LocalVectorIndex, NORM_ABSOLUTE_TOLERANCE, load_local_index


class VectorSearchError(Exception):
    """Base class for validated local vector-search failures."""


class SearchInputError(VectorSearchError):
    """Raised when the caller supplies an invalid query or top-k value."""


class ProviderIdentityMismatchError(VectorSearchError):
    """Raised when the query provider differs from the index provider identity."""


class QueryVectorError(VectorSearchError):
    """Raised when a checked query vector cannot satisfy cosine-search invariants."""


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    rank: int
    row_index: int
    score: float
    document_id: str
    unit_id: str
    fact_id: str
    text: str
    source_pages: tuple[int, ...]
    section_path: tuple[str, ...]
    fact_type: str
    scope_type: ScopeType
    scope_targets: tuple[str, ...]
    parent_college: str | None
    metadata: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "row_index": self.row_index,
            "score": self.score,
            "document_id": self.document_id,
            "unit_id": self.unit_id,
            "fact_id": self.fact_id,
            "text": self.text,
            "source_pages": list(self.source_pages),
            "section_path": list(self.section_path),
            "fact_type": self.fact_type,
            "scope_type": self.scope_type,
            "scope_targets": list(self.scope_targets),
            "parent_college": self.parent_college,
            "metadata": _thaw_json(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    manifest: IndexManifest
    hits: tuple[VectorSearchHit, ...]


def search_local_index(
    index_dir: str | Path,
    query: str,
    provider: EmbeddingProvider,
    *,
    top_k: int = 5,
    eligible_rows: Collection[int] | None = None,
) -> VectorSearchResult:
    """Search one validated local index with deterministic exhaustive cosine ranking."""

    validate_search_inputs(query, top_k)
    index = load_local_index(index_dir, mmap=True)
    return search_loaded_index(index, query, provider, top_k=top_k, eligible_rows=eligible_rows)


def search_loaded_index(
    index: LocalVectorIndex,
    query: str,
    provider: EmbeddingProvider,
    *,
    top_k: int = 5,
    eligible_rows: Collection[int] | None = None,
) -> VectorSearchResult:
    """Search a previously validated local index without reading its files again."""

    validate_search_inputs(query, top_k)
    identity = provider.identity
    _validate_provider_identity(index.manifest, identity)
    query_vector = _normalize_query_vector(
        embed_query_checked(provider, query),
        index.manifest.embedding_dimension,
    )

    scores = np.asarray(index.vectors @ query_vector, dtype=np.dtype("<f4"))
    if scores.shape != (index.manifest.vector_count,) or not np.isfinite(scores).all():
        raise QueryVectorError("cosine similarity scores are invalid")
    validated_rows = validate_eligible_rows(index.manifest.vector_count, eligible_rows)
    row_indices = (
        np.arange(index.manifest.vector_count, dtype=np.int64)
        if validated_rows is None
        else np.asarray(validated_rows, dtype=np.int64)
    )
    eligible_scores = scores[row_indices]
    ordered_positions = np.lexsort((row_indices, -eligible_scores.astype(np.float64)))
    selected_rows = row_indices[ordered_positions[: min(top_k, len(ordered_positions))]]
    hits = tuple(
        _hit_from_payload(rank, index.payloads[int(row)], float(scores[int(row)]))
        for rank, row in enumerate(selected_rows, start=1)
    )
    return VectorSearchResult(manifest=index.manifest.model_copy(deep=True), hits=hits)


def validate_search_inputs(query: object, top_k: object) -> None:
    if not isinstance(query, str) or not query.strip():
        raise SearchInputError("query must be a non-blank Python string")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
        raise SearchInputError("top_k must be a positive non-bool integer")


def _validate_provider_identity(manifest: IndexManifest, identity: EmbeddingIdentity) -> None:
    expected = {
        "provider": manifest.embedding_provider,
        "model": manifest.embedding_model,
        "revision": manifest.embedding_revision,
        "dimension": manifest.embedding_dimension,
    }
    observed = {
        "provider": identity.provider,
        "model": identity.model,
        "revision": identity.revision,
        "dimension": identity.dimension,
    }
    mismatches = [name for name in expected if expected[name] != observed[name]]
    if mismatches:
        raise ProviderIdentityMismatchError(
            "query provider identity does not match index manifest fields: " + ", ".join(mismatches)
        )


def _normalize_query_vector(values: list[float], dimension: int) -> np.ndarray:
    try:
        with np.errstate(over="ignore", invalid="ignore"):
            vector = np.asarray(values, dtype=np.dtype("<f4"), order="C")
    except (TypeError, ValueError, OverflowError) as error:
        raise QueryVectorError("query embedding could not be converted to float32") from error
    if vector.shape != (dimension,):
        raise QueryVectorError("query embedding shape does not match index dimension")
    if not np.isfinite(vector).all():
        raise QueryVectorError("query embedding became non-finite during float32 conversion")

    vector64 = vector.astype(np.float64)
    norm = math.sqrt(float(np.sum(vector64 * vector64, dtype=np.float64)))
    if not math.isfinite(norm) or norm == 0.0:
        raise QueryVectorError("query embedding has a zero or non-finite L2 norm")
    normalized = np.asarray(vector64 / norm, dtype=np.dtype("<f4"), order="C")
    stored_norm = math.sqrt(float(np.sum(normalized.astype(np.float64) ** 2, dtype=np.float64)))
    if not math.isfinite(stored_norm) or not math.isclose(
        stored_norm,
        1.0,
        rel_tol=0.0,
        abs_tol=NORM_ABSOLUTE_TOLERANCE,
    ):
        raise QueryVectorError("normalized query embedding failed stored-vector validation")
    normalized.setflags(write=False)
    return normalized


def _hit_from_payload(rank: int, payload: IndexPayload, score: float) -> VectorSearchHit:
    return VectorSearchHit(
        rank=rank,
        row_index=payload.row_index,
        score=score,
        document_id=payload.document_id,
        unit_id=payload.unit_id,
        fact_id=payload.fact_id,
        text=payload.text,
        source_pages=tuple(payload.source_pages),
        section_path=tuple(payload.section_path),
        fact_type=payload.fact_type,
        scope_type=payload.scope_type,
        scope_targets=tuple(payload.scope_targets),
        parent_college=payload.parent_college,
        metadata=_freeze_json(copy.deepcopy(payload.metadata)),
    )


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(child) for child in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(child) for child in value]
    return value
