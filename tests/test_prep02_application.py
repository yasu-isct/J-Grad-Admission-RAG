"""PREP-02 request → existing reviewed rules → bounded Chinese result."""

import os
from pathlib import Path

import pytest

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
    _demo_applicant_profile,
    build_demo_applicant_comparison,
)


ROOT = Path(__file__).resolve().parents[1]
ASSET = Path(
    os.environ.get(
        "PREP02_REVIEWED_ASSET_ROOT",
        str(ROOT.parent / "m10-09-deepseek-live/runtime-v1"),
    )
)
TARGET = {
    "school_id": "isct",
    "document_id": "isct_2027_4_2026_9_master",
    "degree_id": "master",
    "intake": {"year": 2027, "month": 4},
    "college_id": "情報理工学院",
    "department_id": "情報工学系",
    "application_route": "b_schedule",
}


@pytest.fixture(scope="module")
def reviewed_context():
    try:
        available = (ASSET / "corpus.json").is_file()
    except OSError:
        available = False
    if not available:
        pytest.skip("Existing read-only 391 asset is unavailable")
    manifest = load_corpus_manifest(ASSET / "corpus.json")
    policy = load_corpus_version_policy(ASSET / "policy.json")
    plan = load_reviewed_report_plan(ASSET / "config/reviewed_report_plan.json")
    selection = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(
            document_ids=(TARGET["document_id"],),
        ),
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


def _compare(context, applicant=None, preparation=None, target=TARGET, english=None):
    payload = {"target": target, "applicant": applicant or {}}
    if preparation is not None:
        payload["application_preparation"] = preparation
    if english is not None:
        payload["english_preparation"] = english
    request = DemoApplicantComparisonRequest.model_validate(payload)
    result = build_demo_applicant_comparison(request, *context)
    return (
        request,
        result,
        {
            item.check_id: item
            for item in (
                result.application_preparation_result.checks
                if result.application_preparation_result
                else ()
            )
        },
    )


@pytest.mark.real_pdf
def test_dispatched_without_arrival_uses_reviewed_window_and_keeps_unknown(reviewed_context):
    request, result, checks = _compare(
        reviewed_context,
        preparation={
            "materials_dispatched_date": "2026-06-09",
        },
    )
    profile = _demo_applicant_profile(
        request.target,
        request.applicant,
        application_preparation=request.application_preparation,
    )
    assert profile.application_submission.materials_dispatched_date.isoformat() == "2026-06-09"
    assert profile.application_submission.materials_arrival_date is None
    arrival = checks["application:arrival"]
    assert arrival.status == "needs_information"
    assert "寄出不等于按时送达" in arrival.explanation
    assert arrival.rule_ids == ("isct-master-materials-arrival-window-apr",)
    assert {item.fact_id for item in arrival.evidence} == {"fact:00100"}
    assert len([item for item in result.items if item.category == "materials"]) == 5


@pytest.mark.real_pdf
@pytest.mark.parametrize(
    ("arrival", "status", "fragment"),
    [
        ("2026-06-03", "action_needed", "早于"),
        ("2026-06-04", "reported_match", "接收期间内"),
        ("2026-06-10", "reported_match", "接收期间内"),
        ("2026-06-11", "action_needed", "晚于"),
    ],
)
def test_arrival_window_boundaries(reviewed_context, arrival, status, fragment):
    _, _, checks = _compare(reviewed_context, preparation={"materials_arrival_date": arrival})
    assert checks["application:arrival"].status == status
    assert fragment in checks["application:arrival"].explanation
    assert "材料已受理" not in checks["application:arrival"].explanation


@pytest.mark.real_pdf
@pytest.mark.parametrize(
    ("graduation", "status", "fragment"),
    [
        ("2027-03-20", "reported_match", "日期这一项"),
        ("2027-04-10", "action_needed", "晚于"),
    ],
)
def test_april_graduation_only_checks_date(reviewed_context, graduation, status, fragment):
    _, _, checks = _compare(
        reviewed_context,
        applicant={"credential_basis": "university_graduation", "completion_state": "expected"},
        preparation={"expected_completion_date": graduation},
    )
    check = checks["application:graduation"]
    assert check.status == status
    assert fragment in check.explanation
    assert check.rule_ids == ("isct-master-direct-path-1-university-apr-expected",)
    assert check.evidence
    assert "你没有资格" not in check.explanation


@pytest.mark.real_pdf
@pytest.mark.parametrize("graduation", ["2026-09-28", "2026-09-29", "2026-09-30"])
def test_september_special_contact_and_online_false(reviewed_context, graduation):
    target = {**TARGET, "intake": {"year": 2026, "month": 9}}
    _, _, checks = _compare(
        reviewed_context,
        applicant={"credential_basis": "university_graduation", "completion_state": "expected"},
        preparation={"expected_completion_date": graduation, "online_steps_completed": False},
        target=target,
    )
    assert checks["application:graduation"].status == "needs_information"
    assert "特殊联系" in checks["application:graduation"].explanation
    assert checks["application:graduation"].rule_ids == (
        "isct-master-direct-path-1-university-sep-special-contact",
    )
    assert checks["application:online"].status == "action_needed"


@pytest.mark.real_pdf
@pytest.mark.parametrize(
    ("graduation", "status"),
    [
        ("2026-09-27", "reported_match"),
        ("2026-10-01", "action_needed"),
    ],
)
def test_september_ordinary_deadline_edges(reviewed_context, graduation, status):
    target = {**TARGET, "intake": {"year": 2026, "month": 9}}
    _, _, checks = _compare(
        reviewed_context,
        applicant={"credential_basis": "university_graduation", "completion_state": "expected"},
        preparation={"expected_completion_date": graduation},
        target=target,
    )
    assert checks["application:graduation"].status == status


@pytest.mark.real_pdf
def test_unknown_and_review_path_remain_unknown(reviewed_context):
    _, result, checks = _compare(reviewed_context, preparation={})
    assert set(checks) == {"application:graduation", "application:arrival", "application:online"}
    assert all(item.status == "needs_information" for item in checks.values())
    assert result.model_dump()["application_preparation_result"]
    _, _, review = _compare(
        reviewed_context,
        applicant={"credential_basis": "foreign_15_year_education"},
        preparation={"individual_review_status": "completed"},
    )
    assert review["application:review"].status == "needs_information"
    assert "不表示审查通过" in review["application:review"].explanation
    assert review["application:graduation"].status == "needs_information"
    _, _, other_path = _compare(
        reviewed_context,
        applicant={"credential_basis": "university_three_year_enrollment"},
        preparation={"individual_review_status": "requested"},
    )
    assert other_path["application:review"].status == "needs_information"
    assert "等待结果" in other_path["application:review"].explanation


@pytest.mark.real_pdf
def test_old_shape_and_english_math_exception_unchanged(reviewed_context):
    _, old, checks = _compare(reviewed_context)
    assert not checks
    assert "application_preparation_result" not in old.model_dump()
    target = {
        **TARGET,
        "college_id": "理学院",
        "department_id": "数学系",
        "application_route": None,
    }
    _, both, checks = _compare(reviewed_context, target=target, preparation={}, english={})
    assert both.english_preparation_result.checks[0].check_id == "english:math"
    assert checks["application:arrival"].status == "needs_information"


@pytest.mark.parametrize(
    "preparation,applicant",
    [
        ({"completion_date": "2027-03-20"}, {"completion_state": "expected"}),
        ({"expected_completion_date": "2027-03-20"}, {"completion_state": "completed"}),
        ({"materials_dispatched_date": "2026-06-10", "materials_arrival_date": "2026-06-09"}, {}),
        ({"individual_review_status": "completed"}, {"credential_basis": "university_graduation"}),
    ],
)
def test_conflicting_input_is_rejected(preparation, applicant):
    with pytest.raises(ValueError):
        DemoApplicantComparisonRequest.model_validate(
            {
                "target": TARGET,
                "applicant": applicant,
                "application_preparation": preparation,
            }
        )
