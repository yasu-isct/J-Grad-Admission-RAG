from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..schemas.document_kb import ScopeType

RETRIEVAL_BENCHMARK_SCHEMA_VERSION = "1.0"
ANNOTATION_POLICY_VERSION = "1.0"
MINIMUM_QUERY_COUNT = 30
MINIMUM_CATEGORY_COUNT = 8
MINIMUM_PARAPHRASE_COUNT = 12
MINIMUM_EXACT_OR_IDENTIFIER_COUNT = 6
MINIMUM_SCOPE_SENSITIVE_COUNT = 5
MINIMUM_MULTIPLE_CLAUSE_COUNT = 5
REQUIRED_SCOPE_TYPES = frozenset({"global", "department", "unknown"})

QueryCategory = Literal[
    "eligibility",
    "application_dates",
    "fees",
    "documents",
    "language_tests",
    "selection_exams",
    "results",
    "enrollment",
    "contacts_forms",
    "department_requirements",
]
QueryStyle = Literal["paraphrase", "exact_term", "identifier"]

_FACT_ID_RE = re.compile(r"fact:\d{5}\Z")
_QUERY_ID_RE = re.compile(r"rq:\d{4}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_TRIVIAL_QUERY_CHAR_RE = re.compile(r"[^0-9A-Za-z\u3040-\u30ff\u3400-\u9fff]+")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GoldEvidence(_StrictModel):
    fact_id: str
    source_pages: list[int]
    scope_type: ScopeType
    scope_targets: list[str] = Field(default_factory=list)

    @field_validator("fact_id")
    @classmethod
    def fact_id_must_be_stable(cls, value: str) -> str:
        if _FACT_ID_RE.fullmatch(value) is None:
            raise ValueError("fact_id must use the stable fact:00000 form")
        return value

    @field_validator("source_pages")
    @classmethod
    def pages_must_be_positive_sorted_and_unique(cls, pages: list[int]) -> list[int]:
        if not pages or any(page <= 0 for page in pages):
            raise ValueError("source_pages must contain positive official page numbers")
        if pages != sorted(set(pages)):
            raise ValueError("source_pages must be sorted and unique")
        return pages

    @field_validator("scope_targets")
    @classmethod
    def scope_targets_must_be_clean(cls, targets: list[str]) -> list[str]:
        if any(not target or target != target.strip() for target in targets):
            raise ValueError("scope_targets must contain non-empty trimmed strings")
        if len(targets) != len(set(targets)):
            raise ValueError("scope_targets must be unique")
        return targets


class RetrievalQuery(_StrictModel):
    query_id: str
    query: str
    category: QueryCategory
    query_style: QueryStyle
    relevant_fact_ids: list[str]
    gold_evidence: list[GoldEvidence]
    annotation_note: str
    scope_sensitive: bool = False
    requires_multiple_clauses: bool = False
    requires_reference_expansion: bool = False

    @field_validator("query_id")
    @classmethod
    def query_id_must_be_stable(cls, value: str) -> str:
        if _QUERY_ID_RE.fullmatch(value) is None:
            raise ValueError("query_id must use the stable rq:0001 form")
        return value

    @field_validator("query")
    @classmethod
    def query_must_be_natural_japanese(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("query must be a non-empty trimmed string")
        if _JAPANESE_RE.search(value) is None:
            raise ValueError("query must contain Japanese text")
        return value

    @field_validator("annotation_note")
    @classmethod
    def annotation_note_must_be_clean(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("annotation_note must be a non-empty trimmed string")
        return value

    @field_validator("relevant_fact_ids")
    @classmethod
    def relevant_fact_ids_must_be_sorted_unique(cls, fact_ids: list[str]) -> list[str]:
        if not fact_ids:
            raise ValueError("relevant_fact_ids must not be empty")
        if any(_FACT_ID_RE.fullmatch(fact_id) is None for fact_id in fact_ids):
            raise ValueError("relevant_fact_ids contains an invalid Fact ID")
        if fact_ids != sorted(set(fact_ids)):
            raise ValueError("relevant_fact_ids must be sorted and unique")
        return fact_ids

    @model_validator(mode="after")
    def evidence_must_match_declared_gold(self) -> RetrievalQuery:
        evidence_ids = [evidence.fact_id for evidence in self.gold_evidence]
        if evidence_ids != self.relevant_fact_ids:
            raise ValueError(
                "gold_evidence Fact IDs must exactly equal relevant_fact_ids in the same order"
            )
        if self.requires_multiple_clauses and len(self.relevant_fact_ids) < 2:
            raise ValueError("requires_multiple_clauses needs at least two relevant Facts")
        if self.scope_sensitive and not any(
            evidence.scope_type == "department" for evidence in self.gold_evidence
        ):
            raise ValueError("scope_sensitive queries must include department-scoped evidence")
        return self


class RetrievalBenchmark(_StrictModel):
    schema_version: Literal["1.0"]
    benchmark_id: str
    document_id: str
    source_pdf_sha256: str
    expected_kb_schema_version: str
    fact_content_sha256: str
    fact_structure_sha256: str
    language: Literal["ja"]
    annotation_policy_version: Literal["1.0"]
    queries: list[RetrievalQuery]

    @field_validator("benchmark_id", "document_id", "expected_kb_schema_version")
    @classmethod
    def identifiers_must_be_clean(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("identifier fields must be non-empty trimmed strings")
        return value

    @field_validator("source_pdf_sha256", "fact_content_sha256", "fact_structure_sha256")
    @classmethod
    def hashes_must_be_lowercase_sha256(cls, value: str) -> str:
        if _SHA256_RE.fullmatch(value) is None:
            raise ValueError("hash fields must be lowercase SHA-256 hex strings")
        return value

    @model_validator(mode="after")
    def queries_must_satisfy_v1_contract(self) -> RetrievalBenchmark:
        expected_ids = [f"rq:{position:04d}" for position in range(1, len(self.queries) + 1)]
        observed_ids = [query.query_id for query in self.queries]
        if observed_ids != expected_ids:
            raise ValueError("query IDs must be unique, contiguous, and in presentation order")

        normalized = [_normalize_query(query.query) for query in self.queries]
        if len(normalized) != len(set(normalized)):
            raise ValueError("queries contain a trivial normalized duplicate")

        coverage = benchmark_coverage(self)
        if coverage["total_queries"] < MINIMUM_QUERY_COUNT:
            raise ValueError(f"benchmark requires at least {MINIMUM_QUERY_COUNT} queries")
        if len(coverage["by_category"]) < MINIMUM_CATEGORY_COUNT:
            raise ValueError(f"benchmark requires at least {MINIMUM_CATEGORY_COUNT} categories")
        if coverage["by_style"].get("paraphrase", 0) < MINIMUM_PARAPHRASE_COUNT:
            raise ValueError(f"benchmark requires at least {MINIMUM_PARAPHRASE_COUNT} paraphrases")
        exact_or_identifier = coverage["by_style"].get("exact_term", 0) + coverage["by_style"].get(
            "identifier", 0
        )
        if exact_or_identifier < MINIMUM_EXACT_OR_IDENTIFIER_COUNT:
            raise ValueError(
                "benchmark requires at least "
                f"{MINIMUM_EXACT_OR_IDENTIFIER_COUNT} exact-term or identifier queries"
            )
        if not REQUIRED_SCOPE_TYPES.issubset(coverage["by_scope"]):
            raise ValueError("benchmark must cover global, department, and unknown scopes")
        if coverage["scope_sensitive_queries"] < MINIMUM_SCOPE_SENSITIVE_COUNT:
            raise ValueError(
                f"benchmark requires at least {MINIMUM_SCOPE_SENSITIVE_COUNT} scope-sensitive queries"
            )
        if coverage["multiple_clause_queries"] < MINIMUM_MULTIPLE_CLAUSE_COUNT:
            raise ValueError(
                "benchmark requires at least "
                f"{MINIMUM_MULTIPLE_CLAUSE_COUNT} genuine multiple-clause queries"
            )
        return self


def load_retrieval_benchmark(path: str | Path) -> RetrievalBenchmark:
    """Load and fully validate one versioned retrieval benchmark fixture."""

    return RetrievalBenchmark.model_validate_json(Path(path).read_bytes())


def benchmark_coverage(benchmark: RetrievalBenchmark) -> dict[str, object]:
    category_counts = Counter(query.category for query in benchmark.queries)
    style_counts = Counter(query.query_style for query in benchmark.queries)
    scope_counts = Counter(
        evidence.scope_type for query in benchmark.queries for evidence in query.gold_evidence
    )
    return {
        "total_queries": len(benchmark.queries),
        "by_category": dict(sorted(category_counts.items())),
        "by_style": dict(sorted(style_counts.items())),
        "by_scope": dict(sorted(scope_counts.items())),
        "single_fact_queries": sum(
            len(query.relevant_fact_ids) == 1 for query in benchmark.queries
        ),
        "multi_fact_queries": sum(len(query.relevant_fact_ids) > 1 for query in benchmark.queries),
        "single_clause_queries": sum(
            not query.requires_multiple_clauses for query in benchmark.queries
        ),
        "multiple_clause_queries": sum(
            query.requires_multiple_clauses for query in benchmark.queries
        ),
        "scope_sensitive_queries": sum(query.scope_sensitive for query in benchmark.queries),
        "reference_expansion_queries": sum(
            query.requires_reference_expansion for query in benchmark.queries
        ),
    }


def _normalize_query(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _TRIVIAL_QUERY_CHAR_RE.sub("", normalized)
