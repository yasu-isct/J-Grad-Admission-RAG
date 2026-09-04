"""Versioned, self-contained catalog of explicitly registered document artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .document_identity import DocumentIdentity
from .index import IndexManifest, validate_manifest_compatibility

CORPUS_MANIFEST_SCHEMA_VERSION = "1.0"
SUPPORTED_CORPUS_MANIFEST_SCHEMA_VERSIONS = frozenset({CORPUS_MANIFEST_SCHEMA_VERSION})

_SAFE_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


class CorpusManifestError(Exception):
    """Raised when a corpus manifest is invalid, unsupported, or unsafe to load."""


class CorpusModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CorpusIndexManifest(IndexManifest):
    """Immutable snapshot of the already validated local index authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="after")
    def schema_versions_must_be_supported(self) -> CorpusIndexManifest:
        validate_manifest_compatibility(self)
        return self


class CorpusDocumentEntry(CorpusModel):
    identity: DocumentIdentity
    kb_path: str
    kb_schema_version: Literal["0.6"] = "0.6"
    source_kb_sha256: str
    kb_quality_passed: Literal[True] = True
    index_state: Literal["not_indexed", "ready"]
    index_path: str | None = None
    index_manifest: CorpusIndexManifest | None = None

    @field_validator("kb_path")
    @classmethod
    def kb_path_must_be_safe(cls, value: str) -> str:
        return validate_corpus_relative_path(value, directory=False)

    @field_validator("index_path")
    @classmethod
    def index_path_must_be_safe(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_corpus_relative_path(value, directory=True)

    @field_validator("source_kb_sha256")
    @classmethod
    def kb_hash_must_be_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("source_kb_sha256 must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def index_fields_must_match_state_and_document(self) -> CorpusDocumentEntry:
        if self.index_state == "not_indexed":
            if self.index_path is not None or self.index_manifest is not None:
                raise ValueError("not_indexed entries must not contain index metadata")
            return self
        if self.index_path is None or self.index_manifest is None:
            raise ValueError("ready entries require index_path and index_manifest")
        manifest = self.index_manifest
        expected = (
            manifest.document_id == self.identity.document_id
            and manifest.source_pdf_sha256 == self.identity.source_pdf_sha256
            and manifest.source_kb_sha256 == self.source_kb_sha256
            and manifest.source_kb_schema_version == self.kb_schema_version
            and manifest.payload_count == manifest.vector_count
        )
        if not expected:
            raise ValueError("ready index bindings do not match the corpus entry")
        return self


class CorpusManifest(CorpusModel):
    schema_version: Literal["1.0"] = CORPUS_MANIFEST_SCHEMA_VERSION
    corpus_id: str
    entries: tuple[CorpusDocumentEntry, ...] = Field(min_length=1)
    document_count: int = Field(ge=1, strict=True)
    document_family_count: int = Field(ge=1, strict=True)
    institution_count: int = Field(ge=1, strict=True)
    indexed_document_count: int = Field(ge=0, strict=True)
    unindexed_document_count: int = Field(ge=0, strict=True)

    @field_validator("corpus_id")
    @classmethod
    def corpus_id_must_be_safe(cls, value: str) -> str:
        if (
            not isinstance(value, str)
            or _SAFE_ID.fullmatch(value) is None
            or value.upper() in _WINDOWS_RESERVED
            or value.split(".", maxsplit=1)[0].upper() in _WINDOWS_RESERVED
        ):
            raise ValueError("corpus_id is unsafe or unsupported")
        return value

    @model_validator(mode="after")
    def entries_and_counts_must_be_canonical(self) -> CorpusManifest:
        if tuple(entry.identity.document_id for entry in self.entries) != tuple(
            sorted(entry.identity.document_id for entry in self.entries)
        ):
            raise ValueError("entries must be sorted by exact document_id")
        _require_unique(self.entries, lambda entry: entry.identity.document_id, "document_id")
        _require_unique(
            self.entries,
            lambda entry: (entry.identity.document_family_id, entry.identity.edition_id),
            "document family and edition",
        )
        _require_unique(
            self.entries, lambda entry: entry.identity.source_pdf_sha256, "source PDF hash"
        )
        _require_unique(self.entries, lambda entry: entry.kb_path.casefold(), "KB path")
        indexed = tuple(entry for entry in self.entries if entry.index_state == "ready")
        _require_unique(
            indexed,
            lambda entry: entry.index_path.casefold() if entry.index_path else None,
            "index path",
        )
        expected_counts = (
            len(self.entries),
            len({entry.identity.document_family_id for entry in self.entries}),
            len({entry.identity.institution_id for entry in self.entries}),
            len(indexed),
            len(self.entries) - len(indexed),
        )
        observed_counts = (
            self.document_count,
            self.document_family_count,
            self.institution_count,
            self.indexed_document_count,
            self.unindexed_document_count,
        )
        if observed_counts != expected_counts:
            raise ValueError("corpus aggregate counts do not match entries")
        return self


def canonical_corpus_manifest_bytes(manifest: CorpusManifest) -> bytes:
    """Serialize a fully revalidated manifest as canonical UTF-8 JSON with LF."""

    try:
        if not isinstance(manifest, CorpusManifest):
            raise TypeError
        validated = CorpusManifest.model_validate(manifest.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValidationError, ValueError):
        raise CorpusManifestError("corpus manifest is invalid or unsupported") from None
    return f"{serialized}\n".encode("utf-8")


def load_corpus_manifest_bytes(raw_bytes: bytes) -> CorpusManifest:
    """Load and structurally validate a manifest without reopening registered artifacts."""

    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") not in SUPPORTED_CORPUS_MANIFEST_SCHEMA_VERSIONS
        ):
            raise ValueError
        return CorpusManifest.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValidationError, ValueError):
        raise CorpusManifestError("corpus manifest bytes are invalid or unsupported") from None


def load_corpus_manifest(path_value: str | Path) -> CorpusManifest:
    """Load a manifest only from a regular non-symlinked file."""

    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError
        raw_bytes = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise CorpusManifestError("corpus manifest file is unavailable or unsafe") from None
    return load_corpus_manifest_bytes(raw_bytes)


def validate_corpus_relative_path(value: str, *, directory: bool) -> str:
    """Validate one canonical corpus-root-relative POSIX path."""

    if not isinstance(value, str):
        raise ValueError("corpus artifact path must be a string")
    windows_path = PureWindowsPath(value)
    posix_path = PurePosixPath(value)
    parts = posix_path.parts
    if (
        not value
        or value != value.strip()
        or "\x00" in value
        or "\\" in value
        or ":" in value
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or posix_path.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
        or any(part.endswith((".", " ")) for part in parts)
        or any(
            part.upper() in _WINDOWS_RESERVED
            or part.split(".", maxsplit=1)[0].upper() in _WINDOWS_RESERVED
            for part in parts
        )
        or str(posix_path) != value
    ):
        raise ValueError("corpus artifact path must be canonical, relative, and traversal-free")
    if not directory and posix_path.name in {"", ".", ".."}:
        raise ValueError("KB path must identify a file")
    return value


def _require_unique(entries: tuple[Any, ...], key, label: str) -> None:
    values = tuple(key(entry) for entry in entries)
    if len(values) != len(set(values)):
        raise ValueError(f"corpus entries contain duplicate {label}")


def _reject_constant(_: str) -> Any:
    raise ValueError("non-finite JSON numbers are unsupported")


__all__ = [
    "CORPUS_MANIFEST_SCHEMA_VERSION",
    "SUPPORTED_CORPUS_MANIFEST_SCHEMA_VERSIONS",
    "CorpusDocumentEntry",
    "CorpusIndexManifest",
    "CorpusManifest",
    "CorpusManifestError",
    "canonical_corpus_manifest_bytes",
    "load_corpus_manifest",
    "load_corpus_manifest_bytes",
    "validate_corpus_relative_path",
]
