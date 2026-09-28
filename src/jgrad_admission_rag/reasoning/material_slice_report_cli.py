"""Local, pinned three-topic teacher-reference report; no asset mutation."""

from __future__ import annotations

import argparse
from pathlib import Path
import stat
import sys

from ..reviewed_source_evidence import canonical_json_bytes
from .material_conditions import evaluate, load_request
from .material_slice_report import (
    MaterialSliceError,
    assemble_report,
    load_plan,
    read_candidate_files,
    read_pdf_bytes,
    render_markdown,
    verify_evidence_bytes,
)


def _read_explicit_file(path: Path) -> bytes:
    current = path.absolute()
    while True:
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            raise MaterialSliceError("input path is unsafe")
        if current == current.parent:
            break
        current = current.parent
    if not stat.S_ISREG(path.stat().st_mode):
        raise MaterialSliceError("input must be a regular file")
    return path.read_bytes()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("plan", "trust", "policy", "policy-trust", "seed", "candidate-root", "pdf-dir"):
        parser.add_argument(f"--{flag}", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path, action="append")
    parser.add_argument("--format", choices=("jsonl", "markdown"), default="jsonl")
    args = parser.parse_args(argv)
    try:
        if args.format == "markdown" and len(args.request) != 1:
            raise MaterialSliceError("markdown accepts one request")
        plan, policy, seed, plan_sha, policy_sha = load_plan(
            _read_explicit_file(args.plan),
            _read_explicit_file(args.trust),
            _read_explicit_file(args.policy),
            _read_explicit_file(args.policy_trust),
            _read_explicit_file(args.seed),
        )
        requests = [load_request(_read_explicit_file(path)) for path in args.request]
        covered = any(
            evaluate(policy, request, policy_sha).status == "evaluated" for request in requests
        )
        evidence = (
            verify_evidence_bytes(
                plan,
                policy,
                seed,
                plan_sha256=plan_sha,
                policy_sha256=policy_sha,
                candidate_files=read_candidate_files(args.candidate_root, plan),
                pdf_bytes=read_pdf_bytes(args.pdf_dir, plan),
            )
            if covered
            else None
        )
        encoded = []
        for request in requests:
            report = assemble_report(
                plan,
                policy,
                request,
                plan_sha256=plan_sha,
                policy_sha256=policy_sha,
                evidence=evidence,
            )
            markdown = render_markdown(report)
            raw = (
                markdown.encode("utf-8")
                if args.format == "markdown"
                else canonical_json_bytes(
                    {"report": report.model_dump(mode="json"), "markdown": markdown}
                )
            )
            if len(raw) > 512 * 1024:
                raise MaterialSliceError("report exceeds size bound")
            encoded.append(raw)
        if sum(map(len, encoded)) > 2 * 1024 * 1024:
            raise MaterialSliceError("batch exceeds size bound")
    except (OSError, ValueError, TypeError):
        sys.stderr.buffer.write(canonical_json_bytes({"status": "invalid_report_input"}))
        return 2
    for raw in encoded:
        sys.stdout.buffer.write(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
