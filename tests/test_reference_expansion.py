from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest

from jgrad_admission_rag.retrieval.hybrid_search import HybridSearchHit
from jgrad_admission_rag.retrieval.index_freshness import (
    FRESHNESS_CHECKED_FIELDS,
    FreshIndexContext,
    IndexFreshnessReport,
)
from jgrad_admission_rag.retrieval.local_index import LocalVectorIndex
from jgrad_admission_rag.retrieval.reference_expansion import (
    REFERENCE_EXPANSION_DEPTH,
    REFERENCE_EXPANSION_VERSION,
    ReferenceExpansionError,
    expand_references,
)
from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    QualityGateResult,
    ReferenceDiagnostic,
    RetrievalUnit,
    ScopedFact,
)
from tests.identity_helpers import make_document_identity
from jgrad_admission_rag.schemas.index import IndexManifest, IndexPayload


def _payload(row: int) -> IndexPayload:
    return IndexPayload(
        row_index=row,
        document_id="doc",
        unit_id=f"unit:{row}",
        fact_id=f"fact:{row}",
        text=f"canonical fact {row}",
        source_pages=[row + 1],
        section_path=["募集要項", str(row)],
        fact_type="general",
        scope_type="department" if row < 3 else "unknown",
        scope_targets=["情報工学系"] if row < 3 else [],
        parent_college="情報理工学院" if row < 3 else None,
        metadata={"nested": {"row": row}},
    )


def _claim(
    source: int,
    label: str,
    status: str,
    *,
    selected: int | None = None,
    candidates: tuple[int, ...] = (),
) -> ReferenceDiagnostic:
    return ReferenceDiagnostic(
        source_fact_id=f"fact:{source}",
        label=label,
        reference_key=f"key:{source}:{label}",
        direction="forward",
        status=status,
        selected_target_fact_id=f"fact:{selected}" if selected is not None else None,
        candidate_target_fact_ids=[f"fact:{row}" for row in candidates],
        top_score=2.0 if candidates else None,
        score_margin=0.5 if status == "resolved" else 0.0 if status == "ambiguous" else None,
        reason=f"{status}_reason",
    )


def _kb(claims: list[ReferenceDiagnostic] | None = None) -> DocumentKnowledgeBase:
    payloads = [_payload(row) for row in range(5)]
    facts = [
        ScopedFact(
            fact_id=payload.fact_id,
            fact_type=payload.fact_type,
            scope_type=payload.scope_type,
            scope_targets=list(payload.scope_targets),
            parent_college=payload.parent_college,
            title=f"fact {payload.row_index}",
            text=f"official fact {payload.row_index}",
            source_pages=list(payload.source_pages),
            section_path=list(payload.section_path),
            embedding_text=payload.text,
            metadata={"embedding_text_version": "1"},
        )
        for payload in payloads
    ]
    units = [
        RetrievalUnit(
            unit_id=payload.unit_id,
            fact_id=payload.fact_id,
            text=payload.text,
            source_pages=list(payload.source_pages),
            section_path=list(payload.section_path),
            metadata=dict(payload.metadata),
        )
        for payload in payloads
    ]
    selected_claims = claims or [
        _claim(0, "resolved-a", "resolved", selected=2, candidates=(2, 3)),
        _claim(0, "ambiguous-a", "ambiguous", candidates=(3, 4)),
        _claim(0, "unresolved-a", "unresolved"),
        _claim(1, "resolved-b", "resolved", selected=2, candidates=(2,)),
        _claim(2, "cycle-back", "resolved", selected=0, candidates=(0,)),
    ]
    counts = {status: 0 for status in ("resolved", "ambiguous", "unresolved")}
    for claim in selected_claims:
        counts[claim.status] += 1
    return DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            identity=make_document_identity(document_id="doc", pdf_sha256="b" * 64),
            source_pdf="source.pdf",
            chunk_count=5,
            reference_link_count=counts["resolved"],
        ),
        facts=facts,
        retrieval_units=units,
        diagnostics=BuildDiagnostics(
            reference_claim_count=len(selected_claims),
            reference_status_counts=counts,
            reference_claims=selected_claims,
            quality_gate=QualityGateResult(passed=True),
        ),
    )


def _index() -> LocalVectorIndex:
    payloads = tuple(_payload(row) for row in range(5))
    vectors = np.asarray([[1.0, 0.0]] * 5, dtype="<f4")
    vectors.setflags(write=False)
    return LocalVectorIndex(
        manifest=IndexManifest(
            source_kb_schema_version="0.6",
            document_id="doc",
            source_kb_sha256="a" * 64,
            source_pdf_sha256="b" * 64,
            payload_count=5,
            vector_count=5,
            embedding_dimension=2,
            vectors_normalized=True,
            embedding_provider="static",
            embedding_model="test",
            embedding_revision="r1",
            payloads_sha256="c" * 64,
            vectors_sha256="d" * 64,
        ),
        payloads=payloads,
        vectors=vectors,
    )


def _context(kb: DocumentKnowledgeBase | None = None) -> FreshIndexContext:
    return FreshIndexContext.from_knowledge_base(
        IndexFreshnessReport(
            fresh=True,
            current_kb_sha256="a" * 64,
            checked_fields=FRESHNESS_CHECKED_FIELDS,
        ),
        kb or _kb(),
    )


def _hit(payload: IndexPayload, rank: int) -> HybridSearchHit:
    return HybridSearchHit(
        rank=rank,
        row_index=payload.row_index,
        fused_score=1 / (60 + rank),
        fusion_version="rrf-v1",
        vector_rank=rank,
        vector_score=0.5,
        lexical_rank=None,
        lexical_score=None,
        matched_channels=("vector",),
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
        metadata=payload.metadata,
    )


def test_status_truth_table_attaches_only_resolved_and_preserves_claim_order() -> None:
    index = _index()
    result = expand_references(index, _context(), (_hit(index.payloads[0], 1),))

    assert REFERENCE_EXPANSION_VERSION == "reference-one-hop-v1"
    assert REFERENCE_EXPANSION_DEPTH == 1
    assert [claim.status for claim in result.candidate_expansions[0].claims] == [
        "resolved",
        "ambiguous",
        "unresolved",
    ]
    assert [claim.disposition for claim in result.candidate_expansions[0].claims] == [
        "attached_target",
        "ambiguous",
        "unresolved",
    ]
    assert [target.fact_id for target in result.expanded_targets] == ["fact:2"]
    assert result.expanded_targets[0].source_pages == (3,)
    assert result.expanded_targets[0].incoming_references[0].source_fact_id == "fact:0"
    assert result.disposition_counts == {
        "attached_target": 1,
        "already_primary": 0,
        "ambiguous": 1,
        "unresolved": 1,
    }
    ambiguous = result.candidate_expansions[0].claims[1]
    assert ambiguous.candidate_target_fact_ids == ("fact:3", "fact:4")
    assert ambiguous.target_row_index is None
    assert result.candidate_expansions[0].claims[2].candidate_target_fact_ids == ()


def test_repeated_target_is_unique_and_keeps_all_incoming_relations() -> None:
    index = _index()
    result = expand_references(
        index,
        _context(),
        (_hit(index.payloads[0], 1), _hit(index.payloads[1], 2)),
    )

    assert len(result.expanded_targets) == 1
    assert [
        relation.source_primary_rank for relation in result.expanded_targets[0].incoming_references
    ] == [
        1,
        2,
    ]
    assert result.resolved_relation_count == 2
    assert result.unique_expanded_target_count == 1


def test_already_primary_deduplicates_target_and_cycle_stays_one_hop() -> None:
    index = _index()
    primary = (_hit(index.payloads[0], 1), _hit(index.payloads[2], 2))

    result = expand_references(index, _context(), primary)

    assert result.expanded_targets == ()
    assert result.resolved_relation_count == 2
    assert result.disposition_counts["already_primary"] == 2
    first = result.candidate_expansions[0].claims[0]
    cycle_back = result.candidate_expansions[1].claims[0]
    assert first.already_primary_rank == 2
    assert cycle_back.already_primary_rank == 1
    assert [candidate.rank for candidate in result.primary_candidates] == [1, 2]


def test_no_claim_and_empty_primary_results_are_safe() -> None:
    index = _index()
    no_claim = expand_references(index, _context(), (_hit(index.payloads[4], 1),))
    empty = expand_references(index, _context(), ())

    assert no_claim.expanded_claim_count == 0
    assert no_claim.candidate_expansions[0].claims == ()
    assert empty.primary_candidates == empty.candidate_expansions == empty.expanded_targets == ()


def test_result_and_serialization_are_immutable_detached_and_stable() -> None:
    index = _index()
    kb = _kb()
    kb_before = kb.model_dump(mode="json")
    payload_before = [payload.model_dump(mode="json") for payload in index.payloads]
    result = expand_references(index, _context(kb), (_hit(index.payloads[0], 1),))
    first = result.to_dict()
    second = result.to_dict()

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    first["expanded_targets"][0]["metadata"]["nested"]["row"] = 999
    first["candidate_expansions"][0]["claims"][0]["label"] = "changed"
    assert result.to_dict() == second
    assert kb.model_dump(mode="json") == kb_before
    assert [payload.model_dump(mode="json") for payload in index.payloads] == payload_before
    with pytest.raises(FrozenInstanceError):
        result.max_depth = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    "mutation",
    ("selected_target", "status", "candidates", "claim_count", "status_count"),
)
def test_mutating_exposed_context_kb_cannot_change_frozen_expansion_authority(
    mutation: str,
) -> None:
    index = _index()
    context = _context()
    exposed = context.knowledge_base
    claim = exposed.diagnostics.reference_claims[0]
    if mutation == "selected_target":
        claim.selected_target_fact_id = "fact:3"
    elif mutation == "status":
        claim.status = "ambiguous"
    elif mutation == "candidates":
        claim.candidate_target_fact_ids = ["fact:3"]
    elif mutation == "claim_count":
        exposed.diagnostics.reference_claim_count = 0
    else:
        exposed.diagnostics.reference_status_counts["resolved"] = 0

    result = expand_references(index, context, (_hit(index.payloads[0], 1),))

    assert result.expanded_targets[0].fact_id == "fact:2"
    assert result.candidate_expansions[0].claims[0].status == "resolved"
    assert result.candidate_expansions[0].claims[0].selected_target_fact_id == "fact:2"
    assert result.authoritative_claim_count == 5
    assert result.authoritative_status_counts == {
        "resolved": 3,
        "ambiguous": 1,
        "unresolved": 1,
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda index, context, hits: (index, context, (replace(hits[0], rank=2),)), "contiguous"),
        (
            lambda index, context, hits: (
                index,
                context,
                (replace(hits[0], text="wrong"),),
            ),
            "does not match",
        ),
        (
            lambda index, context, hits: (
                index,
                _context(
                    context.knowledge_base.model_copy(
                        update={
                            "manifest": context.knowledge_base.manifest.model_copy(
                                update={
                                    "identity": context.knowledge_base.manifest.identity.model_copy(
                                        update={"document_id": "other"}
                                    )
                                }
                            )
                        }
                    )
                ),
                hits,
            ),
            "document identity",
        ),
    ],
)
def test_candidate_and_kb_alignment_fail_closed(mutation, message) -> None:
    index = _index()
    context = _context()
    hits = (_hit(index.payloads[0], 1),)
    changed_index, changed_context, changed_hits = mutation(index, context, hits)

    with pytest.raises(ReferenceExpansionError, match=message):
        expand_references(changed_index, changed_context, changed_hits)


def test_malformed_diagnostic_status_target_duplicates_and_self_links_fail_closed() -> None:
    index = _index()
    cases = []
    resolved = _claim(0, "bad-resolved", "resolved", candidates=(2,))
    cases.append(([resolved], "lacks its authoritative selected target"))
    ambiguous = _claim(0, "bad-ambiguous", "ambiguous", candidates=(2,))
    ambiguous.selected_target_fact_id = "fact:2"
    cases.append(([ambiguous], "selected a target"))
    duplicate = _claim(0, "duplicate", "unresolved")
    cases.append(([duplicate, duplicate.model_copy(deep=True)], "duplicate claim identity"))
    self_link = _claim(0, "self", "resolved", selected=0, candidates=(0,))
    cases.append(([self_link], "self-link"))
    missing = _claim(0, "missing", "unresolved", candidates=(99,))
    cases.append(([missing], "does not exist"))

    for claims, message in cases:
        with pytest.raises(ReferenceExpansionError, match=message):
            expand_references(index, _context(_kb(claims)), (_hit(index.payloads[0], 1),))


def test_context_and_manifest_reference_counts_must_reconcile() -> None:
    kb = _kb()
    context = _context(kb)
    wrong_context = replace(
        context,
        freshness=replace(context.freshness, current_kb_sha256="f" * 64),
    )
    with pytest.raises(ReferenceExpansionError, match="current index"):
        expand_references(_index(), wrong_context, ())

    kb.manifest.reference_link_count = 0
    with pytest.raises(ReferenceExpansionError, match="manifest"):
        expand_references(_index(), _context(kb), ())
