"""Intercepted synthetic different-target proofs; zero actual product HTTP/POST."""

# ruff: noqa: F811, F401 -- pytest resolves imported fixtures by name.
from pathlib import Path
from urllib.parse import urlparse

import pytest
from jgrad_admission_rag.reviewed_source_evidence import canonical_json_bytes, parse_json
from tests.test_m19_configs import (
    compiler_case,
    other_compiler_case,
    synthetic_v2,
    v2_inputs,
    compile_case,
    approve_synthetic_edit,
    write,
)  # noqa: F401

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
pytestmark = pytest.mark.skipif(not EDGE.exists(), reason="local browser unavailable")


@pytest.mark.parametrize("width", [1440, 390])
def test_another_target_single_reader_step_reaches_page_and_copy(other_compiler_case, width):
    docs, _ = other_compiler_case
    author_path = docs / "m19-questionnaire-authoring.json"
    author = parse_json(author_path.read_bytes())
    original = author["reader"]["steps"][0]["text"]
    modified = "合成验证：只改这一处reader步骤，页面与复制报告同步。"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(EDGE))
        try:
            for index, expected in enumerate([original, modified]):
                if index:
                    author["reader"]["steps"][0]["text"] = modified
                    write(author_path, author)
                    approve_synthetic_edit(docs)
                files, snapshot, _ = compile_case(other_compiler_case)
                entry = next(
                    r
                    for r in parse_json(
                        (ROOT / "docs/onboarding/author01-evidence/live-catalog.json").read_bytes()
                    )["items"]
                    if r["kind"] == "reviewed_material_slice"
                )
                entry.update(
                    entry_id="m19-reviewed-preview",
                    institution_name="合成大学（仅测试）",
                    organization_name="合成研究科",
                    program_name="合成专攻",
                    program_alias=None,
                    program_display_name="合成专攻",
                    snapshot_id=snapshot.snapshot_id,
                    revision=snapshot.plan.revision,
                    target=snapshot.plan.target.model_dump(mode="json"),
                    request_profile_target=dict(snapshot.profile_aliases),
                )
                context = browser.new_context(viewport=dict(width=width, height=844))
                page = context.new_page()
                page.add_init_script(
                    "Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied=text}}});"
                )
                errors = []
                posts = []
                page.on("pageerror", lambda error: errors.append(str(error)))

                def route_request(route):
                    path = urlparse(route.request.url).path
                    if path == "/app/advanced":
                        route.fulfill(
                            body=(STATIC / "advanced.html").read_bytes(), content_type="text/html"
                        )
                    elif path == "/assets/m19-material-presentation.mjs":
                        route.fulfill(
                            body=files["m19-material-presentation.mjs"],
                            content_type="text/javascript",
                        )
                    elif path.startswith("/assets/"):
                        filename = path.rsplit("/", 1)[-1]
                        route.fulfill(
                            body=(STATIC / filename).read_bytes(),
                            content_type="text/css"
                            if filename.endswith(".css")
                            else "text/javascript",
                        )
                    elif path == "/v1/reference-targets":
                        route.fulfill(json=dict(schema_version="1.0", items=[entry]))
                    elif path == "/v1/generation-status":
                        route.fulfill(
                            json=dict(
                                configured=False, request_timeout_seconds=60, label="synthetic"
                            )
                        )
                    elif path.endswith("/evidence"):
                        route.fulfill(body=snapshot.presentation, content_type="application/json")
                    elif path.endswith("/reports"):
                        posts.append(route.request.post_data_json)
                        route.fulfill(json=snapshot.report(canonical_json_bytes(posts[-1])))
                    else:
                        route.abort()

                page.route("**/*", route_request)
                page.goto("http://synthetic.test/app/advanced")
                page.locator('#school-select option[value="m19-reviewed-preview"]').wait_for(
                    state="attached"
                )
                page.locator("#school-select").select_option("m19-reviewed-preview")
                for selector in [
                    "#intake-select",
                    "#college-select",
                    "#department-select",
                    "#route-select",
                ]:
                    page.locator(selector).select_option(index=1)
                page.locator("#requirements-submit").click()
                card = page.locator(
                    ".materials-section .requirement-card",
                    has=page.get_by_role("heading", name="合成项目表", exact=True),
                )
                card.wait_for()
                card.locator("summary", has_text="如何准备").click()
                assert expected in card.inner_text()
                page.locator("#requirements-continue").click()
                assert page.locator("#slice-material-preparation select").count() == 2
                control = page.locator('[data-slice-material-code="synthetic-project-form"]')
                control.select_option("available")
                assert (
                    page.locator('[data-slice-material-code="application-essay"]').input_value()
                    == "unknown"
                )
                page.locator("#comparison-submit").click()
                page.locator("#readiness-panel").wait_for(state="visible")
                page.locator("#readiness-panel .reference-generate").click()
                page.locator("#reference-report").wait_for(state="visible")
                page.locator("#reference-copy").click()
                page.wait_for_function("window.copied !== undefined")
                copied = page.evaluate("window.copied")
                assert expected.rstrip("。；") in copied and "合成项目表" in copied
                if index:
                    assert original.rstrip("。；") not in copied
                assert "已准备（自报）" in copied
                assert len(posts) == 1 and not errors
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                context.close()
        finally:
            browser.close()
