"""Review R1 in the four-step page with three existing-rule results, no product service."""

# ruff: noqa: E402 -- use this checkout's source instead of another editable worktree.

from __future__ import annotations

import hashlib
import json
import os
import runpy
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright

TREE = Path(__file__).resolve().parents[2]
PROJECT = TREE.parents[1]
sys.path.insert(0, str(TREE / "src"))

from jgrad_admission_rag.corpus_selection import select_corpus_documents
from jgrad_admission_rag.reasoning.reviewed_report_evidence import prepare_reviewed_report_evidence
from jgrad_admission_rag.reasoning.reviewed_report_plan import load_reviewed_report_plan
from jgrad_admission_rag.schemas.corpus_manifest import load_corpus_manifest
from jgrad_admission_rag.schemas.corpus_version import (
    CorpusSelectionRequest,
    load_corpus_version_policy,
)
from jgrad_admission_rag.schemas.page_scope_manifest import load_page_scope_manifest
from jgrad_admission_rag.service.demo_requirements import (
    DemoApplicantComparisonRequest,
    DemoTargetRequest,
    build_demo_applicant_comparison,
    build_demo_base_requirements,
)

OUT = TREE / "docs/onboarding/prep01-evidence"
ASSET = Path(
    os.environ.get(
        "PREP01_REVIEWED_ASSET_ROOT",
        str(TREE.parent / "m10-09-deepseek-live/runtime-v1"),
    )
)
TARGET = {
    "school_id": "isct",
    "document_id": "isct_2027_4_2026_9_master",
    "degree_id": "master",
    "intake": {"year": 2027, "month": 4},
    "college_id": "情報理工学院",
    "department_id": "情報工学系",
    "application_route": "b_schedule",
}


def reviewed_context():
    if not (ASSET / "corpus.json").is_file():
        raise RuntimeError(f"Reviewed 391 asset unavailable: {ASSET}")
    manifest = load_corpus_manifest(ASSET / "corpus.json")
    policy = load_corpus_version_policy(ASSET / "policy.json")
    plan = load_reviewed_report_plan(ASSET / "config/reviewed_report_plan.json")
    selection = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(document_ids=(TARGET["document_id"],)),
    )
    page_scope = load_page_scope_manifest(
        ASSET / "config/page_scope_manifest.json", expected_page_count=85
    )
    evidence = prepare_reviewed_report_evidence(
        ASSET, manifest, policy, selection, (plan,), page_scope
    )
    return plan, evidence


def prepared_cases(plan, evidence):
    math = {
        **TARGET,
        "college_id": "理学院",
        "department_id": "数学系",
        "application_route": None,
    }
    specs = {
        "math": (math, {}, {}),
        "qr_missing": (
            TARGET,
            {"english_test_kind": "toeic_lr"},
            {"toeic_verification_qr_present": False},
        ),
        "kind_unknown": (TARGET, {}, {}),
    }
    cases = {}
    for name, (target, applicant, proof) in specs.items():
        request = DemoApplicantComparisonRequest.model_validate(
            {"target": target, "applicant": applicant, "english_preparation": proof}
        )
        base = build_demo_base_requirements(
            DemoTargetRequest.model_validate(target), plan, evidence
        )
        comparison = build_demo_applicant_comparison(request, plan, evidence)
        cases[name] = (target, base.model_dump(mode="json"), comparison.model_dump(mode="json"))
    return cases


def browser_case(browser, url, name, target, base, comparison):
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    posts = []

    def fulfill(route):
        kind = route.request.url.rsplit("/", 1)[-1]
        posts.append((kind, route.request.post_data_json))
        route.fulfill(json=base if kind == "base-requirements" else comparison)

    page.route("**/v1/base-requirements", fulfill)
    page.route("**/v1/applicant-comparison", fulfill)
    assert page.goto(f"{url}/app").status == 200
    for selector, value in (
        ("school-select", "isct"),
        ("demo-degree-select", "master"),
        ("intake-select", "isct_2027_4_2026_9_master:2027:4"),
        ("college-select", target["college_id"]),
        ("department-select", target["department_id"]),
    ):
        page.locator(f"#{selector}").select_option(value)
    if target["application_route"]:
        page.locator("#route-select").select_option(target["application_route"])
    page.locator("#requirements-submit").click()
    page.locator(".overview-cta").click()
    if name == "qr_missing":
        group = page.locator('.profile-group[data-profile-group="english"]')
        if not group.evaluate("element => element.open"):
            group.locator("summary").click()
        page.locator("#demo-english-kind").select_option("toeic_lr")
        page.locator("#demo-toeic-qr").select_option("false")
    page.locator("#comparison-submit").click()
    page.locator(".english-preparation-group").wait_for(state="visible")

    actual = posts[-1][1]
    assert [kind for kind, _ in posts] == ["base-requirements", "applicant-comparison"]
    assert all(actual["target"][field] == value for field, value in target.items())
    assert actual["applicant"]["english_test_kind"] == (
        "toeic_lr" if name == "qr_missing" else None
    )
    assert actual["english_preparation"]["toeic_verification_qr_present"] == (
        False if name == "qr_missing" else None
    )
    checks = comparison["english_preparation_result"]["checks"]
    assert page.locator(".english-preparation-group .comparison-card").count() == len(checks)
    assert page.locator("#comparison-output .comparison-card").count() == int(
        page.locator("#count-total").inner_text()
    )
    assert page.locator(".comparison-group .comparison-card[data-category='english']").count() == 0
    material_cards = page.locator(".comparison-card[data-category='materials']").count()
    assert material_cards == sum(item["category"] == "materials" for item in comparison["items"])
    displayed_counts = {
        "total": int(page.locator("#count-total").inner_text()),
        "recorded": int(page.locator("#count-recorded").inner_text()),
        "action_required": int(page.locator("#count-action").inner_text()),
        "review_required": int(page.locator("#count-review").inner_text()),
    }
    assert displayed_counts["total"] == sum(
        displayed_counts[key] for key in ("recorded", "action_required", "review_required")
    )

    priority = page.locator("#priority-actions").inner_text()
    links = page.locator("#priority-actions a")
    link_targets = []
    for index in range(links.count()):
        link = links.nth(index)
        fragment = link.get_attribute("href")
        target_card = page.locator(fragment)
        assert target_card.count() == 1
        link.click()
        assert target_card.is_visible()
        assert target_card.evaluate("element => document.activeElement === element")
        link_targets.append(fragment)

    visible_by_filter = {}
    for group in ("all", "action_required", "review_required", "recorded"):
        page.locator(f'input[name="readiness-filter"][value="{group}"]').check()
        visible_by_filter[group] = [
            card.get_attribute("id")
            for card in page.locator(".english-preparation-group .comparison-card:visible").all()
        ]
    if name == "math":
        assert [item["check_id"] for item in checks] == ["english:math"]
        assert checks[0]["status"] == "not_applicable"
        assert "英语考试与官方成绩单" not in priority
        assert "英语" not in priority
        assert not visible_by_filter["action_required"]
        assert not visible_by_filter["review_required"]
        assert len(visible_by_filter["recorded"]) == 1
    elif name == "qr_missing":
        missing = next(
            item for item in checks if item["check_id"] == "english:toeic_verification_qr_present"
        )
        assert missing["status"] == "action_needed"
        assert "TOEIC真伪验证二维码" in priority
        assert len(visible_by_filter["action_required"]) == 1
        assert len(visible_by_filter["review_required"]) >= 1
    else:
        assert [item["check_id"] for item in checks] == ["english:kind"]
        assert checks[0]["status"] == "needs_information"
        assert "英语 · 考试类型" in priority
        assert not visible_by_filter["action_required"]
        assert len(visible_by_filter["review_required"]) == 1

    screenshot_filter = (
        "action_required"
        if name == "qr_missing"
        else "review_required"
        if name == "kind_unknown"
        else "all"
    )
    page.locator(f'input[name="readiness-filter"][value="{screenshot_filter}"]').check()
    page.evaluate(
        "window.scrollTo(0, document.querySelector('#priority-actions').getBoundingClientRect().top + window.scrollY - 112)"
    )
    page.screenshot(path=str(OUT / f"r1-{name}.png"))
    page.locator('#readiness-filters input[value="all"]').check()
    page.locator("#readiness-panel .reference-generate").click()
    page.locator("#reference-report[open]").wait_for(state="visible")
    report = page.locator("#reference-report-body").inner_text()
    if name == "math":
        assert "请补充英语考试类型" not in report
        assert "需要补充英语考试与官方成绩单" not in report
    assert not errors, errors
    page.close()
    return {
        "checks": [{"id": check["check_id"], "status": check["status"]} for check in checks],
        "priority": priority,
        "priority_links": link_targets,
        "api_counts_unchanged": comparison["counts"],
        "visible_counts": displayed_counts,
        "material_cards": material_cards,
        "english_cards_by_filter": visible_by_filter,
        "product_service_starts": 0,
        "product_api_posts": 0,
    }


def main():
    journal = json.loads((OUT / "journal.json").read_text(encoding="utf-8"))
    assert journal["service_startups"] == 1 and journal["base_comparison_posts"] == 2
    protected = journal["asset_hashes_after"]
    assert all(
        hashlib.sha256((PROJECT / path).read_bytes()).hexdigest() == expected
        for path, expected in protected.items()
    )
    plan, evidence = reviewed_context()
    cases = prepared_cases(plan, evidence)
    replay = runpy.run_path(str(TREE / "docs/onboarding/prep01-replay-browser.py"))
    handler = replay["ReplayHandler"]
    handler.posts = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(replay["EDGE"]))
            results = {
                name: browser_case(browser, f"http://127.0.0.1:{server.server_port}", name, *values)
                for name, values in cases.items()
            }
            browser.close()
        assert handler.posts == 0
    finally:
        server.shutdown()
        worker.join(timeout=5)
    assert all(
        hashlib.sha256((PROJECT / path).read_bytes()).hexdigest() == expected
        for path, expected in protected.items()
    )
    results["resource_audit"] = {
        "protected_asset_hashes_unchanged": True,
        "protected_asset_count": len(protected),
        "additional_product_service_starts": 0,
        "additional_product_api_posts": 0,
        "additional_paid_calls": 0,
    }
    (OUT / "r1-browser.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
