"""One-command launcher for the reviewed offline applicant demo."""

from __future__ import annotations

import argparse
import importlib.util
import socket
import sys
from pathlib import Path
from typing import Sequence

from .demo import DemoError, DemoRuntime, default_workspace, load_demo_config, prepare_demo
from .demo_embedding import (
    DEMO_PROVIDER_NAMES,
    DemoEmbeddingConfiguration,
    DemoEmbeddingConfigurationError,
    create_demo_embedding_provider,
    demo_embedding_failure_message,
    resolve_demo_embedding_configuration,
)
from .retrieval.embedding import EmbeddingProviderError
from .generation.config import (
    GenerationRuntimeConfiguration,
    add_generation_arguments,
    create_generation_providers,
    resolve_generation_configuration,
)
from .generation.question_analysis import DeterministicQuestionUnderstandingProvider

_HOST = "127.0.0.1"


def _port(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jgrad-demo",
        description="Build and run the reviewed J-Grad applicant demo on this computer.",
    )
    parser.add_argument(
        "--pdf",
        required=True,
        metavar="ABSOLUTE_PATH",
        help="Absolute path to the fixed official Science Tokyo admissions PDF.",
    )
    parser.add_argument(
        "--workspace",
        metavar="ABSOLUTE_PATH",
        help="Absolute generated-artifact directory (default: ./outputs/demo/<document-id>).",
    )
    parser.add_argument("--port", type=_port, default=8000)
    parser.add_argument(
        "--embedding-provider",
        choices=DEMO_PROVIDER_NAMES,
        default="deterministic-fake",
        help="Formal Demo embedding path (default: deterministic-fake).",
    )
    parser.add_argument(
        "--embedding-cache",
        metavar="ABSOLUTE_PATH",
        help="Canonical absolute cache directory for the fixed cache-only BGE-M3 path.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Safely replace this demo's generated runtime after an audit failure or upgrade.",
    )
    add_generation_arguments(parser)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    config_dir: Path | None = None,
) -> None:
    args = _parser().parse_args(argv)
    try:
        _require_service_extra()
        bundle = load_demo_config(config_dir)
        embedding = resolve_demo_embedding_configuration(
            args.embedding_provider,
            args.embedding_cache,
        )
        generation = resolve_generation_configuration(args)
        workspace = Path(args.workspace) if args.workspace else default_workspace(bundle.identity)
        _require_available_port(args.port)
        runtime = prepare_demo(
            Path(args.pdf),
            workspace,
            rebuild=args.rebuild,
            config_dir=config_dir,
            embedding_configuration=embedding,
        )
        if generation == GenerationRuntimeConfiguration():
            _serve(runtime, args.port, embedding)
        else:
            _serve(runtime, args.port, embedding, generation)
    except (DemoEmbeddingConfigurationError, DemoError, ValueError) as error:
        print(f"jgrad-demo: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        print("\nJ-Grad Demo stopped.")


def _require_service_extra() -> None:
    if any(importlib.util.find_spec(name) is None for name in ("fastapi", "uvicorn")):
        raise DemoError(
            'service dependencies are missing; run: python -m pip install -e ".[service]"'
        )


def _require_available_port(port: int) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((_HOST, port))
    except OSError:
        raise DemoError(f"port {port} is already in use; choose another with --port") from None


def _serve(
    runtime: DemoRuntime,
    port: int,
    embedding: DemoEmbeddingConfiguration,
    generation: GenerationRuntimeConfiguration | None = None,
) -> None:
    from .service.app import create_app
    from .service.runtime import ServiceDependencies, ServiceSettings

    try:
        import uvicorn

        generation = generation or GenerationRuntimeConfiguration()
        provider = create_demo_embedding_provider(embedding)
        if provider.identity != runtime.embedding_identity:
            raise ValueError
        settings = ServiceSettings(
            corpus_root=runtime.corpus_root,
            manifest_path=runtime.manifest_path,
            policy_path=runtime.policy_path,
            report_plan_paths=(runtime.report_plan_path,),
            page_scope_manifest_paths=(runtime.page_scope_manifest_path,),
            query_intent_catalog_path=runtime.query_intent_catalog_path,
            date_presentation_paths=(runtime.date_presentation_path,),
            source_pdf_path=runtime.source_pdf_path,
            source_pdf_document_id=runtime.identity.document_id,
            source_pdf_sha256=runtime.identity.source_pdf_sha256,
            generation_provider_name=generation.provider,
            generation_model_name=generation.model,
            generation_timeout_seconds=generation.timeout_seconds,
            generation_max_retries=generation.max_retries,
        )
        app = create_app(
            settings,
            ServiceDependencies(
                provider_factory=lambda: provider,
                generation_provider_factory=lambda: create_generation_providers(generation)[0],
                question_understanding_provider_factory=(
                    DeterministicQuestionUnderstandingProvider
                ),
            ),
        )
    except EmbeddingProviderError as error:
        raise DemoError(demo_embedding_failure_message(embedding, error)) from None
    except (ImportError, ValueError):
        raise DemoError("formal service configuration is unavailable or incompatible") from None

    url = f"http://{_HOST}:{port}/app"
    action = "reused audited" if runtime.reused else "built and audited"
    print(f"J-Grad Demo data: {runtime.identity.document_id}")
    print(f"Official PDF SHA-256: {runtime.identity.source_pdf_sha256}")
    print(f"Workspace: {runtime.workspace}")
    print(f"Artifacts: {action}")
    identity = runtime.embedding_identity
    print(
        "Retrieval: "
        f"provider={identity.provider} model={identity.model} revision={identity.revision or 'none'} "
        f"dimension={identity.dimension} semantic={str(runtime.semantic).lower()}"
    )
    print(
        "Generation: "
        f"provider={generation.provider} model={generation.model or 'reviewed-rules'} "
        f"online={str(generation.is_online).lower()}"
    )
    if not runtime.semantic:
        print("Retrieval quality: offline contract index only; not semantic search quality")
    print(f"Demo URL: {url}")
    print("Stop: press Ctrl+C")
    uvicorn.run(app, host=_HOST, port=port, log_level="info")


if __name__ == "__main__":
    main()
