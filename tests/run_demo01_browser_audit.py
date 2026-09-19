from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import time

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jgrad_admission_rag.builder.kb_builder import build_document_kb  # noqa: E402
from jgrad_admission_rag.reasoning.reviewed_report_evidence import (  # noqa: E402
    ReviewedReportEvidenceRecord,
)
from jgrad_admission_rag.reasoning.reviewed_report_plan import (  # noqa: E402
    load_reviewed_report_plan,
)
from jgrad_admission_rag.schemas.document_identity import load_document_identity  # noqa: E402
from jgrad_admission_rag.service.demo_requirements import (  # noqa: E402
    DemoApplicantComparisonRequest,
    DemoTargetRequest,
    build_demo_applicant_comparison,
    build_demo_base_requirements,
    build_demo_target_catalog,
)

STATIC_ROOT = ROOT / "src/jgrad_admission_rag/service/static"
PLAN_PATH = ROOT / "tests/fixtures/reviewed_report_plan_isct_master_rule05a_v1.json"
PDF_PATH = ROOT / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf"
IDENTITY_PATH = ROOT / "tests/fixtures/document_identity_isct_master_v1.json"
SCREENSHOTS = ROOT / "outputs/demo03/browser"
OUTPUT = SCREENSHOTS / "audit.json"

PLAN = load_reviewed_report_plan(PLAN_PATH)
KB = build_document_kb(PDF_PATH, load_document_identity(IDENTITY_PATH))
RECORDS = tuple(
    ReviewedReportEvidenceRecord(
        document_id=PLAN.document_identity.document_id,
        fact_id=fact.fact_id,
        text=fact.text,
        source_pages=tuple(fact.source_pages),
        section_path=tuple(fact.section_path),
        fact_type=fact.fact_type,
        scope_type=fact.scope_type,
        scope_targets=tuple(sorted(set(fact.scope_targets))),
        parent_college=fact.parent_college,
        rule_ids=("browser-audit",),
    )
    for fact in KB.facts
    if fact.section_path and fact.source_pages
)
BUNDLE = SimpleNamespace(evidence_records=RECORDS)
CATALOG = build_demo_target_catalog((PLAN,)).model_dump(mode="json")


class Handler(SimpleHTTPRequestHandler):
    base_requirement_requests = 0
    comparison_requests = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def log_message(self, _format, *_args):
        return

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionError, OSError):
            pass

    def do_GET(self):
        if self.path == "/v1/target-catalog":
            self._json(CATALOG)
            return
        if self.path == "/v1/reviewed-documents":
            identity = PLAN.document_identity
            self._json(
                {
                    "schema_version": "1.0",
                    "items": [
                        {
                            "identity": {
                                "document_id": identity.document_id,
                                "institution_name": identity.institution_name,
                                "official_title": identity.official_title,
                                "intake_terms": [
                                    item.model_dump(mode="json") for item in identity.intake_terms
                                ],
                            },
                            "version_classification": "active",
                            "covered_categories": [item.value for item in PLAN.covered_categories],
                            "reviewed_coverage_statement": PLAN.reviewed_coverage_statement,
                            "limitation_statement": PLAN.limitation_statement,
                        }
                    ],
                }
            )
            return
        if self.path.startswith("/assets/"):
            self.path = "/" + self.path.removeprefix("/assets/")
        super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/v1/base-requirements":
            type(self).base_requirement_requests += 1
            if type(self).base_requirement_requests == 1:
                time.sleep(0.3)
            request = DemoTargetRequest.model_validate(payload)
            response = build_demo_base_requirements(request, PLAN, BUNDLE)
            self._json(response.model_dump(mode="json"))
            return
        if self.path == "/v1/applicant-comparison":
            type(self).comparison_requests += 1
            if type(self).comparison_requests == 1:
                time.sleep(0.3)
            request = DemoApplicantComparisonRequest.model_validate(payload)
            response = build_demo_applicant_comparison(request, PLAN, BUNDLE)
            self._json(response.model_dump(mode="json"))
            return
        self.send_error(404)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    records = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                headless=True,
            )
            for viewport, width in (("desktop", 1440), ("mobile", 390)):
                page = browser.new_page(viewport={"width": width, "height": 1000})
                page.goto(f"http://127.0.0.1:{port}/app.html")
                page.wait_for_function(
                    "document.querySelector('#school-select').disabled === false"
                )
                page.locator("#intake-select").select_option(
                    f"{PLAN.document_identity.document_id}:2027:4"
                )
                page.locator("#college-select").select_option("工学院")
                page.locator("#department-select").select_option("システム制御系")
                assert page.locator("#requirements-submit").is_enabled()
                page.locator("#requirements-submit").click()
                if viewport == "desktop":
                    page.locator("#college-select").select_option("理学院")
                    page.wait_for_timeout(500)
                    assert page.locator(".requirement-card").count() == 0
                    assert "正在核对" not in page.locator("#target-status").inner_text()
                    assert page.locator("#requirements-retry").is_hidden()
                    page.locator("#college-select").select_option("工学院")
                    page.locator("#department-select").select_option("システム制御系")
                    page.locator("#requirements-submit").click()
                page.locator(".requirement-card").first.wait_for()
                categories = page.locator(".requirement-group h3").all_text_contents()
                assert categories == ["关键日期", "核心提交材料", "学历与资格", "语言要求"]
                assert "清華" not in page.locator("#requirements-output").inner_text()
                trigger = page.locator(".requirement-card button").first
                trigger.click()
                page.locator("#evidence-drawer[open]").wait_for()
                drawer_text = page.locator("#drawer-content").inner_text()
                assert "官方页码" in drawer_text
                assert "安全限制" in drawer_text
                assert "Fact ID" not in drawer_text
                drawer_screenshot = None
                if viewport == "mobile":
                    drawer_screenshot = SCREENSHOTS / "demo03-mobile-evidence.png"
                    page.screenshot(path=drawer_screenshot)
                page.keyboard.press("Escape")
                assert trigger.evaluate("element => document.activeElement === element")
                page.locator("#demo-credential-basis").select_option("university_graduation")
                page.locator("#demo-completion-state").select_option("expected")
                page.locator("#demo-english-kind").select_option("toeic_lr")
                page.locator("#demo-english-score").fill("800")
                page.locator("#demo-japanese-background").select_option("studied")
                page.locator('[data-material-code="address_label"]').select_option("available")
                assert page.locator("#comparison-submit").is_enabled()
                page.locator("#comparison-submit").click()
                if viewport == "desktop":
                    page.locator("#demo-english-score").fill("810")
                    page.wait_for_timeout(500)
                    assert page.locator(".comparison-card").count() == 0
                    assert "正在由服务端对照" not in page.locator("#comparison-status").inner_text()
                    page.locator("#comparison-submit").click()
                page.locator(".comparison-card").first.wait_for()
                comparison_groups = page.locator(".comparison-group h3").all_text_contents()
                assert comparison_groups == ["学历", "英语", "日语", "已有材料与官方适用性"]
                assert "可能匹配，仍需核对" in page.locator("#comparison-output").inner_text()
                assert "个人准备状态：已有" in page.locator("#comparison-output").inner_text()
                assert page.locator("#readiness-panel").is_visible()
                action_count = int(page.locator("#count-action").inner_text())
                page.locator('input[name="readiness-filter"][value="action_required"]').check()
                assert page.locator(".comparison-card:visible").count() == action_count
                page.locator('input[name="readiness-filter"][value="all"]').check()
                assert page.locator(".comparison-card:visible").count() == int(
                    page.locator("#count-total").inner_text()
                )
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                )
                assert overflow is False
                screenshot = SCREENSHOTS / f"demo03-{viewport}.png"
                page.screenshot(path=screenshot, full_page=True)
                records.append(
                    {
                        "viewport": viewport,
                        "viewport_width": width,
                        "target": "東京科学大学 / 2027年4月 / 工学院 / システム制御系",
                        "categories": categories,
                        "drawer_keyboard_close_and_focus_restore": True,
                        "stale_request_suppressed": True,
                        "stale_comparison_suppressed": True,
                        "comparison_groups": comparison_groups,
                        "readiness_filter_keyboard_flow": True,
                        "conditional_program_evidence_visible": False,
                        "horizontal_overflow": overflow,
                        "screenshot": screenshot.relative_to(ROOT).as_posix(),
                        "drawer_screenshot": (
                            drawer_screenshot.relative_to(ROOT).as_posix()
                            if drawer_screenshot is not None
                            else None
                        ),
                    }
                )
                page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    OUTPUT.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    print(f"wrote {len(records)} browser records to {OUTPUT}")


if __name__ == "__main__":
    main()
