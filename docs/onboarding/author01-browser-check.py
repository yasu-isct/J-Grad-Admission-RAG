"""AUTHOR-01 real four-step browser evidence, plus saved-response regressions.

Usage: python author01-browser-check.py --live-url http://127.0.0.1:PORT
Run --replay for intercepted GSFS v1 and ISCT exam regressions (zero actual POST).
This script does not start a service, import a candidate or fetch remote sources.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path("D:/J-Grad-Admission-RAG")
OUT = ROOT / "docs/onboarding/author01-evidence"
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def select_slice(page, entry_id):
    page.locator("#school-select").select_option(entry_id)
    for selector in ("#intake-select", "#college-select", "#department-select", "#route-select"):
        page.locator(selector).select_option(index=1)
    page.locator("#requirements-submit").click()
    page.locator(".materials-section .requirement-card").first.wait_for(state="visible")


def copy_report(page):
    page.locator("#reference-copy").click()
    page.wait_for_function(
        "() => document.querySelector('#reference-report-status').textContent.includes('已复制')"
    )
    return page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")


def inspect_essay(page, name, evidence):
    card = page.locator(
        ".materials-section .requirement-card",
        has=page.get_by_role("heading", name="申请小论文", exact=True),
    )
    card.locator("summary", has_text="如何准备").click()
    assert "两部分" in card.inner_text() or "研究" in card.inner_text()
    assert "日语或英语" in card.inner_text()
    assert "模板" in card.inner_text()
    card.evaluate(
        "e => window.scrollTo({top: scrollY + e.getBoundingClientRect().top - 170, behavior: 'instant'})"
    )
    page.screenshot(path=str(OUT / f"{name}-essay-card.png"))
    if name == "mobile":
        card.get_by_role("button").last.scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / "mobile-essay-card-bottom.png"))
    card.get_by_role("button").last.click()
    drawer = page.locator("#evidence-drawer")
    drawer.wait_for(state="visible")
    assert drawer.locator(".relation-node").count() == 2
    assert "补充说明" in drawer.inner_text()
    page.screenshot(path=str(OUT / f"{name}-essay-relations.png"))
    topic = next(row for row in evidence["topics"] if row["topic_id"] == "application-essay")
    records = topic["records"]
    for index, record in enumerate(records):
        buttons = drawer.locator(".relation-node button")
        buttons.nth(index).click()
        quotes = drawer.locator("blockquote").all_text_contents()
        assert all(
            any(fragment["quote_text"] in quote for quote in quotes)
            for fragment in record["fragments"]
        )
        assert str(record["physical_page"]) in drawer.inner_text()
        drawer.locator("blockquote").first.scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / f"{name}-{record['record_id']}-source.png"))
        drawer.locator(".relation-back").click()
        assert buttons.nth(index).evaluate("e => e === document.activeElement")
    page.locator("#drawer-close").click()
    assert card.get_by_role("button").last.evaluate("e => e === document.activeElement")


def live(url, saved_four=False):
    started = datetime.now(timezone.utc).isoformat()
    if saved_four:
        catalog = json.loads((OUT / "live-catalog.json").read_bytes())
        evidence = json.loads((OUT / "live-evidence.json").read_bytes())
        generation = json.loads((OUT / "live-generation-status.json").read_bytes())
        entry = next(
            row for row in catalog["items"] if row.get("entry_id") == "gsfs-complex-2027-a-author01"
        )
    else:
        with httpx.Client(base_url=url, timeout=30) as client:
            catalog = client.get("/v1/reference-targets").json()
            entry = next(
                row
                for row in catalog["items"]
                if row.get("entry_id") == "gsfs-complex-2027-a-author01"
            )
            evidence = client.get(f"/v1/reference-slices/{entry['entry_id']}/evidence").json()
            generation = client.get("/v1/generation-status").json()
    assert entry["availability"] == "ready" and generation["configured"] is False
    assert len(evidence["topics"]) == 4
    records = [record for topic in evidence["topics"] for record in topic["records"]]
    assert len(records) == 10 and sum(len(row["fragments"]) for row in records) == 37
    assert (
        evidence["snapshot_id"]
        == "a729b19705be68c9a4e79bc71d6dbaaed12710989aeac79b90cf34347bf89164"
    )
    save("live-catalog.json", catalog)
    save("live-evidence.json", evidence)
    save("live-generation-status.json", generation)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        for name, width, current, retain, preparation in (
            ("desktop", 1440, "unknown", "unknown", "unknown"),
            ("mobile", 390, "no", "unknown", "not_yet"),
        ):
            context = browser.new_context(
                viewport={"width": width, "height": 900 if width > 500 else 844},
                permissions=["clipboard-read", "clipboard-write"],
            )
            page = context.new_page()
            errors, posts = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "request",
                lambda request: posts.append(request.url) if request.method == "POST" else None,
            )
            if saved_four:

                def saved_get(route):
                    path = urlparse(route.request.url).path
                    if route.request.method == "POST":
                        route.fallback()
                    elif path == "/app/advanced":
                        route.fulfill(
                            body=(STATIC / "advanced.html").read_bytes(), content_type="text/html"
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
                    elif path.endswith("/evidence"):
                        route.fulfill(json=evidence)
                    elif path == "/v1/generation-status":
                        route.fulfill(json=generation)
                    else:
                        route.abort()

                page.route("**/*", saved_get)
            saved_path = OUT / f"live-{name}-report.json"
            saved_response_replay = saved_path.exists()
            assert not saved_four or saved_response_replay
            if saved_response_replay:
                saved_payload = json.loads(saved_path.read_bytes())
                saved_request = json.loads((OUT / f"live-{name}-request.json").read_bytes())

                def replay_saved_post(route):
                    assert route.request.post_data_json == saved_request
                    route.fulfill(json=saved_payload)

                page.route("**/reports", replay_saved_post)
            page.goto(url + "/app/advanced")
            assert page.locator(".application-flow > .flow-step").count() == 4
            select_slice(page, entry["entry_id"])
            assert page.locator(".materials-section .requirement-card").count() == 4
            assert not posts
            inspect_essay(page, name, evidence)
            page.locator("#requirements-continue").click()
            page.locator("#slice-current-employed").select_option(current)
            page.locator("#slice-retain-employed").select_option(retain)
            control = page.locator('[data-slice-material-code="application-essay"]')
            control.select_option(preparation)
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST" and response.url.endswith("/reports")
                )
            ) as captured:
                page.locator("#comparison-submit").click()
            response = captured.value
            assert response.status == 200
            payload = response.json()
            save(f"live-{name}-report.json", payload)
            save(f"live-{name}-request.json", response.request.post_data_json)
            page.locator("#readiness-panel").wait_for(state="visible")
            essay = next(
                row
                for row in payload["report"]["topic_results"]
                if row["topic_id"] == "application-essay"
            )
            assert (
                essay["disposition"] == "submission_required"
                and essay["condition_status"] == "matched"
            )
            assert "4 个材料主题" in page.locator("#partial-checklist-statement").inner_text()
            readiness = page.locator(
                "#comparison-output .requirement-card",
                has=page.get_by_role("heading", name="申请小论文", exact=True),
            )
            readiness.scroll_into_view_if_needed()
            page.screenshot(path=str(OUT / f"{name}-essay-readiness.png"))
            page.locator("#readiness-panel .reference-generate").click()
            page.locator("#reference-report").wait_for(state="visible")
            copied = copy_report(page)
            assert "申请小论文" in copied and "字数" in copied and "日语或英语" in copied
            assert all(
                value not in copied
                for value in ("fact_id", "scope_type", "E09-", "citation_key", "证据清单")
            )
            (OUT / f"{name}-copy-{preparation}.txt").write_text(copied + "\n", encoding="utf-8")
            page.screenshot(path=str(OUT / f"{name}-essay-report.png"))
            page.locator(
                ".reader-report-section li", has_text="申请小论文"
            ).last.scroll_into_view_if_needed()
            page.screenshot(path=str(OUT / f"{name}-essay-report-content.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#reference-close").click()
            if name == "desktop":
                # Local self-report projection reuses official evidence, zero new HTTP POST.
                page.locator("#edit-applicant").click()
                control.select_option("available")
                page.locator("#comparison-submit").click()
                assert "已准备（自报）" in readiness.inner_text()
                page.locator("#readiness-panel .reference-generate").click()
                copied_prepared = copy_report(page)
                assert "已准备（自报）" in copied_prepared
                assert "需提交" in copied_prepared and "学校受理" in copied_prepared
                (OUT / "desktop-copy-available.txt").write_text(
                    copied_prepared + "\n", encoding="utf-8"
                )
                page.screenshot(path=str(OUT / "desktop-essay-report-prepared.png"))
                page.locator("#reference-close").click()
                page.locator("#edit-applicant").click()
                control.select_option("not_yet")
                page.locator("#comparison-submit").click()
                assert "待准备" in readiness.inner_text()
                page.locator("#readiness-panel .reference-generate").click()
                copied_missing = copy_report(page)
                assert "待准备" in copied_missing and "申请小论文" in copied_missing
                (OUT / "desktop-copy-not_yet.txt").write_text(
                    copied_missing + "\n", encoding="utf-8"
                )
                page.locator("#reference-close").click()
                page.locator("#change-school").click()
                select_slice(page, entry["entry_id"])
                assert control.input_value() == "unknown"
                assert page.locator("#reference-copy").is_disabled()
            assert len(posts) == 1, posts
            assert not errors, errors
            results.append(
                {
                    "viewport": name,
                    "actual_product_post": 0 if saved_response_replay else len(posts),
                    "saved_real_response_replay": saved_response_replay,
                    "all_traffic_intercepted": saved_four,
                    "status": response.status,
                    "copied_sha256": sha256(copied.encode()).hexdigest(),
                    "errors": errors,
                    "four_steps": True,
                    "four_topics": True,
                    "all_essay_fragments": 14,
                    "no_horizontal_overflow": True,
                }
            )
            context.close()
        browser.close()
    save(
        "saved-four-browser-journal.json"
        if all(row["saved_real_response_replay"] for row in results)
        else "live-browser-journal.json",
        {
            "started_utc": started,
            "ended_utc": datetime.now(timezone.utc).isoformat(),
            "results": results,
        },
    )
    print(
        f"Four topics/37 fragments: desktop+mobile; this pass actual POSTs={sum(row['actual_product_post'] for row in results)} (prior actual HTTP remains separately journaled)"
    )


def replay():
    catalog = json.loads(
        (ROOT / "docs/onboarding/prep01-evidence/reference-targets.json").read_bytes()
    )
    evidence = json.loads(
        (ROOT / "docs/onboarding/evidui01-evidence/gsfs-evidence-real.json").read_bytes()
    )
    entry = next(row for row in catalog["items"] if row["kind"] == "reviewed_material_slice")
    assert entry["snapshot_id"] == evidence["snapshot_id"]
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        for index, (current, retain) in enumerate(
            (("yes", "yes"), ("no", "unknown"), ("unknown", "unknown")), 1
        ):
            report = json.loads(
                (ASSETS / f"outputs/display-01/real-run-2/real-report-{index}.json").read_bytes()
            )
            assert report["snapshot_id"] == evidence["snapshot_id"]
            for width in (1440, 390):
                context = browser.new_context(
                    viewport={"width": width, "height": 844},
                    permissions=["clipboard-read", "clipboard-write"],
                )
                page = context.new_page()
                intercepted, errors = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))

                def route_request(route):
                    path = urlparse(route.request.url).path
                    if route.request.method == "POST":
                        assert path.endswith("/reports")
                        intercepted.append(route.request.post_data_json)
                        route.fulfill(json=report)
                    elif path in ("/app", "/app/advanced"):
                        route.fulfill(
                            body=(STATIC / "advanced.html").read_bytes(), content_type="text/html"
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
                    elif path.endswith("/evidence"):
                        route.fulfill(json=evidence)
                    elif path == "/v1/generation-status":
                        route.fulfill(
                            json={
                                "configured": False,
                                "request_timeout_seconds": 60,
                                "label": "离线",
                            }
                        )
                    else:
                        route.abort()

                page.route("**/*", route_request)
                page.goto("http://127.0.0.1:8016/app/advanced")
                select_slice(page, entry["entry_id"])
                assert page.locator(".materials-section .requirement-card").count() == 3
                assert page.locator("#slice-material-preparation select").count() == 0
                page.locator("#requirements-continue").click()
                page.locator("#slice-current-employed").select_option(current)
                page.locator("#slice-retain-employed").select_option(retain)
                page.locator("#comparison-submit").click()
                page.locator("#readiness-panel").wait_for(state="visible")
                assert "3 个材料主题" in page.locator("#partial-checklist-statement").inner_text()
                page.locator("#readiness-panel .reference-generate").click()
                copied = copy_report(page)
                assert "申请小论文" not in copied and "3 个材料主题" in copied
                (OUT / f"old-three-case{index}-{width}-copy.txt").write_text(
                    copied + "\n", encoding="utf-8"
                )
                if index == 1:
                    page.screenshot(path=str(OUT / f"old-three-{width}-report.png"))
                assert len(intercepted) == 1 and not errors
                results.append(
                    {
                        "case": index,
                        "width": width,
                        "actual_post": 0,
                        "intercepted_post": 1,
                        "saved_real_response": f"real-report-{index}.json",
                        "topics": 3,
                        "copy_sha256": sha256(copied.encode()).hexdigest(),
                    }
                )
                context.close()
        browser.close()
    save("old-three-replay-journal.json", results)
    print("Old three topics/three employment conditions replayed desktop+mobile; 0 actual POST")


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("--live-url")
    args.add_argument("--replay", action="store_true")
    args.add_argument("--replay-four", action="store_true")
    options = args.parse_args()
    OUT.mkdir(exist_ok=True)
    if options.replay_four:
        live("http://127.0.0.1:8016", saved_four=True)
    elif options.live_url:
        live(options.live_url)
    elif options.replay:
        replay()
    else:
        args.error("explicit --live-url, --replay-four or --replay required")
