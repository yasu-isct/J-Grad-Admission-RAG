"""Experimental parser-pilot contracts and adapters."""

from .contracts import (
    ExactSource,
    NormalizedDocument,
    ParseRequest,
    canonical_normalized_document_bytes,
    load_normalized_document,
    load_normalized_document_bytes,
    verify_normalized_document,
)
from .legacy_adapter import LegacyAdapterError, parse_legacy_pdf

__all__ = [
    "ExactSource",
    "LegacyAdapterError",
    "NormalizedDocument",
    "ParseRequest",
    "canonical_normalized_document_bytes",
    "load_normalized_document",
    "load_normalized_document_bytes",
    "parse_legacy_pdf",
    "verify_normalized_document",
]
