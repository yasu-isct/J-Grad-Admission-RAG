from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from jgrad_admission_rag.demo import DemoRuntime, prepare_demo
from jgrad_admission_rag.retrieval.embedding import DeterministicFakeEmbeddingProvider
from jgrad_admission_rag.service import ServiceDependencies, ServiceSettings, create_app
from tests.test_demo_cli import _synthetic_config


@pytest.fixture(scope="module")
def source_runtime(tmp_path_factory: pytest.TempPathFactory) -> tuple[DemoRuntime, bytes]:
    root = tmp_path_factory.mktemp("verified-source-route")
    pdf, config, _ = _synthetic_config(root)
    runtime = prepare_demo(pdf, (root / "workspace").resolve(), config_dir=config)
    return runtime, pdf.read_bytes()


def _settings(
    runtime: DemoRuntime,
    *,
    source_path: Path | None = None,
    source_hash: str | None = None,
) -> ServiceSettings:
    return ServiceSettings(
        corpus_root=runtime.corpus_root,
        manifest_path=runtime.manifest_path,
        policy_path=runtime.policy_path,
        report_plan_paths=(runtime.report_plan_path,),
        page_scope_manifest_paths=(runtime.page_scope_manifest_path,),
        query_intent_catalog_path=runtime.query_intent_catalog_path,
        date_presentation_paths=(runtime.date_presentation_path,),
        source_pdf_path=source_path or runtime.source_pdf_path,
        source_pdf_document_id=runtime.identity.document_id,
        source_pdf_sha256=source_hash or runtime.identity.source_pdf_sha256,
    )


def _client(settings: ServiceSettings) -> TestClient:
    dependencies = ServiceDependencies(
        provider_factory=lambda: DeterministicFakeEmbeddingProvider(8)
    )
    return TestClient(create_app(settings, dependencies))


def test_verified_source_pdf_supports_get_head_and_single_ranges(
    source_runtime: tuple[DemoRuntime, bytes],
) -> None:
    runtime, content = source_runtime
    route = f"/documents/{runtime.identity.document_id}/source.pdf"
    with _client(_settings(runtime)) as client:
        response = client.get(route)
        head = client.head(route)
        closed = client.get(route, headers={"Range": "bytes=0-7"})
        suffix = client.get(route, headers={"Range": "bytes=-6"})

    assert response.status_code == 200
    assert response.content == content
    assert hashlib.sha256(response.content).hexdigest() == runtime.identity.source_pdf_sha256
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert (
        response.headers["content-disposition"]
        == f'inline; filename="{runtime.identity.document_id}.pdf"'
    )
    assert head.status_code == 200 and head.content == b""
    assert int(head.headers["content-length"]) == len(content)
    assert closed.status_code == 206 and closed.content == content[:8]
    assert closed.headers["content-range"] == f"bytes 0-7/{len(content)}"
    assert suffix.status_code == 206 and suffix.content == content[-6:]


@pytest.mark.parametrize(
    "range_value", ["bytes=", "bytes=9-2", "bytes=999999-", "bytes=0-1,3-4", "items=0-1"]
)
def test_verified_source_pdf_rejects_invalid_or_multi_ranges(
    source_runtime: tuple[DemoRuntime, bytes], range_value: str
) -> None:
    runtime, content = source_runtime
    route = f"/documents/{runtime.identity.document_id}/source.pdf"
    with _client(_settings(runtime)) as client:
        response = client.get(route, headers={"Range": range_value})

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(content)}"


def test_source_route_never_accepts_an_arbitrary_path_or_query(
    source_runtime: tuple[DemoRuntime, bytes],
) -> None:
    runtime, _ = source_runtime
    route = f"/documents/{runtime.identity.document_id}/source.pdf"
    with _client(_settings(runtime)) as client:
        wrong = client.get("/documents/other/source.pdf")
        query = client.get(f"{route}?path=C%3A%5Csecret.pdf")
        traversal = client.get("/documents/..%2F..%2Fsecret/source.pdf")

    assert wrong.status_code == 404
    assert query.status_code == 422
    assert traversal.status_code in {404, 422}


def test_source_route_fails_closed_when_pdf_does_not_match_reviewed_identity(
    source_runtime: tuple[DemoRuntime, bytes], tmp_path: Path
) -> None:
    runtime, content = source_runtime
    different_source = (tmp_path / "different.pdf").resolve()
    different_source.write_bytes(content + b"different reviewed document")
    different_hash = hashlib.sha256(different_source.read_bytes()).hexdigest()
    route = f"/documents/{runtime.identity.document_id}/source.pdf"

    with _client(
        _settings(runtime, source_path=different_source, source_hash=different_hash)
    ) as client:
        readiness = client.get("/v1/health/ready")
        response = client.get(route)

    assert readiness.json()["ready"] is False
    assert response.status_code == 503


def test_source_route_requires_reviewed_runtime_and_is_unavailable_when_unconfigured(
    source_runtime: tuple[DemoRuntime, bytes],
) -> None:
    runtime, _ = source_runtime
    source_only = ServiceSettings(
        source_pdf_path=runtime.source_pdf_path,
        source_pdf_document_id=runtime.identity.document_id,
        source_pdf_sha256=runtime.identity.source_pdf_sha256,
    )
    route = f"/documents/{runtime.identity.document_id}/source.pdf"

    with TestClient(create_app(source_only)) as missing_reviewed_identity:
        assert missing_reviewed_identity.get(route).status_code == 503
    with TestClient(create_app()) as unconfigured:
        assert unconfigured.get(route).status_code == 503


def test_verified_source_settings_must_be_complete_canonical_and_absolute(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ServiceSettings(source_pdf_document_id="reviewed-source-2027")
    with pytest.raises(ValidationError):
        ServiceSettings(
            source_pdf_path=Path("relative.pdf"),
            source_pdf_document_id="reviewed-source-2027",
            source_pdf_sha256="0" * 64,
        )
