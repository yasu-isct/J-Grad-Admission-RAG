"""Versioned experimental parser-pilot models and canonical serialization."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

PARSER_PILOT_CONTRACT_VERSION = "0.1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PilotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExactSource(PilotModel):
    """Acquisition input; ``path`` is deliberately absent from public output identity."""

    path: Path
    source_id: str
    expected_sha256: str
    expected_physical_page_count: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def validate_identity(self) -> ExactSource:
        if _SAFE_ID.fullmatch(self.source_id) is None:
            raise ValueError("source_id is unsafe or unsupported")
        if _SHA256.fullmatch(self.expected_sha256) is None:
            raise ValueError("expected_sha256 must be a lowercase SHA-256")
        return self


class ParseRequest(PilotModel):
    """Explicit full-document or subset selection in physical-page coordinates."""

    selection: Literal["all", "pages"] = "all"
    pages: tuple[int, ...] | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> ParseRequest:
        if self.selection == "all":
            if self.pages is not None:
                raise ValueError("all selection must not include pages")
            return self
        if not self.pages:
            raise ValueError("pages selection must be non-empty")
        if any(not isinstance(page, int) or isinstance(page, bool) or page <= 0 for page in self.pages):
            raise ValueError("physical pages must be positive integers")
        if tuple(sorted(set(self.pages))) != self.pages:
            raise ValueError("physical pages must be sorted and unique")
        return self


class SourceBinding(PilotModel):
    source_id: str
    source_pdf_sha256: str
    physical_page_count: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def validate_identity(self) -> SourceBinding:
        if _SAFE_ID.fullmatch(self.source_id) is None or _SHA256.fullmatch(self.source_pdf_sha256) is None:
            raise ValueError("source binding identity is invalid")
        return self


class DependencyVersion(PilotModel):
    package: str
    version: str

    @model_validator(mode="after")
    def validate_values(self) -> DependencyVersion:
        if not self.package or self.package != self.package.strip():
            raise ValueError("dependency package must be non-empty and trimmed")
        if not self.version or self.version != self.version.strip():
            raise ValueError("dependency version must be non-empty and trimmed")
        return self


class ParserProvenance(PilotModel):
    adapter_id: str
    adapter_revision: str
    dependencies: tuple[DependencyVersion, ...]
    model_revision: Literal["not-applicable"] = "not-applicable"
    configuration_digest: str

    @model_validator(mode="after")
    def validate_provenance(self) -> ParserProvenance:
        keys = tuple((item.package.lower(), item.version) for item in self.dependencies)
        if not keys or keys != tuple(sorted(set(keys))):
            raise ValueError("dependencies must be non-empty, sorted, and unique")
        if _SAFE_ID.fullmatch(self.adapter_id) is None or not self.adapter_revision:
            raise ValueError("adapter identity is invalid")
        if _SHA256.fullmatch(self.configuration_digest) is None:
            raise ValueError("configuration digest must be lowercase SHA-256")
        return self


class PageSelection(PilotModel):
    context: Literal["all", "subset"]
    physical_pages: tuple[int, ...] = Field(min_length=1)

    @field_validator("physical_pages")
    @classmethod
    def pages_must_be_canonical(cls, pages: tuple[int, ...]) -> tuple[int, ...]:
        if (
            any(not isinstance(page, int) or isinstance(page, bool) or page <= 0 for page in pages)
            or tuple(sorted(set(pages))) != pages
        ):
            raise ValueError("selected physical pages must be positive, sorted, and unique")
        return pages


class BlockDiagnostics(PilotModel):
    legacy_char_count: int = Field(ge=0, strict=True)
    legacy_table_count: int = Field(ge=0, strict=True)
    legacy_scanned: bool


class NormalizedBlock(PilotModel):
    block_id: str
    block_type: Literal["legacy_page"] = "legacy_page"
    text: str
    text_format: Literal["markdown"] = "markdown"
    reading_order: Literal["coarse_page_aggregate"] = "coarse_page_aggregate"
    source_span: None = None
    bbox: None = None
    relationships: tuple[()] = ()
    diagnostics: BlockDiagnostics


class NormalizedPage(PilotModel):
    physical_page: int = Field(gt=0, strict=True)
    printed_page_label: None = None
    extraction_status: Literal[
        "text_extracted", "blank_or_unreadable", "scanned_without_ocr"
    ]
    blocks: tuple[NormalizedBlock, ...] = Field(min_length=1, max_length=1)
    diagnostics: tuple[str, ...]


class ParserCapabilities(PilotModel):
    block_granularity: Literal["coarse_page"] = "coarse_page"
    physical_page_identity: Literal["supported"] = "supported"
    printed_page_labels: Literal["unknown"] = "unknown"
    native_table_cells: Literal["unsupported"] = "unsupported"
    bbox: Literal["unsupported"] = "unsupported"
    heading_graph: Literal["unsupported"] = "unsupported"
    ocr: Literal["unsupported"] = "unsupported"
    clause_locator: Literal["unsupported"] = "unsupported"
    limitations: tuple[str, ...]

    @field_validator("limitations")
    @classmethod
    def limitations_must_be_explicit(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or any(not value or value != value.strip() for value in values):
            raise ValueError("capability limitations must be explicit and trimmed")
        return values


class Coverage(PilotModel):
    requested_pages: int = Field(ge=1, strict=True)
    returned_pages: int = Field(ge=0, strict=True)
    successful_text_pages: int = Field(ge=0, strict=True)
    scanned_without_ocr_pages: tuple[int, ...]
    blank_or_unreadable_pages: tuple[int, ...]
    missing_pages: tuple[int, ...]


class NormalizedDocument(PilotModel):
    contract_version: Literal["0.1"] = PARSER_PILOT_CONTRACT_VERSION
    artifact_role: Literal["experimental_parser_comparison_only"] = (
        "experimental_parser_comparison_only"
    )
    run_id: str
    source: SourceBinding
    selection: PageSelection
    provenance: ParserProvenance
    pages: tuple[NormalizedPage, ...]
    coverage: Coverage
    capabilities: ParserCapabilities
    output_digest: str

    @model_validator(mode="after")
    def validate_document_shape(self) -> NormalizedDocument:
        requested = self.selection.physical_pages
        returned = tuple(page.physical_page for page in self.pages)
        if returned != requested:
            raise ValueError("normalized pages must exactly match requested physical pages")
        if self.coverage.requested_pages != len(requested):
            raise ValueError("requested page count is inconsistent")
        if self.coverage.returned_pages != len(returned):
            raise ValueError("returned page count is inconsistent")
        if self.coverage.missing_pages:
            raise ValueError("a complete document cannot contain missing requested pages")
        if max(requested) > self.source.physical_page_count:
            raise ValueError("requested page exceeds source physical page count")
        if self.selection.context == "all" and requested != tuple(
            range(1, self.source.physical_page_count + 1)
        ):
            raise ValueError("all context must contain every physical page")
        statuses = {page.physical_page: page.extraction_status for page in self.pages}
        blank = tuple(page for page in requested if statuses[page] == "blank_or_unreadable")
        scanned = tuple(page for page in requested if statuses[page] == "scanned_without_ocr")
        successful = sum(status == "text_extracted" for status in statuses.values())
        if (
            self.coverage.blank_or_unreadable_pages != blank
            or self.coverage.scanned_without_ocr_pages != scanned
            or self.coverage.successful_text_pages != successful
        ):
            raise ValueError("coverage diagnostics are inconsistent with page records")
        for page in self.pages:
            if page.blocks[0].block_id != f"p{page.physical_page:05d}-b00001":
                raise ValueError("legacy block locator is inconsistent with physical page")
        if _SHA256.fullmatch(self.run_id) is None or _SHA256.fullmatch(self.output_digest) is None:
            raise ValueError("run and output identities must be lowercase SHA-256")
        return self


def canonical_json_bytes(payload: object) -> bytes:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{serialized}\n".encode("utf-8")


def normalized_document_content_bytes(document: NormalizedDocument) -> bytes:
    """Canonical deterministic content covered by ``output_digest``."""

    payload = document.model_dump(mode="json", exclude={"output_digest"})
    return canonical_json_bytes(payload)


def calculate_run_id(
    source: SourceBinding,
    selection: PageSelection,
    provenance: ParserProvenance,
    *,
    contract_version: str = PARSER_PILOT_CONTRACT_VERSION,
) -> str:
    payload = {
        "adapter_id": provenance.adapter_id,
        "adapter_revision": provenance.adapter_revision,
        "configuration_digest": provenance.configuration_digest,
        "contract_version": contract_version,
        "dependencies": [item.model_dump(mode="json") for item in provenance.dependencies],
        "model_revision": provenance.model_revision,
        "selection": selection.model_dump(mode="json"),
        "source": source.model_dump(mode="json"),
    }
    return sha256(canonical_json_bytes(payload)).hexdigest()


def canonical_normalized_document_bytes(document: NormalizedDocument) -> bytes:
    """Serialize a verified complete document including its output digest."""

    verify_normalized_document(document)
    return canonical_json_bytes(document.model_dump(mode="json"))


def verify_normalized_document(document: NormalizedDocument) -> None:
    expected_run_id = calculate_run_id(
        document.source,
        document.selection,
        document.provenance,
        contract_version=document.contract_version,
    )
    if document.run_id != expected_run_id:
        raise ValueError("normalized document run identity does not match its context")
    expected = sha256(normalized_document_content_bytes(document)).hexdigest()
    if document.output_digest != expected:
        raise ValueError("normalized document output digest does not match its content")


def load_normalized_document_bytes(raw_bytes: bytes) -> NormalizedDocument:
    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        document = NormalizedDocument.model_validate(payload)
        verify_normalized_document(document)
        if canonical_json_bytes(document.model_dump(mode="json")) != raw_bytes:
            raise ValueError
        return document
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValidationError, ValueError):
        raise ValueError("normalized document bytes are invalid or non-canonical") from None


def load_normalized_document(path: str | Path) -> NormalizedDocument:
    try:
        source_path = Path(path)
        if source_path.is_symlink() or not source_path.is_file():
            raise OSError
        raw_bytes = source_path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise ValueError("normalized document file is unavailable or unsafe") from None
    return load_normalized_document_bytes(raw_bytes)


def _reject_constant(_: str) -> None:
    raise ValueError("non-finite JSON number")
