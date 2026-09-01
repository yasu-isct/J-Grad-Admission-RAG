import argparse
import json
import sys
from pathlib import Path

import pytest

from jgrad_admission_rag.cli import build_kb as build_kb_cli
from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    QualityGateResult,
    QualityGateViolation,
)


def _knowledge_base(*, passed: bool) -> DocumentKnowledgeBase:
    violations = []
    if not passed:
        violations = [
            QualityGateViolation(
                metric="unknown_scope_facts",
                actual=1,
                limit=0,
                related_ids=["fact:00001"],
            )
        ]
    return DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            document_id="sample",
            source_pdf="sample.pdf",
            pdf_sha256="abc",
            chunk_count=0,
        ),
        diagnostics=BuildDiagnostics(
            unknown_scope_fact_ids=["fact:00001"] if not passed else [],
            quality_gate=QualityGateResult(passed=passed, violations=violations),
        ),
    )


def test_cli_prints_concise_summary_for_passing_build(monkeypatch, tmp_path: Path, capsys) -> None:
    output = tmp_path / "passing.json"
    monkeypatch.setattr(
        build_kb_cli, "build_document_kb", lambda *_args, **_kwargs: _knowledge_base(passed=True)
    )
    monkeypatch.setattr(sys, "argv", ["jgrad-build-kb", "sample.pdf", "--output", str(output)])

    build_kb_cli.main()

    summary = json.loads(capsys.readouterr().out)
    assert output.is_file()
    assert summary["schema_version"] == "0.5"
    assert summary["quality_gate_passed"] is True
    assert "reference_claims" not in summary


def test_cli_writes_failed_artifact_and_exits_two(monkeypatch, tmp_path: Path, capsys) -> None:
    output = tmp_path / "failed.json"
    monkeypatch.setattr(
        build_kb_cli, "build_document_kb", lambda *_args, **_kwargs: _knowledge_base(passed=False)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jgrad-build-kb",
            "sample.pdf",
            "--output",
            str(output),
            "--max-unknown-scope-facts",
            "0",
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        build_kb_cli.main()

    summary = json.loads(capsys.readouterr().out)
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert exit_info.value.code == 2
    assert summary["quality_gate_passed"] is False
    assert summary["quality_gate_violations"] == [
        {
            "metric": "unknown_scope_facts",
            "actual": 1,
            "limit": 0,
            "related_id_count": 1,
            "related_claim_count": 0,
        }
    ]
    assert artifact["diagnostics"]["quality_gate"]["passed"] is False


def test_cli_threshold_parser_supports_disabled_and_rejects_negative() -> None:
    assert build_kb_cli._optional_non_negative_int("none") is None
    assert build_kb_cli._optional_non_negative_int("0") == 0
    with pytest.raises(argparse.ArgumentTypeError, match="non-negative"):
        build_kb_cli._optional_non_negative_int("-1")
