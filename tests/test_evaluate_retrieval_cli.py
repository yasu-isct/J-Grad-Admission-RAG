from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from jgrad_admission_rag.cli import evaluate_retrieval as cli
from jgrad_admission_rag.retrieval.embedding import EmbeddingIdentity


def _args(*extra: str) -> list[str]:
    return [
        "index",
        "--current-kb",
        "document_kb.json",
        "--benchmark",
        "benchmark.json",
        "--provider",
        "deterministic-fake",
        "--dimension",
        "8",
        *extra,
    ]


def test_cli_uses_one_shared_runtime_empty_metadata_and_one_search_per_exact_query(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    query_values = ("第一の質問です。", "第二の質問です。", "第三の質問です。")
    benchmark = SimpleNamespace(
        queries=tuple(SimpleNamespace(query=value) for value in query_values)
    )
    index = object()
    context = SimpleNamespace(knowledge_base=object())
    provider = object()
    events: list[str] = []
    searches: list[tuple[object, ...]] = []
    packs: list[object] = []

    monkeypatch.setattr(
        cli,
        "load_local_index",
        lambda path, *, mmap: events.append("index") or index,
    )
    monkeypatch.setattr(
        cli,
        "load_fresh_index_context",
        lambda loaded, path, identity: events.append("freshness") or context,
    )
    monkeypatch.setattr(
        cli,
        "load_evaluation_benchmark",
        lambda path: events.append("benchmark") or benchmark,
    )
    monkeypatch.setattr(
        cli,
        "create_provider",
        lambda configuration: events.append("provider") or provider,
    )

    def search(loaded, query, runtime_provider, **kwargs):
        searches.append((loaded, query, runtime_provider, kwargs))
        return SimpleNamespace(hits=(query,))

    monkeypatch.setattr(cli, "search_metadata_index", search)
    monkeypatch.setattr(cli, "expand_references", lambda loaded, fresh, hits: (fresh, hits))

    def build_pack(query, result, expansion):
        pack = object()
        packs.append(pack)
        return pack

    monkeypatch.setattr(cli, "build_evidence_pack", build_pack)
    report = object()
    monkeypatch.setattr(
        cli,
        "evaluate_retrieval",
        lambda loaded_benchmark, kb, loaded_index, values: report,
    )
    monkeypatch.setattr(
        cli,
        "canonical_retrieval_evaluation_bytes",
        lambda value: b'{"schema_version":"1.0"}\n',
    )

    cli.main(_args())

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["schema_version"] == "1.0"
    assert events == ["index", "freshness", "benchmark", "provider"]
    assert [call[1] for call in searches] == list(query_values)
    assert all(call[0] is index and call[2] is provider for call in searches)
    assert all(call[3]["metadata_filter"].active is False for call in searches)
    assert all(call[3]["scope_preference"].active is False for call in searches)
    assert all(call[3]["top_k"] == 10 and call[3]["candidate_k"] == 50 for call in searches)
    assert len(packs) == len(query_values)


@pytest.mark.parametrize(
    "extra",
    (
        ("--top-k", "9"),
        ("--top-k", "10", "--candidate-k", "9"),
    ),
)
def test_invalid_depth_fails_before_index_or_provider(monkeypatch, capsys, extra) -> None:
    monkeypatch.setattr(
        cli,
        "load_local_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("index must not load")),
    )
    monkeypatch.setattr(
        cli,
        "create_provider",
        lambda *_args: (_ for _ in ()).throw(AssertionError("provider must not construct")),
    )

    with pytest.raises(SystemExit) as captured_exit:
        cli.main(_args(*extra))

    error = json.loads(capsys.readouterr().err)
    assert captured_exit.value.code == 2
    assert error["kind"] == "configuration_error"


def test_model_download_is_always_rejected_before_model_work(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "create_provider",
        lambda *_args: (_ for _ in ()).throw(AssertionError("provider must not construct")),
    )
    args = [
        "index",
        "--current-kb",
        "document_kb.json",
        "--benchmark",
        "benchmark.json",
        "--provider",
        "sentence-transformers",
        "--model",
        "BAAI/bge-m3",
        "--revision",
        "a" * 40,
        "--dimension",
        "1024",
        "--allow-model-download",
    ]

    with pytest.raises(SystemExit) as captured_exit:
        cli.main(args)

    error = json.loads(capsys.readouterr().err)
    assert captured_exit.value.code == 2
    assert error["kind"] == "configuration_error"
    assert "never permits" in error["error"]


def test_evaluation_error_is_structured_without_query_echo(monkeypatch, capsys) -> None:
    secret = "秘密の質問です。"
    benchmark = SimpleNamespace(queries=(SimpleNamespace(query=secret),))
    monkeypatch.setattr(cli, "load_local_index", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        cli,
        "load_fresh_index_context",
        lambda *_args: SimpleNamespace(knowledge_base=object()),
    )
    monkeypatch.setattr(cli, "load_evaluation_benchmark", lambda *_args: benchmark)
    monkeypatch.setattr(cli, "create_provider", lambda *_args: object())
    monkeypatch.setattr(
        cli,
        "search_metadata_index",
        lambda *_args, **_kwargs: SimpleNamespace(hits=()),
    )
    monkeypatch.setattr(cli, "expand_references", lambda *_args: object())
    monkeypatch.setattr(cli, "build_evidence_pack", lambda *_args: object())
    monkeypatch.setattr(
        cli,
        "evaluate_retrieval",
        lambda *_args: (_ for _ in ()).throw(cli.RetrievalEvaluationError("evaluation failed")),
    )

    with pytest.raises(SystemExit) as captured_exit:
        cli.main(_args())

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["kind"] == "evaluation_error"
    assert secret not in captured.err


def test_report_error_has_distinct_structured_kind(monkeypatch, capsys) -> None:
    benchmark = SimpleNamespace(queries=(SimpleNamespace(query="評価の質問です。"),))
    monkeypatch.setattr(cli, "load_local_index", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        cli,
        "load_fresh_index_context",
        lambda *_args: SimpleNamespace(knowledge_base=object()),
    )
    monkeypatch.setattr(cli, "load_evaluation_benchmark", lambda *_args: benchmark)
    monkeypatch.setattr(cli, "create_provider", lambda *_args: object())
    monkeypatch.setattr(
        cli,
        "search_metadata_index",
        lambda *_args, **_kwargs: SimpleNamespace(hits=()),
    )
    monkeypatch.setattr(cli, "expand_references", lambda *_args: object())
    monkeypatch.setattr(cli, "build_evidence_pack", lambda *_args: object())
    monkeypatch.setattr(cli, "evaluate_retrieval", lambda *_args: object())
    monkeypatch.setattr(
        cli,
        "canonical_retrieval_evaluation_bytes",
        lambda *_args: (_ for _ in ()).throw(cli.EvaluationReportError("report failed")),
    )

    with pytest.raises(SystemExit) as captured_exit:
        cli.main(_args())

    assert captured_exit.value.code == 2
    assert json.loads(capsys.readouterr().err)["kind"] == "report_error"


def test_declared_fake_provider_identity_is_resolved_once() -> None:
    parser = cli._parser()
    args = parser.parse_args(_args())
    configuration = cli.resolve_provider_configuration(args)
    assert configuration.identity == EmbeddingIdentity(
        "deterministic-fake", "sha256-counter-v1", None, 8
    )
