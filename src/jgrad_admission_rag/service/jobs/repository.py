"""Single-owner SQLite and filesystem repository for durable build jobs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import BinaryIO, Iterator
from uuid import UUID, uuid4

from pydantic import ValidationError

from ...schemas.document_identity import (
    DocumentIdentity,
    DocumentIdentityError,
    canonical_document_identity_bytes,
    load_document_identity_bytes,
)
from ..contracts import BuildOptions, BuildResponse
from .contracts import (
    JOB_SCHEMA_VERSION,
    LEGAL_TRANSITIONS,
    PHASE_BY_STATE,
    RESULT_STATES,
    TERMINAL_STATES,
    BuildJobRecord,
    JobDiagnosticCode,
    JobState,
    JobTransition,
)

DATABASE_NAME = "jobs.sqlite3"
LOCK_NAME = ".repository.lock"
JOBS_DIRECTORY = "jobs"
STAGING_DIRECTORY = ".staging"
IDENTITY_BLOB = "identity.json"
OPTIONS_BLOB = "options.json"
PDF_BLOB = "source.pdf"
RESULT_BLOB = "result.json"
_ALLOWED_ROOT_NAMES = {
    DATABASE_NAME,
    f"{DATABASE_NAME}-journal",
    f"{DATABASE_NAME}-shm",
    f"{DATABASE_NAME}-wal",
    LOCK_NAME,
    JOBS_DIRECTORY,
    STAGING_DIRECTORY,
}


class JobRepositoryError(Exception):
    """Base class for privacy-safe durable job errors."""


class JobRepositoryUnavailableError(JobRepositoryError):
    """Raised when ownership, storage, schema, or layout cannot be trusted."""


class JobValidationError(JobRepositoryError):
    """Raised when supplied durable input is invalid or inconsistent."""


class JobNotFoundError(JobRepositoryError):
    """Raised when a canonical job ID has no durable record."""


class JobConflictError(JobRepositoryError):
    """Raised when a legal atomic operation cannot apply to current state."""


@dataclass(frozen=True, slots=True)
class OwnedJobInputs:
    identity: DocumentIdentity
    options: BuildOptions
    source_pdf: Path


class BuildJobRepository:
    """Explicitly opened, process-local facade over one server-owned job root."""

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        candidate = Path(root)
        if not candidate.is_absolute():
            raise ValueError("job repository root must be absolute")
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            raise ValueError("job repository root is invalid") from None
        if resolved != candidate:
            raise ValueError("job repository root must be canonical")
        self.root = resolved
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or uuid4
        self._connection: sqlite3.Connection | None = None
        self._lock_handle: BinaryIO | None = None
        self._mutex = RLock()

    @property
    def is_open(self) -> bool:
        return self._connection is not None

    def open(self) -> BuildJobRepository:
        with self._mutex:
            if self.is_open:
                return self
            try:
                if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
                    raise OSError
                self.root.mkdir(parents=True, exist_ok=True)
                self._acquire_owner_lock()
                self._validate_root_layout()
                (self.root / JOBS_DIRECTORY).mkdir(exist_ok=True)
                (self.root / STAGING_DIRECTORY).mkdir(exist_ok=True)
                self._connection = sqlite3.connect(
                    self.root / DATABASE_NAME,
                    timeout=5,
                    isolation_level=None,
                    check_same_thread=False,
                )
                self._connection.row_factory = sqlite3.Row
                self._connection.execute("PRAGMA foreign_keys = ON")
                self._connection.execute("PRAGMA journal_mode = DELETE")
                self._initialize_schema()
                self._recover_owned_storage()
                return self
            except JobRepositoryUnavailableError:
                self.close()
                raise
            except (OSError, sqlite3.Error, ValueError, ValidationError):
                self.close()
                raise JobRepositoryUnavailableError("job repository is unavailable") from None

    def close(self) -> None:
        with self._mutex:
            try:
                if self._connection is not None:
                    self._connection.close()
            finally:
                self._connection = None
                if self._lock_handle is not None:
                    _unlock_file(self._lock_handle)
                    self._lock_handle.close()
                    self._lock_handle = None

    def __enter__(self) -> BuildJobRepository:
        return self.open()

    def __exit__(self, *_: object) -> None:
        self.close()

    def create(
        self,
        identity_bytes: bytes,
        options_bytes: bytes,
        source_pdf: str | Path,
    ) -> BuildJobRecord:
        identity, canonical_identity, canonical_options = _validate_inputs(
            identity_bytes, options_bytes, source_pdf
        )
        source_path = Path(source_pdf)
        with self._mutex:
            connection = self._require_open()
            for _ in range(3):
                job_id = self._new_job_id()
                if (
                    connection.execute(
                        "SELECT 1 FROM jobs WHERE job_id = ?", (str(job_id),)
                    ).fetchone()
                    is None
                    and not self._job_path(job_id).exists()
                ):
                    break
            else:
                raise JobConflictError("could not allocate a unique job ID")
            now = self._now()
            record = _initial_record(job_id, now)
            self._publish_new_job(
                record,
                canonical_identity,
                canonical_options,
                source_path,
                identity,
            )
            return self.get(job_id)

    def get(self, job_id: str | UUID) -> BuildJobRecord:
        canonical_id = _canonical_uuid(job_id)
        with self._mutex:
            row = (
                self._require_open()
                .execute("SELECT * FROM jobs WHERE job_id = ?", (str(canonical_id),))
                .fetchone()
            )
            if row is None:
                raise JobNotFoundError("job was not found")
            record = _load_record_row(row)
            self._validate_job_storage(record)
            return _detach(record)

    def list(self) -> tuple[BuildJobRecord, ...]:
        with self._mutex:
            rows = (
                self._require_open()
                .execute("SELECT * FROM jobs ORDER BY created_at, job_id")
                .fetchall()
            )
            records = tuple(_load_record_row(row) for row in rows)
            for record in records:
                self._validate_job_storage(record)
            return tuple(_detach(record) for record in records)

    def read_inputs(self, job_id: str | UUID) -> OwnedJobInputs:
        record = self.get(job_id)
        identity, _, options_bytes, source_pdf = self._load_owned_inputs(record)
        return OwnedJobInputs(
            identity=identity,
            options=BuildOptions.model_validate_json(options_bytes),
            source_pdf=source_pdf,
        )

    def claim_next_queued(self) -> BuildJobRecord | None:
        with self._mutex, self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE state = ? ORDER BY created_at, job_id LIMIT 1",
                (JobState.QUEUED.value,),
            ).fetchone()
            if row is None:
                return None
            current = _load_record_row(row)
            updated = self._transition(current, JobState.RUNNING)
            self._update_record(connection, updated)
        return self.get(updated.job_id)

    def request_cancel(self, job_id: str | UUID) -> BuildJobRecord:
        canonical_id = _canonical_uuid(job_id)
        with self._mutex, self._transaction() as connection:
            current = self._get_for_update(connection, canonical_id)
            if current.state == JobState.CANCEL_REQUESTED:
                return _detach(current)
            if current.state == JobState.QUEUED:
                target = JobState.CANCELLED
            elif current.state == JobState.RUNNING:
                target = JobState.CANCEL_REQUESTED
            else:
                raise JobConflictError("job cannot accept cancellation in its current state")
            updated = self._transition(
                current,
                target,
                diagnostic=(
                    JobDiagnosticCode.CANCELLED_BY_REQUEST if target == JobState.CANCELLED else None
                ),
            )
            self._update_record(connection, updated)
        return self.get(canonical_id)

    def finish_failed(
        self,
        job_id: str | UUID,
        code: JobDiagnosticCode = JobDiagnosticCode.BUILD_FAILED,
    ) -> BuildJobRecord:
        if code not in {
            JobDiagnosticCode.BUILD_FAILED,
            JobDiagnosticCode.WORKER_INTERRUPTED,
        }:
            raise JobValidationError("failure diagnostic code is invalid")
        return self._finish(job_id, JobState.FAILED, code)

    def finish_cancelled(self, job_id: str | UUID) -> BuildJobRecord:
        return self._finish(
            job_id,
            JobState.CANCELLED,
            JobDiagnosticCode.CANCELLED_BY_REQUEST,
        )

    def publish_result(self, job_id: str | UUID, result: BuildResponse) -> BuildJobRecord:
        canonical_id = _canonical_uuid(job_id)
        try:
            validated = BuildResponse.model_validate(result.model_dump(mode="json"))
            raw = _canonical_json_bytes(validated.model_dump(mode="json"))
        except (AttributeError, TypeError, ValueError, ValidationError):
            raise JobValidationError("build result is invalid") from None
        target_state = (
            JobState.SUCCEEDED if validated.accepted_for_indexing else JobState.QUALITY_FAILED
        )
        stage = self._stage_path("result", canonical_id)
        marker = self._marker_path("result", canonical_id)
        result_path = self._job_path(canonical_id) / RESULT_BLOB
        with self._mutex:
            self._require_open()
            _write_file_exclusive(stage, raw)
            _write_file_exclusive(marker, b"1")
            published = False
            committed = False
            try:
                with self._transaction() as connection:
                    current = self._get_for_update(connection, canonical_id)
                    if current.state != JobState.RUNNING or result_path.exists():
                        raise JobConflictError("job cannot publish a result in its current state")
                    identity, _, _, _ = self._load_owned_inputs(current)
                    if (
                        validated.knowledge_base.manifest.identity != identity
                        or validated.knowledge_base.manifest.source_pdf != PDF_BLOB
                    ):
                        raise JobValidationError("build result does not match job inputs")
                    os.replace(stage, result_path)
                    published = True
                    updated = self._transition(current, target_state, result_available=True)
                    self._update_record(connection, updated)
                committed = True
                _unlink_if_regular(marker)
            except BaseException:
                if not committed:
                    _unlink_if_regular(stage)
                    _unlink_if_regular(marker)
                if published and not committed:
                    row = (
                        self._require_open()
                        .execute("SELECT state FROM jobs WHERE job_id = ?", (str(canonical_id),))
                        .fetchone()
                    )
                    if row is not None and row["state"] not in {
                        JobState.SUCCEEDED.value,
                        JobState.QUALITY_FAILED.value,
                    }:
                        _unlink_if_regular(result_path)
                raise
        return self.get(canonical_id)

    def read_result(self, job_id: str | UUID) -> BuildResponse:
        record = self.get(job_id)
        if not record.result_available:
            raise JobConflictError("job result is not available")
        path = self._job_path(record.job_id) / RESULT_BLOB
        try:
            if path.is_symlink() or not path.is_file():
                raise OSError
            return BuildResponse.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError):
            raise JobRepositoryUnavailableError("job result storage is invalid") from None

    def create_retry(self, parent_job_id: str | UUID) -> BuildJobRecord:
        parent_id = _canonical_uuid(parent_job_id)
        with self._mutex:
            connection = self._require_open()
            parent = self.get(parent_id)
            if parent.state not in {JobState.FAILED, JobState.CANCELLED}:
                raise JobConflictError("job is not eligible for retry")
            if connection.execute(
                "SELECT 1 FROM jobs WHERE parent_job_id = ?", (str(parent_id),)
            ).fetchone():
                raise JobConflictError("a retry already exists for this job")
            identity, identity_bytes, options_bytes, source_path = self._load_owned_inputs(parent)
            child_id = self._new_job_id()
            if (
                connection.execute(
                    "SELECT 1 FROM jobs WHERE job_id = ?", (str(child_id),)
                ).fetchone()
                or self._job_path(child_id).exists()
            ):
                raise JobConflictError("could not allocate a unique retry job ID")
            now = self._now()
            child = _initial_record(
                child_id,
                now,
                attempt=parent.attempt + 1,
                parent_job_id=parent.job_id,
            )
            self._publish_new_job(child, identity_bytes, options_bytes, source_path, identity)
        return self.get(child_id)

    def delete_terminal(self, job_id: str | UUID) -> None:
        canonical_id = _canonical_uuid(job_id)
        tombstone = self._stage_path("delete", canonical_id)
        job_path = self._job_path(canonical_id)
        with self._mutex:
            self._require_open()
            record = self.get(canonical_id)
            if record.state not in TERMINAL_STATES:
                raise JobConflictError("active job cannot be deleted")
            if (
                self._require_open()
                .execute("SELECT 1 FROM jobs WHERE parent_job_id = ?", (str(canonical_id),))
                .fetchone()
            ):
                raise JobConflictError("job with a retry child cannot be deleted")
            if tombstone.exists():
                raise JobRepositoryUnavailableError("job deletion staging is invalid")
            os.replace(job_path, tombstone)
            committed = False
            try:
                with self._transaction() as connection:
                    deleted = connection.execute(
                        "DELETE FROM jobs WHERE job_id = ?", (str(canonical_id),)
                    ).rowcount
                    if deleted != 1:
                        raise JobNotFoundError("job was not found")
                committed = True
            finally:
                if committed:
                    _remove_owned_tree(tombstone, self.root / STAGING_DIRECTORY)
                elif tombstone.exists() and not job_path.exists():
                    os.replace(tombstone, job_path)

    def recover(self) -> None:
        with self._mutex:
            self._recover_owned_storage()

    def _finish(
        self,
        job_id: str | UUID,
        target: JobState,
        code: JobDiagnosticCode,
    ) -> BuildJobRecord:
        canonical_id = _canonical_uuid(job_id)
        with self._mutex, self._transaction() as connection:
            current = self._get_for_update(connection, canonical_id)
            updated = self._transition(current, target, diagnostic=code)
            self._update_record(connection, updated)
        return self.get(canonical_id)

    def _publish_new_job(
        self,
        record: BuildJobRecord,
        identity_bytes: bytes,
        options_bytes: bytes,
        source_pdf: Path,
        identity: DocumentIdentity,
    ) -> None:
        stage = self._stage_path("create", record.job_id)
        marker = self._marker_path("create", record.job_id)
        target = self._job_path(record.job_id)
        published = False
        committed = False
        try:
            stage.mkdir()
            _write_file_exclusive(stage / IDENTITY_BLOB, identity_bytes)
            _write_file_exclusive(stage / OPTIONS_BLOB, options_bytes)
            _copy_pdf_checked(source_pdf, stage / PDF_BLOB, identity.source_pdf_sha256)
            _write_file_exclusive(marker, b"1")
            os.replace(stage, target)
            published = True
            with self._transaction() as connection:
                connection.execute(
                    "INSERT INTO jobs(job_id, parent_job_id, attempt, state, created_at, record_json) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        str(record.job_id),
                        str(record.parent_job_id) if record.parent_job_id else None,
                        record.attempt,
                        record.state.value,
                        record.created_at.isoformat(),
                        _record_json(record),
                    ),
                )
            committed = True
            _unlink_if_regular(marker)
        except sqlite3.IntegrityError:
            if published and not committed:
                _remove_owned_tree(target, self.root / JOBS_DIRECTORY)
            elif not committed:
                _remove_owned_tree(stage, self.root / STAGING_DIRECTORY)
            if not committed:
                _unlink_if_regular(marker)
            raise JobConflictError("job creation conflicts with an existing record") from None
        except BaseException:
            if published and not committed:
                _remove_owned_tree(target, self.root / JOBS_DIRECTORY)
            elif not committed:
                _remove_owned_tree(stage, self.root / STAGING_DIRECTORY)
            if not committed:
                _unlink_if_regular(marker)
            raise

    def _recover_owned_storage(self) -> None:
        connection = self._require_open()
        staging = self.root / STAGING_DIRECTORY
        jobs = self.root / JOBS_DIRECTORY
        if staging.is_symlink() or jobs.is_symlink():
            raise JobRepositoryUnavailableError("job repository layout is invalid")
        rows = connection.execute("SELECT * FROM jobs").fetchall()
        records = {UUID(row["job_id"]): _load_record_row(row) for row in rows}
        self._recover_pending_markers(records)
        for entry in tuple(staging.iterdir()):
            if entry.is_symlink():
                raise JobRepositoryUnavailableError("job staging layout is invalid")
            parsed = _parse_stage_name(entry.name)
            if parsed is None:
                raise JobRepositoryUnavailableError("job staging layout is invalid")
            role, job_id = parsed
            if role == "delete" and job_id in records:
                target = self._job_path(job_id)
                if target.exists():
                    raise JobRepositoryUnavailableError("job deletion recovery is ambiguous")
                os.replace(entry, target)
            else:
                _remove_owned_entry(entry, staging)
        known_ids = set(records)
        for entry in jobs.iterdir():
            if entry.is_symlink() or not entry.is_dir():
                raise JobRepositoryUnavailableError("job directory layout is invalid")
            try:
                entry_id = UUID(entry.name)
            except ValueError:
                raise JobRepositoryUnavailableError("job directory layout is invalid") from None
            if str(entry_id) != entry.name or entry_id not in known_ids:
                raise JobRepositoryUnavailableError("job directory is not owned by a record")
        if {UUID(path.name) for path in jobs.iterdir()} != known_ids:
            raise JobRepositoryUnavailableError("job record storage is incomplete")
        for record in records.values():
            result_path = self._job_path(record.job_id) / RESULT_BLOB
            if record.state not in RESULT_STATES and result_path.exists():
                raise JobRepositoryUnavailableError("unowned job result is present")
            self._validate_job_storage(record)
        with self._transaction() as transaction:
            for record in records.values():
                if record.state == JobState.RUNNING:
                    updated = self._transition(
                        record,
                        JobState.FAILED,
                        diagnostic=JobDiagnosticCode.WORKER_INTERRUPTED,
                    )
                    self._update_record(transaction, updated)
                elif record.state == JobState.CANCEL_REQUESTED:
                    updated = self._transition(
                        record,
                        JobState.CANCELLED,
                        diagnostic=JobDiagnosticCode.CANCELLED_BY_REQUEST,
                    )
                    self._update_record(transaction, updated)

    def _validate_job_storage(self, record: BuildJobRecord) -> None:
        path = self._job_path(record.job_id)
        if path.is_symlink() or not path.is_dir():
            raise JobRepositoryUnavailableError("job storage is invalid")
        expected = {IDENTITY_BLOB, OPTIONS_BLOB, PDF_BLOB}
        if record.result_available:
            expected.add(RESULT_BLOB)
        try:
            entries = {item.name: item for item in path.iterdir()}
        except OSError:
            raise JobRepositoryUnavailableError("job storage is invalid") from None
        if set(entries) != expected or any(
            item.is_symlink() or not item.is_file() for item in entries.values()
        ):
            raise JobRepositoryUnavailableError("job storage layout is invalid")
        identity, _, _, _ = self._load_owned_inputs(record)
        if identity.source_pdf_sha256 != _sha256_file(entries[PDF_BLOB]):
            raise JobRepositoryUnavailableError("job source binding is invalid")
        if record.result_available:
            try:
                result = BuildResponse.model_validate_json(entries[RESULT_BLOB].read_bytes())
            except (OSError, ValidationError, ValueError):
                raise JobRepositoryUnavailableError("job result storage is invalid") from None
            expected_state = (
                JobState.SUCCEEDED if result.accepted_for_indexing else JobState.QUALITY_FAILED
            )
            if (
                record.state != expected_state
                or result.knowledge_base.manifest.identity != identity
                or result.knowledge_base.manifest.source_pdf != PDF_BLOB
            ):
                raise JobRepositoryUnavailableError("job result state is inconsistent")

    def _recover_pending_markers(self, records: dict[UUID, BuildJobRecord]) -> None:
        staging = self.root / STAGING_DIRECTORY
        for marker in tuple(staging.iterdir()):
            parsed = _parse_marker_name(marker.name)
            if parsed is None:
                continue
            try:
                valid_marker = (
                    not marker.is_symlink() and marker.is_file() and marker.read_bytes() == b"1"
                )
            except OSError:
                valid_marker = False
            if not valid_marker:
                raise JobRepositoryUnavailableError("job transaction marker is invalid")
            role, job_id = parsed
            stage = self._stage_path(role, job_id)
            job_path = self._job_path(job_id)
            record = records.get(job_id)
            if role == "create":
                if record is None:
                    _remove_owned_tree(job_path, self.root / JOBS_DIRECTORY)
                elif not job_path.is_dir():
                    raise JobRepositoryUnavailableError("committed job directory is missing")
                _remove_owned_entry_if_present(stage, staging)
            else:
                result_path = job_path / RESULT_BLOB
                if record is not None and record.state in RESULT_STATES:
                    if not result_path.exists() and stage.is_file():
                        os.replace(stage, result_path)
                    elif result_path.exists() and stage.exists():
                        raise JobRepositoryUnavailableError("result recovery is ambiguous")
                else:
                    _unlink_if_regular(result_path)
                    _remove_owned_entry_if_present(stage, staging)
            _unlink_if_regular(marker)

    def _load_owned_inputs(
        self, record: BuildJobRecord
    ) -> tuple[DocumentIdentity, bytes, bytes, Path]:
        path = self._job_path(record.job_id)
        identity_path = path / IDENTITY_BLOB
        options_path = path / OPTIONS_BLOB
        pdf_path = path / PDF_BLOB
        try:
            if any(
                item.is_symlink() or not item.is_file()
                for item in (identity_path, options_path, pdf_path)
            ):
                raise OSError
            identity_bytes = identity_path.read_bytes()
            options_bytes = options_path.read_bytes()
            identity = load_document_identity_bytes(identity_bytes)
            options = BuildOptions.model_validate_json(options_bytes)
            if identity_bytes != canonical_document_identity_bytes(
                identity
            ) or options_bytes != _canonical_json_bytes(options.model_dump(mode="json")):
                raise ValueError
        except (OSError, DocumentIdentityError, ValidationError, ValueError):
            raise JobRepositoryUnavailableError("job input storage is invalid") from None
        return identity, identity_bytes, options_bytes, pdf_path

    def _transition(
        self,
        current: BuildJobRecord,
        target: JobState,
        *,
        diagnostic: JobDiagnosticCode | None = None,
        result_available: bool = False,
    ) -> BuildJobRecord:
        if target not in LEGAL_TRANSITIONS[current.state]:
            raise JobConflictError("job transition is not legal from its current state")
        at = max(self._now(), current.updated_at)
        transition = JobTransition(
            sequence=len(current.transitions) + 1,
            from_state=current.state,
            to_state=target,
            phase=PHASE_BY_STATE[target],
            at=at,
            diagnostic_code=diagnostic,
        )
        data = current.model_dump(mode="python")
        data.update(
            state=target,
            phase=PHASE_BY_STATE[target],
            updated_at=at,
            diagnostic_code=diagnostic,
            result_available=result_available,
            result_blob=RESULT_BLOB if result_available else None,
            transitions=(*current.transitions, transition),
        )
        if target == JobState.RUNNING:
            data["started_at"] = at
        if target in TERMINAL_STATES:
            data["finished_at"] = at
        return BuildJobRecord.model_validate(data)

    def _get_for_update(self, connection: sqlite3.Connection, job_id: UUID) -> BuildJobRecord:
        row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (str(job_id),)).fetchone()
        if row is None:
            raise JobNotFoundError("job was not found")
        return _load_record_row(row)

    def _update_record(self, connection: sqlite3.Connection, record: BuildJobRecord) -> None:
        changed = connection.execute(
            "UPDATE jobs SET state = ?, record_json = ? WHERE job_id = ?",
            (record.state.value, _record_json(record), str(record.job_id)),
        ).rowcount
        if changed != 1:
            raise JobRepositoryUnavailableError("job record update failed")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._require_open()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    def _initialize_schema(self) -> None:
        connection = self._require_open()
        connection.execute(
            "CREATE TABLE IF NOT EXISTS repository_metadata "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS jobs ("
            "job_id TEXT PRIMARY KEY, parent_job_id TEXT UNIQUE, attempt INTEGER NOT NULL CHECK(attempt >= 1), "
            "state TEXT NOT NULL, created_at TEXT NOT NULL, record_json TEXT NOT NULL)"
        )
        row = connection.execute(
            "SELECT value FROM repository_metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            count = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            if count:
                raise JobRepositoryUnavailableError("job repository schema is incompatible")
            connection.execute(
                "INSERT INTO repository_metadata(key, value) VALUES ('schema_version', ?)",
                (JOB_SCHEMA_VERSION,),
            )
        elif row["value"] != JOB_SCHEMA_VERSION:
            raise JobRepositoryUnavailableError("job repository schema is incompatible")

    def _validate_root_layout(self) -> None:
        for entry in self.root.iterdir():
            if entry.name not in _ALLOWED_ROOT_NAMES or entry.is_symlink():
                raise JobRepositoryUnavailableError("job repository root layout is invalid")
            if entry.name in {JOBS_DIRECTORY, STAGING_DIRECTORY} and not entry.is_dir():
                raise JobRepositoryUnavailableError("job repository root layout is invalid")
            if entry.name not in {JOBS_DIRECTORY, STAGING_DIRECTORY} and not entry.is_file():
                raise JobRepositoryUnavailableError("job repository root layout is invalid")

    def _acquire_owner_lock(self) -> None:
        path = self.root / LOCK_NAME
        if path.is_symlink():
            raise JobRepositoryUnavailableError("job repository ownership is unavailable")
        handle = path.open("a+b")
        try:
            handle.seek(0)
            if handle.read(1) != b"1":
                handle.seek(0)
                handle.write(b"1")
                handle.flush()
            handle.seek(0)
            _lock_file(handle)
        except (OSError, BlockingIOError):
            handle.close()
            raise JobRepositoryUnavailableError(
                "job repository already has an active owner"
            ) from None
        self._lock_handle = handle

    def _require_open(self) -> sqlite3.Connection:
        if self._connection is None:
            raise JobRepositoryUnavailableError("job repository is not open")
        return self._connection

    def _job_path(self, job_id: UUID) -> Path:
        return self.root / JOBS_DIRECTORY / str(job_id)

    def _stage_path(self, role: str, job_id: UUID) -> Path:
        return self.root / STAGING_DIRECTORY / f"{role}-{job_id}"

    def _marker_path(self, role: str, job_id: UUID) -> Path:
        return self.root / STAGING_DIRECTORY / f"{role}-{job_id}.pending"

    def _new_job_id(self) -> UUID:
        try:
            value = self._id_factory()
        except Exception:
            raise JobRepositoryUnavailableError("job ID allocation failed") from None
        if not isinstance(value, UUID):
            raise JobValidationError("job ID factory returned an invalid value")
        return value

    def _now(self) -> datetime:
        try:
            value = self._clock()
        except Exception:
            raise JobRepositoryUnavailableError("job clock is unavailable") from None
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() != timezone.utc.utcoffset(value)
        ):
            raise JobRepositoryUnavailableError("job clock returned an invalid timestamp")
        return value


def _initial_record(
    job_id: UUID,
    at: datetime,
    *,
    attempt: int = 1,
    parent_job_id: UUID | None = None,
) -> BuildJobRecord:
    transition = JobTransition(
        sequence=1,
        from_state=None,
        to_state=JobState.QUEUED,
        phase=PHASE_BY_STATE[JobState.QUEUED],
        at=at,
    )
    return BuildJobRecord(
        job_id=job_id,
        state=JobState.QUEUED,
        phase=PHASE_BY_STATE[JobState.QUEUED],
        attempt=attempt,
        parent_job_id=parent_job_id,
        created_at=at,
        updated_at=at,
        result_available=False,
        transitions=(transition,),
    )


def _validate_inputs(
    identity_bytes: bytes, options_bytes: bytes, source_pdf: str | Path
) -> tuple[DocumentIdentity, bytes, bytes]:
    try:
        identity = load_document_identity_bytes(identity_bytes)
        options = BuildOptions.model_validate_json(options_bytes)
        source = Path(source_pdf)
        if source.is_symlink() or not source.is_file() or source.resolve(strict=True) != source:
            raise OSError
        if _sha256_file(source) != identity.source_pdf_sha256:
            raise ValueError
        return (
            identity,
            canonical_document_identity_bytes(identity),
            _canonical_json_bytes(options.model_dump(mode="json")),
        )
    except (DocumentIdentityError, OSError, TypeError, ValidationError, ValueError):
        raise JobValidationError("job inputs are invalid or source binding failed") from None


def _copy_pdf_checked(source: Path, target: Path, expected_hash: str) -> None:
    digest = hashlib.sha256()
    try:
        with source.open("rb") as reader, target.open("xb") as writer:
            while chunk := reader.read(64 * 1024):
                digest.update(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
    except OSError:
        raise JobRepositoryUnavailableError("job input publication failed") from None
    if digest.hexdigest() != expected_hash:
        _unlink_if_regular(target)
        raise JobValidationError("job source changed during publication")


def _write_file_exclusive(path: Path, raw: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        raise JobRepositoryUnavailableError("job blob publication failed") from None


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _record_json(record: BuildJobRecord) -> str:
    return _canonical_json_bytes(record.model_dump(mode="json")).decode("utf-8")


def _load_record(raw: str) -> BuildJobRecord:
    try:
        return BuildJobRecord.model_validate_json(raw)
    except (ValidationError, ValueError):
        raise JobRepositoryUnavailableError("job record is invalid") from None


def _load_record_row(row: sqlite3.Row) -> BuildJobRecord:
    record = _load_record(row["record_json"])
    expected = (
        str(record.job_id),
        str(record.parent_job_id) if record.parent_job_id else None,
        record.attempt,
        record.state.value,
        record.created_at.isoformat(),
    )
    observed = (
        row["job_id"],
        row["parent_job_id"],
        row["attempt"],
        row["state"],
        row["created_at"],
    )
    if observed != expected:
        raise JobRepositoryUnavailableError("job database columns are inconsistent")
    return record


def _detach(record: BuildJobRecord) -> BuildJobRecord:
    return BuildJobRecord.model_validate(record.model_dump(mode="json"))


def _canonical_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise JobValidationError("job ID is invalid") from None
    if str(parsed) != value:
        raise JobValidationError("job ID is invalid")
    return parsed


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(64 * 1024):
                digest.update(chunk)
    except OSError:
        raise JobRepositoryUnavailableError("job source is unavailable") from None
    return digest.hexdigest()


def _parse_stage_name(name: str) -> tuple[str, UUID] | None:
    for role in ("create", "result", "delete"):
        prefix = f"{role}-"
        if name.startswith(prefix):
            try:
                value = UUID(name[len(prefix) :])
            except ValueError:
                return None
            return (role, value) if name == f"{role}-{value}" else None
    return None


def _parse_marker_name(name: str) -> tuple[str, UUID] | None:
    if not name.endswith(".pending"):
        return None
    base = name.removesuffix(".pending")
    parsed = _parse_stage_name(base)
    if parsed is None or parsed[0] not in {"create", "result"}:
        return None
    return parsed


def _unlink_if_regular(path: Path) -> None:
    try:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise JobRepositoryUnavailableError("owned job staging is invalid")
        path.unlink(missing_ok=True)
    except OSError:
        raise JobRepositoryUnavailableError("owned job staging cleanup failed") from None


def _remove_owned_entry_if_present(path: Path, parent: Path) -> None:
    if path.exists() or path.is_symlink():
        _remove_owned_entry(path, parent)


def _remove_owned_entry(path: Path, parent: Path) -> None:
    if path.parent != parent or path.is_symlink():
        raise JobRepositoryUnavailableError("owned job staging is invalid")
    if path.is_dir():
        _remove_owned_tree(path, parent)
    elif path.is_file():
        _unlink_if_regular(path)
    else:
        raise JobRepositoryUnavailableError("owned job staging is invalid")


def _remove_owned_tree(path: Path, parent: Path) -> None:
    if path.parent != parent or path.is_symlink():
        raise JobRepositoryUnavailableError("owned job directory is invalid")
    try:
        if path.exists():
            shutil.rmtree(path)
    except OSError:
        raise JobRepositoryUnavailableError("owned job directory cleanup failed") from None


def _lock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: BinaryIO) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


__all__ = [
    "BuildJobRepository",
    "JobConflictError",
    "JobNotFoundError",
    "JobRepositoryError",
    "JobRepositoryUnavailableError",
    "JobValidationError",
    "OwnedJobInputs",
]
