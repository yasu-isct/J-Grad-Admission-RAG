from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from ..evaluation.retrieval_evaluation import (
    EvaluationReportError,
    load_retrieval_evaluation_bytes,
)
from ..evaluation.semantic_gate import (
    ImplementationContractError,
    SemanticGateError,
    baseline_privacy_violations,
    canonical_semantic_gate_manifest_bytes,
    canonical_semantic_gate_policy_bytes,
    canonical_semantic_gate_result_bytes,
    evaluate_semantic_gate,
    load_semantic_gate_manifest_bytes,
    load_semantic_gate_policy_bytes,
    read_regular_file_bytes,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the frozen semantic retrieval baseline without loading a model or index."
    )
    parser.add_argument("--report", required=True, help="Canonical compact semantic baseline JSON.")
    parser.add_argument("--policy", required=True, help="Canonical semantic gate policy JSON.")
    parser.add_argument("--manifest", required=True, help="Canonical implementation contract JSON.")
    parser.add_argument(
        "--repository-root",
        default=".",
        help="Repository root containing the frozen benchmark and implementation contract.",
    )
    return parser


def _write_error(kind: str, message: str) -> None:
    print(
        json.dumps({"error": message, "kind": kind}, ensure_ascii=True, separators=(",", ":")),
        file=sys.stderr,
    )


def _canonical_or_error(raw_bytes: bytes, expected: bytes, label: str) -> None:
    if raw_bytes != expected:
        raise SemanticGateError(f"{label} must use canonical JSON bytes")


def _benchmark_queries(raw_bytes: bytes) -> tuple[str, ...]:
    try:
        value = json.loads(raw_bytes.decode("utf-8"))
        queries = value["queries"]
        if not isinstance(queries, list):
            raise ValueError("queries is not a list")
        values = tuple(item["query"] for item in queries)
        if not all(isinstance(item, str) for item in values):
            raise ValueError("query is not a string")
        return values
    except (UnicodeDecodeError, TypeError, KeyError, ValueError, json.JSONDecodeError) as error:
        raise SemanticGateError("frozen benchmark queries are invalid") from error


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        root = Path(args.repository_root)
        benchmark_bytes = read_regular_file_bytes(
            root / "tests" / "fixtures" / "retrieval_queries_v1.json",
            label="frozen benchmark",
        )
        report_bytes = read_regular_file_bytes(args.report, label="report")
        policy_bytes = read_regular_file_bytes(args.policy, label="policy")
        manifest_bytes = read_regular_file_bytes(args.manifest, label="manifest")
        report = load_retrieval_evaluation_bytes(report_bytes)
        policy = load_semantic_gate_policy_bytes(policy_bytes)
        manifest = load_semantic_gate_manifest_bytes(manifest_bytes)
        _canonical_or_error(policy_bytes, canonical_semantic_gate_policy_bytes(policy), "policy")
        _canonical_or_error(
            manifest_bytes, canonical_semantic_gate_manifest_bytes(manifest), "manifest"
        )
        violations = baseline_privacy_violations(report_bytes, _benchmark_queries(benchmark_bytes))
        if violations:
            raise SemanticGateError("compact baseline violates the privacy policy")
        result = evaluate_semantic_gate(
            report,
            policy,
            manifest,
            root,
            report_sha256=_sha256(report_bytes),
            policy_sha256=_sha256(policy_bytes),
            benchmark_sha256=_sha256(benchmark_bytes),
        )
    except (EvaluationReportError, SemanticGateError, ImplementationContractError) as error:
        _write_error("semantic_gate_error", str(error))
        raise SystemExit(2) from None

    sys.stdout.write(canonical_semantic_gate_result_bytes(result).decode("utf-8"))
    raise SystemExit(0 if result.passed else 1)


def _sha256(raw_bytes: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw_bytes).hexdigest()


if __name__ == "__main__":
    main()
