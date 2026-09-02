from __future__ import annotations

import json
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .document_kb import DocumentKnowledgeBase, ScopeType

SUPPORTED_INDEX_SCHEMA_VERSIONS = frozenset({"0.1"})
SUPPORTED_SOURCE_KB_SCHEMA_VERSIONS = frozenset({"0.5", "0.6"})
SHA256_FIELDS = (
    "source_kb_sha256",
    "source_pdf_sha256",
    "payloads_sha256",
    "vectors_sha256",
)


class IndexManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index_schema_version: str = "0.1"
    source_kb_schema_version: str
    document_id: str
    source_kb_sha256: str
    source_pdf_sha256: str
    payload_count: int = Field(ge=0)
    vector_count: int = Field(ge=0)
    embedding_dimension: int = Field(ge=0)
    vector_dtype: Literal["float32"] = "float32"
    distance_metric: Literal["cosine"] = "cosine"
    vectors_normalized: bool
    embedding_provider: str
    embedding_model: str
    embedding_revision: str | None = None
    payloads_filename: str = "payloads.jsonl"
    vectors_filename: str = "embeddings.npy"
    payloads_sha256: str
    vectors_sha256: str
    builder_version: str = "0.1.0"

    @field_validator(*SHA256_FIELDS)
    @classmethod
    def hashes_must_be_lowercase_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("must be a lowercase 64-character SHA-256 hex string")
        return value

    @field_validator(
        "document_id",
        "embedding_provider",
        "embedding_model",
        "builder_version",
    )
    @classmethod
    def identifiers_must_be_trimmed(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("must be a non-empty trimmed string")
        return value

    @field_validator("embedding_revision")
    @classmethod
    def revision_must_be_trimmed(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != value.strip()):
            raise ValueError("must be None or a non-empty trimmed string")
        return value

    @field_validator("payloads_filename", "vectors_filename")
    @classmethod
    def artifact_names_must_be_safe_basenames(cls, value: str) -> str:
        windows_path = PureWindowsPath(value)
        posix_path = PurePosixPath(value)
        if (
            not value
            or value != value.strip()
            or value in {".", ".."}
            or "\x00" in value
            or ":" in value
            or "/" in value
            or "\\" in value
            or windows_path.is_absolute()
            or bool(windows_path.drive)
            or posix_path.is_absolute()
        ):
            raise ValueError("must be a safe basename without directories or traversal")
        return value

    @model_validator(mode="after")
    def counts_and_dimension_must_align(self) -> IndexManifest:
        if self.payload_count != self.vector_count:
            raise ValueError("payload_count must equal vector_count")
        if self.vector_count > 0 and self.embedding_dimension <= 0:
            raise ValueError("embedding_dimension must be positive when vectors exist")
        return self


class IndexPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0)
    document_id: str
    unit_id: str
    fact_id: str
    text: str
    source_pages: list[int] = Field(default_factory=list)
    section_path: list[str] = Field(default_factory=list)
    fact_type: str
    scope_type: ScopeType
    scope_targets: list[str] = Field(default_factory=list)
    parent_college: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("document_id", "unit_id", "fact_id", "fact_type")
    @classmethod
    def identifiers_must_be_trimmed(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("must be a non-empty trimmed string")
        return value

    @field_validator("text")
    @classmethod
    def text_must_be_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("must be non-empty")
        return value

    @field_validator("parent_college")
    @classmethod
    def parent_college_must_be_trimmed(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != value.strip()):
            raise ValueError("must be None or a non-empty trimmed string")
        return value

    @field_validator("source_pages")
    @classmethod
    def pages_must_be_positive_sorted_and_unique(cls, pages: list[int]) -> list[int]:
        if any(page <= 0 for page in pages):
            raise ValueError("source_pages must contain only positive page numbers")
        if pages != sorted(set(pages)):
            raise ValueError("source_pages must be sorted and unique")
        return pages

    @field_validator("section_path", "scope_targets")
    @classmethod
    def string_lists_must_be_trimmed(cls, values: list[str]) -> list[str]:
        if any(not value or value != value.strip() for value in values):
            raise ValueError("values must be non-empty trimmed strings")
        return values


def validate_manifest_compatibility(manifest: IndexManifest) -> None:
    if manifest.index_schema_version not in SUPPORTED_INDEX_SCHEMA_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_INDEX_SCHEMA_VERSIONS))
        raise ValueError(
            f"unsupported index schema version {manifest.index_schema_version!r}; "
            f"supported versions: {supported}"
        )
    if manifest.source_kb_schema_version not in SUPPORTED_SOURCE_KB_SCHEMA_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_SOURCE_KB_SCHEMA_VERSIONS))
        raise ValueError(
            f"unsupported source KB schema version {manifest.source_kb_schema_version!r}; "
            f"supported versions: {supported}"
        )


def validate_source_kb_compatibility(kb: DocumentKnowledgeBase) -> None:
    if kb.manifest.schema_version not in SUPPORTED_SOURCE_KB_SCHEMA_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_SOURCE_KB_SCHEMA_VERSIONS))
        raise ValueError(
            f"unsupported source KB schema version {kb.manifest.schema_version!r}; "
            f"supported versions: {supported}"
        )


def validate_payload_collection(
    manifest: IndexManifest,
    payloads: Sequence[IndexPayload],
) -> None:
    validate_manifest_compatibility(manifest)
    if len(payloads) != manifest.payload_count:
        raise ValueError(
            f"payload count mismatch: manifest={manifest.payload_count}, rows={len(payloads)}"
        )

    seen_unit_ids: set[str] = set()
    seen_fact_ids: set[str] = set()
    for position, payload in enumerate(payloads):
        if payload.row_index != position:
            raise ValueError(
                f"non-contiguous payload row_index at position {position}: "
                f"observed {payload.row_index}"
            )
        if payload.unit_id in seen_unit_ids:
            raise ValueError(f"duplicate unit_id {payload.unit_id!r}")
        if payload.fact_id in seen_fact_ids:
            raise ValueError(f"duplicate fact_id {payload.fact_id!r}")
        if payload.document_id != manifest.document_id:
            raise ValueError(
                f"payload document mismatch at row {position}: "
                f"manifest={manifest.document_id!r}, payload={payload.document_id!r}"
            )
        seen_unit_ids.add(payload.unit_id)
        seen_fact_ids.add(payload.fact_id)


def derive_index_payloads(kb: DocumentKnowledgeBase) -> list[IndexPayload]:
    validate_source_kb_compatibility(kb)
    facts_by_id = {fact.fact_id: fact for fact in kb.facts}
    if len(facts_by_id) != len(kb.facts):
        raise ValueError("source KB contains duplicate fact_id values")

    payloads: list[IndexPayload] = []
    for row_index, unit in enumerate(kb.retrieval_units):
        fact = facts_by_id.get(unit.fact_id)
        if fact is None:
            raise ValueError(
                f"retrieval unit {unit.unit_id!r} references missing Fact {unit.fact_id!r}"
            )
        if unit.source_pages != fact.source_pages:
            raise ValueError(f"retrieval unit {unit.unit_id!r} source_pages differ from its Fact")
        if unit.section_path != fact.section_path:
            raise ValueError(f"retrieval unit {unit.unit_id!r} section_path differs from its Fact")
        payloads.append(
            IndexPayload(
                row_index=row_index,
                document_id=kb.manifest.document_id,
                unit_id=unit.unit_id,
                fact_id=fact.fact_id,
                text=unit.text,
                source_pages=list(unit.source_pages),
                section_path=list(unit.section_path),
                fact_type=fact.fact_type,
                scope_type=fact.scope_type,
                scope_targets=list(fact.scope_targets),
                parent_college=fact.parent_college,
                metadata=dict(unit.metadata),
            )
        )
    return payloads


def payloads_to_jsonl(payloads: Sequence[IndexPayload]) -> str:
    return "".join(
        json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        + "\n"
        for payload in payloads
    )


def payloads_from_jsonl(value: str) -> list[IndexPayload]:
    payloads: list[IndexPayload] = []
    for line_number, line in enumerate(value.splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"blank JSONL row at line {line_number}")
        try:
            payloads.append(IndexPayload.model_validate_json(line))
        except ValueError as error:
            raise ValueError(f"invalid payload JSON at line {line_number}: {error}") from error
    return payloads
