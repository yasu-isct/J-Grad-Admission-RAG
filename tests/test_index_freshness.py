from __future__ import annotations

import json
import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from jgrad_admission_rag.retrieval.embedding import (
    DeterministicFakeEmbeddingProvider,
    EmbeddingIdentity,
)
from jgrad_admission_rag.retrieval.index_freshness import (
    FRESHNESS_CHECKED_FIELDS,
    CurrentKbInputError,
    StaleIndexError,
    check_index_freshness,
    load_fresh_index_context,
)
from jgrad_admission_rag.retrieval.local_index import build_local_index, load_local_index
from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    QualityGateResult,
    RetrievalUnit,
    ScopedFact,
)

PDF_HASH = "b" * 64
FAKE_IDENTITY = EmbeddingIdentity("deterministic-fake", "sha256-counter-v1", None, 8)


def _knowledge_base(
    *,
    document_id: str = "sample-document",
    pdf_hash: str = PDF_HASH,
    schema_version: str = "0.5",
    passed: bool = True,
) -> DocumentKnowledgeBase:
    fact = ScopedFact(
        fact_id="fact:00000",
        fact_type="eligibility",
        scope_type="global",
        title="出願資格",
        text="出願資格の本文",
        source_pages=[1],
        section_path=["出願資格"],
        embedding_text="canonical 出願資格",
        metadata={"embedding_text_version": "1"},
    )
    unit = RetrievalUnit(
        unit_id="unit:00000",
        fact_id=fact.fact_id,
        text=fact.embedding_text,
        source_pages=[1],
        section_path=["出願資格"],
        metadata={"embedding_text_version": "1"},
    )
    return DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            document_id=document_id,
            source_pdf="sample.pdf",
            pdf_sha256=pdf_hash,
            schema_version=schema_version,
            chunk_count=1,
        ),
        facts=[fact],
        retrieval_units=[unit],
        diagnostics=BuildDiagnostics(quality_gate=QualityGateResult(passed=passed)),
    )


def _write_kb(path: Path, kb: DocumentKnowledgeBase | None = None) -> bytes:
    raw = (
        json.dumps(
            (kb or _knowledge_base()).model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(raw)
    return raw


def _build(tmp_path: Path):
    kb_path = tmp_path / "document_kb.json"
    _write_kb(kb_path)
    index_dir = tmp_path / "index"
    build_local_index(kb_path, index_dir, DeterministicFakeEmbeddingProvider(dimension=8))
    return kb_path, index_dir, load_local_index(index_dir, mmap=True)


def test_exact_unchanged_bytes_and_identity_report_fresh_deterministically(
    tmp_path: Path,
) -> None:
    kb_path, _index_dir, index = _build(tmp_path)

    first = check_index_freshness(index, kb_path, FAKE_IDENTITY)
    second = check_index_freshness(index.manifest, kb_path, FAKE_IDENTITY)

    assert first == second
    assert first.fresh is True
    assert first.current_kb_sha256 == index.manifest.source_kb_sha256
    assert first.checked_fields == FRESHNESS_CHECKED_FIELDS
    with pytest.raises(FrozenInstanceError):
        first.fresh = False


def test_fresh_context_reuses_report_and_returns_detached_validated_kb(tmp_path: Path) -> None:
    kb_path, _index_dir, index = _build(tmp_path)

    context = load_fresh_index_context(index, kb_path, FAKE_IDENTITY)
    second = load_fresh_index_context(index, kb_path, FAKE_IDENTITY)

    assert context.freshness == check_index_freshness(index, kb_path, FAKE_IDENTITY)
    assert context.knowledge_base == _knowledge_base()
    context.knowledge_base.facts[0].text = "changed"
    assert second.knowledge_base.facts[0].text == "出願資格の本文"
    assert b"changed" not in kb_path.read_bytes()
    with pytest.raises(FrozenInstanceError):
        context.freshness = second.freshness


def test_whitespace_only_byte_change_is_stale_without_mutation(tmp_path: Path) -> None:
    kb_path, index_dir, index = _build(tmp_path)
    kb_path.write_bytes(kb_path.read_bytes() + b" \n")
    before_kb = kb_path.read_bytes()
    before_index = {path.name: path.read_bytes() for path in index_dir.iterdir()}

    with pytest.raises(StaleIndexError) as captured:
        check_index_freshness(index, kb_path, FAKE_IDENTITY)

    assert captured.value.mismatches == ("source_kb_sha256",)
    assert kb_path.read_bytes() == before_kb
    assert {path.name: path.read_bytes() for path in index_dir.iterdir()} == before_index


def test_all_source_and_provider_mismatches_are_reported_in_stable_order(
    tmp_path: Path,
) -> None:
    kb_path, _index_dir, index = _build(tmp_path)
    _write_kb(
        kb_path,
        _knowledge_base(document_id="other-document", pdf_hash="c" * 64),
    )
    identity = EmbeddingIdentity("other-provider", "other-model", "r2", 9)

    with pytest.raises(StaleIndexError) as captured:
        check_index_freshness(index, kb_path, identity)

    assert captured.value.mismatches == FRESHNESS_CHECKED_FIELDS
    assert "other-document" not in str(captured.value)


@pytest.mark.parametrize(
    ("identity", "code"),
    [
        (EmbeddingIdentity("other", "sha256-counter-v1", None, 8), "embedding_provider"),
        (EmbeddingIdentity("deterministic-fake", "other", None, 8), "embedding_model"),
        (
            EmbeddingIdentity("deterministic-fake", "sha256-counter-v1", "r1", 8),
            "embedding_revision",
        ),
        (
            EmbeddingIdentity("deterministic-fake", "sha256-counter-v1", None, 9),
            "embedding_dimension",
        ),
    ],
)
def test_each_declared_provider_mismatch_has_one_stable_code(
    tmp_path: Path, identity: EmbeddingIdentity, code: str
) -> None:
    kb_path, _index_dir, index = _build(tmp_path)

    with pytest.raises(StaleIndexError) as captured:
        check_index_freshness(index, kb_path, identity)

    assert captured.value.mismatches == (code,)


@pytest.mark.parametrize("case", ["missing", "malformed", "unsupported", "failed_gate"])
def test_invalid_current_kb_is_not_classified_as_stale(tmp_path: Path, case: str) -> None:
    kb_path, _index_dir, index = _build(tmp_path)
    if case == "missing":
        kb_path.unlink()
    elif case == "malformed":
        kb_path.write_text("SENTINEL-ADMISSION-TEXT", encoding="utf-8")
    elif case == "unsupported":
        _write_kb(kb_path, _knowledge_base(schema_version="0.4"))
    else:
        _write_kb(kb_path, _knowledge_base(passed=False))

    with pytest.raises(CurrentKbInputError) as captured:
        check_index_freshness(index, kb_path, FAKE_IDENTITY)

    assert "SENTINEL" not in str(captured.value)


def test_symlinked_current_kb_is_rejected(tmp_path: Path) -> None:
    kb_path, _index_dir, index = _build(tmp_path)
    link = tmp_path / "linked-kb.json"
    try:
        os.symlink(kb_path, link)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    with pytest.raises(CurrentKbInputError, match="non-symlink"):
        check_index_freshness(index, link, FAKE_IDENTITY)


def test_current_kb_bytes_are_read_exactly_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    kb_path, _index_dir, index = _build(tmp_path)
    original = Path.read_bytes
    calls = 0

    def counted(path: Path):
        nonlocal calls
        if path == kb_path:
            calls += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted)

    check_index_freshness(index, kb_path, FAKE_IDENTITY)

    assert calls == 1


def test_unexpected_index_type_is_not_disguised(tmp_path: Path) -> None:
    kb_path = tmp_path / "document_kb.json"
    _write_kb(kb_path)

    with pytest.raises(TypeError, match="IndexManifest or LocalVectorIndex"):
        check_index_freshness(object(), kb_path, FAKE_IDENTITY)
