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
PLAN = ROOT / "tests/fixtures/reviewed_report_plan_isct_master_rule01b_v1.json"
INTENT_CATALOG = ROOT / "config/query_intent_catalog_v1.json"


@pytest.fixture(scope="module")
def rule01b_client(tmp_path_factory: pytest.TempPathFactory):
    if not PDF.is_file():
        pytest.skip("real PDF fixture unavailable")
    root = tmp_path_factory.mktemp("rule01b")
    kb = build_document_kb(PDF, load_document_identity(IDENTITY))
    kb_relative = "documents/isct/document_kb.json"
    kb_path = root / Path(*kb_relative.split("/"))
    kb_path.parent.mkdir(parents=True)
    kb_path.write_bytes(canonical_document_kb_bytes(kb))
    index_relative = "indexes/isct"
    build_local_index(
        kb_path,
        root / Path(*index_relative.split("/")),
        DeterministicFakeEmbeddingProvider(8),
    )
    manifest = build_corpus_manifest(
        "rule01b-real", root, (CorpusRegistration(kb_relative, index_relative),)
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


def _special_credential(
    basis: str,
    *,
    country: str = "US",
    state: str | None = "completed",
    completion_date: str | None = "2026-09-01",
    expected_date: str | None = None,
    years: int | None = None,
    coursework_in_japan: bool | None = None,
    duration: int | None = None,
    institution_status: str | None = None,
    program_status: str | None = None,
    person_status: str | None = None,
) -> dict[str, Any]:
    credential = _credential(
        country=country,
        basis=basis,
        state=state,
        completion_date=completion_date,
        expected_date=expected_date,
        years=years,
    )
    credential.update(
        coursework_in_japan=coursework_in_japan,
        program_duration_years=duration,
        institution_recognition_status=institution_status,
        program_designation_status=program_status,
        person_designation_status=person_status,
    )
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


def test_rule01b_real_fact_boundaries_are_complete_and_independent(rule01b_client) -> None:
    kb = build_document_kb(PDF, load_document_identity(IDENTITY))
    facts = {fact.fact_id: fact for fact in kb.facts}
    expected_prefixes = {
        "fact:00063": "（４）外国の学校が行う通信教育",
        "fact:00064": "（５）我が国において、外国の大学の課程",
        "fact:00065": "◆（６）外国の大学その他の外国の学校",
        "fact:00066": "（７）専修学校の専門課程",
        "fact:00067": "（８）文部科学大臣の指定した者",
    }

    assert len(kb.facts) == 316
    for fact_id, prefix in expected_prefixes.items():
        assert facts[fact_id].text.startswith(prefix)
        assert facts[fact_id].source_pages == [7]
    assert "◆（６）" not in facts["fact:00064"].text
    assert "★（９）" not in facts["fact:00067"].text
    assert facts["fact:00068"].text.startswith("★（９）")
    assert facts["fact:00085"].text.startswith("［2026年9月入学希望者で")
    assert "事前に" in facts["fact:00085"].text


def test_path4_distance_education_requires_japan_coursework(rule01b_client) -> None:
    client, document_id = rule01b_client
    rule_id = "isct-master-direct-path-4-distance_in_japan-apr-expected"
    matching = _special_credential(
        "foreign_distance_education_in_japan",
        state="expected",
        completion_date=None,
        expected_date="2027-03-31",
        years=16,
        coursework_in_japan=True,
    )
    report = _report(client, document_id, _profile(matching), "rule01b-path4")
    assert _statuses(report)[rule_id] == "confirmed"
    assert any(c["fact_id"] == "fact:00063" for c in _finding(report, rule_id)["citations"])

    matching["coursework_in_japan"] = None
    missing = _report(client, document_id, _profile(matching), "rule01b-path4-missing")
    assert _statuses(missing)[rule_id] == "needs_information"
    assert _missing(missing, rule_id) == {"academic_credentials.first.coursework_in_japan"}


def test_path5_requires_official_program_designation(rule01b_client) -> None:
    client, document_id = rule01b_client
    rule_id = "isct-master-direct-path-5-foreign_program_in_japan-apr-completed"
    credential = _special_credential(
        "foreign_university_program_in_japan", years=16, program_status=None
    )
    missing = _report(client, document_id, _profile(credential), "rule01b-path5-missing")
    assert _statuses(missing)[rule_id] == "needs_information"
    assert _missing(missing, rule_id) == {"academic_credentials.first.program_designation_status"}

    credential["program_designation_status"] = "officially_confirmed"
    confirmed = _report(client, document_id, _profile(credential), "rule01b-path5")
    assert _statuses(confirmed)[rule_id] == "confirmed"


def test_path6_requires_recognition_duration_and_contact_action(rule01b_client) -> None:
    client, document_id = rule01b_client
    rule_id = "isct-master-direct-path-6-recognized_foreign_three_year-apr-completed"
    credential = _special_credential(
        "recognized_foreign_three_year_bachelor",
        duration=3,
        institution_status="officially_confirmed",
    )
    report = _report(client, document_id, _profile(credential), "rule01b-path6")
    assert _statuses(report)[rule_id] == "confirmed"
    rule = next(item for item in report["source_plan"]["rules"] if item["rule_id"] == rule_id)
    assert "出願期間前" in rule["annotation_note"]
    assert any(c["fact_id"] == "fact:00065" for c in _finding(report, rule_id)["citations"])

    credential["program_duration_years"] = 2
    too_short = _report(client, document_id, _profile(credential), "rule01b-path6-short")
    assert _statuses(too_short)[rule_id] == "not_applicable"


def test_path6_september_special_keeps_both_contact_actions(rule01b_client) -> None:
    client, document_id = rule01b_client
    rule_id = "isct-master-direct-path-6-recognized_foreign_three_year-sep-special-contact"
    credential = _special_credential(
        "recognized_foreign_three_year_bachelor",
        state="expected",
        completion_date=None,
        expected_date="2026-09-28",
        duration=3,
        institution_status="officially_confirmed",
    )
    report = _report(
        client, document_id, _profile(credential, year=2026, month=9), "rule01b-path6-sep"
    )
    assert _statuses(report)[rule_id] == "confirmed"
    citations = _finding(report, rule_id)["citations"]
    assert {item["fact_id"] for item in citations} >= {"fact:00059", "fact:00065", "fact:00085"}
    note = next(item for item in report["source_plan"]["rules"] if item["rule_id"] == rule_id)[
        "annotation_note"
    ]
    assert "出願期間前" in note and "9月28日から30日" in note


def test_path7_has_no_invented_date_predicate(rule01b_client) -> None:
    client, document_id = rule01b_client
    rule_id = "isct-master-direct-path-7-designated_vocational-apr-expected"
    credential = _special_credential(
        "designated_specialized_training_college",
        country="JP",
        state="expected",
        completion_date=None,
        duration=4,
        program_status=None,
    )
    missing = _report(client, document_id, _profile(credential), "rule01b-path7-missing")
    assert _statuses(missing)[rule_id] == "needs_information"
    credential["program_designation_status"] = "officially_confirmed"
    confirmed = _report(client, document_id, _profile(credential), "rule01b-path7")
    assert _statuses(confirmed)[rule_id] == "confirmed"
    rule = next(item for item in confirmed["source_plan"]["rules"] if item["rule_id"] == rule_id)
    assert all("date" not in item["field_path"] for item in rule["predicates"])
    assert "3月31日" in rule["annotation_note"]


def test_path8_requires_official_person_designation_only(rule01b_client) -> None:
    client, document_id = rule01b_client
    rule_id = "isct-master-direct-path-8-minister_designated-apr"
    credential = _special_credential("minister_designated_person", country="JP", person_status=None)
    missing = _report(client, document_id, _profile(credential), "rule01b-path8-missing")
    assert _statuses(missing)[rule_id] == "needs_information"
    assert _missing(missing, rule_id) == {"academic_credentials.first.person_designation_status"}
    credential["person_designation_status"] = "officially_confirmed"
    confirmed = _report(client, document_id, _profile(credential), "rule01b-path8")
    assert _statuses(confirmed)[rule_id] == "confirmed"
    assert any(c["fact_id"] == "fact:00067" for c in _finding(confirmed, rule_id)["citations"])
    assert "overall eligibility" in confirmed["limitation_statement"]


def test_rule01b_multi_credential_and_unsupported_intake_fail_safe(rule01b_client) -> None:
    client, document_id = rule01b_client
    credential = _special_credential(
        "recognized_foreign_three_year_bachelor",
        duration=3,
        institution_status="officially_confirmed",
    )
    multiple = _report(client, document_id, _profile(credential, multiple=True), "rule01b-multiple")
    assert all(
        status == "needs_information"
        for rule_id, status in _statuses(multiple).items()
        if "direct-path" in rule_id
    )

    unsupported = _report(
        client, document_id, _profile(credential, year=2027, month=10), "rule01b-unsupported"
    )
    assert all(
        status == "not_applicable"
        for rule_id, status in _statuses(unsupported).items()
        if "direct-path" in rule_id
    )
