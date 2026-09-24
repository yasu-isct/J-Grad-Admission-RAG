from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.cli.check_grounded_rag_gate import main as gate_main
from jgrad_admission_rag.cli.manual_generation_evaluation import main as manual_main
from jgrad_admission_rag.evaluation.grounded_rag_evaluation import (
    GroundedRagEvaluationError,
    GroundedRagEvaluationSuite,
    canonical_grounded_rag_observations_bytes,
    canonical_grounded_rag_report_bytes,
    canonical_grounded_rag_suite_bytes,
    evaluate_grounded_rag_gate,
    evaluate_grounded_rag_release,
    load_grounded_rag_observations_bytes,
    load_grounded_rag_policy_bytes,
    load_grounded_rag_report_bytes,
    load_grounded_rag_suite_bytes,
    load_retrieval_benchmark_bytes,
    project_grounded_answer,
)
from jgrad_admission_rag.evaluation.retrieval_evaluation import (
    load_retrieval_evaluation_bytes,
)
from tests.test_grounded_rag import _draft, _run

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
SUITE = FIXTURES / "grounded_rag_evaluation_suite_v1.json"
OBSERVATIONS = FIXTURES / "grounded_rag_observations_v1.json"
RETRIEVAL = FIXTURES / "grounded_rag_retrieval_report_v1.json"
BENCHMARK = FIXTURES / "grounded_rag_retrieval_queries_v1.json"
REPORT = FIXTURES / "grounded_rag_evaluation_report_v1.json"
POLICY = ROOT / "config/grounded_rag_release_gate_v1.json"


def _inputs():
    return (
        load_grounded_rag_policy_bytes(POLICY.read_bytes()),
        load_grounded_rag_suite_bytes(SUITE.read_bytes()),
        load_grounded_rag_observations_bytes(OBSERVATIONS.read_bytes()),
        load_retrieval_evaluation_bytes(RETRIEVAL.read_bytes()),
        load_retrieval_benchmark_bytes(BENCHMARK.read_bytes()),
        load_grounded_rag_report_bytes(REPORT.read_bytes()),
    )


def test_release_suite_is_canonical_reviewed_and_covers_required_behavior() -> None:
    _, suite, observations, retrieval, _, report = _inputs()
    assert SUITE.read_bytes() == canonical_grounded_rag_suite_bytes(suite)
    assert OBSERVATIONS.read_bytes() == canonical_grounded_rag_observations_bytes(observations)
    assert REPORT.read_bytes() == canonical_grounded_rag_report_bytes(report)
    assert len(suite.cases) == 20
    assert {item.language for item in suite.cases} == {"ja", "zh"}
    assert sum(item.cross_language for item in suite.cases) == 4
    assert {item.expected_disposition for item in suite.cases} == {
        "answered",
        "needs_information",
        "refused",
    }
    assert retrieval.runtime.embedding_model == "BAAI/bge-m3"
    assert retrieval.runtime.embedding_revision == "5617a9f61b028005a4858fdac845db406aefb181"


def test_release_gate_recomputes_every_metric_and_passes_approved_thresholds() -> None:
    policy, suite, observations, retrieval, benchmark, report = _inputs()
    recomputed = evaluate_grounded_rag_release(suite, observations, retrieval, benchmark)
    assert canonical_grounded_rag_report_bytes(recomputed) == REPORT.read_bytes()
    result = evaluate_grounded_rag_gate(
        policy, suite, observations, retrieval, benchmark, report, ROOT
    )
    assert result.passed
    assert result.failure_codes == ()
    assert recomputed.metrics.citation_correctness == 1
    assert recomputed.metrics.citation_completeness == 1
    assert recomputed.metrics.unsupported_claim_rate == 0
    assert recomputed.metrics.groundedness == 1
    assert recomputed.metrics.refusal_correctness == 1
    assert recomputed.metrics.missing_information_correctness == 1
    assert recomputed.metrics.cross_language_hit_rate_at_10 == 0.5


def test_foreign_citation_and_forbidden_conclusion_fail_the_gate() -> None:
    policy, suite, observations, retrieval, benchmark, report = _inputs()
    payload = observations.model_dump(mode="json")
    for claim in payload["observations"][1]["claims"]:
        for citation in claim["citations"]:
            citation["fact_id"] = "fact:99999"
    payload["observations"][2]["claims"][0]["text"] = "材料已受理"
    tampered = type(observations).model_validate(payload)
    evaluated = evaluate_grounded_rag_release(suite, tampered, retrieval, benchmark)
    assert evaluated.metrics.citation_correctness < 1
    assert evaluated.metrics.citation_completeness < 1
    assert evaluated.metrics.unsupported_claim_rate > 0
    gate = evaluate_grounded_rag_gate(policy, suite, tampered, retrieval, benchmark, report, ROOT)
    assert not gate.passed
    assert {
        "citation_correctness",
        "citation_completeness",
        "groundedness",
        "observations_sha256",
        "report_recomputed",
        "unsupported_claim_rate",
    } <= set(gate.failure_codes)


def test_suite_and_observation_bindings_fail_closed() -> None:
    _, suite, observations, retrieval, benchmark, _ = _inputs()
    payload = suite.model_dump(mode="json")
    payload["cases"][0]["unknown"] = True
    with pytest.raises(ValidationError):
        GroundedRagEvaluationSuite.model_validate(payload)

    detached = observations.model_copy(update={"suite_sha256": "0" * 64})
    with pytest.raises(GroundedRagEvaluationError, match="suite binding"):
        evaluate_grounded_rag_release(suite, detached, retrieval, benchmark)


def test_release_query_binding_and_recorded_rankings_are_authoritative() -> None:
    _, suite, observations, retrieval, benchmark, _ = _inputs()
    suite_payload = suite.model_dump(mode="json")
    suite_payload["cases"][6]["question"] = "哪些 TOEFL 成绩有效？"
    mismatched_suite = GroundedRagEvaluationSuite.model_validate(suite_payload)
    rebound_observations = observations.model_copy(
        update={
            "suite_sha256": hashlib.sha256(
                canonical_grounded_rag_suite_bytes(mismatched_suite)
            ).hexdigest()
        }
    )
    with pytest.raises(GroundedRagEvaluationError, match="does not match"):
        evaluate_grounded_rag_release(mismatched_suite, rebound_observations, retrieval, benchmark)

    baseline = evaluate_grounded_rag_release(suite, observations, retrieval, benchmark)
    observation_payload = observations.model_dump(mode="json")
    observation_payload["observations"][19]["ranked_retrieved_fact_ids"] = [
        "fact:99998",
        "fact:99999",
    ]
    degraded_observations = type(observations).model_validate(observation_payload)
    degraded = evaluate_grounded_rag_release(suite, degraded_observations, retrieval, benchmark)
    assert degraded.metrics.retrieval_recall_at_10 < baseline.metrics.retrieval_recall_at_10
    assert degraded.metrics.retrieval_mrr < baseline.metrics.retrieval_mrr


def test_release_gate_binds_the_implementation_contract() -> None:
    policy, suite, observations, retrieval, benchmark, report = _inputs()
    tampered_policy = policy.model_copy(update={"implementation_sha256": "0" * 64})
    result = evaluate_grounded_rag_gate(
        tampered_policy, suite, observations, retrieval, benchmark, report, ROOT
    )
    assert not result.passed
    assert "implementation_sha256" in result.failure_codes


def test_projection_accepts_only_server_validated_grounded_answer_state() -> None:
    answer = _run(_draft())
    observation = project_grounded_answer(
        "rag:0001",
        (),
        answer,
    )
    assert observation.source == "server-hydrated-grounded-answer-v1"
    assert observation.outcome == "answered"
    assert {citation.fact_id for claim in observation.claims for citation in claim.citations} == {
        "fact:primary",
        "fact:attached",
    }
    assert all(
        citation.document_id == answer.document_id
        for claim in observation.claims
        for citation in claim.citations
    )


def test_gate_cli_passes_and_noncanonical_input_exits_two(tmp_path: Path, capsys) -> None:
    arguments = [
        "--suite",
        str(SUITE),
        "--observations",
        str(OBSERVATIONS),
        "--retrieval-report",
        str(RETRIEVAL),
        "--retrieval-benchmark",
        str(BENCHMARK),
        "--report",
        str(REPORT),
        "--policy",
        str(POLICY),
        "--repository-root",
        str(ROOT),
    ]
    with pytest.raises(SystemExit) as passed:
        gate_main(arguments)
    assert passed.value.code == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True

    noncanonical = tmp_path / "suite.json"
    noncanonical.write_text(
        json.dumps(json.loads(SUITE.read_text(encoding="utf-8"))), encoding="utf-8"
    )
    arguments[1] = str(noncanonical)
    with pytest.raises(SystemExit) as failed:
        gate_main(arguments)
    assert failed.value.code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["kind"] == "grounded_rag_gate_error"
    assert "question" not in error["error"]


def test_paid_workflow_is_manual_bounded_and_protected() -> None:
    workflow = (ROOT / ".github/workflows/manual-paid-generation-evaluation.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "schedule:" not in workflow
    assert "I AUTHORIZE 20 PAID SYNTHETIC CALLS" in workflow
    assert "environment: paid-generation-evaluation" in workflow
    assert 'options: ["1", "5", "10", "20"]' in workflow
    assert "secrets.OPENAI_API_KEY" in workflow
    assert "JGRAD_ALLOW_PAID_EVALUATION" in workflow


def test_paid_evaluation_cli_refuses_before_provider_without_exact_guard(
    monkeypatch, capsys
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "not-used")
    monkeypatch.delenv("JGRAD_ALLOW_PAID_EVALUATION", raising=False)
    with pytest.raises(SystemExit) as stopped:
        manual_main(
            [
                "--suite",
                str(SUITE),
                "--model",
                "gpt-test",
                "--max-cases",
                "1",
                "--synthetic-only",
            ]
        )
    assert stopped.value.code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["kind"] == "manual_generation_evaluation_error"
    assert "authorization" in error["error"]
