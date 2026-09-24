"""Explicitly authorized paid provider-contract evaluation over synthetic inputs only."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Sequence

from ..evaluation.grounded_rag_evaluation import (
    load_grounded_rag_suite_bytes,
    read_regular_file_bytes,
)
from ..generation.contracts import (
    GENERATION_PROMPT_VERSION,
    GenerationEvidence,
    GenerationRequest,
    GenerationRuleFinding,
    GenerationTarget,
)
from ..generation.openai_responses import OpenAIResponsesConfig, OpenAIResponsesGenerationProvider
from ..generation.provider import GenerationError, generate_checked

_AUTHORIZATION = "I AUTHORIZE 20 PAID SYNTHETIC CALLS"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run bounded paid structured-generation checks with synthetic evidence labels only."
        )
    )
    parser.add_argument("--suite", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-cases", required=True, type=int, choices=(1, 5, 10, 20))
    parser.add_argument("--synthetic-only", required=True, action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if os.environ.get("JGRAD_ALLOW_PAID_EVALUATION") != _AUTHORIZATION:
        _fail("paid evaluation lacks the exact one-run authorization guard")
    if not os.environ.get("OPENAI_API_KEY"):
        _fail("paid evaluation credential is unavailable")
    try:
        suite = load_grounded_rag_suite_bytes(read_regular_file_bytes(args.suite, label="suite"))
        provider = OpenAIResponsesGenerationProvider(
            OpenAIResponsesConfig(
                model=args.model,
                timeout_seconds=30,
                max_output_tokens=2_000,
                max_retries=0,
            )
        )
        selected = tuple(case for case in suite.cases if case.expected_disposition != "refused")[
            : args.max_cases
        ]
        passed = 0
        for index, case in enumerate(selected, start=1):
            evidence_ids = tuple(
                f"evidence:{evidence_index:04d}"
                for evidence_index in range(1, len(case.expected_evidence) + 1)
            )
            status = (
                "needs_information"
                if case.expected_disposition == "needs_information"
                else "confirmed"
            )
            request = GenerationRequest(
                request_id=f"manual:{index:04d}",
                question=case.question,
                target=GenerationTarget(application_label="Synthetic reviewed target"),
                rule_findings=(
                    GenerationRuleFinding(
                        finding_id=f"finding:manual-{index:04d}",
                        status=status,
                        statement=(
                            "Synthetic reviewed-state fixture; preserve the supplied status and "
                            "do not infer eligibility, receipt, completeness, or admission."
                        ),
                        evidence_ids=evidence_ids,
                        missing_fields=case.expected_missing_fields,
                    ),
                ),
                evidence=tuple(
                    GenerationEvidence(
                        evidence_id=evidence_id,
                        role="primary",
                        text=(
                            "Synthetic official-evidence placeholder for provider contract "
                            f"evaluation item {evidence_index}."
                        ),
                        scope_label="Synthetic reviewed scope",
                    )
                    for evidence_index, evidence_id in enumerate(evidence_ids, start=1)
                ),
            )
            result = generate_checked(provider, request)
            if result.provider.prompt_version != GENERATION_PROMPT_VERSION:
                raise ValueError("provider prompt version changed")
            passed += 1
    except (GenerationError, ValueError) as error:
        _fail(str(error))
    print(
        json.dumps(
            {
                "calls": passed,
                "generation_schema_version": "1.1",
                "model": args.model,
                "prompt_version": GENERATION_PROMPT_VERSION,
                "provider": "openai-responses",
                "raw_responses_persisted": False,
                "synthetic_only": True,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _fail(message: str) -> None:
    print(
        json.dumps(
            {"error": message, "kind": "manual_generation_evaluation_error"},
            ensure_ascii=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )
    raise SystemExit(2)


if __name__ == "__main__":
    main()
