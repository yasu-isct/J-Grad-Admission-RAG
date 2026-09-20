from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from jgrad_admission_rag.service import ServiceSettings, create_app


DOCUMENT_ID = "reviewed-source-2027"


def _client(tmp_path: Path, *, expected_hash: str | None = None) -> tuple[TestClient, bytes]:
    content = b"%PDF-1.7\nverified immutable test document\n%%EOF\n"
    source = (tmp_path / "reviewed.pdf").resolve()
    source.write_bytes(content)
    settings = ServiceSettings(
        source_pdf_path=source,
        source_pdf_document_id=DOCUMENT_ID,
        source_pdf_sha256=expected_hash or hashlib.sha256(content).hexdigest(),
    )
    return TestClient(create_app(settings)), content


def test_verified_source_pdf_supports_get_head_and_single_ranges(tmp_path: Path) -> None:
    client, content = _client(tmp_path)
    with client:
        response = client.get(f"/documents/{DOCUMENT_ID}/source.pdf")
        head = client.head(f"/documents/{DOCUMENT_ID}/source.pdf")
        closed = client.get(f"/documents/{DOCUMENT_ID}/source.pdf", headers={"Range": "bytes=0-7"})
        suffix = client.get(f"/documents/{DOCUMENT_ID}/source.pdf", headers={"Range": "bytes=-6"})

    assert response.status_code == 200
    assert response.content == content
    assert hashlib.sha256(response.content).hexdigest() == hashlib.sha256(content).hexdigest()
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == f'inline; filename="{DOCUMENT_ID}.pdf"'
    assert head.status_code == 200 and head.content == b""
    assert int(head.headers["content-length"]) == len(content)
    assert closed.status_code == 206 and closed.content == content[:8]
    assert closed.headers["content-range"] == f"bytes 0-7/{len(content)}"
    assert suffix.status_code == 206 and suffix.content == content[-6:]


@pytest.mark.parametrize(
    "range_value", ["bytes=", "bytes=9-2", "bytes=999-", "bytes=0-1,3-4", "items=0-1"]
)
def test_verified_source_pdf_rejects_invalid_or_multi_ranges(
    tmp_path: Path, range_value: str
) -> None:
    client, content = _client(tmp_path)
    with client:
        response = client.get(
            f"/documents/{DOCUMENT_ID}/source.pdf", headers={"Range": range_value}
        )

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(content)}"


def test_source_route_never_accepts_an_arbitrary_path_or_query(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    with client:
        wrong = client.get("/documents/other/source.pdf")
        query = client.get(f"/documents/{DOCUMENT_ID}/source.pdf?path=C%3A%5Csecret.pdf")
        traversal = client.get("/documents/..%2F..%2Fsecret/source.pdf")

    assert wrong.status_code == 404
    assert query.status_code == 422
    assert traversal.status_code in {404, 422}


def test_source_route_fails_closed_for_hash_mismatch_and_when_unconfigured(tmp_path: Path) -> None:
    bad_client, _ = _client(tmp_path, expected_hash="0" * 64)
    with bad_client:
        assert bad_client.get(f"/documents/{DOCUMENT_ID}/source.pdf").status_code == 503
    with TestClient(create_app()) as unconfigured:
        assert unconfigured.get(f"/documents/{DOCUMENT_ID}/source.pdf").status_code == 503


def test_verified_source_settings_must_be_complete_canonical_and_absolute(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ServiceSettings(source_pdf_document_id=DOCUMENT_ID)
    with pytest.raises(ValidationError):
        ServiceSettings(
            source_pdf_path=Path("relative.pdf"),
            source_pdf_document_id=DOCUMENT_ID,
            source_pdf_sha256="0" * 64,
        )
