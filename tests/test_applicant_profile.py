from __future__ import annotations

import importlib
import inspect
import json
import math
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.reasoning import (
    APPLICANT_PROFILE_SCHEMA_VERSION,
    AcademicCredential,
    ApplicantProfile,
    ApplicantProfileError,
    DegreeLevel,
    EligibilityFacts,
    IndividualReviewStatus,
    IntakeMonth,
    LanguageResultStatus,
    LanguageTestResult,
    TargetApplication,
    canonical_applicant_profile_bytes,
    load_applicant_profile,
    load_applicant_profile_bytes,
)


def _profile_payload() -> dict[str, object]:
    return {
        "schema_version": APPLICANT_PROFILE_SCHEMA_VERSION,
        "target_application": {
            "graduate_school_or_college": "Graduate School of Engineering",
            "department_or_program": "Information Engineering",
            "requested_degree_level": "master",
            "intake_year": 2027,
            "intake_month": 4,
            "application_route": "general",
        },
        "citizenship_and_residence": {
            "citizenship_country_codes": ["US", "JP"],
            "current_residence_country_code": "JP",
            "residence_status_category": "student",
        },
        "academic_credentials": [
            {
                "institution_country_code": "US",
                "degree_level": "bachelor",
                "completion_state": "expected",
                "completion_date": None,
                "expected_completion_date": "2027-03-31",
                "years_of_education": 16,
            }
        ],
        "eligibility_facts": {
            "age_at_enrollment": 23,
            "professional_experience_months": 0,
            "research_experience_months": 12,
            "individual_review_status": "requested",
            "individual_review_requested": True,
            "individual_review_completed": False,
        },
        "language_test_results": [
            {
                "test_kind": "TOEFL iBT",
                "score": 100,
                "test_date": "2026-07-01",
                "validity_status": "valid",
                "official_report_available": True,
            }
        ],
    }


def _unknown_profile_payload() -> dict[str, object]:
    return {
        "schema_version": APPLICANT_PROFILE_SCHEMA_VERSION,
        "target_application": {
            "graduate_school_or_college": None,
            "department_or_program": None,
            "requested_degree_level": None,
            "intake_year": None,
            "intake_month": None,
            "application_route": None,
        },
        "citizenship_and_residence": {
            "citizenship_country_codes": None,
            "current_residence_country_code": None,
            "residence_status_category": None,
        },
        "academic_credentials": None,
        "eligibility_facts": {
            "age_at_enrollment": None,
            "professional_experience_months": None,
            "research_experience_months": None,
            "individual_review_status": None,
            "individual_review_requested": None,
            "individual_review_completed": None,
        },
        "language_test_results": None,
    }


def test_full_known_profile_round_trips_as_canonical_json() -> None:
    profile = load_applicant_profile_bytes(json.dumps(_profile_payload()).encode("utf-8"))

    canonical = canonical_applicant_profile_bytes(profile)

    assert canonical.endswith(b"\n")
    assert b"\r\n" not in canonical
    assert json.loads(canonical) == profile.model_dump(mode="json")
    assert load_applicant_profile_bytes(canonical) == profile
    assert profile.citizenship_and_residence.citizenship_country_codes == ("JP", "US")


def test_all_unknown_fields_are_explicitly_null() -> None:
    profile = ApplicantProfile.model_validate(_unknown_profile_payload())

    assert profile.model_dump(mode="json") == _unknown_profile_payload()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("target_application", "intake_year"), None),
        (("citizenship_and_residence", "citizenship_country_codes"), []),
        (("eligibility_facts", "individual_review_requested"), False),
        (("eligibility_facts", "professional_experience_months"), 0),
    ],
)
def test_null_empty_false_and_zero_keep_distinct_meanings(
    path: tuple[str, str], value: object
) -> None:
    payload = _unknown_profile_payload()
    payload[path[0]][path[1]] = value  # type: ignore[index]

    profile = ApplicantProfile.model_validate(payload)

    assert profile.model_dump(mode="json")[path[0]][path[1]] == value


def test_required_fields_and_extras_fail_closed() -> None:
    payload = _unknown_profile_payload()
    del payload["target_application"]["application_route"]  # type: ignore[index]
    with pytest.raises(ValidationError):
        ApplicantProfile.model_validate(payload)

    payload = _unknown_profile_payload()
    payload["private_name"] = "not allowed"
    with pytest.raises(ValidationError):
        ApplicantProfile.model_validate(payload)


def test_academic_and_language_order_is_preserved() -> None:
    payload = _profile_payload()
    payload["academic_credentials"].append(  # type: ignore[union-attr]
        {
            "institution_country_code": "JP",
            "degree_level": "master",
            "completion_state": "completed",
            "completion_date": "2026-03-31",
            "expected_completion_date": None,
            "years_of_education": 18,
        }
    )
    payload["language_test_results"].append(  # type: ignore[union-attr]
        {
            "test_kind": "IELTS",
            "score": "7.5",
            "test_date": "2026-05-01",
            "validity_status": "valid",
            "official_report_available": False,
        }
    )

    profile = ApplicantProfile.model_validate(payload)

    assert [
        credential.institution_country_code for credential in profile.academic_credentials or ()
    ] == [
        "US",
        "JP",
    ]
    assert [result.test_kind for result in profile.language_test_results or ()] == [
        "TOEFL iBT",
        "IELTS",
    ]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), "2.0"),
        (("target_application", "intake_month"), 13),
        (("target_application", "intake_year"), True),
        (("citizenship_and_residence", "current_residence_country_code"), "jp"),
        (("citizenship_and_residence", "residence_status_category"), " unknown "),
        (("eligibility_facts", "age_at_enrollment"), -1),
        (("eligibility_facts", "age_at_enrollment"), True),
    ],
)
def test_version_enum_string_and_boolean_number_validation(
    path: tuple[str, ...], value: object
) -> None:
    payload = _unknown_profile_payload()
    target = payload
    for component in path[:-1]:
        target = target[component]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        ApplicantProfile.model_validate(payload)


@pytest.mark.parametrize(
    "credential",
    [
        {
            "institution_country_code": "JP",
            "degree_level": "bachelor",
            "completion_state": "completed",
            "completion_date": "2026-03-31",
            "expected_completion_date": "2027-03-31",
            "years_of_education": 16,
        },
        {
            "institution_country_code": "JP",
            "degree_level": "bachelor",
            "completion_state": "not_completed",
            "completion_date": "2026-03-31",
            "expected_completion_date": None,
            "years_of_education": 16,
        },
    ],
)
def test_contradictory_credential_states_fail(credential: dict[str, object]) -> None:
    payload = _unknown_profile_payload()
    payload["academic_credentials"] = [credential]

    with pytest.raises(ValidationError):
        ApplicantProfile.model_validate(payload)


def test_contradictory_review_and_language_result_states_fail() -> None:
    payload = _unknown_profile_payload()
    payload["eligibility_facts"]["individual_review_status"] = "completed"  # type: ignore[index]
    payload["eligibility_facts"]["individual_review_completed"] = False  # type: ignore[index]
    with pytest.raises(ValidationError):
        ApplicantProfile.model_validate(payload)

    payload = _unknown_profile_payload()
    payload["language_test_results"] = [
        {
            "test_kind": "TOEFL iBT",
            "score": 100,
            "test_date": None,
            "validity_status": "not_available",
            "official_report_available": None,
        }
    ]
    with pytest.raises(ValidationError):
        ApplicantProfile.model_validate(payload)


def test_duplicate_country_codes_invalid_dates_and_nonfinite_scores_fail() -> None:
    payload = _unknown_profile_payload()
    payload["citizenship_and_residence"]["citizenship_country_codes"] = ["JP", "JP"]  # type: ignore[index]
    with pytest.raises(ValidationError):
        ApplicantProfile.model_validate(payload)

    payload = _profile_payload()
    payload["academic_credentials"][0]["expected_completion_date"] = "2027-02-30"  # type: ignore[index,union-attr]
    with pytest.raises(ValidationError):
        ApplicantProfile.model_validate(payload)

    payload = _profile_payload()
    payload["language_test_results"][0]["score"] = math.nan  # type: ignore[index,union-attr]
    with pytest.raises(ValidationError):
        ApplicantProfile.model_validate(payload)


def test_canonicalization_is_stable_and_sorts_only_citizenship_set() -> None:
    profile = ApplicantProfile.model_validate(_profile_payload())
    reordered = _profile_payload()
    reordered["citizenship_and_residence"]["citizenship_country_codes"] = ["JP", "US"]  # type: ignore[index]

    assert canonical_applicant_profile_bytes(profile) == canonical_applicant_profile_bytes(
        ApplicantProfile.model_validate(reordered)
    )


def test_loaders_reject_unsafe_files_and_keep_errors_private(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    directory = tmp_path / "profile-directory"
    directory.mkdir()
    for unsafe_path in (missing, directory):
        with pytest.raises(ApplicantProfileError) as error:
            load_applicant_profile(unsafe_path)
        assert str(unsafe_path) not in str(error.value)

    source = tmp_path / "profile.json"
    source.write_bytes(json.dumps(_unknown_profile_payload()).encode("utf-8"))
    symlink = tmp_path / "profile-link.json"
    try:
        os.symlink(source, symlink)
    except OSError:
        pytest.skip("symlink creation is unavailable in this environment")
    with pytest.raises(ApplicantProfileError):
        load_applicant_profile(symlink)


def test_byte_loader_hides_supplied_values_and_rejects_nonfinite_json() -> None:
    secret = "private-email@example.test"
    with pytest.raises(ApplicantProfileError) as error:
        load_applicant_profile_bytes(
            f'{{"schema_version":"2.0","private_name":"{secret}"}}'.encode("utf-8")
        )
    assert secret not in str(error.value)

    with pytest.raises(ApplicantProfileError):
        load_applicant_profile_bytes(b'{"schema_version":"1.0","value":NaN}')

    with pytest.raises(ApplicantProfileError):
        load_applicant_profile_bytes("not bytes")  # type: ignore[arg-type]


def test_canonicalizer_revalidates_constructed_or_copied_models() -> None:
    with pytest.raises(ApplicantProfileError):
        canonical_applicant_profile_bytes(
            ApplicantProfile.model_construct(schema_version=APPLICANT_PROFILE_SCHEMA_VERSION)
        )

    valid_profile = ApplicantProfile.model_validate(_unknown_profile_payload())
    with pytest.raises(ApplicantProfileError):
        canonical_applicant_profile_bytes(
            valid_profile.model_copy(update={"schema_version": "2.0"})
        )

    with pytest.raises(ApplicantProfileError):
        canonical_applicant_profile_bytes("not a profile")  # type: ignore[arg-type]


def test_public_schema_import_has_no_retrieval_model_or_network_dependency() -> None:
    module = importlib.import_module("jgrad_admission_rag.reasoning.applicant_profile")

    source = inspect.getsource(module)
    assert "jgrad_admission_rag.retrieval" not in source
    assert "sentence_transformers" not in source
    assert "requests" not in source
    assert ApplicantProfile.model_fields["target_application"].is_required()
    assert TargetApplication.model_fields["intake_month"].annotation == IntakeMonth | None
    assert AcademicCredential.model_fields["degree_level"].annotation == DegreeLevel | None
    assert (
        EligibilityFacts.model_fields["individual_review_status"].annotation
        == IndividualReviewStatus | None
    )
    assert (
        LanguageTestResult.model_fields["validity_status"].annotation == LanguageResultStatus | None
    )
