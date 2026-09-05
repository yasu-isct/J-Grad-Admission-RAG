from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from tempfile import SpooledTemporaryFile
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from jgrad_admission_rag.schemas.corpus_manifest import canonical_corpus_manifest_bytes
from jgrad_admission_rag.schemas.corpus_version import canonical_corpus_version_policy_bytes
from jgrad_admission_rag.schemas.document_identity import canonical_document_identity_bytes
from jgrad_admission_rag.service import ServiceDependencies, ServiceSettings, create_app
from tests.identity_helpers import make_document_identity
from tests.test_corpus_search import ControlledProvider, _prepared_two_document_corpus


def _pdf_bytes() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "Graduate Admission Guidelines\nEligibility\nApplicants must hold a bachelor degree.",
    )
    raw = document.tobytes()
    document.close()
    return raw


def _build_files(pdf: bytes, *, digest: str | None = None, options: dict | None = None):
    identity = make_document_identity(pdf_sha256=digest or hashlib.sha256(pdf).hexdigest())
    files = {
        "pdf": ("private-name.pdf", pdf, "application/pdf"),
        "identity": (
            None,
            canonical_document_identity_bytes(identity),
            "application/json",
        ),
    }
    if options is not None:
        files["options"] = (None, json.dumps(options), "application/json")
    return files


def _query_runtime(tmp_path: Path):
    manifest, policy, _, _, identity = _prepared_two_document_corpus(tmp_path)
    manifest_path = tmp_path / "corpus.json"
    policy_path = tmp_path / "policy.json"
    manifest_path.write_bytes(canonical_corpus_manifest_bytes(manifest))
    policy_path.write_bytes(canonical_corpus_version_policy_bytes(policy))
    settings = ServiceSettings(
        corpus_root=tmp_path.resolve(),
        manifest_path=manifest_path.resolve(),
        policy_path=policy_path.resolve(),
    )
    provider = ControlledProvider(identity=identity)
    return settings, provider


def _query_payload() -> dict:
    return {
        "schema_version": "1.0",
        "selection": {
            "schema_version": "1.0",
            "institution_ids": ["alpha-u", "beta-u"],
            "allow_multiple_documents": True,
        },
        "search": {
            "query": "common requirement",
            "top_k": 3,
            "candidate_k": 4,
        },
    }


def test_import_and_app_creation_do_not_initialize_provider() -> None:
    calls = 0

    def provider_factory():
        nonlocal calls
        calls += 1
        return ControlledProvider()

    app = create_app(dependencies=ServiceDependencies(provider_factory=provider_factory))
    assert calls == 0
    assert app.openapi()["info"]["version"] == "1.0.0"


def test_service_import_explains_missing_optional_dependency() -> None:
    script = """
import builtins
real_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == 'fastapi' or name.startswith('fastapi.'):
        error = ModuleNotFoundError("blocked")
        error.name = 'fastapi'
        raise error
    return real_import(name, *args, **kwargs)
builtins.__import__ = blocked
try:
    import jgrad_admission_rag.service
except ImportError as error:
    assert '.[service]' in str(error)
else:
    raise AssertionError('service import unexpectedly succeeded')
"""
    subprocess.run([sys.executable, "-c", script], check=True)


def test_health_reports_liveness_and_lifecycle_readiness(tmp_path: Path) -> None:
    settings, provider = _query_runtime(tmp_path)
    calls = 0

    def provider_factory():
        nonlocal calls
        calls += 1
        return provider

    app = create_app(settings, ServiceDependencies(provider_factory=provider_factory))
    with TestClient(app) as client:
        assert client.get("/v1/health/live").json()["ready"] is True
        assert client.get("/v1/health/ready").json()["ready"] is True
        assert calls == 1

    assert app.state.service_state.provider is None


def test_failed_provider_initialization_is_not_ready() -> None:
    def provider_factory():
        raise RuntimeError("private initialization detail")

    app = create_app(dependencies=ServiceDependencies(provider_factory=provider_factory))
    with TestClient(app) as client:
        response = client.get("/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0",
        "status": "not_ready",
        "ready": False,
    }


def test_build_returns_complete_kb_and_does_not_expose_upload_name() -> None:
    pdf = _pdf_bytes()
    with TestClient(create_app()) as client:
        response = client.post("/v1/knowledge-bases/build", files=_build_files(pdf))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"quality_passed", "quality_failed"}
    assert body["accepted_for_indexing"] == body["summary"]["quality_gate_passed"]
    assert body["knowledge_base"]["manifest"]["source_pdf"] == "uploaded.pdf"
    assert body["summary"]["facts"] == len(body["knowledge_base"]["facts"])
    assert "private-name.pdf" not in response.text


def test_quality_failed_build_is_inspectable_but_not_index_ready() -> None:
    pdf = _pdf_bytes()
    options = {"quality_thresholds": {"max_unknown_scope_facts": 0}}
    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/knowledge-bases/build", files=_build_files(pdf, options=options)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "quality_failed"
    assert body["accepted_for_indexing"] is False
    assert body["knowledge_base"]["diagnostics"]["quality_gate"]["passed"] is False


def test_build_rejects_hash_mismatch_before_extraction() -> None:
    pdf = _pdf_bytes()
    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/knowledge-bases/build",
            files=_build_files(pdf, digest="0" * 64),
        )

    assert response.status_code == 409
    assert response.json()["code"] == "source_binding_mismatch"
    assert "private-name" not in response.text


def test_build_enforces_content_type_shape_and_size() -> None:
    pdf = _pdf_bytes()
    app = create_app(ServiceSettings(max_pdf_bytes=8))
    with TestClient(app) as client:
        too_large = client.post("/v1/knowledge-bases/build", files=_build_files(pdf))
        wrong_media = client.post(
            "/v1/knowledge-bases/build",
            content=b"not multipart",
            headers={"content-type": "application/json"},
        )
        unknown = client.post(
            "/v1/knowledge-bases/build",
            files=[
                ("pdf", ("a.pdf", pdf, "application/pdf")),
                ("identity", (None, b"{}", "application/json")),
                ("extra", (None, "x")),
            ],
        )
        duplicate = client.post(
            "/v1/knowledge-bases/build",
            files=[
                ("pdf", ("a.pdf", pdf, "application/pdf")),
                ("pdf", ("b.pdf", pdf, "application/pdf")),
                ("identity", (None, b"{}", "application/json")),
            ],
        )

    assert (too_large.status_code, too_large.json()["code"]) == (413, "payload_too_large")
    assert (wrong_media.status_code, wrong_media.json()["code"]) == (
        415,
        "unsupported_media_type",
    )
    assert (unknown.status_code, unknown.json()["code"]) == (422, "invalid_request")
    assert (duplicate.status_code, duplicate.json()["code"]) == (422, "invalid_request")


def test_build_enforces_metadata_limit_while_parsing_multipart() -> None:
    pdf = _pdf_bytes()
    app = create_app(ServiceSettings(max_metadata_bytes=64))
    with TestClient(app) as client:
        response = client.post("/v1/knowledge-bases/build", files=_build_files(pdf))

    assert (response.status_code, response.json()["code"]) == (413, "payload_too_large")


def test_build_metadata_limit_can_exceed_framework_default() -> None:
    pdf = _pdf_bytes()
    oversized_for_default = json.dumps({"padding": "x" * (1024 * 1024 + 1)})
    files = _build_files(pdf)
    files["identity"] = (None, oversized_for_default, "application/json")
    app = create_app(ServiceSettings(max_metadata_bytes=2 * 1024 * 1024))
    with TestClient(app) as client:
        response = client.post("/v1/knowledge-bases/build", files=files)

    assert (response.status_code, response.json()["code"]) == (422, "invalid_request")


@pytest.mark.parametrize("failure", ("identity", "options", "unknown", "duplicate"))
def test_build_closes_uploads_after_multipart_validation_failure(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[object] = []
    original_close = SpooledTemporaryFile.close

    def recording_close(upload) -> None:
        closed.append(upload)
        original_close(upload)

    monkeypatch.setattr(SpooledTemporaryFile, "close", recording_close)
    pdf = _pdf_bytes()
    files = _build_files(pdf)
    if failure == "identity":
        files["identity"] = (None, "{}", "application/json")
    elif failure == "options":
        files["options"] = (None, "{", "application/json")
    elif failure == "unknown":
        files["extra"] = (None, "x")
    else:
        identity = files["identity"]
        files = [
            ("pdf", ("first.pdf", pdf, "application/pdf")),
            ("pdf", ("second.pdf", pdf, "application/pdf")),
            ("identity", identity),
        ]

    with TestClient(create_app()) as client:
        response = client.post("/v1/knowledge-bases/build", files=files)

    assert response.status_code == 422
    assert closed


def test_build_cleans_owned_temporary_directory_after_builder_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jgrad_admission_rag.service.app as app_module

    created: list[Path] = []
    real_temporary_directory = app_module.TemporaryDirectory

    def recording_temporary_directory(*args, **kwargs):
        context = real_temporary_directory(dir=tmp_path, *args, **kwargs)
        created.append(Path(context.name))
        return context

    def fail_build(*args, **kwargs):
        raise RuntimeError("planted secret and path")

    monkeypatch.setattr(app_module, "TemporaryDirectory", recording_temporary_directory)
    monkeypatch.setattr(app_module, "build_document_kb", fail_build)
    pdf = _pdf_bytes()
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.post("/v1/knowledge-bases/build", files=_build_files(pdf))

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "planted secret" not in response.text
    assert created and all(not path.exists() for path in created)


def test_query_uses_server_owned_current_corpus_and_one_query_embedding(tmp_path: Path) -> None:
    settings, provider = _query_runtime(tmp_path)
    app = create_app(settings, ServiceDependencies(provider_factory=lambda: provider))
    with TestClient(app) as client:
        response = client.post("/v1/corpus/query", json=_query_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["corpus_document_count"] == 2
    assert {item["key"]["document_id"] for item in body["hits"]} <= {
        "alpha-2027",
        "beta-2027",
    }
    assert provider.query_calls == ["common requirement"]


def test_query_reloads_policy_and_does_not_serve_stale_context(tmp_path: Path) -> None:
    settings, provider = _query_runtime(tmp_path)
    app = create_app(settings, ServiceDependencies(provider_factory=lambda: provider))
    with TestClient(app) as client:
        first = client.post("/v1/corpus/query", json=_query_payload())
        assert settings.policy_path is not None
        settings.policy_path.write_text("not-json", encoding="utf-8")
        second = client.post("/v1/corpus/query", json=_query_payload())

    assert first.status_code == 200
    assert (second.status_code, second.json()["code"]) == (503, "corpus_unavailable")
    assert provider.query_calls == ["common requirement"]


def test_query_selection_errors_are_typed_and_allowlisted(tmp_path: Path) -> None:
    settings, provider = _query_runtime(tmp_path)
    no_match = _query_payload()
    no_match["selection"] = {"document_ids": ["missing"]}
    ambiguous = _query_payload()
    ambiguous["selection"] = {
        "institution_ids": ["alpha-u", "beta-u"],
        "allow_multiple_documents": False,
    }
    app = create_app(settings, ServiceDependencies(provider_factory=lambda: provider))
    with TestClient(app) as client:
        missing = client.post("/v1/corpus/query", json=no_match)
        multiple = client.post("/v1/corpus/query", json=ambiguous)

    assert (missing.status_code, missing.json()["code"]) == (404, "selection_no_match")
    assert (multiple.status_code, multiple.json()["code"]) == (
        409,
        "selection_ambiguous",
    )
    assert set(multiple.json()["details"]) == {"document_ids"}
    assert provider.query_calls == []


def test_query_returns_provider_unavailable_after_failed_lifespan(tmp_path: Path) -> None:
    settings, _ = _query_runtime(tmp_path)

    def fail_provider():
        raise RuntimeError("secret cache path")

    app = create_app(settings, ServiceDependencies(provider_factory=fail_provider))
    with TestClient(app) as client:
        response = client.post("/v1/corpus/query", json=_query_payload())

    assert (response.status_code, response.json()["code"]) == (503, "provider_unavailable")
    assert "secret cache path" not in response.text


@pytest.mark.parametrize(
    ("path", "method", "kwargs", "status", "code"),
    (
        ("/missing", "get", {}, 404, "invalid_request"),
        ("/v1/health/live", "post", {}, 405, "invalid_request"),
        (
            "/v1/corpus/query",
            "post",
            {"content": b"{}", "headers": {"content-type": "text/plain"}},
            415,
            "unsupported_media_type",
        ),
        (
            "/v1/corpus/query",
            "post",
            {"json": {"unexpected": "private value"}},
            422,
            "invalid_request",
        ),
    ),
)
def test_transport_errors_use_uniform_privacy_safe_envelope(
    path: str, method: str, kwargs: dict, status: int, code: str
) -> None:
    with TestClient(create_app()) as client:
        response = client.request(method, path, **kwargs)

    assert response.status_code == status
    assert response.json() == {
        "schema_version": "1.0",
        "code": code,
        "message": response.json()["message"],
        "details": None,
    }
    assert "private value" not in response.text


def test_openapi_exposes_only_versioned_contract_routes() -> None:
    schema = create_app().openapi()
    operations = {
        operation["operationId"] for path in schema["paths"].values() for operation in path.values()
    }

    assert operations == {
        "getV1HealthLive",
        "getV1HealthReady",
        "getV1ReviewedDocuments",
        "postV1BuildJobs",
        "getV1BuildJob",
        "getV1BuildJobResult",
        "postV1BuildJobCancel",
        "postV1BuildJobRetry",
        "deleteV1BuildJob",
        "postV1KnowledgeBasesBuild",
        "postV1CorpusQuery",
        "postV1ApplicantReports",
    }
    assert "ErrorEnvelope" in schema["components"]["schemas"]
    catalog_operation = schema["paths"]["/v1/reviewed-documents"]["get"]
    assert catalog_operation["operationId"] == "getV1ReviewedDocuments"
    assert set(catalog_operation["responses"]) == {"200", "500", "503"}
    assert "source_pdf_sha256" not in str(
        schema["components"]["schemas"]["ReviewedDocumentPublicIdentity"]
    )
    assert "/app" not in schema["paths"]
    assert "/assets/app.css" not in schema["paths"]
    build_operation = schema["paths"]["/v1/knowledge-bases/build"]["post"]
    multipart = build_operation["requestBody"]["content"]["multipart/form-data"]
    assert multipart["schema"]["required"] == ["pdf", "identity"]
    assert multipart["schema"]["additionalProperties"] is False
    assert set(schema["paths"]["/v1/knowledge-bases/build"]["post"]["responses"]) == {
        "200",
        "409",
        "413",
        "415",
        "422",
        "500",
    }
    assert set(schema["paths"]["/v1/applicant-reports"]["post"]["responses"]) == {
        "200",
        "404",
        "409",
        "415",
        "422",
        "500",
        "503",
    }
    report_operation = schema["paths"]["/v1/applicant-reports"]["post"]
    report_request = schema["components"]["schemas"]["ApplicantReportRequest"]
    report_response = schema["components"]["schemas"]["ApplicantReportResponse"]
    assert report_operation["requestBody"]["content"].keys() == {"application/json"}
    assert report_request["additionalProperties"] is False
    assert set(report_request["required"]) == {"report_id", "profile", "intent", "selection"}
    assert report_response["additionalProperties"] is False
    assert set(report_response["required"]) == {"report", "markdown"}


def test_head_behavior_is_deliberate_and_does_not_leak_alternate_body() -> None:
    with TestClient(create_app()) as client:
        response = client.head("/v1/health/live")

    assert response.status_code == 405
    assert response.content == b""
    assert response.headers["content-type"] == "application/json"


def test_service_settings_require_complete_absolute_query_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ServiceSettings(corpus_root=tmp_path.resolve())
    with pytest.raises(ValueError):
        ServiceSettings(
            corpus_root=Path("relative"),
            manifest_path=Path("manifest.json"),
            policy_path=Path("policy.json"),
        )
    with pytest.raises(ValueError):
        ServiceSettings(job_root=Path("relative-jobs"))


def test_service_exports_applicant_report_contracts() -> None:
    from jgrad_admission_rag.service import ApplicantReportRequest, ApplicantReportResponse

    assert ApplicantReportRequest.model_fields["schema_version"].default == "1.0"
    assert ApplicantReportResponse.model_fields["schema_version"].default == "1.0"


def test_cli_defaults_to_loopback_and_defers_provider_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uvicorn

    from jgrad_admission_rag.service import cli as service_cli

    calls: list[tuple[object, str, int]] = []
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda app, host, port: calls.append((app, host, port)),
    )
    service_cli.main(
        [
            "--corpus-root",
            str(tmp_path),
            "--manifest",
            str(tmp_path / "corpus.json"),
            "--policy",
            str(tmp_path / "policy.json"),
            "--provider",
            "deterministic-fake",
            "--dimension",
            "8",
        ]
    )

    assert len(calls) == 1
    app, host, port = calls[0]
    assert (host, port) == ("127.0.0.1", 8000)
    assert app.state.service_state.provider is None


def test_cli_accepts_repeatable_absolute_report_plans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uvicorn

    from jgrad_admission_rag.service import cli as service_cli

    captured = []
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port: captured.append(app))
    plan_a = (tmp_path / "plan-a.json").resolve()
    plan_b = (tmp_path / "plan-b.json").resolve()
    service_cli.main(
        [
            "--corpus-root",
            str(tmp_path),
            "--manifest",
            str(tmp_path / "corpus.json"),
            "--policy",
            str(tmp_path / "policy.json"),
            "--report-plan",
            str(plan_a),
            "--report-plan",
            str(plan_b),
            "--provider",
            "deterministic-fake",
            "--dimension",
            "8",
        ]
    )

    assert captured[0].state.service_settings.report_plan_paths == (plan_a, plan_b)


def test_cli_rejects_relative_report_plan_path(tmp_path: Path) -> None:
    from jgrad_admission_rag.service import cli as service_cli

    with pytest.raises(SystemExit) as exc_info:
        service_cli.main(
            [
                "--corpus-root",
                str(tmp_path),
                "--manifest",
                str(tmp_path / "corpus.json"),
                "--policy",
                str(tmp_path / "policy.json"),
                "--report-plan",
                "relative-plan.json",
                "--provider",
                "deterministic-fake",
                "--dimension",
                "8",
            ]
        )

    assert exc_info.value.code == 2
