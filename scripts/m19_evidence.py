"""M19 reproducibility, real HTTP/browser and saved legacy replay evidence."""

from hashlib import sha256
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlparse
from time import monotonic

import httpx
from playwright.sync_api import sync_playwright
from jgrad_admission_rag.reviewed_source_evidence import canonical_json_bytes, parse_json
from scripts import m19_configs as compiler
from scripts import m18_evidence as previous
from scripts import m18_asset_audit as asset_audit
from scripts.m19_budget import update, LEDGER

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/onboarding"
OUT = DOCS / "m19-evidence"
ASSETS = Path("D:/J-Grad-Admission-RAG")
PDFS = ASSETS / "outputs/source-documents/utokyo-gsfs/2027"
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def save(name, value):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def prepare():
    runs = []
    with tempfile.TemporaryDirectory(prefix="m19-reproduce-") as directory:
        copied = Path(directory) / "second-workspace"
        copied.mkdir()
        approval = parse_json((DOCS / "m19-design-approval.json").read_bytes())
        names = set(approval["base_inputs"]) | {
            "m19-design-approval.json",
            "m19-source-review.json",
            "m19-source-review-pin-v3.json",
            "m19-questionnaire-evidence-seed-v3.json",
            "m19-questionnaire-authoring.json",
            "utokyo-gsfs-complex-2027.sources.json",
            "gsfs-source-set-contract-v0.1.examples.json",
            "author01-reference-workspace-preview-v2.json",
        }
        for name in names:
            shutil.copyfile(DOCS / name, copied / name)
        baseline = None
        for index, docs in enumerate([DOCS, DOCS, copied]):
            started = monotonic()
            files, snapshot, _ = compiler.compile_configs(docs, pdf_dir=PDFS)
            elapsed = monotonic() - started
            update("pure reproducibility generation", seconds=elapsed)
            if baseline is None:
                baseline = files
            assert baseline == files
            runs.append(
                dict(
                    run=index + 1,
                    seconds=elapsed,
                    bytes=sum(map(len, files.values())),
                    local_paths_excluded_from_identity=True,
                )
            )
        compiler.write_or_check(files, DOCS / "m19-generated", check=True)
        assert (STATIC / "m19-material-presentation.mjs").read_bytes() == files[
            "m19-material-presentation.mjs"
        ]
    examples = parse_json((DOCS / "material-condition-examples-v1.json").read_bytes())
    request = examples["cases"][0]["request"]
    request["target"] = snapshot.plan.target.model_dump(mode="json")
    combinations = []
    for current in [True, False, None]:
        for retain in [True, False, None]:
            request["employment"] = dict(
                currently_employed_in_organization=current, retain_employment_at_enrollment=retain
            )
            response = snapshot.report(canonical_json_bytes(request))
            results = response["report"]["topic_results"]
            assert len(results) == 5 and len(response["report"]["evidence_inventory"]) == 51
            assert [r["disposition"] for r in results[:2]] == ["submission_not_required"] * 2
            assert [r["disposition"] for r in results[-2:]] == ["submission_required"] * 2
            combinations.append(
                dict(
                    current=current, retain=retain, dispositions=[r["disposition"] for r in results]
                )
            )

            def name(v):
                return "yes" if v is True else "no" if v is False else "unknown"

            save(f"direct-report-{name(current)}-{name(retain)}.json", response)
    save("direct-evidence.json", parse_json(snapshot.presentation))
    save(
        "reproducibility.json",
        dict(
            method="pure mapping + complete bytes-bound source verification; zero HTTP",
            runs=runs,
            snapshot_id=snapshot.snapshot_id,
            build_id=snapshot.plan.candidate_reference.build_id,
            candidate_bytes=sum(map(len, snapshot.candidate_files.values())),
            employment_combinations=combinations,
            independent_semantic_acceptance=False,
        ),
    )
    print(
        "Three configurations identical; 51 facts and nine real-source direct projections passed."
    )


def sources(page, topic, title, name):
    card = page.locator(
        ".materials-section .requirement-card",
        has=page.get_by_role("heading", name=title, exact=True),
    )
    card.get_by_role("button").last.click()
    drawer = page.locator("#evidence-drawer")
    drawer.wait_for(state="visible")
    assert drawer.locator(".relation-node").count() == len(topic["records"])
    page.screenshot(path=str(OUT / f"{name}-{topic['topic_id']}-relations.png"))
    for record in topic["records"]:
        button = drawer.locator(
            f'.relation-node button[data-record-id="{record["record_id"]}"]'
        ).first
        button.click()
        quotes = drawer.locator("blockquote").all_text_contents()
        assert all(any(f["quote_text"] in q for q in quotes) for f in record["fragments"])
        drawer.locator("blockquote").first.scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / f"{name}-{record['record_id']}-source.png"))
        drawer.locator(".relation-back").click()
        assert button.evaluate("e=>e===document.activeElement")
    page.locator("#drawer-close").click()


def live(url):
    helper = previous.historical("author01-browser-check.py")
    helper.OUT = OUT
    with httpx.Client(base_url=url, timeout=30) as client:
        for filename in [
            "material-presentation-catalog.mjs",
            "m19-material-presentation.mjs",
            "reviewed-material-presentation.mjs",
        ]:
            response = client.get("/assets/" + filename)
            assert (
                response.status_code == 200 and response.content == (STATIC / filename).read_bytes()
            )
            assert response.headers["cache-control"] == "no-store"
            save(
                filename + ".http.json",
                dict(
                    method="real_HTTP_GET",
                    status=response.status_code,
                    bytes=len(response.content),
                    sha256=sha256(response.content).hexdigest(),
                    headers=dict(response.headers),
                ),
            )
        catalog = client.get("/v1/reference-targets").json()
        entry = next(r for r in catalog["items"] if r["kind"] == "reviewed_material_slice")
        evidence = client.get(f"/v1/reference-slices/{entry['entry_id']}/evidence").json()
        generation = client.get("/v1/generation-status").json()
        assert generation["configured"] is False and evidence == parse_json(
            (OUT / "direct-evidence.json").read_bytes()
        )
    save("live-catalog.json", catalog)
    save("live-evidence.json", evidence)
    save("live-generation-status.json", generation)
    journal = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(EDGE))
        try:
            for name, width, current, retain in [
                ("desktop", 1440, "yes", "yes"),
                ("mobile", 390, "no", "unknown"),
            ]:
                context = browser.new_context(
                    viewport=dict(width=width, height=844),
                    permissions=["clipboard-read", "clipboard-write"],
                )
                page = context.new_page()
                errors = []
                posts = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on(
                    "request",
                    lambda r: posts.append(r.post_data_json) if r.method == "POST" else None,
                )
                page.goto(url + "/app/advanced")
                page.locator(f'#school-select option[value="{entry["entry_id"]}"]').wait_for(
                    state="attached"
                )
                helper.select_slice(page, entry["entry_id"])
                assert page.locator(".materials-section .requirement-card").count() == 5
                titles = [
                    "英语成绩单",
                    "提交材料检查表",
                    "学业与职务兼顾计划书",
                    "申请小论文",
                    "报考志愿调查表",
                ]
                for topic, title in zip(evidence["topics"], titles, strict=True):
                    if topic["topic_id"] in ["application-essay", "application-questionnaire"]:
                        card = page.locator(
                            ".materials-section .requirement-card",
                            has=page.get_by_role("heading", name=title, exact=True),
                        )
                        card.locator("summary", has_text="如何准备").click()
                        if topic["topic_id"] == "application-questionnaire":
                            for step in parse_json(
                                (DOCS / "m19-questionnaire-authoring.json").read_bytes()
                            )["reader"]["steps"]:
                                assert step["text"] in card.inner_text()
                        card.scroll_into_view_if_needed()
                        page.screenshot(path=str(OUT / f"{name}-{topic['topic_id']}-guide.png"))
                        sources(page, topic, title, name)
                page.locator("#requirements-continue").click()
                assert page.locator("#slice-material-preparation select").count() == 2
                essay = page.locator('[data-slice-material-code="application-essay"]')
                questionnaire = page.locator(
                    '[data-slice-material-code="application-questionnaire"]'
                )
                questionnaire.select_option("available")
                assert essay.input_value() == "unknown"
                essay.select_option("not_yet")
                assert questionnaire.input_value() == "available"
                page.locator("#slice-current-employed").select_option(current)
                page.locator("#slice-retain-employed").select_option(retain)
                with page.expect_response(
                    lambda r: r.request.method == "POST" and r.url.endswith("/reports")
                ) as pending:
                    page.locator("#comparison-submit").click()
                response = pending.value
                assert response.status == 200
                actual = response.json()
                assert actual == parse_json(
                    (OUT / f"direct-report-{current}-{retain}.json").read_bytes()
                )
                save(f"live-{name}-report.json", actual)
                save(f"live-{name}-request.json", posts[-1])
                page.locator("#readiness-panel").wait_for(state="visible")
                combinations = [
                    ("available", "not_yet"),
                    ("not_yet", "available"),
                    ("unknown", "unknown"),
                ]
                for index, (q, e) in enumerate(combinations):
                    if index:
                        page.locator("#edit-applicant").click()
                        questionnaire.select_option(q)
                        essay.select_option(e)
                        assert page.locator("#readiness-panel").is_hidden()
                        page.locator("#comparison-submit").click()
                        page.locator("#readiness-panel").wait_for(state="visible")
                    page.locator("#readiness-panel .reference-generate").click()
                    page.locator("#reference-report").wait_for(state="visible")
                    copied = helper.copy_report(page)
                    assert (
                        "报考志愿调查表" in copied
                        and "申请小论文" in copied
                        and "第4志愿" in copied
                    )
                    assert "不是完整清单" in copied
                    (OUT / f"{name}-copy-{q}-{e}.txt").write_text(copied + "\n", encoding="utf-8")
                    page.screenshot(path=str(OUT / f"{name}-report-{q}-{e}.png"))
                    page.locator("#reference-close").click()
                assert len(posts) == 1
                page.locator("#change-school").click()
                legacy = next(r for r in catalog["items"] if r["kind"] == "legacy_applicant")
                page.locator("#school-select").select_option(legacy["legacy_catalog"]["school_id"])
                assert page.locator("#slice-material-preparation").is_hidden()
                helper.select_slice(page, entry["entry_id"])
                page.locator("#requirements-continue").click()
                assert essay.input_value() == questionnaire.input_value() == "unknown"
                assert page.locator("#reference-copy").is_disabled()
                assert (
                    page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    and not errors
                )
                journal.append(
                    dict(
                        viewport=width,
                        actual_report_posts=len(posts),
                        status=response.status,
                        independent_controls=True,
                        school_change_clears_both=True,
                        errors=errors,
                    )
                )
                save("live-browser-journal.json", journal)
                context.close()
        finally:
            browser.close()
    print(
        "Real desktop/mobile five-topic page, all 14 new fragments, two controls and clipboard verified."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--live-url")
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--audit", choices=["before", "after"])
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    previous.OUT = OUT
    if args.audit:
        asset_audit.OUT = OUT
        sys.argv = ["asset-audit", args.audit]
        asset_audit.main()
    if args.prepare:
        prepare()
    if args.live_url:
        live(args.live_url.rstrip("/"))
    if args.replay:
        previous.replay()
        replay_isct_materials()
        previous.OUT = OUT / "legacy-v2"
        previous.OUT.mkdir(exist_ok=True)
        for path in (DOCS / "m18-evidence").glob("direct-*.json"):
            shutil.copyfile(path, previous.OUT / path.name)
        previous.live("http://127.0.0.1:8016", replay_v2=True)
    save("budget-snapshot.json", parse_json(LEDGER.read_bytes()))


def replay_isct_materials():
    """The accepted Science Tokyo material response on this PR's current page."""
    payload = parse_json((DOCS / "exam02b-evidence/computer-science-base-v2.json").read_bytes())
    payload["examination_information"] = parse_json(
        (DOCS / "exam02b-evidence/review-v2-exam-overlays.json").read_bytes()
    )["computer-science-base-v2.json"]
    catalog = parse_json((DOCS / "prep01-evidence/reference-targets.json").read_bytes())
    helper = previous.historical("author01-browser-check.py")
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(EDGE))
        try:
            for width in [1440, 390]:
                context = browser.new_context(
                    viewport=dict(width=width, height=844),
                    permissions=["clipboard-read", "clipboard-write"],
                )
                page = context.new_page()
                requests = []
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))

                def route_request(route):
                    path = urlparse(route.request.url).path.lstrip("/")
                    if path == "app/advanced":
                        route.fulfill(
                            body=(STATIC / "advanced.html").read_bytes(), content_type="text/html"
                        )
                    elif path.startswith("assets/"):
                        name = path.rsplit("/", 1)[-1]
                        route.fulfill(
                            body=(STATIC / name).read_bytes(),
                            content_type="text/css" if name.endswith(".css") else "text/javascript",
                        )
                    elif path == "v1/reference-targets":
                        route.fulfill(json=catalog)
                    elif path == "v1/generation-status":
                        route.fulfill(
                            json=dict(
                                configured=False, request_timeout_seconds=60, label="saved replay"
                            )
                        )
                    elif path == "v1/base-requirements":
                        requests.append(route.request.post_data_json)
                        route.fulfill(json=payload)
                    else:
                        route.abort()

                page.route("**/*", route_request)
                page.goto("http://127.0.0.1:8016/app/advanced")
                page.locator("#school-select").select_option("isct")
                for selector in ["#intake-select", "#college-select", "#department-select"]:
                    if selector == "#intake-select":
                        page.locator(selector).select_option("isct_2027_4_2026_9_master:2027:4")
                    elif selector == "#college-select":
                        page.locator(selector).select_option(payload["target"]["college_name"])
                    else:
                        page.locator(selector).select_option(payload["target"]["department_name"])
                page.locator("#route-select").select_option("b_schedule")
                page.locator("#requirements-submit").click()
                try:
                    page.locator(".exam-arrangement").wait_for(state="visible", timeout=5000)
                except Exception:
                    print(
                        json.dumps(
                            dict(
                                errors=errors,
                                requests=requests,
                                page=page.locator("body").inner_text()[-6000:],
                            ),
                            ensure_ascii=False,
                        )
                    )
                    raise
                page.locator("#step-2-panel .reference-generate").click()
                page.locator("#reference-report").wait_for(state="visible")
                for checkbox in page.locator(".reader-report-options input").all():
                    if checkbox.is_checked():
                        checkbox.uncheck()
                page.locator(".reader-report-options label", has_text="材料与待办").locator(
                    "input"
                ).check()
                copied = helper.copy_report(page)
                assert "材料准备清单" in copied and "入学申请表" in copied
                assert "报考志愿调查表" not in copied and "申请小论文" not in copied
                (OUT / f"isct-materials-{width}-copy.txt").write_text(
                    copied + "\n", encoding="utf-8"
                )
                page.screenshot(path=str(OUT / f"isct-materials-{width}-report.png"))
                assert len(requests) == 1 and not errors
                rows.append(
                    dict(
                        width=width,
                        actual_product_posts=0,
                        intercepted_posts=1,
                        source="saved exam02b computer-science base plus accepted exam overlay; materials unchanged",
                        copy_sha256=sha256(copied.encode()).hexdigest(),
                    )
                )
                context.close()
        finally:
            browser.close()
    save("isct-materials-replay-journal.json", rows)


if __name__ == "__main__":
    main()
