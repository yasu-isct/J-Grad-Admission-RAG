"""Reviewed language conditions for one explicitly selected admission program."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .applicability import EvidenceRole, OfficialEvidenceBinding, OfficialEvidenceReference
from .applicant_profile import ApplicantProfile, DegreeLevel


class ProgramLanguageConditionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProgramLanguageConditionEntry(ProgramLanguageConditionModel):
    program: str
    application_route: Literal["tsinghua_joint_program"]
    requested_degree_level: Literal[DegreeLevel.MASTER]
    intake_year: Literal[2027]
    intake_month: Literal[4]
    language: Literal["chinese"]
    admission_selection: Literal["excluded"]
    evidence_binding: OfficialEvidenceBinding
    limitation_statement: str

    @field_validator("program", "limitation_statement")
    @classmethod
    def text_must_be_explicit(cls, value: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("program language condition text must be explicit")
        return value


class ProgramLanguageConditionPolicy(ProgramLanguageConditionModel):
    policy_id: str
    entries: tuple[ProgramLanguageConditionEntry, ...] = Field(min_length=1)
    out_of_scope_statement: str

    @field_validator("policy_id", "out_of_scope_statement")
    @classmethod
    def text_must_be_explicit(cls, value: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("program language policy text must be explicit")
        return value

    @field_validator("entries")
    @classmethod
    def entries_must_be_canonical(
        cls, values: tuple[ProgramLanguageConditionEntry, ...]
    ) -> tuple[ProgramLanguageConditionEntry, ...]:
        keys = tuple(
            (
                entry.application_route,
                entry.requested_degree_level.value,
                entry.intake_year,
                entry.intake_month,
                entry.language,
            )
            for entry in values
        )
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("program language entries must be sorted and unique")
        return values


class ProgramLanguageConditionStatus(str, Enum):
    CONFIRMED = "confirmed"
    NEEDS_INFORMATION = "needs_information"
    NOT_COVERED = "not_covered"


class ProgramLanguageConditionResult(ProgramLanguageConditionModel):
    policy_id: str
    status: ProgramLanguageConditionStatus
    application_route: str | None
    requested_degree_level: DegreeLevel | None
    intake_year: StrictInt | None
    intake_month: StrictInt | None
    program: str | None
    language: Literal["chinese"] | None
    admission_selection: Literal["excluded"] | None
    evidence: OfficialEvidenceReference | None
    limitation_statement: str

    @model_validator(mode="after")
    def result_must_reconcile(self) -> ProgramLanguageConditionResult:
        reviewed = (self.program, self.language, self.admission_selection, self.evidence)
        if self.status is ProgramLanguageConditionStatus.CONFIRMED:
            if any(value is None for value in reviewed):
                raise ValueError("confirmed program language condition requires reviewed data")
        elif any(value is not None for value in reviewed):
            raise ValueError("unconfirmed program language condition cannot expose reviewed data")
        return self


def resolve_program_language_condition(
    profile: ApplicantProfile,
    policy: ProgramLanguageConditionPolicy,
) -> ProgramLanguageConditionResult:
    """Resolve only an explicit route, degree and intake without inferring program eligibility."""

    profile = ApplicantProfile.model_validate(profile.model_dump(mode="json"))
    policy = ProgramLanguageConditionPolicy.model_validate(policy.model_dump(mode="json"))
    application = profile.target_application
    supplied = (
        application.application_route,
        application.requested_degree_level,
        application.intake_year,
        application.intake_month,
    )
    if any(value is None for value in supplied):
        return _empty_result(policy, ProgramLanguageConditionStatus.NEEDS_INFORMATION, supplied)
    entry = next(
        (
            candidate
            for candidate in policy.entries
            if candidate.application_route == application.application_route
            and candidate.requested_degree_level == application.requested_degree_level
            and candidate.intake_year == application.intake_year
            and candidate.intake_month == application.intake_month
        ),
        None,
    )
    if entry is None:
        return _empty_result(policy, ProgramLanguageConditionStatus.NOT_COVERED, supplied)
    binding = entry.evidence_binding
    return ProgramLanguageConditionResult(
        policy_id=policy.policy_id,
        status=ProgramLanguageConditionStatus.CONFIRMED,
        application_route=application.application_route,
        requested_degree_level=application.requested_degree_level,
        intake_year=application.intake_year,
        intake_month=application.intake_month,
        program=entry.program,
        language=entry.language,
        admission_selection=entry.admission_selection,
        evidence=OfficialEvidenceReference(
            document_id=binding.document_id,
            fact_id=binding.fact_id,
            source_pages=binding.source_pages,
            role=EvidenceRole.PRIMARY,
        ),
        limitation_statement=entry.limitation_statement,
    )


def _empty_result(
    policy: ProgramLanguageConditionPolicy,
    status: ProgramLanguageConditionStatus,
    supplied: tuple[object | None, ...],
) -> ProgramLanguageConditionResult:
    route, degree, year, month = supplied
    return ProgramLanguageConditionResult(
        policy_id=policy.policy_id,
        status=status,
        application_route=route if isinstance(route, str) else None,
        requested_degree_level=degree if isinstance(degree, DegreeLevel) else None,
        intake_year=year if isinstance(year, int) and not isinstance(year, bool) else None,
        intake_month=month if isinstance(month, int) and not isinstance(month, bool) else None,
        program=None,
        language=None,
        admission_selection=None,
        evidence=None,
        limitation_statement=policy.out_of_scope_statement,
    )


__all__ = [
    "ProgramLanguageConditionEntry",
    "ProgramLanguageConditionPolicy",
    "ProgramLanguageConditionResult",
    "ProgramLanguageConditionStatus",
    "resolve_program_language_condition",
]
