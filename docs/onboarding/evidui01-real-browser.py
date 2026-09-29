"""One bounded real-service browser check for EVID-UI-01; no model or retrieval."""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import time
from pathlib import Path
from threading import Thread

TREE = Path(__file__).resolve().parents[2]
ROOT = Path(r"D:\J-Grad-Admission-RAG")
OUT = TREE / "docs/onboarding/evidui01-evidence"
RUNTIME = ROOT / "outputs/m10-09-deepseek-live/runtime-v1"
sys.path.insert(0, str(TREE / "src"))

import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from jgrad_admission_rag.retrieval.embedding import EmbeddingIdentity  # noqa: E402
from jgrad_admission_rag.service import create_app  # noqa: E402
from jgrad_admission_rag.service.runtime import ServiceDependencies, ServiceSettings  # noqa: E402

helper_spec = importlib.util.spec_from_file_location(
    "report02_check_helpers", TREE / "docs/onboarding/report02-real-browser.py"
)
helper = importlib.util.module_from_spec(helper_spec)
helper_spec.loader.exec_module(helper)


class IdentityOnlyEmbedding:
    def __init__(self, identity):
        self.identity = identity

    def embed_documents(self, _texts):
        raise RuntimeError("EVID-UI-01 forbids embedding builds")

    def embed_query(self, _text):
        raise RuntimeError("EVID-UI-01 forbids retrieval")


def save(journal):
    (OUT / "real-browser-journal.json").write_text(
        json.dumps(journal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    journal_path = OUT / "real-browser-journal.json"
    previous = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {}
    if previous.get("service_startups", 0) >= 2 or previous.get("gsfs_report_attempts", 0) + 2 > 3:
        raise RuntimeError("EVID-UI-01 service or report budget is exhausted")
    assert helper.EDGE.is_file() and RUNTIME.is_dir()
    baseline = helper.read(ROOT / "outputs/display-01/real-before.json")
    protected = list(baseline) + [
        f"outputs/m9-01/index-bge-m3-5617a9f6/{name}"
        for name in ("manifest.json", "payloads.jsonl", "embeddings.npy")
    ]
    protected += [
        f"docs/onboarding/{name}"
        for name in (
            "material-slice-report-plan-v1.json",
            "material-condition-policy-v1.json",
            "material-condition-trust-v1.json",
            "material-slice-report-trust-v1.json",
            "gsfs-material-evidence-seed-v1.json",
        )
    ]
    before = {name: helper.digest(ROOT / name) for name in protected}
    assert all(before[name] == row["sha256"] for name, row in baseline.items())
    manifest = helper.read(RUNTIME / "indexes/isct_2027_4_2026_9_master/manifest.json")
    identity = EmbeddingIdentity(
        manifest["embedding_provider"],
        manifest["embedding_model"],
        manifest["embedding_revision"],
        manifest["embedding_dimension"],
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
        "service_startups": previous.get("service_startups", 0),
        "gsfs_report_attempts": previous.get("gsfs_report_attempts", 0),
        "base_comparison_posts": previous.get("base_comparison_posts", 0),
        "other_posts": 0,
        "paid_calls": 0,
        "protected_count": len(protected),
        "protected_hashes_before": before,
        "memory_before": helper.memory(),
        "cases": [],
        "previous_attempt": {
            key: previous.get(key)
            for key in (
                "service_startups",
                "gsfs_report_attempts",
                "base_comparison_posts",
                "status",
            )
        },
        "status": "incomplete",
    }
    save(journal)
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
    journal["service_startups"] += 1
    journal["port"] = port
    save(journal)
    worker.start()
    try:
        started = time.monotonic()
        while not server.started and worker.is_alive() and time.monotonic() - started < 300:
            time.sleep(0.05)
        assert server.started and time.monotonic() - started < 300
        journal["memory_after_startup"] = helper.memory()
        save(journal)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(helper.EDGE))
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_default_timeout(30000)
            errors, posts = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "request",
                lambda request: posts.append(request.url) if request.method == "POST" else None,
            )
            assert page.goto(f"http://127.0.0.1:{port}/app").status == 200
            entries = page.context.request.get(
                f"http://127.0.0.1:{port}/v1/reference-targets"
            ).json()["items"]
            assert len(entries) == 2
            gsfs = next(row for row in entries if row["kind"] == "reviewed_material_slice")
            legacy = next(row for row in entries if row["kind"] == "legacy_applicant")
            helper.choose(page, gsfs)
            with page.expect_response(lambda response: response.url.endswith("/evidence")) as hit:
                page.locator("#requirements-submit").click()
            assert hit.value.status == 200
            evidence = hit.value.json()
            (OUT / "gsfs-evidence-real.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            assert evidence["snapshot_id"] == gsfs["snapshot_id"]
            assert evidence["revision"] == gsfs["revision"]
            plan = helper.read(TREE / "docs/onboarding/material-slice-report-plan-v1.json")
            expected = {(row["from"], row["kind"], row["to"]) for row in plan["relations"]}
            actual = {
                (row["from"], row["kind"], row["to"])
                for topic in evidence["topics"]
                for row in topic["relations"]
            }
            assert actual == expected and len(actual) == 5
            assert page.locator(".materials-section .requirement-card").count() == 3
            page.screenshot(path=str(OUT / "gsfs-step2-desktop-full.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(OUT / "gsfs-step2-mobile-full.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.set_viewport_size({"width": 1440, "height": 900})
            assert not posts
            for index, topic in enumerate(evidence["topics"]):
                trigger = page.locator(
                    ".materials-section .requirement-card .requirement-evidence-actions button"
                ).nth(index)
                trigger.click()
                drawer = page.locator("#evidence-drawer")
                assert drawer.is_visible() and drawer.locator(".relation-node").count() == len(
                    topic["records"]
                )
                assert drawer.locator(".relation-edge").count() == len(topic["relations"])
                assert page.evaluate("document.querySelectorAll('dialog[open]').length") == 1
                page.screenshot(path=str(OUT / f"gsfs-{index + 1}-graph-desktop.png"))
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(OUT / f"gsfs-{index + 1}-graph-mobile.png"))
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                node = drawer.locator(".relation-node button").first
                node.click()
                assert drawer.locator(".relation-back").is_visible()
                assert topic["records"][0]["fragments"][0]["quote_text"] in drawer.inner_text()
                assert topic["records"][0]["source_title"] in drawer.inner_text()
                assert page.evaluate("document.querySelectorAll('dialog[open]').length") == 1
                page.screenshot(path=str(OUT / f"gsfs-{index + 1}-original-mobile.png"))
                drawer.locator(".relation-back").click()
                assert drawer.locator(".relation-node").count() == len(topic["records"])
                assert node.evaluate("element => element === document.activeElement")
                if index == 2:
                    assert drawer.locator(".relation-edge-stage").count() == 1
                    drawer.press("Escape")
                else:
                    page.locator("#drawer-close").click()
                assert drawer.is_hidden() and trigger.evaluate(
                    "element => element === document.activeElement"
                )
                page.set_viewport_size({"width": 1440, "height": 900})
                journal["cases"].append(
                    {
                        "topic": topic["material_name_zh"],
                        "records": len(topic["records"]),
                        "relations": len(topic["relations"]),
                        "same_modal": True,
                    }
                )
            assert not posts
            page.locator(".overview-cta").click()
            page.locator("#slice-current-employed").select_option("yes")
            page.locator("#slice-retain-employed").select_option("yes")
            journal["gsfs_report_attempts"] += 1
            save(journal)
            with page.expect_response(
                lambda response: response.url.endswith("/reports")
            ) as report_hit:
                page.locator("#comparison-submit").click()
            assert report_hit.value.status == 200
            page.locator("#readiness-panel.slice-readiness").wait_for(state="visible")
            assert page.locator("#comparison-output .requirement-card").count() == 3
            page.screenshot(path=str(OUT / "gsfs-step4-desktop-full.png"), full_page=True)
            page.locator("#comparison-output .requirement-evidence-actions button").nth(2).click()
            assert (
                "入学手续相关，非本次出愿提交义务" in page.locator("#evidence-drawer").inner_text()
            )
            page.locator("#drawer-close").click()
            journal["gsfs_report_attempts"] += 1
            save(journal)
            page.locator("#readiness-panel .reference-generate").click()
            page.locator("#reference-report").wait_for(state="visible")
            assert "材料准备清单" in page.locator("#reference-report-body").inner_text()
            assert "物理页" not in page.locator("#reference-report-body").inner_text()
            page.locator("#reference-close").click()
            assert len(posts) == 1
            helper.choose(page, legacy)
            journal["base_comparison_posts"] += 1
            save(journal)
            with page.expect_response(
                lambda response: response.url.endswith("/v1/base-requirements")
            ) as base_hit:
                page.locator("#requirements-submit").click()
            assert base_hit.value.status == 200
            page.locator(".materials-section .requirement-card").first.wait_for(state="visible")
            page.screenshot(path=str(OUT / "isct-step2-desktop-full.png"), full_page=True)
            assert "查看官方依据" in page.locator(".materials-section").inner_text()
            assert len(posts) == 2 and not errors, (posts, errors)
            browser.close()
        journal["memory_after_browser"] = helper.memory()
        journal["protected_hashes_after"] = {name: helper.digest(ROOT / name) for name in protected}
        assert journal["protected_hashes_after"] == before
        journal["status"] = "passed"
        save(journal)
    finally:
        server.should_exit = True
        worker.join(timeout=15)
        listener.close()
        journal["service_stopped"] = not worker.is_alive()
        journal["protected_hashes_after"] = {name: helper.digest(ROOT / name) for name in protected}
        journal["protected_unchanged"] = journal["protected_hashes_after"] == before
        save(journal)


if __name__ == "__main__":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    main()
