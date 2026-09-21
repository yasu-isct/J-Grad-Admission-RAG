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

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jgrad_admission_rag.demo import load_demo_config  # noqa: E402


OUTPUT_ROOT = ROOT / "outputs" / "ux03"
SCREENSHOTS = OUTPUT_ROOT / "browser"
OUTPUT = OUTPUT_ROOT / "acceptance.json"
DOCUMENT_ID = "isct_2027_4_2026_9_master"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run UX-03 through installed jgrad-demo, Uvicorn, FastAPI and a browser."
    )
    parser.add_argument("--pdf", required=True, help="Absolute fixed official PDF path.")
    parser.add_argument("--workspace", default=str((OUTPUT_ROOT / "workspace").resolve()))
    parser.add_argument("--browser-executable")
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _entry_point() -> str:
    executable = shutil.which("jgrad-demo")
    if executable is None:
        name = "jgrad-demo.exe" if os.name == "nt" else "jgrad-demo"
        sibling = Path(sys.executable).with_name(name)
        executable = str(sibling) if sibling.is_file() else None
    if executable is None:
        raise RuntimeError("installed jgrad-demo entry point is unavailable")
    return executable


def _wait_ready(url: str, process: subprocess.Popen[str]) -> dict:
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


def _target(department: str = "システム制御系") -> dict:
    return {
        "schema_version": "1.0",
        "school_id": "isct",
        "document_id": DOCUMENT_ID,
        "degree_id": "master",
        "intake": {"year": 2027, "month": 4},
        "college_id": "工学院",
        "department_id": department,
        "application_route": None,
    }


def _http_checks(base_url: str, pdf: Path, expected_hash: str) -> dict:
    payload = _post_json(f"{base_url}/v1/base-requirements", _target())
    requirements = payload["requirements"]
    must_arrive = [
        event
        for item in requirements
        for event in item.get("date_events", [])
        if event["nature"] == "must_arrive"
    ]
    materials = [item for item in requirements if item["category"] == "materials"]
    pending = [item for item in requirements if item["official_status"] == "needs_information"]
    profile_comparable = [
        item for item in pending if item["category"] in {"eligibility", "materials", "language"}
    ]
    other_confirmation = [item for item in pending if item not in profile_comparable]
    assert len(must_arrive) == 1
    assert len(materials) == 5
    assert len(pending) == 5
    assert len(profile_comparable) == 4
    assert [item["category"] for item in other_confirmation] == ["dates"]

    pdf_url = f"{base_url}/documents/{DOCUMENT_ID}/source.pdf"
    with urlopen(pdf_url, timeout=10) as response:  # noqa: S310 - fixed loopback URL
        served = response.read()
        content_type = response.headers["Content-Type"]
        accept_ranges = response.headers["Accept-Ranges"]
    with urlopen(  # noqa: S310 - fixed loopback URL
        Request(pdf_url, headers={"Range": "bytes=0-1023"}), timeout=10
    ) as response:
        range_status = response.status
    assert served == pdf.read_bytes()
    assert hashlib.sha256(served).hexdigest() == expected_hash
    assert range_status == 206
    return {
        "must_arrive": must_arrive[0]["display_text"],
        "material_count": len(materials),
        "needs_information_count": len(pending),
        "profile_comparable_count": len(profile_comparable),
        "other_confirmation_count": len(other_confirmation),
        "pdf_sha256": expected_hash,
        "pdf_content_type": content_type,
        "pdf_accept_ranges": accept_ranges,
        "pdf_range_status": range_status,
    }


def _load_target(page, base_url: str) -> None:
    page.goto(f"{base_url}/app")
    expect(page.locator("#school-select")).to_be_enabled(timeout=10_000)
    page.locator("#intake-select").select_option(f"{DOCUMENT_ID}:2027:4")
    page.locator("#college-select").select_option("工学院")
    page.locator("#department-select").select_option("システム制御系")
    page.locator("#requirements-submit").click()
    expect(page.locator(".application-overview")).to_be_visible()


def _browser_flow(browser, base_url: str, viewport_name: str, width: int) -> dict:
    page = browser.new_page(viewport={"width": width, "height": 1000})
    requests: list[str] = []
    page.on("request", lambda request: requests.append(request.url))
    try:
        _load_target(page, base_url)
        expect(page.locator('.overview-metrics [data-metric="deadline"]')).to_contain_text(
            "2026年6月10日 必着"
        )
        expect(page.locator('.overview-metrics [data-metric="materials"]')).to_contain_text("5 项")
        expect(page.locator('.overview-metrics [data-metric="pending"]')).to_contain_text("5 项")
        expect(page.locator('.overview-metrics [data-metric="pending"]')).to_contain_text(
            "其中 4 项可进入个人对照，1 项需另行确认"
        )
        assert page.locator(".application-overview").inner_text().index("必着截止") >= 0
        expect(page.locator(".pending-section h3")).to_have_text("仍需进一步确认的基础要求：5 项")
        expect(page.locator(".pending-other-notice")).to_contain_text("材料必着期限")
        assert page.locator(".profile-needs-list li").all_text_contents() == [
            "学历、预计毕业时间与资格审查路径",
            "英语考试与成绩",
            "日语学习或证明情况",
            "已有材料的准备状态",
        ]

        order = page.eval_on_selector_all(
            ".application-overview, .key-dates-section, .materials-section, .pending-section, "
            ".next-step-section, .other-requirements",
            "elements => elements.map(element => element.className)",
        )
        assert order == [
            "application-overview",
            "result-section key-dates-section",
            "result-section materials-section",
            "result-section pending-section",
            "result-section next-step-section",
            "result-section other-requirements",
        ]

        overview_deadline = page.locator('.overview-metrics [data-metric="deadline"]')
        deadline_box = overview_deadline.bounding_box()
        assert deadline_box is not None and deadline_box["y"] < 1000
        deadline = page.locator('.date-event[data-event-type="arrival_deadline"]')
        assert "必着截止" in deadline.inner_text()
        assert (
            "建议到达"
            in page.locator('.date-event[data-event-type="recommended_arrival"]').inner_text()
        )

        cta = page.locator(".overview-cta")
        cta.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#applicant-heading")).to_be_focused()
        page.locator("#edit-target").click()
        expect(page.locator("#demo-heading")).to_be_focused()
        page.locator("#department-select").select_option("機械系")
        assert page.locator(".application-overview").count() == 0
        assert page.locator("#step-2-panel").is_hidden()
        page.locator("#requirements-submit").click()
        expect(page.locator(".overview-target")).to_contain_text("機械系")
        assert "システム制御系" not in page.locator(".overview-target").inner_text()

        evidence_trigger = page.locator('.date-event[data-event-type="arrival_deadline"] button')
        evidence_trigger.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#evidence-drawer[open]")).to_be_visible()
        assert page.locator("#drawer-content .direct-evidence mark").count() >= 1
        pdf_href = page.locator("#drawer-content .pdf-source-link").first.get_attribute("href")
        assert pdf_href == f"/documents/{DOCUMENT_ID}/source.pdf#page=9"
        assert (
            page.locator("#drawer-content .official-web-link")
            .get_attribute("href")
            .startswith("https://admissions.isct.ac.jp/")
        )
        page.keyboard.press("Escape")
        assert evidence_trigger.evaluate("element => document.activeElement === element")

        overflow = page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert overflow is False
        sticky = page.locator(".overview-action").evaluate(
            "element => getComputedStyle(element).position"
        )
        if width == 390:
            assert sticky == "sticky"

        screenshot = SCREENSHOTS / f"ux03-{viewport_name}-application-overview.png"
        page.locator("#step-2-panel").screenshot(path=screenshot)
        origin = f"{base_url}/"
        external_requests = [url for url in requests if not url.startswith(origin)]
        assert external_requests == []
        return {
            "viewport": viewport_name,
            "screenshot": screenshot.relative_to(ROOT).as_posix(),
            "first_viewport_contains_must_arrive": True,
            "overview_counts": {
                "materials": 5,
                "needs_information": 5,
                "profile_comparable": 4,
                "other_confirmation": 1,
            },
            "profile_input_groups": page.locator(".profile-needs-list li").all_text_contents(),
            "target_reset_and_resubmit": True,
            "keyboard_cta_and_drawer_focus_restore": True,
            "pdf_page_link": pdf_href,
            "horizontal_overflow": overflow,
            "overview_action_position": sticky,
            "external_requests": external_requests,
            "document_height": page.evaluate("document.documentElement.scrollHeight"),
            "step_two_height": page.locator("#step-2-panel").evaluate(
                "element => Math.ceil(element.getBoundingClientRect().height)"
            ),
        }
    finally:
        page.close()


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
        ready = _wait_ready(f"{base_url}/v1/health/ready", process)
        http = _http_checks(base_url, pdf, expected_hash)
        with sync_playwright() as playwright:
            options: dict[str, str | bool] = {"headless": True}
            chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
            if args.browser_executable:
                options["executable_path"] = args.browser_executable
            elif chrome.is_file():
                options["executable_path"] = str(chrome)
            browser = playwright.chromium.launch(**options)
            try:
                records = [
                    _browser_flow(browser, base_url, "desktop-1440", 1440),
                    _browser_flow(browser, base_url, "mobile-390", 390),
                ]
                browser_version = browser.version
            finally:
                browser.close()
        result = {
            "schema_version": "1.0",
            "issue": 142,
            "service": "installed jgrad-demo -> uvicorn -> FastAPI",
            "test_http_handler_used": False,
            "command": "jgrad-demo --pdf <absolute-reviewed-pdf>",
            "ready": ready,
            "pdf_sha256": actual_hash,
            "http": http,
            "browser": {"name": "Chromium", "version": browser_version},
            "records": records,
        }
        OUTPUT.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="",
        )
        print(f"PASS: UX-03 real acceptance written to {OUTPUT}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
