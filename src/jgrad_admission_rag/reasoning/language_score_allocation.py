"""Reviewed department-level English score allocations."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .applicability import EvidenceRole, OfficialEvidenceBinding, OfficialEvidenceReference
from .applicant_profile import ApplicantProfile


class LanguageScoreAllocationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DepartmentLanguageScoreAllocation(LanguageScoreAllocationModel):
    target: str
    parent_college: str
    maximum_points: StrictInt = Field(gt=0)
    unit: Literal["points"] = "points"
    evidence_binding: OfficialEvidenceBinding

    @field_validator("target", "parent_college")
    @classmethod
    def text_must_be_explicit(cls, value: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("allocation scope must be explicit")
        return value


class LanguageScoreAllocationPolicy(LanguageScoreAllocationModel):
    policy_id: str
    entries: tuple[DepartmentLanguageScoreAllocation, ...] = Field(min_length=1)
    limitation_statement: str

    @field_validator("policy_id", "limitation_statement")
    @classmethod
    def text_must_be_explicit(cls, value: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("allocation policy text must be explicit")
        return value

    @field_validator("entries")
    @classmethod
    def entries_must_be_canonical(
        cls, values: tuple[DepartmentLanguageScoreAllocation, ...]
    ) -> tuple[DepartmentLanguageScoreAllocation, ...]:
        keys = tuple((entry.parent_college, entry.target) for entry in values)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("allocation entries must be sorted and unique")
        return values


class LanguageScoreAllocationStatus(str, Enum):
    CONFIRMED = "confirmed"
    NEEDS_INFORMATION = "needs_information"
    NOT_PUBLISHED = "not_published"


class LanguageScoreAllocationResult(LanguageScoreAllocationModel):
    policy_id: str
    status: LanguageScoreAllocationStatus
    target: str | None
    parent_college: str | None
    maximum_points: StrictInt | None
    unit: Literal["points"] | None
    evidence: OfficialEvidenceReference | None
    limitation_statement: str

    @model_validator(mode="after")
    def result_must_reconcile(self) -> LanguageScoreAllocationResult:
        payload = (self.maximum_points, self.unit, self.evidence)
        if self.status is LanguageScoreAllocationStatus.CONFIRMED:
            if (
                self.target is None
                or self.parent_college is None
                or any(v is None for v in payload)
            ):
                raise ValueError("confirmed allocation requires complete reviewed data")
        elif any(value is not None for value in payload):
            raise ValueError("non-confirmed allocation cannot expose points or evidence")
        return self


def resolve_language_score_allocation(
    profile: ApplicantProfile,
    policy: LanguageScoreAllocationPolicy,
) -> LanguageScoreAllocationResult:
    """Resolve only an exact reviewed target/college pair; never infer a score."""

    profile = ApplicantProfile.model_validate(profile.model_dump(mode="json"))
    policy = LanguageScoreAllocationPolicy.model_validate(policy.model_dump(mode="json"))
    target = profile.target_application.department_or_program
    parent = profile.target_application.graduate_school_or_college
    if target is None or parent is None:
        return _empty_result(
            policy, LanguageScoreAllocationStatus.NEEDS_INFORMATION, target, parent
        )
    entry = next(
        (
            candidate
            for candidate in policy.entries
            if candidate.target == target and candidate.parent_college == parent
        ),
        None,
    )
    if entry is None:
        return _empty_result(policy, LanguageScoreAllocationStatus.NOT_PUBLISHED, target, parent)
    binding = entry.evidence_binding
    return LanguageScoreAllocationResult(
        policy_id=policy.policy_id,
        status=LanguageScoreAllocationStatus.CONFIRMED,
        target=target,
        parent_college=parent,
        maximum_points=entry.maximum_points,
        unit=entry.unit,
        evidence=OfficialEvidenceReference(
            document_id=binding.document_id,
            fact_id=binding.fact_id,
            source_pages=binding.source_pages,
            role=EvidenceRole.PRIMARY,
        ),
        limitation_statement=policy.limitation_statement,
    )


def _empty_result(
    policy: LanguageScoreAllocationPolicy,
    status: LanguageScoreAllocationStatus,
    target: str | None,
    parent: str | None,
) -> LanguageScoreAllocationResult:
    return LanguageScoreAllocationResult(
        policy_id=policy.policy_id,
        status=status,
        target=target,
        parent_college=parent,
        maximum_points=None,
        unit=None,
        evidence=None,
        limitation_statement=policy.limitation_statement,
    )


__all__ = [
    "DepartmentLanguageScoreAllocation",
    "LanguageScoreAllocationPolicy",
    "LanguageScoreAllocationResult",
    "LanguageScoreAllocationStatus",
    "resolve_language_score_allocation",
]
