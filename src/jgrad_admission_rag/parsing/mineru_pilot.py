"""Strict, experimental MinerU comparison adapter for PARSE-01.

This module deliberately emits a separate comparison-view contract.  It is not
an implementation of, or substitute for, the production MS02 parser contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ComparisonBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    raw_pointer: str
    block_index: int
    block_type: str
    text: str
    bbox: tuple[float, float, float, float] | None
    bbox_status: Literal["known", "unknown"]


class ComparisonPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mineru_page_idx: int = Field(ge=0)
    physical_page: int = Field(ge=1)
    source_id: str
    run_id: str
    blocks: list[ComparisonBlock]
    text: str

    @model_validator(mode="after")
    def page_number_is_converted_once(self) -> "ComparisonPage":
        if self.physical_page != self.mineru_page_idx + 1:
            raise ValueError("physical_page must equal MinerU page_idx + 1 exactly once")
        return self


class ComparisonView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: Literal["mineru-pilot-comparison-view"] = "mineru-pilot-comparison-view"
    contract_version: Literal["1.0"] = "1.0"
    production_enabled: Literal[False] = False
    run_id: str
    run_repetition: int = Field(ge=1)
    execution_lock_sha256: str
    environment_evidence_sha256: str
    config_sha256: str
    model_revision: str
    raw_result_sha256: str
    runtime_audit_sha256: str
    # Historical field name: a configured claim, not per-session attestation.
    actual_provider: Literal["native-text/no-onnx-session", "CPUExecutionProvider"]
    source_id: str
    source_pdf_sha256: str
    source_page_count: int = Field(ge=1)
    tier: Literal["flash", "basic"]
    mineru_version: Literal["4.0.7"]
    raw_schema: Literal["docvortex.middle"]
    raw_schema_version: Literal["2.0"]
    is_full_document: Literal[True]
    pages: list[ComparisonPage]

    @model_validator(mode="after")
    def complete_unique_pages(self) -> "ComparisonView":
        page_indices = [page.mineru_page_idx for page in self.pages]
        expected = list(range(self.source_page_count))
        if page_indices != expected:
            raise ValueError(f"candidate pages must be complete, unique, ordered {expected!r}")
        return self


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_execution_evidence(lock: dict[str, Any], current_evidence: dict[str, Any]) -> str:
    """Fail closed when any resource captured before parsing has changed."""
    if lock.get("artifact_kind") != "parse-01-execution-lock-v3":
        raise ValueError("unexpected execution lock kind")
    expected = lock.get("evidence")
    if not isinstance(expected, dict):
        raise ValueError("execution lock evidence is missing")
    expected_digest = lock.get("evidence_sha256")
    if expected_digest != sha256_json(expected):
        raise ValueError("execution lock evidence digest is invalid")
    if current_evidence != expected:
        raise ValueError("current environment does not match frozen execution evidence")
    return expected_digest


def pdf_page_count(path: Path) -> int:
    try:
        import fitz

        with fitz.open(path) as document:
            return document.page_count
    except ImportError:
        import pypdfium2

        return len(pypdfium2.PdfDocument(path))


def _block_text(value: Any) -> str:
    pieces: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            if item.strip():
                pieces.append(item.strip())
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            for key in ("content", "text", "html", "latex"):
                if key in item:
                    visit(item[key])
                    return
            for key, child in item.items():
                if key not in {"bbox", "index", "type", "block_type", "image_base64"}:
                    visit(child)

    visit(value)
    return "\n".join(pieces)


def adapt_raw_result(
    raw: dict[str, Any],
    *,
    source_id: str,
    source_pdf: Path,
    expected_source_sha256: str,
    raw_result_sha256: str,
    runtime_audit: dict[str, Any],
    runtime_audit_sha256: str,
    execution_lock_sha256: str,
    environment_evidence_sha256: str,
    config_sha256: str,
    model_revision: str,
    run_repetition: int,
    tier: Literal["flash", "basic"],
) -> ComparisonView:
    actual_source_sha256 = sha256_file(source_pdf)
    if actual_source_sha256 != expected_source_sha256:
        raise ValueError("source PDF does not match locked run identity")
    if raw.get("schema") != "docvortex.middle" or raw.get("schema_version") != "2.0":
        raise ValueError("unexpected MinerU raw schema identity or version")
    if raw.get("is_full_document") is not True:
        raise ValueError("MinerU result does not honestly claim a full document")
    metadata = raw.get("metadata")
    producer = metadata.get("producer") if isinstance(metadata, dict) else None
    if producer != {"name": "mineru", "version": "4.0.7"}:
        raise ValueError("unexpected MinerU producer identity")
    extensions = raw.get("extensions")
    mineru_extension = extensions.get("mineru") if isinstance(extensions, dict) else None
    if not isinstance(mineru_extension, dict):
        raise ValueError("MinerU extension is missing")
    if mineru_extension.get("tier") != tier or mineru_extension.get("parse_mode") != "txt":
        raise ValueError("MinerU tier or parse mode does not match the locked run")
    expected_provider = "native-text/no-onnx-session" if tier == "flash" else "CPUExecutionProvider"
    if runtime_audit.get("tier") != tier or runtime_audit.get("parse_mode") != "txt":
        raise ValueError("runtime audit does not match the requested tier/mode")
    if runtime_audit.get("actual_provider") != expected_provider:
        raise ValueError("runtime audit provider does not match the locked tier")
    if runtime_audit.get("mineru_version") != "4.0.7":
        raise ValueError("runtime audit MinerU version mismatch")
    if tier == "basic" and "CPUExecutionProvider" not in runtime_audit.get(
        "onnxruntime_available_providers", []
    ):
        raise ValueError("CPUExecutionProvider is unavailable")
    raw_pages = raw.get("pages")
    if not isinstance(raw_pages, list):
        raise ValueError("MinerU pages must be a list")
    source_page_count = pdf_page_count(source_pdf)
    document_metadata = metadata.get("document") if isinstance(metadata, dict) else None
    if (
        not isinstance(document_metadata, dict)
        or document_metadata.get("page_count") != source_page_count
    ):
        raise ValueError("raw producer page count does not match the source PDF")
    run_identity = {
        "source_id": source_id,
        "run_repetition": run_repetition,
        "source_pdf_sha256": actual_source_sha256,
        "tier": tier,
        "parse_mode": "txt",
        "producer": producer,
        "actual_provider": expected_provider,
        "raw_result_sha256": raw_result_sha256,
        "runtime_audit_sha256": runtime_audit_sha256,
        "execution_lock_sha256": execution_lock_sha256,
        "environment_evidence_sha256": environment_evidence_sha256,
        "config_sha256": config_sha256,
        "model_revision": model_revision,
    }
    run_id = sha256_json(run_identity)
    pages: list[ComparisonPage] = []
    for raw_page in raw_pages:
        if not isinstance(raw_page, dict) or type(raw_page.get("page_idx")) is not int:
            raise ValueError("each MinerU page must have an integer page_idx")
        page_idx = raw_page["page_idx"]
        blocks_raw = raw_page.get("blocks")
        if not isinstance(blocks_raw, list):
            raise ValueError("each MinerU page must have a blocks list")
        blocks: list[ComparisonBlock] = []
        seen_block_indices: set[int] = set()
        for ordinal, block in enumerate(blocks_raw):
            if not isinstance(block, dict):
                raise ValueError("each MinerU block must be an object")
            # The pilot did not review/validate MinerU's normalized coordinate convention
            # against page geometry, so bbox capability remains explicitly unsupported.
            bbox = None
            block_index = block.get("index", ordinal)
            if type(block_index) is not int or block_index < 0:
                raise ValueError("each MinerU block index must be a non-negative integer")
            if block_index in seen_block_indices:
                raise ValueError("duplicate MinerU block index within page")
            seen_block_indices.add(block_index)
            raw_pointer = f"/pages/{len(pages)}/blocks/{ordinal}"
            blocks.append(
                ComparisonBlock(
                    block_id=f"{run_id}:p{page_idx + 1:05d}:b{block_index:05d}",
                    raw_pointer=raw_pointer,
                    block_index=block_index,
                    block_type=str(block.get("type", block.get("block_type", "unknown"))),
                    text=_block_text(block.get("content", block)),
                    bbox=bbox,
                    bbox_status="known" if bbox is not None else "unknown",
                )
            )
        pages.append(
            ComparisonPage(
                source_id=source_id,
                run_id=run_id,
                mineru_page_idx=page_idx,
                physical_page=page_idx + 1,
                blocks=blocks,
                text="\n\n".join(block.text for block in blocks if block.text),
            )
        )
    return ComparisonView(
        run_id=run_id,
        run_repetition=run_repetition,
        execution_lock_sha256=execution_lock_sha256,
        environment_evidence_sha256=environment_evidence_sha256,
        config_sha256=config_sha256,
        model_revision=model_revision,
        raw_result_sha256=raw_result_sha256,
        runtime_audit_sha256=runtime_audit_sha256,
        actual_provider=expected_provider,
        source_id=source_id,
        source_pdf_sha256=actual_source_sha256,
        source_page_count=source_page_count,
        tier=tier,
        mineru_version="4.0.7",
        raw_schema=raw["schema"],
        raw_schema_version=raw["schema_version"],
        is_full_document=raw["is_full_document"],
        pages=pages,
    )


@dataclass(frozen=True)
class RunLimits:
    timeout_seconds: float
    timeout_reason: str = "timeout"
    process_tree_rss_bytes: int = 12 * 1024**3
    minimum_free_ram_bytes: int = 4 * 1024**3
    pilot_root: Path | None = None
    pilot_disk_bytes: int | None = None
    report_root: Path | None = None
    report_bytes: int | None = None
    poll_seconds: float = 0.25
    disk_poll_seconds: float = 5.0


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _terminate_tree(process: subprocess.Popen[str]) -> None:
    try:
        import psutil
    except ImportError:
        process.kill()
        process.wait(timeout=5)
        return

    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in children:
            child.terminate()
        parent.terminate()
        _, alive = psutil.wait_procs([*children, parent], timeout=5)
        for item in alive:
            item.kill()
    except psutil.Error:
        process.kill()


def supervise_worker(
    command: list[str], *, environment: dict[str, str], report_path: Path, limits: RunLimits
) -> dict[str, Any]:
    """Run one candidate serially and enforce wall/RSS/free-RAM fail-closed limits."""
    import psutil

    report_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        env=environment,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    # Drain both pipes concurrently with monitoring; waiting for exit first can
    # deadlock a verbose child on a full pipe. This fix is synthetic-tested only.
    captured: list[tuple[str, str]] = []
    reader = Thread(target=lambda: captured.append(process.communicate()), daemon=True)
    reader.start()
    peak_rss = 0
    minimum_available_ram = psutil.virtual_memory().available
    peak_pilot_bytes = directory_size(limits.pilot_root) if limits.pilot_root else None
    peak_report_bytes = directory_size(limits.report_root) if limits.report_root else None
    last_disk_poll = started
    stop_reason: str | None = None
    while process.poll() is None:
        elapsed = time.monotonic() - started
        try:
            root = psutil.Process(process.pid)
            rss = root.memory_info().rss + sum(
                (child.memory_info().rss for child in root.children(recursive=True)), start=0
            )
            peak_rss = max(peak_rss, rss)
        except psutil.Error:
            rss = 0
        available = psutil.virtual_memory().available
        minimum_available_ram = min(minimum_available_ram, available)
        if time.monotonic() - last_disk_poll >= limits.disk_poll_seconds:
            if limits.pilot_root:
                peak_pilot_bytes = max(peak_pilot_bytes or 0, directory_size(limits.pilot_root))
            if limits.report_root:
                peak_report_bytes = max(peak_report_bytes or 0, directory_size(limits.report_root))
            last_disk_poll = time.monotonic()
        if elapsed > limits.timeout_seconds:
            stop_reason = limits.timeout_reason
        elif rss > limits.process_tree_rss_bytes:
            stop_reason = "process_tree_rss_limit"
        elif available < limits.minimum_free_ram_bytes:
            stop_reason = "minimum_free_ram_limit"
        elif (
            limits.pilot_disk_bytes is not None
            and (peak_pilot_bytes or 0) > limits.pilot_disk_bytes
        ):
            stop_reason = "pilot_disk_limit"
        elif limits.report_bytes is not None and (peak_report_bytes or 0) > limits.report_bytes:
            stop_reason = "report_disk_limit"
        if stop_reason:
            _terminate_tree(process)
            break
        time.sleep(limits.poll_seconds)
    reader.join()
    stdout, stderr = captured[0]
    if limits.pilot_root:
        peak_pilot_bytes = max(peak_pilot_bytes or 0, directory_size(limits.pilot_root))
    if limits.report_root:
        peak_report_bytes = max(peak_report_bytes or 0, directory_size(limits.report_root))
    if stop_reason is None:
        if (
            limits.pilot_disk_bytes is not None
            and (peak_pilot_bytes or 0) > limits.pilot_disk_bytes
        ):
            stop_reason = "pilot_disk_limit"
        elif limits.report_bytes is not None and (peak_report_bytes or 0) > limits.report_bytes:
            stop_reason = "report_disk_limit"
    report = {
        "command": command,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "exit_code": process.returncode,
        "peak_process_tree_rss_bytes": peak_rss,
        "minimum_available_ram_bytes": minimum_available_ram,
        "peak_pilot_disk_bytes": peak_pilot_bytes,
        "peak_report_bytes": peak_report_bytes,
        "stop_reason": stop_reason,
        "stdout": stdout,
        "stderr": stderr,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if stop_reason or process.returncode != 0:
        raise RuntimeError(f"candidate worker failed: {stop_reason or process.returncode}")
    return report


def cancel_worker(process: subprocess.Popen[str]) -> None:
    """Cancellation hook used by the pilot runner and its failure-mode tests."""
    if os.name == "nt":
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _terminate_tree(process)
