from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..schemas.document_kb import DocumentKnowledgeBase
from ..schemas.index import IndexManifest, validate_source_kb_compatibility
from .embedding import EmbeddingIdentity
from .local_index import LocalVectorIndex
from .source_kb import SourceKbReadError, read_source_kb_exact

FRESHNESS_CHECKED_FIELDS = (
    "source_kb_sha256",
    "document_id",
    "source_pdf_sha256",
    "embedding_provider",
    "embedding_model",
    "embedding_revision",
    "embedding_dimension",
)


class IndexFreshnessError(Exception):
    """Base class for current-input freshness failures."""


class CurrentKbInputError(IndexFreshnessError):
    """Raised when the current KB cannot participate in a freshness comparison."""


class StaleIndexError(IndexFreshnessError):
    """Raised when a valid index does not match current declared inputs."""

    def __init__(self, mismatches: tuple[str, ...]) -> None:
        self.mismatches = mismatches
        super().__init__("index is stale: " + ", ".join(mismatches))


@dataclass(frozen=True, slots=True)
class IndexFreshnessReport:
    fresh: Literal[True]
    current_kb_sha256: str
    checked_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FreshIndexContext:
    freshness: IndexFreshnessReport
    _knowledge_base_snapshot: bytes

    @classmethod
    def from_knowledge_base(
        cls,
        freshness: IndexFreshnessReport,
        knowledge_base: DocumentKnowledgeBase,
    ) -> FreshIndexContext:
        """Freeze a validated KB snapshot while exposing only detached parsed copies."""

        if not isinstance(knowledge_base, DocumentKnowledgeBase):
            raise TypeError("knowledge_base must be a DocumentKnowledgeBase")
        return cls(
            freshness=freshness,
            _knowledge_base_snapshot=knowledge_base.model_dump_json().encode("utf-8"),
        )

    @property
    def knowledge_base(self) -> DocumentKnowledgeBase:
        return DocumentKnowledgeBase.model_validate_json(self._knowledge_base_snapshot)


def check_index_freshness(
    index: IndexManifest | LocalVectorIndex,
    current_kb_path: str | Path,
    declared_identity: EmbeddingIdentity,
) -> IndexFreshnessReport:
    """Compare a validated index with exact current KB bytes and declared provider identity."""

    return load_fresh_index_context(index, current_kb_path, declared_identity).freshness


def load_fresh_index_context(
    index: IndexManifest | LocalVectorIndex,
    current_kb_path: str | Path,
    declared_identity: EmbeddingIdentity,
) -> FreshIndexContext:
    """Read the current KB once and retain the exact validated object used for freshness."""

    manifest = index.manifest if isinstance(index, LocalVectorIndex) else index
    if not isinstance(manifest, IndexManifest):
        raise TypeError("index must be an IndexManifest or LocalVectorIndex")
    try:
        source = read_source_kb_exact(current_kb_path)
    except SourceKbReadError as error:
        raise CurrentKbInputError(str(error)) from error
    try:
        validate_source_kb_compatibility(source.knowledge_base)
    except ValueError as error:
        raise CurrentKbInputError("current KB schema is unsupported") from error
    if not source.knowledge_base.diagnostics.quality_gate.passed:
        raise CurrentKbInputError("current KB quality gate did not pass")

    current_values = {
        "source_kb_sha256": source.sha256,
        "document_id": source.knowledge_base.manifest.document_id,
        "source_pdf_sha256": source.knowledge_base.manifest.pdf_sha256,
        "embedding_provider": declared_identity.provider,
        "embedding_model": declared_identity.model,
        "embedding_revision": declared_identity.revision,
        "embedding_dimension": declared_identity.dimension,
    }
    expected_values = {
        "source_kb_sha256": manifest.source_kb_sha256,
        "document_id": manifest.document_id,
        "source_pdf_sha256": manifest.source_pdf_sha256,
        "embedding_provider": manifest.embedding_provider,
        "embedding_model": manifest.embedding_model,
        "embedding_revision": manifest.embedding_revision,
        "embedding_dimension": manifest.embedding_dimension,
    }
    mismatches = tuple(
        field
        for field in FRESHNESS_CHECKED_FIELDS
        if current_values[field] != expected_values[field]
    )
    if mismatches:
        raise StaleIndexError(mismatches)
    report = IndexFreshnessReport(
        fresh=True,
        current_kb_sha256=source.sha256,
        checked_fields=FRESHNESS_CHECKED_FIELDS,
    )
    return FreshIndexContext.from_knowledge_base(report, source.knowledge_base)
