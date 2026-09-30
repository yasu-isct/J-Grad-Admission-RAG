"""UX-01 before/after browser replay from saved real responses; starts no service."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

TREE = Path(__file__).resolve().parents[2]
ROOT = Path(r"D:\J-Grad-Admission-RAG")
STATIC = TREE / "src/jgrad_admission_rag/service/static"
SAVED = ROOT / "outputs/ui02-real/final-head-cd09bd4"
OUT = TREE / "docs/onboarding/ux01-evidence"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
BASELINE = "3cdc26e8ebbec73a81de9cf4a1c7f90932e2021f"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def catalog_from_saved(base, evidence):
    path = TREE / "docs/onboarding/report02-browser-replay.py"
    spec = importlib.util.spec_from_file_location("report02_saved_replay", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.catalog_from_saved(base, evidence)


def static_bytes(name, before):
    if not before:
        return (STATIC / name).read_bytes()
    path = f"src/jgrad_admission_rag/service/static/{name}"
    return subprocess.run(
        ["git", "show", f"{BASELINE}:{path}"],
        cwd=TREE,
        check=True,
        capture_output=True,
    ).stdout


def choose(page, entry):
    if entry["kind"] == "legacy_applicant":
        school = entry["legacy_catalog"]
        degree = school["degrees"][0]
        intake = next(row for row in degree["intakes"] if (row["year"], row["month"]) == (2027, 4))
        college = intake["colleges"][0]
        page.locator("#school-select").select_option(school["school_id"])
        page.locator("#demo-degree-select").select_option(degree["degree_id"])
        page.locator("#intake-select").select_option(
            f"{intake['document_id']}:{intake['year']}:{intake['month']}"
        )
        page.locator("#college-select").select_option(college["college_id"])
        page.locator("#department-select").select_option(college["departments"][0]["department_id"])
    else:
        target = entry["target"]
        page.locator("#school-select").select_option(entry["entry_id"])
        page.locator("#demo-degree-select").select_option(target["degree_level"])
        page.locator("#intake-select").select_option(
            f"null:{target['intake']['year']}:{target['intake']['month']}"
        )
        for selector in ("#college-select", "#department-select", "#route-select"):
            if page.locator(selector).is_visible():
                page.locator(selector).select_option(index=1)


def capture_button(page, version, step):
    trigger = page.locator(f"#{step} .reference-generate")
    for width, height in ((1440, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        trigger.scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / f"{version}-{step}-{width}.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.set_viewport_size({"width": 1440, "height": 900})


def copy_report(page, expected):
    page.locator("#reference-report").wait_for(state="visible")
    assert page.locator("#reference-close").evaluate("button => button === document.activeElement")
    preview = page.locator("#reference-report-body").inner_text()
    page.locator("#reference-copy").click()
    copied = page.evaluate("window.copied")
    assert copied == expected.read_text(encoding="utf-8").rstrip("\n")
    assert "物理页" not in preview and "record_id" not in preview
    page.locator("#reference-close").click()


def run_browser(browser, before, assets, catalog, saved):
    version = "before" if before else "after"
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(
        "Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied=text}}});"
    )
    calls = {"base": 0, "comparison": 0, "evidence": 0, "gsfs_report": 0}
    report_mode = {"value": "normal"}
    held = []

    def route_request(route):
        path = urlparse(route.request.url).path
        if path == "/app":
            route.fulfill(body=assets["advanced.html"], content_type="text/html")
        elif path.startswith("/assets/"):
            name = path.rsplit("/", 1)[-1]
            route.fulfill(
                body=assets[name],
                content_type="text/css" if name.endswith(".css") else "text/javascript",
            )
        elif path == "/v1/reference-targets":
            route.fulfill(json=catalog)
        elif path == "/v1/reviewed-documents":
            route.fulfill(json={"items": []})
        elif path == "/v1/generation-status":
            route.fulfill(json={"configured": False, "label": "问答未配置"})
        elif path == "/v1/base-requirements":
            calls["base"] += 1
            route.fulfill(json=saved["isct-base-2027.json"])
        elif path == "/v1/applicant-comparison":
            calls["comparison"] += 1
            route.fulfill(json=saved["isct-comparison.json"])
        elif path.endswith("/evidence"):
            calls["evidence"] += 1
            route.fulfill(json=saved["gsfs-evidence"])
        elif path.endswith("/reports"):
            calls["gsfs_report"] += 1
            if report_mode["value"] == "hold":
                held.append(route)
            else:
                employment = route.request.post_data_json["employment"]
                if employment["currently_employed_in_organization"] is True:
                    name = "gsfs-yes-yes.json"
                else:
                    name = "gsfs-unknown-unknown.json"
                route.fulfill(json=saved[name])
        else:
            route.abort()

    page.route("**/*", route_request)
    page.goto("http://ux01-replay.test/app")
    page.locator("#school-select option").nth(2).wait_for(state="attached")
    legacy = next(item for item in catalog["items"] if item["kind"] == "legacy_applicant")
    gsfs = next(item for item in catalog["items"] if item["kind"] == "reviewed_material_slice")
    choose(page, legacy)
    page.locator("#requirements-submit").click()
    page.locator(".key-dates-section .date-event").first.wait_for(state="visible")
    capture_button(page, version, "step-2-panel")
    if not before:
        assert page.locator("#current-target-bar").is_visible()
        assert (
            legacy["legacy_catalog"]["school_name"]
            in page.locator("#current-target-name").inner_text()
        )
        page.locator("#change-school").click()
        assert page.locator("#school-select").input_value() == legacy["legacy_catalog"]["school_id"]
        assert calls["base"] == 1
        page.locator("#edit-requirements").click()
    page.locator("#step-2-panel .reference-generate").click()
    copy_report(page, OUT.parent / "report02-evidence/isct-no-profile-after-copy.txt")
    page.locator(".overview-cta").click()
    page.locator("#demo-credential-basis").select_option("ui_unknown")
    page.locator('[data-material-code="address_label"]').select_option("available")
    page.locator('[data-material-code="application_form"]').select_option("not_yet")
    page.locator("#comparison-submit").click()
    page.locator("#readiness-panel").wait_for(state="visible")
    capture_button(page, version, "readiness-panel")
    page.locator("#readiness-panel .reference-generate").click()
    copy_report(page, OUT.parent / "report02-evidence/isct-with-profile-after-copy.txt")
    if not before:
        assert "已打开" in page.locator("#reference-step4-status").inner_text()
        page.locator("#change-school").click()
        assert page.locator('[data-material-code="application_form"]').input_value() == "not_yet"
        choose(page, gsfs)
        assert page.locator("#reference-report-body").inner_text() == ""
        assert page.locator('[data-material-code="application_form"]').input_value() == ""
        page.locator("#requirements-submit").click()
        page.locator(".materials-section .requirement-card").first.wait_for(state="visible")
        assert "东京大学" in page.locator("#current-target-name").inner_text()
        assert "入学志願票" not in page.locator("#requirements-output").inner_text()
        report_mode["value"] = "hold"
        page.locator("#step-2-panel .reference-generate").click()
        page.wait_for_function(
            "document.querySelector('#step-2-panel .reference-generate').disabled"
        )
        assert len(held) == 1 and calls["gsfs_report"] == 1
        assert "正在整理" in page.locator("#reference-inline-status").inner_text()
        page.locator("#step-2-panel .reference-generate").evaluate("button => button.click()")
        assert calls["gsfs_report"] == 1
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(OUT / "after-report-wait-390.png"))
        held.pop().fulfill(status=503, json={"code": "unavailable"})
        page.locator("#step-2-panel .reference-generate").get_by_text("重试生成报告").wait_for()
        assert "失败" in page.locator("#reference-inline-status").inner_text()
        page.screenshot(path=str(OUT / "after-report-failure-390.png"))
        report_mode["value"] = "normal"
        page.locator("#step-2-panel .reference-generate").click()
        page.locator("#reference-report").wait_for(state="visible")
        assert calls["gsfs_report"] == 2
        page.locator("#reference-close").click()
        page.locator("#change-school").click()
        choose(page, legacy)
        assert page.locator("#reference-report-body").inner_text() == ""
        page.locator("#requirements-submit").click()
        page.locator(".key-dates-section .date-event").first.wait_for(state="visible")
        assert "東京科学大学" in page.locator("#current-target-name").inner_text()
        assert "学业与职务" not in page.locator("#requirements-output").inner_text()
    assert not errors, errors
    page.close()
    return calls


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    saved = {
        name: read(SAVED / name)
        for name in (
            "isct-base-2027.json",
            "isct-comparison.json",
            "gsfs-unknown-unknown.json",
            "gsfs-yes-yes.json",
        )
    }
    saved["gsfs-evidence"] = read(
        TREE / "docs/onboarding/evidui01-evidence/gsfs-evidence-real.json"
    )
    catalog = catalog_from_saved(saved["isct-base-2027.json"], saved["gsfs-evidence"])
    names = ("advanced.html", "app.css", "app.js", "overview.js", "unified-core.mjs")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        before = run_browser(
            browser, True, {name: static_bytes(name, True) for name in names}, catalog, saved
        )
        after = run_browser(
            browser, False, {name: static_bytes(name, False) for name in names}, catalog, saved
        )
        browser.close()
    (OUT / "replay-journal.json").write_text(
        json.dumps(
            {
                "method": "same saved real responses in baseline and current browser code",
                "baseline": BASELINE,
                "service_starts": 0,
                "real_posts": 0,
                "baseline_replayed": before,
                "current_replayed": after,
                "current_wait_failure_retry": True,
                "current_switch": "ISCT → GSFS → ISCT",
                "report_copy_matches_saved_projection": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
