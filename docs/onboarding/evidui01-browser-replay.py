"""Supplementary mobile captures from saved real responses; starts no service."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

TREE = Path(__file__).resolve().parents[2]
ROOT = Path(r"D:\J-Grad-Admission-RAG")
OUT = TREE / "docs/onboarding/evidui01-evidence"
STATIC = TREE / "src/jgrad_admission_rag/service/static"
SAVED = ROOT / "outputs/ui02-real/final-head-cd09bd4"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def load_helper(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


real_helper = load_helper("report02_real_helper", TREE / "docs/onboarding/report02-real-browser.py")
replay_helper = load_helper(
    "report02_replay_helper", TREE / "docs/onboarding/report02-browser-replay.py"
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    base = read(SAVED / "isct-base-2027.json")
    evidence = read(OUT / "gsfs-evidence-real.json")
    report = read(SAVED / "gsfs-yes-yes.json")
    catalog = replay_helper.catalog_from_saved(base, evidence)
    calls = {"evidence_get": 0, "base_post": 0, "report_post": 0}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

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
            elif path.endswith("/evidence"):
                calls["evidence_get"] += 1
                route.fulfill(json=evidence)
            elif path.endswith("/reports"):
                calls["report_post"] += 1
                route.fulfill(json=report)
            elif path == "/v1/base-requirements":
                calls["base_post"] += 1
                route.fulfill(json=base)
            else:
                route.abort()

        page.route("**/*", route_request)
        page.goto("http://evidui01-replay.test/app")
        page.locator("#school-select option").nth(2).wait_for(state="attached")
        gsfs = next(item for item in catalog["items"] if item["kind"] == "reviewed_material_slice")
        legacy = next(item for item in catalog["items"] if item["kind"] == "legacy_applicant")
        real_helper.choose(page, gsfs)
        page.locator("#requirements-submit").click()
        page.locator(".materials-section .requirement-card").first.wait_for(state="visible")
        page.locator(".overview-cta").click()
        page.locator("#slice-current-employed").select_option("yes")
        page.locator("#slice-retain-employed").select_option("yes")
        page.locator("#comparison-submit").click()
        page.locator("#readiness-panel.slice-readiness").wait_for(state="visible")
        page.screenshot(path=str(OUT / "gsfs-step4-mobile-replay-full.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        real_helper.choose(page, legacy)
        page.locator("#requirements-submit").click()
        page.locator(".materials-section .requirement-card").first.wait_for(state="visible")
        page.screenshot(path=str(OUT / "isct-step2-mobile-replay-full.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert calls == {"evidence_get": 1, "base_post": 1, "report_post": 1} and not errors
        browser.close()
    (OUT / "replay-journal.json").write_text(
        json.dumps(
            {
                "method": "saved real HTTP responses through current four-step browser code",
                "service_startups": 0,
                "real_posts": 0,
                "replayed_posts": calls,
                "screenshots": [
                    "gsfs-step4-mobile-replay-full.png",
                    "isct-step2-mobile-replay-full.png",
                ],
                "no_horizontal_overflow": True,
                "browser_errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
