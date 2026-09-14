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
from tests.test_rule01a_real import _profile, _report, _statuses

pytestmark = pytest.mark.real_pdf
ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf"
IDENTITY = ROOT / "tests/fixtures/document_identity_isct_master_v1.json"
PLAN = ROOT / "tests/fixtures/reviewed_report_plan_isct_master_rule03a_v1.json"


@pytest.fixture(scope="module")
def rule03a_client(tmp_path_factory: pytest.TempPathFactory):
    if not PDF.is_file():
        pytest.skip("real PDF fixture unavailable")
    root = tmp_path_factory.mktemp("rule03a")
    kb = build_document_kb(PDF, load_document_identity(IDENTITY))
    kb_path = root / "documents/isct/document_kb.json"
    kb_path.parent.mkdir(parents=True)
    kb_path.write_bytes(canonical_document_kb_bytes(kb))
    build_local_index(kb_path, root / "indexes/isct", DeterministicFakeEmbeddingProvider(8))
    manifest = build_corpus_manifest(
        "rule03a-real",
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


def _submission_profile(*, arrival=None, dispatched=None, online=None, year=2027, month=4):
    profile = _profile(None, year=year, month=month)
    profile["application_submission"] = {
        "materials_arrival_date": arrival,
        "materials_dispatched_date": dispatched,
        "online_steps_completed": online,
    }
    return profile


def _missing(report: dict[str, Any], rule_id: str) -> set[str]:
    return {
        item["field_path"]
        for item in report["cited_answer"]["missing_information"]
        if item["rule_id"] == rule_id
    }


def test_real_application_facts_are_global_complete_and_on_page_9() -> None:
    if not PDF.is_file():
        pytest.skip("real PDF fixture unavailable")
    kb = build_document_kb(PDF, load_document_identity(IDENTITY))
    facts = {fact.fact_id: fact for fact in kb.facts}
    for fact_id in ("fact:00099", "fact:00100", "fact:00101", "fact:00102"):
        assert facts[fact_id].source_pages == [9]
        assert facts[fact_id].scope_type == "global"
        assert facts[fact_id].section_path[0] == "４．出願手続"
    assert len(facts) == 318
    assert "6月1日（月）午前9時" in facts["fact:00099"].text
    assert "出願書類一式が出願期間内に本学へ到着しない場合" in facts["fact:00100"].text


@pytest.mark.parametrize("year,month,suffix", [(2027, 4, "apr"), (2026, 9, "sep")])
def test_scenarios_1_2_and_7_show_one_official_schedule_without_progress(
    rule03a_client, year, month, suffix
) -> None:
    client, document_id = rule03a_client
    report = _report(
        client, document_id, _submission_profile(year=year, month=month), f"schedule-{suffix}"
    )
    statuses = _statuses(report)
    assert statuses[f"isct-master-application-window-{suffix}"] == "confirmed"
    arrival_rule = f"isct-master-materials-arrival-window-{suffix}"
    assert statuses[arrival_rule] == "needs_information"
    assert _missing(report, arrival_rule) == {"application_submission.materials_arrival_date"}
    text = report["cited_answer"]
    assert (
        sum(
            item["rule_id"] == f"isct-master-application-window-{suffix}"
            for item in text["rule_findings"]
        )
        == 1
    )


@pytest.mark.parametrize("arrival", ["2026-06-04", "2026-06-10"])
def test_scenario_3_arrival_boundaries_confirm_only_atomic_window(rule03a_client, arrival) -> None:
    client, document_id = rule03a_client
    report = _report(
        client, document_id, _submission_profile(arrival=arrival), f"arrival-{arrival}"
    )
    assert _statuses(report)["isct-master-materials-arrival-window-apr"] == "confirmed"
    assert "学校による受理" in report["limitation_statement"]


@pytest.mark.parametrize("arrival", ["2026-06-03", "2026-06-11"])
def test_scenario_4_outside_arrival_window_is_not_applicable(rule03a_client, arrival) -> None:
    client, document_id = rule03a_client
    report = _report(
        client, document_id, _submission_profile(arrival=arrival), f"outside-{arrival}"
    )
    assert _statuses(report)["isct-master-materials-arrival-window-apr"] == "not_applicable"


def test_scenario_5_dispatch_on_deadline_does_not_replace_arrival(rule03a_client) -> None:
    client, document_id = rule03a_client
    report = _report(client, document_id, _submission_profile(dispatched="2026-06-10"), "dispatch")
    rule_id = "isct-master-materials-arrival-window-apr"
    assert _statuses(report)[rule_id] == "needs_information"
    assert _missing(report, rule_id) == {"application_submission.materials_arrival_date"}
    assert "発送日は到着日として扱いません" in report["limitation_statement"]


@pytest.mark.parametrize("arrival", [None, "2026-06-11"])
def test_scenario_6_online_steps_never_mean_application_complete(rule03a_client, arrival) -> None:
    client, document_id = rule03a_client
    report = _report(
        client, document_id, _submission_profile(arrival=arrival, online=True), "online"
    )
    assert _statuses(report)["isct-master-online-steps-not-completion-apr"] == "confirmed"
    assert "出願完了ではありません" in str(report)


@pytest.mark.parametrize(
    "year,month,degree", [(2027, 5, "master"), (2028, 4, "master"), (2027, 4, "doctorate")]
)
def test_scenario_8_wrong_target_is_safely_not_applicable(
    rule03a_client, year, month, degree
) -> None:
    client, document_id = rule03a_client
    profile = _submission_profile(arrival="2026-06-10", year=year, month=month)
    profile["target_application"]["requested_degree_level"] = degree
    report = _report(client, document_id, profile, "wrong-target")
    assert all(
        status == "not_applicable"
        for rule, status in _statuses(report).items()
        if "application-window" in rule or "arrival-window" in rule
    )


def test_scenario_8_conflicting_arrival_shape_is_rejected(rule03a_client) -> None:
    client, document_id = rule03a_client
    profile = _submission_profile()
    profile["application_submission"]["materials_arrival_dates"] = ["2026-06-04", "2026-06-11"]
    response = client.post(
        "/v1/applicant-reports",
        json={
            "schema_version": "1.0",
            "report_id": "conflict",
            "profile": profile,
            "intent": {
                "schema_version": "1.0",
                "raw_query": "出願期間",
                "categories": ["application_dates"],
                "scope_targets": [],
                "parent_colleges": [],
                "requested_degree_levels": [],
                "intake_months": [],
                "intake_years": [],
                "mentions": [],
                "diagnostics": [],
            },
            "selection": {"document_ids": [document_id]},
        },
    )
    assert response.status_code == 422


def test_scenario_9_primary_evidence_is_page_9_without_duplicate_rule(rule03a_client) -> None:
    client, document_id = rule03a_client
    report = _report(client, document_id, _submission_profile(arrival="2026-06-10"), "evidence")
    finding = next(
        item
        for item in report["cited_answer"]["rule_findings"]
        if item["rule_id"] == "isct-master-materials-arrival-window-apr"
    )
    assert [item["fact_id"] for item in finding["citations"]] == ["fact:00100"]
    assert finding["citations"][0]["source_pages"] == [9]
