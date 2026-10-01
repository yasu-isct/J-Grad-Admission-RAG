"""TOOLS-01 saved-response/browser audit; no product service or external network."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.test_ui02_browser import _data, _select_slice, _slice_report_for


ROOT = Path(__file__).resolve().parents[2]
CURRENT = ROOT / "src/jgrad_admission_rag/service/static"
PREVIOUS = ROOT.parent / "prep02-worktree/src/jgrad_admission_rag/service/static"
SAVED = ROOT / "docs/onboarding/prep02-evidence"
OUT = ROOT / "docs/onboarding/tools01-evidence"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def respond(
    route,
    static: Path,
    catalog: dict,
    base: dict | None,
    comparison: dict | None,
    evidence: dict | None,
    report: dict | None,
    requests: list[str],
) -> None:
    path = urlparse(route.request.url).path
    requests.append(f"{route.request.method} {path}")
    if path in {"/app", "/app/advanced"}:
        route.fulfill(body=(static / "advanced.html").read_bytes(), content_type="text/html")
    elif path == "/app/reference":
        route.fulfill(status=307, headers={"location": "/app"})
    elif path.startswith("/assets/") and "/" not in path[len("/assets/") :]:
        name = path[len("/assets/") :]
        route.fulfill(
            body=(static / name).read_bytes(),
            content_type="text/css" if name.endswith(".css") else "text/javascript",
        )
    elif path == "/v1/reference-targets":
        route.fulfill(json=catalog)
    elif path == "/v1/generation-status":
        route.fulfill(
            json={
                "configured": False,
                "mode": "offline_rules",
                "label": "离线规则",
                "request_timeout_seconds": 30,
            }
        )
    elif path == "/v1/reviewed-documents":
        route.fulfill(json={"items": []})
    elif path == "/v1/base-requirements" and base is not None:
        route.fulfill(json=base)
    elif path == "/v1/applicant-comparison" and comparison is not None:
        route.fulfill(json=comparison)
    elif path.endswith("/evidence") and evidence is not None:
        route.fulfill(json=evidence)
    elif path.endswith("/reports") and report is not None:
        route.fulfill(json=_slice_report_for(route.request.post_data_json, report))
    else:
        raise AssertionError(f"Unexpected browser request: {route.request.method} {path}")


def select_isct(page) -> None:
    for selector, value in (
        ("school-select", "isct"),
        ("demo-degree-select", "master"),
        ("intake-select", "isct_2027_4_2026_9_master:2027:4"),
        ("college-select", "情報理工学院"),
        ("department-select", "情報工学系"),
        ("route-select", "b_schedule"),
    ):
        page.locator(f"#{selector}").select_option(value)


def case(browser, school: str, width: int, before: bool) -> dict:
    label = f"{'before' if before else 'after'}-{school}-{width}"
    context = browser.new_context(
        viewport={"width": width, "height": 900}, permissions=["clipboard-read", "clipboard-write"]
    )
    page = context.new_page()
    page.add_init_script(
        "Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: async text => {window.copied = text}}});"
    )
    errors: list[str] = []
    requests: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    if school == "isct":
        catalog = json.loads((SAVED / "reference-targets.json").read_text(encoding="utf-8"))
        base = json.loads((SAVED / "base.json").read_text(encoding="utf-8"))
        comparison = json.loads(
            (SAVED / "dispatched_unknown_arrival-response.json").read_text(encoding="utf-8")
        )
        evidence = report = None
    else:
        catalog, base, comparison, evidence, report = _data()
    static = PREVIOUS if before else CURRENT
    page.route(
        "**/*",
        lambda route: respond(route, static, catalog, base, comparison, evidence, report, requests),
    )
    assert page.goto("http://tools.test/app").status == 200
    page.locator("#school-select option").nth(2).wait_for(state="attached")
    if before:
        assert page.locator("#advanced-tools").count() == 1
        page.locator("#advanced-tools").scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / f"{label}.png"))
    else:
        assert page.locator("#advanced-tools").count() == 0
        if school == "isct":
            select_isct(page)
        else:
            _select_slice(page)
        page.locator("#requirements-submit").click()
        page.locator(".requirement-card").first.wait_for()
        page.screenshot(path=str(OUT / f"{label}-step2.png"), full_page=True)
        if school == "isct":
            page.locator(".overview-cta").click()
            page.locator("#demo-credential-basis").select_option("university_graduation")
            page.locator("#demo-completion-state").select_option("expected")
            page.locator("#demo-expected-completion-date").fill("2027-03-20")
            submission = page.locator('.profile-group[data-profile-group="submission"]')
            if not submission.evaluate("element => element.open"):
                submission.locator("summary").click()
            page.locator("#demo-online-steps").select_option("true")
            page.locator("#demo-dispatched-date").fill("2026-06-09")
            page.locator("#comparison-submit").click()
            page.locator(".application-preparation-group").wait_for(state="visible")
            assert "寄出不等于按时送达" in page.locator("#comparison-output").inner_text()
        else:
            page.locator(".overview-cta").click()
            page.locator("#slice-current-employed").select_option("yes")
            page.locator("#slice-retain-employed").select_option("no")
            page.locator("#comparison-submit").click()
            page.locator("#readiness-panel.slice-readiness").wait_for(state="visible")
            assert page.locator("#comparison-output .requirement-card").count() == 3
            page.locator("#comparison-output .requirement-evidence-actions button").first.click()
            assert page.locator("#evidence-drawer .relation-node").count() >= 1
            page.locator("#drawer-close").click()
        page.screenshot(path=str(OUT / f"{label}-step4.png"), full_page=True)
        page.locator("#readiness-panel .reference-generate").click()
        page.locator("#reference-report[open]").wait_for(state="visible")
        page.locator("#reference-copy").click()
        copied = page.evaluate("window.copied")
        assert copied and "募集" not in copied[:10]
        page.screenshot(path=str(OUT / f"{label}-report.png"))
        (OUT / f"{label}-copy.txt").write_text(copied, encoding="utf-8")
        page.locator("#reference-close").click()
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        page.screenshot(path=str(OUT / f"{label}-tail.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not errors, errors
    context.close()
    return {
        "case": label,
        "requests": requests,
        "console_errors": errors,
        "mocked_post_count": sum(item.startswith("POST ") for item in requests),
        "real_product_post_count": 0,
        "copy_sha256": hashlib.sha256(copied.encode("utf-8")).hexdigest() if not before else None,
    }


def main() -> None:
    OUT.mkdir(exist_ok=True)
    cases = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        try:
            for width in (1440, 390):
                for school in ("isct", "gsfs"):
                    cases.append(case(browser, school, width, True))
                    cases.append(case(browser, school, width, False))
        finally:
            browser.close()
    assert all(
        not any(request.startswith("POST /v1/natural-language") for request in case["requests"])
        for case in cases
    )
    (OUT / "journal.json").write_text(
        json.dumps(
            {
                "source": "saved real ISCT PREP-02 response and synthetic GSFS fixture",
                "product_service_starts": 0,
                "product_api_posts": 0,
                "cases": cases,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
