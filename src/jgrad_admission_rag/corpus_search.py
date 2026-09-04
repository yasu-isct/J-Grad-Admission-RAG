"""Safe in-memory hybrid retrieval across an explicitly selected corpus."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .corpus import CorpusAuditError, audit_corpus_manifest
from .corpus_selection import (
    CorpusSelectionError,
    revalidate_corpus_selection_result,
)
from .retrieval.embedding import EmbeddingIdentity, EmbeddingProvider, embed_query_checked
from .retrieval.embedding_text import EMBEDDING_TEXT_VERSION
from .retrieval.hybrid_search import (
    HYBRID_FUSION_VERSION,
    LEXICAL_CHANNEL_WEIGHT,
    RRF_K,
    VECTOR_CHANNEL_WEIGHT,
    resolve_candidate_depth,
)
from .retrieval.index_freshness import (
    IndexFreshnessError,
    IndexFreshnessReport,
    load_fresh_index_context,
)
from .retrieval.lexical_search import (
    BM25_B,
    BM25_K1,
    LEXICAL_SCORING_VERSION,
    LEXICAL_TOKENIZER_VERSION,
    build_lexical_projection,
    tokenize_lexical,
)
from .retrieval.local_index import NORM_ABSOLUTE_TOLERANCE, IndexLoadError, load_local_index
from .retrieval.metadata_search import (
    METADATA_FILTER_VERSION,
    PARENT_COLLEGE_MATCH_BOOST,
    SCOPE_RERANK_VERSION,
    SCOPE_TARGET_MATCH_BOOST,
    MetadataFilter,
    ScopePreference,
)
from .schemas.corpus_manifest import CorpusIndexManifest, CorpusManifest
from .schemas.corpus_version import (
    CorpusSelectionResult,
    CorpusVersionPolicy,
    SelectedCorpusDocument,
    canonical_corpus_selection_result_bytes,
)
from .schemas.document_identity import DocumentIdentity
from .schemas.document_kb import ScopeType
from .schemas.index import IndexManifest, IndexPayload, derive_index_payloads

CORPUS_SEARCH_SCHEMA_VERSION = "1.0"
CORPUS_SEARCH_RANKING_VERSION = "global-hybrid-v1"
CORPUS_PAYLOAD_SCHEMA_VERSION = "index-payload-v1"
RETRIEVAL_CANDIDATES_ONLY = "retrieval_candidates_not_eligibility_or_answers"


class CorpusSearchError(Exception):
    """Base class for generic corpus preparation and search failures."""


class CorpusSearchPreparationError(CorpusSearchError):
    """Raised when selected artifacts cannot form one safe search context."""


class CorpusSearchInputError(CorpusSearchError):
    """Raised when a corpus query request is invalid."""


class CorpusSearchProviderError(CorpusSearchError):
    """Raised when the query provider cannot satisfy the prepared context."""


class CorpusSearchResultCompatibilityError(CorpusSearchError):
    """Raised when a saved result differs from a re-executed prepared query."""


class CorpusSearchSchemaError(CorpusSearchError):
    """Raised when corpus-search result bytes are invalid or unsupported."""


class SearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CorpusEmbeddingIdentity(SearchModel):
    provider: str
    model: str
    revision: str | None = None
    dimension: int = Field(gt=0, strict=True)

    @field_validator("provider", "model", "revision")
    @classmethod
    def identity_values_must_be_trimmed(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != value.strip()):
            raise ValueError("embedding identity values must be non-empty and trimmed")
        return value


class CorpusMetadataFilter(SearchModel):
    fact_types: tuple[str, ...] = ()
    scope_types: tuple[ScopeType, ...] = ()
    scope_targets: tuple[str, ...] = ()
    parent_colleges: tuple[str, ...] = ()

    @field_validator("fact_types", "scope_types", "scope_targets", "parent_colleges")
    @classmethod
    def values_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.strip() for value in values):
            raise ValueError("metadata filter values must be non-empty and trimmed")
        if len(values) != len(set(values)):
            raise ValueError("metadata filter values must be unique")
        return tuple(sorted(values))


class CorpusScopePreference(SearchModel):
    preferred_scope_targets: tuple[str, ...] = ()
    preferred_parent_colleges: tuple[str, ...] = ()

    @field_validator("preferred_scope_targets", "preferred_parent_colleges")
    @classmethod
    def values_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or value != value.strip() for value in values):
            raise ValueError("scope preference values must be non-empty and trimmed")
        if len(values) != len(set(values)):
            raise ValueError("scope preference values must be unique")
        return tuple(sorted(values))


class CorpusSearchRequest(SearchModel):
    query: str
    top_k: int = Field(default=5, gt=0, strict=True)
    candidate_k: int | None = Field(default=None, gt=0, strict=True)
    metadata_filter: CorpusMetadataFilter = Field(default_factory=CorpusMetadataFilter)
    scope_preference: CorpusScopePreference = Field(default_factory=CorpusScopePreference)

    @field_validator("query")
    @classmethod
    def query_must_be_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must be non-blank")
        if not tokenize_lexical(value):
            raise ValueError("query must contain lexical tokens")
        return value

    @model_validator(mode="after")
    def candidate_depth_must_cover_top_k(self) -> CorpusSearchRequest:
        if self.candidate_k is not None and self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        return self


class CorpusEvidenceKey(SearchModel):
    document_id: str
    local_row_index: int = Field(ge=0, strict=True)
    unit_id: str
    fact_id: str

    @field_validator("document_id", "unit_id", "fact_id")
    @classmethod
    def values_must_be_trimmed(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("evidence identity values must be non-empty and trimmed")
        return value


class CorpusChannelCandidate(SearchModel):
    rank: int = Field(gt=0, strict=True)
    key: CorpusEvidenceKey
    score: float
    matched_terms: tuple[str, ...] = ()

    @field_validator("score")
    @classmethod
    def score_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("candidate score must be finite")
        return value


class CorpusDocumentSearchCounts(SearchModel):
    document_id: str
    corpus_row_count: int = Field(ge=0, strict=True)
    eligible_row_count: int = Field(ge=0, strict=True)
    vector_candidate_count: int = Field(ge=0, strict=True)
    lexical_candidate_count: int = Field(ge=0, strict=True)
    result_count: int = Field(ge=0, strict=True)


class CorpusSearchHit(SearchModel):
    rank: int = Field(gt=0, strict=True)
    key: CorpusEvidenceKey
    version_classification: Literal["active", "historical"]
    identity: DocumentIdentity
    payload: IndexPayload
    kb_path: str
    source_kb_sha256: str
    index_path: str
    index_manifest: CorpusIndexManifest
    ranking_score: float
    fused_score: float
    scope_boost_total: float
    matched_preferences: tuple[Literal["scope_target", "parent_college"], ...]
    matched_scope_targets: tuple[str, ...]
    matched_parent_college: str | None
    vector_rank: int | None = Field(default=None, gt=0, strict=True)
    vector_score: float | None = None
    lexical_rank: int | None = Field(default=None, gt=0, strict=True)
    lexical_score: float | None = None
    matched_channels: tuple[Literal["vector", "lexical"], ...]
    text: str
    source_pages: tuple[int, ...]
    section_path: tuple[str, ...]
    fact_type: str
    scope_type: ScopeType
    scope_targets: tuple[str, ...]
    parent_college: str | None
    metadata: dict[str, Any]

    @model_validator(mode="after")
    def channel_and_score_fields_must_align(self) -> CorpusSearchHit:
        for value in (
            self.ranking_score,
            self.fused_score,
            self.scope_boost_total,
            self.vector_score,
            self.lexical_score,
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError("hit scores must be finite")
        expected_channels = tuple(
            channel
            for channel, rank, score in (
                ("vector", self.vector_rank, self.vector_score),
                ("lexical", self.lexical_rank, self.lexical_score),
            )
            if rank is not None and score is not None
        )
        if expected_channels != self.matched_channels:
            raise ValueError("matched channels do not align with channel fields")
        if not expected_channels:
            raise ValueError("a hit must belong to at least one channel")
        if (self.vector_rank is None) != (self.vector_score is None) or (
            self.lexical_rank is None
        ) != (self.lexical_score is None):
            raise ValueError("channel ranks and scores must be paired")
        return self


class CorpusSearchResult(SearchModel):
    schema_version: Literal["1.0"] = CORPUS_SEARCH_SCHEMA_VERSION
    ranking_version: Literal["global-hybrid-v1"] = CORPUS_SEARCH_RANKING_VERSION
    fusion_version: Literal["rrf-v1"] = HYBRID_FUSION_VERSION
    lexical_tokenizer_version: Literal["nfkc-casefold-ja23-v1"] = LEXICAL_TOKENIZER_VERSION
    lexical_scoring_version: Literal["bm25-v1"] = LEXICAL_SCORING_VERSION
    metadata_filter_version: Literal["exact-metadata-v1"] = METADATA_FILTER_VERSION
    scope_rerank_version: Literal["scope-match-v1"] = SCOPE_RERANK_VERSION
    payload_schema_version: Literal["index-payload-v1"] = CORPUS_PAYLOAD_SCHEMA_VERSION
    rrf_k: Literal[60] = RRF_K
    retrieval_meaning: Literal["retrieval_candidates_not_eligibility_or_answers"] = (
        RETRIEVAL_CANDIDATES_ONLY
    )
    corpus_id: str
    request: CorpusSearchRequest
    selected_documents: tuple[SelectedCorpusDocument, ...] = Field(min_length=1)
    embedding_identity: CorpusEmbeddingIdentity
    semantic: bool = Field(strict=True)
    corpus_document_count: int = Field(ge=1, strict=True)
    corpus_row_count: int = Field(ge=0, strict=True)
    eligible_row_count: int = Field(ge=0, strict=True)
    vector_candidate_count: int = Field(ge=0, strict=True)
    lexical_candidate_count: int = Field(ge=0, strict=True)
    result_count: int = Field(ge=0, strict=True)
    candidate_k_resolved: int = Field(gt=0, strict=True)
    eligible_keys: tuple[CorpusEvidenceKey, ...]
    vector_candidates: tuple[CorpusChannelCandidate, ...]
    lexical_candidates: tuple[CorpusChannelCandidate, ...]
    per_document_counts: tuple[CorpusDocumentSearchCounts, ...]
    hits: tuple[CorpusSearchHit, ...]

    @model_validator(mode="after")
    def result_contract_must_recompute(self) -> CorpusSearchResult:
        selected = {item.entry.identity.document_id: item for item in self.selected_documents}
        selected_ids = tuple(selected)
        if selected_ids != tuple(sorted(selected)) or len(selected) != len(self.selected_documents):
            raise ValueError("selected documents must be canonical and unique")
        if self.corpus_document_count != len(selected):
            raise ValueError("corpus document count does not match selection")
        if self.semantic != (self.embedding_identity.provider != "deterministic-fake"):
            raise ValueError("semantic flag does not match provider identity")
        if self.candidate_k_resolved != resolve_candidate_depth(
            self.request.top_k, self.request.candidate_k
        ):
            raise ValueError("resolved candidate depth is invalid")

        eligible_keys = tuple(_key_tuple(key) for key in self.eligible_keys)
        if eligible_keys != tuple(sorted(set(eligible_keys))):
            raise ValueError("eligible keys must be canonical and unique")
        vector_by_key = _validate_candidates(self.vector_candidates, "vector")
        lexical_by_key = _validate_candidates(self.lexical_candidates, "lexical")
        if (
            len(vector_by_key) > self.candidate_k_resolved
            or len(lexical_by_key) > self.candidate_k_resolved
        ):
            raise ValueError("channel candidates exceed candidate depth")
        if not set(vector_by_key).issubset(eligible_keys) or not set(lexical_by_key).issubset(
            eligible_keys
        ):
            raise ValueError("channel candidates must be eligible")

        counts_by_document = {item.document_id: item for item in self.per_document_counts}
        if tuple(counts_by_document) != selected_ids or len(counts_by_document) != len(
            self.per_document_counts
        ):
            raise ValueError("per-document counts must cover selected documents canonically")
        expected_rows = {
            document_id: selected[document_id].entry.index_manifest.payload_count
            for document_id in selected_ids
            if selected[document_id].entry.index_manifest is not None
        }
        if len(expected_rows) != len(selected):
            raise ValueError("selected documents must contain index manifests")
        eligible_coordinates: set[tuple[str, int]] = set()
        for key in eligible_keys:
            document_id, row_index, _, _ = key
            coordinate = (document_id, row_index)
            if (
                document_id not in expected_rows
                or row_index >= expected_rows[document_id]
                or coordinate in eligible_coordinates
            ):
                raise ValueError("eligible keys are outside or duplicate selected rows")
            eligible_coordinates.add(coordinate)

        hit_keys: set[tuple[str, int, str, str]] = set()
        previous_order: tuple[float, str, int] | None = None
        for position, hit in enumerate(self.hits, start=1):
            key = _key_tuple(hit.key)
            if hit.rank != position or key in hit_keys:
                raise ValueError("result ranks and composite keys must be unique and contiguous")
            hit_keys.add(key)
            selected_document = selected.get(hit.key.document_id)
            if selected_document is None:
                raise ValueError("hit document is outside the selected corpus")
            if hit.version_classification != selected_document.version_classification:
                raise ValueError("hit version classification differs from selection")
            _validate_hit_binding(hit, selected_document.entry)
            if not _matches_filter(hit.payload, self.request.metadata_filter):
                raise ValueError("hit payload does not satisfy the requested metadata filter")
            vector = vector_by_key.get(key)
            lexical = lexical_by_key.get(key)
            if (hit.vector_rank, hit.vector_score) != _candidate_rank_score(vector) or (
                hit.lexical_rank,
                hit.lexical_score,
            ) != _candidate_rank_score(lexical):
                raise ValueError("hit channel fields differ from channel candidates")
            expected_fused = math.fsum(
                contribution
                for contribution in (
                    VECTOR_CHANNEL_WEIGHT / (RRF_K + vector.rank) if vector else None,
                    LEXICAL_CHANNEL_WEIGHT / (RRF_K + lexical.rank) if lexical else None,
                )
                if contribution is not None
            )
            targets = tuple(
                sorted(
                    set(hit.scope_targets).intersection(
                        self.request.scope_preference.preferred_scope_targets
                    )
                )
            )
            college = (
                hit.parent_college
                if hit.parent_college in self.request.scope_preference.preferred_parent_colleges
                else None
            )
            expected_preferences = tuple(
                name
                for name, matched in (("scope_target", bool(targets)), ("parent_college", college))
                if matched
            )
            expected_boost = math.fsum(
                (
                    SCOPE_TARGET_MATCH_BOOST if targets else 0.0,
                    PARENT_COLLEGE_MATCH_BOOST if college else 0.0,
                )
            )
            if (
                hit.fused_score != expected_fused
                or hit.matched_scope_targets != targets
                or hit.matched_parent_college != college
                or hit.matched_preferences != expected_preferences
                or hit.scope_boost_total != expected_boost
                or hit.ranking_score != math.fsum((expected_fused, expected_boost))
            ):
                raise ValueError("hit fusion or scope preference fields are invalid")
            order = (-hit.ranking_score, hit.key.document_id, hit.key.local_row_index)
            if previous_order is not None and order < previous_order:
                raise ValueError("hits are not in deterministic global order")
            previous_order = order

        if len(self.hits) > self.request.top_k:
            raise ValueError("result count exceeds top_k")
        candidate_union = set(vector_by_key).union(lexical_by_key)
        if len(self.hits) != min(self.request.top_k, len(candidate_union)):
            raise ValueError("final hits do not fill the available global result depth")
        expected_per_document = {}
        for document_id in selected_ids:
            expected_per_document[document_id] = (
                expected_rows[document_id],
                sum(key[0] == document_id for key in eligible_keys),
                sum(key[0] == document_id for key in vector_by_key),
                sum(key[0] == document_id for key in lexical_by_key),
                sum(key[0] == document_id for key in hit_keys),
            )
            observed = counts_by_document[document_id]
            if (
                observed.corpus_row_count,
                observed.eligible_row_count,
                observed.vector_candidate_count,
                observed.lexical_candidate_count,
                observed.result_count,
            ) != expected_per_document[document_id]:
                raise ValueError("per-document counts are invalid")
            if (
                observed.vector_candidate_count > observed.eligible_row_count
                or observed.lexical_candidate_count > observed.eligible_row_count
                or observed.result_count > sum(key[0] == document_id for key in candidate_union)
            ):
                raise ValueError("per-document counts exceed eligible or candidate rows")
        totals = (
            sum(value[0] for value in expected_per_document.values()),
            len(eligible_keys),
            len(vector_by_key),
            len(lexical_by_key),
            len(hit_keys),
        )
        observed_totals = (
            self.corpus_row_count,
            self.eligible_row_count,
            self.vector_candidate_count,
            self.lexical_candidate_count,
            self.result_count,
        )
        if observed_totals != totals:
            raise ValueError("global counts are invalid")
        per_document_totals = (
            sum(item.corpus_row_count for item in self.per_document_counts),
            sum(item.eligible_row_count for item in self.per_document_counts),
            sum(item.vector_candidate_count for item in self.per_document_counts),
            sum(item.lexical_candidate_count for item in self.per_document_counts),
            sum(item.result_count for item in self.per_document_counts),
        )
        if observed_totals != per_document_totals:
            raise ValueError("global and per-document counts do not reconcile")
        return self


@dataclass(frozen=True, slots=True)
class _PreparedRow:
    key: tuple[str, int, str, str]
    payload_bytes: bytes
    vector_bytes: bytes
    term_frequencies: tuple[tuple[str, int], ...]
    document_length: int


@dataclass(frozen=True, slots=True)
class CorpusDocumentFreshness:
    document_id: str
    report: IndexFreshnessReport


@dataclass(frozen=True, slots=True)
class CorpusSearchContext:
    corpus_id: str
    embedding_identity: EmbeddingIdentity
    semantic: bool
    freshness_reports: tuple[CorpusDocumentFreshness, ...]
    _selection_bytes: bytes
    _rows: tuple[_PreparedRow, ...]

    @property
    def selection_result(self) -> CorpusSelectionResult:
        return CorpusSelectionResult.model_validate_json(self._selection_bytes)

    @property
    def selected_documents(self) -> tuple[SelectedCorpusDocument, ...]:
        return self.selection_result.selected_documents

    @property
    def row_count(self) -> int:
        return len(self._rows)


def prepare_corpus_search_context(
    corpus_root: str | Path,
    manifest: CorpusManifest,
    policy: CorpusVersionPolicy,
    selection: CorpusSelectionResult,
) -> CorpusSearchContext:
    """Audit and freeze only the explicitly selected compatible ready indexes."""

    try:
        audited = audit_corpus_manifest(manifest, corpus_root)
        revalidated = revalidate_corpus_selection_result(selection, audited, policy)
        root = _validated_root(corpus_root)
        prepared: list[
            tuple[
                SelectedCorpusDocument,
                IndexManifest,
                tuple[IndexPayload, ...],
                Any,
                IndexFreshnessReport,
            ]
        ] = []
        common_contract: tuple[Any, ...] | None = None
        for selected in revalidated.selected_documents:
            entry = selected.entry
            if (
                entry.index_state != "ready"
                or entry.index_path is None
                or entry.index_manifest is None
            ):
                raise ValueError
            kb_path = _resolve_selected_path(root, entry.kb_path, directory=False)
            index_path = _resolve_selected_path(root, entry.index_path, directory=True)
            index = load_local_index(index_path, mmap=False)
            if index.manifest.model_dump(mode="json") != entry.index_manifest.model_dump(
                mode="json"
            ):
                raise ValueError
            identity = _embedding_identity(index.manifest)
            fresh = load_fresh_index_context(index, kb_path, identity)
            kb = fresh.knowledge_base
            if (
                kb.manifest.identity != entry.identity
                or fresh.freshness.current_kb_sha256 != entry.source_kb_sha256
                or tuple(payload.model_dump(mode="json") for payload in index.payloads)
                != tuple(payload.model_dump(mode="json") for payload in derive_index_payloads(kb))
            ):
                raise ValueError
            if any(
                payload.metadata.get("embedding_text_version") != EMBEDDING_TEXT_VERSION
                for payload in index.payloads
            ):
                raise ValueError
            contract = _index_contract(index.manifest)
            if common_contract is None:
                common_contract = contract
            elif contract != common_contract:
                raise ValueError
            prepared.append(
                (selected, index.manifest, index.payloads, index.vectors, fresh.freshness)
            )
        if common_contract is None:
            raise ValueError

        rows: list[_PreparedRow] = []
        for selected, manifest_snapshot, payloads, vectors, _ in prepared:
            if selected.entry.identity.document_id != manifest_snapshot.document_id:
                raise ValueError
            for payload, vector in zip(payloads, vectors, strict=True):
                projection = build_lexical_projection(payload)
                frequencies = Counter(tokenize_lexical(projection))
                rows.append(
                    _PreparedRow(
                        key=(
                            payload.document_id,
                            payload.row_index,
                            payload.unit_id,
                            payload.fact_id,
                        ),
                        payload_bytes=json.dumps(
                            payload.model_dump(mode="json"),
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode("utf-8"),
                        vector_bytes=np.asarray(vector, dtype=np.dtype("<f4")).tobytes(),
                        term_frequencies=tuple(sorted(frequencies.items())),
                        document_length=sum(frequencies.values()),
                    )
                )
        rows.sort(key=lambda row: row.key)
        _validate_prepared_rows(rows, common_contract[3])
        identity = _embedding_identity(prepared[0][1])
        return CorpusSearchContext(
            corpus_id=revalidated.corpus_id,
            embedding_identity=identity,
            semantic=identity.provider != "deterministic-fake",
            freshness_reports=tuple(
                CorpusDocumentFreshness(
                    document_id=selected.entry.identity.document_id,
                    report=freshness,
                )
                for selected, _, _, _, freshness in prepared
            ),
            _selection_bytes=canonical_corpus_selection_result_bytes(revalidated),
            _rows=tuple(rows),
        )
    except (CorpusAuditError, CorpusSelectionError, IndexLoadError, IndexFreshnessError):
        raise CorpusSearchPreparationError("corpus search context preparation failed") from None
    except (OSError, TypeError, ValidationError, ValueError):
        raise CorpusSearchPreparationError("corpus search context preparation failed") from None


def search_corpus(
    context: CorpusSearchContext,
    query: str,
    provider: EmbeddingProvider,
    *,
    top_k: int = 5,
    candidate_k: int | None = None,
    metadata_filter: MetadataFilter | None = None,
    scope_preference: ScopePreference | None = None,
) -> CorpusSearchResult:
    """Run one deterministic global hybrid search over a prepared corpus context."""

    request = _build_request(query, top_k, candidate_k, metadata_filter, scope_preference)
    try:
        _validate_context(context)
        if provider.identity != context.embedding_identity:
            raise CorpusSearchProviderError("query provider is incompatible with corpus context")
    except CorpusSearchProviderError:
        raise
    except Exception:
        raise CorpusSearchProviderError(
            "query provider is incompatible with corpus context"
        ) from None
    try:
        query_vector = _normalize_query(
            embed_query_checked(provider, request.query), context.embedding_identity.dimension
        )
    except Exception:
        raise CorpusSearchProviderError("corpus query embedding failed") from None

    payloads = tuple(IndexPayload.model_validate_json(row.payload_bytes) for row in context._rows)
    eligible_positions = tuple(
        position
        for position, payload in enumerate(payloads)
        if _matches_filter(payload, request.metadata_filter)
    )
    eligible_keys = tuple(
        _key_model(context._rows[position].key) for position in eligible_positions
    )
    resolved_candidate_k = resolve_candidate_depth(request.top_k, request.candidate_k)

    vector_scored: list[tuple[float, tuple[str, int, str, str]]] = []
    for position in eligible_positions:
        vector = np.frombuffer(
            context._rows[position].vector_bytes,
            dtype=np.dtype("<f4"),
            count=context.embedding_identity.dimension,
        )
        score = float(np.dot(vector, query_vector))
        if not math.isfinite(score):
            raise CorpusSearchError("corpus vector scoring failed")
        vector_scored.append((score, context._rows[position].key))
    vector_scored.sort(key=lambda item: (-item[0], item[1][0], item[1][1]))
    vector_candidates = tuple(
        CorpusChannelCandidate(rank=rank, key=_key_model(key), score=score)
        for rank, (score, key) in enumerate(vector_scored[:resolved_candidate_k], start=1)
    )

    lexical_candidates = _global_lexical_candidates(
        context, request.query, eligible_positions, resolved_candidate_k
    )
    result = _fuse_result(
        context,
        request,
        resolved_candidate_k,
        payloads,
        eligible_keys,
        vector_candidates,
        lexical_candidates,
    )
    return CorpusSearchResult.model_validate_json(canonical_corpus_search_result_bytes(result))


def revalidate_corpus_search_result(
    result: CorpusSearchResult,
    context: CorpusSearchContext,
    provider: EmbeddingProvider,
) -> CorpusSearchResult:
    """Re-execute a saved request against a prepared context and require exact equality."""

    try:
        if not isinstance(result, CorpusSearchResult):
            raise TypeError
        detached = CorpusSearchResult.model_validate(result.model_dump(mode="json"))
        request = detached.request
        expected = search_corpus(
            context,
            request.query,
            provider,
            top_k=request.top_k,
            candidate_k=request.candidate_k,
            metadata_filter=MetadataFilter(**request.metadata_filter.model_dump()),
            scope_preference=ScopePreference(**request.scope_preference.model_dump()),
        )
        if canonical_corpus_search_result_bytes(detached) != canonical_corpus_search_result_bytes(
            expected
        ):
            raise ValueError
        return detached
    except Exception:
        raise CorpusSearchResultCompatibilityError(
            "corpus search result does not match the prepared context and request"
        ) from None


def canonical_corpus_search_result_bytes(result: CorpusSearchResult) -> bytes:
    try:
        if not isinstance(result, CorpusSearchResult):
            raise TypeError
        validated = CorpusSearchResult.model_validate(result.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return f"{serialized}\n".encode("utf-8")
    except (TypeError, ValidationError, ValueError):
        raise CorpusSearchSchemaError("corpus search result is invalid or unsupported") from None


def load_corpus_search_result_bytes(raw_bytes: bytes) -> CorpusSearchResult:
    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
            raise ValueError
        return CorpusSearchResult.model_validate(payload)
    except (UnicodeError, json.JSONDecodeError, TypeError, ValidationError, ValueError):
        raise CorpusSearchSchemaError(
            "corpus search result bytes are invalid or unsupported"
        ) from None


def load_corpus_search_result(path_value: str | Path) -> CorpusSearchResult:
    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError
        raw_bytes = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise CorpusSearchSchemaError(
            "corpus search result file is unavailable or unsafe"
        ) from None
    return load_corpus_search_result_bytes(raw_bytes)


def _build_request(query, top_k, candidate_k, metadata_filter, scope_preference):
    try:
        selected_filter = MetadataFilter() if metadata_filter is None else metadata_filter
        selected_preference = ScopePreference() if scope_preference is None else scope_preference
        if not isinstance(selected_filter, MetadataFilter) or not isinstance(
            selected_preference, ScopePreference
        ):
            raise TypeError
        return CorpusSearchRequest(
            query=query,
            top_k=top_k,
            candidate_k=candidate_k,
            metadata_filter=CorpusMetadataFilter(**selected_filter.to_dict()),
            scope_preference=CorpusScopePreference(**selected_preference.to_dict()),
        )
    except (TypeError, ValidationError, ValueError):
        raise CorpusSearchInputError("corpus search request is invalid") from None


def _global_lexical_candidates(context, query, eligible_positions, candidate_k):
    query_tokens = tokenize_lexical(query)
    query_frequencies = Counter(query_tokens)
    corpus_size = len(eligible_positions)
    if corpus_size == 0:
        return ()
    document_frequency: Counter[str] = Counter()
    lengths = [context._rows[position].document_length for position in eligible_positions]
    for position in eligible_positions:
        document_frequency.update(term for term, _ in context._rows[position].term_frequencies)
    average_length = math.fsum(lengths) / corpus_size
    scored = []
    ordered_terms = tuple(dict.fromkeys(query_tokens))
    for position in eligible_positions:
        row = context._rows[position]
        frequencies = dict(row.term_frequencies)
        contributions = []
        for term, query_frequency in query_frequencies.items():
            frequency = frequencies.get(term, 0)
            if frequency:
                contributions.append(
                    query_frequency
                    * _bm25_term_score(
                        frequency,
                        document_frequency[term],
                        row.document_length,
                        average_length,
                        corpus_size,
                    )
                )
        score = math.fsum(contributions)
        if not math.isfinite(score):
            raise CorpusSearchError("corpus lexical scoring failed")
        if score > 0:
            scored.append(
                (score, row.key, tuple(term for term in ordered_terms if frequencies.get(term, 0)))
            )
    scored.sort(key=lambda item: (-item[0], item[1][0], item[1][1]))
    return tuple(
        CorpusChannelCandidate(rank=rank, key=_key_model(key), score=score, matched_terms=terms)
        for rank, (score, key, terms) in enumerate(scored[:candidate_k], start=1)
    )


def _fuse_result(context, request, candidate_k, payloads, eligible, vectors, lexicals):
    vector_by_key = {_key_tuple(item.key): item for item in vectors}
    lexical_by_key = {_key_tuple(item.key): item for item in lexicals}
    payload_by_key = {
        row.key: payload for row, payload in zip(context._rows, payloads, strict=True)
    }
    selected_by_id = {item.entry.identity.document_id: item for item in context.selected_documents}
    fused = []
    for key in set(vector_by_key).union(lexical_by_key):
        vector = vector_by_key.get(key)
        lexical = lexical_by_key.get(key)
        fused_score = math.fsum(
            value
            for value in (
                VECTOR_CHANNEL_WEIGHT / (RRF_K + vector.rank) if vector else None,
                LEXICAL_CHANNEL_WEIGHT / (RRF_K + lexical.rank) if lexical else None,
            )
            if value is not None
        )
        payload = payload_by_key[key]
        targets = tuple(
            sorted(
                set(payload.scope_targets).intersection(
                    request.scope_preference.preferred_scope_targets
                )
            )
        )
        college = (
            payload.parent_college
            if payload.parent_college in request.scope_preference.preferred_parent_colleges
            else None
        )
        boost = math.fsum(
            (
                SCOPE_TARGET_MATCH_BOOST if targets else 0.0,
                PARENT_COLLEGE_MATCH_BOOST if college else 0.0,
            )
        )
        fused.append((math.fsum((fused_score, boost)), key, fused_score, boost, targets, college))
    fused.sort(key=lambda item: (-item[0], item[1][0], item[1][1]))

    hits = []
    for rank, (ranking, key, fused_score, boost, targets, college) in enumerate(
        fused[: request.top_k], start=1
    ):
        payload = payload_by_key[key]
        selected = selected_by_id[key[0]]
        vector = vector_by_key.get(key)
        lexical = lexical_by_key.get(key)
        entry = selected.entry
        hits.append(
            CorpusSearchHit(
                rank=rank,
                key=_key_model(key),
                version_classification=selected.version_classification,
                identity=entry.identity.model_copy(deep=True),
                payload=payload.model_copy(deep=True),
                kb_path=entry.kb_path,
                source_kb_sha256=entry.source_kb_sha256,
                index_path=entry.index_path,
                index_manifest=entry.index_manifest.model_copy(deep=True),
                ranking_score=ranking,
                fused_score=fused_score,
                scope_boost_total=boost,
                matched_preferences=tuple(
                    name
                    for name, matched in (
                        ("scope_target", bool(targets)),
                        ("parent_college", college),
                    )
                    if matched
                ),
                matched_scope_targets=targets,
                matched_parent_college=college,
                vector_rank=vector.rank if vector else None,
                vector_score=vector.score if vector else None,
                lexical_rank=lexical.rank if lexical else None,
                lexical_score=lexical.score if lexical else None,
                matched_channels=tuple(
                    channel
                    for channel, item in (("vector", vector), ("lexical", lexical))
                    if item is not None
                ),
                text=payload.text,
                source_pages=tuple(payload.source_pages),
                section_path=tuple(payload.section_path),
                fact_type=payload.fact_type,
                scope_type=payload.scope_type,
                scope_targets=tuple(payload.scope_targets),
                parent_college=payload.parent_college,
                metadata=json.loads(
                    json.dumps(payload.metadata, ensure_ascii=False, allow_nan=False)
                ),
            )
        )
    hit_keys = {_key_tuple(hit.key) for hit in hits}
    eligible_tuples = {_key_tuple(key) for key in eligible}
    per_document = tuple(
        CorpusDocumentSearchCounts(
            document_id=document_id,
            corpus_row_count=selected.entry.index_manifest.payload_count,
            eligible_row_count=sum(key[0] == document_id for key in eligible_tuples),
            vector_candidate_count=sum(key[0] == document_id for key in vector_by_key),
            lexical_candidate_count=sum(key[0] == document_id for key in lexical_by_key),
            result_count=sum(key[0] == document_id for key in hit_keys),
        )
        for document_id, selected in selected_by_id.items()
    )
    identity = context.embedding_identity
    return CorpusSearchResult(
        corpus_id=context.corpus_id,
        request=request,
        selected_documents=context.selected_documents,
        embedding_identity=CorpusEmbeddingIdentity(
            provider=identity.provider,
            model=identity.model,
            revision=identity.revision,
            dimension=identity.dimension,
        ),
        semantic=context.semantic,
        corpus_document_count=len(selected_by_id),
        corpus_row_count=len(context._rows),
        eligible_row_count=len(eligible),
        vector_candidate_count=len(vectors),
        lexical_candidate_count=len(lexicals),
        result_count=len(hits),
        candidate_k_resolved=candidate_k,
        eligible_keys=eligible,
        vector_candidates=vectors,
        lexical_candidates=lexicals,
        per_document_counts=per_document,
        hits=tuple(hits),
    )


def _validate_candidates(candidates, channel):
    by_key = {}
    previous = None
    for position, candidate in enumerate(candidates, start=1):
        key = _key_tuple(candidate.key)
        if candidate.rank != position or key in by_key:
            raise ValueError("channel candidate ranks and keys must be unique and contiguous")
        if channel == "vector" and candidate.matched_terms:
            raise ValueError("vector candidates cannot contain lexical terms")
        if channel == "lexical" and (candidate.score <= 0 or not candidate.matched_terms):
            raise ValueError("lexical candidates require positive scores and matched terms")
        order = (-candidate.score, key[0], key[1])
        if previous is not None and order < previous:
            raise ValueError("channel candidates are not globally ordered")
        previous = order
        by_key[key] = candidate
    return by_key


def _validate_hit_binding(hit, entry):
    payload = hit.payload
    if (
        hit.identity != entry.identity
        or hit.key.document_id != entry.identity.document_id
        or hit.kb_path != entry.kb_path
        or hit.source_kb_sha256 != entry.source_kb_sha256
        or hit.index_path != entry.index_path
        or hit.index_manifest.model_dump(mode="json")
        != entry.index_manifest.model_dump(mode="json")
        or hit.key.local_row_index >= entry.index_manifest.payload_count
        or _key_tuple(hit.key)
        != (payload.document_id, payload.row_index, payload.unit_id, payload.fact_id)
        or (
            hit.text,
            hit.source_pages,
            hit.section_path,
            hit.fact_type,
            hit.scope_type,
            hit.scope_targets,
            hit.parent_college,
            hit.metadata,
        )
        != (
            payload.text,
            tuple(payload.source_pages),
            tuple(payload.section_path),
            payload.fact_type,
            payload.scope_type,
            tuple(payload.scope_targets),
            payload.parent_college,
            payload.metadata,
        )
    ):
        raise ValueError("hit provenance does not match selected document")


def _candidate_rank_score(candidate):
    return (None, None) if candidate is None else (candidate.rank, candidate.score)


def _matches_filter(payload, metadata_filter):
    return (
        (not metadata_filter.fact_types or payload.fact_type in metadata_filter.fact_types)
        and (not metadata_filter.scope_types or payload.scope_type in metadata_filter.scope_types)
        and (
            not metadata_filter.scope_targets
            or set(payload.scope_targets).intersection(metadata_filter.scope_targets)
        )
        and (
            not metadata_filter.parent_colleges
            or payload.parent_college in metadata_filter.parent_colleges
        )
    )


def _bm25_term_score(term_frequency, document_frequency, document_length, average_length, size):
    if average_length <= 0:
        raise CorpusSearchError("corpus lexical statistics are invalid")
    idf = math.log1p((size - document_frequency + 0.5) / (document_frequency + 0.5))
    normalization = 1.0 - BM25_B + BM25_B * (document_length / average_length)
    score = idf * (term_frequency * (BM25_K1 + 1.0)) / (term_frequency + BM25_K1 * normalization)
    if not math.isfinite(score) or score <= 0:
        raise CorpusSearchError("corpus lexical statistics are invalid")
    return score


def _normalize_query(values, dimension):
    vector = np.asarray(values, dtype=np.dtype("<f4"), order="C")
    if vector.shape != (dimension,) or not np.isfinite(vector).all():
        raise ValueError
    vector64 = vector.astype(np.float64)
    norm = math.sqrt(float(np.sum(vector64 * vector64, dtype=np.float64)))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError
    normalized = np.asarray(vector64 / norm, dtype=np.dtype("<f4"), order="C")
    stored_norm = math.sqrt(float(np.sum(normalized.astype(np.float64) ** 2)))
    if not math.isclose(stored_norm, 1.0, rel_tol=0, abs_tol=NORM_ABSOLUTE_TOLERANCE):
        raise ValueError
    normalized.setflags(write=False)
    return normalized


def _embedding_identity(manifest):
    return EmbeddingIdentity(
        provider=manifest.embedding_provider,
        model=manifest.embedding_model,
        revision=manifest.embedding_revision,
        dimension=manifest.embedding_dimension,
    )


def _index_contract(manifest):
    if manifest.distance_metric != "cosine" or not manifest.vectors_normalized:
        raise ValueError
    return (
        manifest.index_schema_version,
        manifest.source_kb_schema_version,
        manifest.embedding_provider,
        manifest.embedding_dimension,
        manifest.embedding_model,
        manifest.embedding_revision,
        manifest.vector_dtype,
        manifest.distance_metric,
        manifest.vectors_normalized,
        EMBEDDING_TEXT_VERSION,
        CORPUS_PAYLOAD_SCHEMA_VERSION,
    )


def _validate_prepared_rows(rows, dimension):
    keys = tuple(row.key for row in rows)
    if keys != tuple(sorted(set(keys))):
        raise ValueError
    for row in rows:
        if len(row.vector_bytes) != dimension * np.dtype("<f4").itemsize:
            raise ValueError
        payload = IndexPayload.model_validate_json(row.payload_bytes)
        if row.key != (payload.document_id, payload.row_index, payload.unit_id, payload.fact_id):
            raise ValueError


def _validate_context(context):
    if not isinstance(context, CorpusSearchContext):
        raise TypeError
    selection = context.selection_result
    if selection.corpus_id != context.corpus_id:
        raise ValueError
    if tuple(item.document_id for item in context.freshness_reports) != tuple(
        selected.entry.identity.document_id for selected in selection.selected_documents
    ):
        raise ValueError
    _validate_prepared_rows(list(context._rows), context.embedding_identity.dimension)
    if context.semantic != (context.embedding_identity.provider != "deterministic-fake"):
        raise ValueError


def _validated_root(value):
    root = Path(value)
    if not root.is_absolute() or any(path.is_symlink() for path in _path_components(root)):
        raise ValueError
    return root.resolve(strict=True)


def _resolve_selected_path(root, relative, *, directory):
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError
    resolved = current.resolve(strict=True)
    if (
        not resolved.is_relative_to(root)
        or (directory and not resolved.is_dir())
        or (not directory and not resolved.is_file())
    ):
        raise ValueError
    return resolved


def _path_components(path):
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        yield current


def _key_model(key):
    return CorpusEvidenceKey(
        document_id=key[0], local_row_index=key[1], unit_id=key[2], fact_id=key[3]
    )


def _key_tuple(key):
    return (key.document_id, key.local_row_index, key.unit_id, key.fact_id)


def _reject_constant(_):
    raise ValueError


__all__ = [
    "CORPUS_SEARCH_RANKING_VERSION",
    "CORPUS_SEARCH_SCHEMA_VERSION",
    "CorpusChannelCandidate",
    "CorpusDocumentSearchCounts",
    "CorpusDocumentFreshness",
    "CorpusEmbeddingIdentity",
    "CorpusEvidenceKey",
    "CorpusMetadataFilter",
    "CorpusScopePreference",
    "CorpusSearchContext",
    "CorpusSearchError",
    "CorpusSearchHit",
    "CorpusSearchInputError",
    "CorpusSearchPreparationError",
    "CorpusSearchProviderError",
    "CorpusSearchRequest",
    "CorpusSearchResult",
    "CorpusSearchResultCompatibilityError",
    "CorpusSearchSchemaError",
    "canonical_corpus_search_result_bytes",
    "load_corpus_search_result",
    "load_corpus_search_result_bytes",
    "prepare_corpus_search_context",
    "revalidate_corpus_search_result",
    "search_corpus",
]
