from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..retrieval.local_index import LocalVectorIndex
from ..schemas.document_kb import DocumentKnowledgeBase
from ..schemas.evidence_pack import EvidencePack, EvidenceRuntime
from .retrieval_queries import QueryCategory, QueryStyle, RetrievalBenchmark, RetrievalQuery

RETRIEVAL_EVALUATION_SCHEMA_VERSION = "1.0"
RETRIEVAL_METRIC_VERSION = "retrieval-metrics-v1"
EVALUATED_K_VALUES = (1, 3, 5, 10)
BREAKDOWN_DIMENSIONS = (
    "category",
    "query_style",
    "scope_sensitive",
    "multiple_clause",
    "reference_expansion",
)


class RetrievalEvaluationError(Exception):
    """Raised when retrieval metrics or their report cannot be trusted."""


class EvaluationBenchmarkError(RetrievalEvaluationError):
    """Raised when the evaluation benchmark path or bytes are unsafe or invalid."""


class EvaluationReportError(RetrievalEvaluationError):
    """Raised when a retrieval evaluation report cannot be serialized or loaded."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BenchmarkBinding(_StrictModel):
    benchmark_id: str
    benchmark_schema_version: Literal["1.0"]
    annotation_policy_version: Literal["1.0"]
    document_id: str
    source_pdf_sha256: str
    expected_kb_schema_version: Literal["0.5"]
    fact_content_sha256: str
    fact_structure_sha256: str
    ordered_query_count: int = Field(gt=0)

    @field_validator("benchmark_id", "document_id")
    @classmethod
    def identifiers_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @field_validator("source_pdf_sha256", "fact_content_sha256", "fact_structure_sha256")
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value


class EvaluationRuntime(_StrictModel):
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
    embedding_dimension: int = Field(gt=0)
    distance_metric: Literal["cosine"]
    semantic: bool
    retrieval_mode: Literal["hybrid"] = "hybrid"
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
    corpus_row_count: int = Field(gt=0)
    top_k_requested: int = Field(ge=10)
    candidate_k_requested: int | None = Field(default=None, ge=10)
    candidate_k_resolved: int = Field(ge=10)
    evaluated_k_values: tuple[Literal[1, 3, 5, 10], ...] = EVALUATED_K_VALUES

    @field_validator("source_kb_sha256", "source_pdf_sha256", "payloads_sha256", "vectors_sha256")
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value

    @field_validator("embedding_provider", "embedding_model")
    @classmethod
    def identifiers_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @field_validator("embedding_revision")
    @classmethod
    def revision_must_be_trimmed(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_trimmed(value)
        return value

    @field_validator("scope_target_match_boost", "parent_college_match_boost")
    @classmethod
    def boosts_must_be_finite(cls, value: float) -> float:
        _validate_finite(value)
        if value < 0:
            raise ValueError("boost must be non-negative")
        return value

    @model_validator(mode="after")
    def runtime_must_reconcile(self) -> EvaluationRuntime:
        if self.semantic != (self.embedding_provider != "deterministic-fake"):
            raise ValueError("semantic flag does not match provider")
        if self.evaluated_k_values != EVALUATED_K_VALUES:
            raise ValueError("evaluated K values are unsupported")
        if self.candidate_k_resolved < self.top_k_requested:
            raise ValueError("candidate depth must cover top_k")
        if (
            self.candidate_k_requested is not None
            and self.candidate_k_requested != self.candidate_k_resolved
        ):
            raise ValueError("requested and resolved candidate depths differ")
        return self


class RecallValues(_StrictModel):
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    recall_at_10: float

    @field_validator("*")
    @classmethod
    def recalls_must_be_finite_unit_interval(cls, value: float) -> float:
        _validate_finite(value)
        if value < 0 or value > 1:
            raise ValueError("recall must be between zero and one")
        return value

    def ordered(self) -> tuple[float, ...]:
        return (self.recall_at_1, self.recall_at_3, self.recall_at_5, self.recall_at_10)


class MissingGoldByDepth(_StrictModel):
    at_1: tuple[str, ...]
    at_3: tuple[str, ...]
    at_5: tuple[str, ...]
    at_10: tuple[str, ...]

    @field_validator("*")
    @classmethod
    def ids_must_be_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_fact_ids(values)
        if values != tuple(sorted(set(values))):
            raise ValueError("missing gold IDs must be sorted and unique")
        return values

    def ordered(self) -> tuple[tuple[str, ...], ...]:
        return (self.at_1, self.at_3, self.at_5, self.at_10)


class RankedFact(_StrictModel):
    rank: int = Field(gt=0)
    fact_id: str

    @field_validator("fact_id")
    @classmethod
    def fact_id_must_be_valid(cls, value: str) -> str:
        _validate_fact_ids((value,))
        return value


class QueryEvaluation(_StrictModel):
    query_id: str
    category: QueryCategory
    query_style: QueryStyle
    scope_sensitive: bool
    requires_multiple_clauses: bool
    requires_reference_expansion: bool
    ranked_primary_facts: tuple[RankedFact, ...]
    relevant_fact_ids: tuple[str, ...]
    first_relevant_rank: int | None = Field(default=None, gt=0)
    reciprocal_rank: float
    recall: RecallValues
    missing_gold: MissingGoldByDepth
    returned_count: int = Field(ge=0)
    eligible_row_count: int = Field(ge=0)
    vector_candidate_count: int = Field(ge=0)
    lexical_candidate_count: int = Field(ge=0)
    reference_only_gold_fact_ids: tuple[str, ...] = ()

    @field_validator("query_id", "category", "query_style")
    @classmethod
    def identifiers_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @field_validator("relevant_fact_ids", "reference_only_gold_fact_ids")
    @classmethod
    def fact_ids_must_be_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_fact_ids(values)
        if values != tuple(sorted(set(values))):
            raise ValueError("Fact IDs must be sorted and unique")
        return values

    @field_validator("reciprocal_rank")
    @classmethod
    def reciprocal_rank_must_be_finite(cls, value: float) -> float:
        _validate_finite(value)
        if value < 0 or value > 1:
            raise ValueError("reciprocal rank must be between zero and one")
        return value

    @model_validator(mode="after")
    def metrics_must_recompute_exactly(self) -> QueryEvaluation:
        ranked = tuple(item.fact_id for item in self.ranked_primary_facts)
        ranks = tuple(item.rank for item in self.ranked_primary_facts)
        if ranks != tuple(range(1, len(ranked) + 1)):
            raise ValueError("primary ranks must be contiguous and ordered")
        if len(ranked) != len(set(ranked)):
            raise ValueError("ranked primary Fact IDs must be unique")
        if self.returned_count != len(ranked):
            raise ValueError("returned count does not match ranked facts")
        expected_first, expected_rr, expected_recall, expected_missing = _score(
            self.relevant_fact_ids, ranked
        )
        if self.first_relevant_rank != expected_first or self.reciprocal_rank != expected_rr:
            raise ValueError("reciprocal-rank fields do not reconcile")
        if self.recall.ordered() != expected_recall:
            raise ValueError("per-query recall values do not reconcile")
        if self.missing_gold.ordered() != expected_missing:
            raise ValueError("missing gold IDs do not reconcile")
        primary_ids = set(ranked)
        if not set(self.reference_only_gold_fact_ids).issubset(self.relevant_fact_ids):
            raise ValueError("reference-only IDs must be relevant gold Facts")
        if primary_ids.intersection(self.reference_only_gold_fact_ids):
            raise ValueError("reference-only IDs cannot also be primary")
        if self.reference_only_gold_fact_ids and not self.requires_reference_expansion:
            raise ValueError("reference-only diagnostics require the benchmark flag")
        if self.returned_count > self.eligible_row_count:
            raise ValueError("returned count exceeds eligible rows")
        return self


class MetricSummary(_StrictModel):
    query_count: int = Field(gt=0)
    recall: RecallValues
    mrr: float
    zero_hit_query_ids: tuple[str, ...]

    @field_validator("mrr")
    @classmethod
    def mrr_must_be_finite(cls, value: float) -> float:
        _validate_finite(value)
        if value < 0 or value > 1:
            raise ValueError("MRR must be between zero and one")
        return value

    @field_validator("zero_hit_query_ids")
    @classmethod
    def query_ids_must_be_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("zero-hit query IDs must be unique")
        return values


class Breakdown(_StrictModel):
    dimension: Literal[
        "category",
        "query_style",
        "scope_sensitive",
        "multiple_clause",
        "reference_expansion",
    ]
    group: str
    summary: MetricSummary

    @field_validator("group")
    @classmethod
    def group_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value)
        return value


class EvaluationAggregates(_StrictModel):
    overall: MetricSummary
    breakdowns: tuple[Breakdown, ...]


class QualityEligibility(_StrictModel):
    semantic_evaluation: bool
    quality_eligible: bool
    gate_status: Literal["not_evaluated"] = "not_evaluated"

    @model_validator(mode="after")
    def eligibility_must_reconcile(self) -> QualityEligibility:
        if self.quality_eligible != self.semantic_evaluation:
            raise ValueError("quality eligibility must equal semantic evaluation")
        return self


class RetrievalEvaluationReport(_StrictModel):
    schema_version: Literal["1.0"] = RETRIEVAL_EVALUATION_SCHEMA_VERSION
    metric_version: Literal["retrieval-metrics-v1"] = RETRIEVAL_METRIC_VERSION
    benchmark: BenchmarkBinding
    runtime: EvaluationRuntime
    queries: tuple[QueryEvaluation, ...]
    aggregates: EvaluationAggregates
    quality: QualityEligibility

    @model_validator(mode="after")
    def report_must_reconcile(self) -> RetrievalEvaluationReport:
        if len(self.queries) != self.benchmark.ordered_query_count:
            raise ValueError("query collection does not match benchmark count")
        query_ids = tuple(query.query_id for query in self.queries)
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("query IDs must be unique")
        expected_overall = _summary(self.queries)
        if self.aggregates.overall != expected_overall:
            raise ValueError("overall aggregate metrics do not reconcile")
        expected_breakdowns = _breakdowns(self.queries)
        if self.aggregates.breakdowns != expected_breakdowns:
            raise ValueError("breakdown metrics do not reconcile")
        if self.quality.semantic_evaluation != self.runtime.semantic:
            raise ValueError("quality semantics do not match runtime provider")
        required_returned = min(self.runtime.top_k_requested, self.runtime.corpus_row_count)
        for query in self.queries:
            if query.eligible_row_count != self.runtime.corpus_row_count:
                raise ValueError("evaluation must use the unfiltered corpus")
            if query.returned_count != required_returned:
                raise ValueError("query did not return the full requested evaluation depth")
            if query.vector_candidate_count > query.eligible_row_count:
                raise ValueError("vector candidate count exceeds eligible rows")
            if query.lexical_candidate_count > query.eligible_row_count:
                raise ValueError("lexical candidate count exceeds eligible rows")
        return self


def evaluate_retrieval(
    benchmark: RetrievalBenchmark,
    knowledge_base: DocumentKnowledgeBase,
    index: LocalVectorIndex,
    evidence_packs: Sequence[EvidencePack],
) -> RetrievalEvaluationReport:
    """Evaluate primary rankings only after validating benchmark and runtime authority."""

    try:
        _validate_inputs(benchmark, knowledge_base, index, evidence_packs)
        queries = tuple(
            _evaluate_query(query, pack)
            for query, pack in zip(benchmark.queries, evidence_packs, strict=True)
        )
        first_pack = evidence_packs[0]
        report = RetrievalEvaluationReport(
            benchmark=BenchmarkBinding(
                benchmark_id=benchmark.benchmark_id,
                benchmark_schema_version=benchmark.schema_version,
                annotation_policy_version=benchmark.annotation_policy_version,
                document_id=benchmark.document_id,
                source_pdf_sha256=benchmark.source_pdf_sha256,
                expected_kb_schema_version=benchmark.expected_kb_schema_version,
                fact_content_sha256=benchmark.fact_content_sha256,
                fact_structure_sha256=benchmark.fact_structure_sha256,
                ordered_query_count=len(benchmark.queries),
            ),
            runtime=_evaluation_runtime(first_pack.runtime, first_pack),
            queries=queries,
            aggregates=EvaluationAggregates(
                overall=_summary(queries),
                breakdowns=_breakdowns(queries),
            ),
            quality=QualityEligibility(
                semantic_evaluation=first_pack.runtime.semantic,
                quality_eligible=first_pack.runtime.semantic,
            ),
        )
    except (TypeError, ValueError, ValidationError, KeyError) as error:
        raise RetrievalEvaluationError("retrieval evaluation inputs are inconsistent") from error
    return report


def canonical_retrieval_evaluation_bytes(report: RetrievalEvaluationReport) -> bytes:
    if not isinstance(report, RetrievalEvaluationReport):
        raise EvaluationReportError("value must be a RetrievalEvaluationReport")
    try:
        validated = RetrievalEvaluationReport.model_validate(report.model_dump(mode="json"))
        text = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, ValidationError) as error:
        raise EvaluationReportError("evaluation report cannot be serialized") from error
    return (text + "\n").encode("utf-8")


def load_retrieval_evaluation_bytes(raw_bytes: bytes) -> RetrievalEvaluationReport:
    if not isinstance(raw_bytes, bytes):
        raise EvaluationReportError("evaluation report input must be bytes")
    try:
        value = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != (
            RETRIEVAL_EVALUATION_SCHEMA_VERSION
        ):
            raise ValueError("unsupported report")
        return RetrievalEvaluationReport.model_validate(value)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        ValidationError,
    ) as error:
        raise EvaluationReportError("evaluation report bytes are invalid or unsupported") from error


def load_retrieval_evaluation(path_value: str | Path) -> RetrievalEvaluationReport:
    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        raise EvaluationReportError("evaluation report path is missing or unsafe")
    try:
        raw_bytes = path.read_bytes()
    except OSError as error:
        raise EvaluationReportError("evaluation report path could not be read") from error
    return load_retrieval_evaluation_bytes(raw_bytes)


def load_evaluation_benchmark(path_value: str | Path) -> RetrievalBenchmark:
    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        raise EvaluationBenchmarkError("evaluation benchmark path is missing or unsafe")
    try:
        raw_bytes = path.read_bytes()
        return RetrievalBenchmark.model_validate_json(raw_bytes)
    except (OSError, ValueError, ValidationError) as error:
        raise EvaluationBenchmarkError("evaluation benchmark is invalid or unsupported") from error


def fact_content_sha256(knowledge_base: DocumentKnowledgeBase) -> str:
    projection = [
        {
            "fact_id": fact.fact_id,
            "title": fact.title,
            "text": fact.text,
            "source_pages": fact.source_pages,
            "section_path": fact.section_path,
        }
        for fact in knowledge_base.facts
    ]
    return _projection_sha256(projection)


def fact_structure_sha256(knowledge_base: DocumentKnowledgeBase) -> str:
    units_by_fact = {unit.fact_id: unit for unit in knowledge_base.retrieval_units}
    if len(units_by_fact) != len(knowledge_base.retrieval_units):
        raise RetrievalEvaluationError("RetrievalUnit Fact identities are not unique")
    try:
        projection = [
            {
                "fact_id": fact.fact_id,
                "unit_id": units_by_fact[fact.fact_id].unit_id,
                "source_pages": fact.source_pages,
                "section_path": fact.section_path,
                "scope_type": fact.scope_type,
                "scope_targets": fact.scope_targets,
                "parent_college": fact.parent_college,
            }
            for fact in knowledge_base.facts
        ]
    except KeyError as error:
        raise RetrievalEvaluationError("Fact and RetrievalUnit identities do not align") from error
    return _projection_sha256(projection)


def _validate_inputs(
    benchmark: RetrievalBenchmark,
    knowledge_base: DocumentKnowledgeBase,
    index: LocalVectorIndex,
    packs: Sequence[EvidencePack],
) -> None:
    if not isinstance(benchmark, RetrievalBenchmark):
        raise TypeError("benchmark has the wrong type")
    if not isinstance(knowledge_base, DocumentKnowledgeBase):
        raise TypeError("knowledge base has the wrong type")
    if not isinstance(index, LocalVectorIndex):
        raise TypeError("index has the wrong type")
    if len(packs) != len(benchmark.queries) or not packs:
        raise ValueError("one EvidencePack is required for every benchmark query")
    if any(not isinstance(pack, EvidencePack) for pack in packs):
        raise TypeError("evidence packs have the wrong type")
    if (
        benchmark.document_id != knowledge_base.manifest.document_id
        or benchmark.source_pdf_sha256 != knowledge_base.manifest.pdf_sha256
        or benchmark.expected_kb_schema_version != knowledge_base.manifest.schema_version
    ):
        raise ValueError("benchmark does not match the current knowledge base")
    if benchmark.fact_content_sha256 != fact_content_sha256(knowledge_base):
        raise ValueError("benchmark Fact-content hash is stale")
    if benchmark.fact_structure_sha256 != fact_structure_sha256(knowledge_base):
        raise ValueError("benchmark Fact-structure hash is stale")
    manifest = index.manifest
    if (
        manifest.document_id != benchmark.document_id
        or manifest.source_pdf_sha256 != benchmark.source_pdf_sha256
    ):
        raise ValueError("index does not match benchmark document")
    facts = {fact.fact_id: fact for fact in knowledge_base.facts}
    payloads = {payload.fact_id: payload for payload in index.payloads}
    payload_fact_ids = set(payloads)
    if len(facts) != len(knowledge_base.facts) or payload_fact_ids != set(facts):
        raise ValueError("authoritative Fact and index identities do not align")
    for query in benchmark.queries:
        for evidence in query.gold_evidence:
            fact = facts.get(evidence.fact_id)
            if fact is None or evidence.fact_id not in payload_fact_ids:
                raise ValueError("gold Fact does not exist in the current corpus")
            if (
                evidence.source_pages != fact.source_pages
                or evidence.scope_type != fact.scope_type
                or evidence.scope_targets != fact.scope_targets
            ):
                raise ValueError("gold evidence provenance is stale")

    first = packs[0]
    common_runtime = _common_runtime(first)
    for query, pack in zip(benchmark.queries, packs, strict=True):
        if pack.request.query != query.query:
            raise ValueError("EvidencePack query does not match benchmark order")
        if any(pack.request.metadata_filter.model_dump(mode="json").values()):
            raise ValueError("evaluation EvidencePacks must not contain metadata filters")
        if any(pack.request.scope_preference.model_dump(mode="json").values()):
            raise ValueError("evaluation EvidencePacks must not contain scope preferences")
        if pack.request.top_k_requested < max(EVALUATED_K_VALUES):
            raise ValueError("retrieval depth is insufficient for required metrics")
        if _common_runtime(pack) != common_runtime:
            raise ValueError("EvidencePacks mix runtime or provider bindings")
        if pack.runtime.document_id != benchmark.document_id:
            raise ValueError("EvidencePack document does not match benchmark")
        if (
            pack.runtime.source_kb_sha256 != manifest.source_kb_sha256
            or pack.runtime.payloads_sha256 != manifest.payloads_sha256
            or pack.runtime.vectors_sha256 != manifest.vectors_sha256
        ):
            raise ValueError("EvidencePack index hashes do not match current index")
        ranked = tuple(item.fact_id for item in pack.primary_evidence)
        if len(ranked) != len(set(ranked)) or any(fact_id not in facts for fact_id in ranked):
            raise ValueError("ranked primary Facts are duplicate or unknown")
        expected_returned = min(pack.request.top_k_requested, pack.runtime.eligible_row_count)
        if len(ranked) != expected_returned:
            raise ValueError("EvidencePack returned fewer primary rows than required")
        for evidence in (*pack.primary_evidence, *pack.attached_reference_evidence):
            payload = payloads.get(evidence.fact_id)
            if payload is None or _evidence_projection(evidence) != _payload_projection(payload):
                raise ValueError("EvidencePack evidence does not match current index payload")


def _evaluate_query(query: RetrievalQuery, pack: EvidencePack) -> QueryEvaluation:
    ranked = tuple(item.fact_id for item in pack.primary_evidence)
    first_rank, reciprocal_rank, recall, missing = _score(tuple(query.relevant_fact_ids), ranked)
    attached = {item.fact_id for item in pack.attached_reference_evidence}
    reference_only = (
        tuple(sorted((set(query.relevant_fact_ids) & attached) - set(ranked)))
        if query.requires_reference_expansion
        else ()
    )
    return QueryEvaluation(
        query_id=query.query_id,
        category=query.category,
        query_style=query.query_style,
        scope_sensitive=query.scope_sensitive,
        requires_multiple_clauses=query.requires_multiple_clauses,
        requires_reference_expansion=query.requires_reference_expansion,
        ranked_primary_facts=tuple(
            RankedFact(rank=rank, fact_id=fact_id) for rank, fact_id in enumerate(ranked, start=1)
        ),
        relevant_fact_ids=tuple(query.relevant_fact_ids),
        first_relevant_rank=first_rank,
        reciprocal_rank=reciprocal_rank,
        recall=RecallValues(
            recall_at_1=recall[0],
            recall_at_3=recall[1],
            recall_at_5=recall[2],
            recall_at_10=recall[3],
        ),
        missing_gold=MissingGoldByDepth(
            at_1=missing[0],
            at_3=missing[1],
            at_5=missing[2],
            at_10=missing[3],
        ),
        returned_count=len(ranked),
        eligible_row_count=pack.runtime.eligible_row_count,
        vector_candidate_count=pack.runtime.vector_candidate_count,
        lexical_candidate_count=pack.runtime.lexical_candidate_count,
        reference_only_gold_fact_ids=reference_only,
    )


def _score(
    relevant_fact_ids: Sequence[str],
    ranked_fact_ids: Sequence[str],
) -> tuple[int | None, float, tuple[float, ...], tuple[tuple[str, ...], ...]]:
    gold = tuple(relevant_fact_ids)
    if not gold or len(gold) != len(set(gold)):
        raise ValueError("gold Fact IDs must be non-empty and unique")
    ranked = tuple(ranked_fact_ids)
    if len(ranked) != len(set(ranked)):
        raise ValueError("ranked Fact IDs must be unique")
    rank_by_fact = {fact_id: rank for rank, fact_id in enumerate(ranked, start=1)}
    relevant_ranks = [rank_by_fact[fact_id] for fact_id in gold if fact_id in rank_by_fact]
    first_rank = min(relevant_ranks) if relevant_ranks else None
    reciprocal_rank = 1.0 / first_rank if first_rank is not None else 0.0
    recalls: list[float] = []
    missing: list[tuple[str, ...]] = []
    for depth in EVALUATED_K_VALUES:
        retrieved = set(ranked[: min(depth, len(ranked))])
        recalls.append(len(set(gold).intersection(retrieved)) / len(gold))
        missing.append(tuple(sorted(set(gold) - retrieved)))
    return first_rank, reciprocal_rank, tuple(recalls), tuple(missing)


def _summary(queries: Sequence[QueryEvaluation]) -> MetricSummary:
    if not queries:
        raise ValueError("metric summary requires at least one query")
    count = len(queries)
    recall_columns = tuple(zip(*(query.recall.ordered() for query in queries), strict=True))
    macro = tuple(math.fsum(column) / count for column in recall_columns)
    return MetricSummary(
        query_count=count,
        recall=RecallValues(
            recall_at_1=macro[0],
            recall_at_3=macro[1],
            recall_at_5=macro[2],
            recall_at_10=macro[3],
        ),
        mrr=math.fsum(query.reciprocal_rank for query in queries) / count,
        zero_hit_query_ids=tuple(
            query.query_id for query in queries if query.first_relevant_rank is None
        ),
    )


def _breakdowns(queries: Sequence[QueryEvaluation]) -> tuple[Breakdown, ...]:
    values: list[Breakdown] = []
    for dimension in BREAKDOWN_DIMENSIONS:
        groups: defaultdict[str, list[QueryEvaluation]] = defaultdict(list)
        for query in queries:
            groups[_group_value(query, dimension)].append(query)
        for group in sorted(groups):
            values.append(
                Breakdown(
                    dimension=dimension,
                    group=group,
                    summary=_summary(groups[group]),
                )
            )
    return tuple(values)


def _group_value(query: QueryEvaluation, dimension: str) -> str:
    if dimension == "category":
        return query.category
    if dimension == "query_style":
        return query.query_style
    if dimension == "scope_sensitive":
        return str(query.scope_sensitive).lower()
    if dimension == "multiple_clause":
        return str(query.requires_multiple_clauses).lower()
    return str(query.requires_reference_expansion).lower()


def _common_runtime(pack: EvidencePack) -> tuple[Any, ...]:
    runtime = pack.runtime
    request = pack.request
    return (
        runtime.document_id,
        runtime.source_kb_sha256,
        runtime.source_pdf_sha256,
        runtime.index_schema_version,
        runtime.source_kb_schema_version,
        runtime.payloads_sha256,
        runtime.vectors_sha256,
        runtime.index_builder_version,
        runtime.embedding_provider,
        runtime.embedding_model,
        runtime.embedding_revision,
        runtime.embedding_dimension,
        runtime.distance_metric,
        runtime.semantic,
        runtime.lexical_tokenizer_version,
        runtime.lexical_scoring_version,
        runtime.fusion_version,
        runtime.rrf_k,
        runtime.metadata_filter_version,
        runtime.scope_rerank_version,
        runtime.scope_target_match_boost,
        runtime.parent_college_match_boost,
        runtime.reference_expansion_version,
        runtime.reference_expansion_depth,
        runtime.corpus_row_count,
        runtime.eligible_row_count,
        request.top_k_requested,
        request.candidate_k_requested,
        request.candidate_k_resolved,
    )


def _evaluation_runtime(runtime: EvidenceRuntime, pack: EvidencePack) -> EvaluationRuntime:
    return EvaluationRuntime(
        source_kb_sha256=runtime.source_kb_sha256,
        source_pdf_sha256=runtime.source_pdf_sha256,
        index_schema_version=runtime.index_schema_version,
        source_kb_schema_version=runtime.source_kb_schema_version,
        payloads_sha256=runtime.payloads_sha256,
        vectors_sha256=runtime.vectors_sha256,
        index_builder_version=runtime.index_builder_version,
        embedding_provider=runtime.embedding_provider,
        embedding_model=runtime.embedding_model,
        embedding_revision=runtime.embedding_revision,
        embedding_dimension=runtime.embedding_dimension,
        distance_metric=runtime.distance_metric,
        semantic=runtime.semantic,
        lexical_tokenizer_version=runtime.lexical_tokenizer_version,
        lexical_scoring_version=runtime.lexical_scoring_version,
        fusion_version=runtime.fusion_version,
        rrf_k=runtime.rrf_k,
        metadata_filter_version=runtime.metadata_filter_version,
        scope_rerank_version=runtime.scope_rerank_version,
        scope_target_match_boost=runtime.scope_target_match_boost,
        parent_college_match_boost=runtime.parent_college_match_boost,
        reference_expansion_version=runtime.reference_expansion_version,
        reference_expansion_depth=runtime.reference_expansion_depth,
        corpus_row_count=runtime.corpus_row_count,
        top_k_requested=pack.request.top_k_requested,
        candidate_k_requested=pack.request.candidate_k_requested,
        candidate_k_resolved=pack.request.candidate_k_resolved,
    )


def _projection_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _evidence_projection(evidence: Any) -> tuple[Any, ...]:
    return (
        evidence.row_index,
        evidence.document_id,
        evidence.unit_id,
        evidence.fact_id,
        evidence.text,
        tuple(evidence.source_pages),
        tuple(evidence.section_path),
        evidence.fact_type,
        evidence.scope_type,
        tuple(evidence.scope_targets),
        evidence.parent_college,
        evidence.metadata,
    )


def _payload_projection(payload: Any) -> tuple[Any, ...]:
    return (
        payload.row_index,
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
        payload.metadata,
    )


def _validate_trimmed(value: str) -> None:
    if not value or value != value.strip():
        raise ValueError("value must be a non-empty trimmed string")


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("value must be lowercase SHA-256 hex")


def _validate_finite(value: float) -> None:
    if not math.isfinite(value):
        raise ValueError("metric value must be finite")


def _validate_fact_ids(values: Sequence[str]) -> None:
    if any(
        len(value) != 10
        or not value.startswith("fact:")
        or not value.removeprefix("fact:").isdigit()
        for value in values
    ):
        raise ValueError("Fact IDs must use the stable fact:00000 form")
