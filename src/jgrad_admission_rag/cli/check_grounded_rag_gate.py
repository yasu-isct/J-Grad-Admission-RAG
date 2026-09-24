from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from ..evaluation.grounded_rag_evaluation import (
    GroundedRagEvaluationError,
    canonical_grounded_rag_gate_result_bytes,
    evaluate_grounded_rag_gate,
    load_grounded_rag_observations_bytes,
    load_grounded_rag_policy_bytes,
    load_grounded_rag_report_bytes,
    load_grounded_rag_suite_bytes,
    load_retrieval_benchmark_bytes,
    read_regular_file_bytes,
)
from ..evaluation.retrieval_evaluation import (
    EvaluationReportError,
    load_retrieval_evaluation_bytes,
)
from ..evaluation.semantic_gate import ImplementationContractError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the offline grounded-RAG release baseline without model or API access."
    )
    parser.add_argument("--suite", required=True, help="Canonical reviewed query suite JSON.")
    parser.add_argument(
        "--observations", required=True, help="Canonical server-hydrated observation JSON."
    )
    parser.add_argument(
        "--retrieval-report", required=True, help="Canonical pinned semantic report JSON."
    )
    parser.add_argument(
        "--retrieval-benchmark", required=True, help="Canonical reviewed retrieval benchmark JSON."
    )
    parser.add_argument("--report", required=True, help="Canonical grounded release report JSON.")
    parser.add_argument("--policy", required=True, help="Canonical grounded release policy JSON.")
    parser.add_argument(
        "--repository-root",
        required=True,
        help="Repository root used to verify the bound implementation contract.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        suite = load_grounded_rag_suite_bytes(read_regular_file_bytes(args.suite, label="suite"))
        observations = load_grounded_rag_observations_bytes(
            read_regular_file_bytes(args.observations, label="observations")
        )
        retrieval_report = load_retrieval_evaluation_bytes(
            read_regular_file_bytes(args.retrieval_report, label="retrieval report")
        )
        retrieval_benchmark = load_retrieval_benchmark_bytes(
            read_regular_file_bytes(args.retrieval_benchmark, label="retrieval benchmark")
        )
        report = load_grounded_rag_report_bytes(
            read_regular_file_bytes(args.report, label="report")
        )
        policy = load_grounded_rag_policy_bytes(
            read_regular_file_bytes(args.policy, label="policy")
        )
        result = evaluate_grounded_rag_gate(
            policy,
            suite,
            observations,
            retrieval_report,
            retrieval_benchmark,
            report,
            args.repository_root,
        )
    except (
        GroundedRagEvaluationError,
        EvaluationReportError,
        ImplementationContractError,
    ) as error:
        print(
            json.dumps(
                {"error": str(error), "kind": "grounded_rag_gate_error"},
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    sys.stdout.write(canonical_grounded_rag_gate_result_bytes(result).decode("utf-8"))
    raise SystemExit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
