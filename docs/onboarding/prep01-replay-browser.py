"""Finish browser presentation with the saved real PREP-01 responses; no product service."""

from __future__ import annotations

import json
import runpy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright

TREE = Path(__file__).resolve().parents[2]
STATIC = TREE / "src/jgrad_admission_rag/service/static"
OUT = TREE / "docs/onboarding/prep01-evidence"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


class ReplayHandler(BaseHTTPRequestHandler):
    posts = 0

    def log_message(self, *_args):
        return

    def do_POST(self):
        type(self).posts += 1
        self.send_error(500, "Unexpected replay POST")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/app":
            filename = STATIC / "advanced.html"
            content_type = "text/html; charset=utf-8"
        elif path.startswith("/assets/") and "/" not in path[len("/assets/") :]:
            filename = STATIC / path[len("/assets/") :]
            content_type = (
                "text/javascript; charset=utf-8"
                if filename.suffix in {".js", ".mjs"}
                else "text/css; charset=utf-8"
                if filename.suffix == ".css"
                else "application/octet-stream"
            )
        elif path == "/v1/reference-targets":
            filename = OUT / "reference-targets.json"
            content_type = "application/json; charset=utf-8"
        else:
            self.send_error(503, "Outside saved-response replay")
            return
        if not filename.is_file():
            self.send_error(404)
            return
        data = filename.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    journal = json.loads((OUT / "journal.json").read_text(encoding="utf-8"))
    assert journal["service_startups"] == 1 and journal["base_comparison_posts"] == 2
    assert journal["service_stopped"] and journal["assets_unchanged"]
    base = json.loads((OUT / "isct-base.json").read_text(encoding="utf-8"))
    comparison = json.loads((OUT / "isct-comparison.json").read_text(encoding="utf-8"))
    catalog = json.loads((OUT / "reference-targets.json").read_text(encoding="utf-8"))
    browser_case = runpy.run_path(str(TREE / "docs/onboarding/prep01-real-browser.py"))[
        "browser_case"
    ]
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ReplayHandler)
    worker = Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
            results = [
                browser_case(
                    browser,
                    f"http://127.0.0.1:{httpd.server_port}",
                    catalog,
                    base,
                    comparison,
                    width,
                    label,
                )
                for width, label in ((1440, "desktop"), (390, "mobile"))
            ]
            browser.close()
        assert ReplayHandler.posts == 0
        journal["saved_response_replay"] = {
            "cases": results,
            "product_service_starts": 0,
            "product_api_posts": 0,
        }
        (OUT / "journal.json").write_text(
            json.dumps(journal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    finally:
        httpd.shutdown()
        worker.join(timeout=5)


if __name__ == "__main__":
    main()
