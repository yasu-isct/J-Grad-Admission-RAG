from __future__ import annotations

import pytest

from jgrad_admission_rag.reasoning import load_reviewed_report_plan
from tests.test_rule01a_real import _profile, _report
from tests.test_rule04a_real import _language_result
from tests.test_rule04b_real import PLAN

pytestmark = pytest.mark.real_pdf
pytest_plugins = ("tests.test_rule04b_real",)


def _language_profile(kind: str, score: int | str, *, department: str = "物理学系"):
    profile = _profile(None)
    profile["target_application"]["graduate_school_or_college"] = "理学院"
    profile["target_application"]["department_or_program"] = department
    profile["language_test_results"] = [_language_result(kind, score=score)]
    return profile


def _conversion(rule04b_client, profile, report_id: str):
    client, document_id = rule04b_client
    return _report(client, document_id, profile, report_id)["language_score_conversion"]


def test_appendix_three_is_one_clean_global_fact(rule04b_kb) -> None:
    facts = [fact for fact in rule04b_kb.facts if fact.source_pages == [16]]

    assert len(rule04b_kb.facts) == 391
    assert len(facts) == 1
    fact = facts[0]
    assert fact.fact_id == "fact:00139"
    assert fact.title == "附録３．本学が定める英語外部試験の換算基準"
    assert fact.section_path == [fact.title]
    assert fact.scope_type == "global"
    assert fact.scope_targets == []
    assert fact.text.count("((TOEFL-PBT) － 296) ÷ 0.348 ＝ TOEIC L&R") == 1
    assert fact.text.count("| 120 |  |  | 677 |  |  |") == 1
    assert "120 677 92-93" not in fact.text


def test_reviewed_plan_preserves_all_74_visual_rows() -> None:
    policy = load_reviewed_report_plan(PLAN).language_score_conversion

    assert policy is not None
    assert len(policy.table_rows) == 74
    assert [
        len([row for row in policy.table_rows if row.group_index == group]) for group in range(1, 5)
    ] == [19, 19, 19, 17]
    assert [(row.raw_ibt_cell, row.raw_pbt_cell) for row in policy.table_rows[:2]] == [
        ("120", "677"),
        ("120", "673"),
    ]
    assert (policy.table_rows[-1].raw_ibt_cell, policy.table_rows[-1].raw_pbt_cell) == (
        "17",
        "333-337",
    )


@pytest.mark.parametrize(("score", "status"), [(300, "not_applicable"), (301, "converted")])
def test_toeic_300_301_boundary_is_visible_in_api(rule04b_client, score, status) -> None:
    result = _conversion(rule04b_client, _language_profile("toeic_lr", score), f"toeic-{score}")

    assert result["status"] == status
    assert result["evidence_binding"]["fact_id"] == "fact:00139"
    assert result["evidence_binding"]["source_pages"] == [16]
    if score == 301:
        assert result["pbt_candidates"][0]["lower"]["decimal"] == "400.748"


def test_ibt_120_api_keeps_both_candidates_and_formula_chain(rule04b_client) -> None:
    result = _conversion(rule04b_client, _language_profile("toefl_ibt", 120), "ibt-120")

    assert result["status"] == "converted"
    assert result["result_shape"] == "candidates"
    assert [item["lower"]["decimal"] for item in result["pbt_candidates"]] == ["673", "677"]
    assert len(result["toeic_candidates"]) == 2
    assert [step["operation"] for step in result["conversion_chain"]] == [
        "selected_input",
        "ibt_table_lookup",
        "pbt_to_toeic_formula",
    ]


@pytest.mark.parametrize("score", [16, 121])
def test_ibt_outside_official_table_is_not_extrapolated(rule04b_client, score) -> None:
    result = _conversion(rule04b_client, _language_profile("toefl_ibt", score), f"ibt-{score}")

    assert result["status"] == "out_of_table"
    assert result["result_shape"] == "none"
    assert result["pbt_candidates"] == []


def test_invalid_kind_ambiguous_selection_and_math_exception_remain_separate(
    rule04b_client,
) -> None:
    invalid = _conversion(
        rule04b_client,
        _language_profile("toefl_itp", 500),
        "invalid-kind",
    )
    ambiguous = _profile(None)
    ambiguous["language_test_results"] = [
        _language_result("toeic_lr", score=301, selected_for_submission=None),
        _language_result("toefl_ibt", score=120, selected_for_submission=None),
    ]
    ambiguous_result = _conversion(rule04b_client, ambiguous, "ambiguous")
    math = _profile(None)
    math["target_application"]["department_or_program"] = "数学系"
    math_result = _conversion(rule04b_client, math, "math-exception")

    assert invalid["status"] == "unsupported_test_kind"
    assert ambiguous_result["status"] == "missing_selection"
    assert ambiguous_result["missing_fields"] == ["language_test_results.selected_for_submission"]
    assert math_result["status"] == "not_required"
    assert math_result["missing_fields"] == []
