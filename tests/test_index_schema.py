from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.schemas.document_kb import (
    DocumentKnowledgeBase,
    KnowledgeManifest,
    RetrievalUnit,
    ScopedFact,
)
from jgrad_admission_rag.schemas.index import (
    IndexManifest,
    IndexPayload,
    derive_index_payloads,
    payloads_from_jsonl,
    payloads_to_jsonl,
    validate_manifest_compatibility,
    validate_payload_collection,
    validate_source_kb_compatibility,
)
from tests.identity_helpers import make_document_identity

HASH = "a" * 64


def _manifest(**changes) -> IndexManifest:
    values = {
        "source_kb_schema_version": "0.5",
        "document_id": "science-tokyo-2027",
        "source_kb_sha256": HASH,
        "source_pdf_sha256": "b" * 64,
        "payload_count": 2,
        "vector_count": 2,
        "embedding_dimension": 384,
        "vectors_normalized": True,
        "embedding_provider": "local-test",
        "embedding_model": "multilingual-model",
        "embedding_revision": "rev-1",
        "payloads_sha256": "c" * 64,
        "vectors_sha256": "d" * 64,
    }
    values.update(changes)
    return IndexManifest(**values)


def _payload(row_index: int, **changes) -> IndexPayload:
    values = {
        "row_index": row_index,
        "document_id": "science-tokyo-2027",
        "unit_id": f"unit:{row_index:05d}",
        "fact_id": f"fact:{row_index:05d}",
        "text": f"出願資格 {row_index}",
        "source_pages": [row_index + 1],
        "section_path": ["３．出願資格"],
        "fact_type": "eligibility",
        "scope_type": "global",
        "scope_targets": [],
        "parent_college": None,
        "metadata": {"rank": row_index},
    }
    values.update(changes)
    return IndexPayload(**values)


def test_manifest_roundtrip_preserves_explicit_contract() -> None:
    manifest = _manifest()

    restored = IndexManifest.model_validate_json(manifest.model_dump_json())

    assert restored == manifest
    assert restored.index_schema_version == "0.1"
    assert restored.vector_dtype == "float32"
    assert restored.distance_metric == "cosine"
    assert restored.payloads_filename == "payloads.jsonl"
    assert restored.vectors_filename == "embeddings.npy"


@pytest.mark.parametrize(
    "field", ["source_kb_sha256", "source_pdf_sha256", "payloads_sha256", "vectors_sha256"]
)
@pytest.mark.parametrize("bad_hash", ["a" * 63, "A" * 64, "g" * 64])
def test_manifest_rejects_invalid_sha256(field: str, bad_hash: str) -> None:
    with pytest.raises(ValidationError, match="lowercase 64-character"):
        _manifest(**{field: bad_hash})


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../payloads.jsonl",
        "sub/payloads.jsonl",
        r"sub\payloads.jsonl",
        r"C:\payloads.jsonl",
        "C:payloads.jsonl",
        "payloads.jsonl:stream",
        "/tmp/payloads.jsonl",
    ],
)
def test_manifest_rejects_unsafe_artifact_filename(unsafe_name: str) -> None:
    with pytest.raises(ValidationError, match="safe basename"):
        _manifest(payloads_filename=unsafe_name)
    with pytest.raises(ValidationError, match="safe basename"):
        _manifest(vectors_filename=unsafe_name)


def test_manifest_rejects_count_dimension_and_identifier_errors() -> None:
    with pytest.raises(ValidationError, match="payload_count must equal vector_count"):
        _manifest(vector_count=1)
    with pytest.raises(ValidationError, match="embedding_dimension must be positive"):
        _manifest(embedding_dimension=0)
    with pytest.raises(ValidationError, match="non-empty trimmed"):
        _manifest(embedding_provider=" provider ")
    with pytest.raises(ValidationError, match="non-empty trimmed"):
        _manifest(embedding_revision="")
    with pytest.raises(ValidationError, match="Extra inputs"):
        _manifest(created_at="2026-09-01T00:00:00Z")
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        _manifest(payload_count=-1, vector_count=-1)

    empty = _manifest(payload_count=0, vector_count=0, embedding_dimension=0)
    assert empty.embedding_dimension == 0


def test_manifest_compatibility_rejects_unsupported_versions() -> None:
    unsupported_index = _manifest(index_schema_version="0.2")
    unsupported_kb = _manifest(source_kb_schema_version="0.4")

    with pytest.raises(ValueError, match="index schema version '0.2'.*0.1"):
        validate_manifest_compatibility(unsupported_index)
    with pytest.raises(ValueError, match="source KB schema version '0.4'.*0.5"):
        validate_manifest_compatibility(unsupported_kb)


def test_payload_jsonl_roundtrip_preserves_japanese_text_and_order() -> None:
    payloads = [_payload(0), _payload(1, text="検定料は30,000円です。")]

    restored = payloads_from_jsonl(payloads_to_jsonl(payloads))

    assert restored == payloads
    assert [payload.row_index for payload in restored] == [0, 1]
    assert restored[1].text == "検定料は30,000円です。"


def test_payload_rejects_invalid_pages_and_blank_jsonl_rows() -> None:
    with pytest.raises(ValidationError, match="positive page"):
        _payload(0, source_pages=[0])
    with pytest.raises(ValidationError, match="sorted and unique"):
        _payload(0, source_pages=[2, 1])
    with pytest.raises(ValueError, match="blank JSONL row"):
        payloads_from_jsonl(payloads_to_jsonl([_payload(0)]) + "\n")
    with pytest.raises(ValidationError, match="non-empty trimmed"):
        _payload(0, unit_id=" unit:00000 ")
    with pytest.raises(ValidationError, match="Extra inputs"):
        _payload(0, diagnostics={"missing": []})


@pytest.mark.parametrize(
    ("payloads", "message"),
    [
        ([_payload(0)], "payload count mismatch"),
        ([_payload(0), _payload(2)], "non-contiguous"),
        ([_payload(0), _payload(1, unit_id="unit:00000")], "duplicate unit_id"),
        ([_payload(0), _payload(1, fact_id="fact:00000")], "duplicate fact_id"),
        ([_payload(0), _payload(1, document_id="other")], "document mismatch"),
    ],
)
def test_payload_collection_rejects_integrity_errors(
    payloads: list[IndexPayload], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_payload_collection(_manifest(), payloads)


def test_payload_collection_accepts_exact_ordered_rows() -> None:
    validate_payload_collection(_manifest(), [_payload(0), _payload(1)])


def test_payload_derivation_joins_retrieval_unit_to_authoritative_fact() -> None:
    fact = ScopedFact(
        fact_id="fact:00000",
        fact_type="fees",
        scope_type="department",
        scope_targets=["情報工学系"],
        parent_college="情報理工学院",
        title="検定料",
        text="検定料は30,000円です。",
        source_pages=[10],
        section_path=["３．出願手続", "（１）検定料"],
        embedding_text="fees 検定料 30,000円",
    )
    unit = RetrievalUnit(
        unit_id="unit:00000",
        fact_id=fact.fact_id,
        text="[fees] 検定料 30,000円",
        source_pages=list(fact.source_pages),
        section_path=list(fact.section_path),
        metadata={"scope_type": "department"},
    )
    kb = DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            identity=make_document_identity(document_id="sample", pdf_sha256=HASH),
            source_pdf="sample.pdf",
            chunk_count=1,
        ),
        facts=[fact],
        retrieval_units=[unit],
    )

    payload = derive_index_payloads(kb)[0]

    assert payload.row_index == 0
    assert payload.unit_id == unit.unit_id
    assert payload.fact_id == fact.fact_id
    assert payload.text == unit.text
    assert payload.source_pages == fact.source_pages
    assert payload.section_path == fact.section_path
    assert payload.fact_type == fact.fact_type
    assert payload.scope_type == fact.scope_type
    assert payload.scope_targets == fact.scope_targets
    assert payload.parent_college == fact.parent_college


def test_payload_derivation_rejects_missing_or_mismatched_fact_links() -> None:
    fact = ScopedFact(
        fact_id="fact:00000",
        fact_type="general",
        text="text",
        source_pages=[1],
        section_path=["section"],
        embedding_text="text",
    )
    unit = RetrievalUnit(
        unit_id="unit:00000",
        fact_id="fact:missing",
        text="text",
        source_pages=[1],
        section_path=["section"],
    )
    kb = DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            identity=make_document_identity(document_id="sample", pdf_sha256=HASH),
            source_pdf="sample.pdf",
            chunk_count=1,
        ),
        facts=[fact],
        retrieval_units=[unit],
    )

    with pytest.raises(ValueError, match="missing Fact"):
        derive_index_payloads(kb)

    mismatched = deepcopy(kb)
    mismatched.retrieval_units[0].fact_id = fact.fact_id
    mismatched.retrieval_units[0].source_pages = [2]
    with pytest.raises(ValueError, match="source_pages differ"):
        derive_index_payloads(mismatched)

    old_kb = deepcopy(kb)
    old_kb.manifest.schema_version = "0.4"
    with pytest.raises(ValueError, match="source KB schema version '0.4'.*0.5"):
        validate_source_kb_compatibility(old_kb)
