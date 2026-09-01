from __future__ import annotations

from collections import Counter

from pydantic import ValidationError

from ..schemas.evidence_pack import (
    AttachedReferenceEvidence,
    EvidenceCounts,
    EvidenceMetadataFilter,
    EvidencePack,
    EvidencePackError,
    EvidenceRequest,
    EvidenceRuntime,
    EvidenceScopePreference,
    IncomingRelation,
    PrimaryEvidence,
    ReferenceWarning,
    ResolvedReferenceRelation,
)
from .lexical_search import LEXICAL_SCORING_VERSION, LEXICAL_TOKENIZER_VERSION
from .metadata_search import MetadataSearchHit, MetadataSearchResult
from .reference_expansion import (
    REFERENCE_EXPANSION_DEPTH,
    REFERENCE_EXPANSION_VERSION,
    ExpandedTargetEvidence,
    ReferenceClaimView,
    ReferenceExpansionResult,
)

FAKE_PROVIDER_NAME = "deterministic-fake"


def build_evidence_pack(
    query: str,
    metadata_result: MetadataSearchResult,
    reference_expansion: ReferenceExpansionResult,
) -> EvidencePack:
    """Build the strict v1 handoff without interpreting or summarizing evidence."""

    if not isinstance(metadata_result, MetadataSearchResult):
        raise EvidencePackError("metadata_result must be a MetadataSearchResult")
    if not isinstance(reference_expansion, ReferenceExpansionResult):
        raise EvidencePackError("reference_expansion must be a ReferenceExpansionResult")
    try:
        _validate_input_bindings(metadata_result, reference_expansion)
        primaries = tuple(_primary_evidence(hit) for hit in metadata_result.hits)
        attached = tuple(
            _attached_evidence(target) for target in reference_expansion.expanded_targets
        )
        relations: list[ResolvedReferenceRelation] = []
        warnings: list[ReferenceWarning] = []
        for candidate in reference_expansion.candidate_expansions:
            for claim_index, claim in enumerate(candidate.claims):
                if claim.status == "resolved":
                    relations.append(_resolved_relation(claim, claim_index))
                else:
                    warnings.append(_reference_warning(claim, claim_index))
        warning_counts = Counter(warning.status for warning in warnings)
        pack = EvidencePack(
            request=_request(query, metadata_result),
            runtime=_runtime(metadata_result, reference_expansion),
            primary_evidence=primaries,
            attached_reference_evidence=attached,
            resolved_relations=tuple(relations),
            reference_warnings=tuple(warnings),
            counts=EvidenceCounts(
                primary_evidence_count=len(primaries),
                attached_evidence_count=len(attached),
                resolved_relation_count=len(relations),
                warning_count=len(warnings),
                warning_status_counts={
                    "ambiguous": warning_counts.get("ambiguous", 0),
                    "unresolved": warning_counts.get("unresolved", 0),
                },
                unique_evidence_count=len(primaries) + len(attached),
            ),
        )
    except (TypeError, ValueError, ValidationError, KeyError) as error:
        raise EvidencePackError("EvidencePack inputs are inconsistent or malformed") from error
    return pack


def _validate_input_bindings(
    result: MetadataSearchResult,
    expansion: ReferenceExpansionResult,
) -> None:
    manifest = result.manifest
    expected_primaries = tuple(
        (hit.rank, hit.row_index, hit.unit_id, hit.fact_id) for hit in result.hits
    )
    expansion_primaries = tuple(
        (item.rank, item.row_index, item.unit_id, item.fact_id)
        for item in expansion.primary_candidates
    )
    expansion_candidates = tuple(
        (item.primary_rank, item.row_index, item.fact_id) for item in expansion.candidate_expansions
    )
    if expected_primaries != expansion_primaries:
        raise ValueError("reference primaries do not match metadata hits")
    if tuple((rank, row, fact) for rank, row, _unit, fact in expected_primaries) != (
        expansion_candidates
    ):
        raise ValueError("candidate expansion order does not match metadata hits")
    if (
        expansion.document_id != manifest.document_id
        or expansion.source_kb_sha256 != manifest.source_kb_sha256
        or expansion.source_pdf_sha256 != manifest.source_pdf_sha256
        or expansion.payloads_sha256 != manifest.payloads_sha256
        or expansion.vectors_sha256 != manifest.vectors_sha256
    ):
        raise ValueError("reference expansion source binding does not match metadata result")
    if (
        expansion.expansion_version != REFERENCE_EXPANSION_VERSION
        or expansion.max_depth != REFERENCE_EXPANSION_DEPTH
    ):
        raise ValueError("reference expansion version or depth is unsupported")
    expanded_status_total = sum(expansion.expanded_status_counts.values())
    if expansion.expanded_claim_count != expanded_status_total:
        raise ValueError("expanded reference status counts do not reconcile")
    disposition_total = sum(expansion.disposition_counts.values())
    if disposition_total != expansion.expanded_claim_count:
        raise ValueError("reference disposition counts do not reconcile")
    if expansion.unique_expanded_target_count != len(expansion.expanded_targets):
        raise ValueError("expanded target count does not reconcile")
    expected_resolved = expansion.disposition_counts.get(
        "attached_target", 0
    ) + expansion.disposition_counts.get("already_primary", 0)
    if expansion.resolved_relation_count != expected_resolved:
        raise ValueError("resolved reference count does not reconcile")
    actual_claims = sum(len(candidate.claims) for candidate in expansion.candidate_expansions)
    if actual_claims != expansion.expanded_claim_count:
        raise ValueError("candidate reference claims do not reconcile")


def _request(query: str, result: MetadataSearchResult) -> EvidenceRequest:
    return EvidenceRequest(
        query=query,
        top_k_requested=result.top_k_requested,
        candidate_k_requested=result.candidate_k_requested,
        candidate_k_resolved=result.candidate_k_resolved,
        metadata_filter=EvidenceMetadataFilter(**result.requested_filter.to_dict()),
        scope_preference=EvidenceScopePreference(**result.requested_preference.to_dict()),
    )


def _runtime(
    result: MetadataSearchResult,
    expansion: ReferenceExpansionResult,
) -> EvidenceRuntime:
    manifest = result.manifest
    return EvidenceRuntime(
        document_id=manifest.document_id,
        source_kb_sha256=manifest.source_kb_sha256,
        source_pdf_sha256=manifest.source_pdf_sha256,
        index_schema_version=manifest.index_schema_version,
        source_kb_schema_version=manifest.source_kb_schema_version,
        payloads_sha256=manifest.payloads_sha256,
        vectors_sha256=manifest.vectors_sha256,
        index_builder_version=manifest.builder_version,
        embedding_provider=manifest.embedding_provider,
        embedding_model=manifest.embedding_model,
        embedding_revision=manifest.embedding_revision,
        embedding_dimension=manifest.embedding_dimension,
        distance_metric=manifest.distance_metric,
        semantic=manifest.embedding_provider != FAKE_PROVIDER_NAME,
        lexical_tokenizer_version=LEXICAL_TOKENIZER_VERSION,
        lexical_scoring_version=LEXICAL_SCORING_VERSION,
        fusion_version=result.fusion_version,
        rrf_k=result.rrf_k,
        metadata_filter_version=result.metadata_filter_version,
        scope_rerank_version=result.scope_rerank_version,
        scope_target_match_boost=result.scope_target_match_boost,
        parent_college_match_boost=result.parent_college_match_boost,
        reference_expansion_version=expansion.expansion_version,
        reference_expansion_depth=expansion.max_depth,
        corpus_row_count=result.corpus_row_count,
        eligible_row_count=result.eligible_row_count,
        vector_candidate_count=result.vector_candidate_count,
        lexical_candidate_count=result.lexical_candidate_count,
    )


def _primary_evidence(hit: MetadataSearchHit) -> PrimaryEvidence:
    value = hit.to_dict()
    return PrimaryEvidence(
        primary_rank=hit.rank,
        ranking_score=hit.ranking_score,
        fused_score=hit.fused_score,
        scope_boost_total=hit.scope_boost_total,
        matched_preferences=hit.matched_preferences,
        matched_scope_targets=hit.matched_scope_targets,
        matched_parent_college=hit.matched_parent_college,
        fusion_version=hit.fusion_version,
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
        metadata=value["metadata"],
    )


def _attached_evidence(target: ExpandedTargetEvidence) -> AttachedReferenceEvidence:
    value = target.to_dict()
    return AttachedReferenceEvidence(
        row_index=target.row_index,
        document_id=target.document_id,
        unit_id=target.unit_id,
        fact_id=target.fact_id,
        text=target.text,
        source_pages=target.source_pages,
        section_path=target.section_path,
        fact_type=target.fact_type,
        scope_type=target.scope_type,
        scope_targets=target.scope_targets,
        parent_college=target.parent_college,
        metadata=value["metadata"],
        incoming_relations=tuple(
            IncomingRelation(**relation.to_dict()) for relation in target.incoming_references
        ),
    )


def _resolved_relation(
    claim: ReferenceClaimView,
    claim_index: int,
) -> ResolvedReferenceRelation:
    if (
        claim.selected_target_fact_id is None
        or claim.target_row_index is None
        or claim.disposition not in {"attached_target", "already_primary"}
    ):
        raise ValueError("resolved claim lacks a target location")
    return ResolvedReferenceRelation(
        source_primary_rank=claim.source_primary_rank,
        source_claim_index=claim_index,
        source_fact_id=claim.source_fact_id,
        label=claim.label,
        reference_key=claim.reference_key,
        direction=claim.direction,
        selected_target_fact_id=claim.selected_target_fact_id,
        candidate_target_fact_ids=claim.candidate_target_fact_ids,
        top_score=claim.top_score,
        score_margin=claim.score_margin,
        reason=claim.reason,
        disposition=claim.disposition,
        target_row_index=claim.target_row_index,
        target_primary_rank=claim.already_primary_rank,
    )


def _reference_warning(claim: ReferenceClaimView, claim_index: int) -> ReferenceWarning:
    if (
        claim.status not in {"ambiguous", "unresolved"}
        or claim.selected_target_fact_id is not None
        or claim.target_row_index is not None
        or claim.already_primary_rank is not None
    ):
        raise ValueError("reference warning contains promoted target evidence")
    return ReferenceWarning(
        source_primary_rank=claim.source_primary_rank,
        source_claim_index=claim_index,
        source_fact_id=claim.source_fact_id,
        label=claim.label,
        reference_key=claim.reference_key,
        direction=claim.direction,
        status=claim.status,
        candidate_target_fact_ids=claim.candidate_target_fact_ids,
        top_score=claim.top_score,
        score_margin=claim.score_margin,
        reason=claim.reason,
    )
