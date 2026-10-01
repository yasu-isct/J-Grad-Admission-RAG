"""UX-03 urgent before/after replay from saved responses; no product server.

The QR-absent comparison is a clearly labelled in-memory synthetic variant of a
saved real response. It changes one English check only, not application facts.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


TREE = Path(__file__).resolve().parents[2]
STATIC = TREE / "src/jgrad_admission_rag/service/static"
OUT = TREE / "docs/onboarding/ux03-urgent-evidence"
SAVED_GSFS = TREE.parent / "ui02-real/final-head-cd09bd4"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
BASELINE = "57463a0282fdeb992b1d1f3daec203b76c7ffc93"
ORIGIN = "http://ux03-replay.test"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def static_bytes(name: str, before: bool) -> bytes:
    if not before:
        return (STATIC / name).read_bytes()
    result = subprocess.run(
        ["git", "show", f"{BASELINE}:src/jgrad_admission_rag/service/static/{name}"],
        cwd=TREE,
        check=True,
        capture_output=True,
    )
    return result.stdout


def synthetic_qr_absent(saved: dict) -> dict:
    result = copy.deepcopy(saved)
    qr = next(
        item
        for item in result["english_preparation_result"]["checks"]
        if item["check_id"] == "english:toeic_verification_qr_present"
    )
    qr["status"] = "action_needed"
    qr["explanation"] = "本人明确填写尚未准备 TOEIC 真伪验证二维码。"
    qr["next_action"] = "准备带真伪验证二维码的指定证明，并核对官方提交要求。"
    return result


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


def select_gsfs(page) -> None:
    page.locator("#school-select").select_option("gsfs-complex-2027-a")
    page.locator("#demo-degree-select").select_option("master")
    page.locator("#intake-select").select_option("null:2027:4")
    for selector in ("#college-select", "#department-select", "#route-select"):
        if page.locator(selector).is_visible():
            page.locator(selector).select_option(index=1)


def run_case(browser, phase: str, width: int, height: int, payloads: dict) -> dict:
    before = phase == "before"
    assets = {
        name: static_bytes(name, before)
        for name in ("advanced.html", "app.css", "app.js", "overview.js", "unified-core.mjs")
    }
    page = browser.new_page(viewport={"width": width, "height": height})
    errors: list[str] = []
    calls = {"base": 0, "comparison": 0, "gsfs_evidence": 0, "gsfs_report": 0}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(
        "Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied=text}}});"
    )

    def route_request(route) -> None:
        path = urlparse(route.request.url).path
        if path == "/app":
            route.fulfill(body=assets["advanced.html"], content_type="text/html; charset=utf-8")
        elif path.startswith("/assets/"):
            name = path.rsplit("/", 1)[-1]
            if name not in assets:
                raise AssertionError(f"Unmocked static asset: {name}")
            route.fulfill(
                body=assets[name],
                content_type="text/css" if name.endswith(".css") else "text/javascript",
            )
        elif path == "/v1/reference-targets":
            route.fulfill(json=payloads["catalog"])
        elif path == "/v1/reviewed-documents":
            route.fulfill(json={"items": []})
        elif path == "/v1/generation-status":
            route.fulfill(json={"configured": False, "label": "问答未配置"})
        elif path == "/v1/base-requirements":
            calls["base"] += 1
            route.fulfill(json=payloads["isct_base"])
        elif path == "/v1/applicant-comparison":
            calls["comparison"] += 1
            request = route.request.post_data_json
            assert request["english_preparation"]["toeic_verification_qr_present"] is False
            assert request["applicant"]["english_test_kind"] == "toeic_lr"
            route.fulfill(json=payloads["synthetic_comparison"])
        elif path.endswith("/evidence"):
            calls["gsfs_evidence"] += 1
            route.fulfill(json=payloads["gsfs_evidence"])
        elif path.endswith("/reports"):
            calls["gsfs_report"] += 1
            route.fulfill(json=payloads["gsfs_report"])
        else:
            route.abort()
            raise AssertionError(f"Unmocked request: {path}")

    page.route("**/*", route_request)
    assert page.goto(f"{ORIGIN}/app").status == 200
    page.locator("#school-select option").nth(2).wait_for(state="attached")
    select_isct(page)
    page.locator("#requirements-submit").click()
    page.locator(".materials-section .requirement-card").first.wait_for(state="visible")
    if not before:
        multi_source = None
        for choice in page.locator("#step-2-panel .evidence-choice-list").all():
            if choice.locator("button").count() > 1:
                multi_source = choice
                break
        assert multi_source is not None, "Expected a saved multi-source requirement"
        multi_source.locator("summary").click()
        source_buttons = multi_source.locator("button")
        source_texts = []
        for index in range(source_buttons.count()):
            button = source_buttons.nth(index)
            button.click()
            source_texts.append(page.locator("#drawer-content").inner_text())
            page.locator("#drawer-close").click()
            assert button.evaluate("node => node === document.activeElement")
        assert len(set(source_texts)) == len(source_texts), "Distinct source clauses were merged"
        multi_source.locator("summary").click()
    page.locator(".overview-cta").click()
    english = page.locator('.profile-group[data-profile-group="english"]')
    if not english.evaluate("node => node.open"):
        english.locator("summary").click()
    page.locator("#demo-english-kind").select_option("toeic_lr")
    page.locator("#demo-toeic-qr").select_option("false")
    materials = page.locator('.profile-group[data-profile-group="materials"]')
    if not materials.evaluate("node => node.open"):
        materials.locator("summary").click()
    page.locator('[data-material-code="application_form"]').select_option("not_yet")
    page.locator("#comparison-submit").click()
    page.locator(".english-preparation-group").wait_for(state="visible")
    assert "TOEIC真伪验证二维码" in page.locator("#readiness-panel").inner_text()
    assert "尚未填写准备情况" in page.locator("#readiness-panel").inner_text()
    assert calls["base"] == 1 and calls["comparison"] == 1
    page.locator('input[name="readiness-filter"][value="all"]').check()
    if not before:
        assert page.locator("#step-1-summary").is_visible()
        assert page.locator("#step-2-summary").is_visible()
        assert page.locator("#step-3-summary").is_visible()
        assert page.locator("#priority-actions a").count() <= 3
        qr_row = page.locator(".english-preparation-group .english-check-row").filter(
            has_text="TOEIC真伪验证二维码"
        )
        assert qr_row.is_visible(), "Explicitly missing QR must stay visible"
        reference = page.locator(".english-reference-details")
        assert reference.count() == 1 and not reference.evaluate("node => node.open")
        assert reference.locator(".english-check-row").count() == 4
        reference.locator("summary").first.click()
        assert reference.locator(".english-check-row").first.is_visible()
        reference.locator("summary").first.click()
        material_cards = page.locator('.comparison-card[data-category="materials"]')
        assert material_cards.count() == 5
        assert sum("尚未填写" in text for text in material_cards.all_inner_texts()) >= 1
        guide = material_cards.first.locator(".preparation-guide-details")
        assert guide.count() == 1 and not guide.evaluate("node => node.open")
        guide.locator("summary").click()
        assert guide.locator(".preparation-steps").is_visible()
        guide.locator("summary").click()
        for link in page.locator("#priority-actions a").all():
            target = page.locator(link.get_attribute("href"))
            link.click()
            assert target.is_visible() and target.evaluate(
                "node => node === document.activeElement"
            )
        page.locator('#readiness-filters input[value="all"]').check()
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / f"{phase}-isct-step4-{width}.png"), full_page=True)
    screenshot_size = (OUT / f"{phase}-isct-step4-{width}.png").stat().st_size
    overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
    priority = page.locator("#priority-actions").inner_text()
    readiness = page.locator("#readiness-panel").inner_text()
    if not before:
        page.locator("#readiness-panel .reference-generate").click()
        report = page.locator("#reference-report")
        report.wait_for(state="visible")
        for label in report.locator(".reader-report-options label").all():
            checkbox = label.locator("input")
            if checkbox.is_checked():
                checkbox.uncheck()
        report.get_by_label("考试安排").check()
        page.locator("#reference-copy").click()
        copied = page.evaluate("window.copied")
        assert "考试安排" in copied and "待补材料" not in copied
        assert calls["comparison"] == 1
        page.locator("#reference-close").click()
        question = page.locator("#grounded-question")
        # The saved replay intentionally advertises unconfigured QA. Enable only
        # this local field to exercise its retained input listener; never submit.
        question.evaluate("node => { node.disabled = false; }")
        question.fill("托业是什么")
        assert page.locator("#grounded-question-count").inner_text() == "5 / 1000"
        question.fill("")
        assert page.locator("#grounded-question-count").inner_text() == "0 / 1000"
        page.locator("#edit-applicant").click()
        assert page.locator("#applicant-panel").is_visible()
        page.locator("#demo-credential-basis").select_option("ui_unknown")
        assert page.locator("#readiness-panel").is_hidden()

    page.locator("#edit-target" if not before else "#change-school").click()
    select_gsfs(page)
    page.locator("#requirements-submit").click()
    page.locator(".materials-section .requirement-card").first.wait_for(state="visible")
    source = page.locator(".materials-section .requirement-evidence-actions button").first
    source.click()
    relation = page.locator("#evidence-drawer .relation-node button")
    relation.first.wait_for(state="visible")
    relation.first.click()
    page.locator("#evidence-drawer .relation-back").click()
    page.locator("#drawer-close").click()
    assert source.evaluate("node => document.activeElement === node")
    page.locator(".overview-cta").click()
    page.locator("#comparison-submit").click()
    page.locator("#readiness-panel").wait_for(state="visible")
    assert calls["gsfs_report"] == 1
    assert page.locator("#comparison-output .requirement-card").count() == 3
    page.screenshot(path=str(OUT / f"{phase}-gsfs-step4-{width}.png"), full_page=True)
    gsfs_overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
    assert not errors, errors
    page.close()
    return {
        "viewport": [width, height],
        "screenshot_bytes": screenshot_size,
        "horizontal_overflow": overflow,
        "gsfs_horizontal_overflow": gsfs_overflow,
        "priority_sha256": hashlib.sha256(priority.encode()).hexdigest(),
        "readiness_sha256": hashlib.sha256(readiness.encode()).hexdigest(),
        "calls": calls,
        "relation_window_reopened_original": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("before", "after"))
    args = parser.parse_args()
    payloads = {
        "catalog": read(TREE / "docs/onboarding/prep01-evidence/reference-targets.json"),
        "isct_base": read(TREE / "docs/onboarding/exam01-evidence/cs-april-response.json"),
        "gsfs_evidence": read(SAVED_GSFS / "gsfs-evidence.json"),
        "gsfs_report": read(SAVED_GSFS / "gsfs-unknown-unknown.json"),
    }
    saved_comparison = read(TREE / "docs/onboarding/prep01-evidence/isct-comparison.json")
    payloads["synthetic_comparison"] = synthetic_qr_absent(saved_comparison)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        try:
            results = [
                run_case(browser, args.phase, width, height, payloads)
                for width, height in ((1440, 900), (390, 844))
            ]
        finally:
            browser.close()
    assert results[0]["readiness_sha256"] == results[1]["readiness_sha256"]
    journal = {
        "phase": args.phase,
        "baseline": BASELINE,
        "source_data": [
            "docs/onboarding/exam01-evidence/cs-april-response.json",
            "docs/onboarding/prep01-evidence/isct-comparison.json",
            "docs/onboarding/prep01-evidence/reference-targets.json",
            "outputs/ui02-real/final-head-cd09bd4/gsfs-evidence.json",
        ],
        "synthetic_variant": "Saved PREP-01 comparison; QR check alone set to action_needed for an explicit user 'no'.",
        "product_service_starts": 0,
        "product_posts": 0,
        "paid_calls": 0,
        "results": results,
    }
    (OUT / f"{args.phase}-journal.json").write_text(
        json.dumps(journal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(journal, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
