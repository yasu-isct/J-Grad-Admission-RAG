from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from playwright.sync_api import expect, sync_playwright

import run_ux03_real_acceptance as ux03


ROOT = ux03.ROOT
OUTPUT_ROOT = ROOT / "outputs" / "ux04"
SCREENSHOTS = OUTPUT_ROOT / "browser"
OUTPUT = OUTPUT_ROOT / "acceptance.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run UX-04 Step 3 acceptance through installed jgrad-demo and a real browser."
    )
    parser.add_argument("--pdf", required=True, help="Absolute fixed reviewed PDF path.")
    parser.add_argument("--workspace", default=str((OUTPUT_ROOT / "workspace").resolve()))
    parser.add_argument("--browser-executable")
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args()


def _open_group(page, key: str) -> None:
    group = page.locator(f'.profile-group[data-profile-group="{key}"]')
    if not group.evaluate("element => element.open"):
        group.locator("summary").click()
    expect(group).to_have_attribute("open", "")


def _comparison_requests(page) -> list[dict]:
    requests: list[dict] = []

    def capture(request) -> None:
        if request.url.endswith("/v1/applicant-comparison") and request.method == "POST":
            requests.append(request.post_data_json)

    page.on("request", capture)
    return requests


def _browser_flow(browser, base_url: str, viewport_name: str, width: int) -> dict:
    page = browser.new_page(viewport={"width": width, "height": 1000})
    all_requests: list[str] = []
    page.on("request", lambda request: all_requests.append(request.url))
    comparison_requests = _comparison_requests(page)
    try:
        ux03._load_target(page, base_url)
        evidence_trigger = page.locator('.date-event[data-event-type="arrival_deadline"] button')
        evidence_trigger.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#evidence-drawer[open]")).to_be_visible()
        pdf_href = page.locator("#drawer-content .pdf-source-link").first.get_attribute("href")
        assert pdf_href == f"/documents/{ux03.DOCUMENT_ID}/source.pdf#page=9"
        page.keyboard.press("Escape")
        assert evidence_trigger.evaluate("element => document.activeElement === element")

        page.locator(".overview-cta").click()
        expect(page.locator("#applicant-heading")).to_be_focused()
        expect(page.locator(".profile-group")).to_have_count(4)
        states = page.locator(".profile-group-state").all_text_contents()
        assert states == ["待填写"] * 4
        open_count = page.locator(".profile-group[open]").count()
        assert open_count == (1 if width == 390 else 4)
        assert page.locator(".profile-state-guide").is_visible()
        assert page.locator(".profile-submit-help").is_visible()

        english_summary = page.locator('.profile-group[data-profile-group="english"] summary')
        english_summary.focus()
        original_open = page.locator('.profile-group[data-profile-group="english"]').evaluate(
            "element => element.open"
        )
        page.keyboard.press("Enter")
        assert (
            page.locator('.profile-group[data-profile-group="english"]').evaluate(
                "element => element.open"
            )
            is not original_open
        )
        assert english_summary.evaluate("element => document.activeElement === element")
        page.keyboard.press("Enter")
        assert (
            page.locator('.profile-group[data-profile-group="english"]').evaluate(
                "element => element.open"
            )
            is original_open
        )

        initial_screenshot = SCREENSHOTS / f"ux04-{viewport_name}-step3-initial.png"
        page.locator("#applicant-panel").screenshot(path=initial_screenshot)

        page.locator("#comparison-submit").click()
        expect(page.locator("#readiness-heading")).to_be_focused()
        assert len(comparison_requests) == 1
        empty = comparison_requests[-1]["applicant"]
        assert empty["credential_basis"] is None
        assert empty["english_test_kind"] is None
        assert empty["japanese_background"] is None
        assert {item["preparation"] for item in empty["materials"]} == {"unknown"}
        assert "不符合" not in page.locator("#comparison-output").inner_text()

        page.locator("#edit-applicant").click()
        expect(page.locator("#applicant-heading")).to_be_focused()
        for group in ("education", "english", "japanese", "materials"):
            _open_group(page, group)
        page.locator("#demo-credential-basis").select_option("ui_unknown")
        page.locator("#demo-completion-state").select_option("ui_not_applicable")
        page.locator("#demo-english-kind").select_option("ui_unknown")
        page.locator("#demo-english-report").select_option("ui_not_applicable")
        page.locator("#demo-japanese-background").select_option("ui_not_applicable")
        page.locator('[data-material-code="address_label"]').select_option("unknown")
        page.locator('[data-material-code="application_form"]').select_option("ui_not_applicable")
        assert (
            page.locator(
                '.profile-group[data-profile-group="education"] .profile-group-state'
            ).inner_text()
            == "仍需确认"
        )
        page.locator("#comparison-submit").click()
        expect(page.locator("#readiness-heading")).to_be_focused()
        assert len(comparison_requests) == 2
        unknown = comparison_requests[-1]["applicant"]
        assert all(
            unknown[field] is None
            for field in (
                "credential_basis",
                "completion_state",
                "english_test_kind",
                "english_official_report_available",
                "japanese_background",
            )
        )
        assert {item["preparation"] for item in unknown["materials"]} == {"unknown"}

        page.locator("#edit-applicant").click()
        _open_group(page, "english")
        page.locator("#demo-english-score").fill("800")
        page.locator("#demo-english-date").fill("2026-05-01")
        expect(page.locator("#english-link-hint")).to_contain_text("服务端还需要考试类型")
        assert page.locator("#comparison-submit").is_enabled()
        page.locator("#demo-english-kind").select_option("toeic_lr")
        expect(page.locator("#english-link-hint")).to_contain_text(
            "成绩、日期和官方成绩单可暂时留空"
        )
        page.locator("#demo-english-report").select_option("false")
        page.locator("#demo-credential-basis").select_option("university_graduation")
        page.locator("#demo-completion-state").select_option("expected")
        page.locator("#demo-japanese-background").select_option("studied")
        page.locator('[data-material-code="address_label"]').select_option("available")
        page.locator('[data-material-code="application_form"]').select_option("not_yet")
        filled_screenshot = SCREENSHOTS / f"ux04-{viewport_name}-step3-filled.png"
        page.locator("#applicant-panel").screenshot(path=filled_screenshot)
        page.locator("#comparison-submit").click()
        expect(page.locator("#readiness-heading")).to_be_focused()
        assert len(comparison_requests) == 3
        filled = comparison_requests[-1]["applicant"]
        assert filled["english_test_kind"] == "toeic_lr"
        assert filled["english_score"] == 800
        assert filled["english_test_date"] == "2026-05-01"
        assert filled["english_official_report_available"] is False
        assert filled["materials"][0]["preparation"] == "available"
        assert filled["materials"][1]["preparation"] == "not_yet"
        material_cards = page.locator(".comparison-card").filter(has_text="宛名ラベル")
        assert material_cards.count() >= 1
        assert "官方适用性：" in material_cards.first.inner_text()
        assert "个人准备状态：已有" in material_cards.first.inner_text()
        assert "学校已受理" not in material_cards.first.inner_text()
        assert "日语情况已记录" in page.locator("#comparison-output").inner_text()
        assert "证据不足" in page.locator("#comparison-output").inner_text()
        checklist_screenshot = SCREENSHOTS / f"ux04-{viewport_name}-checklist.png"
        page.locator("#readiness-panel").screenshot(path=checklist_screenshot)

        page.locator("#edit-target").click()
        expect(page.locator("#demo-heading")).to_be_focused()
        page.locator("#department-select").select_option("機械系")
        expect(page.locator("#step-2-panel")).to_be_hidden()
        assert page.locator("#demo-english-score").input_value() == ""
        assert page.locator("#demo-credential-basis").input_value() == ""
        assert page.locator('[data-material-code="address_label"]').input_value() == ""
        page.locator("#requirements-submit").click()
        expect(page.locator(".overview-target")).to_contain_text("機械系")
        page.locator(".overview-cta").click()
        expect(page.locator("#applicant-heading")).to_be_focused()
        assert page.locator(".profile-group-state").all_text_contents() == ["待填写"] * 4

        overflow = page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert overflow is False
        origin = f"{base_url}/"
        assert all(url.startswith(origin) for url in all_requests)
        return {
            "viewport": viewport_name,
            "initial_open_groups": open_count,
            "empty_unknown_and_filled_requests": len(comparison_requests),
            "keyboard_summary_and_focus": True,
            "target_change_cleared_inputs": True,
            "checklist_regression": True,
            "pdf_page_link": pdf_href,
            "horizontal_overflow": overflow,
            "external_requests": [],
            "screenshots": [
                item.relative_to(ROOT).as_posix()
                for item in (initial_screenshot, filled_screenshot, checklist_screenshot)
            ],
        }
    finally:
        page.close()


def main() -> None:
    args = _arguments()
    pdf = Path(args.pdf)
    if not pdf.is_absolute() or not pdf.is_file():
        raise SystemExit("FAIL: pass an existing absolute fixed PDF path")
    expected_hash = ux03.load_demo_config().identity.source_pdf_sha256
    actual_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise SystemExit("FAIL: real PDF SHA-256 does not match the reviewed edition")

    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    port = ux03._free_port()
    command = [
        ux03._entry_point(),
        "--pdf",
        str(pdf),
        "--workspace",
        str(Path(args.workspace)),
        "--port",
        str(port),
    ]
    if args.rebuild:
        command.append("--rebuild")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        ready = ux03._wait_ready(f"{base_url}/v1/health/ready", process)
        http = ux03._http_checks(base_url, pdf, expected_hash)
        with sync_playwright() as playwright:
            options: dict[str, str | bool] = {"headless": True}
            chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
            if args.browser_executable:
                options["executable_path"] = args.browser_executable
            elif chrome.is_file():
                options["executable_path"] = str(chrome)
            browser = playwright.chromium.launch(**options)
            try:
                records = [
                    _browser_flow(browser, base_url, "desktop-1440", 1440),
                    _browser_flow(browser, base_url, "mobile-390", 390),
                ]
                browser_version = browser.version
            finally:
                browser.close()
        result = {
            "schema_version": "1.0",
            "issue": 144,
            "service": "installed jgrad-demo -> uvicorn -> FastAPI",
            "test_http_handler_used": False,
            "pdf_sha256": actual_hash,
            "ready": ready,
            "http": http,
            "browser": {"name": "Chromium", "version": browser_version},
            "records": records,
        }
        OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"PASS: UX-04 real acceptance written to {OUTPUT}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
