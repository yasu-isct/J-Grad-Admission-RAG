from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jgrad_admission_rag.generation import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_DEFAULT_TIMEOUT_SECONDS,
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
from jgrad_admission_rag.generation.config import (
    GenerationRuntimeConfiguration,
    create_generation_providers,
)
from jgrad_admission_rag.generation.deepseek_schema import (
    DeepSeekSchemaProjectionError,
    DeepSeekSchemaProjectionErrorCode,
)
from jgrad_admission_rag.generation import deepseek_responses as deepseek_module
from jgrad_admission_rag.generation.simple_qa import (
    SimpleQaDraft,
    SimpleQaRequest,
    SimpleQaSource,
)
from jgrad_admission_rag.demo_cli import _parser as demo_parser
from jgrad_admission_rag.manual_deepseek_evaluation import (
    _CallBudgetExceeded,
    _LiveCallLedger,
    _ObservedResponses,
    _emit_report,
    _safe_structured_output_diagnostic,
    main as manual_deepseek_main,
)
from jgrad_admission_rag.manual_simple_qa_evaluation import main as manual_simple_qa_main


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
    default_config = DeepSeekResponsesConfig(model="deepseek-flash")
    assert default_config.model == "deepseek-flash"
    assert default_config.timeout_seconds == DEEPSEEK_DEFAULT_TIMEOUT_SECONDS
    assert default_config.max_output_tokens == 8_000
    assert DeepSeekResponsesConfig(model="deepseek-v4-pro").model == "deepseek-v4-pro"
    with pytest.raises(ValueError, match="DeepSeek model"):
        DeepSeekResponsesConfig(model="deepseek-chat")
    with pytest.raises(ValueError, match="generation-model"):
        GenerationRuntimeConfiguration(provider="deepseek-responses")
    with pytest.raises(ValueError, match="DeepSeek model"):
        GenerationRuntimeConfiguration(provider="deepseek-responses", model="gpt-5")
    deepseek_runtime = GenerationRuntimeConfiguration(
        provider="deepseek-responses", model="deepseek-flash"
    )
    assert deepseek_runtime.is_online
    assert deepseek_runtime.timeout_seconds == DEEPSEEK_DEFAULT_TIMEOUT_SECONDS
    assert deepseek_runtime.max_output_tokens == 8_000
    assert (
        GenerationRuntimeConfiguration(
            provider="openai-responses", model="gpt-test"
        ).timeout_seconds
        == 30.0
    )
    assert (
        GenerationRuntimeConfiguration(
            provider="deepseek-responses",
            model="deepseek-flash",
            timeout_seconds=45,
        ).timeout_seconds
        == 45
    )
    assert (
        GenerationRuntimeConfiguration(
            provider="openai-responses", model="gpt-test"
        ).max_output_tokens
        == 2_000
    )
    assert (
        GenerationRuntimeConfiguration(
            provider="deepseek-responses",
            model="deepseek-flash",
            max_output_tokens=512,
        ).max_output_tokens
        == 512
    )
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
        "timeout": DEEPSEEK_DEFAULT_TIMEOUT_SECONDS,
        "max_retries": 1,
    }


def test_deepseek_projection_error_context_is_detached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")

    def fail_projection(_: object) -> object:
        try:
            raise RuntimeError("PRIVATE-SCHEMA-CONTEXT")
        except RuntimeError:
            raise DeepSeekSchemaProjectionError(DeepSeekSchemaProjectionErrorCode.INVALID_SCHEMA)

    monkeypatch.setattr(deepseek_module, "build_deepseek_schema_projection", fail_projection)
    with pytest.raises(GenerationError) as caught:
        DeepSeekResponsesGenerationProvider(
            DeepSeekResponsesConfig(model="deepseek-flash"),
            _client_factory=lambda **_: FakeClient(FakeResponses()),
        )
    assert caught.value.code is GenerationErrorCode.PROVIDER_UNAVAILABLE
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "PRIVATE-SCHEMA-CONTEXT" not in str(caught.value)


def test_deepseek_unexpected_projector_error_is_detached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")

    def fail_projection(_: object) -> object:
        raise RuntimeError("PRIVATE-PROJECTOR-CONTEXT")

    monkeypatch.setattr(deepseek_module, "build_deepseek_schema_projection", fail_projection)
    with pytest.raises(GenerationError) as caught:
        DeepSeekResponsesGenerationProvider(
            DeepSeekResponsesConfig(model="deepseek-flash"),
            _client_factory=lambda **_: FakeClient(FakeResponses()),
        )
    assert caught.value.code is GenerationErrorCode.PROVIDER_UNAVAILABLE
    assert caught.value.args == ("generation provider is unavailable",)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "PRIVATE-PROJECTOR-CONTEXT" not in str(caught.value)


def test_deepseek_schema_hook_error_is_detached() -> None:
    class SensitiveSchema:
        @classmethod
        def model_json_schema(cls) -> dict[str, object]:
            raise RuntimeError("PRIVATE-SCHEMA-HOOK")

    with pytest.raises(GenerationError) as caught:
        deepseek_module._projection_for(SensitiveSchema)  # type: ignore[arg-type]
    assert caught.value.code is GenerationErrorCode.PROVIDER_UNAVAILABLE
    assert caught.value.args == ("generation provider is unavailable",)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "PRIVATE-SCHEMA-HOOK" not in str(caught.value)


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
    assert responses.kwargs["max_output_tokens"] == 8_000
    assert responses.kwargs["reasoning"] == {"effort": "none"}
    assert responses.kwargs["store"] is False
    assert "stream" not in responses.kwargs
    assert "tools" not in responses.kwargs
    text = responses.kwargs["text"]
    assert text["format"]["type"] == "json_schema"  # type: ignore[index]
    assert text["format"]["strict"] is True  # type: ignore[index]
    wire_schema = text["format"]["schema"]  # type: ignore[index]
    assert "$defs" not in wire_schema
    assert "maxLength" not in json.dumps(wire_schema)
    assert wire_schema != GenerationDraft.model_json_schema()
    sent = responses.kwargs["input"][1]["content"]  # type: ignore[index]
    system_prompt = responses.kwargs["input"][0]["content"]  # type: ignore[index]
    assert "every array field must be a JSON array, never null" in system_prompt
    assert "claim:0001, claim:0002" in system_prompt
    assert "exactly the claim text values joined" in system_prompt
    assert "refusal_reason=null" in system_prompt
    assert "evidence:0001" in sent
    assert "source_pdf" not in sent
    assert "reasoning_content" not in sent


def test_deepseek_simple_qa_uses_minimal_schema_and_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = SimpleQaDraft(answer="当前本地资料显示英语满分为100分。")
    responses = FakeResponses(
        SimpleNamespace(status="completed", output=(), output_text=draft.model_dump_json())
    )
    provider, _ = _provider(monkeypatch, responses)
    request = SimpleQaRequest(
        question="英语满分是多少？",
        target_label="情報工学系",
        sources=(
            SimpleQaSource(
                source_id="source:0001",
                text="英語は100点満点。",
                scope_label="情報工学系",
            ),
        ),
    )

    assert provider.answer_simple(request) == draft
    assert responses.calls == 1
    assert responses.kwargs["reasoning"] == {"effort": "none"}
    wire_schema = responses.kwargs["text"]["format"]["schema"]  # type: ignore[index]
    assert set(wire_schema["properties"]) == {"answer"}
    assert responses.kwargs["text"]["format"]["name"] == "simple_qa_answer"  # type: ignore[index]
    assert "英語は100点満点" in responses.kwargs["input"][1]["content"]  # type: ignore[index]


def test_deepseek_runtime_uses_local_question_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setattr(
        deepseek_module,
        "_create_client",
        lambda *_args, **_kwargs: FakeClient(FakeResponses()),
    )
    _, analyzer = create_generation_providers(
        GenerationRuntimeConfiguration(provider="deepseek-responses", model="deepseek-flash")
    )

    assert isinstance(analyzer, DeterministicQuestionUnderstandingProvider)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            SimpleNamespace(status="completed", output=(), output_text=""),
            GenerationErrorCode.MALFORMED_OUTPUT,
        ),
        (
            SimpleNamespace(status="completed", output=(), output_text="{"),
            GenerationErrorCode.MALFORMED_OUTPUT,
        ),
        (
            SimpleNamespace(status="incomplete", output=(), output_text="{}"),
            GenerationErrorCode.INCOMPLETE_RESPONSE,
        ),
        (
            SimpleNamespace(
                status="completed",
                output=(SimpleNamespace(content=(SimpleNamespace(type="refusal"),)),),
                output_text="",
            ),
            GenerationErrorCode.PROVIDER_REFUSAL,
        ),
        (
            SimpleNamespace(status="completed", output=(), output_text="{}"),
            GenerationErrorCode.MALFORMED_OUTPUT,
        ),
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
    provider, _ = _provider(monkeypatch, FakeResponses(error=timeout_type("private-profile-秘密")))
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
    assert "reasoning" not in responses.kwargs
    assert responses.kwargs["text"]["format"]["type"] == "json_schema"  # type: ignore[index]
    wire_schema = responses.kwargs["text"]["format"]["schema"]  # type: ignore[index]
    assert "$defs" not in wire_schema
    assert "minItems" not in json.dumps(wire_schema)
    assert wire_schema != expected.model_json_schema()


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
        manual_deepseek_main(["--model", "deepseek-flash", "--max-calls", "2", "--synthetic-only"])
    assert stopped.value.code == 2
    assert "exact one-run call authorization" in capsys.readouterr().err


def test_simple_qa_live_evaluation_refuses_before_provider_without_exact_guard(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-used")
    monkeypatch.delenv("JGRAD_ALLOW_DEEPSEEK_LIVE", raising=False)
    with pytest.raises(SystemExit) as stopped:
        manual_simple_qa_main(["--model", "deepseek-flash", "--synthetic-only"])
    assert stopped.value.code == 2
    assert "exact one-run call authorization" in capsys.readouterr().err


def test_live_ledger_counts_incomplete_call_and_allowlists_reason() -> None:
    response = SimpleNamespace(
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens", private="SECRET"),
    )
    ledger = _LiveCallLedger(model="deepseek-flash", max_calls=2)
    observed = _ObservedResponses(FakeResponses(response), ledger, "question-analysis")

    assert observed.create(model="deepseek-flash") is response
    assert ledger.calls == 1
    assert ledger.observations == [
        {
            "attempt": 1,
            "citation_validation": "not_applicable",
            "incomplete_reason": "max_output_tokens",
            "latency_ms": ledger.observations[0]["latency_ms"],
            "phase": "question-analysis",
            "response_status": "incomplete",
            "result_status": "response_received",
            "structured_output": "missing",
            "validation_errors": [],
        }
    ]
    assert "SECRET" not in json.dumps(ledger.observations)


def test_live_ledger_sanitizes_unknown_status_reason_and_transport_error() -> None:
    ledger = _LiveCallLedger(model="deepseek-flash", max_calls=3)
    unknown = _ObservedResponses(
        FakeResponses(
            SimpleNamespace(
                status="PRIVATE-STATUS",
                incomplete_details=SimpleNamespace(reason="PRIVATE-REASON"),
            )
        ),
        ledger,
        "question-analysis",
    )
    unknown.create()
    assert ledger.observations[0]["response_status"] == "other"
    assert ledger.observations[0]["incomplete_reason"] == "other"

    failed = _ObservedResponses(
        FakeResponses(error=RuntimeError("PRIVATE-TRANSPORT")),
        ledger,
        "citation-closure",
    )
    with pytest.raises(RuntimeError, match="PRIVATE-TRANSPORT"):
        failed.create()
    assert ledger.calls == 2
    assert ledger.observations[1]["result_status"] == "transport_error"
    assert "PRIVATE-TRANSPORT" not in json.dumps(ledger.observations)


def test_live_diagnostic_reports_only_safe_pydantic_error_shape() -> None:
    invalid = _draft().model_dump(mode="json")
    invalid["claims"] = None
    response = SimpleNamespace(output_text=json.dumps(invalid, ensure_ascii=False))

    diagnostic, errors = _safe_structured_output_diagnostic(response, "citation-closure")

    assert diagnostic == "pydantic_invalid"
    assert errors == ["claims.tuple_type"]
    assert "draft" not in json.dumps(errors)


def test_live_diagnostic_allowlists_generation_root_validator_category() -> None:
    invalid = _draft().model_dump(mode="json")
    invalid["answer"] = "not the ordered claim projection"
    response = SimpleNamespace(output_text=json.dumps(invalid, ensure_ascii=False))

    diagnostic, errors = _safe_structured_output_diagnostic(response, "citation-closure")

    assert diagnostic == "pydantic_invalid"
    assert errors == ["value_error_answer_projection"]
    assert "not the ordered claim projection" not in json.dumps(errors)


def test_live_diagnostic_distinguishes_json_missing_and_valid_output() -> None:
    assert _safe_structured_output_diagnostic(
        SimpleNamespace(output_text="{"), "citation-closure"
    ) == ("invalid_json", [])
    assert _safe_structured_output_diagnostic(
        SimpleNamespace(output_text=""), "citation-closure"
    ) == ("missing", [])
    assert _safe_structured_output_diagnostic(
        SimpleNamespace(output_text=_draft().model_dump_json()), "citation-closure"
    ) == ("pydantic_valid", [])


def test_live_diagnostic_does_not_emit_model_controlled_extra_field_name() -> None:
    invalid = _draft().model_dump(mode="json")
    invalid["private_payload_name"] = "SECRET"
    diagnostic, errors = _safe_structured_output_diagnostic(
        SimpleNamespace(output_text=json.dumps(invalid)), "citation-closure"
    )
    assert diagnostic == "pydantic_invalid"
    assert errors == ["field.extra_forbidden"]
    assert "private_payload_name" not in json.dumps(errors)


def test_live_ledger_enforces_call_budget_before_sdk_call() -> None:
    ledger = _LiveCallLedger(model="deepseek-flash", max_calls=1)
    responses = FakeResponses(SimpleNamespace(status="completed", incomplete_details=None))
    observed = _ObservedResponses(responses, ledger, "question-analysis")
    observed.create()
    with pytest.raises(_CallBudgetExceeded):
        observed.create()
    assert responses.calls == 1
    assert ledger.calls == 1


def test_live_report_contains_only_safe_bounded_observations(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = _LiveCallLedger(model="deepseek-flash", max_calls=2)
    index = ledger.begin("citation-closure")
    ledger.response_received(
        index,
        SimpleNamespace(
            status="incomplete",
            incomplete_details=SimpleNamespace(reason="content_filter", raw="PRIVATE-RAW"),
        ),
        12.3456,
    )
    ledger.fail("incomplete_response")
    _emit_report(ledger, error_code="incomplete_response", success=False)
    report = json.loads(capsys.readouterr().out)
    assert report["calls"] == 1
    assert report["max_calls"] == 2
    assert report["success"] is False
    assert report["observations"][0]["citation_validation"] == "failed"
    assert "PRIVATE-RAW" not in json.dumps(report)


def test_deepseek_live_evaluation_source_does_not_emit_raw_questions_or_responses() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "jgrad_admission_rag" / "manual_deepseek_evaluation.py"
    ).read_text(encoding="utf-8")
    assert '"question": question' not in source
    assert '"raw_response"' not in source
    assert '"calls": ledger.calls' in source
    assert '"latency_ms"' in source
    assert '"citation_validation"' in source
    assert '"incomplete_reason"' in source
