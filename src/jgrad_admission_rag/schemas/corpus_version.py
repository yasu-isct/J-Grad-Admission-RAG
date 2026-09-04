"""Reviewed corpus version policy and deterministic selection contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .corpus_manifest import CorpusDocumentEntry
from .document_identity import DegreeLevel, IntakeTerm

CORPUS_VERSION_POLICY_SCHEMA_VERSION = "1.0"
CORPUS_SELECTION_SCHEMA_VERSION = "1.0"
SUPPORTED_CORPUS_VERSION_POLICY_SCHEMA_VERSIONS = frozenset({CORPUS_VERSION_POLICY_SCHEMA_VERSION})
SUPPORTED_CORPUS_SELECTION_SCHEMA_VERSIONS = frozenset({CORPUS_SELECTION_SCHEMA_VERSION})
_SAFE_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


class CorpusVersionSchemaError(Exception):
    """Raised when policy, request, or result bytes are invalid or unsafe."""


class VersionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CorpusFamilyVersionPolicy(VersionModel):
    document_family_id: str
    active_document_id: str | None = None
    historical_document_ids: tuple[str, ...] = ()

    @field_validator("document_family_id", "active_document_id")
    @classmethod
    def ids_must_be_safe(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_id(value)
        return value

    @field_validator("historical_document_ids")
    @classmethod
    def historical_ids_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _validate_id(value)
        if len(values) != len(set(values)):
            raise ValueError("historical document IDs must be unique")
        return tuple(sorted(values))

    @model_validator(mode="after")
    def active_and_historical_must_be_disjoint(self) -> CorpusFamilyVersionPolicy:
        if self.active_document_id in self.historical_document_ids:
            raise ValueError("active and historical document IDs must be disjoint")
        return self


class CorpusVersionPolicy(VersionModel):
    schema_version: Literal["1.0"] = CORPUS_VERSION_POLICY_SCHEMA_VERSION
    corpus_id: str
    family_policies: tuple[CorpusFamilyVersionPolicy, ...] = Field(min_length=1)

    @field_validator("corpus_id")
    @classmethod
    def corpus_id_must_be_safe(cls, value: str) -> str:
        _validate_id(value)
        return value

    @field_validator("family_policies")
    @classmethod
    def family_policies_must_be_canonical(
        cls, values: tuple[CorpusFamilyVersionPolicy, ...]
    ) -> tuple[CorpusFamilyVersionPolicy, ...]:
        ids = tuple(value.document_family_id for value in values)
        if len(ids) != len(set(ids)):
            raise ValueError("family policies must be unique")
        return tuple(sorted(values, key=lambda value: value.document_family_id))


class CorpusSelectionRequest(VersionModel):
    schema_version: Literal["1.0"] = CORPUS_SELECTION_SCHEMA_VERSION
    document_ids: tuple[str, ...] = ()
    institution_ids: tuple[str, ...] = ()
    document_family_ids: tuple[str, ...] = ()
    degree_levels: tuple[DegreeLevel, ...] = ()
    intake_terms: tuple[IntakeTerm, ...] = ()
    version_mode: Literal["active_only", "historical_only", "all_versions"] = "active_only"
    allow_multiple_documents: bool = Field(default=False, strict=True)

    @field_validator("document_ids", "institution_ids", "document_family_ids")
    @classmethod
    def id_constraints_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _validate_id(value)
        if len(values) != len(set(values)):
            raise ValueError("ID constraints must be unique")
        return tuple(sorted(values))

    @field_validator("degree_levels")
    @classmethod
    def degree_constraints_must_be_canonical(
        cls, values: tuple[DegreeLevel, ...]
    ) -> tuple[DegreeLevel, ...]:
        if len(values) != len(set(values)):
            raise ValueError("degree constraints must be unique")
        return tuple(sorted(values, key=lambda value: value.value))

    @field_validator("intake_terms")
    @classmethod
    def intake_constraints_must_be_canonical(
        cls, values: tuple[IntakeTerm, ...]
    ) -> tuple[IntakeTerm, ...]:
        keys = tuple((value.year, value.month) for value in values)
        if len(keys) != len(set(keys)):
            raise ValueError("intake constraints must be unique")
        return tuple(sorted(values, key=lambda value: (value.year, value.month)))

    @model_validator(mode="after")
    def at_least_one_positive_constraint_is_required(self) -> CorpusSelectionRequest:
        if not any(
            (
                self.document_ids,
                self.institution_ids,
                self.document_family_ids,
                self.degree_levels,
                self.intake_terms,
            )
        ):
            raise ValueError("selection requires a positive identity constraint")
        return self


class SelectedCorpusDocument(VersionModel):
    version_classification: Literal["active", "historical"]
    entry: CorpusDocumentEntry

    @model_validator(mode="after")
    def selected_entry_must_be_ready(self) -> SelectedCorpusDocument:
        if self.entry.index_state != "ready":
            raise ValueError("selected corpus entry must be ready")
        return self


class CorpusSelectionResult(VersionModel):
    schema_version: Literal["1.0"] = CORPUS_SELECTION_SCHEMA_VERSION
    corpus_id: str
    request: CorpusSelectionRequest
    selected_documents: tuple[SelectedCorpusDocument, ...] = Field(min_length=1)
    selected_document_count: int = Field(ge=1, strict=True)
    selected_family_count: int = Field(ge=1, strict=True)
    selected_institution_count: int = Field(ge=1, strict=True)

    @field_validator("corpus_id")
    @classmethod
    def corpus_id_must_be_safe(cls, value: str) -> str:
        _validate_id(value)
        return value

    @model_validator(mode="after")
    def selection_and_counts_must_be_canonical(self) -> CorpusSelectionResult:
        ids = tuple(item.entry.identity.document_id for item in self.selected_documents)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("selected documents must be sorted and unique")
        expected = (
            len(self.selected_documents),
            len({item.entry.identity.document_family_id for item in self.selected_documents}),
            len({item.entry.identity.institution_id for item in self.selected_documents}),
        )
        observed = (
            self.selected_document_count,
            self.selected_family_count,
            self.selected_institution_count,
        )
        if observed != expected:
            raise ValueError("selection counts do not match selected documents")
        if not self.request.allow_multiple_documents and len(self.selected_documents) != 1:
            raise ValueError("request does not authorize multiple selected documents")
        for item in self.selected_documents:
            if (
                self.request.version_mode == "active_only"
                and item.version_classification != "active"
            ):
                raise ValueError("selected version classification conflicts with request")
            if (
                self.request.version_mode == "historical_only"
                and item.version_classification != "historical"
            ):
                raise ValueError("selected version classification conflicts with request")
            if not _entry_matches_request(item.entry, self.request):
                raise ValueError("selected document does not satisfy request constraints")
        return self


T = TypeVar("T", bound=BaseModel)


def canonical_corpus_version_policy_bytes(policy: CorpusVersionPolicy) -> bytes:
    return _canonical_bytes(policy, CorpusVersionPolicy, "corpus version policy")


def canonical_corpus_selection_request_bytes(request: CorpusSelectionRequest) -> bytes:
    return _canonical_bytes(request, CorpusSelectionRequest, "corpus selection request")


def canonical_corpus_selection_result_bytes(result: CorpusSelectionResult) -> bytes:
    return _canonical_bytes(result, CorpusSelectionResult, "corpus selection result")


def load_corpus_version_policy_bytes(raw_bytes: bytes) -> CorpusVersionPolicy:
    return _load_bytes(raw_bytes, CorpusVersionPolicy, "corpus version policy")


def load_corpus_selection_request_bytes(raw_bytes: bytes) -> CorpusSelectionRequest:
    return _load_bytes(raw_bytes, CorpusSelectionRequest, "corpus selection request")


def load_corpus_selection_result_bytes(raw_bytes: bytes) -> CorpusSelectionResult:
    return _load_bytes(raw_bytes, CorpusSelectionResult, "corpus selection result")


def load_corpus_version_policy(path_value: str | Path) -> CorpusVersionPolicy:
    return _load_file(path_value, load_corpus_version_policy_bytes, "corpus version policy")


def load_corpus_selection_request(path_value: str | Path) -> CorpusSelectionRequest:
    return _load_file(path_value, load_corpus_selection_request_bytes, "corpus selection request")


def load_corpus_selection_result(path_value: str | Path) -> CorpusSelectionResult:
    return _load_file(path_value, load_corpus_selection_result_bytes, "corpus selection result")


def _canonical_bytes(value: T, model_type: type[T], label: str) -> bytes:
    try:
        if not isinstance(value, model_type):
            raise TypeError
        validated = model_type.model_validate(value.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValidationError, ValueError):
        raise CorpusVersionSchemaError(f"{label} is invalid or unsupported") from None
    return f"{serialized}\n".encode("utf-8")


def _load_bytes(raw_bytes: bytes, model_type: type[T], label: str) -> T:
    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        supported_versions = (
            SUPPORTED_CORPUS_VERSION_POLICY_SCHEMA_VERSIONS
            if model_type is CorpusVersionPolicy
            else SUPPORTED_CORPUS_SELECTION_SCHEMA_VERSIONS
        )
        if not isinstance(payload, dict) or payload.get("schema_version") not in supported_versions:
            raise ValueError
        return model_type.model_validate(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValidationError, ValueError):
        raise CorpusVersionSchemaError(f"{label} bytes are invalid or unsupported") from None


def _load_file(path_value: str | Path, loader, label: str):
    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError
        raw_bytes = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise CorpusVersionSchemaError(f"{label} file is unavailable or unsafe") from None
    return loader(raw_bytes)


def _validate_id(value: str) -> None:
    if (
        not isinstance(value, str)
        or _SAFE_ID.fullmatch(value) is None
        or value.upper() in _WINDOWS_RESERVED
        or value.split(".", maxsplit=1)[0].upper() in _WINDOWS_RESERVED
    ):
        raise ValueError("ID is unsafe or unsupported")


def _entry_matches_request(
    entry: CorpusDocumentEntry,
    request: CorpusSelectionRequest,
) -> bool:
    identity = entry.identity
    return (
        (not request.document_ids or identity.document_id in request.document_ids)
        and (not request.institution_ids or identity.institution_id in request.institution_ids)
        and (
            not request.document_family_ids
            or identity.document_family_id in request.document_family_ids
        )
        and (
            not request.degree_levels
            or any(level in identity.degree_levels for level in request.degree_levels)
        )
        and (
            not request.intake_terms
            or any(term in identity.intake_terms for term in request.intake_terms)
        )
    )


def _reject_constant(_: str) -> Any:
    raise ValueError("non-finite JSON numbers are unsupported")


__all__ = [
    "CORPUS_SELECTION_SCHEMA_VERSION",
    "CORPUS_VERSION_POLICY_SCHEMA_VERSION",
    "SUPPORTED_CORPUS_SELECTION_SCHEMA_VERSIONS",
    "SUPPORTED_CORPUS_VERSION_POLICY_SCHEMA_VERSIONS",
    "CorpusFamilyVersionPolicy",
    "CorpusSelectionRequest",
    "CorpusSelectionResult",
    "CorpusVersionPolicy",
    "CorpusVersionSchemaError",
    "SelectedCorpusDocument",
    "canonical_corpus_selection_request_bytes",
    "canonical_corpus_selection_result_bytes",
    "canonical_corpus_version_policy_bytes",
    "load_corpus_selection_request",
    "load_corpus_selection_request_bytes",
    "load_corpus_selection_result",
    "load_corpus_selection_result_bytes",
    "load_corpus_version_policy",
    "load_corpus_version_policy_bytes",
]
