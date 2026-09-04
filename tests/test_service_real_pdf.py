from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jgrad_admission_rag.corpus import CorpusRegistration, build_corpus_manifest
from jgrad_admission_rag.retrieval.embedding import DeterministicFakeEmbeddingProvider
from jgrad_admission_rag.retrieval.local_index import build_local_index
from jgrad_admission_rag.schemas.corpus_manifest import canonical_corpus_manifest_bytes
from jgrad_admission_rag.schemas.corpus_version import (
    CorpusFamilyVersionPolicy,
    CorpusVersionPolicy,
    canonical_corpus_version_policy_bytes,
)
from jgrad_admission_rag.schemas.document_identity import (
    canonical_document_identity_bytes,
    load_document_identity,
)
from jgrad_admission_rag.schemas.document_kb import (
    DocumentKnowledgeBase,
    canonical_document_kb_bytes,
)
from jgrad_admission_rag.service import ServiceDependencies, ServiceSettings, create_app
from jgrad_admission_rag.utils import sha256_file

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
REAL_MANIFEST = FIXTURES / "real_pdf_manifest.json"

pytestmark = pytest.mark.real_pdf


def _real_inputs() -> tuple[Path, object]:
    metadata = json.loads(REAL_MANIFEST.read_text(encoding="utf-8"))
    configured = os.getenv("JGRAD_REAL_PDF")
    candidates = [
        Path(configured).expanduser() if configured else None,
        FIXTURES / "private" / metadata["filename"],
        REPO_ROOT / "outputs" / "real_pdf" / metadata["filename"],
    ]
    pdf = next((path for path in candidates if path is not None and path.is_file()), None)
    if pdf is None:
        pytest.skip("real PDF fixture unavailable; set JGRAD_REAL_PDF")
    assert sha256_file(pdf) == metadata["sha256"]
    return pdf, load_document_identity(FIXTURES / metadata["identity_file"])


def test_real_pdf_build_and_query_preserve_http_identity_and_pages(tmp_path: Path) -> None:
    pdf_path, identity = _real_inputs()
    with TestClient(create_app()) as client:
        built = client.post(
            "/v1/knowledge-bases/build",
            files={
                "pdf": ("untrusted.pdf", pdf_path.read_bytes(), "application/pdf"),
                "identity": (
                    None,
                    canonical_document_identity_bytes(identity),
                    "application/json",
                ),
            },
        )

    assert built.status_code == 200
    assert built.json()["status"] == "quality_passed"
    kb = DocumentKnowledgeBase.model_validate(built.json()["knowledge_base"])
    assert len(kb.facts) == len(kb.retrieval_units) == 298
    assert {(term.year, term.month) for term in kb.manifest.identity.intake_terms} == {
        (2026, 9),
        (2027, 4),
    }
    assert not kb.diagnostics.missing_source_page_fact_ids

    kb_path = tmp_path / "documents" / "isct" / "document_kb.json"
    kb_path.parent.mkdir(parents=True)
    kb_path.write_bytes(canonical_document_kb_bytes(kb))
    index_path = tmp_path / "indexes" / "isct"
    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    build_local_index(kb_path, index_path, provider)
    manifest = build_corpus_manifest(
        "service-real",
        tmp_path,
        (CorpusRegistration("documents/isct/document_kb.json", "indexes/isct"),),
    )
    policy = CorpusVersionPolicy(
        corpus_id=manifest.corpus_id,
        family_policies=(
            CorpusFamilyVersionPolicy(
                document_family_id=identity.document_family_id,
                active_document_id=identity.document_id,
            ),
        ),
    )
    manifest_path = tmp_path / "corpus.json"
    policy_path = tmp_path / "policy.json"
    manifest_path.write_bytes(canonical_corpus_manifest_bytes(manifest))
    policy_path.write_bytes(canonical_corpus_version_policy_bytes(policy))
    app = create_app(
        ServiceSettings(
            corpus_root=tmp_path.resolve(),
            manifest_path=manifest_path.resolve(),
            policy_path=policy_path.resolve(),
        ),
        ServiceDependencies(provider_factory=lambda: provider),
    )
    with TestClient(app) as client:
        result = client.post(
            "/v1/corpus/query",
            json={
                "selection": {"document_ids": [identity.document_id]},
                "search": {"query": "出願資格", "top_k": 3},
            },
        )

    assert result.status_code == 200
    assert result.json()["semantic"] is False
    assert result.json()["hits"]
    assert all(hit["source_pages"] for hit in result.json()["hits"])
    assert all(hit["key"]["document_id"] == identity.document_id for hit in result.json()["hits"])
