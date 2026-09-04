from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import pytest
from pydantic import ValidationError

import jgrad_admission_rag.corpus_search as corpus_search_module
from jgrad_admission_rag.corpus import CorpusAuditError, CorpusRegistration, build_corpus_manifest
from jgrad_admission_rag.corpus_search import (
    CorpusSearchPreparationError,
    CorpusSearchProviderError,
    CorpusSearchResultCompatibilityError,
    CorpusSearchSchemaError,
    canonical_corpus_search_result_bytes,
    load_corpus_search_result_bytes,
    prepare_corpus_search_context,
    revalidate_corpus_search_result,
    search_corpus,
)
from jgrad_admission_rag.corpus_selection import select_corpus_documents
from jgrad_admission_rag.retrieval.embedding import EmbeddingIdentity
from jgrad_admission_rag.retrieval.local_index import build_local_index
from jgrad_admission_rag.retrieval.metadata_search import MetadataFilter, ScopePreference
from jgrad_admission_rag.schemas.corpus_version import (
    CorpusFamilyVersionPolicy,
    CorpusSelectionRequest,
    CorpusSelectionResult,
    CorpusVersionPolicy,
)
from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    QualityGateResult,
    RetrievalUnit,
    ScopedFact,
    canonical_document_kb_bytes,
)
from tests.test_corpus_manifest import _identity


class ControlledProvider:
    def __init__(
        self,
        document_vectors: Sequence[Sequence[float]] = (),
        *,
        identity: EmbeddingIdentity | None = None,
        query_vector: Sequence[float] = (1.0, 0.0),
    ) -> None:
        self.identity = identity or EmbeddingIdentity("controlled", "axes", "r1", 2)
        self.document_vectors = [list(vector) for vector in document_vectors]
        self.query_vector = list(query_vector)
        self.document_calls = 0
        self.query_calls: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls += 1
        assert len(texts) == len(self.document_vectors)
        return [list(vector) for vector in self.document_vectors]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return list(self.query_vector)


def _write_search_kb(
    root: Path,
    document_id: str,
    *,
    family: str,
    institution: str,
    edition: str,
    rows: Sequence[dict],
    vectors: Sequence[Sequence[float]],
    provider_identity: EmbeddingIdentity | None = None,
) -> CorpusRegistration:
    identity = _identity(
        document_id,
        family=family,
        institution=institution,
        edition=edition,
    )
    facts = []
    units = []
    for position, row in enumerate(rows, start=1):
        fact_id = f"fact:{position:05d}"
        unit_id = f"unit:{position:05d}"
        metadata = {"embedding_text_version": "1", "source_label": document_id}
        fact = ScopedFact(
            fact_id=fact_id,
            fact_type=row.get("fact_type", "eligibility"),
            scope_type=row.get("scope_type", "global"),
            scope_targets=row.get("scope_targets", ()),
            parent_college=row.get("parent_college"),
            title=row["title"],
            text=row["text"],
            source_pages=[row["page"]],
            section_path=["Admissions", row["title"]],
            embedding_text=row["embedding_text"],
            metadata=metadata,
        )
        facts.append(fact)
        units.append(
            RetrievalUnit(
                unit_id=unit_id,
                fact_id=fact_id,
                text=fact.embedding_text,
                source_pages=list(fact.source_pages),
                section_path=list(fact.section_path),
                metadata=metadata,
            )
        )
    kb = DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            identity=identity,
            source_pdf=f"{document_id}.pdf",
            chunk_count=len(facts),
        ),
        facts=facts,
        retrieval_units=units,
        diagnostics=BuildDiagnostics(quality_gate=QualityGateResult(passed=True)),
    )
    kb_relative = f"documents/{document_id}/document_kb.json"
    kb_path = root / Path(*kb_relative.split("/"))
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    kb_path.write_bytes(canonical_document_kb_bytes(kb))
    index_relative = f"indexes/{document_id}"
    build_local_index(
        kb_path,
        root / Path(*index_relative.split("/")),
        ControlledProvider(vectors, identity=provider_identity),
    )
    return CorpusRegistration(kb_relative, index_relative)


def _prepared_two_document_corpus(tmp_path: Path):
    common_identity = EmbeddingIdentity("controlled", "axes", "r1", 2)
    alpha = _write_search_kb(
        tmp_path,
        "alpha-2027",
        family="alpha-family",
        institution="alpha-u",
        edition="2027",
        rows=(
            {
                "title": "Alpha identifier",
                "text": "Official alpha evidence.",
                "embedding_text": "ALPHA-CODE 2027 common requirement",
                "page": 11,
                "scope_type": "department",
                "scope_targets": ("informatics",),
                "parent_college": "engineering",
            },
            {
                "title": "Alpha fee",
                "text": "Official alpha fee evidence.",
                "embedding_text": "tuition common",
                "page": 12,
                "fact_type": "fees",
            },
        ),
        vectors=((1.0, 0.0), (0.6, 0.8)),
        provider_identity=common_identity,
    )
    beta = _write_search_kb(
        tmp_path,
        "beta-2027",
        family="beta-family",
        institution="beta-u",
        edition="2027",
        rows=(
            {
                "title": "Beta identifier",
                "text": "Official beta evidence.",
                "embedding_text": "BETA-CODE 2028 common common common requirement",
                "page": 31,
            },
            {
                "title": "Beta schedule",
                "text": "Official beta schedule evidence.",
                "embedding_text": "interview 2030",
                "page": 32,
            },
        ),
        vectors=((0.9, 0.435889894), (-1.0, 0.0)),
        provider_identity=common_identity,
    )
    manifest = build_corpus_manifest("test-corpus", tmp_path, (alpha, beta))
    policy = CorpusVersionPolicy(
        corpus_id=manifest.corpus_id,
        family_policies=(
            CorpusFamilyVersionPolicy(
                document_family_id="alpha-family", active_document_id="alpha-2027"
            ),
            CorpusFamilyVersionPolicy(
                document_family_id="beta-family", active_document_id="beta-2027"
            ),
        ),
    )
    selection = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(
            institution_ids=("alpha-u", "beta-u"),
            allow_multiple_documents=True,
        ),
    )
    context = prepare_corpus_search_context(tmp_path, manifest, policy, selection)
    return manifest, policy, selection, context, common_identity


def test_prepare_freezes_selected_indexes_without_calling_provider(tmp_path: Path) -> None:
    manifest, policy, selection, context, identity = _prepared_two_document_corpus(tmp_path)

    assert context.corpus_id == manifest.corpus_id
    assert context.embedding_identity == identity
    assert context.row_count == 4
    assert [item.entry.identity.document_id for item in context.selected_documents] == [
        "alpha-2027",
        "beta-2027",
    ]
    assert [item.document_id for item in context.freshness_reports] == [
        "alpha-2027",
        "beta-2027",
    ]
    assert all(item.report.fresh for item in context.freshness_reports)
    detached = context.selection_result
    assert detached == selection
    assert detached is not context.selection_result

    stale = CorpusSelectionResult(
        corpus_id=selection.corpus_id,
        request=selection.request,
        selected_documents=(selection.selected_documents[0],),
        selected_document_count=1,
        selected_family_count=1,
        selected_institution_count=1,
    )
    with pytest.raises(CorpusSearchPreparationError):
        prepare_corpus_search_context(tmp_path, manifest, policy, stale)


def test_preparation_audits_then_revalidates_before_selected_index_load(
    tmp_path: Path, monkeypatch
) -> None:
    manifest, policy, selection, _, _ = _prepared_two_document_corpus(tmp_path)
    events = []
    original_audit = corpus_search_module.audit_corpus_manifest
    original_revalidate = corpus_search_module.revalidate_corpus_selection_result
    original_load = corpus_search_module.load_local_index

    def tracked_audit(*args, **kwargs):
        events.append("audit")
        return original_audit(*args, **kwargs)

    def tracked_revalidate(*args, **kwargs):
        events.append("revalidate")
        return original_revalidate(*args, **kwargs)

    def tracked_load(*args, **kwargs):
        events.append("load-selected")
        return original_load(*args, **kwargs)

    monkeypatch.setattr(corpus_search_module, "audit_corpus_manifest", tracked_audit)
    monkeypatch.setattr(
        corpus_search_module, "revalidate_corpus_selection_result", tracked_revalidate
    )
    monkeypatch.setattr(corpus_search_module, "load_local_index", tracked_load)

    prepare_corpus_search_context(tmp_path, manifest, policy, selection)

    assert events[:2] == ["audit", "revalidate"]
    assert events[2:] == ["load-selected", "load-selected"]


def test_search_embeds_once_and_ranks_vector_candidates_globally(
    tmp_path: Path, monkeypatch
) -> None:
    _, _, _, context, identity = _prepared_two_document_corpus(tmp_path)
    provider = ControlledProvider(identity=identity)

    def forbid_file_access(*args, **kwargs):
        raise AssertionError("prepared corpus search must not reopen files")

    monkeypatch.setattr(Path, "open", forbid_file_access)
    monkeypatch.setattr(Path, "read_bytes", forbid_file_access)
    monkeypatch.setattr(Path, "read_text", forbid_file_access)
    result = search_corpus(context, "common", provider, top_k=2, candidate_k=2)

    assert provider.query_calls == ["common"]
    assert provider.document_calls == 0
    assert [
        (item.key.document_id, item.key.local_row_index) for item in result.vector_candidates
    ] == [
        ("alpha-2027", 0),
        ("beta-2027", 0),
    ]
    assert result.vector_candidate_count == 2
    assert sum(item.vector_candidate_count for item in result.per_document_counts) == 2


def test_global_lexical_union_keeps_duplicate_local_ids_document_qualified(
    tmp_path: Path,
) -> None:
    _, _, _, context, identity = _prepared_two_document_corpus(tmp_path)
    provider = ControlledProvider(identity=identity)

    result = search_corpus(context, "BETA-CODE 2028", provider, top_k=3, candidate_k=3)

    lexical = result.lexical_candidates[0]
    assert lexical.key.document_id == "beta-2027"
    assert lexical.key.local_row_index == 0
    assert lexical.key.fact_id == "fact:00001"
    assert lexical.key.unit_id == "unit:00001"
    alpha_key = result.vector_candidates[0].key
    assert alpha_key.fact_id == lexical.key.fact_id
    assert alpha_key.unit_id == lexical.key.unit_id
    assert alpha_key.document_id != lexical.key.document_id
    beta_hit = next(hit for hit in result.hits if hit.key.document_id == "beta-2027")
    assert beta_hit.source_pages == (31,)
    assert beta_hit.identity.institution_id == "beta-u"


def test_global_bm25_uses_union_statistics_instead_of_local_rank_splicing(
    tmp_path: Path,
) -> None:
    _, _, _, context, identity = _prepared_two_document_corpus(tmp_path)
    result = search_corpus(
        context,
        "common",
        ControlledProvider(identity=identity),
        top_k=1,
        candidate_k=1,
    )

    assert result.lexical_candidates[0].key.document_id == "beta-2027"
    assert result.lexical_candidates[0].key.local_row_index == 0


def test_filter_precedes_global_depth_and_preference_reranks_only_eligible(
    tmp_path: Path,
) -> None:
    _, _, _, context, identity = _prepared_two_document_corpus(tmp_path)
    provider = ControlledProvider(identity=identity)
    result = search_corpus(
        context,
        "common requirement",
        provider,
        top_k=1,
        candidate_k=1,
        metadata_filter=MetadataFilter(scope_types=("department",)),
        scope_preference=ScopePreference(
            preferred_scope_targets=("informatics",),
            preferred_parent_colleges=("engineering",),
        ),
    )

    assert result.eligible_row_count == 1
    assert result.hits[0].key.document_id == "alpha-2027"
    assert result.hits[0].matched_preferences == ("scope_target", "parent_college")
    assert result.hits[0].scope_boost_total > 0
    beta_counts = next(
        item for item in result.per_document_counts if item.document_id == "beta-2027"
    )
    assert beta_counts.eligible_row_count == 0
    assert beta_counts.result_count == 0


def test_zero_hit_selected_document_remains_in_diagnostics(tmp_path: Path) -> None:
    _, _, _, context, identity = _prepared_two_document_corpus(tmp_path)
    result = search_corpus(
        context,
        "ALPHA-CODE",
        ControlledProvider(identity=identity),
        top_k=1,
        candidate_k=1,
    )

    assert result.result_count == 1
    assert len(result.per_document_counts) == 2
    assert (
        next(
            item.result_count
            for item in result.per_document_counts
            if item.document_id == "beta-2027"
        )
        == 0
    )


def test_zero_eligible_corpus_keeps_every_selected_document_visible(tmp_path: Path) -> None:
    _, _, _, context, identity = _prepared_two_document_corpus(tmp_path)
    result = search_corpus(
        context,
        "common",
        ControlledProvider(identity=identity),
        metadata_filter=MetadataFilter(fact_types=("unknown-type",)),
    )

    assert result.eligible_row_count == 0
    assert result.vector_candidate_count == 0
    assert result.lexical_candidate_count == 0
    assert result.result_count == 0
    assert len(result.per_document_counts) == 2
    assert all(item.result_count == 0 for item in result.per_document_counts)


def test_global_vector_ties_use_document_then_local_row(tmp_path: Path) -> None:
    _, _, _, context, identity = _prepared_two_document_corpus(tmp_path)
    result = search_corpus(
        context,
        "common",
        ControlledProvider(identity=identity, query_vector=(0.0, 1.0)),
        top_k=4,
        candidate_k=4,
    )

    tied = [candidate for candidate in result.vector_candidates if candidate.score == 0.0]
    assert [(candidate.key.document_id, candidate.key.local_row_index) for candidate in tied] == [
        ("alpha-2027", 0),
        ("beta-2027", 1),
    ]


def test_result_is_canonical_structural_and_requires_context_revalidation(
    tmp_path: Path,
) -> None:
    _, _, _, context, identity = _prepared_two_document_corpus(tmp_path)
    provider = ControlledProvider(identity=identity)
    result = search_corpus(context, "common", provider, top_k=2, candidate_k=2)
    raw = canonical_corpus_search_result_bytes(result)
    loaded = load_corpus_search_result_bytes(raw)

    assert loaded == result
    assert revalidate_corpus_search_result(loaded, context, provider) == result
    payload = result.model_dump(mode="json")
    payload["result_count"] += 1
    with pytest.raises(CorpusSearchSchemaError):
        load_corpus_search_result_bytes(json.dumps(payload).encode())
    payload = result.model_dump(mode="json")
    payload["hits"][0]["text"] = "tampered outer evidence"
    with pytest.raises(CorpusSearchSchemaError):
        load_corpus_search_result_bytes(json.dumps(payload).encode())

    changed = result.model_copy(
        update={
            "hits": tuple(
                hit.model_copy(update={"text": "substituted evidence"}) if hit.rank == 1 else hit
                for hit in result.hits
            )
        }
    )
    with pytest.raises(CorpusSearchResultCompatibilityError):
        revalidate_corpus_search_result(changed, context, provider)


def test_result_loader_rejects_ghost_duplicate_and_out_of_range_eligible_keys(
    tmp_path: Path,
) -> None:
    _, _, _, context, identity = _prepared_two_document_corpus(tmp_path)
    result = search_corpus(
        context,
        "common",
        ControlledProvider(identity=identity),
        top_k=2,
        candidate_k=2,
    )

    ghost = result.model_dump(mode="json")
    ghost["eligible_keys"].append(
        {
            "document_id": "ghost-document",
            "local_row_index": 0,
            "unit_id": "unit:00001",
            "fact_id": "fact:00001",
        }
    )
    ghost["eligible_keys"] = _sort_key_payloads(ghost["eligible_keys"])
    ghost["eligible_row_count"] += 1
    with pytest.raises(CorpusSearchSchemaError):
        load_corpus_search_result_bytes(json.dumps(ghost).encode())

    duplicate = result.model_dump(mode="json")
    repeated_coordinate = dict(duplicate["eligible_keys"][0])
    repeated_coordinate["unit_id"] = "unit:99999"
    repeated_coordinate["fact_id"] = "fact:99999"
    duplicate["eligible_keys"].append(repeated_coordinate)
    duplicate["eligible_keys"] = _sort_key_payloads(duplicate["eligible_keys"])
    duplicate["eligible_row_count"] += 1
    duplicate["per_document_counts"][0]["eligible_row_count"] += 1
    with pytest.raises(CorpusSearchSchemaError):
        load_corpus_search_result_bytes(json.dumps(duplicate).encode())

    outside = result.model_dump(mode="json")
    outside["eligible_keys"].append(
        {
            "document_id": "alpha-2027",
            "local_row_index": 99,
            "unit_id": "unit:99999",
            "fact_id": "fact:99999",
        }
    )
    outside["eligible_keys"] = _sort_key_payloads(outside["eligible_keys"])
    outside["eligible_row_count"] += 1
    outside["per_document_counts"][0]["eligible_row_count"] += 1
    with pytest.raises(CorpusSearchSchemaError):
        load_corpus_search_result_bytes(json.dumps(outside).encode())


def test_result_loader_rejects_incomplete_final_hit_prefix(tmp_path: Path) -> None:
    _, _, _, context, identity = _prepared_two_document_corpus(tmp_path)
    result = search_corpus(
        context,
        "common",
        ControlledProvider(identity=identity),
        top_k=2,
        candidate_k=2,
    )
    payload = result.model_dump(mode="json")
    removed = payload["hits"].pop(0)
    payload["hits"][0]["rank"] = 1
    payload["result_count"] = 1
    for counts in payload["per_document_counts"]:
        if counts["document_id"] == removed["key"]["document_id"]:
            counts["result_count"] -= 1

    with pytest.raises(CorpusSearchSchemaError):
        load_corpus_search_result_bytes(json.dumps(payload).encode())


def test_provider_identity_is_checked_before_query_embedding(tmp_path: Path) -> None:
    _, _, _, context, _ = _prepared_two_document_corpus(tmp_path)
    provider = ControlledProvider(identity=EmbeddingIdentity("other", "axes", "r1", 2))

    with pytest.raises(CorpusSearchProviderError):
        search_corpus(context, "common", provider)
    assert provider.query_calls == []


def test_boundary_errors_are_typed_and_do_not_echo_nested_secrets(
    tmp_path: Path, monkeypatch
) -> None:
    manifest, policy, selection, context, identity = _prepared_two_document_corpus(tmp_path)

    def fail_audit(*args, **kwargs):
        raise CorpusAuditError("planted-secret")

    monkeypatch.setattr(corpus_search_module, "audit_corpus_manifest", fail_audit)
    with pytest.raises(CorpusSearchPreparationError) as preparation:
        prepare_corpus_search_context(tmp_path, manifest, policy, selection)
    assert "planted-secret" not in str(preparation.value)

    class FailingProvider(ControlledProvider):
        def embed_query(self, text: str) -> list[float]:
            raise RuntimeError("planted-secret")

    with pytest.raises(CorpusSearchProviderError) as search:
        search_corpus(context, "common", FailingProvider(identity=identity))
    assert "planted-secret" not in str(search.value)


def test_preparation_rejects_incompatible_embedding_contracts(tmp_path: Path) -> None:
    alpha = _write_search_kb(
        tmp_path,
        "alpha-2027",
        family="alpha-family",
        institution="alpha-u",
        edition="2027",
        rows=({"title": "A", "text": "A", "embedding_text": "alpha", "page": 1},),
        vectors=((1.0, 0.0),),
    )
    beta = _write_search_kb(
        tmp_path,
        "beta-2027",
        family="beta-family",
        institution="beta-u",
        edition="2027",
        rows=({"title": "B", "text": "B", "embedding_text": "beta", "page": 2},),
        vectors=((1.0, 0.0, 0.0),),
        provider_identity=EmbeddingIdentity("controlled", "axes", "r1", 3),
    )
    manifest = build_corpus_manifest("mixed", tmp_path, (alpha, beta))
    policy = CorpusVersionPolicy(
        corpus_id="mixed",
        family_policies=(
            CorpusFamilyVersionPolicy(
                document_family_id="alpha-family", active_document_id="alpha-2027"
            ),
            CorpusFamilyVersionPolicy(
                document_family_id="beta-family", active_document_id="beta-2027"
            ),
        ),
    )
    selection = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(
            institution_ids=("alpha-u", "beta-u"), allow_multiple_documents=True
        ),
    )

    with pytest.raises(CorpusSearchPreparationError):
        prepare_corpus_search_context(tmp_path, manifest, policy, selection)


def test_preparation_honors_active_only_and_explicit_all_versions(tmp_path: Path) -> None:
    old = _write_search_kb(
        tmp_path,
        "alpha-2026",
        family="alpha-family",
        institution="alpha-u",
        edition="2026",
        rows=({"title": "Old", "text": "Old", "embedding_text": "old", "page": 1},),
        vectors=((1.0, 0.0),),
    )
    new = _write_search_kb(
        tmp_path,
        "alpha-2027",
        family="alpha-family",
        institution="alpha-u",
        edition="2027",
        rows=({"title": "New", "text": "New", "embedding_text": "new", "page": 2},),
        vectors=((1.0, 0.0),),
    )
    manifest = build_corpus_manifest("versions", tmp_path, (old, new))
    policy = CorpusVersionPolicy(
        corpus_id="versions",
        family_policies=(
            CorpusFamilyVersionPolicy(
                document_family_id="alpha-family",
                active_document_id="alpha-2027",
                historical_document_ids=("alpha-2026",),
            ),
        ),
    )
    active = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(document_family_ids=("alpha-family",)),
    )
    active_context = prepare_corpus_search_context(tmp_path, manifest, policy, active)
    assert [item.entry.identity.document_id for item in active_context.selected_documents] == [
        "alpha-2027"
    ]

    all_versions = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(
            document_family_ids=("alpha-family",),
            version_mode="all_versions",
            allow_multiple_documents=True,
        ),
    )
    all_context = prepare_corpus_search_context(tmp_path, manifest, policy, all_versions)
    assert [item.entry.identity.document_id for item in all_context.selected_documents] == [
        "alpha-2026",
        "alpha-2027",
    ]


def test_result_models_are_frozen_and_reject_nonfinite_scores(tmp_path: Path) -> None:
    _, _, _, context, identity = _prepared_two_document_corpus(tmp_path)
    result = search_corpus(context, "common", ControlledProvider(identity=identity))
    with pytest.raises(ValidationError):
        result.result_count = 99
    payload = result.model_dump(mode="json")
    payload["hits"][0]["ranking_score"] = float("nan")
    with pytest.raises(CorpusSearchSchemaError):
        load_corpus_search_result_bytes(json.dumps(payload).encode())


def _sort_key_payloads(values: list[dict]) -> list[dict]:
    return sorted(
        values,
        key=lambda item: (
            item["document_id"],
            item["local_row_index"],
            item["unit_id"],
            item["fact_id"],
        ),
    )
