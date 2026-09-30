"""PREP-01 request-to-reviewed-rule checks over the existing read-only 391 asset."""

from importlib import import_module
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jgrad_admission_rag.corpus_selection import select_corpus_documents
from jgrad_admission_rag.reasoning.reviewed_report_evidence import prepare_reviewed_report_evidence
from jgrad_admission_rag.reasoning.reviewed_report_plan import load_reviewed_report_plan
from jgrad_admission_rag.schemas.corpus_manifest import load_corpus_manifest
from jgrad_admission_rag.schemas.corpus_version import (
    CorpusSelectionRequest,
    load_corpus_version_policy,
)
from jgrad_admission_rag.schemas.page_scope_manifest import load_page_scope_manifest
from jgrad_admission_rag.service.demo_requirements import (
    DemoApplicantComparisonRequest,
    DemoTargetRequest,
    build_demo_applicant_comparison,
    build_demo_base_requirements,
)


ROOT = Path(__file__).resolve().parents[1]
ASSET = Path(
    os.environ.get(
        "PREP01_REVIEWED_ASSET_ROOT", str(ROOT.parent / "ux02-review/workspace/runtime-v1")
    )
)


@pytest.fixture(scope="module")
def reviewed_context():
    try:
        accessible = (ASSET / "corpus.json").is_file()
    except OSError:
        accessible = False
    if not accessible:
        pytest.skip("Existing read-only 391 asset is unavailable")
    manifest = load_corpus_manifest(ASSET / "corpus.json")
    policy = load_corpus_version_policy(ASSET / "policy.json")
    plan = load_reviewed_report_plan(ASSET / "config/reviewed_report_plan.json")
    selection = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(document_ids=("isct_2027_4_2026_9_master",)),
    )
    page_scope = load_page_scope_manifest(
        ASSET / "config/page_scope_manifest.json",
        expected_page_count=85,
    )
    evidence = prepare_reviewed_report_evidence(
        ASSET,
        manifest,
        policy,
        selection,
        (plan,),
        page_scope,
    )
    return plan, evidence


TARGET = {
    "school_id": "isct",
    "document_id": "isct_2027_4_2026_9_master",
    "degree_id": "master",
    "intake": {"year": 2027, "month": 4},
    "college_id": "情報理工学院",
    "department_id": "情報工学系",
    "application_route": "b_schedule",
}


def _result(context, applicant, proof, target=TARGET):
    request = DemoApplicantComparisonRequest.model_validate(
        {
            "target": target,
            "applicant": applicant,
            "english_preparation": proof,
        }
    )
    plan, evidence = context
    result = build_demo_applicant_comparison(request, plan, evidence)
    assert result.english_preparation_result is not None
    return {item.check_id: item for item in result.english_preparation_result.checks}


@pytest.mark.real_pdf
def test_second_step_guide_is_bound_to_current_target_and_source(reviewed_context):
    plan, evidence = reviewed_context
    base = build_demo_base_requirements(DemoTargetRequest.model_validate(TARGET), plan, evidence)
    guide = next(
        item for item in base.requirements if item.requirement_id == "language:preparation-guide"
    )
    assert {source.fact_id for source in guide.evidence} == {
        "fact:00110",
        "fact:00111",
        "fact:00114",
        "fact:00115",
        "fact:00122",
    }
    assert "2024年6月11日" in guide.reviewed_summary
    submission = next(
        item
        for item in base.requirements
        if "english-submission-computer-science" in item.requirement_id
    )
    assert submission.evidence[0].fact_id == "fact:00287"
    assert "截止后不能补交" in submission.reviewed_summary


@pytest.mark.real_pdf
def test_toeic_proof_reaches_reviewed_rule_trace(reviewed_context):
    applicant = {"english_test_kind": "toeic_lr", "english_test_date": "2024-06-11"}
    checks = _result(
        reviewed_context,
        applicant,
        {
            "downloaded_online_pdf": True,
            "toeic_verification_qr_present": None,
            "toeic_digital_official_score_certificate": False,
        },
    )
    assert checks["english:kind"].status == "reported_match"
    assert checks["english:date"].status == "reported_match"
    assert checks["english:downloaded_online_pdf"].status == "reported_match"
    assert checks["english:toeic_verification_qr_present"].status == "needs_information"
    assert checks["english:toeic_digital_official_score_certificate"].status == "action_needed"
    assert all(item.rule_ids and item.evidence for item in checks.values())


@pytest.mark.real_pdf
def test_toefl_date_and_g179_use_same_existing_rules(reviewed_context):
    applicant = {"english_test_kind": "toefl_ibt", "english_test_date": "2024-06-10"}
    checks = _result(
        reviewed_context,
        applicant,
        {
            "downloaded_online_pdf": False,
            "toefl_test_taker_score_report_pdf": True,
            "toefl_di_code_g179_set": False,
        },
    )
    assert checks["english:date"].status == "action_needed"
    assert checks["english:downloaded_online_pdf"].status == "action_needed"
    assert checks["english:toefl_test_taker_score_report_pdf"].status == "reported_match"
    assert checks["english:toefl_di_code_g179_set"].status == "action_needed"


@pytest.mark.real_pdf
def test_unknown_false_and_rejected_kinds_remain_distinct(reviewed_context):
    applicant = {"english_test_kind": "toeic_lr"}
    unknown = _result(reviewed_context, applicant, {"toeic_verification_qr_present": None})
    missing = _result(reviewed_context, applicant, {"toeic_verification_qr_present": False})
    ready = _result(reviewed_context, applicant, {"toeic_verification_qr_present": True})
    assert unknown["english:toeic_verification_qr_present"].status == "needs_information"
    assert missing["english:toeic_verification_qr_present"].status == "action_needed"
    assert ready["english:toeic_verification_qr_present"].status == "reported_match"
    rejected = _result(reviewed_context, {"english_test_kind": "toeic_ip"}, {})
    assert rejected["english:kind"].status == "action_needed"
    assert "english:toeic_verification_qr_present" not in rejected


@pytest.mark.real_pdf
@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "needs_information"), (False, "action_needed"), (True, "reported_match")],
)
def test_online_pdf_three_states_follow_existing_rule(reviewed_context, value, expected):
    checks = _result(
        reviewed_context,
        {"english_test_kind": "toeic_lr"},
        {"downloaded_online_pdf": value},
    )
    check = checks["english:downloaded_online_pdf"]
    assert check.status == expected
    assert check.rule_ids == ("isct-master-english-online-pdf-apr",)
    assert {item.fact_id for item in check.evidence} == {"fact:00115"}


@pytest.mark.real_pdf
@pytest.mark.parametrize(
    ("kind", "field", "value", "expected"),
    [
        ("toefl_ibt", "toefl_test_taker_score_report_pdf", None, "needs_information"),
        ("toefl_ibt", "toefl_test_taker_score_report_pdf", False, "action_needed"),
        ("toefl_ibt", "toefl_test_taker_score_report_pdf", True, "reported_match"),
        ("toefl_ibt_home_edition", "toefl_di_code_g179_set", None, "needs_information"),
        ("toefl_ibt_home_edition", "toefl_di_code_g179_set", False, "action_needed"),
        ("toefl_ibt_home_edition", "toefl_di_code_g179_set", True, "reported_match"),
    ],
)
def test_toefl_proof_three_states_follow_existing_rules(
    reviewed_context, kind, field, value, expected
):
    checks = _result(reviewed_context, {"english_test_kind": kind}, {field: value})
    assert checks[f"english:{field}"].status == expected
    assert checks[f"english:{field}"].rule_ids
    assert checks[f"english:{field}"].evidence


@pytest.mark.real_pdf
def test_itp_and_unknown_kind_do_not_claim_acceptance(reviewed_context):
    rejected = _result(reviewed_context, {"english_test_kind": "toefl_itp"}, {})
    unknown = _result(reviewed_context, {"english_test_kind": "other"}, {})
    assert rejected["english:kind"].status == "action_needed"
    assert unknown["english:kind"].status == "needs_information"
    assert list(rejected) == list(unknown) == ["english:kind"]


@pytest.mark.real_pdf
def test_math_target_never_counts_missing_external_proof(reviewed_context):
    target = {
        **TARGET,
        "college_id": "理学院",
        "department_id": "数学系",
        "application_route": None,
    }
    checks = _result(reviewed_context, {}, {}, target)
    assert list(checks) == ["english:math"]
    assert checks["english:math"].status == "not_applicable"


def test_wrong_test_specific_fields_are_rejected():
    with pytest.raises(ValueError, match="TOEIC proof fields"):
        DemoApplicantComparisonRequest.model_validate(
            {
                "target": TARGET,
                "applicant": {"english_test_kind": "toefl_ibt"},
                "english_preparation": {"toeic_verification_qr_present": False},
            }
        )


def test_mismatched_proof_api_reports_the_field():
    app_module = import_module("jgrad_admission_rag.service.app")
    with TestClient(app_module.create_app()) as client:
        response = client.post(
            "/v1/applicant-comparison",
            json={
                "target": TARGET,
                "applicant": {"english_test_kind": "toefl_ibt"},
                "english_preparation": {"toeic_verification_qr_present": False},
            },
        )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert response.json()["details"] == {
        "field": "english_preparation.toeic_*",
        "expected_test_kind": "toeic_lr",
    }


@pytest.mark.real_pdf
def test_legacy_request_has_no_detailed_result(reviewed_context):
    request = DemoApplicantComparisonRequest.model_validate(
        {
            "target": TARGET,
            "applicant": {"english_test_kind": "toeic_lr"},
        }
    )
    assert request.english_preparation is None
    plan, evidence = reviewed_context
    response = build_demo_applicant_comparison(request, plan, evidence).model_dump(mode="json")
    assert "english_preparation_result" not in response
    assert response["counts"]["total"] == len(response["items"])


def test_comparison_api_omits_extension_for_legacy_requests(monkeypatch):
    app_module = import_module("jgrad_admission_rag.service.app")
    from jgrad_admission_rag.service.demo_requirements import DemoApplicantComparisonResponse

    target = {
        "school_name": "東京科学大学",
        "degree_name": "修士课程",
        "intake_name": "2027年4月入学",
        "college_name": "情報理工学院",
        "department_name": "情報工学系",
        "application_route_name": "B 日程",
    }

    def build(request, _settings, _state):
        return DemoApplicantComparisonResponse.model_validate(
            {
                "target": target,
                "comparison_statement": "保守对照",
                "partial_checklist_statement": "部分清单",
                "limitation_statement": "仅供参考",
                "items": [],
                "counts": {"total": 0, "recorded": 0, "action_required": 0, "review_required": 0},
                **(
                    {
                        "english_preparation_result": {
                            "document_id": request.target.document_id,
                            "target": target,
                            "scope_statement": "部分核对",
                            "checks": [],
                        }
                    }
                    if request.english_preparation is not None
                    else {}
                ),
            }
        )

    monkeypatch.setattr(app_module, "_report_service_ready", lambda _state: True)
    monkeypatch.setattr(app_module, "_build_demo_applicant_comparison_response", build)
    with TestClient(app_module.create_app()) as client:
        legacy = client.post(
            "/v1/applicant-comparison",
            json={
                "target": TARGET,
                "applicant": {},
            },
        )
        detailed = client.post(
            "/v1/applicant-comparison",
            json={
                "target": TARGET,
                "applicant": {},
                "english_preparation": {},
            },
        )
    assert legacy.status_code == detailed.status_code == 200
    assert "english_preparation_result" not in legacy.json()
    assert detailed.json()["english_preparation_result"]["document_id"] == TARGET["document_id"]
    assert legacy.json()["counts"] == detailed.json()["counts"]
