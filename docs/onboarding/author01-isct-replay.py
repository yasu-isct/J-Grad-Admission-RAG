"""Saved real Science Tokyo exam response on the current four-step page; zero HTTP.

All browser traffic is intercepted. This is a presentation/clipboard regression,
not a fresh verification of the official exam facts or the real backend.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/onboarding/author01-evidence"
OLD = ROOT / "docs/onboarding/exam02b-evidence"
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def main():
    payload = json.loads((OLD / "computer-science-base-v2.json").read_bytes())
    overlay = json.loads((OLD / "review-v2-exam-overlays.json").read_bytes())
    payload["examination_information"] = overlay["computer-science-base-v2.json"]
    target = payload["examination_information"]["target_identity"]
    journal = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        for width in (1440, 390):
            context = browser.new_context(
                viewport={"width": width, "height": 844},
                permissions=["clipboard-read", "clipboard-write"],
            )
            page = context.new_page()
            requests, errors = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def route_request(route):
                path = urlparse(route.request.url).path
                if route.request.method == "POST":
                    assert path == "/v1/base-requirements"
                    sent = route.request.post_data_json
                    assert sent == {key: target[key] for key in sent}
                    requests.append(sent)
                    route.fulfill(json=payload)
                elif path == "/app/advanced":
                    route.fulfill(
                        body=(STATIC / "advanced.html").read_bytes(), content_type="text/html"
                    )
                elif path.startswith("/assets/"):
                    filename = path.rsplit("/", 1)[-1]
                    route.fulfill(
                        body=(STATIC / filename).read_bytes(),
                        content_type="text/css" if filename.endswith(".css") else "text/javascript",
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
                        json={"configured": False, "request_timeout_seconds": 60, "label": "离线"}
                    )
                else:
                    route.abort()

            page.route("**/*", route_request)
            page.goto("http://127.0.0.1:8016/app/advanced")
            page.locator("#school-select").select_option("isct")
            page.locator("#intake-select").select_option(
                f"{target['document_id']}:{target['intake']['year']}:{target['intake']['month']}"
            )
            page.locator("#college-select").select_option(target["college_id"])
            page.locator("#department-select").select_option(target["department_id"])
            page.locator("#route-select").select_option(target["application_route"])
            page.locator("#requirements-submit").click()
            page.locator(".exam-arrangement").wait_for(state="visible")
            assert page.locator(".application-flow > .flow-step").count() == 4
            page.locator("#step-2-panel .reference-generate").click()
            page.locator("#reference-report").wait_for(state="visible")
            for checkbox in page.locator(".reader-report-options input").all():
                if checkbox.is_checked():
                    checkbox.uncheck()
            page.locator(".reader-report-options label", has_text="考试安排").locator(
                "input"
            ).check()
            page.locator("#reference-copy").click()
            page.wait_for_function(
                "() => document.querySelector('#reference-report-status').textContent.includes('已复制')"
            )
            copied = page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
            assert "情報工学系" in copied and "2026" in copied and "B 日程" in copied
            assert "申请小论文" not in copied and "fact_id" not in copied
            (OUT / f"isct-exam-{width}-copy.txt").write_text(copied + "\n", encoding="utf-8")
            page.screenshot(path=str(OUT / f"isct-exam-{width}-report.png"))
            assert not errors and len(requests) == 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            journal.append(
                {
                    "width": width,
                    "actual_product_post": 0,
                    "intercepted_product_post": 1,
                    "saved_real_response": "computer-science-base-v2.json + accepted review-v2 overlay",
                    "copy_sha256": sha256(copied.encode()).hexdigest(),
                    "no_horizontal_overflow": True,
                }
            )
            context.close()
        browser.close()
    assert journal[0]["copy_sha256"] == journal[1]["copy_sha256"]
    (OUT / "isct-replay-journal.json").write_text(
        json.dumps(journal, indent=2) + "\n", encoding="utf-8"
    )
    print("Science Tokyo exam report saved-response replay/copy desktop+mobile; 0 actual POST")


if __name__ == "__main__":
    main()
