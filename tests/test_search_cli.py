from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from jgrad_admission_rag.cli import search as search_cli
from jgrad_admission_rag.retrieval.embedding import DeterministicFakeEmbeddingProvider
from jgrad_admission_rag.retrieval.local_index import build_local_index
from jgrad_admission_rag.retrieval.sentence_transformer import (
    SentenceTransformerEmbeddingProvider,
)
from jgrad_admission_rag.retrieval.vector_search import VectorSearchResult
from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    QualityGateResult,
    RetrievalUnit,
    ScopedFact,
)
from jgrad_admission_rag.schemas.index import IndexManifest

REVISION = "a" * 40
PDF_HASH = "b" * 64


def _knowledge_base() -> DocumentKnowledgeBase:
    facts = []
    units = []
    for row, text in enumerate(("出願資格", "検定料")):
        fact = ScopedFact(
            fact_id=f"fact:{row:05d}",
            fact_type="eligibility" if row == 0 else "fees",
            scope_type="department" if row == 0 else "global",
            scope_targets=["情報工学系"] if row == 0 else [],
            parent_college="情報理工学院" if row == 0 else None,
            title=text,
            text=f"{text}の本文",
            source_pages=[row + 1],
            section_path=["募集要項", text],
            embedding_text=f"canonical {text}",
            metadata={"embedding_text_version": "1"},
        )
        facts.append(fact)
        units.append(
            RetrievalUnit(
                unit_id=f"unit:{row:05d}",
                fact_id=fact.fact_id,
                text=fact.embedding_text,
                source_pages=list(fact.source_pages),
                section_path=list(fact.section_path),
                metadata={"embedding_text_version": "1"},
            )
        )
    return DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            document_id="sample-document",
            source_pdf="sample.pdf",
            pdf_sha256=PDF_HASH,
            chunk_count=2,
        ),
        facts=facts,
        retrieval_units=units,
        diagnostics=BuildDiagnostics(quality_gate=QualityGateResult(passed=True)),
    )


def _write_kb(path: Path) -> None:
    path.write_text(
        json.dumps(
            _knowledge_base().model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
        newline="",
    )


def _build_fake_index(tmp_path: Path, *, dimension: int = 8) -> Path:
    kb_path = tmp_path / "document_kb.json"
    _write_kb(kb_path)
    index_dir = tmp_path / "index"
    build_local_index(
        kb_path,
        index_dir,
        DeterministicFakeEmbeddingProvider(dimension=dimension),
    )
    return index_dir


def _fake_args(index_dir: Path, *, top_k: int = 5, query: str = "出願資格") -> list[str]:
    return [
        str(index_dir),
        "--query",
        query,
        "--top-k",
        str(top_k),
        "--provider",
        "deterministic-fake",
        "--dimension",
        "8",
    ]


def _manifest(**changes) -> IndexManifest:
    values = {
        "source_kb_schema_version": "0.5",
        "document_id": "sample-document",
        "source_kb_sha256": "1" * 64,
        "source_pdf_sha256": PDF_HASH,
        "payload_count": 0,
        "vector_count": 0,
        "embedding_dimension": 1024,
        "vectors_normalized": True,
        "embedding_provider": "sentence-transformers",
        "embedding_model": "BAAI/bge-m3",
        "embedding_revision": REVISION,
        "payloads_sha256": "2" * 64,
        "vectors_sha256": "3" * 64,
    }
    values.update(changes)
    return IndexManifest(**values)


def test_fake_search_cli_returns_one_complete_read_only_json_summary(
    tmp_path: Path, capsys
) -> None:
    index_dir = _build_fake_index(tmp_path)
    before = {path.name: path.read_bytes() for path in index_dir.iterdir()}

    search_cli.main(_fake_args(index_dir, top_k=1))

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    assert summary["index"] == str(index_dir)
    assert summary["document_id"] == "sample-document"
    assert summary["source_pdf_sha256"] == PDF_HASH
    assert summary["index_schema_version"] == "0.1"
    assert summary["embedding_provider"] == "deterministic-fake"
    assert summary["embedding_model"] == "sha256-counter-v1"
    assert summary["embedding_revision"] is None
    assert summary["embedding_dimension"] == 8
    assert summary["distance_metric"] == "cosine"
    assert summary["semantic"] is False
    assert summary["top_k_requested"] == 1
    assert summary["result_count"] == 1
    hit = summary["results"][0]
    assert set(hit) == {
        "rank",
        "row_index",
        "score",
        "document_id",
        "unit_id",
        "fact_id",
        "text",
        "source_pages",
        "section_path",
        "fact_type",
        "scope_type",
        "scope_targets",
        "parent_college",
        "metadata",
    }
    assert hit["document_id"] == "sample-document"
    assert hit["source_pages"]
    assert hit["section_path"]
    assert {path.name: path.read_bytes() for path in index_dir.iterdir()} == before


def test_top_k_overflow_reports_all_rows(tmp_path: Path, capsys) -> None:
    index_dir = _build_fake_index(tmp_path)

    search_cli.main(_fake_args(index_dir, top_k=99))

    summary = json.loads(capsys.readouterr().out)
    assert summary["top_k_requested"] == 99
    assert summary["result_count"] == 2
    assert [hit["rank"] for hit in summary["results"]] == [1, 2]


@pytest.mark.parametrize(
    "extra",
    [
        ["--model", "BAAI/bge-m3"],
        ["--revision", REVISION],
        ["--batch-size", "4"],
        ["--cache-folder", "private-cache"],
        ["--allow-model-download"],
    ],
)
def test_fake_rejects_sentence_transformers_only_options(
    tmp_path: Path, capsys, extra: list[str]
) -> None:
    index_dir = _build_fake_index(tmp_path)

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main([*_fake_args(index_dir), *extra])

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["kind"] == "configuration_error"


@pytest.mark.parametrize("allow_download", [False, True])
def test_sentence_transformers_configuration_reuses_build_cli_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
    allow_download: bool,
) -> None:
    captured = {}

    def fake_search(index, query, provider, *, top_k):
        captured.update(index=index, query=query, provider=provider, top_k=top_k)
        return VectorSearchResult(manifest=_manifest(), hits=())

    monkeypatch.setattr(search_cli, "search_local_index", fake_search)
    args = [
        "index",
        "--query",
        "query",
        "--top-k",
        "3",
        "--provider",
        "sentence-transformers",
        "--model",
        "BAAI/bge-m3",
        "--revision",
        REVISION,
        "--dimension",
        "1024",
        "--batch-size",
        "4",
        "--cache-folder",
        "private-cache",
    ]
    if allow_download:
        args.append("--allow-model-download")

    search_cli.main(args)

    provider = captured["provider"]
    assert isinstance(provider, SentenceTransformerEmbeddingProvider)
    assert provider.config.model_name == "BAAI/bge-m3"
    assert provider.config.revision == REVISION
    assert provider.config.expected_dimension == 1024
    assert provider.config.batch_size == 4
    assert provider.config.cache_folder == "private-cache"
    assert provider.config.allow_download is allow_download
    assert captured["query"] == "query"
    assert captured["top_k"] == 3
    assert json.loads(capsys.readouterr().out)["semantic"] is True


def test_blank_query_is_safe_json_without_echo(tmp_path: Path, capsys) -> None:
    index_dir = _build_fake_index(tmp_path)

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(_fake_args(index_dir, query=" "))

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["kind"] == "search_error"
    assert "SENTINEL" not in captured.err


def test_identity_mismatch_is_safe_json_without_query_echo(tmp_path: Path, capsys) -> None:
    index_dir = _build_fake_index(tmp_path)
    sentinel = "SENTINEL-RAW-QUERY"

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(
            [
                str(index_dir),
                "--query",
                sentinel,
                "--provider",
                "deterministic-fake",
                "--dimension",
                "3",
            ]
        )

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["kind"] == "search_error"
    assert sentinel not in captured.err


def test_corrupt_index_fails_before_sentence_transformers_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "manifest.json").write_text("not-json", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(
            [
                str(index_dir),
                "--query",
                "query",
                "--provider",
                "sentence-transformers",
                "--model",
                "BAAI/bge-m3",
                "--revision",
                REVISION,
                "--dimension",
                "1024",
            ]
        )

    error = json.loads(capsys.readouterr().err)
    assert captured_exit.value.code == 2
    assert error["kind"] == "index_load_error"


def test_missing_optional_dependency_is_safe_embedding_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    index_dir = _build_fake_index(tmp_path)
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(
            [
                str(index_dir),
                "--query",
                "query",
                "--provider",
                "sentence-transformers",
                "--model",
                "BAAI/bge-m3",
                "--revision",
                REVISION,
                "--dimension",
                "1024",
            ]
        )

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["kind"] == "embedding_error"


@pytest.mark.parametrize("bad_top_k", ["0", "-1", "bad"])
def test_invalid_top_k_uses_argparse_exit_two(tmp_path: Path, capsys, bad_top_k: str) -> None:
    index_dir = _build_fake_index(tmp_path)
    args = _fake_args(index_dir, top_k=1)
    args[4] = bad_top_k

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(args)

    assert captured_exit.value.code == 2
    assert capsys.readouterr().out == ""


def test_unexpected_programming_error_is_not_disguised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        search_cli,
        "search_local_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bug")),
    )

    with pytest.raises(RuntimeError, match="bug"):
        search_cli.main(
            [
                "index",
                "--query",
                "query",
                "--provider",
                "deterministic-fake",
                "--dimension",
                "8",
            ]
        )


@pytest.mark.parametrize("entrypoint", ["module", "console-script"])
def test_subprocess_smoke_uses_current_python_and_temporary_index(
    tmp_path: Path, entrypoint: str
) -> None:
    index_dir = _build_fake_index(tmp_path)
    env = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [source_root, env.get("PYTHONPATH")]))
    if entrypoint == "module":
        command = [sys.executable, "-m", "jgrad_admission_rag.cli.search"]
    else:
        executable = Path(sys.executable).with_name("jgrad-search.exe")
        assert executable.is_file()
        command = [str(executable)]

    result = subprocess.run(
        [*command, *_fake_args(index_dir, top_k=1)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["result_count"] == 1
