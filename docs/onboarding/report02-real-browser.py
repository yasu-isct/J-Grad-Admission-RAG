"""Bounded REPORT-02 real-service browser check; run once after synthetic checks.

Uses the existing 391 runtime and GSFS config read-only, with an identity-only
embedding provider. No retrieval, model generation, download, or indexing.
"""

from __future__ import annotations

import hashlib
import ctypes
import json
import os
import socket
import sys
import time
from pathlib import Path
from threading import Thread

TREE = Path(__file__).resolve().parents[2]
ROOT = Path(r"D:\J-Grad-Admission-RAG")
SAVED = ROOT / "outputs/ui02-real/final-head-cd09bd4"
OUT = TREE / "docs/onboarding/report02-evidence"
RUNTIME = ROOT / "outputs/m10-09-deepseek-live/runtime-v1"
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
        raise RuntimeError("REPORT-02 forbids embedding builds")

    def embed_query(self, _text):
        raise RuntimeError("REPORT-02 forbids retrieval")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ulong),
        ("load", ctypes.c_ulong),
        ("total_physical", ctypes.c_ulonglong),
        ("available_physical", ctypes.c_ulonglong),
        ("total_page_file", ctypes.c_ulonglong),
        ("available_page_file", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong),
        ("available_virtual", ctypes.c_ulonglong),
        ("available_extended", ctypes.c_ulonglong),
    ]


class ProcessMemory(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_ulong),
        ("page_faults", ctypes.c_ulong),
        ("peak_working_set", ctypes.c_size_t),
        ("working_set", ctypes.c_size_t),
        ("peak_pagefile", ctypes.c_size_t),
        ("pagefile", ctypes.c_size_t),
        ("peak_nonpaged_pool", ctypes.c_size_t),
        ("nonpaged_pool", ctypes.c_size_t),
        ("peak_paged_pool", ctypes.c_size_t),
        ("paged_pool", ctypes.c_size_t),
    ]


def memory():
    system = MemoryStatus()
    system.length = ctypes.sizeof(system)
    assert ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(system))
    process = ProcessMemory()
    process.size = ctypes.sizeof(process)
    getter = ctypes.windll.psapi.GetProcessMemoryInfo
    getter.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    current = ctypes.windll.kernel32.GetCurrentProcess
    current.restype = ctypes.c_void_p
    assert getter(current(), ctypes.byref(process), process.size)
    assert system.available_physical >= 4 * 1024**3 and process.working_set < 12 * 1024**3
    return {"available": system.available_physical, "rss": process.working_set}


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def choose(page, entry):
    if not page.locator("#school-select").is_visible():
        page.locator("#edit-target").click()
    if entry["kind"] == "legacy_applicant":
        school = entry["legacy_catalog"]
        intake = next(
            x for x in school["degrees"][0]["intakes"] if (x["year"], x["month"]) == (2027, 4)
        )
        college = intake["colleges"][0]
        department = college["departments"][0]
        page.locator("#school-select").select_option(school["school_id"])
        page.locator("#demo-degree-select").select_option(school["degrees"][0]["degree_id"])
        page.locator("#intake-select").select_option(
            f"{intake['document_id']}:{intake['year']}:{intake['month']}"
        )
        page.locator("#college-select").select_option(college["college_id"])
        page.locator("#department-select").select_option(department["department_id"])
    else:
        target = entry["target"]
        page.locator("#school-select").select_option(entry["entry_id"])
        page.locator("#demo-degree-select").select_option(target["degree_level"])
        page.locator("#intake-select").select_option(
            f"null:{target['intake']['year']}:{target['intake']['month']}"
        )
        for selector in ("#college-select", "#department-select", "#route-select"):
            if page.locator(selector).is_visible():
                page.locator(selector).select_option(index=1)


def main():
    assert EDGE.is_file() and SAVED.is_dir() and RUNTIME.is_dir()
    baseline = read(ROOT / "outputs/display-01/real-before.json")
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
    before = {name: digest(ROOT / name) for name in protected}
    assert all(before[name] == row["sha256"] for name, row in baseline.items())
    manifest = read(RUNTIME / "indexes/isct_2027_4_2026_9_master/manifest.json")
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
    previous = (
        read(OUT / "browser-journal.json") if (OUT / "browser-journal.json").is_file() else {}
    )
    previous_startups = previous.get("service_startups", 0)
    assert previous_startups < 2
    journal = {
        "service_startups": previous.get("service_startups", 0),
        "report_attempts": previous.get("report_attempts", 0),
        "base_comparison_posts": previous.get("base_comparison_posts", 0),
        "other_posts": 0,
        "paid_calls": 0,
        "cases": [],
        "previous_attempt": {
            key: previous.get(key)
            for key in ("service_startups", "report_attempts", "base_comparison_posts")
        },
        "protected_hashes_before": before,
        "memory_before": memory(),
    }
    save("browser-journal.json", journal)
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
    save("browser-journal.json", journal)
    worker.start()
    try:
        started = time.monotonic()
        while not server.started and worker.is_alive() and time.monotonic() - started < 300:
            time.sleep(0.05)
        assert server.started and time.monotonic() - started < 300
        journal["memory_after_startup"] = memory()
        save("browser-journal.json", journal)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(EDGE))
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                permissions=["clipboard-read", "clipboard-write"],
            )
            page = context.new_page()
            page.set_default_timeout(30000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            assert page.goto(f"http://127.0.0.1:{port}/app").status == 200
            entries = context.request.get(f"http://127.0.0.1:{port}/v1/reference-targets").json()[
                "items"
            ]
            assert len(entries) == 2
            legacy = next(x for x in entries if x["kind"] == "legacy_applicant")
            slice_entry = next(x for x in entries if x["kind"] == "reviewed_material_slice")

            def post(selector, suffix, expected_file, report=False):
                journal["report_attempts" if report else "base_comparison_posts"] += 1
                assert journal["report_attempts"] <= 8 and journal["base_comparison_posts"] <= 12
                save("browser-journal.json", journal)
                with page.expect_response(
                    lambda r: r.request.method == "POST" and r.url.endswith(suffix), timeout=60000
                ) as hit:
                    page.locator(selector).click()
                assert hit.value.status == 200
                response = hit.value.json()
                assert response == read(SAVED / expected_file), expected_file
                return response

            def capture(name, selector, expected_copy, required, forbidden):
                journal["report_attempts"] += 1
                assert journal["report_attempts"] <= 8
                save("browser-journal.json", journal)
                page.locator(selector).click()
                page.locator("#reference-report").wait_for(state="visible")
                body = page.locator("#reference-report-body").inner_text()
                for phrase in required:
                    assert phrase in body, (name, phrase)
                for phrase in forbidden:
                    assert phrase not in body, (name, phrase)
                page.locator("#reference-copy").click()
                page.get_by_text("已复制当前选中的简洁报告。").wait_for()
                copied = page.evaluate("navigator.clipboard.readText()").replace("\r\n", "\n")
                expected = (OUT / expected_copy).read_text(encoding="utf-8").replace("\r\n", "\n")
                assert copied + "\n" == expected
                page.screenshot(path=str(OUT / f"{name}-desktop.png"), full_page=False)
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(OUT / f"{name}-mobile.png"), full_page=False)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), name
                page.set_viewport_size({"width": 1440, "height": 900})
                journal["cases"].append(
                    {
                        "name": name,
                        "copied_sha256": hashlib.sha256(copied.encode()).hexdigest(),
                        "copied_length": len(copied),
                        "no_horizontal_overflow": True,
                    }
                )
                save("browser-journal.json", journal)
                page.locator("#reference-close").click()

            choose(page, legacy)
            post("#requirements-submit", "/v1/base-requirements", "isct-base-2027.json")
            if previous_startups == 0:
                capture(
                    "isct-no-profile",
                    "#step-2-panel .reference-generate",
                    "isct-no-profile-after-copy.txt",
                    ["未填写准备情况", "关键时间"],
                    ["物理页", "官方原文：", "record_id"],
                )
            page.locator(".overview-cta").click()
            page.locator("#demo-credential-basis").select_option("ui_unknown")
            page.locator('[data-material-code="address_label"]').select_option("available")
            page.locator('[data-material-code="application_form"]').select_option("not_yet")
            post("#comparison-submit", "/v1/applicant-comparison", "isct-comparison.json")
            capture(
                "isct-with-profile",
                "#readiness-panel .reference-generate",
                "isct-with-profile-after-copy.txt",
                ["待补材料", "已自报准备", "待确认适用"],
                ["物理页", "官方原文：", "record_id"],
            )
            choose(page, slice_entry)
            with page.expect_response(lambda r: r.url.endswith("/evidence"), timeout=60000) as hit:
                page.locator("#requirements-submit").click()
            assert hit.value.status == 200 and hit.value.json() == read(
                SAVED / "gsfs-evidence.json"
            )
            page.locator(".overview-cta").click()
            for current, retain, name, filename, required in (
                ("unknown", "unknown", "gsfs-unknown", "gsfs-unknown-unknown.json", "待确认适用"),
                ("yes", "yes", "gsfs-required", "gsfs-yes-yes.json", "需要准备，完成情况未填写"),
                ("no", "unknown", "gsfs-inapplicable", "gsfs-no-unknown.json", "本条条件不适用"),
            ):
                if not page.locator("#slice-current-employed").is_visible():
                    page.locator("#edit-applicant").click()
                page.locator("#slice-current-employed").select_option(current)
                page.locator("#slice-retain-employed").select_option(retain)
                post("#comparison-submit", "/reports", filename, report=True)
                count = journal["report_attempts"]
                capture(
                    name,
                    "#readiness-panel .reference-generate",
                    f"{name}-after-copy.txt",
                    [required, "材料准备清单"],
                    ["物理页", "# 原始报告", "record_id"],
                )
                assert journal["report_attempts"] == count + 1
            assert not errors, errors
            browser.close()
        journal["memory_after_browser"] = memory()
        journal["protected_hashes_after"] = {name: digest(ROOT / name) for name in protected}
        assert journal["protected_hashes_after"] == before
        expected = (1, 8, 2, 0, 0) if previous_startups == 0 else (2, 8, 3, 0, 0)
        assert (
            journal["service_startups"],
            journal["report_attempts"],
            journal["base_comparison_posts"],
            journal["other_posts"],
            journal["paid_calls"],
        ) == expected
        journal["status"] = "passed"
        save("browser-journal.json", journal)
    finally:
        server.should_exit = True
        worker.join(timeout=15)
        listener.close()
        journal["service_stopped"] = not worker.is_alive()
        save("browser-journal.json", journal)


if __name__ == "__main__":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    main()
