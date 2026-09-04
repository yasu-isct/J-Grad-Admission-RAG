"""Strict durable v1 contracts for local build jobs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

JOB_SCHEMA_VERSION = "1.0"


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    QUALITY_FAILED = "quality_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPhase(str, Enum):
    WAITING = "waiting"
    BUILDING = "building"
    CANCELLING = "cancelling"
    FINISHED = "finished"


class JobDiagnosticCode(str, Enum):
    WORKER_INTERRUPTED = "worker_interrupted"
    BUILD_FAILED = "build_failed"
    CANCELLED_BY_REQUEST = "cancelled_by_request"


TERMINAL_STATES = frozenset(
    {JobState.SUCCEEDED, JobState.QUALITY_FAILED, JobState.FAILED, JobState.CANCELLED}
)
RESULT_STATES = frozenset({JobState.SUCCEEDED, JobState.QUALITY_FAILED})
PHASE_BY_STATE = {
    JobState.QUEUED: JobPhase.WAITING,
    JobState.RUNNING: JobPhase.BUILDING,
    JobState.CANCEL_REQUESTED: JobPhase.CANCELLING,
    JobState.SUCCEEDED: JobPhase.FINISHED,
    JobState.QUALITY_FAILED: JobPhase.FINISHED,
    JobState.FAILED: JobPhase.FINISHED,
    JobState.CANCELLED: JobPhase.FINISHED,
}
LEGAL_TRANSITIONS = {
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.CANCELLED}),
    JobState.RUNNING: frozenset(
        {
            JobState.CANCEL_REQUESTED,
            JobState.SUCCEEDED,
            JobState.QUALITY_FAILED,
            JobState.FAILED,
            JobState.CANCELLED,
        }
    ),
    JobState.CANCEL_REQUESTED: frozenset({JobState.CANCELLED}),
    JobState.SUCCEEDED: frozenset(),
    JobState.QUALITY_FAILED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELLED: frozenset(),
}


class JobModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JobTransition(JobModel):
    sequence: int = Field(ge=1, strict=True)
    from_state: JobState | None
    to_state: JobState
    phase: JobPhase
    at: datetime
    diagnostic_code: JobDiagnosticCode | None = None

    @field_validator("at")
    @classmethod
    def timestamp_must_be_utc(cls, value: datetime) -> datetime:
        return _validate_utc(value)

    @model_validator(mode="after")
    def transition_must_be_legal(self) -> JobTransition:
        if self.phase != PHASE_BY_STATE[self.to_state]:
            raise ValueError("transition phase does not match target state")
        if self.from_state is None:
            if self.sequence != 1 or self.to_state != JobState.QUEUED:
                raise ValueError("only the initial queued transition has no source state")
        elif self.to_state not in LEGAL_TRANSITIONS[self.from_state]:
            raise ValueError("job transition is not legal")
        if self.to_state == JobState.FAILED:
            if self.diagnostic_code not in {
                JobDiagnosticCode.BUILD_FAILED,
                JobDiagnosticCode.WORKER_INTERRUPTED,
            }:
                raise ValueError("failed transition requires an allowlisted failure code")
        elif self.to_state == JobState.CANCELLED:
            if self.diagnostic_code != JobDiagnosticCode.CANCELLED_BY_REQUEST:
                raise ValueError("cancelled transition requires its allowlisted code")
        elif self.diagnostic_code is not None:
            raise ValueError("diagnostic code is not legal for this transition")
        return self


class BuildJobRecord(JobModel):
    schema_version: Literal["1.0"] = JOB_SCHEMA_VERSION
    job_id: UUID
    state: JobState
    phase: JobPhase
    attempt: int = Field(ge=1, strict=True)
    parent_job_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    diagnostic_code: JobDiagnosticCode | None = None
    result_available: bool = Field(strict=True)
    identity_blob: Literal["identity.json"] = "identity.json"
    options_blob: Literal["options.json"] = "options.json"
    source_pdf_blob: Literal["source.pdf"] = "source.pdf"
    result_blob: Literal["result.json"] | None = None
    transitions: tuple[JobTransition, ...] = Field(min_length=1)

    @field_validator("job_id", "parent_job_id", mode="before")
    @classmethod
    def uuid_must_be_canonical(cls, value: object) -> object:
        if value is None or isinstance(value, UUID):
            return value
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError("job ID must be a canonical UUID")
        return value

    @field_validator("created_at", "updated_at", "started_at", "finished_at")
    @classmethod
    def timestamps_must_be_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _validate_utc(value)

    @model_validator(mode="after")
    def record_must_be_consistent(self) -> BuildJobRecord:
        if self.phase != PHASE_BY_STATE[self.state]:
            raise ValueError("job phase does not match state")
        if (self.attempt == 1) != (self.parent_job_id is None):
            raise ValueError("only retry attempts have a parent job")
        if self.parent_job_id == self.job_id:
            raise ValueError("job cannot parent itself")
        if self.state in {JobState.RUNNING, JobState.CANCEL_REQUESTED} and self.started_at is None:
            raise ValueError("active execution requires a start timestamp")
        if self.state in {JobState.SUCCEEDED, JobState.QUALITY_FAILED, JobState.FAILED} and (
            self.started_at is None
        ):
            raise ValueError("completed execution requires a start timestamp")
        if self.state == JobState.QUEUED and (
            self.started_at is not None or self.finished_at is not None
        ):
            raise ValueError("queued job cannot have execution timestamps")
        if (self.state in TERMINAL_STATES) != (self.finished_at is not None):
            raise ValueError("only terminal jobs require a finish timestamp")
        if self.result_available != (self.state in RESULT_STATES):
            raise ValueError("result availability does not match state")
        if (self.result_blob is not None) != self.result_available:
            raise ValueError("result blob does not match availability")
        if self.state == JobState.FAILED:
            if self.diagnostic_code not in {
                JobDiagnosticCode.BUILD_FAILED,
                JobDiagnosticCode.WORKER_INTERRUPTED,
            }:
                raise ValueError("failed job requires an allowlisted failure code")
        elif self.state == JobState.CANCELLED:
            if self.diagnostic_code != JobDiagnosticCode.CANCELLED_BY_REQUEST:
                raise ValueError("cancelled job requires its allowlisted code")
        elif self.diagnostic_code is not None:
            raise ValueError("diagnostic code is not legal for this job")
        present = [
            value
            for value in (self.created_at, self.started_at, self.finished_at, self.updated_at)
            if value is not None
        ]
        if any(left > right for left, right in zip(present, present[1:])):
            raise ValueError("job timestamps are not monotonic")
        if tuple(item.sequence for item in self.transitions) != tuple(
            range(1, len(self.transitions) + 1)
        ):
            raise ValueError("transition sequence is not contiguous")
        if self.transitions[0].at != self.created_at:
            raise ValueError("initial transition must match creation time")
        for previous, current in zip(self.transitions, self.transitions[1:]):
            if current.from_state != previous.to_state or current.at < previous.at:
                raise ValueError("transition history is not continuous and monotonic")
        final = self.transitions[-1]
        if (
            final.to_state != self.state
            or final.phase != self.phase
            or final.at != self.updated_at
            or final.diagnostic_code != self.diagnostic_code
        ):
            raise ValueError("current job fields do not match transition history")
        return self


def canonical_job_record_bytes(record: BuildJobRecord) -> bytes:
    validated = BuildJobRecord.model_validate(record.model_dump(mode="json"))
    payload = json.dumps(
        validated.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{payload}\n".encode("utf-8")


def _validate_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("job timestamps must be timezone-aware UTC")
    return value


__all__ = [
    "BuildJobRecord",
    "JOB_SCHEMA_VERSION",
    "JobDiagnosticCode",
    "JobPhase",
    "JobState",
    "JobTransition",
    "LEGAL_TRANSITIONS",
    "PHASE_BY_STATE",
    "RESULT_STATES",
    "TERMINAL_STATES",
    "canonical_job_record_bytes",
]
