from __future__ import annotations

import pytest

from jgrad_admission_rag.reasoning.applicant_report import (
    ApplicantReport,
    render_applicant_report_markdown,
)
from tests.test_rule01a_real import _report
from tests.test_rule04b_real import _submission_profile

pytestmark = pytest.mark.real_pdf
pytest_plugins = ("tests.test_rule04b_real",)


def test_math_evaluation_binding_matches_exact_reviewed_fact(rule04b_kb) -> None:
    fact = next(item for item in rule04b_kb.facts if item.fact_id == "fact:00149")

    assert fact.source_pages == [19]
    assert fact.scope_type == "department"
    assert fact.scope_targets == ["数学系"]
    assert fact.parent_college == "理学院"
    assert "合格か不合格" in fact.text
    assert "必要条件" in fact.text


@pytest.mark.parametrize(("year", "month"), ((2026, 9), (2027, 4)))
def test_math_evaluation_metadata_is_stable_for_both_intakes(rule04b_client, year, month) -> None:
    client, document_id = rule04b_client
    profile = _submission_profile("数学系", year, month, method="no_external_submission")
    report = _report(client, document_id, profile, f"math-evaluation-{year}-{month}")
    result = report["language_evaluation"]

    assert result["status"] == "confirmed"
    assert result["target"] == "数学系"
    assert result["parent_college"] == "理学院"
    assert result["assessment_source"] == "written_exam"
    assert result["result_scale"] == "pass_fail"
    assert result["required_for_all"] is True
    assert result["external_score_exemption"] is False
    assert result["selection_role"] == "necessary_condition"
    assert result["evidence"]["fact_id"] == "fact:00149"
    assert result["evidence"]["source_pages"] == [19]
    assert "数学筆答試験と口頭試問" in result["limitation_statement"]
    assert "最終合格者を決定" in result["limitation_statement"]
    evidence = next(
        item
        for item in report["evidence_bundle"]["evidence_records"]
        if item["fact_id"] == "fact:00149"
    )
    assert "合格か不合格" in evidence["text"]
    assert "必要条件" in evidence["text"]
    markdown = render_applicant_report_markdown(ApplicantReport.model_validate(report))
    assert "数学筆答試験と口頭試問" in markdown
    assert "fact:00149" in markdown
    assert "p.19" in markdown
    assert "maximum_points" not in result
    assert "applicant_result" not in result
    assert report["language_score_allocation"]["status"] == "not_covered"
    assert report["language_score_allocation"]["maximum_points"] is None


@pytest.mark.parametrize("target", ("物理学系", "情報工学系", "建築学系"))
def test_other_departments_do_not_receive_math_evaluation(rule04b_client, target) -> None:
    client, document_id = rule04b_client
    profile = _submission_profile(target, 2027, 4, method="with_application")
    report = _report(client, document_id, profile, f"math-evaluation-uncovered-{len(target)}")
    result = report["language_evaluation"]

    assert result["status"] == "not_covered"
    assert result["assessment_source"] is None
    assert result["selection_role"] is None
    assert result["evidence"] is None
    assert "数学筆答試験と口頭試問" not in result["limitation_statement"]
    assert "対象系の公式規則は別途確認" in result["limitation_statement"]


def test_wrong_parent_college_cannot_receive_math_evaluation(rule04b_client) -> None:
    client, document_id = rule04b_client
    profile = _submission_profile("数学系", 2027, 4, method="no_external_submission")
    profile["target_application"]["graduate_school_or_college"] = "工学院"
    report = _report(client, document_id, profile, "math-evaluation-parent-conflict")
    result = report["language_evaluation"]

    assert result["status"] == "not_covered"
    assert result["evidence"] is None
    assert "数学筆答試験と口頭試問" not in result["limitation_statement"]
