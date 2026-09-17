from __future__ import annotations

import json
import hashlib
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "rule04e_browser_acceptance_v1.json"
APP_JS = Path(__file__).parents[1] / "src/jgrad_admission_rag/service/static/app.js"


def _records() -> list[dict[str, object]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_rule04e_browser_acceptance_covers_scenarios_and_viewports() -> None:
    records = _records()
    scenarios = {"math-confirmed", "physics-not-covered", "math-wrong-parent"}
    viewports = {"desktop": 1440, "mobile": 390}

    assert len(records) == len(scenarios) * len(viewports)
    assert {(item["viewport"], item["scenario"]) for item in records} == {
        (viewport, scenario) for viewport in viewports for scenario in scenarios
    }
    assert all(item["viewport_width"] == viewports[item["viewport"]] for item in records)
    assert all(item["horizontal_overflow"] is False for item in records)
    assert all(item["limitation_statement"] for item in records)
    audited_hash = hashlib.sha256(APP_JS.read_bytes()).hexdigest()
    assert all(item["audited_app_js_sha256"] == audited_hash for item in records)


def test_rule04e_browser_acceptance_preserves_method_and_fail_closed_paths() -> None:
    desktop = {item["scenario"]: item for item in _records() if item["viewport"] == "desktop"}
    confirmed = desktop["math-confirmed"]

    assert confirmed["status"] == "confirmed"
    assert confirmed["assessment_source"] == "written_exam"
    assert confirmed["result_scale"] == "pass_fail"
    assert confirmed["required_for_all"] is True
    assert confirmed["external_score_exemption"] is False
    assert confirmed["selection_role"] == "necessary_condition"
    assert confirmed["evidence"]["fact_id"] == "fact:00149"
    assert confirmed["evidence"]["source_pages"] == [19]
    assert "数学筆答試験と口頭試問" in confirmed["limitation_statement"]
    assert "最終合格者を決定" in confirmed["limitation_statement"]
    for scenario in ("physics-not-covered", "math-wrong-parent"):
        assert desktop[scenario]["status"] == "not_covered"
        assert desktop[scenario]["assessment_source"] is None
        assert desktop[scenario]["evidence"] is None
        assert "数学筆答試験と口頭試問" not in desktop[scenario]["limitation_statement"]
        assert "対象系の公式規則は別途確認" in desktop[scenario]["limitation_statement"]
