"""Replay a slow comparison closed by X or Esc using saved real responses."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
OUT = ROOT / "docs/onboarding/exam01-evidence"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def replay(browser, width: int, height: int, close_with: str) -> dict:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        permissions=["clipboard-read", "clipboard-write"],
    )
    page = context.new_page()
    errors: list[str] = []
    pending = []
    posts = 0
    slow = True
    page.on("pageerror", lambda error: errors.append(str(error)))
    catalog = (ROOT / "docs/onboarding/prep01-evidence/reference-targets.json").read_bytes()
    base = (OUT / "cs-april-response.json").read_bytes()
    comparison = (ROOT / "docs/onboarding/prep01-evidence/isct-comparison.json").read_bytes()

    def route_request(route):
        nonlocal posts
        path = urlparse(route.request.url).path
        if path == "/app":
            route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=(STATIC / "advanced.html").read_bytes(),
            )
        elif path.startswith("/assets/") and (STATIC / path.rsplit("/", 1)[1]).is_file():
            file = STATIC / path.rsplit("/", 1)[1]
            route.fulfill(
                status=200,
                content_type="text/javascript" if file.suffix in {".js", ".mjs"} else "text/css",
                body=file.read_bytes(),
            )
        elif path == "/v1/reference-targets":
            route.fulfill(status=200, content_type="application/json", body=catalog)
        elif path == "/v1/base-requirements":
            route.fulfill(status=200, content_type="application/json", body=base)
        elif path == "/v1/generation-status":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"schema_version": "1.0", "status": "offline"}),
            )
        elif path == "/v1/applicant-comparison":
            posts += 1
            if slow:
                pending.append(route)
            else:
                route.fulfill(status=200, content_type="application/json", body=comparison)
        else:
            route.fulfill(status=404, body="not replayed")

    page.route("http://127.0.0.1:18641/**", route_request)
    assert page.goto("http://127.0.0.1:18641/app").status == 200
    for select, value in (
        ("#school-select", "isct"),
        ("#demo-degree-select", "master"),
        ("#intake-select", "isct_2027_4_2026_9_master:2027:4"),
        ("#college-select", "情報理工学院"),
        ("#department-select", "情報工学系"),
        ("#route-select", "b_schedule"),
    ):
        page.locator(select).select_option(value)
    page.locator("#requirements-submit").click()
    page.locator(".exam-arrangement").wait_for(state="visible")
    page.locator("#requirements-continue").click()
    page.locator("#demo-completion-state").select_option("expected")
    page.locator("#edit-requirements").click()
    trigger = page.locator("#step-2-panel .reference-generate")
    trigger.click()
    dialog = page.locator("#reference-report")
    dialog.wait_for(state="visible")
    with page.expect_request("**/v1/applicant-comparison"):
        dialog.get_by_role("button", name="核对个人情况并生成所选报告").click()
    page.wait_for_timeout(50)
    assert posts == 1 and len(pending) == 1
    if close_with == "x":
        page.locator("#reference-close").click()
    else:
        page.keyboard.press("Escape")
    dialog.wait_for(state="hidden")
    trigger.click()
    dialog.wait_for(state="visible")
    assert posts == 1
    for theme in ("关键时间", "材料与待办", "其他已加载要求"):
        option = dialog.get_by_label(theme)
        if option.is_checked():
            option.uncheck()
    dialog.get_by_label("考试安排").check()
    page.locator("#reference-copy").click()
    exam_text = page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
    assert "2026年8月18日" in exam_text and "材料准备清单" not in exam_text
    assert posts == 1
    label = f"{width}-{close_with}"
    page.screenshot(path=str(OUT / f"r11-close-pending-{label}.png"))

    slow = False
    late_status = 503 if close_with == "x" else 200
    try:
        pending.pop().fulfill(
            status=late_status,
            content_type="application/json",
            body=comparison if late_status == 200 else b"{}",
        )
        late_delivery = "delivered"
    except Error:
        late_delivery = "aborted_by_browser"
    page.wait_for_timeout(50)
    assert "个人对照失败" not in page.locator("#reference-report-status").inner_text()
    assert "个人情况已核对" not in page.locator("#reference-report-status").inner_text()
    assert page.locator("#reference-copy").is_enabled()
    page.locator("#reference-copy").click()
    assert page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n") == exam_text

    dialog.get_by_label("材料与待办").check()
    assert page.locator("#reference-copy").is_disabled()
    dialog.get_by_role("button", name="核对个人情况并生成所选报告").click()
    page.get_by_text("个人情况已核对，可查看和复制所选报告。", exact=True).wait_for()
    assert posts == 2 and page.locator("#reference-copy").is_enabled()
    page.locator("#reference-close").click()
    trigger.click()
    assert posts == 2 and page.locator("#reference-copy").is_enabled()
    assert not errors, errors
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    context.close()
    return {
        "viewport": width,
        "closed_with": close_with,
        "late_status": late_status,
        "late_delivery": late_delivery,
        "posts_after_close": 1,
        "posts_after_explicit_retry": posts,
        "reopened_without_waiting": True,
    }


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        results = [
            replay(browser, width, height, close_with)
            for width, height in ((1440, 900), (390, 844))
            for close_with in ("x", "esc")
        ]
        browser.close()
    (OUT / "r11-close-pending.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
