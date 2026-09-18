from __future__ import annotations

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.reasoning.applicability import OfficialEvidenceBinding
from jgrad_admission_rag.reasoning.applicant_profile import ApplicantProfile
from jgrad_admission_rag.reasoning.language_evaluation import (
    DepartmentLanguageEvaluation,
    LanguageEvaluationPolicy,
    LanguageEvaluationStatus,
    LanguageEvaluationUsage,
    resolve_language_evaluation,
)
from tests.test_rule01a_real import _profile


def _policy() -> LanguageEvaluationPolicy:
    return LanguageEvaluationPolicy(
        policy_id="math-evaluation-v1",
        entries=(
            DepartmentLanguageEvaluation(
                target="数学系",
                parent_college="理学院",
                evidence_binding=OfficialEvidenceBinding(
                    document_id="document",
                    source_kb_sha256="a" * 64,
                    source_pdf_sha256="b" * 64,
                    fact_id="fact:00149",
                    source_pages=(19,),
                    authoritative_fact_text_sha256="c" * 64,
                ),
            ),
        ),
        limitation_statement="必要条件だけを示し、受験者の結果や最終合否を判定しません。",
        out_of_scope_statement="この対象には審査済み評価規則がありません。",
    )


def _information_policy() -> LanguageEvaluationPolicy:
    return LanguageEvaluationPolicy(
        policy_id="information-evaluation-v1",
        entries=(
            DepartmentLanguageEvaluation(
                target="情報工学系",
                parent_college="情報理工学院",
                application_route="b_schedule",
                assessment_source="external_score",
                result_scale=None,
                required_for_all=None,
                external_score_exemption=None,
                selection_role=None,
                no_internal_written_exam=True,
                evaluation_uses=(
                    LanguageEvaluationUsage.ORAL_EXAM_CANDIDATE_SELECTION,
                    LanguageEvaluationUsage.FINAL_HOLISTIC_EVALUATION,
                ),
                limitation_statement="用途だけを示し、資格や合否を判定しません。",
                evidence_binding=OfficialEvidenceBinding(
                    document_id="document",
                    source_kb_sha256="a" * 64,
                    source_pdf_sha256="b" * 64,
                    fact_id="fact:00288",
                    source_pages=(52,),
                    authoritative_fact_text_sha256="c" * 64,
                ),
            ),
        ),
        limitation_statement="審査済み用途だけを示します。",
        out_of_scope_statement="この対象には審査済み評価規則がありません。",
    )


def _applicant(
    target: str | None,
    college: str | None,
    route: str | None = "general",
) -> ApplicantProfile:
    payload = _profile(None)
    payload["target_application"]["department_or_program"] = target
    payload["target_application"]["graduate_school_or_college"] = college
    payload["target_application"]["application_route"] = route
    return ApplicantProfile.model_validate(payload)


def test_exact_math_scope_returns_official_nonnumeric_method_only() -> None:
    result = resolve_language_evaluation(_applicant("数学系", "理学院"), _policy())

    assert result.status is LanguageEvaluationStatus.CONFIRMED
    assert result.assessment_source == "written_exam"
    assert result.result_scale == "pass_fail"
    assert result.required_for_all is True
    assert result.external_score_exemption is False
    assert result.selection_role == "necessary_condition"
    assert result.evidence is not None
    assert result.evidence.fact_id == "fact:00149"
    payload = result.model_dump(mode="json")
    assert "maximum_points" not in payload
    assert "applicant_result" not in payload


def test_uncovered_and_conflicting_scope_expose_no_method_or_evidence() -> None:
    uncovered = resolve_language_evaluation(_applicant("物理学系", "理学院"), _policy())
    conflict = resolve_language_evaluation(_applicant("数学系", "工学院"), _policy())

    for result in (uncovered, conflict):
        assert result.status is LanguageEvaluationStatus.NOT_COVERED
        assert result.assessment_source is None
        assert result.selection_role is None
        assert result.evidence is None
        assert result.limitation_statement == "この対象には審査済み評価規則がありません。"


def test_missing_scope_needs_information_without_method() -> None:
    result = resolve_language_evaluation(_applicant(None, None), _policy())

    assert result.status is LanguageEvaluationStatus.NEEDS_INFORMATION
    assert result.assessment_source is None
    assert result.evidence is None
    assert result.limitation_statement == "この対象には審査済み評価規則がありません。"


def test_information_engineering_b_schedule_returns_only_reviewed_uses() -> None:
    result = resolve_language_evaluation(
        _applicant("情報工学系", "情報理工学院", "b_schedule"),
        _information_policy(),
    )

    assert result.status is LanguageEvaluationStatus.CONFIRMED
    assert result.application_route == "b_schedule"
    assert result.assessment_source == "external_score"
    assert result.no_internal_written_exam is True
    assert result.evaluation_uses == (
        LanguageEvaluationUsage.ORAL_EXAM_CANDIDATE_SELECTION,
        LanguageEvaluationUsage.FINAL_HOLISTIC_EVALUATION,
    )
    assert result.result_scale is None
    assert result.selection_role is None
    assert result.evidence is not None
    assert result.evidence.fact_id == "fact:00288"
    payload = result.model_dump(mode="json")
    for forbidden in ("ranking", "threshold", "oral_exam_eligibility", "applicant_result"):
        assert forbidden not in payload


def test_information_engineering_route_scope_fails_closed() -> None:
    missing = resolve_language_evaluation(
        _applicant("情報工学系", "情報理工学院", None), _information_policy()
    )
    wrong = resolve_language_evaluation(
        _applicant("情報工学系", "情報理工学院", "a_schedule"),
        _information_policy(),
    )
    wrong_parent = resolve_language_evaluation(
        _applicant("情報工学系", "工学院", "b_schedule"), _information_policy()
    )

    assert missing.status is LanguageEvaluationStatus.NEEDS_INFORMATION
    for result in (missing, wrong, wrong_parent):
        assert result.assessment_source is None
        assert result.evaluation_uses is None
        assert result.evidence is None
    assert wrong.status is LanguageEvaluationStatus.NOT_COVERED
    assert wrong_parent.status is LanguageEvaluationStatus.NOT_COVERED


def test_external_score_usage_requires_exact_canonical_enum_sequence() -> None:
    payload = _information_policy().entries[0].model_dump(mode="json")
    payload["evaluation_uses"] = ["final_holistic_evaluation"]

    with pytest.raises(ValidationError):
        DepartmentLanguageEvaluation.model_validate(payload)
