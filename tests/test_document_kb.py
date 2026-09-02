import json

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    BuildQualityThresholds,
    DocumentKnowledgeBase,
    DocumentKnowledgeBaseError,
    KnowledgeManifest,
    LegacyDocumentKnowledgeBaseV05,
    ReferenceDiagnostic,
    RetrievalUnit,
    ScopedFact,
    canonical_document_kb_bytes,
    load_document_kb_bytes,
    migrate_document_kb_v05,
    migrate_document_kb_v05_bytes,
)
from tests.identity_helpers import DEFAULT_PDF_SHA256, make_document_identity


def _fact() -> ScopedFact:
    return ScopedFact(
        fact_id="fact:00001",
        fact_type="fees",
        scope_type="global",
        title="検定料",
        text="検定料は30,000円です。",
        source_pages=[10],
        section_path=["３．出願手続", "（１）検定料"],
        embedding_text="fees 検定料 30,000円",
    )


def _kb() -> DocumentKnowledgeBase:
    fact = _fact()
    return DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            identity=make_document_identity(document_id="sample"),
            source_pdf="sample.pdf",
            chunk_count=1,
        ),
        facts=[fact],
        retrieval_units=[
            RetrievalUnit(
                unit_id="unit:00001",
                fact_id=fact.fact_id,
                text=fact.embedding_text,
                source_pages=fact.source_pages,
                section_path=fact.section_path,
            )
        ],
    )


def _legacy_payload() -> dict:
    payload = _kb().model_dump(mode="json")
    identity = payload["manifest"].pop("identity")
    payload["manifest"]["document_id"] = identity["document_id"]
    payload["manifest"]["pdf_sha256"] = identity["source_pdf_sha256"]
    payload["manifest"]["schema_version"] = "0.5"
    return payload


def test_document_kb_schema_roundtrip_uses_identity_as_sole_authority() -> None:
    kb = _kb()
    payload = kb.model_dump(mode="json")
    restored = DocumentKnowledgeBase.model_validate(payload)

    assert restored.facts[0].title == "検定料"
    assert restored.manifest.schema_version == "0.6"
    assert restored.manifest.document_id == "sample"
    assert restored.manifest.pdf_sha256 == DEFAULT_PDF_SHA256
    assert "document_id" not in payload["manifest"]
    assert "pdf_sha256" not in payload["manifest"]
    assert payload["manifest"]["identity"]["document_id"] == "sample"
    assert restored.diagnostics == BuildDiagnostics()
    assert restored.retrieval_units[0].section_path == restored.facts[0].section_path


def test_document_kb_canonical_bytes_are_deterministic_and_strict() -> None:
    raw = canonical_document_kb_bytes(_kb())
    assert raw == canonical_document_kb_bytes(load_document_kb_bytes(raw))
    assert raw.endswith(b"\n")

    payload = json.loads(raw)
    payload["unexpected"] = True
    with pytest.raises(DocumentKnowledgeBaseError, match="invalid or unsupported"):
        load_document_kb_bytes(json.dumps(payload).encode())


def test_document_kb_rejects_legacy_versions_without_explicit_migration() -> None:
    with pytest.raises(DocumentKnowledgeBaseError, match="invalid or unsupported"):
        load_document_kb_bytes(json.dumps(_legacy_payload()).encode())


def test_v05_migration_requires_exact_reviewed_identity_and_preserves_content() -> None:
    legacy_payload = _legacy_payload()
    legacy = LegacyDocumentKnowledgeBaseV05.model_validate(legacy_payload)
    migrated = migrate_document_kb_v05(legacy, make_document_identity(document_id="sample"))
    migrated_payload = migrated.model_dump(mode="json")

    assert migrated.manifest.schema_version == "0.6"
    assert migrated.manifest.document_id == legacy.manifest.document_id
    assert migrated.manifest.pdf_sha256 == legacy.manifest.pdf_sha256
    for field in ("entities", "facts", "retrieval_units", "diagnostics"):
        assert migrated_payload[field] == legacy_payload[field]
    for field in (
        "source_pdf",
        "builder_version",
        "input_chunk_count",
        "chunk_count",
        "dropped_chunk_count",
        "dropped_chunk_reasons",
        "merged_heading_count",
        "reference_link_count",
        "chunk_size_limit",
        "max_chunk_chars",
        "oversized_chunk_count",
        "oversized_chunk_reasons",
    ):
        assert migrated_payload["manifest"][field] == legacy_payload["manifest"][field]

    migrated_from_bytes = migrate_document_kb_v05_bytes(
        json.dumps(legacy_payload).encode(), make_document_identity(document_id="sample")
    )
    assert canonical_document_kb_bytes(migrated_from_bytes) == canonical_document_kb_bytes(migrated)


@pytest.mark.parametrize(
    "identity",
    [
        make_document_identity(document_id="different"),
        make_document_identity(document_id="sample", pdf_sha256="b" * 64),
    ],
)
def test_v05_migration_fails_closed_on_identity_mismatch(identity) -> None:
    with pytest.raises(DocumentKnowledgeBaseError, match="invalid or inconsistent") as error:
        migrate_document_kb_v05_bytes(json.dumps(_legacy_payload()).encode(), identity)
    assert "different" not in str(error.value)
    assert "bbbb" not in str(error.value)


def test_v05_migration_rejects_missing_or_unsupported_input_generically() -> None:
    payload = _legacy_payload()
    del payload["manifest"]["pdf_sha256"]
    with pytest.raises(DocumentKnowledgeBaseError, match="invalid or unsupported"):
        migrate_document_kb_v05_bytes(json.dumps(payload).encode(), make_document_identity())

    payload = _legacy_payload()
    payload["manifest"]["schema_version"] = "0.4"
    with pytest.raises(DocumentKnowledgeBaseError, match="invalid or unsupported"):
        migrate_document_kb_v05_bytes(json.dumps(payload).encode(), make_document_identity())


def test_quality_thresholds_reject_negative_limits() -> None:
    with pytest.raises(ValidationError, match="non-negative"):
        BuildQualityThresholds(max_unknown_scope_facts=-1)


def test_diagnostics_roundtrip_preserves_reference_claim_order() -> None:
    claims = [
        ReferenceDiagnostic(
            source_fact_id=f"fact:{index:05d}",
            label=f"claim-{index}",
            reference_key="item:1",
            direction="forward",
            status="unresolved",
            reason="no_positive_candidate",
        )
        for index in (2, 1)
    ]
    kb = DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            identity=make_document_identity(document_id="sample"),
            source_pdf="sample.pdf",
            chunk_count=0,
        ),
        diagnostics=BuildDiagnostics(reference_claim_count=2, reference_claims=claims),
    )

    restored = DocumentKnowledgeBase.model_validate(kb.model_dump(mode="json"))
    assert [claim.source_fact_id for claim in restored.diagnostics.reference_claims] == [
        "fact:00002",
        "fact:00001",
    ]
    assert restored.diagnostics.quality_thresholds == BuildQualityThresholds()
