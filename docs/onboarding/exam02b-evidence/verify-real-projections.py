"""Stream 36 EXAM-02B projections from existing assets to a JS checker.

Usage: python verify-real-projections.py CORPUS_ROOT SOURCE_PDF | node verify-real-projections.mjs
No product service, POST, parser, build or asset write is involved.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from jgrad_admission_rag.schemas.corpus_manifest import load_corpus_manifest
from jgrad_admission_rag.service.demo_requirements import DemoTargetRequest
from jgrad_admission_rag.service.exam_presentation_v2 import (
    exam_response_v2,
    load_exam_presentation_v2,
)


ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "src/jgrad_admission_rag/demo_config/exam02b_source_bindings.json"


def main(corpus_root: Path, source_pdf: Path) -> None:
    manifest = corpus_root / "corpus.json"
    presentation = load_exam_presentation_v2(CONFIG, corpus_root, manifest, source_pdf)
    source_id = presentation.data["source_identity"]["document_id"]
    identity = next(
        row.identity
        for row in load_corpus_manifest(manifest).entries
        if row.identity.document_id == source_id
    )
    plan = SimpleNamespace(document_identity=identity)
    responses = []
    for item in presentation.data["departments"]:
        for intake in item["intakes"]:
            target = DemoTargetRequest(
                school_id="isct",
                document_id=source_id,
                degree_id="master",
                intake=intake,
                college_id=item["college_id"],
                department_id=item["department_id"],
                application_route=item["catalog_route"],
            )
            response = exam_response_v2(target, presentation, False, plan, None)
            assert response["status"] == "available_official_paths"
            responses.append(response)
            if any(field["field_path"] == "course.coverage_exclusion" for field in item["fields"]):
                excluded = exam_response_v2(
                    target, presentation, False, plan, None, "地球生命コース"
                )
                assert excluded["status"] == "not_covered_course"
                assert excluded["pathways"] == excluded["evidence"] == []
    assert len(responses) == 36
    sys.stdout.write(json.dumps(responses, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
