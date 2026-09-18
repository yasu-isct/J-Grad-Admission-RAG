from __future__ import annotations

import hashlib
import json
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "rule04f_browser_acceptance_v1.json"
APP_JS = Path(__file__).parents[1] / "src/jgrad_admission_rag/service/static/app.js"


def _records() -> list[dict[str, object]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_rule04f_browser_acceptance_covers_scenarios_and_viewports() -> None:
    records = _records()
    scenarios = {
        "information-b-confirmed",
        "information-missing-route",
        "information-a-not-covered",
        "information-wrong-parent",
    }
    viewports = {"desktop": 1440, "mobile": 390}

    assert len(records) == len(scenarios) * len(viewports)
    assert {(item["viewport"], item["scenario"]) for item in records} == {
        (viewport, scenario) for viewport in viewports for scenario in scenarios
    }
    assert all(item["viewport_width"] == viewports[item["viewport"]] for item in records)
    assert all(item["horizontal_overflow"] is False for item in records)
    audited_hash = hashlib.sha256(APP_JS.read_bytes()).hexdigest()
    assert all(item["audited_app_js_sha256"] == audited_hash for item in records)


def test_rule04f_browser_acceptance_preserves_uses_and_fail_closed_paths() -> None:
    desktop = {item["scenario"]: item for item in _records() if item["viewport"] == "desktop"}
    confirmed = desktop["information-b-confirmed"]

    assert confirmed["status"] == "confirmed"
    assert confirmed["application_route"] == "b_schedule"
    assert confirmed["assessment_source"] == "external_score"
    assert confirmed["no_internal_written_exam"] is True
    assert confirmed["evaluation_uses"] == [
        "oral_exam_candidate_selection",
        "final_holistic_evaluation",
    ]
    assert confirmed["evidence"]["fact_id"] == "fact:00288"
    assert confirmed["evidence"]["source_pages"] == [52]
    assert confirmed["allocation_maximum_points"] == 100
    assert confirmed["allocation_evidence"] == confirmed["evidence"]
    assert "人数や閾値は公表されておらず" in confirmed["limitation_statement"]

    missing = desktop["information-missing-route"]
    assert missing["status"] == "needs_information"
    for scenario in (
        "information-missing-route",
        "information-a-not-covered",
    ):
        item = desktop[scenario]
        assert item["assessment_source"] is None
        assert item["evaluation_uses"] is None
        assert item["evidence"] is None
        assert item["allocation_maximum_points"] == 100
        assert item["allocation_evidence"]["fact_id"] == "fact:00288"
        assert "人数や閾値" not in item["limitation_statement"]
    wrong_parent = desktop["information-wrong-parent"]
    assert wrong_parent["assessment_source"] is None
    assert wrong_parent["evaluation_uses"] is None
    assert wrong_parent["evidence"] is None
    assert wrong_parent["allocation_maximum_points"] is None
    assert wrong_parent["allocation_evidence"] is None
    assert "人数や閾値" not in wrong_parent["limitation_statement"]
