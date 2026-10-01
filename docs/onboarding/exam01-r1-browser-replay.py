"""Check report recovery with saved responses; no product service is started."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
EVIDENCE = ROOT / "docs/onboarding/exam01-evidence"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def run_viewport(browser, width: int, height: int, label: str) -> dict:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        permissions=["clipboard-read", "clipboard-write"],
    )
    page = context.new_page()
    errors: list[str] = []
    comparison_posts = 0
    comparison_status = 503
    page.on("pageerror", lambda error: errors.append(str(error)))
    catalog = (ROOT / "docs/onboarding/prep01-evidence/reference-targets.json").read_bytes()
    base = (EVIDENCE / "cs-april-response.json").read_bytes()
    comparison = (ROOT / "docs/onboarding/prep01-evidence/isct-comparison.json").read_bytes()

    def route_request(route):
        nonlocal comparison_posts
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
            comparison_posts += 1
            route.fulfill(
                status=comparison_status,
                content_type="application/json",
                body=comparison if comparison_status == 200 else b"{}",
            )
        else:
            route.fulfill(status=404, body="not replayed")

    page.route("http://127.0.0.1:18640/**", route_request)
    assert page.goto("http://127.0.0.1:18640/app").status == 200
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
    page.locator("#demo-credential-basis").select_option("university_graduation")
    page.locator("#edit-requirements").click()
    page.locator("#step-2-panel .reference-generate").click()
    dialog = page.locator("#reference-report")
    dialog.wait_for(state="visible")
    assert comparison_posts == 0
    assert page.locator("#reference-copy").is_disabled()
    assert "需先核对个人情况" in dialog.inner_text()

    for theme in ("关键时间", "材料与待办", "其他已加载要求"):
        option = dialog.get_by_label(theme)
        if option.is_checked():
            option.uncheck()
    dialog.get_by_label("考试安排").check()
    assert comparison_posts == 0
    assert page.locator("#reference-copy").is_enabled()
    page.locator("#reference-copy").click()
    exam_text = page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
    assert "2026年8月18日" in exam_text and "待补材料" not in exam_text
    assert "考试安排" in dialog.inner_text()
    assert comparison_posts == 0

    dialog.get_by_label("材料与待办").check()
    assert page.locator("#reference-copy").is_disabled()
    dialog.get_by_role("button", name="核对个人情况并生成所选报告").click()
    page.get_by_text("个人对照失败；所选个人报告尚未生成。", exact=False).wait_for()
    assert comparison_posts == 1
    assert page.locator("#reference-copy").is_disabled()
    dialog.get_by_label("材料与待办").uncheck()
    assert page.locator("#reference-copy").is_enabled()
    page.locator("#reference-copy").click()
    assert page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n") == exam_text
    page.screenshot(path=str(EVIDENCE / f"r1-report-recovery-{label}.png"))

    if label == "desktop":
        comparison_status = 200
        dialog.get_by_label("关键时间").check()
        dialog.get_by_label("材料与待办").check()
        dialog.get_by_role("button", name="核对个人情况并生成所选报告").click()
        page.get_by_text("个人情况已核对，可查看和复制所选报告。", exact=True).wait_for()
        assert comparison_posts == 2
        assert page.locator("#reference-copy").is_enabled()
        page.locator("#reference-copy").click()
        personal_text = page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
        assert "关键时间" in personal_text and "材料准备清单" in personal_text
        assert "考试安排" in personal_text
        page.locator("#reference-close").click()
        page.locator("#step-2-panel .reference-generate").click()
        assert comparison_posts == 2
        assert page.locator("#reference-copy").is_enabled()
        page.locator("#reference-close").click()
        page.locator("#edit-target").click()
        page.locator("#school-select").select_option("gsfs-complex-2027-a")
        assert page.locator(".exam-arrangement").count() == 0
        assert page.locator("#step-2-panel .reference-generate").is_disabled()
        (EVIDENCE / "r1-report-personal-copy.txt").write_text(
            personal_text + "\n", encoding="utf-8"
        )

    assert not errors, errors
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    context.close()
    return {
        "viewport": label,
        "comparison_posts": comparison_posts,
        "exam_only_posts": 0,
        "exam_copy_chars": len(exam_text),
        "failure_kept_exam_copy": True,
    }


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        results = [
            run_viewport(browser, 1440, 900, "desktop"),
            run_viewport(browser, 390, 844, "mobile"),
        ]
        browser.close()
    (EVIDENCE / "r1-report-recovery.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
