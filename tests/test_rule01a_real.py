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


pytestmark = pytest.mark.real_pdf
ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf"
IDENTITY = ROOT / "tests/fixtures/document_identity_isct_master_v1.json"
PLAN = ROOT / "tests/fixtures/reviewed_report_plan_isct_master_rule01a_v1.json"
INTENT_CATALOG = ROOT / "config/query_intent_catalog_v1.json"


@pytest.fixture(scope="module")
def rule01a_client(tmp_path_factory: pytest.TempPathFactory):
    if not PDF.is_file():
        pytest.skip("real PDF fixture unavailable")
    root = tmp_path_factory.mktemp("rule01a")
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
        "rule01a-real",
        root,
        (CorpusRegistration(kb_relative, index_relative),),
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


def _credential(
    *,
    country: str | None = "JP",
    basis: str | None = "university_graduation",
    state: str | None = "completed",
    completion_date: str | None = "2026-09-01",
    expected_date: str | None = None,
    years: int | None = 16,
) -> dict[str, Any]:
    return {
        "institution_country_code": country,
        "degree_level": "bachelor",
        "credential_basis": basis,
        "completion_state": state,
        "completion_date": completion_date,
        "expected_completion_date": expected_date,
        "years_of_education": years,
    }


def _profile(
    credential: dict[str, Any] | None,
    *,
    year: int = 2027,
    month: int = 4,
    degree: str = "master",
    multiple: bool = False,
) -> dict[str, Any]:
    credentials = None if credential is None else [credential]
    if credentials is not None and multiple:
        credentials.append(dict(credential))
    return {
        "schema_version": "1.0",
        "target_application": {
            "graduate_school_or_college": "環境・社会理工学院",
            "department_or_program": "技術経営専門職学位課程",
            "requested_degree_level": degree,
            "intake_year": year,
            "intake_month": month,
            "application_route": "general",
        },
        "citizenship_and_residence": {
            "citizenship_country_codes": None,
            "current_residence_country_code": None,
            "residence_status_category": None,
        },
        "academic_credentials": credentials,
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


def _report(client: TestClient, document_id: str, profile: dict[str, Any], report_id: str):
    intent = client.post(
        "/v1/query-intents/parse",
        json={"schema_version": "1.0", "query": "修士課程の出願資格"},
    )
    assert intent.status_code == 200
    response = client.post(
        "/v1/applicant-reports",
        json={
            "schema_version": "1.0",
            "report_id": report_id,
            "profile": profile,
            "intent": intent.json(),
            "selection": {"document_ids": [document_id]},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["report"]


def _statuses(report: dict[str, Any]) -> dict[str, str]:
    return {
        item["rule_id"]: item["original_status"] for item in report["cited_answer"]["rule_findings"]
    }


@pytest.mark.parametrize(
    ("scenario", "credential", "year", "month", "rule_id", "status"),
    [
        (
            "jp-completed",
            _credential(),
            2027,
            4,
            "isct-master-direct-path-1-university-apr-completed",
            "confirmed",
        ),
        (
            "jp-expected-boundary",
            _credential(state="expected", completion_date=None, expected_date="2027-03-31"),
            2027,
            4,
            "isct-master-direct-path-1-university-apr-expected",
            "confirmed",
        ),
        (
            "jp-expected-late",
            _credential(state="expected", completion_date=None, expected_date="2027-04-01"),
            2027,
            4,
            "isct-master-direct-path-1-university-apr-expected",
            "not_applicable",
        ),
        (
            "sep-boundary",
            _credential(state="expected", completion_date=None, expected_date="2026-09-27"),
            2026,
            9,
            "isct-master-direct-path-1-university-sep-expected",
            "confirmed",
        ),
        (
            "foreign-16-years",
            _credential(
                country="US",
                basis="foreign_16_year_bachelor_equivalent",
                years=16,
            ),
            2027,
            4,
            "isct-master-direct-path-3-foreign_16_year-apr-completed",
            "confirmed",
        ),
        (
            "foreign-15-years",
            _credential(
                country="US",
                basis="foreign_16_year_bachelor_equivalent",
                years=15,
            ),
            2027,
            4,
            "isct-master-direct-path-3-foreign_16_year-apr-completed",
            "not_applicable",
        ),
        (
            "niad-award",
            _credential(basis="niad_qe_bachelor_award"),
            2027,
            4,
            "isct-master-direct-path-2-niad_qe-apr-completed",
            "confirmed",
        ),
    ],
)
def test_rule01a_json_api_direct_path_scenarios(
    rule01a_client,
    scenario: str,
    credential: dict[str, Any],
    year: int,
    month: int,
    rule_id: str,
    status: str,
) -> None:
    client, document_id = rule01a_client
    report = _report(client, document_id, _profile(credential, year=year, month=month), scenario)

    assert _statuses(report)[rule_id] == status
    assert "overall eligibility" in report["limitation_statement"]
    if status == "confirmed":
        finding = next(
            item for item in report["cited_answer"]["rule_findings"] if item["rule_id"] == rule_id
        )
        assert any(citation["source_pages"] == [7] for citation in finding["citations"])


def test_rule01a_sep_special_contact_is_explicit_and_cited(rule01a_client) -> None:
    client, document_id = rule01a_client
    report = _report(
        client,
        document_id,
        _profile(
            _credential(state="expected", completion_date=None, expected_date="2026-09-28"),
            year=2026,
            month=9,
        ),
        "sep-special-contact",
    )
    rule_id = "isct-master-direct-path-1-university-sep-special-contact"

    assert _statuses(report)[rule_id] == "confirmed"
    finding = next(
        item for item in report["cited_answer"]["rule_findings"] if item["rule_id"] == rule_id
    )
    assert any(citation["fact_id"] == "fact:00075" for citation in finding["citations"])
    assert any(
        record["source_pages"] == [8] for record in report["evidence_bundle"]["evidence_records"]
    )
    rule = next(item for item in report["source_plan"]["rules"] if item["rule_id"] == rule_id)
    assert "事前に入試課へメール" in rule["annotation_note"]


def test_rule01a_missing_years_and_completion_fields_are_exact(rule01a_client) -> None:
    client, document_id = rule01a_client
    missing_years = _report(
        client,
        document_id,
        _profile(
            _credential(
                country="US",
                basis="foreign_16_year_bachelor_equivalent",
                years=None,
            )
        ),
        "missing-years",
    )
    rule_id = "isct-master-direct-path-3-foreign_16_year-apr-completed"
    missing = {
        item["field_path"]
        for item in missing_years["cited_answer"]["missing_information"]
        if item["rule_id"] == rule_id
    }
    assert _statuses(missing_years)[rule_id] == "needs_information"
    assert missing == {"academic_credentials.first.years_of_education"}

    missing_completion = _report(
        client,
        document_id,
        _profile(_credential(state=None, completion_date=None, expected_date=None)),
        "missing-completion",
    )
    completed_rule = "isct-master-direct-path-1-university-apr-completed"
    completed_missing = {
        item["field_path"]
        for item in missing_completion["cited_answer"]["missing_information"]
        if item["rule_id"] == completed_rule
    }
    assert completed_missing == {
        "academic_credentials.first.completion_date",
        "academic_credentials.first.completion_state",
    }


def test_rule01a_multiple_credentials_and_wrong_degree_fail_safe(rule01a_client) -> None:
    client, document_id = rule01a_client
    multiple = _report(
        client,
        document_id,
        _profile(_credential(), multiple=True),
        "multiple-credentials",
    )
    direct_statuses = {
        rule_id: status
        for rule_id, status in _statuses(multiple).items()
        if rule_id.startswith("isct-master-direct-path-")
    }
    assert set(direct_statuses.values()) == {"needs_information"}
    assert any(
        item["kind"] == "multiple_academic_credentials"
        for item in multiple["cited_answer"]["process_notices"]
    )

    wrong_degree = _report(
        client,
        document_id,
        _profile(_credential(), degree="professional"),
        "wrong-degree",
    )
    assert all(
        status == "not_applicable"
        for rule_id, status in _statuses(wrong_degree).items()
        if rule_id.startswith("isct-master-direct-path-")
    )


def test_rule01a_real_fact_boundaries_are_exact(rule01a_client) -> None:
    _, _ = rule01a_client
    kb = build_document_kb(PDF, load_document_identity(IDENTITY))
    facts = {fact.fact_id: fact for fact in kb.facts}

    assert facts["fact:00060"].text == (
        "（１）我が国において、大学を卒業した者及び2027年3月31日までに卒業見込みの者"
    )
    assert facts["fact:00060"].source_pages == [7]
    assert facts["fact:00075"].text == (
        "## Page 8\n\n"
        "［2026年9月入学希望者で、9月28日から9月30日までの間に上記（１）～（６）の出願資格を満たす者への注意］\n"
        "2026年9月入学希望者（希望する入学時期②選択の者）で、9月28日時点で出願資格を満たさず、9月28日～9月30日の間に上記\n"
        "（１）～（６）の出願資格を満たす者は、事前に「卒業見込み（授与見込み、修了見込み）の年月日」をメールにて、入試課\n"
        "(inquiries.grad.se@adm.isct.ac.jp)へお知らせください。"
    )
    assert facts["fact:00075"].source_pages == [8]
