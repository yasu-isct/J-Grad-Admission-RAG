"""Explicit offline preview over original assets, with persistent #285 developer quotas."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket

import uvicorn
from fastapi.responses import JSONResponse

from jgrad_admission_rag.retrieval.embedding import EmbeddingIdentity
from jgrad_admission_rag.service import create_app
from jgrad_admission_rag.service.runtime import ServiceDependencies, ServiceSettings


ROOT = Path(__file__).resolve().parents[1]


class NoEmbeddingCalls:
    def __init__(self, identity):
        self.identity = identity

    def embed_documents(self, texts):
        raise RuntimeError("embedding is outside M18")

    def embed_query(self, text):
        raise RuntimeError("retrieval/model calls are outside M18")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--assets-root", type=Path, required=True)
    parser.add_argument(
        "--role",
        choices=("developer", "design"),
        default="developer",
        help="Design reserve is for the independent design Agent only",
    )
    args = parser.parse_args()
    assets = args.assets_root.resolve()
    # Fixed cumulative ledger in the shared original root, never in a new worktree.
    journal = assets / "outputs/m18-audit/budget.json"
    rows = json.loads(journal.read_bytes())
    role = args.role
    start_key, post_key = f"{role}_starts", f"{role}_posts"
    post_limit = 4 if role == "developer" else 2
    assert rows[start_key] < 1, f"M18 {role} start budget exhausted"
    runtime = assets / "outputs/m10-09-deepseek-live/runtime-v1"
    manifest = json.loads(
        (runtime / "indexes/isct_2027_4_2026_9_master/manifest.json").read_bytes()
    )
    identity = EmbeddingIdentity(
        *(
            manifest[field]
            for field in (
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
    row = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "port": listener.getsockname()[1],
        "config": str(args.config.resolve()),
        "worktree": str(ROOT),
        "offline": True,
        "role": role,
        "gets": [],
        "posts": [],
    }
    rows[start_key] += 1
    rows["sessions"].append(row)

    def save():
        journal.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()

    @app.middleware("http")
    async def record_requests(request, call_next):
        attempt = {"at_utc": datetime.now(timezone.utc).isoformat(), "path": request.url.path}
        if request.method == "POST":
            if rows[post_key] >= post_limit:
                return JSONResponse({"code": "m18_budget_exhausted"}, status_code=429)
            rows[post_key] += 1  # count before execution, including failed attempts
            row["posts"].append(attempt)
        else:
            row["gets"].append(attempt)
        save()
        response = await call_next(request)
        attempt["status"] = response.status_code
        save()
        return response

    print(f"M18 isolated offline preview http://127.0.0.1:{row['port']}/app/advanced", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on")).run(
            sockets=[listener]
        )
    finally:
        row["stopped_utc"] = datetime.now(timezone.utc).isoformat()
        save()


if __name__ == "__main__":
    main()
