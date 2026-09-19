from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import sys
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jgrad_admission_rag.builder.kb_builder import build_document_kb  # noqa: E402
from jgrad_admission_rag.reasoning import (  # noqa: E402
    ApplicantProfile,
    load_reviewed_report_plan,
    resolve_program_language_condition,
)
from jgrad_admission_rag.schemas.document_identity import load_document_identity  # noqa: E402
from tests.test_rule01a_real import _profile  # noqa: E402

STATIC_ROOT = ROOT / "src/jgrad_admission_rag/service/static"
PLAN = ROOT / "tests/fixtures/reviewed_report_plan_isct_master_rule04g_v1.json"
OUTPUT = ROOT / "tests/fixtures/rule04g_browser_acceptance_v1.json"
SCREENSHOTS = ROOT / "outputs/rule04g/browser"
DOCUMENT_ID = "isct_2027_4_2026_9_master"
APP_JS = STATIC_ROOT / "app.js"
PDF = ROOT / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf"
IDENTITY = ROOT / "src/jgrad_admission_rag/demo_config/document_identity.json"
SCENARIOS = {
    "tsinghua-confirmed": (2027, 4, "tsinghua_joint_program"),
    "tsinghua-missing-route": (2027, 4, None),
    "tsinghua-wrong-intake": (2026, 9, "tsinghua_joint_program"),
    "tsinghua-wrong-route": (2027, 4, "general"),
}
REAL_KB = build_document_kb(PDF, load_document_identity(IDENTITY))
FACT = next(fact for fact in REAL_KB.facts if fact.fact_id == "fact:00347")


def scenario_results():
    policy = load_reviewed_report_plan(PLAN).program_language_condition
    assert policy is not None
    results = {}
    for name, (year, month, route) in SCENARIOS.items():
        payload = _profile(None)
        payload["target_application"]["requested_degree_level"] = "master"
        payload["target_application"]["intake_year"] = year
        payload["target_application"]["intake_month"] = month
        payload["target_application"]["application_route"] = route
        profile = ApplicantProfile.model_validate(payload)
        results[name] = resolve_program_language_condition(profile, policy)
    return results


def report_payload(result):
    evidence_records = []
    if result.evidence is not None:
        evidence_records.append(
            {
                "document_id": DOCUMENT_ID,
                "fact_id": FACT.fact_id,
                "source_pages": FACT.source_pages,
                "text": FACT.text,
            }
        )
    return {
        "schema_version": "1.0",
        "report": {
            "reviewed_coverage_statement": "清華大学合同プログラムの中国語選考範囲を審査済みです。",
            "limitation_statement": "入学選考での扱いだけを示し、能力免除、奨学金又は合否を示しません。",
            "report_status": "complete",
            "source_plan": {"rules": []},
            "cited_answer": {
                "rule_findings": [],
                "missing_information": [],
                "interaction_warnings": [],
                "process_notices": [],
            },
            "language_score_conversion": None,
            "language_score_allocation": None,
            "language_evaluation": None,
            "program_language_condition": result.model_dump(mode="json"),
            "evidence_bundle": {"evidence_records": evidence_records},
        },
        "markdown": "",
    }


class Handler(SimpleHTTPRequestHandler):
    results = scenario_results()
    current_scenario = "tsinghua-confirmed"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def log_message(self, _format, *_args):
        return

    def _json(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/reviewed-documents":
            self._json(
                {
                    "schema_version": "1.0",
                    "items": [
                        {
                            "identity": {
                                "document_id": DOCUMENT_ID,
                                "institution_name": "Institute of Science Tokyo",
                                "official_title": "Master's Program Admission Guidelines",
                                "intake_terms": [{"year": 2027, "month": 4}],
                            },
                            "version_classification": "active",
                            "covered_categories": ["language_tests"],
                            "reviewed_coverage_statement": "清華大学合同プログラムの中国語選考範囲。",
                            "limitation_statement": "能力免除、奨学金又は合否を示しません。",
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
        if self.path == "/v1/query-intents/parse":
            type(self).current_scenario = payload["query"]
            self._json({"schema_version": "1.0", "categories": ["language_tests"]})
            return
        if self.path == "/v1/applicant-reports":
            self._json(report_payload(self.results[self.current_scenario]))
            return
        self.send_error(404)


def main():
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
                for scenario, result in Handler.results.items():
                    year, month, route = SCENARIOS[scenario]
                    page = browser.new_page(viewport={"width": width, "height": 1000})
                    page.goto(f"http://127.0.0.1:{port}/app.html")
                    page.wait_for_function(
                        "document.querySelector('#report-submit').disabled === false"
                    )
                    page.locator("#report-tab").click()
                    page.locator("#report-query").fill(scenario)
                    page.locator("#application-route").fill(route or "")
                    page.locator("#degree-level").select_option("master")
                    page.locator("#intake-year").fill(str(year))
                    page.locator("#intake-month").select_option(str(month))
                    page.locator("#report-submit").click()
                    section = page.locator("#report-output .report-section").filter(
                        has=page.locator("h3", has_text="プロジェクト固有の言語選考条件")
                    )
                    section.wait_for()
                    text = section.inner_text()
                    page_text = page.locator("#report-output").inner_text()
                    assert result.status.value in text
                    assert result.limitation_statement in text
                    if result.evidence is not None:
                        assert "中国語" in text
                        assert "選考対象外" in text
                        assert "fact:00347" in text
                        assert "p.76" in text
                        assert "入学試験では、中国語の語学力は選考対象外です" in page_text
                    else:
                        assert "審査範囲外または情報不足" in text
                        assert "選考対象外" not in text
                        assert "fact:00347" not in text
                        assert "fact:00347" not in page_text
                        assert "入学試験では、中国語の語学力は選考対象外です" not in page_text
                    overflow = page.evaluate(
                        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                    )
                    page.screenshot(path=SCREENSHOTS / f"{scenario}-{viewport}.png", full_page=True)
                    records.append(
                        {
                            "viewport": viewport,
                            "viewport_width": width,
                            "scenario": scenario,
                            "intake_year": year,
                            "intake_month": month,
                            "application_route": route,
                            "status": result.status.value,
                            "program": result.program,
                            "language": result.language,
                            "admission_selection": result.admission_selection,
                            "evidence": (
                                result.evidence.model_dump(mode="json")
                                if result.evidence is not None
                                else None
                            ),
                            "visible_evidence_fact_ids": [
                                item["fact_id"]
                                for item in report_payload(result)["report"]["evidence_bundle"][
                                    "evidence_records"
                                ]
                            ],
                            "limitation_statement": result.limitation_statement,
                            "horizontal_overflow": overflow,
                            "audited_app_js_sha256": hashlib.sha256(
                                APP_JS.read_bytes()
                            ).hexdigest(),
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
