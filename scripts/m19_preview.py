"""M19 offline preview over original assets; shared developer budgets only."""

from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import socket

import uvicorn
from fastapi.responses import JSONResponse
from jgrad_admission_rag.retrieval.embedding import EmbeddingIdentity
from jgrad_admission_rag.service import create_app
from jgrad_admission_rag.service.runtime import ServiceDependencies, ServiceSettings
from scripts.m18_preview import NoEmbeddingCalls
from scripts.m19_budget import LEDGER, update

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--assets-root", type=Path, required=True)
    args = parser.parse_args()
    assets = args.assets_root.resolve()
    checked = json.loads(LEDGER.read_bytes())
    if checked["worktree"].replace("\\", "/") != str(ROOT).replace("\\", "/"):
        raise ValueError("M19 worktree owner mismatch")
    update(
        "reserve developer offline service start",
        resource="service_starts",
        pid=os.getpid(),
        worktree=str(ROOT),
    )
    runtime = assets / "outputs/m10-09-deepseek-live/runtime-v1"
    manifest = json.loads(
        (runtime / "indexes/isct_2027_4_2026_9_master/manifest.json").read_bytes()
    )
    identity = EmbeddingIdentity(
        *(
            manifest[k]
            for k in (
                "embedding_provider",
                "embedding_model",
                "embedding_revision",
                "embedding_dimension",
            )
        )
    )
    settings = ServiceSettings(
        corpus_root=runtime,
        manifest_path=runtime / "corpus.json",
        policy_path=runtime / "policy.json",
        report_plan_paths=(runtime / "config/reviewed_report_plan.json",),
        page_scope_manifest_paths=(runtime / "config/page_scope_manifest.json",),
        query_intent_catalog_path=runtime / "config/query_intent_catalog.json",
        date_presentation_paths=(runtime / "config/reviewed_date_presentation.json",),
        exam_presentation_paths=(
            ROOT / "src/jgrad_admission_rag/demo_config/reviewed_exam_presentation.json",
        ),
        exam_presentation_v2_path=ROOT
        / "src/jgrad_admission_rag/demo_config/exam02b_source_bindings.json",
        source_pdf_path=assets / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf",
        source_pdf_document_id="isct_2027_4_2026_9_master",
        source_pdf_sha256="57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735",
        reference_workspace_config_path=args.config.resolve(),
        generation_provider_name="reviewed-state-offline",
    )
    app = create_app(
        settings, ServiceDependencies(provider_factory=lambda: NoEmbeddingCalls(identity))
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    session = dict(
        pid=os.getpid(),
        port=listener.getsockname()[1],
        config=str(args.config.resolve()),
        worktree=str(ROOT),
        started_utc=datetime.now(timezone.utc).isoformat(),
        role="developer",
    )
    update("offline listener ready", **session)
    (LEDGER.parent / "service.json").write_text(
        json.dumps(session, indent=2) + "\n", encoding="utf-8"
    )

    @app.middleware("http")
    async def count(request, call_next):
        if request.method == "POST":
            try:
                update("product POST attempt", resource="posts", path=request.url.path)
            except ValueError:
                return JSONResponse({"code": "m19_budget_exhausted"}, status_code=429)
        response = await call_next(request)
        update(
            "HTTP response",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
        )
        return response

    print(
        f"M19 isolated offline preview http://127.0.0.1:{session['port']}/app/advanced", flush=True
    )
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on")).run(
            sockets=[listener]
        )
    finally:
        update("developer service stopped", pid=os.getpid())


if __name__ == "__main__":
    main()
