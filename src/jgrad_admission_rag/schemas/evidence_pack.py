from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .document_kb import ScopeType

EVIDENCE_PACK_SCHEMA_VERSION = "1.0"
SUPPORTED_EVIDENCE_PACK_SCHEMA_VERSIONS = frozenset({EVIDENCE_PACK_SCHEMA_VERSION})


class EvidencePackError(Exception):
    """Raised when an EvidencePack cannot be built, serialized, or loaded safely."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceMetadataFilter(StrictModel):
    fact_types: tuple[str, ...] = ()
    scope_types: tuple[ScopeType, ...] = ()
    scope_targets: tuple[str, ...] = ()
    parent_colleges: tuple[str, ...] = ()

    @field_validator("fact_types", "scope_types", "scope_targets", "parent_colleges")
    @classmethod
    def values_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_canonical_strings(values, "filter values")
        return values


class EvidenceScopePreference(StrictModel):
    preferred_scope_targets: tuple[str, ...] = ()
    preferred_parent_colleges: tuple[str, ...] = ()

    @field_validator("preferred_scope_targets", "preferred_parent_colleges")
    @classmethod
    def values_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_canonical_strings(values, "preference values")
        return values


class EvidenceRequest(StrictModel):
    query: str
    retrieval_mode: Literal["hybrid"] = "hybrid"
    top_k_requested: int = Field(gt=0)
    candidate_k_requested: int | None = Field(default=None, gt=0)
    candidate_k_resolved: int = Field(gt=0)
    metadata_filter: EvidenceMetadataFilter = Field(default_factory=EvidenceMetadataFilter)
    scope_preference: EvidenceScopePreference = Field(default_factory=EvidenceScopePreference)

    @field_validator("query")
    @classmethod
    def query_must_be_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must be non-blank")
        return value

    @model_validator(mode="after")
    def candidate_depth_must_cover_top_k(self) -> EvidenceRequest:
        if self.candidate_k_resolved < self.top_k_requested:
            raise ValueError("candidate_k_resolved must be at least top_k_requested")
        if (
            self.candidate_k_requested is not None
            and self.candidate_k_requested != self.candidate_k_resolved
        ):
            raise ValueError("requested and resolved candidate depths do not reconcile")
        return self


class EvidenceRuntime(StrictModel):
    document_id: str
    source_kb_sha256: str
    source_pdf_sha256: str
    index_schema_version: Literal["0.1"]
    source_kb_schema_version: Literal["0.5"]
    payloads_sha256: str
    vectors_sha256: str
    index_builder_version: Literal["0.1.0"]
    embedding_provider: str
    embedding_model: str
    embedding_revision: str | None = None
    embedding_dimension: int = Field(ge=0)
    distance_metric: Literal["cosine"]
    semantic: bool
    lexical_tokenizer_version: Literal["nfkc-casefold-ja23-v1"]
    lexical_scoring_version: Literal["bm25-v1"]
    fusion_version: Literal["rrf-v1"]
    rrf_k: Literal[60]
    metadata_filter_version: Literal["exact-metadata-v1"]
    scope_rerank_version: Literal["scope-match-v1"]
    scope_target_match_boost: float
    parent_college_match_boost: float
    reference_expansion_version: Literal["reference-one-hop-v1"]
    reference_expansion_depth: Literal[1]
    corpus_row_count: int = Field(ge=0)
    eligible_row_count: int = Field(ge=0)
    vector_candidate_count: int = Field(ge=0)
    lexical_candidate_count: int = Field(ge=0)

    @field_validator(
        "document_id",
        "embedding_provider",
        "embedding_model",
    )
    @classmethod
    def identifiers_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value, "runtime identifier")
        return value

    @field_validator("embedding_revision")
    @classmethod
    def revision_must_be_trimmed(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_trimmed(value, "embedding revision")
        return value

    @field_validator("source_kb_sha256", "source_pdf_sha256", "payloads_sha256", "vectors_sha256")
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value

    @field_validator("scope_target_match_boost", "parent_college_match_boost")
    @classmethod
    def boosts_must_be_finite_non_negative(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("boosts must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def counts_and_provider_must_reconcile(self) -> EvidenceRuntime:
        if self.eligible_row_count > self.corpus_row_count:
            raise ValueError("eligible_row_count exceeds corpus_row_count")
        if self.vector_candidate_count > self.eligible_row_count:
            raise ValueError("vector_candidate_count exceeds eligible_row_count")
        if self.lexical_candidate_count > self.eligible_row_count:
            raise ValueError("lexical_candidate_count exceeds eligible_row_count")
        if self.corpus_row_count > 0 and self.embedding_dimension <= 0:
            raise ValueError("embedding_dimension must be positive for a non-empty corpus")
        if self.semantic != (self.embedding_provider != "deterministic-fake"):
            raise ValueError("semantic flag does not match embedding provider")
        return self


class EvidenceRecord(StrictModel):
    row_index: int = Field(ge=0)
    document_id: str
    unit_id: str
    fact_id: str
    text: str
    source_pages: tuple[int, ...]
    section_path: tuple[str, ...]
    fact_type: str
    scope_type: ScopeType
    scope_targets: tuple[str, ...] = ()
    parent_college: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("document_id", "unit_id", "fact_id", "fact_type")
    @classmethod
    def identifiers_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value, "evidence identifier")
        return value

    @field_validator("text")
    @classmethod
    def text_must_be_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("evidence text must be non-empty")
        return value

    @field_validator("source_pages")
    @classmethod
    def pages_must_be_positive_sorted_unique(cls, pages: tuple[int, ...]) -> tuple[int, ...]:
        if not pages or any(page <= 0 for page in pages) or tuple(sorted(set(pages))) != pages:
            raise ValueError("source_pages must be non-empty, positive, sorted, and unique")
        return pages

    @field_validator("section_path")
    @classmethod
    def section_path_must_be_non_empty(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values:
            raise ValueError("section_path must be non-empty")
        _validate_trimmed_strings(values, "section_path")
        return values

    @field_validator("scope_targets")
    @classmethod
    def scope_targets_must_be_exact_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_trimmed_strings(values, "scope_targets")
        return values

    @field_validator("parent_college")
    @classmethod
    def parent_college_must_be_trimmed(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_trimmed(value, "parent_college")
        return value

    @field_validator("metadata")
    @classmethod
    def metadata_must_be_finite_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_json_value(value)
        return value


class PrimaryEvidence(EvidenceRecord):
    role: Literal["primary"] = "primary"
    primary_rank: int = Field(gt=0)
    ranking_score: float
    fused_score: float
    scope_boost_total: float
    matched_preferences: tuple[Literal["scope_target", "parent_college"], ...] = ()
    matched_scope_targets: tuple[str, ...] = ()
    matched_parent_college: str | None = None
    fusion_version: Literal["rrf-v1"]
    vector_rank: int | None = Field(default=None, gt=0)
    vector_score: float | None = None
    lexical_rank: int | None = Field(default=None, gt=0)
    lexical_score: float | None = None
    matched_channels: tuple[Literal["vector", "lexical"], ...]

    @field_validator("ranking_score", "fused_score", "scope_boost_total")
    @classmethod
    def scores_must_be_finite(cls, value: float) -> float:
        _validate_finite(value, "ranking score")
        return value

    @field_validator("vector_score", "lexical_score")
    @classmethod
    def optional_scores_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None:
            _validate_finite(value, "channel score")
        return value

    @model_validator(mode="after")
    def channel_and_preference_provenance_must_reconcile(self) -> PrimaryEvidence:
        vector_present = self.vector_rank is not None and self.vector_score is not None
        lexical_present = self.lexical_rank is not None and self.lexical_score is not None
        if (self.vector_rank is None) != (self.vector_score is None):
            raise ValueError("vector rank and score must be paired")
        if (self.lexical_rank is None) != (self.lexical_score is None):
            raise ValueError("lexical rank and score must be paired")
        expected_channels = tuple(
            channel
            for channel, present in (("vector", vector_present), ("lexical", lexical_present))
            if present
        )
        if self.matched_channels != expected_channels or not self.matched_channels:
            raise ValueError("matched_channels do not reconcile with channel ranks and scores")
        expected_preferences = tuple(
            preference
            for preference, present in (
                ("scope_target", bool(self.matched_scope_targets)),
                ("parent_college", self.matched_parent_college is not None),
            )
            if present
        )
        if self.matched_preferences != expected_preferences:
            raise ValueError("matched_preferences do not reconcile with matched values")
        if self.scope_boost_total < 0:
            raise ValueError("scope_boost_total must be non-negative")
        return self


class IncomingRelation(StrictModel):
    source_primary_rank: int = Field(gt=0)
    source_fact_id: str
    label: str
    reference_key: str
    direction: str

    @field_validator("source_fact_id", "label", "reference_key", "direction")
    @classmethod
    def values_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value, "incoming relation value")
        return value


class AttachedReferenceEvidence(EvidenceRecord):
    role: Literal["reference_target"] = "reference_target"
    incoming_relations: tuple[IncomingRelation, ...]

    @field_validator("incoming_relations")
    @classmethod
    def incoming_must_be_non_empty(cls, values: tuple[IncomingRelation, ...]):
        if not values:
            raise ValueError("attached evidence requires at least one incoming relation")
        if len(values) != len(set(values)):
            raise ValueError("incoming relations must be unique")
        return values


class ResolvedReferenceRelation(StrictModel):
    source_primary_rank: int = Field(gt=0)
    source_claim_index: int = Field(ge=0)
    source_fact_id: str
    label: str
    reference_key: str
    direction: str
    status: Literal["resolved"] = "resolved"
    selected_target_fact_id: str
    candidate_target_fact_ids: tuple[str, ...]
    top_score: float | None = None
    score_margin: float | None = None
    reason: str
    disposition: Literal["attached_target", "already_primary"]
    target_row_index: int = Field(ge=0)
    target_primary_rank: int | None = Field(default=None, gt=0)

    @field_validator(
        "source_fact_id",
        "label",
        "reference_key",
        "direction",
        "selected_target_fact_id",
        "reason",
    )
    @classmethod
    def values_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value, "resolved relation value")
        return value

    @field_validator("candidate_target_fact_ids")
    @classmethod
    def candidates_must_be_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_trimmed_strings(values, "candidate_target_fact_ids")
        if len(values) != len(set(values)):
            raise ValueError("candidate target Fact IDs must be unique")
        return values

    @field_validator("top_score", "score_margin")
    @classmethod
    def optional_scores_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None:
            _validate_finite(value, "reference score")
        return value

    @model_validator(mode="after")
    def selected_target_and_location_must_reconcile(self) -> ResolvedReferenceRelation:
        if self.selected_target_fact_id not in self.candidate_target_fact_ids:
            raise ValueError("selected target must be one of the candidate targets")
        if self.disposition == "attached_target" and self.target_primary_rank is not None:
            raise ValueError("attached target cannot have a primary rank")
        if self.disposition == "already_primary" and self.target_primary_rank is None:
            raise ValueError("already-primary target requires its primary rank")
        return self


class ReferenceWarning(StrictModel):
    warning_type: Literal["reference_uncertainty"] = "reference_uncertainty"
    source_primary_rank: int = Field(gt=0)
    source_claim_index: int = Field(ge=0)
    source_fact_id: str
    label: str
    reference_key: str
    direction: str
    status: Literal["ambiguous", "unresolved"]
    candidate_target_fact_ids: tuple[str, ...] = ()
    top_score: float | None = None
    score_margin: float | None = None
    reason: str

    @field_validator("source_fact_id", "label", "reference_key", "direction", "reason")
    @classmethod
    def values_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value, "reference warning value")
        return value

    @field_validator("candidate_target_fact_ids")
    @classmethod
    def candidates_must_be_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_trimmed_strings(values, "candidate_target_fact_ids")
        if len(values) != len(set(values)):
            raise ValueError("candidate target Fact IDs must be unique")
        return values

    @field_validator("top_score", "score_margin")
    @classmethod
    def optional_scores_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None:
            _validate_finite(value, "warning score")
        return value


class EvidenceCounts(StrictModel):
    primary_evidence_count: int = Field(ge=0)
    attached_evidence_count: int = Field(ge=0)
    resolved_relation_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    warning_status_counts: dict[Literal["ambiguous", "unresolved"], int]
    unique_evidence_count: int = Field(ge=0)

    @field_validator("warning_status_counts")
    @classmethod
    def warning_counts_must_have_exact_keys(cls, value: dict[str, int]) -> dict[str, int]:
        if set(value) != {"ambiguous", "unresolved"} or any(count < 0 for count in value.values()):
            raise ValueError("warning_status_counts must contain non-negative exact status keys")
        return value


class EvidencePack(StrictModel):
    schema_version: Literal["1.0"] = EVIDENCE_PACK_SCHEMA_VERSION
    request: EvidenceRequest
    runtime: EvidenceRuntime
    primary_evidence: tuple[PrimaryEvidence, ...]
    attached_reference_evidence: tuple[AttachedReferenceEvidence, ...]
    resolved_relations: tuple[ResolvedReferenceRelation, ...]
    reference_warnings: tuple[ReferenceWarning, ...]
    counts: EvidenceCounts

    @model_validator(mode="after")
    def all_collections_must_reconcile(self) -> EvidencePack:
        _validate_pack_collections(self)
        return self


def canonical_evidence_pack_bytes(pack: EvidencePack) -> bytes:
    if not isinstance(pack, EvidencePack):
        raise EvidencePackError("value must be an EvidencePack")
    try:
        validated = EvidencePack.model_validate(pack.model_dump(mode="json"))
        text = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, ValidationError) as error:
        raise EvidencePackError("EvidencePack cannot be serialized canonically") from error
    return (text + "\n").encode("utf-8")


def load_evidence_pack_bytes(raw_bytes: bytes) -> EvidencePack:
    if not isinstance(raw_bytes, bytes):
        raise EvidencePackError("EvidencePack input must be bytes")
    try:
        value = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("top level is not an object")
        version = value.get("schema_version")
        if version not in SUPPORTED_EVIDENCE_PACK_SCHEMA_VERSIONS:
            raise ValueError("unsupported schema version")
        return EvidencePack.model_validate(value)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        ValidationError,
    ) as error:
        raise EvidencePackError("EvidencePack bytes are invalid or unsupported") from error


def load_evidence_pack(path_value: str | Path) -> EvidencePack:
    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        raise EvidencePackError("EvidencePack path is missing or unsafe")
    try:
        raw_bytes = path.read_bytes()
    except OSError as error:
        raise EvidencePackError("EvidencePack path could not be read") from error
    return load_evidence_pack_bytes(raw_bytes)


def _validate_pack_collections(pack: EvidencePack) -> None:
    primaries = pack.primary_evidence
    attached = pack.attached_reference_evidence
    if tuple(item.primary_rank for item in primaries) != tuple(range(1, len(primaries) + 1)):
        raise ValueError("primary evidence ranks must be contiguous and ordered")
    if len(primaries) > pack.request.top_k_requested:
        raise ValueError("primary evidence exceeds requested top_k")
    if len(primaries) > pack.runtime.eligible_row_count:
        raise ValueError("primary evidence exceeds eligible corpus")
    all_evidence = (*primaries, *attached)
    if any(item.document_id != pack.runtime.document_id for item in all_evidence):
        raise ValueError("evidence document identity does not match runtime")
    if any(item.row_index >= pack.runtime.corpus_row_count for item in all_evidence):
        raise ValueError("evidence row is outside the runtime corpus")
    for field in ("fact_id", "unit_id", "row_index"):
        values = [getattr(item, field) for item in all_evidence]
        if len(values) != len(set(values)):
            raise ValueError(f"evidence {field} values must be unique")

    primary_by_fact = {item.fact_id: item for item in primaries}
    attached_by_fact = {item.fact_id: item for item in attached}
    relation_identities: set[tuple[int, str, str, str, str]] = set()
    attached_incoming: dict[str, list[IncomingRelation]] = {item.fact_id: [] for item in attached}
    if tuple(
        (relation.source_primary_rank, relation.source_claim_index)
        for relation in pack.resolved_relations
    ) != tuple(
        sorted(
            (relation.source_primary_rank, relation.source_claim_index)
            for relation in pack.resolved_relations
        )
    ):
        raise ValueError("resolved relations must preserve primary and claim order")
    if tuple(
        (warning.source_primary_rank, warning.source_claim_index)
        for warning in pack.reference_warnings
    ) != tuple(
        sorted(
            (warning.source_primary_rank, warning.source_claim_index)
            for warning in pack.reference_warnings
        )
    ):
        raise ValueError("reference warnings must preserve primary and claim order")
    metadata_filter = pack.request.metadata_filter
    preference = pack.request.scope_preference
    for primary in primaries:
        if primary.fusion_version != pack.runtime.fusion_version:
            raise ValueError("primary fusion version does not match runtime")
        if (
            primary.vector_rank is not None
            and primary.vector_rank > pack.runtime.vector_candidate_count
        ):
            raise ValueError("primary vector rank exceeds runtime candidate count")
        if (
            primary.lexical_rank is not None
            and primary.lexical_rank > pack.runtime.lexical_candidate_count
        ):
            raise ValueError("primary lexical rank exceeds runtime candidate count")
        if metadata_filter.fact_types and primary.fact_type not in metadata_filter.fact_types:
            raise ValueError("primary evidence violates fact-type filter")
        if metadata_filter.scope_types and primary.scope_type not in metadata_filter.scope_types:
            raise ValueError("primary evidence violates scope-type filter")
        if metadata_filter.scope_targets and not set(primary.scope_targets).intersection(
            metadata_filter.scope_targets
        ):
            raise ValueError("primary evidence violates scope-target filter")
        if (
            metadata_filter.parent_colleges
            and primary.parent_college not in metadata_filter.parent_colleges
        ):
            raise ValueError("primary evidence violates parent-college filter")
        expected_targets = tuple(
            sorted(set(primary.scope_targets).intersection(preference.preferred_scope_targets))
        )
        expected_college = (
            primary.parent_college
            if primary.parent_college in preference.preferred_parent_colleges
            else None
        )
        if (
            primary.matched_scope_targets != expected_targets
            or primary.matched_parent_college != expected_college
        ):
            raise ValueError("primary preference matches do not match request")
        expected_boost = math.fsum(
            (
                pack.runtime.scope_target_match_boost if expected_targets else 0.0,
                pack.runtime.parent_college_match_boost if expected_college else 0.0,
            )
        )
        if primary.scope_boost_total != expected_boost:
            raise ValueError("primary scope boost does not match runtime constants")
        if primary.ranking_score != math.fsum((primary.fused_score, expected_boost)):
            raise ValueError("primary ranking score does not reconcile")
    for relation in pack.resolved_relations:
        identity = _relation_identity(relation)
        if identity in relation_identities:
            raise ValueError("resolved relation identities must be unique")
        relation_identities.add(identity)
        source = primary_by_fact.get(relation.source_fact_id)
        if source is None or source.primary_rank != relation.source_primary_rank:
            raise ValueError("resolved relation source does not match primary evidence")
        if relation.disposition == "attached_target":
            target = attached_by_fact.get(relation.selected_target_fact_id)
            if target is None or target.row_index != relation.target_row_index:
                raise ValueError("attached resolved target location does not reconcile")
            attached_incoming[target.fact_id].append(_incoming_from_relation(relation))
        else:
            target = primary_by_fact.get(relation.selected_target_fact_id)
            if (
                target is None
                or target.row_index != relation.target_row_index
                or target.primary_rank != relation.target_primary_rank
            ):
                raise ValueError("already-primary target location does not reconcile")

    warning_identities: set[tuple[int, str, str, str, str]] = set()
    for warning in pack.reference_warnings:
        identity = _warning_identity(warning)
        if identity in warning_identities or identity in relation_identities:
            raise ValueError("reference claim identities must be unique")
        warning_identities.add(identity)
        source = primary_by_fact.get(warning.source_fact_id)
        if source is None or source.primary_rank != warning.source_primary_rank:
            raise ValueError("reference warning source does not match primary evidence")

    claim_indexes_by_rank: dict[int, list[int]] = {
        primary.primary_rank: [] for primary in primaries
    }
    for claim in (*pack.resolved_relations, *pack.reference_warnings):
        claim_indexes_by_rank[claim.source_primary_rank].append(claim.source_claim_index)
    for indexes in claim_indexes_by_rank.values():
        if sorted(indexes) != list(range(len(indexes))):
            raise ValueError("source claim indexes must be contiguous from zero")

    for target in attached:
        if target.incoming_relations != tuple(attached_incoming[target.fact_id]):
            raise ValueError("attached incoming relations do not match resolved relations")

    warning_counts = Counter(warning.status for warning in pack.reference_warnings)
    expected_counts = {
        "primary_evidence_count": len(primaries),
        "attached_evidence_count": len(attached),
        "resolved_relation_count": len(pack.resolved_relations),
        "warning_count": len(pack.reference_warnings),
        "warning_status_counts": {
            "ambiguous": warning_counts.get("ambiguous", 0),
            "unresolved": warning_counts.get("unresolved", 0),
        },
        "unique_evidence_count": len(all_evidence),
    }
    if pack.counts.model_dump(mode="json") != expected_counts:
        raise ValueError("declared EvidencePack counts do not reconcile")


def _incoming_from_relation(relation: ResolvedReferenceRelation) -> IncomingRelation:
    return IncomingRelation(
        source_primary_rank=relation.source_primary_rank,
        source_fact_id=relation.source_fact_id,
        label=relation.label,
        reference_key=relation.reference_key,
        direction=relation.direction,
    )


def _relation_identity(value: ResolvedReferenceRelation) -> tuple[int, str, str, str, str]:
    return (
        value.source_primary_rank,
        value.source_fact_id,
        value.label,
        value.reference_key,
        value.direction,
    )


def _warning_identity(value: ReferenceWarning) -> tuple[int, str, str, str, str]:
    return (
        value.source_primary_rank,
        value.source_fact_id,
        value.label,
        value.reference_key,
        value.direction,
    )


def _validate_trimmed(value: str, name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty trimmed string")


def _validate_trimmed_strings(values: tuple[str, ...], name: str) -> None:
    for value in values:
        _validate_trimmed(value, name)


def _validate_canonical_strings(values: tuple[str, ...], name: str) -> None:
    _validate_trimmed_strings(values, name)
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{name} must be sorted and unique")


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("hash must be lowercase SHA-256 hex")


def _validate_finite(value: float, name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def _validate_json_value(value: Any) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        _validate_finite(value, "metadata number")
        return
    if isinstance(value, list):
        for child in value:
            _validate_json_value(child)
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("metadata object keys must be strings")
        for child in value.values():
            _validate_json_value(child)
        return
    raise ValueError("metadata must contain only JSON-compatible values")
