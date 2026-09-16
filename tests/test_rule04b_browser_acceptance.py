from __future__ import annotations

import json
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "rule04b_browser_acceptance_v1.json"


def test_rule04b_browser_acceptance_covers_scenarios_and_viewports() -> None:
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))
    scenarios = {
        "normal-department-with-application",
        "physics-exam-day-carry",
        "physics-missing-exam-day-submission",
        "civil-later-registered-mail",
        "civil-late-arrival",
        "civil-a-schedule-conflict",
        "math-written-exam-exception",
        "scope-unknown",
        "scope-parent-conflict",
    }
    viewports = {"desktop": 1440, "mobile": 390}

    assert len(records) == len(scenarios) * len(viewports)
    assert {(item["viewport"], item["scenario"]) for item in records} == {
        (viewport, scenario) for viewport in viewports for scenario in scenarios
    }
    assert all(item["viewport_width"] == viewports[item["viewport"]] for item in records)
    assert all(item["horizontal_overflow"] is False for item in records)
    assert all(item["limitation"] for item in records)
    assert all(item["rules"] for item in records)
    assert all(
        evidence["fact_id"] and evidence["source_pages"]
        for item in records
        for rule in item["rules"]
        for evidence in rule["evidence"]
    )


def test_rule04b_browser_acceptance_records_special_paths_and_scope_failures() -> None:
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))
    desktop = {item["scenario"]: item for item in records if item["viewport"] == "desktop"}

    assert desktop["normal-department-with-application"]["rules"][0]["rule_id"] == (
        "isct-master-english-submission-chemistry-apr"
    )
    assert desktop["physics-exam-day-carry"]["rules"][0]["status"] == "confirmed"
    assert (
        "missing-exam-day-risk-physics"
        in desktop["physics-missing-exam-day-submission"]["rules"][0]["rule_id"]
    )
    assert desktop["civil-later-registered-mail"]["rules"][0]["evidence"] == [
        {"fact_id": "fact:00314", "source_pages": [63]}
    ]
    assert "a-schedule-conflict" in desktop["civil-a-schedule-conflict"]["rules"][0]["rule_id"]
    assert "math-written-exam" in desktop["math-written-exam-exception"]["rules"][0]["rule_id"]

    unknown = desktop["scope-unknown"]["rules"][0]
    conflict = desktop["scope-parent-conflict"]["rules"][0]
    assert unknown["status"] == "needs_information"
    assert unknown["disposition"] == "pending"
    assert "target_application.department_or_program" in unknown["missing_items"]
    assert "late-arrival-risk" in desktop["civil-late-arrival"]["rules"][0]["rule_id"]
    assert conflict["status"] == "needs_information"
    assert conflict["disposition"] == "pending"
    assert conflict["diagnostic_code"] == "scope_input_conflict"
