from __future__ import annotations

import json

import pytest

from jgrad_admission_rag.reasoning.applicant_report import (
    ApplicantReport,
    render_applicant_report_markdown,
)
from tests.test_rule01a_real import _report
from tests.test_rule04b_real import _submission_profile

pytestmark = pytest.mark.real_pdf
pytest_plugins = ("tests.test_rule04b_real",)


def _information_profile(year: int, month: int, route: str | None) -> dict[str, object]:
    profile = _submission_profile("情報工学系", year, month, method="with_application")
    profile["target_application"]["application_route"] = route
    return profile


def test_information_engineering_usage_binding_matches_exact_reviewed_fact(rule04b_kb) -> None:
    fact = next(item for item in rule04b_kb.facts if item.fact_id == "fact:00288")

    assert fact.source_pages == [52]
    assert fact.scope_type == "department"
    assert fact.scope_targets == ["情報工学系"]
    assert fact.parent_college == "情報理工学院"
    assert "筆答試験は実施せず" in fact.text
    assert "英語成績" in fact.text
    assert "（英語外部試験）の上位者を口頭試" in fact.text
    assert "問の対象とします" in fact.text
    assert "頭試問の結果を総合的に評価" in fact.text


@pytest.mark.parametrize(("year", "month"), ((2026, 9), (2027, 4)))
def test_information_engineering_b_schedule_uses_are_stable_for_both_intakes(
    rule04b_client, year, month
) -> None:
    client, document_id = rule04b_client
    report = _report(
        client,
        document_id,
        _information_profile(year, month, "b_schedule"),
        f"information-evaluation-{year}-{month}",
    )
    result = report["language_evaluation"]

    assert result["status"] == "confirmed"
    assert result["target"] == "情報工学系"
    assert result["parent_college"] == "情報理工学院"
    assert result["application_route"] == "b_schedule"
    assert result["assessment_source"] == "external_score"
    assert result["no_internal_written_exam"] is True
    assert result["evaluation_uses"] == [
        "oral_exam_candidate_selection",
        "final_holistic_evaluation",
    ]
    assert result["result_scale"] is None
    assert result["required_for_all"] is None
    assert result["external_score_exemption"] is None
    assert result["selection_role"] is None
    assert result["evidence"]["fact_id"] == "fact:00288"
    assert result["evidence"]["source_pages"] == [52]
    assert "人数や閾値は公表されておらず" in result["limitation_statement"]
    assert "口頭試問資格" in result["limitation_statement"]

    allocation = report["language_score_allocation"]
    assert allocation["status"] == "confirmed"
    assert allocation["maximum_points"] == 100
    assert allocation["evidence"] == result["evidence"]

    evidence = next(
        item
        for item in report["evidence_bundle"]["evidence_records"]
        if item["fact_id"] == "fact:00288"
    )
    assert "筆答試験は実施せず" in evidence["text"]
    assert "（英語外部試験）の上位者を口頭試" in evidence["text"]
    assert "問の対象とします" in evidence["text"]
    markdown = render_applicant_report_markdown(ApplicantReport.model_validate(report))
    assert "external_score" in markdown
    assert "oral_exam_candidate_selection, final_holistic_evaluation" in markdown
    assert "fact:00288" in markdown
    assert "p.52" in markdown

    serialized = json.dumps(result, ensure_ascii=False)
    for forbidden in ("ranking_threshold", "oral_exam_eligibility", "applicant_result"):
        assert forbidden not in serialized


def test_information_engineering_missing_route_needs_information(rule04b_client) -> None:
    client, document_id = rule04b_client
    report = _report(
        client,
        document_id,
        _information_profile(2027, 4, None),
        "information-evaluation-missing-route",
    )
    result = report["language_evaluation"]

    assert result["status"] == "needs_information"
    assert result["application_route"] is None
    assert result["assessment_source"] is None
    assert result["evaluation_uses"] is None
    assert result["evidence"] is None
    assert "人数や閾値" not in result["limitation_statement"]
    markdown = render_applicant_report_markdown(ApplicantReport.model_validate(report))
    evaluation_section = markdown.split("## 志望系の英語評価方式", 1)[1].split(
        "## 公式根拠（原文）", 1
    )[0]
    assert "oral_exam_candidate_selection" not in evaluation_section
    assert "fact:00288" not in evaluation_section


@pytest.mark.parametrize(
    ("target", "parent", "route"),
    (
        ("情報工学系", "情報理工学院", "a_schedule"),
        ("数学系", "理学院", "b_schedule"),
        ("物理学系", "理学院", "b_schedule"),
        ("情報工学系", "工学院", "b_schedule"),
    ),
)
def test_nonmatching_scope_does_not_receive_information_engineering_uses(
    rule04b_client, target, parent, route
) -> None:
    client, document_id = rule04b_client
    profile = _submission_profile(target, 2027, 4, method="with_application")
    profile["target_application"]["graduate_school_or_college"] = parent
    profile["target_application"]["application_route"] = route
    report = _report(
        client,
        document_id,
        profile,
        f"information-evaluation-uncovered-{len(target)}-{len(parent)}",
    )
    result = report["language_evaluation"]

    if target == "数学系" and parent == "理学院":
        assert result["status"] == "confirmed"
        assert result["assessment_source"] == "written_exam"
        assert result["evaluation_uses"] == []
        assert "人数や閾値" not in result["limitation_statement"]
        return
    assert result["status"] == "not_covered"
    assert result["assessment_source"] is None
    assert result["evaluation_uses"] is None
    assert result["evidence"] is None
    assert "人数や閾値" not in result["limitation_statement"]
    assert "数学筆答試験と口頭試問" not in result["limitation_statement"]
    markdown = render_applicant_report_markdown(ApplicantReport.model_validate(report))
    evaluation_section = markdown.split("## 志望系の英語評価方式", 1)[1].split(
        "## 公式根拠（原文）", 1
    )[0]
    assert "oral_exam_candidate_selection" not in evaluation_section
    assert "fact:00288" not in evaluation_section
