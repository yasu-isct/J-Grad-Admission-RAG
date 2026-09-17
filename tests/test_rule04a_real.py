from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from jgrad_admission_rag.builder.kb_builder import build_document_kb
from jgrad_admission_rag.corpus import CorpusRegistration, build_corpus_manifest
from jgrad_admission_rag.corpus_selection import select_corpus_documents
from jgrad_admission_rag.reasoning.reviewed_report_evidence import prepare_reviewed_report_evidence
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

pytestmark = pytest.mark.real_pdf
ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf"
IDENTITY = ROOT / "tests/fixtures/document_identity_isct_master_v1.json"
PLAN = ROOT / "tests/fixtures/reviewed_report_plan_isct_master_rule04c_v1.json"
BATCHES = ((2027, 4, "apr"), (2026, 9, "sep"))


@pytest.fixture(scope="module")
def rule04a_client(tmp_path_factory: pytest.TempPathFactory):
    if not PDF.is_file():
        pytest.skip("real PDF fixture unavailable")
    root = tmp_path_factory.mktemp("rule04a")
    kb = build_document_kb(PDF, load_document_identity(IDENTITY))
    kb_path = root / "documents/isct/document_kb.json"
    kb_path.parent.mkdir(parents=True)
    kb_path.write_bytes(canonical_document_kb_bytes(kb))
    build_local_index(kb_path, root / "indexes/isct", DeterministicFakeEmbeddingProvider(8))
    manifest = build_corpus_manifest(
        "rule04a-real",
        root,
        (CorpusRegistration("documents/isct/document_kb.json", "indexes/isct"),),
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
    selection = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(document_ids=(kb.manifest.identity.document_id,)),
    )
    prepare_reviewed_report_evidence(
        root,
        manifest,
        policy,
        selection,
        (load_reviewed_report_plan(PLAN),),
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
        yield client, kb.manifest.identity.document_id


def _language_profile(
    year: int,
    month: int,
    *,
    department: str = "情報通信系",
    college: str | None = None,
    results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    profile = _profile(None, year=year, month=month)
    profile["target_application"]["department_or_program"] = department
    if college is not None:
        profile["target_application"]["graduate_school_or_college"] = college
    profile["language_test_results"] = results
    return profile


def _language_result(kind: str, **changes: Any) -> dict[str, Any]:
    result = {
        "test_kind": kind,
        "test_date": "2024-06-11",
        "score": None,
        "validity_status": None,
        "official_report_available": None,
        "selected_for_submission": True,
        "downloaded_online_pdf": True,
        "toeic_verification_qr_present": None,
        "toeic_digital_official_score_certificate": None,
        "toefl_test_taker_score_report_pdf": None,
        "toefl_di_code_g179_set": None,
        "ets_paper_sent_to_applicant": False,
        "ets_paper_sent_to_institution": False,
    }
    result.update(changes)
    return result


def _finding(report: dict[str, Any], rule_id: str) -> dict[str, Any]:
    return next(
        item for item in report["cited_answer"]["rule_findings"] if item["rule_id"] == rule_id
    )


def test_real_english_facts_are_atomic_and_scoped() -> None:
    if not PDF.is_file():
        pytest.skip("real PDF fixture unavailable")
    kb = build_document_kb(PDF, load_document_identity(IDENTITY))
    assert len(kb.facts) == 391
    facts = {fact.fact_id: fact for fact in kb.facts}
    for fact_id in ("fact:00110", "fact:00111", "fact:00114", "fact:00115", "fact:00122"):
        assert facts[fact_id].scope_type == "global"
        assert facts[fact_id].scope_targets == []
    assert facts["fact:00123"].scope_type == "department"
    assert facts["fact:00123"].scope_targets == ["数学系"]
    assert "奨学金" not in facts["fact:00114"].text
    assert "奨学金" not in facts["fact:00115"].text


@pytest.mark.parametrize(("year", "month", "suffix"), BATCHES)
def test_toeic_submission_requirements(rule04a_client, year, month, suffix) -> None:
    client, document_id = rule04a_client
    result = _language_result(
        "toeic_lr",
        toeic_verification_qr_present=True,
        toeic_digital_official_score_certificate=True,
    )
    report = _report(
        client,
        document_id,
        _language_profile(year, month, results=[result]),
        f"toeic-{suffix}",
    )
    statuses = _statuses(report)
    for name in (
        "external-score-required",
        "approved-kind-toeic_lr",
        "test-date",
        "online-pdf",
        "toeic-qr",
        "toeic-digital-certificate",
        "no-paper-to-applicant",
        "no-paper-to-university",
    ):
        assert statuses[f"isct-master-english-{name}-{suffix}"] == "confirmed"
    approved = _finding(report, f"isct-master-english-approved-kind-toeic_lr-{suffix}")
    assert {item["fact_id"] for item in approved["citations"]} == {"fact:00110"}
    common = _finding(report, f"isct-master-english-external-score-required-{suffix}")
    assert {item["fact_id"] for item in common["citations"]} == {"fact:00122"}


@pytest.mark.parametrize("test_kind", ("toefl_ibt", "toefl_ibt_home_edition"))
@pytest.mark.parametrize(("year", "month", "suffix"), BATCHES)
def test_toefl_submission_requirements(rule04a_client, year, month, suffix, test_kind) -> None:
    client, document_id = rule04a_client
    result = _language_result(
        test_kind,
        toefl_test_taker_score_report_pdf=True,
        toefl_di_code_g179_set=True,
    )
    report = _report(
        client,
        document_id,
        _language_profile(year, month, results=[result]),
        f"toefl-{suffix}",
    )
    statuses = _statuses(report)
    for name in (
        f"approved-kind-{test_kind}",
        "test-date",
        "online-pdf",
        f"toefl-report-{test_kind}",
        f"toefl-g179-{test_kind}",
        "no-paper-to-applicant",
        "no-paper-to-university",
    ):
        assert statuses[f"isct-master-english-{name}-{suffix}"] == "confirmed"
    approved = _finding(report, f"isct-master-english-approved-kind-{test_kind}-{suffix}")
    assert {item["fact_id"] for item in approved["citations"]} == {"fact:00111"}


@pytest.mark.parametrize(("year", "month", "suffix"), BATCHES)
def test_test_date_boundary_is_inclusive(rule04a_client, year, month, suffix) -> None:
    client, document_id = rule04a_client
    profile = _language_profile(
        year,
        month,
        results=[_language_result("toeic_lr", test_date="2024-06-10")],
    )
    report = _report(client, document_id, profile, f"old-date-{suffix}")
    assert _statuses(report)[f"isct-master-english-test-date-{suffix}"] == "not_applicable"

    unknown = _language_profile(
        year,
        month,
        results=[_language_result("toeic_lr", test_date=None)],
    )
    report = _report(client, document_id, unknown, f"unknown-date-{suffix}")
    finding = _finding(report, f"isct-master-english-test-date-{suffix}")
    assert finding["original_status"] == "needs_information"
    assert any(
        item["field_path"] == "language_test_results.selected.test_date"
        for item in report["cited_answer"]["missing_information"]
    )


@pytest.mark.parametrize(
    ("test_kind", "rule_kind"), (("toefl_itp", "toefl_itp"), ("toeic_ip", "toeic_ip"))
)
@pytest.mark.parametrize(("year", "month", "suffix"), BATCHES)
def test_unapproved_test_is_not_misreported_as_approved(
    rule04a_client, year, month, suffix, test_kind, rule_kind
) -> None:
    client, document_id = rule04a_client
    profile = _language_profile(year, month, results=[_language_result(test_kind)])
    report = _report(client, document_id, profile, f"{rule_kind}-{suffix}")
    statuses = _statuses(report)
    assert statuses[f"isct-master-english-unapproved-kind-{rule_kind}-{suffix}"] == "confirmed"
    for kind in ("toeic_lr", "toefl_ibt", "toefl_ibt_home_edition"):
        assert statuses[f"isct-master-english-approved-kind-{kind}-{suffix}"] == "not_applicable"


@pytest.mark.parametrize(("year", "month", "suffix"), BATCHES)
def test_other_test_kind_requires_individual_review(rule04a_client, year, month, suffix) -> None:
    client, document_id = rule04a_client
    profile = _language_profile(year, month, results=[_language_result("other")])
    report = _report(client, document_id, profile, f"other-{suffix}")
    statuses = _statuses(report)
    assert statuses[f"isct-master-english-unreviewed-kind-other-{suffix}"] == "confirmed"
    for kind in ("toeic_lr", "toefl_ibt", "toefl_ibt_home_edition"):
        assert statuses[f"isct-master-english-approved-kind-{kind}-{suffix}"] == "not_applicable"


@pytest.mark.parametrize(("year", "month", "suffix"), BATCHES)
def test_toefl_missing_di_and_paper_delivery_fail_safely(
    rule04a_client, year, month, suffix
) -> None:
    client, document_id = rule04a_client
    rule_id = f"isct-master-english-toefl-g179-toefl_ibt-{suffix}"
    for marker, di_code, expected in (
        ("missing", False, "not_applicable"),
        ("unknown", None, "needs_information"),
    ):
        result = _language_result("toefl_ibt", toefl_di_code_g179_set=di_code)
        report = _report(
            client,
            document_id,
            _language_profile(year, month, results=[result]),
            f"toefl-di-{marker}-{suffix}",
        )
        assert _statuses(report)[rule_id] == expected

    paper = _language_result(
        "toefl_ibt",
        downloaded_online_pdf=False,
        ets_paper_sent_to_institution=True,
    )
    report = _report(
        client,
        document_id,
        _language_profile(year, month, results=[paper]),
        f"toefl-paper-{suffix}",
    )
    assert _statuses(report)[f"isct-master-english-no-paper-to-university-{suffix}"] == (
        "not_applicable"
    )


@pytest.mark.parametrize(("year", "month", "suffix"), BATCHES)
def test_toeic_missing_qr_and_paper_certificate_fail_safely(
    rule04a_client, year, month, suffix
) -> None:
    client, document_id = rule04a_client
    rule_id = f"isct-master-english-toeic-qr-{suffix}"
    for marker, qr_present, expected in (
        ("missing", False, "not_applicable"),
        ("unknown", None, "needs_information"),
    ):
        result = _language_result("toeic_lr", toeic_verification_qr_present=qr_present)
        report = _report(
            client,
            document_id,
            _language_profile(year, month, results=[result]),
            f"toeic-qr-{marker}-{suffix}",
        )
        assert _statuses(report)[rule_id] == expected

    paper = _language_result(
        "toeic_lr",
        downloaded_online_pdf=False,
        ets_paper_sent_to_applicant=True,
    )
    report = _report(
        client,
        document_id,
        _language_profile(year, month, results=[paper]),
        f"toeic-paper-{suffix}",
    )
    assert _statuses(report)[f"isct-master-english-no-paper-to-applicant-{suffix}"] == (
        "not_applicable"
    )


@pytest.mark.parametrize(("year", "month", "suffix"), BATCHES)
def test_math_department_uses_written_exam_exception(rule04a_client, year, month, suffix) -> None:
    client, document_id = rule04a_client
    report = _report(
        client,
        document_id,
        _language_profile(year, month, department="数学系", college="理学院"),
        f"math-{suffix}",
    )
    statuses = _statuses(report)
    assert statuses[f"isct-master-english-math-written-exam-{suffix}"] == "confirmed"
    assert statuses[f"isct-master-english-test-date-{suffix}"] == "not_applicable"


@pytest.mark.parametrize(("year", "month", "suffix"), BATCHES)
def test_multiple_results_require_explicit_selection(rule04a_client, year, month, suffix) -> None:
    client, document_id = rule04a_client
    results = [
        _language_result("toeic_lr", selected_for_submission=None),
        _language_result("toefl_ibt", selected_for_submission=None),
    ]
    report = _report(
        client,
        document_id,
        _language_profile(year, month, results=results),
        f"ambiguous-{suffix}",
    )
    finding = _finding(report, f"isct-master-english-test-date-{suffix}")
    assert finding["original_status"] == "needs_information"
    assert any(
        item["field_path"] == "language_test_results.selected_for_submission"
        for item in report["cited_answer"]["missing_information"]
    )
    assert all(
        not item["field_path"].startswith("language_test_results.selected.")
        for item in report["cited_answer"]["missing_information"]
    )
    assert any(
        item["kind"] == "ambiguous_language_result_selection"
        for item in report["cited_answer"]["process_notices"]
    )


@pytest.mark.parametrize(("year", "month", "suffix"), BATCHES)
def test_missing_result_and_unknown_department_need_information(
    rule04a_client, year, month, suffix
) -> None:
    client, document_id = rule04a_client
    no_result = _language_profile(year, month, results=None)
    report = _report(client, document_id, no_result, f"no-result-{suffix}")
    assert _statuses(report)[f"isct-master-english-test-date-{suffix}"] == "needs_information"

    unknown_target = _language_profile(
        year,
        month,
        department=None,
        results=[_language_result("toeic_lr")],
    )
    unknown_target["target_application"]["graduate_school_or_college"] = None
    report = _report(client, document_id, unknown_target, f"unknown-target-{suffix}")
    finding = _finding(report, f"isct-master-english-math-written-exam-{suffix}")
    assert finding["original_status"] == "needs_information"
    assert any(
        item["field_path"] == "target_application.department_or_program"
        for item in report["cited_answer"]["missing_information"]
    )
