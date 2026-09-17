"""Reviewed department-level language evaluation methods and uses."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .applicability import EvidenceRole, OfficialEvidenceBinding, OfficialEvidenceReference
from .applicant_profile import ApplicantProfile


class LanguageEvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LanguageEvaluationUsage(str, Enum):
    ORAL_EXAM_CANDIDATE_SELECTION = "oral_exam_candidate_selection"
    FINAL_HOLISTIC_EVALUATION = "final_holistic_evaluation"


class DepartmentLanguageEvaluation(LanguageEvaluationModel):
    target: str
    parent_college: str
    application_route: Literal["b_schedule"] | None = None
    assessment_source: Literal["written_exam", "external_score"] = "written_exam"
    result_scale: Literal["pass_fail"] | None = "pass_fail"
    required_for_all: Literal[True] | None = True
    external_score_exemption: Literal[False] | None = False
    selection_role: Literal["necessary_condition"] | None = "necessary_condition"
    no_internal_written_exam: Literal[True] | None = None
    evaluation_uses: tuple[LanguageEvaluationUsage, ...] = ()
    limitation_statement: str | None = None
    evidence_binding: OfficialEvidenceBinding

    @field_validator("target", "parent_college")
    @classmethod
    def text_must_be_explicit(cls, value: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("language evaluation scope must be explicit")
        return value

    @field_validator("limitation_statement")
    @classmethod
    def optional_text_must_be_explicit(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != value.strip()):
            raise ValueError("language evaluation limitation must be explicit")
        return value

    @model_validator(mode="after")
    def method_metadata_must_reconcile(self) -> DepartmentLanguageEvaluation:
        if self.assessment_source == "written_exam":
            if (
                self.application_route is not None
                or self.result_scale != "pass_fail"
                or self.required_for_all is not True
                or self.external_score_exemption is not False
                or self.selection_role != "necessary_condition"
                or self.no_internal_written_exam is not None
                or self.evaluation_uses
            ):
                raise ValueError("written exam evaluation metadata is inconsistent")
        elif (
            self.application_route != "b_schedule"
            or self.result_scale is not None
            or self.required_for_all is not None
            or self.external_score_exemption is not None
            or self.selection_role is not None
            or self.no_internal_written_exam is not True
            or self.evaluation_uses
            != (
                LanguageEvaluationUsage.ORAL_EXAM_CANDIDATE_SELECTION,
                LanguageEvaluationUsage.FINAL_HOLISTIC_EVALUATION,
            )
        ):
            raise ValueError("external score evaluation metadata is inconsistent")
        return self


class LanguageEvaluationPolicy(LanguageEvaluationModel):
    policy_id: str
    entries: tuple[DepartmentLanguageEvaluation, ...] = Field(min_length=1)
    limitation_statement: str
    out_of_scope_statement: str

    @field_validator("policy_id", "limitation_statement", "out_of_scope_statement")
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
        keys = tuple(
            (entry.parent_college, entry.target, entry.application_route or "") for entry in values
        )
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("language evaluation entries must be sorted and unique")
        scopes: dict[tuple[str, str], set[str | None]] = {}
        for entry in values:
            scopes.setdefault((entry.parent_college, entry.target), set()).add(
                entry.application_route
            )
        if any(None in routes and len(routes) > 1 for routes in scopes.values()):
            raise ValueError("route-neutral and route-specific entries cannot overlap")
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
    application_route: str | None
    assessment_source: Literal["written_exam", "external_score"] | None
    result_scale: Literal["pass_fail"] | None
    required_for_all: Literal[True] | None
    external_score_exemption: Literal[False] | None
    selection_role: Literal["necessary_condition"] | None
    no_internal_written_exam: Literal[True] | None
    evaluation_uses: tuple[LanguageEvaluationUsage, ...] | None
    evidence: OfficialEvidenceReference | None
    limitation_statement: str

    @field_validator("application_route")
    @classmethod
    def route_must_be_explicit(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != value.strip()):
            raise ValueError("application route must be explicit")
        return value

    @model_validator(mode="after")
    def result_must_reconcile(self) -> LanguageEvaluationResult:
        metadata = (
            self.assessment_source,
            self.result_scale,
            self.required_for_all,
            self.external_score_exemption,
            self.selection_role,
            self.no_internal_written_exam,
            self.evaluation_uses,
            self.evidence,
        )
        if self.status is LanguageEvaluationStatus.CONFIRMED:
            if (
                self.target is None
                or self.parent_college is None
                or self.assessment_source is None
                or self.evaluation_uses is None
                or self.evidence is None
            ):
                raise ValueError("confirmed language evaluation requires complete reviewed data")
            if self.assessment_source == "written_exam":
                if (
                    self.result_scale != "pass_fail"
                    or self.required_for_all is not True
                    or self.external_score_exemption is not False
                    or self.selection_role != "necessary_condition"
                    or self.no_internal_written_exam is not None
                    or self.evaluation_uses
                ):
                    raise ValueError("written exam result metadata is inconsistent")
            elif (
                self.application_route != "b_schedule"
                or self.result_scale is not None
                or self.required_for_all is not None
                or self.external_score_exemption is not None
                or self.selection_role is not None
                or self.no_internal_written_exam is not True
                or self.evaluation_uses
                != (
                    LanguageEvaluationUsage.ORAL_EXAM_CANDIDATE_SELECTION,
                    LanguageEvaluationUsage.FINAL_HOLISTIC_EVALUATION,
                )
            ):
                raise ValueError("external score result metadata is inconsistent")
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
    route = profile.target_application.application_route
    if target is None or parent is None:
        return _empty_result(
            policy, LanguageEvaluationStatus.NEEDS_INFORMATION, target, parent, route
        )
    scope_entries = tuple(
        candidate
        for candidate in policy.entries
        if candidate.target == target and candidate.parent_college == parent
    )
    if not scope_entries:
        return _empty_result(policy, LanguageEvaluationStatus.NOT_COVERED, target, parent, route)
    if route is None and any(
        candidate.application_route is not None for candidate in scope_entries
    ):
        return _empty_result(
            policy, LanguageEvaluationStatus.NEEDS_INFORMATION, target, parent, route
        )
    entry = next(
        (
            candidate
            for candidate in scope_entries
            if candidate.application_route is None or candidate.application_route == route
        ),
        None,
    )
    if entry is None:
        return _empty_result(policy, LanguageEvaluationStatus.NOT_COVERED, target, parent, route)
    binding = entry.evidence_binding
    return LanguageEvaluationResult(
        policy_id=policy.policy_id,
        status=LanguageEvaluationStatus.CONFIRMED,
        target=target,
        parent_college=parent,
        application_route=route,
        assessment_source=entry.assessment_source,
        result_scale=entry.result_scale,
        required_for_all=entry.required_for_all,
        external_score_exemption=entry.external_score_exemption,
        selection_role=entry.selection_role,
        no_internal_written_exam=entry.no_internal_written_exam,
        evaluation_uses=entry.evaluation_uses,
        evidence=OfficialEvidenceReference(
            document_id=binding.document_id,
            fact_id=binding.fact_id,
            source_pages=binding.source_pages,
            role=EvidenceRole.PRIMARY,
        ),
        limitation_statement=entry.limitation_statement or policy.limitation_statement,
    )


def _empty_result(
    policy: LanguageEvaluationPolicy,
    status: LanguageEvaluationStatus,
    target: str | None,
    parent: str | None,
    route: str | None,
) -> LanguageEvaluationResult:
    return LanguageEvaluationResult(
        policy_id=policy.policy_id,
        status=status,
        target=target,
        parent_college=parent,
        application_route=route,
        assessment_source=None,
        result_scale=None,
        required_for_all=None,
        external_score_exemption=None,
        selection_role=None,
        no_internal_written_exam=None,
        evaluation_uses=None,
        evidence=None,
        limitation_statement=policy.out_of_scope_statement,
    )


__all__ = [
    "DepartmentLanguageEvaluation",
    "LanguageEvaluationPolicy",
    "LanguageEvaluationResult",
    "LanguageEvaluationStatus",
    "LanguageEvaluationUsage",
    "resolve_language_evaluation",
]
