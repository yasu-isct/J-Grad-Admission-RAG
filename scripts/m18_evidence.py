"""M18 measured generation, direct projection, real browser and saved replay evidence.

The --live-url action never starts a service; only its three explicit browser
checks issue actual product POSTs. --prepare and --replay use zero product HTTP.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from time import monotonic
from urllib.parse import urlparse

import httpx
from playwright.sync_api import sync_playwright

from jgrad_admission_rag.reviewed_source_evidence import canonical_json_bytes, parse_json
from scripts import m18_presentation as generator


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/onboarding"
OUT = DOCS / "m18-evidence"
ASSETS = Path("D:/J-Grad-Admission-RAG")
CANDIDATE = (
    ASSETS
    / "outputs/reviewed-source-candidates/7ea490375de4c28859ca38dd76bb3952aa8b3d601aa3ccc9eeb5f4ee93cad752"
)
PDFS = ASSETS / "outputs/source-documents/utokyo-gsfs/2027"
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
DESCRIPTOR = DOCS / "m18-presentation-build.json"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def save(name, value):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def historical(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), DOCS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT = OUT  # reuse accepted helper, never overwrite old evidence
    return module


def prepare():
    started = datetime.now(timezone.utc).isoformat()
    runs = []
    files = None
    with tempfile.TemporaryDirectory(prefix="m18-reproduce-") as directory:
        temp = Path(directory)
        # Only small author/metadata files move. PDF/candidate/model/runtime stay at
        # original paths; local paths never enter the generated content identity.
        copied = temp / "second-workspace"
        copied.mkdir()
        descriptor = parse_json(DESCRIPTOR.read_bytes())
        names = set(descriptor["metadata"].values()) | {
            DESCRIPTOR.name,
            descriptor["authoring"],
            descriptor["displays"],
            descriptor["preview_template"],
        }
        for name in names:
            shutil.copyfile(DOCS / name, copied / name)
        for index, path in enumerate((DESCRIPTOR, DESCRIPTOR, copied / DESCRIPTOR.name)):
            clock = monotonic()
            current = generator.build(path, CANDIDATE, PDFS)
            runs.append(
                {
                    "run": index + 1,
                    "seconds": monotonic() - clock,
                    "bytes": sum(map(len, current.values())),
                    "other_workspace": index == 2,
                }
            )
            assert files is None or current == files
            files = current
        output = temp / "generated"
        generator.write_or_check(files, output)
        before = {p.name: p.stat().st_mtime_ns for p in output.iterdir()}
        generator.write_or_check(generator.build(DESCRIPTOR, CANDIDATE, PDFS), output, check=True)
        assert before == {p.name: p.stat().st_mtime_ns for p in output.iterdir()}
        (output / generator.MODULE).write_bytes(files[generator.MODULE] + b" ")
        try:
            generator.write_or_check(files, output, check=True)
        except ValueError:
            drift_rejected = True
        else:
            raise AssertionError("drift was not rejected")
    generator.write_or_check(files, STATIC)
    preview = generator.preview_config(DESCRIPTOR, CANDIDATE, PDFS)
    (ASSETS / "outputs/m18-audit/preview.json").write_bytes(canonical_json_bytes(preview))
    snapshot = generator.load_snapshot(DESCRIPTOR, CANDIDATE, PDFS)
    save("direct-evidence.json", parse_json(snapshot.presentation))
    rows = []
    for current in (True, False, None):
        for retain in (True, False, None):
            request = parse_json(
                (DOCS / "author01-evidence/live-desktop-request.json").read_bytes()
            )
            request["employment"] = {
                "currently_employed_in_organization": current,
                "retain_employment_at_enrollment": retain,
            }
            clock = monotonic()
            report = snapshot.report(canonical_json_bytes(request))
            expected_work = (
                "submission_required"
                if current is True and retain is True
                else (
                    "rule_not_applicable"
                    if current is False or retain is False
                    else "needs_information"
                )
            )
            dispositions = [row["disposition"] for row in report["report"]["topic_results"]]
            assert dispositions == [
                "submission_not_required",
                "submission_not_required",
                expected_work,
                "submission_required",
            ]

            def name(value):
                return "yes" if value is True else "no" if value is False else "unknown"

            filename = f"direct-report-{name(current)}-{name(retain)}.json"
            save(filename, report)
            rows.append(
                {
                    "current": current,
                    "retain": retain,
                    "dispositions": dispositions,
                    "seconds": monotonic() - clock,
                    "method": "direct_existing_report_projection",
                    "actual_product_post": 0,
                    "file": filename,
                }
            )
    save(
        "generation-and-direct-journal.json",
        {
            "started_utc": started,
            "ended_utc": datetime.now(timezone.utc).isoformat(),
            "generation": runs,
            "byte_identical": True,
            "check_mtime_unchanged": True,
            "drift_rejected": drift_rejected,
            "content_id": parse_json(files[generator.MANIFEST])["content_id"],
            "employment_combinations": rows,
        },
    )
    print(
        "Three identical display generations, read-only check, drift and nine direct combinations passed"
    )


def inspect_sources(page, topic, name):
    card = page.locator(
        ".materials-section .requirement-card",
        has=page.get_by_role("heading", name=name, exact=True),
    )
    card.get_by_role("button").last.click()
    drawer = page.locator("#evidence-drawer")
    drawer.wait_for(state="visible")
    shown = set(
        drawer.locator(".relation-node").evaluate_all(
            "nodes => nodes.map(node => node.dataset.recordId)"
        )
    )
    assert shown == {record["record_id"] for record in topic["records"]}
    for record in topic["records"]:
        button = drawer.locator(
            f'.relation-node button[data-record-id="{record["record_id"]}"]'
        ).first
        button.click()
        quotes = drawer.locator("blockquote").all_text_contents()
        assert all(
            any(fragment["quote_text"] in quote for quote in quotes)
            for fragment in record["fragments"]
        )
        drawer.locator(".relation-back").click()
        assert button.evaluate("e => e === document.activeElement")
    page.locator("#drawer-close").click()
    assert card.get_by_role("button").last.evaluate("e => e === document.activeElement")


def live(url, replay_v2=False):
    helper = historical("author01-browser-check.py")
    if replay_v2:
        catalog = parse_json((DOCS / "author01-evidence/live-catalog.json").read_bytes())
        evidence = parse_json((OUT / "direct-evidence.json").read_bytes())
        generation = parse_json(
            (DOCS / "author01-evidence/live-generation-status.json").read_bytes()
        )
        entry = next(row for row in catalog["items"] if row["kind"] == "reviewed_material_slice")
    else:
        client = httpx.Client(base_url=url, timeout=30)
        try:
            module = client.get("/assets/" + generator.MODULE)
            assert (
                module.status_code == 200
                and module.content == (STATIC / generator.MODULE).read_bytes()
            )
            assert "script-src 'self'" in module.headers["content-security-policy"]
            assert module.headers["cache-control"] == "no-store"
            catalog = client.get("/v1/reference-targets").json()
            entry = next(
                row for row in catalog["items"] if row["kind"] == "reviewed_material_slice"
            )
            assert entry["availability"] == "ready"
            evidence = client.get(f"/v1/reference-slices/{entry['entry_id']}/evidence").json()
            generation = client.get("/v1/generation-status").json()
            assert not generation["configured"]
        finally:
            client.close()
        save(
            "static-http.json",
            {
                "status": module.status_code,
                "bytes": len(module.content),
                "sha256": sha256(module.content).hexdigest(),
                "headers": dict(module.headers),
                "method": "real_HTTP_GET",
            },
        )
        save("live-catalog.json", catalog)
        save("live-evidence.json", evidence)
        save("live-generation-status.json", generation)
    assert evidence == parse_json((OUT / "direct-evidence.json").read_bytes())
    rows = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        try:
            for name, width, current, retain in (
                ("desktop", 1440, "yes", "yes"),
                ("mobile", 390, "no", "unknown"),
                ("unknown", 1440, "unknown", "unknown"),
            ):
                context = browser.new_context(
                    viewport={"width": width, "height": 844},
                    permissions=["clipboard-read", "clipboard-write"],
                )
                page = context.new_page()
                errors, posts = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "request",
                    lambda request: (
                        posts.append(request.post_data_json) if request.method == "POST" else None
                    ),
                )
                if replay_v2:

                    def route_request(route):
                        path = urlparse(route.request.url).path
                        if path == "/app/advanced":
                            route.fulfill(
                                body=(STATIC / "advanced.html").read_bytes(),
                                content_type="text/html",
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
                            route.fulfill(json=catalog)
                        elif path == "/v1/generation-status":
                            route.fulfill(json=generation)
                        elif path.endswith("/evidence"):
                            route.fulfill(json=evidence)
                        elif path.endswith("/reports"):
                            payload = parse_json(
                                (OUT / f"direct-report-{current}-{retain}.json").read_bytes()
                            )
                            route.fulfill(
                                body=canonical_json_bytes(payload), content_type="application/json"
                            )
                        else:
                            route.abort()

                    page.route("**/*", route_request)
                page.goto(url + "/app/advanced")
                page.locator(f'#school-select option[value="{entry["entry_id"]}"]').wait_for(
                    state="attached"
                )
                helper.select_slice(page, entry["entry_id"])
                assert page.locator(".materials-section .requirement-card").count() == 4
                if name != "unknown":
                    for topic, display_name in zip(
                        evidence["topics"],
                        ("英语成绩单", "提交材料检查表", "学业与职务兼顾计划书", "申请小论文"),
                        strict=True,
                    ):
                        inspect_sources(page, topic, display_name)
                    helper.inspect_essay(page, name, evidence)
                page.locator("#requirements-continue").click()
                page.locator("#slice-current-employed").select_option(current)
                page.locator("#slice-retain-employed").select_option(retain)
                control = page.locator('[data-slice-material-code="application-essay"]')
                assert page.locator("#slice-material-preparation select").count() == 1
                with page.expect_response(
                    lambda response: (
                        response.request.method == "POST" and response.url.endswith("/reports")
                    )
                ) as pending:
                    page.locator("#comparison-submit").click()
                response = pending.value
                actual = response.json()
                if not replay_v2:
                    save(f"live-{name}-report.json", actual)
                    save(f"live-{name}-request.json", posts[-1])
                assert response.status == 200
                assert actual == parse_json(
                    (OUT / f"direct-report-{current}-{retain}.json").read_bytes()
                )
                page.locator("#readiness-panel").wait_for(state="visible")
                for state, expected in (
                    ("unknown", "需提交，尚未填写准备情况"),
                    ("available", "已准备（自报）"),
                    ("not_yet", "待准备"),
                ):
                    if state != "unknown":
                        page.locator("#edit-applicant").click()
                        control.select_option(state)
                        assert page.locator("#readiness-panel").is_hidden()
                        page.locator("#comparison-submit").click()
                        page.locator("#readiness-panel").wait_for(state="visible")
                    page.locator("#readiness-panel .reference-generate").click()
                    page.locator("#reference-report").wait_for(state="visible")
                    copied = helper.copy_report(page)
                    assert (
                        expected in copied and "日语或英语" in copied and "不是完整清单" in copied
                    )
                    (OUT / f"{name}-copy-{state}.txt").write_text(copied + "\n", encoding="utf-8")
                    if state == "not_yet":
                        page.screenshot(path=str(OUT / f"{name}-report.png"))
                    page.locator("#reference-close").click()
                assert len(posts) == 1, posts
                # Selection changes clear all personal preparation and stale copy.
                page.locator("#change-school").click()
                legacy = next(row for row in catalog["items"] if row["kind"] == "legacy_applicant")
                page.locator("#school-select").select_option(legacy["legacy_catalog"]["school_id"])
                assert page.locator("#slice-material-preparation").is_hidden()
                helper.select_slice(page, entry["entry_id"])
                page.locator("#requirements-continue").click()
                assert control.input_value() == "unknown"
                assert page.locator("#slice-current-employed").input_value() == "unknown"
                assert page.locator("#reference-copy").is_disabled()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not errors
                rows.append(
                    {
                        "viewport": name,
                        "width": width,
                        "employment": [current, retain],
                        "actual_product_post": 0 if replay_v2 else len(posts),
                        "intercepted_post": len(posts) if replay_v2 else 0,
                        "method": "direct_projection_saved_replay"
                        if replay_v2
                        else "real_HTTP_browser",
                        "status": response.status,
                        "all_37_fragments": name != "unknown",
                        "preparation_states": 3,
                        "original_source_focus_return": name != "unknown",
                        "cross_school_clear": True,
                        "errors": errors,
                    }
                )
                save(
                    "v2-replay-browser-journal.json" if replay_v2 else "live-browser-journal.json",
                    rows,
                )
                context.close()
        finally:
            browser.close()
    print(
        f"{'Saved replay: 0 actual' if replay_v2 else 'Real offline HTTP: 3'} report POSTs; desktop/mobile sources, self-report and copied reports passed"
    )


def replay():
    helper = historical("author01-browser-check.py")
    helper.replay()
    historical("author01-isct-replay.py").main()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--live-url")
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--replay-v2", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    if args.live_url:
        live(args.live_url.rstrip("/"))
    if args.replay:
        replay()
    if args.replay_v2:
        live("http://127.0.0.1:8016", replay_v2=True)


if __name__ == "__main__":
    main()
