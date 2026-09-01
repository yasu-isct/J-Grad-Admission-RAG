from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Sequence

import numpy as np
import pytest

import jgrad_admission_rag.retrieval.local_index as local_index_module
from jgrad_admission_rag.retrieval.embedding import EmbeddingIdentity
from jgrad_admission_rag.retrieval.local_index import (
    MANIFEST_FILENAME,
    PAYLOADS_FILENAME,
    VECTORS_FILENAME,
    IndexBuildError,
    IndexLoadError,
    build_local_index,
    load_local_index,
)
from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    QualityGateResult,
    RetrievalUnit,
    ScopedFact,
)

PDF_HASH = "b" * 64


class StaticProvider:
    def __init__(self, vectors, *, dimension: int = 3, error: Exception | None = None):
        self.identity = EmbeddingIdentity("static", "test-vectors", "r1", dimension)
        self.vectors = vectors
        self.error = error
        self.calls: list[list[str]] = []

    def embed_documents(self, texts: Sequence[str]):
        self.calls.append(list(texts))
        if self.error:
            raise self.error
        return deepcopy(self.vectors)

    def embed_query(self, text: str):
        raise NotImplementedError


def _kb(*, empty: bool = False, passed: bool = True, schema_version: str = "0.5"):
    facts = []
    units = []
    if not empty:
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
            source_pdf="not-serialized-as-index-path.pdf",
            pdf_sha256=PDF_HASH,
            schema_version=schema_version,
            chunk_count=len(facts),
        ),
        facts=facts,
        retrieval_units=units,
        diagnostics=BuildDiagnostics(quality_gate=QualityGateResult(passed=passed)),
    )


def _write_kb(path: Path, kb: DocumentKnowledgeBase | None = None) -> bytes:
    raw = (
        json.dumps(
            (kb or _kb()).model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(raw)
    return raw


def _build(tmp_path: Path, *, vectors=None, kb: DocumentKnowledgeBase | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    kb_path = tmp_path / "document_kb.json"
    raw = _write_kb(kb_path, kb)
    output = tmp_path / "index"
    provider = StaticProvider(vectors or [[3.0, 4.0, 0.0], [0.0, 0.0, 2.0]])
    manifest = build_local_index(kb_path, output, provider)
    return raw, output, provider, manifest


def _read_manifest(index_dir: Path) -> dict:
    return json.loads((index_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))


def _write_manifest(index_dir: Path, manifest: dict) -> None:
    (index_dir / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="",
    )


def _rehash(index_dir: Path, filename: str, manifest_field: str) -> None:
    manifest = _read_manifest(index_dir)
    manifest[manifest_field] = hashlib.sha256((index_dir / filename).read_bytes()).hexdigest()
    _write_manifest(index_dir, manifest)


def _replace_vectors(
    index_dir: Path, array: np.ndarray, *, allow_pickle: bool = False, trailing=b""
):
    with (index_dir / VECTORS_FILENAME).open("wb") as handle:
        np.save(handle, array, allow_pickle=allow_pickle)
        handle.write(trailing)
    _rehash(index_dir, VECTORS_FILENAME, "vectors_sha256")


def test_two_row_build_has_exact_manifest_payload_and_normalized_alignment(tmp_path: Path) -> None:
    raw, output, provider, manifest = _build(tmp_path)

    assert sorted(path.name for path in output.iterdir()) == [
        VECTORS_FILENAME,
        MANIFEST_FILENAME,
        PAYLOADS_FILENAME,
    ]
    assert manifest.source_kb_sha256 == hashlib.sha256(raw).hexdigest()
    assert manifest.source_pdf_sha256 == PDF_HASH
    assert manifest.payload_count == manifest.vector_count == 2
    assert manifest.embedding_dimension == 3
    assert manifest.vector_dtype == "float32"
    assert manifest.distance_metric == "cosine"
    assert manifest.vectors_normalized is True
    assert manifest.embedding_provider == "static"
    assert manifest.embedding_model == "test-vectors"
    assert manifest.embedding_revision == "r1"
    assert provider.calls == [["canonical 出願資格", "canonical 検定料"]]

    payload_lines = (output / PAYLOADS_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(payload_lines) == 2
    assert [json.loads(line)["row_index"] for line in payload_lines] == [0, 1]
    assert [json.loads(line)["unit_id"] for line in payload_lines] == ["unit:00000", "unit:00001"]

    loaded = load_local_index(output, mmap=False)
    np.testing.assert_allclose(
        loaded.vectors,
        np.array([[0.6, 0.8, 0.0], [0.0, 0.0, 1.0]], dtype="<f4"),
        rtol=0,
        atol=1e-7,
    )
    assert loaded.vectors.dtype == np.dtype("<f4")
    assert loaded.vectors.flags.c_contiguous
    assert loaded.vectors.flags.writeable is False
    assert isinstance(loaded.payloads, tuple)


def test_empty_kb_builds_valid_zero_row_matrix(tmp_path: Path) -> None:
    kb_path = tmp_path / "empty.json"
    _write_kb(kb_path, _kb(empty=True))
    output = tmp_path / "empty-index"
    provider = StaticProvider([], dimension=4)

    manifest = build_local_index(kb_path, output, provider)
    loaded = load_local_index(output, mmap=False)

    assert provider.calls == []
    assert manifest.payload_count == 0
    assert manifest.embedding_dimension == 4
    assert loaded.vectors.shape == (0, 4)
    assert loaded.vectors.dtype == np.dtype("<f4")
    assert loaded.payloads == ()


@pytest.mark.parametrize(
    "vectors",
    [
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
        [[float("nan"), 0.0, 0.0], [1.0, 0.0, 0.0]],
        [[float("inf"), 0.0, 0.0], [1.0, 0.0, 0.0]],
        [[1e40, 0.0, 0.0], [1.0, 0.0, 0.0]],
    ],
)
def test_bad_provider_vectors_publish_no_target(tmp_path: Path, vectors) -> None:
    kb_path = tmp_path / "kb.json"
    _write_kb(kb_path)
    output = tmp_path / "index"

    with pytest.raises(IndexBuildError):
        build_local_index(kb_path, output, StaticProvider(vectors))

    assert not output.exists()


@pytest.mark.parametrize(
    "kb_bytes",
    [b"not-json", b'{"manifest":{}}'],
)
def test_invalid_kb_fails_without_target(tmp_path: Path, kb_bytes: bytes) -> None:
    kb_path = tmp_path / "kb.json"
    kb_path.write_bytes(kb_bytes)
    output = tmp_path / "index"

    with pytest.raises(IndexBuildError, match="source KB"):
        build_local_index(kb_path, output, StaticProvider([]))
    assert not output.exists()


def test_unsupported_kb_and_failed_gate_are_rejected(tmp_path: Path) -> None:
    for name, kb in (("old", _kb(schema_version="0.4")), ("failed", _kb(passed=False))):
        kb_path = tmp_path / f"{name}.json"
        _write_kb(kb_path, kb)
        output = tmp_path / f"{name}-index"

        with pytest.raises(IndexBuildError):
            build_local_index(kb_path, output, StaticProvider([]))
        assert not output.exists()


def test_invalid_fact_unit_linkage_is_rejected(tmp_path: Path) -> None:
    kb = _kb()
    kb.retrieval_units[0].fact_id = "fact:missing"
    kb_path = tmp_path / "kb.json"
    _write_kb(kb_path, kb)

    with pytest.raises(IndexBuildError, match="source KB or embedding provider"):
        build_local_index(kb_path, tmp_path / "index", StaticProvider([]))


def test_repeated_builds_are_byte_identical(tmp_path: Path) -> None:
    kb_path = tmp_path / "kb.json"
    _write_kb(kb_path)
    first = tmp_path / "first"
    second = tmp_path / "second"

    build_local_index(kb_path, first, StaticProvider([[3, 4, 0], [0, 0, 2]]))
    build_local_index(kb_path, second, StaticProvider([[3, 4, 0], [0, 0, 2]]))

    for filename in (MANIFEST_FILENAME, PAYLOADS_FILENAME, VECTORS_FILENAME):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()


@pytest.mark.parametrize("target_kind", ["file", "directory"])
def test_existing_target_is_rejected_without_mutation(tmp_path: Path, target_kind: str) -> None:
    kb_path = tmp_path / "kb.json"
    _write_kb(kb_path)
    target = tmp_path / "existing"
    if target_kind == "file":
        target.write_bytes(b"keep-file")
    else:
        target.mkdir()
        (target / "keep.txt").write_bytes(b"keep-directory")
    before = (
        {path.relative_to(target): path.read_bytes() for path in target.rglob("*")}
        if target.is_dir()
        else target.read_bytes()
    )

    with pytest.raises(IndexBuildError, match="already exists"):
        build_local_index(kb_path, target, StaticProvider([]))

    after = (
        {path.relative_to(target): path.read_bytes() for path in target.rglob("*")}
        if target.is_dir()
        else target.read_bytes()
    )
    assert after == before


def test_dangling_output_symlink_is_rejected_without_target_or_staging(tmp_path: Path) -> None:
    kb_path = tmp_path / "kb.json"
    _write_kb(kb_path)
    destination = tmp_path / "missing-destination"
    output_link = tmp_path / "index"
    try:
        output_link.symlink_to(destination, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"platform does not permit test symlink creation: {error}")

    assert output_link.is_symlink()
    assert not output_link.exists()
    original_link_target = output_link.readlink()

    with pytest.raises(IndexBuildError, match="symbolic link"):
        build_local_index(kb_path, output_link, StaticProvider([[1, 0, 0], [0, 1, 0]]))

    assert output_link.is_symlink()
    assert output_link.readlink() == original_link_target
    assert not destination.exists()
    assert list(tmp_path.glob(".index.tmp-*")) == []


def test_raw_output_symlink_check_precedes_absolute_path_and_parent_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_path = tmp_path / "kb.json"
    _write_kb(kb_path)
    requested = tmp_path / "index"
    original_is_symlink = Path.is_symlink
    absolute_calls = []

    def report_requested_symlink(path: Path) -> bool:
        return path == requested or original_is_symlink(path)

    def forbidden_abspath(path) -> str:
        absolute_calls.append(path)
        raise AssertionError("absolute path conversion must not run for an output symlink")

    monkeypatch.setattr(Path, "is_symlink", report_requested_symlink)
    monkeypatch.setattr(local_index_module.os.path, "abspath", forbidden_abspath)

    with pytest.raises(IndexBuildError, match="symbolic link"):
        build_local_index(kb_path, requested, StaticProvider([[1, 0, 0], [0, 1, 0]]))

    assert absolute_calls == []
    assert not requested.exists()
    assert list(tmp_path.glob(".index.tmp-*")) == []


@pytest.mark.parametrize(
    "failure_phase",
    [
        "after_payload_write",
        "after_vector_write",
        "after_manifest_construction",
        "after_validation",
    ],
)
def test_staged_failures_cleanup_only_created_temp_directory(
    tmp_path: Path,
    failure_phase: str,
) -> None:
    kb_path = tmp_path / "kb.json"
    _write_kb(kb_path)
    unrelated = tmp_path / ".index.tmp-unrelated"
    unrelated.mkdir()
    (unrelated / "keep").write_text("keep", encoding="utf-8")
    target = tmp_path / "index"

    def fail(phase: str, _staged: Path) -> None:
        if phase == failure_phase:
            raise RuntimeError("injected failure")

    with pytest.raises(IndexBuildError, match="staging or publication"):
        build_local_index(
            kb_path,
            target,
            StaticProvider([[1, 0, 0], [0, 1, 0]]),
            _failure_hook=fail,
        )

    assert not target.exists()
    assert (unrelated / "keep").read_text(encoding="utf-8") == "keep"
    assert sorted(path.name for path in tmp_path.glob(".index.tmp-*")) == [unrelated.name]


def test_manifest_is_written_last_before_validated_publication(tmp_path: Path) -> None:
    kb_path = tmp_path / "kb.json"
    _write_kb(kb_path)
    observed: dict[str, set[str]] = {}

    def observe(phase: str, staged: Path) -> None:
        observed[phase] = {path.name for path in staged.iterdir()}

    build_local_index(
        kb_path,
        tmp_path / "index",
        StaticProvider([[1, 0, 0], [0, 1, 0]]),
        _failure_hook=observe,
    )

    assert observed == {
        "after_payload_write": {PAYLOADS_FILENAME},
        "after_vector_write": {PAYLOADS_FILENAME, VECTORS_FILENAME},
        "after_manifest_construction": {PAYLOADS_FILENAME, VECTORS_FILENAME},
        "after_validation": {MANIFEST_FILENAME, PAYLOADS_FILENAME, VECTORS_FILENAME},
    }


def test_atomic_rename_failure_cleans_staging_and_publishes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_path = tmp_path / "kb.json"
    _write_kb(kb_path)
    target = tmp_path / "index"

    def fail_publish(_staged: Path, _target: Path) -> None:
        raise IndexBuildError("injected rename failure")

    monkeypatch.setattr(local_index_module, "_publish_staged_directory", fail_publish)
    with pytest.raises(IndexBuildError, match="rename failure"):
        build_local_index(kb_path, target, StaticProvider([[1, 0, 0], [0, 1, 0]]))

    assert not target.exists()
    assert list(tmp_path.glob(".index.tmp-*")) == []


def test_builder_and_loader_always_disable_pickle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_calls = []
    load_calls = []
    original_save = local_index_module.np.save
    original_load = local_index_module.np.load

    def save(*args, **kwargs):
        save_calls.append(kwargs)
        return original_save(*args, **kwargs)

    def load(*args, **kwargs):
        load_calls.append(kwargs)
        return original_load(*args, **kwargs)

    monkeypatch.setattr(local_index_module.np, "save", save)
    monkeypatch.setattr(local_index_module.np, "load", load)
    _, output, _, _ = _build(tmp_path)
    load_local_index(output, mmap=True)

    assert save_calls and all(call["allow_pickle"] is False for call in save_calls)
    assert load_calls and all(call["allow_pickle"] is False for call in load_calls)


def test_mmap_and_non_mmap_are_equivalent_and_read_only(tmp_path: Path) -> None:
    _, output, _, _ = _build(tmp_path)

    mapped = load_local_index(output, mmap=True)
    memory = load_local_index(output, mmap=False)

    assert isinstance(mapped.vectors, np.memmap)
    assert not mapped.vectors.flags.writeable
    assert not memory.vectors.flags.writeable
    np.testing.assert_array_equal(mapped.vectors, memory.vectors)
    with pytest.raises(ValueError):
        mapped.vectors[0, 0] = 5


@pytest.mark.parametrize(
    ("manifest_value", "message"),
    [
        (b"not-json", "invalid or unsupported"),
        (json.dumps({"extra": True}).encode(), "invalid or unsupported"),
    ],
)
def test_invalid_manifest_is_rejected(tmp_path: Path, manifest_value: bytes, message: str) -> None:
    _, output, _, _ = _build(tmp_path)
    (output / MANIFEST_FILENAME).write_bytes(manifest_value)

    with pytest.raises(IndexLoadError, match=message):
        load_local_index(output)


def test_missing_manifest_is_rejected(tmp_path: Path) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    with pytest.raises(IndexLoadError, match="manifest is missing"):
        load_local_index(index_dir)


@pytest.mark.parametrize(
    ("field", "value"),
    [("index_schema_version", "9.9"), ("source_kb_schema_version", "0.4")],
)
def test_unsupported_manifest_versions_are_rejected(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    _, output, _, _ = _build(tmp_path)
    manifest = _read_manifest(output)
    manifest[field] = value
    _write_manifest(output, manifest)

    with pytest.raises(IndexLoadError, match="invalid or unsupported"):
        load_local_index(output)


@pytest.mark.parametrize("filename", [PAYLOADS_FILENAME, VECTORS_FILENAME])
def test_missing_artifact_is_rejected(tmp_path: Path, filename: str) -> None:
    _, output, _, _ = _build(tmp_path)
    (output / filename).unlink()
    with pytest.raises(IndexLoadError, match="missing"):
        load_local_index(output)


@pytest.mark.parametrize("filename", [PAYLOADS_FILENAME, VECTORS_FILENAME])
def test_tampered_artifact_hash_is_rejected_before_parsing(tmp_path: Path, filename: str) -> None:
    _, output, _, _ = _build(tmp_path)
    with (output / filename).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(IndexLoadError, match="hash mismatch"):
        load_local_index(output)


@pytest.mark.parametrize("mutation", ["blank", "count", "order", "duplicate", "document"])
def test_jsonl_integrity_failures_are_rejected_after_valid_hash(
    tmp_path: Path,
    mutation: str,
) -> None:
    _, output, _, _ = _build(tmp_path)
    payload_path = output / PAYLOADS_FILENAME
    rows = [json.loads(line) for line in payload_path.read_text(encoding="utf-8").splitlines()]
    if mutation == "blank":
        value = json.dumps(rows[0], ensure_ascii=False, separators=(",", ":")) + "\n\n"
    elif mutation == "count":
        value = json.dumps(rows[0], ensure_ascii=False, separators=(",", ":")) + "\n"
    else:
        if mutation == "order":
            rows[0]["row_index"] = 1
        elif mutation == "duplicate":
            rows[1]["unit_id"] = rows[0]["unit_id"]
        elif mutation == "document":
            rows[1]["document_id"] = "different"
        value = "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
        )
    payload_path.write_text(value, encoding="utf-8", newline="")
    _rehash(output, PAYLOADS_FILENAME, "payloads_sha256")

    with pytest.raises(IndexLoadError, match="payload artifact is invalid"):
        load_local_index(output)


@pytest.mark.parametrize(
    "array",
    [
        np.array([[1, 2, 3], [4, 5, 6]], dtype="<f8"),
        np.array([[1, 2, 3], [4, 5, 6]], dtype="<i4"),
        np.array([1, 2, 3], dtype="<f4"),
        np.array([[[1, 2, 3]], [[4, 5, 6]]], dtype="<f4"),
        np.array([[1, 0, 0]], dtype="<f4"),
        np.array([[1, 0, 0], [0, 0, 0]], dtype="<f4"),
        np.array([[1, 0, 0], [0, 2, 0]], dtype="<f4"),
        np.array([[1, 0, 0], [0, float("nan"), 0]], dtype="<f4"),
        np.array([[1, 0, 0], [0, float("inf"), 0]], dtype="<f4"),
    ],
)
def test_invalid_stored_vector_contract_is_rejected(tmp_path: Path, array: np.ndarray) -> None:
    _, output, _, _ = _build(tmp_path)
    _replace_vectors(output, array)

    with pytest.raises(IndexLoadError):
        load_local_index(output)


def test_object_pickle_array_is_rejected(tmp_path: Path) -> None:
    _, output, _, _ = _build(tmp_path)
    _replace_vectors(output, np.array([[object()]], dtype=object), allow_pickle=True)

    with pytest.raises(IndexLoadError, match="safe NumPy array"):
        load_local_index(output)


def test_corrupt_and_trailing_numpy_data_are_rejected(tmp_path: Path) -> None:
    _, corrupt, _, _ = _build(tmp_path / "corrupt")
    (corrupt / VECTORS_FILENAME).write_bytes(b"not-npy")
    _rehash(corrupt, VECTORS_FILENAME, "vectors_sha256")
    with pytest.raises(IndexLoadError, match="safe NumPy array"):
        load_local_index(corrupt)

    _, trailing, _, _ = _build(tmp_path / "trailing")
    vectors = np.array([[0.6, 0.8, 0], [0, 0, 1]], dtype="<f4")
    _replace_vectors(trailing, vectors, trailing=b"extra-array-or-data")
    with pytest.raises(IndexLoadError, match="trailing data"):
        load_local_index(trailing)


def test_unsafe_manifest_basename_is_rejected_before_path_resolution(tmp_path: Path) -> None:
    _, output, _, _ = _build(tmp_path)
    manifest = _read_manifest(output)
    manifest["payloads_filename"] = "../outside.jsonl"
    _write_manifest(output, manifest)

    with pytest.raises(IndexLoadError, match="manifest is invalid"):
        load_local_index(output)


def test_errors_do_not_leak_source_text_or_unrelated_absolute_path(tmp_path: Path) -> None:
    sentinel = "SENTINEL-FULL-ADMISSION-TEXT"
    kb = _kb()
    kb.retrieval_units[0].text = sentinel
    kb_path = tmp_path / "kb.json"
    _write_kb(kb_path, kb)
    private_path = tmp_path / "private-cache-never-log"
    provider = StaticProvider([], error=RuntimeError(str(private_path)))

    with pytest.raises(IndexBuildError) as captured:
        build_local_index(kb_path, tmp_path / "index", provider)

    assert sentinel not in str(captured.value)
    assert str(private_path) not in str(captured.value)
