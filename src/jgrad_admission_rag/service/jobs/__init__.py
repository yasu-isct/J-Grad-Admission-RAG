"""Durable local build-job contracts and repository."""

from .contracts import BuildJobRecord, JobDiagnosticCode, JobPhase, JobState, JobTransition
from .repository import (
    BuildJobRepository,
    JobConflictError,
    JobNotFoundError,
    JobRepositoryError,
    JobRepositoryUnavailableError,
    JobValidationError,
    OwnedJobInputs,
)
from .worker import (
    BuildJobWorker,
    BuildRunner,
    MAX_SHUTDOWN_GRACE_SECONDS,
    MAX_WORKER_CONCURRENCY,
    WorkerDiagnosticCode,
    WorkerSnapshot,
    WorkerStatus,
)

__all__ = [
    "BuildJobRecord",
    "BuildJobRepository",
    "BuildJobWorker",
    "BuildRunner",
    "JobConflictError",
    "JobDiagnosticCode",
    "JobNotFoundError",
    "JobPhase",
    "JobRepositoryError",
    "JobRepositoryUnavailableError",
    "JobState",
    "JobTransition",
    "JobValidationError",
    "MAX_SHUTDOWN_GRACE_SECONDS",
    "MAX_WORKER_CONCURRENCY",
    "OwnedJobInputs",
    "WorkerDiagnosticCode",
    "WorkerSnapshot",
    "WorkerStatus",
]
