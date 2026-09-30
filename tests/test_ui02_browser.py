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
    base["requirements"][0]["date_events"].append(
        {
            "label": "建议送达",
            "display_text": "2026-11-25 17:00",
            "nature": "recommended_arrival",
            "event_type": "recommended_arrival",
            "precision": "minute",
            "unknown_fields": [],
            "uncertainty_note": "建议时间不等于强制截止",
            "evidence": [source],
        }
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
        citation["printed_page_label"] = "7"
        report["report"]["evidence_inventory"].append(citation)
    return catalog, base, comparison, evidence, report


def _comparison_for(request, template):
    materials = {item["code"]: item["preparation"] for item in request["applicant"]["materials"]}
    source = template["items"][0]["evidence"]
    items = [
        {
            "title": "宛名标签",
            "category": "materials",
            "comparison_status": "recorded"
            if materials["address_label"] == "available"
            else "needs_information",
            "action_group": "recorded"
            if materials["address_label"] == "available"
            else "action_required",
            "description": f"本人自报宛名标签：{materials['address_label']}。",
            "next_action": "核对官方要求与实际材料",
            "official_status": "required",
            "preparation_status": materials["address_label"],
            "evidence": source,
            "limitation": "自报不等于受理",
        },
        {
            "title": "入学志愿票",
            "category": "materials",
            "comparison_status": "recorded"
            if materials["application_form"] == "available"
            else "needs_information",
            "action_group": "recorded"
            if materials["application_form"] == "available"
            else "action_required",
            "description": f"本人自报入学志愿票：{materials['application_form']}。",
            "next_action": "尚未取得时准备并核对原文",
            "official_status": "required",
            "preparation_status": materials["application_form"],
            "evidence": source,
            "limitation": "自报不等于受理",
        },
        {
            "title": "学历路径",
            "category": "education",
            "comparison_status": "needs_review",
            "action_group": "review_required",
            "description": "学历路径未填写，须人工核对。",
            "next_action": "与学校核对学历路径",
            "official_status": "needs_information",
            "preparation_status": "unknown",
            "evidence": source,
            "limitation": "未知不能当作不符合",
        },
    ]
    response = deepcopy(template)
    response["items"] = items
    response["counts"] = {"total": 3, "recorded": 1, "action_required": 1, "review_required": 1}
    return response


def _slice_report_for(request, template):
    current = request["employment"]["currently_employed_in_organization"]
    retain = request["employment"]["retain_employment_at_enrollment"]
    names = {True: "是", False: "否", None: "未知"}
    response = deepcopy(template)
    condition = f"目前任职{names[current]}；入学后继续任职{names[retain]}"
    disposition = (
        "needs_information"
        if current is None
        else "submission_required"
        if current
        else "rule_not_applicable"
    )
    response["markdown"] = f"# 原始报告\n{condition}；合成状态 {disposition}；仅限三个材料主题。"
    for result in response["report"]["topic_results"]:
        result["disposition"] = disposition
        result["condition_status"] = disposition
        result["missing_fields"] = [
            name
            for name, value in (
                ("employment.currently_employed_in_organization", current),
                ("employment.retain_employment_at_enrollment", retain),
            )
            if value is None
        ]
        result["explanation_zh"] = (
            f"{result['material_name_zh']}：{condition}；合成状态 {disposition}。"
        )
    return response


def _select_legacy(page):
    page.locator("#school-select").select_option("school-one")
    page.locator("#intake-select").select_option("doc-one:2027:4")
    page.locator("#college-select").select_option("org")
    page.locator("#department-select").select_option("program")
    page.locator("#route-select").select_option("a_schedule")


def _select_slice(page):
    page.locator("#school-select").select_option("slice-two")
    page.locator("#intake-select").select_option("null:2027:4")
    page.locator("#college-select").select_option("organization")
    page.locator("#department-select").select_option("program")
    page.locator("#route-select").select_option("A")


def test_ui02_four_step_synthetic_visual_checkpoint(tmp_path):
    catalog, base, comparison, evidence, report = _data()
    base["requirements"][1]["reviewed_summary"] = "<img src=x onerror=window.reportXss=1>"
    base["requirements"][1]["official_status"] = "required"
    evidence["topics"][0]["records"].extend(
        {**deepcopy(evidence["topics"][0]["records"][0]), "record_id": f"extra-record-{i}"}
        for i in range(8)
    )
    evidence["topics"][0]["records"][3]["stage"] = "enrollment_context_only"
    primary_record_id = evidence["topics"][0]["records"][0]["record_id"]
    evidence["topics"][0]["relations"] = [
        {"from": "extra-record-0", "kind": "cross_reference", "to": primary_record_id},
        {"from": "extra-record-1", "kind": "unknown_reviewed_kind", "to": primary_record_id},
        {
            "from": "extra-record-2",
            "kind": "shares_employment_context_but_separate_enrollment_stage",
            "to": primary_record_id,
        },
    ]
    calls = {"base": [], "comparison": [], "reports": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(
            "Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: async text => {window.copied = text}}});"
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
                request = route.request.post_data_json
                calls["comparison"].append(request)
                route.fulfill(json=_comparison_for(request, comparison))
            elif path.endswith("/evidence"):
                route.fulfill(json=evidence)
            elif path.endswith("/reports"):
                request = route.request.post_data_json
                calls["reports"].append(request)
                route.fulfill(json=_slice_report_for(request, report))
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
        assert "建议到达" in page.locator(".key-dates-section").inner_text()
        assert page.locator('.date-event .date-nature[data-nature="must_arrive"]').count() == 1
        assert (
            page.locator('.date-event .date-nature[data-nature="recommended_arrival"]').count() == 1
        )
        assert page.locator(".overview-cta").is_visible()
        assert not calls["comparison"] and not calls["reports"]
        assert page.locator("#current-target-bar").is_visible()
        assert "第一所学校 · 专业" in page.locator("#current-target-name").inner_text()
        page.locator("#change-school").click()
        assert page.locator("#step-1-content").is_visible()
        assert page.locator("#school-select").input_value() == "school-one"
        assert page.locator("#current-target-bar").is_hidden()
        assert len(calls["base"]) == 1
        page.locator("#edit-requirements").click()
        assert page.locator("#current-target-bar").is_visible()
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
        sent = calls["comparison"][0]
        assert sent["target"]["document_id"] == "doc-one"
        assert sent["applicant"]["credential_basis"] is None
        assert {item["code"]: item["preparation"] for item in sent["applicant"]["materials"]}[
            "address_label"
        ] == "available"
        assert {item["code"]: item["preparation"] for item in sent["applicant"]["materials"]}[
            "application_form"
        ] == "not_yet"
        assert page.locator("#count-total").inner_text() == "3"
        assert page.locator("#count-action").inner_text() == "1"
        assert page.locator("#count-recorded").inner_text() == "1"
        assert page.locator("#count-review").inner_text() == "1"
        cards = page.locator("#comparison-output .comparison-card")
        assert "材料准备" in page.locator("#comparison-output .comparison-group").first.inner_text()
        assert "待准备" in cards.filter(has_text="入学志愿票").inner_text()
        assert "已准备（自报）" in cards.filter(has_text="宛名标签").inner_text()
        assert "未提供／不确定" in cards.filter(has_text="学历路径").inner_text()
        assert page.locator("#readiness-heading").evaluate(
            "node => node === document.activeElement"
        )
        page.screenshot(path=str(tmp_path / "new-action-summary-1440.png"), full_page=True)
        page.locator("#readiness-panel .reference-generate").click()
        page.locator("#reference-report").wait_for(state="visible")
        assert "已打开" in page.locator("#reference-step4-status").inner_text()
        page.locator("#reference-copy").click()
        preview = page.locator("#reference-report-body").inner_text()
        copied = page.evaluate("window.copied")
        for value in ("英语成绩单", "尚未填写准备情况", "关键时间", "材料准备清单"):
            assert value in preview and value in copied
        for value in ("available", "not_yet", "保守对照", "官方原文", "物理页"):
            assert value not in preview and value not in copied
        assert page.locator("#reference-report-body img").count() == 0
        assert not page.evaluate("window.reportXss")
        options = page.locator(".reader-report-options input")
        assert options.count() == 3
        options.nth(1).uncheck()
        page.locator("#reference-copy").click()
        selected_copy = page.evaluate("window.copied")
        assert "材料准备清单" not in selected_copy and "英语成绩单" not in selected_copy
        assert len(calls["base"]) == 1 and len(calls["comparison"]) == 1
        options.nth(2).uncheck()
        date_preview = page.locator("#reference-report-body").inner_text()
        page.locator("#reference-copy").click()
        date_copy = page.evaluate("window.copied")
        for value in ("接下来先做什么", "待准备", "材料准备清单", "已准备不代表"):
            assert value not in date_preview and value not in date_copy
        assert "关键时间" in date_preview and "关键时间" in date_copy
        options.nth(0).uncheck()
        options.nth(2).check()
        other_preview = page.locator("#reference-report-body").inner_text()
        page.locator("#reference-copy").click()
        other_copy = page.evaluate("window.copied")
        for value in ("接下来先做什么", "待准备", "材料准备清单", "已准备不代表"):
            assert value not in other_preview and value not in other_copy
        assert "其他已加载要求" in other_preview and "其他已加载要求" in other_copy
        options.nth(2).uncheck()
        assert page.locator("#reference-copy").is_disabled()
        assert "请至少选择一类报告内容" in page.locator("#reference-report-body").inner_text()
        options.nth(1).check()
        assert "材料准备清单" in page.locator("#reference-report-body").inner_text()
        page.evaluate(
            "Object.defineProperty(navigator, 'clipboard', {value: {writeText: async () => {throw Error('blocked')}}});"
        )
        page.locator("#reference-copy").click()
        assert page.locator("#reference-copy-fallback").is_visible()
        assert "材料准备清单" in page.locator("#reference-copy-fallback").input_value()
        page.evaluate(
            "Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: async text => {window.copied = text}}});"
        )
        page.locator("#reference-close").click()
        assert len(calls["base"]) == 1 and len(calls["comparison"]) == 1
        assert page.locator("#current-target-bar").is_visible()
        page.locator("#change-school").click()
        assert page.locator('[data-material-code="application_form"]').input_value() == "not_yet"
        assert page.locator("#reference-report-body").inner_text() != ""
        _select_slice(page)
        assert page.locator("#reference-report-body").inner_text() == ""
        assert page.locator('[data-material-code="application_form"]').input_value() == ""
        assert page.locator("#grounded-answer-panel").is_hidden()
        assert page.locator("#advanced-tools").is_hidden()
        page.locator("#requirements-submit").click()
        page.locator(".materials-section .requirement-card").first.wait_for()
        assert page.locator(".materials-section .requirement-card").count() == 3
        assert "当前资料尚未覆盖日期" in page.locator(".key-dates-section").inner_text()
        assert not calls["reports"]
        graph_trigger = page.locator(
            ".materials-section .requirement-evidence-actions button"
        ).first
        graph_trigger.scroll_into_view_if_needed()
        main_scroll = page.evaluate("window.scrollY")
        graph_trigger.click()
        drawer = page.locator("#evidence-drawer")
        assert set(
            drawer.locator(".relation-node").evaluate_all(
                "nodes => nodes.map(node => node.dataset.recordId)"
            )
        ) == {record["record_id"] for record in evidence["topics"][0]["records"]}
        assert drawer.locator(".relation-edge").count() == 2
        assert drawer.locator(".relation-path").count() == 2
        assert "部分关系类型尚未展示" in drawer.inner_text()
        assert "送付方法参照" in drawer.inner_text()
        assert (
            "入学手续相关，非本次出愿提交义务"
            in drawer.locator(".relation-edge-stage").inner_text()
        )
        for width, height in ((1440, 900), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            repeated = drawer.locator(
                f'.relation-node[data-record-id="{primary_record_id}"] button'
            )
            assert repeated.count() == 2
            for instance in range(2):
                button = repeated.nth(instance)
                button.scroll_into_view_if_needed()
                before = drawer.evaluate("dialog => dialog.scrollTop")
                button.click()
                drawer.locator(".relation-back").click()
                assert drawer.evaluate("dialog => dialog.scrollTop") == before
                assert button.evaluate("node => node === document.activeElement")
        page.set_viewport_size({"width": 1440, "height": 900})
        drawer.locator(".relation-node button").first.click()
        assert "PDF 物理页 8／印刷页 7" in drawer.inner_text()
        assert "提出が必要" in drawer.inner_text()
        assert "第二所学校官方文件" in drawer.inner_text()
        drawer.locator(".relation-back").click()
        assert drawer.locator(".relation-node").count() >= 9
        page.locator("#drawer-close").click()
        assert page.evaluate("window.scrollY") == main_scroll
        assert graph_trigger.evaluate("button => button === document.activeElement")
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
        assert calls["reports"][0]["employment"] == {
            "currently_employed_in_organization": True,
            "retain_employment_at_enrollment": False,
        }
        assert "目前任职是；入学后继续任职否" in page.locator("#comparison-output").inner_text()
        assert "当前条件：需提交" in page.locator("#comparison-output").inner_text()
        page.locator("#comparison-output .requirement-evidence-actions button").first.click()
        assert drawer.locator(".relation-node").count() >= 9
        drawer.locator(".relation-node button").first.click()
        assert "PDF 物理页 8／印刷页 7" in drawer.inner_text()
        drawer.press("Escape")
        assert drawer.is_hidden()
        page.screenshot(path=str(tmp_path / "new-slice-conditions-1440.png"), full_page=True)
        page.locator("#readiness-panel .reference-generate").click()
        page.locator("#reference-report").wait_for(state="visible")
        assert len(calls["reports"]) == 1
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator(
            "#comparison-output .requirement-evidence-actions button"
        ).first.evaluate("button => button.getBoundingClientRect().width >= 125")
        page.set_viewport_size({"width": 1440, "height": 900})
        page.locator("#reference-copy").click()
        preview = page.locator("#reference-report-body").inner_text()
        copied = page.evaluate("window.copied")
        for value in ("计划书", "成绩单", "申请表", "需提交，尚未填写准备情况"):
            assert value in preview and value in copied
        for value in ("# 原始报告", "物理页 8", "印刷页 7", "提出が必要", "record_id"):
            assert value not in preview and value not in copied
        page.locator("#reference-close").click()
        for topic in evidence["topics"]:
            topic["records"][0]["printed_page_label"] = None
        page.locator("#edit-target").click()
        page.locator("#requirements-submit").click()
        page.locator(".materials-section .requirement-evidence-actions button").first.click()
        drawer.locator(f'.relation-node[data-record-id="{primary_record_id}"] button').first.click()
        no_printed = drawer.inner_text()
        assert "PDF 物理页 8" in no_printed
        assert "印刷页" not in no_printed
        page.evaluate("""() => {
            const select = document.querySelector('#school-select');
            select.value = 'school-one';
            select.dispatchEvent(new Event('change', {bubbles: true}));
        }""")
        assert drawer.is_hidden()
        page.locator("#intake-select").select_option("doc-one:2027:4")
        page.locator("#college-select").select_option("org")
        page.locator("#department-select").select_option("program")
        page.locator("#route-select").select_option("a_schedule")
        assert page.locator("#reference-report").is_hidden()
        page.locator("#requirements-submit").click()
        page.locator(".key-dates-section .date-event").first.wait_for()
        assert page.locator("#count-total").inner_text() == "0"
        assert len(calls["base"]) == 2
        assert len(calls["reports"]) == 1
        assert errors == []
        browser.close()


def test_ui02_question_boundaries_and_school_isolation():
    catalog, base, _, evidence, _ = _data()
    questions = []

    def answer_for(question):
        no_result = question == "no safe result"
        answer_text = (
            "参考正文 formatted\n\n- JLPT N1\n- J.TEST\n\n**提醒** <img src=x onerror=window.answerXss=1>"
            if question == "formatted"
            else f"参考正文 {question}"
        )
        return {
            "mode": "reference_only",
            "analysis": {},
            "summary": f"处理概况 {question}",
            "delivery": {"source": "fallback" if question == "fallback" else "offline"},
            "result": None
            if no_result
            else {
                "local_scope_statement": "仅覆盖本地已审核的申请材料",
                "official_source_url": "https://example.edu/official.pdf",
                "answer": {
                    "kind": "reference_answer",
                    "answer": answer_text,
                    "claims": [],
                    "missing_information": ["还缺申请人的具体成绩"],
                    "limitations": [
                        "本地未命中可引用片段" if question == "zero hits" else "不能判断最终资格"
                    ],
                },
            },
            "missing_context": ["尚待确认考试日期"],
            "unsupported_parts": [
                "院外课程要求" if question == "partial unsupported" else "暂不覆盖住宿问题"
            ],
            "subanswers": [{"status": "no_clear_evidence", "message": "该分项没有清晰依据"}],
        }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route_request(route):
            path = urlparse(route.request.url).path
            if path == "/app":
                route.fulfill(
                    body=(STATIC / "advanced.html").read_bytes(), content_type="text/html"
                )
            elif path.startswith("/assets/"):
                name = path.rsplit("/", 1)[-1]
                route.fulfill(
                    body=(STATIC / name).read_bytes(),
                    content_type="text/css" if name.endswith(".css") else "text/javascript",
                )
            elif path == "/v1/reference-targets":
                route.fulfill(json=catalog)
            elif path == "/v1/reviewed-documents":
                route.fulfill(json={"items": []})
            elif path == "/v1/generation-status":
                route.fulfill(
                    json={
                        "configured": True,
                        "mode": "offline_rules",
                        "request_timeout_seconds": 30,
                        "label": "合成离线问答",
                    }
                )
            elif path == "/v1/base-requirements":
                route.fulfill(json=base)
            elif path.endswith("/evidence"):
                route.fulfill(json=evidence)
            elif path == "/v1/natural-language-answers":
                question = route.request.post_data_json["question"]
                questions.append(question)
                if question == "service failure":
                    route.fulfill(status=503, json={"code": "grounded_service_unavailable"})
                else:
                    route.fulfill(json=answer_for(question))
            else:
                route.abort()

        page.route("**/*", route_request)
        page.goto("http://ui02.test/app")
        page.locator("#school-select option").nth(2).wait_for(state="attached")
        _select_legacy(page)
        page.locator("#requirements-submit").click()
        page.locator(".key-dates-section .date-event").first.wait_for()
        for question in (
            "normal",
            "zero hits",
            "fallback",
            "partial unsupported",
            "no safe result",
            "formatted",
        ):
            page.locator("#grounded-question").fill(question)
            page.locator("#grounded-answer-submit").click()
            page.get_by_text(
                f"处理概况 {question}" if question == "no safe result" else f"参考正文 {question}"
            ).wait_for()
            output = page.locator("#grounded-answer-output").inner_text()
            if question == "no safe result":
                assert "本次没有可安全展示的引用回答" in output
                assert "参考正文 partial unsupported" not in output
                continue
            assert f"参考正文 {question}" in output
            assert "仅覆盖本地已审核的申请材料" not in output
            assert "还缺申请人的具体成绩" in output
            assert "尚待确认考试日期" in output
            if question == "zero hits":
                assert "本地未命中可引用片段" in output
            if question == "fallback":
                assert "在线服务不可用" in output
            if question == "partial unsupported":
                assert "院外课程要求" in output
            if question == "formatted":
                assert page.locator(".grounded-response-text li").count() == 2
                assert page.locator(".grounded-response-text strong").count() == 1
                assert page.locator("#grounded-answer-output img").count() == 0
                assert not page.evaluate("window.answerXss")
        page.locator("#grounded-question").fill("service failure")
        page.locator("#grounded-answer-submit").click()
        page.get_by_text("生成或检索服务暂时不可用，请稍后重试。").wait_for()
        assert page.locator("#grounded-answer-output").is_hidden()
        assert page.locator("#grounded-answer-retry").is_visible()
        page.locator("#edit-target").click()
        _select_slice(page)
        assert page.locator("#grounded-question").is_disabled()
        assert page.locator("#grounded-answer-panel").is_hidden()
        page.locator("#requirements-submit").click()
        page.locator(".materials-section .requirement-card").first.wait_for()
        assert questions == [
            "normal",
            "zero hits",
            "fallback",
            "partial unsupported",
            "no safe result",
            "formatted",
            "service failure",
        ]
        assert errors == []
        browser.close()


def test_ui02_delayed_switch_failure_retry_and_report_invalidation():
    catalog, base, comparison, evidence, report = _data()
    held_base = []
    held_report = []
    held_report_error = []
    calls = {"base": [], "evidence": 0, "reports": [], "comparison": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route_request(route):
            path = urlparse(route.request.url).path
            if path == "/app":
                route.fulfill(
                    body=(STATIC / "advanced.html").read_bytes(), content_type="text/html"
                )
            elif path.startswith("/assets/"):
                name = path.rsplit("/", 1)[-1]
                route.fulfill(
                    body=(STATIC / name).read_bytes(),
                    content_type="text/css" if name.endswith(".css") else "text/javascript",
                )
            elif path == "/v1/reference-targets":
                route.fulfill(json=catalog)
            elif path == "/v1/reviewed-documents":
                route.fulfill(json={"items": []})
            elif path == "/v1/generation-status":
                route.fulfill(
                    json={"configured": False, "request_timeout_seconds": 30, "label": "问答未配置"}
                )
            elif path == "/v1/base-requirements":
                calls["base"].append(route.request.post_data_json)
                if len(calls["base"]) == 1:
                    held_base.append(route)
                else:
                    updated = deepcopy(base)
                    updated["requirements"][0]["date_events"][0]["display_text"] = (
                        "新 A 必着 2026-12-02"
                    )
                    route.fulfill(json=updated)
            elif path.endswith("/evidence"):
                calls["evidence"] += 1
                if calls["evidence"] == 1:
                    route.fulfill(status=503, json={"code": "unavailable"})
                else:
                    route.fulfill(json=evidence)
            elif path.endswith("/reports"):
                request = route.request.post_data_json
                calls["reports"].append(request)
                if len(calls["reports"]) == 1:
                    held_report_error.append(route)
                elif len(calls["reports"]) == 3:
                    held_report.append(route)
                else:
                    route.fulfill(json=_slice_report_for(request, report))
            elif path == "/v1/applicant-comparison":
                request = route.request.post_data_json
                calls["comparison"].append(request)
                response = _comparison_for(request, comparison)
                if len(calls["comparison"]) == 1:
                    response["target"]["school_name"] = "另一所学校"
                route.fulfill(json=response)
            else:
                route.abort()

        page.route("**/*", route_request)
        page.goto("http://ui02.test/app")
        page.locator("#school-select option").nth(2).wait_for(state="attached")
        _select_legacy(page)
        page.locator("#requirements-submit").click()
        page.wait_for_function("document.querySelector('#requirements-submit').disabled")
        page.locator("#requirements-submit").evaluate("element => element.click()")
        assert len(calls["base"]) == 1
        _select_slice(page)
        page.locator("#requirements-submit").click()
        page.locator("#requirements-retry").wait_for(state="visible")
        assert "无法加载" in page.locator("#target-status").inner_text()
        assert page.locator("#reference-report").is_hidden()
        page.locator("#requirements-retry").click()
        page.locator(".materials-section .requirement-card").first.wait_for()
        assert calls["evidence"] == 2
        assert "当前资料尚未覆盖日期" in page.locator(".key-dates-section").inner_text()
        page.locator("#step-2-panel .reference-generate").click()
        page.wait_for_function(
            "document.querySelector('#step-2-panel .reference-generate').disabled"
        )
        assert "正在整理" in page.locator("#reference-inline-status").inner_text()
        page.locator("#step-2-panel .reference-generate").evaluate("button => button.click()")
        assert len(calls["reports"]) == 1
        held_report_error[0].fulfill(status=503, json={"code": "unavailable"})
        page.wait_for_function(
            "document.querySelector('#reference-inline-status').textContent.includes('失败')"
        )
        assert page.locator("#reference-report").is_hidden()
        assert page.locator("#step-2-panel .reference-generate").inner_text() == "重试生成报告"
        page.locator("#step-2-panel .reference-generate").click()
        page.locator("#reference-report").wait_for(state="visible")
        assert "已打开" in page.locator("#reference-inline-status").inner_text()
        assert len(calls["reports"]) == 2
        assert calls["reports"][0]["employment"] == calls["reports"][1]["employment"]
        page.locator("#reference-close").click()
        page.locator(".overview-cta").click()
        page.locator("#slice-current-employed").select_option("yes")
        assert page.locator("#reference-report-body").inner_text() == ""
        page.locator("#comparison-submit").click()
        page.wait_for_function("document.querySelector('#comparison-submit').disabled")
        assert len(calls["reports"]) == 3
        page.locator("#slice-current-employed").select_option("no")
        page.locator("#comparison-submit").click()
        page.locator("#readiness-panel.slice-readiness").wait_for(state="visible")
        assert len(calls["reports"]) == 4
        assert calls["reports"][2]["employment"]["currently_employed_in_organization"] is True
        assert calls["reports"][3]["employment"]["currently_employed_in_organization"] is False
        try:
            held_report[0].fulfill(json=_slice_report_for(calls["reports"][2], report))
        except Exception:  # The edited profile aborted this request.
            pass
        assert "目前任职否" in page.locator("#comparison-output").inner_text()
        assert "目前任职是" not in page.locator("#comparison-output").inner_text()
        assert (
            "本条规则不适用，不能推定一般性免交" in page.locator("#comparison-output").inner_text()
        )
        page.locator("#edit-target").click()
        page.locator("#school-select").select_option("school-one")
        page.locator("#intake-select").select_option("doc-one:2027:4")
        page.locator("#college-select").select_option("org")
        page.locator("#department-select").select_option("program")
        page.locator("#route-select").select_option("a_schedule")
        page.locator("#requirements-submit").click()
        page.locator(".key-dates-section .date-conclusion").get_by_text(
            "新 A 必着 2026-12-02", exact=True
        ).wait_for()
        assert len(calls["base"]) == 2
        try:
            held_base[0].fulfill(json=base)
        except Exception:  # Browser correctly aborted the obsolete request.
            pass
        assert "新 A 必着 2026-12-02" in page.locator("#requirements-output").inner_text()
        assert "当前已覆盖的 3 个材料主题" not in page.locator("#requirements-output").inner_text()
        assert page.locator("#reference-report").is_hidden()
        page.locator(".overview-cta").click()
        page.locator('[data-material-code="address_label"]').select_option("available")
        page.locator("#comparison-submit").click()
        page.locator("#comparison-retry").wait_for(state="visible")
        assert page.locator("#readiness-panel").is_hidden()
        page.locator("#comparison-retry").click()
        page.locator("#readiness-panel").wait_for(state="visible")
        assert len(calls["comparison"]) == 2
        assert calls["comparison"][0]["target"]["document_id"] == "doc-one"
        assert errors == []
        browser.close()
