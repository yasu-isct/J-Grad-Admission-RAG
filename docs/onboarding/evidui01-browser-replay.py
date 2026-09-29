"""Replay saved real responses through the current UI; starts no service."""

from __future__ import annotations

import importlib.util
import json
import re
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
        screenshots = []
        duplicate_focus = []
        for index, topic in enumerate(evidence["topics"], start=1):
            page.set_viewport_size({"width": 1440, "height": 900})
            trigger = page.locator(
                ".materials-section .requirement-card .requirement-evidence-actions button"
            ).nth(index - 1)
            trigger.click()
            drawer = page.locator("#evidence-drawer")
            assert drawer.is_visible()
            assert drawer.locator(".relation-edge").count() == len(topic["relations"])
            assert {
                record_id
                for record_id in drawer.locator(".relation-node").evaluate_all(
                    "nodes => nodes.map(node => node.dataset.recordId)"
                )
            } == {record["record_id"] for record in topic["records"]}
            edge_labels = drawer.locator(".relation-edge").evaluate_all(
                "edges => edges.map(edge => edge.getAttribute('aria-label'))"
            )
            for relation in topic["relations"]:
                from_label = drawer.locator(
                    f'.relation-node[data-record-id="{relation["from"]}"] h4'
                ).first.inner_text()
                to_label = drawer.locator(
                    f'.relation-node[data-record-id="{relation["to"]}"] h4'
                ).first.inner_text()
                assert any(f"{from_label} 指向 {to_label}：" in label for label in edge_labels)
            assert not any(
                re.search(r"\bE\d{2,}\b", label)
                for label in drawer.locator(".relation-node h4").all_inner_texts() + edge_labels
            )
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            if index == 1:
                assert drawer.locator(".relation-path").count() == 1
                assert drawer.locator(".relation-path .relation-node").count() == 3
                assert drawer.evaluate("dialog => dialog.scrollHeight <= dialog.clientHeight"), (
                    drawer.evaluate(
                        "dialog => ({scroll: dialog.scrollHeight, client: dialog.clientHeight, "
                        "path: dialog.querySelector('.relation-path').getBoundingClientRect().height, "
                        "children: [...dialog.querySelector('.relation-path').children].map(x => [x.className, x.getBoundingClientRect().height, x.getBoundingClientRect().width]), "
                        "display: getComputedStyle(dialog.querySelector('.relation-path')).display})"
                    )
                )
            if index == 2:
                labels = drawer.locator(".relation-node h4").all_inner_texts()
                assert len(labels) == 2 and labels[0] != labels[1]
                assert "第 28 页" in labels[0] and "第 40 页" in labels[1]
            if index == 3:
                labels = {
                    record_id: drawer.locator(
                        f'.relation-node[data-record-id="{record_id}"] h4'
                    ).first.inner_text()
                    for record_id in ("E06", "E07")
                }
                assert labels["E06"] != labels["E07"]
                assert "出愿" in labels["E06"] and "入学手续" in labels["E07"]
                stage = drawer.locator(".relation-edge-stage")
                assert stage.count() == 1
                assert "入学手续" in stage.get_attribute("aria-label")
                assert "出愿" in stage.get_attribute("aria-label")
                assert (
                    stage.evaluate("node => getComputedStyle(node, '::before').borderTopStyle")
                    == "dashed"
                )
            for width, height, name in ((1440, 900, "desktop"), (390, 844, "mobile")):
                page.set_viewport_size({"width": width, "height": height})
                drawer.evaluate("dialog => { dialog.scrollTop = 0; }")
                assert drawer.evaluate(
                    "dialog => { const dialogBox = dialog.getBoundingClientRect(); "
                    "const headerBox = dialog.querySelector('.drawer-header').getBoundingClientRect(); "
                    "return dialogBox.top >= 0 && headerBox.top >= 0 && headerBox.bottom <= innerHeight; }"
                )
                filename = f"gsfs-{index}-graph-{name}-review-replay.png"
                page.screenshot(path=str(OUT / filename))
                screenshots.append(filename)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                if index == 3:
                    repeated = drawer.locator('.relation-node[data-record-id="E06"] button')
                    assert repeated.count() == 2
                    record = next(row for row in topic["records"] if row["record_id"] == "E06")
                    for instance in range(2):
                        button = repeated.nth(instance)
                        button.scroll_into_view_if_needed()
                        before = drawer.evaluate("dialog => dialog.scrollTop")
                        button.click()
                        assert record["fragments"][0]["quote_text"] in drawer.inner_text()
                        drawer.locator(".relation-back").click()
                        after = drawer.evaluate("dialog => dialog.scrollTop")
                        assert after == before
                        assert button.evaluate("node => node === document.activeElement")
                        duplicate_focus.append(
                            {"viewport": width, "instance": instance + 1, "scroll_restored": True}
                        )
            node = drawer.locator(".relation-node button").first
            record_id = node.get_attribute("data-record-id")
            node.click()
            record = next(row for row in topic["records"] if row["record_id"] == record_id)
            assert record["fragments"][0]["quote_text"] in drawer.inner_text()
            assert record["source_title"] in drawer.inner_text()
            drawer.locator(".relation-back").click()
            assert drawer.locator(
                f'.relation-node[data-record-id="{record_id}"] button'
            ).first.evaluate("button => button === document.activeElement")
            drawer.press("Escape")
            assert trigger.evaluate("button => button === document.activeElement")
            page.set_viewport_size({"width": 390, "height": 844})
        page.locator(".overview-cta").click()
        page.locator("#slice-current-employed").select_option("yes")
        page.locator("#slice-retain-employed").select_option("yes")
        page.locator("#comparison-submit").click()
        page.locator("#readiness-panel.slice-readiness").wait_for(state="visible")
        page.screenshot(path=str(OUT / "gsfs-step4-mobile-replay-full.png"), full_page=True)
        screenshots.append("gsfs-step4-mobile-replay-full.png")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        real_helper.choose(page, legacy)
        page.locator("#requirements-submit").click()
        page.locator(".materials-section .requirement-card").first.wait_for(state="visible")
        page.screenshot(path=str(OUT / "isct-step2-mobile-replay-full.png"), full_page=True)
        screenshots.append("isct-step2-mobile-replay-full.png")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert calls == {"evidence_get": 1, "base_post": 1, "report_post": 1} and not errors
        assert len(duplicate_focus) == 4
        browser.close()
    (OUT / "replay-journal.json").write_text(
        json.dumps(
            {
                "method": "saved real HTTP responses through current four-step browser code",
                "service_startups": 0,
                "real_posts": 0,
                "replayed_posts": calls,
                "screenshots": screenshots,
                "duplicate_record_focus": duplicate_focus,
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
