from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.schemas.document_identity import canonical_document_identity_bytes
from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    QualityGateResult,
)
from jgrad_admission_rag.service.contracts import BuildResponse, BuildSummary
from jgrad_admission_rag.service.jobs import (
    BuildJobRecord,
    BuildJobRepository,
    JobConflictError,
    JobNotFoundError,
    JobRepositoryUnavailableError,
    JobState,
    JobValidationError,
)
from jgrad_admission_rag.service.jobs.contracts import canonical_job_record_bytes
from tests.identity_helpers import make_document_identity

NOW = datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc)
JOB_IDS = tuple(UUID(f"00000000-0000-4000-8000-{value:012d}") for value in range(1, 20))


def _inputs(tmp_path: Path) -> tuple[bytes, bytes, Path]:
    pdf = tmp_path / "incoming.pdf"
    pdf.write_bytes(b"%PDF-1.7\nsynthetic repository input\n%%EOF")
    identity = make_document_identity(pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())
    return canonical_document_identity_bytes(identity), b"{}", pdf


def _repository(root: Path, ids=JOB_IDS) -> BuildJobRepository:
    iterator = iter(ids)
    return BuildJobRepository(root.resolve(), clock=lambda: NOW, id_factory=lambda: next(iterator))


def _result(identity_bytes: bytes, *, accepted: bool = True) -> BuildResponse:
    identity = json.loads(identity_bytes)
    diagnostics = BuildDiagnostics(quality_gate=QualityGateResult(passed=accepted))
    kb = DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            identity=identity,
            source_pdf="source.pdf",
            chunk_count=0,
        ),
        diagnostics=diagnostics,
    )
    summary = BuildSummary(
        document_id=kb.manifest.document_id,
        kb_schema_version=kb.manifest.schema_version,
        chunks=0,
        facts=0,
        retrieval_units=0,
        dropped_chunks=0,
        dropped_chunk_reasons={},
        missing_source_pages=0,
        missing_section_paths=0,
        empty_or_noninformative=0,
        short_facts=0,
        unknown_scopes=0,
        max_chunk_chars=0,
        oversized_facts=0,
        reference_links=0,
        reference_status_counts={"resolved": 0, "ambiguous": 0, "unresolved": 0},
        quality_gate_passed=accepted,
        quality_gate_violations=(),
    )
    return BuildResponse(
        status="quality_passed" if accepted else "quality_failed",
        accepted_for_indexing=accepted,
        knowledge_base=kb,
        summary=summary,
    )


def test_construction_has_no_filesystem_side_effect(tmp_path: Path) -> None:
    root = (tmp_path / "jobs").resolve()
    repository = BuildJobRepository(root)

    assert not root.exists()
    assert repository.is_open is False


def test_models_are_strict_canonical_and_detached(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    with _repository(root) as repository:
        record = repository.create(identity, options, pdf)

    assert canonical_job_record_bytes(record).endswith(b"\n")
    payload = record.model_dump(mode="json")
    payload["job_id"] = "{" + str(record.job_id) + "}"
    with pytest.raises(ValidationError):
        BuildJobRecord.model_validate(payload)


@pytest.mark.parametrize(
    "changes",
    (
        {"attempt": 2},
        {"parent_job_id": str(JOB_IDS[1])},
        {"phase": "finished"},
        {"result_available": True, "result_blob": "result.json"},
        {"state": "unknown"},
        {"diagnostic_code": "raw_exception"},
        {"finished_at": NOW.isoformat()},
    ),
)
def test_job_record_impossible_states_fail_closed(tmp_path: Path, changes: dict) -> None:
    identity, options, pdf = _inputs(tmp_path)
    with _repository((tmp_path / "store").resolve()) as repository:
        record = repository.create(identity, options, pdf)
    payload = record.model_dump(mode="json")
    payload.update(changes)

    with pytest.raises(ValidationError):
        BuildJobRecord.model_validate(payload)
    payload = record.model_dump(mode="json")
    payload["unknown"] = "secret"
    with pytest.raises(ValidationError):
        BuildJobRecord.model_validate(payload)


def test_atomic_create_is_discoverable_after_reopen_and_sanitizes_names(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    first = _repository(root)
    record = first.open().create(identity, options, pdf)
    first.close()

    with BuildJobRepository(root).open() as reopened:
        loaded = reopened.get(record.job_id)
        assert reopened.list() == (loaded,)
        owned_inputs = reopened.read_inputs(record.job_id)
        assert (
            owned_inputs.identity.source_pdf_sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest()
        )
        assert owned_inputs.options.max_chars == 6000
        assert owned_inputs.source_pdf == root / "jobs" / str(record.job_id) / "source.pdf"

    job_files = {path.name for path in (root / "jobs" / str(record.job_id)).iterdir()}
    assert job_files == {"identity.json", "options.json", "source.pdf"}
    durable_text = (root / "jobs.sqlite3").read_bytes()
    assert pdf.name.encode() not in durable_text
    assert str(pdf).encode() not in durable_text
    assert not any((root / ".staging").iterdir())


@pytest.mark.parametrize("failure", ("hash", "identity", "options", "symlink"))
def test_failed_create_leaves_no_job_or_staging(tmp_path: Path, failure: str) -> None:
    identity, options, pdf = _inputs(tmp_path)
    if failure == "hash":
        pdf.write_bytes(pdf.read_bytes() + b"changed")
    elif failure == "identity":
        identity = b'{"secret":"document text"}'
    elif failure == "options":
        options = b'{"unknown":"secret"}'
    elif failure == "symlink":
        link = tmp_path / "linked.pdf"
        try:
            link.symlink_to(pdf)
        except OSError:
            pytest.skip("symlink creation is unavailable")
        pdf = link
    root = (tmp_path / "store").resolve()
    with _repository(root) as repository:
        with pytest.raises(JobValidationError) as captured:
            repository.create(identity, options, pdf)
        assert repository.list() == ()
        assert not any((root / "jobs").iterdir())
        assert not any((root / ".staging").iterdir())
    assert "secret" not in str(captured.value)
    assert str(tmp_path) not in str(captured.value)


def test_id_collision_retries_then_fails_without_residue(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    with _repository(root, ids=(JOB_IDS[0],) * 4) as repository:
        repository.create(identity, options, pdf)
        with pytest.raises(JobConflictError):
            repository.create(identity, options, pdf)
        assert len(repository.list()) == 1
        assert not any((root / ".staging").iterdir())


@pytest.mark.parametrize("hook", ("id", "clock"))
def test_failing_injected_hooks_do_not_disclose_exception_text(tmp_path: Path, hook: str) -> None:
    identity, options, pdf = _inputs(tmp_path)

    def fail():
        raise RuntimeError("planted secret path and document text")

    kwargs = {"id_factory": fail} if hook == "id" else {"clock": fail}
    with BuildJobRepository((tmp_path / "store").resolve(), **kwargs).open() as repository:
        with pytest.raises(JobRepositoryUnavailableError) as captured:
            repository.create(identity, options, pdf)
    assert "planted secret" not in str(captured.value)


def test_concurrent_claim_has_exactly_one_winner(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    with _repository((tmp_path / "store").resolve()) as repository:
        queued = repository.create(identity, options, pdf)
        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed = list(pool.map(lambda _: repository.claim_next_queued(), range(2)))

        winners = [item for item in claimed if item is not None]
        assert len(winners) == 1
        assert winners[0].job_id == queued.job_id
        assert repository.get(queued.job_id).state == JobState.RUNNING


def test_cancel_and_terminal_states_are_immutable(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    with _repository((tmp_path / "store").resolve()) as repository:
        queued = repository.create(identity, options, pdf)
        cancelled = repository.request_cancel(queued.job_id)
        assert cancelled.state == JobState.CANCELLED
        assert cancelled.started_at is None
        with pytest.raises(JobConflictError):
            repository.request_cancel(queued.job_id)

        running = repository.create(identity, options, pdf)
        assert repository.claim_next_queued().job_id == running.job_id
        requested = repository.request_cancel(running.job_id)
        assert requested.state == JobState.CANCEL_REQUESTED
        assert repository.request_cancel(running.job_id) == requested
        finished = repository.finish_cancelled(running.job_id)
        assert finished.state == JobState.CANCELLED
        with pytest.raises(JobConflictError):
            repository.finish_failed(running.job_id)


@pytest.mark.parametrize("accepted", (True, False))
def test_result_publication_is_atomic_consistent_and_single_use(
    tmp_path: Path, accepted: bool
) -> None:
    identity, options, pdf = _inputs(tmp_path)
    with _repository((tmp_path / "store").resolve()) as repository:
        queued = repository.create(identity, options, pdf)
        repository.claim_next_queued()
        result = _result(identity, accepted=accepted)
        terminal = repository.publish_result(queued.job_id, result)

        assert terminal.state == (JobState.SUCCEEDED if accepted else JobState.QUALITY_FAILED)
        assert terminal.result_available is True
        assert repository.read_result(queued.job_id) == result
        with pytest.raises(JobConflictError):
            repository.publish_result(queued.job_id, result)


def test_result_cannot_be_read_or_published_in_wrong_state(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    with _repository((tmp_path / "store").resolve()) as repository:
        queued = repository.create(identity, options, pdf)
        with pytest.raises(JobConflictError):
            repository.read_result(queued.job_id)
        with pytest.raises(JobConflictError):
            repository.publish_result(queued.job_id, _result(identity))
        assert not (repository.root / "jobs" / str(queued.job_id) / "result.json").exists()


def test_result_must_match_reviewed_job_identity_without_partial_visibility(
    tmp_path: Path,
) -> None:
    identity, options, pdf = _inputs(tmp_path)
    wrong_identity = make_document_identity(
        document_id="other-document",
        pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
    )
    result = _result(canonical_document_identity_bytes(wrong_identity))
    with _repository((tmp_path / "store").resolve()) as repository:
        job = repository.create(identity, options, pdf)
        repository.claim_next_queued()
        with pytest.raises(JobValidationError):
            repository.publish_result(job.job_id, result)

        assert repository.get(job.job_id).state == JobState.RUNNING
        assert not (repository.root / "jobs" / str(job.job_id) / "result.json").exists()
        assert not any((repository.root / ".staging").iterdir())


def test_concurrent_result_publication_has_one_winner(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    with _repository((tmp_path / "store").resolve()) as repository:
        job = repository.create(identity, options, pdf)
        repository.claim_next_queued()
        result = _result(identity)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(repository.publish_result, job.job_id, result) for _ in range(2)]
        winners = []
        conflicts = []
        for future in futures:
            try:
                winners.append(future.result())
            except JobConflictError as error:
                conflicts.append(error)

        assert len(winners) == len(conflicts) == 1
        assert repository.get(job.job_id).state == JobState.SUCCEEDED
        assert repository.read_result(job.job_id) == result


def test_cancel_and_result_race_never_loses_terminal_consistency(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    with _repository((tmp_path / "store").resolve()) as repository:
        job = repository.create(identity, options, pdf)
        repository.claim_next_queued()
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancel = pool.submit(repository.request_cancel, job.job_id)
            publish = pool.submit(repository.publish_result, job.job_id, _result(identity))
        outcomes = []
        for future in (cancel, publish):
            try:
                outcomes.append(future.result())
            except JobConflictError:
                pass

        final = repository.get(job.job_id)
        assert len(outcomes) == 1
        assert final.state in {JobState.CANCEL_REQUESTED, JobState.SUCCEEDED}
        assert final.result_available == (final.state == JobState.SUCCEEDED)
        assert (repository.root / "jobs" / str(job.job_id) / "result.json").exists() == (
            final.state == JobState.SUCCEEDED
        )


def test_restart_recovery_handles_queued_running_cancel_requested_and_terminal(
    tmp_path: Path,
) -> None:
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    repository = _repository(root)
    repository.open()
    running = repository.create(identity, options, pdf)
    repository.claim_next_queued()
    cancelling = repository.create(identity, options, pdf)
    repository.claim_next_queued()
    repository.request_cancel(cancelling.job_id)
    terminal = repository.create(identity, options, pdf)
    repository.claim_next_queued()
    repository.finish_failed(terminal.job_id)
    queued = repository.create(identity, options, pdf)
    repository.close()

    with BuildJobRepository(root).open() as recovered:
        assert recovered.get(running.job_id).state == JobState.FAILED
        assert recovered.get(running.job_id).diagnostic_code == "worker_interrupted"
        assert recovered.get(cancelling.job_id).state == JobState.CANCELLED
        assert recovered.get(queued.job_id).state == JobState.QUEUED
        assert recovered.get(terminal.job_id).state == JobState.FAILED


def test_recovery_cleans_uncommitted_staging_and_restores_delete_tombstone(
    tmp_path: Path,
) -> None:
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    repository = _repository(root).open()
    record = repository.create(identity, options, pdf)
    repository.close()
    staging = root / ".staging"
    abandoned = staging / f"create-{JOB_IDS[10]}"
    abandoned.mkdir()
    (abandoned / "partial").write_text("secret", encoding="utf-8")
    job_path = root / "jobs" / str(record.job_id)
    tombstone = staging / f"delete-{record.job_id}"
    job_path.rename(tombstone)

    with BuildJobRepository(root).open() as recovered:
        assert recovered.get(record.job_id).state == JobState.QUEUED
        assert job_path.is_dir()
        assert not abandoned.exists()
        assert not tombstone.exists()


def test_recovery_uses_pending_marker_to_clean_uncommitted_result(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    repository = _repository(root).open()
    record = repository.create(identity, options, pdf)
    repository.close()
    job_path = root / "jobs" / str(record.job_id)
    (job_path / "result.json").write_bytes(b"partial private result")
    marker = root / ".staging" / f"result-{record.job_id}.pending"
    marker.write_bytes(b"1")

    with BuildJobRepository(root).open() as recovered:
        assert recovered.get(record.job_id).state == JobState.QUEUED
        assert not (job_path / "result.json").exists()
        assert not marker.exists()


def test_recovery_removes_marked_uncommitted_created_directory(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    repository = _repository(root).open()
    record = repository.create(identity, options, pdf)
    repository.close()
    with sqlite3.connect(root / "jobs.sqlite3") as connection:
        connection.execute("DELETE FROM jobs WHERE job_id = ?", (str(record.job_id),))
    marker = root / ".staging" / f"create-{record.job_id}.pending"
    marker.write_bytes(b"1")

    with BuildJobRepository(root).open() as recovered:
        assert recovered.list() == ()
    assert not (root / "jobs" / str(record.job_id)).exists()
    assert not marker.exists()


def test_unmarked_result_in_nonterminal_job_fails_closed(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    repository = _repository(root).open()
    record = repository.create(identity, options, pdf)
    repository.close()
    (root / "jobs" / str(record.job_id) / "result.json").write_bytes(b"foreign")

    with pytest.raises(JobRepositoryUnavailableError):
        BuildJobRepository(root).open()


def test_retry_is_atomic_single_and_preserves_attempt_linkage(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    with _repository((tmp_path / "store").resolve()) as repository:
        parent = repository.create(identity, options, pdf)
        repository.claim_next_queued()
        parent = repository.finish_failed(parent.job_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(repository.create_retry, parent.job_id) for _ in range(2)]
        results = []
        errors = []
        for future in futures:
            try:
                results.append(future.result())
            except JobConflictError as error:
                errors.append(error)

        assert len(results) == len(errors) == 1
        child = results[0]
        assert child.parent_job_id == parent.job_id
        assert child.attempt == 2
        assert child.state == JobState.QUEUED
        with pytest.raises(JobConflictError):
            repository.delete_terminal(parent.job_id)


def test_retry_rejects_ineligible_parent_and_missing_inputs(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    with _repository((tmp_path / "store").resolve()) as repository:
        queued = repository.create(identity, options, pdf)
        with pytest.raises(JobConflictError):
            repository.create_retry(queued.job_id)
        repository.claim_next_queued()
        failed = repository.finish_failed(queued.job_id)
        (repository.root / "jobs" / str(failed.job_id) / "source.pdf").unlink()
        with pytest.raises(JobRepositoryUnavailableError):
            repository.create_retry(failed.job_id)


def test_exact_terminal_deletion_preserves_sibling_and_external_sentinels(
    tmp_path: Path,
) -> None:
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    external = tmp_path / "corpus-sentinel"
    external.write_text("keep", encoding="utf-8")
    with _repository(root) as repository:
        deleted = repository.create(identity, options, pdf)
        repository.request_cancel(deleted.job_id)
        sibling = repository.create(identity, options, pdf)
        with pytest.raises(JobConflictError):
            repository.delete_terminal(sibling.job_id)
        repository.delete_terminal(deleted.job_id)
        with pytest.raises(JobNotFoundError):
            repository.get(deleted.job_id)
        assert repository.get(sibling.job_id).state == JobState.QUEUED
        with pytest.raises(JobNotFoundError):
            repository.delete_terminal(deleted.job_id)
    assert external.read_text(encoding="utf-8") == "keep"


def test_concurrent_exact_deletion_removes_only_once(tmp_path: Path) -> None:
    identity, options, pdf = _inputs(tmp_path)
    with _repository((tmp_path / "store").resolve()) as repository:
        terminal = repository.create(identity, options, pdf)
        repository.request_cancel(terminal.job_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(repository.delete_terminal, terminal.job_id) for _ in range(2)]
        successes = 0
        missing = 0
        for future in futures:
            try:
                future.result()
                successes += 1
            except JobNotFoundError:
                missing += 1
        assert (successes, missing) == (1, 1)
        assert not (repository.root / "jobs" / str(terminal.job_id)).exists()


def test_second_owner_is_rejected_and_clean_reopen_succeeds(tmp_path: Path) -> None:
    root = (tmp_path / "store").resolve()
    first = BuildJobRepository(root).open()
    second = BuildJobRepository(root)
    with pytest.raises(JobRepositoryUnavailableError):
        second.open()
    first.close()
    second.open().close()


@pytest.mark.parametrize("corruption", ("foreign", "database", "database_columns", "job_symlink"))
def test_corrupt_or_foreign_layout_fails_closed(tmp_path: Path, corruption: str) -> None:
    identity, options, pdf = _inputs(tmp_path)
    root = (tmp_path / "store").resolve()
    repository = _repository(root).open()
    record = repository.create(identity, options, pdf)
    repository.close()
    if corruption == "foreign":
        (root / "secret.txt").write_text("private", encoding="utf-8")
    elif corruption == "database":
        (root / "jobs.sqlite3").write_bytes(b"not sqlite")
    elif corruption == "database_columns":
        with sqlite3.connect(root / "jobs.sqlite3") as connection:
            connection.execute(
                "UPDATE jobs SET state = 'running' WHERE job_id = ?", (str(record.job_id),)
            )
    else:
        job_path = root / "jobs" / str(record.job_id)
        backup = tmp_path / "job-backup"
        job_path.rename(backup)
        try:
            job_path.symlink_to(backup, target_is_directory=True)
        except OSError:
            pytest.skip("directory symlink creation is unavailable")

    with pytest.raises(JobRepositoryUnavailableError) as captured:
        BuildJobRepository(root).open()
    assert "private" not in str(captured.value)
    assert str(root) not in str(captured.value)


def test_noncanonical_root_and_job_ids_cannot_traverse(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        BuildJobRepository(tmp_path / "child" / ".." / "store")
    root = (tmp_path / "store").resolve()
    with BuildJobRepository(root).open() as repository:
        with pytest.raises(JobValidationError):
            repository.get("../secret")
