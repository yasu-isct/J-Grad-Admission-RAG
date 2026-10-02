"""Replay saved EXAM-02B real responses on the current four-step page.

Every GET and POST is intercepted. Saved real base responses are paired in
memory with current direct examination projections from the protected assets.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


HERE = Path(__file__).resolve().parent
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
ROOT = HERE.parents[2]
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
# Loopback is a secure clipboard context; all requests are fulfilled by route_post.
ORIGIN = "http://127.0.0.1:8010"
CASES = {
    "system-control": ("システム制御系", "system-control-base-v2.json"),
    "math": ("数学系", "math-base-v2.json"),
    "materials": ("材料系", "materials-base-v2.json"),
    "architecture": ("建築学系", "architecture-base-v2.json"),
    "transdisciplinary": ("融合理工学系", "transdisciplinary-base-v2.json"),
    "social-human": ("社会・人間科学系", "social-human-base-v2.json"),
    "computer-science": ("情報工学系", "computer-science-base-v2.json"),
}
OVERLAYS = json.loads((HERE / "review-v2-exam-overlays.json").read_text(encoding="utf-8"))


def expected_copies() -> dict[str, str]:
    raw = (HERE / "review-exam-only-report-copy-samples.txt").read_text(encoding="utf-8")
    chunks = re.split(r"(?=^===== \d+\. )", raw, flags=re.M)
    result = {}
    for chunk in chunks:
        if not chunk.startswith("===== "):
            continue
        first, body = chunk.split("\n", 1)
        department = first.split(". ", 1)[1].split(" / ", 1)[0]
        result[department] = body.strip() + "\n"
    return result


def choose(page, target: dict) -> None:
    page.locator("#school-select").select_option("isct")
    page.locator("#demo-degree-select").select_option(target["degree_id"])
    intake = target["intake"]
    page.locator("#intake-select").select_option(
        f"{target['document_id']}:{intake['year']}:{intake['month']}"
    )
    page.locator("#college-select").select_option(target["college_id"])
    page.locator("#department-select").select_option(target["department_id"])
    if target["application_route"]:
        page.locator("#route-select").select_option(target["application_route"])


def run_case(browser, name: str, department: str, filename: str, copy: str) -> dict:
    payload = json.loads((HERE / filename).read_text(encoding="utf-8"))
    payload["examination_information"] = OVERLAYS[filename]
    target = payload["examination_information"]["target_identity"]
    assert target["department_id"] == department
    requests = []
    errors = []
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        permissions=["clipboard-read", "clipboard-write"],
    )
    page = context.new_page()
    page.set_default_timeout(30000)
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route_post(route) -> None:
        request = route.request
        if request.method == "GET":
            path = urlparse(request.url).path
            if path == "/app/advanced":
                route.fulfill(
                    body=(STATIC / "advanced.html").read_bytes(), content_type="text/html"
                )
            elif path.startswith("/assets/") and path.rsplit("/", 1)[-1] in {
                "app.css",
                "overview.js",
                "app.js",
                "unified-core.mjs",
            }:
                filename = path.rsplit("/", 1)[-1]
                route.fulfill(
                    body=(STATIC / filename).read_bytes(),
                    content_type=("text/css" if filename.endswith(".css") else "text/javascript"),
                )
            elif path == "/v1/reference-targets":
                route.fulfill(
                    body=(
                        ROOT / "docs/onboarding/prep01-evidence/reference-targets.json"
                    ).read_bytes(),
                    content_type="application/json",
                )
            elif path == "/v1/generation-status":
                route.fulfill(
                    body='{"configured":false,"request_timeout_seconds":60,"label":"离线"}',
                    content_type="application/json",
                )
            else:
                route.abort()
                raise AssertionError(f"unexpected GET: {path}")
            return
        if request.method != "POST":
            route.abort()
            raise AssertionError(f"unexpected method: {request.method}")
        requests.append({"method": request.method, "url": request.url})
        if "/v1/base-requirements?" not in request.url:
            route.abort()
            raise AssertionError(f"unexpected product POST: {request.url}")
        sent = request.post_data_json
        assert sent == {key: target[key] for key in sent}, (sent, target)
        route.fulfill(
            status=200,
            content_type="application/json; charset=utf-8",
            body=json.dumps(payload, ensure_ascii=False),
        )

    page.route("**/*", route_post)
    assert page.goto(f"{ORIGIN}/app/advanced").status == 200
    assert page.locator(".application-flow > .flow-step").count() == 4
    choose(page, target)
    page.locator("#requirements-submit").click()
    page.locator(".exam-arrangement").wait_for(state="visible")
    assert page.locator(".exam-arrangement").count() == 1
    exam_text = page.locator(".exam-arrangement").inner_text()
    assert "学校公布的 A/B 日程" in exam_text
    assert "本人" in exam_text or "适用" in exam_text or "目录为 B 日程" in exam_text, (
        name,
        exam_text[:500],
    )
    assert "fact_type" not in exam_text and "section_path" not in exam_text
    if name == "social-human":
        assert "不举行笔试" in exam_text
    else:
        assert "考什么" in exam_text
    page.locator(".requirements-jump button", has_text="考试安排").click()
    assert page.locator(".exam-arrangement").evaluate("e => e === document.activeElement")
    page.locator(".exam-arrangement summary").click()
    assert page.locator(".exam-arrangement details").get_attribute("open") is not None
    source_button = page.locator(".exam-arrangement button", has_text="查看 A 日程原文")
    source_button.click()
    assert page.locator("#evidence-drawer").is_visible()
    assert "官方" in page.locator("#evidence-drawer").inner_text()
    page.locator("#drawer-close").click()
    assert page.evaluate("document.activeElement.textContent.includes('查看 A 日程原文')")
    page.locator("#step-2-panel .reference-generate").click()
    page.locator("#reference-report").wait_for(state="visible")
    exam_option = page.locator(".reader-report-options label", has_text="考试安排").locator("input")
    assert not exam_option.is_checked()
    assert page.locator(".reader-report-section h3", has_text="考试安排").count() == 0
    for checkbox in page.locator(".reader-report-options input").all():
        if checkbox.is_checked():
            checkbox.uncheck()
    exam_option.check()
    assert "考试安排" in page.locator("#reference-report-body").inner_text()
    page.locator("#reference-copy").click()
    copied = page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
    assert copied + "\n" == copy, (name, copied, copy)
    page.locator("#reference-close").click()
    page.locator("#step-2-panel .reference-generate").click()
    assert page.locator("#reference-report").is_visible()
    page.locator("#reference-close").click()
    page.locator("#step-2-panel .reference-generate").click()
    exam_option = page.locator(".reader-report-options label", has_text="考试安排").locator("input")
    for checkbox in page.locator(".reader-report-options input").all():
        if checkbox.is_checked():
            checkbox.uncheck()
    exam_option.check()
    page.screenshot(path=str(HERE / f"{name}-report-desktop.png"), full_page=False)
    page.locator("#reference-close").click()
    page.evaluate("""() => { const el = document.querySelector('.exam-arrangement');
      window.scrollTo({top: scrollY + el.getBoundingClientRect().top - 180, behavior: 'instant'}); }""")
    page.screenshot(path=str(HERE / f"{name}-step2-desktop.png"), full_page=False)
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("""() => { const el = document.querySelector('.exam-arrangement');
      window.scrollTo({top: scrollY + el.getBoundingClientRect().top - 180, behavior: 'instant'}); }""")
    page.screenshot(path=str(HERE / f"{name}-step2-mobile.png"), full_page=False)
    page.locator(".exam-arrangement .source-actions").scroll_into_view_if_needed()
    page.screenshot(path=str(HERE / f"{name}-step2-mobile-bottom.png"), full_page=False)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator("#step-2-panel .reference-generate").click()
    for checkbox in page.locator(".reader-report-options input").all():
        if checkbox.is_checked():
            checkbox.uncheck()
    page.locator(".reader-report-options label", has_text="考试安排").locator("input").check()
    page.screenshot(path=str(HERE / f"{name}-report-mobile.png"), full_page=False)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not errors, errors
    assert len(requests) == 1, requests
    context.close()
    return {
        "case": name,
        "department": department,
        "saved_response": filename,
        "intercepted_product_post": len(requests),
        "actual_product_post": 0,
        "copy_sha256": hashlib.sha256(copied.encode("utf-8")).hexdigest(),
        "desktop_and_mobile_no_overflow": True,
        "page_errors": errors,
    }


def main() -> None:
    assert EDGE.is_file()
    copies = expected_copies()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        results = [
            run_case(browser, name, department, filename, copies[department])
            for name, (department, filename) in CASES.items()
        ]
        browser.close()
    (HERE / "browser-replay-journal.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(results)} saved-real-response four-step browser cases; 0 product POST")


if __name__ == "__main__":
    main()
