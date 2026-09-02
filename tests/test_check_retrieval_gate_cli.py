from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from jgrad_admission_rag.cli import check_retrieval_gate as cli
from jgrad_admission_rag.evaluation.semantic_gate import (
    SemanticGateManifest,
    canonical_semantic_gate_manifest_bytes,
    implementation_contract,
)

ROOT = Path(__file__).parents[1]
REPORT = ROOT / "tests" / "fixtures" / "semantic_retrieval_baseline_v1.json"
POLICY = ROOT / "config" / "semantic_retrieval_gate_v1.json"
GLOBS = (
    "pyproject.toml",
    "src/jgrad_admission_rag/cli/*.py",
    "src/jgrad_admission_rag/evaluation/*.py",
    "src/jgrad_admission_rag/retrieval/*.py",
    "src/jgrad_admission_rag/schemas/*.py",
    "tests/fixtures/retrieval_queries_v1.json",
)


def _manifest() -> bytes:
    paths, implementation_sha256 = implementation_contract(ROOT, GLOBS)
    return canonical_semantic_gate_manifest_bytes(
        SemanticGateManifest(
            policy_sha256=hashlib.sha256(POLICY.read_bytes()).hexdigest(),
            report_sha256=hashlib.sha256(REPORT.read_bytes()).hexdigest(),
            implementation_globs=GLOBS,
            implementation_paths=paths,
            implementation_sha256=implementation_sha256,
        )
    )


def _args(manifest: Path) -> list[str]:
    return [
        "--report",
        str(REPORT),
        "--policy",
        str(POLICY),
        "--manifest",
        str(manifest),
        "--repository-root",
        str(ROOT),
    ]


def test_cli_emits_a_canonical_passing_result(tmp_path: Path, capsys) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(_manifest())

    with pytest.raises(SystemExit) as captured_exit:
        cli.main(_args(manifest))

    assert captured_exit.value.code == 0
    assert capsys.readouterr().err == ""


def test_cli_rejects_noncanonical_policy_before_evaluating(tmp_path: Path, capsys) -> None:
    manifest = tmp_path / "manifest.json"
    policy = tmp_path / "policy.json"
    manifest.write_bytes(_manifest())
    policy.write_bytes(POLICY.read_bytes() + b" ")
    args = _args(manifest)
    args[args.index(str(POLICY))] = str(policy)

    with pytest.raises(SystemExit) as captured_exit:
        cli.main(args)

    captured = capsys.readouterr()
    assert captured_exit.value.code == 2
    assert captured.out == ""
    assert '"kind":"semantic_gate_error"' in captured.err


def test_cli_returns_one_for_a_valid_baseline_hash_regression(tmp_path: Path, capsys) -> None:
    manifest = tmp_path / "manifest.json"
    report = tmp_path / "report.json"
    manifest.write_bytes(_manifest())
    report.write_bytes(REPORT.read_bytes() + b" ")
    args = _args(manifest)
    args[args.index(str(REPORT))] = str(report)

    with pytest.raises(SystemExit) as captured_exit:
        cli.main(args)

    assert captured_exit.value.code == 1
    assert capsys.readouterr().err == ""


def test_cli_rejects_noncanonical_manifest_before_evaluating(tmp_path: Path, capsys) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(_manifest() + b" ")

    with pytest.raises(SystemExit) as captured_exit:
        cli.main(_args(manifest))

    assert captured_exit.value.code == 2
    assert '"kind":"semantic_gate_error"' in capsys.readouterr().err
