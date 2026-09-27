from __future__ import annotations

from pathlib import Path

import pytest

from jgrad_admission_rag.demo import prepare_demo
from jgrad_admission_rag.operations.artifact_inventory import (
    ArtifactRequest,
    inventory_artifacts,
    main,
)
from tests.test_demo_cli import _synthetic_config


def test_inventory_inspects_only_explicit_paths_and_marks_exact_duplicates(tmp_path: Path) -> None:
    pdf, config, identity = _synthetic_config(tmp_path)
    workspace = (tmp_path / "workspace").resolve()
    runtime = prepare_demo(pdf, workspace, config_dir=config)
    index_path = runtime.runtime_root / "indexes" / identity.document_id
    missing = (tmp_path / "missing").resolve()

    records = inventory_artifacts(
        (
            ArtifactRequest("production", workspace),
            ArtifactRequest("candidate-duplicate", index_path),
            ArtifactRequest("historical", missing),
        )
    )

    assert records[0]["accessibility"] == "ready"
    assert records[0]["artifact_kind"] == "demo-runtime"
    assert records[0]["identity"]["payload_count"] == runtime.payload_count
    assert records[0]["artifact_identity"] == records[1]["artifact_identity"]
    assert records[0]["duplicate_candidate"] is True
    assert records[1]["duplicate_candidate"] is True
    assert records[2]["accessibility"] == "missing"
    assert records[2]["duplicate_candidate"] is False
    assert not missing.exists()


def test_inventory_cli_prints_json_without_mutating_runtime(capsys, tmp_path: Path) -> None:
    pdf, config, _ = _synthetic_config(tmp_path)
    workspace = (tmp_path / "workspace").resolve()
    prepare_demo(pdf, workspace, config_dir=config)
    before = {
        path.relative_to(workspace): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in workspace.rglob("*")
        if path.is_file()
    }

    main(["--artifact", f"production={workspace}"])

    output = capsys.readouterr().out
    assert '"accessibility": "ready"' in output
    assert '"role": "production"' in output
    after = {
        path.relative_to(workspace): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_inventory_cli_rejects_relative_paths() -> None:
    with pytest.raises(SystemExit):
        main(["--artifact", "historical=outputs/index"])
