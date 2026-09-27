"""Isolated pilot adapter around the unchanged legacy PDF extractor."""

from __future__ import annotations

from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import NoReturn

import fitz

from jgrad_admission_rag.builder.extractor import ExtractedPage, extract_pdf

from .contracts import (
    BlockDiagnostics,
    Coverage,
    DependencyVersion,
    ExactSource,
    NormalizedBlock,
    NormalizedDocument,
    NormalizedPage,
    PageSelection,
    ParseRequest,
    ParserCapabilities,
    ParserProvenance,
    SourceBinding,
    calculate_run_id,
    canonical_json_bytes,
    normalized_document_content_bytes,
)

ADAPTER_ID = "jgrad-legacy-extract-pdf"
ADAPTER_REVISION = "1"
_CONFIGURATION = {
    "block_granularity": "one-legacy-page-payload",
    "printed_page_labels": "unknown",
    "text_format": "markdown",
}
_LIMITATIONS = (
    "Each block is a whole-page legacy aggregate, not an exact clause locator.",
    "Printed labels, bounding boxes, heading relationships, and native table cells are unknown.",
    "OCR is not performed; image-only pages may have no extracted text.",
)


class LegacyAdapterError(Exception):
    """Bounded adapter failure carrying a stable machine-readable category."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def parse_legacy_pdf(source: ExactSource, request: ParseRequest) -> NormalizedDocument:
    """Validate an exact source, then wrap legacy pages without changing their payloads."""

    source_path, actual_hash, page_count = _validate_source(source)
    effective_pages = _effective_pages(request, page_count)
    dependencies = _dependency_versions()
    configuration_digest = sha256(canonical_json_bytes(_CONFIGURATION)).hexdigest()
    selection = PageSelection(
        context="all" if request.selection == "all" else "subset",
        physical_pages=effective_pages,
    )
    source_binding = SourceBinding(
        source_id=source.source_id,
        source_pdf_sha256=actual_hash,
        physical_page_count=page_count,
    )
    provenance = ParserProvenance(
        adapter_id=ADAPTER_ID,
        adapter_revision=ADAPTER_REVISION,
        dependencies=dependencies,
        configuration_digest=configuration_digest,
    )
    run_id = calculate_run_id(source_binding, selection, provenance)

    try:
        extracted = extract_pdf(
            source_path,
            None if request.selection == "all" else list(effective_pages),
        )
    except Exception as error:
        raise LegacyAdapterError("extraction_failed", "legacy PDF extraction failed") from error

    try:
        final_hash = _sha256_file(source_path)
    except OSError as error:
        raise LegacyAdapterError(
            "source_changed", "source PDF became unavailable during extraction"
        ) from error
    if final_hash != actual_hash:
        _fail("source_changed", "source bytes changed during extraction")
    _validate_legacy_result(extracted, effective_pages)
    pages = tuple(_normalize_page(page) for page in extracted)
    blank = tuple(
        page.physical_page for page in pages if page.extraction_status == "blank_or_unreadable"
    )
    scanned = tuple(
        page.physical_page for page in pages if page.extraction_status == "scanned_without_ocr"
    )
    successful = sum(page.extraction_status == "text_extracted" for page in pages)
    provisional = NormalizedDocument(
        run_id=run_id,
        source=source_binding,
        selection=selection,
        provenance=provenance,
        pages=pages,
        coverage=Coverage(
            requested_pages=len(effective_pages),
            returned_pages=len(pages),
            successful_text_pages=successful,
            scanned_without_ocr_pages=scanned,
            blank_or_unreadable_pages=blank,
            missing_pages=(),
        ),
        capabilities=ParserCapabilities(limitations=_LIMITATIONS),
        output_digest="0" * 64,
    )
    output_digest = sha256(normalized_document_content_bytes(provisional)).hexdigest()
    return provisional.model_copy(update={"output_digest": output_digest})


def _validate_source(source: ExactSource) -> tuple[Path, str, int]:
    path = source.path
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError
        actual_hash = _sha256_file(path)
    except (OSError, PermissionError):
        _fail("source_unavailable", "source PDF is missing, unreadable, or unsafe")
    if actual_hash != source.expected_sha256:
        _fail("source_hash_mismatch", "source PDF SHA-256 does not match the exact source")
    try:
        with fitz.open(path) as document:
            page_count = len(document)
    except Exception as error:
        raise LegacyAdapterError("source_invalid", "source PDF cannot be opened") from error
    if page_count != source.expected_physical_page_count:
        _fail("source_page_count_mismatch", "source PDF physical page count does not match")
    return path, actual_hash, page_count


def _effective_pages(request: ParseRequest, page_count: int) -> tuple[int, ...]:
    if request.selection == "all":
        return tuple(range(1, page_count + 1))
    assert request.pages is not None
    if request.pages[-1] > page_count:
        _fail("page_out_of_range", "requested physical page is outside the source PDF")
    return request.pages


def _dependency_versions() -> tuple[DependencyVersion, ...]:
    dependencies = []
    for distribution in ("pdfplumber", "PyMuPDF"):
        try:
            installed = version(distribution)
        except PackageNotFoundError:
            _fail("dependency_unavailable", f"required dependency is not installed: {distribution}")
        dependencies.append(DependencyVersion(package=distribution, version=installed))
    return tuple(sorted(dependencies, key=lambda item: item.package.lower()))


def _normalize_page(page: ExtractedPage) -> NormalizedPage:
    if page.scanned:
        status = "scanned_without_ocr"
        diagnostics = ("legacy extractor detected a likely scanned page; OCR was not run",)
    elif page.char_count == 0 and page.table_count == 0:
        status = "blank_or_unreadable"
        diagnostics = ("legacy extractor returned no text or tables",)
    else:
        status = "text_extracted"
        diagnostics = ()
    return NormalizedPage(
        physical_page=page.page,
        extraction_status=status,
        blocks=(
            NormalizedBlock(
                block_id=f"p{page.page:05d}-b00001",
                text=page.markdown,
                diagnostics=BlockDiagnostics(
                    legacy_char_count=page.char_count,
                    legacy_table_count=page.table_count,
                    legacy_scanned=page.scanned,
                ),
            ),
        ),
        diagnostics=diagnostics,
    )


def _validate_legacy_result(
    extracted: list[ExtractedPage], effective_pages: tuple[int, ...]
) -> None:
    returned = tuple(page.page for page in extracted)
    if returned != effective_pages or len(returned) != len(set(returned)):
        _fail("incomplete_extraction", "legacy extractor did not return every requested page once")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fail(code: str, message: str) -> NoReturn:
    raise LegacyAdapterError(code, message)
