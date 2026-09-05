"""Build and audit a corpus manifest from finite, explicit registrations."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from collections.abc import Callable
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
    CorpusManifestError,
    canonical_corpus_manifest_bytes,
    load_corpus_manifest_bytes,
    validate_corpus_relative_path,
)


class CorpusBuildError(Exception):
    """Raised when explicit corpus registrations cannot be validated safely."""


class CorpusAuditError(Exception):
    """Raised when a manifest no longer matches its registered artifacts."""


class CorpusUpdateError(Exception):
    """Base class for incremental corpus-manifest update failures."""


class CorpusUpdateValidationError(CorpusUpdateError):
    """Raised before publication when update inputs or artifacts are invalid."""


class CorpusConcurrentUpdateError(CorpusUpdateError):
    """Raised when the current manifest changes before activation."""


class CorpusPublicationError(CorpusUpdateError):
    """Raised when staging or atomic activation fails before commit."""


class CorpusCommitStateError(CorpusUpdateError):
    """Raised when the committed manifest cannot be verified after activation."""


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


@dataclass(frozen=True, slots=True)
class CorpusUpdateResult:
    action: Literal["add", "replace"]
    corpus_id: str
    old_document_id: str | None
    candidate_document_id: str
    document_count: int
    document_family_count: int
    institution_count: int
    indexed_document_count: int
    unindexed_document_count: int
    candidate_index_state: Literal["not_indexed", "ready"]
    manifest_path: str


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
    return _manifest_from_entries(corpus_id, entries)


def update_corpus_manifest(
    corpus_root: str | Path,
    manifest_path: str | Path,
    *,
    action: Literal["add", "replace"],
    candidate: CorpusRegistration,
    replace_document_id: str | None = None,
    _failure_hook: Callable[[str, Path], None] | None = None,
) -> CorpusUpdateResult:
    """Validate and atomically activate one explicit add or replacement."""

    root = _validated_root(corpus_root)
    target = _validated_manifest_target(manifest_path)
    _validate_update_request(action, candidate, replace_document_id)
    try:
        original_bytes = target.read_bytes()
        current = load_corpus_manifest_bytes(original_bytes)
        if canonical_corpus_manifest_bytes(current) != original_bytes:
            raise ValueError
        audited = audit_corpus_manifest(current, root)
    except (CorpusAuditError, CorpusManifestError, OSError, ValueError) as error:
        raise CorpusUpdateValidationError(
            "current corpus manifest validation or audit failed"
        ) from error
    try:
        candidate_manifest = build_corpus_manifest(current.corpus_id, root, (candidate,))
    except CorpusBuildError as error:
        if "explicit migration" in str(error):
            raise CorpusUpdateValidationError(str(error)) from error
        raise CorpusUpdateValidationError(
            "candidate corpus registration validation failed"
        ) from error

    candidate_entry = candidate_manifest.entries[0]
    proposed = _derive_updated_manifest(
        audited,
        action=action,
        candidate=candidate_entry,
        replace_document_id=replace_document_id,
    )
    proposed_bytes = canonical_corpus_manifest_bytes(proposed)
    staged: Path | None = None
    committed = False
    try:
        staged = _stage_manifest(target, proposed_bytes)
        _call_update_hook(_failure_hook, "after_stage_write", staged)
        staged_bytes = staged.read_bytes()
        staged_manifest = load_corpus_manifest_bytes(staged_bytes)
        if staged_bytes != proposed_bytes:
            raise CorpusPublicationError("staged corpus manifest bytes changed unexpectedly")
        audit_corpus_manifest(staged_manifest, root)
        _call_update_hook(_failure_hook, "after_stage_validation", staged)
        _call_update_hook(_failure_hook, "before_precommit_compare", target)
        if not _current_manifest_unchanged(target, original_bytes):
            raise CorpusConcurrentUpdateError("current corpus manifest changed before activation")
        _call_update_hook(_failure_hook, "before_atomic_replace", staged)
        os.replace(staged, target)
        committed = True
    except CorpusConcurrentUpdateError:
        _cleanup_owned_stage(staged, target.parent)
        raise
    except (
        CorpusAuditError,
        CorpusManifestError,
        CorpusPublicationError,
        OSError,
        ValueError,
    ) as error:
        _cleanup_owned_stage(staged, target.parent)
        if isinstance(error, CorpusPublicationError):
            raise
        raise CorpusPublicationError("corpus manifest publication failed before commit") from error
    except Exception as error:
        _cleanup_owned_stage(staged, target.parent)
        raise CorpusPublicationError("corpus manifest publication failed before commit") from error

    try:
        _call_update_hook(_failure_hook, "after_atomic_replace", target)
        committed_bytes = target.read_bytes()
        committed_manifest = load_corpus_manifest_bytes(committed_bytes)
        if (
            committed_bytes != proposed_bytes
            or canonical_corpus_manifest_bytes(committed_manifest) != proposed_bytes
        ):
            raise ValueError
    except Exception as error:
        if committed:
            raise CorpusCommitStateError(
                "corpus manifest was activated but final verification failed"
            ) from error
        raise

    return CorpusUpdateResult(
        action=action,
        corpus_id=committed_manifest.corpus_id,
        old_document_id=replace_document_id,
        candidate_document_id=candidate_entry.identity.document_id,
        document_count=committed_manifest.document_count,
        document_family_count=committed_manifest.document_family_count,
        institution_count=committed_manifest.institution_count,
        indexed_document_count=committed_manifest.indexed_document_count,
        unindexed_document_count=committed_manifest.unindexed_document_count,
        candidate_index_state=candidate_entry.index_state,
        manifest_path=str(target),
    )


def _manifest_from_entries(
    corpus_id: str, entries: tuple[CorpusDocumentEntry, ...]
) -> CorpusManifest:
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


def _derive_updated_manifest(
    current: CorpusManifest,
    *,
    action: Literal["add", "replace"],
    candidate: CorpusDocumentEntry,
    replace_document_id: str | None,
) -> CorpusManifest:
    existing = {entry.identity.document_id: entry for entry in current.entries}
    candidate_id = candidate.identity.document_id
    if action == "add":
        if candidate_id in existing:
            raise CorpusUpdateValidationError("add candidate document is already present")
        entries = current.entries + (candidate,)
    else:
        if replace_document_id not in existing:
            raise CorpusUpdateValidationError("replace target document is absent")
        replaced = existing[replace_document_id]
        if candidate_id == replace_document_id:
            if candidate.identity != replaced.identity:
                raise CorpusUpdateValidationError(
                    "same-document replacement must retain the complete identity"
                )
            if candidate == replaced:
                raise CorpusUpdateValidationError(
                    "replacement candidate is already the active registration"
                )
        elif (
            candidate.identity.institution_id != replaced.identity.institution_id
            or candidate.identity.document_family_id != replaced.identity.document_family_id
        ):
            raise CorpusUpdateValidationError(
                "successor replacement must retain institution and document family"
            )
        entries = tuple(
            candidate if entry.identity.document_id == replace_document_id else entry
            for entry in current.entries
        )
    try:
        return _manifest_from_entries(current.corpus_id, entries)
    except CorpusBuildError as error:
        raise CorpusUpdateValidationError(
            "proposed corpus violates corpus-wide invariants"
        ) from error


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


def resolve_registered_corpus_kb_path(
    corpus_root: str | Path,
    kb_path: str,
) -> Path:
    """Resolve one validated corpus-relative KB path beneath a server-owned root."""

    try:
        validate_corpus_relative_path(kb_path, directory=False)
        root = _validated_root(corpus_root)
        return _registered_target(root, kb_path, expected="file")
    except (CorpusBuildError, TypeError, ValueError) as error:
        raise CorpusAuditError("registered corpus KB path is unavailable or unsafe") from error


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


def _validated_manifest_target(path_value: str | Path) -> Path:
    try:
        path = Path(path_value)
        if (
            not path.is_absolute()
            or _has_symlink_component(path)
            or not path.is_file()
            or path.is_symlink()
        ):
            raise OSError
        return path.resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise CorpusUpdateValidationError("manifest file is unavailable or unsafe") from None


def _validate_update_request(
    action: object,
    candidate: object,
    replace_document_id: object,
) -> None:
    if action not in {"add", "replace"} or not isinstance(candidate, CorpusRegistration):
        raise CorpusUpdateValidationError("corpus update request is invalid")
    if action == "add" and replace_document_id is not None:
        raise CorpusUpdateValidationError("add must not include a replacement document ID")
    if action == "replace" and (
        not isinstance(replace_document_id, str)
        or not replace_document_id
        or replace_document_id != replace_document_id.strip()
    ):
        raise CorpusUpdateValidationError("replace requires one explicit document ID")


def _stage_manifest(target: Path, payload: bytes) -> Path:
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{target.name}.tmp-",
            suffix=".json",
            dir=target.parent,
        )
        staged = Path(raw_path)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if staged.is_symlink() or not staged.is_file() or staged.parent != target.parent:
            raise OSError
        return staged
    except OSError as error:
        try:
            os.close(descriptor)
        except (OSError, UnboundLocalError):
            pass
        if "staged" in locals():
            _cleanup_owned_stage(staged, target.parent)
        raise CorpusPublicationError("corpus manifest staging failed") from error


def _current_manifest_unchanged(target: Path, original_bytes: bytes) -> bool:
    try:
        return (
            not target.is_symlink() and target.is_file() and target.read_bytes() == original_bytes
        )
    except OSError:
        return False


def _cleanup_owned_stage(staged: Path | None, parent: Path) -> None:
    if staged is None:
        return
    try:
        if (
            staged.parent == parent
            and staged.name.startswith(".")
            and ".tmp-" in staged.name
            and staged.suffix == ".json"
            and staged.is_file()
            and not staged.is_symlink()
        ):
            staged.unlink()
    except OSError:
        pass


def _call_update_hook(
    hook: Callable[[str, Path], None] | None,
    phase: str,
    path: Path,
) -> None:
    if hook is not None:
        hook(phase, path)


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
    "CorpusCommitStateError",
    "CorpusConcurrentUpdateError",
    "CorpusPublicationError",
    "CorpusRegistration",
    "CorpusUpdateError",
    "CorpusUpdateResult",
    "CorpusUpdateValidationError",
    "audit_corpus_manifest",
    "build_corpus_manifest",
    "resolve_registered_corpus_kb_path",
    "update_corpus_manifest",
]
