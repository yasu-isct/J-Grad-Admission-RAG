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
    AdaptiveQaPlanDraft,
    ClaimKind,
    DeepSeekResponsesConfig,
    DeepSeekResponsesGenerationProvider,
    DeterministicQuestionUnderstandingProvider,
    GenerationError,
    GenerationErrorCode,
    GeneratedClaim,
    GenerationDraft,
    GenerationProviderIdentity,
    OpenAIResponsesConfig,
    OpenAIResponsesGenerationProvider,
    ReviewedStateGenerationProvider,
)
from jgrad_admission_rag.generation.simple_qa import SimpleQaDraft
from jgrad_admission_rag.service import ServiceDependencies, ServiceSettings, create_app
from jgrad_admission_rag.service.runtime import ServiceState
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

    def __init__(self, *, needs_local_lookup: bool = True) -> None:
        self.calls = 0
        self.requests = []
        self.needs_local_lookup = needs_local_lookup

    def plan_adaptive(self, request):
        self.calls += 1
        self.requests.append(request)
        return AdaptiveQaPlanDraft(
            draft_answer="一般说明。",
            needs_local_lookup=self.needs_local_lookup,
            search_queries=("score conversion accepted tests",) if self.needs_local_lookup else (),
        )

    def answer_adaptive(self, request):
        self.calls += 1
        self.requests.append(request)
        if request.retrieval_status == "no_hits":
            return SimpleQaDraft(
                answer="一般说明。当前选择的本地募集要项没有确认相关学校规则，请查看官方原文。"
            )
        return SimpleQaDraft(
            answer=f"已根据 {len(request.sources)} 条本地记录回答：{request.question}"
        )

    def answer_simple(self, request):
        self.calls += 1
        self.requests.append(request)
        return SimpleQaDraft(
            answer=f"已根据 {len(request.sources)} 条本地记录回答：{request.question}"
        )

    def generate(self, request):
        self.calls += 1
        claims = []
        for index, finding in enumerate(request.rule_findings, start=1):
            fields = dict(
                item.split("=", 1) for item in finding.statement.split("; ") if "=" in item
            )
            predicate = fields["predicate"]
            if predicate == "exam_normalization":
                text = f"这里的“{fields['source']}”按{fields['canonical']}理解。"
            elif predicate == "unpublished_score_conversion":
                text = f"当前审核资料未公开{fields['exam']} {fields['score']} 分到最终英语配点的换算关系。"
            elif predicate == "no_reviewed_evidence":
                text = f"当前审核资料中未找到{fields['subject']}的要求或替代规则。"
            elif predicate == "missing_applicant_information":
                text = f"还需要补充{fields['subject']}信息，才能继续判断。"
            else:
                text = f"{fields['subject']}的英语满分为{fields['value']}分。"
            claims.append(
                GeneratedClaim(
                    claim_id=f"claim:{index:04d}",
                    kind=(
                        ClaimKind.REVIEWED_RULE
                        if finding.evidence_ids
                        else ClaimKind.REVIEWED_DISPOSITION
                    ),
                    text=text,
                    evidence_ids=finding.evidence_ids,
                    finding_ids=(finding.finding_id,),
                )
            )
        return GenerationDraft(
            answer="\n".join(item.text for item in claims),
            claims=tuple(claims),
            missing_information=tuple(
                sorted(
                    field for finding in request.rule_findings for field in finding.missing_fields
                )
            ),
            needs_review=any(not item.evidence_ids for item in request.rule_findings),
            refused=False,
        )


class _FailingSimpleGenerationProvider:
    identity = GenerationProviderIdentity(
        provider="fake-online",
        model="fake-natural-v1",
        revision="test",
    )

    def plan_adaptive(self, _request):
        raise GenerationError(GenerationErrorCode.MALFORMED_OUTPUT)


class _FailingFinalGenerationProvider(_CountingNaturalGenerationProvider):
    def answer_adaptive(self, request):
        self.calls += 1
        self.requests.append(request)
        raise GenerationError(GenerationErrorCode.PROVIDER_TIMEOUT)


class _LongDraftFailingFinalGenerationProvider(_FailingFinalGenerationProvider):
    def plan_adaptive(self, request):
        self.calls += 1
        self.requests.append(request)
        return AdaptiveQaPlanDraft(
            draft_answer="D" * 25_000,
            needs_local_lookup=True,
            search_queries=("school rule",),
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
            return DeepSeekResponsesGenerationProvider(
                deepseek_config,
                _client_factory=lambda **_: SimpleNamespace(responses=SimpleNamespace()),
            )

        def analysis_factory():
            return DeterministicQuestionUnderstandingProvider()

    elif online:
        openai_config = OpenAIResponsesConfig(model=model or "")

        def generation_factory():
            return OpenAIResponsesGenerationProvider(
                openai_config,
                _client_factory=lambda **_: SimpleNamespace(responses=SimpleNamespace()),
            )

        def analysis_factory():
            return DeterministicQuestionUnderstandingProvider()

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


@pytest.mark.real_pdf
def test_formal_question_uses_real_reviewed_rules_with_mock_retrieval(
    tmp_path, real_pdf_path, monkeypatch
) -> None:
    runtime = prepare_demo(real_pdf_path, (tmp_path / "real-workspace").resolve())
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
    client = TestClient(
        create_app(
            settings,
            ServiceDependencies(
                provider_factory=lambda: embedding,
                generation_provider_factory=ReviewedStateGenerationProvider,
                question_understanding_provider_factory=(
                    DeterministicQuestionUnderstandingProvider
                ),
            ),
        )
    )
    with client:
        catalog = client.get("/v1/target-catalog").json()
        school = catalog["schools"][0]
        degree = school["degrees"][0]
        intake = next(item for item in degree["intakes"] if item["year"] == 2027)
        college = next(item for item in intake["colleges"] if item["college_id"] == "情報理工学院")
        department = next(
            item for item in college["departments"] if item["department_id"] == "情報工学系"
        )
        route = department["application_routes"][0]
        target = {
            "school_id": school["school_id"],
            "document_id": intake["document_id"],
            "degree_id": degree["degree_id"],
            "intake": {"year": 2027, "month": 4},
            "college_id": college["college_id"],
            "department_id": department["department_id"],
            "application_route": route["route_id"],
        }
        request_target = service_app.DemoTargetRequest.model_validate(target)
        state = client.app.state.service_state
        plan, bundle, _ = service_app._load_demo_context(request_target, settings, state)
        allocation = next(
            item for item in plan.language_score_allocation.entries if item.target == "情報工学系"
        )
        selected = tuple(
            item
            for item in bundle.evidence_records
            if item.fact_id == allocation.evidence_binding.fact_id
        )
        assert len(selected) == 1
        monkeypatch.setattr(
            service_app,
            "_select_consolidated_evidence",
            lambda *_args, **_kwargs: selected,
        )
        monkeypatch.setattr(
            service_app,
            "_project_reviewed_answer_to_records",
            lambda *_args, **_kwargs: None,
        )
        response = client.post(
            "/v1/natural-language-answers",
            json={
                "question": "托业840按官方的标准是多少英语配点，还有没有jlpt成绩，j-test可以吗",
                "target": target,
                "applicant": {"english_test_kind": "toeic_lr", "english_score": 840},
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    answer = body["result"]["answer"]
    assert "100" in answer["answer"]
    assert answer["kind"] == "reference_answer"
    assert answer["assurance"] == "reference_only"
    assert "claims" not in answer
    assert "evidence" not in body["result"]
    assert answer["needs_review"] is True
    assert body["delivery"]["source"] == "offline"


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
    assert body["delivery"]["source"] == "offline"
    assert all(item["status"] in {"answered", "no_clear_evidence"} for item in body["subanswers"])


@pytest.mark.parametrize(
    "question",
    (
        "托业是什么意思？",
        "JLPT是什么？",
        "TOEFL Home Edition和普通TOEFL有什么区别？",
    ),
)
def test_general_questions_use_one_planning_call_without_local_retrieval(
    tmp_path, monkeypatch, question
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    client = _client(tmp_path, online=True)
    generator = _CountingNaturalGenerationProvider(needs_local_lookup=False)

    def unexpected_retrieval(*_args, **_kwargs):
        raise AssertionError("general question must not perform local retrieval")

    monkeypatch.setattr(service_app, "_retrieve_natural_answer_evidence", unexpected_retrieval)
    with client:
        client.app.state.service_state.generation_provider = generator
        target = _target(client.get("/v1/target-catalog").json())
        response = client.post(
            "/v1/natural-language-answers",
            json={"question": question, "target": target, "applicant": {}},
        )

    assert response.status_code == 200, response.text
    assert generator.calls == 1
    assert response.json()["delivery"]["source"] == "live"
    assert response.json()["result"]["answer"]["answer"] == "一般说明。"
    assert "未查询本地募集要项" in response.json()["summary"]


def test_school_rule_zero_hits_still_uses_final_call_and_marks_local_gap(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    client = _client(tmp_path, online=True)
    generator = _CountingNaturalGenerationProvider()
    monkeypatch.setattr(service_app, "_select_consolidated_evidence", lambda *_args: ())
    with client:
        client.app.state.service_state.generation_provider = generator
        target = _target(client.get("/v1/target-catalog").json())
        response = client.post(
            "/v1/natural-language-answers",
            json={"question": "这个专业接受一种全新的考试吗？", "target": target, "applicant": {}},
        )

    assert response.status_code == 200, response.text
    assert generator.calls == 2
    assert generator.requests[1].retrieval_status == "no_hits"
    assert generator.requests[1].sources == ()
    assert "没有确认" in response.json()["result"]["answer"]["answer"]
    assert response.json()["subanswers"][0]["status"] == "no_clear_evidence"


def test_adaptive_natural_answer_is_two_calls_then_exact_cache_hit(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    client = _client(tmp_path, online=True)
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
        cached_values_repr = repr(
            tuple(entry.value for entry in state.natural_answer_cache._entries.values())
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert changed.status_code == 200, changed.text
    assert changed_model.status_code == 200, changed_model.text
    assert analyzer.calls == 0
    assert generator.calls == 6, first.text
    assert all("777" not in item.model_dump_json() for item in generator.requests)
    assert all("fact:" not in item.model_dump_json() for item in generator.requests)
    for forbidden in ("synthetic-demo-2027", "source_pages", "pdf_sha256", "rule_ids"):
        assert all(forbidden not in item.model_dump_json() for item in generator.requests)
    assert not hasattr(generator.requests[0], "sources")
    assert len(generator.requests[1].sources) == 1
    first_body = first.json()
    second_body = second.json()
    assert first_body["delivery"]["source"] == "live"
    assert first_body["result"]["answer"]["kind"] == "reference_answer"
    assert first_body["result"]["answer"]["assurance"] == "reference_only"
    assert "claims" not in first_body["result"]["answer"]
    assert '"draft_answer"' not in first.text
    assert '"search_queries"' not in first.text
    assert first_body["result"]["answer"]["missing_information"] == ["exam_date"]
    assert second_body["delivery"]["source"] == "cache_hit"
    assert second_body["summary"] == first_body["summary"]
    assert "已校验依据" not in second_body["summary"]
    assert second_body["result"] == first_body["result"]
    assert changed_page_scope_key != original_key
    assert "777" not in cached_values_repr
    assert "Synthetic Department English maximum 100 points." not in cached_values_repr


def test_arbitrary_admission_question_reaches_model_planning_and_local_retrieval(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    client = _client(tmp_path, online=True)
    generator = _CountingNaturalGenerationProvider()
    captured_queries = []
    real_retrieval = service_app._retrieve_natural_answer_evidence

    def capture_retrieval(queries, *args, **kwargs):
        captured_queries.append(queries)
        return real_retrieval(queries, *args, **kwargs)

    monkeypatch.setattr(service_app, "_retrieve_natural_answer_evidence", capture_retrieval)
    with client:
        client.app.state.service_state.generation_provider = generator
        target = _target(client.get("/v1/target-catalog").json())
        response = client.post(
            "/v1/natural-language-answers",
            json={"question": "面试时需要准备哪些材料？", "target": target, "applicant": {}},
        )

    assert response.status_code == 200
    assert response.json()["analysis"]["requested_intents"] == ["general"]
    assert response.json()["analysis"]["subquestions"][0]["retrieval_query"] == (
        "面试时需要准备哪些材料？"
    )
    assert generator.calls == 2
    assert generator.requests[0].question == "面试时需要准备哪些材料？"
    assert captured_queries == [("score conversion accepted tests",)]
    assert generator.requests[1].retrieval_status in {"hits", "no_hits"}


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


def test_online_generation_failure_falls_back_to_local_retrieval(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    client = _client(tmp_path, online=True)
    with client:
        client.app.state.service_state.generation_provider = _FailingSimpleGenerationProvider()
        monkeypatch.setattr(
            service_app,
            "_select_consolidated_evidence",
            lambda *_args, **_kwargs: (
                SimpleNamespace(text="Synthetic local record.", section_path=("Synthetic",)),
            ),
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
        cache_entries = len(client.app.state.service_state.natural_answer_cache._entries)

    assert response.status_code == 200
    assert response.json()["delivery"]["source"] == "fallback"
    assert "在线自然语言整理暂时不可用" in response.json()["result"]["answer"]["answer"]
    assert cache_entries == 0


def test_final_generation_failure_keeps_draft_and_bounded_local_status(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    client = _client(tmp_path, online=True)
    generator = _FailingFinalGenerationProvider()
    with client:
        client.app.state.service_state.generation_provider = generator
        monkeypatch.setattr(
            service_app,
            "_select_consolidated_evidence",
            lambda *_args, **_kwargs: (
                SimpleNamespace(text="Synthetic local record.", section_path=("Synthetic",)),
            ),
        )
        target = _target(client.get("/v1/target-catalog").json())
        response = client.post(
            "/v1/natural-language-answers",
            json={"question": "学校规则是什么？", "target": target, "applicant": {}},
        )
        cache_entries = len(client.app.state.service_state.natural_answer_cache._entries)

    assert response.status_code == 200, response.text
    assert generator.calls == 2
    assert response.json()["delivery"]["source"] == "fallback"
    answer = response.json()["result"]["answer"]["answer"]
    assert "一般说明" in answer
    assert "Synthetic local record." in answer
    assert "最终整理未完成" in answer
    assert cache_entries == 0


def test_final_failure_with_maximum_draft_and_long_evidence_stays_within_public_contract(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    client = _client(tmp_path, online=True)
    generator = _LongDraftFailingFinalGenerationProvider()
    with client:
        client.app.state.service_state.generation_provider = generator
        monkeypatch.setattr(
            service_app,
            "_select_consolidated_evidence",
            lambda *_args, **_kwargs: (
                SimpleNamespace(text="E" * 20_000, section_path=("Synthetic",)),
                SimpleNamespace(text="F" * 20_000, section_path=("Synthetic",)),
                SimpleNamespace(text="G" * 20_000, section_path=("Synthetic",)),
            ),
        )
        target = _target(client.get("/v1/target-catalog").json())
        response = client.post(
            "/v1/natural-language-answers",
            json={"question": "学校规则是什么？", "target": target, "applicant": {}},
        )
        cache_entries = len(client.app.state.service_state.natural_answer_cache._entries)

    assert response.status_code == 200, response.text
    answer = response.json()["result"]["answer"]["answer"]
    assert len(answer) == 25_000
    assert "最终整理未完成" in answer
    assert "尚未由最终模型整合" in answer
    assert "D" in answer
    assert response.json()["delivery"]["source"] == "fallback"
    assert cache_entries == 0


def test_planning_failure_with_long_local_evidence_stays_within_public_contract(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    client = _client(tmp_path, online=True)
    with client:
        client.app.state.service_state.generation_provider = _FailingSimpleGenerationProvider()
        monkeypatch.setattr(
            service_app,
            "_select_consolidated_evidence",
            lambda *_args, **_kwargs: (
                SimpleNamespace(text="E" * 20_000, section_path=("Synthetic",)),
                SimpleNamespace(text="F" * 20_000, section_path=("Synthetic",)),
                SimpleNamespace(text="G" * 20_000, section_path=("Synthetic",)),
            ),
        )
        target = _target(client.get("/v1/target-catalog").json())
        response = client.post(
            "/v1/natural-language-answers",
            json={"question": "学校规则是什么？", "target": target, "applicant": {}},
        )
        cache_entries = len(client.app.state.service_state.natural_answer_cache._entries)

    assert response.status_code == 200, response.text
    answer = response.json()["result"]["answer"]["answer"]
    assert len(answer) == 25_000
    assert "在线自然语言整理暂时不可用" in answer
    assert "E" in answer
    assert response.json()["delivery"]["source"] == "fallback"
    assert cache_entries == 0


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


def test_simple_qa_does_not_invoke_reviewed_report_pipeline(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path)

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("simple QA must not invoke reviewed report preparation")

    monkeypatch.setattr(service_app, "_load_demo_context", must_not_run)
    monkeypatch.setattr(service_app, "build_applicant_report", must_not_run)
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

    assert response.status_code == 200
