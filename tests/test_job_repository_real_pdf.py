from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

import pytest

from jgrad_admission_rag.schemas.document_identity import (
    canonical_document_identity_bytes,
    load_document_identity,
    load_document_identity_bytes,
)
from jgrad_admission_rag.service.jobs import BuildJobRepository, JobState
from jgrad_admission_rag.utils import sha256_file

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
REAL_MANIFEST = FIXTURES / "real_pdf_manifest.json"

pytestmark = pytest.mark.real_pdf


def test_real_pdf_inputs_survive_job_repository_reopen_without_extraction(tmp_path: Path) -> None:
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
    root = (tmp_path / "durable-jobs").resolve()
    repository = BuildJobRepository(
        root,
        id_factory=lambda: UUID("00000000-0000-4000-8000-000000000001"),
    ).open()
    record = repository.create(canonical_document_identity_bytes(identity), b"{}", pdf)
    repository.close()

    with BuildJobRepository(root).open() as reopened:
        loaded = reopened.get(record.job_id)
        assert loaded.state == JobState.QUEUED

    owned = root / "jobs" / str(record.job_id)
    persisted_identity = load_document_identity_bytes((owned / "identity.json").read_bytes())
    assert persisted_identity == identity
    assert {(term.year, term.month) for term in persisted_identity.intake_terms} == {
        (2026, 9),
        (2027, 4),
    }
    assert sha256_file(owned / "source.pdf") == identity.source_pdf_sha256
