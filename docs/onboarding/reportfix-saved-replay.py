"""REPORT-FIX #272: intercepted browser replay; never starts a product service.

The saved comparison is for ISCT Computer Science B, April 2027. For the
three supplied Japanese values, only its Japanese self-report item and counts
are changed in memory to the backend's existing `recorded` response shape.
This is a synthetic variant, not a real HTTP response for the user's target.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
EVIDENCE = ROOT / "docs/onboarding/reportfix-evidence"
SAVED = ROOT / "docs/onboarding/prep01-evidence"
EXAM = ROOT / "docs/onboarding/exam01-evidence"
BASELINE = "c53b7f7efe31fdcd176af2cfc62a908fde1c53f4"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
ORIGIN = "http://reportfix-replay.test"
VALUES = {
    "unfilled": "",
    "studied": "studied",
    "certificate": "certificate_available",
    "not_studied": "not_studied",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def static_bytes(name: str, phase: str) -> bytes:
    if phase == "after":
        return (STATIC / name).read_bytes()
    result = subprocess.run(
        ["git", "show", f"{BASELINE}:src/jgrad_admission_rag/service/static/{name}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout


def comparison_variant(saved: dict, value: str) -> dict:
    response = copy.deepcopy(saved)
    if not value:
        return response
    japanese = next(item for item in response["items"] if item["item_id"] == "japanese:background")
    assert japanese["comparison_status"] == "needs_information"
    assert japanese["evidence"] == []
    japanese.update(
        comparison_status="recorded",
        description="日语情况已记录；当前审核证据不足以判断是否满足任何项目要求。",
        action_group="recorded",
        next_action="保留当前记录；如项目另有要求，请以官方原文或学校答复为准。",
    )
    response["counts"]["recorded"] += 1
    response["counts"]["action_required"] -= 1
    assert response["counts"]["total"] == len(response["items"])
    return response


def run_case(
    browser, phase: str, label: str, width: int, height: int, japanese_name: str, payloads: dict
) -> dict:
    japanese_value = VALUES[japanese_name]
    response = comparison_variant(payloads["comparison"], japanese_value)
    assets = {
        name: static_bytes(name, phase)
        for name in ("advanced.html", "app.css", "app.js", "overview.js", "unified-core.mjs")
    }
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    errors: list[str] = []
    calls = {"base": 0, "comparison": 0, "other_product": 0}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(
        "Object.defineProperty(navigator,'clipboard',{value:{"
        "writeText:async text=>{window.copied=text}}});"
    )

    def route_request(route) -> None:
        path = urlparse(route.request.url).path
        if path == "/app":
            route.fulfill(body=assets["advanced.html"], content_type="text/html; charset=utf-8")
        elif path.startswith("/assets/"):
            name = path.rsplit("/", 1)[-1]
            assert name in assets, f"Unexpected static resource: {name}"
            route.fulfill(
                body=assets[name],
                content_type="text/css" if name.endswith(".css") else "text/javascript",
            )
        elif path == "/v1/reference-targets":
            route.fulfill(json=payloads["catalog"])
        elif path == "/v1/reviewed-documents":
            route.fulfill(json={"items": []})
        elif path == "/v1/generation-status":
            route.fulfill(json={"schema_version": "1.0", "status": "offline"})
        elif path == "/v1/base-requirements":
            calls["base"] += 1
            route.fulfill(json=payloads["base"])
        elif path == "/v1/applicant-comparison":
            calls["comparison"] += 1
            request = route.request.post_data_json
            assert request["applicant"]["japanese_background"] == (japanese_value or None)
            assert request["target"]["school_id"] == "isct"
            assert request["target"]["department_id"] == "情報工学系"
            route.fulfill(json=response)
        else:
            calls["other_product"] += 1
            route.abort()
            raise AssertionError(f"Unexpected product request: {path}")

    page.route("**/*", route_request)
    assert page.goto(f"{ORIGIN}/app").status == 200
    page.locator("#school-select option").nth(2).wait_for(state="attached")
    for selector, value in (
        ("school-select", "isct"),
        ("demo-degree-select", "master"),
        ("intake-select", "isct_2027_4_2026_9_master:2027:4"),
        ("college-select", "情報理工学院"),
        ("department-select", "情報工学系"),
        ("route-select", "b_schedule"),
    ):
        page.locator(f"#{selector}").select_option(value)
    page.locator("#requirements-submit").click()
    page.locator(".exam-arrangement").wait_for(state="visible")
    page.locator("#requirements-continue").click()
    japanese = page.locator('.profile-group[data-profile-group="japanese"]')
    if not japanese.evaluate("node => node.open"):
        japanese.locator("summary").click()
    page.locator("#demo-japanese-background").select_option(japanese_value)
    page.locator("#comparison-submit").click()
    page.locator("#readiness-panel").wait_for(state="visible")
    japanese_card = page.locator('.comparison-card[data-category="japanese"]')
    japanese_card.wait_for(state="attached")
    japanese_text = japanese_card.inner_text()
    if japanese_value:
        assert "日语情况已记录" in japanese_text
        assert "已满足日语要求" not in japanese_text
    else:
        assert "尚未提供日语情况" in japanese_text
    assert calls == {"base": 1, "comparison": 1, "other_product": 0}
    page.locator("#readiness-panel .reference-generate").click()
    dialog = page.locator("#reference-report")

    if phase == "before" and japanese_value:
        assert not dialog.is_visible(), "Baseline unexpectedly accepted evidence-free self-report"
        assert "报告生成失败或依据不完整" in page.locator("#reference-step4-status").inner_text()
        result = {
            "phase": phase,
            "viewport": label,
            "japanese": japanese_name,
            "comparison_posts": calls["comparison"],
            "report_open": False,
            "baseline_error": "报告生成失败或依据不完整",
            "page_errors": errors,
        }
    else:
        dialog.wait_for(state="visible")
        assert page.locator("#reference-copy").is_enabled()
        assert "关键时间" in dialog.inner_text()
        assert "材料准备清单" in dialog.inner_text()
        assert "已满足日语要求" not in dialog.inner_text()
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        if phase == "after" and japanese_name == "certificate":
            page.screenshot(path=str(EVIDENCE / f"after-certificate-default-{label}.png"))
        page.locator("#reference-copy").click()
        page.wait_for_function(
            "() => typeof window.copied === 'string' && window.copied.length > 0"
        )
        default_copy = page.evaluate("window.copied")
        assert "关键时间" in default_copy and "材料准备清单" in default_copy
        assert "已满足日语要求" not in default_copy
        for option in dialog.locator(".reader-report-options input[type=checkbox]").all():
            if option.is_checked():
                option.uncheck()
        dialog.get_by_label("考试安排").check()
        assert page.locator("#reference-copy").is_enabled()
        page.locator("#reference-copy").click()
        page.wait_for_function(
            "() => window.copied.includes('考试安排') && !window.copied.includes('材料准备清单')"
        )
        exam_copy = page.evaluate("window.copied")
        assert "考试安排" in exam_copy and "材料准备清单" not in exam_copy
        assert "已满足日语要求" not in exam_copy
        assert calls["comparison"] == 1, "Exam-only selection caused another comparison request"
        if phase == "after" and japanese_name == "certificate":
            page.screenshot(path=str(EVIDENCE / f"after-certificate-exam-{label}.png"))
            (EVIDENCE / f"after-certificate-default-{label}.txt").write_text(
                default_copy + "\n", encoding="utf-8"
            )
            (EVIDENCE / f"after-certificate-exam-{label}.txt").write_text(
                exam_copy + "\n", encoding="utf-8"
            )
        result = {
            "phase": phase,
            "viewport": label,
            "japanese": japanese_name,
            "comparison_posts": calls["comparison"],
            "report_open": True,
            "default_copy_chars": len(default_copy),
            "exam_copy_chars": len(exam_copy),
            "page_errors": errors,
            "horizontal_overflow": page.evaluate(
                "document.documentElement.scrollWidth > innerWidth"
            ),
        }
    assert not errors, errors
    assert calls["other_product"] == 0
    context.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("before", "after"))
    args = parser.parse_args()
    payloads = {
        "catalog": read_json(SAVED / "reference-targets.json"),
        "base": read_json(EXAM / "cs-april-response.json"),
        "comparison": read_json(SAVED / "isct-comparison.json"),
    }
    values = ("certificate",) if args.phase == "before" else tuple(VALUES)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        results = [
            run_case(browser, args.phase, label, width, height, value, payloads)
            for label, width, height in (("desktop", 1440, 900), ("mobile", 390, 844))
            for value in values
        ]
        browser.close()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"{args.phase}-journal.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
