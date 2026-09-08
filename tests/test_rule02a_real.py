from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from jgrad_admission_rag.builder.kb_builder import build_document_kb
from jgrad_admission_rag.corpus import CorpusRegistration, build_corpus_manifest
from jgrad_admission_rag.retrieval.embedding import DeterministicFakeEmbeddingProvider
from jgrad_admission_rag.retrieval.local_index import build_local_index
from jgrad_admission_rag.schemas.corpus_manifest import canonical_corpus_manifest_bytes
from jgrad_admission_rag.schemas.corpus_version import (
    CorpusFamilyVersionPolicy,
    CorpusVersionPolicy,
    canonical_corpus_version_policy_bytes,
)
from jgrad_admission_rag.schemas.document_identity import load_document_identity
from jgrad_admission_rag.schemas.document_kb import canonical_document_kb_bytes
from jgrad_admission_rag.service import ServiceDependencies, ServiceSettings, create_app
from tests.test_rule01a_real import _credential, _profile, _report, _statuses

pytestmark = pytest.mark.real_pdf
ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf"
IDENTITY = ROOT / "tests/fixtures/document_identity_isct_master_v1.json"
PLAN = ROOT / "tests/fixtures/reviewed_report_plan_isct_master_rule02a_v1.json"
INTENT_CATALOG = ROOT / "config/query_intent_catalog_v1.json"


@pytest.fixture(scope="module")
def rule02a_client(tmp_path_factory: pytest.TempPathFactory):
    if not PDF.is_file():
        pytest.skip("real PDF fixture unavailable")
    root = tmp_path_factory.mktemp("rule02a")
    kb = build_document_kb(PDF, load_document_identity(IDENTITY))
    kb_relative = "documents/isct/document_kb.json"
    kb_path = root / Path(*kb_relative.split("/"))
    kb_path.parent.mkdir(parents=True)
    kb_path.write_bytes(canonical_document_kb_bytes(kb))
    index_relative = "indexes/isct"
    build_local_index(
        kb_path, root / Path(*index_relative.split("/")), DeterministicFakeEmbeddingProvider(8)
    )
    manifest = build_corpus_manifest(
        "rule02a-real", root, (CorpusRegistration(kb_relative, index_relative),)
    )
    policy = CorpusVersionPolicy(
        corpus_id=manifest.corpus_id,
        family_policies=(
            CorpusFamilyVersionPolicy(
                document_family_id=kb.manifest.identity.document_family_id,
                active_document_id=kb.manifest.identity.document_id,
            ),
        ),
    )
    manifest_path = (root / "corpus.json").resolve()
    policy_path = (root / "policy.json").resolve()
    manifest_path.write_bytes(canonical_corpus_manifest_bytes(manifest))
    policy_path.write_bytes(canonical_corpus_version_policy_bytes(policy))
    app = create_app(
        ServiceSettings(
            corpus_root=root.resolve(),
            manifest_path=manifest_path,
            policy_path=policy_path,
            report_plan_paths=(PLAN.resolve(),),
            query_intent_catalog_path=INTENT_CATALOG.resolve(),
        ),
        ServiceDependencies(provider_factory=lambda: DeterministicFakeEmbeddingProvider(8)),
    )
    with TestClient(app) as client:
        yield client, kb.manifest.identity.document_id


def _path9(basis: str = "university_three_year_enrollment", **overrides: Any) -> dict[str, Any]:
    local = basis == "university_three_year_enrollment"
    credential = _credential(
        country="JP" if local else "US",
        basis=basis,
        state="not_completed" if local else "completed",
        completion_date=None if local else "2026-04-01",
        expected_date=None,
        years=15 if "15_year" in basis else None,
    )
    credential.update(
        coursework_in_japan=None,
        program_duration_years=None,
        institution_recognition_status=None,
        program_designation_status=(
            "officially_confirmed" if basis.startswith("designated_") else None
        ),
        completion_timing_verification_status=None,
        person_designation_status=None,
        years_enrolled_at_eligibility_cutoff=3,
        prescribed_credits_excellence_status="officially_confirmed",
        institution_is_target_university=True if local else None,
        gpt_after_two_years=3.0,
        credits_after_two_years=90,
        required_specialization_courses_expected_status="officially_confirmed",
        expected_specialist_credits=60,
        liberal_arts_requirements_expected_status="officially_confirmed",
    )
    credential.update(overrides)
    return credential


def _finding(report: dict[str, Any], rule_id: str) -> dict[str, Any]:
    return next(
        item for item in report["cited_answer"]["rule_findings"] if item["rule_id"] == rule_id
    )


def _missing(report: dict[str, Any], rule_id: str) -> set[str]:
    return {
        item["field_path"]
        for item in report["cited_answer"]["missing_information"]
        if item["rule_id"] == rule_id
    }


def _note(report: dict[str, Any], rule_id: str) -> str:
    return next(
        item["annotation_note"]
        for item in report["source_plan"]["rules"]
        if item["rule_id"] == rule_id
    )


def test_rule02a_restores_exact_page8_gpt_fact(rule02a_client) -> None:
    kb = build_document_kb(PDF, load_document_identity(IDENTITY))
    facts = {fact.fact_id: fact for fact in kb.facts}
    assert len(kb.facts) == 318
    assert (
        facts["fact:00090"].text
        == "２．本学に2年間在学した時点においてGPTが3.00以上であり、かつ、原則として90単位以上を修得していること。"
    )
    assert facts["fact:00090"].source_pages == [8]


def test_scenario_1_exact_isct_boundaries_are_independent(rule02a_client) -> None:
    client, document_id = rule02a_client
    report = _report(client, document_id, _profile(_path9()), "rule02a-exact")
    statuses = _statuses(report)
    for number in (1, 2, 3):
        assert (
            statuses[f"isct-master-path-9-isct-early-entry-requirement-{number}-apr"] == "confirmed"
        )
    finding = _finding(report, "isct-master-path-9-isct-early-entry-requirement-2-apr")
    assert {item["fact_id"] for item in finding["citations"]} == {"fact:00088", "fact:00090"}
    assert {page for item in finding["citations"] for page in item["source_pages"]} == {8}
    assert "GPT" in _note(report, "isct-master-path-9-isct-early-entry-requirement-2-apr")
    assert "school approval" in report["limitation_statement"]


@pytest.mark.parametrize(
    "value,field", [(2.99, "gpt_after_two_years"), (89, "credits_after_two_years")]
)
def test_scenarios_2_and_3_numeric_failure_is_not_final_rejection(
    rule02a_client, value, field
) -> None:
    client, document_id = rule02a_client
    rule_id = "isct-master-path-9-isct-early-entry-requirement-2-apr"
    report = _report(client, document_id, _profile(_path9(**{field: value})), f"rule02a-{field}")
    assert _statuses(report)[rule_id] == "not_applicable"
    assert "合否は示しません" in _note(report, rule_id)


def test_scenario_4_missing_official_confirmations_is_precise(rule02a_client) -> None:
    client, document_id = rule02a_client
    report = _report(
        client,
        document_id,
        _profile(
            _path9(
                prescribed_credits_excellence_status=None,
                required_specialization_courses_expected_status=None,
            )
        ),
        "rule02a-missing",
    )
    recognition = "isct-master-path-9-school-recognition-university-three-year-apr"
    requirement3 = "isct-master-path-9-isct-early-entry-requirement-3-apr"
    assert _statuses(report)[recognition] == "needs_information"
    assert _missing(report, recognition) == {
        "academic_credentials.first.prescribed_credits_excellence_status"
    }
    assert _statuses(report)[requirement3] == "needs_information"
    assert _missing(report, requirement3) == {
        "academic_credentials.first.required_specialization_courses_expected_status"
    }


@pytest.mark.parametrize(
    "state,date_field", [("completed", "completion_date"), ("expected", "expected_completion_date")]
)
def test_scenario_5_graduate_is_redirected_to_path1(rule02a_client, state, date_field) -> None:
    client, document_id = rule02a_client
    report = _report(
        client,
        document_id,
        _profile(_path9(completion_state=state, **{date_field: "2027-03-31"})),
        f"rule02a-redirect-{state}",
    )
    redirect = f"isct-master-path-9-redirect-to-path-1-apr-{state}"
    assert _statuses(report)[redirect] == "confirmed"
    assert "出願資格（1）" in _note(report, redirect)
    assert (
        _statuses(report)["isct-master-path-9-candidate-university-three-year-apr"]
        == "not_applicable"
    )


def test_scenario_6_foreign_15_year_candidate_waits_for_school_review(rule02a_client) -> None:
    client, document_id = rule02a_client
    report = _report(
        client,
        document_id,
        _profile(_path9("foreign_15_year_education", prescribed_credits_excellence_status=None)),
        "rule02a-foreign15",
    )
    assert _statuses(report)["isct-master-path-9-candidate-foreign-15-year-apr"] == "confirmed"
    recognition = "isct-master-path-9-school-recognition-foreign-15-year-apr"
    assert _statuses(report)[recognition] == "needs_information"
    assert "final individual review" in report["limitation_statement"]


def test_scenario_7_process_actions_keep_page8_evidence(rule02a_client) -> None:
    client, document_id = rule02a_client
    report = _report(client, document_id, _profile(_path9()), "rule02a-process")
    finding = _finding(report, "isct-master-path-9-review-process-university-three-year-apr")
    assert {item["fact_id"] for item in finding["citations"]} == {"fact:00086"}
    assert {page for item in finding["citations"] for page in item["source_pages"]} == {8}
    for marker in ("メール", "2026年5月11日", "5月19日", "5月21日", "印刷"):
        assert marker in _note(
            report, "isct-master-path-9-review-process-university-three-year-apr"
        )


def test_scenario_8_multi_credential_and_wrong_intake_fail_safe(rule02a_client) -> None:
    client, document_id = rule02a_client
    credential = _path9()
    multiple = _report(client, document_id, _profile(credential, multiple=True), "rule02a-multi")
    assert "confirmed" not in {
        status for rule_id, status in _statuses(multiple).items() if "path-9" in rule_id
    }
    wrong = _report(client, document_id, _profile(credential, year=2027, month=10), "rule02a-wrong")
    assert all(
        status == "not_applicable"
        for rule_id, status in _statuses(wrong).items()
        if "path-9" in rule_id
    )
