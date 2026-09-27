"""Bounded offline real-PDF evidence runner for MS-02 (not a production build)."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

from jgrad_admission_rag.builder.extractor import extract_pdf
from jgrad_admission_rag.cli.parse_legacy_pilot import _publish_new_file
from jgrad_admission_rag.parsing import (
    ExactSource,
    ParseRequest,
    canonical_normalized_document_bytes,
    parse_legacy_pdf,
)

MAX_SOURCE_SECONDS = 600
MAX_REPORT_BYTES = 100 * 1024 * 1024
SAMPLES = {
    "complex-guide-2027-revised": (28, 40),
    "complex-master-a-additional": (1,),
}
SAMPLE_LIMITATIONS = (
    "The 15-page sample is review coverage, not a complete block/table gold dataset.",
    "Whole-page Markdown cannot establish native table cells, merged-cell fidelity, bounding boxes, or clause locators.",
    "Printed page labels remain unknown; department physical page 28 is not rewritten from its printed label 26.",
    "The locked real sources do not establish OCR quality unless an actual scanned page is observed.",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-lock", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    if not args.output_dir.is_dir() or any(args.output_dir.iterdir()):
        parser.error("output directory must already exist and be empty")
    lock = json.loads(args.source_lock.read_text(encoding="utf-8"))
    evidence: dict[str, object] = {
        "evidence_kind": "ms02-real-parser-comparison",
        "source_lock": args.source_lock.name,
        "limits": {
            "maximum_seconds_per_source_phase": MAX_SOURCE_SECONDS,
            "maximum_report_bytes": MAX_REPORT_BYTES,
        },
        "sources": [],
        "sample_limitations": SAMPLE_LIMITATIONS,
        "asset_impact": {
            "production_assets_mutated": False,
            "kb_builder_called": False,
            "model_downloaded_or_loaded": False,
            "runtime_activated": False,
            "network_called": False,
        },
    }
    total_report_bytes = 0
    total_pages = 0
    for entry in lock["sources"]:
        source_path = args.source_dir / f"{entry['sha256']}.pdf"
        source = ExactSource(
            path=source_path,
            source_id=entry["source_id"],
            expected_sha256=entry["sha256"],
            expected_physical_page_count=entry["physical_page_count"],
        )

        direct_started = time.perf_counter()
        direct = extract_pdf(source_path)
        direct_seconds = time.perf_counter() - direct_started
        _check_duration(entry["source_id"], "direct", direct_seconds)

        adapter_started = time.perf_counter()
        normalized = parse_legacy_pdf(source, ParseRequest(selection="all"))
        adapter_seconds = time.perf_counter() - adapter_started
        _check_duration(entry["source_id"], "adapter", adapter_seconds)

        assert len(direct) == entry["physical_page_count"]
        assert tuple(page.page for page in direct) == tuple(
            page.physical_page for page in normalized.pages
        )
        for legacy, page in zip(direct, normalized.pages, strict=True):
            block = page.blocks[0]
            assert block.text == legacy.markdown
            assert block.diagnostics.legacy_char_count == legacy.char_count
            assert block.diagnostics.legacy_table_count == legacy.table_count
            assert block.diagnostics.legacy_scanned == legacy.scanned

        output_bytes = canonical_normalized_document_bytes(normalized)
        total_report_bytes += len(output_bytes)
        if total_report_bytes > MAX_REPORT_BYTES:
            raise RuntimeError("planned normalized reports exceed the 100 MiB evidence ceiling")
        _publish_new_file(args.output_dir / f"{entry['source_id']}.json", output_bytes)
        total_pages += len(normalized.pages)
        samples = []
        for physical_page in SAMPLES.get(entry["source_id"], ()):
            page = normalized.pages[physical_page - 1]
            block = page.blocks[0]
            samples.append(
                {
                    "physical_page": page.physical_page,
                    "printed_page_label": page.printed_page_label,
                    "block_id": block.block_id,
                    "text_sha256": sha256(block.text.encode("utf-8")).hexdigest(),
                    "legacy_char_count": block.diagnostics.legacy_char_count,
                    "legacy_table_count": block.diagnostics.legacy_table_count,
                    "legacy_scanned": block.diagnostics.legacy_scanned,
                }
            )
        evidence["sources"].append(
            {
                "source_id": entry["source_id"],
                "source_pdf_sha256": normalized.source.source_pdf_sha256,
                "physical_page_count": normalized.source.physical_page_count,
                "returned_pages": normalized.coverage.returned_pages,
                "successful_text_pages": normalized.coverage.successful_text_pages,
                "scanned_without_ocr_pages": normalized.coverage.scanned_without_ocr_pages,
                "blank_or_unreadable_pages": normalized.coverage.blank_or_unreadable_pages,
                "run_id": normalized.run_id,
                "output_digest": normalized.output_digest,
                "dependency_versions": [
                    item.model_dump(mode="json") for item in normalized.provenance.dependencies
                ],
                "direct_seconds": round(direct_seconds, 3),
                "adapter_seconds": round(adapter_seconds, 3),
                "normalized_bytes": len(output_bytes),
                "direct_payloads_equal": True,
                "samples": samples,
            }
        )

    evidence["total_physical_pages"] = total_pages
    evidence["total_normalized_bytes"] = total_report_bytes
    assert total_pages == 83
    summary_bytes = (
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _publish_new_file(args.output_dir / "evidence-summary.json", summary_bytes)
    print(summary_bytes.decode("utf-8"))


def _check_duration(source_id: str, phase: str, seconds: float) -> None:
    if seconds > MAX_SOURCE_SECONDS:
        raise RuntimeError(f"{source_id} {phase} phase exceeded 10 minutes; stopping")


if __name__ == "__main__":
    main()
