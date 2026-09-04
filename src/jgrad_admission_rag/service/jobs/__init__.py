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

__all__ = [
    "BuildJobRecord",
    "BuildJobRepository",
    "JobConflictError",
    "JobDiagnosticCode",
    "JobNotFoundError",
    "JobPhase",
    "JobRepositoryError",
    "JobRepositoryUnavailableError",
    "JobState",
    "JobTransition",
    "JobValidationError",
    "OwnedJobInputs",
]
