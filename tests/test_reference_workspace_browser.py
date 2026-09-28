"""Browser-executed state tests with synthetic API responses only."""

from __future__ import annotations

import json
from pathlib import Path
import socket
from threading import Thread
from time import monotonic, sleep

import uvicorn
import pytest

from jgrad_admission_rag.service import create_app
from jgrad_admission_rag.service.runtime import ServiceSettings
from tests.test_reference_workspace import _local_slice

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

STATIC = Path(__file__).parents[1] / "src" / "jgrad_admission_rag" / "service" / "static"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
pytestmark = pytest.mark.skipif(not EDGE.exists(), reason="local browser executable unavailable")


def test_reference_page_explicit_post_and_stale_response(tmp_path):
    catalog = {
        "schema_version": "1.0",
        "items": [
            {
                "entry_id": "legacy-isct",
                "kind": "legacy_applicant",
                "availability": "ready",
                "institution_name": "東京科学大学",
                "href": "/app",
            },
            {
                "entry_id": "synthetic-slice",
                "kind": "reviewed_material_slice",
                "availability": "ready",
                "institution_name": "合成大学",
                "organization_name": "合成研究科",
                "program_name": "合成専攻",
                "snapshot_id": "a" * 64,
                "revision": 1,
                "limitations_zh": ["历史部分切片"],
                "target": {
                    "target_id": "synthetic",
                    "institution_id": "synthetic",
                    "organization_id": "synthetic-grad",
                    "program_id": "synthetic-program",
                    "degree_level": "master",
                    "admission_cycle": 2027,
                    "selection_route_id": "general",
                    "examination_schedule_id": "A",
                    "intake": {"year": 2027, "month": 4},
                },
                "request_profile_target": {
                    "graduate_school_or_college": "synthetic-grad",
                    "department_or_program": "synthetic-program",
                    "application_route": "general",
                },
            },
        ],
    }
    evidence = {
        "snapshot_id": "a" * 64,
        "topics": [
            {
                "material_name_zh": "合成材料",
                "context_note_zh": "仅测试",
                "records": [
                    {
                        "role": "basis",
                        "stage": "application",
                        "source_title": "合成募集要项",
                        "physical_page": 2,
                        "printed_page_label": "1",
                        "scope_note_zh": "测试范围",
                        "official_heading_path": ["材料"],
                        "official_source_url": "https://example.edu/source.pdf",
                        "fragments": [{"fragment_role": "clause", "quote_text": "公式の合成原文"}],
                    }
                ],
            }
        ],
    }
    report = {
        "snapshot_id": "a" * 64,
        "markdown": "# 参考报告\n公式の合成原文\n物理页 2\n",
        "report": {
            "status": "evaluated",
            "topic_results": [
                {
                    "material_name_zh": "合成材料",
                    "disposition": "needs_information",
                    "explanation_zh": "需要更多信息",
                    "missing_fields": ["employment.retain_employment_at_enrollment"],
                }
            ],
        },
    }
    posts = []
    delayed = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.add_init_script(
            "Object.defineProperty(navigator, 'clipboard', {value: {writeText: async (text) => {if (window.failClipboard) throw new Error('denied'); window.copied = text}}});"
        )

        def route_request(route):
            url = route.request.url
            if url.endswith("/app/reference"):
                route.fulfill(
                    body=(STATIC / "reference.html").read_bytes(), content_type="text/html"
                )
            elif url.endswith("/assets/reference.js"):
                route.fulfill(
                    body=(STATIC / "reference.js").read_bytes(), content_type="text/javascript"
                )
            elif url.endswith("/assets/reference.css") or url.endswith("/assets/app.css"):
                name = "reference.css" if url.endswith("reference.css") else "app.css"
                route.fulfill(body=(STATIC / name).read_bytes(), content_type="text/css")
            elif url.endswith("/v1/reference-targets"):
                route.fulfill(json=catalog)
            elif url.endswith("/evidence"):
                route.fulfill(json=evidence)
            elif url.endswith("/reports"):
                posts.append(json.loads(route.request.post_data))
                delayed.append(route)
            else:
                route.abort()

        page.route("**/*", route_request)
        page.goto("http://reference.test/app/reference")
        page.wait_for_function("document.querySelector('#reference-select').options.length === 3")
        assert not posts
        page.locator("#reference-select").select_option("synthetic-slice")
        page.locator("#evidence-panel").wait_for(state="visible")
        assert page.get_by_text("公式の合成原文").count() == 1
        page.locator("#employment-select").select_option("yes")
        assert not posts
        page.locator("#generate-report").click()
        page.wait_for_function("document.querySelector('#generate-report').disabled")
        assert (
            len(posts) == 1 and posts[0]["employment"]["currently_employed_in_organization"] is True
        )
        page.locator("#retain-select").select_option("no")
        delayed.pop(0).fulfill(json=report)
        page.wait_for_timeout(50)
        assert page.locator("#report-output").is_hidden()
        page.locator("#generate-report").click()
        assert len(posts) == 2
        delayed.pop(0).fulfill(json=report)
        page.locator("#report-output").wait_for(state="visible")
        page.locator("#copy-report").click()
        page.wait_for_function("window.copied !== undefined")
        assert "合成大学" in page.evaluate("window.copied")
        assert "公式の合成原文" in page.evaluate("window.copied")
        page.screenshot(path=str(tmp_path / "synthetic-mobile.png"), full_page=True)
        page.evaluate("window.failClipboard = true")
        page.locator("#copy-report").click()
        page.locator("#copy-fallback").wait_for(state="visible")
        assert "公式の合成原文" in page.locator("#copy-fallback").input_value()
        page.locator("#generate-report").click()
        assert len(posts) == 3
        page.locator("#reference-select").select_option("legacy-isct")
        page.locator("#reference-select").select_option("synthetic-slice")
        page.locator("#evidence-panel").wait_for(state="visible")
        delayed.pop(0).fulfill(json=report)
        assert page.locator("#report-output").is_hidden()
        page.locator("#reference-select").select_option("legacy-isct")
        assert page.get_by_role("link", name="打开申请检查").get_attribute("href") == "/app"
        page.reload()
        page.wait_for_function("document.querySelector('#reference-select').options.length === 3")
        assert page.locator("#report-output").is_hidden()
        assert page.locator("#employment-select").input_value() == "unknown"
        assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        browser.close()


def test_browser_reaches_synthetic_http_backend(tmp_path):
    config_path, row, _, _ = _local_slice(tmp_path)
    app = create_app(ServiceSettings(reference_workspace_config_path=config_path))
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    worker = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    deadline = monotonic() + 10
    while not server.started and monotonic() < deadline:
        sleep(0.05)
    assert server.started
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.add_init_script(
                "Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => {window.copied = text}}});"
            )
            posts = []
            page.on(
                "request",
                lambda request: posts.append(request) if request.method == "POST" else None,
            )
            page.goto(f"http://127.0.0.1:{port}/app/reference")
            page.locator("#reference-select").select_option(row["slice_id"])
            page.locator("#evidence-panel").wait_for(state="visible")
            assert page.locator("#evidence-topics blockquote").count() == 2
            page.screenshot(path=str(tmp_path / "synthetic-desktop.png"), full_page=True)
            assert not posts
            page.locator("#generate-report").click()
            page.locator("#report-output").wait_for(state="visible")
            assert len(posts) == 1
            assert page.locator("#report-summary h4").count() == 1
            assert page.locator("#report-summary pre").count() == 1
            page.locator("#copy-report").click()
            page.wait_for_function("window.copied !== undefined")
            assert "合成大学" in page.evaluate("window.copied")
            page.screenshot(path=str(tmp_path / "synthetic-report.png"), full_page=True)
            assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
            browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
    assert not worker.is_alive()


def _race_entry(entry_id: str, snapshot_id: str) -> dict:
    return {
        "entry_id": entry_id,
        "kind": "reviewed_material_slice",
        "availability": "ready",
        "institution_name": "合成大学",
        "organization_name": "合成研究科",
        "program_name": entry_id,
        "snapshot_id": snapshot_id,
        "revision": 1,
        "limitations_zh": [],
        "target": {
            "target_id": entry_id,
            "degree_level": "master",
            "selection_route_id": "general",
            "admission_cycle": 2027,
            "examination_schedule_id": "A",
            "intake": {"year": 2027, "month": 4},
        },
        "request_profile_target": {
            "graduate_school_or_college": "synthetic-grad",
            "department_or_program": entry_id,
            "application_route": "general",
        },
    }


def _race_evidence(snapshot_id: str, quote: str) -> dict:
    return {
        "snapshot_id": snapshot_id,
        "topics": [
            {
                "material_name_zh": "合成材料",
                "context_note_zh": "仅测试",
                "records": [
                    {
                        "role": "basis",
                        "stage": "application",
                        "source_title": "合成募集要项",
                        "physical_page": 2,
                        "printed_page_label": "1",
                        "scope_note_zh": "测试范围",
                        "official_heading_path": ["材料"],
                        "official_source_url": "https://example.edu/source.pdf",
                        "fragments": [{"fragment_role": "clause", "quote_text": quote}],
                    }
                ],
            }
        ],
    }


def _wait_for_routes(page, routes: list, count: int) -> None:
    for _ in range(100):
        if len(routes) == count:
            return
        page.wait_for_timeout(10)
    assert len(routes) == count


@pytest.mark.parametrize("action", ["edit_condition", "generate_report"])
def test_delayed_evidence_survives_report_only_invalidation(action):
    catalog = {"items": [_race_entry("slice-a", "a" * 64)]}
    report = {
        "snapshot_id": "a" * 64,
        "report": {"status": "evaluated", "topic_results": []},
        "markdown": "# Synthetic report",
    }
    evidence_routes = []
    posts = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        page = browser.new_page(viewport={"width": 390, "height": 844})

        def route_request(route):
            path = route.request.url.split("reference.test", 1)[-1]
            if path == "/app/reference":
                route.fulfill(
                    body=(STATIC / "reference.html").read_bytes(), content_type="text/html"
                )
            elif path.startswith("/assets/"):
                name = path.removeprefix("/assets/")
                route.fulfill(
                    body=(STATIC / name).read_bytes(),
                    content_type="text/javascript" if name.endswith(".js") else "text/css",
                )
            elif path == "/v1/reference-targets":
                route.fulfill(json=catalog)
            elif path.endswith("/evidence"):
                evidence_routes.append(route)
            elif path.endswith("/reports"):
                posts.append(route.request.post_data_json)
                route.fulfill(json=report)
            else:
                route.abort()

        page.route("**/*", route_request)
        page.goto("http://reference.test/app/reference")
        page.locator("#reference-select").select_option("slice-a")
        _wait_for_routes(page, evidence_routes, 1)
        assert page.locator("#evidence-panel").is_hidden()
        assert "正在读取" in page.locator("#reference-status").inner_text()
        if action == "edit_condition":
            page.locator("#employment-select").select_option("yes")
            assert not posts
        else:
            page.locator("#generate-report").click()
            page.locator("#report-output").wait_for(state="visible")
            assert len(posts) == 1
        evidence_routes[0].fulfill(json=_race_evidence("a" * 64, "延迟返回的公式原文"))
        page.locator("#evidence-panel").wait_for(state="visible")
        assert page.locator("#evidence-topics blockquote").all_text_contents() == [
            "延迟返回的公式原文"
        ]
        assert "已加载 1 个材料主题" in page.locator("#reference-status").inner_text()
        assert len(evidence_routes) == 1
        assert len(posts) == (0 if action == "edit_condition" else 1)
        browser.close()


def test_evidence_a_b_a_rejects_stale_responses_and_reports_snapshot_error():
    catalog = {"items": [_race_entry("slice-a", "a" * 64), _race_entry("slice-b", "b" * 64)]}
    evidence_routes = []
    posts = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        page = browser.new_page()

        def route_request(route):
            path = route.request.url.split("reference.test", 1)[-1]
            if path == "/app/reference":
                route.fulfill(
                    body=(STATIC / "reference.html").read_bytes(), content_type="text/html"
                )
            elif path.startswith("/assets/"):
                name = path.removeprefix("/assets/")
                route.fulfill(
                    body=(STATIC / name).read_bytes(),
                    content_type="text/javascript" if name.endswith(".js") else "text/css",
                )
            elif path == "/v1/reference-targets":
                route.fulfill(json=catalog)
            elif path.endswith("/evidence"):
                evidence_routes.append(route)
            elif path.endswith("/reports"):
                posts.append(route.request.post_data_json)
                route.abort()
            else:
                route.abort()

        page.route("**/*", route_request)
        page.goto("http://reference.test/app/reference")
        selector = page.locator("#reference-select")
        selector.select_option("slice-a")
        _wait_for_routes(page, evidence_routes, 1)
        selector.select_option("slice-b")
        _wait_for_routes(page, evidence_routes, 2)
        selector.select_option("slice-a")
        _wait_for_routes(page, evidence_routes, 3)
        evidence_routes[2].fulfill(json=_race_evidence("a" * 64, "当前A原文"))
        page.locator("#evidence-panel").wait_for(state="visible")
        evidence_routes[0].fulfill(json=_race_evidence("a" * 64, "过期A原文"))
        evidence_routes[1].fulfill(json=_race_evidence("b" * 64, "过期B原文"))
        page.wait_for_timeout(50)
        assert page.locator("#evidence-topics blockquote").all_text_contents() == ["当前A原文"]
        assert "已加载 1 个材料主题" in page.locator("#reference-status").inner_text()
        selector.select_option("slice-b")
        _wait_for_routes(page, evidence_routes, 4)
        evidence_routes[3].fulfill(json=_race_evidence("c" * 64, "错误快照"))
        page.get_by_text("官方依据暂时不可用。").wait_for()
        assert page.locator("#evidence-panel").is_hidden()
        assert not posts
        browser.close()
