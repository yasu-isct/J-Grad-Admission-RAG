"""Reviewed department-level nonnumeric language evaluation methods."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .applicability import EvidenceRole, OfficialEvidenceBinding, OfficialEvidenceReference
from .applicant_profile import ApplicantProfile


class LanguageEvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DepartmentLanguageEvaluation(LanguageEvaluationModel):
    target: str
    parent_college: str
    assessment_source: Literal["written_exam"] = "written_exam"
    result_scale: Literal["pass_fail"] = "pass_fail"
    required_for_all: Literal[True] = True
    external_score_exemption: Literal[False] = False
    selection_role: Literal["necessary_condition"] = "necessary_condition"
    evidence_binding: OfficialEvidenceBinding

    @field_validator("target", "parent_college")
    @classmethod
    def text_must_be_explicit(cls, value: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("language evaluation scope must be explicit")
        return value


class LanguageEvaluationPolicy(LanguageEvaluationModel):
    policy_id: str
    entries: tuple[DepartmentLanguageEvaluation, ...] = Field(min_length=1)
    limitation_statement: str

    @field_validator("policy_id", "limitation_statement")
    @classmethod
    def text_must_be_explicit(cls, value: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("language evaluation policy text must be explicit")
        return value

    @field_validator("entries")
    @classmethod
    def entries_must_be_canonical(
        cls, values: tuple[DepartmentLanguageEvaluation, ...]
    ) -> tuple[DepartmentLanguageEvaluation, ...]:
        keys = tuple((entry.parent_college, entry.target) for entry in values)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("language evaluation entries must be sorted and unique")
        return values


class LanguageEvaluationStatus(str, Enum):
    CONFIRMED = "confirmed"
    NEEDS_INFORMATION = "needs_information"
    NOT_COVERED = "not_covered"


class LanguageEvaluationResult(LanguageEvaluationModel):
    policy_id: str
    status: LanguageEvaluationStatus
    target: str | None
    parent_college: str | None
    assessment_source: Literal["written_exam"] | None
    result_scale: Literal["pass_fail"] | None
    required_for_all: Literal[True] | None
    external_score_exemption: Literal[False] | None
    selection_role: Literal["necessary_condition"] | None
    evidence: OfficialEvidenceReference | None
    limitation_statement: str

    @model_validator(mode="after")
    def result_must_reconcile(self) -> LanguageEvaluationResult:
        metadata = (
            self.assessment_source,
            self.result_scale,
            self.required_for_all,
            self.external_score_exemption,
            self.selection_role,
            self.evidence,
        )
        if self.status is LanguageEvaluationStatus.CONFIRMED:
            if (
                self.target is None
                or self.parent_college is None
                or any(value is None for value in metadata)
            ):
                raise ValueError("confirmed language evaluation requires complete reviewed data")
        elif any(value is not None for value in metadata):
            raise ValueError("unconfirmed language evaluation cannot expose reviewed metadata")
        return self


def resolve_language_evaluation(
    profile: ApplicantProfile,
    policy: LanguageEvaluationPolicy,
) -> LanguageEvaluationResult:
    """Resolve an exact reviewed scope without inferring an applicant exam result."""

    profile = ApplicantProfile.model_validate(profile.model_dump(mode="json"))
    policy = LanguageEvaluationPolicy.model_validate(policy.model_dump(mode="json"))
    target = profile.target_application.department_or_program
    parent = profile.target_application.graduate_school_or_college
    if target is None or parent is None:
        return _empty_result(policy, LanguageEvaluationStatus.NEEDS_INFORMATION, target, parent)
    entry = next(
        (
            candidate
            for candidate in policy.entries
            if candidate.target == target and candidate.parent_college == parent
        ),
        None,
    )
    if entry is None:
        return _empty_result(policy, LanguageEvaluationStatus.NOT_COVERED, target, parent)
    binding = entry.evidence_binding
    return LanguageEvaluationResult(
        policy_id=policy.policy_id,
        status=LanguageEvaluationStatus.CONFIRMED,
        target=target,
        parent_college=parent,
        assessment_source=entry.assessment_source,
        result_scale=entry.result_scale,
        required_for_all=entry.required_for_all,
        external_score_exemption=entry.external_score_exemption,
        selection_role=entry.selection_role,
        evidence=OfficialEvidenceReference(
            document_id=binding.document_id,
            fact_id=binding.fact_id,
            source_pages=binding.source_pages,
            role=EvidenceRole.PRIMARY,
        ),
        limitation_statement=policy.limitation_statement,
    )


def _empty_result(
    policy: LanguageEvaluationPolicy,
    status: LanguageEvaluationStatus,
    target: str | None,
    parent: str | None,
) -> LanguageEvaluationResult:
    return LanguageEvaluationResult(
        policy_id=policy.policy_id,
        status=status,
        target=target,
        parent_college=parent,
        assessment_source=None,
        result_scale=None,
        required_for_all=None,
        external_score_exemption=None,
        selection_role=None,
        evidence=None,
        limitation_statement=policy.limitation_statement,
    )


__all__ = [
    "DepartmentLanguageEvaluation",
    "LanguageEvaluationPolicy",
    "LanguageEvaluationResult",
    "LanguageEvaluationStatus",
    "resolve_language_evaluation",
]
