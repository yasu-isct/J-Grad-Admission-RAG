from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

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
from jgrad_admission_rag.generation.contracts import GenerationRequest
from jgrad_admission_rag.generation.question_analysis import (
    DeterministicQuestionUnderstandingProvider,
)
from jgrad_admission_rag.generation.grounded_rag import (
    MAX_GROUNDED_EVIDENCE_CHARACTERS,
    MAX_GROUNDED_EVIDENCE_RECORDS,
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
from jgrad_admission_rag.service.app import (
    GROUNDED_RETRIEVAL_CANDIDATE_K,
    GROUNDED_RETRIEVAL_TOP_K,
    _bounded_grounded_retrieval_depth,
    _obligations_for_reviewed_finding,
    _project_reviewed_answer_to_retrieval,
    _reviewed_exact_evidence_propositions,
)
from tests.test_demo_cli import _synthetic_config
from tests.test_grounded_rag import _cited_answer, _pack
from jgrad_admission_rag.reasoning.cited_answer import CitedAnswer, ReportStatus
from jgrad_admission_rag.reasoning.query_intent import (
    load_query_intent_catalog,
    parse_query_intent,
)


class _FailingGenerationProvider:
    identity = GenerationProviderIdentity(provider="test-failure", model="test", revision=None)

    def __init__(self, code: GenerationErrorCode) -> None:
        self.code = code

    def generate(self, _request):
        raise GenerationError(self.code)


class _RecordingGenerationProvider:
    def __init__(self) -> None:
        self.delegate = ReviewedStateGenerationProvider()
        self.identity = self.delegate.identity
        self.requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest):
        self.requests.append(request)
        return self.delegate.generate(request)


def _grounded_client(
    tmp_path: Path,
    generation_provider_factory=ReviewedStateGenerationProvider,
) -> tuple[TestClient, object]:
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
            generation_provider_factory=generation_provider_factory,
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
    recorder = _RecordingGenerationProvider()
    client, runtime = _grounded_client(tmp_path, lambda: recorder)
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
    assert len(recorder.requests) == 1
    provider_request = recorder.requests[0]
    assert len(provider_request.evidence) <= GROUNDED_RETRIEVAL_TOP_K
    assert len(provider_request.evidence) <= MAX_GROUNDED_EVIDENCE_RECORDS
    assert (
        sum(len(item.text) + len(item.scope_label or "") for item in provider_request.evidence)
        <= MAX_GROUNDED_EVIDENCE_CHARACTERS
    )

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


def test_grounded_retrieval_depth_is_bounded_independently_of_document_size() -> None:
    assert _bounded_grounded_retrieval_depth(391) == (
        GROUNDED_RETRIEVAL_TOP_K,
        GROUNDED_RETRIEVAL_CANDIDATE_K,
    )
    assert _bounded_grounded_retrieval_depth(2) == (2, 2)


def test_reviewed_answer_projection_is_bound_to_requested_intent_category() -> None:
    catalog = load_query_intent_catalog(
        Path(__file__).parents[1] / "src/jgrad_admission_rag/demo_config/query_intent_catalog.json"
    )
    payload = _cited_answer().model_dump(mode="json")
    payload["rule_findings"][0]["subject_key"] = "eligibility.reviewed.test-rule"
    answer = CitedAnswer.model_validate(payload)

    eligibility = parse_query_intent("出願資格を教えてください。", catalog)
    dates = parse_query_intent("出願期間はいつですか。", catalog)

    projected = _project_reviewed_answer_to_retrieval(_pack(), answer, eligibility)
    assert projected is not None
    assert tuple(item.subject_key for item in projected.rule_findings) == (
        "eligibility.reviewed.test-rule",
    )
    assert _project_reviewed_answer_to_retrieval(_pack(), answer, dates) is None


def test_generic_reviewed_finding_is_not_exposed_as_unvalidated_free_text() -> None:
    catalog = load_query_intent_catalog(
        Path(__file__).parents[1] / "src/jgrad_admission_rag/demo_config/query_intent_catalog.json"
    )
    payload = _cited_answer().model_dump(mode="json")
    payload["rule_findings"][0]["subject_key"] = "eligibility.reviewed.test-rule"
    answer = CitedAnswer.model_validate(payload)
    pack = _pack()
    projected = _project_reviewed_answer_to_retrieval(
        pack,
        answer,
        parse_query_intent("出願資格を教えてください。", catalog),
    )
    assert projected is not None
    records = pack.primary_evidence + pack.attached_reference_evidence
    evidence_id_by_fact = {
        record.fact_id: f"evidence:{index:04d}" for index, record in enumerate(records, start=1)
    }
    analysis = SimpleNamespace(
        subquestions=(
            SimpleNamespace(
                subquestion_id="subquestion:01",
                requested_intent="eligibility",
            ),
        )
    )

    propositions = _reviewed_exact_evidence_propositions(
        projected,
        analysis,
        records,
        evidence_id_by_fact,
        start_index=1,
        suppress_language=False,
    )

    assert propositions == ()


def test_language_finding_binds_only_matching_exam_subquestion() -> None:
    analysis = DeterministicQuestionUnderstandingProvider().analyze(
        "TOEFL iBT 和 TOEIC IP 可以吗？"
    )

    assert _obligations_for_reviewed_finding(
        analysis, "language.reviewed.external-toefl_ibt-apr"
    ) == ("subquestion:01",)
    assert _obligations_for_reviewed_finding(
        analysis, "language.reviewed.external-toeic_ip-apr"
    ) == ("subquestion:02",)
    assert _obligations_for_reviewed_finding(analysis, "language.reviewed.unspecified-apr") == ()


def test_reviewed_answer_projection_preserves_all_retained_rule_states() -> None:
    catalog = load_query_intent_catalog(
        Path(__file__).parents[1] / "src/jgrad_admission_rag/demo_config/query_intent_catalog.json"
    )
    base = _cited_answer().model_dump(mode="json")
    findings = []
    inventory = []
    statuses = (
        ("rule:confirmed", "confirmed", "active"),
        ("rule:not-applicable", "not_applicable", "not_applicable"),
        ("rule:pending", "needs_information", "pending"),
    )
    for rule_id, original_status, disposition in statuses:
        finding = copy.deepcopy(base["rule_findings"][0])
        finding.update(
            {
                "finding_id": f"finding:{rule_id}",
                "rule_id": rule_id,
                "subject_key": "eligibility.reviewed.shared-state",
                "original_status": original_status,
                "disposition": disposition,
                "source_applicability_step_id": f"applicability:{rule_id}",
                "source_resolution_step_id": f"resolution:{rule_id}",
            }
        )
        for citation in finding["citations"]:
            citation["source_rule_id"] = rule_id
            citation["source_step_ids"] = [
                f"applicability:{rule_id}",
                f"resolution:{rule_id}",
            ]
        findings.append(finding)
        inventory.extend(finding["citations"])
    base.update(
        {
            "report_status": ReportStatus.NEEDS_INFORMATION.value,
            "source_rule_ids": sorted(rule_id for rule_id, _, _ in statuses),
            "source_trace_step_ids": sorted(
                step
                for rule_id, _, _ in statuses
                for step in (f"applicability:{rule_id}", f"resolution:{rule_id}")
            ),
            "rule_findings": sorted(findings, key=lambda item: item["rule_id"]),
            "missing_information": [
                {
                    "rule_id": "rule:pending",
                    "field_path": "academic.expected_completion_date",
                    "source_applicability_step_id": "applicability:rule:pending",
                    "source_resolution_step_id": "resolution:rule:pending",
                }
            ],
            "citation_inventory": sorted(
                inventory,
                key=lambda item: (
                    item["document_id"],
                    item["fact_id"],
                    item["source_pages"],
                    item["role"],
                    item["source_rule_id"],
                    item["source_step_ids"],
                ),
            ),
        }
    )
    answer = CitedAnswer.model_validate(base)
    intent = parse_query_intent("出願資格を教えてください。", catalog)

    projected = _project_reviewed_answer_to_retrieval(_pack(), answer, intent)

    assert projected is not None
    assert projected.report_status is ReportStatus.NEEDS_INFORMATION
    assert tuple(item.original_status.value for item in projected.rule_findings) == (
        "confirmed",
        "not_applicable",
        "needs_information",
    )
    assert tuple(item.field_path for item in projected.missing_information) == (
        "academic.expected_completion_date",
    )
