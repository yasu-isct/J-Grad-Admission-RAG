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

PROGRAM = "東京科学大学・清華大学 大学院合同プログラム"


def _program_profile(year: int | None, month: int | None, route: str | None):
    profile = _submission_profile("情報工学系", year or 2027, month or 4, method="with_application")
    profile["target_application"]["intake_year"] = year
    profile["target_application"]["intake_month"] = month
    profile["target_application"]["application_route"] = route
    return profile


def test_tsinghua_program_scope_and_exact_reviewed_fact(rule04b_kb) -> None:
    facts = {item.fact_id: item for item in rule04b_kb.facts}
    fact = facts["fact:00347"]

    assert len(facts) == 391
    assert fact.source_pages == [76]
    assert fact.scope_type == "program"
    assert fact.scope_targets == [PROGRAM]
    assert fact.parent_college is None
    assert "入学試験では、中国語の語学力は選考対象外です" in fact.text
    assert facts["fact:00380"].source_pages == [79]
    assert facts["fact:00380"].scope_targets != [PROGRAM]
    assert facts["fact:00381"].scope_targets != [PROGRAM]


def test_exact_tsinghua_route_reports_only_chinese_selection_exclusion(rule04b_client) -> None:
    client, document_id = rule04b_client
    report = _report(
        client,
        document_id,
        _program_profile(2027, 4, "tsinghua_joint_program"),
        "tsinghua-program-language-confirmed",
    )
    result = report["program_language_condition"]

    assert result["status"] == "confirmed"
    assert result["application_route"] == "tsinghua_joint_program"
    assert result["requested_degree_level"] == "master"
    assert result["intake_year"] == 2027
    assert result["intake_month"] == 4
    assert result["program"] == PROGRAM
    assert result["language"] == "chinese"
    assert result["admission_selection"] == "excluded"
    assert result["evidence"]["fact_id"] == "fact:00347"
    assert result["evidence"]["source_pages"] == [76]
    assert "奨学金" in result["limitation_statement"]
    evidence = next(
        item
        for item in report["evidence_bundle"]["evidence_records"]
        if item["fact_id"] == "fact:00347"
    )
    assert evidence["scope_type"] == "program"
    assert evidence["scope_targets"] == [PROGRAM]
    assert "入学試験では、中国語の語学力は選考対象外です" in evidence["text"]
    confirmed_json = json.dumps(report, ensure_ascii=False)
    assert PROGRAM in confirmed_json
    assert "奨学金" in confirmed_json

    markdown = render_applicant_report_markdown(ApplicantReport.model_validate(report))
    section = markdown.split("## プロジェクト固有の言語選考条件", 1)[1].split(
        "## 公式根拠（原文）", 1
    )[0]
    assert "chinese" in section
    assert "excluded" in section
    assert "fact:00347" in section
    assert "p.76" in section

    serialized = json.dumps(result, ensure_ascii=False)
    for forbidden in (
        "required_level",
        "scholarship_certificate",
        "program_eligibility",
        "admission_probability",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("year", "month", "route"),
    (
        (2027, 4, None),
        (None, 4, "tsinghua_joint_program"),
        (2027, None, "tsinghua_joint_program"),
    ),
)
def test_missing_route_or_intake_does_not_expose_program_evidence(
    rule04b_client, year, month, route
) -> None:
    client, document_id = rule04b_client
    report = _report(
        client,
        document_id,
        _program_profile(year, month, route),
        f"tsinghua-program-language-missing-{year}-{month}-{route}",
    )
    assert report["program_language_condition"] is None
    report_json = json.dumps(report, ensure_ascii=False)
    assert "fact:00347" not in report_json
    assert '"source_pages": [76]' not in report_json
    assert "入学試験では、中国語の語学力は選考対象外です" not in report_json
    assert report["source_plan"]["program_language_condition"] is None
    for hidden in (PROGRAM, "清華", "奨学金", "プログラム出願資格"):
        assert hidden not in report_json
    markdown = render_applicant_report_markdown(ApplicantReport.model_validate(report))
    assert "fact:00347" not in markdown
    assert "入学試験では、中国語の語学力は選考対象外です" not in markdown


@pytest.mark.parametrize(
    ("year", "month", "route"),
    (
        (2026, 9, "tsinghua_joint_program"),
        (2027, 4, "general"),
        (2027, 4, "b_schedule"),
        (2027, 4, "international_graduate_program_b"),
    ),
)
def test_other_intakes_and_routes_are_not_covered(rule04b_client, year, month, route) -> None:
    client, document_id = rule04b_client
    report = _report(
        client,
        document_id,
        _program_profile(year, month, route),
        f"tsinghua-program-language-uncovered-{year}-{month}-{len(route)}",
    )
    assert report["program_language_condition"] is None
    report_json = json.dumps(report, ensure_ascii=False)
    assert "fact:00347" not in report_json
    assert '"source_pages": [76]' not in report_json
    assert "入学試験では、中国語の語学力は選考対象外です" not in report_json
    assert report["source_plan"]["program_language_condition"] is None
    for hidden in (PROGRAM, "清華", "奨学金", "プログラム出願資格"):
        assert hidden not in report_json
    markdown = render_applicant_report_markdown(ApplicantReport.model_validate(report))
    assert "fact:00347" not in markdown
    assert "入学試験では、中国語の語学力は選考対象外です" not in markdown
