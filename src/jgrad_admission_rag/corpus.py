"""Build and audit a corpus manifest from finite, explicit registrations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import ValidationError

from .retrieval.embedding import EmbeddingIdentity
from .retrieval.index_freshness import IndexFreshnessError, load_fresh_index_context
from .retrieval.local_index import IndexLoadError, load_local_index
from .retrieval.source_kb import ExactSourceKnowledgeBase, SourceKbReadError, read_source_kb_exact
from .schemas.corpus_manifest import (
    CorpusDocumentEntry,
    CorpusIndexManifest,
    CorpusManifest,
    canonical_corpus_manifest_bytes,
    validate_corpus_relative_path,
)


class CorpusBuildError(Exception):
    """Raised when explicit corpus registrations cannot be validated safely."""


class CorpusAuditError(Exception):
    """Raised when a manifest no longer matches its registered artifacts."""


@dataclass(frozen=True, slots=True)
class CorpusRegistration:
    kb_path: str
    index_path: str | None = None

    def __post_init__(self) -> None:
        try:
            validate_corpus_relative_path(self.kb_path, directory=False)
            if self.index_path is not None:
                validate_corpus_relative_path(self.index_path, directory=True)
        except (TypeError, ValueError):
            raise CorpusBuildError("registration contains an unsafe artifact path") from None


def build_corpus_manifest(
    corpus_id: str,
    corpus_root: str | Path,
    registrations: tuple[CorpusRegistration, ...],
) -> CorpusManifest:
    """Validate explicitly named artifacts and return a detached canonical catalog."""

    root = _validated_root(corpus_root)
    if not isinstance(registrations, tuple) or not registrations:
        raise CorpusBuildError("registrations must be a finite non-empty tuple")
    if any(not isinstance(registration, CorpusRegistration) for registration in registrations):
        raise CorpusBuildError("registrations contain an unsupported value")
    _preflight_unique_paths(registrations)

    entries = tuple(_build_entry(root, registration) for registration in registrations)
    ordered = tuple(sorted(entries, key=lambda entry: entry.identity.document_id))
    try:
        manifest = CorpusManifest(
            corpus_id=corpus_id,
            entries=ordered,
            document_count=len(ordered),
            document_family_count=len({entry.identity.document_family_id for entry in ordered}),
            institution_count=len({entry.identity.institution_id for entry in ordered}),
            indexed_document_count=sum(entry.index_state == "ready" for entry in ordered),
            unindexed_document_count=sum(entry.index_state == "not_indexed" for entry in ordered),
        )
        return CorpusManifest.model_validate_json(canonical_corpus_manifest_bytes(manifest))
    except (TypeError, ValidationError, ValueError) as error:
        raise CorpusBuildError("corpus registrations violate corpus-wide invariants") from error


def audit_corpus_manifest(
    manifest: CorpusManifest,
    corpus_root: str | Path,
) -> CorpusManifest:
    """Reopen every declared artifact and require an exact manifest reconstruction."""

    try:
        if not isinstance(manifest, CorpusManifest):
            raise TypeError
        detached = CorpusManifest.model_validate(manifest.model_dump(mode="json"))
        registrations = tuple(
            CorpusRegistration(kb_path=entry.kb_path, index_path=entry.index_path)
            for entry in detached.entries
        )
        rebuilt = build_corpus_manifest(detached.corpus_id, corpus_root, registrations)
        if canonical_corpus_manifest_bytes(rebuilt) != canonical_corpus_manifest_bytes(detached):
            raise ValueError
        return rebuilt
    except (CorpusBuildError, TypeError, ValidationError, ValueError) as error:
        raise CorpusAuditError("corpus manifest audit failed") from error


def _build_entry(root: Path, registration: CorpusRegistration) -> CorpusDocumentEntry:
    kb_path = _registered_target(root, registration.kb_path, expected="file")
    if registration.index_path is None:
        source = _read_registered_kb(kb_path)
        kb = source.knowledge_base
        kb_sha256 = source.sha256
        index_state: Literal["not_indexed", "ready"] = "not_indexed"
        index_manifest = None
    else:
        index_path = _registered_target(root, registration.index_path, expected="directory")
        try:
            index = load_local_index(index_path, mmap=True)
            identity = EmbeddingIdentity(
                provider=index.manifest.embedding_provider,
                model=index.manifest.embedding_model,
                revision=index.manifest.embedding_revision,
                dimension=index.manifest.embedding_dimension,
            )
            fresh = load_fresh_index_context(index, kb_path, identity)
        except (IndexLoadError, IndexFreshnessError, TypeError, ValueError) as error:
            _raise_legacy_migration_if_needed(kb_path, error)
            raise CorpusBuildError("registered index is invalid, stale, or unsafe") from error
        kb = fresh.knowledge_base
        kb_sha256 = fresh.freshness.current_kb_sha256
        index_state = "ready"
        index_manifest = CorpusIndexManifest.model_validate(index.manifest.model_dump(mode="json"))

    if kb.manifest.schema_version != "0.6":
        raise CorpusBuildError("registered KB must be migrated explicitly to schema 0.6")
    if not kb.diagnostics.quality_gate.passed:
        raise CorpusBuildError("registered KB quality gate did not pass")
    try:
        return CorpusDocumentEntry(
            identity=kb.manifest.identity.model_copy(deep=True),
            kb_path=registration.kb_path,
            source_kb_sha256=kb_sha256,
            index_state=index_state,
            index_path=registration.index_path,
            index_manifest=index_manifest,
        )
    except ValidationError as error:
        raise CorpusBuildError("registered artifacts have inconsistent bindings") from error


def _validated_root(root_value: str | Path) -> Path:
    try:
        root = Path(root_value)
        if not root.is_absolute() or _has_symlink_component(root) or not root.is_dir():
            raise OSError
        return root.resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise CorpusBuildError("corpus root is unavailable or unsafe") from None


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _read_registered_kb(path: Path) -> ExactSourceKnowledgeBase:
    try:
        return read_source_kb_exact(path)
    except SourceKbReadError as error:
        _raise_legacy_migration_if_needed(path, error)
        raise CorpusBuildError("registered KB is missing, unsafe, or invalid") from error


def _raise_legacy_migration_if_needed(path: Path, cause: Exception) -> None:
    try:
        payload = json.loads(path.read_bytes().decode("utf-8"))
        version = payload.get("manifest", {}).get("schema_version")
    except (AttributeError, OSError, UnicodeError, ValueError):
        return
    if version == "0.5":
        raise CorpusBuildError(
            "registered KB schema 0.5 requires explicit migration to schema 0.6"
        ) from cause


def _registered_target(
    root: Path, relative: str, *, expected: Literal["file", "directory"]
) -> Path:
    try:
        current = root
        for part in PurePosixPath(relative).parts:
            current = current / part
            if current.is_symlink():
                raise OSError
        resolved = current.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise OSError
        if expected == "file" and not resolved.is_file():
            raise OSError
        if expected == "directory" and not resolved.is_dir():
            raise OSError
        return resolved
    except (OSError, RuntimeError, ValueError):
        raise CorpusBuildError("registered artifact is missing or unsafe") from None


def _preflight_unique_paths(registrations: tuple[CorpusRegistration, ...]) -> None:
    kb_paths = tuple(registration.kb_path for registration in registrations)
    index_paths = tuple(
        registration.index_path
        for registration in registrations
        if registration.index_path is not None
    )
    if len(kb_paths) != len({path.casefold() for path in kb_paths}):
        raise CorpusBuildError("registrations contain a duplicate KB path")
    if len(index_paths) != len({path.casefold() for path in index_paths}):
        raise CorpusBuildError("registrations contain a duplicate index path")


__all__ = [
    "CorpusAuditError",
    "CorpusBuildError",
    "CorpusRegistration",
    "audit_corpus_manifest",
    "build_corpus_manifest",
]
