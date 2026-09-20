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
from urllib.request import Request, urlopen

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jgrad_admission_rag.demo import load_demo_config  # noqa: E402


OUTPUT_ROOT = ROOT / "outputs" / "ux02"
SCREENSHOTS = OUTPUT_ROOT / "browser"
OUTPUT = OUTPUT_ROOT / "acceptance.json"
DOCUMENT_ID = "isct_2027_4_2026_9_master"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run UX-02 acceptance against the installed formal jgrad-demo service."
    )
    parser.add_argument("--pdf", required=True, help="Absolute fixed official PDF path.")
    parser.add_argument(
        "--workspace",
        default=str((OUTPUT_ROOT / "workspace").resolve()),
    )
    parser.add_argument("--browser-executable")
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_json(url: str, process: subprocess.Popen[str]) -> dict:
    deadline = time.monotonic() + 45
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
        raise RuntimeError("installed jgrad-demo entry point is unavailable")
    return executable


def _browser_options(explicit: str | None) -> dict[str, str | bool]:
    if explicit:
        return {"headless": True, "executable_path": explicit}
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if chrome.is_file():
        return {"headless": True, "executable_path": str(chrome)}
    return {"headless": True}


def _target_payload() -> dict:
    return {
        "schema_version": "1.0",
        "school_id": "isct",
        "document_id": DOCUMENT_ID,
        "degree_id": "master",
        "intake": {"year": 2027, "month": 4},
        "college_id": "工学院",
        "department_id": "システム制御系",
        "application_route": None,
    }


def _post_json(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed loopback URL
        assert response.status == 200
        return json.loads(response.read())


def _http_acceptance(base_url: str, pdf: Path, expected_hash: str) -> dict:
    payload = _post_json(f"{base_url}/v1/base-requirements", _target_payload())
    events = [
        event
        for requirement in payload["requirements"]
        for event in requirement.get("date_events", [])
    ]
    assert [event["event_type"] for event in events] == [
        "registration_open",
        "application_window",
        "arrival_deadline",
        "recommended_arrival",
    ]
    assert events[0]["display_text"] == "2026年6月1日 09:00 起（JST）"
    assert events[2]["nature"] == "must_arrive"
    assert "不是当天寄出即可" in events[2]["display_text"]
    for event in events:
        assert event["unknown_fields"]
        for evidence in event["evidence"]:
            assert evidence["local_pdf_url"] == f"/documents/{DOCUMENT_ID}/source.pdf"
            for highlight in evidence["highlights"]:
                assert (
                    evidence["official_text"][highlight["start"] : highlight["end"]]
                    == highlight["exact_text"]
                )

    source_url = f"{base_url}/documents/{DOCUMENT_ID}/source.pdf"
    with urlopen(source_url, timeout=10) as response:  # noqa: S310 - fixed loopback URL
        served = response.read()
        content_type = response.headers["Content-Type"]
        accept_ranges = response.headers["Accept-Ranges"]
    with urlopen(  # noqa: S310 - fixed loopback URL
        Request(source_url, headers={"Range": "bytes=0-1023"}), timeout=10
    ) as response:
        range_status = response.status
        range_bytes = response.read()
        content_range = response.headers["Content-Range"]
    assert served == pdf.read_bytes()
    assert hashlib.sha256(served).hexdigest() == expected_hash
    assert range_status == 206 and range_bytes == served[:1024]
    return {
        "date_event_types": [event["event_type"] for event in events],
        "character_highlights_checked": sum(
            len(evidence["highlights"]) for event in events for evidence in event["evidence"]
        ),
        "pdf_route": f"/documents/{DOCUMENT_ID}/source.pdf",
        "pdf_sha256": hashlib.sha256(served).hexdigest(),
        "content_type": content_type,
        "accept_ranges": accept_ranges,
        "range_status": range_status,
        "content_range": content_range,
    }


def _browser_flow(page, base_url: str, viewport: str) -> tuple[dict, str]:
    page.goto(f"{base_url}/app")
    expect(page.locator("#school-select")).to_be_enabled(timeout=10_000)
    page.locator("#intake-select").select_option(f"{DOCUMENT_ID}:2027:4")
    page.locator("#college-select").select_option("工学院")
    page.locator("#department-select").select_option("システム制御系")
    page.locator("#requirements-submit").click()
    expect(page.locator(".date-event")).to_have_count(4)
    conclusions = page.locator(".date-conclusion").all_text_contents()
    assert conclusions == [
        "2026年6月1日 09:00 起（JST）",
        "2026年6月4日至2026年6月10日",
        "2026年6月10日 必着（不是当天寄出即可）",
        "建议尽量在2026年6月4日到达",
    ]
    deadline = page.locator('.date-event[data-event-type="arrival_deadline"]')
    assert "必着截止" in deadline.inner_text()

    trigger = page.locator('.date-event[data-event-type="arrival_deadline"] button')
    trigger.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#evidence-drawer[open]")).to_be_visible()
    assert page.locator("#drawer-content .direct-evidence mark").count() >= 1
    assert "直接依据" in page.locator("#drawer-content").inner_text()
    pdf_link = page.locator("#drawer-content .pdf-source-link").first
    pdf_href = pdf_link.get_attribute("href")
    assert pdf_href == f"/documents/{DOCUMENT_ID}/source.pdf#page=9"
    official_link = page.locator("#drawer-content .official-web-link")
    assert official_link.get_attribute("href").startswith("https://admissions.isct.ac.jp/")
    assert official_link.get_attribute("rel") == "noopener noreferrer"

    drawer_screenshot = SCREENSHOTS / f"ux02-{viewport}-direct-evidence.png"
    page.screenshot(path=drawer_screenshot, full_page=True)
    page.keyboard.press("Escape")
    assert trigger.evaluate("element => document.activeElement === element")
    overflow = page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert overflow is False
    screenshot = SCREENSHOTS / f"ux02-{viewport}-key-dates.png"
    page.screenshot(path=screenshot, full_page=True)
    return (
        {
            "viewport": viewport,
            "conclusions": conclusions,
            "keyboard_open_and_focus_return": True,
            "direct_evidence_marks": page.locator("#drawer-content .direct-evidence mark").count(),
            "official_web_link_retained": True,
            "horizontal_overflow": overflow,
            "document_height": page.evaluate("document.documentElement.scrollHeight"),
            "screenshot": screenshot.relative_to(ROOT).as_posix(),
            "drawer_screenshot": drawer_screenshot.relative_to(ROOT).as_posix(),
        },
        pdf_href,
    )


def _viewer_check(browser, base_url: str, href: str) -> dict:
    url = f"{base_url}{href}"
    viewer = browser.new_page(viewport={"width": 1200, "height": 900})
    try:
        response = viewer.goto(url, wait_until="commit", timeout=15_000)
        time.sleep(1)
        detected = False
        detection = "none"
        try:
            if viewer.locator('embed[type="application/pdf"]').count():
                detected, detection = True, "application/pdf embed"
            elif viewer.url.startswith("chrome-extension://"):
                detected, detection = True, "Chromium PDF extension URL"
            elif viewer.locator("pdf-viewer").count():
                detected, detection = True, "Chromium pdf-viewer element"
        except PlaywrightError:
            detection = "viewer DOM is browser-internal and not script-readable"
        return {
            "requested_url": url,
            "final_url": viewer.url,
            "fragment_page": 9,
            "http_status": response.status if response is not None else None,
            "response_content_type": (
                response.headers.get("content-type") if response is not None else None
            ),
            "native_viewer_surface_detected": detected,
            "detection": detection,
            "degradation": (
                "浏览器原生 PDF viewer 可见；#page=9 的实际定位由浏览器实现。"
                if detected
                else "未能脚本识别浏览器内部 viewer；已验证 PDF 200/206、哈希和 #page=9 链接，"
                "页面仍显示官方页码供手动定位。"
            ),
        }
    except PlaywrightError as error:
        return {
            "requested_url": url,
            "native_viewer_surface_detected": False,
            "detection": type(error).__name__,
            "degradation": "浏览器未开放可自动化的原生 viewer；PDF HTTP、哈希、Range 与页码提示仍可用。",
        }
    finally:
        viewer.close()


def main() -> None:
    args = _arguments()
    pdf = Path(args.pdf)
    workspace = Path(args.workspace)
    if not pdf.is_absolute() or not pdf.is_file():
        raise SystemExit("FAIL: pass an existing absolute fixed PDF path")
    expected_hash = load_demo_config().identity.source_pdf_sha256
    actual_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise SystemExit("FAIL: real PDF SHA-256 does not match the reviewed edition")

    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    command = [
        _entry_point(),
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
        http_record = _http_acceptance(base_url, pdf, expected_hash)
        records = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**_browser_options(args.browser_executable))
            try:
                pdf_href = ""
                for viewport, width in (("desktop-1440", 1440), ("mobile-390", 390)):
                    page = browser.new_page(viewport={"width": width, "height": 1000})
                    try:
                        record, pdf_href = _browser_flow(page, base_url, viewport)
                        records.append(record)
                    finally:
                        page.close()
                viewer = _viewer_check(browser, base_url, pdf_href)
                browser_version = browser.version
            finally:
                browser.close()
        result = {
            "schema_version": "1.0",
            "issue": 140,
            "service": "installed jgrad-demo -> uvicorn -> FastAPI",
            "test_http_handler_used": False,
            "command": "jgrad-demo --pdf <absolute-reviewed-pdf> --rebuild",
            "ready": ready,
            "pdf_sha256": actual_hash,
            "http": http_record,
            "browser": {"name": "Chromium", "version": browser_version},
            "records": records,
            "pdf_viewer": viewer,
        }
        OUTPUT.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="",
        )
        print(f"PASS: UX-02 real acceptance written to {OUTPUT}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
