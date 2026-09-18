from __future__ import annotations

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.reasoning.applicability import OfficialEvidenceBinding
from jgrad_admission_rag.reasoning.applicant_profile import ApplicantProfile
from jgrad_admission_rag.reasoning.application_materials import (
    ApplicationMaterialsPolicy,
    ReviewedApplicationMaterial,
    resolve_application_materials,
)
from tests.test_rule01a_real import _credential, _profile


def _policy() -> ApplicationMaterialsPolicy:
    names = (
        ("address_label", "宛名ラベル"),
        ("application_form", "入学志願票"),
        ("statement_of_purpose", "志望理由書"),
        ("bachelor_transcript", "学士課程の成績証明書"),
        (
            "graduation_or_expected_graduation_certificate",
            "学士課程の卒業証明書又は卒業見込み証明書",
        ),
    )
    return ApplicationMaterialsPolicy(
        policy_id="materials-v1",
        entries=tuple(
            ReviewedApplicationMaterial(
                number=index,
                code=code,
                official_name=name,
                exempt_for_eligibility_review_paths=index >= 3,
            )
            for index, (code, name) in enumerate(names, start=1)
        ),
        evidence_binding=OfficialEvidenceBinding(
            document_id="doc",
            fact_id="fact:1",
            source_pages=(10,),
            source_pdf_sha256="1" * 64,
            source_kb_sha256="2" * 64,
            authoritative_fact_text_sha256="3" * 64,
        ),
        limitation_statement="Requirements only; no receipt decision.",
    )


@pytest.mark.parametrize(
    ("basis", "expected_tail"),
    [
        ("university_graduation", ["required"] * 3),
        ("foreign_15_year_education", ["eligibility_review_path"] * 3),
        (None, ["needs_information"] * 3),
    ],
)
def test_material_applicability_is_path_aware_and_fail_closed(basis, expected_tail) -> None:
    result = resolve_application_materials(
        ApplicantProfile.model_validate(_profile(_credential(basis=basis))), _policy()
    )
    assert [entry.applicability.value for entry in result.entries[:2]] == [
        "required",
        "required",
    ]
    assert [entry.applicability.value for entry in result.entries[2:]] == expected_tail


def test_missing_or_multiple_credentials_do_not_crash_or_grant_an_exception() -> None:
    for profile in (_profile(None), _profile(_credential(), multiple=True)):
        result = resolve_application_materials(ApplicantProfile.model_validate(profile), _policy())
        assert [entry.applicability.value for entry in result.entries[2:]] == [
            "needs_information"
        ] * 3


def test_policy_rejects_a_false_official_exception() -> None:
    payload = _policy().model_dump(mode="json")
    payload["entries"][0]["exempt_for_eligibility_review_paths"] = True
    with pytest.raises(ValidationError, match="official items 3 through 5"):
        ApplicationMaterialsPolicy.model_validate(payload)
