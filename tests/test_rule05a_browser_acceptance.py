from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/rule05a_browser_acceptance_v1.json"
APP_JS = ROOT / "src/jgrad_admission_rag/service/static/app.js"


def _records():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_rule05a_browser_acceptance_covers_only_three_high_value_scenarios() -> None:
    records = _records()
    scenarios = {"materials-direct", "materials-review-path", "materials-missing-path"}
    viewports = {"desktop": 1440, "mobile": 390}
    assert len(records) == 6
    assert {(item["viewport"], item["scenario"]) for item in records} == {
        (viewport, scenario) for viewport in viewports for scenario in scenarios
    }
    assert all(item["viewport_width"] == viewports[item["viewport"]] for item in records)
    assert all(item["horizontal_overflow"] is False for item in records)
    app_hash = hashlib.sha256(APP_JS.read_bytes()).hexdigest()
    assert all(item["app_js_sha256"] == app_hash for item in records)


def test_rule05a_browser_acceptance_preserves_path_boundaries() -> None:
    by_scenario = {item["scenario"]: item for item in _records() if item["viewport"] == "desktop"}
    assert by_scenario["materials-direct"]["applicability"] == ["required"] * 5
    assert by_scenario["materials-review-path"]["applicability"] == [
        "required",
        "required",
        "eligibility_review_path",
        "eligibility_review_path",
        "eligibility_review_path",
    ]
    assert by_scenario["materials-missing-path"]["applicability"] == [
        "required",
        "required",
        "needs_information",
        "needs_information",
        "needs_information",
    ]
    assert all(item["fact_id"] == "fact:00104" for item in by_scenario.values())
    assert all(item["source_pages"] == [10] for item in by_scenario.values())
