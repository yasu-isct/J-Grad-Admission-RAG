from __future__ import annotations

from copy import deepcopy

from jgrad_admission_rag.reasoning import (
    ApplicantProfile,
    ClosedIntegerInterval,
    ConversionResultShape,
    ConversionStatus,
    LanguageScoreConversionPolicy,
    OfficialEvidenceBinding,
    ScoreConversionTableRow,
    convert_selected_language_score,
)
from tests.test_rule01a_real import _profile
from tests.test_rule04a_real import _language_result


def _policy() -> LanguageScoreConversionPolicy:
    binding = OfficialEvidenceBinding(
        document_id="document",
        source_kb_sha256="a" * 64,
        source_pdf_sha256="b" * 64,
        fact_id="fact:00139",
        source_pages=(16,),
        authoritative_fact_text_sha256="c" * 64,
    )
    rows = (
        ScoreConversionTableRow(
            row_id="g1-r01",
            group_index=1,
            row_index=1,
            raw_ibt_cell="120",
            raw_pbt_cell="677",
            ibt=ClosedIntegerInterval(lower=120, upper=120),
            pbt=ClosedIntegerInterval(lower=677, upper=677),
            source_page=16,
        ),
        ScoreConversionTableRow(
            row_id="g1-r02",
            group_index=1,
            row_index=2,
            raw_ibt_cell="120",
            raw_pbt_cell="673",
            ibt=ClosedIntegerInterval(lower=120, upper=120),
            pbt=ClosedIntegerInterval(lower=673, upper=673),
            source_page=16,
        ),
        ScoreConversionTableRow(
            row_id="g2-r01",
            group_index=2,
            row_index=1,
            raw_ibt_cell="92-93",
            raw_pbt_cell="580-583",
            ibt=ClosedIntegerInterval(lower=92, upper=93),
            pbt=ClosedIntegerInterval(lower=580, upper=583),
            source_page=16,
        ),
        ScoreConversionTableRow(
            row_id="g4-r17",
            group_index=4,
            row_index=17,
            raw_ibt_cell="17",
            raw_pbt_cell="333-337",
            ibt=ClosedIntegerInterval(lower=17, upper=17),
            pbt=ClosedIntegerInterval(lower=333, upper=337),
            source_page=16,
        ),
    )
    return LanguageScoreConversionPolicy(
        policy_id="appendix-3",
        evidence_binding=binding,
        table_rows=rows,
        limitation_statement="換算基準であり、最低点や合否を示しません。",
    )


def _applicant(kind: str, score: int | float | str, *, department: str = "物理学系"):
    payload = _profile(None)
    payload["target_application"]["department_or_program"] = department
    payload["language_test_results"] = [_language_result(kind, score=score)]
    return ApplicantProfile.model_validate(payload)


def test_toeic_boundary_uses_exact_decimal_formula() -> None:
    policy = _policy()

    at_boundary = convert_selected_language_score(_applicant("toeic_lr", 300), policy)
    converted = convert_selected_language_score(_applicant("toeic_lr", "301"), policy)

    assert at_boundary.status is ConversionStatus.NOT_APPLICABLE
    assert converted.status is ConversionStatus.CONVERTED
    assert converted.result_shape is ConversionResultShape.SINGLE
    assert converted.pbt_candidates[0].lower.decimal == "400.748"
    assert converted.pbt_candidates[0].lower.numerator == 100187
    assert converted.pbt_candidates[0].lower.denominator == 250


def test_ibt_120_preserves_both_official_candidates_and_exact_rationals() -> None:
    result = convert_selected_language_score(_applicant("toefl_ibt", 120), _policy())

    assert result.status is ConversionStatus.CONVERTED
    assert result.result_shape is ConversionResultShape.CANDIDATES
    assert [item.lower.decimal for item in result.pbt_candidates] == ["673", "677"]
    assert len(result.toeic_candidates) == 2
    assert all(item.lower.decimal is None for item in result.toeic_candidates)
    assert {(item.lower.numerator, item.lower.denominator) for item in result.toeic_candidates} == {
        (31750, 29),
        (3250, 3),
    }


def test_interval_and_table_boundaries_are_not_collapsed_or_extrapolated() -> None:
    interval = convert_selected_language_score(_applicant("toefl_ibt_home_edition", 92), _policy())
    below = convert_selected_language_score(_applicant("toefl_ibt", 16), _policy())
    above = convert_selected_language_score(_applicant("toefl_ibt", 121), _policy())

    assert interval.result_shape is ConversionResultShape.INTERVAL
    assert interval.pbt_candidates[0].lower.decimal == "580"
    assert interval.pbt_candidates[0].upper.decimal == "583"
    assert below.status is ConversionStatus.OUT_OF_TABLE
    assert above.status is ConversionStatus.OUT_OF_TABLE


def test_selection_unsupported_kind_and_math_exception_remain_explicit() -> None:
    policy = _policy()
    unsupported = convert_selected_language_score(_applicant("toefl_itp", 500), policy)
    math = convert_selected_language_score(
        _applicant("toefl_itp", 500, department="数学系"),
        policy,
    )
    ambiguous_payload = _profile(None)
    ambiguous_payload["language_test_results"] = [
        _language_result("toeic_lr", score=301, selected_for_submission=None),
        _language_result("toefl_ibt", score=120, selected_for_submission=None),
    ]
    ambiguous = convert_selected_language_score(
        ApplicantProfile.model_validate(deepcopy(ambiguous_payload)),
        policy,
    )

    assert unsupported.status is ConversionStatus.UNSUPPORTED_TEST_KIND
    assert math.status is ConversionStatus.NOT_REQUIRED
    assert math.missing_fields == ()
    assert ambiguous.status is ConversionStatus.MISSING_SELECTION
    assert ambiguous.missing_fields == ("language_test_results.selected_for_submission",)
