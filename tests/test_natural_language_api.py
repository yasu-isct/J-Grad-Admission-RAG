from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import jgrad_admission_rag.service.app as service_app
from jgrad_admission_rag.demo import prepare_demo
from jgrad_admission_rag.corpus import resolve_registered_corpus_kb_path
from jgrad_admission_rag.demo_embedding import (
    create_demo_embedding_provider,
    resolve_demo_embedding_configuration,
)
from jgrad_admission_rag.generation import (
    ClaimKind,
    DeepSeekResponsesConfig,
    DeepSeekResponsesGenerationProvider,
    DeepSeekResponsesQuestionUnderstandingProvider,
    DeterministicQuestionUnderstandingProvider,
    GenerationError,
    GenerationErrorCode,
    GeneratedClaim,
    GenerationDraft,
    GenerationProviderIdentity,
    OpenAIResponsesConfig,
    OpenAIResponsesGenerationProvider,
    OpenAIResponsesQuestionUnderstandingProvider,
    ReviewedStateGenerationProvider,
)
from jgrad_admission_rag.service import ServiceDependencies, ServiceSettings, create_app
from jgrad_admission_rag.service.runtime import ServiceState
from jgrad_admission_rag.reasoning.language_score_allocation import LanguageScoreAllocationStatus
from jgrad_admission_rag.reasoning.reviewed_report_evidence import (
    ReviewedReportEvidenceBundle,
    ReviewedReportEvidenceCounts,
    ReviewedReportEvidenceRecord,
)
from jgrad_admission_rag.schemas.corpus_manifest import load_corpus_manifest
from jgrad_admission_rag.schemas.document_kb import load_document_kb
from tests.test_demo_cli import _synthetic_config
from tests.test_grounded_answer_api import _target


class _FailingQuestionUnderstandingProvider:
    def __init__(self, code: GenerationErrorCode) -> None:
        self.code = code

    def analyze(self, _question: str):
        raise GenerationError(self.code)


class _CountingQuestionUnderstandingProvider:
    provider_name = "fake-online"
    model_name = "fake-analysis-v1"

    def __init__(self) -> None:
        self.calls = 0
        self._delegate = DeterministicQuestionUnderstandingProvider()

    def analyze(self, question: str):
        self.calls += 1
        return self._delegate.analyze(question)


class _CountingNaturalGenerationProvider:
    identity = GenerationProviderIdentity(
        provider="fake-online",
        model="fake-natural-v1",
        revision="test",
    )

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        finding = request.rule_findings[0]
        fields = dict(item.split("=", 1) for item in finding.statement.split("; ") if "=" in item)
        text = f"{fields['subject']}的英语满分为{fields['value']}分。"
        claim = GeneratedClaim(
            claim_id="claim:0001",
            kind=ClaimKind.REVIEWED_RULE,
            text=text,
            evidence_ids=finding.evidence_ids,
            finding_ids=(finding.finding_id,),
        )
        return GenerationDraft(
            answer=text,
            claims=(claim,),
            needs_review=False,
            refused=False,
        )


def _client(tmp_path, *, online: bool = False, deepseek: bool = False) -> TestClient:
    pdf, config, _ = _synthetic_config(tmp_path)
    runtime = prepare_demo(pdf, (tmp_path / "workspace").resolve(), config_dir=config)
    embedding = create_demo_embedding_provider(resolve_demo_embedding_configuration())
    model = "deepseek-flash" if deepseek else "test-model" if online else None
    provider_name = (
        "deepseek-responses"
        if deepseek
        else "openai-responses"
        if online
        else "reviewed-state-offline"
    )
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
        generation_provider_name=provider_name,
        generation_model_name=model,
    )
    if deepseek:
        deepseek_config = DeepSeekResponsesConfig(model=model or "")

        def generation_factory():
            return DeepSeekResponsesGenerationProvider(deepseek_config)

        def analysis_factory():
            return DeepSeekResponsesQuestionUnderstandingProvider(deepseek_config)

    elif online:
        openai_config = OpenAIResponsesConfig(model=model or "")

        def generation_factory():
            return OpenAIResponsesGenerationProvider(openai_config)

        def analysis_factory():
            return OpenAIResponsesQuestionUnderstandingProvider(openai_config)

    else:
        generation_factory = ReviewedStateGenerationProvider
        analysis_factory = DeterministicQuestionUnderstandingProvider
    return TestClient(
        create_app(
            settings,
            ServiceDependencies(
                provider_factory=lambda: embedding,
                generation_provider_factory=generation_factory,
                question_understanding_provider_factory=analysis_factory,
            ),
        )
    )


def test_complex_question_returns_partial_subanswers_instead_of_whole_rejection(tmp_path) -> None:
    client = _client(tmp_path)
    with client:
        target = _target(client.get("/v1/target-catalog").json())
        response = client.post(
            "/v1/natural-language-answers",
            json={
                "question": "托业是什么意思，j-test可以吗",
                "target": target,
                "applicant": {},
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"]["label"] == "离线规则结果"
    assert len(body["analysis"]["subquestions"]) == 2
    assert len(body["subanswers"]) == 2
    assert body["subanswers"][0]["status"] == "interpreted"
    assert any(item["status"] == "no_clear_evidence" for item in body["subanswers"])
    assert body["result"] is None
    assert all(item["claim_ids"] == [] for item in body["subanswers"])
    assert body["delivery"]["source"] == "offline"


def test_consolidated_natural_answer_is_one_generation_then_exact_cache_hit(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path)
    analyzer = _CountingQuestionUnderstandingProvider()
    generator = _CountingNaturalGenerationProvider()
    question = "托业840按官方的标准是多少英语配点，还有没有jlpt成绩，j-test可以吗"
    with client:
        state = client.app.state.service_state
        state.question_understanding_provider = analyzer
        state.generation_provider = generator
        settings = client.app.state.service_settings
        plan = state.report_plans[0]
        manifest = load_corpus_manifest(settings.manifest_path)
        kb_path = resolve_registered_corpus_kb_path(
            settings.corpus_root, manifest.entries[0].kb_path
        )
        fact = load_document_kb(kb_path).facts[0]
        bundle = ReviewedReportEvidenceBundle(
            plan_id=plan.plan_id,
            document_identity=plan.document_identity,
            source_kb_sha256=plan.source_kb_sha256,
            evidence_records=(
                ReviewedReportEvidenceRecord(
                    document_id=plan.document_identity.document_id,
                    fact_id=fact.fact_id,
                    text="Synthetic Department English maximum 100 points.",
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
        allocation = SimpleNamespace(
            status=LanguageScoreAllocationStatus.CONFIRMED,
            evidence=SimpleNamespace(fact_id=fact.fact_id),
            maximum_points=100,
        )
        monkeypatch.setattr(
            service_app,
            "_load_demo_context",
            lambda *_args, **_kwargs: (plan, bundle, None),
        )
        monkeypatch.setattr(
            service_app,
            "build_applicant_report",
            lambda *_args, **_kwargs: SimpleNamespace(language_score_allocation=allocation),
        )
        monkeypatch.setattr(
            service_app,
            "_select_consolidated_evidence",
            lambda *_args, **_kwargs: bundle.evidence_records,
        )
        target = _target(client.get("/v1/target-catalog").json())
        payload = {
            "question": question,
            "target": target,
            "applicant": {"english_test_kind": "toeic_lr", "english_score": 777},
        }
        parsed_request = service_app.GroundedAnswerRequest.model_validate(payload)
        local_analysis = DeterministicQuestionUnderstandingProvider().analyze(question)
        original_page_scopes = state.page_scope_manifests
        original_key = service_app._natural_answer_cache_key(
            parsed_request, settings, state, local_analysis
        )
        manifest = original_page_scopes[0]
        changed_entry = manifest.entries[0].model_copy(
            update={"review_note": f"{manifest.entries[0].review_note} revised"}
        )
        state.page_scope_manifests = (
            manifest.model_copy(update={"entries": (changed_entry, *manifest.entries[1:])}),
        )
        changed_page_scope_key = service_app._natural_answer_cache_key(
            parsed_request, settings, state, local_analysis
        )
        state.page_scope_manifests = original_page_scopes
        first = client.post("/v1/natural-language-answers", json=payload)
        second = client.post("/v1/natural-language-answers", json=payload)
        changed = client.post(
            "/v1/natural-language-answers",
            json={**payload, "question": question.replace("840", "800")},
        )
        generator.identity = generator.identity.model_copy(update={"revision": "test-v2"})
        changed_model = client.post("/v1/natural-language-answers", json=payload)
        monkeypatch.setattr(service_app, "CLAIM_SEMANTICS_VERSION", "typed-claim-semantics-v2")
        changed_validator = client.post("/v1/natural-language-answers", json=payload)
        cached_values_repr = repr(
            tuple(entry.value for entry in state.natural_answer_cache._entries.values())
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert changed.status_code == 200, changed.text
    assert changed_model.status_code == 200, changed_model.text
    assert changed_validator.status_code == 200, changed_validator.text
    assert analyzer.calls == 4
    assert generator.calls == 4, first.text
    first_body = first.json()
    second_body = second.json()
    parsed_first = service_app.NaturalLanguageAnswerResponse.model_validate(first_body)
    assert parsed_first.result is not None
    official_text = parsed_first.result.evidence[0].official_text
    exact_claim = parsed_first.result.answer.claims[0].model_copy(update={"text": official_text})
    exact_answer = parsed_first.result.answer.model_copy(
        update={"answer": official_text, "claims": (exact_claim,)}
    )
    exact_response = parsed_first.model_copy(
        update={"result": parsed_first.result.model_copy(update={"answer": exact_answer})}
    )
    exact_cache_core = service_app._project_natural_answer_for_cache(exact_response)
    assert first_body["result"]["answer"]["claims"][0]["text"].endswith("英语满分为100分。")
    assert second_body["delivery"]["source"] == "cache_hit"
    assert second_body["result"] == first_body["result"]
    assert "finding:" not in first.text
    assert "rule_id" not in first.text
    statuses = [item["status"] for item in first_body["subanswers"]]
    assert statuses == ["interpreted", "answered", "no_clear_evidence", "no_clear_evidence"]
    assert changed_page_scope_key != original_key
    assert question not in cached_values_repr
    assert "777" not in cached_values_repr
    assert "Synthetic Department English maximum 100 points." not in cached_values_repr
    assert official_text not in repr(exact_cache_core)
    assert exact_cache_core.claims[0].text is None
    assert exact_cache_core.claims[0].exact_text_citation_key is not None
    assert (
        service_app._restore_cached_claim_text(
            exact_cache_core.claims[0],
            {exact_cache_core.claims[0].exact_text_citation_key: "authoritative text reloaded"},
        )
        == "authoritative text reloaded"
    )


def test_missing_online_key_keeps_structured_service_ready_and_labels_nl_unconfigured(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = _client(tmp_path, online=True)
    with client:
        readiness = client.get("/v1/health/ready")
        status = client.get("/v1/generation-status")
        target = _target(client.get("/v1/target-catalog").json())
        response = client.post(
            "/v1/natural-language-answers",
            json={"question": "TOEIC可以吗？", "target": target, "applicant": {}},
        )

    assert readiness.json() == {"schema_version": "1.0", "status": "ready", "ready": True}
    assert status.json()["configured"] is False
    assert status.json()["label"] == "在线生成服务未配置"
    assert response.status_code == 503
    assert response.json()["code"] == "online_generation_not_configured"


def test_missing_deepseek_key_keeps_readiness_and_identifies_provider(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    client = _client(tmp_path, deepseek=True)
    with client:
        readiness = client.get("/v1/health/ready")
        status = client.get("/v1/generation-status")
        target = _target(client.get("/v1/target-catalog").json())
        response = client.post(
            "/v1/natural-language-answers",
            json={"question": "TOEIC可以吗？", "target": target, "applicant": {}},
        )

    assert readiness.json() == {"schema_version": "1.0", "status": "ready", "ready": True}
    assert status.json() == {
        "schema_version": "1.0",
        "provider": "deepseek-responses",
        "model": "deepseek-flash",
        "mode": "online_model",
        "configured": False,
        "label": "DeepSeek 在线生成服务未配置",
        "request_timeout_seconds": 375,
    }
    assert response.status_code == 503
    assert response.json()["code"] == "online_generation_not_configured"


@pytest.mark.parametrize(
    ("provider_code", "expected_status", "expected_code"),
    (
        (GenerationErrorCode.PROVIDER_UNAVAILABLE, 503, "generation_provider_unavailable"),
        (GenerationErrorCode.PROVIDER_TIMEOUT, 504, "generation_provider_timeout"),
        (GenerationErrorCode.PROVIDER_REFUSAL, 502, "generation_provider_refusal"),
        (GenerationErrorCode.INCOMPLETE_RESPONSE, 502, "incomplete_response"),
        (GenerationErrorCode.MALFORMED_OUTPUT, 502, "malformed_output"),
    ),
)
def test_question_analysis_failures_have_distinct_safe_error_codes(
    tmp_path, provider_code, expected_status, expected_code
) -> None:
    client = _client(tmp_path)
    with client:
        client.app.state.service_state.question_understanding_provider = (
            _FailingQuestionUnderstandingProvider(provider_code)
        )
        target = _target(client.get("/v1/target-catalog").json())
        response = client.post(
            "/v1/natural-language-answers",
            json={
                "question": "private question marker",
                "target": target,
                "applicant": {"english_test_kind": "toeic_lr", "english_score": 840},
            },
        )

    assert (response.status_code, response.json()["code"]) == (
        expected_status,
        expected_code,
    )
    assert "private question marker" not in response.text
    assert "840" not in response.text


def test_configured_deepseek_status_shows_actual_model_name() -> None:
    settings = ServiceSettings(
        generation_provider_name="deepseek-responses",
        generation_model_name="deepseek-v4-pro",
    )
    state = ServiceState(
        provider=object(),
        generation_provider=object(),
        question_understanding_provider=object(),
        report_plans=(object(),),
        page_scope_manifests=(object(),),
        query_intent_catalog=object(),
    )
    status = service_app._generation_status_response(settings, state)
    assert status.configured is True
    assert status.model == "deepseek-v4-pro"
    assert status.label == "DeepSeek 在线模型 · deepseek-v4-pro"
    assert status.request_timeout_seconds == 375


def test_generation_request_timeout_budget_tracks_provider_configuration() -> None:
    settings = ServiceSettings(
        generation_provider_name="deepseek-responses",
        generation_model_name="deepseek-flash",
        generation_timeout_seconds=45,
        generation_max_retries=0,
    )
    state = ServiceState(
        provider=object(),
        generation_provider=object(),
        question_understanding_provider=object(),
        report_plans=(object(),),
        page_scope_manifests=(object(),),
        query_intent_catalog=object(),
    )

    status = service_app._generation_status_response(settings, state)

    assert status.request_timeout_seconds == 105


def test_reviewed_evidence_conflict_is_not_downgraded_to_missing_coverage(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path)

    def fail_closed(*_args, **_kwargs):
        raise service_app.ApiProblem(
            409,
            "report_preparation_failed",
            "reviewed report preparation failed",
        )

    monkeypatch.setattr(service_app, "_build_grounded_answer_response", fail_closed)
    with client:
        target = _target(client.get("/v1/target-catalog").json())
        response = client.post(
            "/v1/natural-language-answers",
            json={
                "question": "TOEFL Home Edition可以吗？",
                "target": target,
                "applicant": {},
            },
        )

    assert response.status_code == 409
    assert response.json()["code"] == "report_preparation_failed"
