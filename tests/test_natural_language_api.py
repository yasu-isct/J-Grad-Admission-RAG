from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import jgrad_admission_rag.service.app as service_app
from jgrad_admission_rag.demo import prepare_demo
from jgrad_admission_rag.demo_embedding import (
    create_demo_embedding_provider,
    resolve_demo_embedding_configuration,
)
from jgrad_admission_rag.generation import (
    DeepSeekResponsesConfig,
    DeepSeekResponsesGenerationProvider,
    DeepSeekResponsesQuestionUnderstandingProvider,
    DeterministicQuestionUnderstandingProvider,
    GenerationError,
    GenerationErrorCode,
    OpenAIResponsesConfig,
    OpenAIResponsesGenerationProvider,
    OpenAIResponsesQuestionUnderstandingProvider,
    ReviewedStateGenerationProvider,
)
from jgrad_admission_rag.service import ServiceDependencies, ServiceSettings, create_app
from jgrad_admission_rag.service.runtime import ServiceState
from tests.test_demo_cli import _synthetic_config
from tests.test_grounded_answer_api import _target


class _FailingQuestionUnderstandingProvider:
    def __init__(self, code: GenerationErrorCode) -> None:
        self.code = code

    def analyze(self, _question: str):
        raise GenerationError(self.code)


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
    assert all(
        item["result"] is None
        or all(
            claim["citations"]
            for claim in item["result"]["answer"]["claims"]
            if claim["kind"] != "applicant_statement"
        )
        for item in body["subanswers"]
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
        "request_timeout_seconds": 1635,
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
    assert status.request_timeout_seconds == 1635


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

    assert status.request_timeout_seconds == 420


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
