from __future__ import annotations

import json
from pathlib import Path
import subprocess


STATIC_ROOT = Path(__file__).parents[1] / "src" / "jgrad_admission_rag" / "service" / "static"
OVERVIEW_JS = STATIC_ROOT / "overview.js"


def _overview(payload: dict, profile_groups: list[dict]) -> dict:
    script = """
require(process.argv[1]);
const payload = JSON.parse(process.argv[2]);
const groups = JSON.parse(process.argv[3]);
process.stdout.write(JSON.stringify(globalThis.JGradOverview.buildApplicationOverview(payload, groups)));
"""
    result = subprocess.run(
        ["node", "-e", script, str(OVERVIEW_JS), json.dumps(payload), json.dumps(profile_groups)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def _profile_groups() -> list[dict]:
    return [
        {
            "key": "education",
            "label": "学历、预计毕业时间与资格审查路径",
            "requirementCategories": ["eligibility"],
        },
        {
            "key": "english",
            "label": "英语考试与成绩",
            "requirementCategories": ["language"],
        },
        {
            "key": "materials",
            "label": "已有材料的准备状态",
            "requirementCategories": ["materials"],
        },
    ]


def test_structured_overview_aggregates_typed_fields_only() -> None:
    payload = {
        "target": {
            "school_name": "测试大学",
            "degree_name": "修士课程",
            "intake_name": "2027年4月入学",
            "college_name": "工学院",
            "department_name": "控制系",
        },
        "requirements": [
            {
                "category": "dates",
                "official_status": "required",
                "official_text": "错误的日文日期 2099年1月1日",
                "reviewed_summary": "错误摘要 2099年2月2日",
                "date_events": [
                    {"nature": "recommended_arrival", "display_text": "建议日期"},
                    {"nature": "must_arrive", "display_text": "结构化必着日期"},
                ],
            },
            {"category": "materials", "official_status": "required"},
            {"category": "materials", "official_status": "needs_information"},
            {"category": "eligibility", "official_status": "needs_information"},
            {"category": "language", "official_status": "needs_review"},
        ],
    }

    result = _overview(payload, _profile_groups())

    assert result["deadlineText"] == "结构化必着日期"
    assert result["materialCount"] == 2
    assert result["needsInformationCount"] == 2
    assert [item["key"] for item in result["neededProfileGroups"]] == [
        "education",
        "materials",
    ]
    assert "2099" not in json.dumps(result, ensure_ascii=False)


def test_overview_degrades_without_reviewed_dates_materials_or_requirements() -> None:
    missing_categories = _overview(
        {
            "target": {},
            "requirements": [{"category": "language", "official_status": "needs_review"}],
        },
        _profile_groups(),
    )
    missing_requirements = _overview({"target": {}}, _profile_groups())

    assert missing_categories["deadlineText"] == "暂无已审核数据"
    assert missing_categories["materialCount"] is None
    assert missing_categories["needsInformationCount"] == 0
    assert missing_requirements["materialCount"] is None
    assert missing_requirements["needsInformationCount"] is None
    assert missing_requirements["target"]["schoolName"] == "暂无已审核数据"


def test_result_hierarchy_cta_profile_schema_and_reset_are_explicit() -> None:
    html = (STATIC_ROOT / "app.html").read_text(encoding="utf-8")
    javascript = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
    css = (STATIC_ROOT / "app.css").read_text(encoding="utf-8")

    assert '<script src="/assets/overview.js" defer></script>' in html
    assert 'data-profile-group="education"' in html
    assert 'data-requirement-categories="eligibility"' in html
    assert "renderApplicationOverview(payload, overview)" in javascript
    assert "renderKeyDates(dateRequirements)" in javascript
    assert 'renderRequirementSection("必须准备的材料"' in javascript
    assert "renderPendingRequirements(pending, overview)" in javascript
    assert 'button.textContent = "填写个人情况，检查我还缺什么"' in javascript
    assert 'item.official_status === "needs_information"' in javascript
    assert 'event.nature === "must_arrive"' not in javascript
    assert 'clearDemoResults("申请目标已改变' in javascript
    assert "baseRequirementsLoaded = false" in javascript
    assert ".overview-action" in css
    assert "position: sticky" in css
    assert "overflow-wrap: break-word" in css


def test_overview_source_has_no_school_specific_conclusions_or_text_parsing() -> None:
    javascript = OVERVIEW_JS.read_text(encoding="utf-8")

    assert "official_text" not in javascript
    assert "reviewed_summary" not in javascript
    assert "東京科学大学" not in javascript
    assert "2026年" not in javascript
    assert 'event.nature === "must_arrive"' in javascript
    assert 'item.category === "materials"' in javascript
    assert 'item.official_status === "needs_information"' in javascript
