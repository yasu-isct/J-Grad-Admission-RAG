"""Replay the saved real CS base response; no product service or model is started."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
OUT = ROOT / "docs/onboarding/exam01-evidence"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    catalog = (ROOT / "docs/onboarding/prep01-evidence/reference-targets.json").read_text(
        encoding="utf-8"
    )
    base = (OUT / "cs-april-response.json").read_text(encoding="utf-8")
    responses = {
        "/v1/reference-targets": catalog,
        "/v1/base-requirements": base,
        "/v1/generation-status": json.dumps({"schema_version": "1.0", "status": "offline"}),
    }
    errors = []
    requests = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            permissions=["clipboard-read", "clipboard-write"],
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append((request.method, request.url)))

        def route_request(route):
            path = urlparse(route.request.url).path
            if path == "/app":
                route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=(STATIC / "advanced.html").read_bytes(),
                )
            elif path.startswith("/assets/") and (STATIC / path.rsplit("/", 1)[1]).is_file():
                file = STATIC / path.rsplit("/", 1)[1]
                kind = "text/javascript" if file.suffix in {".js", ".mjs"} else "text/css"
                route.fulfill(status=200, content_type=kind, body=file.read_bytes())
            elif path in responses:
                route.fulfill(
                    status=200, content_type="application/json; charset=utf-8", body=responses[path]
                )
            else:
                route.fulfill(status=404, body="not replayed")

        page.route("http://127.0.0.1:18640/**", route_request)
        assert page.goto("http://127.0.0.1:18640/app").status == 200
        page.locator("#school-select").select_option("isct")
        page.locator("#demo-degree-select").select_option("master")
        page.locator("#intake-select").select_option("isct_2027_4_2026_9_master:2027:4")
        page.locator("#college-select").select_option("情報理工学院")
        page.locator("#department-select").select_option("情報工学系")
        page.locator("#route-select").select_option("b_schedule")
        page.locator("#requirements-submit").click()
        card = page.locator(".exam-arrangement")
        card.wait_for(state="visible")
        assert "2026年8月18日" in card.inner_text()
        assert "900分" in card.inner_text()
        assert "A组" in card.inner_text() and "C组" in card.inner_text()
        card.get_by_role("button", name="查看官方原文").click()
        assert "8 月 18 日" in page.locator("#drawer-content").inner_text()
        page.locator("#drawer-close").click()
        assert card.get_by_role("button", name="查看官方原文").evaluate(
            "el => el === document.activeElement"
        )
        card.get_by_role("button", name="查看英语证明要求").click()
        assert page.locator(".english-section").evaluate("el => el === document.activeElement")
        page.screenshot(path=str(OUT / "exam01-step2-desktop.png"), full_page=True)
        card.screenshot(path=str(OUT / "exam01-card-desktop.png"))
        page.locator("#step-2-panel .reference-generate").click()
        dialog = page.locator("#reference-report")
        dialog.wait_for(state="visible")
        page.locator("#reference-copy").click()
        before = page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
        (OUT / "report-default.txt").write_text(before + "\n", encoding="utf-8")
        assert "考试安排" not in before
        for label in dialog.locator(".reader-report-options label").all():
            checkbox = label.locator("input")
            if checkbox.is_checked():
                checkbox.uncheck()
        dialog.get_by_label("考试安排").check()
        page.locator("#reference-copy").click()
        exams = page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
        (OUT / "report-exams-only.txt").write_text(exams + "\n", encoding="utf-8")
        assert "2026年8月18日" in exams and "待补材料" not in exams
        page.screenshot(path=str(OUT / "exam01-report-desktop.png"))
        page.locator("#reference-close").click()
        page.set_viewport_size({"width": 390, "height": 844})
        card.scroll_into_view_if_needed()
        card.evaluate(
            "el => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 180)"
        )
        page.screenshot(path=str(OUT / "exam01-step2-mobile.png"), full_page=True)
        page.screenshot(path=str(OUT / "exam01-card-mobile.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.locator("#step-2-panel .reference-generate").click()
        dialog.get_by_label("关键时间").uncheck()
        dialog.get_by_label("材料与待办").uncheck()
        dialog.get_by_label("其他已加载要求").uncheck()
        dialog.get_by_label("考试安排").check()
        page.screenshot(path=str(OUT / "exam01-report-mobile.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert [method for method, url in requests if method == "POST" and "/v1/" in url] == [
            "POST"
        ]
        assert not errors, errors
        browser.close()
    print(
        "saved real-response replay: desktop/mobile card and report; one mocked base request; no product service"
    )


if __name__ == "__main__":
    main()
