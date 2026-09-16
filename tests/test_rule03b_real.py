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
    CorpusVersionPolicy,
    canonical_corpus_version_policy_bytes,
)
from jgrad_admission_rag.schemas.corpus_version import CorpusSelectionRequest
from jgrad_admission_rag.schemas.document_identity import load_document_identity
from jgrad_admission_rag.schemas.document_kb import canonical_document_kb_bytes
from jgrad_admission_rag.service import ServiceDependencies, ServiceSettings, create_app
from tests.test_rule01a_real import _profile, _report, _statuses

pytestmark = pytest.mark.real_pdf
ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf"
IDENTITY = ROOT / "tests/fixtures/document_identity_isct_master_v1.json"
PLAN = ROOT / "tests/fixtures/reviewed_report_plan_isct_master_rule03b_v1.json"


@pytest.fixture(scope="module")
def rule03b_client(tmp_path_factory: pytest.TempPathFactory):
    if not PDF.is_file():
        pytest.skip("real PDF fixture unavailable")
    root = tmp_path_factory.mktemp("rule03b")
    kb = build_document_kb(PDF, load_document_identity(IDENTITY))
    kb_path = root / "documents/isct/document_kb.json"
    kb_path.parent.mkdir(parents=True)
    kb_path.write_bytes(canonical_document_kb_bytes(kb))
    build_local_index(kb_path, root / "indexes/isct", DeterministicFakeEmbeddingProvider(8))
    manifest = build_corpus_manifest(
        "rule03b-real",
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
    manifest_path, policy_path = (root / "corpus.json").resolve(), (root / "policy.json").resolve()
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


def _pre(*, year=2027, month=4, residence=None, **facts):
    profile = _profile(None, year=year, month=month)
    profile["citizenship_and_residence"]["current_residence_country_code"] = residence
    profile["preapplication_actions"] = facts
    return profile


def _missing(report: dict[str, Any], rule_id: str) -> set[str]:
    return {
        item["field_path"]
        for item in report["cited_answer"]["missing_information"]
        if item["rule_id"] == rule_id
    }


def test_real_preapplication_facts_remain_global_after_english_atomization() -> None:
    if not PDF.is_file():
        pytest.skip("real PDF fixture unavailable")
    kb = build_document_kb(PDF, load_document_identity(IDENTITY))
    facts = {fact.fact_id: fact for fact in kb.facts}
    expected = {
        "fact:00010": 3,
        "fact:00018": 3,
        "fact:00024": 4,
        "fact:00025": 4,
        "fact:00026": 4,
        "fact:00029": 4,
        "fact:00030": 4,
        "fact:00031": 4,
        "fact:00112": 11,
    }
    assert len(facts) == 334
    for fact_id, page in expected.items():
        assert facts[fact_id].source_pages == [page]
        assert facts[fact_id].scope_type == "global"
        assert facts[fact_id].scope_targets == []
    assert "数学系" not in facts["fact:00112"].text
    assert facts["fact:00112"].section_path[-1] == "【外国籍の志願者のみ提出する書類】"
    assert facts["fact:00108"].scope_type == "department"
    assert facts["fact:00108"].scope_targets == ["数学系"]


def test_special_accommodation_has_purpose_specific_missing_contact(rule03b_client) -> None:
    client, document_id = rule03b_client
    report = _report(client, document_id, _pre(special_accommodation_needed=True), "accommodation")
    rule_id = "isct-master-special-accommodation-contact-apr"
    assert _statuses(report)[rule_id] == "needs_information"
    assert _missing(report, rule_id) == {
        "preapplication_actions.special_accommodation_contacted_admissions"
    }


@pytest.mark.parametrize(
    ("expiry", "validity", "contact"),
    [
        ("2026-09-08", "not_applicable", "confirmed"),
        ("2026-09-27", "not_applicable", "confirmed"),
        ("2026-09-28", "confirmed", "not_applicable"),
    ],
)
def test_foreign_september_date_boundaries(rule03b_client, expiry, validity, contact) -> None:
    client, document_id = rule03b_client
    report = _report(
        client,
        document_id,
        _pre(
            year=2026,
            month=9,
            residence="JP",
            foreign_national_rule_applies=True,
            residence_status_valid_until=expiry,
            residence_status_allows_long_term_stay=True,
        ),
        f"foreign-{expiry}",
    )
    statuses = _statuses(report)
    assert statuses["isct-master-foreign-sep-resides-in-japan"] == "confirmed"
    assert statuses["isct-master-foreign-sep-long-term-residence-status"] == "confirmed"
    assert statuses["isct-master-foreign-sep-residence-valid-through-boundary"] == validity
    assert statuses["isct-master-foreign-sep-residence-contact-window"] == contact
    if contact == "confirmed":
        completed = "isct-master-foreign-sep-residence-contact-completed"
        assert statuses[completed] == "needs_information"
        assert _missing(report, completed) == {
            "preapplication_actions.residence_status_contacted_admissions"
        }


def test_foreign_conditions_are_independent_and_september_only(rule03b_client) -> None:
    client, document_id = rule03b_client
    facts = {
        "foreign_national_rule_applies": True,
        "residence_status_valid_until": "2026-09-28",
        "residence_status_allows_long_term_stay": False,
    }
    report = _report(
        client,
        document_id,
        _pre(year=2026, month=9, residence="US", **facts),
        "foreign-independent",
    )
    statuses = _statuses(report)
    assert statuses["isct-master-foreign-sep-resides-in-japan"] == "not_applicable"
    assert statuses["isct-master-foreign-sep-long-term-residence-status"] == "not_applicable"
    assert statuses["isct-master-foreign-sep-residence-valid-through-boundary"] == "confirmed"
    april = _report(client, document_id, _pre(residence="JP", **facts), "foreign-april")
    assert _statuses(april)["isct-master-foreign-sep-resides-in-japan"] == "not_applicable"


def test_foreign_september_unknown_expiry_is_precise(rule03b_client) -> None:
    client, document_id = rule03b_client
    report = _report(
        client,
        document_id,
        _pre(
            year=2026,
            month=9,
            residence="JP",
            foreign_national_rule_applies=True,
            residence_status_allows_long_term_stay=True,
        ),
        "foreign-unknown-expiry",
    )
    rule_id = "isct-master-foreign-sep-residence-valid-through-boundary"
    assert _statuses(report)[rule_id] == "needs_information"
    assert _missing(report, rule_id) == {"preapplication_actions.residence_status_valid_until"}


def test_non_foreign_applicant_does_not_trigger_september_residence_rules(
    rule03b_client,
) -> None:
    client, document_id = rule03b_client
    report = _report(
        client,
        document_id,
        _pre(
            year=2026,
            month=9,
            residence="JP",
            foreign_national_rule_applies=False,
            residence_status_valid_until="2026-09-28",
            residence_status_allows_long_term_stay=True,
            residence_status_contacted_admissions=True,
        ),
        "not-foreign",
    )
    statuses = _statuses(report)
    for rule_id in (
        "isct-master-foreign-sep-resides-in-japan",
        "isct-master-foreign-sep-long-term-residence-status",
        "isct-master-foreign-sep-residence-valid-through-boundary",
        "isct-master-foreign-sep-residence-contact-window",
        "isct-master-foreign-sep-residence-contact-completed",
    ):
        assert statuses[rule_id] == "not_applicable"


def test_contact_purposes_do_not_substitute(rule03b_client) -> None:
    client, document_id = rule03b_client
    report = _report(
        client,
        document_id,
        _pre(
            visa_arrangements_needed=True,
            visa_timing_consulted_advisor=True,
            transcript_unavailable_reason="institution_closed",
            disaster_fee_consultation_needed=True,
        ),
        "purpose-specific",
    )
    statuses = _statuses(report)
    assert statuses["isct-master-visa-timing-consultation-apr"] == "confirmed"
    transcript = "isct-master-transcript-unavailable-institution_closed-apr"
    disaster = "isct-master-disaster-fee-consultation-apr"
    assert statuses[transcript] == statuses[disaster] == "needs_information"
    assert _missing(report, transcript) == {
        "preapplication_actions.transcript_unavailability_consulted_admissions"
    }
    assert _missing(report, disaster) == {
        "preapplication_actions.disaster_fee_consulted_admissions"
    }


def test_needed_visa_with_unknown_consultation_is_precise(rule03b_client) -> None:
    client, document_id = rule03b_client
    report = _report(
        client,
        document_id,
        _pre(visa_arrangements_needed=True),
        "visa-consultation-unknown",
    )
    rule_id = "isct-master-visa-timing-consultation-apr"
    assert _statuses(report)[rule_id] == "needs_information"
    assert _missing(report, rule_id) == {"preapplication_actions.visa_timing_consulted_advisor"}


@pytest.mark.parametrize("reason", ["retention_expired", "institution_closed", "disaster"])
def test_each_reviewed_transcript_reason_triggers_its_own_rule(rule03b_client, reason) -> None:
    client, document_id = rule03b_client
    report = _report(
        client,
        document_id,
        _pre(
            transcript_unavailable_reason=reason,
            transcript_unavailability_consulted_admissions=True,
        ),
        f"transcript-{reason}",
    )
    statuses = _statuses(report)
    assert statuses[f"isct-master-transcript-unavailable-{reason}-apr"] == "confirmed"
    for other in {"retention_expired", "institution_closed", "disaster"} - {reason}:
        assert statuses[f"isct-master-transcript-unavailable-{other}-apr"] == "not_applicable"


@pytest.mark.parametrize("scholarship", ["mext", "japan_korea_joint", "foreign_government"])
def test_scholarship_may_27_boundary_does_not_prove_exemption(rule03b_client, scholarship) -> None:
    client, document_id = rule03b_client
    report = _report(
        client,
        document_id,
        _pre(scholarship_status=scholarship, scholarship_copy_emailed_date="2026-05-27"),
        f"scholarship-{scholarship}",
    )
    deadline = f"isct-master-scholarship-copy-deadline-{scholarship}-apr"
    method = f"isct-master-scholarship-method-received-{scholarship}-apr"
    assert _statuses(report)[deadline] == "confirmed"
    assert _statuses(report)[method] == "needs_information"
    assert _missing(report, method) == {
        "preapplication_actions.scholarship_application_method_received"
    }
    note = next(
        item["annotation_note"]
        for item in report["source_plan"]["rules"]
        if item["rule_id"] == deadline
    )
    assert "期限内という原子条件だけ" in note


def test_scholarship_may_28_is_late_and_unknown_date_is_missing(rule03b_client) -> None:
    client, document_id = rule03b_client
    rule_id = "isct-master-scholarship-copy-deadline-mext-apr"
    late = _report(
        client,
        document_id,
        _pre(scholarship_status="mext", scholarship_copy_emailed_date="2026-05-28"),
        "scholarship-late",
    )
    assert _statuses(late)[rule_id] == "not_applicable"
    unknown = _report(client, document_id, _pre(scholarship_status="mext"), "scholarship-unknown")
    assert _statuses(unknown)[rule_id] == "needs_information"
    assert _missing(unknown, rule_id) == {"preapplication_actions.scholarship_copy_emailed_date"}


@pytest.mark.parametrize("scholarship", ["none", None])
def test_no_or_unknown_scholarship_never_confirms_special_procedure(
    rule03b_client, scholarship
) -> None:
    client, document_id = rule03b_client
    facts = {} if scholarship is None else {"scholarship_status": scholarship}
    report = _report(client, document_id, _pre(**facts), f"scholarship-safe-{scholarship}")
    statuses = _statuses(report)
    relevant = {
        rule_id: status
        for rule_id, status in statuses.items()
        if "scholarship-copy-deadline" in rule_id or "scholarship-method-received" in rule_id
    }
    assert relevant
    assert "confirmed" not in relevant.values()
    if scholarship == "none":
        assert set(relevant.values()) == {"not_applicable"}
    else:
        assert {status for rule_id, status in relevant.items() if rule_id.endswith("-apr")} == {
            "needs_information"
        }
        assert {status for rule_id, status in relevant.items() if rule_id.endswith("-sep")} == {
            "not_applicable"
        }


def test_conflicting_plural_scholarship_dates_are_rejected(rule03b_client) -> None:
    client, document_id = rule03b_client
    profile = _pre(scholarship_status="mext", scholarship_copy_emailed_date="2026-05-27")
    profile["preapplication_actions"]["scholarship_copy_emailed_dates"] = [
        "2026-05-27",
        "2026-05-28",
    ]
    intent = client.post(
        "/v1/query-intents/parse", json={"schema_version": "1.0", "query": "出願前の手続"}
    ).json()
    response = client.post(
        "/v1/applicant-reports",
        json={
            "schema_version": "1.0",
            "report_id": "conflicting-dates",
            "profile": profile,
            "intent": intent,
            "selection": {"document_ids": [document_id]},
        },
    )
    assert response.status_code == 422


def test_duplicate_facts_do_not_duplicate_actions(rule03b_client) -> None:
    client, document_id = rule03b_client
    report = _report(
        client,
        document_id,
        _pre(
            special_accommodation_needed=True,
            special_accommodation_contacted_admissions=True,
            disaster_fee_consultation_needed=True,
            disaster_fee_consulted_admissions=True,
        ),
        "deduplicated-actions",
    )
    fact_ids = [item["fact_id"] for item in report["evidence_bundle"]["evidence_records"]]
    assert fact_ids.count("fact:00010") == fact_ids.count("fact:00100") == 1
    assert "fact:00018" not in fact_ids and "fact:00102" not in fact_ids
