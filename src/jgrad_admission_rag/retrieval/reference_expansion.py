from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from ..schemas.document_kb import DocumentKnowledgeBase, ReferenceDiagnostic, ScopeType
from ..schemas.index import IndexPayload
from .hybrid_search import HybridSearchHit
from .index_freshness import FreshIndexContext
from .local_index import LocalVectorIndex
from .metadata_search import MetadataSearchHit

REFERENCE_EXPANSION_VERSION = "reference-one-hop-v1"
REFERENCE_EXPANSION_DEPTH = 1
REFERENCE_STATUSES = ("resolved", "ambiguous", "unresolved")
REFERENCE_DISPOSITIONS = ("attached_target", "already_primary", "ambiguous", "unresolved")

Disposition = Literal["attached_target", "already_primary", "ambiguous", "unresolved"]
CandidateHit = HybridSearchHit | MetadataSearchHit


class ReferenceExpansionError(Exception):
    """Raised when reference evidence cannot be expanded without guessing."""


@dataclass(frozen=True, slots=True)
class PrimaryCandidateReference:
    rank: int
    row_index: int
    unit_id: str
    fact_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "row_index": self.row_index,
            "unit_id": self.unit_id,
            "fact_id": self.fact_id,
        }


@dataclass(frozen=True, slots=True)
class IncomingReference:
    source_primary_rank: int
    source_fact_id: str
    label: str
    reference_key: str
    direction: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_primary_rank": self.source_primary_rank,
            "source_fact_id": self.source_fact_id,
            "label": self.label,
            "reference_key": self.reference_key,
            "direction": self.direction,
        }


@dataclass(frozen=True, slots=True)
class ReferenceClaimView:
    source_primary_rank: int
    source_fact_id: str
    label: str
    reference_key: str
    direction: str
    status: str
    selected_target_fact_id: str | None
    candidate_target_fact_ids: tuple[str, ...]
    top_score: float | None
    score_margin: float | None
    reason: str
    disposition: Disposition
    target_row_index: int | None
    already_primary_rank: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_primary_rank": self.source_primary_rank,
            "source_fact_id": self.source_fact_id,
            "label": self.label,
            "reference_key": self.reference_key,
            "direction": self.direction,
            "status": self.status,
            "selected_target_fact_id": self.selected_target_fact_id,
            "candidate_target_fact_ids": list(self.candidate_target_fact_ids),
            "top_score": self.top_score,
            "score_margin": self.score_margin,
            "reason": self.reason,
            "disposition": self.disposition,
            "target_row_index": self.target_row_index,
            "already_primary_rank": self.already_primary_rank,
        }


@dataclass(frozen=True, slots=True)
class CandidateReferenceExpansion:
    primary_rank: int
    row_index: int
    fact_id: str
    claims: tuple[ReferenceClaimView, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_rank": self.primary_rank,
            "row_index": self.row_index,
            "fact_id": self.fact_id,
            "claims": [claim.to_dict() for claim in self.claims],
        }


@dataclass(frozen=True, slots=True)
class ExpandedTargetEvidence:
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
    incoming_references: tuple[IncomingReference, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
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
            "incoming_references": [relation.to_dict() for relation in self.incoming_references],
        }


@dataclass(frozen=True, slots=True)
class ReferenceExpansionResult:
    expansion_version: str
    max_depth: int
    document_id: str
    source_kb_sha256: str
    source_pdf_sha256: str
    payloads_sha256: str
    vectors_sha256: str
    authoritative_claim_count: int
    authoritative_status_counts: Mapping[str, int]
    primary_candidates: tuple[PrimaryCandidateReference, ...]
    candidate_expansions: tuple[CandidateReferenceExpansion, ...]
    expanded_targets: tuple[ExpandedTargetEvidence, ...]
    expanded_claim_count: int
    expanded_status_counts: Mapping[str, int]
    disposition_counts: Mapping[str, int]
    resolved_relation_count: int
    unique_expanded_target_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "expansion_version": self.expansion_version,
            "max_depth": self.max_depth,
            "document_id": self.document_id,
            "source_kb_sha256": self.source_kb_sha256,
            "source_pdf_sha256": self.source_pdf_sha256,
            "payloads_sha256": self.payloads_sha256,
            "vectors_sha256": self.vectors_sha256,
            "authoritative_claim_count": self.authoritative_claim_count,
            "authoritative_status_counts": dict(self.authoritative_status_counts),
            "primary_candidates": [candidate.to_dict() for candidate in self.primary_candidates],
            "candidate_expansions": [value.to_dict() for value in self.candidate_expansions],
            "expanded_targets": [target.to_dict() for target in self.expanded_targets],
            "expanded_claim_count": self.expanded_claim_count,
            "expanded_status_counts": dict(self.expanded_status_counts),
            "disposition_counts": dict(self.disposition_counts),
            "resolved_relation_count": self.resolved_relation_count,
            "unique_expanded_target_count": self.unique_expanded_target_count,
        }


def expand_references(
    index: LocalVectorIndex,
    context: FreshIndexContext,
    primary_hits: Sequence[CandidateHit],
) -> ReferenceExpansionResult:
    """Attach only authoritative one-hop resolved targets to original ranked candidates."""

    if not isinstance(index, LocalVectorIndex):
        raise ReferenceExpansionError("index must be a validated LocalVectorIndex")
    if not isinstance(context, FreshIndexContext):
        raise ReferenceExpansionError("context must be a FreshIndexContext")
    if context.freshness.current_kb_sha256 != index.manifest.source_kb_sha256:
        raise ReferenceExpansionError("fresh context does not belong to the current index")
    kb = context.knowledge_base
    payload_by_fact, claims_by_source, authoritative_counts = _validate_alignment(index, kb)
    candidates = _validate_primary_hits(index, primary_hits)
    primary_rank_by_fact = {hit.fact_id: hit.rank for hit in candidates}

    target_relations: dict[str, list[IncomingReference]] = {}
    candidate_expansions: list[CandidateReferenceExpansion] = []
    expanded_status_counts: Counter[str] = Counter()
    disposition_counts: Counter[str] = Counter()
    resolved_relation_count = 0

    for hit in candidates:
        views: list[ReferenceClaimView] = []
        for claim in claims_by_source.get(hit.fact_id, ()):
            expanded_status_counts[claim.status] += 1
            target_row_index: int | None = None
            already_primary_rank: int | None = None
            if claim.status == "resolved":
                resolved_relation_count += 1
                assert claim.selected_target_fact_id is not None
                target_payload = payload_by_fact[claim.selected_target_fact_id]
                target_row_index = target_payload.row_index
                already_primary_rank = primary_rank_by_fact.get(claim.selected_target_fact_id)
                if already_primary_rank is not None:
                    disposition: Disposition = "already_primary"
                else:
                    disposition = "attached_target"
                    target_relations.setdefault(claim.selected_target_fact_id, []).append(
                        IncomingReference(
                            source_primary_rank=hit.rank,
                            source_fact_id=claim.source_fact_id,
                            label=claim.label,
                            reference_key=claim.reference_key,
                            direction=claim.direction,
                        )
                    )
            elif claim.status == "ambiguous":
                disposition = "ambiguous"
            else:
                disposition = "unresolved"
            disposition_counts[disposition] += 1
            views.append(
                _claim_view(
                    claim,
                    source_primary_rank=hit.rank,
                    disposition=disposition,
                    target_row_index=target_row_index,
                    already_primary_rank=already_primary_rank,
                )
            )
        candidate_expansions.append(
            CandidateReferenceExpansion(
                primary_rank=hit.rank,
                row_index=hit.row_index,
                fact_id=hit.fact_id,
                claims=tuple(views),
            )
        )

    expanded_targets = tuple(
        _expanded_target(payload_by_fact[fact_id], tuple(relations))
        for fact_id, relations in target_relations.items()
    )
    manifest = index.manifest
    return ReferenceExpansionResult(
        expansion_version=REFERENCE_EXPANSION_VERSION,
        max_depth=REFERENCE_EXPANSION_DEPTH,
        document_id=manifest.document_id,
        source_kb_sha256=context.freshness.current_kb_sha256,
        source_pdf_sha256=manifest.source_pdf_sha256,
        payloads_sha256=manifest.payloads_sha256,
        vectors_sha256=manifest.vectors_sha256,
        authoritative_claim_count=len(kb.diagnostics.reference_claims),
        authoritative_status_counts=MappingProxyType(
            {status: authoritative_counts.get(status, 0) for status in REFERENCE_STATUSES}
        ),
        primary_candidates=tuple(
            PrimaryCandidateReference(hit.rank, hit.row_index, hit.unit_id, hit.fact_id)
            for hit in candidates
        ),
        candidate_expansions=tuple(candidate_expansions),
        expanded_targets=expanded_targets,
        expanded_claim_count=sum(expanded_status_counts.values()),
        expanded_status_counts=MappingProxyType(
            {status: expanded_status_counts.get(status, 0) for status in REFERENCE_STATUSES}
        ),
        disposition_counts=MappingProxyType(
            {
                disposition: disposition_counts.get(disposition, 0)
                for disposition in REFERENCE_DISPOSITIONS
            }
        ),
        resolved_relation_count=resolved_relation_count,
        unique_expanded_target_count=len(expanded_targets),
    )


def _validate_alignment(
    index: LocalVectorIndex,
    kb: DocumentKnowledgeBase,
) -> tuple[dict[str, IndexPayload], dict[str, tuple[ReferenceDiagnostic, ...]], Counter[str]]:
    if not isinstance(kb, DocumentKnowledgeBase):
        raise ReferenceExpansionError("fresh context does not contain a DocumentKnowledgeBase")
    if kb.manifest.document_id != index.manifest.document_id:
        raise ReferenceExpansionError("KB document identity does not match index")
    if kb.manifest.pdf_sha256 != index.manifest.source_pdf_sha256:
        raise ReferenceExpansionError("KB PDF identity does not match index")

    facts = _unique_by(kb.facts, "fact_id", "KB Facts")
    units = _unique_by(kb.retrieval_units, "fact_id", "KB RetrievalUnits")
    payload_by_fact = _unique_by(index.payloads, "fact_id", "index payloads")
    _unique_by(kb.retrieval_units, "unit_id", "KB RetrievalUnits")
    if any(payload.row_index != position for position, payload in enumerate(index.payloads)):
        raise ReferenceExpansionError("index payload row indices must be contiguous from zero")
    if set(payload_by_fact) != set(facts) or set(units) != set(facts):
        raise ReferenceExpansionError("Fact, RetrievalUnit, and payload identities do not align")
    for payload in index.payloads:
        fact = facts[payload.fact_id]
        unit = units[payload.fact_id]
        if (
            payload.unit_id != unit.unit_id
            or payload.text != fact.embedding_text
            or payload.text != unit.text
            or payload.source_pages != fact.source_pages
            or payload.source_pages != unit.source_pages
            or payload.section_path != fact.section_path
            or payload.section_path != unit.section_path
            or payload.fact_type != fact.fact_type
            or payload.scope_type != fact.scope_type
            or payload.scope_targets != fact.scope_targets
            or payload.parent_college != fact.parent_college
            or payload.metadata != unit.metadata
        ):
            raise ReferenceExpansionError("payload evidence does not align with authoritative KB")

    claims_by_source: defaultdict[str, list[ReferenceDiagnostic]] = defaultdict(list)
    claim_identities: set[tuple[str, str, str, str]] = set()
    status_counts: Counter[str] = Counter()
    for claim in kb.diagnostics.reference_claims:
        identity = (claim.source_fact_id, claim.label, claim.reference_key, claim.direction)
        if identity in claim_identities:
            raise ReferenceExpansionError(
                "reference diagnostics contain a duplicate claim identity"
            )
        claim_identities.add(identity)
        if claim.source_fact_id not in facts:
            raise ReferenceExpansionError("reference claim source Fact does not exist")
        if len(claim.candidate_target_fact_ids) != len(set(claim.candidate_target_fact_ids)):
            raise ReferenceExpansionError("reference candidate Fact IDs contain duplicates")
        if any(candidate not in facts for candidate in claim.candidate_target_fact_ids):
            raise ReferenceExpansionError("reference candidate target Fact does not exist")
        if claim.top_score is not None and not math.isfinite(claim.top_score):
            raise ReferenceExpansionError("reference top score is non-finite")
        if claim.score_margin is not None and not math.isfinite(claim.score_margin):
            raise ReferenceExpansionError("reference score margin is non-finite")
        if claim.status == "resolved":
            if (
                claim.selected_target_fact_id is None
                or claim.selected_target_fact_id not in claim.candidate_target_fact_ids
            ):
                raise ReferenceExpansionError(
                    "resolved claim lacks its authoritative selected target"
                )
            if claim.selected_target_fact_id == claim.source_fact_id:
                raise ReferenceExpansionError("resolved self-link is invalid")
        elif claim.selected_target_fact_id is not None:
            raise ReferenceExpansionError("ambiguous or unresolved claim selected a target")
        status_counts[claim.status] += 1
        claims_by_source[claim.source_fact_id].append(claim.model_copy(deep=True))
    observed_status_counts = {status: status_counts.get(status, 0) for status in REFERENCE_STATUSES}
    if observed_status_counts != kb.diagnostics.reference_status_counts:
        raise ReferenceExpansionError("reference diagnostic status counts do not reconcile")
    if len(kb.diagnostics.reference_claims) != kb.diagnostics.reference_claim_count:
        raise ReferenceExpansionError("reference diagnostic claim count does not reconcile")
    if status_counts.get("resolved", 0) != kb.manifest.reference_link_count:
        raise ReferenceExpansionError("resolved reference count does not reconcile with manifest")
    return (
        payload_by_fact,
        {key: tuple(values) for key, values in claims_by_source.items()},
        Counter(observed_status_counts),
    )


def _validate_primary_hits(
    index: LocalVectorIndex,
    hits: Sequence[CandidateHit],
) -> tuple[CandidateHit, ...]:
    if not isinstance(hits, Sequence) or isinstance(hits, (str, bytes, bytearray)):
        raise ReferenceExpansionError("primary_hits must be a ranked candidate sequence")
    seen_rows: set[int] = set()
    for position, hit in enumerate(hits, start=1):
        if not isinstance(hit, (HybridSearchHit, MetadataSearchHit)):
            raise ReferenceExpansionError("primary_hits contains an unsupported hit type")
        if hit.rank != position or isinstance(hit.rank, bool):
            raise ReferenceExpansionError("primary candidate ranks must be contiguous from one")
        if isinstance(hit.row_index, bool) or not isinstance(hit.row_index, int):
            raise ReferenceExpansionError("primary candidate row must be an integer")
        if hit.row_index in seen_rows:
            raise ReferenceExpansionError("primary candidates contain a duplicate row")
        if hit.row_index < 0 or hit.row_index >= len(index.payloads):
            raise ReferenceExpansionError("primary candidate row is out of range")
        if _candidate_evidence(hit) != _payload_evidence(index.payloads[hit.row_index]):
            raise ReferenceExpansionError(
                "primary candidate evidence does not match its payload row"
            )
        seen_rows.add(hit.row_index)
    return tuple(hits)


def _claim_view(
    claim: ReferenceDiagnostic,
    *,
    source_primary_rank: int,
    disposition: Disposition,
    target_row_index: int | None,
    already_primary_rank: int | None,
) -> ReferenceClaimView:
    return ReferenceClaimView(
        source_primary_rank=source_primary_rank,
        source_fact_id=claim.source_fact_id,
        label=claim.label,
        reference_key=claim.reference_key,
        direction=claim.direction,
        status=claim.status,
        selected_target_fact_id=claim.selected_target_fact_id,
        candidate_target_fact_ids=tuple(claim.candidate_target_fact_ids),
        top_score=claim.top_score,
        score_margin=claim.score_margin,
        reason=claim.reason,
        disposition=disposition,
        target_row_index=target_row_index,
        already_primary_rank=already_primary_rank,
    )


def _expanded_target(
    payload: IndexPayload,
    incoming: tuple[IncomingReference, ...],
) -> ExpandedTargetEvidence:
    return ExpandedTargetEvidence(
        row_index=payload.row_index,
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
        incoming_references=incoming,
    )


def _unique_by(values: Sequence[Any], field: str, name: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        key = getattr(value, field, None)
        if not isinstance(key, str) or not key or key in result:
            raise ReferenceExpansionError(f"{name} identities must be unique non-blank strings")
        result[key] = value
    return result


def _candidate_evidence(hit: CandidateHit) -> tuple[Any, ...]:
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
