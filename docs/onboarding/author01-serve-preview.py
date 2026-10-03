"""Opt-in AUTHOR-01 real offline preview using original assets, no model calls.

Run once from the isolated worktree; stop only this process with Ctrl+C.
The normal user preview and all old asset/configuration paths stay untouched.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import socket

import uvicorn

from jgrad_admission_rag.retrieval.embedding import EmbeddingIdentity
from jgrad_admission_rag.service import create_app
from jgrad_admission_rag.service.runtime import ServiceDependencies, ServiceSettings


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/onboarding/author01-evidence"
ASSETS = Path("D:/J-Grad-Admission-RAG")
RUNTIME = ASSETS / "outputs/m10-09-deepseek-live/runtime-v1"


class NoEmbeddingCalls:
    """Use the retained index identity; this material journey needs no embedding."""

    def __init__(self, identity):
        self.identity = identity

    def embed_documents(self, texts):
        raise RuntimeError("embedding is outside AUTHOR-01")

    def embed_query(self, text):
        raise RuntimeError("retrieval/model calls are outside AUTHOR-01")


def main() -> None:
    path = OUT / "service-journal.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    assert len(rows) < 2, "AUTHOR-01 developer startup budget exhausted"
    manifest = json.loads(
        (RUNTIME / "indexes/isct_2027_4_2026_9_master/manifest.json").read_bytes()
    )
    identity = EmbeddingIdentity(
        *(
            manifest[name]
            for name in (
                "embedding_provider",
                "embedding_model",
                "embedding_revision",
                "embedding_dimension",
            )
        )
    )
    config = ROOT / "docs/onboarding/author01-reference-workspace-preview-v2.json"
    settings = ServiceSettings(
        corpus_root=RUNTIME,
        manifest_path=RUNTIME / "corpus.json",
        policy_path=RUNTIME / "policy.json",
        report_plan_paths=(RUNTIME / "config/reviewed_report_plan.json",),
        page_scope_manifest_paths=(RUNTIME / "config/page_scope_manifest.json",),
        query_intent_catalog_path=RUNTIME / "config/query_intent_catalog.json",
        date_presentation_paths=(RUNTIME / "config/reviewed_date_presentation.json",),
        exam_presentation_paths=(
            ROOT / "src/jgrad_admission_rag/demo_config/reviewed_exam_presentation.json",
        ),
        exam_presentation_v2_path=ROOT
        / "src/jgrad_admission_rag/demo_config/exam02b_source_bindings.json",
        source_pdf_path=ASSETS / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf",
        source_pdf_document_id="isct_2027_4_2026_9_master",
        source_pdf_sha256="57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735",
        reference_workspace_config_path=config,
        generation_provider_name="reviewed-state-offline",
    )
    app = create_app(
        settings, ServiceDependencies(provider_factory=lambda: NoEmbeddingCalls(identity))
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    row = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "port": port,
        "config": str(config),
        "offline": True,
        "product_post_attempts": [],
    }
    rows.append(row)

    def save():
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()

    @app.middleware("http")
    async def record_posts(request, call_next):
        if request.method == "POST":
            assert sum(len(r["product_post_attempts"]) for r in rows) < 16
            attempt = {"at_utc": datetime.now(timezone.utc).isoformat(), "path": request.url.path}
            row["product_post_attempts"].append(attempt)
            save()
            response = await call_next(request)
            attempt["status"] = response.status_code
            save()
            return response
        return await call_next(request)

    print(f"AUTHOR-01 isolated offline preview: http://127.0.0.1:{port}/app/advanced", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on")).run(
            sockets=[listener]
        )
    finally:
        row["stopped_utc"] = datetime.now(timezone.utc).isoformat()
        save()


if __name__ == "__main__":
    main()
