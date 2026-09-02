"""Strict, caller-supplied applicant facts for later admission reasoning.

This module deliberately has no dependency on retrieval, evidence, or reasoning code.  A profile
states only what an applicant (or their operator) supplied; it neither proves eligibility nor
contains official guideline evidence.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool, StrictFloat, StrictInt, ValidationError
from pydantic import field_validator, model_validator

APPLICANT_PROFILE_SCHEMA_VERSION = "1.0"
SUPPORTED_APPLICANT_PROFILE_SCHEMA_VERSIONS = frozenset({APPLICANT_PROFILE_SCHEMA_VERSION})

_ISO_COUNTRY_CODE = re.compile(r"[A-Z]{2}\Z")
_PLACEHOLDERS = frozenset({"unknown", "n/a", "na", "undecided", "未定", "不明"})

__all__ = [
    "APPLICANT_PROFILE_SCHEMA_VERSION",
    "SUPPORTED_APPLICANT_PROFILE_SCHEMA_VERSIONS",
    "AcademicCredential",
    "ApplicantProfile",
    "ApplicantProfileError",
    "CitizenshipAndResidence",
    "CompletionState",
    "DegreeLevel",
    "EligibilityFacts",
    "IndividualReviewStatus",
    "IntakeMonth",
    "LanguageResultStatus",
    "LanguageTestResult",
    "TargetApplication",
    "canonical_applicant_profile_bytes",
    "load_applicant_profile",
    "load_applicant_profile_bytes",
]


class ApplicantProfileError(Exception):
    """Raised when an applicant profile cannot be validated, serialized, or loaded safely."""


class ApplicantProfileModel(BaseModel):
    """Base class for immutable, closed applicant-supplied profile records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DegreeLevel(str, Enum):
    BACHELOR = "bachelor"
    MASTER = "master"
    DOCTORATE = "doctorate"
    PROFESSIONAL = "professional"
    OTHER = "other"


class CompletionState(str, Enum):
    COMPLETED = "completed"
    EXPECTED = "expected"
    NOT_COMPLETED = "not_completed"


class IntakeMonth(int, Enum):
    JANUARY = 1
    FEBRUARY = 2
    MARCH = 3
    APRIL = 4
    MAY = 5
    JUNE = 6
    JULY = 7
    AUGUST = 8
    SEPTEMBER = 9
    OCTOBER = 10
    NOVEMBER = 11
    DECEMBER = 12


class IndividualReviewStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"
    COMPLETED = "completed"


class LanguageResultStatus(str, Enum):
    VALID = "valid"
    EXPIRED = "expired"
    NOT_AVAILABLE = "not_available"


class TargetApplication(ApplicantProfileModel):
    graduate_school_or_college: str | None
    department_or_program: str | None
    requested_degree_level: DegreeLevel | None
    intake_year: StrictInt | None
    intake_month: IntakeMonth | None
    application_route: str | None

    @field_validator("graduate_school_or_college", "department_or_program", "application_route")
    @classmethod
    def strings_must_be_explicit_when_supplied(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_explicit_string(value, "target application value")
        return value

    @field_validator("intake_year")
    @classmethod
    def intake_year_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("intake_year must be positive")
        return value


class CitizenshipAndResidence(ApplicantProfileModel):
    citizenship_country_codes: tuple[str, ...] | None
    current_residence_country_code: str | None
    residence_status_category: str | None

    @field_validator("citizenship_country_codes")
    @classmethod
    def citizenship_codes_must_be_unique_iso_codes(
        cls, value: tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        if value is None:
            return None
        _validate_country_codes(value, "citizenship_country_codes")
        # Citizenship is a set.  Its order has no meaning, so use the stable serialized order.
        return tuple(sorted(value))

    @field_validator("current_residence_country_code")
    @classmethod
    def residence_country_must_be_an_iso_code(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_country_code(value, "current_residence_country_code")
        return value

    @field_validator("residence_status_category")
    @classmethod
    def residence_category_must_be_explicit(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_explicit_string(value, "residence_status_category")
        return value


class AcademicCredential(ApplicantProfileModel):
    institution_country_code: str | None
    degree_level: DegreeLevel | None
    completion_state: CompletionState | None
    completion_date: date | None
    expected_completion_date: date | None
    years_of_education: StrictInt | None

    @field_validator("institution_country_code")
    @classmethod
    def institution_country_must_be_an_iso_code(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_country_code(value, "institution_country_code")
        return value

    @field_validator("years_of_education")
    @classmethod
    def years_of_education_must_not_be_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("years_of_education must not be negative")
        return value

    @model_validator(mode="after")
    def completion_fields_must_reconcile(self) -> AcademicCredential:
        if (
            self.completion_state is CompletionState.COMPLETED
            and self.expected_completion_date is not None
        ):
            raise ValueError("completed credentials cannot have an expected_completion_date")
        if self.completion_state is CompletionState.EXPECTED and self.completion_date is not None:
            raise ValueError("expected credentials cannot have a completion_date")
        if self.completion_state is CompletionState.NOT_COMPLETED and (
            self.completion_date is not None or self.expected_completion_date is not None
        ):
            raise ValueError("not_completed credentials cannot have completion dates")
        return self


class EligibilityFacts(ApplicantProfileModel):
    age_at_enrollment: StrictInt | None
    professional_experience_months: StrictInt | None
    research_experience_months: StrictInt | None
    individual_review_status: IndividualReviewStatus | None
    individual_review_requested: StrictBool | None
    individual_review_completed: StrictBool | None

    @field_validator(
        "age_at_enrollment", "professional_experience_months", "research_experience_months"
    )
    @classmethod
    def quantities_must_not_be_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("eligibility quantity must not be negative")
        return value

    @model_validator(mode="after")
    def individual_review_fields_must_not_contradict(self) -> EligibilityFacts:
        status = self.individual_review_status
        if status is IndividualReviewStatus.NOT_REQUESTED and (
            self.individual_review_requested is True or self.individual_review_completed is True
        ):
            raise ValueError("individual review status contradicts supplied review facts")
        if status is IndividualReviewStatus.REQUESTED and (
            self.individual_review_requested is False or self.individual_review_completed is True
        ):
            raise ValueError("individual review status contradicts supplied review facts")
        if status is IndividualReviewStatus.COMPLETED and (
            self.individual_review_requested is False or self.individual_review_completed is False
        ):
            raise ValueError("individual review status contradicts supplied review facts")
        if self.individual_review_completed is True and self.individual_review_requested is False:
            raise ValueError("a completed individual review cannot be unrequested")
        return self


class LanguageTestResult(ApplicantProfileModel):
    test_kind: str | None
    score: StrictInt | StrictFloat | str | None
    test_date: date | None
    validity_status: LanguageResultStatus | None
    official_report_available: StrictBool | None

    @field_validator("test_kind")
    @classmethod
    def test_kind_must_be_explicit(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_explicit_string(value, "test_kind")
        return value

    @field_validator("score")
    @classmethod
    def score_must_be_finite_or_explicit(
        cls, value: int | float | str | None
    ) -> int | float | str | None:
        if value is None:
            return None
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("score must be finite")
        if isinstance(value, str):
            _validate_explicit_string(value, "score")
        return value

    @model_validator(mode="after")
    def result_fields_must_not_contradict(self) -> LanguageTestResult:
        if self.score is not None and self.test_kind is None:
            raise ValueError("a score requires a supplied test_kind")
        if self.validity_status is LanguageResultStatus.NOT_AVAILABLE and (
            self.score is not None
            or self.test_date is not None
            or self.official_report_available is True
        ):
            raise ValueError("not_available language results cannot have supplied result facts")
        return self


class ApplicantProfile(ApplicantProfileModel):
    """Versioned applicant assertions, distinct from official evidence and conclusions."""

    schema_version: str
    target_application: TargetApplication
    citizenship_and_residence: CitizenshipAndResidence
    academic_credentials: tuple[AcademicCredential, ...] | None
    eligibility_facts: EligibilityFacts
    language_test_results: tuple[LanguageTestResult, ...] | None

    @field_validator("schema_version")
    @classmethod
    def schema_version_must_be_supported(cls, value: str) -> str:
        if value not in SUPPORTED_APPLICANT_PROFILE_SCHEMA_VERSIONS:
            raise ValueError("unsupported applicant profile schema version")
        return value


def canonical_applicant_profile_bytes(profile: ApplicantProfile) -> bytes:
    """Serialize a profile into its deterministic UTF-8 JSON representation."""

    try:
        if not isinstance(profile, ApplicantProfile):
            raise TypeError("profile must be an ApplicantProfile")
        validated_profile = ApplicantProfile.model_validate(profile.model_dump(mode="json"))
        serialized = json.dumps(
            validated_profile.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValidationError, ValueError):
        raise ApplicantProfileError("Applicant profile is invalid or unsupported") from None
    return f"{serialized}\n".encode("utf-8")


def load_applicant_profile_bytes(raw_bytes: bytes) -> ApplicantProfile:
    """Validate one JSON byte payload without exposing supplied personal data in errors."""

    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError("profile input must be bytes")
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_non_finite_json)
        return ApplicantProfile.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValidationError, ValueError):
        raise ApplicantProfileError("Applicant profile bytes are invalid or unsupported") from None


def load_applicant_profile(path_value: str | Path) -> ApplicantProfile:
    """Load a profile only from a regular, non-symlinked file."""

    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError("profile path is not a regular file")
        raw_bytes = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise ApplicantProfileError("Applicant profile file is unavailable or unsafe") from None
    return load_applicant_profile_bytes(raw_bytes)


def _reject_non_finite_json(_: str) -> Any:
    raise ValueError("non-finite JSON numbers are not supported")


def _validate_explicit_string(value: str, name: str) -> None:
    if not value or value != value.strip() or value.casefold() in _PLACEHOLDERS:
        raise ValueError(f"{name} must be an explicit, trimmed value")


def _validate_country_code(value: str, name: str) -> None:
    if not _ISO_COUNTRY_CODE.fullmatch(value):
        raise ValueError(f"{name} must be an uppercase ISO 3166-1 alpha-2 code")


def _validate_country_codes(values: tuple[str, ...], name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{name} must not contain duplicates")
    for value in values:
        _validate_country_code(value, name)
