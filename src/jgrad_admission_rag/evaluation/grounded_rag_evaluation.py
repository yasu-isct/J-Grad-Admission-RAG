"""Deterministic release evaluation for server-hydrated grounded RAG answers."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..generation.grounded_rag import GroundedAnswer
from ..service.demo_requirements import DemoApplicantInput, DemoTargetRequest
from .retrieval_evaluation import RetrievalEvaluationReport
from .retrieval_queries import RetrievalBenchmark
from .semantic_gate import ImplementationContractError, implementation_contract

GROUNDED_RAG_EVALUATION_SCHEMA_VERSION = "1.0"
GROUNDED_RAG_EVALUATION_VERSION = "grounded-rag-release-v1"
_CASE_ID = re.compile(r"^rag:[0-9]{4}$")
_QUERY_ID = re.compile(r"^rq:[0-9]{4}$")
_FACT_ID = re.compile(r"^fact:[0-9]{5}$")
_SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_]*$")


class GroundedRagEvaluationError(Exception):
    """Raised when release-evaluation inputs or results cannot be trusted."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExpectedEvidence(_StrictModel):
    fact_id: str
    source_pages: tuple[int, ...] = Field(min_length=1)

    @field_validator("fact_id")
    @classmethod
    def fact_id_must_be_safe(cls, value: str) -> str:
        if _FACT_ID.fullmatch(value) is None:
            raise ValueError("Fact ID is unsafe")
        return value

    @field_validator("source_pages")
    @classmethod
    def pages_must_be_canonical(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value <= 0 for value in values) or values != tuple(sorted(set(values))):
            raise ValueError("source pages must be positive, sorted, and unique")
        return values


class GroundedRagEvaluationCase(_StrictModel):
    case_id: str
    retrieval_query_id: str | None = None
    language: Literal["ja", "zh"]
    category: Literal[
        "education",
        "individual_eligibility_review",
        "application_dates",
        "english",
        "japanese",
        "common_materials",
        "department_scope",
        "missing_profile",
        "unsupported_scope",
        "unsafe_conclusion",
        "no_evidence",
    ]
    question: str = Field(min_length=1, max_length=1_000)
    applicant: DemoApplicantInput = Field(default_factory=DemoApplicantInput)
    expected_disposition: Literal["answered", "needs_information", "refused"]
    expected_evidence: tuple[ExpectedEvidence, ...] = ()
    expected_missing_fields: tuple[str, ...] = ()
    expected_error_code: str | None = None
    cross_language: bool = False

    @field_validator("case_id")
    @classmethod
    def case_id_must_be_safe(cls, value: str) -> str:
        if _CASE_ID.fullmatch(value) is None:
            raise ValueError("case ID is unsafe")
        return value

    @field_validator("retrieval_query_id")
    @classmethod
    def query_id_must_be_safe(cls, value: str | None) -> str | None:
        if value is not None and _QUERY_ID.fullmatch(value) is None:
            raise ValueError("retrieval query ID is unsafe")
        return value

    @field_validator("question")
    @classmethod
    def question_must_be_trimmed(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("question must be trimmed printable text")
        return value

    @field_validator("expected_evidence")
    @classmethod
    def evidence_must_be_canonical(
        cls, values: tuple[ExpectedEvidence, ...]
    ) -> tuple[ExpectedEvidence, ...]:
        keys = tuple(item.fact_id for item in values)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("expected evidence must be sorted and unique")
        return values

    @field_validator("expected_missing_fields")
    @classmethod
    def missing_fields_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))) or any(
            not value or value != value.strip() for value in values
        ):
            raise ValueError("missing fields must be sorted, unique, and explicit")
        return values

    @field_validator("expected_error_code")
    @classmethod
    def error_code_must_be_safe(cls, value: str | None) -> str | None:
        if value is not None and _SAFE_ERROR.fullmatch(value) is None:
            raise ValueError("error code is unsafe")
        return value

    @model_validator(mode="after")
    def expectation_must_reconcile(self) -> GroundedRagEvaluationCase:
        if self.expected_disposition == "refused":
            if (
                self.expected_evidence
                or self.expected_missing_fields
                or not self.expected_error_code
            ):
                raise ValueError("refusal expectations must carry only an error code")
        elif not self.expected_evidence or self.expected_error_code is not None:
            raise ValueError("answer expectations require evidence and no error code")
        if (self.expected_disposition == "needs_information") != bool(self.expected_missing_fields):
            raise ValueError("only needs-information cases declare missing fields")
        behavior_only_categories = {"japanese", "missing_profile", "unsafe_conclusion"}
        if (
            self.retrieval_query_id is None
            and self.expected_disposition != "refused"
            and self.category not in behavior_only_categories
        ):
            raise ValueError("retrieval-scored answer cases require a benchmark query")
        if self.cross_language != (self.language == "zh" and self.retrieval_query_id is not None):
            raise ValueError("cross-language flag must identify Chinese retrieval cases")
        return self


class GroundedRagEvaluationSuite(_StrictModel):
    schema_version: Literal["1.0"] = GROUNDED_RAG_EVALUATION_SCHEMA_VERSION
    evaluation_version: Literal["grounded-rag-release-v1"] = GROUNDED_RAG_EVALUATION_VERSION
    suite_id: Literal["isct-master-grounded-rag-release-v1"]
    document_id: str
    target: DemoTargetRequest
    source_kb_sha256: str
    source_pdf_sha256: str
    retrieval_benchmark_id: str
    retrieval_benchmark_sha256: str
    retrieval_report_sha256: str
    generation_provider: Literal["reviewed-state-offline"]
    generation_model: Literal["grounded-reviewed-v1"]
    generation_revision: Literal["1"]
    prompt_version: Literal["grounded-answer-v2"]
    generation_schema_version: Literal["1.1"]
    grounded_schema_version: Literal["1.0"]
    forbidden_conclusion_terms: tuple[str, ...] = Field(min_length=4)
    cases: tuple[GroundedRagEvaluationCase, ...] = Field(min_length=20)

    @field_validator(
        "source_kb_sha256",
        "source_pdf_sha256",
        "retrieval_benchmark_sha256",
        "retrieval_report_sha256",
    )
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value

    @field_validator("document_id", "retrieval_benchmark_id")
    @classmethod
    def identifiers_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @field_validator("forbidden_conclusion_terms")
    @classmethod
    def forbidden_terms_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))) or any(
            not value or value != value.strip() for value in values
        ):
            raise ValueError("forbidden terms must be sorted, unique, and explicit")
        return values

    @model_validator(mode="after")
    def cases_must_cover_release_scope(self) -> GroundedRagEvaluationSuite:
        if self.target.document_id != self.document_id:
            raise ValueError("evaluation target must match the bound document")
        case_ids = tuple(item.case_id for item in self.cases)
        if case_ids != tuple(f"rag:{index:04d}" for index in range(1, len(self.cases) + 1)):
            raise ValueError("case IDs must be contiguous and ordered")
        questions = tuple(item.question for item in self.cases)
        if len(questions) != len(set(questions)):
            raise ValueError("evaluation questions must be unique")
        query_ids = tuple(
            item.retrieval_query_id for item in self.cases if item.retrieval_query_id is not None
        )
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("retrieval query IDs must be unique")
        required_categories = {
            "education",
            "individual_eligibility_review",
            "application_dates",
            "english",
            "japanese",
            "common_materials",
            "department_scope",
            "missing_profile",
            "unsupported_scope",
            "unsafe_conclusion",
            "no_evidence",
        }
        if {item.category for item in self.cases} != required_categories:
            raise ValueError("evaluation categories do not cover the release contract")
        dispositions = Counter(item.expected_disposition for item in self.cases)
        if dispositions["answered"] < 6 or dispositions["needs_information"] < 2:
            raise ValueError("evaluation lacks answer and missing-information coverage")
        if dispositions["refused"] < 2 or sum(item.cross_language for item in self.cases) < 4:
            raise ValueError("evaluation lacks refusal or cross-language coverage")
        return self


class ObservedCitation(_StrictModel):
    document_id: str
    fact_id: str
    source_pages: tuple[int, ...]
    source_kb_sha256: str
    source_pdf_sha256: str

    @field_validator("source_kb_sha256", "source_pdf_sha256")
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value


class ObservedClaim(_StrictModel):
    kind: Literal["official_fact", "reviewed_rule", "applicant_statement"]
    text: str = Field(min_length=1, max_length=25_000)
    citations: tuple[ObservedCitation, ...] = ()

    @model_validator(mode="after")
    def factual_claims_must_be_cited(self) -> ObservedClaim:
        if (self.kind in {"official_fact", "reviewed_rule"}) != bool(self.citations):
            raise ValueError("only factual claims require citations")
        return self


class GroundedRagObservation(_StrictModel):
    case_id: str
    source: Literal["server-hydrated-grounded-answer-v1"]
    outcome: Literal["answered", "needs_information", "refused"]
    ranked_retrieved_fact_ids: tuple[str, ...] = ()
    claims: tuple[ObservedClaim, ...] = ()
    missing_information: tuple[str, ...] = ()
    error_code: str | None = None

    @field_validator("case_id")
    @classmethod
    def case_id_must_be_safe(cls, value: str) -> str:
        if _CASE_ID.fullmatch(value) is None:
            raise ValueError("case ID is unsafe")
        return value

    @field_validator("ranked_retrieved_fact_ids")
    @classmethod
    def ranked_facts_must_be_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or any(
            _FACT_ID.fullmatch(value) is None for value in values
        ):
            raise ValueError("ranked facts must be unique safe Fact IDs")
        return values

    @field_validator("missing_information")
    @classmethod
    def missing_information_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("missing information must be sorted and unique")
        return values

    @field_validator("error_code")
    @classmethod
    def error_code_must_be_safe(cls, value: str | None) -> str | None:
        if value is not None and _SAFE_ERROR.fullmatch(value) is None:
            raise ValueError("error code is unsafe")
        return value

    @model_validator(mode="after")
    def outcome_must_reconcile(self) -> GroundedRagObservation:
        if self.outcome == "refused":
            if self.claims or self.missing_information or not self.error_code:
                raise ValueError("refusal observations require only an error code")
        elif not self.claims or self.error_code is not None:
            raise ValueError("answer observations require claims and no error code")
        if (self.outcome == "needs_information") != bool(self.missing_information):
            raise ValueError("only needs-information observations carry missing fields")
        return self


class GroundedRagObservationSet(_StrictModel):
    schema_version: Literal["1.0"] = GROUNDED_RAG_EVALUATION_SCHEMA_VERSION
    evaluation_version: Literal["grounded-rag-release-v1"] = GROUNDED_RAG_EVALUATION_VERSION
    suite_sha256: str
    observations: tuple[GroundedRagObservation, ...] = Field(min_length=20)

    @field_validator("suite_sha256")
    @classmethod
    def suite_hash_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value

    @model_validator(mode="after")
    def observations_must_be_ordered(self) -> GroundedRagObservationSet:
        ids = tuple(item.case_id for item in self.observations)
        if ids != tuple(f"rag:{index:04d}" for index in range(1, len(ids) + 1)):
            raise ValueError("observations must be contiguous and ordered")
        return self


class GroundedRagMetrics(_StrictModel):
    retrieval_recall_at_10: float = Field(ge=0, le=1)
    retrieval_mrr: float = Field(ge=0, le=1)
    citation_correctness: float = Field(ge=0, le=1)
    citation_completeness: float = Field(ge=0, le=1)
    unsupported_claim_rate: float = Field(ge=0, le=1)
    groundedness: float = Field(ge=0, le=1)
    refusal_correctness: float = Field(ge=0, le=1)
    missing_information_correctness: float = Field(ge=0, le=1)
    cross_language_hit_rate_at_10: float = Field(ge=0, le=1)

    @field_validator("*")
    @classmethod
    def metrics_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("metric must be finite")
        return value


class GroundedRagEvaluationReport(_StrictModel):
    schema_version: Literal["1.0"] = GROUNDED_RAG_EVALUATION_SCHEMA_VERSION
    evaluation_version: Literal["grounded-rag-release-v1"] = GROUNDED_RAG_EVALUATION_VERSION
    suite_sha256: str
    observations_sha256: str
    retrieval_report_sha256: str
    case_count: int = Field(ge=20)
    answered_case_count: int = Field(ge=1)
    needs_information_case_count: int = Field(ge=1)
    refused_case_count: int = Field(ge=1)
    factual_claim_count: int = Field(ge=1)
    citation_count: int = Field(ge=1)
    metrics: GroundedRagMetrics

    @field_validator("suite_sha256", "observations_sha256", "retrieval_report_sha256")
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value

    @model_validator(mode="after")
    def counts_must_reconcile(self) -> GroundedRagEvaluationReport:
        if (
            self.answered_case_count + self.needs_information_case_count + self.refused_case_count
            != self.case_count
        ):
            raise ValueError("case counts do not reconcile")
        return self


class GroundedRagMetricFloors(_StrictModel):
    retrieval_recall_at_10: float = Field(ge=0, le=1)
    retrieval_mrr: float = Field(ge=0, le=1)
    citation_correctness: float = Field(ge=0, le=1)
    citation_completeness: float = Field(ge=0, le=1)
    groundedness: float = Field(ge=0, le=1)
    refusal_correctness: float = Field(ge=0, le=1)
    missing_information_correctness: float = Field(ge=0, le=1)
    cross_language_hit_rate_at_10: float = Field(ge=0, le=1)


class GroundedRagGatePolicy(_StrictModel):
    schema_version: Literal["1.0"] = GROUNDED_RAG_EVALUATION_SCHEMA_VERSION
    evaluation_version: Literal["grounded-rag-release-v1"] = GROUNDED_RAG_EVALUATION_VERSION
    suite_sha256: str
    observations_sha256: str
    retrieval_benchmark_sha256: str
    retrieval_report_sha256: str
    report_sha256: str
    implementation_paths: tuple[str, ...] = Field(min_length=1)
    implementation_sha256: str
    minimum_case_count: int = Field(ge=20)
    metric_floors: GroundedRagMetricFloors
    unsupported_claim_rate_ceiling: float = Field(ge=0, le=1)

    @field_validator(
        "suite_sha256",
        "observations_sha256",
        "retrieval_benchmark_sha256",
        "retrieval_report_sha256",
        "report_sha256",
        "implementation_sha256",
    )
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value

    @field_validator("implementation_paths")
    @classmethod
    def implementation_paths_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))) or any(
            not value or value != value.strip() or "\\" in value for value in values
        ):
            raise ValueError("implementation paths must be sorted unique POSIX paths")
        return values


class GroundedRagGateCheck(_StrictModel):
    code: str
    observed: float | int | str
    comparator: Literal[">=", "<=", "=="]
    threshold: float | int | str
    passed: bool


class GroundedRagGateResult(_StrictModel):
    schema_version: Literal["1.0"] = GROUNDED_RAG_EVALUATION_SCHEMA_VERSION
    evaluation_version: Literal["grounded-rag-release-v1"] = GROUNDED_RAG_EVALUATION_VERSION
    passed: bool
    checks: tuple[GroundedRagGateCheck, ...]
    failure_codes: tuple[str, ...]

    @model_validator(mode="after")
    def failures_must_reconcile(self) -> GroundedRagGateResult:
        failures = tuple(sorted(item.code for item in self.checks if not item.passed))
        if self.failure_codes != failures or self.passed != (not failures):
            raise ValueError("gate failures do not reconcile")
        return self


def project_grounded_answer(
    case_id: str,
    ranked_retrieved_fact_ids: tuple[str, ...],
    answer: GroundedAnswer,
) -> GroundedRagObservation:
    """Project only validated public answer state; never retain provider payloads or hidden reasoning."""

    checked = GroundedAnswer.model_validate(answer.model_dump(mode="json"))
    outcome = "needs_information" if checked.missing_information else "answered"
    return GroundedRagObservation(
        case_id=case_id,
        source="server-hydrated-grounded-answer-v1",
        outcome=outcome,
        ranked_retrieved_fact_ids=ranked_retrieved_fact_ids,
        claims=tuple(
            ObservedClaim(
                kind=claim.kind.value,
                text=claim.text,
                citations=tuple(
                    ObservedCitation(
                        document_id=citation.document_id,
                        fact_id=citation.fact_id,
                        source_pages=citation.source_pages,
                        source_kb_sha256=citation.source_kb_sha256,
                        source_pdf_sha256=citation.source_pdf_sha256,
                    )
                    for citation in claim.citations
                ),
            )
            for claim in checked.claims
        ),
        missing_information=checked.missing_information,
    )


def refusal_observation(
    case_id: str,
    error_code: str,
    *,
    ranked_retrieved_fact_ids: tuple[str, ...] = (),
) -> GroundedRagObservation:
    return GroundedRagObservation(
        case_id=case_id,
        source="server-hydrated-grounded-answer-v1",
        outcome="refused",
        ranked_retrieved_fact_ids=ranked_retrieved_fact_ids,
        error_code=error_code,
    )


def evaluate_grounded_rag_release(
    suite: GroundedRagEvaluationSuite,
    observations: GroundedRagObservationSet,
    retrieval_report: RetrievalEvaluationReport,
    retrieval_benchmark: RetrievalBenchmark,
) -> GroundedRagEvaluationReport:
    """Recompute all release metrics from strict source-bound inputs."""

    checked_suite = GroundedRagEvaluationSuite.model_validate(suite.model_dump(mode="json"))
    checked_observations = GroundedRagObservationSet.model_validate(
        observations.model_dump(mode="json")
    )
    checked_retrieval = RetrievalEvaluationReport.model_validate(
        retrieval_report.model_dump(mode="json")
    )
    checked_benchmark = RetrievalBenchmark.model_validate(
        retrieval_benchmark.model_dump(mode="json")
    )
    suite_bytes = canonical_grounded_rag_suite_bytes(checked_suite)
    if checked_observations.suite_sha256 != _sha256(suite_bytes):
        raise GroundedRagEvaluationError("observation suite binding does not reconcile")
    retrieval_bytes = _canonical_model_bytes(checked_retrieval)
    benchmark_bytes = _canonical_model_bytes(checked_benchmark)
    if checked_suite.retrieval_benchmark_sha256 != _sha256(benchmark_bytes):
        raise GroundedRagEvaluationError("retrieval benchmark binding does not reconcile")
    if checked_suite.retrieval_report_sha256 != _sha256(retrieval_bytes):
        raise GroundedRagEvaluationError("retrieval report binding does not reconcile")
    if (
        checked_retrieval.benchmark.benchmark_id != checked_suite.retrieval_benchmark_id
        or checked_benchmark.benchmark_id != checked_suite.retrieval_benchmark_id
        or checked_benchmark.document_id != checked_suite.document_id
        or checked_benchmark.source_pdf_sha256 != checked_suite.source_pdf_sha256
        or checked_retrieval.benchmark.document_id != checked_suite.document_id
        or checked_retrieval.runtime.source_kb_sha256 != checked_suite.source_kb_sha256
        or checked_retrieval.runtime.source_pdf_sha256 != checked_suite.source_pdf_sha256
    ):
        raise GroundedRagEvaluationError("release source identity does not reconcile")

    observations_by_id = {item.case_id: item for item in checked_observations.observations}
    if tuple(observations_by_id) != tuple(item.case_id for item in checked_suite.cases):
        raise GroundedRagEvaluationError("observation coverage does not reconcile")
    benchmark_by_id = {item.query_id: item for item in checked_benchmark.queries}

    retrieval_recalls: list[float] = []
    retrieval_rrs: list[float] = []
    cross_hits: list[float] = []
    correct_citations = 0
    citation_count = 0
    complete_expected = 0
    expected_count = 0
    factual_claim_count = 0
    unsupported_claim_count = 0
    refusal_checks: list[bool] = []
    missing_checks: list[bool] = []

    for case in checked_suite.cases:
        observed = observations_by_id[case.case_id]
        if case.retrieval_query_id is not None:
            benchmark_query = benchmark_by_id.get(case.retrieval_query_id)
            if benchmark_query is None or benchmark_query.query != case.question:
                raise GroundedRagEvaluationError(
                    "release question does not match its bound retrieval query"
                )
            relevant = set(benchmark_query.relevant_fact_ids)
            ranked_at_10 = observed.ranked_retrieved_fact_ids[:10]
            relevant_ranks = tuple(
                rank for rank, fact_id in enumerate(ranked_at_10, start=1) if fact_id in relevant
            )
            retrieval_recalls.append(len(set(ranked_at_10) & relevant) / len(relevant))
            retrieval_rrs.append(1.0 / relevant_ranks[0] if relevant_ranks else 0.0)
            if case.cross_language:
                cross_hits.append(float(bool(relevant_ranks)))
        expected_citations = {
            (
                checked_suite.document_id,
                item.fact_id,
                item.source_pages,
                checked_suite.source_kb_sha256,
                checked_suite.source_pdf_sha256,
            )
            for item in case.expected_evidence
        }
        observed_citations = []
        for claim in observed.claims:
            if claim.kind not in {"official_fact", "reviewed_rule"}:
                continue
            factual_claim_count += 1
            claim_citations = {
                (
                    item.document_id,
                    item.fact_id,
                    item.source_pages,
                    item.source_kb_sha256,
                    item.source_pdf_sha256,
                )
                for item in claim.citations
            }
            has_forbidden_conclusion = any(
                term.casefold() in claim.text.casefold()
                for term in checked_suite.forbidden_conclusion_terms
            )
            if (
                not claim_citations
                or not claim_citations <= expected_citations
                or has_forbidden_conclusion
            ):
                unsupported_claim_count += 1
            observed_citations.extend(claim_citations)
        citation_count += len(observed_citations)
        correct_citations += sum(item in expected_citations for item in observed_citations)
        observed_unique = set(observed_citations)
        expected_count += len(expected_citations)
        complete_expected += len(expected_citations & observed_unique)
        refusal_checks.append(
            (case.expected_disposition == "refused") == (observed.outcome == "refused")
            and (
                case.expected_disposition != "refused"
                or observed.error_code == case.expected_error_code
            )
        )
        if case.expected_disposition == "needs_information":
            missing_checks.append(observed.missing_information == case.expected_missing_fields)

    if not retrieval_recalls or not cross_hits or not citation_count or not expected_count:
        raise GroundedRagEvaluationError("release metric denominator is empty")
    if not factual_claim_count or not missing_checks or not refusal_checks:
        raise GroundedRagEvaluationError("grounded metric denominator is empty")
    unsupported_rate = unsupported_claim_count / factual_claim_count
    counts = Counter(item.outcome for item in checked_observations.observations)
    return GroundedRagEvaluationReport(
        suite_sha256=_sha256(suite_bytes),
        observations_sha256=_sha256(
            canonical_grounded_rag_observations_bytes(checked_observations)
        ),
        retrieval_report_sha256=_sha256(retrieval_bytes),
        case_count=len(checked_suite.cases),
        answered_case_count=counts["answered"],
        needs_information_case_count=counts["needs_information"],
        refused_case_count=counts["refused"],
        factual_claim_count=factual_claim_count,
        citation_count=citation_count,
        metrics=GroundedRagMetrics(
            retrieval_recall_at_10=sum(retrieval_recalls) / len(retrieval_recalls),
            retrieval_mrr=sum(retrieval_rrs) / len(retrieval_rrs),
            citation_correctness=correct_citations / citation_count,
            citation_completeness=complete_expected / expected_count,
            unsupported_claim_rate=unsupported_rate,
            groundedness=1.0 - unsupported_rate,
            refusal_correctness=sum(refusal_checks) / len(refusal_checks),
            missing_information_correctness=sum(missing_checks) / len(missing_checks),
            cross_language_hit_rate_at_10=sum(cross_hits) / len(cross_hits),
        ),
    )


def evaluate_grounded_rag_gate(
    policy: GroundedRagGatePolicy,
    suite: GroundedRagEvaluationSuite,
    observations: GroundedRagObservationSet,
    retrieval_report: RetrievalEvaluationReport,
    retrieval_benchmark: RetrievalBenchmark,
    expected_report: GroundedRagEvaluationReport,
    repository_root: str | Path,
) -> GroundedRagGateResult:
    """Recompute the release report, bind every input hash, and enforce approved thresholds."""

    checked_policy = GroundedRagGatePolicy.model_validate(policy.model_dump(mode="json"))
    actual = evaluate_grounded_rag_release(
        suite, observations, retrieval_report, retrieval_benchmark
    )
    expected = GroundedRagEvaluationReport.model_validate(expected_report.model_dump(mode="json"))
    actual_bytes = canonical_grounded_rag_report_bytes(actual)
    expected_bytes = canonical_grounded_rag_report_bytes(expected)
    suite_hash = _sha256(canonical_grounded_rag_suite_bytes(suite))
    observations_hash = _sha256(canonical_grounded_rag_observations_bytes(observations))
    retrieval_hash = _sha256(_canonical_model_bytes(retrieval_report))
    benchmark_hash = _sha256(_canonical_model_bytes(retrieval_benchmark))
    report_hash = _sha256(expected_bytes)
    implementation_paths, implementation_hash = implementation_contract(
        repository_root, checked_policy.implementation_paths
    )
    if implementation_paths != checked_policy.implementation_paths:
        raise ImplementationContractError(
            "grounded RAG implementation path set no longer matches the policy"
        )
    checks = [
        _gate_check("suite_sha256", suite_hash, "==", checked_policy.suite_sha256),
        _gate_check(
            "observations_sha256",
            observations_hash,
            "==",
            checked_policy.observations_sha256,
        ),
        _gate_check(
            "retrieval_benchmark_sha256",
            benchmark_hash,
            "==",
            checked_policy.retrieval_benchmark_sha256,
        ),
        _gate_check(
            "retrieval_report_sha256",
            retrieval_hash,
            "==",
            checked_policy.retrieval_report_sha256,
        ),
        _gate_check("report_sha256", report_hash, "==", checked_policy.report_sha256),
        _gate_check(
            "implementation_sha256",
            implementation_hash,
            "==",
            checked_policy.implementation_sha256,
        ),
        _gate_check("report_recomputed", _sha256(actual_bytes), "==", report_hash),
        _gate_check("case_count", actual.case_count, ">=", checked_policy.minimum_case_count),
    ]
    for field_name in GroundedRagMetricFloors.model_fields:
        checks.append(
            _gate_check(
                field_name,
                getattr(actual.metrics, field_name),
                ">=",
                getattr(checked_policy.metric_floors, field_name),
            )
        )
    checks.append(
        _gate_check(
            "unsupported_claim_rate",
            actual.metrics.unsupported_claim_rate,
            "<=",
            checked_policy.unsupported_claim_rate_ceiling,
        )
    )
    failures = tuple(sorted(item.code for item in checks if not item.passed))
    return GroundedRagGateResult(
        passed=not failures,
        checks=tuple(checks),
        failure_codes=failures,
    )


def canonical_grounded_rag_suite_bytes(suite: GroundedRagEvaluationSuite) -> bytes:
    return _canonical_typed_bytes(suite, GroundedRagEvaluationSuite, "evaluation suite")


def canonical_grounded_rag_observations_bytes(observations: GroundedRagObservationSet) -> bytes:
    return _canonical_typed_bytes(observations, GroundedRagObservationSet, "observations")


def canonical_grounded_rag_report_bytes(report: GroundedRagEvaluationReport) -> bytes:
    return _canonical_typed_bytes(report, GroundedRagEvaluationReport, "evaluation report")


def canonical_grounded_rag_policy_bytes(policy: GroundedRagGatePolicy) -> bytes:
    return _canonical_typed_bytes(policy, GroundedRagGatePolicy, "evaluation policy")


def canonical_retrieval_benchmark_bytes(benchmark: RetrievalBenchmark) -> bytes:
    return _canonical_typed_bytes(benchmark, RetrievalBenchmark, "retrieval benchmark")


def canonical_grounded_rag_gate_result_bytes(result: GroundedRagGateResult) -> bytes:
    return _canonical_typed_bytes(result, GroundedRagGateResult, "evaluation gate result")


def load_grounded_rag_suite_bytes(raw_bytes: bytes) -> GroundedRagEvaluationSuite:
    return _load_bytes(raw_bytes, GroundedRagEvaluationSuite, "evaluation suite")


def load_grounded_rag_observations_bytes(raw_bytes: bytes) -> GroundedRagObservationSet:
    return _load_bytes(raw_bytes, GroundedRagObservationSet, "observations")


def load_grounded_rag_report_bytes(raw_bytes: bytes) -> GroundedRagEvaluationReport:
    return _load_bytes(raw_bytes, GroundedRagEvaluationReport, "evaluation report")


def load_grounded_rag_policy_bytes(raw_bytes: bytes) -> GroundedRagGatePolicy:
    return _load_bytes(raw_bytes, GroundedRagGatePolicy, "evaluation policy")


def load_retrieval_benchmark_bytes(raw_bytes: bytes) -> RetrievalBenchmark:
    return _load_bytes(raw_bytes, RetrievalBenchmark, "retrieval benchmark")


def read_regular_file_bytes(path_value: str | Path, *, label: str) -> bytes:
    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        raise GroundedRagEvaluationError(f"{label} path is missing or unsafe")
    try:
        return path.read_bytes()
    except OSError:
        raise GroundedRagEvaluationError(f"{label} path cannot be read") from None


def _canonical_typed_bytes(value, model_type, label: str) -> bytes:
    try:
        checked = model_type.model_validate(value.model_dump(mode="json"))
    except Exception:
        raise GroundedRagEvaluationError(f"{label} is invalid") from None
    return _canonical_model_bytes(checked)


def _canonical_model_bytes(value: BaseModel) -> bytes:
    return (
        json.dumps(
            value.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _load_bytes(raw_bytes: bytes, model_type, label: str):
    try:
        value = json.loads(raw_bytes.decode("utf-8"))
        checked = model_type.model_validate(value)
        if raw_bytes != _canonical_model_bytes(checked):
            raise ValueError
        return checked
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError, ValueError):
        raise GroundedRagEvaluationError(f"{label} is invalid or non-canonical") from None


def _sha256(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def _gate_check(code: str, observed, comparator: str, threshold) -> GroundedRagGateCheck:
    passed = {
        "==": observed == threshold,
        ">=": observed >= threshold,
        "<=": observed <= threshold,
    }[comparator]
    return GroundedRagGateCheck(
        code=code,
        observed=observed,
        comparator=comparator,
        threshold=threshold,
        passed=passed,
    )


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("value must be a lowercase SHA-256")


def _validate_trimmed(value: str) -> None:
    if not value or value != value.strip():
        raise ValueError("value must be a non-empty trimmed string")
