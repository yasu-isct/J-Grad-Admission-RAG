from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jgrad_admission_rag.generation import (
    DEEPSEEK_BASE_URL,
    ApplicantFact,
    ClaimKind,
    DeepSeekResponsesConfig,
    DeepSeekResponsesGenerationProvider,
    DeepSeekResponsesQuestionUnderstandingProvider,
    DetectedLanguage,
    DeterministicQuestionUnderstandingProvider,
    EvidenceRole,
    GeneratedClaim,
    GenerationDraft,
    GenerationError,
    GenerationErrorCode,
    GenerationEvidence,
    GenerationRequest,
    GenerationTarget,
    QuestionCorrection,
    generate_checked,
)
from jgrad_admission_rag.generation.config import GenerationRuntimeConfiguration
from jgrad_admission_rag.demo_cli import _parser as demo_parser
from jgrad_admission_rag.manual_deepseek_evaluation import main as manual_deepseek_main


FORMAL_QUESTION = "托业840按官方的标准是多少英语配点，还有没有jlpt成绩,j-test可以吗"


class FakeResponses:
    def __init__(self, response: object | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.kwargs: dict[str, object] = {}
        self.calls = 0

    def create(self, **kwargs: object) -> object:
        self.calls += 1
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def _request() -> GenerationRequest:
    return GenerationRequest(
        request_id="request:deepseek-test",
        question="TOEIC 840は何点ですか。",
        target=GenerationTarget(application_label="情報工学系 修士課程"),
        applicant_facts=(ApplicantFact(field_path="language.toeic.score", value="840"),),
        evidence=(
            GenerationEvidence(
                evidence_id="evidence:0001",
                role=EvidenceRole.PRIMARY,
                text="英語の満点は100点である。",
            ),
        ),
    )


def _draft(*, evidence_id: str = "evidence:0001") -> GenerationDraft:
    return GenerationDraft(
        answer="draft",
        claims=(
            GeneratedClaim(
                claim_id="claim:0001",
                kind=ClaimKind.OFFICIAL_FACT,
                text="draft",
                evidence_ids=(evidence_id,),
            ),
        ),
        needs_review=False,
        refused=False,
    )


def _provider(
    monkeypatch: pytest.MonkeyPatch,
    responses: FakeResponses,
    *,
    model: str = "deepseek-flash",
) -> tuple[DeepSeekResponsesGenerationProvider, dict[str, object]]:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> FakeClient:
        captured.update(kwargs)
        return FakeClient(responses)

    provider = DeepSeekResponsesGenerationProvider(
        DeepSeekResponsesConfig(model=model), _client_factory=factory
    )
    return provider, captured


def test_deepseek_configuration_is_closed_and_models_are_allowlisted() -> None:
    assert DeepSeekResponsesConfig(model="deepseek-flash").model == "deepseek-flash"
    assert DeepSeekResponsesConfig(model="deepseek-v4-pro").model == "deepseek-v4-pro"
    with pytest.raises(ValueError, match="DeepSeek model"):
        DeepSeekResponsesConfig(model="deepseek-chat")
    with pytest.raises(ValueError, match="generation-model"):
        GenerationRuntimeConfiguration(provider="deepseek-responses")
    with pytest.raises(ValueError, match="DeepSeek model"):
        GenerationRuntimeConfiguration(provider="deepseek-responses", model="gpt-5")
    assert GenerationRuntimeConfiguration(
        provider="deepseek-responses", model="deepseek-flash"
    ).is_online
    parser = demo_parser()
    parsed = parser.parse_args(
        [
            "--pdf",
            "D:/synthetic.pdf",
            "--generation-provider",
            "deepseek-responses",
            "--generation-model",
            "deepseek-flash",
        ]
    )
    assert parsed.generation_provider == "deepseek-responses"
    assert parsed.generation_model == "deepseek-flash"
    assert "base_url" not in {action.dest for action in parser._actions}


def test_deepseek_uses_only_its_key_and_fixed_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-reused")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://attacker.invalid")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://attacker.invalid")
    with pytest.raises(GenerationError) as caught:
        DeepSeekResponsesGenerationProvider(
            DeepSeekResponsesConfig(model="deepseek-flash"),
            _client_factory=lambda **_: None,
        )
    assert caught.value.code is GenerationErrorCode.MISSING_API_KEY

    responses = FakeResponses(
        SimpleNamespace(status="completed", output=(), output_text=_draft().model_dump_json())
    )
    provider, client_args = _provider(monkeypatch, responses)
    assert provider.identity.provider == "deepseek-responses"
    assert client_args == {
        "api_key": "deepseek-test-key",
        "base_url": DEEPSEEK_BASE_URL,
        "timeout": 30.0,
        "max_retries": 1,
    }


def test_deepseek_generation_uses_non_streaming_json_schema_and_bounded_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = FakeResponses(
        SimpleNamespace(status="completed", output=(), output_text=_draft().model_dump_json())
    )
    provider, _ = _provider(monkeypatch, responses)
    assert provider.generate(_request()) == _draft()

    assert responses.calls == 1
    assert responses.kwargs["model"] == "deepseek-flash"
    assert responses.kwargs["max_output_tokens"] == 2_000
    assert responses.kwargs["store"] is False
    assert "stream" not in responses.kwargs
    assert "tools" not in responses.kwargs
    text = responses.kwargs["text"]
    assert text["format"]["type"] == "json_schema"  # type: ignore[index]
    assert text["format"]["strict"] is True  # type: ignore[index]
    sent = responses.kwargs["input"][1]["content"]  # type: ignore[index]
    assert "evidence:0001" in sent
    assert "source_pdf" not in sent
    assert "reasoning_content" not in sent


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (SimpleNamespace(status="completed", output=(), output_text=""), GenerationErrorCode.MALFORMED_OUTPUT),
        (SimpleNamespace(status="completed", output=(), output_text="{"), GenerationErrorCode.MALFORMED_OUTPUT),
        (SimpleNamespace(status="incomplete", output=(), output_text="{}"), GenerationErrorCode.INCOMPLETE_RESPONSE),
        (
            SimpleNamespace(
                status="completed",
                output=(SimpleNamespace(content=(SimpleNamespace(type="refusal"),)),),
                output_text="",
            ),
            GenerationErrorCode.PROVIDER_REFUSAL,
        ),
        (SimpleNamespace(status="completed", output=(), output_text="{}"), GenerationErrorCode.MALFORMED_OUTPUT),
    ],
)
def test_deepseek_generation_fails_closed(
    monkeypatch: pytest.MonkeyPatch, response: object, expected: GenerationErrorCode
) -> None:
    provider, _ = _provider(monkeypatch, FakeResponses(response))
    with pytest.raises(GenerationError) as caught:
        provider.generate(_request())
    assert caught.value.code is expected


def test_deepseek_timeout_does_not_retain_sensitive_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeout_type = type("APITimeoutError", (Exception,), {})
    provider, _ = _provider(
        monkeypatch, FakeResponses(error=timeout_type("private-profile-秘密"))
    )
    with pytest.raises(GenerationError) as caught:
        provider.generate(_request())
    assert caught.value.code is GenerationErrorCode.PROVIDER_TIMEOUT
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "秘密" not in str(caught.value)


def test_deepseek_response_inspection_does_not_retain_sensitive_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "PRIVATE-RAW-RESPONSE"

    class SensitiveResponse:
        status = "completed"
        output = ()

        @property
        def output_text(self) -> str:
            raise RuntimeError(secret)

    provider, _ = _provider(monkeypatch, FakeResponses(SensitiveResponse()))
    with pytest.raises(GenerationError) as caught:
        provider.generate(_request())
    assert caught.value.code is GenerationErrorCode.MALFORMED_OUTPUT
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in str(caught.value)


def test_deepseek_unknown_reference_is_rejected_by_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = FakeResponses(
        SimpleNamespace(
            status="completed",
            output=(),
            output_text=_draft(evidence_id="evidence:9999").model_dump_json(),
        )
    )
    provider, _ = _provider(monkeypatch, responses)
    with pytest.raises(GenerationError) as caught:
        generate_checked(provider, _request())
    assert caught.value.code is GenerationErrorCode.UNKNOWN_REFERENCE


@pytest.mark.parametrize(
    ("question", "language"),
    [
        (FORMAL_QUESTION, DetectedLanguage.CHINESE),
        ("JLPT N1 はひつようですか。", DetectedLanguage.JAPANESE),
        ("托业840は何点、J.TEST可以吗？", DetectedLanguage.MIXED),
    ],
)
def test_deepseek_question_analysis_preserves_multilingual_server_constraints(
    monkeypatch: pytest.MonkeyPatch, question: str, language: DetectedLanguage
) -> None:
    expected = DeterministicQuestionUnderstandingProvider().analyze(question)
    responses = FakeResponses(
        SimpleNamespace(status="completed", output=(), output_text=expected.model_dump_json())
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    provider = DeepSeekResponsesQuestionUnderstandingProvider(
        DeepSeekResponsesConfig(model="deepseek-flash"),
        _client_factory=lambda **_: FakeClient(responses),
    )
    assert provider.analyze(question) == expected
    assert expected.detected_language is language
    assert responses.kwargs["text"]["format"]["type"] == "json_schema"  # type: ignore[index]


def test_deepseek_question_analysis_accepts_one_typo_but_rejects_topic_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    typo_question = "toiec 840可以吗？"
    corrected = DeterministicQuestionUnderstandingProvider().analyze("TOEIC L&R 840可以吗？")
    corrected = corrected.model_copy(
        update={"corrections": (QuestionCorrection(original="toiec", normalized="TOEIC L&R"),)}
    )
    typo_responses = FakeResponses(
        SimpleNamespace(status="completed", output=(), output_text=corrected.model_dump_json())
    )
    typo_provider = DeepSeekResponsesQuestionUnderstandingProvider(
        DeepSeekResponsesConfig(model="deepseek-flash"),
        _client_factory=lambda **_: FakeClient(typo_responses),
    )
    assert typo_provider.analyze(typo_question) == corrected

    redirected = corrected.model_copy(
        update={"corrections": (QuestionCorrection(original="topic", normalized="TOEIC L&R"),)}
    )
    redirect_responses = FakeResponses(
        SimpleNamespace(status="completed", output=(), output_text=redirected.model_dump_json())
    )
    redirect_provider = DeepSeekResponsesQuestionUnderstandingProvider(
        DeepSeekResponsesConfig(model="deepseek-flash"),
        _client_factory=lambda **_: FakeClient(redirect_responses),
    )
    with pytest.raises(GenerationError) as caught:
        redirect_provider.analyze("topic 840可以吗？")
    assert caught.value.code is GenerationErrorCode.MALFORMED_OUTPUT


def test_deepseek_does_not_persist_reasoning_output(monkeypatch: pytest.MonkeyPatch) -> None:
    response = SimpleNamespace(
        status="completed",
        output=(SimpleNamespace(type="reasoning", reasoning_content="hidden"),),
        output_text=json.dumps(_draft().model_dump(mode="json"), ensure_ascii=False),
    )
    provider, _ = _provider(monkeypatch, FakeResponses(response))
    assert provider.generate(_request()) == _draft()
    assert not hasattr(provider, "response")
    assert not hasattr(provider, "reasoning_content")


def test_deepseek_live_evaluation_refuses_before_provider_without_exact_guard(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-used")
    monkeypatch.delenv("JGRAD_ALLOW_DEEPSEEK_LIVE", raising=False)
    with pytest.raises(SystemExit) as stopped:
        manual_deepseek_main(
            ["--model", "deepseek-flash", "--max-calls", "2", "--synthetic-only"]
        )
    assert stopped.value.code == 2
    assert "exact one-run call authorization" in capsys.readouterr().err


def test_deepseek_live_evaluation_source_does_not_emit_raw_questions_or_responses() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "jgrad_admission_rag"
        / "manual_deepseek_evaluation.py"
    ).read_text(encoding="utf-8")
    assert '"question": question' not in source
    assert '"raw_response"' not in source
    assert '"calls": len(observations)' in source
    assert '"latency_ms"' in source
    assert '"citation_validation"' in source
