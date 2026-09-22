from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from playwright.sync_api import expect, sync_playwright

import run_ux03_real_acceptance as ux03
import run_ux04_real_acceptance as ux04


ROOT = ux03.ROOT
OUTPUT_ROOT = ROOT / "outputs" / "ux05"
SCREENSHOTS = OUTPUT_ROOT / "browser"
OUTPUT = OUTPUT_ROOT / "acceptance.json"
ENDPOINT = "/v1/applicant-comparison"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run UX-05 Step 4 acceptance through installed jgrad-demo and a real browser."
    )
    parser.add_argument("--pdf", required=True, help="Absolute fixed reviewed PDF path.")
    parser.add_argument("--workspace", default=str((OUTPUT_ROOT / "workspace").resolve()))
    parser.add_argument("--browser-executable")
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args()


def _submit_comparison(page) -> dict:
    with page.expect_response(
        lambda response: (
            response.url.endswith(ENDPOINT)
            and response.request.method == "POST"
            and response.status == 200
        )
    ) as response_info:
        page.locator("#comparison-submit").click()
    expect(page.locator("#readiness-heading")).to_be_focused()
    return response_info.value.json()


def _assert_summary(page, payload: dict) -> None:
    counts = payload["counts"]
    assert page.locator("#count-total").inner_text() == str(counts["total"])
    assert page.locator("#count-action").inner_text() == str(counts["action_required"])
    assert page.locator("#count-review").inner_text() == str(counts["review_required"])
    assert page.locator("#count-recorded").inner_text() == str(counts["recorded"])
    assert page.locator(".comparison-card").count() == counts["total"]
    assert page.locator(".comparison-group").first.get_attribute("data-action-group") == (
        "action_required" if counts["action_required"] else "review_required"
    )
    assert page.locator("#action-summary-heading").is_visible()
    assert page.locator("#priority-actions").is_visible()
    assert page.locator("#priority-actions").bounding_box()["y"] < 1000
    assert "已满足" not in page.locator("#readiness-panel").inner_text()
    assert "最终资格" in page.locator(".progress-boundary").inner_text()
    assert "材料实际到达" in page.locator(".progress-boundary").inner_text()
    assert page.locator(".personal-check input").count() == (
        counts["action_required"] + counts["review_required"]
    )


def _browser_flow(browser, base_url: str, name: str, width: int) -> dict:
    page = browser.new_page(viewport={"width": width, "height": 1000})
    all_requests: list[str] = []
    page.on("request", lambda request: all_requests.append(request.url))
    try:
        ux03._load_target(page, base_url)
        date_trigger = page.locator('.date-event[data-event-type="arrival_deadline"] button')
        date_trigger.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#evidence-drawer[open]")).to_be_visible()
        assert (
            page.locator("#drawer-content .pdf-source-link").first.get_attribute("href")
            == f"/documents/{ux03.DOCUMENT_ID}/source.pdf#page=9"
        )
        page.keyboard.press("Escape")
        assert date_trigger.evaluate("element => document.activeElement === element")

        page.locator(".overview-cta").click()
        empty = _submit_comparison(page)
        _assert_summary(page, empty)
        assert [
            item["official_status"] for item in empty["items"] if item["category"] == "materials"
        ] == ["required", "required", "needs_information", "needs_information", "needs_information"]
        assert all(
            item["action_group"] != "recorded"
            for item in empty["items"]
            if item["comparison_status"] == "needs_information"
        )
        empty_screenshot = SCREENSHOTS / f"ux05-{name}-empty-step4.png"
        page.locator("#readiness-panel").screenshot(path=empty_screenshot)
        filter_screenshot = SCREENSHOTS / f"ux05-{name}-filters.png"
        page.locator("#readiness-filters").screenshot(path=filter_screenshot)
        filter_boxes = [
            label.bounding_box() for label in page.locator("#readiness-filters label").all()
        ]
        assert all(box["height"] < 50 for box in filter_boxes), filter_boxes
        if width == 390:
            assert all(box["width"] > 100 for box in filter_boxes), filter_boxes

        count_snapshot = page.locator(".readiness-counts").inner_text()
        first_status = page.locator(".comparison-card .requirement-status").first.inner_text()
        checkbox = page.locator(".personal-check input").first
        checkbox.focus()
        page.keyboard.press("Space")
        assert checkbox.is_checked()
        assert (
            "已标记处理（仅个人记录）"
            in page.locator(".comparison-card .personal-progress").first.inner_text()
        )
        assert page.locator(".readiness-counts").inner_text() == count_snapshot
        assert (
            page.locator(".comparison-card .requirement-status").first.inner_text() == first_status
        )
        page.keyboard.press("Space")
        assert not checkbox.is_checked()
        checkbox.check()

        priority_link = page.locator("#priority-actions a").first
        priority_link.focus()
        page.keyboard.press("Enter")
        assert re.fullmatch(
            r"#comparison-(action_required|review_required)-\d+", page.evaluate("location.hash")
        )
        for group, field in (
            ("action_required", "action_required"),
            ("review_required", "review_required"),
            ("recorded", "recorded"),
        ):
            page.locator(f'#readiness-filters input[value="{group}"]').check()
            assert page.locator(".comparison-card:visible").count() == empty["counts"][field]
        page.locator('#readiness-filters input[value="all"]').check()

        evidence_button = page.locator(".comparison-card .actions button").first
        evidence_button.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#evidence-drawer[open]")).to_be_visible()
        assert page.locator("#drawer-content .official-web-link").is_visible()
        assert page.locator("#drawer-content .evidence-text").is_visible()
        step_four_pdf = (
            page.locator("#drawer-content .pdf-source-link").first.get_attribute("href")
            if page.locator("#drawer-content .pdf-source-link").count()
            else None
        )
        assert step_four_pdf is None or re.search(r"/source\.pdf#page=\d+$", step_four_pdf)
        page.keyboard.press("Escape")
        assert evidence_button.evaluate("element => document.activeElement === element")

        page.locator("#edit-applicant").click()
        expect(page.locator("#applicant-heading")).to_be_focused()
        assert page.locator(".personal-check input:checked").count() == 0
        ux04._open_group(page, "materials")
        page.locator('[data-material-code="address_label"]').select_option("available")
        partial = _submit_comparison(page)
        _assert_summary(page, partial)
        assert page.locator(".personal-check input:checked").count() == 0
        material = next(
            item for item in partial["items"] if item["item_id"].endswith("address_label")
        )
        assert material["preparation_status"] == "available"
        card = page.locator(".comparison-card").filter(has_text=material["title"]).first
        assert "官方适用性：" in card.inner_text()
        assert "个人准备状态：已有" in card.inner_text()

        page.locator("#edit-applicant").click()
        ux04._open_group(page, "education")
        page.locator("#demo-credential-basis").select_option("university_graduation")
        direct = _submit_comparison(page)
        _assert_summary(page, direct)
        assert all(
            item["official_status"] == "required"
            for item in direct["items"]
            if item["category"] == "materials"
        )
        assert page.locator(".personal-check input:checked").count() == 0

        page.locator("#edit-applicant").click()
        ux04._open_group(page, "education")
        page.locator("#demo-credential-basis").select_option("foreign_15_year_education")
        page.locator("#demo-completion-state").select_option("expected")
        review = _submit_comparison(page)
        _assert_summary(page, review)
        assert any(item["comparison_status"] == "needs_review" for item in review["items"])
        assert [
            item["official_status"] for item in review["items"] if item["category"] == "materials"
        ] == [
            "required",
            "required",
            "eligibility_review_path",
            "eligibility_review_path",
            "eligibility_review_path",
        ]
        assert page.locator(".personal-check input:checked").count() == 0
        review_card = page.locator(
            '.comparison-card[data-action-group="review_required"]:has(.requirement-status[data-status="needs_review"])'
        ).first
        review_checkbox = review_card.locator(".personal-check input")
        review_checkbox.check()
        assert "已标记处理（仅个人记录）" in review_card.inner_text()
        assert "需要学校／人工审核" in review_card.inner_text()
        review_screenshot = SCREENSHOTS / f"ux05-{name}-review-step4.png"
        page.locator("#readiness-panel").screenshot(path=review_screenshot)

        # No selectable target in this fixed PDF currently returns not_covered. Exercise
        # that display branch with the same real response shape, without claiming it came
        # from the HTTP service or changing any rule/API response.
        page.evaluate(
            """payload => {
              const displayFixture = structuredClone(payload);
              const item = displayFixture.items.find(entry => entry.comparison_status === 'needs_review');
              item.comparison_status = 'not_covered';
              item.next_action = '查看官方依据，并向学校人工确认当前未覆盖的条件。';
              renderComparison(displayFixture);
            }""",
            review,
        )
        uncovered_card = page.locator(
            '.comparison-card:has(.requirement-status[data-status="not_covered"])'
        ).first
        assert "当前未覆盖" in uncovered_card.inner_text()
        uncovered_card.locator(".personal-check input").check()
        assert "当前未覆盖" in uncovered_card.locator(".requirement-status").inner_text()
        assert "已满足" not in uncovered_card.inner_text()
        assert page.locator("#count-action").inner_text() == str(
            review["counts"]["action_required"]
        )
        assert page.locator("#count-review").inner_text() == str(
            review["counts"]["review_required"]
        )
        page.evaluate("payload => renderComparison(payload)", review)

        page.locator("#edit-target").click()
        expect(page.locator("#demo-heading")).to_be_focused()
        assert page.locator(".personal-check input:checked").count() == 0
        page.locator("#department-select").select_option("機械系")
        page.locator("#requirements-submit").click()
        page.locator(".overview-cta").click()
        reset = _submit_comparison(page)
        _assert_summary(page, reset)
        assert page.locator(".personal-check input:checked").count() == 0
        page.locator(".personal-check input").first.check()
        page.reload()
        assert page.locator(".personal-check input").count() == 0
        assert page.locator("#readiness-panel").is_hidden()

        assert not page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert all(url.startswith(f"{base_url}/") for url in all_requests)
        return {
            "viewport": name,
            "empty_counts": empty["counts"],
            "partial_counts": partial["counts"],
            "direct_material_counts": direct["counts"],
            "review_counts": review["counts"],
            "target_reset_counts": reset["counts"],
            "check_uncheck_isolated_from_system_counts": True,
            "edit_resubmit_refresh_reset": True,
            "keyboard_filter_focus_and_evidence": True,
            "supplemental_not_covered_display_fixture": True,
            "step_four_pdf_link": step_four_pdf,
            "horizontal_overflow": False,
            "external_requests": [],
            "screenshots": [
                empty_screenshot.relative_to(ROOT).as_posix(),
                filter_screenshot.relative_to(ROOT).as_posix(),
                review_screenshot.relative_to(ROOT).as_posix(),
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
            "issue": 146,
            "service": "installed jgrad-demo -> uvicorn -> FastAPI",
            "test_http_handler_used": False,
            "pdf_sha256": actual_hash,
            "ready": ready,
            "http": http,
            "browser": {"name": "Chromium", "version": browser_version},
            "records": records,
        }
        OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"PASS: UX-05 real acceptance written to {OUTPUT}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
