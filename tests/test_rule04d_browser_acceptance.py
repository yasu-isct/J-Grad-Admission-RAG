from __future__ import annotations

import json
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "rule04d_browser_acceptance_v1.json"


def _records() -> list[dict[str, object]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_rule04d_browser_acceptance_covers_scenarios_and_viewports() -> None:
    records = _records()
    scenarios = {
        "physics-60",
        "math-computing-20",
        "chemistry-200",
        "electrical-150",
        "math-non-numeric",
        "architecture-unpublished",
        "wrong-parent",
    }
    viewports = {"desktop": 1440, "mobile": 390}

    assert len(records) == len(scenarios) * len(viewports)
    assert {(item["viewport"], item["scenario"]) for item in records} == {
        (viewport, scenario) for viewport in viewports for scenario in scenarios
    }
    assert all(item["viewport_width"] == viewports[item["viewport"]] for item in records)
    assert all(item["horizontal_overflow"] is False for item in records)
    assert all(item["limitation_statement"] for item in records)


def test_rule04d_browser_acceptance_preserves_points_and_non_published_paths() -> None:
    desktop = {item["scenario"]: item for item in _records() if item["viewport"] == "desktop"}

    assert desktop["physics-60"]["maximum_points"] == 60
    assert desktop["math-computing-20"]["maximum_points"] == 20
    assert desktop["chemistry-200"]["maximum_points"] == 200
    assert desktop["electrical-150"]["evidence"]["source_pages"] == [34]
    for scenario in ("math-non-numeric", "architecture-unpublished", "wrong-parent"):
        assert desktop[scenario]["status"] == "not_published"
        assert desktop[scenario]["maximum_points"] is None
        assert desktop[scenario]["evidence"] is None
