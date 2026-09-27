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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ComparisonBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_index: int
    block_type: str
    text: str
    bbox: tuple[float, float, float, float] | None
    bbox_status: Literal["known", "unknown"]


class ComparisonPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mineru_page_idx: int = Field(ge=0)
    physical_page: int = Field(ge=1)
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
    return "\n".join(dict.fromkeys(pieces))


def adapt_raw_result(
    raw: dict[str, Any],
    *,
    source_id: str,
    source_pdf: Path,
    expected_source_sha256: str,
    tier: Literal["flash", "basic"],
) -> ComparisonView:
    actual_source_sha256 = sha256_file(source_pdf)
    if actual_source_sha256 != expected_source_sha256:
        raise ValueError("source PDF does not match locked run identity")
    if raw.get("schema") != "docvortex.middle" or raw.get("schema_version") != "2.0":
        raise ValueError("unexpected MinerU raw schema identity or version")
    if raw.get("is_full_document") is not True:
        raise ValueError("MinerU result does not honestly claim a full document")
    raw_pages = raw.get("pages")
    if not isinstance(raw_pages, list):
        raise ValueError("MinerU pages must be a list")
    source_page_count = pdf_page_count(source_pdf)
    pages: list[ComparisonPage] = []
    for raw_page in raw_pages:
        if not isinstance(raw_page, dict) or type(raw_page.get("page_idx")) is not int:
            raise ValueError("each MinerU page must have an integer page_idx")
        blocks_raw = raw_page.get("blocks")
        if not isinstance(blocks_raw, list):
            raise ValueError("each MinerU page must have a blocks list")
        blocks: list[ComparisonBlock] = []
        for ordinal, block in enumerate(blocks_raw):
            if not isinstance(block, dict):
                raise ValueError("each MinerU block must be an object")
            bbox_raw = block.get("bbox")
            bbox: tuple[float, float, float, float] | None = None
            if isinstance(bbox_raw, list) and len(bbox_raw) == 4 and all(
                isinstance(number, (int, float)) for number in bbox_raw
            ):
                bbox = tuple(float(number) for number in bbox_raw)
            blocks.append(
                ComparisonBlock(
                    block_index=block.get("index", ordinal),
                    block_type=str(block.get("type", block.get("block_type", "unknown"))),
                    text=_block_text(block.get("content", block)),
                    bbox=bbox,
                    bbox_status="known" if bbox is not None else "unknown",
                )
            )
        page_idx = raw_page["page_idx"]
        pages.append(
            ComparisonPage(
                mineru_page_idx=page_idx,
                physical_page=page_idx + 1,
                blocks=blocks,
                text="\n\n".join(block.text for block in blocks if block.text),
            )
        )
    return ComparisonView(
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
    process_tree_rss_bytes: int = 12 * 1024**3
    minimum_free_ram_bytes: int = 4 * 1024**3
    poll_seconds: float = 0.25


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
        env=environment,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    peak_rss = 0
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
        if elapsed > limits.timeout_seconds:
            stop_reason = "timeout"
        elif rss > limits.process_tree_rss_bytes:
            stop_reason = "process_tree_rss_limit"
        elif available < limits.minimum_free_ram_bytes:
            stop_reason = "minimum_free_ram_limit"
        if stop_reason:
            _terminate_tree(process)
            break
        time.sleep(limits.poll_seconds)
    stdout, stderr = process.communicate()
    report = {
        "command": command,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "exit_code": process.returncode,
        "peak_process_tree_rss_bytes": peak_rss,
        "stop_reason": stop_reason,
        "stdout": stdout,
        "stderr": stderr,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
