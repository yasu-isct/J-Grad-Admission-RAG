from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from jgrad_admission_rag.evaluation.retrieval_evaluation import (
    EVALUATED_K_VALUES,
    RETRIEVAL_EVALUATION_SCHEMA_VERSION,
    RETRIEVAL_METRIC_VERSION,
    EvaluationBenchmarkError,
    RetrievalEvaluationError,
    RetrievalEvaluationReport,
    canonical_retrieval_evaluation_bytes,
    evaluate_retrieval,
    fact_content_sha256,
    fact_structure_sha256,
    load_retrieval_evaluation,
    load_retrieval_evaluation_bytes,
    load_evaluation_benchmark,
)
from jgrad_admission_rag.evaluation.retrieval_queries import (
    GoldEvidence,
    RetrievalBenchmark,
    RetrievalQuery,
)
from jgrad_admission_rag.retrieval.local_index import LocalVectorIndex
from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    QualityGateResult,
    RetrievalUnit,
    ScopedFact,
)
from tests.identity_helpers import make_document_identity
from jgrad_admission_rag.schemas.evidence_pack import (
    AttachedReferenceEvidence,
    EvidenceCounts,
    EvidenceMetadataFilter,
    EvidencePack,
    EvidenceRequest,
    EvidenceRuntime,
    EvidenceScopePreference,
    IncomingRelation,
    PrimaryEvidence,
    ResolvedReferenceRelation,
)
from jgrad_admission_rag.schemas.index import IndexManifest, IndexPayload

PDF_HASH = "b" * 64
KB_HASH = "a" * 64
PAYLOAD_HASH = "c" * 64
VECTOR_HASH = "d" * 64
BENCHMARK_PATH = Path(__file__).parent / "fixtures" / "retrieval_queries_v1.json"


def _kb(count: int = 12) -> DocumentKnowledgeBase:
    facts = []
    units = []
    for row in range(count):
        fact = ScopedFact(
            fact_id=f"fact:{row:05d}",
            fact_type="general",
            scope_type="department" if row % 2 else "global",
            scope_targets=["情報工学系"] if row % 2 else [],
            title=f"fact {row}",
            text=f"official fact {row}",
            source_pages=[row + 1],
            section_path=["募集要項", str(row)],
            embedding_text=f"canonical fact {row}",
            metadata={"embedding_text_version": "1"},
        )
        facts.append(fact)
        units.append(
            RetrievalUnit(
                unit_id=f"unit:{row:05d}",
                fact_id=fact.fact_id,
                text=fact.embedding_text,
                source_pages=list(fact.source_pages),
                section_path=list(fact.section_path),
                metadata={"embedding_text_version": "1"},
            )
        )
    return DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            identity=make_document_identity(document_id="doc", pdf_sha256=PDF_HASH),
            source_pdf="source.pdf",
            chunk_count=count,
        ),
        facts=facts,
        retrieval_units=units,
        diagnostics=BuildDiagnostics(quality_gate=QualityGateResult(passed=True)),
    )


def _index(kb: DocumentKnowledgeBase) -> LocalVectorIndex:
    payloads = tuple(
        IndexPayload(
            row_index=row,
            document_id="doc",
            unit_id=f"unit:{row:05d}",
            fact_id=fact.fact_id,
            text=fact.embedding_text,
            source_pages=list(fact.source_pages),
            section_path=list(fact.section_path),
            fact_type=fact.fact_type,
            scope_type=fact.scope_type,
            scope_targets=list(fact.scope_targets),
            parent_college=fact.parent_college,
            metadata={"embedding_text_version": "1"},
        )
        for row, fact in enumerate(kb.facts)
    )
    vectors = np.zeros((len(payloads), 2), dtype="<f4")
    vectors[:, 0] = 1.0
    vectors.setflags(write=False)
    return LocalVectorIndex(
        manifest=IndexManifest(
            source_kb_schema_version="0.6",
            document_id="doc",
            source_kb_sha256=KB_HASH,
            source_pdf_sha256=PDF_HASH,
            payload_count=len(payloads),
            vector_count=len(payloads),
            embedding_dimension=2,
            vectors_normalized=True,
            embedding_provider="deterministic-fake",
            embedding_model="sha256-counter-v1",
            payloads_sha256=PAYLOAD_HASH,
            vectors_sha256=VECTOR_HASH,
        ),
        payloads=payloads,
        vectors=vectors,
    )


def _query(
    number: int,
    relevant_rows: tuple[int, ...],
    kb: DocumentKnowledgeBase,
    *,
    category: str,
    style: str,
    scope_sensitive: bool = False,
    multiple: bool = False,
    reference: bool = False,
) -> RetrievalQuery:
    evidence = [
        GoldEvidence(
            fact_id=kb.facts[row].fact_id,
            source_pages=kb.facts[row].source_pages,
            scope_type=kb.facts[row].scope_type,
            scope_targets=kb.facts[row].scope_targets,
        )
        for row in relevant_rows
    ]
    return RetrievalQuery(
        query_id=f"rq:{number:04d}",
        query=f"評価用の質問{number}です。",
        category=category,
        query_style=style,
        relevant_fact_ids=sorted(item.fact_id for item in evidence),
        gold_evidence=sorted(evidence, key=lambda item: item.fact_id),
        annotation_note="synthetic hand calculation",
        scope_sensitive=scope_sensitive,
        requires_multiple_clauses=multiple,
        requires_reference_expansion=reference,
    )


def _benchmark(kb: DocumentKnowledgeBase) -> RetrievalBenchmark:
    queries = [
        _query(
            1,
            (0, 2),
            kb,
            category="eligibility",
            style="paraphrase",
            multiple=True,
        ),
        _query(2, (10,), kb, category="fees", style="exact_term"),
        _query(
            3,
            (11,),
            kb,
            category="eligibility",
            style="identifier",
            scope_sensitive=True,
            reference=True,
        ),
    ]
    return RetrievalBenchmark.model_construct(
        schema_version="1.0",
        benchmark_id="synthetic-v1",
        document_id="doc",
        source_pdf_sha256=PDF_HASH,
        expected_kb_schema_version="0.6",
        fact_content_sha256=fact_content_sha256(kb),
        fact_structure_sha256=fact_structure_sha256(kb),
        language="ja",
        annotation_policy_version="1.0",
        queries=queries,
    )


def _runtime(count: int) -> EvidenceRuntime:
    return EvidenceRuntime(
        document_id="doc",
        source_kb_sha256=KB_HASH,
        source_pdf_sha256=PDF_HASH,
        index_schema_version="0.1",
        source_kb_schema_version="0.6",
        payloads_sha256=PAYLOAD_HASH,
        vectors_sha256=VECTOR_HASH,
        index_builder_version="0.1.0",
        embedding_provider="deterministic-fake",
        embedding_model="sha256-counter-v1",
        embedding_dimension=2,
        distance_metric="cosine",
        semantic=False,
        lexical_tokenizer_version="nfkc-casefold-ja23-v1",
        lexical_scoring_version="bm25-v1",
        fusion_version="rrf-v1",
        rrf_k=60,
        metadata_filter_version="exact-metadata-v1",
        scope_rerank_version="scope-match-v1",
        scope_target_match_boost=1 / 61,
        parent_college_match_boost=0.5 / 61,
        reference_expansion_version="reference-one-hop-v1",
        reference_expansion_depth=1,
        corpus_row_count=count,
        eligible_row_count=count,
        vector_candidate_count=min(10, count),
        lexical_candidate_count=min(10, count),
    )


def _primary(row: int, rank: int, kb: DocumentKnowledgeBase) -> PrimaryEvidence:
    fact = kb.facts[row]
    score = 2 / (60 + rank)
    return PrimaryEvidence(
        primary_rank=rank,
        ranking_score=score,
        fused_score=score,
        scope_boost_total=0.0,
        fusion_version="rrf-v1",
        vector_rank=rank,
        vector_score=1 - rank / 100,
        lexical_rank=rank,
        lexical_score=2 - rank / 100,
        matched_channels=("vector", "lexical"),
        row_index=row,
        document_id="doc",
        unit_id=f"unit:{row:05d}",
        fact_id=fact.fact_id,
        text=fact.embedding_text,
        source_pages=tuple(fact.source_pages),
        section_path=tuple(fact.section_path),
        fact_type=fact.fact_type,
        scope_type=fact.scope_type,
        scope_targets=tuple(fact.scope_targets),
        parent_college=fact.parent_college,
        metadata={"embedding_text_version": "1"},
    )


def _pack(
    query: RetrievalQuery,
    ranked_rows: tuple[int, ...],
    kb: DocumentKnowledgeBase,
    *,
    attached_row: int | None = None,
) -> EvidencePack:
    primaries = tuple(_primary(row, rank, kb) for rank, row in enumerate(ranked_rows, start=1))
    attached = ()
    relations = ()
    if attached_row is not None:
        fact = kb.facts[attached_row]
        incoming = IncomingRelation(
            source_primary_rank=1,
            source_fact_id=primaries[0].fact_id,
            label="下記",
            reference_key="key",
            direction="forward",
        )
        attached = (
            AttachedReferenceEvidence(
                row_index=attached_row,
                document_id="doc",
                unit_id=f"unit:{attached_row:05d}",
                fact_id=fact.fact_id,
                text=fact.embedding_text,
                source_pages=tuple(fact.source_pages),
                section_path=tuple(fact.section_path),
                fact_type=fact.fact_type,
                scope_type=fact.scope_type,
                scope_targets=tuple(fact.scope_targets),
                parent_college=fact.parent_college,
                metadata={"embedding_text_version": "1"},
                incoming_relations=(incoming,),
            ),
        )
        relations = (
            ResolvedReferenceRelation(
                source_primary_rank=1,
                source_claim_index=0,
                source_fact_id=primaries[0].fact_id,
                label="下記",
                reference_key="key",
                direction="forward",
                selected_target_fact_id=fact.fact_id,
                candidate_target_fact_ids=(fact.fact_id,),
                reason="unique_match",
                disposition="attached_target",
                target_row_index=attached_row,
            ),
        )
    return EvidencePack(
        request=EvidenceRequest(
            query=query.query,
            top_k_requested=10,
            candidate_k_requested=10,
            candidate_k_resolved=10,
            metadata_filter=EvidenceMetadataFilter(),
            scope_preference=EvidenceScopePreference(),
        ),
        runtime=_runtime(len(kb.facts)),
        primary_evidence=primaries,
        attached_reference_evidence=attached,
        resolved_relations=relations,
        reference_warnings=(),
        counts=EvidenceCounts(
            primary_evidence_count=len(primaries),
            attached_evidence_count=len(attached),
            resolved_relation_count=len(relations),
            warning_count=0,
            warning_status_counts={"ambiguous": 0, "unresolved": 0},
            unique_evidence_count=len(primaries) + len(attached),
        ),
    )


def _inputs():
    kb = _kb()
    benchmark = _benchmark(kb)
    rankings = (
        (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
        (0, 1, 2, 10, 3, 4, 5, 6, 7, 8),
        (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    )
    packs = tuple(
        _pack(query, ranking, kb, attached_row=11 if query.query_id == "rq:0003" else None)
        for query, ranking in zip(benchmark.queries, rankings, strict=True)
    )
    return benchmark, kb, _index(kb), packs


def test_hand_calculated_primary_metrics_and_reference_only_diagnostic() -> None:
    benchmark, kb, index, packs = _inputs()

    report = evaluate_retrieval(benchmark, kb, index, packs)

    assert report.schema_version == RETRIEVAL_EVALUATION_SCHEMA_VERSION
    assert report.metric_version == RETRIEVAL_METRIC_VERSION
    assert report.runtime.evaluated_k_values == EVALUATED_K_VALUES
    first, second, third = report.queries
    assert first.recall.ordered() == (0.5, 1.0, 1.0, 1.0)
    assert first.reciprocal_rank == 1.0
    assert second.recall.ordered() == (0.0, 0.0, 1.0, 1.0)
    assert second.first_relevant_rank == 4
    assert second.reciprocal_rank == 0.25
    assert third.recall.ordered() == (0.0, 0.0, 0.0, 0.0)
    assert third.reciprocal_rank == 0.0
    assert third.reference_only_gold_fact_ids == ("fact:00011",)
    assert report.aggregates.overall.recall.ordered() == (1 / 6, 1 / 3, 2 / 3, 2 / 3)
    assert report.aggregates.overall.mrr == pytest.approx(5 / 12)
    assert report.aggregates.overall.zero_hit_query_ids == ("rq:0003",)
    assert report.quality.model_dump(mode="json") == {
        "semantic_evaluation": False,
        "quality_eligible": False,
        "gate_status": "not_evaluated",
    }


def test_canonical_report_loader_round_trip_is_deterministic_and_detached(tmp_path: Path) -> None:
    benchmark, kb, index, packs = _inputs()
    report = evaluate_retrieval(benchmark, kb, index, packs)
    first = canonical_retrieval_evaluation_bytes(report)
    second = canonical_retrieval_evaluation_bytes(evaluate_retrieval(benchmark, kb, index, packs))

    assert first == second
    assert first.endswith(b"\n") and first.count(b"\n") == 1
    loaded = load_retrieval_evaluation_bytes(first)
    assert canonical_retrieval_evaluation_bytes(loaded) == first
    dumped = loaded.model_dump(mode="json")
    dumped["queries"][0]["ranked_primary_facts"][0]["fact_id"] = "fact:99999"
    assert loaded.queries[0].ranked_primary_facts[0].fact_id == "fact:00000"
    path = tmp_path / "report.json"
    path.write_bytes(first)
    assert canonical_retrieval_evaluation_bytes(load_retrieval_evaluation(path)) == first


def test_evaluation_benchmark_loader_reads_one_validated_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = BENCHMARK_PATH.read_bytes()
    path = tmp_path / "benchmark.json"
    path.write_bytes(raw)
    original = Path.read_bytes
    reads = 0

    def counting_read_bytes(value: Path) -> bytes:
        nonlocal reads
        reads += 1
        return original(value)

    monkeypatch.setattr(Path, "read_bytes", counting_read_bytes)
    loaded = load_evaluation_benchmark(path)

    assert reads == 1
    assert loaded.benchmark_id == "isct-master-retrieval-v1"
    assert len(loaded.queries) == 34


def test_evaluation_benchmark_loader_rejects_missing_and_malformed_paths(tmp_path: Path) -> None:
    with pytest.raises(EvaluationBenchmarkError, match="missing or unsafe"):
        load_evaluation_benchmark(tmp_path / "missing.json")

    malformed = tmp_path / "malformed.json"
    malformed.write_bytes(b'{"schema_version":"1.0"}')
    with pytest.raises(EvaluationBenchmarkError, match="invalid or unsupported"):
        load_evaluation_benchmark(malformed)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update(schema_version="2.0"),
        lambda value: value.update(extra="field"),
        lambda value: value["queries"][0]["recall"].update(recall_at_1=0.0),
        lambda value: value["queries"][0]["ranked_primary_facts"][1].update(rank=1),
        lambda value: value["aggregates"]["overall"].update(mrr=0.0),
        lambda value: value["aggregates"]["breakdowns"].reverse(),
        lambda value: value["quality"].update(quality_eligible=True),
    ),
)
def test_loader_rejects_versions_extras_false_metrics_rankings_breakdowns_and_quality(
    mutation,
) -> None:
    benchmark, kb, index, packs = _inputs()
    value = evaluate_retrieval(benchmark, kb, index, packs).model_dump(mode="json")
    mutation(value)
    raw = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    with pytest.raises(RetrievalEvaluationError, match="invalid or unsupported"):
        load_retrieval_evaluation_bytes(raw)


def test_schema_rejects_non_finite_metric() -> None:
    benchmark, kb, index, packs = _inputs()
    value = evaluate_retrieval(benchmark, kb, index, packs).model_dump(mode="json")
    value["queries"][0]["reciprocal_rank"] = float("nan")
    with pytest.raises(ValidationError):
        RetrievalEvaluationReport.model_validate(value)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda benchmark, kb, index, packs: packs[:-1],
        lambda benchmark, kb, index, packs: (
            packs[0].model_copy(
                update={"request": packs[0].request.model_copy(update={"query": "別の質問"})}
            ),
            *packs[1:],
        ),
        lambda benchmark, kb, index, packs: (
            packs[0].model_copy(
                update={
                    "request": packs[0].request.model_copy(
                        update={
                            "scope_preference": EvidenceScopePreference(
                                preferred_scope_targets=("情報工学系",)
                            )
                        }
                    )
                }
            ),
            *packs[1:],
        ),
        lambda benchmark, kb, index, packs: (
            packs[0].model_copy(
                update={
                    "primary_evidence": (
                        packs[0].primary_evidence[0].model_copy(update={"fact_id": "fact:99999"}),
                        *packs[0].primary_evidence[1:],
                    )
                }
            ),
            *packs[1:],
        ),
        lambda benchmark, kb, index, packs: (
            packs[0].model_copy(
                update={
                    "primary_evidence": (
                        packs[0].primary_evidence[0].model_copy(update={"text": "tampered"}),
                        *packs[0].primary_evidence[1:],
                    )
                }
            ),
            *packs[1:],
        ),
        lambda benchmark, kb, index, packs: (
            packs[0],
            packs[1].model_copy(
                update={
                    "runtime": packs[1].runtime.model_copy(
                        update={"embedding_model": "different-model"}
                    )
                }
            ),
            *packs[2:],
        ),
    ),
)
def test_evaluator_rejects_incomplete_pairing_gold_influence_and_tampering(mutation) -> None:
    benchmark, kb, index, packs = _inputs()
    changed = mutation(benchmark, kb, index, packs)
    with pytest.raises(RetrievalEvaluationError, match="inconsistent"):
        evaluate_retrieval(benchmark, kb, index, changed)


def test_evaluator_rejects_payload_and_pack_tampered_together() -> None:
    benchmark, kb, index, packs = _inputs()
    tampered_payload = index.payloads[0].model_copy(update={"source_pages": [99]})
    tampered_index = LocalVectorIndex(
        manifest=index.manifest,
        payloads=(tampered_payload, *index.payloads[1:]),
        vectors=index.vectors,
    )
    tampered_primary = packs[0].primary_evidence[0].model_copy(update={"source_pages": (99,)})
    tampered_pack = packs[0].model_copy(
        update={"primary_evidence": (tampered_primary, *packs[0].primary_evidence[1:])}
    )

    with pytest.raises(RetrievalEvaluationError, match="inconsistent"):
        evaluate_retrieval(
            benchmark,
            kb,
            tampered_index,
            (tampered_pack, *packs[1:]),
        )


def test_fewer_than_k_available_rows_keep_all_requested_metric_labels() -> None:
    kb = _kb(count=2)
    query = _query(1, (1,), kb, category="fees", style="exact_term")
    benchmark = RetrievalBenchmark.model_construct(
        schema_version="1.0",
        benchmark_id="small-v1",
        document_id="doc",
        source_pdf_sha256=PDF_HASH,
        expected_kb_schema_version="0.6",
        fact_content_sha256=fact_content_sha256(kb),
        fact_structure_sha256=fact_structure_sha256(kb),
        language="ja",
        annotation_policy_version="1.0",
        queries=[query],
    )
    pack = _pack(query, (0, 1), kb)

    report = evaluate_retrieval(benchmark, kb, _index(kb), (pack,))

    assert report.queries[0].returned_count == 2
    assert report.queries[0].recall.ordered() == (0.0, 1.0, 1.0, 1.0)
