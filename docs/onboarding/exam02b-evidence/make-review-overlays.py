"""Refresh examination slices for saved base responses without product POSTs.

The saved base responses stay unchanged. Each new examination slice is projected
directly from the registered 391 KB and the packaged, checked field map.
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


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FILES = (
    "system-control-base-v2.json",
    "math-base-v2.json",
    "materials-base-v2.json",
    "architecture-base-v2.json",
    "transdisciplinary-base-v2.json",
    "social-human-base-v2.json",
    "computer-science-base-v2.json",
    "applied-chemistry-base-v2.json",
    "civil-environment-base-v2.json",
    "physics-base-v2.json",
)


def main(corpus_root: Path, source_pdf: Path) -> None:
    presentation = load_exam_presentation_v2(
        ROOT / "src/jgrad_admission_rag/demo_config/exam02b_source_bindings.json",
        corpus_root,
        corpus_root / "corpus.json",
        source_pdf,
    )
    source_id = presentation.data["source_identity"]["document_id"]
    identity = next(
        item.identity
        for item in load_corpus_manifest(corpus_root / "corpus.json").entries
        if item.identity.document_id == source_id
    )
    plan = SimpleNamespace(document_identity=identity)
    overlays = {}
    for filename in FILES:
        saved = json.loads((HERE / filename).read_text(encoding="utf-8"))
        old = saved["examination_information"]
        target = DemoTargetRequest.model_validate(old["target_identity"])
        fresh = exam_response_v2(
            target, presentation, False, plan, identity if old.get("local_pdf_url") else None
        )
        assert fresh["status"] == "available_official_paths"
        overlays[filename] = fresh
    for key, department_id in (
        ("direct-earth", "地球惑星科学系"),
        ("direct-life", "生命理工学系"),
    ):
        item = next(
            row for row in presentation.data["departments"] if row["department_id"] == department_id
        )
        target = DemoTargetRequest(
            school_id="isct",
            document_id=source_id,
            degree_id="master",
            intake={"year": 2027, "month": 4},
            college_id=item["college_id"],
            department_id=department_id,
            application_route=None,
        )
        overlays[key] = exam_response_v2(target, presentation, False, plan, identity)
        assert overlays[key]["status"] == "available_official_paths"
    (HERE / "review-v2-exam-overlays.json").write_text(
        json.dumps(overlays, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(FILES)} saved-base overlays and 2 direct-only examination projections")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
