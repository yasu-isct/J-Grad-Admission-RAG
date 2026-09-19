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
    resolve_language_evaluation,
    resolve_language_score_allocation,
)
from jgrad_admission_rag.schemas.document_identity import load_document_identity  # noqa: E402
from tests.test_rule01a_real import _profile  # noqa: E402


STATIC_ROOT = ROOT / "src/jgrad_admission_rag/service/static"
PLAN = ROOT / "tests/fixtures/reviewed_report_plan_isct_master_rule04f_v1.json"
OUTPUT = ROOT / "tests/fixtures/rule04f_browser_acceptance_v1.json"
SCREENSHOTS = ROOT / "outputs/rule04f/browser"
DOCUMENT_ID = "isct_2027_4_2026_9_master"
APP_JS = STATIC_ROOT / "app.js"
PDF = ROOT / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf"
IDENTITY = ROOT / "src/jgrad_admission_rag/demo_config/document_identity.json"
SCENARIOS = {
    "information-b-confirmed": ("情報理工学院", "情報工学系", "b_schedule"),
    "information-missing-route": ("情報理工学院", "情報工学系", None),
    "information-a-not-covered": ("情報理工学院", "情報工学系", "a_schedule"),
    "information-wrong-parent": ("工学院", "情報工学系", "b_schedule"),
}
REAL_KB = build_document_kb(PDF, load_document_identity(IDENTITY))
FACT_TEXT = next(fact.text for fact in REAL_KB.facts if fact.fact_id == "fact:00288")


def scenario_results():
    plan = load_reviewed_report_plan(PLAN)
    evaluation_policy = plan.language_evaluation
    allocation_policy = plan.language_score_allocation
    assert evaluation_policy is not None
    assert allocation_policy is not None
    results = {}
    for name, (college, target, route) in SCENARIOS.items():
        payload = _profile(None)
        payload["target_application"]["graduate_school_or_college"] = college
        payload["target_application"]["department_or_program"] = target
        payload["target_application"]["application_route"] = route
        profile = ApplicantProfile.model_validate(payload)
        results[name] = (
            resolve_language_evaluation(profile, evaluation_policy),
            resolve_language_score_allocation(profile, allocation_policy),
        )
    return results


def report_payload(result, allocation):
    records = []
    evidence = result.evidence or allocation.evidence
    if evidence is not None:
        records.append(
            {
                "document_id": DOCUMENT_ID,
                "fact_id": evidence.fact_id,
                "source_pages": list(evidence.source_pages),
                "text": FACT_TEXT,
            }
        )
    return {
        "schema_version": "1.0",
        "report": {
            "reviewed_coverage_statement": "情報工学系 B 日程の英語成績評価用途を審査済みです。",
            "limitation_statement": "用途は受験者の結果、口頭試問資格又は最終合否を示しません。",
            "report_status": "complete",
            "source_plan": {"rules": []},
            "cited_answer": {
                "rule_findings": [],
                "missing_information": [],
                "interaction_warnings": [],
                "process_notices": [],
            },
            "language_score_conversion": None,
            "language_score_allocation": allocation.model_dump(mode="json"),
            "language_evaluation": result.model_dump(mode="json"),
            "evidence_bundle": {"evidence_records": records},
        },
        "markdown": "",
    }


class Handler(SimpleHTTPRequestHandler):
    results = scenario_results()
    current_scenario = "information-b-confirmed"

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
                                "intake_terms": [
                                    {"year": 2026, "month": 9},
                                    {"year": 2027, "month": 4},
                                ],
                            },
                            "version_classification": "active",
                            "covered_categories": ["language_tests"],
                            "reviewed_coverage_statement": "情報工学系 B 日程の英語評価用途。",
                            "limitation_statement": "用途は結果又は最終合否を示しません。",
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
            self._json(report_payload(*self.results[self.current_scenario]))
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
                for scenario, (result, allocation) in Handler.results.items():
                    college, target, route = SCENARIOS[scenario]
                    page = browser.new_page(viewport={"width": width, "height": 1000})
                    page.goto(f"http://127.0.0.1:{port}/app.html")
                    page.wait_for_function(
                        "document.querySelector('#report-submit').disabled === false"
                    )
                    page.locator("#report-tab").click()
                    page.locator("#report-query").fill(scenario)
                    page.locator("#graduate-school").fill(college)
                    page.locator("#department-program").fill(target)
                    page.locator("#application-route").fill(route or "")
                    page.locator("#degree-level").select_option("master")
                    page.locator("#intake-year").fill("2027")
                    page.locator("#intake-month").select_option("4")
                    page.locator("#report-submit").click()
                    section = page.locator("#report-output .report-section").filter(
                        has=page.locator("h3", has_text="志望系の英語評価方式")
                    )
                    section.wait_for()
                    text = section.inner_text()
                    page_text = page.locator("#report-output").inner_text()
                    allocation_text = (
                        page.locator("#report-output .report-section")
                        .filter(has=page.locator("h3", has_text="志望系の英語公式配点"))
                        .inner_text()
                    )
                    assert result.status.value in text
                    assert result.limitation_statement in text
                    if allocation.maximum_points is not None:
                        assert allocation.maximum_points == 100
                        assert "100 points" in allocation_text
                        assert "fact:00288" in allocation_text
                        assert "p.52" in allocation_text
                    else:
                        assert "対象外または未確認" in allocation_text
                    if result.evidence is not None:
                        assert "指定英語外部試験のスコア" in text
                        assert "実施なし" in text
                        assert "口頭試問対象者の選定 / 最終総合評価" in text
                        assert "fact:00288" in text
                        assert "p.52" in text
                        assert "筆答試験は実施せず" in page_text
                        assert "上位者を口頭試" in page_text
                    else:
                        assert "対象外または未確認" in text
                        assert "口頭試問対象者の選定" not in text
                        assert "fact:00288" not in text
                    overflow = page.evaluate(
                        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                    )
                    page.screenshot(path=SCREENSHOTS / f"{scenario}-{viewport}.png", full_page=True)
                    records.append(
                        {
                            "viewport": viewport,
                            "viewport_width": width,
                            "scenario": scenario,
                            "target": target,
                            "parent_college": college,
                            "application_route": route,
                            "status": result.status.value,
                            "assessment_source": result.assessment_source,
                            "no_internal_written_exam": result.no_internal_written_exam,
                            "evaluation_uses": (
                                [value.value for value in result.evaluation_uses]
                                if result.evaluation_uses is not None
                                else None
                            ),
                            "evidence": (
                                result.evidence.model_dump(mode="json")
                                if result.evidence is not None
                                else None
                            ),
                            "allocation_maximum_points": allocation.maximum_points,
                            "allocation_evidence": (
                                allocation.evidence.model_dump(mode="json")
                                if allocation.evidence is not None
                                else None
                            ),
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
