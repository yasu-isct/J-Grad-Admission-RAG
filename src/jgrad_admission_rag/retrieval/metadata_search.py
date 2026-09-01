from __future__ import annotations

import copy
import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from ..schemas.document_kb import ScopeType
from ..schemas.index import IndexManifest, IndexPayload
from .embedding import EmbeddingProvider
from .hybrid_search import (
    HYBRID_FUSION_VERSION,
    RRF_K,
    HybridInputError,
    HybridSearchHit,
    _rank_fused_union,
    resolve_candidate_depth,
)
from .lexical_search import build_lexical_searcher, tokenize_lexical
from .local_index import LocalVectorIndex
from .vector_search import SearchInputError, search_loaded_index, validate_search_inputs

METADATA_FILTER_VERSION = "exact-metadata-v1"
SCOPE_RERANK_VERSION = "scope-match-v1"
SCOPE_TARGET_MATCH_BOOST = 1.0 / (RRF_K + 1)
PARENT_COLLEGE_MATCH_BOOST = 0.5 / (RRF_K + 1)
PREFERENCE_ORDER = ("scope_target", "parent_college")
SCOPE_TYPES = frozenset({"global", "department", "unknown"})

PreferenceName = Literal["scope_target", "parent_college"]


class MetadataSearchError(Exception):
    """Base class for explicit metadata retrieval failures."""


class MetadataInputError(MetadataSearchError):
    """Raised when a filter or preference is malformed."""


@dataclass(frozen=True, slots=True)
class MetadataFilter:
    fact_types: tuple[str, ...] = ()
    scope_types: tuple[ScopeType, ...] = ()
    scope_targets: tuple[str, ...] = ()
    parent_colleges: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_types", _normalize_values(self.fact_types, "fact_types"))
        object.__setattr__(
            self,
            "scope_types",
            _normalize_scope_types(self.scope_types),
        )
        object.__setattr__(
            self,
            "scope_targets",
            _normalize_values(self.scope_targets, "scope_targets"),
        )
        object.__setattr__(
            self,
            "parent_colleges",
            _normalize_values(self.parent_colleges, "parent_colleges"),
        )

    @property
    def active(self) -> bool:
        return any((self.fact_types, self.scope_types, self.scope_targets, self.parent_colleges))

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "fact_types": list(self.fact_types),
            "scope_types": list(self.scope_types),
            "scope_targets": list(self.scope_targets),
            "parent_colleges": list(self.parent_colleges),
        }


@dataclass(frozen=True, slots=True)
class ScopePreference:
    preferred_scope_targets: tuple[str, ...] = ()
    preferred_parent_colleges: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "preferred_scope_targets",
            _normalize_values(self.preferred_scope_targets, "preferred_scope_targets"),
        )
        object.__setattr__(
            self,
            "preferred_parent_colleges",
            _normalize_values(self.preferred_parent_colleges, "preferred_parent_colleges"),
        )

    @property
    def active(self) -> bool:
        return bool(self.preferred_scope_targets or self.preferred_parent_colleges)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "preferred_scope_targets": list(self.preferred_scope_targets),
            "preferred_parent_colleges": list(self.preferred_parent_colleges),
        }


@dataclass(frozen=True, slots=True)
class MetadataSearchHit:
    rank: int
    ranking_score: float
    fused_score: float
    scope_boost_total: float
    matched_preferences: tuple[PreferenceName, ...]
    matched_scope_targets: tuple[str, ...]
    matched_parent_college: str | None
    fusion_version: str
    vector_rank: int | None
    vector_score: float | None
    lexical_rank: int | None
    lexical_score: float | None
    matched_channels: tuple[str, ...]
    row_index: int
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
            "ranking_score": self.ranking_score,
            "fused_score": self.fused_score,
            "scope_boost_total": self.scope_boost_total,
            "matched_preferences": list(self.matched_preferences),
            "matched_scope_targets": list(self.matched_scope_targets),
            "matched_parent_college": self.matched_parent_college,
            "fusion_version": self.fusion_version,
            "vector_rank": self.vector_rank,
            "vector_score": self.vector_score,
            "lexical_rank": self.lexical_rank,
            "lexical_score": self.lexical_score,
            "matched_channels": list(self.matched_channels),
            "row_index": self.row_index,
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
class MetadataSearchResult:
    manifest: IndexManifest
    metadata_filter_version: str
    scope_rerank_version: str
    fusion_version: str
    rrf_k: int
    scope_target_match_boost: float
    parent_college_match_boost: float
    requested_filter: MetadataFilter
    requested_preference: ScopePreference
    corpus_row_count: int
    eligible_row_count: int
    top_k_requested: int
    candidate_k_requested: int | None
    candidate_k_resolved: int
    vector_candidate_count: int
    lexical_candidate_count: int
    hits: tuple[MetadataSearchHit, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.model_dump(mode="json"),
            "metadata_filter_version": self.metadata_filter_version,
            "scope_rerank_version": self.scope_rerank_version,
            "fusion_version": self.fusion_version,
            "rrf_k": self.rrf_k,
            "scope_target_match_boost": self.scope_target_match_boost,
            "parent_college_match_boost": self.parent_college_match_boost,
            "requested_filter": self.requested_filter.to_dict(),
            "requested_preference": self.requested_preference.to_dict(),
            "corpus_row_count": self.corpus_row_count,
            "eligible_row_count": self.eligible_row_count,
            "top_k_requested": self.top_k_requested,
            "candidate_k_requested": self.candidate_k_requested,
            "candidate_k_resolved": self.candidate_k_resolved,
            "vector_candidate_count": self.vector_candidate_count,
            "lexical_candidate_count": self.lexical_candidate_count,
            "result_count": len(self.hits),
            "hits": [hit.to_dict() for hit in self.hits],
        }


def derive_eligible_rows(
    payloads: Sequence[IndexPayload],
    metadata_filter: MetadataFilter,
) -> tuple[int, ...]:
    """Return ordered rows satisfying exact OR-within/AND-across filter semantics."""

    if not isinstance(metadata_filter, MetadataFilter):
        raise MetadataInputError("metadata_filter must be a MetadataFilter")
    eligible: list[int] = []
    for position, payload in enumerate(payloads):
        if not isinstance(payload, IndexPayload) or payload.row_index != position:
            raise MetadataInputError("payloads must be contiguous ordered IndexPayload rows")
        if metadata_filter.fact_types and payload.fact_type not in metadata_filter.fact_types:
            continue
        if metadata_filter.scope_types and payload.scope_type not in metadata_filter.scope_types:
            continue
        if metadata_filter.scope_targets and not set(payload.scope_targets).intersection(
            metadata_filter.scope_targets
        ):
            continue
        if metadata_filter.parent_colleges and (
            payload.parent_college is None
            or payload.parent_college not in metadata_filter.parent_colleges
        ):
            continue
        eligible.append(payload.row_index)
    return tuple(eligible)


def search_metadata_index(
    index: LocalVectorIndex,
    query: str,
    provider: EmbeddingProvider,
    *,
    metadata_filter: MetadataFilter | None = None,
    scope_preference: ScopePreference | None = None,
    top_k: int = 5,
    candidate_k: int | None = None,
) -> MetadataSearchResult:
    """Filter before channel truncation, fuse all candidates, then apply exact scope boosts."""

    selected_filter = MetadataFilter() if metadata_filter is None else metadata_filter
    selected_preference = ScopePreference() if scope_preference is None else scope_preference
    if not isinstance(selected_filter, MetadataFilter):
        raise MetadataInputError("metadata_filter must be a MetadataFilter")
    if not isinstance(selected_preference, ScopePreference):
        raise MetadataInputError("scope_preference must be a ScopePreference")
    try:
        validate_search_inputs(query, top_k)
        resolved_candidate_k = resolve_candidate_depth(top_k, candidate_k)
    except (SearchInputError, HybridInputError, ValueError) as error:
        raise MetadataInputError(str(error)) from error
    if not tokenize_lexical(query):
        raise MetadataInputError("query does not contain any lexical tokens")

    eligible_rows = derive_eligible_rows(index.payloads, selected_filter)
    vector = search_loaded_index(
        index,
        query,
        provider,
        top_k=resolved_candidate_k,
        eligible_rows=eligible_rows,
    )
    lexical = build_lexical_searcher(index).search(
        query,
        top_k=resolved_candidate_k,
        eligible_rows=eligible_rows,
    )
    fused_union, vector_count, lexical_count = _rank_fused_union(
        index,
        vector.hits,
        lexical.hits,
        candidate_k=resolved_candidate_k,
    )
    hits = rerank_hybrid_hits(
        fused_union,
        selected_preference,
        top_k=top_k,
    )
    return MetadataSearchResult(
        manifest=index.manifest.model_copy(deep=True),
        metadata_filter_version=METADATA_FILTER_VERSION,
        scope_rerank_version=SCOPE_RERANK_VERSION,
        fusion_version=HYBRID_FUSION_VERSION,
        rrf_k=RRF_K,
        scope_target_match_boost=SCOPE_TARGET_MATCH_BOOST,
        parent_college_match_boost=PARENT_COLLEGE_MATCH_BOOST,
        requested_filter=selected_filter,
        requested_preference=selected_preference,
        corpus_row_count=len(index.payloads),
        eligible_row_count=len(eligible_rows),
        top_k_requested=top_k,
        candidate_k_requested=candidate_k,
        candidate_k_resolved=resolved_candidate_k,
        vector_candidate_count=vector_count,
        lexical_candidate_count=lexical_count,
        hits=hits,
    )


def rerank_hybrid_hits(
    fused_hits: Sequence[HybridSearchHit],
    preference: ScopePreference,
    *,
    top_k: int,
) -> tuple[MetadataSearchHit, ...]:
    if not isinstance(preference, ScopePreference):
        raise MetadataInputError("preference must be a ScopePreference")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
        raise MetadataInputError("top_k must be a positive non-bool integer")
    if not isinstance(fused_hits, Sequence) or isinstance(fused_hits, (str, bytes, bytearray)):
        raise MetadataInputError("fused_hits must be a sequence of HybridSearchHit records")
    if any(not isinstance(hit, HybridSearchHit) for hit in fused_hits):
        raise MetadataInputError("fused_hits contains the wrong hit type")
    scored: list[tuple[float, int, HybridSearchHit, tuple[str, ...], str | None]] = []
    requested_targets = set(preference.preferred_scope_targets)
    requested_colleges = set(preference.preferred_parent_colleges)
    for hit in fused_hits:
        matched_targets = tuple(sorted(set(hit.scope_targets).intersection(requested_targets)))
        matched_college = (
            hit.parent_college
            if hit.parent_college is not None and hit.parent_college in requested_colleges
            else None
        )
        bonus = math.fsum(
            (
                SCOPE_TARGET_MATCH_BOOST if matched_targets else 0.0,
                PARENT_COLLEGE_MATCH_BOOST if matched_college is not None else 0.0,
            )
        )
        ranking_score = math.fsum((hit.fused_score, bonus))
        if not math.isfinite(ranking_score):
            raise MetadataSearchError("metadata ranking score became non-finite")
        scored.append((ranking_score, hit.row_index, hit, matched_targets, matched_college))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(
        _metadata_hit(rank, ranking_score, hit, matched_targets, matched_college)
        for rank, (ranking_score, _, hit, matched_targets, matched_college) in enumerate(
            scored[: min(top_k, len(scored))], start=1
        )
    )


def _metadata_hit(
    rank: int,
    ranking_score: float,
    hit: HybridSearchHit,
    matched_targets: tuple[str, ...],
    matched_college: str | None,
) -> MetadataSearchHit:
    matched_preferences: tuple[PreferenceName, ...] = tuple(
        name
        for name, matched in (
            ("scope_target", bool(matched_targets)),
            ("parent_college", matched_college is not None),
        )
        if matched
    )
    scope_boost_total = math.fsum(
        (
            SCOPE_TARGET_MATCH_BOOST if matched_targets else 0.0,
            PARENT_COLLEGE_MATCH_BOOST if matched_college is not None else 0.0,
        )
    )
    return MetadataSearchHit(
        rank=rank,
        ranking_score=ranking_score,
        fused_score=hit.fused_score,
        scope_boost_total=scope_boost_total,
        matched_preferences=matched_preferences,
        matched_scope_targets=matched_targets,
        matched_parent_college=matched_college,
        fusion_version=HYBRID_FUSION_VERSION,
        vector_rank=hit.vector_rank,
        vector_score=hit.vector_score,
        lexical_rank=hit.lexical_rank,
        lexical_score=hit.lexical_score,
        matched_channels=hit.matched_channels,
        row_index=hit.row_index,
        document_id=hit.document_id,
        unit_id=hit.unit_id,
        fact_id=hit.fact_id,
        text=hit.text,
        source_pages=hit.source_pages,
        section_path=hit.section_path,
        fact_type=hit.fact_type,
        scope_type=hit.scope_type,
        scope_targets=hit.scope_targets,
        parent_college=hit.parent_college,
        metadata=_freeze_json(copy.deepcopy(_thaw_json(hit.metadata))),
    )


def _normalize_values(values: Collection[str], name: str) -> tuple[str, ...]:
    if not isinstance(values, Collection) or isinstance(values, (str, bytes, bytearray)):
        raise MetadataInputError(f"{name} must be a finite collection of exact strings")
    items = tuple(values)
    if any(not isinstance(value, str) or not value or value != value.strip() for value in items):
        raise MetadataInputError(f"{name} values must be non-blank trimmed strings")
    if len(items) != len(set(items)):
        raise MetadataInputError(f"{name} values must be duplicate-free")
    return tuple(sorted(items))


def _normalize_scope_types(values: Collection[str]) -> tuple[ScopeType, ...]:
    normalized = _normalize_values(values, "scope_types")
    if any(value not in SCOPE_TYPES for value in normalized):
        raise MetadataInputError("scope_types contains an unsupported controlled value")
    return normalized  # type: ignore[return-value]


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
