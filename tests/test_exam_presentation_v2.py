"""EXAM-02B opt-in boundaries without starting a product service."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jgrad_admission_rag.service.demo_requirements import DemoTargetRequest
from jgrad_admission_rag.service.exam_presentation import (
    ExamPresentationError,
    ReviewedExamPresentation,
)
from jgrad_admission_rag.service.exam_presentation_v2 import (
    SOURCE_SHA256,
    exam_response_v2,
    load_exam_presentation_v2,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "src/jgrad_admission_rag/demo_config/exam02b_source_bindings.json"
SOURCE = ROOT / "docs/onboarding/exam02a-field-bindings.json"


def _target(item: dict, route: str | None = None) -> DemoTargetRequest:
    return DemoTargetRequest(
        school_id="isct",
        document_id="isct_2027_4_2026_9_master",
        degree_id="master",
        intake={"year": 2027, "month": 4},
        college_id=item["college_id"],
        department_id=item["department_id"],
        application_route=route,
    )


def test_packaged_source_is_exact_design_artifact_and_change_fails_before_kb_read(
    tmp_path: Path,
) -> None:
    assert CONFIG.read_bytes() == SOURCE.read_bytes()
    assert hashlib.sha256(CONFIG.read_bytes()).hexdigest() == SOURCE_SHA256
    changed = tmp_path / "changed.json"
    changed.write_bytes(CONFIG.read_bytes() + b" ")
    with pytest.raises(ExamPresentationError):
        load_exam_presentation_v2(changed, tmp_path, tmp_path / "missing.json", tmp_path)


def test_target_route_and_course_exclusion_fail_closed_without_fact_leak() -> None:
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    item = next(row for row in data["departments"] if row["department_id"] == "応用化学系")
    presentation = ReviewedExamPresentation(data, SOURCE_SHA256, {})
    identity = SimpleNamespace(
        institution_id="isct",
        document_id=data["source_identity"]["document_id"],
        source_pdf_sha256=data["source_identity"]["source_pdf_sha256"],
    )
    plan = SimpleNamespace(document_identity=identity)
    wrong_route = exam_response_v2(_target(item, "b_schedule"), presentation, False, plan, None)
    assert wrong_route["status"] == "not_covered"
    assert wrong_route["pathways"] == wrong_route["evidence"] == []
    excluded = exam_response_v2(_target(item), presentation, False, plan, None, "地球生命コース")
    assert excluded["status"] == "not_covered_course"
    assert excluded["applicability"]["course_state"] == "excluded"
    assert excluded["pathways"] == excluded["field_bindings"] == []
    unknown = exam_response_v2(_target(item), presentation, False, plan, None, "其他コース")
    assert unknown["status"] == "not_covered_course"
    assert unknown["applicability"]["course_state"] == "unknown"


def test_v2_unavailable_and_wrong_school_do_not_expose_old_cs_schedule() -> None:
    item = json.loads(CONFIG.read_text(encoding="utf-8"))["departments"][0]
    target = _target(item)
    unavailable = exam_response_v2(target, None, True, None, None)
    assert unavailable["status"] == "unavailable"
    assert unavailable["pathways"] == unavailable["evidence"] == []
    unconfigured = exam_response_v2(target, None, False, None, None)
    assert unconfigured["status"] == "unavailable"
    wrong_school = exam_response_v2(
        target.model_copy(update={"school_id": "utokyo"}), None, True, None, None
    )
    assert wrong_school["status"] == "not_covered"
