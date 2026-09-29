"""Browser screenshots from saved real HTTP responses; no service or model is started."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

TREE = Path(__file__).resolve().parents[2]
ROOT = Path(r"D:\J-Grad-Admission-RAG")
SAVED = ROOT / "outputs/ui02-real/final-head-cd09bd4"
OUT = TREE / "docs/onboarding/report02-evidence"
STATIC = TREE / "src/jgrad_admission_rag/service/static"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def read(name):
    return json.loads((SAVED / name).read_text(encoding="utf-8"))


def catalog_from_saved(base, evidence):
    """Only route replay UI to saved targets; this catalog is never shipped to production."""
    target = base["target"]
    document_id = base["requirements"][0]["evidence"][0]["document_id"]
    return {
        "schema_version": "1.0",
        "items": [
            {
                "entry_id": "legacy-isct",
                "kind": "legacy_applicant",
                "availability": "ready",
                "institution_name": target["school_name"],
                "capabilities": {"evidence_browse": True, "reference_report": True},
                "legacy_edition_labels": {
                    document_id: "2027 April / 2026 September Master's Program Admission Guidelines"
                },
                "legacy_catalog": {
                    "school_id": "isct",
                    "school_name": target["school_name"],
                    "degrees": [
                        {
                            "degree_id": "master",
                            "degree_name": target["degree_name"],
                            "intakes": [
                                {
                                    "document_id": document_id,
                                    "year": 2027,
                                    "month": 4,
                                    "intake_name": target["intake_name"],
                                    "colleges": [
                                        {
                                            "college_id": target["college_name"],
                                            "college_name": target["college_name"],
                                            "departments": [
                                                {
                                                    "department_id": target["department_name"],
                                                    "department_name": target["department_name"],
                                                    "application_routes": [],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            },
            {
                "entry_id": "gsfs-complex-2027-a",
                "kind": "reviewed_material_slice",
                "availability": "ready",
                "institution_name": "东京大学",
                "organization_name": "新领域创成科学研究科",
                "program_name": "複雑理工学専攻",
                "program_display_name": "複雑理工学専攻",
                "program_alias": "CBMS",
                "capabilities": {"evidence_browse": True, "reference_report": True},
                "target": evidence["target"],
                "snapshot_id": evidence["snapshot_id"],
                "request_profile_target": {
                    "graduate_school_or_college": "utokyo-gsfs",
                    "department_or_program": "utokyo-gsfs-complex",
                    "application_route": "general-ordinary",
                },
            },
        ],
    }


def main():
    base, comparison, evidence = (
        read(name) for name in ("isct-base-2027.json", "isct-comparison.json", "gsfs-evidence.json")
    )
    catalog = catalog_from_saved(base, evidence)
    reports = {
        (None, None): read("gsfs-unknown-unknown.json"),
        (True, True): read("gsfs-yes-yes.json"),
        (False, None): read("gsfs-no-unknown.json"),
    }
    calls = {"base": 0, "comparison": 0, "reports": 0}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(
            "Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied=text}}});"
        )

        def route_request(route):
            path = urlparse(route.request.url).path
            if path == "/app":
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
            elif path == "/v1/reviewed-documents":
                route.fulfill(json={"items": []})
            elif path == "/v1/generation-status":
                route.fulfill(json={"configured": False, "label": "未配置问答"})
            elif path == "/v1/base-requirements":
                calls["base"] += 1
                route.fulfill(json=base)
            elif path == "/v1/applicant-comparison":
                calls["comparison"] += 1
                route.fulfill(json=comparison)
            elif path.endswith("/evidence"):
                route.fulfill(json=evidence)
            elif path.endswith("/reports"):
                calls["reports"] += 1
                values = route.request.post_data_json["employment"]
                key = (
                    values["currently_employed_in_organization"],
                    values["retain_employment_at_enrollment"],
                )
                route.fulfill(json=reports[key])
            else:
                route.abort()

        def capture(name, trigger):
            page.locator(trigger).click()
            page.locator("#reference-report").wait_for(state="visible")
            body = page.locator("#reference-report-body").inner_text()
            assert "出愿准备" not in body or "接下来先做什么" in body
            assert not any(x in body for x in ("物理页", "record_id", "# 原始报告"))
            page.locator("#reference-copy").click()
            copy = page.evaluate("window.copied")
            expected = (OUT / f"{name}-after-copy.txt").read_text(encoding="utf-8").rstrip("\n")
            assert copy == expected, (name, len(copy), len(expected))
            page.screenshot(path=str(OUT / f"{name}-desktop.png"), full_page=False)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(OUT / f"{name}-mobile.png"), full_page=False)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), name
            page.set_viewport_size({"width": 1440, "height": 900})
            page.locator("#reference-close").click()

        def full_page_pair(name):
            page.screenshot(path=str(OUT / f"{name}-desktop-full.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(OUT / f"{name}-mobile-full.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), name
            page.set_viewport_size({"width": 1440, "height": 900})

        page.route("**/*", route_request)
        page.goto("http://report02-replay.test/app")
        page.locator("#school-select option").nth(2).wait_for(state="attached")
        page.locator("#school-select").select_option("isct")
        page.locator("#demo-degree-select").select_option("master")
        page.locator("#intake-select").select_option("isct_2027_4_2026_9_master:2027:4")
        page.locator("#college-select").select_option("工学院")
        page.locator("#department-select").select_option("システム制御系")
        page.locator("#requirements-submit").click()
        page.locator(".key-dates-section .date-event").first.wait_for()
        full_page_pair("isct-step2")
        capture("isct-no-profile", "#step-2-panel .reference-generate")
        page.locator(".overview-cta").click()
        page.locator("#demo-credential-basis").select_option("ui_unknown")
        page.locator('[data-material-code="address_label"]').select_option("available")
        page.locator('[data-material-code="application_form"]').select_option("not_yet")
        page.locator("#comparison-submit").click()
        page.locator("#readiness-panel").wait_for(state="visible")
        full_page_pair("isct-step4")
        capture("isct-with-profile", "#readiness-panel .reference-generate")
        before_themes = dict(calls)
        page.locator("#readiness-panel .reference-generate").click()
        page.locator("#reference-report").wait_for(state="visible")
        choices = page.locator(".reader-report-options input")
        assert choices.count() == 3
        for index, key in enumerate(("dates", "materials", "other")):
            for slot in range(3):
                choices.nth(slot).set_checked(slot == index)
            preview = page.locator("#reference-report-body").inner_text()
            page.locator("#reference-copy").click()
            copied = page.evaluate("window.copied")
            expected = (OUT / f"isct-{key}-only-copy.txt").read_text(encoding="utf-8").rstrip("\n")
            assert copied == expected, key
            if key == "dates":
                for value in ("接下来先做什么", "待补材料", "材料准备清单", "已准备不代表"):
                    assert value not in preview and value not in copied, key
            elif key == "materials":
                assert "入学志願票：待补材料" in preview and "入学志願票：待补材料" in copied
            else:
                assert "没有明确的待补材料" not in preview + copied
                assert "已准备不代表" not in preview + copied
            if key in ("dates", "other"):
                page.screenshot(path=str(OUT / f"isct-{key}-only-desktop.png"), full_page=False)
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(OUT / f"isct-{key}-only-mobile.png"), full_page=False)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), key
                page.set_viewport_size({"width": 1440, "height": 900})
        choices.nth(2).uncheck()
        assert page.locator("#reference-copy").is_disabled()
        assert "请至少选择一类报告内容" in page.locator("#reference-report-body").inner_text()
        assert calls == before_themes
        page.locator("#reference-close").click()
        page.locator("#edit-target").click()
        page.locator("#school-select").select_option("gsfs-complex-2027-a")
        page.locator("#demo-degree-select").select_option("master")
        page.locator("#intake-select").select_option("null:2027:4")
        for selector in ("#college-select", "#department-select", "#route-select"):
            if page.locator(selector).is_visible():
                page.locator(selector).select_option(index=1)
        page.locator("#requirements-submit").click()
        page.locator(".materials-section .requirement-card").first.wait_for()
        full_page_pair("gsfs-step2")
        page.locator(".overview-cta").click()
        for current, retain, name in (
            ("unknown", "unknown", "gsfs-unknown"),
            ("yes", "yes", "gsfs-required"),
            ("no", "unknown", "gsfs-inapplicable"),
        ):
            if not page.locator("#slice-current-employed").is_visible():
                page.locator("#edit-applicant").click()
            page.locator("#slice-current-employed").select_option(current)
            page.locator("#slice-retain-employed").select_option(retain)
            page.locator("#comparison-submit").click()
            page.locator("#readiness-panel.slice-readiness").wait_for(state="visible")
            if name == "gsfs-unknown":
                full_page_pair("gsfs-step4")
            capture(name, "#readiness-panel .reference-generate")
        assert calls == {"base": 1, "comparison": 1, "reports": 3} and not errors, (calls, errors)
        browser.close()
    (OUT / "replay-browser-journal.json").write_text(
        json.dumps(
            {
                "method": "saved real HTTP responses through current browser code",
                "service_startups": 0,
                "real_posts": 0,
                "replayed_posts": calls,
                "screenshots": 22,
                "single_theme_copies": 3,
                "copy_matches_projection": True,
                "no_horizontal_overflow": True,
                "browser_errors": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
