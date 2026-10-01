"""Bounded EXAM-01 compatibility and fail-closed checks without the real 391 runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jgrad_admission_rag.service.demo_requirements import (
    DemoBaseRequirementsResponse,
    DemoTargetRequest,
    DemoTargetSummary,
)
from jgrad_admission_rag.service.exam_presentation import (
    ExamPresentationError,
    load_exam_presentation,
)
from jgrad_admission_rag.service.exam_presentation import exam_response


def test_optional_exam_field_keeps_legacy_shape_and_uncovered_status() -> None:
    target = DemoTargetSummary(
        school_name="示例",
        degree_name="修士",
        intake_name="2027年4月入学",
        college_name="学院",
        department_name="专业",
    )
    base = DemoBaseRequirementsResponse(
        target=target,
        coverage_statement="部分覆盖",
        limitation_statement="请核对原文",
        requirements=(),
    )
    assert "examination_information" not in base.model_dump(mode="json")
    request = DemoTargetRequest(
        school_id="example",
        document_id="example-2027",
        degree_id="master",
        intake={"year": 2027, "month": 4},
        college_id="学院",
        department_id="专业",
    )
    exam = exam_response(request, None, False, None, None)
    opted = base.model_copy(update={"examination_information": exam}).model_dump(mode="json")
    assert opted["examination_information"]["status"] == "not_covered"
    assert opted["examination_information"]["schedule"] is None
    assert opted["examination_information"]["evidence"] == []
    assert {
        key: value for key, value in opted.items() if key != "examination_information"
    } == base.model_dump(mode="json")


def test_changed_reviewed_config_fails_before_any_kb_read(tmp_path: Path) -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src/jgrad_admission_rag/demo_config/reviewed_exam_presentation.json"
    )
    data = json.loads(source.read_text(encoding="utf-8"))
    data["schedule"]["english_points"] = 0
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ExamPresentationError):
        load_exam_presentation(changed, tmp_path, tmp_path / "missing-manifest.json")


def test_expected_target_with_failed_source_exposes_no_stale_exam_fields() -> None:
    request = DemoTargetRequest(
        school_id="isct",
        document_id="isct_2027_4_2026_9_master",
        degree_id="master",
        intake={"year": 2026, "month": 9},
        college_id="情報理工学院",
        department_id="情報工学系",
        application_route="b_schedule",
    )
    failed = exam_response(request, None, True, None, None)
    assert failed["status"] == "unavailable"
    assert failed["schedule"] is None and failed["evidence"] == []
    assert "source_identity" not in failed and "presentation_sha256" not in failed
    assert (
        exam_response(
            request.model_copy(update={"application_route": "a_schedule"}), None, True, None, None
        )["status"]
        == "not_covered"
    )
