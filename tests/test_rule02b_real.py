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
PLAN = ROOT / "tests/fixtures/reviewed_report_plan_isct_master_rule02b_v1.json"
INTENT_CATALOG = ROOT / "config/query_intent_catalog_v1.json"


@pytest.fixture(scope="module")
def rule02b_client(tmp_path_factory: pytest.TempPathFactory):
    if not PDF.is_file():
        pytest.skip("real PDF fixture unavailable")
    root = tmp_path_factory.mktemp("rule02b")
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
        "rule02b-real", root, (CorpusRegistration(kb_relative, index_relative),)
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


def _path10_entry1(**overrides: Any) -> dict[str, Any]:
    credential = _credential(
        basis="review_path10_sixteen_year_equivalent",
        state="completed",
        completion_date="2027-03-31",
    )
    credential.update(
        prior_education_category="technical_college_advanced_course",
        sixteen_year_equivalence_status="officially_confirmed",
        graduate_equivalent_recognition_status="officially_confirmed",
    )
    credential.update(overrides)
    return credential


def _path11(**overrides: Any) -> dict[str, Any]:
    credential = _credential(
        country="US",
        basis="review_path11_under_sixteen_year_bachelor",
        state="completed",
        completion_date="2025-03-31",
        years=15,
    )
    credential.update(
        under_sixteen_year_bachelor_country_status="officially_confirmed",
        university_education_completion_status="officially_confirmed",
        post_university_research_months=12,
        graduate_equivalent_recognition_status="officially_confirmed",
    )
    credential.update(overrides)
    return credential


def _with_facts(profile: dict[str, Any], *, age: int, work: int | None = None) -> dict[str, Any]:
    profile["eligibility_facts"].update(
        age_at_eligibility_cutoff=age,
        professional_experience_months=work,
    )
    return profile


def _missing(report: dict[str, Any], rule_id: str) -> set[str]:
    return {
        item["field_path"]
        for item in report["cited_answer"]["missing_information"]
        if item["rule_id"] == rule_id
    }


def test_path10_and_path11_real_facts_are_complete(rule02b_client) -> None:
    kb = build_document_kb(PDF, load_document_identity(IDENTITY))
    facts = {fact.fact_id: fact for fact in kb.facts}
    assert "入学する日の前日までに22歳" in facts["fact:00069"].text
    assert "合計2年以上の職務経験" in facts["fact:00069"].text
    assert "1年以上研究に従事" in facts["fact:00070"].text
    assert facts["fact:00069"].source_pages == [7]
    assert facts["fact:00070"].source_pages == [7]


def test_scenario_1_path10_entry1_exact_boundaries_and_age_failure(rule02b_client) -> None:
    client, document_id = rule02b_client
    report = _report(client, document_id, _with_facts(_profile(_path10_entry1()), age=22), "p10-1")
    statuses = _statuses(report)
    assert (
        statuses["isct-master-path-10-entry-1-technical_college_advanced_course-completed-apr"]
        == "confirmed"
    )
    assert statuses["isct-master-path-10-age-sixteen_year_equivalent-apr"] == "confirmed"
    assert (
        statuses["isct-master-path-10-school-recognition-sixteen_year_equivalent-apr"]
        == "confirmed"
    )
    assert "学校による個別資格審査の承認" in report["limitation_statement"]
    low = _report(client, document_id, _with_facts(_profile(_path10_entry1()), age=21), "p10-age21")
    assert _statuses(low)["isct-master-path-10-age-sixteen_year_equivalent-apr"] == "not_applicable"


def test_scenario_2_path10_entry1_missing_official_facts(rule02b_client) -> None:
    client, document_id = rule02b_client
    report = _report(
        client,
        document_id,
        _with_facts(
            _profile(
                _path10_entry1(
                    sixteen_year_equivalence_status=None,
                    graduate_equivalent_recognition_status=None,
                )
            ),
            age=22,
        ),
        "p10-missing",
    )
    candidate = "isct-master-path-10-entry-1-technical_college_advanced_course-completed-apr"
    recognition = "isct-master-path-10-school-recognition-sixteen_year_equivalent-apr"
    assert _missing(report, candidate) == {
        "academic_credentials.first.sixteen_year_equivalence_status"
    }
    assert _missing(report, recognition) == {
        "academic_credentials.first.graduate_equivalent_recognition_status"
    }


def test_scenario_3_path10_entry2_ministerial_confirmation(rule02b_client) -> None:
    client, document_id = rule02b_client
    credential = _credential(basis="review_path10_four_year_specialized_course")
    credential.update(
        program_duration_years=4,
        ministerial_course_standard_status="officially_confirmed",
        ministerial_completion_deadline_status=None,
        graduate_equivalent_recognition_status="officially_confirmed",
    )
    rule_id = "isct-master-path-10-entry-2-apr"
    report = _report(
        client, document_id, _with_facts(_profile(credential), age=22), "p10-entry2-missing"
    )
    assert _missing(report, rule_id) == {
        "academic_credentials.first.ministerial_completion_deadline_status"
    }
    credential["ministerial_completion_deadline_status"] = "officially_confirmed"
    confirmed = _report(
        client, document_id, _with_facts(_profile(credential), age=22), "p10-entry2"
    )
    assert _statuses(confirmed)[rule_id] == "confirmed"


def test_scenario_4_path10_entry3_is_mot_only_and_24_month_boundary(rule02b_client) -> None:
    client, document_id = rule02b_client
    credential = _credential(basis="review_path10_mot_professional_experience")
    credential.update(
        prior_education_category="specialized_training_college",
        graduate_equivalent_recognition_status="officially_confirmed",
    )
    rule_id = "isct-master-path-10-entry-3-specialized_training_college-apr"
    exact_profile = _with_facts(_profile(credential), age=22, work=24)
    assert (
        _statuses(_report(client, document_id, exact_profile, "p10-mot24"))[rule_id] == "confirmed"
    )
    assert (
        _statuses(
            _report(
                client, document_id, _with_facts(_profile(credential), age=22, work=23), "p10-mot23"
            )
        )[rule_id]
        == "not_applicable"
    )
    wrong = _with_facts(_profile(credential), age=22, work=24)
    wrong["target_application"]["department_or_program"] = "建築学系"
    assert (
        _statuses(_report(client, document_id, wrong, "p10-not-mot"))[rule_id] == "not_applicable"
    )


@pytest.mark.parametrize("field,value", [("post_university_research_months", 11), ("age", 21)])
def test_scenario_5_path11_boundaries(rule02b_client, field, value) -> None:
    client, document_id = rule02b_client
    exact = _with_facts(_profile(_path11()), age=22)
    statuses = _statuses(_report(client, document_id, exact, "p11-exact"))
    assert statuses["isct-master-path-11-research-apr"] == "confirmed"
    assert statuses["isct-master-path-11-age-apr"] == "confirmed"
    if field == "age":
        changed = _with_facts(_profile(_path11()), age=value)
        target = "isct-master-path-11-age-apr"
    else:
        changed = _with_facts(_profile(_path11(**{field: value})), age=22)
        target = "isct-master-path-11-research-apr"
    assert (
        _statuses(_report(client, document_id, changed, f"p11-{field}"))[target] == "not_applicable"
    )


def test_scenario_6_review_completion_does_not_imply_recognition(rule02b_client) -> None:
    client, document_id = rule02b_client
    profile = _with_facts(_profile(_path11(graduate_equivalent_recognition_status=None)), age=22)
    profile["eligibility_facts"].update(
        individual_review_status="completed",
        individual_review_requested=True,
        individual_review_completed=True,
    )
    report = _report(client, document_id, profile, "p11-no-recognition")
    rule_id = "isct-master-path-11-school-recognition-apr"
    assert _statuses(report)[rule_id] == "needs_information"
    assert _missing(report, rule_id) == {
        "academic_credentials.first.graduate_equivalent_recognition_status"
    }


def test_scenario_7_september_cutoff_and_unsupported_intake(rule02b_client) -> None:
    client, document_id = rule02b_client
    credential = _path10_entry1(
        completion_state="expected", completion_date=None, expected_completion_date="2026-09-27"
    )
    sep = _report(
        client,
        document_id,
        _with_facts(_profile(credential, year=2026, month=9), age=22),
        "p10-sep",
    )
    assert (
        _statuses(sep)["isct-master-path-10-entry-1-technical_college_advanced_course-expected-sep"]
        == "confirmed"
    )
    wrong = _report(
        client,
        document_id,
        _with_facts(_profile(credential, year=2026, month=10), age=22),
        "p10-wrong",
    )
    assert all(
        status == "not_applicable"
        for rule_id, status in _statuses(wrong).items()
        if "path-10" in rule_id or "path-11" in rule_id
    )


@pytest.mark.parametrize("credential", [_path10_entry1(), _path11()])
def test_scenario_8_shared_process_is_reused(rule02b_client, credential) -> None:
    client, document_id = rule02b_client
    report = _report(
        client, document_id, _with_facts(_profile(credential), age=22), "shared-process"
    )
    process = next(
        item
        for item in report["cited_answer"]["rule_findings"]
        if "review-process" in item["rule_id"]
        and item["original_status"] == "confirmed"
        and ("path-10" in item["rule_id"] or "path-11" in item["rule_id"])
    )
    assert {item["fact_id"] for item in process["citations"]} == {"fact:00086"}
    assert {page for item in process["citations"] for page in item["source_pages"]} == {8}


def test_scenario_9_multiple_credentials_and_missing_mot_scope_fail_safe(rule02b_client) -> None:
    client, document_id = rule02b_client
    credential = _path11()
    multiple = _report(
        client, document_id, _with_facts(_profile(credential, multiple=True), age=22), "p11-multi"
    )
    assert "confirmed" not in {
        status for rule_id, status in _statuses(multiple).items() if "path-11" in rule_id
    }
    mot = _credential(basis="review_path10_mot_professional_experience")
    mot.update(
        prior_education_category="specialized_training_college",
        graduate_equivalent_recognition_status="officially_confirmed",
    )
    profile = _with_facts(_profile(mot), age=22, work=24)
    profile["target_application"]["department_or_program"] = None
    report = _report(client, document_id, profile, "p10-missing-scope")
    assert (
        _statuses(report)["isct-master-path-10-entry-3-specialized_training_college-apr"]
        == "needs_information"
    )
