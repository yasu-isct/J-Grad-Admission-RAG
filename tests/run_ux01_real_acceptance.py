from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jgrad_admission_rag.demo import load_demo_config  # noqa: E402

OUTPUT_ROOT = ROOT / "outputs" / "ux01" / "acceptance"
BASELINE = ROOT / "tests" / "fixtures" / "ux01_before_measurements_v1.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run UX-01 browser acceptance against the formal jgrad-demo service."
    )
    parser.add_argument("--pdf", required=True, help="Absolute fixed official PDF path.")
    parser.add_argument(
        "--workspace",
        default=str((ROOT / "outputs" / "ux01" / "workspace").resolve()),
    )
    parser.add_argument("--browser-executable")
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_json(url: str, process: subprocess.Popen[str]) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(f"formal service exited early\nstdout={stdout}\nstderr={stderr}")
        try:
            with urlopen(url, timeout=1) as response:  # noqa: S310 - fixed loopback URL
                return json.loads(response.read())
        except (OSError, URLError):
            time.sleep(0.2)
    raise RuntimeError("formal service did not become ready")


def _entry_point() -> str:
    executable = shutil.which("jgrad-demo")
    if executable is None:
        script_name = "jgrad-demo.exe" if os.name == "nt" else "jgrad-demo"
        sibling = Path(sys.executable).with_name(script_name)
        executable = str(sibling) if sibling.is_file() else None
    if executable is None:
        raise RuntimeError(
            "installed jgrad-demo entry point is unavailable; install .[service] first"
        )
    return executable


def _browser_options(explicit: str | None) -> dict[str, str | bool]:
    if explicit:
        return {"headless": True, "executable_path": explicit}
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if chrome.is_file():
        return {"headless": True, "executable_path": str(chrome)}
    return {"headless": True}


def _capture(page, viewport: str, state: str) -> dict:
    path = OUTPUT_ROOT / f"ux01-{viewport}-{state}.png"
    height = int(page.evaluate("document.documentElement.scrollHeight"))
    page.screenshot(path=path, full_page=True)
    return {
        "state": state,
        "height": height,
        "screenshot": path.relative_to(ROOT).as_posix(),
    }


def _active_is(page, selector: str) -> bool:
    return bool(page.locator(selector).evaluate("element => document.activeElement === element"))


def _assert_visible_focus(page, selector: str) -> None:
    locator = page.locator(selector)
    locator.focus()
    style = locator.evaluate(
        "element => { const value = getComputedStyle(element); "
        "return {style: value.outlineStyle, width: value.outlineWidth}; }"
    )
    assert style["style"] != "none"
    assert float(style["width"].replace("px", "")) >= 3


def _complete_target(page) -> None:
    page.locator("#intake-select").select_option("isct_2027_4_2026_9_master:2027:4")
    page.locator("#college-select").select_option("工学院")
    page.locator("#department-select").select_option("システム制御系")
    expect(page.locator("#requirements-submit")).to_be_enabled()
    assert "可以查看" in page.locator("#target-completion-hint").inner_text()


def _load_requirements_with_keyboard(page) -> None:
    submit = page.locator("#requirements-submit")
    submit.focus()
    page.keyboard.press("Enter")
    page.locator(".requirement-card").first.wait_for()
    expect(page.locator("#step-1-summary")).to_be_visible()
    expect(page.locator("#step-2-content")).to_be_visible()
    expect(page.locator("#applicant-panel")).to_be_hidden()
    assert _active_is(page, "#requirements-heading")


def _open_and_close_evidence(page, selector: str) -> None:
    trigger = page.locator(selector).first
    trigger.focus()
    page.keyboard.press("Enter")
    page.locator("#evidence-drawer[open]").wait_for()
    assert "官方页码" in page.locator("#drawer-content").inner_text()
    assert page.locator("#drawer-content .evidence-text").inner_text().strip()
    page.keyboard.press("Escape")
    assert trigger.evaluate("element => document.activeElement === element")


def _fill_applicant(page, score: str = "800") -> None:
    page.locator("#demo-credential-basis").select_option("university_graduation")
    page.locator("#demo-completion-state").select_option("expected")
    page.locator("#demo-english-kind").select_option("toeic_lr")
    page.locator("#demo-english-score").fill(score)
    page.locator("#demo-japanese-background").select_option("studied")
    page.locator('[data-material-code="address_label"]').select_option("available")


def _submit_comparison_with_keyboard(page) -> None:
    submit = page.locator("#comparison-submit")
    expect(submit).to_be_enabled()
    submit.focus()
    page.keyboard.press("Enter")
    page.locator(".comparison-card").first.wait_for()
    expect(page.locator("#readiness-panel")).to_be_visible()
    assert _active_is(page, "#readiness-heading")


def _exercise_filters(page) -> None:
    all_filter = page.locator('input[name="readiness-filter"][value="all"]')
    recorded = page.locator('input[name="readiness-filter"][value="recorded"]')
    all_filter.focus()
    page.keyboard.press("ArrowRight")
    assert page.locator('input[name="readiness-filter"][value="action_required"]').is_checked()
    page.keyboard.press("ArrowRight")
    assert recorded.is_checked()
    assert _active_is(page, 'input[name="readiness-filter"][value="recorded"]')
    assert page.locator(".comparison-card:visible").count() == int(
        page.locator("#count-recorded").inner_text()
    )
    all_filter.focus()
    page.keyboard.press("Space")
    assert all_filter.is_checked()


def _exercise_return_and_stale_flow(page) -> None:
    edit_applicant = page.locator("#edit-applicant")
    edit_applicant.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#step-3-content")).to_be_visible()
    expect(page.locator("#readiness-panel")).to_be_hidden()
    expect(page.locator("#applicant-heading")).to_be_focused()
    page.locator("#demo-english-score").fill("810")
    assert page.locator(".comparison-card").count() == 0
    assert page.locator("#step-nav-4 small").inner_text() == "需要重新确认"
    _submit_comparison_with_keyboard(page)

    edit_target = page.locator("#edit-target")
    edit_target.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#demo-heading")).to_be_focused()
    page.locator("#college-select").select_option("理学院")
    assert page.locator(".requirement-card").count() == 0
    expect(page.locator("#step-2-panel")).to_be_hidden()
    assert page.locator("#step-nav-2 small").inner_text() == "需要重新确认"
    page.locator("#college-select").select_option("工学院")
    page.locator("#department-select").select_option("システム制御系")
    _load_requirements_with_keyboard(page)
    page.locator("#requirements-continue").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#applicant-heading")).to_be_focused()
    _submit_comparison_with_keyboard(page)


def _exercise_advanced_tools(page, run_requests: bool) -> dict:
    summary = page.locator("#advanced-tools > summary")
    summary.focus()
    page.keyboard.press("Enter")
    assert page.locator("#advanced-tools").get_attribute("open") is not None
    expect(page.locator("#document-select")).to_be_enabled()
    evidence_tab = page.locator("#evidence-tab")
    evidence_tab.focus()
    page.keyboard.press("ArrowRight")
    assert page.locator("#report-tab").get_attribute("aria-selected") == "true"
    page.keyboard.press("ArrowLeft")
    assert evidence_tab.get_attribute("aria-selected") == "true"
    if run_requests:
        page.locator("#query-input").fill("出願資格")
        page.locator("#submit-button").focus()
        page.keyboard.press("Enter")
        page.locator(".evidence-item").first.wait_for()
        page.locator("#report-tab").click()
        page.locator("#report-query").fill("情報理工学院の出願資格")
        page.locator("#report-submit").focus()
        page.keyboard.press("Enter")
        page.locator(".report-section").first.wait_for(timeout=20_000)
    return {"expanded": True, "tabs_keyboard_operable": True, "requests_exercised": run_requests}


def _run_viewport(browser, base_url: str, viewport: str, width: int) -> dict:
    context = browser.new_context(
        viewport={"width": width, "height": 1000},
        reduced_motion="reduce",
    )
    page = context.new_page()
    requests: list[str] = []
    page.on("request", lambda request: requests.append(request.url))
    try:
        page.goto(f"{base_url}/app")
        expect(page.locator("#school-select")).to_be_enabled(timeout=10_000)
        assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
        expect(page.locator("#step-1-content")).to_be_visible()
        expect(page.locator("#step-2-panel")).to_be_hidden()
        expect(page.locator("#applicant-panel")).to_be_hidden()
        expect(page.locator("#readiness-panel")).to_be_hidden()
        assert page.locator("#advanced-tools").get_attribute("open") is None
        _assert_visible_focus(page, "#school-select")
        screenshots = [_capture(page, viewport, "initial")]

        _complete_target(page)
        _load_requirements_with_keyboard(page)
        assert page.locator(".requirement-group h3").all_text_contents() == [
            "关键日期",
            "核心提交材料",
            "学历与资格",
            "语言要求",
        ]
        assert page.locator('.requirement-card[data-category="dates"]').count() > 0
        _open_and_close_evidence(page, ".requirement-card button")
        screenshots.append(_capture(page, viewport, "requirements"))

        page.locator("#requirements-continue").focus()
        page.keyboard.press("Enter")
        assert _active_is(page, "#applicant-heading")
        _fill_applicant(page)
        _submit_comparison_with_keyboard(page)
        step_three_summary = page.locator("#step-3-summary-text").inner_text()
        assert "800" not in step_three_summary
        assert "已提供类别" in step_three_summary and "未提供类别" in step_three_summary
        _exercise_filters(page)
        _open_and_close_evidence(page, ".comparison-card button")
        _exercise_return_and_stale_flow(page)
        screenshots.append(_capture(page, viewport, "complete"))

        advanced = _exercise_advanced_tools(page, run_requests=viewport == "desktop")
        parsed = [urlparse(url) for url in requests]
        external = sorted(
            {item.netloc for item in parsed if item.netloc != urlparse(base_url).netloc}
        )
        assert external == []
        overflow = page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert overflow is False
        return {
            "viewport": viewport,
            "width": width,
            "screenshots": screenshots,
            "keyboard_flow": True,
            "drawer_focus_restored": True,
            "step_return_and_stale_clear": True,
            "focus_visible": True,
            "reduced_motion": True,
            "advanced_tools": advanced,
            "horizontal_overflow": overflow,
            "request_paths": sorted({item.path for item in parsed}),
            "external_request_hosts": external,
        }
    finally:
        context.close()


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    adjusted = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]


def _contrast(foreground: str, background: str) -> float:
    values = sorted((_relative_luminance(foreground), _relative_luminance(background)))
    return (values[1] + 0.05) / (values[0] + 0.05)


def main() -> None:
    args = _arguments()
    pdf = Path(args.pdf)
    workspace = Path(args.workspace)
    if not pdf.is_absolute() or not pdf.is_file():
        print("SKIP: fixed real PDF unavailable; pass --pdf <absolute-path>")
        raise SystemExit(5)
    identity = load_demo_config().identity
    actual_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if actual_hash != identity.source_pdf_sha256:
        raise SystemExit("FAIL: real PDF SHA-256 does not match the reviewed edition")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    executable = _entry_point()
    command = [
        executable,
        "--pdf",
        str(pdf),
        "--workspace",
        str(workspace),
        "--port",
        str(port),
    ]
    if args.rebuild:
        command.append("--rebuild")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        ready = _wait_json(f"{base_url}/v1/health/ready", process)
        live = _wait_json(f"{base_url}/v1/health/live", process)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**_browser_options(args.browser_executable))
            try:
                records = [
                    _run_viewport(browser, base_url, "desktop", 1440),
                    _run_viewport(browser, base_url, "mobile", 390),
                ]
            finally:
                browser.close()

        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["viewports"]
        height_comparison = {}
        for record in records:
            viewport = record["viewport"]
            after = {item["state"]: item["height"] for item in record["screenshots"]}
            before = baseline[viewport]
            complete_reduction = round(
                (before["complete_height"] - after["complete"]) / before["complete_height"] * 100,
                1,
            )
            assert complete_reduction >= 25
            height_comparison[viewport] = {
                "before": {
                    "initial": before["initial_height"],
                    "requirements": before["requirements_height"],
                    "complete": before["complete_height"],
                },
                "after": after,
                "complete_reduction_percent": complete_reduction,
            }

        contrast_pairs = {
            "primary_on_white": _contrast("#0e5a52", "#ffffff"),
            "success_state": _contrast("#24563f", "#e5f2e9"),
            "warning_state": _contrast("#64470e", "#fff1c9"),
            "review_state": _contrast("#5b4b77", "#eee9f5"),
            "body_text": _contrast("#172522", "#f5f6f3"),
            "focus_on_white": _contrast("#9b6500", "#ffffff"),
        }
        assert all(value >= 4.5 for value in contrast_pairs.values())
        result = {
            "schema_version": "1.0",
            "service": "installed jgrad-demo -> Uvicorn -> FastAPI",
            "installed_entry_point": Path(executable).name,
            "test_http_handler_used": False,
            "pdf_sha256": actual_hash,
            "command": "jgrad-demo --pdf <absolute-path-to-reviewed-pdf>",
            "live": live,
            "ready": ready,
            "height_comparison": height_comparison,
            "wcag_aa_contrast": {key: round(value, 2) for key, value in contrast_pairs.items()},
            "records": records,
        }
        output = OUTPUT_ROOT / "acceptance.json"
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="",
        )
        print(f"PASS: UX-01 formal real-PDF acceptance written to {output}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
