from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.service.build_execution import build_response
from jgrad_admission_rag.service.jobs import (
    BuildJobRepository,
    BuildJobWorker,
    JobRepositoryUnavailableError,
    JobState,
    MAX_WORKER_CONCURRENCY,
    WorkerDiagnosticCode,
    WorkerStatus,
    WorkerSnapshot,
)
from tests.test_job_repository import _inputs, _repository, _result


async def _wait_for_state(
    repository: BuildJobRepository,
    job_id,
    states: set[JobState],
    *,
    timeout: float = 3,
):
    async def wait():
        while True:
            record = await asyncio.to_thread(repository.get, job_id)
            if record.state in states:
                return record
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(wait(), timeout)


def _queued_job(tmp_path: Path):
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    repository = _repository(root).open()
    record = repository.create(identity, options, pdf)
    repository.close()
    return root, record, identity


def test_worker_configuration_and_snapshot_are_strict(tmp_path: Path) -> None:
    repository = BuildJobRepository((tmp_path / "store").resolve())
    with pytest.raises(ValueError):
        BuildJobWorker(repository, max_active=MAX_WORKER_CONCURRENCY + 1)
    with pytest.raises(ValueError):
        BuildJobWorker(repository, shutdown_grace_seconds=float("nan"))
    with pytest.raises(ValidationError):
        WorkerSnapshot(status="stopped", healthy=True, active_count=0, max_active=1)


class _RecordingRepository:
    def __init__(self, repository: BuildJobRepository) -> None:
        self.repository = repository
        self.thread_ids: list[int] = []
        self.calls: list[str] = []

    def _call(self, name: str, *args):
        self.thread_ids.append(threading.get_ident())
        self.calls.append(name)
        return getattr(self.repository, name)(*args)

    def open(self):
        return self._call("open")

    def close(self):
        return self._call("close")

    def claim_next_queued(self):
        return self._call("claim_next_queued")

    def read_inputs(self, job_id):
        return self._call("read_inputs", job_id)

    def get(self, job_id):
        return self._call("get", job_id)

    def publish_result(self, job_id, result):
        return self._call("publish_result", job_id, result)

    def finish_failed(self, job_id):
        return self._call("finish_failed", job_id)

    def finish_cancelled(self, job_id):
        return self._call("finish_cancelled", job_id)


def test_construction_is_inert_and_start_drains_off_event_loop(tmp_path: Path) -> None:
    root, queued, identity_bytes = _queued_job(tmp_path)
    repository = _RecordingRepository(BuildJobRepository(root))
    builder_threads: list[int] = []

    def runner(_path, _identity, _options):
        builder_threads.append(threading.get_ident())
        return _result(identity_bytes)

    worker = BuildJobWorker(repository, build_runner=runner)
    assert worker.snapshot.status == WorkerStatus.STOPPED
    assert not repository.repository.is_open

    async def exercise() -> None:
        loop_thread = threading.get_ident()
        first = await worker.start()
        second = await worker.start()
        assert first == second
        terminal = await _wait_for_state(repository.repository, queued.job_id, {JobState.SUCCEEDED})
        assert terminal.result_available
        await asyncio.sleep(0.05)
        idle_claim_count = len(repository.thread_ids)
        await asyncio.sleep(0.05)
        assert len(repository.thread_ids) == idle_claim_count
        assert builder_threads and all(item != loop_thread for item in builder_threads)
        assert repository.thread_ids and all(item != loop_thread for item in repository.thread_ids)
        stopped = await asyncio.gather(worker.stop(), worker.stop())
        assert all(item.status == WorkerStatus.STOPPED for item in stopped)
        assert (await worker.stop()).status == WorkerStatus.STOPPED

    asyncio.run(exercise())
    assert not repository.repository.is_open
    assert repository.thread_ids
    assert repository.calls.count("close") == 1


def test_wake_processes_a_job_submitted_after_idle(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    repository = BuildJobRepository(root)
    worker = BuildJobWorker(repository, build_runner=lambda *_: _result(identity))

    async def exercise() -> None:
        await worker.start()
        await asyncio.sleep(0.05)
        queued = await asyncio.to_thread(repository.create, identity, options, pdf)
        worker.wake()
        await _wait_for_state(repository, queued.job_id, {JobState.SUCCEEDED})
        await worker.stop()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("accepted", "expected"),
    ((True, JobState.SUCCEEDED), (False, JobState.QUALITY_FAILED)),
)
def test_worker_publishes_complete_quality_outcome(
    tmp_path: Path, accepted: bool, expected: JobState
) -> None:
    root, queued, identity_bytes = _queued_job(tmp_path)
    repository = BuildJobRepository(root)
    worker = BuildJobWorker(
        repository,
        build_runner=lambda *_: _result(identity_bytes, accepted=accepted),
    )

    async def exercise() -> None:
        await worker.start()
        terminal = await _wait_for_state(repository, queued.job_id, {expected})
        result = await asyncio.to_thread(repository.read_result, queued.job_id)
        assert result.accepted_for_indexing is accepted
        assert terminal.result_available
        await worker.stop()

    asyncio.run(exercise())


def test_builder_failure_is_private_and_next_job_continues(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    creator = _repository(root).open()
    first = creator.create(identity, options, pdf)
    second = creator.create(identity, options, pdf)
    creator.close()
    calls = 0

    def runner(*_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("private path and extracted document text")
        return _result(identity)

    repository = BuildJobRepository(root)
    worker = BuildJobWorker(repository, build_runner=runner)

    async def exercise() -> None:
        await worker.start()
        failed = await _wait_for_state(repository, first.job_id, {JobState.FAILED})
        succeeded = await _wait_for_state(repository, second.job_id, {JobState.SUCCEEDED})
        assert failed.diagnostic_code == "build_failed"
        assert "private" not in failed.model_dump_json()
        assert succeeded.result_available
        assert worker.snapshot.healthy
        await worker.stop()

    asyncio.run(exercise())


def test_mismatched_builder_result_fails_only_its_job(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    wrong_payload = json.loads(identity)
    wrong_payload["document_id"] = "other-document"
    wrong_identity = json.dumps(wrong_payload).encode()
    root = (tmp_path / "store").resolve()
    creator = _repository(root).open()
    first = creator.create(identity, options, pdf)
    second = creator.create(identity, options, pdf)
    creator.close()
    calls = 0

    def runner(*_):
        nonlocal calls
        calls += 1
        return _result(wrong_identity if calls == 1 else identity)

    repository = BuildJobRepository(root)
    worker = BuildJobWorker(repository, build_runner=runner)

    async def exercise() -> None:
        await worker.start()
        await _wait_for_state(repository, first.job_id, {JobState.FAILED})
        await _wait_for_state(repository, second.job_id, {JobState.SUCCEEDED})
        assert worker.snapshot.healthy
        await worker.stop()

    asyncio.run(exercise())


def test_queued_cancellation_never_invokes_builder(tmp_path: Path) -> None:
    root, queued, _ = _queued_job(tmp_path)
    repository = BuildJobRepository(root).open()
    repository.request_cancel(queued.job_id)
    repository.close()
    calls = 0

    def runner(*_):
        nonlocal calls
        calls += 1
        raise AssertionError

    worker = BuildJobWorker(BuildJobRepository(root), build_runner=runner)

    async def exercise() -> None:
        await worker.start()
        await asyncio.sleep(0.05)
        await worker.stop()

    asyncio.run(exercise())
    assert calls == 0


def test_running_cancellation_discards_builder_result(tmp_path: Path) -> None:
    root, queued, identity_bytes = _queued_job(tmp_path)
    repository = BuildJobRepository(root)
    entered = threading.Event()
    release = threading.Event()

    def runner(*_):
        entered.set()
        assert release.wait(3)
        return _result(identity_bytes)

    worker = BuildJobWorker(repository, build_runner=runner)

    async def exercise() -> None:
        await worker.start()
        assert await asyncio.to_thread(entered.wait, 2)
        requested = await asyncio.to_thread(repository.request_cancel, queued.job_id)
        assert requested.state == JobState.CANCEL_REQUESTED
        release.set()
        terminal = await _wait_for_state(repository, queued.job_id, {JobState.CANCELLED})
        assert not terminal.result_available
        await worker.stop()

    asyncio.run(exercise())


def test_configured_concurrency_is_bounded(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    creator = _repository(root).open()
    jobs = [creator.create(identity, options, pdf) for _ in range(3)]
    creator.close()
    lock = threading.Lock()
    release = threading.Event()
    entered_two = threading.Event()
    active = 0
    maximum = 0

    def runner(*_):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                entered_two.set()
        assert release.wait(3)
        with lock:
            active -= 1
        return _result(identity)

    repository = BuildJobRepository(root)
    worker = BuildJobWorker(repository, build_runner=runner, max_active=2)

    async def exercise() -> None:
        await worker.start()
        assert await asyncio.to_thread(entered_two.wait, 2)
        assert worker.snapshot.active_count == 2
        release.set()
        for job in jobs:
            await _wait_for_state(repository, job.job_id, {JobState.SUCCEEDED})
        await worker.stop()

    asyncio.run(exercise())
    assert maximum == 2


def test_stop_during_build_is_bounded_and_recovery_marks_interruption(tmp_path: Path) -> None:
    root, queued, identity_bytes = _queued_job(tmp_path)
    repository = BuildJobRepository(root)
    entered = threading.Event()
    release = threading.Event()

    def runner(*_):
        entered.set()
        assert release.wait(3)
        return _result(identity_bytes)

    worker = BuildJobWorker(
        repository,
        build_runner=runner,
        shutdown_grace_seconds=0,
    )

    async def exercise() -> None:
        await worker.start()
        assert await asyncio.to_thread(entered.wait, 2)
        await worker.stop()
        assert not repository.is_open
        release.set()
        await asyncio.sleep(0.05)

    asyncio.run(exercise())
    with BuildJobRepository(root).open() as recovered:
        record = recovered.get(queued.job_id)
        assert record.state == JobState.FAILED
        assert record.diagnostic_code == "worker_interrupted"
        assert not record.result_available


def test_repository_start_failure_is_unhealthy_and_privacy_safe(tmp_path: Path) -> None:
    root = (tmp_path / "store").resolve()
    root.mkdir()
    (root / "private-secret.txt").write_text("document text", encoding="utf-8")
    worker = BuildJobWorker(BuildJobRepository(root))

    async def exercise() -> None:
        snapshot = await worker.start()
        assert snapshot.status == WorkerStatus.UNHEALTHY
        assert snapshot.diagnostic_code == WorkerDiagnosticCode.REPOSITORY_UNAVAILABLE
        assert "private" not in snapshot.model_dump_json()
        await worker.stop()

    asyncio.run(exercise())


def test_runtime_repository_failure_stops_claims_and_marks_unhealthy(tmp_path: Path) -> None:
    class FailingClaimRepository(BuildJobRepository):
        def claim_next_queued(self):
            raise JobRepositoryUnavailableError("planted secret and path")

    repository = FailingClaimRepository((tmp_path / "store").resolve())
    worker = BuildJobWorker(repository)

    async def exercise() -> None:
        await worker.start()

        async def wait_unhealthy():
            while worker.snapshot.status != WorkerStatus.UNHEALTHY:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_unhealthy(), 2)
        snapshot = worker.snapshot
        assert snapshot.diagnostic_code == WorkerDiagnosticCode.REPOSITORY_UNAVAILABLE
        assert "secret" not in snapshot.model_dump_json()
        await worker.stop()

    asyncio.run(exercise())


def test_shared_build_assembly_preserves_options_and_detaches_result(tmp_path: Path) -> None:
    identity_bytes, _, pdf = _inputs(tmp_path)
    from jgrad_admission_rag.schemas.document_identity import load_document_identity_bytes
    from jgrad_admission_rag.service.contracts import BuildOptions

    identity = load_document_identity_bytes(identity_bytes)
    options = BuildOptions(max_chars=1234, short_fact_threshold=55)
    observed: list[dict] = []
    source_kb = _result(identity_bytes).knowledge_base

    def builder(_path, _identity, **kwargs):
        observed.append(kwargs)
        return source_kb

    worker_result = build_response(
        pdf,
        identity,
        options,
        source_pdf="source.pdf",
        builder=builder,
    )
    upload_result = build_response(
        pdf,
        identity,
        options,
        source_pdf="uploaded.pdf",
        builder=builder,
    )

    assert observed[0] == observed[1]
    assert observed[0]["max_chars"] == 1234
    assert observed[0]["short_fact_threshold"] == 55
    assert worker_result.summary == upload_result.summary
    assert worker_result.knowledge_base.manifest.source_pdf == "source.pdf"
    assert upload_result.knowledge_base.manifest.source_pdf == "uploaded.pdf"
    assert source_kb.manifest.source_pdf == "source.pdf"
