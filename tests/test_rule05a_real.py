from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.reasoning.applicant_report import (
    ApplicantReport,
    ApplicantReportError,
    canonical_applicant_report_bytes,
    load_applicant_report_bytes,
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


def test_demo_target_catalog_and_base_requirements_are_server_owned(rule04b_client) -> None:
    client, document_id = rule04b_client
    catalog_response = client.get("/v1/target-catalog")

    assert catalog_response.status_code == 200
    schools = catalog_response.json()["schools"]
    assert [(item["school_id"], item["school_name"]) for item in schools] == [
        ("isct", "東京科学大学")
    ]
    master = schools[0]["degrees"][0]
    assert master["degree_id"] == "master"
    intake = next(item for item in master["intakes"] if (item["year"], item["month"]) == (2027, 4))
    engineering = next(item for item in intake["colleges"] if item["college_id"] == "工学院")
    assert "システム制御系" in {item["department_id"] for item in engineering["departments"]}
    assert "tsinghua_joint_program" not in catalog_response.text

    response = client.post(
        "/v1/base-requirements",
        json={
            "schema_version": "1.0",
            "school_id": "isct",
            "document_id": document_id,
            "degree_id": "master",
            "intake": {"year": 2027, "month": 4},
            "college_id": "工学院",
            "department_id": "システム制御系",
            "application_route": None,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["coverage_status"] == "partial_reviewed_rules"
    assert {item["category"] for item in payload["requirements"]} == {
        "dates",
        "materials",
        "eligibility",
        "language",
    }
    materials = [item for item in payload["requirements"] if item["category"] == "materials"]
    assert [item["official_status"] for item in materials] == [
        "required",
        "required",
        "needs_information",
        "needs_information",
        "needs_information",
    ]
    assert {evidence["fact_id"] for item in materials for evidence in item["evidence"]} == {
        "fact:00104"
    }
    all_evidence = [evidence for item in payload["requirements"] for evidence in item["evidence"]]
    assert all(evidence["pages"] and evidence["official_text"] for evidence in all_evidence)
    dates = [item for item in payload["requirements"] if item["category"] == "dates"]
    assert all(item["reviewed_summary"] for item in dates)
    assert all(
        "2026" in item["reviewed_summary"] or "到着日" in item["reviewed_summary"] for item in dates
    )
    assert "fact:00347" not in {evidence["fact_id"] for evidence in all_evidence}
    assert "tsinghua_joint_program" not in response.text


def test_demo_target_rejects_incomplete_or_unreviewed_selection(rule04b_client) -> None:
    client, document_id = rule04b_client
    base = {
        "schema_version": "1.0",
        "school_id": "isct",
        "document_id": document_id,
        "degree_id": "master",
        "intake": {"year": 2027, "month": 4},
        "college_id": "情報理工学院",
        "department_id": "情報工学系",
        "application_route": None,
    }

    missing_route = client.post("/v1/base-requirements", json=base)
    unknown_department = client.post(
        "/v1/base-requirements",
        json={**base, "college_id": "工学院", "department_id": "未审核系"},
    )

    assert (missing_route.status_code, missing_route.json()["code"]) == (422, "invalid_request")
    assert (unknown_department.status_code, unknown_department.json()["code"]) == (
        422,
        "invalid_request",
    )


@pytest.mark.parametrize(
    ("basis", "education_status", "material_tail", "education_fact_ids"),
    [
        (
            "university_graduation",
            "possible_match",
            ["required"] * 3,
            {"fact:00056", "fact:00059", "fact:00060"},
        ),
        (
            "foreign_15_year_education",
            "needs_review",
            ["eligibility_review_path"] * 3,
            {"fact:00068", "fact:00086"},
        ),
        (None, "needs_information", ["needs_information"] * 3, set()),
    ],
)
def test_demo_applicant_comparison_is_conservative_and_path_aware(
    rule04b_client, basis, education_status, material_tail, education_fact_ids
) -> None:
    client, document_id = rule04b_client
    response = client.post(
        "/v1/applicant-comparison",
        json={
            "schema_version": "1.0",
            "target": {
                "schema_version": "1.0",
                "school_id": "isct",
                "document_id": document_id,
                "degree_id": "master",
                "intake": {"year": 2027, "month": 4},
                "college_id": "工学院",
                "department_id": "システム制御系",
                "application_route": None,
            },
            "applicant": {
                "credential_basis": basis,
                "completion_state": "expected" if basis else None,
                "english_test_kind": "toeic_lr",
                "english_score": 800,
                "english_test_date": "2026-05-01",
                "english_official_report_available": True,
                "japanese_background": "certificate_available",
                "materials": [
                    {"code": "address_label", "preparation": "available"},
                    {"code": "application_form", "preparation": "not_yet"},
                ],
            },
        },
    )

    assert response.status_code == 200
    items = response.json()["items"]
    counts = response.json()["counts"]
    assert counts["total"] == len(items)
    assert counts["recorded"] + counts["action_required"] + counts["review_required"] == len(items)
    assert all(item["next_action"] and item["action_group"] for item in items)
    education = next(item for item in items if item["item_id"] == "education:credential")
    assert education["comparison_status"] == education_status
    assert {item["fact_id"] for item in education["evidence"]} == education_fact_ids
    assert "资格" not in response.json()["comparison_statement"]
    assert (
        next(item for item in items if item["item_id"] == "english:result")["comparison_status"]
        == "recorded"
    )
    japanese = next(item for item in items if item["item_id"] == "japanese:background")
    assert japanese["comparison_status"] == "recorded"
    assert japanese["evidence"] == []
    materials = [item for item in items if item["category"] == "materials"]
    assert [item["official_status"] for item in materials[2:]] == material_tail
    assert materials[0]["preparation_status"] == "available"
    assert materials[1]["preparation_status"] == "not_yet"
    assert all(item["evidence"][0]["fact_id"] == "fact:00104" for item in materials)
    all_evidence = [evidence for item in items for evidence in item["evidence"]]
    assert "fact:00347" not in {evidence["fact_id"] for evidence in all_evidence}
    assert all(evidence["scope_type"] != "conditional_program" for evidence in all_evidence)

    from jgrad_admission_rag.service.demo_requirements import DemoApplicantComparisonResponse

    invalid = response.json()
    invalid["counts"]["total"] += 1
    with pytest.raises(ValidationError):
        DemoApplicantComparisonResponse.model_validate(invalid)
    invalid_group = response.json()
    current_group = invalid_group["items"][0]["action_group"]
    invalid_group["items"][0]["action_group"] = (
        "recorded" if current_group != "recorded" else "action_required"
    )
    with pytest.raises(ValidationError):
        DemoApplicantComparisonResponse.model_validate(invalid_group)


def test_demo_applicant_comparison_rejects_ambiguous_language_or_material_input(
    rule04b_client,
) -> None:
    client, document_id = rule04b_client
    target = {
        "school_id": "isct",
        "document_id": document_id,
        "degree_id": "master",
        "intake": {"year": 2027, "month": 4},
        "college_id": "工学院",
        "department_id": "システム制御系",
    }
    score_without_kind = client.post(
        "/v1/applicant-comparison",
        json={"target": target, "applicant": {"english_score": 800}},
    )
    repeated_material = client.post(
        "/v1/applicant-comparison",
        json={
            "target": target,
            "applicant": {
                "materials": [
                    {"code": "address_label", "preparation": "available"},
                    {"code": "address_label", "preparation": "not_yet"},
                ]
            },
        },
    )
    score_out_of_range = client.post(
        "/v1/applicant-comparison",
        json={
            "target": target,
            "applicant": {"english_test_kind": "toeic_lr", "english_score": 10_001},
        },
    )

    assert score_without_kind.status_code == 422
    assert repeated_material.status_code == 422
    assert score_out_of_range.status_code == 422


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


def test_report_loader_and_canonicalizer_reject_tampered_material_applicability(
    rule04b_client,
) -> None:
    client, document_id = rule04b_client
    report, _ = _materials(
        client,
        document_id,
        _profile(_credential()),
        "rule05a-tamper-rejection",
    )
    payload = json.loads(json.dumps(report, ensure_ascii=False))
    payload["application_materials"]["entries"][2]["applicability"] = "eligibility_review_path"
    with pytest.raises(ApplicantReportError):
        load_applicant_report_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    validated = ApplicantReport.model_validate(report)
    materials = validated.application_materials
    assert materials is not None
    entries = list(materials.entries)
    entries[2] = entries[2].model_copy(
        update={"applicability": type(entries[2].applicability).ELIGIBILITY_REVIEW_PATH}
    )
    bypassed_materials = materials.model_copy(update={"entries": tuple(entries)})
    bypassed_report = validated.model_copy(update={"application_materials": bypassed_materials})
    with pytest.raises(ApplicantReportError):
        canonical_applicant_report_bytes(bypassed_report)
