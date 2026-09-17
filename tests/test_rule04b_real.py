from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from jgrad_admission_rag.builder.kb_builder import build_document_kb
from jgrad_admission_rag.corpus import CorpusRegistration, build_corpus_manifest
from jgrad_admission_rag.corpus_selection import select_corpus_documents
from jgrad_admission_rag.reasoning.reviewed_report_evidence import (
    prepare_reviewed_report_evidence,
)
from jgrad_admission_rag.reasoning.reviewed_report_plan import load_reviewed_report_plan
from jgrad_admission_rag.retrieval.embedding import DeterministicFakeEmbeddingProvider
from jgrad_admission_rag.retrieval.local_index import build_local_index
from jgrad_admission_rag.schemas.corpus_manifest import canonical_corpus_manifest_bytes
from jgrad_admission_rag.schemas.corpus_version import (
    CorpusFamilyVersionPolicy,
    CorpusSelectionRequest,
    CorpusVersionPolicy,
    canonical_corpus_version_policy_bytes,
)
from jgrad_admission_rag.schemas.document_identity import load_document_identity
from jgrad_admission_rag.schemas.document_kb import canonical_document_kb_bytes
from jgrad_admission_rag.service import ServiceDependencies, ServiceSettings, create_app
from tests.test_rule01a_real import _profile, _report, _statuses
from tests.test_rule04a_real import _language_result

pytestmark = pytest.mark.real_pdf
ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf"
IDENTITY = ROOT / "tests/fixtures/document_identity_isct_master_v1.json"
PLAN = ROOT / "tests/fixtures/reviewed_report_plan_isct_master_rule04b_v1.json"

EXPECTED_SUBMISSION_FACTS = {
    19: ("department", "数学系"),
    21: ("department", "物理学系"),
    23: ("department", "化学系"),
    25: ("department", "地球惑星科学系"),
    27: ("department", "機械系"),
    31: ("department", "システム制御系"),
    33: ("department", "電気電子系"),
    37: ("department", "情報通信系"),
    40: ("department", "経営工学系"),
    42: ("department", "材料系"),
    46: ("department", "応用化学系"),
    50: ("department", "数理・計算科学系"),
    52: ("department", "情報工学系"),
    55: ("department", "生命理工学系"),
    60: ("department", "建築学系"),
    63: ("department", "土木・環境工学系"),
    66: ("department", "融合理工学系"),
    70: ("department", "社会・人間科学系"),
    73: ("program", "技術経営専門職学位課程"),
}
SUBMISSION_TITLES = {
    "【英語試験】",
    "【英語外部試験のスコアシートの取扱い】",
    "【外部英語試験のスコアシートの取扱い】",
}
NORMAL_RULE_SLUGS = {
    "化学系": "chemistry",
    "地球惑星科学系": "earth-science",
    "機械系": "mechanical",
    "システム制御系": "systems-control",
    "電気電子系": "electrical",
    "情報通信系": "ict",
    "経営工学系": "industrial-engineering",
    "材料系": "materials",
    "応用化学系": "applied-chemistry",
    "数理・計算科学系": "math-computing",
    "情報工学系": "computer-science",
    "生命理工学系": "life-science",
    "建築学系": "architecture",
    "融合理工学系": "transdisciplinary",
    "社会・人間科学系": "social-human",
    "技術経営専門職学位課程": "mot",
}
TARGET_COLLEGES = {
    "数学系": "理学院",
    "物理学系": "理学院",
    "化学系": "理学院",
    "地球惑星科学系": "理学院",
    "機械系": "工学院",
    "システム制御系": "工学院",
    "電気電子系": "工学院",
    "情報通信系": "工学院",
    "経営工学系": "工学院",
    "材料系": "物質理工学院",
    "応用化学系": "物質理工学院",
    "数理・計算科学系": "情報理工学院",
    "情報工学系": "情報理工学院",
    "生命理工学系": "生命理工学院",
    "建築学系": "環境・社会理工学院",
    "土木・環境工学系": "環境・社会理工学院",
    "融合理工学系": "環境・社会理工学院",
    "社会・人間科学系": "環境・社会理工学院",
    "技術経営専門職学位課程": "環境・社会理工学院",
}


@pytest.fixture(scope="module")
def rule04b_kb():
    if not PDF.is_file():
        pytest.skip("real PDF fixture unavailable")
    return build_document_kb(PDF, load_document_identity(IDENTITY))


@pytest.fixture(scope="module")
def rule04b_client(tmp_path_factory: pytest.TempPathFactory, rule04b_kb):
    root = tmp_path_factory.mktemp("rule04b")
    kb_path = root / "documents/isct/document_kb.json"
    kb_path.parent.mkdir(parents=True)
    kb_path.write_bytes(canonical_document_kb_bytes(rule04b_kb))
    build_local_index(kb_path, root / "indexes/isct", DeterministicFakeEmbeddingProvider(8))
    manifest = build_corpus_manifest(
        "rule04b-real",
        root,
        (CorpusRegistration("documents/isct/document_kb.json", "indexes/isct"),),
    )
    policy = CorpusVersionPolicy(
        corpus_id=manifest.corpus_id,
        family_policies=(
            CorpusFamilyVersionPolicy(
                document_family_id=rule04b_kb.manifest.identity.document_family_id,
                active_document_id=rule04b_kb.manifest.identity.document_id,
            ),
        ),
    )
    manifest_path = (root / "corpus.json").resolve()
    policy_path = (root / "policy.json").resolve()
    manifest_path.write_bytes(canonical_corpus_manifest_bytes(manifest))
    policy_path.write_bytes(canonical_corpus_version_policy_bytes(policy))
    selection = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(document_ids=(rule04b_kb.manifest.identity.document_id,)),
    )
    reviewed_plan = load_reviewed_report_plan(PLAN)
    assert manifest.entries[0].source_kb_sha256 == reviewed_plan.source_kb_sha256
    prepare_reviewed_report_evidence(
        root,
        manifest,
        policy,
        selection,
        (reviewed_plan,),
    )
    app = create_app(
        ServiceSettings(
            corpus_root=root.resolve(),
            manifest_path=manifest_path,
            policy_path=policy_path,
            report_plan_paths=(PLAN.resolve(),),
            query_intent_catalog_path=(ROOT / "config/query_intent_catalog_v1.json").resolve(),
        ),
        ServiceDependencies(provider_factory=lambda: DeterministicFakeEmbeddingProvider(8)),
    )
    with TestClient(app) as client:
        yield client, rule04b_kb.manifest.identity.document_id


def _submission_profile(
    target: str,
    year: int,
    month: int,
    *,
    method: str | None,
    arrival: str | None = None,
    registered: bool | None = None,
    replacement: bool | None = False,
    oral: bool | None = None,
    downloaded: bool | None = True,
) -> dict[str, Any]:
    profile = _profile(None, year=year, month=month)
    profile["target_application"]["graduate_school_or_college"] = TARGET_COLLEGES[target]
    profile["target_application"]["department_or_program"] = target
    result = _language_result(
        "toeic_lr",
        score_sheet_submission_method=method,
        score_sheet_expected_arrival_date=arrival,
        score_sheet_registered_mail_planned=registered,
        score_sheet_replacement_after_deadline_planned=replacement,
        downloaded_online_pdf=downloaded,
    )
    profile["language_test_results"] = [result]
    profile["application_submission"] = {"a_schedule_oral_exam_participation_planned": oral}
    return profile


def _submission_facts(kb):
    return [
        fact
        for fact in kb.facts
        if fact.title in SUBMISSION_TITLES
        and fact.text.lstrip().startswith(fact.title)
        and len(fact.source_pages) == 1
        and 19 <= fact.source_pages[0] <= 73
    ]


def test_all_department_submission_rules_are_atomic_and_narrowly_scoped(rule04b_kb) -> None:
    facts = _submission_facts(rule04b_kb)

    assert len(facts) == len(EXPECTED_SUBMISSION_FACTS)
    assert {fact.source_pages[0] for fact in facts} == set(EXPECTED_SUBMISSION_FACTS)
    for fact in facts:
        expected_scope, expected_target = EXPECTED_SUBMISSION_FACTS[fact.source_pages[0]]
        assert fact.scope_type == expected_scope
        assert fact.scope_targets == [expected_target]
        assert "試験区分" not in fact.text
        assert "### Table" not in fact.text


@pytest.mark.parametrize(
    ("page", "target"),
    (
        (23, "化学系"),
        (31, "システム制御系"),
        (55, "生命理工学系"),
        (70, "社会・人間科学系"),
    ),
)
def test_previously_missing_submission_clauses_are_restored(rule04b_kb, page, target) -> None:
    fact = next(fact for fact in _submission_facts(rule04b_kb) if fact.source_pages == [page])

    assert fact.scope_targets == [target]
    assert "出願時に提出" in fact.text
    assert "差し替えは一切認めません" in fact.text


def test_special_submission_paths_keep_complete_official_language(rule04b_kb) -> None:
    by_page = {fact.source_pages[0]: fact for fact in _submission_facts(rule04b_kb)}

    assert "筆答試験当日に持参" in by_page[21].text
    assert "不合格となります" in by_page[21].text
    assert "7月29日必着" in re.sub(r"\s+", "", by_page[63].text)
    assert "簡易書留郵便" in by_page[63].text


def _finding(report: dict[str, Any], rule_id: str) -> dict[str, Any]:
    return next(
        item for item in report["cited_answer"]["rule_findings"] if item["rule_id"] == rule_id
    )


@pytest.mark.parametrize(("year", "month", "suffix"), ((2027, 4, "apr"), (2026, 9, "sep")))
@pytest.mark.parametrize(("target", "slug"), tuple(NORMAL_RULE_SLUGS.items()))
def test_normal_department_submission_matrix(
    rule04b_client, year, month, suffix, target, slug
) -> None:
    client, document_id = rule04b_client
    report = _report(
        client,
        document_id,
        _submission_profile(target, year, month, method="with_application"),
        f"matrix-{slug}-{suffix}",
    )
    rule_id = f"isct-master-english-submission-{slug}-{suffix}"
    finding = next(
        item for item in report["cited_answer"]["rule_findings"] if item["rule_id"] == rule_id
    )
    assert finding["original_status"] == "confirmed", finding
    assert finding["scope"]["scope_targets"] == [target]
    assert {citation["source_pages"][0] for citation in finding["citations"]} == {
        next(page for page, (_, name) in EXPECTED_SUBMISSION_FACTS.items() if name == target)
    }


@pytest.mark.parametrize(("year", "month", "suffix"), ((2027, 4, "apr"), (2026, 9, "sep")))
def test_physics_submission_paths_are_three_state(rule04b_client, year, month, suffix) -> None:
    client, document_id = rule04b_client
    rule_id = f"isct-master-english-submission-physics-{suffix}"
    correct = _report(
        client,
        document_id,
        _submission_profile("物理学系", year, month, method="written_exam_day_carry"),
        f"physics-correct-{suffix}",
    )
    wrong = _report(
        client,
        document_id,
        _submission_profile("物理学系", year, month, method="with_application"),
        f"physics-wrong-{suffix}",
    )
    unknown = _report(
        client,
        document_id,
        _submission_profile("物理学系", year, month, method=None),
        f"physics-unknown-{suffix}",
    )
    absent = _report(
        client,
        document_id,
        _submission_profile("物理学系", year, month, method="no_external_submission"),
        f"physics-absent-{suffix}",
    )

    assert _statuses(correct)[rule_id] == "confirmed"
    assert _statuses(wrong)[rule_id] == "not_applicable"
    assert _statuses(unknown)[rule_id] == "needs_information"
    risk_id = f"isct-master-english-missing-exam-day-risk-physics-{suffix}"
    assert _statuses(absent)[risk_id] == "confirmed"
    risk = next(item for item in absent["source_plan"]["rules"] if item["rule_id"] == risk_id)
    assert "最終不合格を判定しません" in risk["annotation_note"]


@pytest.mark.parametrize(("year", "month", "suffix"), ((2027, 4, "apr"), (2026, 9, "sep")))
def test_normal_submission_method_is_three_state_and_exposes_official_risks(
    rule04b_client, year, month, suffix
) -> None:
    client, document_id = rule04b_client
    target = "化学系"
    submission_id = f"isct-master-english-submission-chemistry-{suffix}"
    late_id = f"isct-master-english-late-submission-risk-chemistry-{suffix}"
    replacement_id = f"isct-master-english-replacement-risk-chemistry-{suffix}"
    later = _report(
        client,
        document_id,
        _submission_profile(target, year, month, method="department_later_by_mail"),
        f"chemistry-later-{suffix}",
    )
    unknown = _report(
        client,
        document_id,
        _submission_profile(target, year, month, method=None),
        f"chemistry-unknown-{suffix}",
    )
    replacement = _report(
        client,
        document_id,
        _submission_profile(
            target,
            year,
            month,
            method="with_application",
            replacement=True,
        ),
        f"chemistry-replacement-{suffix}",
    )

    assert _statuses(later)[submission_id] == "not_applicable"
    assert _statuses(later)[late_id] == "confirmed"
    assert _statuses(unknown)[submission_id] == "needs_information"
    assert any(
        item["field_path"] == "language_test_results.selected.score_sheet_submission_method"
        and item["rule_id"] == submission_id
        for item in unknown["cited_answer"]["missing_information"]
    )
    assert _statuses(replacement)[replacement_id] == "confirmed"


@pytest.mark.parametrize(("year", "month", "suffix"), ((2027, 4, "apr"), (2026, 9, "sep")))
def test_electrical_missing_submission_surfaces_official_risk(
    rule04b_client, year, month, suffix
) -> None:
    client, document_id = rule04b_client
    report = _report(
        client,
        document_id,
        _submission_profile("電気電子系", year, month, method="no_external_submission"),
        f"electrical-missing-{suffix}",
    )
    risk_id = f"isct-master-english-missing-application-risk-electrical-{suffix}"

    assert _statuses(report)[risk_id] == "confirmed"
    note = next(
        item["annotation_note"]
        for item in report["source_plan"]["rules"]
        if item["rule_id"] == risk_id
    )
    assert "受験資格が無い" in note
    assert "学校の拒否を判定しません" in note


@pytest.mark.parametrize(("year", "month", "suffix"), ((2027, 4, "apr"), (2026, 9, "sep")))
def test_civil_later_mail_boundaries(rule04b_client, year, month, suffix) -> None:
    client, document_id = rule04b_client
    target = "土木・環境工学系"
    later_id = f"isct-master-english-submission-civil-later-mail-{suffix}"
    principle_id = f"isct-master-english-submission-civil-principle-{suffix}"
    oral_principle = _report(
        client,
        document_id,
        _submission_profile(
            target,
            year,
            month,
            method="with_application",
            oral=True,
        ),
        f"civil-oral-principle-{suffix}",
    )
    valid = _report(
        client,
        document_id,
        _submission_profile(
            target,
            year,
            month,
            method="department_later_by_mail",
            arrival="2026-07-29",
            registered=True,
            oral=False,
        ),
        f"civil-valid-{suffix}",
    )
    late = _report(
        client,
        document_id,
        _submission_profile(
            target,
            year,
            month,
            method="department_later_by_mail",
            arrival="2026-07-30",
            registered=True,
            oral=False,
        ),
        f"civil-late-{suffix}",
    )
    missing_arrival = _report(
        client,
        document_id,
        _submission_profile(
            target,
            year,
            month,
            method="department_later_by_mail",
            registered=True,
            oral=False,
        ),
        f"civil-missing-{suffix}",
    )
    unregistered = _report(
        client,
        document_id,
        _submission_profile(
            target,
            year,
            month,
            method="department_later_by_mail",
            arrival="2026-07-29",
            registered=False,
            oral=False,
        ),
        f"civil-unregistered-{suffix}",
    )
    unknown_oral = _report(
        client,
        document_id,
        _submission_profile(
            target,
            year,
            month,
            method="department_later_by_mail",
            arrival="2026-07-29",
            registered=True,
            oral=None,
        ),
        f"civil-unknown-oral-{suffix}",
    )
    unknown_registered = _report(
        client,
        document_id,
        _submission_profile(
            target,
            year,
            month,
            method="department_later_by_mail",
            arrival="2026-07-29",
            registered=None,
            oral=False,
        ),
        f"civil-unknown-registered-{suffix}",
    )

    assert _statuses(oral_principle)[principle_id] == "confirmed"
    assert _statuses(valid)[later_id] == "confirmed"
    assert _statuses(late)[later_id] == "not_applicable"
    assert _statuses(late)[f"isct-master-english-civil-late-arrival-risk-{suffix}"] == ("confirmed")
    assert _statuses(missing_arrival)[later_id] == "needs_information"
    assert any(
        item["field_path"] == "language_test_results.selected.score_sheet_expected_arrival_date"
        for item in missing_arrival["cited_answer"]["missing_information"]
    )
    assert (
        _statuses(unregistered)[f"isct-master-english-civil-unregistered-mail-risk-{suffix}"]
        == "confirmed"
    )
    assert _statuses(unknown_oral)[later_id] == "needs_information"
    assert any(
        item["rule_id"] == later_id
        and item["field_path"]
        == "application_submission.a_schedule_oral_exam_participation_planned"
        for item in unknown_oral["cited_answer"]["missing_information"]
    )
    assert _statuses(unknown_registered)[later_id] == "needs_information"
    assert any(
        item["rule_id"] == later_id
        and item["field_path"]
        == "language_test_results.selected.score_sheet_registered_mail_planned"
        for item in unknown_registered["cited_answer"]["missing_information"]
    )


def test_math_exception_does_not_request_external_submission_plan(rule04b_client) -> None:
    client, document_id = rule04b_client
    profile = _profile(None, year=2027, month=4)
    profile["target_application"]["graduate_school_or_college"] = "理学院"
    profile["target_application"]["department_or_program"] = "数学系"
    profile["language_test_results"] = None

    report = _report(client, document_id, profile, "math-no-external-score")

    assert _statuses(report)["isct-master-english-math-written-exam-apr"] == ("confirmed")
    assert not any(
        item["field_path"].startswith("language_test_results.selected.score_sheet_")
        for item in report["cited_answer"]["missing_information"]
    )


def test_unknown_and_conflicting_scope_never_guess_department_rules(
    rule04b_client,
) -> None:
    client, document_id = rule04b_client
    unknown = _submission_profile("化学系", 2027, 4, method="with_application")
    unknown["target_application"]["graduate_school_or_college"] = None
    unknown["target_application"]["department_or_program"] = None
    unknown_report = _report(client, document_id, unknown, "rule04b-unknown-target")
    chemistry_id = "isct-master-english-submission-chemistry-apr"

    assert _statuses(unknown_report)[chemistry_id] == "needs_information"
    assert any(
        item["field_path"] == "target_application.department_or_program"
        and item["rule_id"] == chemistry_id
        for item in unknown_report["cited_answer"]["missing_information"]
    )

    conflict = _submission_profile("化学系", 2027, 4, method="with_application")
    conflict["target_application"]["graduate_school_or_college"] = "工学院"
    conflict_report = _report(client, document_id, conflict, "rule04b-college-conflict")
    assert _statuses(conflict_report)[chemistry_id] == "needs_information"
    assert any(
        item["kind"] == "scope_input_conflict" and chemistry_id in item["rule_ids"]
        for item in conflict_report["cited_answer"]["process_notices"]
    )


def test_professional_program_with_wrong_parent_scope_is_not_guessed(
    rule04b_client,
) -> None:
    client, document_id = rule04b_client
    profile = _submission_profile("技術経営専門職学位課程", 2027, 4, method="with_application")
    profile["target_application"]["graduate_school_or_college"] = "工学院"
    report = _report(client, document_id, profile, "rule04b-mot-wrong-parent")
    rule_id = "isct-master-english-submission-mot-apr"

    assert _statuses(report)[rule_id] == "needs_information"
    assert _finding(report, rule_id)["scope"]["scope_type"] == "program"
    assert any(
        item["kind"] == "scope_input_conflict" and rule_id in item["rule_ids"]
        for item in report["cited_answer"]["process_notices"]
    )
