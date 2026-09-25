"""Run the M9-05 browser acceptance against an already-running formal local service."""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8125")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parents[1] / "docs/assets",
    )
    args = parser.parse_args()
    if args.base_url not in {"http://127.0.0.1:8125", "http://localhost:8125"}:
        raise SystemExit("real browser acceptance is restricted to the reviewed loopback service")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True,
        )
        for width in (1440, 390):
            page = browser.new_page(viewport={"width": width, "height": 1100})
            page.goto(f"{args.base_url}/app", wait_until="networkidle")
            page.locator("#intake-select").select_option("isct_2027_4_2026_9_master:2027:4")
            page.locator("#college-select").select_option("情報理工学院")
            page.locator("#department-select").select_option("情報工学系")
            page.locator("#route-select").select_option("b_schedule")
            expect(page.locator("#requirements-submit")).to_be_enabled()
            page.locator("#requirements-submit").click()
            expect(page.locator("#grounded-question")).to_be_enabled()

            page.locator("#grounded-question").fill("出願期間と書類必着日はいつですか。")
            page.locator("#grounded-answer-submit").click()
            expect(page.locator(".grounded-claim")).to_have_count(1, timeout=30_000)
            expect(page.locator(".grounded-citations button")).to_have_count(2)
            first_citation = page.locator(".grounded-citations button").first
            first_citation.click()
            expect(page.locator("#evidence-drawer[open]")).to_be_visible()
            expect(page.locator(".pdf-source-link")).to_have_attribute(
                "href", "/documents/isct_2027_4_2026_9_master/source.pdf#page=9"
            )
            page.locator("#drawer-close").click()
            expect(first_citation).to_be_focused()
            assert not page.evaluate(
                "document.documentElement.scrollWidth > document.documentElement.clientWidth"
            )
            page.screenshot(
                path=output_dir / f"m9-grounded-rag-{width}.png",
                full_page=True,
            )

            page.locator("#grounded-question").fill(
                "募集要項にない学生寮の空室数を教えてください。"
            )
            page.locator("#grounded-answer-submit").click()
            expect(page.locator(".grounded-missing")).to_contain_text(
                "需要补充信息", timeout=30_000
            )
            expect(page.locator(".grounded-claim")).to_have_count(0)
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
