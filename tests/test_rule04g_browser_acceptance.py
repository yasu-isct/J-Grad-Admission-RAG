from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/rule04g_browser_acceptance_v1.json"
APP_JS = ROOT / "src/jgrad_admission_rag/service/static/app.js"


def _records():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_rule04g_browser_acceptance_covers_scenarios_and_viewports() -> None:
    records = _records()
    scenarios = {
        "tsinghua-confirmed",
        "tsinghua-missing-route",
        "tsinghua-wrong-intake",
        "tsinghua-wrong-route",
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


def test_rule04g_browser_acceptance_is_fail_closed() -> None:
    records = _records()
    confirmed = next(item for item in records if item["scenario"] == "tsinghua-confirmed")
    assert confirmed["status"] == "confirmed"
    assert confirmed["application_route"] == "tsinghua_joint_program"
    assert confirmed["intake_year"] == 2027
    assert confirmed["intake_month"] == 4
    assert confirmed["language"] == "chinese"
    assert confirmed["admission_selection"] == "excluded"
    assert confirmed["evidence"]["fact_id"] == "fact:00347"
    assert confirmed["evidence"]["source_pages"] == [76]
    assert confirmed["visible_evidence_fact_ids"] == ["fact:00347"]

    missing = next(item for item in records if item["scenario"] == "tsinghua-missing-route")
    assert missing["status"] == "needs_information"
    assert missing["evidence"] is None
    assert missing["visible_evidence_fact_ids"] == []
    for scenario in ("tsinghua-wrong-intake", "tsinghua-wrong-route"):
        item = next(record for record in records if record["scenario"] == scenario)
        assert item["status"] == "not_covered"
        assert item["program"] is None
        assert item["language"] is None
        assert item["admission_selection"] is None
        assert item["evidence"] is None
        assert item["visible_evidence_fact_ids"] == []
