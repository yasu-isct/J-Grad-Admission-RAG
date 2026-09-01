from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.retrieval.evidence_pack import build_evidence_pack
from jgrad_admission_rag.retrieval.metadata_search import (
    METADATA_FILTER_VERSION,
    PARENT_COLLEGE_MATCH_BOOST,
    SCOPE_RERANK_VERSION,
    SCOPE_TARGET_MATCH_BOOST,
    MetadataFilter,
    MetadataSearchHit,
    MetadataSearchResult,
    ScopePreference,
)
from jgrad_admission_rag.retrieval.reference_expansion import (
    REFERENCE_EXPANSION_VERSION,
    CandidateReferenceExpansion,
    ExpandedTargetEvidence,
    IncomingReference,
    PrimaryCandidateReference,
    ReferenceClaimView,
    ReferenceExpansionResult,
)
from jgrad_admission_rag.schemas.evidence_pack import (
    EVIDENCE_PACK_SCHEMA_VERSION,
    EvidencePack,
    EvidencePackError,
    canonical_evidence_pack_bytes,
    load_evidence_pack,
    load_evidence_pack_bytes,
)
from jgrad_admission_rag.schemas.index import IndexManifest


def _manifest() -> IndexManifest:
    return IndexManifest(
        source_kb_schema_version="0.5",
        document_id="doc",
        source_kb_sha256="a" * 64,
        source_pdf_sha256="b" * 64,
        payload_count=4,
        vector_count=4,
        embedding_dimension=8,
        vectors_normalized=True,
        embedding_provider="deterministic-fake",
        embedding_model="sha256-counter-v1",
        payloads_sha256="c" * 64,
        vectors_sha256="d" * 64,
    )


def _hit(row: int, rank: int) -> MetadataSearchHit:
    return MetadataSearchHit(
        rank=rank,
        ranking_score=2 / (60 + rank),
        fused_score=2 / (60 + rank),
        scope_boost_total=0.0,
        matched_preferences=(),
        matched_scope_targets=(),
        matched_parent_college=None,
        fusion_version="rrf-v1",
        vector_rank=rank,
        vector_score=0.8 - row / 10,
        lexical_rank=rank,
        lexical_score=2.0 - row / 10,
        matched_channels=("vector", "lexical"),
        row_index=row,
        document_id="doc",
        unit_id=f"unit:{row}",
        fact_id=f"fact:{row}",
        text=f"canonical fact {row}",
        source_pages=(row + 1,),
        section_path=("募集要項", str(row)),
        fact_type="general",
        scope_type="global",
        scope_targets=(),
        parent_college=None,
        metadata=MappingProxyType({"nested": MappingProxyType({"row": row})}),
    )


def _metadata_result(*, hits: tuple[MetadataSearchHit, ...] | None = None) -> MetadataSearchResult:
    selected_hits = (_hit(0, 1), _hit(1, 2)) if hits is None else hits
    return MetadataSearchResult(
        manifest=_manifest(),
        metadata_filter_version=METADATA_FILTER_VERSION,
        scope_rerank_version=SCOPE_RERANK_VERSION,
        fusion_version="rrf-v1",
        rrf_k=60,
        scope_target_match_boost=SCOPE_TARGET_MATCH_BOOST,
        parent_college_match_boost=PARENT_COLLEGE_MATCH_BOOST,
        requested_filter=MetadataFilter(),
        requested_preference=ScopePreference(),
        corpus_row_count=4,
        eligible_row_count=4,
        top_k_requested=2,
        candidate_k_requested=2,
        candidate_k_resolved=2,
        vector_candidate_count=len(selected_hits),
        lexical_candidate_count=len(selected_hits),
        hits=selected_hits,
    )


def _claim(
    source_rank: int,
    source: int,
    label: str,
    status: str,
    *,
    selected: int | None = None,
    candidates: tuple[int, ...] = (),
    disposition: str,
    target_row: int | None = None,
    primary_rank: int | None = None,
) -> ReferenceClaimView:
    return ReferenceClaimView(
        source_primary_rank=source_rank,
        source_fact_id=f"fact:{source}",
        label=label,
        reference_key=f"key:{source}:{label}",
        direction="forward",
        status=status,
        selected_target_fact_id=f"fact:{selected}" if selected is not None else None,
        candidate_target_fact_ids=tuple(f"fact:{value}" for value in candidates),
        top_score=2.0 if candidates else None,
        score_margin=0.5 if status == "resolved" else 0.0 if status == "ambiguous" else None,
        reason=f"{status}_reason",
        disposition=disposition,
        target_row_index=target_row,
        already_primary_rank=primary_rank,
    )


def _expansion() -> ReferenceExpansionResult:
    incoming = (
        IncomingReference(1, "fact:0", "to-two-a", "key:0:to-two-a", "forward"),
        IncomingReference(2, "fact:1", "to-two-b", "key:1:to-two-b", "forward"),
    )
    claims_zero = (
        _claim(
            1,
            0,
            "to-two-a",
            "resolved",
            selected=2,
            candidates=(2,),
            disposition="attached_target",
            target_row=2,
        ),
        _claim(
            1,
            0,
            "already-one",
            "resolved",
            selected=1,
            candidates=(1,),
            disposition="already_primary",
            target_row=1,
            primary_rank=2,
        ),
        _claim(
            1,
            0,
            "maybe-three",
            "ambiguous",
            candidates=(2, 3),
            disposition="ambiguous",
        ),
    )
    claims_one = (
        _claim(
            2,
            1,
            "to-two-b",
            "resolved",
            selected=2,
            candidates=(2,),
            disposition="attached_target",
            target_row=2,
        ),
        _claim(2, 1, "missing", "unresolved", disposition="unresolved"),
    )
    return ReferenceExpansionResult(
        expansion_version=REFERENCE_EXPANSION_VERSION,
        max_depth=1,
        document_id="doc",
        source_kb_sha256="a" * 64,
        source_pdf_sha256="b" * 64,
        payloads_sha256="c" * 64,
        vectors_sha256="d" * 64,
        authoritative_claim_count=5,
        authoritative_status_counts=MappingProxyType(
            {"resolved": 3, "ambiguous": 1, "unresolved": 1}
        ),
        primary_candidates=(
            PrimaryCandidateReference(1, 0, "unit:0", "fact:0"),
            PrimaryCandidateReference(2, 1, "unit:1", "fact:1"),
        ),
        candidate_expansions=(
            CandidateReferenceExpansion(1, 0, "fact:0", claims_zero),
            CandidateReferenceExpansion(2, 1, "fact:1", claims_one),
        ),
        expanded_targets=(
            ExpandedTargetEvidence(
                row_index=2,
                document_id="doc",
                unit_id="unit:2",
                fact_id="fact:2",
                text="canonical fact 2",
                source_pages=(3,),
                section_path=("募集要項", "2"),
                fact_type="general",
                scope_type="global",
                scope_targets=(),
                parent_college=None,
                metadata=MappingProxyType({"nested": MappingProxyType({"row": 2})}),
                incoming_references=incoming,
            ),
        ),
        expanded_claim_count=5,
        expanded_status_counts=MappingProxyType({"resolved": 3, "ambiguous": 1, "unresolved": 1}),
        disposition_counts=MappingProxyType(
            {
                "attached_target": 2,
                "already_primary": 1,
                "ambiguous": 1,
                "unresolved": 1,
            }
        ),
        resolved_relation_count=3,
        unique_expanded_target_count=1,
    )


def test_builder_packages_primary_attached_relation_warning_and_runtime_provenance() -> None:
    pack = build_evidence_pack("exact query", _metadata_result(), _expansion())

    assert pack.schema_version == EVIDENCE_PACK_SCHEMA_VERSION
    assert pack.request.query == "exact query"
    assert [evidence.fact_id for evidence in pack.primary_evidence] == ["fact:0", "fact:1"]
    assert [evidence.fact_id for evidence in pack.attached_reference_evidence] == ["fact:2"]
    assert [relation.disposition for relation in pack.resolved_relations] == [
        "attached_target",
        "already_primary",
        "attached_target",
    ]
    assert [
        (relation.source_primary_rank, relation.source_claim_index)
        for relation in pack.resolved_relations
    ] == [(1, 0), (1, 1), (2, 0)]
    assert [warning.status for warning in pack.reference_warnings] == [
        "ambiguous",
        "unresolved",
    ]
    assert [
        (warning.source_primary_rank, warning.source_claim_index)
        for warning in pack.reference_warnings
    ] == [(1, 2), (2, 1)]
    assert pack.counts.model_dump(mode="json") == {
        "primary_evidence_count": 2,
        "attached_evidence_count": 1,
        "resolved_relation_count": 3,
        "warning_count": 2,
        "warning_status_counts": {"ambiguous": 1, "unresolved": 1},
        "unique_evidence_count": 3,
    }
    assert pack.runtime.semantic is False
    assert pack.runtime.reference_expansion_depth == 1


def test_canonical_serialization_and_loader_are_deterministic_and_detached(tmp_path: Path) -> None:
    result = _metadata_result()
    expansion = _expansion()
    pack = build_evidence_pack("exact query", result, expansion)
    first = canonical_evidence_pack_bytes(pack)
    second = canonical_evidence_pack_bytes(build_evidence_pack("exact query", result, expansion))

    assert first == second
    assert first.endswith(b"\n") and first.count(b"\n") == 1
    loaded = load_evidence_pack_bytes(first)
    assert canonical_evidence_pack_bytes(loaded) == first
    dumped = loaded.model_dump(mode="json")
    dumped["primary_evidence"][0]["metadata"]["nested"]["row"] = 999
    assert loaded.primary_evidence[0].metadata["nested"]["row"] == 0

    path = tmp_path / "pack.json"
    path.write_bytes(first)
    assert canonical_evidence_pack_bytes(load_evidence_pack(path)) == first


def test_path_loader_reads_one_regular_file_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "pack.json"
    path.write_bytes(
        canonical_evidence_pack_bytes(
            build_evidence_pack("exact query", _metadata_result(), _expansion())
        )
    )
    original_read_bytes = Path.read_bytes
    reads = 0

    def counting_read_bytes(candidate: Path) -> bytes:
        nonlocal reads
        if candidate.resolve() == path.resolve():
            reads += 1
        return original_read_bytes(candidate)

    monkeypatch.setattr(Path, "read_bytes", counting_read_bytes)

    assert load_evidence_pack(path).schema_version == "1.0"
    assert reads == 1


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(schema_version="2.0"), "invalid or unsupported"),
        (lambda value: value.update(extra="field"), "invalid or unsupported"),
        (
            lambda value: value["counts"].update(primary_evidence_count=99),
            "invalid or unsupported",
        ),
        (
            lambda value: value["resolved_relations"][0].update(selected_target_fact_id="fact:3"),
            "invalid or unsupported",
        ),
        (
            lambda value: value["attached_reference_evidence"][0].update(fact_id="fact:0"),
            "invalid or unsupported",
        ),
        (
            lambda value: value["reference_warnings"][0].update(source_claim_index=9),
            "invalid or unsupported",
        ),
    ],
)
def test_loader_rejects_unknown_extra_false_counts_broken_relations_and_collisions(
    mutation, message
) -> None:
    value = build_evidence_pack("exact query", _metadata_result(), _expansion()).model_dump(
        mode="json"
    )
    mutation(value)
    raw = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()

    with pytest.raises(EvidencePackError, match=message):
        load_evidence_pack_bytes(raw)


def test_loader_rejects_invalid_utf8_json_and_unsafe_path(tmp_path: Path) -> None:
    for raw in (b"\xff", b"not-json", b"[]"):
        with pytest.raises(EvidencePackError):
            load_evidence_pack_bytes(raw)
    with pytest.raises(EvidencePackError, match="missing or unsafe"):
        load_evidence_pack(tmp_path / "missing.json")


def test_builder_rejects_cross_request_identity_version_and_count_drift() -> None:
    expansion = _expansion()
    cases = (
        replace(
            expansion,
            primary_candidates=(replace(expansion.primary_candidates[0], fact_id="fact:9"),),
        ),
        replace(expansion, expansion_version="other"),
        replace(expansion, expanded_claim_count=4),
        replace(expansion, source_kb_sha256="e" * 64),
    )
    for changed in cases:
        with pytest.raises(EvidencePackError, match="inconsistent or malformed"):
            build_evidence_pack("secret query", _metadata_result(), changed)


def test_schema_rejects_non_finite_scores_and_direct_false_counts() -> None:
    value = build_evidence_pack("exact query", _metadata_result(), _expansion()).model_dump(
        mode="json"
    )
    value["primary_evidence"][0]["ranking_score"] = float("nan")
    with pytest.raises(ValidationError):
        EvidencePack.model_validate(value)

    value = build_evidence_pack("exact query", _metadata_result(), _expansion()).model_dump(
        mode="json"
    )
    value["counts"]["warning_status_counts"]["ambiguous"] = 0
    with pytest.raises(ValidationError):
        EvidencePack.model_validate(value)


def test_zero_primary_result_builds_a_valid_empty_pack() -> None:
    result = _metadata_result(hits=())
    expansion = replace(
        _expansion(),
        primary_candidates=(),
        candidate_expansions=(),
        expanded_targets=(),
        expanded_claim_count=0,
        expanded_status_counts=MappingProxyType({"resolved": 0, "ambiguous": 0, "unresolved": 0}),
        disposition_counts=MappingProxyType(
            {
                "attached_target": 0,
                "already_primary": 0,
                "ambiguous": 0,
                "unresolved": 0,
            }
        ),
        resolved_relation_count=0,
        unique_expanded_target_count=0,
    )

    pack = build_evidence_pack("exact query", result, expansion)

    assert pack.primary_evidence == pack.attached_reference_evidence == ()
    assert pack.resolved_relations == pack.reference_warnings == ()
    assert pack.counts.unique_evidence_count == 0


def test_request_preserves_canonical_filter_and_preference_without_inference() -> None:
    result = replace(
        _metadata_result(),
        requested_filter=MetadataFilter(
            fact_types=("general",),
            scope_types=("global",),
        ),
        requested_preference=ScopePreference(
            preferred_scope_targets=("情報工学系",),
            preferred_parent_colleges=("情報理工学院",),
        ),
    )

    pack = build_evidence_pack("  exact query with spaces  ", result, _expansion())

    assert pack.request.query == "  exact query with spaces  "
    assert pack.request.metadata_filter.fact_types == ("general",)
    assert pack.request.metadata_filter.scope_types == ("global",)
    assert pack.request.scope_preference.preferred_scope_targets == ("情報工学系",)
    assert pack.request.scope_preference.preferred_parent_colleges == ("情報理工学院",)
