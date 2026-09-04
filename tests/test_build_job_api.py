from __future__ import annotations

import asyncio
import time
from pathlib import Path
from fastapi.testclient import TestClient

from jgrad_admission_rag.schemas.document_identity import canonical_document_identity_bytes
from jgrad_admission_rag.service import ServiceDependencies, ServiceSettings, create_app
from jgrad_admission_rag.service.jobs import (
    BuildJobRepository,
    BuildJobWorker,
    WorkerSnapshot,
    WorkerStatus,
)
from tests.test_job_repository import JOB_IDS, _result
from tests.test_service_api import _build_files, _pdf_bytes, _query_runtime


def _settings(tmp_path: Path) -> ServiceSettings:
    return ServiceSettings(job_root=(tmp_path / "jobs").resolve())


def _dependencies(*, accepted: bool = True) -> ServiceDependencies:
    ids = iter(JOB_IDS)

    def repository_factory(root: Path):
        return BuildJobRepository(root, id_factory=lambda: next(ids))

    def worker_factory(repository, **kwargs):
        def runner(_path, identity, _options):
            return _result(canonical_document_identity_bytes(identity), accepted=accepted)

        return BuildJobWorker(repository, build_runner=runner, **kwargs)

    return ServiceDependencies(
        repository_factory=repository_factory,
        worker_factory=worker_factory,
    )


def _wait_terminal(client: TestClient, status_path: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(status_path)
        assert response.status_code == 200
        body = response.json()
        if body["state"] in {"succeeded", "quality_failed", "failed", "cancelled"}:
            return body
        time.sleep(0.01)
    raise AssertionError("job did not reach a terminal state")


def test_submit_worker_result_restart_and_exact_delete(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    dependencies = _dependencies()
    pdf = _pdf_bytes()
    with TestClient(create_app(settings, dependencies)) as client:
        submitted = client.post(
            "/v1/build-jobs",
            files=_build_files(pdf),
            headers={"host": "attacker.example"},
        )
        assert submitted.status_code == 202
        receipt = submitted.json()
        assert receipt["state"] == "queued"
        assert receipt["status_path"].startswith("/v1/build-jobs/")
        assert "attacker" not in submitted.text
        terminal = _wait_terminal(client, receipt["status_path"])
        assert terminal["state"] == "succeeded"
        assert terminal["result_available"] is True
        assert terminal["transitions"][-1]["to_state"] == "succeeded"
        assert set(terminal) == {
            "schema_version",
            "job_id",
            "state",
            "phase",
            "attempt",
            "parent_job_id",
            "created_at",
            "updated_at",
            "result_available",
            "status_path",
            "result_path",
            "started_at",
            "finished_at",
            "diagnostic_code",
            "transitions",
        }
        result = client.get(receipt["result_path"])
        assert result.status_code == 200
        assert result.json()["knowledge_base"]["manifest"]["source_pdf"] == "source.pdf"
        cancel_conflict = client.post(receipt["status_path"] + "/cancel")
        assert (cancel_conflict.status_code, cancel_conflict.json()["code"]) == (
            409,
            "job_cancellation_conflict",
        )

    with TestClient(create_app(settings, _dependencies())) as restarted:
        assert restarted.get(receipt["status_path"]).json()["state"] == "succeeded"
        assert restarted.get(receipt["result_path"]).status_code == 200
        deleted = restarted.delete(receipt["status_path"])
        assert deleted.status_code == 204
        assert deleted.content == b""
        assert "content-type" not in deleted.headers
        missing = restarted.get(receipt["status_path"])
        assert (missing.status_code, missing.json()["code"]) == (404, "job_not_found")
        assert restarted.delete(receipt["status_path"]).status_code == 404


def test_quality_failed_job_result_remains_inspectable(tmp_path: Path) -> None:
    pdf = _pdf_bytes()
    with TestClient(create_app(_settings(tmp_path), _dependencies(accepted=False))) as client:
        receipt = client.post("/v1/build-jobs", files=_build_files(pdf)).json()
        terminal = _wait_terminal(client, receipt["status_path"])
        assert terminal["state"] == "quality_failed"
        result = client.get(receipt["result_path"])
        assert result.status_code == 200
        assert result.json()["status"] == "quality_failed"
        assert result.json()["accepted_for_indexing"] is False


class _PassiveWorker:
    def __init__(self, repository, **_kwargs) -> None:
        self.repository = repository
        self.starts = 0
        self.stops = 0
        self.wakes = 0
        self.healthy = False

    @property
    def snapshot(self) -> WorkerSnapshot:
        return WorkerSnapshot(
            status=WorkerStatus.HEALTHY if self.healthy else WorkerStatus.STOPPED,
            healthy=self.healthy,
            active_count=0,
            max_active=1,
        )

    async def start(self) -> WorkerSnapshot:
        self.starts += 1
        await asyncio.to_thread(self.repository.open)
        self.healthy = True
        return self.snapshot

    async def stop(self) -> WorkerSnapshot:
        self.stops += 1
        await asyncio.to_thread(self.repository.close)
        self.healthy = False
        return self.snapshot

    def wake(self) -> None:
        self.wakes += 1


def test_cancel_retry_delete_and_wake_follow_repository_state(tmp_path: Path) -> None:
    workers: list[_PassiveWorker] = []
    ids = iter(JOB_IDS)

    def repository_factory(root: Path):
        return BuildJobRepository(root, id_factory=lambda: next(ids))

    def worker_factory(repository, **kwargs):
        worker = _PassiveWorker(repository, **kwargs)
        workers.append(worker)
        return worker

    app = create_app(
        _settings(tmp_path),
        ServiceDependencies(
            repository_factory=repository_factory,
            worker_factory=worker_factory,
        ),
    )
    pdf = _pdf_bytes()
    with TestClient(app) as client:
        receipt = client.post("/v1/build-jobs", files=_build_files(pdf)).json()
        assert workers[0].starts == 1
        assert workers[0].wakes == 1
        not_ready = client.get(receipt["result_path"])
        assert (not_ready.status_code, not_ready.json()["code"]) == (
            409,
            "job_result_not_ready",
        )
        cancelled = client.post(receipt["status_path"] + "/cancel")
        assert cancelled.json()["state"] == "cancelled"
        repeated = client.post(receipt["status_path"] + "/cancel")
        assert repeated.json() == cancelled.json()
        retried = client.post(receipt["status_path"] + "/retry")
        assert retried.status_code == 202
        child = retried.json()
        assert child["attempt"] == 2
        assert child["parent_job_id"] == receipt["job_id"]
        assert workers[0].wakes == 2
        duplicate = client.post(receipt["status_path"] + "/retry")
        assert (duplicate.status_code, duplicate.json()["code"]) == (409, "job_retry_conflict")
        parent_delete = client.delete(receipt["status_path"])
        assert (parent_delete.status_code, parent_delete.json()["code"]) == (
            409,
            "job_delete_conflict",
        )
        active_delete = client.delete(child["status_path"])
        assert (active_delete.status_code, active_delete.json()["code"]) == (
            409,
            "job_delete_conflict",
        )
        client.post(child["status_path"] + "/cancel")
        assert client.delete(child["status_path"]).status_code == 204
        assert client.delete(receipt["status_path"]).status_code == 204
    assert workers[0].stops == 1


def test_unconfigured_invalid_and_failed_job_service_errors_are_stable(tmp_path: Path) -> None:
    with TestClient(create_app()) as client:
        unavailable = client.get("/v1/build-jobs/00000000-0000-4000-8000-000000000001")
    assert (unavailable.status_code, unavailable.json()["code"]) == (
        503,
        "job_service_unavailable",
    )

    settings = _settings(tmp_path)
    assert settings.job_root is not None
    settings.job_root.mkdir()
    (settings.job_root / "private-secret.txt").write_text("document", encoding="utf-8")
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/health/live").json()["ready"] is True
        assert client.get("/v1/health/ready").json()["ready"] is False
        failed = client.get("/v1/build-jobs/../private-secret.txt")
        assert failed.status_code in {404, 422}
        canonical_bad = client.get("/v1/build-jobs/%7B00000000-0000-4000-8000-000000000001%7D")
        assert canonical_bad.status_code == 503
        assert "private" not in canonical_bad.text


def test_submit_reuses_multipart_and_source_binding_errors(tmp_path: Path) -> None:
    pdf = _pdf_bytes()
    with TestClient(create_app(_settings(tmp_path), _dependencies())) as client:
        wrong_media = client.post(
            "/v1/build-jobs", content=b"{}", headers={"content-type": "application/json"}
        )
        mismatch = client.post("/v1/build-jobs", files=_build_files(pdf, digest="0" * 64))
        missing = client.post("/v1/build-jobs", files={"pdf": ("x.pdf", pdf, "application/pdf")})
        malformed_id = client.get("/v1/build-jobs/%7B00000000-0000-4000-8000-000000000001%7D")
    assert (wrong_media.status_code, wrong_media.json()["code"]) == (
        415,
        "unsupported_media_type",
    )
    assert (mismatch.status_code, mismatch.json()["code"]) == (
        409,
        "source_binding_mismatch",
    )
    assert (missing.status_code, missing.json()["code"]) == (422, "invalid_request")
    assert (malformed_id.status_code, malformed_id.json()["code"]) == (422, "invalid_request")


def test_readiness_combines_query_and_job_lifecycles(tmp_path: Path) -> None:
    query_settings, provider = _query_runtime(tmp_path)
    settings = query_settings.model_copy(update={"job_root": (tmp_path / "jobs").resolve()})
    job_dependencies = _dependencies()
    dependencies = ServiceDependencies(
        provider_factory=lambda: provider,
        repository_factory=job_dependencies.repository_factory,
        worker_factory=job_dependencies.worker_factory,
    )
    with TestClient(create_app(settings, dependencies)) as client:
        assert client.get("/v1/health/ready").json() == {
            "schema_version": "1.0",
            "status": "ready",
            "ready": True,
        }


def test_openapi_freezes_job_route_surface() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]
    assert set(path for path in paths if "build-jobs" in path) == {
        "/v1/build-jobs",
        "/v1/build-jobs/{job_id}",
        "/v1/build-jobs/{job_id}/result",
        "/v1/build-jobs/{job_id}/cancel",
        "/v1/build-jobs/{job_id}/retry",
    }
    submit = paths["/v1/build-jobs"]["post"]
    assert submit["operationId"] == "postV1BuildJobs"
    assert submit["responses"].keys() >= {"202", "409", "413", "415", "422", "500", "503"}
    assert submit["requestBody"]["content"]["multipart/form-data"]["schema"]["required"] == [
        "pdf",
        "identity",
    ]
    assert paths["/v1/build-jobs/{job_id}"]["delete"]["operationId"] == "deleteV1BuildJob"


def test_job_head_and_trailing_slash_use_uniform_envelopes(tmp_path: Path) -> None:
    job_id = "00000000-0000-4000-8000-000000000001"
    with TestClient(create_app(_settings(tmp_path), _dependencies())) as client:
        head = client.head(f"/v1/build-jobs/{job_id}")
        trailing = client.post("/v1/build-jobs/", follow_redirects=False)
    assert head.status_code == 405 and head.content == b""
    assert trailing.status_code == 404
    assert trailing.json()["code"] == "invalid_request"
