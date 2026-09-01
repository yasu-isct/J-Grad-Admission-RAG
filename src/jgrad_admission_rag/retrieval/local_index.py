from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import ValidationError

from ..schemas.document_kb import DocumentKnowledgeBase
from ..schemas.index import (
    IndexManifest,
    IndexPayload,
    derive_index_payloads,
    payloads_from_jsonl,
    payloads_to_jsonl,
    validate_manifest_compatibility,
    validate_payload_collection,
    validate_source_kb_compatibility,
)
from .embedding import EmbeddingProvider, embed_documents_checked

INDEX_BUILDER_VERSION = "0.1.0"
MANIFEST_FILENAME = "manifest.json"
PAYLOADS_FILENAME = "payloads.jsonl"
VECTORS_FILENAME = "embeddings.npy"
NORM_ABSOLUTE_TOLERANCE = 1e-5
NUMPY_MAX_HEADER_SIZE = 10_000


class IndexArtifactError(Exception):
    """Base class for local index artifact failures."""


class IndexBuildError(IndexArtifactError):
    """Raised when a local index cannot be built and published safely."""


class IndexLoadError(IndexArtifactError):
    """Raised when an existing local index fails self-integrity validation."""


@dataclass(frozen=True, slots=True)
class LocalVectorIndex:
    manifest: IndexManifest
    payloads: tuple[IndexPayload, ...]
    vectors: np.ndarray


def build_local_index(
    kb_path: str | Path,
    output_dir: str | Path,
    provider: EmbeddingProvider,
    *,
    _failure_hook: Callable[[str, Path], None] | None = None,
) -> IndexManifest:
    """Build, validate, and atomically publish a new local index directory."""

    target = Path(output_dir).resolve(strict=False)
    if target.exists() or target.is_symlink():
        raise IndexBuildError("output target already exists")
    parent = target.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise IndexBuildError("output parent could not be created") from error
    if not parent.is_dir():
        raise IndexBuildError("output parent is not a directory")

    kb, source_kb_sha256 = _read_source_kb(kb_path)
    try:
        validate_source_kb_compatibility(kb)
        if not kb.diagnostics.quality_gate.passed:
            raise IndexBuildError("source KB quality gate did not pass")
        payloads = derive_index_payloads(kb)
        identity = provider.identity
        provider_vectors = embed_documents_checked(provider, [payload.text for payload in payloads])
        vectors = _normalize_vectors(provider_vectors, len(payloads), identity.dimension)
    except IndexBuildError:
        raise
    except Exception as error:
        raise IndexBuildError("source KB or embedding provider validation failed") from error

    prefix = f".{target.name}.tmp-"
    try:
        staged = Path(tempfile.mkdtemp(prefix=prefix, dir=parent)).resolve()
    except OSError as error:
        raise IndexBuildError("local index staging directory could not be created") from error
    try:
        payload_path = staged / PAYLOADS_FILENAME
        payload_path.write_text(payloads_to_jsonl(payloads), encoding="utf-8", newline="")
        _call_failure_hook(_failure_hook, "after_payload_write", staged)

        vector_path = staged / VECTORS_FILENAME
        with vector_path.open("wb") as handle:
            np.save(handle, vectors, allow_pickle=False)
        _call_failure_hook(_failure_hook, "after_vector_write", staged)

        manifest = IndexManifest(
            source_kb_schema_version=kb.manifest.schema_version,
            document_id=kb.manifest.document_id,
            source_kb_sha256=source_kb_sha256,
            source_pdf_sha256=kb.manifest.pdf_sha256,
            payload_count=len(payloads),
            vector_count=vectors.shape[0],
            embedding_dimension=vectors.shape[1],
            vectors_normalized=True,
            embedding_provider=identity.provider,
            embedding_model=identity.model,
            embedding_revision=identity.revision,
            payloads_filename=PAYLOADS_FILENAME,
            vectors_filename=VECTORS_FILENAME,
            payloads_sha256=_sha256_file(payload_path),
            vectors_sha256=_sha256_file(vector_path),
            builder_version=INDEX_BUILDER_VERSION,
        )
        _call_failure_hook(_failure_hook, "after_manifest_construction", staged)

        manifest_path = staged / MANIFEST_FILENAME
        manifest_path.write_text(_serialize_manifest(manifest), encoding="utf-8", newline="")
        load_local_index(staged, mmap=False)
        _call_failure_hook(_failure_hook, "after_validation", staged)
        _publish_staged_directory(staged, target)
        return manifest
    except Exception as error:
        _cleanup_staged_directory(staged, parent, prefix)
        if isinstance(error, IndexBuildError):
            raise
        raise IndexBuildError("local index staging or publication failed") from error


def load_local_index(index_dir: str | Path, *, mmap: bool = True) -> LocalVectorIndex:
    """Load an index after validating only its current on-disk self-integrity."""

    index_path = Path(index_dir)
    manifest_path = index_path / MANIFEST_FILENAME
    if not _is_regular_file(manifest_path):
        raise IndexLoadError("index manifest is missing or is not a regular file")
    try:
        manifest = IndexManifest.model_validate_json(manifest_path.read_bytes())
        validate_manifest_compatibility(manifest)
    except (OSError, ValueError, ValidationError) as error:
        raise IndexLoadError("index manifest is invalid or unsupported") from error

    payload_path = index_path / manifest.payloads_filename
    vector_path = index_path / manifest.vectors_filename
    if not _is_regular_file(payload_path):
        raise IndexLoadError("index payload artifact is missing or is not a regular file")
    if not _is_regular_file(vector_path):
        raise IndexLoadError("index vector artifact is missing or is not a regular file")
    try:
        if _sha256_file(payload_path) != manifest.payloads_sha256:
            raise IndexLoadError("index payload artifact hash mismatch")
        if _sha256_file(vector_path) != manifest.vectors_sha256:
            raise IndexLoadError("index vector artifact hash mismatch")
    except IndexLoadError:
        raise
    except OSError as error:
        raise IndexLoadError("index artifact could not be hashed") from error

    try:
        payloads = payloads_from_jsonl(payload_path.read_text(encoding="utf-8"))
        validate_payload_collection(manifest, payloads)
    except (OSError, UnicodeError, ValueError) as error:
        raise IndexLoadError("index payload artifact is invalid") from error

    vectors = _load_exact_numpy_array(vector_path, mmap=mmap)
    _validate_stored_vectors(vectors, manifest)
    vectors.setflags(write=False)
    return LocalVectorIndex(
        manifest=manifest,
        payloads=tuple(payload.model_copy(deep=True) for payload in payloads),
        vectors=vectors,
    )


def _read_source_kb(kb_path: str | Path) -> tuple[DocumentKnowledgeBase, str]:
    path = Path(kb_path)
    if not _is_regular_file(path):
        raise IndexBuildError("source KB is missing or is not a regular file")
    try:
        raw_bytes = path.read_bytes()
        kb = DocumentKnowledgeBase.model_validate_json(raw_bytes)
    except (OSError, ValueError, ValidationError) as error:
        raise IndexBuildError("source KB is not valid UTF-8 DocumentKnowledgeBase JSON") from error
    return kb, hashlib.sha256(raw_bytes).hexdigest()


def _normalize_vectors(
    values: list[list[float]],
    row_count: int,
    dimension: int,
) -> np.ndarray:
    if row_count == 0:
        return np.empty((0, dimension), dtype=np.dtype("<f4"), order="C")
    try:
        with np.errstate(over="ignore", invalid="ignore"):
            float32_values = np.asarray(values, dtype=np.dtype("<f4"), order="C")
    except (TypeError, ValueError, OverflowError) as error:
        raise IndexBuildError("embedding vectors could not be converted to float32") from error
    if float32_values.shape != (row_count, dimension):
        raise IndexBuildError("embedding vector matrix shape does not match payloads and identity")
    if not np.isfinite(float32_values).all():
        raise IndexBuildError("embedding vectors became non-finite during float32 conversion")

    float64_values = float32_values.astype(np.float64)
    norms = np.sqrt(np.sum(float64_values * float64_values, axis=1, dtype=np.float64))
    if not np.isfinite(norms).all() or np.any(norms == 0.0):
        raise IndexBuildError("embedding vectors contain zero or non-finite L2 norms")
    normalized = np.asarray(float64_values / norms[:, None], dtype=np.dtype("<f4"), order="C")
    stored_norms = np.sqrt(np.sum(normalized.astype(np.float64) ** 2, axis=1, dtype=np.float64))
    if not np.isfinite(normalized).all() or not np.allclose(
        stored_norms,
        1.0,
        rtol=0.0,
        atol=NORM_ABSOLUTE_TOLERANCE,
    ):
        raise IndexBuildError("normalized embedding vectors failed stored-vector validation")
    return np.ascontiguousarray(normalized, dtype=np.dtype("<f4"))


def _load_exact_numpy_array(path: Path, *, mmap: bool) -> np.ndarray:
    try:
        with path.open("rb") as handle:
            validated = np.load(
                handle,
                allow_pickle=False,
                max_header_size=NUMPY_MAX_HEADER_SIZE,
            )
            if handle.read(1):
                raise IndexLoadError("index vector artifact contains trailing data")
        if mmap:
            return np.load(
                path,
                allow_pickle=False,
                mmap_mode="r",
                max_header_size=NUMPY_MAX_HEADER_SIZE,
            )
        return validated
    except IndexLoadError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise IndexLoadError("index vector artifact is not a safe NumPy array") from error


def _validate_stored_vectors(vectors: np.ndarray, manifest: IndexManifest) -> None:
    if vectors.ndim != 2:
        raise IndexLoadError("index vector artifact must be a two-dimensional matrix")
    expected_shape = (manifest.vector_count, manifest.embedding_dimension)
    if vectors.shape != expected_shape:
        raise IndexLoadError("index vector artifact shape does not match manifest")
    if vectors.dtype != np.dtype("<f4"):
        raise IndexLoadError("index vector artifact dtype must be little-endian float32")
    if not vectors.flags.c_contiguous:
        raise IndexLoadError("index vector artifact must be C-contiguous")
    if not np.isfinite(vectors).all():
        raise IndexLoadError("index vector artifact contains non-finite values")
    if vectors.shape[0] == 0:
        return
    norms = np.sqrt(np.sum(vectors.astype(np.float64) ** 2, axis=1, dtype=np.float64))
    if np.any(norms == 0.0) or not np.allclose(
        norms,
        1.0,
        rtol=0.0,
        atol=NORM_ABSOLUTE_TOLERANCE,
    ):
        raise IndexLoadError("index vector artifact rows are zero or not normalized")


def _serialize_manifest(manifest: IndexManifest) -> str:
    return (
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _call_failure_hook(
    hook: Callable[[str, Path], None] | None,
    phase: str,
    staged: Path,
) -> None:
    if hook is not None:
        hook(phase, staged)


def _publish_staged_directory(staged: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        raise IndexBuildError("output target appeared before publication")
    try:
        os.rename(staged, target)
    except OSError as error:
        raise IndexBuildError("atomic index directory publication failed") from error


def _cleanup_staged_directory(staged: Path, parent: Path, prefix: str) -> None:
    try:
        resolved_staged = staged.resolve(strict=False)
        resolved_parent = parent.resolve(strict=False)
        if (
            resolved_staged.parent == resolved_parent
            and resolved_staged.name.startswith(prefix)
            and resolved_staged.exists()
            and resolved_staged.is_dir()
            and not resolved_staged.is_symlink()
        ):
            shutil.rmtree(resolved_staged)
    except OSError:
        pass
