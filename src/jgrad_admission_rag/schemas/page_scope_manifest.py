"""Reviewed page-level document scope for rule and report boundaries."""

from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator
from pydantic import model_validator

from .document_identity import DocumentIdentity

PAGE_SCOPE_MANIFEST_SCHEMA_VERSION = "1.0"
SUPPORTED_PAGE_SCOPE_MANIFEST_SCHEMA_VERSIONS = frozenset({PAGE_SCOPE_MANIFEST_SCHEMA_VERSION})
_SAFE_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_GENERIC_ERROR = "page scope manifest is invalid or unsupported"


class PageScopeManifestError(Exception):
    """Raised without echoing untrusted manifest content."""


class PageScopeCategory(str, Enum):
    CORE_ADMISSION = "core_admission"
    CONDITIONAL_PROGRAM = "conditional_program"
    FACULTY_DIRECTORY = "faculty_directory"
    GENERAL_REFERENCE = "general_reference"
    IRRELEVANT_OR_APPENDIX = "irrelevant_or_appendix"


class PageScopeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PageScopeEntry(PageScopeModel):
    pages: tuple[StrictInt, ...] = Field(min_length=1)
    category: PageScopeCategory
    conditional_routes: tuple[str, ...] = ()
    review_note: str

    @field_validator("pages")
    @classmethod
    def pages_must_be_canonical(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(page <= 0 for page in value) or value != tuple(sorted(set(value))):
            raise ValueError("pages must be positive, sorted, and unique")
        return value

    @field_validator("conditional_routes")
    @classmethod
    def routes_must_be_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("conditional routes must be sorted and unique")
        for route in value:
            _validate_explicit(route)
        return value

    @field_validator("review_note")
    @classmethod
    def note_must_be_explicit(cls, value: str) -> str:
        _validate_explicit(value)
        return value

    @model_validator(mode="after")
    def routes_must_match_category(self) -> PageScopeEntry:
        if self.category is PageScopeCategory.CONDITIONAL_PROGRAM:
            if not self.conditional_routes:
                raise ValueError("conditional pages require an explicit route gate")
        elif self.conditional_routes:
            raise ValueError("only conditional pages may declare route gates")
        return self


class PageScopeManifest(PageScopeModel):
    schema_version: Literal["1.0"] = PAGE_SCOPE_MANIFEST_SCHEMA_VERSION
    manifest_id: str
    document_identity: DocumentIdentity
    page_count: StrictInt = Field(gt=0)
    entries: tuple[PageScopeEntry, ...] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def nested_models_must_be_revalidated(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        detached = dict(value)
        identity = detached.get("document_identity")
        if isinstance(identity, DocumentIdentity):
            detached["document_identity"] = identity.model_dump(mode="json")
        entries = detached.get("entries")
        if isinstance(entries, (list, tuple)):
            detached["entries"] = [
                item.model_dump(mode="json") if isinstance(item, PageScopeEntry) else item
                for item in entries
            ]
        return detached

    @field_validator("manifest_id")
    @classmethod
    def manifest_id_must_be_safe(cls, value: str) -> str:
        if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
            raise ValueError("manifest ID is unsafe")
        return value

    @model_validator(mode="after")
    def pages_must_cover_document_exactly_once(self) -> PageScopeManifest:
        flattened = tuple(page for entry in self.entries for page in entry.pages)
        if len(flattened) != len(set(flattened)):
            raise ValueError("page scope entries overlap")
        if set(flattened) != set(range(1, self.page_count + 1)):
            raise ValueError("page scope entries do not cover the document")
        category_order = {category: index for index, category in enumerate(PageScopeCategory)}
        keys = tuple((category_order[entry.category], entry.pages) for entry in self.entries)
        if keys != tuple(sorted(keys)):
            raise ValueError("page scope entries are not canonical")
        return self

    def entry_for_pages(self, pages: tuple[int, ...]) -> PageScopeEntry:
        if not pages or pages != tuple(sorted(set(pages))):
            raise PageScopeManifestError(_GENERIC_ERROR)
        matches = {entry for page in pages for entry in self.entries if page in entry.pages}
        if len(matches) != 1:
            raise PageScopeManifestError(_GENERIC_ERROR)
        return next(iter(matches))


def canonical_page_scope_manifest_bytes(manifest: PageScopeManifest) -> bytes:
    try:
        if not isinstance(manifest, PageScopeManifest) or set(manifest.__dict__) != set(
            PageScopeManifest.model_fields
        ):
            raise TypeError
        validated = PageScopeManifest.model_validate(manifest.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValidationError, ValueError):
        raise PageScopeManifestError(_GENERIC_ERROR) from None
    return f"{serialized}\n".encode("utf-8")


def load_page_scope_manifest_bytes(raw_bytes: bytes) -> PageScopeManifest:
    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") not in SUPPORTED_PAGE_SCOPE_MANIFEST_SCHEMA_VERSIONS
        ):
            raise ValueError
        return PageScopeManifest.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValidationError, ValueError):
        raise PageScopeManifestError(_GENERIC_ERROR) from None


def load_page_scope_manifest(path_value: str | Path) -> PageScopeManifest:
    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError
        raw_bytes = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise PageScopeManifestError("page scope manifest is unavailable or unsafe") from None
    return load_page_scope_manifest_bytes(raw_bytes)


def _validate_explicit(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("value must be explicit")


def _reject_constant(_: str) -> None:
    raise ValueError


__all__ = [
    "PAGE_SCOPE_MANIFEST_SCHEMA_VERSION",
    "SUPPORTED_PAGE_SCOPE_MANIFEST_SCHEMA_VERSIONS",
    "PageScopeCategory",
    "PageScopeEntry",
    "PageScopeManifest",
    "PageScopeManifestError",
    "canonical_page_scope_manifest_bytes",
    "load_page_scope_manifest",
    "load_page_scope_manifest_bytes",
]
