"""Bounded async orchestration for durable local build jobs."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...schemas.document_identity import DocumentIdentity
from ..build_execution import build_response
from ..contracts import BuildOptions, BuildResponse
from .contracts import JobState, RESULT_STATES
from .repository import (
    BuildJobRepository,
    JobConflictError,
    JobRepositoryError,
    JobValidationError,
)

BuildRunner = Callable[[Path, DocumentIdentity, BuildOptions], BuildResponse]
MAX_WORKER_CONCURRENCY = 8
MAX_SHUTDOWN_GRACE_SECONDS = 60.0


class WorkerStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    HEALTHY = "healthy"
    STOPPING = "stopping"
    UNHEALTHY = "unhealthy"


class WorkerDiagnosticCode(str, Enum):
    REPOSITORY_UNAVAILABLE = "repository_unavailable"
    WORKER_FAILURE = "worker_failure"


class WorkerSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: WorkerStatus
    healthy: bool = Field(strict=True)
    active_count: int = Field(ge=0, strict=True)
    max_active: int = Field(gt=0, strict=True)
    diagnostic_code: WorkerDiagnosticCode | None = None

    @model_validator(mode="after")
    def snapshot_must_be_consistent(self) -> WorkerSnapshot:
        if self.healthy != (self.status == WorkerStatus.HEALTHY):
            raise ValueError("worker health does not match status")
        if self.active_count > self.max_active:
            raise ValueError("worker active count exceeds its bound")
        if (self.diagnostic_code is not None) != (self.status == WorkerStatus.UNHEALTHY):
            raise ValueError("worker diagnostic does not match status")
        return self


class BuildJobWorker:
    """Own a fixed number of claim loops without doing work at construction time."""

    def __init__(
        self,
        repository: BuildJobRepository,
        *,
        build_runner: BuildRunner | None = None,
        max_active: int = 1,
        shutdown_grace_seconds: float = 0.25,
    ) -> None:
        if (
            isinstance(max_active, bool)
            or not isinstance(max_active, int)
            or not 1 <= max_active <= MAX_WORKER_CONCURRENCY
        ):
            raise ValueError("worker max_active is outside its supported bound")
        if (
            isinstance(shutdown_grace_seconds, bool)
            or not isinstance(shutdown_grace_seconds, (int, float))
            or not math.isfinite(shutdown_grace_seconds)
            or not 0 <= shutdown_grace_seconds <= MAX_SHUTDOWN_GRACE_SECONDS
        ):
            raise ValueError("worker shutdown grace is outside its supported bound")
        self._repository = repository
        self._build_runner = build_runner or _default_build_runner
        self._max_active = max_active
        self._shutdown_grace_seconds = float(shutdown_grace_seconds)
        self._status = WorkerStatus.STOPPED
        self._diagnostic_code: WorkerDiagnosticCode | None = None
        self._active_count = 0
        self._tasks: set[asyncio.Task[None]] = set()
        self._wake_event = asyncio.Event()
        self._stopped_event = asyncio.Event()
        self._stopped_event.set()
        self._lifecycle_lock = asyncio.Lock()
        self._stop_requested = False
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def snapshot(self) -> WorkerSnapshot:
        return WorkerSnapshot(
            status=self._status,
            healthy=self._status == WorkerStatus.HEALTHY,
            active_count=self._active_count,
            max_active=self._max_active,
            diagnostic_code=self._diagnostic_code,
        )

    async def start(self) -> WorkerSnapshot:
        async with self._lifecycle_lock:
            if self._status in {WorkerStatus.HEALTHY, WorkerStatus.STARTING}:
                return self.snapshot
            if self._status in {WorkerStatus.STOPPING, WorkerStatus.UNHEALTHY}:
                return self.snapshot
            self._status = WorkerStatus.STARTING
            self._diagnostic_code = None
            self._stop_requested = False
            self._loop = asyncio.get_running_loop()
            self._wake_event = asyncio.Event()
            open_task = asyncio.create_task(asyncio.to_thread(self._repository.open))
            try:
                await asyncio.shield(open_task)
            except asyncio.CancelledError:
                try:
                    await open_task
                finally:
                    await asyncio.to_thread(self._repository.close)
                    self._status = WorkerStatus.STOPPED
                    self._loop = None
                raise
            except BaseException:
                self._status = WorkerStatus.UNHEALTHY
                self._diagnostic_code = WorkerDiagnosticCode.REPOSITORY_UNAVAILABLE
                return self.snapshot
            self._status = WorkerStatus.HEALTHY
            self._stopped_event.clear()
            self._wake_event.set()
            self._tasks = {
                asyncio.create_task(self._claim_loop(), name=f"jgrad-build-worker-{slot}")
                for slot in range(self._max_active)
            }
            return self.snapshot

    def wake(self) -> None:
        loop = self._loop
        if loop is not None and loop.is_running() and self._status == WorkerStatus.HEALTHY:
            loop.call_soon_threadsafe(self._wake_event.set)

    notify = wake

    async def stop(self) -> WorkerSnapshot:
        async with self._lifecycle_lock:
            if self._status == WorkerStatus.STOPPED:
                return self.snapshot
            if self._status == WorkerStatus.STOPPING:
                wait_for_owner = True
                tasks: tuple[asyncio.Task[None], ...] = ()
            else:
                wait_for_owner = False
                self._status = WorkerStatus.STOPPING
                self._stop_requested = True
                self._wake_event.set()
                tasks = tuple(self._tasks)
        if wait_for_owner:
            await self._stopped_event.wait()
            return self.snapshot
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self._shutdown_grace_seconds)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        close_failed = False
        try:
            await asyncio.to_thread(self._repository.close)
        except BaseException:
            close_failed = True
        finally:
            async with self._lifecycle_lock:
                self._tasks.clear()
                self._active_count = 0
                self._status = WorkerStatus.UNHEALTHY if close_failed else WorkerStatus.STOPPED
                self._diagnostic_code = (
                    WorkerDiagnosticCode.REPOSITORY_UNAVAILABLE if close_failed else None
                )
                self._loop = None
                self._stopped_event.set()
        return self.snapshot

    async def _claim_loop(self) -> None:
        try:
            while not self._stop_requested:
                record = await asyncio.to_thread(self._repository.claim_next_queued)
                if record is not None:
                    await self._run_job(record.job_id)
                    continue
                self._wake_event.clear()
                if self._stop_requested:
                    return
                # Close the clear/submit race before sleeping for a notification.
                record = await asyncio.to_thread(self._repository.claim_next_queued)
                if record is not None:
                    await self._run_job(record.job_id)
                    continue
                await self._wake_event.wait()
        except asyncio.CancelledError:
            raise
        except JobRepositoryError:
            self._mark_unhealthy(WorkerDiagnosticCode.REPOSITORY_UNAVAILABLE)
        except BaseException:
            self._mark_unhealthy(WorkerDiagnosticCode.WORKER_FAILURE)

    async def _run_job(self, job_id: Any) -> None:
        try:
            inputs = await asyncio.to_thread(self._repository.read_inputs, job_id)
            current = await asyncio.to_thread(self._repository.get, job_id)
            if current.state == JobState.CANCEL_REQUESTED:
                await asyncio.to_thread(self._repository.finish_cancelled, job_id)
                return
            if current.state != JobState.RUNNING or self._stop_requested:
                return
        except JobRepositoryError:
            raise

        self._active_count += 1
        build_task = asyncio.create_task(
            asyncio.to_thread(
                self._build_runner,
                inputs.source_pdf,
                inputs.identity,
                inputs.options,
            )
        )
        build_task.add_done_callback(_consume_detached_task)
        try:
            result = await asyncio.shield(build_task)
            result = BuildResponse.model_validate(result.model_dump(mode="json"))
        except asyncio.CancelledError:
            raise
        except BaseException:
            await self._finish_after_build_failure(job_id)
            return
        finally:
            self._active_count -= 1

        if self._stop_requested:
            return
        current = await asyncio.to_thread(self._repository.get, job_id)
        if current.state == JobState.CANCEL_REQUESTED:
            await asyncio.to_thread(self._repository.finish_cancelled, job_id)
            return
        if current.state != JobState.RUNNING:
            return
        try:
            await asyncio.to_thread(self._repository.publish_result, job_id, result)
        except JobValidationError:
            await self._finish_after_build_failure(job_id)
        except JobConflictError:
            current = await asyncio.to_thread(self._repository.get, job_id)
            if current.state == JobState.CANCEL_REQUESTED:
                await asyncio.to_thread(self._repository.finish_cancelled, job_id)
            elif current.state not in RESULT_STATES:
                raise

    async def _finish_after_build_failure(self, job_id: Any) -> None:
        if self._stop_requested:
            return
        current = await asyncio.to_thread(self._repository.get, job_id)
        if current.state == JobState.CANCEL_REQUESTED:
            await asyncio.to_thread(self._repository.finish_cancelled, job_id)
        elif current.state == JobState.RUNNING:
            await asyncio.to_thread(self._repository.finish_failed, job_id)

    def _mark_unhealthy(self, code: WorkerDiagnosticCode) -> None:
        self._diagnostic_code = code
        self._status = WorkerStatus.UNHEALTHY
        self._stop_requested = True
        self._wake_event.set()


def _default_build_runner(
    pdf_path: Path, identity: DocumentIdentity, options: BuildOptions
) -> BuildResponse:
    return build_response(
        pdf_path,
        identity,
        options,
        source_pdf="source.pdf",
    )


def _consume_detached_task(task: asyncio.Task[BuildResponse]) -> None:
    if not task.cancelled():
        try:
            task.exception()
        except BaseException:
            pass


__all__ = [
    "BuildJobWorker",
    "BuildRunner",
    "MAX_SHUTDOWN_GRACE_SECONDS",
    "MAX_WORKER_CONCURRENCY",
    "WorkerDiagnosticCode",
    "WorkerSnapshot",
    "WorkerStatus",
]
