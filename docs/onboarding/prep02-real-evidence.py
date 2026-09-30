"""One bounded PREP-02 service session over existing read-only assets."""

# ruff: noqa: E402 -- bind this checkout's source, not another editable worktree.

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
OUT = TREE / "docs/onboarding/prep02-evidence"
sys.path.insert(0, str(TREE / "src"))

import uvicorn
from playwright.sync_api import sync_playwright
from jgrad_admission_rag.retrieval.embedding import EmbeddingIdentity
from jgrad_admission_rag.service import create_app
from jgrad_admission_rag.service.runtime import ServiceDependencies, ServiceSettings


class IdentityOnlyEmbedding:
    def __init__(self, identity):
        self.identity = identity

    def embed_documents(self, _texts):
        raise RuntimeError("PREP-02 prohibits index builds")

    def embed_query(self, _text):
        raise RuntimeError("PREP-02 prohibits retrieval")


TARGET = {
    "school_id": "isct",
    "document_id": "isct_2027_4_2026_9_master",
    "degree_id": "master",
    "intake": {"year": 2027, "month": 4},
    "college_id": "情報理工学院",
    "department_id": "情報工学系",
    "application_route": "b_schedule",
}
SCENARIOS = {
    "dispatched_unknown_arrival": {
        "target": TARGET,
        "applicant": {"credential_basis": "university_graduation", "completion_state": "expected"},
        "english_preparation": {},
        "application_preparation": {
            "expected_completion_date": "2027-03-20",
            "materials_dispatched_date": "2026-06-09",
            "materials_arrival_date": None,
            "online_steps_completed": True,
        },
    },
    "late_graduation_arrival": {
        "target": TARGET,
        "applicant": {"credential_basis": "university_graduation", "completion_state": "expected"},
        "english_preparation": {},
        "application_preparation": {
            "expected_completion_date": "2027-04-10",
            "materials_dispatched_date": "2026-06-09",
            "materials_arrival_date": "2026-06-10",
            "online_steps_completed": False,
        },
    },
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save(name: str, value) -> None:
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "journal.json").is_file():
        raise RuntimeError("PREP-02 real-service session is already recorded")
    paths = [
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
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}
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
        "case_http_statuses": {},
    }
    save("journal.json", journal)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    app = create_app(
        settings,
        ServiceDependencies(
            provider_factory=lambda: IdentityOnlyEmbedding(identity),
        ),
    )
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="on",
        )
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
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            )
            request = browser.new_context().request
            url = f"http://127.0.0.1:{port}"
            catalog = request.get(f"{url}/v1/reference-targets")
            assert catalog.status == 200
            save("reference-targets.json", catalog.json())
            journal["base_comparison_posts"] += 1
            save("journal.json", journal)
            base = request.post(f"{url}/v1/base-requirements", data=TARGET)
            journal["case_http_statuses"]["base"] = base.status
            save("journal.json", journal)
            assert base.status == 200, base.text()
            save("base.json", base.json())
            for name, payload in SCENARIOS.items():
                journal["base_comparison_posts"] += 1
                save("journal.json", journal)
                save(f"{name}-request.json", payload)
                response = request.post(f"{url}/v1/applicant-comparison", data=payload)
                journal["case_http_statuses"][name] = response.status
                save("journal.json", journal)
                assert response.status == 200, response.text()
                save(f"{name}-response.json", response.json())
            browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
        journal["service_stopped"] = not worker.is_alive()
        journal["asset_hashes_after"] = {
            path.relative_to(ROOT).as_posix(): sha(path) for path in paths
        }
        journal["assets_unchanged"] = journal["asset_hashes_after"] == before
        save("journal.json", journal)
    assert journal["service_stopped"] and journal["assets_unchanged"]
    assert journal["base_comparison_posts"] == 3 and journal["gsfs_report_posts"] == 0


if __name__ == "__main__":
    main()
