"""Synthetic four-step browser journey; no real service or asset is opened."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.test_unified_browser import _fixture

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "src/jgrad_admission_rag/service/static"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
pytestmark = pytest.mark.skipif(not EDGE.exists(), reason="local browser executable unavailable")


def _data():
    catalog, base, comparison, evidence, report = _fixture()
    source = base["requirements"][0]["evidence"][0]
    base["requirements"][0]["date_events"][0].update(
        {"nature": "must_arrive", "event_type": "arrival_deadline"}
    )
    base["requirements"].append(
        {
            "requirement_id": "material-one",
            "category": "materials",
            "title": "英语成绩单",
            "description": "出愿时提交；准备状态须另行核对。",
            "reviewed_summary": "出愿时提交",
            "official_status": "required",
            "deadline": None,
            "evidence": [source],
            "date_events": [],
            "limitation": "只审核当前出愿范围",
        }
    )
    item = comparison["items"][0]
    comparison["items"] = [
        item,
        {
            **item,
            "title": "入学志愿票",
            "comparison_status": "recorded",
            "action_group": "recorded",
            "description": "本人自报已有，仍需核对官方要求。",
            "preparation_status": "available",
        },
        {
            **item,
            "title": "学历路径",
            "comparison_status": "needs_review",
            "action_group": "review_required",
            "description": "学历路径尚不确定。",
            "preparation_status": "unknown",
        },
    ]
    comparison["counts"] = {
        "total": 3,
        "recorded": 1,
        "action_required": 1,
        "review_required": 1,
    }
    original_topic = evidence["topics"][0]
    original_result = report["report"]["topic_results"][0]
    original_citation = report["report"]["evidence_inventory"][0]
    evidence["topics"] = []
    report["report"]["topic_results"] = []
    report["report"]["evidence_inventory"] = []
    for index, title in enumerate(("计划书", "成绩单", "申请表"), start=1):
        topic = deepcopy(original_topic)
        topic["topic_id"] = f"topic-{index}"
        topic["material_name_zh"] = title
        topic["records"][0]["record_id"] = f"record-{index}"
        evidence["topics"].append(topic)
        result = deepcopy(original_result)
        result["material_name_zh"] = title
        result["basis_citation_keys"] = [f"C{index}"]
        report["report"]["topic_results"].append(result)
        citation = deepcopy(original_citation)
        citation["citation_key"] = f"C{index}"
        citation["record_id"] = f"record-{index}"
        report["report"]["evidence_inventory"].append(citation)
    return catalog, base, comparison, evidence, report


def _select_legacy(page):
    page.locator("#school-select").select_option("school-one")
    page.locator("#intake-select").select_option("doc-one:2027:4")
    page.locator("#college-select").select_option("org")
    page.locator("#department-select").select_option("program")
    page.locator("#route-select").select_option("a_schedule")


def test_ui02_four_step_synthetic_visual_checkpoint(tmp_path):
    catalog, base, comparison, evidence, report = _data()
    calls = {"base": [], "comparison": [], "reports": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(
            "Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => {window.copied = text}}});"
        )

        def route_request(route):
            path = urlparse(route.request.url).path
            if path == "/app":
                route.fulfill(
                    body=(STATIC / "advanced.html").read_bytes(), content_type="text/html"
                )
            elif path.startswith("/assets/"):
                name = path.rsplit("/", 1)[-1]
                media = "text/css" if name.endswith(".css") else "text/javascript"
                route.fulfill(body=(STATIC / name).read_bytes(), content_type=media)
            elif path == "/v1/reference-targets":
                route.fulfill(json=catalog)
            elif path == "/v1/reviewed-documents":
                route.fulfill(json={"items": []})
            elif path == "/v1/generation-status":
                route.fulfill(json={"configured": False, "label": "本地未配置问答"})
            elif path == "/v1/base-requirements":
                calls["base"].append(route.request.post_data_json)
                route.fulfill(json=base)
            elif path == "/v1/applicant-comparison":
                calls["comparison"].append(route.request.post_data_json)
                route.fulfill(json=comparison)
            elif path.endswith("/evidence"):
                route.fulfill(json=evidence)
            elif path.endswith("/reports"):
                calls["reports"].append(route.request.post_data_json)
                route.fulfill(json=report)
            else:
                route.abort()

        page.route("**/*", route_request)
        page.goto("http://ui02.test/app")
        page.locator("#school-select option").nth(2).wait_for(state="attached")
        assert page.locator("#school-select option").count() == 3
        _select_legacy(page)
        assert calls == {"base": [], "comparison": [], "reports": []}
        page.locator("#requirements-submit").click()
        page.locator(".key-dates-section .date-event").first.wait_for()
        assert page.locator(".materials-section .requirement-card").count() == 1
        assert "必着截止" in page.locator(".key-dates-section").inner_text()
        assert page.locator(".overview-cta").is_visible()
        assert not calls["comparison"] and not calls["reports"]
        page.screenshot(path=str(tmp_path / "new-dates-materials-1440.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(tmp_path / "new-dates-materials-390.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.set_viewport_size({"width": 1440, "height": 900})
        page.locator("#step-2-panel .reference-generate").click()
        page.locator("#reference-report").wait_for(state="visible")
        assert not calls["comparison"] and not calls["reports"]
        page.locator("#reference-close").click()
        page.locator(".overview-cta").click()
        page.locator("#demo-credential-basis").select_option("ui_unknown")
        page.locator('[data-material-code="address_label"]').select_option("available")
        page.locator('[data-material-code="application_form"]').select_option("not_yet")
        page.screenshot(path=str(tmp_path / "new-personal-1440.png"), full_page=True)
        page.locator("#comparison-submit").click()
        page.locator("#priority-actions li").first.wait_for()
        assert page.locator("#count-total").inner_text() == "3"
        assert "尚未准备" in page.locator("#comparison-output").inner_text()
        assert "已有" in page.locator("#comparison-output").inner_text()
        assert "未提供／不确定" in page.locator("#comparison-output").inner_text()
        assert page.locator("#readiness-heading").evaluate(
            "node => node === document.activeElement"
        )
        page.screenshot(path=str(tmp_path / "new-action-summary-1440.png"), full_page=True)
        page.locator("#readiness-panel .reference-generate").click()
        page.locator("#reference-report").wait_for(state="visible")
        page.locator("#reference-copy").click()
        assert "官方适用性" in page.evaluate("window.copied")
        page.locator("#reference-close").click()
        assert len(calls["base"]) == 1 and len(calls["comparison"]) == 1
        page.locator("#edit-target").click()
        page.locator("#school-select").select_option("slice-two")
        page.locator("#intake-select").select_option("null:2027:4")
        page.locator("#college-select").select_option("organization")
        page.locator("#department-select").select_option("program")
        page.locator("#route-select").select_option("A")
        assert page.locator("#grounded-answer-panel").is_hidden()
        assert page.locator("#advanced-tools").is_hidden()
        page.locator("#requirements-submit").click()
        page.locator(".materials-section .requirement-card").first.wait_for()
        assert page.locator(".materials-section .requirement-card").count() == 3
        assert "当前资料尚未覆盖日期" in page.locator(".key-dates-section").inner_text()
        assert not calls["reports"]
        page.screenshot(path=str(tmp_path / "new-slice-materials-1440.png"), full_page=True)
        page.locator(".overview-cta").click()
        assert page.locator("#slice-profile").is_visible()
        assert page.locator("#legacy-profile-grid").is_hidden()
        page.locator("#slice-current-employed").select_option("yes")
        page.locator("#slice-retain-employed").select_option("no")
        page.locator("#comparison-submit").click()
        page.locator("#readiness-panel.slice-readiness").wait_for(state="visible")
        assert page.locator("#readiness-panel .readiness-counts").is_hidden()
        assert page.locator("#comparison-output .requirement-card").count() == 3
        assert len(calls["reports"]) == 1
        page.screenshot(path=str(tmp_path / "new-slice-conditions-1440.png"), full_page=True)
        page.locator("#readiness-panel .reference-generate").click()
        page.locator("#reference-report").wait_for(state="visible")
        assert len(calls["reports"]) == 1
        page.locator("#reference-copy").click()
        assert "# 原始报告" in page.evaluate("window.copied")
        assert errors == []
        browser.close()
