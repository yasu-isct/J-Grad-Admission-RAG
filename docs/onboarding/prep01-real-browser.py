"""One bounded, read-only PREP-01 service session over the existing 391 runtime."""

from __future__ import annotations

import hashlib
import json
import socket
import sys
import time
from pathlib import Path
from threading import Thread

TREE = Path(__file__).resolve().parents[2]
ROOT = Path(r"D:\J-Grad-Admission-RAG")
RUNTIME = ROOT / "outputs/m10-09-deepseek-live/runtime-v1"
OUT = TREE / "docs/onboarding/prep01-evidence"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
sys.path.insert(0, str(TREE / "src"))

import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from jgrad_admission_rag.retrieval.embedding import EmbeddingIdentity  # noqa: E402
from jgrad_admission_rag.service import create_app  # noqa: E402
from jgrad_admission_rag.service.runtime import ServiceDependencies, ServiceSettings  # noqa: E402


class IdentityOnlyEmbedding:
    def __init__(self, identity):
        self.identity = identity

    def embed_documents(self, _texts):
        raise RuntimeError("PREP-01 prohibits index builds")

    def embed_query(self, _text):
        raise RuntimeError("PREP-01 prohibits retrieval")


TARGET = {
    "school_id": "isct",
    "document_id": "isct_2027_4_2026_9_master",
    "degree_id": "master",
    "intake": {"year": 2027, "month": 4},
    "college_id": "情報理工学院",
    "department_id": "情報工学系",
    "application_route": "b_schedule",
}
MATERIALS = [
    "address_label",
    "application_form",
    "statement_of_purpose",
    "bachelor_transcript",
    "graduation_or_expected_graduation_certificate",
]
COMPARISON = {
    "target": TARGET,
    "applicant": {
        "credential_basis": "university_graduation",
        "completion_state": None,
        "english_test_kind": "toeic_lr",
        "english_score": None,
        "english_test_date": "2024-06-11",
        "english_official_report_available": True,
        "japanese_background": None,
        "materials": [
            {
                "code": code,
                "preparation": "available"
                if code == "address_label"
                else "not_yet"
                if code == "application_form"
                else "unknown",
            }
            for code in MATERIALS
        ],
    },
    "english_preparation": {
        "downloaded_online_pdf": True,
        "toeic_verification_qr_present": None,
        "toeic_digital_official_score_certificate": True,
        "toefl_test_taker_score_report_pdf": None,
        "toefl_di_code_g179_set": None,
    },
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(name: str, value) -> None:
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def screenshot(page, name: str) -> None:
    page.screenshot(path=str(OUT / name), full_page=True)


def browser_case(browser, base_url: str, catalog, base, comparison, width: int, label: str):
    context = browser.new_context(
        viewport={"width": width, "height": 900}, permissions=["clipboard-read", "clipboard-write"]
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    routed_posts = []

    def fulfill(route):
        endpoint = route.request.url.rsplit("/", 1)[-1]
        routed_posts.append(endpoint)
        payload = base if endpoint == "base-requirements" else comparison
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        )

    page.route("**/v1/base-requirements", fulfill)
    page.route("**/v1/applicant-comparison", fulfill)
    assert page.goto(f"{base_url}/app").status == 200
    page.locator("#school-select").select_option("isct")
    page.locator("#demo-degree-select").select_option("master")
    page.locator("#intake-select").select_option("isct_2027_4_2026_9_master:2027:4")
    page.locator("#college-select").select_option("情報理工学院")
    page.locator("#department-select").select_option("情報工学系")
    page.locator("#route-select").select_option("b_schedule")
    page.locator("#requirements-submit").click()
    page.locator(".english-section .english-guide-list").wait_for(state="visible")
    assert "2024年6月11日" in page.locator(".english-section").inner_text()
    screenshot(page, f"{label}-step2.png")
    page.locator(".english-section").scroll_into_view_if_needed()
    page.screenshot(path=str(OUT / f"{label}-step2-focus.png"))

    page.locator(".materials-section .requirement-card").first.locator("button").first.click()
    assert "这项材料的准备要点" in page.locator("#drawer-content").inner_text()
    assert "240×332" in page.locator("#drawer-content").inner_text()
    page.locator("#drawer-close").click()
    page.locator(".overview-cta").click()
    group = page.locator('.profile-group[data-profile-group="english"]')
    if not group.evaluate("element => element.open"):
        group.locator("summary").click()
    page.locator("#demo-credential-basis").select_option("university_graduation")
    page.locator("#demo-english-kind").select_option("toeic_lr")
    page.locator("#demo-english-date").fill("2024-06-11")
    page.locator("#demo-english-report").select_option("true")
    page.locator("#demo-english-online-pdf").select_option("true")
    page.locator("#demo-toeic-certificate").select_option("true")
    materials_group = page.locator('.profile-group[data-profile-group="materials"]')
    if not materials_group.evaluate("element => element.open"):
        materials_group.locator("summary").click()
    page.locator('[data-material-code="address_label"]').select_option("available")
    page.locator('[data-material-code="application_form"]').select_option("not_yet")
    page.locator("#comparison-submit").click()
    page.locator(".english-preparation-group").wait_for(state="visible")
    readiness = page.locator("#readiness-panel").inner_text()
    assert "TOEIC真伪验证二维码" in readiness and "尚待确认" in readiness
    assert "入学申请表" in readiness and "报名费" in readiness
    screenshot(page, f"{label}-step4.png")
    page.locator(".english-preparation-group").scroll_into_view_if_needed()
    page.screenshot(path=str(OUT / f"{label}-step4-focus.png"))

    page.locator("#readiness-panel .reference-generate").click()
    page.locator("#reference-report[open]").wait_for(state="visible")
    boxes = page.locator('.reader-report-options input[type="checkbox"]')
    # The options are in dates, materials, other order for this target.
    boxes.nth(0).uncheck()
    boxes.nth(2).uncheck()
    report_body = page.locator("#reference-report-body").inner_text()
    assert "英语成绩与证明" in report_body and "二维码" in report_body
    assert "邮寄地址标签" in report_body and "入学申请表" in report_body
    screenshot(page, f"{label}-report-materials.png")
    page.locator("#reference-copy").click()
    copied = page.evaluate("navigator.clipboard.readText()")
    assert "英语成绩与证明" in copied and "报名费" in copied
    normalized_copy = copied.replace("\r\n", "\n").replace("\r", "\n")
    (OUT / f"{label}-materials-copy.txt").write_bytes(normalized_copy.encode("utf-8"))
    boxes.nth(0).check()
    boxes.nth(1).uncheck()
    dates = page.locator("#reference-report-body").inner_text()
    assert "关键时间" in dates and "没有明确的待补材料" not in dates
    assert "英语成绩与证明" not in dates
    screenshot(page, f"{label}-report-dates.png")
    page.locator("#reference-close").click()
    page.locator("#edit-applicant").click()
    page.locator("#demo-english-kind").select_option("toefl_ibt")
    assert page.locator("#demo-english-date").input_value() == ""
    assert page.locator("#demo-english-report").input_value() == ""
    assert all(
        page.locator(f"#{control}").input_value() == ""
        for control in ("demo-english-online-pdf", "demo-toeic-qr", "demo-toeic-certificate")
    )
    assert page.locator("#demo-toeic-proof-fields").is_hidden()
    assert page.locator("#demo-toefl-proof-fields").is_visible()
    page.locator("#edit-target").click()
    page.locator("#school-select").select_option("gsfs-complex-2027-a")
    assert page.locator("#demo-english-kind").input_value() == ""
    assert page.locator("#demo-english-date").input_value() == ""
    assert not errors, errors
    assert routed_posts == ["base-requirements", "applicant-comparison"]
    context.close()
    return {
        "width": width,
        "routed_saved_posts": routed_posts,
        "materials_copy_sha256": hashlib.sha256(normalized_copy.encode("utf-8")).hexdigest(),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "journal.json").is_file() and json.loads(
        (OUT / "journal.json").read_text(encoding="utf-8")
    ).get("service_startups", 0) >= 1:
        raise RuntimeError("PREP-01 developer real-service start budget is exhausted")
    assert EDGE.is_file() and RUNTIME.is_dir()
    files = [
        RUNTIME / "corpus.json",
        RUNTIME / "policy.json",
        RUNTIME / "config/reviewed_report_plan.json",
        RUNTIME / "config/page_scope_manifest.json",
        RUNTIME / "config/query_intent_catalog.json",
        RUNTIME / "config/reviewed_date_presentation.json",
        RUNTIME / "documents/isct_2027_4_2026_9_master/document_kb.json",
        RUNTIME / "indexes/isct_2027_4_2026_9_master/manifest.json",
        RUNTIME / "indexes/isct_2027_4_2026_9_master/payloads.jsonl",
        RUNTIME / "indexes/isct_2027_4_2026_9_master/embeddings.npy",
        ROOT / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf",
        ROOT / "outputs/display-01/real-config.json",
    ]
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in files}
    assert before["outputs/real_pdf/isct_2027_4_2026_9_master.pdf"] == (
        "57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735"
    )
    manifest = json.loads(
        (RUNTIME / "indexes/isct_2027_4_2026_9_master/manifest.json").read_text(encoding="utf-8")
    )
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
        source_pdf_document_id=TARGET["document_id"],
        source_pdf_sha256=before["outputs/real_pdf/isct_2027_4_2026_9_master.pdf"],
        reference_workspace_config_path=ROOT / "outputs/display-01/real-config.json",
    )
    journal = {
        "service_startups": 0,
        "base_comparison_posts": 0,
        "gsfs_report_posts": 0,
        "paid_calls": 0,
        "downloads": 0,
        "parser_runs": 0,
        "builds": 0,
        "asset_hashes_before": before,
        "cases": [],
    }
    save("journal.json", journal)
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
    journal["service_startups"] = 1
    journal["port"] = port
    save("journal.json", journal)
    worker.start()
    try:
        started = time.monotonic()
        while not server.started and worker.is_alive() and time.monotonic() - started < 60:
            time.sleep(0.05)
        assert server.started and time.monotonic() - started < 60
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
            context = browser.new_context()
            request = context.request
            base_url = f"http://127.0.0.1:{port}"
            catalog = request.get(f"{base_url}/v1/reference-targets").json()
            save("reference-targets.json", catalog)
            journal["base_comparison_posts"] += 1
            save("journal.json", journal)
            base_response = request.post(f"{base_url}/v1/base-requirements", data=TARGET)
            assert base_response.status == 200
            base = base_response.json()
            save("isct-base.json", base)
            journal["base_comparison_posts"] += 1
            save("journal.json", journal)
            comparison_response = request.post(
                f"{base_url}/v1/applicant-comparison", data=COMPARISON
            )
            assert comparison_response.status == 200
            comparison = comparison_response.json()
            save("isct-comparison.json", comparison)
            for width, label in ((1440, "desktop"), (390, "mobile")):
                journal["cases"].append(
                    browser_case(browser, base_url, catalog, base, comparison, width, label)
                )
                save("journal.json", journal)
            browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
        journal["service_stopped"] = not worker.is_alive()
        journal["asset_hashes_after"] = {
            path.relative_to(ROOT).as_posix(): sha(path) for path in files
        }
        journal["assets_unchanged"] = journal["asset_hashes_after"] == before
        save("journal.json", journal)
    assert journal["service_stopped"] and journal["assets_unchanged"]
    assert journal["base_comparison_posts"] == 2 and journal["gsfs_report_posts"] == 0


if __name__ == "__main__":
    main()
