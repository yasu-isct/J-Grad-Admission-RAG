from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.evaluation.retrieval_queries import (
    RetrievalBenchmark,
    benchmark_coverage,
    load_retrieval_benchmark,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "retrieval_queries_v1.json"


def _payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_v1_fixture_loads_with_frozen_coverage() -> None:
    benchmark = load_retrieval_benchmark(FIXTURE_PATH)

    assert benchmark.schema_version == "1.0"
    assert benchmark.benchmark_id == "isct-master-retrieval-v1"
    assert benchmark.document_id == "isct_2027_4_2026_9_master"
    assert benchmark.source_pdf_sha256 == (
        "57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735"
    )
    assert benchmark.expected_kb_schema_version == "0.6"
    assert benchmark_coverage(benchmark) == {
        "total_queries": 34,
        "by_category": {
            "application_dates": 2,
            "contacts_forms": 2,
            "department_requirements": 4,
            "documents": 5,
            "eligibility": 3,
            "enrollment": 3,
            "fees": 3,
            "language_tests": 4,
            "results": 2,
            "selection_exams": 6,
        },
        "by_style": {"exact_term": 7, "identifier": 6, "paraphrase": 21},
        "by_scope": {"department": 25, "global": 10, "unknown": 70},
        "single_fact_queries": 5,
        "multi_fact_queries": 29,
        "single_clause_queries": 27,
        "multiple_clause_queries": 7,
        "scope_sensitive_queries": 9,
        "reference_expansion_queries": 1,
    }


def test_loader_returns_independent_mutable_collections() -> None:
    first = load_retrieval_benchmark(FIXTURE_PATH)
    second = load_retrieval_benchmark(FIXTURE_PATH)

    first.queries[0].relevant_fact_ids.append("fact:99999")
    first.queries[0].gold_evidence[0].source_pages.append(999)

    assert "fact:99999" not in second.queries[0].relevant_fact_ids
    assert 999 not in second.queries[0].gold_evidence[0].source_pages


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(schema_version="2.0"), "schema_version"),
        (lambda value: value.update(annotation_policy_version="2.0"), "annotation_policy_version"),
        (lambda value: value.update(source_pdf_sha256="A" * 64), "SHA-256"),
        (lambda value: value.update(created_at="2026-09-02"), "Extra inputs"),
    ],
)
def test_dataset_contract_rejects_versions_hashes_and_extra_fields(mutation, message) -> None:
    payload = _payload()
    mutation(payload)

    with pytest.raises(ValidationError, match=message):
        RetrievalBenchmark.model_validate(payload)


def test_query_ids_must_be_contiguous_and_questions_non_duplicate_japanese() -> None:
    payload = _payload()
    payload["queries"][1]["query_id"] = "rq:0003"
    with pytest.raises(ValidationError, match="unique, contiguous"):
        RetrievalBenchmark.model_validate(payload)

    payload = _payload()
    payload["queries"][1]["query"] = payload["queries"][0]["query"] + "！？"
    with pytest.raises(ValidationError, match="trivial normalized duplicate"):
        RetrievalBenchmark.model_validate(payload)

    payload = _payload()
    payload["queries"][0]["query"] = "TOEFL 2026?"
    with pytest.raises(ValidationError, match="Japanese text"):
        RetrievalBenchmark.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("category", "ranking", "category"),
        ("query_style", "semantic", "query_style"),
        ("difficulty", "hard", "Extra inputs"),
    ],
)
def test_query_contract_rejects_unknown_controlled_values(field, value, message) -> None:
    payload = _payload()
    payload["queries"][0][field] = value

    with pytest.raises(ValidationError, match=message):
        RetrievalBenchmark.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda query: query.update(relevant_fact_ids=[]),
            "must not be empty",
        ),
        (
            lambda query: query.update(
                relevant_fact_ids=list(reversed(query["relevant_fact_ids"]))
            ),
            "sorted and unique",
        ),
        (
            lambda query: query["gold_evidence"].pop(),
            "exactly equal relevant_fact_ids",
        ),
        (
            lambda query: query["gold_evidence"][0].update(source_pages=[2, 1]),
            "sorted and unique",
        ),
        (
            lambda query: query["gold_evidence"][0].update(scope_type="course"),
            "scope_type",
        ),
    ],
)
def test_gold_contract_rejects_incomplete_or_invalid_evidence(mutation, message) -> None:
    payload = _payload()
    query = payload["queries"][0]
    mutation(query)

    with pytest.raises(ValidationError, match=message):
        RetrievalBenchmark.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(queries=value["queries"][:29]), "at least 30 queries"),
        (
            lambda value: [query.update(category="eligibility") for query in value["queries"]],
            "at least 8 categories",
        ),
        (
            lambda value: [query.update(query_style="exact_term") for query in value["queries"]],
            "at least 12 paraphrases",
        ),
        (
            lambda value: [query.update(query_style="paraphrase") for query in value["queries"]],
            "exact-term or identifier",
        ),
        (
            lambda value: [query.update(scope_sensitive=False) for query in value["queries"]],
            "scope-sensitive queries",
        ),
        (
            lambda value: [
                evidence.update(scope_type="unknown", scope_targets=[])
                for query in value["queries"]
                for evidence in query["gold_evidence"]
                if evidence["scope_type"] == "global"
            ],
            "cover global, department, and unknown scopes",
        ),
        (
            lambda value: [
                query.update(requires_multiple_clauses=False) for query in value["queries"]
            ],
            "multiple-clause queries",
        ),
    ],
)
def test_dataset_coverage_gates_reject_underfilled_benchmarks(mutation, message) -> None:
    payload = _payload()
    mutation(payload)

    with pytest.raises(ValidationError, match=message):
        RetrievalBenchmark.model_validate(payload)


def test_scope_sensitive_and_multiple_clause_flags_have_structural_evidence() -> None:
    payload = _payload()
    scope_query = next(query for query in payload["queries"] if query["scope_sensitive"])
    scope_query["gold_evidence"] = [
        {**evidence, "scope_type": "unknown", "scope_targets": []}
        for evidence in scope_query["gold_evidence"]
    ]
    with pytest.raises(ValidationError, match="department-scoped evidence"):
        RetrievalBenchmark.model_validate(payload)

    payload = _payload()
    query = deepcopy(payload["queries"][0])
    query["requires_multiple_clauses"] = True
    query["relevant_fact_ids"] = [query["relevant_fact_ids"][0]]
    query["gold_evidence"] = [query["gold_evidence"][0]]
    payload["queries"][0] = query
    with pytest.raises(ValidationError, match="at least two relevant Facts"):
        RetrievalBenchmark.model_validate(payload)

    payload = _payload()
    payload["queries"][0]["requires_reference_expansion"] = "yes"
    with pytest.raises(ValidationError, match="valid boolean"):
        RetrievalBenchmark.model_validate(payload)
