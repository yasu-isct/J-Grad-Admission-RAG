from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import shutil
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

import fitz
import pytest

from jgrad_admission_rag.builder.kb_builder import DocumentBuildError, build_document_kb
from jgrad_admission_rag.demo import DemoError, load_demo_config, prepare_demo
from jgrad_admission_rag.reasoning.query_intent import canonical_query_intent_catalog_bytes
from jgrad_admission_rag.reasoning.applicability import RuleScope
from jgrad_admission_rag.reasoning.reviewed_report_plan import (
    canonical_reviewed_report_plan_bytes,
)
from jgrad_admission_rag.schemas.document_identity import (
    DocumentIdentity,
    canonical_document_identity_bytes,
)
from jgrad_admission_rag.schemas.document_kb import canonical_document_kb_bytes
from jgrad_admission_rag.schemas.page_scope_manifest import (
    PageScopeCategory,
    PageScopeEntry,
    PageScopeManifest,
    canonical_page_scope_manifest_bytes,
)
from jgrad_admission_rag.service.date_presentation import (
    ReviewedDateEvent,
    ReviewedDatePresentation,
    ReviewedEvidenceHighlight,
    canonical_reviewed_date_presentation_bytes,
)
from tests.test_reviewed_report_evidence import _plan, _rule


def _synthetic_config(root: Path) -> tuple[Path, Path, DocumentIdentity]:
    pdf = root / "synthetic-reviewed.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "1. Eligibility\nApplicants must be at least 18 years old at enrollment.",
    )
    document.save(pdf)
    document.close()
    pdf_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    identity = DocumentIdentity(
        document_id="synthetic-demo-2027",
        document_family_id="synthetic-demo",
        edition_id="2027-april",
        institution_id="synthetic-u",
        institution_name="Synthetic University",
        degree_levels=("master",),
        intake_terms=({"year": 2027, "month": 4},),
        official_title="Synthetic reviewed admission guidelines",
        official_source_url="https://example.edu/admissions/guidelines.pdf",
        source_pdf_sha256=pdf_hash,
    )
    kb = build_document_kb(
        pdf,
        identity,
        source_pdf_label=f"{identity.document_id}.pdf",
    )
    assert kb.diagnostics.quality_gate.passed
    kb_hash = hashlib.sha256(canonical_document_kb_bytes(kb)).hexdigest()
    fact = kb.facts[0]
    rule = _rule(
        identity,
        kb_hash,
        fact.text,
        fact_id=fact.fact_id,
        pages=tuple(fact.source_pages),
        scope=RuleScope(
            scope_type="department",
            scope_targets=("Synthetic Department",),
            parent_college="Synthetic College",
        ),
    )
    plan = _plan(identity, kb_hash, fact.text, rules=(rule,))
    page_scope = PageScopeManifest(
        manifest_id="synthetic-demo-page-scope-v1",
        document_identity=identity,
        page_count=1,
        entries=(
            PageScopeEntry(
                pages=(1,),
                category=PageScopeCategory.CORE_ADMISSION,
                review_note="Reviewed synthetic demo scope.",
            ),
        ),
    )
    config = root / "config"
    config.mkdir()
    product = load_demo_config()
    (config / "document_identity.json").write_bytes(canonical_document_identity_bytes(identity))
    (config / "reviewed_report_plan.json").write_bytes(canonical_reviewed_report_plan_bytes(plan))
    (config / "page_scope_manifest.json").write_bytes(
        canonical_page_scope_manifest_bytes(page_scope)
    )
    (config / "query_intent_catalog.json").write_bytes(
        canonical_query_intent_catalog_bytes(product.query_intent)
    )
    event_id = "date:synthetic:registration-open"
    highlight_id = "highlight:synthetic:registration-open"
    date_presentation = ReviewedDatePresentation(
        presentation_id="synthetic-demo-key-dates-v1",
        document_id=identity.document_id,
        source_pdf_sha256=identity.source_pdf_sha256,
        events=(
            ReviewedDateEvent(
                event_id=event_id,
                intake_year=2027,
                intake_month=4,
                event_type="registration_open",
                label="Registration opens",
                display_text="2026年6月1日 09:00 起（JST）",
                start_date="2026-06-01",
                start_time="09:00:00",
                timezone="Asia/Tokyo",
                nature="opens",
                precision="minute",
                unknown_fields=("end_date", "end_time"),
                uncertainty_note="Registration close is not specified.",
                highlight_ids=(highlight_id,),
            ),
        ),
        highlights=(
            ReviewedEvidenceHighlight(
                highlight_id=highlight_id,
                fact_id=fact.fact_id,
                start=0,
                end=len(fact.text),
                exact_text=fact.text,
                claim_ids=(event_id,),
            ),
        ),
    )
    (config / "reviewed_date_presentation.json").write_bytes(
        canonical_reviewed_date_presentation_bytes(date_presentation)
    )
    return pdf.resolve(), config.resolve(), identity


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_json(url: str, process: subprocess.Popen[str]) -> dict:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"service exited early\nstdout={stdout}\nstderr={stderr}")
        try:
            with urlopen(url, timeout=1) as response:  # noqa: S310 - fixed loopback URL
                return json.loads(response.read())
        except (OSError, URLError):
            time.sleep(0.1)
    raise AssertionError("formal demo service did not become ready")


def test_demo_builds_and_reuses_a_fully_audited_workspace(tmp_path: Path) -> None:
    pdf, config, identity = _synthetic_config(tmp_path)
    workspace = (tmp_path / "workspace").resolve()

    built = prepare_demo(pdf, workspace, config_dir=config)
    reused = prepare_demo(pdf, workspace, config_dir=config)

    assert built.reused is False
    assert reused.reused is True
    assert reused.identity == identity
    assert reused.report_plan_path.is_relative_to(workspace)
    assert str(pdf) not in reused.report_plan_path.read_text(encoding="utf-8")
    assert (
        json.loads(
            (
                reused.corpus_root / "documents" / identity.document_id / "document_kb.json"
            ).read_text(encoding="utf-8")
        )["manifest"]["source_pdf"]
        == f"{identity.document_id}.pdf"
    )


def test_demo_rejects_bad_pdf_before_creating_workspace(tmp_path: Path) -> None:
    pdf, config, _ = _synthetic_config(tmp_path)
    pdf.write_bytes(pdf.read_bytes() + b"tampered")
    workspace = (tmp_path / "must-not-exist").resolve()

    with pytest.raises(DemoError, match="PDF version mismatch"):
        prepare_demo(pdf, workspace, config_dir=config)

    assert not workspace.exists()


def test_demo_rejects_relative_pdf_and_unsafe_source_label(tmp_path: Path) -> None:
    pdf, config, identity = _synthetic_config(tmp_path)
    workspace = (tmp_path / "must-not-exist").resolve()

    with pytest.raises(DemoError, match="absolute path"):
        prepare_demo(Path(pdf.name), workspace, config_dir=config)
    with pytest.raises(DocumentBuildError):
        build_document_kb(pdf, identity, source_pdf_label="../source.pdf")

    assert not workspace.exists()


def test_demo_rejects_corrupt_reuse_and_recovers_only_with_rebuild(
    monkeypatch, tmp_path: Path
) -> None:
    from jgrad_admission_rag import demo

    pdf, config, _ = _synthetic_config(tmp_path)
    workspace = (tmp_path / "workspace").resolve()
    built = prepare_demo(pdf, workspace, config_dir=config)
    built.manifest_path.write_text("{}", encoding="utf-8")

    with pytest.raises(DemoError, match="--rebuild"):
        prepare_demo(pdf, workspace, config_dir=config)

    monkeypatch.setattr(
        demo,
        "_build_runtime",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DemoError("build failed")),
    )
    with pytest.raises(DemoError, match="build failed"):
        prepare_demo(pdf, workspace, rebuild=True, config_dir=config)
    assert built.runtime_root.is_dir()
    assert built.manifest_path.read_text(encoding="utf-8") == "{}"

    monkeypatch.undo()
    rebuilt = prepare_demo(pdf, workspace, rebuild=True, config_dir=config)
    assert rebuilt.reused is False


def test_rebuild_refuses_an_unowned_runtime_directory(tmp_path: Path) -> None:
    pdf, config, _ = _synthetic_config(tmp_path)
    workspace = (tmp_path / "workspace").resolve()
    runtime = workspace / "runtime-v1"
    runtime.mkdir(parents=True)
    user_file = runtime / "user-file.txt"
    user_file.write_text("keep me", encoding="utf-8")

    with pytest.raises(DemoError, match="cannot be rebuilt safely"):
        prepare_demo(pdf, workspace, rebuild=True, config_dir=config)

    assert user_file.read_text(encoding="utf-8") == "keep me"


def test_workspace_probe_preserves_a_preexisting_similar_file(tmp_path: Path) -> None:
    pdf, config, _ = _synthetic_config(tmp_path)
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()
    user_file = workspace / ".jgrad-demo-write-probe"
    user_file.write_text("keep me", encoding="utf-8")

    prepare_demo(pdf, workspace, config_dir=config)

    assert user_file.read_text(encoding="utf-8") == "keep me"


def test_installed_console_entry_point_is_available() -> None:
    executable = shutil.which("jgrad-demo")
    if executable is None:
        script_name = "jgrad-demo.exe" if os.name == "nt" else "jgrad-demo"
        sibling = Path(sys.executable).with_name(script_name)
        executable = str(sibling) if sibling.is_file() else None
    assert executable is not None, "install the package before running its test suite"
    result = subprocess.run(
        [executable, "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert "--pdf ABSOLUTE_PATH" in result.stdout


def test_formal_cli_process_serves_real_http_without_a_test_handler(tmp_path: Path) -> None:
    pdf, config, identity = _synthetic_config(tmp_path)
    workspace = (tmp_path / "workspace").resolve()
    port = _free_port()
    command = [
        sys.executable,
        "-m",
        "tests.demo_cli_harness",
        "--config-dir",
        str(config),
        "--pdf",
        str(pdf),
        "--workspace",
        str(workspace),
        "--port",
        str(port),
    ]
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    process = subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready = _wait_json(f"http://127.0.0.1:{port}/v1/health/ready", process)
        assert ready == {"schema_version": "1.0", "status": "ready", "ready": True}
        with urlopen(  # noqa: S310 - fixed loopback URL
            f"http://127.0.0.1:{port}/v1/target-catalog", timeout=2
        ) as response:
            catalog = json.loads(response.read())
        with urlopen(f"http://127.0.0.1:{port}/app", timeout=2) as response:  # noqa: S310
            app_html = response.read().decode("utf-8")
        source_url = f"http://127.0.0.1:{port}/documents/{identity.document_id}/source.pdf"
        with urlopen(source_url, timeout=2) as response:  # noqa: S310 - loopback URL
            served_pdf = response.read()
            assert response.headers["Content-Type"] == "application/pdf"
            assert response.headers["Accept-Ranges"] == "bytes"
        range_request = Request(source_url, headers={"Range": "bytes=0-15"})
        with urlopen(range_request, timeout=2) as response:  # noqa: S310 - loopback URL
            assert response.status == 206
            assert response.read() == pdf.read_bytes()[:16]
            assert response.headers["Content-Range"].startswith("bytes 0-15/")
        assert catalog["schools"][0]["school_id"] == identity.institution_id
        assert "STEP 1" in app_html
        assert served_pdf == pdf.read_bytes()
        assert hashlib.sha256(served_pdf).hexdigest() == identity.source_pdf_sha256
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_cli_fails_actionably_when_port_is_occupied(tmp_path: Path) -> None:
    pdf, config, _ = _synthetic_config(tmp_path)
    workspace = (tmp_path / "unused-workspace").resolve()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        port = int(occupied.getsockname()[1])
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.demo_cli_harness",
                "--config-dir",
                str(config),
                "--pdf",
                str(pdf),
                "--workspace",
                str(workspace),
                "--port",
                str(port),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    assert result.returncode == 2
    assert "already in use" in result.stderr
    assert not workspace.exists()


def test_workspace_must_be_an_absolute_writable_directory(tmp_path: Path) -> None:
    pdf, config, _ = _synthetic_config(tmp_path)
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("occupied", encoding="utf-8")

    with pytest.raises(DemoError, match="absolute writable directory"):
        prepare_demo(pdf, not_a_directory.resolve(), config_dir=config)


def test_cli_reports_clean_interrupt(monkeypatch, capsys, tmp_path: Path) -> None:
    from jgrad_admission_rag import demo_cli

    pdf, config, _ = _synthetic_config(tmp_path)
    workspace = (tmp_path / "workspace").resolve()
    monkeypatch.setattr(demo_cli, "_require_available_port", lambda _port: None)
    monkeypatch.setattr(
        demo_cli, "_serve", lambda _runtime, _port: (_ for _ in ()).throw(KeyboardInterrupt)
    )

    demo_cli.main(
        [
            "--pdf",
            str(pdf),
            "--workspace",
            str(workspace),
        ],
        config_dir=config,
    )

    assert "J-Grad Demo stopped." in capsys.readouterr().out


def test_cli_reports_missing_service_extra_without_a_traceback(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    from jgrad_admission_rag import demo_cli

    monkeypatch.setattr(demo_cli.importlib.util, "find_spec", lambda _name: None)
    with pytest.raises(SystemExit) as exc_info:
        demo_cli.main(["--pdf", str((tmp_path / "missing.pdf").resolve())])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "install -e" in captured.err
    assert "Traceback" not in captured.err
