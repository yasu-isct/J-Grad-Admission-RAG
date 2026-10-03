"""Saved-response replay for AUTHOR-01; no real service or product POST is used."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
SAVED = ROOT / "docs/onboarding/author01-evidence"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
pytestmark = pytest.mark.skipif(not EDGE.exists(), reason="local browser executable unavailable")


@pytest.mark.parametrize("width", [1440, 390])
def test_essay_preparation_reuses_verified_conditions_after_explicit_recheck(width):
    def read(name):
        return json.loads((SAVED / name).read_bytes())

    catalog = read("live-catalog.json")
    evidence = read("live-evidence.json")
    report = read("live-desktop-report.json")
    entry_id = report["slice_id"]
    posts = []
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        try:
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(
                "Object.defineProperty(navigator, 'clipboard', {value: {writeText: async text => {window.copied = text}}});"
            )

            def route_request(route):
                path = urlparse(route.request.url).path
                if path == "/app/advanced":
                    route.fulfill(
                        body=(STATIC / "advanced.html").read_bytes(), content_type="text/html"
                    )
                elif path.startswith("/assets/"):
                    name = path.rsplit("/", 1)[-1]
                    route.fulfill(
                        body=(STATIC / name).read_bytes(),
                        content_type="text/css" if name.endswith(".css") else "text/javascript",
                    )
                elif path == "/v1/reference-targets":
                    route.fulfill(json=catalog)
                elif path == "/v1/generation-status":
                    route.fulfill(json=read("live-generation-status.json"))
                elif path.endswith("/evidence"):
                    route.fulfill(json=evidence)
                elif path.endswith("/reports"):
                    request = route.request.post_data_json
                    posts.append(request)
                    if request["employment"]["currently_employed_in_organization"] is True:
                        route.fulfill(status=503, json={"code": "replay_failure"})
                    else:
                        route.fulfill(json=report)
                else:
                    route.abort()

            page.route("**/*", route_request)
            page.goto("http://author01.test/app/advanced")
            page.locator(f'#school-select option[value="{entry_id}"]').wait_for(state="attached")

            def select_slice():
                page.locator("#school-select").select_option(entry_id)
                for selector in (
                    "#intake-select",
                    "#college-select",
                    "#department-select",
                    "#route-select",
                ):
                    page.locator(selector).select_option(index=1)
                page.locator("#requirements-submit").click()
                page.locator(".materials-section .requirement-card").first.wait_for()

            select_slice()
            page.locator("#requirements-continue").click()
            control = page.locator('[data-slice-material-code="application-essay"]')
            assert control.input_value() == "unknown"
            page.locator("#comparison-submit").click()
            page.locator("#readiness-panel").wait_for(state="visible")
            assert len(posts) == 1
            for preparation, label in (("available", "已准备（自报）"), ("not_yet", "待准备")):
                page.locator("#edit-applicant").click()
                control.select_option(preparation)
                assert page.locator("#step-3-content").is_visible()
                assert page.locator("#readiness-panel").is_hidden()
                page.locator("#comparison-submit").click()
                page.locator("#readiness-panel").wait_for(state="visible")
                assert len(posts) == 1
                card = page.locator(
                    "#comparison-output .requirement-card",
                    has=page.get_by_role("heading", name="申请小论文", exact=True),
                )
                assert "当前条件：需提交" in card.inner_text()
                assert label in card.inner_text()
                page.locator("#readiness-panel .reference-generate").click()
                page.locator("#reference-report").wait_for(state="visible")
                page.locator("#reference-copy").click()
                page.wait_for_function("window.copied !== undefined")
                copied = page.evaluate("window.copied")
                assert label in copied and "不代表学校确认材料已完成" in copied
                assert "申请小论文" in copied and "日语或英语" in copied
                assert len(posts) == 1
                page.locator("#reference-close").click()
            page.locator("#edit-applicant").click()
            page.locator("#slice-current-employed").select_option("yes")
            page.locator("#comparison-submit").click()
            page.wait_for_function(
                "document.querySelector('#comparison-status').textContent.includes('暂时无法核对')"
            )
            assert len(posts) == 2
            page.locator("#change-school").click()
            legacy = next(row for row in catalog["items"] if row["kind"] == "legacy_applicant")
            page.locator("#school-select").select_option(legacy["legacy_catalog"]["school_id"])
            assert page.locator("#slice-material-preparation").is_hidden()
            select_slice()
            page.locator("#requirements-continue").click()
            assert control.input_value() == "unknown"
            assert page.locator("#slice-current-employed").input_value() == "unknown"
            assert page.locator("#reference-copy").is_disabled()
            page.locator("#comparison-submit").click()
            page.locator("#readiness-panel").wait_for(state="visible")
            assert len(posts) == 3
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert errors == []
        finally:
            browser.close()
