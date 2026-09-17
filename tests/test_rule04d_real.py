from __future__ import annotations

import pytest

from tests.test_rule01a_real import _report
from tests.test_rule04b_real import TARGET_COLLEGES, _submission_profile

pytestmark = pytest.mark.real_pdf
pytest_plugins = ("tests.test_rule04b_real",)

EXPECTED_ALLOCATIONS = {
    "システム制御系": (50, "fact:00220", 31),
    "化学系": (200, "fact:00190", 23),
    "地球惑星科学系": (75, "fact:00202", 25),
    "情報工学系": (100, "fact:00288", 52),
    "情報通信系": (100, "fact:00238", 37),
    "応用化学系": (100, "fact:00270", 46),
    "数理・計算科学系": (20, "fact:00280", 50),
    "材料系": (150, "fact:00256", 42),
    "機械系": (100, "fact:00207", 27),
    "物理学系": (60, "fact:00182", 21),
    "生命理工学系": (100, "fact:00296", 55),
    "経営工学系": (50, "fact:00247", 40),
    "融合理工学系": (75, "fact:00322", 66),
    "電気電子系": (150, "fact:00230", 34),
    "土木・環境工学系": (100, "fact:00315", 63),
}


def test_all_reviewed_allocations_match_exact_department_facts(rule04b_kb) -> None:
    facts = {fact.fact_id: fact for fact in rule04b_kb.facts}

    for target, (_, fact_id, page) in EXPECTED_ALLOCATIONS.items():
        fact = facts[fact_id]
        assert fact.source_pages == [page]
        assert fact.scope_type == "department"
        assert fact.scope_targets == [target]
        assert fact.parent_college == TARGET_COLLEGES[target]


def test_electrical_continuation_page_has_one_correct_scope(rule04b_kb) -> None:
    page_facts = [fact for fact in rule04b_kb.facts if fact.source_pages == [34]]

    assert page_facts
    assert all(fact.scope_type == "department" for fact in page_facts)
    assert all(fact.scope_targets == ["電気電子系"] for fact in page_facts)
    assert all(fact.parent_college == "工学院" for fact in page_facts)


@pytest.mark.parametrize(("year", "month"), ((2026, 9), (2027, 4)))
@pytest.mark.parametrize(("target", "expected"), tuple(EXPECTED_ALLOCATIONS.items()))
def test_allocation_matrix_is_stable_for_both_intakes(
    rule04b_client, target, expected, year, month
) -> None:
    client, document_id = rule04b_client
    profile = _submission_profile(target, year, month, method="with_application")
    report = _report(client, document_id, profile, f"allocation-{year}-{month}-{expected[0]}")
    result = report["language_score_allocation"]

    assert result["status"] == "confirmed"
    assert result["target"] == target
    assert result["parent_college"] == TARGET_COLLEGES[target]
    assert result["maximum_points"] == expected[0]
    assert result["unit"] == "points"
    assert result["evidence"]["fact_id"] == expected[1]
    assert result["evidence"]["source_pages"] == [expected[2]]


@pytest.mark.parametrize(
    "target",
    ("数学系", "建築学系", "社会・人間科学系", "技術経営専門職学位課程"),
)
def test_non_numeric_or_unpublished_targets_never_receive_zero(rule04b_client, target) -> None:
    client, document_id = rule04b_client
    method = "no_external_submission" if target == "数学系" else "with_application"
    profile = _submission_profile(target, 2027, 4, method=method)
    report = _report(client, document_id, profile, f"allocation-unpublished-{len(target)}")
    result = report["language_score_allocation"]

    assert result["status"] == "not_published"
    assert result["maximum_points"] is None
    assert result["unit"] is None
    assert result["evidence"] is None


def test_wrong_parent_college_cannot_match_another_department(rule04b_client) -> None:
    client, document_id = rule04b_client
    profile = _submission_profile("物理学系", 2027, 4, method="with_application")
    profile["target_application"]["graduate_school_or_college"] = "工学院"
    report = _report(client, document_id, profile, "allocation-parent-conflict")
    result = report["language_score_allocation"]

    assert result["status"] == "not_published"
    assert result["maximum_points"] is None
