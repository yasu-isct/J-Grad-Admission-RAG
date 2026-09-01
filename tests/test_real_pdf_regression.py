from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from jgrad_admission_rag.builder.extractor import ExtractedPage, extract_pdf
from jgrad_admission_rag.builder.kb_builder import build_document_kb
from jgrad_admission_rag.schemas.document_kb import DocumentKnowledgeBase
from jgrad_admission_rag.utils import sha256_file

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "tests" / "fixtures" / "real_pdf_manifest.json"
REAL_PDF_ENV = "JGRAD_REAL_PDF"

pytestmark = pytest.mark.real_pdf


@pytest.fixture(scope="module")
def real_pdf_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real_pdf_path(real_pdf_manifest: dict[str, Any]) -> Path:
    filename = real_pdf_manifest["filename"]
    configured = os.getenv(REAL_PDF_ENV)
    configured_path = Path(configured).expanduser() if configured else None
    if configured_path and not configured_path.is_absolute():
        configured_path = REPO_ROOT / configured_path
    candidates = [
        configured_path,
        REPO_ROOT / "tests" / "fixtures" / "private" / filename,
        REPO_ROOT / "outputs" / "real_pdf" / filename,
    ]
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


@pytest.fixture(scope="module")
def extracted_pages(real_pdf_path: Path) -> list[ExtractedPage]:
    return extract_pdf(real_pdf_path)


@pytest.fixture(scope="module")
def real_document_kb(real_pdf_path: Path) -> DocumentKnowledgeBase:
    return build_document_kb(real_pdf_path)


def test_real_pdf_extraction_matches_baseline(
    real_pdf_manifest: dict[str, Any],
    extracted_pages: list[ExtractedPage],
) -> None:
    expected = real_pdf_manifest["expected"]
    assert len(extracted_pages) == expected["page_count"]
    assert [page.page for page in extracted_pages] == list(range(1, expected["page_count"] + 1))
    assert sum(page.table_count for page in extracted_pages) == expected["table_count"]
    assert sum(page.scanned for page in extracted_pages) == expected["scanned_page_count"]

    extracted_text = "\n".join(page.markdown for page in extracted_pages)
    for marker in real_pdf_manifest["text_markers"]:
        assert marker in extracted_text


def test_real_pdf_knowledge_base_matches_baseline(
    real_pdf_manifest: dict[str, Any],
    real_document_kb: DocumentKnowledgeBase,
) -> None:
    expected = real_pdf_manifest["expected"]
    manifest = real_document_kb.manifest
    assert manifest.schema_version == "0.2"
    assert manifest.pdf_sha256 == real_pdf_manifest["sha256"]
    assert manifest.chunk_count == expected["chunk_count"]
    assert manifest.reference_link_count == expected["reference_link_count"]
    assert len(real_document_kb.entities) == expected["entity_count"]
    assert len(real_document_kb.facts) == expected["fact_count"]
    assert len(real_document_kb.retrieval_units) == expected["retrieval_unit_count"]

    assert all(fact.source_pages for fact in real_document_kb.facts)
    assert all(unit.source_pages for unit in real_document_kb.retrieval_units)
    assert all(fact.section_path for fact in real_document_kb.facts)
    assert all(unit.section_path for unit in real_document_kb.retrieval_units)
    assert all(
        1 <= page <= expected["page_count"]
        for fact in real_document_kb.facts
        for page in fact.source_pages
    )

    fact_ids = [fact.fact_id for fact in real_document_kb.facts]
    assert fact_ids == [f"fact:{index:05d}" for index in range(expected["fact_count"])]
    assert len(fact_ids) == len(set(fact_ids))
    assert {unit.fact_id for unit in real_document_kb.retrieval_units} == set(fact_ids)
    pages_by_fact = {fact.fact_id: fact.source_pages for fact in real_document_kb.facts}
    paths_by_fact = {fact.fact_id: fact.section_path for fact in real_document_kb.facts}
    assert all(
        unit.source_pages == pages_by_fact[unit.fact_id]
        for unit in real_document_kb.retrieval_units
    )
    assert all(
        unit.section_path == paths_by_fact[unit.fact_id]
        for unit in real_document_kb.retrieval_units
    )

    assert any(fact.scope_type == "department" for fact in real_document_kb.facts)
    assert any("情報工学系" in fact.scope_targets for fact in real_document_kb.facts)
    assert any(fact.metadata["anchors"] for fact in real_document_kb.facts)
    assert any(
        reference["label"].startswith("下記")
        for fact in real_document_kb.facts
        for reference in fact.metadata["references"]
    )
