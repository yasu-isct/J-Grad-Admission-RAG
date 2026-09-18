from __future__ import annotations

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.reasoning.applicability import OfficialEvidenceBinding
from jgrad_admission_rag.reasoning.applicant_profile import ApplicantProfile, DegreeLevel
from jgrad_admission_rag.reasoning.program_language_condition import (
    ProgramLanguageConditionEntry,
    ProgramLanguageConditionPolicy,
    ProgramLanguageConditionStatus,
    resolve_program_language_condition,
)
from tests.test_rule01a_real import _profile

PROGRAM = "東京科学大学・清華大学 大学院合同プログラム"


def _policy() -> ProgramLanguageConditionPolicy:
    return ProgramLanguageConditionPolicy(
        policy_id="tsinghua-language-v1",
        entries=(
            ProgramLanguageConditionEntry(
                program=PROGRAM,
                application_route="tsinghua_joint_program",
                requested_degree_level=DegreeLevel.MASTER,
                intake_year=2027,
                intake_month=4,
                language="chinese",
                admission_selection="excluded",
                evidence_binding=OfficialEvidenceBinding(
                    document_id="document",
                    source_kb_sha256="a" * 64,
                    source_pdf_sha256="b" * 64,
                    fact_id="fact:00347",
                    source_pages=(76,),
                    authoritative_fact_text_sha256="c" * 64,
                ),
                limitation_statement="入学選考での用途だけを示します。",
            ),
        ),
        out_of_scope_statement="この入力には審査済みプロジェクト言語条件を適用しません。",
    )


def _applicant(*, route: str | None, year: int | None = 2027, month: int | None = 4):
    payload = _profile(None)
    payload["target_application"]["requested_degree_level"] = "master"
    payload["target_application"]["intake_year"] = year
    payload["target_application"]["intake_month"] = month
    payload["target_application"]["application_route"] = route
    return ApplicantProfile.model_validate(payload)


def test_exact_tsinghua_route_confirms_only_admission_selection_exclusion() -> None:
    result = resolve_program_language_condition(
        _applicant(route="tsinghua_joint_program"), _policy()
    )

    assert result.status is ProgramLanguageConditionStatus.CONFIRMED
    assert result.program == PROGRAM
    assert result.language == "chinese"
    assert result.admission_selection == "excluded"
    assert result.evidence is not None
    assert result.evidence.fact_id == "fact:00347"
    assert result.evidence.source_pages == (76,)
    payload = result.model_dump(mode="json")
    assert "required_level" not in payload
    assert "scholarship" not in payload
    assert "eligible" not in payload


@pytest.mark.parametrize(
    ("route", "year", "month"),
    [
        (None, 2027, 4),
        ("tsinghua_joint_program", None, 4),
        ("tsinghua_joint_program", 2027, None),
    ],
)
def test_missing_route_or_intake_fails_closed(route, year, month) -> None:
    result = resolve_program_language_condition(
        _applicant(route=route, year=year, month=month), _policy()
    )

    assert result.status is ProgramLanguageConditionStatus.NEEDS_INFORMATION
    assert result.program is None
    assert result.language is None
    assert result.admission_selection is None
    assert result.evidence is None


@pytest.mark.parametrize(
    ("route", "year", "month"),
    [
        ("general", 2027, 4),
        ("b_schedule", 2027, 4),
        ("international_graduate_program_b", 2027, 4),
        ("tsinghua_joint_program", 2026, 9),
    ],
)
def test_other_routes_and_intakes_are_not_covered(route, year, month) -> None:
    result = resolve_program_language_condition(
        _applicant(route=route, year=year, month=month), _policy()
    )

    assert result.status is ProgramLanguageConditionStatus.NOT_COVERED
    assert result.program is None
    assert result.evidence is None


def test_program_language_models_are_strict_and_frozen() -> None:
    entry = _policy().entries[0]
    with pytest.raises(ValidationError):
        ProgramLanguageConditionEntry.model_validate(
            {**entry.model_dump(mode="json"), "language": "english"}
        )
    with pytest.raises(ValidationError):
        ProgramLanguageConditionEntry.model_validate(
            {**entry.model_dump(mode="json"), "unexpected": True}
        )
    with pytest.raises(ValidationError):
        entry.program = "changed"  # type: ignore[misc]
