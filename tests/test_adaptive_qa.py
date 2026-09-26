from __future__ import annotations

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.generation.adaptive_qa import (
    ADAPTIVE_QA_PLANNING_PROMPT_VERSION,
    ADAPTIVE_QA_PLANNING_SYSTEM_PROMPT,
    MAX_ADAPTIVE_SEARCH_QUERIES,
    AdaptiveQaFinalRequest,
    AdaptiveQaPlanDraft,
    AdaptiveQaPlanningRequest,
    answer_adaptive_checked,
    plan_adaptive_checked,
)
from jgrad_admission_rag.generation.contracts import GenerationProviderIdentity
from jgrad_admission_rag.generation.provider import GenerationError, GenerationErrorCode
from jgrad_admission_rag.generation.simple_qa import SimpleQaDraft, SimpleQaSource


class _Provider:
    identity = GenerationProviderIdentity(
        provider="fake-online",
        model="adaptive-test",
        revision="test",
    )

    def __init__(self, plan: object, answer: object | None = None) -> None:
        self.plan = plan
        self.answer = answer or SimpleQaDraft(answer="final")
        self.plan_calls = 0
        self.answer_calls = 0

    def plan_adaptive(self, _request):
        self.plan_calls += 1
        return self.plan

    def answer_adaptive(self, _request):
        self.answer_calls += 1
        return self.answer


def _planning_request() -> AdaptiveQaPlanningRequest:
    return AdaptiveQaPlanningRequest(question="学校の締切は？", target_label="Synthetic target")


def test_general_plan_requires_empty_queries_and_one_checked_call() -> None:
    provider = _Provider(
        AdaptiveQaPlanDraft(
            draft_answer="TOEIC is an English test.",
            needs_local_lookup=False,
            search_queries=(),
        )
    )

    result = plan_adaptive_checked(provider, _planning_request())

    assert result.needs_local_lookup is False
    assert result.search_queries == ()
    assert provider.plan_calls == 1


def test_planning_prompt_routes_pure_definitions_without_target_lookup() -> None:
    assert ADAPTIVE_QA_PLANNING_PROMPT_VERSION == "adaptive-qa-planning-v2"
    assert "presence of a selected target label" in ADAPTIVE_QA_PLANNING_SYSTEM_PROMPT
    assert '"What is [an exam or acronym]?"' in ADAPTIVE_QA_PLANNING_SYSTEM_PROMPT
    assert "MUST use needs_local_lookup=false" in ADAPTIVE_QA_PLANNING_SYSTEM_PROMPT


def test_school_plan_accepts_multiple_bounded_queries_without_wording_rules() -> None:
    queries = ("TOEIC score conversion", "JLPT requirement", "application fee")
    provider = _Provider(
        AdaptiveQaPlanDraft(
            draft_answer="These points depend on the selected programme.",
            needs_local_lookup=True,
            search_queries=queries,
        )
    )

    result = plan_adaptive_checked(provider, _planning_request())

    assert result.search_queries == queries


@pytest.mark.parametrize(
    "payload",
    (
        {"draft_answer": "x", "needs_local_lookup": False, "search_queries": ["query"]},
        {"draft_answer": "x", "needs_local_lookup": True, "search_queries": []},
        {
            "draft_answer": "x",
            "needs_local_lookup": True,
            "search_queries": [
                f"query-{index}" for index in range(MAX_ADAPTIVE_SEARCH_QUERIES + 1)
            ],
        },
        {
            "draft_answer": "x",
            "needs_local_lookup": True,
            "search_queries": [
                " duplicate",
            ],
        },
    ),
)
def test_plan_structure_rejects_inconsistent_or_unbounded_queries(payload) -> None:
    with pytest.raises(ValidationError):
        AdaptiveQaPlanDraft.model_validate(payload)


def test_checked_planning_rejects_malformed_provider_output_without_context() -> None:
    provider = _Provider({"draft_answer": "PRIVATE", "needs_local_lookup": False})

    with pytest.raises(GenerationError) as caught:
        plan_adaptive_checked(provider, _planning_request())

    assert caught.value.code is GenerationErrorCode.MALFORMED_OUTPUT
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "PRIVATE" not in str(caught.value)


def test_final_request_allows_explicit_zero_hit_and_minimal_answer() -> None:
    provider = _Provider(
        AdaptiveQaPlanDraft(draft_answer="draft", needs_local_lookup=False, search_queries=()),
        SimpleQaDraft(answer="The local material did not confirm the school-specific point."),
    )
    request = AdaptiveQaFinalRequest(
        question="Is this accepted?",
        target_label="Synthetic target",
        draft_answer="General context.",
        retrieval_status="no_hits",
        sources=(),
    )

    result = answer_adaptive_checked(provider, request)

    assert "did not confirm" in result.answer
    assert provider.answer_calls == 1


def test_final_request_requires_hit_status_to_match_sources() -> None:
    source = SimpleQaSource(source_id="source:0001", text="record")
    with pytest.raises(ValidationError):
        AdaptiveQaFinalRequest(
            question="question",
            target_label="target",
            draft_answer="draft",
            retrieval_status="no_hits",
            sources=(source,),
        )
    with pytest.raises(ValidationError):
        AdaptiveQaFinalRequest(
            question="question",
            target_label="target",
            draft_answer="draft",
            retrieval_status="hits",
            sources=(),
        )
