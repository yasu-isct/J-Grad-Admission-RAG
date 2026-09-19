from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from jgrad_admission_rag.builder.extractor import ExtractedPage, extract_pdf
from jgrad_admission_rag.builder.kb_builder import build_document_kb
from jgrad_admission_rag.schemas.document_identity import (
    DocumentIdentity,
    load_document_identity,
)
from jgrad_admission_rag.schemas.document_kb import (
    DocumentKnowledgeBase,
    canonical_document_kb_bytes,
    load_document_kb_bytes,
)
from jgrad_admission_rag.utils import sha256_file


REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_PDF_MANIFEST_PATH = REPO_ROOT / "tests" / "fixtures" / "real_pdf_manifest.json"
REAL_IDENTITY_PATH = (
    REPO_ROOT / "src" / "jgrad_admission_rag" / "demo_config" / "document_identity.json"
)
REAL_PDF_ENV = "JGRAD_REAL_PDF"


@pytest.fixture(scope="session")
def real_pdf_manifest() -> dict[str, Any]:
    return json.loads(REAL_PDF_MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def real_pdf_path(real_pdf_manifest: dict[str, Any]) -> Path:
    filename = real_pdf_manifest["filename"]
    configured = os.getenv(REAL_PDF_ENV)
    configured_path = Path(configured).expanduser() if configured else None
    if configured_path and not configured_path.is_absolute():
        configured_path = REPO_ROOT / configured_path
    candidates = (
        configured_path,
        REPO_ROOT / "tests" / "fixtures" / "private" / filename,
        REPO_ROOT / "outputs" / "real_pdf" / filename,
    )
    path = next((candidate for candidate in candidates if candidate and candidate.is_file()), None)
    if path is None:
        pytest.skip(
            f"real PDF fixture unavailable; set {REAL_PDF_ENV} or follow tests/fixtures/README.md"
        )

    actual_hash = sha256_file(path)
    assert actual_hash == real_pdf_manifest["sha256"], (
        f"real PDF fixture hash mismatch: expected {real_pdf_manifest['sha256']}, got {actual_hash}"
    )
    return path


@pytest.fixture(scope="session")
def real_document_identity(real_pdf_manifest: dict[str, Any]) -> DocumentIdentity:
    identity = load_document_identity(REAL_IDENTITY_PATH)
    assert identity.source_pdf_sha256 == real_pdf_manifest["sha256"]
    return identity


@pytest.fixture(scope="session")
def real_document_kb_bytes(
    real_pdf_path: Path,
    real_document_identity: DocumentIdentity,
) -> bytes:
    """Build the expensive real-PDF baseline once and cache immutable canonical bytes."""
    return canonical_document_kb_bytes(build_document_kb(real_pdf_path, real_document_identity))


@pytest.fixture(scope="module")
def real_document_kb(real_document_kb_bytes: bytes) -> DocumentKnowledgeBase:
    """Give each test module a detached model so mutations cannot cross module boundaries."""
    return load_document_kb_bytes(real_document_kb_bytes)


@pytest.fixture(scope="session")
def extracted_pages(real_pdf_path: Path) -> list[ExtractedPage]:
    """Keep the extraction baseline separate because it validates pre-KB output directly."""
    return extract_pdf(real_pdf_path)
