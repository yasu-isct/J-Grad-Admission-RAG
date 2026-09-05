"""Command-line launcher for the optional local HTTP service."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from ..cli.provider_config import (
    CliConfigurationError,
    add_provider_arguments,
    create_provider,
    resolve_provider_configuration,
)
from .app import create_app
from .runtime import ServiceDependencies, ServiceSettings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local, versioned J-Grad Admission RAG HTTP API."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--corpus-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument(
        "--report-plan",
        action="append",
        default=[],
        metavar="ABSOLUTE_PATH",
        help="Reviewed report plan JSON path; repeat for each explicitly enabled document.",
    )
    parser.add_argument("--max-pdf-bytes", type=int, default=25 * 1024 * 1024)
    parser.add_argument("--job-root")
    parser.add_argument("--job-worker-max-active", type=int, default=1)
    parser.add_argument("--job-shutdown-grace-seconds", type=float, default=0.25)
    add_provider_arguments(parser)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if (
        not 1 <= args.port <= 65535
        or args.max_pdf_bytes <= 0
        or not 1 <= args.job_worker_max_active <= 8
        or not 0 <= args.job_shutdown_grace_seconds <= 60
    ):
        _parser().error("port, upload, worker concurrency, or shutdown grace is out of range")
    try:
        provider_configuration = resolve_provider_configuration(args)
        report_plan_paths = tuple(Path(path) for path in args.report_plan)
        if any(not path.is_absolute() for path in report_plan_paths):
            raise ValueError("reviewed report plan paths must be absolute")
        settings = ServiceSettings(
            corpus_root=Path(args.corpus_root).resolve(strict=False),
            manifest_path=Path(args.manifest).resolve(strict=False),
            policy_path=Path(args.policy).resolve(strict=False),
            report_plan_paths=tuple(path.resolve(strict=False) for path in report_plan_paths),
            max_pdf_bytes=args.max_pdf_bytes,
            job_root=(Path(args.job_root).resolve(strict=False) if args.job_root else None),
            job_worker_max_active=args.job_worker_max_active,
            job_shutdown_grace_seconds=args.job_shutdown_grace_seconds,
        )
    except (CliConfigurationError, ValueError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        raise SystemExit(2) from None

    app = create_app(
        settings,
        ServiceDependencies(provider_factory=lambda: create_provider(provider_configuration)),
    )
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
