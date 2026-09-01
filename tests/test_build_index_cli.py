from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from jgrad_admission_rag.cli import build_index as build_index_cli
from jgrad_admission_rag.retrieval.embedding import EmbeddingInputError
from jgrad_admission_rag.retrieval.local_index import IndexBuildError, load_local_index
from jgrad_admission_rag.retrieval.sentence_transformer import (
    SentenceTransformerEmbeddingProvider,
)
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


def _knowledge_base(*, passed: bool = True) -> DocumentKnowledgeBase:
    facts = []
    units = []
    for row, text in enumerate(("出願資格", "検定料")):
        fact = ScopedFact(
            fact_id=f"fact:{row:05d}",
            fact_type="eligibility" if row == 0 else "fees",
            scope_type="global",
            title=text,
            text=f"{text}の本文",
            source_pages=[row + 1],
            section_path=[text],
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
        diagnostics=BuildDiagnostics(quality_gate=QualityGateResult(passed=passed)),
    )


def _write_kb(path: Path, *, passed: bool = True) -> None:
    path.write_text(
        json.dumps(
            _knowledge_base(passed=passed).model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
        newline="",
    )


def _fake_args(kb: Path, output: Path) -> list[str]:
    return [
        str(kb),
        "--output",
        str(output),
        "--provider",
        "deterministic-fake",
        "--dimension",
        "8",
    ]


def _manifest() -> IndexManifest:
    return IndexManifest(
        source_kb_schema_version="0.5",
        document_id="sample-document",
        source_kb_sha256="1" * 64,
        source_pdf_sha256=PDF_HASH,
        payload_count=2,
        vector_count=2,
        embedding_dimension=8,
        vectors_normalized=True,
        embedding_provider="deterministic-fake",
        embedding_model="sha256-counter-v1",
        payloads_sha256="2" * 64,
        vectors_sha256="3" * 64,
    )


def test_fake_cli_builds_loadable_two_row_index_and_prints_one_summary(
    tmp_path: Path, capsys
) -> None:
    kb_path = tmp_path / "document_kb.json"
    output = tmp_path / "index"
    _write_kb(kb_path)

    build_index_cli.main(_fake_args(kb_path, output))

    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    summary = json.loads(captured.out)
    loaded = load_local_index(output, mmap=False)
    assert summary == {
        "output": str(output),
        "document_id": "sample-document",
        "source_kb_sha256": loaded.manifest.source_kb_sha256,
        "source_pdf_sha256": PDF_HASH,
        "index_schema_version": "0.1",
        "payload_count": 2,
        "vector_count": 2,
        "embedding_dimension": 8,
        "embedding_provider": "deterministic-fake",
        "embedding_model": "sha256-counter-v1",
        "embedding_revision": None,
        "distance_metric": "cosine",
        "vectors_normalized": True,
        "payloads_sha256": loaded.manifest.payloads_sha256,
        "vectors_sha256": loaded.manifest.vectors_sha256,
        "artifacts": {
            "manifest": "manifest.json",
            "payloads": "payloads.jsonl",
            "vectors": "embeddings.npy",
        },
        "semantic": False,
    }
    assert loaded.vectors.shape == (2, 8)


@pytest.mark.parametrize(
    "extra",
    [
        ["--model", "BAAI/bge-m3"],
        ["--revision", REVISION],
        ["--batch-size", "4"],
        ["--cache-folder", "cache"],
        ["--allow-model-download"],
    ],
)
def test_fake_rejects_sentence_transformers_only_options(
    tmp_path: Path, capsys, extra: list[str]
) -> None:
    output = tmp_path / "index"

    with pytest.raises(SystemExit) as captured_exit:
        build_index_cli.main(
            [
                "kb.json",
                "--output",
                str(output),
                "--provider",
                "deterministic-fake",
                "--dimension",
                "8",
                *extra,
            ]
        )

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["kind"] == "configuration_error"
    assert not output.exists()


def test_fake_requires_dimension(tmp_path: Path, capsys) -> None:
    output = tmp_path / "index"

    with pytest.raises(SystemExit) as captured_exit:
        build_index_cli.main(
            [
                "kb.json",
                "--output",
                str(output),
                "--provider",
                "deterministic-fake",
            ]
        )

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["kind"] == "configuration_error"
    assert not output.exists()


@pytest.mark.parametrize("missing", ["dimension", "model", "revision"])
def test_sentence_transformers_requires_reproducible_identity(
    tmp_path: Path, capsys, missing: str
) -> None:
    options = {
        "model": ["--model", "BAAI/bge-m3"],
        "revision": ["--revision", REVISION],
        "dimension": ["--dimension", "1024"],
    }
    args = [
        "kb.json",
        "--output",
        str(tmp_path / "index"),
        "--provider",
        "sentence-transformers",
    ]
    for name, values in options.items():
        if name != missing:
            args.extend(values)

    with pytest.raises(SystemExit) as captured_exit:
        build_index_cli.main(args)

    error = json.loads(capsys.readouterr().err)
    assert captured_exit.value.code == 2
    assert error["kind"] == "configuration_error"
    assert f"--{missing}" in error["error"]


@pytest.mark.parametrize("allow_download", [False, True])
def test_sentence_transformers_options_map_exactly_to_adapter_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys,
    allow_download: bool,
) -> None:
    captured = {}

    def fake_build(kb_path, output, provider):
        captured["kb_path"] = kb_path
        captured["output"] = output
        captured["provider"] = provider
        return _manifest().model_copy(
            update={
                "embedding_provider": "sentence-transformers",
                "embedding_model": "BAAI/bge-m3",
                "embedding_revision": REVISION,
                "embedding_dimension": 1024,
            }
        )

    monkeypatch.setattr(build_index_cli, "build_local_index", fake_build)
    args = [
        "document_kb.json",
        "--output",
        str(tmp_path / "index"),
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

    build_index_cli.main(args)

    provider = captured["provider"]
    assert isinstance(provider, SentenceTransformerEmbeddingProvider)
    assert provider.config.model_name == "BAAI/bge-m3"
    assert provider.config.revision == REVISION
    assert provider.config.expected_dimension == 1024
    assert provider.config.batch_size == 4
    assert provider.config.cache_folder == "private-cache"
    assert provider.config.allow_download is allow_download
    assert json.loads(capsys.readouterr().out)["semantic"] is True


def test_sentence_transformers_defaults_to_batch_eight_and_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    captured = {}

    def fake_build(_kb_path, _output, provider):
        captured["config"] = provider.config
        return _manifest()

    monkeypatch.setattr(build_index_cli, "build_local_index", fake_build)
    build_index_cli.main(
        [
            "kb.json",
            "--output",
            str(tmp_path / "index"),
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

    assert captured["config"].batch_size == 8
    assert captured["config"].allow_download is False
    assert capsys.readouterr().err == ""


def test_invalid_revision_is_one_json_error_without_target(tmp_path: Path, capsys) -> None:
    output = tmp_path / "index"

    with pytest.raises(SystemExit) as captured_exit:
        build_index_cli.main(
            [
                "kb.json",
                "--output",
                str(output),
                "--provider",
                "sentence-transformers",
                "--model",
                "BAAI/bge-m3",
                "--revision",
                "main",
                "--dimension",
                "1024",
            ]
        )

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    assert json.loads(captured.err)["kind"] == "configuration_error"
    assert not output.exists()


@pytest.mark.parametrize("bad_value", ["0", "-1", "nope"])
def test_non_positive_or_invalid_numeric_option_uses_argparse_exit_two(
    tmp_path: Path, capsys, bad_value: str
) -> None:
    output = tmp_path / "index"

    with pytest.raises(SystemExit) as captured_exit:
        build_index_cli.main(
            [
                "kb.json",
                "--output",
                str(output),
                "--provider",
                "deterministic-fake",
                "--dimension",
                bad_value,
            ]
        )

    assert captured_exit.value.code == 2
    assert capsys.readouterr().out == ""
    assert not output.exists()


@pytest.mark.parametrize("case", ["missing", "invalid", "failed_gate", "existing_target"])
def test_expected_build_failures_are_safe_json_and_publish_no_new_target(
    tmp_path: Path, capsys, case: str
) -> None:
    kb_path = tmp_path / "document_kb.json"
    output = tmp_path / "index"
    if case == "invalid":
        kb_path.write_text("SENTINEL-ADMISSION-TEXT", encoding="utf-8")
    elif case == "failed_gate":
        _write_kb(kb_path, passed=False)
    elif case == "existing_target":
        _write_kb(kb_path)
        output.mkdir()

    with pytest.raises(SystemExit) as captured_exit:
        build_index_cli.main(_fake_args(kb_path, output))

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    error = json.loads(captured.err)
    assert error["kind"] == "index_build_error"
    assert error["provider"] == "deterministic-fake"
    assert "SENTINEL" not in captured.err
    if case != "existing_target":
        assert not output.exists()
    else:
        assert list(output.iterdir()) == []


def test_existing_file_target_is_untouched(tmp_path: Path, capsys) -> None:
    kb_path = tmp_path / "document_kb.json"
    output = tmp_path / "index"
    _write_kb(kb_path)
    output.write_bytes(b"KEEP-ME")

    with pytest.raises(SystemExit) as captured_exit:
        build_index_cli.main(_fake_args(kb_path, output))

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["kind"] == "index_build_error"
    assert output.read_bytes() == b"KEEP-ME"


def test_existing_target_fails_before_sentence_transformers_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    kb_path = tmp_path / "document_kb.json"
    output = tmp_path / "index"
    _write_kb(kb_path)
    output.mkdir()
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(SystemExit) as captured_exit:
        build_index_cli.main(
            [
                str(kb_path),
                "--output",
                str(output),
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
    assert error["error"] == "output target already exists"
    assert list(output.iterdir()) == []


def test_missing_embedding_dependency_is_safe_json_without_download_or_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    kb_path = tmp_path / "document_kb.json"
    output = tmp_path / "index"
    _write_kb(kb_path)
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(SystemExit) as captured_exit:
        build_index_cli.main(
            [
                str(kb_path),
                "--output",
                str(output),
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
    assert json.loads(captured.err) == {
        "error": "source KB or embedding provider validation failed",
        "kind": "index_build_error",
        "provider": "sentence-transformers",
    }
    assert not output.exists()


def test_known_provider_failure_is_safe_json(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    sentinel = "SENTINEL-FULL-ADMISSION-TEXT"

    def fail(*_args, **_kwargs):
        raise IndexBuildError("embedding provider validation failed") from RuntimeError(sentinel)

    monkeypatch.setattr(build_index_cli, "build_local_index", fail)
    with pytest.raises(SystemExit) as captured_exit:
        build_index_cli.main(
            [
                "kb.json",
                "--output",
                "index",
                "--provider",
                "deterministic-fake",
                "--dimension",
                "8",
            ]
        )

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert sentinel not in captured.err
    assert json.loads(captured.err)["error"] == "embedding provider validation failed"


def test_direct_embedding_error_is_safe_json(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(
        build_index_cli,
        "_build_provider",
        lambda _args: (_ for _ in ()).throw(EmbeddingInputError("token limit exceeded")),
    )

    with pytest.raises(SystemExit) as captured_exit:
        build_index_cli.main(
            [
                "kb.json",
                "--output",
                "index",
                "--provider",
                "deterministic-fake",
                "--dimension",
                "8",
            ]
        )

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": "token limit exceeded",
        "kind": "embedding_error",
        "provider": "deterministic-fake",
    }


@pytest.mark.parametrize("error", [RuntimeError("bug"), ValueError("bad internal state")])
def test_unexpected_programming_error_is_not_disguised(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(
        build_index_cli,
        "build_local_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(type(error), match=str(error)):
        build_index_cli.main(
            [
                "kb.json",
                "--output",
                "index",
                "--provider",
                "deterministic-fake",
                "--dimension",
                "8",
            ]
        )


def test_module_subprocess_smoke_uses_current_python_and_no_network(tmp_path: Path) -> None:
    kb_path = tmp_path / "document_kb.json"
    output = tmp_path / "index"
    _write_kb(kb_path)
    env = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [source_root, env.get("PYTHONPATH")]))

    result = subprocess.run(
        [sys.executable, "-m", "jgrad_admission_rag.cli.build_index", *_fake_args(kb_path, output)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["payload_count"] == 2
    assert load_local_index(output, mmap=False).vectors.shape == (2, 8)
