"""Explicitly authorized one-call DeepSeek evaluation for the simple QA product path."""

from __future__ import annotations

import argparse
import os
from typing import Sequence

from .generation import DeepSeekResponsesConfig, DeepSeekResponsesGenerationProvider
from .generation.provider import GenerationError
from .generation.simple_qa import (
    SimpleQaRequest,
    SimpleQaSource,
    answer_simple_checked,
)
from .manual_deepseek_evaluation import _LiveCallLedger, _emit_report, _fail


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run exactly one explicitly authorized DeepSeek simple-QA synthetic call."
    )
    parser.add_argument("--model", required=True, choices=("deepseek-flash", "deepseek-v4-pro"))
    parser.add_argument("--synthetic-only", required=True, action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if os.environ.get("JGRAD_ALLOW_DEEPSEEK_LIVE") != "I AUTHORIZE 1 DEEPSEEK SIMPLE QA CALL":
        _fail("DeepSeek simple-QA evaluation lacks the exact one-run call authorization")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        _fail("DeepSeek evaluation credential is unavailable")

    config = DeepSeekResponsesConfig(
        model=args.model,
        timeout_seconds=90,
        max_output_tokens=8_000,
        max_retries=0,
    )
    ledger = _LiveCallLedger(model=args.model, max_calls=1)
    provider = DeepSeekResponsesGenerationProvider(
        config,
        _client_factory=ledger.client_factory("simple-answer"),
    )
    request = SimpleQaRequest(
        question="What English maximum is stated in the supplied local record?",
        target_label="Synthetic target",
        sources=(
            SimpleQaSource(
                source_id="source:0001",
                text="Synthetic local admission record: English has a maximum of 100 points.",
                scope_label="Synthetic scope",
            ),
        ),
    )
    try:
        answer_simple_checked(provider, request)
        ledger.finish("simple-answer", "validated", "not_applicable")
    except GenerationError as error:
        ledger.fail(error.code.value)
        _emit_report(ledger, error_code=error.code.value, success=False)
        raise SystemExit(2) from None
    _emit_report(ledger, error_code=None, success=True)


if __name__ == "__main__":
    main()
