from __future__ import annotations

from jgrad_admission_rag.schemas.document_identity import DocumentIdentity

DEFAULT_PDF_SHA256 = "a" * 64


def make_document_identity(
    *,
    document_id: str = "sample-document",
    pdf_sha256: str = DEFAULT_PDF_SHA256,
) -> DocumentIdentity:
    """Return explicit reviewed identity data for synthetic test documents."""

    return DocumentIdentity(
        document_id=document_id,
        document_family_id=f"{document_id}-family",
        edition_id="2027-edition",
        institution_id="sample-university",
        institution_name="Sample University",
        degree_levels=["master"],
        intake_terms=[{"year": 2027, "month": 4}],
        official_title="Sample Graduate Admission Guidelines",
        official_source_url="https://example.edu/admissions/guidelines.pdf",
        source_pdf_sha256=pdf_sha256,
    )
