"""Reviewed identity and exact-source version binding for one official document."""

from __future__ import annotations

import ipaddress
import json
import re
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

DOCUMENT_IDENTITY_SCHEMA_VERSION = "1.0"
SUPPORTED_DOCUMENT_IDENTITY_SCHEMA_VERSIONS = frozenset({DOCUMENT_IDENTITY_SCHEMA_VERSION})

__all__ = [
    "DOCUMENT_IDENTITY_SCHEMA_VERSION",
    "SUPPORTED_DOCUMENT_IDENTITY_SCHEMA_VERSIONS",
    "DegreeLevel",
    "DocumentIdentity",
    "DocumentIdentityError",
    "IntakeTerm",
    "canonical_document_identity_bytes",
    "load_document_identity",
    "load_document_identity_bytes",
]

_SAFE_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_WINDOWS_RESERVED_IDS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


class DocumentIdentityError(Exception):
    """Raised when reviewed document identity is invalid or unavailable."""


class IdentityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DegreeLevel(str, Enum):
    MASTER = "master"
    DOCTORAL = "doctoral"
    PROFESSIONAL_DEGREE = "professional_degree"


class IntakeTerm(IdentityModel):
    year: int = Field(gt=0, strict=True)
    month: int = Field(ge=1, le=12, strict=True)


class DocumentIdentity(IdentityModel):
    schema_version: Literal["1.0"] = DOCUMENT_IDENTITY_SCHEMA_VERSION
    document_id: str
    document_family_id: str
    edition_id: str
    institution_id: str
    institution_name: str
    degree_levels: tuple[DegreeLevel, ...] = Field(min_length=1)
    intake_terms: tuple[IntakeTerm, ...] = Field(min_length=1)
    official_title: str
    official_source_url: str
    source_pdf_sha256: str
    publication_date: date | None = None
    revision_date: date | None = None

    @field_validator(
        "document_id",
        "document_family_id",
        "edition_id",
        "institution_id",
    )
    @classmethod
    def ids_must_be_path_independent(cls, value: str) -> str:
        if (
            _SAFE_ID.fullmatch(value) is None
            or value.upper() in _WINDOWS_RESERVED_IDS
            or value.split(".", maxsplit=1)[0].upper() in _WINDOWS_RESERVED_IDS
        ):
            raise ValueError("identity ID is unsafe or unsupported")
        return value

    @field_validator("institution_name", "official_title")
    @classmethod
    def display_text_must_be_explicit(cls, value: str) -> str:
        if not value or value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("identity display text must be non-empty and trimmed")
        return value

    @field_validator("degree_levels")
    @classmethod
    def degree_levels_must_be_canonical(
        cls, values: tuple[DegreeLevel, ...]
    ) -> tuple[DegreeLevel, ...]:
        if len(values) != len(set(values)):
            raise ValueError("degree levels must be unique")
        return tuple(sorted(values, key=lambda item: item.value))

    @field_validator("intake_terms")
    @classmethod
    def intake_terms_must_be_canonical(
        cls, values: tuple[IntakeTerm, ...]
    ) -> tuple[IntakeTerm, ...]:
        keys = tuple((item.year, item.month) for item in values)
        if len(keys) != len(set(keys)):
            raise ValueError("intake terms must be unique")
        return tuple(sorted(values, key=lambda item: (item.year, item.month)))

    @field_validator("official_source_url")
    @classmethod
    def source_url_must_be_canonical_public_https(cls, value: str) -> str:
        _validate_source_url(value)
        return value

    @field_validator("source_pdf_sha256")
    @classmethod
    def source_hash_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value


def canonical_document_identity_bytes(identity: DocumentIdentity) -> bytes:
    """Serialize a fully revalidated identity as canonical UTF-8 JSON with LF."""

    try:
        if not isinstance(identity, DocumentIdentity):
            raise TypeError
        validated = DocumentIdentity.model_validate(identity.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValidationError, ValueError):
        raise DocumentIdentityError("document identity is invalid or unsupported") from None
    return f"{serialized}\n".encode("utf-8")


def load_document_identity_bytes(raw_bytes: bytes) -> DocumentIdentity:
    """Load strict versioned identity JSON without echoing supplied content."""

    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") not in SUPPORTED_DOCUMENT_IDENTITY_SCHEMA_VERSIONS
        ):
            raise ValueError
        return DocumentIdentity.model_validate(payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValidationError,
        ValueError,
    ):
        raise DocumentIdentityError("document identity bytes are invalid or unsupported") from None


def load_document_identity(path_value: str | Path) -> DocumentIdentity:
    """Load identity only from a regular non-symlinked file."""

    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError
        raw_bytes = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise DocumentIdentityError("document identity file is unavailable or unsafe") from None
    return load_document_identity_bytes(raw_bytes)


def _validate_source_url(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or not value.startswith("https://")
        or "\\" in value
    ):
        raise ValueError("source URL is invalid")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.hostname is None
        or any(character.isupper() for character in parsed.netloc)
    ):
        raise ValueError("source URL must be canonical public HTTPS")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("source URL must be canonical public HTTPS") from None
    if port == 443:
        raise ValueError("source URL must omit the default HTTPS port")
    hostname = parsed.hostname
    if hostname.endswith("."):
        raise ValueError("source URL host must be canonical")
    if (
        not hostname
        or hostname == "localhost"
        or hostname.endswith((".localhost", ".local", ".internal", ".lan", ".home"))
    ):
        raise ValueError("source URL host is not public")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is None and "." not in hostname:
        raise ValueError("source URL host is not public")
    if address is not None and not address.is_global:
        raise ValueError("source URL host is not public")
    decoded_path = unquote(parsed.path)
    if (
        "\x00" in decoded_path
        or "\\" in decoded_path
        or any(part in {".", ".."} for part in decoded_path.split("/"))
    ):
        raise ValueError("source URL path is unsafe")


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("value must be lowercase SHA-256")


def _reject_constant(_: str) -> Any:
    raise ValueError("non-finite JSON numbers are unsupported")
