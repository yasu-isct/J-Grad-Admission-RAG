from __future__ import annotations

import json
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "rule04c_browser_acceptance_v1.json"


def _records() -> list[dict[str, object]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_rule04c_browser_acceptance_covers_scenarios_and_viewports() -> None:
    records = _records()
    scenarios = {
        "toeic-300",
        "toeic-301",
        "ibt-120-candidates",
        "ibt-out-of-table",
        "multiple-results-unselected",
        "math-written-exam-exception",
    }
    viewports = {"desktop": 1440, "mobile": 390}

    assert len(records) == len(scenarios) * len(viewports)
    assert {(item["viewport"], item["scenario"]) for item in records} == {
        (viewport, scenario) for viewport in viewports for scenario in scenarios
    }
    assert all(item["viewport_width"] == viewports[item["viewport"]] for item in records)
    assert all(item["horizontal_overflow"] is False for item in records)
    assert all(item["limitations"] for item in records)
    assert all(
        item["evidence"] == {"fact_id": "fact:00139", "source_pages": [16]} for item in records
    )


def test_rule04c_browser_acceptance_records_exact_conversion_shapes() -> None:
    desktop = {item["scenario"]: item for item in _records() if item["viewport"] == "desktop"}

    assert desktop["toeic-300"]["status"] == "not_applicable"
    assert desktop["toeic-301"]["status"] == "converted"
    assert desktop["toeic-301"]["pbt_candidates"][0]["lower"]["decimal"] == "400.748"
    assert desktop["ibt-120-candidates"]["result_shape"] == "candidates"
    assert [
        candidate["lower"]["decimal"]
        for candidate in desktop["ibt-120-candidates"]["pbt_candidates"]
    ] == ["673", "677"]
    assert desktop["ibt-out-of-table"]["status"] == "out_of_table"
    assert desktop["multiple-results-unselected"]["missing_fields"] == [
        "language_test_results.selected_for_submission"
    ]
    assert desktop["math-written-exam-exception"]["status"] == "not_required"
