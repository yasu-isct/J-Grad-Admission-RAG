"""One bounded UX-01 real-service browser session using existing assets read-only."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from threading import Thread

TREE = Path(__file__).resolve().parents[2]
ROOT = Path(r"D:\J-Grad-Admission-RAG")
RUNTIME = ROOT / "outputs/m10-09-deepseek-live/runtime-v1"
SAVED = ROOT / "outputs/ui02-real/final-head-cd09bd4"
MANIFEST = ROOT / "outputs/backups/demo-before-usability-20260930/manifest.json"
OUT = TREE / "docs/onboarding/ux01-evidence"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
sys.path.insert(0, str(TREE / "src"))

import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from jgrad_admission_rag.retrieval.embedding import EmbeddingIdentity  # noqa: E402
from jgrad_admission_rag.service import create_app  # noqa: E402
from jgrad_admission_rag.service.runtime import (  # noqa: E402
    ServiceDependencies,
    ServiceSettings,
)


class IdentityOnlyEmbedding:
    def __init__(self, identity):
        self.identity = identity

    def embed_documents(self, _texts):
        raise RuntimeError("UX-01 forbids embedding builds")

    def embed_query(self, _text):
        raise RuntimeError("UX-01 forbids retrieval")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(value):
    (OUT / "real-journal.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def digest(path):
    hash_value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hash_value.update(block)
    return hash_value.hexdigest()


def asset_state(assets):
    return {
        row["path"]: {"size": Path(row["path"]).stat().st_size, "sha256": digest(Path(row["path"]))}
        for row in assets
    }


def choose(page, entry):
    path = TREE / "docs/onboarding/ux01-browser-replay.py"
    spec = importlib.util.spec_from_file_location("ux01_saved_replay", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.choose(page, entry)


def main():
    assert EDGE.is_file() and RUNTIME.is_dir() and SAVED.is_dir()
    previous = read(OUT / "real-journal.json") if (OUT / "real-journal.json").is_file() else {}
    assert previous.get("service_starts", 0) == 0, "UX-01 developer service budget is exhausted"
    manifest = read(MANIFEST)
    assert len(manifest["assets"]) == 31
    before = asset_state(manifest["assets"])
    assert all(
        before[row["path"]] == {"size": row["size"], "sha256": row["sha256"]}
        for row in manifest["assets"]
    )
    identity_manifest = read(RUNTIME / "indexes/isct_2027_4_2026_9_master/manifest.json")
    identity = EmbeddingIdentity(
        identity_manifest["embedding_provider"],
        identity_manifest["embedding_model"],
        identity_manifest["embedding_revision"],
        identity_manifest["embedding_dimension"],
    )
    settings = ServiceSettings(
        corpus_root=RUNTIME,
        manifest_path=RUNTIME / "corpus.json",
        policy_path=RUNTIME / "policy.json",
        report_plan_paths=(RUNTIME / "config/reviewed_report_plan.json",),
        page_scope_manifest_paths=(RUNTIME / "config/page_scope_manifest.json",),
        query_intent_catalog_path=RUNTIME / "config/query_intent_catalog.json",
        date_presentation_paths=(RUNTIME / "config/reviewed_date_presentation.json",),
        source_pdf_path=ROOT / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf",
        source_pdf_document_id="isct_2027_4_2026_9_master",
        source_pdf_sha256="57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735",
        reference_workspace_config_path=ROOT / "outputs/display-01/real-config.json",
    )
    journal = {
        "head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=TREE,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "service_starts": 0,
        "base_comparison_posts": 0,
        "gsfs_report_posts": 0,
        "other_posts": 0,
        "paid_calls": 0,
        "protected_asset_count": len(before),
        "protected_hashes_before": before,
        "status": "preflight passed",
    }
    save(journal)
    if "--preflight" in sys.argv:
        print(f"Preflight passed: {len(before)} protected assets unchanged; no service started")
        return
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    app = create_app(
        settings, ServiceDependencies(provider_factory=lambda: IdentityOnlyEmbedding(identity))
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    )
    worker = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    journal["service_starts"] = 1
    journal["port"] = port
    journal["status"] = "service starting"
    save(journal)
    worker.start()
    try:
        started = time.monotonic()
        while not server.started and worker.is_alive() and time.monotonic() - started < 300:
            time.sleep(0.05)
        assert server.started and time.monotonic() - started < 300
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                permissions=["clipboard-read", "clipboard-write"],
            )
            page = context.new_page()
            errors = []
            requests = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: requests.append((request.method, request.url)))
            assert page.goto(f"http://127.0.0.1:{port}/app").status == 200
            entries = context.request.get(f"http://127.0.0.1:{port}/v1/reference-targets").json()[
                "items"
            ]
            assert len(entries) == 2
            legacy = next(row for row in entries if row["kind"] == "legacy_applicant")
            gsfs = next(row for row in entries if row["kind"] == "reviewed_material_slice")

            def post(selector, suffix, expected, kind):
                key = "gsfs_report_posts" if kind == "report" else "base_comparison_posts"
                journal[key] += 1
                assert journal["base_comparison_posts"] <= 4 and journal["gsfs_report_posts"] <= 1
                save(journal)
                with page.expect_response(
                    lambda response: (
                        response.request.method == "POST" and response.url.endswith(suffix)
                    ),
                    timeout=60000,
                ) as hit:
                    page.locator(selector).click()
                assert hit.value.status == 200
                assert hit.value.json() == read(SAVED / expected)

            def report(selector, expected):
                before_posts = len([method for method, _url in requests if method == "POST"])
                page.locator(selector).click()
                page.locator("#reference-report").wait_for(state="visible")
                assert page.locator("#reference-close").evaluate(
                    "button => button === document.activeElement"
                )
                page.locator("#reference-copy").click()
                page.get_by_text("已复制当前选中的简洁报告。").wait_for()
                copied = page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
                expected_text = (
                    (TREE / "docs/onboarding/report02-evidence" / expected)
                    .read_text(encoding="utf-8")
                    .rstrip("\n")
                )
                assert copied == expected_text
                assert (
                    len([method for method, _url in requests if method == "POST"]) == before_posts
                )
                page.locator("#reference-close").click()

            choose(page, legacy)
            post("#requirements-submit", "/v1/base-requirements", "isct-base-2027.json", "base")
            page.locator("#current-target-bar").wait_for(state="visible")
            assert legacy["institution_name"] in page.locator("#current-target-name").inner_text()
            page.locator("#change-school").click()
            assert (
                page.locator("#school-select").input_value()
                == legacy["legacy_catalog"]["school_id"]
            )
            page.locator("#edit-requirements").click()
            report("#step-2-panel .reference-generate", "isct-no-profile-after-copy.txt")
            page.locator(".overview-cta").click()
            page.locator("#demo-credential-basis").select_option("ui_unknown")
            page.locator('[data-material-code="address_label"]').select_option("available")
            page.locator('[data-material-code="application_form"]').select_option("not_yet")
            post("#comparison-submit", "/v1/applicant-comparison", "isct-comparison.json", "base")
            page.locator("#readiness-panel").wait_for(state="visible")
            report("#readiness-panel .reference-generate", "isct-with-profile-after-copy.txt")
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#readiness-panel .reference-generate").scroll_into_view_if_needed()
            page.screenshot(path=str(OUT / "real-isct-step4-mobile.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#change-school").click()
            assert (
                page.locator('[data-material-code="application_form"]').input_value() == "not_yet"
            )
            choose(page, gsfs)
            assert page.locator("#reference-report-body").inner_text() == ""
            assert page.locator('[data-material-code="application_form"]').input_value() == ""
            with page.expect_response(lambda response: response.url.endswith("/evidence")) as hit:
                page.locator("#requirements-submit").click()
            assert hit.value.status == 200
            assert hit.value.json() == read(
                TREE / "docs/onboarding/evidui01-evidence/gsfs-evidence-real.json"
            )
            assert "东京大学" in page.locator("#current-target-name").inner_text()
            page.locator(".materials-section .requirement-evidence-actions button").first.click()
            assert page.locator("#evidence-drawer .relation-edge").count() == 2
            page.locator("#evidence-drawer .relation-node button").first.click()
            page.locator("#evidence-drawer .relation-back").click()
            page.locator("#drawer-close").click()
            post(
                "#step-2-panel .reference-generate",
                "/reports",
                "gsfs-unknown-unknown.json",
                "report",
            )
            page.locator("#reference-report").wait_for(state="visible")
            page.locator("#reference-close").click()
            page.locator("#change-school").click()
            choose(page, legacy)
            post("#requirements-submit", "/v1/base-requirements", "isct-base-2027.json", "base")
            assert "东京大学" not in page.locator("#current-target-name").inner_text()
            actual_posts = [url for method, url in requests if method == "POST"]
            assert len(actual_posts) == 4
            assert journal["base_comparison_posts"] == 3 and journal["gsfs_report_posts"] == 1
            assert not errors, errors
            browser.close()
        journal["protected_hashes_after"] = asset_state(manifest["assets"])
        assert journal["protected_hashes_after"] == before
        journal["status"] = "passed"
        save(journal)
    except Exception as error:
        journal["status"] = "failed"
        journal["error"] = f"{type(error).__name__}: {error}"
        save(journal)
        raise
    finally:
        server.should_exit = True
        worker.join(timeout=15)
        listener.close()
        journal["service_stopped"] = not worker.is_alive()
        journal["protected_hashes_after"] = asset_state(manifest["assets"])
        journal["protected_assets_unchanged"] = journal["protected_hashes_after"] == before
        save(journal)


if __name__ == "__main__":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    main()
