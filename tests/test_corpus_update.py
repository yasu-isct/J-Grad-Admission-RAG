from __future__ import annotations

import json
from pathlib import Path

import pytest

import jgrad_admission_rag.corpus as corpus_module
from jgrad_admission_rag.cli import update_corpus as update_corpus_cli
from jgrad_admission_rag.corpus import (
    CorpusCommitStateError,
    CorpusConcurrentUpdateError,
    CorpusPublicationError,
    CorpusRegistration,
    CorpusUpdateValidationError,
    build_corpus_manifest,
    update_corpus_manifest,
)
from jgrad_admission_rag.retrieval.embedding import DeterministicFakeEmbeddingProvider
from jgrad_admission_rag.retrieval.local_index import build_local_index
from jgrad_admission_rag.schemas.corpus_manifest import (
    canonical_corpus_manifest_bytes,
    load_corpus_manifest,
)
from tests.test_corpus_manifest import _identity, _write_kb


def _write_manifest(
    root: Path,
    registrations: tuple[CorpusRegistration, ...],
    *,
    name: str = "corpus.json",
) -> Path:
    manifest = build_corpus_manifest("graduate-admissions", root, registrations)
    path = root / name
    path.write_bytes(canonical_corpus_manifest_bytes(manifest))
    return path


def _basic_add_corpus(root: Path) -> tuple[Path, CorpusRegistration]:
    _write_kb(
        root,
        "current/document_kb.json",
        _identity("current-2027", family="current", institution="current-u"),
    )
    manifest_path = _write_manifest(root, (CorpusRegistration("current/document_kb.json"),))
    _write_kb(
        root,
        "candidate/document_kb.json",
        _identity("candidate-2027", family="candidate", institution="candidate-u"),
    )
    return manifest_path, CorpusRegistration("candidate/document_kb.json")


def test_add_publishes_canonical_manifest_and_is_fail_closed_on_repeat(tmp_path: Path) -> None:
    manifest_path, candidate = _basic_add_corpus(tmp_path)
    before = load_corpus_manifest(manifest_path)
    untouched = before.entries[0]

    result = update_corpus_manifest(
        tmp_path,
        manifest_path,
        action="add",
        candidate=candidate,
    )

    updated = load_corpus_manifest(manifest_path)
    assert result.action == "add"
    assert result.old_document_id is None
    assert result.candidate_document_id == "candidate-2027"
    assert result.document_count == 2
    assert result.candidate_index_state == "not_indexed"
    assert updated.entries[1] == untouched
    assert manifest_path.read_bytes() == canonical_corpus_manifest_bytes(updated)
    with pytest.raises(CorpusUpdateValidationError, match="already present"):
        update_corpus_manifest(tmp_path, manifest_path, action="add", candidate=candidate)


def test_add_preserves_two_editions_without_active_selection(tmp_path: Path) -> None:
    _write_kb(
        tmp_path,
        "2027/kb.json",
        _identity("sample-2027", family="sample", edition="2027", institution="sample-u"),
    )
    manifest_path = _write_manifest(tmp_path, (CorpusRegistration("2027/kb.json"),))
    _write_kb(
        tmp_path,
        "2028/kb.json",
        _identity("sample-2028", family="sample", edition="2028", institution="sample-u"),
    )

    update_corpus_manifest(
        tmp_path,
        manifest_path,
        action="add",
        candidate=CorpusRegistration("2028/kb.json"),
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [entry["identity"]["edition_id"] for entry in payload["entries"]] == ["2027", "2028"]
    assert "active" not in manifest_path.read_text(encoding="utf-8")


def test_replace_accepts_same_identity_index_upgrade(tmp_path: Path) -> None:
    identity = _identity("sample-2027", family="sample", institution="sample-u")
    kb_path = _write_kb(tmp_path, "sample/kb.json", identity)
    manifest_path = _write_manifest(tmp_path, (CorpusRegistration("sample/kb.json"),))
    build_local_index(
        kb_path, tmp_path / "indexes" / "sample", DeterministicFakeEmbeddingProvider(4)
    )

    result = update_corpus_manifest(
        tmp_path,
        manifest_path,
        action="replace",
        replace_document_id="sample-2027",
        candidate=CorpusRegistration("sample/kb.json", "indexes/sample"),
    )

    assert result.old_document_id == result.candidate_document_id == "sample-2027"
    assert result.candidate_index_state == "ready"
    assert load_corpus_manifest(manifest_path).entries[0].index_state == "ready"
    with pytest.raises(CorpusUpdateValidationError, match="already the active registration"):
        update_corpus_manifest(
            tmp_path,
            manifest_path,
            action="replace",
            replace_document_id="sample-2027",
            candidate=CorpusRegistration("sample/kb.json", "indexes/sample"),
        )


def test_replace_accepts_reviewed_successor_and_rejects_repeat_or_cross_family(
    tmp_path: Path,
) -> None:
    _write_kb(
        tmp_path,
        "old/kb.json",
        _identity("sample-2027", family="sample", edition="2027", institution="sample-u"),
    )
    manifest_path = _write_manifest(tmp_path, (CorpusRegistration("old/kb.json"),))
    _write_kb(
        tmp_path,
        "new/kb.json",
        _identity("sample-2028", family="sample", edition="2028", institution="sample-u"),
    )
    candidate = CorpusRegistration("new/kb.json")

    update_corpus_manifest(
        tmp_path,
        manifest_path,
        action="replace",
        replace_document_id="sample-2027",
        candidate=candidate,
    )

    assert load_corpus_manifest(manifest_path).entries[0].identity.document_id == "sample-2028"
    with pytest.raises(CorpusUpdateValidationError, match="absent"):
        update_corpus_manifest(
            tmp_path,
            manifest_path,
            action="replace",
            replace_document_id="sample-2027",
            candidate=candidate,
        )

    _write_kb(
        tmp_path,
        "other/kb.json",
        _identity("other-2029", family="other", edition="2029", institution="other-u"),
    )
    with pytest.raises(CorpusUpdateValidationError, match="retain institution"):
        update_corpus_manifest(
            tmp_path,
            manifest_path,
            action="replace",
            replace_document_id="sample-2028",
            candidate=CorpusRegistration("other/kb.json"),
        )


def test_same_document_replacement_requires_complete_identity_match(tmp_path: Path) -> None:
    original = _identity("sample", family="sample", institution="sample-u")
    _write_kb(tmp_path, "old/kb.json", original)
    manifest_path = _write_manifest(tmp_path, (CorpusRegistration("old/kb.json"),))
    changed = _identity("sample", family="different", institution="sample-u")
    _write_kb(tmp_path, "changed/kb.json", changed)

    with pytest.raises(CorpusUpdateValidationError, match="complete identity"):
        update_corpus_manifest(
            tmp_path,
            manifest_path,
            action="replace",
            replace_document_id="sample",
            candidate=CorpusRegistration("changed/kb.json"),
        )


@pytest.mark.parametrize(
    ("action", "replacement"),
    [("invalid", None), ("add", "extra"), ("replace", None), ("replace", "")],
)
def test_request_validation_rejects_invalid_action_combinations(
    tmp_path: Path, action: str, replacement: str | None
) -> None:
    manifest_path, candidate = _basic_add_corpus(tmp_path)
    original = manifest_path.read_bytes()
    with pytest.raises(CorpusUpdateValidationError):
        update_corpus_manifest(
            tmp_path,
            manifest_path,
            action=action,  # type: ignore[arg-type]
            replace_document_id=replacement,
            candidate=candidate,
        )
    assert manifest_path.read_bytes() == original


def test_noncanonical_or_stale_current_manifest_is_rejected_without_publication(
    tmp_path: Path,
) -> None:
    manifest_path, candidate = _basic_add_corpus(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    noncanonical = manifest_path.read_bytes()
    with pytest.raises(CorpusUpdateValidationError, match="current corpus"):
        update_corpus_manifest(tmp_path, manifest_path, action="add", candidate=candidate)
    assert manifest_path.read_bytes() == noncanonical

    manifest_path.write_bytes(
        canonical_corpus_manifest_bytes(
            build_corpus_manifest(
                "graduate-admissions", tmp_path, (CorpusRegistration("current/document_kb.json"),)
            )
        )
    )
    current_kb = tmp_path / "current" / "document_kb.json"
    current_kb.write_bytes(current_kb.read_bytes() + b" ")
    stale = manifest_path.read_bytes()
    with pytest.raises(CorpusUpdateValidationError, match="current corpus"):
        update_corpus_manifest(tmp_path, manifest_path, action="add", candidate=candidate)
    assert manifest_path.read_bytes() == stale


@pytest.mark.parametrize("indexed", [False, True])
def test_legacy_candidate_preserves_explicit_migration_guidance(
    tmp_path: Path, indexed: bool
) -> None:
    manifest_path, _ = _basic_add_corpus(tmp_path)
    identity = _identity("legacy-candidate")
    legacy_path = _write_kb(tmp_path, "legacy/kb.json", identity)
    index_relative = None
    if indexed:
        index_relative = "indexes/legacy"
        build_local_index(
            legacy_path,
            tmp_path / "indexes" / "legacy",
            DeterministicFakeEmbeddingProvider(4),
        )
    payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    payload["manifest"]["schema_version"] = "0.5"
    payload["manifest"]["document_id"] = identity.document_id
    payload["manifest"]["pdf_sha256"] = identity.source_pdf_sha256
    del payload["manifest"]["identity"]
    legacy_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CorpusUpdateValidationError, match="explicit migration"):
        update_corpus_manifest(
            tmp_path,
            manifest_path,
            action="add",
            candidate=CorpusRegistration("legacy/kb.json", index_relative),
        )


@pytest.mark.parametrize(
    "phase",
    ["after_stage_write", "after_stage_validation", "before_atomic_replace"],
)
def test_precommit_failures_preserve_original_and_clean_owned_stage(
    tmp_path: Path, phase: str
) -> None:
    manifest_path, candidate = _basic_add_corpus(tmp_path)
    original = manifest_path.read_bytes()

    def fail(selected: str, _: Path) -> None:
        if selected == phase:
            raise RuntimeError("injected")

    with pytest.raises(CorpusPublicationError):
        update_corpus_manifest(
            tmp_path,
            manifest_path,
            action="add",
            candidate=candidate,
            _failure_hook=fail,
        )

    assert manifest_path.read_bytes() == original
    assert list(tmp_path.glob(".corpus.json.tmp-*.json")) == []


def test_staged_corruption_fails_before_commit(tmp_path: Path) -> None:
    manifest_path, candidate = _basic_add_corpus(tmp_path)
    original = manifest_path.read_bytes()

    def corrupt(phase: str, path: Path) -> None:
        if phase == "after_stage_write":
            path.write_text("{}", encoding="utf-8")

    with pytest.raises(CorpusPublicationError):
        update_corpus_manifest(
            tmp_path,
            manifest_path,
            action="add",
            candidate=candidate,
            _failure_hook=corrupt,
        )
    assert manifest_path.read_bytes() == original


def test_staging_creation_failure_preserves_original(tmp_path: Path, monkeypatch) -> None:
    manifest_path, candidate = _basic_add_corpus(tmp_path)
    original = manifest_path.read_bytes()

    def fail_stage(*args, **kwargs):
        raise OSError("injected")

    monkeypatch.setattr(corpus_module.tempfile, "mkstemp", fail_stage)
    with pytest.raises(CorpusPublicationError, match="staging failed"):
        update_corpus_manifest(tmp_path, manifest_path, action="add", candidate=candidate)
    assert manifest_path.read_bytes() == original


def test_compare_and_swap_does_not_overwrite_another_writer(tmp_path: Path) -> None:
    manifest_path, candidate = _basic_add_corpus(tmp_path)
    other_writer_bytes = b'{"other_writer":true}\n'

    def change_current(phase: str, _: Path) -> None:
        if phase == "before_precommit_compare":
            manifest_path.write_bytes(other_writer_bytes)

    with pytest.raises(CorpusConcurrentUpdateError):
        update_corpus_manifest(
            tmp_path,
            manifest_path,
            action="add",
            candidate=candidate,
            _failure_hook=change_current,
        )
    assert manifest_path.read_bytes() == other_writer_bytes
    assert list(tmp_path.glob(".corpus.json.tmp-*.json")) == []


def test_atomic_replace_failure_preserves_original(tmp_path: Path, monkeypatch) -> None:
    manifest_path, candidate = _basic_add_corpus(tmp_path)
    original = manifest_path.read_bytes()

    def fail_replace(_: Path, __: Path) -> None:
        raise OSError("injected")

    monkeypatch.setattr(corpus_module.os, "replace", fail_replace)
    with pytest.raises(CorpusPublicationError):
        update_corpus_manifest(tmp_path, manifest_path, action="add", candidate=candidate)
    assert manifest_path.read_bytes() == original
    assert list(tmp_path.glob(".corpus.json.tmp-*.json")) == []


def test_postcommit_failure_reports_uncertain_state_without_rollback(tmp_path: Path) -> None:
    manifest_path, candidate = _basic_add_corpus(tmp_path)
    original = manifest_path.read_bytes()

    def fail_after_commit(phase: str, _: Path) -> None:
        if phase == "after_atomic_replace":
            raise RuntimeError("injected")

    with pytest.raises(CorpusCommitStateError):
        update_corpus_manifest(
            tmp_path,
            manifest_path,
            action="add",
            candidate=candidate,
            _failure_hook=fail_after_commit,
        )
    assert manifest_path.read_bytes() != original
    assert load_corpus_manifest(manifest_path).document_count == 2


def test_unrelated_ready_index_is_never_modified_or_deleted(tmp_path: Path) -> None:
    identity = _identity("current", family="current", institution="current-u")
    kb_path = _write_kb(tmp_path, "current/kb.json", identity)
    index_path = tmp_path / "indexes" / "current"
    build_local_index(kb_path, index_path, DeterministicFakeEmbeddingProvider(4))
    manifest_path = _write_manifest(
        tmp_path,
        (CorpusRegistration("current/kb.json", "indexes/current"),),
    )
    protected_paths = (kb_path, *tuple(index_path.iterdir()))
    snapshots = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in protected_paths}
    _write_kb(tmp_path, "candidate/kb.json", _identity("candidate"))

    update_corpus_manifest(
        tmp_path,
        manifest_path,
        action="add",
        candidate=CorpusRegistration("candidate/kb.json"),
    )

    assert all(
        (path.read_bytes(), path.stat().st_mtime_ns) == snapshot
        for path, snapshot in snapshots.items()
    )
    assert index_path.is_dir()


def test_cli_emits_one_success_object_and_typed_validation_error(tmp_path: Path, capsys) -> None:
    manifest_path, _ = _basic_add_corpus(tmp_path)
    args = [
        str(manifest_path),
        "--corpus-root",
        str(tmp_path),
        "--action",
        "add",
        "--kb",
        "candidate/document_kb.json",
    ]
    update_corpus_cli.main(args)
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["candidate_document_id"] == "candidate-2027"

    with pytest.raises(SystemExit) as exit_info:
        update_corpus_cli.main(args)
    assert exit_info.value.code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["kind"] == "validation_error"
    assert str(tmp_path) not in error["error"]


@pytest.mark.parametrize(
    ("error", "kind", "exit_code"),
    [
        (CorpusConcurrentUpdateError("changed"), "concurrent_update_error", 3),
        (CorpusPublicationError("failed"), "publication_error", 4),
        (CorpusCommitStateError("uncertain"), "commit_state_error", 5),
    ],
)
def test_cli_distinguishes_operational_failure_classes(
    tmp_path: Path, capsys, monkeypatch, error: Exception, kind: str, exit_code: int
) -> None:
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(update_corpus_cli, "update_corpus_manifest", fail)
    with pytest.raises(SystemExit) as exit_info:
        update_corpus_cli.main(
            [
                str(tmp_path / "corpus.json"),
                "--corpus-root",
                str(tmp_path),
                "--action",
                "add",
                "--kb",
                "candidate/kb.json",
            ]
        )
    assert exit_info.value.code == exit_code
    assert json.loads(capsys.readouterr().err)["kind"] == kind


def test_cli_argument_errors_are_one_privacy_safe_json_object(capsys) -> None:
    planted = "SECRET_LOCAL_PATH"
    with pytest.raises(SystemExit) as exit_info:
        update_corpus_cli.main([planted])
    assert exit_info.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {
        "error": "invalid command arguments",
        "kind": "argument_error",
    }
    assert planted not in output.err
