from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import fitz
import pytest

from jgrad_admission_rag.parsing.mineru_pilot import (
    ComparisonPage,
    RunLimits,
    adapt_raw_result,
    cancel_worker,
    sha256_file,
    supervise_worker,
)


def _pdf(path: Path, pages: int = 2) -> Path:
    document = fitz.open()
    for number in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), f"page {number + 1}")
    document.save(path)
    return path


def _raw(pages: list[int] | None = None, *, full: bool = True) -> dict:
    return {
        "schema": "docvortex.middle",
        "schema_version": "2.0",
        "is_full_document": full,
        "pages": [
            {
                "page_idx": index,
                "blocks": [{"index": 0, "type": "text", "bbox": [1, 2, 3, 4], "content": "ok"}],
            }
            for index in (pages if pages is not None else [0, 1])
        ],
    }


def test_adapts_zero_based_pages_once_and_preserves_source_identity(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "source.pdf")
    view = adapt_raw_result(
        _raw(),
        source_id="locked",
        source_pdf=pdf,
        expected_source_sha256=sha256_file(pdf),
        tier="flash",
    )
    assert [page.physical_page for page in view.pages] == [1, 2]
    assert view.source_pdf_sha256


def test_rejects_wrong_source_identity_at_call_boundary(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "source.pdf")
    with pytest.raises(ValueError, match="locked run identity"):
        adapt_raw_result(
            _raw(),
            source_id="locked",
            source_pdf=pdf,
            expected_source_sha256="0" * 64,
            tier="flash",
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda raw: raw.update(schema_version="9"), "schema"),
        (lambda raw: raw.update(is_full_document=False), "full document"),
        (lambda raw: raw.update(pages=[raw["pages"][0]]), "complete"),
        (lambda raw: raw.update(pages=[raw["pages"][0], raw["pages"][0]]), "complete"),
    ],
)
def test_rejects_schema_fullness_missing_and_duplicate_pages(
    tmp_path: Path, mutation, message: str
) -> None:
    pdf = _pdf(tmp_path / "source.pdf")
    raw = _raw()
    mutation(raw)
    with pytest.raises(ValueError, match=message):
        adapt_raw_result(
            raw,
            source_id="locked",
            source_pdf=pdf,
            expected_source_sha256=sha256_file(pdf),
            tier="basic",
        )


def test_rejects_double_page_conversion() -> None:
    with pytest.raises(ValueError, match="exactly once"):
        ComparisonPage(mineru_page_idx=0, physical_page=2, blocks=[], text="")


def test_unknown_bbox_is_explicit(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "source.pdf")
    raw = _raw()
    raw["pages"][0]["blocks"][0].pop("bbox")
    view = adapt_raw_result(
        raw,
        source_id="locked",
        source_pdf=pdf,
        expected_source_sha256=sha256_file(pdf),
        tier="flash",
    )
    assert view.pages[0].blocks[0].bbox is None
    assert view.pages[0].blocks[0].bbox_status == "unknown"


def test_supervisor_timeout_kills_worker_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_process = lambda pid: SimpleNamespace(  # noqa: E731
        memory_info=lambda: SimpleNamespace(rss=0), children=lambda recursive: []
    )
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(
            Process=fake_process,
            virtual_memory=lambda: SimpleNamespace(available=16 * 1024**3),
        ),
    )
    monkeypatch.setattr(
        "jgrad_admission_rag.parsing.mineru_pilot._terminate_tree", lambda process: process.kill()
    )
    with pytest.raises(RuntimeError, match="timeout"):
        supervise_worker(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            environment=dict(__import__("os").environ),
            report_path=tmp_path / "timeout.json",
            limits=RunLimits(timeout_seconds=0.1, poll_seconds=0.02),
        )
    assert json.loads((tmp_path / "timeout.json").read_text())["stop_reason"] == "timeout"


def test_worker_refuses_output_conflict(tmp_path: Path) -> None:
    occupied = tmp_path / "raw.json"
    occupied.write_text("owned")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "jgrad_admission_rag.parsing.mineru_worker",
            "--source-id",
            "x",
            "--pdf",
            str(tmp_path / "missing.pdf"),
            "--tier",
            "flash",
            "--raw",
            str(occupied),
            "--markdown",
            str(tmp_path / "m.md"),
            "--network-audit",
            str(tmp_path / "n.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert occupied.read_text() == "owned"


def test_cancel_stops_worker() -> None:
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], creationflags=creationflags
    )
    cancel_worker(process)
    assert process.poll() is not None


def test_contract_is_separate_from_ms02() -> None:
    from jgrad_admission_rag.parsing import contracts

    assert (
        "mineru-pilot-comparison-view"
        not in contracts.NormalizedDocument.model_json_schema().__repr__()
    )
