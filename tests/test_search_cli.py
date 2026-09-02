from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from jgrad_admission_rag.cli import search as search_cli
from jgrad_admission_rag.retrieval.embedding import (
    DeterministicFakeEmbeddingProvider,
    EmbeddingIdentity,
)
from jgrad_admission_rag.retrieval.local_index import build_local_index
from jgrad_admission_rag.retrieval.hybrid_search import (
    HybridFusionError,
    search_hybrid_index,
)
from jgrad_admission_rag.retrieval.local_index import load_local_index
from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    QualityGateResult,
    ReferenceDiagnostic,
    RetrievalUnit,
    ScopedFact,
)

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


def _write_reference_kb(path: Path) -> None:
    kb = _knowledge_base()
    claim = ReferenceDiagnostic(
        source_fact_id="fact:00000",
        label="下記(1)",
        reference_key="1",
        direction="forward",
        status="resolved",
        selected_target_fact_id="fact:00001",
        candidate_target_fact_ids=["fact:00001"],
        top_score=2.0,
        score_margin=1.0,
        reason="unique_match",
    )
    kb.manifest.reference_link_count = 1
    kb.diagnostics.reference_claim_count = 1
    kb.diagnostics.reference_status_counts = {
        "resolved": 1,
        "ambiguous": 0,
        "unresolved": 0,
    }
    kb.diagnostics.reference_claims = [claim]
    path.write_text(
        json.dumps(kb.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")) + "\n",
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


def _build_reference_index(tmp_path: Path) -> Path:
    kb_path = tmp_path / "document_kb.json"
    _write_reference_kb(kb_path)
    index_dir = tmp_path / "index"
    build_local_index(
        kb_path,
        index_dir,
        DeterministicFakeEmbeddingProvider(dimension=8),
    )
    return index_dir


def _fake_args(index_dir: Path, *, top_k: int = 5, query: str = "出願資格") -> list[str]:
    return [
        str(index_dir),
        "--current-kb",
        str(index_dir.parent / "document_kb.json"),
        "--query",
        query,
        "--top-k",
        str(top_k),
        "--provider",
        "deterministic-fake",
        "--dimension",
        "8",
    ]


def _hybrid_args(
    index_dir: Path,
    *,
    top_k: int = 5,
    candidate_k: int | None = None,
    query: str = "出願資格",
) -> list[str]:
    args = [*_fake_args(index_dir, top_k=top_k, query=query), "--retrieval-mode", "hybrid"]
    if candidate_k is not None:
        args.extend(("--candidate-k", str(candidate_k)))
    return args


def _metadata_args(index_dir: Path, *options: str, top_k: int = 2) -> list[str]:
    return [*_hybrid_args(index_dir, top_k=top_k, candidate_k=2), *options]


def _set_index_identity(
    index_dir: Path,
    *,
    provider: str,
    model: str,
    revision: str | None,
) -> None:
    manifest_path = index_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["embedding_provider"] = provider
    manifest["embedding_model"] = model
    manifest["embedding_revision"] = revision
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="",
    )


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
    assert summary["freshness"] == {
        "fresh": True,
        "current_kb_sha256": summary["source_kb_sha256"],
        "checked_fields": [
            "source_kb_sha256",
            "document_id",
            "source_pdf_sha256",
            "embedding_provider",
            "embedding_model",
            "embedding_revision",
            "embedding_dimension",
        ],
    }
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


def test_hybrid_cli_matches_library_and_reports_reproducible_depths(
    tmp_path: Path,
    capsys,
) -> None:
    index_dir = _build_fake_index(tmp_path)
    before = {path.name: path.read_bytes() for path in index_dir.iterdir()}

    search_cli.main(_hybrid_args(index_dir, top_k=2, candidate_k=2))

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    expected = search_hybrid_index(
        load_local_index(index_dir, mmap=True),
        "出願資格",
        DeterministicFakeEmbeddingProvider(dimension=8),
        top_k=2,
        candidate_k=2,
    )
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    assert summary["retrieval_mode"] == "hybrid"
    assert summary["semantic"] is False
    assert summary["fusion_version"] == "rrf-v1"
    assert summary["rrf_k"] == 60
    assert summary["top_k_requested"] == 2
    assert summary["candidate_k_requested"] == 2
    assert summary["candidate_k_resolved"] == 2
    assert summary["vector_candidate_count"] == 2
    assert 0 < summary["lexical_candidate_count"] <= 2
    assert summary["results"] == [hit.to_dict() for hit in expected.hits]
    assert all(hit["source_pages"] and hit["section_path"] for hit in summary["results"])
    assert all(hit["matched_channels"] for hit in summary["results"])
    assert {path.name: path.read_bytes() for path in index_dir.iterdir()} == before


def test_hybrid_reference_expansion_is_opt_in_and_keeps_base_results(
    tmp_path: Path, capsys
) -> None:
    index_dir = _build_reference_index(tmp_path)
    base_args = _metadata_args(
        index_dir,
        "--filter-fact-type",
        "eligibility",
        top_k=1,
    )

    search_cli.main(base_args)
    without_expansion = json.loads(capsys.readouterr().out)
    search_cli.main([*base_args, "--expand-references"])
    with_expansion = json.loads(capsys.readouterr().out)

    assert "reference_expansion" not in without_expansion
    expansion = with_expansion.pop("reference_expansion")
    assert with_expansion == without_expansion
    assert expansion["max_depth"] == 1
    assert expansion["resolved_relation_count"] == 1
    assert expansion["unique_expanded_target_count"] == 1
    assert expansion["expanded_targets"][0]["fact_id"] == "fact:00001"
    assert expansion["candidate_expansions"][0]["claims"][0]["disposition"] == "attached_target"


def test_reference_expansion_reads_current_kb_once(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_dir = _build_reference_index(tmp_path)
    kb_path = index_dir.parent / "document_kb.json"
    original_read_bytes = Path.read_bytes
    reads = 0

    def counting_read_bytes(path: Path) -> bytes:
        nonlocal reads
        if path.resolve() == kb_path.resolve():
            reads += 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", counting_read_bytes)
    search_cli.main([*_hybrid_args(index_dir, top_k=1), "--expand-references"])

    assert json.loads(capsys.readouterr().out)["reference_expansion"]
    assert reads == 1


def test_vector_mode_rejects_reference_expansion_before_provider(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_dir = _build_fake_index(tmp_path)
    monkeypatch.setattr(
        search_cli,
        "create_provider",
        lambda _configuration: (_ for _ in ()).throw(
            AssertionError("invalid expansion mode must fail before provider construction")
        ),
    )

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main([*_fake_args(index_dir), "--expand-references"])

    error = json.loads(capsys.readouterr().err)
    assert captured_exit.value.code == 2
    assert error["kind"] == "configuration_error"
    assert "hybrid" in error["error"]


def test_reference_expansion_failure_is_structured_json(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_dir = _build_fake_index(tmp_path)
    monkeypatch.setattr(
        search_cli,
        "expand_references",
        lambda *_args: (_ for _ in ()).throw(
            search_cli.ReferenceExpansionError("alignment failed")
        ),
    )

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main([*_hybrid_args(index_dir), "--expand-references"])

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["kind"] == "reference_expansion_error"


def test_evidence_pack_output_is_explicit_hybrid_only_canonical_handoff(
    tmp_path: Path, capsys
) -> None:
    index_dir = _build_reference_index(tmp_path)
    args = [
        *_metadata_args(
            index_dir,
            "--filter-fact-type",
            "eligibility",
            top_k=1,
        ),
        "--output-format",
        "evidence-pack",
    ]

    search_cli.main(args)

    captured = capsys.readouterr()
    pack = json.loads(captured.out)
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    assert pack["schema_version"] == "1.0"
    assert pack["request"]["query"] == "出願資格"
    assert pack["request"]["retrieval_mode"] == "hybrid"
    assert pack["primary_evidence"][0]["fact_id"] == "fact:00000"
    assert pack["attached_reference_evidence"][0]["fact_id"] == "fact:00001"
    assert pack["resolved_relations"][0]["disposition"] == "attached_target"
    assert pack["counts"]["unique_evidence_count"] == 2
    assert "results" not in pack
    assert "freshness" not in pack


def test_evidence_pack_reads_current_kb_once(tmp_path: Path, capsys, monkeypatch) -> None:
    index_dir = _build_reference_index(tmp_path)
    kb_path = index_dir.parent / "document_kb.json"
    original_read_bytes = Path.read_bytes
    reads = 0

    def counting_read_bytes(path: Path) -> bytes:
        nonlocal reads
        if path.resolve() == kb_path.resolve():
            reads += 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", counting_read_bytes)
    search_cli.main([*_hybrid_args(index_dir, top_k=1), "--output-format", "evidence-pack"])

    assert json.loads(capsys.readouterr().out)["schema_version"] == "1.0"
    assert reads == 1


@pytest.mark.parametrize(
    "extra_args",
    (
        ("--output-format", "evidence-pack"),
        (
            "--retrieval-mode",
            "hybrid",
            "--output-format",
            "evidence-pack",
            "--expand-references",
        ),
    ),
)
def test_evidence_pack_rejects_vector_and_duplicate_expansion_before_provider(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch, extra_args: tuple[str, ...]
) -> None:
    index_dir = _build_fake_index(tmp_path)
    monkeypatch.setattr(
        search_cli,
        "create_provider",
        lambda _configuration: (_ for _ in ()).throw(
            AssertionError("invalid pack configuration must fail before provider construction")
        ),
    )

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main([*_fake_args(index_dir), *extra_args])

    error = json.loads(capsys.readouterr().err)
    assert captured_exit.value.code == 2
    assert error["kind"] == "configuration_error"


def test_evidence_pack_failure_is_structured_without_query_echo(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_dir = _build_fake_index(tmp_path)
    monkeypatch.setattr(
        search_cli,
        "build_evidence_pack",
        lambda *_args: (_ for _ in ()).throw(search_cli.EvidencePackError("pack failed")),
    )

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(
            [
                *_hybrid_args(index_dir, query="SECRET-QUERY"),
                "--output-format",
                "evidence-pack",
            ]
        )

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["kind"] == "evidence_pack_error"
    assert "SECRET-QUERY" not in captured.err


def test_vector_mode_rejects_candidate_k_without_constructing_provider(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = _build_fake_index(tmp_path)
    monkeypatch.setattr(
        search_cli,
        "create_provider",
        lambda _configuration: (_ for _ in ()).throw(
            AssertionError("invalid mode options must fail before provider construction")
        ),
    )

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main([*_fake_args(index_dir), "--candidate-k", "10"])

    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert error["kind"] == "configuration_error"
    assert "requires --retrieval-mode hybrid" in error["error"]


def test_hybrid_candidate_depth_error_is_structured_and_pre_provider(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = _build_fake_index(tmp_path)
    monkeypatch.setattr(
        search_cli,
        "create_provider",
        lambda _configuration: (_ for _ in ()).throw(
            AssertionError("invalid depth must fail before provider construction")
        ),
    )

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(_hybrid_args(index_dir, top_k=5, candidate_k=4))

    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert error["kind"] == "configuration_error"
    assert "greater than or equal" in error["error"]


def test_hybrid_fusion_failure_is_structured_json(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = _build_fake_index(tmp_path)
    monkeypatch.setattr(
        search_cli,
        "search_hybrid_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(HybridFusionError("bad channel rows")),
    )

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(_hybrid_args(index_dir))

    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert error == {
        "error": "bad channel rows",
        "kind": "fusion_error",
        "provider": "deterministic-fake",
    }


def test_hybrid_cli_loads_constructs_and_embeds_once(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = _build_fake_index(tmp_path)
    original_load = search_cli.load_local_index
    inner_provider = DeterministicFakeEmbeddingProvider(dimension=8)
    load_calls: list[tuple[object, bool]] = []
    provider_calls: list[object] = []
    query_calls: list[str] = []

    class RecordingProvider:
        identity = inner_provider.identity

        def embed_documents(self, texts):
            raise AssertionError("search must not embed documents")

        def embed_query(self, text):
            query_calls.append(text)
            return inner_provider.embed_query(text)

    def recording_load(path, *, mmap):
        load_calls.append((path, mmap))
        return original_load(path, mmap=mmap)

    def recording_create(configuration):
        provider_calls.append(configuration)
        return RecordingProvider()

    monkeypatch.setattr(search_cli, "load_local_index", recording_load)
    monkeypatch.setattr(search_cli, "create_provider", recording_create)

    search_cli.main(_hybrid_args(index_dir, top_k=1, candidate_k=2))

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["retrieval_mode"] == "hybrid"
    assert load_calls == [(str(index_dir), True)]
    assert len(provider_calls) == 1
    assert query_calls == ["出願資格"]


def test_metadata_cli_filters_and_reports_exact_scope_boosts(tmp_path: Path, capsys) -> None:
    index_dir = _build_fake_index(tmp_path)
    before = {path.name: path.read_bytes() for path in index_dir.iterdir()}

    search_cli.main(
        _metadata_args(
            index_dir,
            "--filter-fact-type",
            "eligibility",
            "--filter-scope-type",
            "department",
            "--filter-scope-target",
            "情報工学系",
            "--filter-parent-college",
            "情報理工学院",
            "--prefer-scope-target",
            "情報工学系",
            "--prefer-parent-college",
            "情報理工学院",
            top_k=1,
        )
    )

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert captured.err == ""
    assert summary["retrieval_mode"] == "hybrid"
    assert summary["metadata_aware"] is True
    assert summary["metadata_filter_version"] == "exact-metadata-v1"
    assert summary["scope_rerank_version"] == "scope-match-v1"
    assert summary["fusion_version"] == "rrf-v1"
    assert summary["rrf_k"] == 60
    assert summary["corpus_row_count"] == 2
    assert summary["eligible_row_count"] == 1
    assert summary["vector_candidate_count"] == 1
    assert summary["lexical_candidate_count"] == 1
    assert summary["result_count"] == 1
    assert summary["requested_filter"] == {
        "fact_types": ["eligibility"],
        "scope_types": ["department"],
        "scope_targets": ["情報工学系"],
        "parent_colleges": ["情報理工学院"],
    }
    hit = summary["results"][0]
    assert hit["fact_type"] == "eligibility"
    assert hit["scope_type"] == "department"
    assert hit["scope_targets"] == ["情報工学系"]
    assert hit["parent_college"] == "情報理工学院"
    assert hit["matched_preferences"] == ["scope_target", "parent_college"]
    assert hit["matched_scope_targets"] == ["情報工学系"]
    assert hit["matched_parent_college"] == "情報理工学院"
    assert hit["scope_boost_total"] == pytest.approx(1.5 / 61)
    assert hit["ranking_score"] == pytest.approx(hit["fused_score"] + 1.5 / 61)
    assert {path.name: path.read_bytes() for path in index_dir.iterdir()} == before


def test_metadata_cli_valid_zero_match_is_successful_empty_json(tmp_path: Path, capsys) -> None:
    index_dir = _build_fake_index(tmp_path)

    search_cli.main(_metadata_args(index_dir, "--filter-fact-type", "not-present", top_k=1))

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert captured.err == ""
    assert summary["eligible_row_count"] == 0
    assert summary["vector_candidate_count"] == 0
    assert summary["lexical_candidate_count"] == 0
    assert summary["result_count"] == 0
    assert summary["results"] == []


@pytest.mark.parametrize(
    "option",
    (
        "--filter-fact-type",
        "--filter-scope-type",
        "--filter-scope-target",
        "--filter-parent-college",
        "--prefer-scope-target",
        "--prefer-parent-college",
    ),
)
def test_vector_cli_rejects_every_metadata_option_before_provider(
    option: str,
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = _build_fake_index(tmp_path)
    monkeypatch.setattr(
        search_cli,
        "create_provider",
        lambda _configuration: (_ for _ in ()).throw(
            AssertionError("metadata mode error must precede provider construction")
        ),
    )

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main([*_fake_args(index_dir), option, "exact-value"])

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["kind"] == "configuration_error"


def test_metadata_cli_invalid_scope_and_duplicates_are_configuration_errors(
    tmp_path: Path,
    capsys,
) -> None:
    index_dir = _build_fake_index(tmp_path)

    for args in (
        _metadata_args(index_dir, "--filter-scope-type", "course"),
        _metadata_args(
            index_dir,
            "--prefer-scope-target",
            "情報工学系",
            "--prefer-scope-target",
            "情報工学系",
        ),
    ):
        with pytest.raises(SystemExit) as captured_exit:
            search_cli.main(args)
        captured = capsys.readouterr()
        assert captured_exit.value.code == 2
        assert captured.out == ""
        assert json.loads(captured.err)["kind"] == "configuration_error"


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
    index_dir = _build_fake_index(tmp_path, dimension=1024)
    _set_index_identity(
        index_dir,
        provider="sentence-transformers",
        model="BAAI/bge-m3",
        revision=REVISION,
    )
    captured = {}

    class RuntimeProvider:
        identity = EmbeddingIdentity("sentence-transformers", "BAAI/bge-m3", REVISION, 1024)

        def embed_documents(self, texts):
            raise AssertionError

        def embed_query(self, text):
            captured["query"] = text
            return [1.0] * 1024

    def fake_create(configuration):
        captured["configuration"] = configuration
        return RuntimeProvider()

    monkeypatch.setattr(search_cli, "create_provider", fake_create)
    args = [
        str(index_dir),
        "--current-kb",
        str(tmp_path / "document_kb.json"),
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

    config = captured["configuration"].sentence_transformer_config
    assert config.model_name == "BAAI/bge-m3"
    assert config.revision == REVISION
    assert config.expected_dimension == 1024
    assert config.batch_size == 4
    assert config.cache_folder == "private-cache"
    assert config.allow_download is allow_download
    assert captured["query"] == "query"
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


def test_declared_identity_mismatch_is_stale_without_query_echo(tmp_path: Path, capsys) -> None:
    index_dir = _build_fake_index(tmp_path)
    sentinel = "SENTINEL-RAW-QUERY"

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(
            [
                str(index_dir),
                "--current-kb",
                str(tmp_path / "document_kb.json"),
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
    error = json.loads(captured.err)
    assert error["kind"] == "stale_index"
    assert error["mismatches"] == ["embedding_dimension"]
    assert sentinel not in captured.err


def test_stale_kb_fails_before_runtime_provider_creation_without_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    index_dir = _build_fake_index(tmp_path)
    kb_path = tmp_path / "document_kb.json"
    kb_path.write_bytes(kb_path.read_bytes() + b" \n")
    before_kb = kb_path.read_bytes()
    before_index = {path.name: path.read_bytes() for path in index_dir.iterdir()}
    monkeypatch.setattr(
        search_cli,
        "create_provider",
        lambda _configuration: (_ for _ in ()).throw(
            AssertionError("runtime provider must not be constructed for stale input")
        ),
    )

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(_fake_args(index_dir, query="SENTINEL-RAW-QUERY"))

    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert error == {
        "error": "index is stale",
        "kind": "stale_index",
        "provider": "deterministic-fake",
        "mismatches": ["source_kb_sha256"],
    }
    assert "SENTINEL" not in captured.err
    assert kb_path.read_bytes() == before_kb
    assert {path.name: path.read_bytes() for path in index_dir.iterdir()} == before_index


def test_invalid_current_kb_fails_before_runtime_provider_creation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    index_dir = _build_fake_index(tmp_path)
    kb_path = tmp_path / "document_kb.json"
    kb_path.write_text("SENTINEL-ADMISSION-TEXT", encoding="utf-8")
    monkeypatch.setattr(
        search_cli,
        "create_provider",
        lambda _configuration: (_ for _ in ()).throw(
            AssertionError("runtime provider must not be constructed for invalid KB")
        ),
    )

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(_fake_args(index_dir))

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["kind"] == "current_kb_error"
    assert "SENTINEL" not in captured.err


def test_fresh_declared_identity_still_checks_runtime_identity_before_embedding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    index_dir = _build_fake_index(tmp_path)
    query_calls = []

    class MismatchedRuntimeProvider:
        identity = EmbeddingIdentity("deterministic-fake", "other-runtime", None, 8)

        def embed_documents(self, texts):
            raise AssertionError

        def embed_query(self, text):
            query_calls.append(text)
            return [1.0] * 8

    monkeypatch.setattr(
        search_cli,
        "create_provider",
        lambda _configuration: MismatchedRuntimeProvider(),
    )

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(_fake_args(index_dir, query="SENTINEL-RAW-QUERY"))

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["kind"] == "search_error"
    assert query_calls == []
    assert "SENTINEL" not in captured.err


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
                "--current-kb",
                str(tmp_path / "document_kb.json"),
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
    _set_index_identity(
        index_dir,
        provider="sentence-transformers",
        model="BAAI/bge-m3",
        revision=REVISION,
    )
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(
            [
                str(index_dir),
                "--current-kb",
                str(tmp_path / "document_kb.json"),
                "--query",
                "query",
                "--provider",
                "sentence-transformers",
                "--model",
                "BAAI/bge-m3",
                "--revision",
                REVISION,
                "--dimension",
                "8",
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
    args[6] = bad_top_k

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(args)

    assert captured_exit.value.code == 2
    assert capsys.readouterr().out == ""


def test_current_kb_is_required_by_argparse(tmp_path: Path, capsys) -> None:
    index_dir = _build_fake_index(tmp_path)

    with pytest.raises(SystemExit) as captured_exit:
        search_cli.main(
            [
                str(index_dir),
                "--query",
                "query",
                "--provider",
                "deterministic-fake",
                "--dimension",
                "8",
            ]
        )

    assert captured_exit.value.code == 2
    assert capsys.readouterr().out == ""


def test_unexpected_programming_error_is_not_disguised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    index_dir = _build_fake_index(tmp_path)
    monkeypatch.setattr(
        search_cli,
        "search_loaded_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bug")),
    )

    with pytest.raises(RuntimeError, match="bug"):
        search_cli.main(
            [
                str(index_dir),
                "--current-kb",
                str(tmp_path / "document_kb.json"),
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
        suffix = ".exe" if os.name == "nt" else ""
        executable = Path(sys.executable).with_name(f"jgrad-search{suffix}")
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
