"""Synthetic generation-to-browser proofs; all traffic is intercepted."""
# ruff: noqa: F811 -- pytest resolves the imported fixture names by parameter.

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from jgrad_admission_rag.reviewed_source_evidence import canonical_json_bytes, parse_json
from scripts import m18_presentation as generator
from tests.test_m18_presentation import synthetic_other, v2_inputs  # noqa: F401

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
pytestmark = pytest.mark.skipif(not EDGE.exists(), reason="local browser unavailable")


@pytest.mark.parametrize("width", [1440, 390])
def test_synthetic_other_school_and_single_author_edit_reach_page_and_report(
    synthetic_other, width
):
    inputs, snapshot = synthetic_other
    original_catalog = parse_json(
        (ROOT / "docs/onboarding/author01-evidence/live-catalog.json").read_bytes()
    )
    entry = next(
        row for row in original_catalog["items"] if row["kind"] == "reviewed_material_slice"
    )
    entry.update(
        entry_id="synthetic-preview",
        institution_name="合成学校（验证专用）",
        organization_name="合成研究科",
        program_name="合成专攻",
        snapshot_id=snapshot.snapshot_id,
        revision=snapshot.plan.revision,
        target=snapshot.plan.target.model_dump(mode="json"),
        request_profile_target=dict(snapshot.profile_aliases),
    )
    entry.update(program_alias=None, program_display_name="合成专攻")
    evidence = parse_json(snapshot.presentation)
    author_path = inputs[0].parent / "author01-essay-authoring-input.json"
    author = parse_json(author_path.read_bytes())
    first = author["guide"]["preparation"][0]
    second = "合成验证：仅修改这一处指南；页面和报告必须同步。"
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        try:
            for index, expected in enumerate((first, second)):
                if index:
                    author["guide"]["preparation"][0] = second
                    author_path.write_bytes(canonical_json_bytes(author))
                files = generator.build(*inputs)
                context = browser.new_context(viewport={"width": width, "height": 844})
                page = context.new_page()
                errors, intercepted = [], []
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
                    elif path == "/assets/" + generator.MODULE:
                        route.fulfill(body=files[generator.MODULE], content_type="text/javascript")
                    elif path.startswith("/assets/"):
                        name = path.rsplit("/", 1)[-1]
                        route.fulfill(
                            body=(STATIC / name).read_bytes(),
                            content_type="text/css" if name.endswith(".css") else "text/javascript",
                        )
                    elif path == "/v1/reference-targets":
                        route.fulfill(json={"schema_version": "1.0", "items": [entry]})
                    elif path == "/v1/generation-status":
                        route.fulfill(
                            json={
                                "configured": False,
                                "request_timeout_seconds": 60,
                                "label": "合成离线",
                            }
                        )
                    elif path.endswith("/evidence"):
                        route.fulfill(json=evidence)
                    elif path.endswith("/reports"):
                        intercepted.append(route.request.post_data_json)
                        response = snapshot.report(
                            canonical_json_bytes(route.request.post_data_json)
                        )
                        route.fulfill(json=response)
                    else:
                        route.abort()

                page.route("**/*", route_request)
                page.goto("http://synthetic.test/app/advanced")
                page.locator('#school-select option[value="synthetic-preview"]').wait_for(
                    state="attached"
                )
                probe = page.evaluate(
                    """async ([entry, evidence]) => {
                  const core = await import('/assets/unified-core.mjs');
                  try { core.mapSliceEvidence(core.scopesFor(entry)[0], evidence); return 'ok'; }
                  catch (error) { return String(error); }
                }""",
                    [entry, evidence],
                )
                assert probe == "ok", probe
                page.locator("#school-select").select_option("synthetic-preview")
                for selector in (
                    "#intake-select",
                    "#college-select",
                    "#department-select",
                    "#route-select",
                ):
                    page.locator(selector).select_option(index=1)
                page.locator("#requirements-submit").click()
                card = page.locator(
                    ".materials-section .requirement-card",
                    has=page.get_by_role("heading", name="合成练习说明", exact=True),
                )
                card.wait_for()
                card.locator("summary", has_text="如何准备").click()
                assert expected in card.inner_text()
                page.locator("#requirements-continue").click()
                control = page.locator('[data-slice-material-code="synthetic-writing"]')
                assert page.locator("#slice-material-preparation select").count() == 1
                assert "合成练习说明" in control.locator("..").inner_text()
                control.select_option("available")
                page.locator("#comparison-submit").click()
                page.locator("#readiness-panel").wait_for(state="visible")
                assert "合成练习说明" in page.locator("#step-3-summary-text").inner_text()
                assert "申请小论文" not in page.locator("#step-3-summary-text").inner_text()
                page.locator("#readiness-panel .reference-generate").click()
                page.locator("#reference-report").wait_for(state="visible")
                page.locator("#reference-copy").click()
                page.wait_for_function("window.copied !== undefined")
                copied = page.evaluate("window.copied")
                assert expected.rstrip("。；") in copied and "合成练习说明" in copied
                if index:
                    assert first.rstrip("。；") not in copied
                assert "已准备（自报）" in copied
                assert not errors and len(intercepted) == 1
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                results.append(
                    {
                        "synthetic": True,
                        "actual_product_posts": 0,
                        "intercepted_posts": 1,
                        "width": width,
                        "guide_edit": bool(index),
                        "copy_sha256": sha256(copied.encode()).hexdigest(),
                        "guide_visible_in_page_and_report": expected,
                        "no_js_branch_added": True,
                        "generated_content_id": parse_json(files[generator.MANIFEST])["content_id"],
                    }
                )
                if directory := os.environ.get("M18_EVIDENCE_DIR"):
                    out = Path(directory)
                    out.mkdir(exist_ok=True)
                    page.screenshot(path=str(out / f"synthetic-{width}-guide-{index}.png"))
                    (out / f"synthetic-{width}-guide-{index}-copy.txt").write_text(
                        copied, encoding="utf-8"
                    )
                context.close()
        finally:
            browser.close()
    if directory := os.environ.get("M18_EVIDENCE_DIR"):
        (Path(directory) / f"synthetic-{width}-journal.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def test_missing_generated_module_has_load_error_and_refresh_recovers():
    saved = ROOT / "docs/onboarding/author01-evidence"
    failed = True
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        try:
            page = browser.new_page()

            def route_request(route):
                path = urlparse(route.request.url).path
                if path == "/app/advanced":
                    route.fulfill(
                        body=(STATIC / "advanced.html").read_bytes(), content_type="text/html"
                    )
                elif path == "/assets/" + generator.MODULE and failed:
                    route.fulfill(status=404, body="missing")
                elif path.startswith("/assets/"):
                    name = path.rsplit("/", 1)[-1]
                    route.fulfill(
                        body=(STATIC / name).read_bytes(),
                        content_type="text/css" if name.endswith(".css") else "text/javascript",
                    )
                elif path == "/v1/reference-targets":
                    route.fulfill(
                        body=(saved / "live-catalog.json").read_bytes(),
                        content_type="application/json",
                    )
                elif path == "/v1/generation-status":
                    route.fulfill(
                        body=(saved / "live-generation-status.json").read_bytes(),
                        content_type="application/json",
                    )
                else:
                    route.abort()

            page.route("**/*", route_request)
            page.goto("http://missing.test/app/advanced")
            page.wait_for_function(
                "document.querySelector('#target-status').textContent.includes('组件暂时无法加载')"
            )
            assert "刷新页面" in page.locator("#target-status").inner_text()
            failed = False
            page.reload()
            page.locator('#school-select option[value="gsfs-complex-2027-a-author01"]').wait_for(
                state="attached"
            )
        finally:
            browser.close()
