from __future__ import annotations

from jgrad_admission_rag.reasoning.applicability import OfficialEvidenceBinding
from jgrad_admission_rag.reasoning.applicant_profile import ApplicantProfile
from jgrad_admission_rag.reasoning.language_score_allocation import (
    DepartmentLanguageScoreAllocation,
    LanguageScoreAllocationPolicy,
    LanguageScoreAllocationStatus,
    resolve_language_score_allocation,
)
from tests.test_rule01a_real import _profile


def _policy() -> LanguageScoreAllocationPolicy:
    return LanguageScoreAllocationPolicy(
        policy_id="allocation-v1",
        entries=(
            DepartmentLanguageScoreAllocation(
                target="物理学系",
                parent_college="理学院",
                maximum_points=60,
                evidence_binding=OfficialEvidenceBinding(
                    document_id="document",
                    source_kb_sha256="a" * 64,
                    source_pdf_sha256="b" * 64,
                    fact_id="fact:00182",
                    source_pages=(21,),
                    authoritative_fact_text_sha256="c" * 64,
                ),
            ),
        ),
        limitation_statement="公式配点だけを示し、受験者の実得点や合否を示しません。",
    )


def _applicant(target: str | None, college: str | None) -> ApplicantProfile:
    payload = _profile(None)
    payload["target_application"]["department_or_program"] = target
    payload["target_application"]["graduate_school_or_college"] = college
    return ApplicantProfile.model_validate(payload)


def test_exact_reviewed_scope_returns_only_official_maximum_points() -> None:
    result = resolve_language_score_allocation(_applicant("物理学系", "理学院"), _policy())

    assert result.status is LanguageScoreAllocationStatus.CONFIRMED
    assert result.maximum_points == 60
    assert result.evidence is not None
    assert result.evidence.fact_id == "fact:00182"


def test_unpublished_or_conflicting_scope_never_fabricates_zero() -> None:
    unpublished = resolve_language_score_allocation(_applicant("数学系", "理学院"), _policy())
    conflict = resolve_language_score_allocation(_applicant("物理学系", "工学院"), _policy())

    assert unpublished.status is LanguageScoreAllocationStatus.NOT_PUBLISHED
    assert conflict.status is LanguageScoreAllocationStatus.NOT_PUBLISHED
    assert unpublished.maximum_points is None
    assert conflict.maximum_points is None


def test_missing_scope_is_reported_without_points() -> None:
    result = resolve_language_score_allocation(_applicant(None, None), _policy())

    assert result.status is LanguageScoreAllocationStatus.NEEDS_INFORMATION
    assert result.maximum_points is None
    assert result.evidence is None
