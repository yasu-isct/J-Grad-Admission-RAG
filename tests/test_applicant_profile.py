from __future__ import annotations

import importlib
import inspect
import json
import math
import os
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.reasoning import (
    APPLICANT_PROFILE_SCHEMA_VERSION,
    AcademicCredential,
    ApplicationSubmission,
    ApplicantProfile,
    ApplicantProfileError,
    CredentialBasis,
    DegreeLevel,
    EligibilityFacts,
    IndividualReviewStatus,
    IntakeMonth,
    LanguageResultStatus,
    LanguageScoreSubmissionMethod,
    LanguageTestKind,
    LanguageTestResult,
    OfficialVerificationStatus,
    PreapplicationActions,
    PriorEducationCategory,
    ScholarshipStatus,
    TargetApplication,
    TranscriptUnavailableReason,
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
                "credential_basis": "foreign_16_year_bachelor_equivalent",
                "completion_state": "expected",
                "completion_date": None,
                "expected_completion_date": "2027-03-31",
                "years_of_education": 16,
                "coursework_in_japan": True,
                "program_duration_years": 4,
                "institution_recognition_status": "officially_confirmed",
                "program_designation_status": None,
                "completion_timing_verification_status": "applicant_claimed",
                "person_designation_status": None,
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
                "test_kind": "toefl_ibt",
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
            "age_at_eligibility_cutoff": None,
        },
        "language_test_results": None,
        "application_submission": None,
        "preapplication_actions": None,
    }


def test_full_known_profile_round_trips_as_canonical_json() -> None:
    profile = load_applicant_profile_bytes(json.dumps(_profile_payload()).encode("utf-8"))

    canonical = canonical_applicant_profile_bytes(profile)

    assert canonical.endswith(b"\n")
    assert b"\r\n" not in canonical
    assert json.loads(canonical) == profile.model_dump(mode="json")
    assert load_applicant_profile_bytes(canonical) == profile
    assert profile.citizenship_and_residence.citizenship_country_codes == ("JP", "US")
    assert profile.academic_credentials is not None
    assert (
        profile.academic_credentials[0].credential_basis
        is CredentialBasis.FOREIGN_16_YEAR_BACHELOR_EQUIVALENT
    )
    assert (
        profile.academic_credentials[0].institution_recognition_status
        is OfficialVerificationStatus.OFFICIALLY_CONFIRMED
    )
    assert (
        profile.academic_credentials[0].completion_timing_verification_status
        is OfficialVerificationStatus.APPLICANT_CLAIMED
    )


def test_all_unknown_fields_are_explicitly_null() -> None:
    profile = ApplicantProfile.model_validate(_unknown_profile_payload())

    assert profile.model_dump(mode="json") == _unknown_profile_payload()


def test_preapplication_actions_are_typed_purpose_specific_and_optional() -> None:
    payload = _unknown_profile_payload()
    payload["preapplication_actions"] = {
        "special_accommodation_needed": True,
        "special_accommodation_contacted_admissions": None,
        "foreign_national_rule_applies": True,
        "residence_status_valid_until": "2026-09-28",
        "residence_status_allows_long_term_stay": True,
        "residence_status_contacted_admissions": None,
        "visa_arrangements_needed": True,
        "visa_timing_consulted_advisor": False,
        "transcript_unavailable_reason": "institution_closed",
        "transcript_unavailability_consulted_admissions": True,
        "disaster_fee_consultation_needed": False,
        "disaster_fee_consulted_admissions": None,
        "scholarship_status": "mext",
        "scholarship_copy_emailed_date": "2026-05-27",
        "scholarship_application_method_received": False,
    }

    profile = ApplicantProfile.model_validate(payload)

    assert isinstance(profile.preapplication_actions, PreapplicationActions)
    assert profile.preapplication_actions.residence_status_valid_until == date(2026, 9, 28)
    assert (
        profile.preapplication_actions.transcript_unavailable_reason
        is TranscriptUnavailableReason.INSTITUTION_CLOSED
    )
    assert profile.preapplication_actions.scholarship_status is ScholarshipStatus.MEXT


@pytest.mark.parametrize(
    "field,value",
    [
        ("special_accommodation_needed", 1),
        ("foreign_national_rule_applies", "true"),
        ("scholarship_status", "unknown"),
        ("transcript_unavailable_reason", "missing"),
    ],
)
def test_preapplication_actions_reject_ambiguous_or_non_strict_values(field, value) -> None:
    payload = _unknown_profile_payload()
    payload["preapplication_actions"] = {field: value}

    with pytest.raises(ValidationError):
        ApplicantProfile.model_validate(payload)


def test_rule02b_profile_fields_are_strict_and_typed() -> None:
    payload = _profile_payload()
    credential = payload["academic_credentials"][0]  # type: ignore[index]
    credential.update(  # type: ignore[union-attr]
        credential_basis="review_path10_mot_professional_experience",
        prior_education_category="university_withdrawal",
        years_enrolled_before_withdrawal=2,
        post_university_research_months_at_eligibility_cutoff=12,
        graduate_equivalent_recognition_status="officially_confirmed",
    )
    payload["eligibility_facts"]["age_at_eligibility_cutoff"] = 22  # type: ignore[index]

    profile = ApplicantProfile.model_validate(payload)

    assert profile.academic_credentials is not None
    assert (
        profile.academic_credentials[0].prior_education_category
        is PriorEducationCategory.UNIVERSITY_WITHDRAWAL
    )
    assert profile.eligibility_facts.age_at_eligibility_cutoff == 22


def test_application_submission_keeps_arrival_dispatch_and_online_steps_distinct() -> None:
    payload = _profile_payload()
    payload["application_submission"] = {
        "materials_arrival_date": "2026-06-10",
        "materials_dispatched_date": "2026-06-09",
        "online_steps_completed": True,
    }

    profile = ApplicantProfile.model_validate(payload)

    assert profile.application_submission == ApplicationSubmission(
        materials_arrival_date=date(2026, 6, 10),
        materials_dispatched_date=date(2026, 6, 9),
        online_steps_completed=True,
    )


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
            "test_kind": "other",
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
    assert [result.test_kind.value for result in profile.language_test_results or ()] == [
        "toefl_ibt",
        "other",
    ]


def test_language_result_uses_closed_kind_and_preserves_submission_facts() -> None:
    payload = _unknown_profile_payload()
    payload["language_test_results"] = [
        {
            "test_kind": "toeic_lr",
            "score": None,
            "test_date": "2024-06-11",
            "validity_status": None,
            "official_report_available": None,
            "selected_for_submission": True,
            "downloaded_online_pdf": True,
            "toeic_verification_qr_present": True,
            "toeic_digital_official_score_certificate": True,
            "toefl_test_taker_score_report_pdf": None,
            "toefl_di_code_g179_set": None,
            "ets_paper_sent_to_applicant": False,
            "ets_paper_sent_to_institution": False,
        }
    ]

    profile = ApplicantProfile.model_validate(payload)
    result = profile.language_test_results[0]  # type: ignore[index]
    assert result.test_kind is LanguageTestKind.TOEIC_LR
    assert result.selected_for_submission is True
    assert result.toeic_verification_qr_present is True

    payload["language_test_results"][0]["test_kind"] = "IELTS"  # type: ignore[index]
    migrated = ApplicantProfile.model_validate(payload)
    assert migrated.language_test_results[0].test_kind is LanguageTestKind.OTHER  # type: ignore[index]

    payload["language_test_results"][0]["test_kind"] = "TOEFL iBT"  # type: ignore[index]
    migrated = ApplicantProfile.model_validate(payload)
    assert migrated.language_test_results[0].test_kind is LanguageTestKind.TOEFL_IBT  # type: ignore[index]


def test_rule04b_submission_plan_fields_are_typed_and_optional() -> None:
    payload = _profile_payload()
    result_payload = payload["language_test_results"][0]  # type: ignore[index]
    result_payload.update(
        {
            "selected_for_submission": True,
            "score_sheet_submission_method": "department_later_by_mail",
            "score_sheet_expected_arrival_date": "2026-07-29",
            "score_sheet_registered_mail_planned": True,
            "score_sheet_replacement_after_deadline_planned": False,
        }
    )
    payload["application_submission"] = {
        "a_schedule_oral_exam_participation_planned": False,
    }

    profile = ApplicantProfile.model_validate(payload)
    result = profile.language_test_results[0]  # type: ignore[index]

    assert (
        result.score_sheet_submission_method
        is LanguageScoreSubmissionMethod.DEPARTMENT_LATER_BY_MAIL
    )
    assert result.score_sheet_expected_arrival_date == date(2026, 7, 29)
    assert result.score_sheet_registered_mail_planned is True
    assert result.score_sheet_replacement_after_deadline_planned is False
    assert profile.application_submission is not None
    assert profile.application_submission.a_schedule_oral_exam_participation_planned is False


def test_rule04b_fields_preserve_legacy_profile_compatibility() -> None:
    profile = ApplicantProfile.model_validate(_profile_payload())
    result = profile.language_test_results[0]  # type: ignore[index]

    assert result.score_sheet_submission_method is None
    assert result.score_sheet_expected_arrival_date is None
    assert result.score_sheet_registered_mail_planned is None
    assert result.score_sheet_replacement_after_deadline_planned is None


def test_rule04b_sent_date_cannot_masquerade_as_required_arrival_date() -> None:
    payload = _profile_payload()
    result_payload = payload["language_test_results"][0]  # type: ignore[index]
    result_payload.update(
        {
            "selected_for_submission": True,
            "score_sheet_submission_method": "department_later_by_mail",
            "score_sheet_sent_date": "2026-07-28",
        }
    )

    with pytest.raises(ValidationError):
        ApplicantProfile.model_validate(payload)


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
            "test_kind": "toeic_lr",
            "score": None,
            "test_date": None,
            "validity_status": "not_available",
            "official_report_available": None,
            "selected_for_submission": True,
            "downloaded_online_pdf": True,
        }
    ]
    with pytest.raises(ValidationError):
        ApplicantProfile.model_validate(payload)

    payload = _unknown_profile_payload()
    payload["language_test_results"] = [
        {
            "test_kind": "toefl_ibt",
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
    assert {
        "years_enrolled_at_eligibility_cutoff",
        "prescribed_credits_excellence_status",
        "institution_is_target_university",
        "gpt_after_two_years",
        "credits_after_two_years",
        "required_specialization_courses_expected_status",
        "expected_specialist_credits",
        "liberal_arts_requirements_expected_status",
    } <= AcademicCredential.model_fields.keys()
    assert (
        EligibilityFacts.model_fields["individual_review_status"].annotation
        == IndividualReviewStatus | None
    )
    assert (
        LanguageTestResult.model_fields["validity_status"].annotation == LanguageResultStatus | None
    )
    assert LanguageTestResult.model_fields["test_kind"].annotation == LanguageTestKind | None
