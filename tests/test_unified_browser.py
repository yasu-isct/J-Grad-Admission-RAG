"""Synthetic browser checks for the unified page; no local KB or model is opened."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "src" / "jgrad_admission_rag" / "service" / "static"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
pytestmark = pytest.mark.skipif(not EDGE.exists(), reason="local browser executable unavailable")


def _fixture():
    target = {
        "target_id": "fixed-target",
        "institution_id": "synthetic-two",
        "organization_id": "organization",
        "program_id": "program",
        "degree_level": "master",
        "admission_cycle": 2027,
        "selection_route_id": "general-ordinary",
        "examination_schedule_id": "A",
        "intake": {"year": 2027, "month": 4},
    }
    catalog = {
        "schema_version": "1.0",
        "items": [
            {
                "entry_id": "legacy-one",
                "kind": "legacy_applicant",
                "availability": "ready",
                "institution_name": "第一所学校",
                "capabilities": {
                    "applicant_check": True,
                    "evidence_browse": True,
                    "reference_report": True,
                },
                "legacy_catalog": {
                    "school_id": "school-one",
                    "school_name": "第一所学校",
                    "degrees": [
                        {
                            "degree_id": "master",
                            "degree_name": "修士课程",
                            "intakes": [
                                {
                                    "document_id": "doc-one",
                                    "year": 2027,
                                    "month": 4,
                                    "intake_name": "2027 年 4 月",
                                    "colleges": [
                                        {
                                            "college_id": "org",
                                            "college_name": "学院",
                                            "departments": [
                                                {
                                                    "department_id": "program",
                                                    "department_name": "专业",
                                                    "application_routes": [
                                                        {
                                                            "route_id": "a_schedule",
                                                            "route_name": "A 日程",
                                                        }
                                                    ],
                                                }
                                            ],
                                        }
                                    ],
                                },
                                {
                                    "document_id": "doc-one",
                                    "year": 2026,
                                    "month": 9,
                                    "intake_name": "2026 年 9 月",
                                    "colleges": [
                                        {
                                            "college_id": "org",
                                            "college_name": "学院",
                                            "departments": [
                                                {
                                                    "department_id": "program",
                                                    "department_name": "专业",
                                                    "application_routes": [],
                                                }
                                            ],
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                },
            },
            {
                "entry_id": "slice-two",
                "kind": "reviewed_material_slice",
                "availability": "ready",
                "institution_name": "第二所学校",
                "organization_name": "研究科",
                "program_name": "固定专攻",
                "snapshot_id": "a" * 64,
                "capabilities": {
                    "applicant_check": False,
                    "evidence_browse": True,
                    "reference_report": True,
                },
                "target": target,
                "request_profile_target": {
                    "graduate_school_or_college": "研究科",
                    "department_or_program": "固定专攻",
                    "application_route": "ordinary",
                },
            },
        ],
    }
    source = {
        "document_id": "doc-one",
        "school_name": "第一所学校",
        "intake_name": "2027 年 4 月",
        "official_title": "官方文件",
        "official_text": "公式原文",
        "source_url": "https://example.edu/file.pdf",
        "pages": [4],
        "limitation": "固定范围",
        "highlights": [],
        "local_pdf_url": "/documents/doc-one/source.pdf",
    }
    base = {
        "schema_version": "1.0",
        "target": {
            "school_name": "第一所学校",
            "degree_name": "修士课程",
            "intake_name": "2027 年 4 月",
            "college_name": "学院",
            "department_name": "专业",
            "application_route_name": "A 日程",
        },
        "coverage_statement": "部分审核范围",
        "limitation_statement": "仍需官方确认",
        "requirements": [
            {
                "requirement_id": "one",
                "category": "dates",
                "title": "出愿日期",
                "description": "截止日期",
                "reviewed_summary": "必须在期限内到达",
                "official_status": "required",
                "deadline": "2026-12-01 17:00",
                "evidence": [source],
                "date_events": [
                    {
                        "label": "截止",
                        "display_text": "2026-12-01 17:00",
                        "precision": "minute",
                        "unknown_fields": ["截止后补交是否受理"],
                        "uncertainty_note": "仅审核到达时间",
                        "evidence": [source],
                    }
                ],
                "limitation": "只涵盖当前批次",
            },
            {
                "requirement_id": "two",
                "category": "language",
                "title": "英语成绩",
                "description": "成绩类型待确认",
                "official_status": "needs_information",
                "evidence": [source],
                "date_events": [],
                "limitation": "未覆盖分数换算",
            },
        ],
    }
    comparison = {
        "schema_version": "1.0",
        "target": base["target"],
        "comparison_statement": "保守对照",
        "partial_checklist_statement": "仅供准备",
        "limitation_statement": "不作资格判断",
        "counts": {"total": 1, "recorded": 0, "action_required": 1, "review_required": 0},
        "items": [
            {
                "title": "英语成绩单",
                "comparison_status": "needs_information",
                "description": "尚缺信息",
                "action_group": "action_required",
                "next_action": "单独联系招生办公室核对下一步",
                "official_status": "required",
                "preparation_status": "not_yet",
                "evidence": [source],
                "limitation": "不能据此判定个人资格",
            }
        ],
    }
    evidence = {
        "schema_version": "1.0",
        "snapshot_id": "a" * 64,
        "target": target,
        "limitations_zh": ["历史资料，仅部分材料"],
        "topics": [
            {
                "topic_id": "topic",
                "material_name_zh": "计划书",
                "context_note_zh": "在职条件",
                "records": [
                    {
                        "record_id": "record",
                        "role": "basis",
                        "stage": "application",
                        "source_title": "第二所学校官方文件",
                        "physical_page": 8,
                        "printed_page_label": "7",
                        "official_source_url": "https://example.edu/two.pdf",
                        "scope_note_zh": "固定范围",
                        "official_heading_path": ["材料"],
                        "fragments": [{"quote_text": "提出が必要"}],
                    }
                ],
            }
        ],
    }
    report = {
        "schema_version": "1.0",
        "slice_id": "slice-two",
        "snapshot_id": "a" * 64,
        "markdown": "# 原始报告\n条件未知；不能推定免交。\n第二所学校官方文件 · 物理页 8 · 公式引用",
        "report": {
            "status": "evaluated",
            "target": target,
            "limitations_zh": ["历史资料"],
            "topic_results": [
                {
                    "material_name_zh": "计划书",
                    "disposition": "needs_information",
                    "condition_status": "needs_information",
                    "explanation_zh": "条件未知",
                    "missing_fields": ["employment.currently_employed_in_organization"],
                    "limitations_zh": ["不能推定免交"],
                    "basis_citation_keys": ["C1"],
                    "context_citation_keys": [],
                }
            ],
            "evidence_inventory": [
                {
                    "citation_key": "C1",
                    "record_id": "record",
                    "quote_text": "提出が必要",
                    "source_title": "第二所学校官方文件",
                    "physical_pages": [8],
                }
            ],
        },
    }
    return catalog, base, comparison, evidence, report


def test_unified_page_explicit_actions_and_state_isolation(tmp_path):
    catalog, base, comparison, evidence, report = _fixture()
    calls = {"base": [], "comparison": [], "reports": [], "qa": []}
    delayed_evidence = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(
            "Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => {window.copied = text}}});"
        )

        def route_request(route):
            path = urlparse(route.request.url).path
            if path == "/app":
                route.fulfill(body=(STATIC / "app.html").read_bytes(), content_type="text/html")
            elif (
                path.startswith("/assets/unified")
                or path == "/assets/reviewed-material-presentation.mjs"
            ):
                name = path.rsplit("/", 1)[-1]
                media = "text/css" if name.endswith(".css") else "text/javascript"
                route.fulfill(body=(STATIC / name).read_bytes(), content_type=media)
            elif path == "/v1/reference-targets":
                route.fulfill(json=catalog)
            elif path == "/v1/base-requirements":
                calls["base"].append(route.request.post_data_json)
                route.fulfill(json=base)
            elif path == "/v1/applicant-comparison":
                calls["comparison"].append(route.request.post_data_json)
                route.fulfill(json=comparison)
            elif path.endswith("/evidence"):
                delayed_evidence.append(route)
            elif path.endswith("/reports"):
                calls["reports"].append(route.request.post_data_json)
                route.fulfill(json=report)
            elif path == "/v1/natural-language-answers":
                calls["qa"].append(route.request.post_data_json)
                route.fulfill(status=503, json={"code": "unavailable"})
            else:
                route.abort()

        page.route("**/*", route_request)
        page.goto("http://unified.test/app")
        page.locator("#uw-school option").nth(1).wait_for(state="attached")
        assert page.locator("#uw-school option").count() == 2
        assert page.locator("#uw-intake option").count() == 2
        assert calls == {"base": [], "comparison": [], "reports": [], "qa": []}

        page.locator("#uw-load").click()
        page.get_by_text("出愿日期", exact=True).wait_for()
        page.screenshot(path=str(tmp_path / "isct-mobile.png"), full_page=True)
        assert len(calls["base"]) == 1
        assert not calls["comparison"] and not calls["reports"]
        page.locator("#uw-generate").click()
        page.locator("#uw-report").wait_for(state="visible")
        page.screenshot(path=str(tmp_path / "isct-report.png"), full_page=True)
        assert not calls["comparison"] and not calls["reports"]
        page.locator("#uw-copy").click()
        assert "公式原文" in page.evaluate("window.copied")
        page.locator("#uw-report [data-close]").click()

        page.locator("#uw-profile-details > summary").click()
        page.locator("#uw-profile-credential_basis").select_option("ui_unknown")
        assert page.locator("#uw-report").is_hidden()
        page.locator("#uw-generate").click()
        page.locator("#uw-report").wait_for(state="visible")
        assert len(calls["comparison"]) == 1
        preview = page.locator("#uw-report-body").inner_text()
        page.locator("#uw-copy").click()
        copied = page.evaluate("window.copied")
        for value in (
            "保守对照",
            "单独联系招生办公室核对下一步",
            "不能据此判定个人资格",
            "官方适用性：需要提交／满足对应条件时适用",
            "自报准备状态：尚未取得",
            "截止后补交是否受理",
            "精度 minute",
            "仅审核到达时间",
        ):
            assert value in preview and value in copied
        page.locator("#uw-report [data-close]").click()
        page.locator("#uw-generate").click()
        page.locator("#uw-report").wait_for(state="visible")
        assert len(calls["comparison"]) == 1
        page.locator("#uw-report [data-close]").click()

        page.locator("#uw-school").select_option("slice-two")
        assert page.locator("#uw-report").is_hidden()
        assert page.locator("#uw-question").is_disabled()
        assert "暂不支持" in page.locator("#uw-qa-status").inner_text()
        page.locator("#uw-load").click()
        page.wait_for_function(
            "document.querySelector('#uw-coverage-tag').textContent === '正在加载'"
        )
        assert len(delayed_evidence) == 1
        page.locator("#uw-employment-current").select_option("yes")
        delayed_evidence.pop().fulfill(json=evidence)
        page.get_by_text("计划书", exact=True).wait_for()
        page.screenshot(path=str(tmp_path / "slice-mobile.png"), full_page=True)
        assert page.locator("#uw-coverage-tag").inner_text().startswith("第二所学校")
        assert not calls["reports"] and not calls["qa"]
        page.locator("#uw-generate").click()
        page.locator("#uw-report").wait_for(state="visible")
        page.screenshot(path=str(tmp_path / "slice-report.png"), full_page=True)
        assert len(calls["reports"]) == 1
        assert calls["reports"][0]["employment"]["currently_employed_in_organization"] is True
        page.locator("#uw-copy").click()
        assert "# 原始报告" in page.evaluate("window.copied")
        assert "不能推定免交" in page.evaluate("window.copied")
        page.locator("#uw-report [data-close]").click()
        page.locator("#uw-school").select_option("legacy-one")
        assert page.locator("#uw-generate").is_disabled()
        assert not calls["qa"]
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert errors == []
        browser.close()


def test_unified_question_displays_source_scope_and_actual_boundaries():
    catalog, base, _, _, _ = _fixture()
    questions = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def response_for(question):
            fallback = question == "fallback"
            zero_hits = question == "zero hits"
            unsupported = question == "partial unsupported"
            no_result = question == "no safe result"
            return {
                "summary": f"处理概况 {question}",
                "delivery": {"source": "fallback" if fallback else "offline"},
                "result": None
                if no_result
                else {
                    "local_scope_statement": "仅覆盖本地已审核的申请材料",
                    "official_source_url": "https://example.edu/official.pdf",
                    "local_pdf_url": "/documents/doc-one/source.pdf",
                    "answer": {
                        "answer": f"参考正文 {question}",
                        "missing_information": ["还缺申请人的具体成绩"],
                        "limitations": [
                            "本地未命中可引用片段" if zero_hits else "不能判断最终资格"
                        ],
                    },
                },
                "missing_context": ["尚待确认考试日期"],
                "unsupported_parts": ["院外课程要求" if unsupported else "暂不覆盖住宿问题"],
                "subanswers": [{"status": "no_clear_evidence", "message": "该分项没有清晰依据"}],
            }

        def route_request(route):
            path = urlparse(route.request.url).path
            if path == "/app":
                route.fulfill(body=(STATIC / "app.html").read_bytes(), content_type="text/html")
            elif (
                path.startswith("/assets/unified")
                or path == "/assets/reviewed-material-presentation.mjs"
            ):
                name = path.rsplit("/", 1)[-1]
                media = "text/css" if name.endswith(".css") else "text/javascript"
                route.fulfill(body=(STATIC / name).read_bytes(), content_type=media)
            elif path == "/v1/reference-targets":
                route.fulfill(json=catalog)
            elif path == "/v1/base-requirements":
                route.fulfill(json=base)
            elif path == "/v1/natural-language-answers":
                question = route.request.post_data_json["question"]
                questions.append(question)
                route.fulfill(json=response_for(question))
            else:
                route.abort()

        page.route("**/*", route_request)
        page.goto("http://unified.test/app")
        page.locator("#uw-school option").first.wait_for(state="attached")
        page.locator("#uw-load").click()
        page.get_by_text("出愿日期", exact=True).wait_for()
        for question in (
            "normal",
            "zero hits",
            "fallback",
            "partial unsupported",
            "no safe result",
        ):
            page.locator("#uw-question").fill(question)
            page.locator("#uw-ask").click()
            output = page.locator("#uw-qa-result")
            if question == "no safe result":
                page.get_by_text("处理概况 no safe result").wait_for()
                assert "本次没有可安全展示的引用回答" in output.inner_text()
                assert "参考正文 partial unsupported" not in output.inner_text()
                assert output.locator("a").count() == 0
                assert "尚待确认考试日期" in output.inner_text()
                continue
            page.get_by_text(f"参考正文 {question}").wait_for()
            for value in (
                "仅覆盖本地已审核的申请材料",
                "还缺申请人的具体成绩",
                "尚待确认考试日期",
                "该分项没有清晰依据",
            ):
                assert value in output.inner_text()
            assert output.locator('a[href="https://example.edu/official.pdf"]').count() == 1
            assert output.locator('a[href="/documents/doc-one/source.pdf"]').count() == 1
            assert (
                "本地未命中可引用片段" if question == "zero hits" else "不能判断最终资格"
            ) in output.inner_text()
            if question == "fallback":
                assert "在线整理不可用" in output.inner_text()
            if question == "partial unsupported":
                assert "院外课程要求" in output.inner_text()
        assert questions == [
            "normal",
            "zero hits",
            "fallback",
            "partial unsupported",
            "no safe result",
        ]
        assert errors == []
        browser.close()
