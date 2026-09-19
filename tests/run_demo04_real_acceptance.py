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
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jgrad_admission_rag.demo import load_demo_config  # noqa: E402

SCREENSHOTS = ROOT / "outputs" / "demo04" / "browser"
OUTPUT = SCREENSHOTS / "acceptance.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run DEMO-04 browser acceptance against the formal jgrad-demo service."
    )
    parser.add_argument("--pdf", required=True, help="Absolute fixed official PDF path.")
    parser.add_argument(
        "--workspace",
        default=str((ROOT / "outputs" / "demo04" / "workspace").resolve()),
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


def _launch_command(pdf: Path, workspace: Path, port: int, rebuild: bool) -> list[str]:
    executable = shutil.which("jgrad-demo")
    command = [executable] if executable else [sys.executable, "-m", "jgrad_admission_rag.demo_cli"]
    command.extend(["--pdf", str(pdf), "--workspace", str(workspace), "--port", str(port)])
    if rebuild:
        command.append("--rebuild")
    return command


def _browser_launch_options(explicit: str | None) -> dict[str, str | bool]:
    if explicit:
        return {"headless": True, "executable_path": explicit}
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if chrome.is_file():
        return {"headless": True, "executable_path": str(chrome)}
    return {"headless": True}


def _run_flow(page, base_url: str, viewport: str) -> dict:
    page.goto(f"{base_url}/app")
    expect(page.locator("#school-select")).to_be_enabled(timeout=10_000)
    page.locator("#intake-select").select_option("isct_2027_4_2026_9_master:2027:4")
    page.locator("#college-select").select_option("工学院")
    page.locator("#department-select").select_option("システム制御系")
    assert page.locator("#requirements-submit").is_enabled()
    page.locator("#requirements-submit").click()
    page.locator(".requirement-card").first.wait_for()
    categories = page.locator(".requirement-group h3").all_text_contents()
    assert categories == ["关键日期", "核心提交材料", "学历与资格", "语言要求"]

    first_evidence = page.locator(".requirement-card button").first
    first_evidence.click()
    page.locator("#evidence-drawer[open]").wait_for()
    first_drawer = page.locator("#drawer-content").inner_text()
    assert "官方页码" in first_drawer
    assert page.locator("#drawer-content .evidence-text").inner_text().strip()
    page.keyboard.press("Escape")
    assert first_evidence.evaluate("element => document.activeElement === element")

    page.locator("#demo-credential-basis").select_option("university_graduation")
    page.locator("#demo-completion-state").select_option("expected")
    page.locator("#demo-english-kind").select_option("toeic_lr")
    page.locator("#demo-english-score").fill("800")
    page.locator("#demo-japanese-background").select_option("studied")
    page.locator('[data-material-code="address_label"]').select_option("available")
    page.locator("#comparison-submit").click()
    page.locator(".comparison-card").first.wait_for()
    assert page.locator("#readiness-panel").is_visible()
    comparison_groups = page.locator(".comparison-group h3").all_text_contents()
    assert comparison_groups == ["学历", "英语", "日语", "已有材料与官方适用性"]

    recorded_filter = page.locator('input[name="readiness-filter"][value="recorded"]')
    recorded_filter.check()
    assert recorded_filter.is_checked()
    visible_cards = page.locator(".comparison-card:visible")
    assert visible_cards.count() == int(page.locator("#count-recorded").inner_text())
    second_evidence = page.locator(".comparison-card:visible button").first
    second_evidence.click()
    page.locator("#evidence-drawer[open]").wait_for()
    second_drawer = page.locator("#drawer-content").inner_text()
    assert "官方页码" in second_drawer
    assert page.locator("#drawer-content .evidence-text").inner_text().strip()
    page.keyboard.press("Escape")

    overflow = page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert overflow is False
    screenshot = SCREENSHOTS / f"demo04-{viewport}.png"
    page.screenshot(path=screenshot, full_page=True)
    return {
        "viewport": viewport,
        "target": "東京科学大学 / 修士 / 2027年4月 / 工学院 / システム制御系",
        "requirements": categories,
        "comparison_groups": comparison_groups,
        "official_evidence_opened_before_and_after_filter": True,
        "filter": "recorded",
        "horizontal_overflow": overflow,
        "screenshot": screenshot.relative_to(ROOT).as_posix(),
    }


def main() -> None:
    args = _arguments()
    pdf = Path(args.pdf)
    workspace = Path(args.workspace)
    if not pdf.is_absolute() or not pdf.is_file():
        print("SKIP: fixed real PDF unavailable; pass --pdf <absolute-path>")
        raise SystemExit(5)
    expected_hash = load_demo_config().identity.source_pdf_sha256
    actual_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise SystemExit("FAIL: real PDF SHA-256 does not match the reviewed edition")

    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    command = _launch_command(pdf, workspace, port, args.rebuild)
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
        catalog = _wait_json(f"{base_url}/v1/target-catalog", process)
        records = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**_browser_launch_options(args.browser_executable))
            try:
                for viewport, width in (("desktop", 1440), ("mobile", 390)):
                    page = browser.new_page(viewport={"width": width, "height": 1000})
                    try:
                        records.append(_run_flow(page, base_url, viewport))
                    finally:
                        page.close()
            finally:
                browser.close()
        result = {
            "schema_version": "1.0",
            "service": "jgrad-demo -> uvicorn -> FastAPI",
            "test_http_handler_used": False,
            "pdf_sha256": actual_hash,
            "command": "jgrad-demo --pdf <absolute-path-to-reviewed-pdf>",
            "live": live,
            "ready": ready,
            "school_count": len(catalog["schools"]),
            "records": records,
        }
        OUTPUT.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="",
        )
        print(f"PASS: formal DEMO-04 acceptance written to {OUTPUT}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
