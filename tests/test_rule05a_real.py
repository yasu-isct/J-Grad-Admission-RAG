from __future__ import annotations

import json

import pytest

from jgrad_admission_rag.reasoning.applicant_report import (
    ApplicantReport,
    render_applicant_report_markdown,
)
from tests.test_rule01a_real import _credential, _profile, _report

pytestmark = pytest.mark.real_pdf
pytest_plugins = ("tests.test_rule04b_real",)


def _materials(client, document_id: str, profile, report_id: str):
    report = _report(client, document_id, profile, report_id)
    return report, report["application_materials"]


@pytest.mark.parametrize(
    "basis",
    [
        "university_graduation",
        "niad_qe_bachelor_award",
        "foreign_16_year_bachelor_equivalent",
        "minister_designated_person",
    ],
)
def test_direct_paths_require_all_five_common_materials(rule04b_client, basis) -> None:
    client, document_id = rule04b_client
    report, materials = _materials(
        client,
        document_id,
        _profile(_credential(basis=basis)),
        f"rule05a-direct-{basis}",
    )
    assert [entry["applicability"] for entry in materials["entries"]] == ["required"] * 5
    assert materials["evidence"]["fact_id"] == "fact:00104"
    assert materials["evidence"]["source_pages"] == [10]
    assert "宛名ラベル" in json.dumps(report, ensure_ascii=False)


@pytest.mark.parametrize(
    "basis",
    [
        "university_three_year_enrollment",
        "foreign_15_year_education",
        "review_path10_sixteen_year_equivalent",
        "review_path11_under_sixteen_year_bachelor",
    ],
)
def test_review_paths_use_the_separate_review_material_route(rule04b_client, basis) -> None:
    client, document_id = rule04b_client
    _, materials = _materials(
        client,
        document_id,
        _profile(_credential(basis=basis)),
        f"rule05a-review-{basis}",
    )
    assert [entry["applicability"] for entry in materials["entries"]] == [
        "required",
        "required",
        "eligibility_review_path",
        "eligibility_review_path",
        "eligibility_review_path",
    ]


def test_missing_credential_basis_fails_closed_for_path_dependent_items(rule04b_client) -> None:
    client, document_id = rule04b_client
    _, materials = _materials(
        client,
        document_id,
        _profile(_credential(basis=None)),
        "rule05a-missing-basis",
    )
    assert [entry["applicability"] for entry in materials["entries"]] == [
        "required",
        "required",
        "needs_information",
        "needs_information",
        "needs_information",
    ]


def test_common_materials_do_not_expose_conditional_or_excluded_materials(rule04b_client) -> None:
    client, document_id = rule04b_client
    report, _ = _materials(
        client,
        document_id,
        _profile(_credential()),
        "rule05a-core-only",
    )
    serialized = json.dumps(report["application_materials"], ensure_ascii=False)
    for hidden in ("清華", "HSK", "奨学金", "在留カード", "GMAT"):
        assert hidden not in serialized


def test_markdown_and_ui_expose_one_compact_materials_section(rule04b_client) -> None:
    client, document_id = rule04b_client
    report, _ = _materials(
        client,
        document_id,
        _profile(_credential()),
        "rule05a-rendering",
    )
    markdown = render_applicant_report_markdown(ApplicantReport.model_validate(report))
    assert "## 一般志願者の共通出願書類" in markdown
    app_js = client.get("/assets/app.js")
    assert app_js.status_code == 200
    assert "一般志願者の共通出願書類" in app_js.text
