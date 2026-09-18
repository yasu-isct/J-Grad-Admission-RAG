"""Reviewed common application-material applicability for ordinary applicants."""

from __future__ import annotations

from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from .applicability import EvidenceRole, OfficialEvidenceBinding, OfficialEvidenceReference
from .applicant_profile import ApplicantProfile, CredentialBasis, DegreeLevel


class ApplicationMaterialsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApplicationMaterialCode(str, Enum):
    ADDRESS_LABEL = "address_label"
    APPLICATION_FORM = "application_form"
    STATEMENT_OF_PURPOSE = "statement_of_purpose"
    BACHELOR_TRANSCRIPT = "bachelor_transcript"
    GRADUATION_CERTIFICATE = "graduation_or_expected_graduation_certificate"


class ApplicationMaterialApplicability(str, Enum):
    REQUIRED = "required"
    ELIGIBILITY_REVIEW_PATH = "eligibility_review_path"
    NEEDS_INFORMATION = "needs_information"
    NOT_COVERED = "not_covered"


class ReviewedApplicationMaterial(ApplicationMaterialsModel):
    number: StrictInt = Field(ge=1, le=5)
    code: ApplicationMaterialCode
    official_name: str
    exempt_for_eligibility_review_paths: StrictBool

    @field_validator("official_name")
    @classmethod
    def name_must_be_explicit(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("material name must be explicit")
        return value


class ApplicationMaterialsPolicy(ApplicationMaterialsModel):
    policy_id: str
    entries: tuple[ReviewedApplicationMaterial, ...] = Field(min_length=5, max_length=5)
    evidence_binding: OfficialEvidenceBinding
    limitation_statement: str

    @field_validator("policy_id", "limitation_statement")
    @classmethod
    def text_must_be_explicit(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("application materials policy text must be explicit")
        return value

    @field_validator("entries")
    @classmethod
    def entries_must_match_official_order(
        cls, values: tuple[ReviewedApplicationMaterial, ...]
    ) -> tuple[ReviewedApplicationMaterial, ...]:
        if tuple(entry.number for entry in values) != (1, 2, 3, 4, 5):
            raise ValueError("application materials must retain official order")
        if len({entry.code for entry in values}) != 5:
            raise ValueError("application material codes must be unique")
        if any(
            entry.exempt_for_eligibility_review_paths != (entry.number >= 3) for entry in values
        ):
            raise ValueError("eligibility-review exceptions must match official items 3 through 5")
        return values


class ApplicationMaterialResult(ApplicationMaterialsModel):
    number: StrictInt
    code: ApplicationMaterialCode
    official_name: str
    applicability: ApplicationMaterialApplicability


class ApplicationMaterialsResult(ApplicationMaterialsModel):
    policy_id: str
    entries: tuple[ApplicationMaterialResult, ...] = Field(min_length=5, max_length=5)
    credential_basis: CredentialBasis | None
    evidence: OfficialEvidenceReference
    limitation_statement: str

    @model_validator(mode="after")
    def entries_must_remain_canonical(self) -> "ApplicationMaterialsResult":
        if tuple(entry.number for entry in self.entries) != (1, 2, 3, 4, 5):
            raise ValueError("material results must retain official order")
        if len({entry.code for entry in self.entries}) != 5:
            raise ValueError("material result codes must be unique")
        return self


_DIRECT_BASES = frozenset(
    {
        CredentialBasis.UNIVERSITY_GRADUATION,
        CredentialBasis.NIAD_QE_BACHELOR_AWARD,
        CredentialBasis.FOREIGN_16_YEAR_BACHELOR_EQUIVALENT,
        CredentialBasis.FOREIGN_DISTANCE_EDUCATION_IN_JAPAN,
        CredentialBasis.FOREIGN_UNIVERSITY_PROGRAM_IN_JAPAN,
        CredentialBasis.RECOGNIZED_FOREIGN_THREE_YEAR_BACHELOR,
        CredentialBasis.DESIGNATED_SPECIALIZED_TRAINING_COLLEGE,
        CredentialBasis.MINISTER_DESIGNATED_PERSON,
    }
)
_REVIEW_BASES = frozenset(set(CredentialBasis) - set(_DIRECT_BASES))


def resolve_application_materials(
    profile: ApplicantProfile, policy: ApplicationMaterialsPolicy
) -> ApplicationMaterialsResult:
    """Resolve only the p.10 common list; never claim actual submission or receipt."""

    profile = ApplicantProfile.model_validate(profile.model_dump(mode="json"))
    policy = ApplicationMaterialsPolicy.model_validate(policy.model_dump(mode="json"))
    target = profile.target_application
    supported = target.requested_degree_level is DegreeLevel.MASTER and (
        (target.intake_year, target.intake_month.value if target.intake_month else None)
        in {(2026, 9), (2027, 4)}
    )
    target_missing = any(
        value is None
        for value in (target.requested_degree_level, target.intake_year, target.intake_month)
    )
    credentials = profile.academic_credentials
    basis = (
        credentials[0].credential_basis
        if credentials is not None and len(credentials) == 1
        else None
    )

    results = []
    for entry in policy.entries:
        if target_missing:
            applicability = ApplicationMaterialApplicability.NEEDS_INFORMATION
        elif not supported:
            applicability = ApplicationMaterialApplicability.NOT_COVERED
        elif not entry.exempt_for_eligibility_review_paths:
            applicability = ApplicationMaterialApplicability.REQUIRED
        elif basis in _DIRECT_BASES:
            applicability = ApplicationMaterialApplicability.REQUIRED
        elif basis in _REVIEW_BASES:
            applicability = ApplicationMaterialApplicability.ELIGIBILITY_REVIEW_PATH
        else:
            applicability = ApplicationMaterialApplicability.NEEDS_INFORMATION
        results.append(
            ApplicationMaterialResult(
                number=entry.number,
                code=entry.code,
                official_name=entry.official_name,
                applicability=applicability,
            )
        )
    binding = policy.evidence_binding
    return ApplicationMaterialsResult(
        policy_id=policy.policy_id,
        entries=tuple(results),
        credential_basis=basis,
        evidence=OfficialEvidenceReference(
            document_id=binding.document_id,
            fact_id=binding.fact_id,
            source_pages=binding.source_pages,
            role=EvidenceRole.PRIMARY,
        ),
        limitation_statement=policy.limitation_statement,
    )


__all__ = [
    "ApplicationMaterialApplicability",
    "ApplicationMaterialCode",
    "ApplicationMaterialResult",
    "ApplicationMaterialsPolicy",
    "ApplicationMaterialsResult",
    "ReviewedApplicationMaterial",
    "resolve_application_materials",
]
