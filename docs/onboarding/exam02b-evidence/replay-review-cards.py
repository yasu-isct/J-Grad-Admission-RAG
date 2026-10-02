"""Replay reviewed examination card and source drawer with local browser assets only.

The source slices are direct projections from registered PDF/KB; this verifies
their UI treatment, not a new base-requirements HTTP response.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STATIC = ROOT / "src/jgrad_admission_rag/service/static"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
ORIGIN = "http://exam02b-card-replay.test"
OVERLAYS = json.loads((HERE / "review-v2-exam-overlays.json").read_text(encoding="utf-8"))
CASES = {
    "earth": ("direct-earth", True),
    "applied-chemistry": ("applied-chemistry-base-v2.json", True),
    "life": ("direct-life", True),
    "system-control": ("system-control-base-v2.json", False),
}


def route_request(route) -> None:
    request = route.request
    if request.method != "GET":
        route.abort()
        raise AssertionError(f"unexpected product request: {request.url}")
    path = urlparse(request.url).path
    if path == "/app/advanced":
        route.fulfill(body=(STATIC / "advanced.html").read_bytes(), content_type="text/html")
    elif path.startswith("/assets/") and path.rsplit("/", 1)[-1] in {
        "app.css", "overview.js", "app.js", "unified-core.mjs"
    }:
        name = path.rsplit("/", 1)[-1]
        route.fulfill(body=(STATIC / name).read_bytes(), content_type=(
            "text/css" if name.endswith(".css") else "text/javascript"
        ))
    elif path == "/v1/reference-targets":
        route.fulfill(body=(ROOT / "docs/onboarding/prep01-evidence/reference-targets.json").read_bytes(),
                      content_type="application/json")
    elif path == "/v1/generation-status":
        route.fulfill(body='{"configured":false,"request_timeout_seconds":60,"label":"离线"}',
                      content_type="application/json")
    else:
        route.abort()
        raise AssertionError(f"unexpected GET: {path}")


def run_case(browser, name: str, overlay: dict, course_notice: bool, width: int) -> dict:
    page = browser.new_page(viewport={"width": width, "height": 844})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/*", route_request)
    assert page.goto(f"{ORIGIN}/app/advanced").status == 200
    page.wait_for_function("referenceCore !== null")
    page.evaluate("""(response) => {
      const card = renderExamCardV2({...response, status: 'available'});
      document.body.append(document.querySelector('#evidence-drawer'));
      document.querySelector('.app-header').remove();
      document.querySelector('main').remove();
      document.body.append(card);
      const style = document.createElement('style');
      style.textContent = '.exam-arrangement { max-width: 960px; margin: 20px auto; }';
      document.head.append(style);
    }""", overlay)
    card = page.locator(".exam-arrangement")
    assert card.is_visible()
    if course_notice:
        notice = card.locator(".exam-course-notice")
        assert notice.is_visible()
        assert "本册覆盖课程" in notice.inner_text()
        assert "地球生命コース采用另册" in notice.inner_text()
        assert card.locator("details").get_attribute("open") is None
    else:
        assert card.locator(".exam-course-notice").count() == 0
    page.screenshot(path=str(HERE / f"review-{name}-{width}-card.png"))
    label = "查看笔试原文" if name == "earth" else "查看 B 口述原文"
    if name in {"earth", "system-control"}:
        button = card.locator("button", has_text=label)
        button.click()
        drawer = page.locator("#evidence-drawer")
        assert drawer.is_visible()
        direct = "\n".join(drawer.locator(".direct-evidence mark").all_inner_texts())
        if name == "earth":
            assert all(text in direct for text in ["（１）数学", "（２）物理", "（３）化学・地球科学", "３問を選択し解答"])
            assert "英語で行います" not in direct
            assert drawer.locator(".relation-node").count() == 4
        else:
            assert "8 月 20 日（木）17 時頃" in direct
            assert "あらかじめ受験者が準備した資料を用いた発表" in direct
            assert drawer.locator(".relation-node").count() >= 2
        page.screenshot(path=str(HERE / f"review-{name}-{width}-source.png"))
        page.locator("#drawer-close").click()
        assert button.evaluate("element => document.activeElement === element")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not errors, errors
    page.close()
    return {"case": name, "width": width, "default_course_notice": course_notice,
            "source_checked": name in {"earth", "system-control"},
            "product_post": 0, "page_errors": errors}


def main() -> None:
    assert EDGE.is_file()
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
        for name, (key, notice) in CASES.items():
            for width in (1440, 390):
                results.append(run_case(browser, name, OVERLAYS[key], notice, width))
        browser.close()
    (HERE / "review-card-replay.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(results)} direct-projection card states; 0 service/POST")


if __name__ == "__main__":
    main()
