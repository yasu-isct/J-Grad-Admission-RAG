from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

import pytest

from jgrad_admission_rag.schemas.document_identity import (
    canonical_document_identity_bytes,
    load_document_identity,
)
from jgrad_admission_rag.service.jobs import BuildJobRepository, BuildJobWorker, JobState
from jgrad_admission_rag.utils import sha256_file

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
REAL_MANIFEST = FIXTURES / "real_pdf_manifest.json"

pytestmark = pytest.mark.real_pdf


def test_real_pdf_worker_publishes_reviewed_complete_result(tmp_path: Path) -> None:
    metadata = json.loads(REAL_MANIFEST.read_text(encoding="utf-8"))
    configured = os.getenv("JGRAD_REAL_PDF")
    configured_path = Path(configured).expanduser() if configured else None
    if configured_path is not None and not configured_path.is_absolute():
        configured_path = REPO_ROOT / configured_path
    candidates = [
        configured_path,
        FIXTURES / "private" / metadata["filename"],
        REPO_ROOT / "outputs" / "real_pdf" / metadata["filename"],
    ]
    pdf = next((path for path in candidates if path is not None and path.is_file()), None)
    if pdf is None:
        pytest.skip("real PDF fixture unavailable; set JGRAD_REAL_PDF")
    identity = load_document_identity(FIXTURES / metadata["identity_file"])
    assert sha256_file(pdf) == identity.source_pdf_sha256
    root = (tmp_path / "durable-worker").resolve()
    creator = BuildJobRepository(
        root,
        id_factory=lambda: UUID("00000000-0000-4000-8000-000000000001"),
    ).open()
    queued = creator.create(canonical_document_identity_bytes(identity), b"{}", pdf)
    creator.close()
    repository = BuildJobRepository(root)
    worker = BuildJobWorker(repository)

    async def exercise() -> None:
        await worker.start()

        async def wait_for_result():
            while True:
                record = await asyncio.to_thread(repository.get, queued.job_id)
                if record.state in {
                    JobState.SUCCEEDED,
                    JobState.QUALITY_FAILED,
                    JobState.FAILED,
                }:
                    return record
                await asyncio.sleep(0.02)

        record = await asyncio.wait_for(wait_for_result(), 30)
        assert record.state == JobState.SUCCEEDED
        result = await asyncio.to_thread(repository.read_result, queued.job_id)
        assert result.accepted_for_indexing
        assert result.knowledge_base.manifest.source_pdf == "source.pdf"
        assert len(result.knowledge_base.facts) == 304
        assert len(result.knowledge_base.retrieval_units) == 304
        assert not result.knowledge_base.diagnostics.missing_source_page_fact_ids
        assert all(fact.source_pages for fact in result.knowledge_base.facts)
        assert {
            (term.year, term.month) for term in result.knowledge_base.manifest.identity.intake_terms
        } == {
            (2026, 9),
            (2027, 4),
        }
        await worker.stop()

    asyncio.run(exercise())
