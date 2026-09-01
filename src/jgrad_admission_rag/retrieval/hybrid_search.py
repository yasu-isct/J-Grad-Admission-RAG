from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from ..schemas.document_kb import ScopeType
from ..schemas.index import IndexManifest, IndexPayload
from .embedding import EmbeddingProvider
from .lexical_search import (
    LexicalSearchError,
    LexicalSearchHit,
    build_lexical_searcher,
    tokenize_lexical,
)
from .local_index import LocalVectorIndex
from .vector_search import (
    SearchInputError,
    VectorSearchHit,
    search_loaded_index,
    validate_search_inputs,
)

HYBRID_FUSION_VERSION = "rrf-v1"
RRF_K = 60
VECTOR_CHANNEL_WEIGHT = 1.0
LEXICAL_CHANNEL_WEIGHT = 1.0
DEFAULT_HYBRID_CANDIDATE_K = 50
CHANNEL_ORDER = ("vector", "lexical")

ChannelName = Literal["vector", "lexical"]


class HybridSearchError(Exception):
    """Base class for deterministic hybrid-search failures."""


class HybridInputError(HybridSearchError):
    """Raised when top-k or candidate-depth input is invalid."""


class HybridFusionError(HybridSearchError):
    """Raised when ranked channel candidates cannot be fused safely."""


@dataclass(frozen=True, slots=True)
class HybridSearchHit:
    rank: int
    row_index: int
    fused_score: float
    fusion_version: str
    vector_rank: int | None
    vector_score: float | None
    lexical_rank: int | None
    lexical_score: float | None
    matched_channels: tuple[ChannelName, ...]
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
            "fused_score": self.fused_score,
            "fusion_version": self.fusion_version,
            "vector_rank": self.vector_rank,
            "vector_score": self.vector_score,
            "lexical_rank": self.lexical_rank,
            "lexical_score": self.lexical_score,
            "matched_channels": list(self.matched_channels),
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
class HybridSearchResult:
    manifest: IndexManifest
    fusion_version: str
    rrf_k: int
    top_k_requested: int
    candidate_k_requested: int | None
    candidate_k_resolved: int
    vector_candidate_count: int
    lexical_candidate_count: int
    hits: tuple[HybridSearchHit, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.model_dump(mode="json"),
            "fusion_version": self.fusion_version,
            "rrf_k": self.rrf_k,
            "top_k_requested": self.top_k_requested,
            "candidate_k_requested": self.candidate_k_requested,
            "candidate_k_resolved": self.candidate_k_resolved,
            "vector_candidate_count": self.vector_candidate_count,
            "lexical_candidate_count": self.lexical_candidate_count,
            "hits": [hit.to_dict() for hit in self.hits],
        }


def resolve_candidate_depth(top_k: int, candidate_k: int | None = None) -> int:
    """Validate hybrid depths and return the shared per-channel candidate depth."""

    _validate_positive_int(top_k, "top_k")
    if candidate_k is None:
        return max(top_k, DEFAULT_HYBRID_CANDIDATE_K)
    _validate_positive_int(candidate_k, "candidate_k")
    if candidate_k < top_k:
        raise HybridInputError("candidate_k must be greater than or equal to top_k")
    return candidate_k


def fuse_ranked_hits(
    index: LocalVectorIndex,
    vector_hits: Sequence[VectorSearchHit],
    lexical_hits: Sequence[LexicalSearchHit],
    *,
    top_k: int = 5,
    candidate_k: int | None = None,
) -> HybridSearchResult:
    """Fuse validated channel ranks without comparing their raw scores."""

    if not isinstance(index, LocalVectorIndex):
        raise HybridFusionError("index must be a validated LocalVectorIndex")
    resolved_candidate_k = resolve_candidate_depth(top_k, candidate_k)
    vectors = _validate_channel_hits(
        index, vector_hits, channel="vector", candidate_k=resolved_candidate_k
    )
    lexicals = _validate_channel_hits(
        index, lexical_hits, channel="lexical", candidate_k=resolved_candidate_k
    )

    rows = set(vectors).union(lexicals)
    scored_rows: list[tuple[float, int]] = []
    for row_index in rows:
        contributions: list[float] = []
        if row_index in vectors:
            contributions.append(VECTOR_CHANNEL_WEIGHT / (RRF_K + vectors[row_index].rank))
        if row_index in lexicals:
            contributions.append(LEXICAL_CHANNEL_WEIGHT / (RRF_K + lexicals[row_index].rank))
        fused_score = math.fsum(contributions)
        if not math.isfinite(fused_score) or fused_score <= 0.0:
            raise HybridFusionError("fused RRF score is invalid")
        scored_rows.append((fused_score, row_index))

    scored_rows.sort(key=lambda item: (-item[0], item[1]))
    selected = scored_rows[: min(top_k, len(scored_rows))]
    hits = tuple(
        _hybrid_hit(
            rank,
            index.payloads[row_index],
            fused_score,
            vectors.get(row_index),
            lexicals.get(row_index),
        )
        for rank, (fused_score, row_index) in enumerate(selected, start=1)
    )
    return HybridSearchResult(
        manifest=index.manifest.model_copy(deep=True),
        fusion_version=HYBRID_FUSION_VERSION,
        rrf_k=RRF_K,
        top_k_requested=top_k,
        candidate_k_requested=candidate_k,
        candidate_k_resolved=resolved_candidate_k,
        vector_candidate_count=len(vectors),
        lexical_candidate_count=len(lexicals),
        hits=hits,
    )


def search_hybrid_index(
    index: LocalVectorIndex,
    query: str,
    provider: EmbeddingProvider,
    *,
    top_k: int = 5,
    candidate_k: int | None = None,
) -> HybridSearchResult:
    """Run vector and lexical retrieval once each over one validated index, then fuse ranks."""

    try:
        validate_search_inputs(query, top_k)
    except SearchInputError as error:
        raise HybridInputError(str(error)) from error
    resolved_candidate_k = resolve_candidate_depth(top_k, candidate_k)
    if not tokenize_lexical(query):
        raise HybridInputError("query does not contain any lexical tokens")
    vector_result = search_loaded_index(index, query, provider, top_k=resolved_candidate_k)
    try:
        lexical_result = build_lexical_searcher(index).search(query, top_k=resolved_candidate_k)
    except LexicalSearchError as error:
        raise HybridInputError(str(error)) from error
    return fuse_ranked_hits(
        index,
        vector_result.hits,
        lexical_result.hits,
        top_k=top_k,
        candidate_k=candidate_k,
    )


def _validate_channel_hits(
    index: LocalVectorIndex,
    hits: Sequence[VectorSearchHit] | Sequence[LexicalSearchHit],
    *,
    channel: ChannelName,
    candidate_k: int,
) -> dict[int, VectorSearchHit | LexicalSearchHit]:
    expected_type = VectorSearchHit if channel == "vector" else LexicalSearchHit
    if not isinstance(hits, Sequence) or isinstance(hits, (str, bytes, bytearray)):
        raise HybridFusionError(f"{channel} hits must be a ranked sequence")
    if len(hits) > candidate_k:
        raise HybridFusionError(f"{channel} hit count exceeds candidate_k")

    by_row: dict[int, VectorSearchHit | LexicalSearchHit] = {}
    for position, hit in enumerate(hits, start=1):
        if not isinstance(hit, expected_type):
            raise HybridFusionError(f"{channel} result contains the wrong hit type")
        if isinstance(hit.rank, bool) or not isinstance(hit.rank, int) or hit.rank != position:
            raise HybridFusionError(f"{channel} ranks must be contiguous from one")
        if (
            isinstance(hit.row_index, bool)
            or not isinstance(hit.row_index, int)
            or hit.row_index < 0
            or hit.row_index >= len(index.payloads)
        ):
            raise HybridFusionError(f"{channel} row_index is outside the payload corpus")
        if hit.row_index in by_row:
            raise HybridFusionError(f"{channel} results contain a duplicate row_index")
        if not isinstance(hit.score, (int, float)) or isinstance(hit.score, bool):
            raise HybridFusionError(f"{channel} raw score is invalid")
        if not math.isfinite(float(hit.score)):
            raise HybridFusionError(f"{channel} raw score is non-finite")
        if _hit_evidence(hit) != _payload_evidence(index.payloads[hit.row_index]):
            raise HybridFusionError(f"{channel} hit evidence does not match its payload row")
        by_row[hit.row_index] = hit
    return by_row


def _hybrid_hit(
    rank: int,
    payload: IndexPayload,
    fused_score: float,
    vector_hit: VectorSearchHit | LexicalSearchHit | None,
    lexical_hit: VectorSearchHit | LexicalSearchHit | None,
) -> HybridSearchHit:
    if vector_hit is None and lexical_hit is None:
        raise HybridFusionError("hybrid hit must have at least one channel")
    matched_channels: tuple[ChannelName, ...] = tuple(
        channel
        for channel, hit in (("vector", vector_hit), ("lexical", lexical_hit))
        if hit is not None
    )
    return HybridSearchHit(
        rank=rank,
        row_index=payload.row_index,
        fused_score=fused_score,
        fusion_version=HYBRID_FUSION_VERSION,
        vector_rank=vector_hit.rank if vector_hit is not None else None,
        vector_score=float(vector_hit.score) if vector_hit is not None else None,
        lexical_rank=lexical_hit.rank if lexical_hit is not None else None,
        lexical_score=float(lexical_hit.score) if lexical_hit is not None else None,
        matched_channels=matched_channels,
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


def _hit_evidence(hit: VectorSearchHit | LexicalSearchHit) -> tuple[Any, ...]:
    return (
        hit.document_id,
        hit.unit_id,
        hit.fact_id,
        hit.text,
        tuple(hit.source_pages),
        tuple(hit.section_path),
        hit.fact_type,
        hit.scope_type,
        tuple(hit.scope_targets),
        hit.parent_college,
        _thaw_json(hit.metadata),
    )


def _payload_evidence(payload: IndexPayload) -> tuple[Any, ...]:
    return (
        payload.document_id,
        payload.unit_id,
        payload.fact_id,
        payload.text,
        tuple(payload.source_pages),
        tuple(payload.section_path),
        payload.fact_type,
        payload.scope_type,
        tuple(payload.scope_targets),
        payload.parent_college,
        copy.deepcopy(payload.metadata),
    )


def _validate_positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HybridInputError(f"{name} must be a positive non-bool integer")


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
