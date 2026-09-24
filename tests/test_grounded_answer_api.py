from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from jgrad_admission_rag.corpus import resolve_registered_corpus_kb_path
from jgrad_admission_rag.demo import prepare_demo
from jgrad_admission_rag.demo_embedding import (
    create_demo_embedding_provider,
    resolve_demo_embedding_configuration,
)
from jgrad_admission_rag.generation import (
    GenerationError,
    GenerationErrorCode,
    GenerationProviderIdentity,
    ReviewedStateGenerationProvider,
)
from jgrad_admission_rag.reasoning.reviewed_report_evidence import (
    ReviewedReportEvidenceBundle,
    ReviewedReportEvidenceCounts,
    ReviewedReportEvidenceRecord,
)
from jgrad_admission_rag.reasoning.reviewed_report_plan import load_reviewed_report_plan
from jgrad_admission_rag.schemas.document_kb import load_document_kb
from jgrad_admission_rag.schemas.corpus_manifest import load_corpus_manifest
from jgrad_admission_rag.service import ServiceDependencies, ServiceSettings, create_app
from tests.test_demo_cli import _synthetic_config


class _FailingGenerationProvider:
    identity = GenerationProviderIdentity(provider="test-failure", model="test", revision=None)

    def __init__(self, code: GenerationErrorCode) -> None:
        self.code = code

    def generate(self, _request):
        raise GenerationError(self.code)


def _grounded_client(tmp_path: Path) -> tuple[TestClient, object]:
    pdf, config, _ = _synthetic_config(tmp_path)
    runtime = prepare_demo(pdf, (tmp_path / "workspace").resolve(), config_dir=config)
    embedding = create_demo_embedding_provider(resolve_demo_embedding_configuration())
    settings = ServiceSettings(
        corpus_root=runtime.corpus_root,
        manifest_path=runtime.manifest_path,
        policy_path=runtime.policy_path,
        report_plan_paths=(runtime.report_plan_path,),
        page_scope_manifest_paths=(runtime.page_scope_manifest_path,),
        query_intent_catalog_path=runtime.query_intent_catalog_path,
        date_presentation_paths=(runtime.date_presentation_path,),
        source_pdf_path=runtime.source_pdf_path,
        source_pdf_document_id=runtime.identity.document_id,
        source_pdf_sha256=runtime.identity.source_pdf_sha256,
    )
    app = create_app(
        settings,
        ServiceDependencies(
            provider_factory=lambda: embedding,
            generation_provider_factory=ReviewedStateGenerationProvider,
        ),
    )
    return TestClient(app), runtime


def _target(catalog: dict) -> dict:
    school = catalog["schools"][0]
    degree = school["degrees"][0]
    intake = degree["intakes"][0]
    college = intake["colleges"][0]
    department = college["departments"][0]
    return {
        "school_id": school["school_id"],
        "document_id": intake["document_id"],
        "degree_id": degree["degree_id"],
        "intake": {"year": intake["year"], "month": intake["month"]},
        "college_id": college["college_id"],
        "department_id": department["department_id"],
        "application_route": None,
    }


def test_grounded_answer_runs_offline_retrieval_review_and_citation_closure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, runtime = _grounded_client(tmp_path)
    plan = load_reviewed_report_plan(runtime.report_plan_path)
    manifest = load_corpus_manifest(runtime.manifest_path)
    kb_path = resolve_registered_corpus_kb_path(runtime.corpus_root, manifest.entries[0].kb_path)
    fact = load_document_kb(kb_path).facts[0]
    bundle = ReviewedReportEvidenceBundle(
        plan_id=plan.plan_id,
        document_identity=plan.document_identity,
        source_kb_sha256=plan.source_kb_sha256,
        evidence_records=(
            ReviewedReportEvidenceRecord(
                document_id=plan.document_identity.document_id,
                fact_id=fact.fact_id,
                text=fact.text,
                source_pages=tuple(fact.source_pages),
                section_path=tuple(fact.section_path),
                fact_type=fact.fact_type,
                scope_type="department",
                scope_targets=("Synthetic Department",),
                parent_college="Synthetic College",
                rule_ids=(plan.rules[0].rule_id,),
            ),
        ),
        counts=ReviewedReportEvidenceCounts(record_count=1, rule_count=1, source_page_count=1),
    )
    monkeypatch.setattr(
        "jgrad_admission_rag.service.app.prepare_reviewed_report_evidence",
        lambda *_args, **_kwargs: bundle,
    )
    with client:
        target = _target(client.get("/v1/target-catalog").json())
        response = client.post(
            "/v1/grounded-answers",
            json={
                "question": "出願資格",
                "target": target,
                "applicant": {},
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    answer = body["answer"]
    assert answer["document_id"] == runtime.identity.document_id
    assert answer["provider"]["provider"] == "reviewed-state-offline"
    assert answer["provider"]["model"] == "grounded-reviewed-v1"
    assert answer["provider"]["revision"] == "1"
    assert answer["claims"]
    assert answer["citation_inventory"]
    evidence = {(item["document_id"], item["fact_id"]) for item in body["evidence"]}
    assert all(
        (citation["document_id"], citation["fact_id"]) in evidence
        for citation in answer["citation_inventory"]
    )
    assert body["local_pdf_url"] == f"/documents/{runtime.identity.document_id}/source.pdf"
    assert body["official_source_url"] == runtime.identity.official_source_url

    expected = {
        GenerationErrorCode.PROVIDER_TIMEOUT: (504, "generation_provider_timeout"),
        GenerationErrorCode.PROVIDER_REFUSAL: (502, "generation_provider_refusal"),
        GenerationErrorCode.MALFORMED_OUTPUT: (502, "malformed_output"),
        GenerationErrorCode.UNKNOWN_REFERENCE: (502, "invalid_citation"),
    }
    with client:
        target = _target(client.get("/v1/target-catalog").json())
        for code, status_and_code in expected.items():
            client.app.state.service_state.generation_provider = _FailingGenerationProvider(code)
            failure = client.post(
                "/v1/grounded-answers",
                json={"question": "出願資格", "target": target, "applicant": {}},
            )
            assert (failure.status_code, failure.json()["code"]) == status_and_code
            assert "出願資格" not in failure.text


def test_grounded_answer_is_strict_and_fails_closed_without_generation_provider(
    tmp_path: Path,
) -> None:
    client, _ = _grounded_client(tmp_path)
    with client:
        target = _target(client.get("/v1/target-catalog").json())
        extra = client.post(
            "/v1/grounded-answers",
            json={"question": "eligibility", "target": target, "applicant": {}, "extra": True},
        )
        client.app.state.service_state.generation_provider = None
        unavailable = client.post(
            "/v1/grounded-answers",
            json={"question": "eligibility", "target": target, "applicant": {}},
        )

    assert (extra.status_code, extra.json()["code"]) == (422, "invalid_request")
    assert (unavailable.status_code, unavailable.json()["code"]) == (
        503,
        "grounded_service_unavailable",
    )
    assert "eligibility" not in unavailable.text
