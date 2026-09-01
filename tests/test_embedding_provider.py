from __future__ import annotations

import math
from dataclasses import FrozenInstanceError
from typing import Sequence

import pytest

from jgrad_admission_rag.retrieval.embedding import (
    DeterministicFakeEmbeddingProvider,
    EmbeddingIdentity,
    EmbeddingInputError,
    EmbeddingOutputError,
    EmbeddingProvider,
    EmbeddingProviderError,
    embed_documents_checked,
    embed_query_checked,
)


class SyntheticProvider:
    def __init__(self, document_output=None, query_output=None, error: Exception | None = None):
        self.identity = EmbeddingIdentity("synthetic", "test-model", "r1", 2)
        self.document_output = document_output
        self.query_output = query_output
        self.error = error
        self.document_calls = 0
        self.query_calls = 0

    def embed_documents(self, texts: Sequence[str]):
        self.document_calls += 1
        if self.error:
            raise self.error
        if self.document_output is not None:
            return self.document_output
        return [[float(index), float(index + 1)] for index, _ in enumerate(texts)]

    def embed_query(self, text: str):
        self.query_calls += 1
        if self.error:
            raise self.error
        return self.query_output if self.query_output is not None else [1.0, 2.0]


class InputMutatingProvider(SyntheticProvider):
    def embed_documents(self, texts: Sequence[str]):
        texts[0] = "changed"
        return [[1.0, 2.0]]


@pytest.mark.parametrize("provider", [SyntheticProvider(), DeterministicFakeEmbeddingProvider()])
def test_protocol_accepts_structural_providers(provider) -> None:
    assert isinstance(provider, EmbeddingProvider)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"provider": ""}, "provider"),
        ({"provider": " fake"}, "provider"),
        ({"model": ""}, "model"),
        ({"model": "fake "}, "model"),
        ({"revision": ""}, "revision"),
        ({"revision": " r1"}, "revision"),
        ({"dimension": 0}, "dimension"),
        ({"dimension": -1}, "dimension"),
        ({"dimension": True}, "dimension"),
        ({"dimension": 1.5}, "dimension"),
    ],
)
def test_identity_rejects_invalid_values(changes: dict, message: str) -> None:
    values = {"provider": "fake", "model": "sha256", "revision": None, "dimension": 8}
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        EmbeddingIdentity(**values)


def test_identity_is_immutable_and_maps_to_index_manifest_fields() -> None:
    identity = EmbeddingIdentity("fake", "sha256", "r1", 8)

    with pytest.raises(FrozenInstanceError):
        identity.dimension = 16

    assert {
        "embedding_provider": identity.provider,
        "embedding_model": identity.model,
        "embedding_revision": identity.revision,
        "embedding_dimension": identity.dimension,
    } == {
        "embedding_provider": "fake",
        "embedding_model": "sha256",
        "embedding_revision": "r1",
        "embedding_dimension": 8,
    }


def test_empty_document_batch_skips_provider_call() -> None:
    provider = SyntheticProvider()

    assert embed_documents_checked(provider, []) == []
    assert provider.document_calls == 0


def test_document_embedding_preserves_count_and_order() -> None:
    provider = SyntheticProvider()

    assert embed_documents_checked(provider, ["一", "二", "三"]) == [
        [0.0, 1.0],
        [1.0, 2.0],
        [2.0, 3.0],
    ]


def test_checked_document_call_isolates_mutation_of_caller_batch() -> None:
    caller_texts = ["出願資格"]

    with pytest.raises(EmbeddingProviderError) as captured:
        embed_documents_checked(InputMutatingProvider(), caller_texts)

    assert isinstance(captured.value.__cause__, TypeError)
    assert caller_texts == ["出願資格"]


@pytest.mark.parametrize("bad_text", ["", "  \t\n", 12, None])
def test_blank_or_non_string_document_fails_before_provider_call(bad_text) -> None:
    provider = SyntheticProvider()

    with pytest.raises(EmbeddingInputError, match="embed_documents row 1"):
        embed_documents_checked(provider, ["有効", bad_text])

    assert provider.document_calls == 0


@pytest.mark.parametrize("bad_text", ["", "  \t\n", 12, None])
def test_blank_or_non_string_query_fails_before_provider_call(bad_text) -> None:
    provider = SyntheticProvider()

    with pytest.raises(EmbeddingInputError, match="embed_query"):
        embed_query_checked(provider, bad_text)

    assert provider.query_calls == 0


def test_document_batch_rejects_a_bare_string() -> None:
    provider = SyntheticProvider()

    with pytest.raises(EmbeddingInputError, match="sequence of strings"):
        embed_documents_checked(provider, "出願資格")
    assert provider.document_calls == 0


@pytest.mark.parametrize("operation", ["documents", "query"])
def test_backend_failure_is_wrapped_with_preserved_cause(operation: str) -> None:
    backend_error = RuntimeError("backend secret")
    provider = SyntheticProvider(error=backend_error)

    with pytest.raises(EmbeddingProviderError, match=f"embed_{operation}") as captured:
        if operation == "documents":
            embed_documents_checked(provider, ["出願資格"])
        else:
            embed_query_checked(provider, "出願資格")

    assert captured.value.__cause__ is backend_error
    assert "backend secret" not in str(captured.value)


def test_existing_provider_error_is_not_double_wrapped() -> None:
    provider_error = EmbeddingProviderError("safe provider failure")
    provider = SyntheticProvider(error=provider_error)

    with pytest.raises(EmbeddingProviderError) as captured:
        embed_query_checked(provider, "出願資格")

    assert captured.value is provider_error


@pytest.mark.parametrize(
    ("output", "message"),
    [
        ([], "row count mismatch"),
        ([[1.0]], "dimension mismatch"),
        ([[True, 1.0]], "coordinate 0"),
        ([["1", 1.0]], "coordinate 0"),
        ([[float("nan"), 1.0]], "finite"),
        ([[float("inf"), 1.0]], "finite"),
        ([[-float("inf"), 1.0]], "finite"),
    ],
)
def test_document_output_validation_rejects_malformed_vectors(output, message: str) -> None:
    provider = SyntheticProvider(document_output=output)

    with pytest.raises(EmbeddingOutputError, match=message):
        embed_documents_checked(provider, ["出願資格"])


@pytest.mark.parametrize(
    ("output", "message"),
    [
        ([1.0], "dimension mismatch"),
        ([True, 1.0], "coordinate 0"),
        ([object(), 1.0], "coordinate 0"),
        ([float("nan"), 1.0], "finite"),
        ([float("inf"), 1.0], "finite"),
        ([-float("inf"), 1.0], "finite"),
    ],
)
def test_query_output_validation_rejects_malformed_vectors(output, message: str) -> None:
    provider = SyntheticProvider(query_output=output)

    with pytest.raises(EmbeddingOutputError, match=message):
        embed_query_checked(provider, "出願資格")


def test_checked_calls_copy_adapter_owned_sequences_to_plain_lists() -> None:
    document_row = [1, 2.5]
    query_row = (3, 4.5)
    provider = SyntheticProvider(document_output=(document_row,), query_output=query_row)

    documents = embed_documents_checked(provider, ["出願資格"])
    query = embed_query_checked(provider, "試験科目")
    document_row[0] = 99

    assert documents == [[1.0, 2.5]]
    assert query == [3.0, 4.5]
    assert type(documents) is list and type(documents[0]) is list and type(query) is list


def test_fake_is_stable_for_japanese_and_shared_between_entry_points() -> None:
    first = DeterministicFakeEmbeddingProvider(dimension=8)
    second = DeterministicFakeEmbeddingProvider(dimension=8)
    text = "日本語の出願資格"

    document_vector = embed_documents_checked(first, [text])[0]
    query_vector = embed_query_checked(first, text)

    assert document_vector == query_vector == embed_query_checked(second, text)
    assert document_vector != embed_query_checked(second, "英語外部試験の要件")
    assert math.isclose(math.sqrt(sum(value * value for value in document_vector)), 1.0)
    assert any(value != 0.0 for value in document_vector)


def test_fake_counter_expansion_is_deterministic_beyond_one_digest() -> None:
    first = DeterministicFakeEmbeddingProvider(dimension=9)
    second = DeterministicFakeEmbeddingProvider(dimension=9)

    first_vector = embed_query_checked(first, "検定料")

    assert len(first_vector) == 9
    assert first_vector == embed_query_checked(second, "検定料")
    assert math.isclose(math.sqrt(sum(value * value for value in first_vector)), 1.0)


def test_error_messages_do_not_include_complete_source_text() -> None:
    sentinel = "SENTINEL-FULL-ADMISSION-TEXT-DO-NOT-LEAK"
    provider = SyntheticProvider(document_output=[[1.0]])

    with pytest.raises(EmbeddingOutputError) as captured:
        embed_documents_checked(provider, [sentinel])

    assert sentinel not in str(captured.value)
