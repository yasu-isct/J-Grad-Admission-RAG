"""Replay the same saved real PREP-02 responses in desktop and phone UI."""

from __future__ import annotations

import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright

TREE = Path(__file__).resolve().parents[2]
STATIC = TREE / "src/jgrad_admission_rag/service/static"
OUT = TREE / "docs/onboarding/prep02-evidence"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


class ReplayHandler(BaseHTTPRequestHandler):
    posts = 0

    def log_message(self, *_args):
        return

    def do_POST(self):
        type(self).posts += 1
        self.send_error(500, "Unexpected product POST")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/app":
            file = STATIC / "advanced.html"
            content_type = "text/html; charset=utf-8"
        elif path.startswith("/assets/") and "/" not in path[len("/assets/") :]:
            file = STATIC / path[len("/assets/") :]
            content_type = (
                "text/javascript; charset=utf-8"
                if file.suffix in {".js", ".mjs"}
                else "text/css; charset=utf-8"
            )
        elif path == "/v1/reference-targets":
            file = OUT / "reference-targets.json"
            content_type = "application/json; charset=utf-8"
        else:
            self.send_error(503, "Outside saved-response replay")
            return
        if not file.is_file():
            self.send_error(404)
            return
        content = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def case(browser, url: str, width: int, label: str, base: dict, comparison: dict):
    context = browser.new_context(
        viewport={"width": width, "height": 900}, permissions=["clipboard-read", "clipboard-write"]
    )
    page = context.new_page()
    errors = []
    posts = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def fulfill(route):
        kind = route.request.url.rsplit("/", 1)[-1]
        posts.append((kind, route.request.post_data_json))
        route.fulfill(json=base if kind == "base-requirements" else comparison)

    page.route("**/v1/base-requirements", fulfill)
    page.route("**/v1/applicant-comparison", fulfill)
    assert page.goto(f"{url}/app").status == 200
    for selector, value in (
        ("school-select", "isct"),
        ("demo-degree-select", "master"),
        ("intake-select", "isct_2027_4_2026_9_master:2027:4"),
        ("college-select", "情報理工学院"),
        ("department-select", "情報工学系"),
        ("route-select", "b_schedule"),
    ):
        page.locator(f"#{selector}").select_option(value)
    page.locator("#requirements-submit").click()
    page.locator(".overview-cta").click()
    education = page.locator('.profile-group[data-profile-group="education"]')
    if not education.evaluate("element => element.open"):
        education.locator("summary").click()
    page.locator("#demo-credential-basis").select_option("university_graduation")
    page.locator("#demo-completion-state").select_option("expected")
    page.locator("#demo-expected-completion-date").fill("2027-03-20")
    submission = page.locator('.profile-group[data-profile-group="submission"]')
    if not submission.evaluate("element => element.open"):
        submission.locator("summary").click()
    page.locator("#demo-online-steps").select_option("true")
    page.locator("#demo-dispatched-date").fill("2026-06-09")
    page.locator("#demo-arrival-date").fill("")
    page.screenshot(path=str(OUT / f"{label}-step3.png"), full_page=True)
    page.locator("#comparison-submit").click()
    page.locator(".application-preparation-group").wait_for(state="visible")
    request = posts[-1][1]
    assert request["application_preparation"]["materials_dispatched_date"] == "2026-06-09"
    assert request["application_preparation"]["materials_arrival_date"] is None
    assert request["application_preparation"]["expected_completion_date"] == "2027-03-20"
    assert [kind for kind, _ in posts] == ["base-requirements", "applicant-comparison"]
    assert page.locator(".application-preparation-group .comparison-card").count() == 3
    assert "寄出不等于按时送达" in page.locator(".application-preparation-group").inner_text()
    assert page.locator(".comparison-card[data-category='materials']").count() == 5
    assert page.locator("#comparison-output .comparison-card").count() == int(
        page.locator("#count-total").inner_text()
    )
    priority = page.locator("#priority-actions")
    for link in priority.locator("a").all():
        target = page.locator(link.get_attribute("href"))
        assert target.count() == 1
        link.click()
        assert target.is_visible() and target.evaluate(
            "element => document.activeElement === element"
        )
    page.locator('input[name="readiness-filter"][value="review_required"]').check()
    assert page.locator(".application-preparation-group .comparison-card:visible").count() >= 1
    page.locator('input[name="readiness-filter"][value="all"]').check()
    page.locator(".application-preparation-group").scroll_into_view_if_needed()
    page.screenshot(path=str(OUT / f"{label}-step4.png"), full_page=True)
    page.screenshot(path=str(OUT / f"{label}-step4-focus.png"))
    page.locator(
        ".application-preparation-group .requirement-evidence-actions button"
    ).first.click()
    assert page.locator("#evidence-drawer[open]").count() == 1
    assert page.locator("#drawer-title").inner_text() == "官方依据"
    assert page.locator("#drawer-content").inner_text().strip()
    page.locator("#drawer-close").click()
    page.locator("#readiness-panel .reference-generate").click()
    page.locator("#reference-report[open]").wait_for(state="visible")
    options = page.locator('.reader-report-options input[type="checkbox"]')
    options.nth(0).uncheck()
    options.nth(2).uncheck()
    materials = page.locator("#reference-report-body").inner_text()
    assert "毕业与提交提醒" in materials and "寄出不等于按时送达" in materials
    page.screenshot(path=str(OUT / f"{label}-report-materials.png"), full_page=True)
    page.screenshot(path=str(OUT / f"{label}-report-materials-focus.png"))
    page.locator("#reference-copy").click()
    copied = (
        page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n").replace("\r", "\n")
    )
    assert "毕业与提交提醒" in copied and "寄出不等于按时送达" in copied
    (OUT / f"{label}-materials-copy.txt").write_text(copied, encoding="utf-8")
    options.nth(0).check()
    options.nth(1).uncheck()
    dates = page.locator("#reference-report-body").inner_text()
    assert "关键时间" in dates and "毕业与提交提醒" not in dates
    assert "寄出不等于按时送达" not in dates
    page.screenshot(path=str(OUT / f"{label}-report-dates.png"), full_page=True)
    page.locator("#reference-close").click()
    page.locator("#edit-applicant").click()
    page.locator("#demo-dispatched-date").fill("2026-06-10")
    page.locator("#demo-arrival-date").fill("2026-06-09")
    assert "不能早于寄出日期" in page.locator("#demo-submission-hint").inner_text()
    page.locator("#comparison-submit").click()
    assert len(posts) == 2
    page.locator("#edit-target").click()
    page.locator("#school-select").select_option("gsfs-complex-2027-a")
    assert page.locator("#demo-dispatched-date").input_value() == ""
    assert page.locator("#demo-expected-completion-date").input_value() == ""
    assert not errors, errors
    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    context.close()
    return {
        "width": width,
        "saved_response_posts": len(posts),
        "overflow": overflow,
        "materials_copy_sha256": hashlib.sha256(copied.encode("utf-8")).hexdigest(),
    }


def main():
    journal = json.loads((OUT / "journal.json").read_text(encoding="utf-8"))
    assert journal["service_startups"] == 1 and journal["service_stopped"]
    assert journal["base_comparison_posts"] == 3 and journal["assets_unchanged"]
    base = json.loads((OUT / "base.json").read_text(encoding="utf-8"))
    comparison = json.loads(
        (OUT / "dispatched_unknown_arrival-response.json").read_text(encoding="utf-8")
    )
    ReplayHandler.posts = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), ReplayHandler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
            url = f"http://127.0.0.1:{server.server_port}"
            cases = [
                case(browser, url, width, name, base, comparison)
                for width, name in ((1440, "desktop"), (390, "mobile"))
            ]
            browser.close()
        assert ReplayHandler.posts == 0
    finally:
        server.shutdown()
        worker.join(timeout=5)
    assert not any(item["overflow"] for item in cases)
    assert cases[0]["materials_copy_sha256"] == cases[1]["materials_copy_sha256"]
    journal["browser_replay"] = {
        "cases": cases,
        "product_service_starts": 0,
        "product_api_posts": 0,
    }
    (OUT / "journal.json").write_text(
        json.dumps(journal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
