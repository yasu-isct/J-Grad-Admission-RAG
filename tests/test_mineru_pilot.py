from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from jgrad_admission_rag.parsing.mineru_pilot import (
    ComparisonPage,
    RunLimits,
    adapt_raw_result,
    cancel_worker,
    sha256_file,
    sha256_json,
    supervise_worker,
    validate_execution_evidence,
)


def _pdf(path: Path, pages: int = 2) -> Path:
    document = fitz.open()
    for number in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), f"page {number + 1}")
    document.save(path)
    document.close()
    return path


def _raw(pages: list[int] | None = None, *, full: bool = True, page_count: int = 2) -> dict:
    return {
        "schema": "docvortex.middle",
        "schema_version": "2.0",
        "is_full_document": full,
        "metadata": {
            "producer": {"name": "mineru", "version": "4.0.7"},
            "document": {"page_count": page_count},
        },
        "extensions": {"mineru": {"tier": "flash", "parse_mode": "txt"}},
        "pages": [
            {
                "page_idx": index,
                "blocks": [{"index": 0, "type": "text", "bbox": [1, 2, 3, 4], "content": "ok"}],
            }
            for index in (pages if pages is not None else [0, 1])
        ],
    }


def _adapt(raw: dict, pdf: Path, *, tier: str = "flash", **overrides):
    raw["extensions"]["mineru"]["tier"] = tier
    provider = "native-text/no-onnx-session" if tier == "flash" else "CPUExecutionProvider"
    runtime = {
        "mineru_version": "4.0.7",
        "tier": tier,
        "parse_mode": "txt",
        "actual_provider": provider,
        "onnxruntime_available_providers": ["CPUExecutionProvider"] if tier == "basic" else [],
    }
    arguments = {
        "source_id": "locked",
        "source_pdf": pdf,
        "expected_source_sha256": sha256_file(pdf),
        "raw_result_sha256": sha256_json(raw),
        "runtime_audit": runtime,
        "runtime_audit_sha256": sha256_json(runtime),
        "execution_lock_sha256": "1" * 64,
        "environment_evidence_sha256": "2" * 64,
        "config_sha256": "3" * 64,
        "model_revision": "4" * 40,
        "run_repetition": 1,
        "tier": tier,
    }
    arguments.update(overrides)
    return adapt_raw_result(raw, **arguments)


def test_adapts_pages_once_and_binds_every_identifier_to_run(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "source.pdf")
    view = _adapt(_raw(), pdf)
    assert [page.physical_page for page in view.pages] == [1, 2]
    assert all(page.source_id == "locked" for page in view.pages)
    assert all(page.run_id == view.run_id for page in view.pages)
    assert view.pages[0].blocks[0].block_id == f"{view.run_id}:p00001:b00000"
    assert view.pages[0].blocks[0].raw_pointer == "/pages/0/blocks/0"


def test_run_identity_changes_with_raw_or_lock(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "source.pdf")
    first = _adapt(_raw(), pdf)
    changed_raw = _adapt(_raw(), pdf, raw_result_sha256="a" * 64)
    changed_lock = _adapt(_raw(), pdf, execution_lock_sha256="b" * 64)
    changed_repetition = _adapt(_raw(), pdf, run_repetition=2)
    assert (
        len({first.run_id, changed_raw.run_id, changed_lock.run_id, changed_repetition.run_id}) == 4
    )


def test_rejects_wrong_source_identity_at_call_boundary(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "source.pdf")
    with pytest.raises(ValueError, match="locked run identity"):
        _adapt(_raw(), pdf, expected_source_sha256="0" * 64)


def test_duplicate_block_identity_is_rejected(tmp_path: Path) -> None:
    raw = _raw()
    raw["pages"][0]["blocks"].append(dict(raw["pages"][0]["blocks"][0]))
    with pytest.raises(ValueError, match="duplicate MinerU block index"):
        _adapt(raw, _pdf(tmp_path / "source.pdf"))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda raw: raw.update(schema_version="9"), "schema"),
        (lambda raw: raw.update(is_full_document=False), "full document"),
        (lambda raw: raw.update(pages=[raw["pages"][0]]), "complete"),
        (lambda raw: raw.update(pages=[raw["pages"][0], raw["pages"][0]]), "complete"),
        (lambda raw: raw["metadata"]["producer"].update(version="9"), "producer"),
        (lambda raw: raw["metadata"]["document"].update(page_count=1), "page count"),
    ],
)
def test_rejects_invalid_raw_contract(tmp_path: Path, mutation, message: str) -> None:
    pdf = _pdf(tmp_path / "source.pdf")
    raw = _raw()
    mutation(raw)
    with pytest.raises(ValueError, match=message):
        _adapt(raw, pdf)


@pytest.mark.parametrize(
    "bbox",
    ([1, 2, 3, 4], [3, 2, 1, 4], [float("nan"), 2, 3, 4], [0, 0, 2, 2], None),
)
def test_bbox_is_always_honestly_unknown_until_coordinates_are_validated(
    tmp_path: Path, bbox
) -> None:
    pdf = _pdf(tmp_path / "source.pdf")
    raw = _raw()
    if bbox is None:
        raw["pages"][0]["blocks"][0].pop("bbox")
    else:
        raw["pages"][0]["blocks"][0]["bbox"] = bbox
    block = _adapt(raw, pdf).pages[0].blocks[0]
    assert block.bbox is None
    assert block.bbox_status == "unknown"


def test_repeated_text_is_not_deduplicated(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "source.pdf")
    raw = _raw()
    raw["pages"][0]["blocks"][0]["content"] = ["repeat", "repeat"]
    assert _adapt(raw, pdf).pages[0].blocks[0].text == "repeat\nrepeat"


def test_rejects_runtime_provenance_mismatch(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "source.pdf")
    with pytest.raises(ValueError, match="provider"):
        _adapt(
            _raw(),
            pdf,
            runtime_audit={
                "mineru_version": "4.0.7",
                "tier": "flash",
                "parse_mode": "txt",
                "actual_provider": "CPUExecutionProvider",
                "onnxruntime_available_providers": ["CPUExecutionProvider"],
            },
        )


def test_execution_evidence_must_match_frozen_digest() -> None:
    evidence = {"resource": {"sha256": "a" * 64}}
    lock = {
        "artifact_kind": "parse-01-execution-lock-v3",
        "evidence": evidence,
        "evidence_sha256": sha256_json(evidence),
    }
    assert validate_execution_evidence(lock, evidence) == sha256_json(evidence)
    with pytest.raises(ValueError, match="does not match"):
        validate_execution_evidence(lock, {"resource": {"sha256": "b" * 64}})


def test_rejects_double_page_conversion() -> None:
    with pytest.raises(ValueError, match="exactly once"):
        ComparisonPage(
            source_id="source",
            run_id="run",
            mineru_page_idx=0,
            physical_page=2,
            blocks=[],
            text="",
        )


def _fake_psutil(rss: int, available: int):
    process = lambda pid: SimpleNamespace(  # noqa: E731
        memory_info=lambda: SimpleNamespace(rss=rss), children=lambda recursive: []
    )
    return SimpleNamespace(
        Process=process,
        Error=Exception,
        virtual_memory=lambda: SimpleNamespace(available=available),
    )


@pytest.mark.parametrize(
    ("limits", "expected", "rss", "available"),
    [
        (RunLimits(timeout_seconds=0.1, poll_seconds=0.02), "timeout", 0, 16 * 1024**3),
        (
            RunLimits(timeout_seconds=10, process_tree_rss_bytes=1, poll_seconds=0.02),
            "process_tree_rss_limit",
            2,
            16 * 1024**3,
        ),
        (
            RunLimits(timeout_seconds=10, minimum_free_ram_bytes=2, poll_seconds=0.02),
            "minimum_free_ram_limit",
            0,
            1,
        ),
    ],
)
def test_supervisor_enforces_time_and_memory_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limits: RunLimits,
    expected: str,
    rss: int,
    available: int,
) -> None:
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil(rss, available))
    monkeypatch.setattr(
        "jgrad_admission_rag.parsing.mineru_pilot._terminate_tree", lambda process: process.kill()
    )
    report_path = tmp_path / f"{expected}.json"
    with pytest.raises(RuntimeError, match=expected):
        supervise_worker(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            environment=dict(__import__("os").environ),
            report_path=report_path,
            limits=limits,
        )
    assert json.loads(report_path.read_text())["stop_reason"] == expected


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("pilot", "pilot_disk_limit"), ("report", "report_disk_limit")],
)
def test_supervisor_enforces_disk_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, expected: str
) -> None:
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil(0, 16 * 1024**3))
    monkeypatch.setattr(
        "jgrad_admission_rag.parsing.mineru_pilot._terminate_tree", lambda process: process.kill()
    )
    root = tmp_path / kind
    root.mkdir()
    (root / "existing.bin").write_bytes(b"xx")
    kwargs = (
        {"pilot_root": root, "pilot_disk_bytes": 1}
        if kind == "pilot"
        else {"report_root": root, "report_bytes": 1}
    )
    report_path = tmp_path / f"{expected}.json"
    with pytest.raises(RuntimeError, match=expected):
        supervise_worker(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            environment=dict(__import__("os").environ),
            report_path=report_path,
            limits=RunLimits(timeout_seconds=10, poll_seconds=0.02, **kwargs),
        )


@pytest.mark.parametrize("occupied_output", [False, True])
def test_closed_worker_refuses_before_output_creation(
    tmp_path: Path, occupied_output: bool
) -> None:
    occupied = tmp_path / "raw.json"
    if occupied_output:
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
            "--runtime-audit",
            str(tmp_path / "r.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "PARSE-01 closed" in result.stderr
    if occupied_output:
        assert occupied.read_text() == "owned"
    else:
        assert not occupied.exists()
    assert not (tmp_path / "m.md").exists()
    assert not (tmp_path / "n.json").exists()
    assert not (tmp_path / "r.json").exists()


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


def test_manual_scorecard_is_complete_bound_and_arithmetically_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    scorecard = json.loads(
        (root / "docs" / "onboarding" / "mineru-4.0.7-pilot-scorecard.json").read_text()
    )
    gold = json.loads(
        (root / "docs" / "onboarding" / "mineru-4.0.7-pilot-gold-v1.json").read_text()
    )
    rows = scorecard["rows"]
    assert [row["unit_id"] for row in rows] == [unit["unit_id"] for unit in gold["units"]]
    gold_by_id = {unit["unit_id"]: unit for unit in gold["units"]}
    for candidate in ("legacy", "flash"):
        summary_name = "legacy_ms02" if candidate == "legacy" else candidate
        passed = sum(row[candidate]["status"] == "pass" for row in rows)
        critical_passed = sum(
            row[candidate]["status"] == "pass" and gold_by_id[row["unit_id"]]["critical"]
            for row in rows
        )
        table_structure_passed = sum(
            row[candidate]["status"] == "pass"
            and gold_by_id[row["unit_id"]]["metric_group"] in {"table", "structure"}
            for row in rows
        )
        summary = scorecard["summary"][summary_name]
        assert (passed, critical_passed, table_structure_passed) == (
            summary["passed"],
            summary["critical_passed"],
            summary["table_structure_passed"],
        )
        for row in rows:
            source_alias = row[candidate]["locator"].split(":", 1)[0]
            assert source_alias in scorecard["run_bindings"][summary_name]
            assert len(scorecard["run_bindings"][summary_name][source_alias]["run_id"]) == 64


def test_runner_enforces_cumulative_candidate_wall_limit(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(str(root / "tests" / "run_parse01_pilot.py"))
    preflight = namespace["_preflight_limits"]
    preflight.__globals__["PILOT"] = tmp_path
    preflight.__globals__["RUNS"] = tmp_path / "runs"
    limits = {
        "pilot_disk_bytes": 1024,
        "report_bytes": 1024,
        "candidate_parse_wall_seconds": 10,
    }
    assert preflight(limits, {"wall_seconds": 9}) == 1
    with pytest.raises(RuntimeError, match="candidate_wall_limit"):
        preflight(limits, {"wall_seconds": 10})


def test_supervisor_drains_verbose_child_without_pipe_stall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "psutil", _fake_psutil(0, 16 * 1024**3))
    report = supervise_worker(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x'*262144); sys.stderr.write('y'*262144)",
        ],
        environment=dict(__import__("os").environ),
        report_path=tmp_path / "verbose.json",
        limits=RunLimits(timeout_seconds=10, minimum_free_ram_bytes=0, poll_seconds=0.02),
    )
    assert report["stop_reason"] is None
    assert report["stdout"] == "x" * 262144
    assert report["stderr"] == "y" * 262144


def test_closed_runner_refuses_freeze_and_run_before_side_effects(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(str(root / "tests" / "run_parse01_pilot.py"))
    for name, arguments in (("_freeze", ()), ("_run", ("unused", "flash", 1))):
        entry = namespace[name]
        entry.__globals__["PILOT"] = tmp_path / "must-not-exist"
        with pytest.raises(RuntimeError, match="388.*168"):
            entry(*arguments)
        assert not (tmp_path / "must-not-exist").exists()


def test_retrospective_audit_counts_all_generations_and_binds_scorecard() -> None:
    root = Path(__file__).resolve().parents[1] / "docs" / "onboarding"
    audit = json.loads((root / "mineru-4.0.7-pilot-audit.json").read_text(encoding="utf-8"))
    score = json.loads((root / "mineru-4.0.7-pilot-scorecard.json").read_text())
    assert audit["decision"] == score["decision"] == "reject"
    assert audit["candidate_execution_closed"] is True
    runs = audit["runs"]
    assert len(runs) == 21
    assert sum(run["pages_attempted"] for run in runs) == audit["candidate_page_passes"] == 388
    assert audit["candidate_page_passes"] > audit["candidate_page_limit"] == 168
    assert round(sum(run["seconds"] for run in runs), 3) == 3813.905
    for generation in audit["generations"]:
        selected = [run for run in runs if run["generation"] == generation["generation"]]
        assert len(selected) == generation["run_count"]
        assert sum(run["pages_attempted"] for run in selected) == generation["page_passes"]
    original_lock = next(
        item
        for item in audit["original_execution_lock_files"]
        if item["file"] == "execution-lock-v3.json"
    )
    assert original_lock["sha256"] == score["execution_lock_sha256"]
    lock = audit["v3_execution_lock"]
    assert validate_execution_evidence(lock, lock["evidence"]) == lock["evidence_sha256"]
    assert sha256_file(root / "mineru-4.0.7-pilot-gold-v1.json") == score["gold_sha256"]
    for source, binding in score["run_bindings"]["flash"].items():
        run = next(
            item
            for item in runs
            if item["generation"] == "runs-v3"
            and item["tier"] == "flash"
            and item["source_id"] == source
            and item["repetition"] == "run-1"
        )
        assert run["files"]["raw.json"]["sha256"] == binding["raw_sha256"]
        assert run["files"]["comparison-view.json"]["sha256"] == binding["comparison_view_sha256"]
