from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture UX-01 initial, requirements, and completed-flow visual evidence."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--browser-executable")
    return parser.parse_args()


def _launch_options(executable: str | None) -> dict[str, str | bool]:
    if executable:
        return {"headless": True, "executable_path": executable}
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if chrome.is_file():
        return {"headless": True, "executable_path": str(chrome)}
    return {"headless": True}


def _height(page) -> int:
    return int(page.evaluate("document.documentElement.scrollHeight"))


def _capture(page, output_dir: Path, phase: str, viewport: str, state: str) -> dict:
    path = output_dir / f"{phase}-{viewport}-{state}.png"
    height = _height(page)
    page.screenshot(path=path, full_page=True)
    return {
        "state": state,
        "height": height,
        "screenshot": path.relative_to(ROOT).as_posix(),
    }


def _run(page, base_url: str, output_dir: Path, phase: str, viewport: str) -> dict:
    page.goto(f"{base_url}/app")
    expect(page.locator("#school-select")).to_be_enabled(timeout=10_000)
    records = [_capture(page, output_dir, phase, viewport, "initial")]

    page.locator("#intake-select").select_option("isct_2027_4_2026_9_master:2027:4")
    page.locator("#college-select").select_option("工学院")
    page.locator("#department-select").select_option("システム制御系")
    page.locator("#requirements-submit").click()
    page.locator(".requirement-card").first.wait_for()
    records.append(_capture(page, output_dir, phase, viewport, "requirements"))

    continue_button = page.locator("#requirements-continue")
    if continue_button.count() and continue_button.is_visible():
        continue_button.click()
    page.locator("#demo-credential-basis").select_option("university_graduation")
    page.locator("#demo-completion-state").select_option("expected")
    page.locator("#demo-english-kind").select_option("toeic_lr")
    page.locator("#demo-english-score").fill("800")
    page.locator("#demo-japanese-background").select_option("studied")
    page.locator('[data-material-code="address_label"]').select_option("available")
    page.locator("#comparison-submit").click()
    page.locator(".comparison-card").first.wait_for()
    expect(page.locator("#readiness-panel")).to_be_visible()
    records.append(_capture(page, output_dir, phase, viewport, "complete"))

    return {
        "viewport": viewport,
        "width": page.viewport_size["width"],
        "states": records,
        "horizontal_overflow": page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
        ),
    }


def main() -> None:
    args = _arguments()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_launch_options(args.browser_executable))
        try:
            for viewport, width in (("desktop", 1440), ("mobile", 390)):
                page = browser.new_page(viewport={"width": width, "height": 1000})
                try:
                    results.append(
                        _run(page, args.base_url.rstrip("/"), output_dir, args.phase, viewport)
                    )
                finally:
                    page.close()
        finally:
            browser.close()
    payload = {"schema_version": "1.0", "phase": args.phase, "results": results}
    evidence = output_dir / f"{args.phase}-measurements.json"
    evidence.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    print(f"PASS: UX-01 {args.phase} visual evidence written to {evidence}")


if __name__ == "__main__":
    main()
