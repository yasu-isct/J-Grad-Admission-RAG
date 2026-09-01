from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import ModuleType

import pytest

from jgrad_admission_rag.retrieval.embedding import (
    DeterministicFakeEmbeddingProvider,
    EmbeddingInputError,
    EmbeddingOutputError,
    EmbeddingProvider,
    EmbeddingProviderError,
    embed_documents_checked,
    embed_query_checked,
)
from jgrad_admission_rag.retrieval.sentence_transformer import (
    SentenceTransformerConfig,
    SentenceTransformerEmbeddingProvider,
)

REVISION = "a" * 40


class ArrayLike:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class FakeTokenizer:
    def __init__(self, counts: dict[str, int] | None = None, error: Exception | None = None):
        self.counts = counts or {}
        self.error = error
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, texts, **kwargs):
        self.calls.append((list(texts), kwargs))
        if self.error:
            raise self.error
        return {"input_ids": [list(range(self.counts.get(text, len(text) + 2))) for text in texts]}


class FakeBackend:
    def __init__(
        self,
        *,
        dimension: int = 3,
        max_seq_length: int = 8,
        tokenizer: FakeTokenizer | None = None,
        output=None,
        encode_error: Exception | None = None,
    ):
        self.dimension = dimension
        self.max_seq_length = max_seq_length
        self.tokenizer = tokenizer or FakeTokenizer()
        self.output = output
        self.encode_error = encode_error
        self.encode_calls: list[tuple[list[str], dict]] = []

    def get_sentence_embedding_dimension(self):
        return self.dimension

    def encode(self, texts, **kwargs):
        self.encode_calls.append((list(texts), kwargs))
        if self.encode_error:
            raise self.encode_error
        if self.output is not None:
            return self.output
        return ArrayLike([[float(row), 1.0, 2.0] for row, _ in enumerate(texts)])


def _config(**changes) -> SentenceTransformerConfig:
    values = {
        "model_name": "BAAI/bge-m3",
        "revision": REVISION,
        "expected_dimension": 3,
    }
    values.update(changes)
    return SentenceTransformerConfig(**values)


def _provider(backend: FakeBackend, **config_changes) -> SentenceTransformerEmbeddingProvider:
    return SentenceTransformerEmbeddingProvider(
        _config(**config_changes), _backend_factory=lambda _config: backend
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"model_name": ""}, "model_name"),
        ({"model_name": " model"}, "model_name"),
        ({"revision": "main"}, "40-character"),
        ({"revision": "A" * 40}, "40-character"),
        ({"revision": "a" * 39}, "40-character"),
        ({"expected_dimension": 0}, "expected_dimension"),
        ({"expected_dimension": True}, "expected_dimension"),
        ({"batch_size": 0}, "batch_size"),
        ({"batch_size": True}, "batch_size"),
        ({"device": "cuda"}, "device"),
        ({"allow_download": 1}, "allow_download"),
        ({"cache_folder": object()}, "cache_folder"),
    ],
)
def test_config_rejects_non_reproducible_or_unsupported_values(changes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _config(**changes)


def test_provider_structurally_conforms_and_maps_validated_identity() -> None:
    provider = _provider(FakeBackend())

    assert isinstance(provider, EmbeddingProvider)
    assert provider.identity.provider == "sentence-transformers"
    assert provider.identity.model == "BAAI/bge-m3"
    assert provider.identity.revision == REVISION
    assert provider.identity.dimension == 3


def test_config_is_immutable() -> None:
    config = _config()

    with pytest.raises(FrozenInstanceError):
        config.batch_size = 16


def test_backend_loads_once_per_instance() -> None:
    backend = FakeBackend()
    calls = []
    provider = SentenceTransformerEmbeddingProvider(
        _config(), _backend_factory=lambda config: calls.append(config) or backend
    )

    assert provider.identity == provider.identity
    embed_query_checked(provider, "問い")

    assert calls == [provider.config]


@pytest.mark.parametrize("dimension", [None, 0, True])
def test_invalid_loaded_dimension_is_rejected(dimension) -> None:
    with pytest.raises(EmbeddingProviderError, match="invalid embedding dimension"):
        _provider(FakeBackend(dimension=dimension)).identity


def test_dimension_mismatch_is_rejected() -> None:
    with pytest.raises(EmbeddingProviderError, match="dimension mismatch"):
        _provider(FakeBackend(dimension=4)).identity


@pytest.mark.parametrize("max_seq_length", [None, 0, -1, True])
def test_invalid_model_maximum_is_rejected(max_seq_length) -> None:
    with pytest.raises(EmbeddingProviderError, match="invalid maximum sequence length"):
        _provider(FakeBackend(max_seq_length=max_seq_length)).identity


def test_missing_tokenizer_is_rejected() -> None:
    backend = FakeBackend()
    backend.tokenizer = None

    with pytest.raises(EmbeddingProviderError, match="tokenizer is unavailable"):
        _provider(backend).identity


@pytest.mark.parametrize("allow_download", [False, True])
def test_default_loader_passes_exact_safe_constructor_arguments(
    monkeypatch: pytest.MonkeyPatch,
    allow_download: bool,
) -> None:
    captured = {}
    module = ModuleType("sentence_transformers")

    def constructor(model_name, **kwargs):
        captured["model_name"] = model_name
        captured["kwargs"] = kwargs
        return FakeBackend()

    module.SentenceTransformer = constructor
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    config = _config(
        allow_download=allow_download,
        cache_folder=Path("private-cache"),
    )

    identity = SentenceTransformerEmbeddingProvider(config).identity

    assert identity.dimension == 3
    assert captured == {
        "model_name": "BAAI/bge-m3",
        "kwargs": {
            "revision": REVISION,
            "device": "cpu",
            "cache_folder": "private-cache",
            "local_files_only": not allow_download,
            "trust_remote_code": False,
        },
    }


def test_missing_optional_dependency_has_safe_install_hint_and_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(EmbeddingProviderError, match=r"pip install -e .\[embedding\]") as captured:
        SentenceTransformerEmbeddingProvider(_config()).identity

    assert isinstance(captured.value.__cause__, ImportError)


def test_base_imports_and_fake_do_not_require_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    provider = DeterministicFakeEmbeddingProvider(3)

    assert len(embed_query_checked(provider, "出願資格")) == 3


def test_document_encode_preserves_text_order_and_exact_arguments() -> None:
    tokenizer = FakeTokenizer({"文書A": 3, "文書B": 4})
    backend = FakeBackend(tokenizer=tokenizer)
    provider = _provider(backend, batch_size=5)

    vectors = embed_documents_checked(provider, ["文書A", "文書B"])

    assert vectors == [[0.0, 1.0, 2.0], [1.0, 1.0, 2.0]]
    assert tokenizer.calls == [
        (
            ["文書A", "文書B"],
            {
                "add_special_tokens": True,
                "truncation": False,
                "padding": False,
                "return_attention_mask": False,
                "return_token_type_ids": False,
            },
        )
    ]
    assert backend.encode_calls == [
        (
            ["文書A", "文書B"],
            {
                "batch_size": 5,
                "show_progress_bar": False,
                "output_value": "sentence_embedding",
                "precision": "float32",
                "convert_to_numpy": True,
                "convert_to_tensor": False,
                "device": "cpu",
                "normalize_embeddings": False,
            },
        )
    ]
    assert "prompt" not in backend.encode_calls[0][1]
    assert "prompt_name" not in backend.encode_calls[0][1]


def test_query_uses_same_exact_unprefixed_text() -> None:
    backend = FakeBackend()
    provider = _provider(backend)

    assert embed_query_checked(provider, "日本語の質問") == [0.0, 1.0, 2.0]
    assert backend.tokenizer.calls[0][0] == ["日本語の質問"]
    assert backend.encode_calls[0][0] == ["日本語の質問"]


def test_array_like_output_is_copied_to_independent_plain_lists() -> None:
    owned = [[1, 2, 3]]
    provider = _provider(FakeBackend(output=ArrayLike(owned)))

    result = embed_documents_checked(provider, ["文書"])
    owned[0][0] = 99

    assert result == [[1.0, 2.0, 3.0]]
    assert type(result) is list and type(result[0]) is list


def test_empty_document_batch_skips_load_tokenizer_and_encode() -> None:
    calls = []
    provider = SentenceTransformerEmbeddingProvider(
        _config(), _backend_factory=lambda config: calls.append(config) or FakeBackend()
    )

    assert provider.embed_documents([]) == []
    assert calls == []


def test_mixed_lengths_and_exact_boundary_pass_preflight() -> None:
    tokenizer = FakeTokenizer({"短": 2, "境界": 8})
    backend = FakeBackend(max_seq_length=8, tokenizer=tokenizer)

    result = embed_documents_checked(_provider(backend), ["短", "境界"])

    assert len(result) == 2
    assert len(backend.encode_calls) == 1


def test_document_overflow_reports_row_count_and_limit_before_encode() -> None:
    sentinel = "SENTINEL-FULL-ADMISSION-TEXT"
    tokenizer = FakeTokenizer({"短": 2, sentinel: 9})
    backend = FakeBackend(max_seq_length=8, tokenizer=tokenizer)

    with pytest.raises(
        EmbeddingInputError,
        match=r"documents row 1 token count 9 exceeds model limit 8",
    ) as captured:
        embed_documents_checked(_provider(backend), ["短", sentinel])

    assert backend.encode_calls == []
    assert sentinel not in str(captured.value)


def test_query_overflow_is_rejected_before_encode_without_text_leak() -> None:
    sentinel = "SENTINEL-QUERY-CONTENT"
    backend = FakeBackend(max_seq_length=4, tokenizer=FakeTokenizer({sentinel: 5}))

    with pytest.raises(EmbeddingInputError, match=r"query token count 5.*limit 4") as captured:
        embed_query_checked(_provider(backend), sentinel)

    assert backend.encode_calls == []
    assert sentinel not in str(captured.value)


def test_load_failure_is_safe_and_preserves_cause() -> None:
    cause = RuntimeError("SECRET cache=C:/private token=abc")
    provider = SentenceTransformerEmbeddingProvider(
        _config(cache_folder="C:/private"),
        _backend_factory=lambda _config: (_ for _ in ()).throw(cause),
    )

    with pytest.raises(EmbeddingProviderError, match="model loading failed") as captured:
        provider.identity

    assert captured.value.__cause__ is cause
    assert "SECRET" not in str(captured.value)
    assert "C:/private" not in str(captured.value)


def test_tokenizer_failure_is_safe_and_preserves_cause() -> None:
    cause = RuntimeError("SECRET source text")
    backend = FakeBackend(tokenizer=FakeTokenizer(error=cause))

    with pytest.raises(EmbeddingProviderError, match="documents tokenization failed") as captured:
        embed_documents_checked(_provider(backend), ["文書"])

    assert captured.value.__cause__ is cause
    assert "SECRET" not in str(captured.value)
    assert backend.encode_calls == []


def test_encode_failure_is_safe_and_preserves_cause() -> None:
    cause = RuntimeError("SECRET credential")
    backend = FakeBackend(encode_error=cause)

    with pytest.raises(EmbeddingProviderError, match="query embedding encode failed") as captured:
        embed_query_checked(_provider(backend), "質問")

    assert captured.value.__cause__ is cause
    assert "SECRET" not in str(captured.value)


@pytest.mark.parametrize(
    "output",
    [[], [[1.0, 2.0]], [[1.0, 2.0, float("nan")]]],
)
def test_malformed_backend_output_uses_idx02_output_error(output) -> None:
    provider = _provider(FakeBackend(output=ArrayLike(output)))

    with pytest.raises(EmbeddingOutputError):
        embed_documents_checked(provider, ["文書"])
