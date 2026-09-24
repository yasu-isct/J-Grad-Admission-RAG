from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "src/jgrad_admission_rag/service/static"
DOCUMENT_ID = "reviewed-demo-2027"


def _target_catalog() -> dict:
    return {
        "schema_version": "1.0",
        "schools": [
            {
                "school_id": "demo-u",
                "school_name": "Demo University",
                "degrees": [
                    {
                        "degree_id": "master",
                        "degree_name": "硕士",
                        "intakes": [
                            {
                                "document_id": DOCUMENT_ID,
                                "year": 2027,
                                "month": 4,
                                "intake_name": "2027年4月入学",
                                "colleges": [
                                    {
                                        "college_id": "理学院",
                                        "college_name": "理学院",
                                        "departments": [
                                            {
                                                "department_id": "数学系",
                                                "department_name": "数学系",
                                                "application_routes": [],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _evidence() -> dict:
    return {
        "document_id": DOCUMENT_ID,
        "official_title": "Reviewed admission guidelines",
        "school_name": "Demo University",
        "intake_name": "2027年4月入学",
        "fact_id": "fact:00001",
        "pages": [7],
        "official_text": "Applicants must provide the reviewed eligibility information.",
        "source_url": "https://example.edu/admissions",
        "scope_type": "department",
        "scope_targets": ["数学系"],
        "parent_college": "理学院",
        "limitation": "This evidence does not establish admission.",
        "highlights": [],
        "local_pdf_url": f"/documents/{DOCUMENT_ID}/source.pdf",
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def log_message(self, _format, *_args):
        return

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/reviewed-documents":
            self._json({"schema_version": "1.0", "items": []})
            return
        if self.path == "/v1/target-catalog":
            self._json(_target_catalog())
            return
        if self.path.startswith("/assets/"):
            self.path = "/" + self.path.removeprefix("/assets/")
        super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/v1/base-requirements":
            self._json(
                {
                    "schema_version": "1.0",
                    "target": {
                        "school_name": "Demo University",
                        "degree_name": "硕士",
                        "intake_name": "2027年4月入学",
                        "college_name": "理学院",
                        "department_name": "数学系",
                        "application_route_name": None,
                    },
                    "coverage_status": "partial_reviewed_rules",
                    "coverage_statement": "Reviewed eligibility scope.",
                    "limitation_statement": "Not an admission decision.",
                    "requirements": [],
                }
            )
            return
        if self.path == "/v1/grounded-answers":
            citation = {
                "evidence_id": "evidence:0001",
                "document_id": DOCUMENT_ID,
                "fact_id": "fact:00001",
                "source_pages": [7],
                "role": "primary",
                "source_kb_sha256": "1" * 64,
                "source_pdf_sha256": "2" * 64,
            }
            self._json(
                {
                    "schema_version": "1.0",
                    "target": {
                        "school_name": "Demo University",
                        "degree_name": "硕士",
                        "intake_name": "2027年4月入学",
                        "college_name": "理学院",
                        "department_name": "数学系",
                        "application_route_name": None,
                    },
                    "reviewed_scope_statement": "Reviewed eligibility scope.",
                    "official_source_url": "https://example.edu/admissions",
                    "local_pdf_url": f"/documents/{DOCUMENT_ID}/source.pdf",
                    "answer": {
                        "provider": {
                            "provider": "reviewed-state-offline",
                            "model": "grounded-reviewed-v1",
                            "revision": "1",
                        },
                        "needs_review": True,
                        "claims": [
                            {
                                "kind": "reviewed_rule",
                                "text": "Reviewed eligibility finding.",
                                "citations": [citation],
                            }
                        ],
                        "citation_inventory": [citation],
                        "missing_information": ["eligibility_facts.age_at_enrollment"],
                        "limitations": ["needs_review"],
                    },
                    "evidence": [_evidence()],
                }
            )
            return
        self.send_error(404)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                headless=True,
            )
            for width in (1440, 390):
                page = browser.new_page(viewport={"width": width, "height": 1000})
                page.goto(f"http://127.0.0.1:{port}/app.html")
                page.locator("#intake-select").select_option(f"{DOCUMENT_ID}:2027:4")
                page.locator("#college-select").select_option("理学院")
                page.locator("#department-select").select_option("数学系")
                expect(page.locator("#requirements-submit")).to_be_enabled()
                page.locator("#requirements-submit").click()
                expect(page.locator("#grounded-question")).to_be_enabled()
                page.locator("#grounded-question").fill("出願資格")
                page.locator("#grounded-answer-submit").click()
                expect(page.locator(".grounded-claim")).to_contain_text(
                    "Reviewed eligibility finding."
                )
                citation = page.locator(".grounded-citations button")
                citation.click()
                expect(page.locator("#evidence-drawer[open]")).to_be_visible()
                expect(page.locator(".pdf-source-link")).to_have_attribute(
                    "href", f"/documents/{DOCUMENT_ID}/source.pdf#page=7"
                )
                page.locator("#drawer-close").click()
                expect(citation).to_be_focused()
                assert not page.evaluate(
                    "document.documentElement.scrollWidth > document.documentElement.clientWidth"
                )
                page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
