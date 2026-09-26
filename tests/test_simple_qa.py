from __future__ import annotations

import pytest

from jgrad_admission_rag.generation import (
    GenerationError,
    GenerationErrorCode,
    GenerationProviderIdentity,
)
from jgrad_admission_rag.generation.simple_qa import (
    MAX_SIMPLE_QA_SOURCE_CHARACTERS,
    SimpleQaDraft,
    SimpleQaRequest,
    SimpleQaSource,
    answer_simple_checked,
)


def _request(text: str = "本地记录") -> SimpleQaRequest:
    return SimpleQaRequest(
        question="募集要项里怎么写？",
        target_label="Synthetic target",
        sources=(SimpleQaSource(source_id="source:0001", text=text),),
    )


class _Provider:
    identity = GenerationProviderIdentity(
        provider="fake-online",
        model="simple-test",
        revision="test",
    )

    def __init__(self, output: object) -> None:
        self.output = output
        self.calls = 0

    def answer_simple(self, _request: SimpleQaRequest):
        self.calls += 1
        return self.output


def test_simple_qa_accepts_one_answer_without_claim_or_citation_contracts() -> None:
    provider = _Provider(SimpleQaDraft(answer="这是基于本地资料的回答。"))

    result = answer_simple_checked(provider, _request())

    assert result.answer == "这是基于本地资料的回答。"
    assert result.provider.model == "simple-test"
    assert provider.calls == 1


def test_simple_qa_rejects_malformed_output_without_retaining_context() -> None:
    provider = _Provider({"answer": "PRIVATE", "unknown": "field"})

    with pytest.raises(GenerationError) as caught:
        answer_simple_checked(provider, _request())

    assert caught.value.code is GenerationErrorCode.MALFORMED_OUTPUT
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "PRIVATE" not in str(caught.value)


def test_simple_qa_enforces_total_source_character_bound_before_provider() -> None:
    provider = _Provider(SimpleQaDraft(answer="unused"))
    per_source = MAX_SIMPLE_QA_SOURCE_CHARACTERS // 4 + 1
    oversized = SimpleQaRequest(
        question="question",
        target_label="target",
        sources=tuple(
            SimpleQaSource(source_id=f"source:{index:04d}", text="x" * per_source)
            for index in range(1, 5)
        ),
    )

    with pytest.raises(GenerationError) as caught:
        answer_simple_checked(provider, oversized)

    assert caught.value.code is GenerationErrorCode.INVALID_INPUT
    assert provider.calls == 0
