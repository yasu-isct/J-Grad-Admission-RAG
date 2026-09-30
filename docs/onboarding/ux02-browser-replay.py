"""Compare UX-02 baseline/current UI with saved real responses; no service or model."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

TREE = Path(__file__).resolve().parents[2]
ROOT = Path(r"D:\J-Grad-Admission-RAG")
STATIC = TREE / "src/jgrad_admission_rag/service/static"
SAVED = ROOT / "outputs/ui02-real/final-head-cd09bd4"
OUT = TREE / "docs/onboarding/ux02-evidence"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
BASELINE = "b0943cc651f5d0b92bfa0226f7583b810e90a29a"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def helper():
    path = TREE / "docs/onboarding/ux01-browser-replay.py"
    spec = importlib.util.spec_from_file_location("ux01_replay_helper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def static_bytes(name, before):
    if not before:
        return (STATIC / name).read_bytes()
    path = f"src/jgrad_admission_rag/service/static/{name}"
    return subprocess.run(
        ["git", "show", f"{BASELINE}:{path}"], cwd=TREE, check=True, capture_output=True
    ).stdout


def capture(page, version, step, selector):
    target = page.locator(selector)
    target.wait_for(state="visible")
    for width, height in ((1440, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        target.screenshot(path=str(OUT / f"{version}-{step}-{width}.png"))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
            version,
            step,
            width,
        )
    page.set_viewport_size({"width": 1440, "height": 900})


def capture_report_materials(page, version, step):
    for width, height in ((1440, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        page.locator(".reader-report-section").filter(
            has_text="材料准备清单"
        ).scroll_into_view_if_needed()
        page.locator("#reference-report").screenshot(
            path=str(OUT / f"{version}-{step}-{width}.png")
        )
    page.set_viewport_size({"width": 1440, "height": 900})


def run(browser, before, catalog, saved, answer):
    version = "before" if before else "after"
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    calls = {"base": 0, "comparison": 0, "evidence": 0, "report": 0, "answer": 0}
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(
        "Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied=text}}});"
    )
    assets = {
        name: static_bytes(name, before)
        for name in ("advanced.html", "app.css", "app.js", "overview.js", "unified-core.mjs")
    }

    def route_request(route):
        path = urlparse(route.request.url).path
        if path == "/app":
            route.fulfill(body=assets["advanced.html"], content_type="text/html")
        elif path.startswith("/assets/"):
            name = path.rsplit("/", 1)[-1]
            route.fulfill(
                body=assets[name],
                content_type="text/css" if name.endswith(".css") else "text/javascript",
            )
        elif path == "/v1/reference-targets":
            route.fulfill(json=catalog)
        elif path == "/v1/reviewed-documents":
            route.fulfill(json={"items": []})
        elif path == "/v1/generation-status":
            route.fulfill(json=read(TREE / "docs/evaluation/qa01-online20/generation-status.json"))
        elif path == "/v1/base-requirements":
            calls["base"] += 1
            route.fulfill(json=saved["isct-base-2027.json"])
        elif path == "/v1/applicant-comparison":
            calls["comparison"] += 1
            route.fulfill(json=saved["isct-comparison.json"])
        elif path.endswith("/evidence"):
            calls["evidence"] += 1
            route.fulfill(json=saved["gsfs-evidence"])
        elif path.endswith("/reports"):
            calls["report"] += 1
            route.fulfill(json=saved["gsfs-unknown-unknown.json"])
        elif path == "/v1/natural-language-answers":
            calls["answer"] += 1
            route.fulfill(json=answer)
        else:
            route.abort()

    page.route("**/*", route_request)
    page.goto("http://ux02-replay.test/app")
    page.locator("#school-select option").nth(2).wait_for(state="attached")
    choose = helper().choose
    legacy = next(item for item in catalog["items"] if item["kind"] == "legacy_applicant")
    gsfs = next(item for item in catalog["items"] if item["kind"] == "reviewed_material_slice")
    capture(page, version, "step1", "#step-1-panel")
    choose(page, legacy)
    page.locator("#requirements-submit").click()
    page.locator(".materials-section .requirement-card").first.wait_for(state="visible")
    capture(page, version, "step2", "#step-2-panel")
    if not before:
        cards = page.locator(".materials-section .requirement-card")
        assert cards.count() == 5
        assert "邮寄地址标签" in cards.first.inner_text()
        assert "宛名ラベル" in cards.first.inner_text()
    page.locator(".overview-cta").click()
    page.locator("#demo-credential-basis").select_option("ui_unknown")
    page.locator('[data-material-code="address_label"]').select_option("available")
    page.locator('[data-material-code="application_form"]').select_option("not_yet")
    capture(page, version, "step3", "#applicant-panel")
    page.locator("#comparison-submit").click()
    page.locator("#readiness-panel").wait_for(state="visible")
    capture(page, version, "step4", "#readiness-panel")
    if not before:
        cards = page.locator('#comparison-output .comparison-card[data-category="materials"]')
        text = cards.all_inner_texts()
        assert any("已准备（自报）" in value for value in text)
        assert any("待准备" in value for value in text)
        assert any("尚未填写准备情况" in value for value in text)
        assert "低保证" not in page.locator("#readiness-panel").inner_text()
    page.locator("#readiness-panel .reference-generate").click()
    page.locator("#reference-report").wait_for(state="visible")
    capture(page, version, "report", "#reference-report")
    capture_report_materials(page, version, "report-materials")
    report_preview = page.locator("#reference-report-body").inner_text()
    page.locator("#reference-copy").click()
    copied = page.evaluate("window.copied")
    assert "材料准备清单" in report_preview and "材料准备清单" in copied
    (OUT / f"{version}-report-copy.txt").write_text(copied + "\n", encoding="utf-8")
    if not before:
        for name in (
            "邮寄地址标签",
            "入学申请表",
            "志愿理由书",
            "学士课程成绩证明",
            "毕业或预计毕业证明",
        ):
            assert name in report_preview and name in copied
        assert "邮寄地址标签" in copied and "宛名ラベル" in copied
        assert "待准备" in copied and "尚未填写准备情况" in copied
    page.locator("#reference-close").click()
    page.locator("#grounded-question").fill("日语能力考试与JLPT N1、N2是什么？")
    page.locator("#grounded-answer-submit").click()
    page.get_by_text(answer["result"]["answer"]["answer"][:40], exact=False).wait_for()
    capture(page, version, "answer", "#grounded-answer-panel")
    if not before:
        assert page.locator("#generation-mode-label").inner_text() == "在线问答可用"
        assert "deepseek-flash" not in page.locator("#grounded-answer-panel").inner_text()
        assert "低保证" not in page.locator("#grounded-answer-panel").inner_text()
        assert page.locator("#grounded-answer-output .grounded-citations").count() == 0
    page.locator("#change-school").click()
    choose(page, gsfs)
    assert page.locator("#grounded-answer-output").is_hidden()
    page.locator("#requirements-submit").click()
    page.locator(".materials-section .requirement-card").first.wait_for(state="visible")
    assert page.locator(".materials-section .requirement-card").count() == 3
    capture(page, version, "gsfs-step2", "#step-2-panel")
    assert "当前资料尚未覆盖日期" in page.locator(".key-dates-section").inner_text()
    if not before:
        gsfs_text = page.locator(".materials-section").inner_text()
        for value in (
            "英语成绩单",
            "英語のスコアシート",
            "提交材料检查表",
            "提出書類等チェックシート",
            "学业与职务兼顾计划书",
            "学業・職務両立計画書",
        ):
            assert value in gsfs_text
    page.locator(".materials-section .requirement-evidence-actions button").first.click()
    page.locator("#evidence-drawer .relation-node button").first.click()
    page.locator("#evidence-drawer .relation-back").click()
    page.locator("#drawer-close").click()
    page.locator("#step-2-panel .reference-generate").click()
    page.locator("#reference-report").wait_for(state="visible")
    capture(page, version, "gsfs-report", "#reference-report")
    capture_report_materials(page, version, "gsfs-report-materials")
    gsfs_preview = page.locator("#reference-report-body").inner_text()
    page.locator("#reference-copy").click()
    gsfs_copy = page.evaluate("window.copied")
    (OUT / f"{version}-gsfs-report-copy.txt").write_text(gsfs_copy + "\n", encoding="utf-8")
    if not before:
        assert "学业与职务兼顾计划书" in gsfs_copy
        assert "待确认适用" in gsfs_copy
        assert "关键时间" not in gsfs_copy
        for name in ("英语成绩单", "提交材料检查表", "学业与职务兼顾计划书"):
            assert name in gsfs_preview and name in gsfs_copy
    page.locator("#reference-close").click()
    assert not errors, errors
    page.close()
    return calls


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    saved = {
        name: read(SAVED / name)
        for name in (
            "isct-base-2027.json",
            "isct-comparison.json",
            "gsfs-unknown-unknown.json",
        )
    }
    saved["gsfs-evidence"] = read(
        TREE / "docs/onboarding/evidui01-evidence/gsfs-evidence-real.json"
    )
    prior = helper()
    catalog = prior.catalog_from_saved(saved["isct-base-2027.json"], saved["gsfs-evidence"])
    responses = read(TREE / "docs/evaluation/qa01-online20/responses.json")
    answer = next(row["body"] for row in responses if row["case"] == "03" and row["turn"] == 1)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        before = run(browser, True, catalog, saved, answer)
        after = run(browser, False, catalog, saved, answer)
        browser.close()
    (OUT / "journal.json").write_text(
        json.dumps(
            {
                "baseline": BASELINE,
                "response_sources": [
                    str(SAVED),
                    "docs/onboarding/evidui01-evidence/gsfs-evidence-real.json",
                ],
                "answer_source": "docs/evaluation/qa01-online20/responses.json case 03 turn 1",
                "response_sha256": {
                    key: hashlib.sha256(
                        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
                    ).hexdigest()
                    for key, value in saved.items()
                },
                "before_replayed": before,
                "after_replayed": after,
                "service_starts": 0,
                "real_posts": 0,
                "paid_calls": 0,
                "same_saved_responses": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
