"""Record M9-05 observations from a running formal service after human review.

This script never synthesizes observations from expected values. Start the fixed-PDF,
cache-only BGE-M3 demo first, then pass its loopback URL explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

from jgrad_admission_rag.evaluation.grounded_rag_evaluation import (
    GroundedRagEvaluationSuite,
    GroundedRagObservationSet,
    canonical_grounded_rag_observations_bytes,
    canonical_grounded_rag_report_bytes,
    canonical_grounded_rag_suite_bytes,
    canonical_retrieval_benchmark_bytes,
    evaluate_grounded_rag_release,
    load_retrieval_benchmark_bytes,
    project_grounded_answer,
    refusal_observation,
)
from jgrad_admission_rag.evaluation.retrieval_evaluation import (
    canonical_retrieval_evaluation_bytes,
    load_retrieval_evaluation_bytes,
)
from jgrad_admission_rag.generation.grounded_rag import GroundedAnswer

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
SUITE_PATH = FIXTURES / "grounded_rag_evaluation_suite_v1.json"
OBSERVATIONS_PATH = FIXTURES / "grounded_rag_observations_v1.json"
REPORT_PATH = FIXTURES / "grounded_rag_evaluation_report_v1.json"
RETRIEVAL_REPORT_PATH = FIXTURES / "grounded_rag_retrieval_report_v1.json"
RETRIEVAL_BENCHMARK_PATH = FIXTURES / "grounded_rag_retrieval_queries_v1.json"
TARGET = {
    "schema_version": "1.0",
    "school_id": "isct",
    "document_id": "isct_2027_4_2026_9_master",
    "degree_id": "master",
    "intake": {"year": 2027, "month": 4},
    "college_id": "情報理工学院",
    "department_id": "情報工学系",
    "application_route": "b_schedule",
}
SYNTHETIC_APPLICANTS = {
    "rag:0001": {
        "credential_basis": "foreign_16_year_bachelor_equivalent",
        "completion_state": "expected",
    },
    "rag:0007": {
        "english_test_kind": "toefl_ibt",
        "english_official_report_available": False,
    },
    "rag:0016": {
        "credential_basis": "foreign_16_year_bachelor_equivalent",
        "completion_state": "expected",
    },
}
CASE_REVISIONS = {
    "rag:0001": {
        "expected_disposition": "refused",
        "expected_evidence": [],
        "expected_missing_fields": [],
        "expected_error_code": "insufficient_evidence",
    },
    "rag:0002": {
        "retrieval_query_id": "rq:0039",
        "category": "english",
        "question": "TOEFLの有効な種類を教えてください。",
        "expected_disposition": "answered",
        "expected_evidence": [{"fact_id": "fact:00111", "source_pages": [11]}],
        "expected_missing_fields": [],
        "expected_error_code": None,
        "applicant": {
            "english_test_kind": "toefl_ibt",
            "english_official_report_available": True,
        },
    },
    "rag:0003": {
        "expected_disposition": "needs_information",
        "expected_evidence": [{"fact_id": "fact:00086", "source_pages": [8]}],
        "expected_missing_fields": ["academic_credentials.first.credential_basis"],
        "expected_error_code": None,
    },
    "rag:0004": {
        "retrieval_query_id": "rq:0040",
        "category": "english",
        "question": "英語外部試験としてTOEFL iBTは認められますか。",
        "expected_disposition": "answered",
        "expected_evidence": [{"fact_id": "fact:00111", "source_pages": [11]}],
        "expected_missing_fields": [],
        "expected_error_code": None,
        "applicant": {
            "english_test_kind": "toefl_ibt",
            "english_official_report_available": True,
        },
    },
    "rag:0005": {
        "expected_evidence": [
            {"fact_id": "fact:00099", "source_pages": [9]},
            {"fact_id": "fact:00100", "source_pages": [9]},
        ],
    },
    "rag:0006": {
        "expected_disposition": "refused",
        "expected_evidence": [],
        "expected_missing_fields": [],
        "expected_error_code": "insufficient_evidence",
    },
    "rag:0007": {
        "question": "哪些 TOEFL 成绩有效，英语成绩单应当怎样提交？",
        "expected_disposition": "needs_information",
        "expected_evidence": [{"fact_id": "fact:00111", "source_pages": [11]}],
        "expected_missing_fields": [
            "language_test_results.selected.toefl_test_taker_score_report_pdf"
        ],
        "expected_error_code": None,
    },
    "rag:0008": {
        "expected_evidence": [{"fact_id": "fact:00122", "source_pages": [12]}],
    },
    "rag:0009": {"expected_error_code": "unsupported_question"},
    "rag:0010": {
        "retrieval_query_id": None,
        "expected_disposition": "refused",
        "expected_evidence": [],
        "expected_missing_fields": [],
        "expected_error_code": "unsupported_question",
    },
    "rag:0011": {
        "expected_disposition": "refused",
        "expected_evidence": [],
        "expected_missing_fields": [],
        "expected_error_code": "unsupported_question",
    },
    "rag:0012": {
        "retrieval_query_id": None,
        "expected_disposition": "refused",
        "expected_evidence": [],
        "expected_missing_fields": [],
        "expected_error_code": "unsupported_question",
    },
    "rag:0013": {
        "retrieval_query_id": None,
        "expected_disposition": "refused",
        "expected_evidence": [],
        "expected_missing_fields": [],
        "expected_error_code": "unsupported_question",
    },
    "rag:0014": {
        "expected_evidence": [{"fact_id": "fact:00069", "source_pages": [7]}],
        "expected_missing_fields": [
            "academic_credentials.first.completion_date",
            "academic_credentials.first.completion_state",
            "academic_credentials.first.credential_basis",
            "academic_credentials.first.expected_completion_date",
            "academic_credentials.first.graduate_equivalent_recognition_status",
            "academic_credentials.first.ministerial_completion_deadline_status",
            "academic_credentials.first.ministerial_course_standard_status",
            "academic_credentials.first.prior_education_category",
            "academic_credentials.first.program_duration_years",
            "academic_credentials.first.sixteen_year_equivalence_status",
            "eligibility_facts.age_at_eligibility_cutoff",
        ],
    },
    "rag:0015": {
        "expected_disposition": "needs_information",
        "expected_evidence": [
            {"fact_id": "fact:00114", "source_pages": [11]},
            {"fact_id": "fact:00122", "source_pages": [12]},
        ],
        "expected_missing_fields": ["language_test_results.selected.test_date"],
        "expected_error_code": None,
    },
    "rag:0016": {
        "expected_disposition": "refused",
        "expected_evidence": [],
        "expected_missing_fields": [],
        "expected_error_code": "unsupported_question",
    },
    "rag:0017": {
        "retrieval_query_id": "rq:0041",
        "category": "english",
        "question": "TOEFL iBT Home Editionは有効ですか。",
        "expected_disposition": "answered",
        "expected_evidence": [{"fact_id": "fact:00111", "source_pages": [11]}],
        "expected_missing_fields": [],
        "expected_error_code": None,
        "applicant": {
            "english_test_kind": "toefl_ibt",
            "english_official_report_available": True,
        },
    },
    "rag:0019": {"expected_error_code": "unsupported_question"},
    "rag:0020": {
        "retrieval_query_id": "rq:0042",
        "category": "application_dates",
        "question": "出願期間と書類必着日はいつですか。",
        "expected_disposition": "answered",
        "expected_evidence": [
            {"fact_id": "fact:00099", "source_pages": [9]},
            {"fact_id": "fact:00100", "source_pages": [9]},
        ],
        "expected_missing_fields": [],
        "expected_error_code": None,
        "applicant": {},
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    if args.base_url not in {"http://127.0.0.1:8125", "http://localhost:8125"}:
        raise SystemExit("fixture recording is restricted to the reviewed loopback service")

    raw_suite = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    retrieval = load_retrieval_evaluation_bytes(RETRIEVAL_REPORT_PATH.read_bytes())
    benchmark = load_retrieval_benchmark_bytes(RETRIEVAL_BENCHMARK_PATH.read_bytes())
    raw_suite.setdefault("target", TARGET)
    raw_suite["source_kb_sha256"] = retrieval.runtime.source_kb_sha256
    raw_suite["retrieval_benchmark_sha256"] = hashlib.sha256(
        canonical_retrieval_benchmark_bytes(benchmark)
    ).hexdigest()
    raw_suite["retrieval_report_sha256"] = hashlib.sha256(
        canonical_retrieval_evaluation_bytes(retrieval)
    ).hexdigest()
    for item in raw_suite["cases"]:
        item.setdefault("applicant", SYNTHETIC_APPLICANTS.get(item["case_id"], {}))
        item.update(CASE_REVISIONS.get(item["case_id"], {}))
    suite = GroundedRagEvaluationSuite.model_validate(raw_suite)
    suite_bytes = canonical_grounded_rag_suite_bytes(suite)
    observations = GroundedRagObservationSet(
        suite_sha256=hashlib.sha256(suite_bytes).hexdigest(),
        observations=tuple(_observe(args.base_url, suite, case) for case in suite.cases),
    )
    report = evaluate_grounded_rag_release(suite, observations, retrieval, benchmark)
    SUITE_PATH.write_bytes(suite_bytes)
    OBSERVATIONS_PATH.write_bytes(canonical_grounded_rag_observations_bytes(observations))
    REPORT_PATH.write_bytes(canonical_grounded_rag_report_bytes(report))


def _observe(base_url: str, suite: GroundedRagEvaluationSuite, case):
    retrieval_payload, retrieval_status = _post(
        f"{base_url}/v1/corpus/query",
        {
            "schema_version": "1.0",
            "selection": {
                "schema_version": "1.0",
                "document_ids": [suite.document_id],
                "version_mode": "active_only",
                "allow_multiple_documents": False,
            },
            "search": {
                "query": case.question,
                "top_k": 12,
                "candidate_k": 48,
                "metadata_filter": {},
                "scope_preference": {
                    "preferred_scope_targets": [suite.target.department_id],
                    "preferred_parent_colleges": [suite.target.college_id],
                },
            },
        },
    )
    if retrieval_status != 200:
        raise RuntimeError("formal retrieval request failed")
    ranked = tuple(item["key"]["fact_id"] for item in retrieval_payload["hits"])
    payload, status = _post(
        f"{base_url}/v1/grounded-answers",
        {
            "schema_version": "1.0",
            "question": case.question,
            "target": suite.target.model_dump(mode="json"),
            "applicant": case.applicant.model_dump(mode="json"),
        },
    )
    if status != 200:
        return refusal_observation(case.case_id, payload["code"], ranked_retrieved_fact_ids=ranked)
    answer = GroundedAnswer.model_validate(payload["answer"])
    provider = answer.provider
    if (
        answer.document_id != suite.document_id
        or answer.source_kb_sha256 != suite.source_kb_sha256
        or answer.source_pdf_sha256 != suite.source_pdf_sha256
        or provider.provider != suite.generation_provider
        or provider.model != suite.generation_model
        or provider.revision != suite.generation_revision
        or provider.prompt_version != suite.prompt_version
    ):
        raise RuntimeError("formal response identity does not match the reviewed suite")
    return project_grounded_answer(case.case_id, ranked, answer)


def _post(url: str, payload: dict) -> tuple[dict, int]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8")), response.status
    except urllib.error.HTTPError as error:
        return json.loads(error.read().decode("utf-8")), error.code


if __name__ == "__main__":
    main()
