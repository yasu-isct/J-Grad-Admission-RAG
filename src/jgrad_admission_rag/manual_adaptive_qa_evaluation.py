"""Explicit two-call HTTP acceptance for adaptive DeepSeek QA and exact-cache reuse."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any, Sequence

from fastapi.testclient import TestClient

from .demo import prepare_demo
from .demo_embedding import create_demo_embedding_provider, resolve_demo_embedding_configuration
from .generation import DeepSeekResponsesConfig, DeepSeekResponsesGenerationProvider
from .generation.question_analysis import DeterministicQuestionUnderstandingProvider
from .manual_deepseek_evaluation import _LiveCallLedger, _emit_report, _fail
from .service import ServiceDependencies, ServiceSettings, create_app

_AUTHORIZATION = "I AUTHORIZE 2 DEEPSEEK ADAPTIVE QA CALLS"
_QUESTION = "托业840按官方的标准是多少英语配点，还有没有jlpt成绩，j-test可以吗"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one two-call adaptive DeepSeek HTTP acceptance and one exact repeat."
    )
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--embedding-cache", required=True, type=Path)
    parser.add_argument("--model", required=True, choices=("deepseek-flash", "deepseek-v4-pro"))
    parser.add_argument("--synthetic-applicant-only", required=True, action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if os.environ.get("JGRAD_ALLOW_DEEPSEEK_LIVE") != _AUTHORIZATION:
        _fail("DeepSeek adaptive evaluation lacks the exact two-call authorization")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        _fail("DeepSeek evaluation credential is unavailable")
    for path in (args.pdf, args.workspace, args.embedding_cache):
        if not path.is_absolute():
            _fail("adaptive evaluation paths must be absolute")

    ledger = _LiveCallLedger(model=args.model, max_calls=2)
    try:
        embedding_config = resolve_demo_embedding_configuration("bge-m3", str(args.embedding_cache))
        runtime = prepare_demo(
            args.pdf,
            args.workspace,
            embedding_configuration=embedding_config,
        )
        embedding_provider = create_demo_embedding_provider(embedding_config)
        generation_provider = DeepSeekResponsesGenerationProvider(
            DeepSeekResponsesConfig(
                model=args.model,
                timeout_seconds=90,
                max_output_tokens=8_000,
                max_retries=0,
            ),
            _client_factory=_adaptive_client_factory(ledger),
        )
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
            generation_provider_name="deepseek-responses",
            generation_model_name=args.model,
            generation_timeout_seconds=90,
            generation_max_retries=0,
        )
        app = create_app(
            settings,
            ServiceDependencies(
                provider_factory=lambda: embedding_provider,
                generation_provider_factory=lambda: generation_provider,
                question_understanding_provider_factory=DeterministicQuestionUnderstandingProvider,
            ),
        )
        with TestClient(app) as client:
            catalog = client.get("/v1/target-catalog")
            if catalog.status_code != 200:
                raise ValueError("target catalog unavailable")
            payload = {
                "question": _QUESTION,
                "target": _first_target(catalog.json()),
                "applicant": {},
            }
            first = client.post("/v1/natural-language-answers", json=payload)
            first_calls = ledger.calls
            repeated = client.post("/v1/natural-language-answers", json=payload)
        if (
            first.status_code != 200
            or repeated.status_code != 200
            or first_calls != 2
            or ledger.calls != 2
            or first.json().get("delivery", {}).get("source") != "live"
            or repeated.json().get("delivery", {}).get("source") != "cache_hit"
            or first.json().get("result") != repeated.json().get("result")
        ):
            raise ValueError("adaptive HTTP or exact-cache acceptance failed")
        for observation in ledger.observations:
            if observation["structured_output"] != "pydantic_valid":
                raise ValueError("adaptive structured output validation failed")
            observation["result_status"] = "validated"
        _emit_report(
            ledger,
            error_code=None,
            success=True,
            extra={
                "first_delivery_source": "live",
                "repeat_additional_calls": 0,
                "repeat_delivery_source": "cache_hit",
            },
        )
    except Exception:
        ledger.fail("local_validation_failed")
        _emit_report(ledger, error_code="local_validation_failed", success=False)
        raise SystemExit(2) from None


def _adaptive_client_factory(ledger: _LiveCallLedger):
    def factory(**kwargs: object):
        from openai import OpenAI

        client = OpenAI(**kwargs)
        return SimpleNamespace(responses=_AdaptiveObservedResponses(client.responses, ledger))

    return factory


class _AdaptiveObservedResponses:
    def __init__(self, responses: Any, ledger: _LiveCallLedger) -> None:
        self._responses = responses
        self._ledger = ledger

    def create(self, **kwargs: object) -> object:
        phase = _phase_from_request(kwargs)
        index = self._ledger.begin(phase)
        started = time.perf_counter()
        try:
            response = self._responses.create(**kwargs)
        except Exception:
            self._ledger.transport_failed(index, (time.perf_counter() - started) * 1_000)
            raise
        self._ledger.response_received(index, response, (time.perf_counter() - started) * 1_000)
        return response


def _phase_from_request(kwargs: dict[str, object]) -> str:
    try:
        name = kwargs["text"]["format"]["name"]  # type: ignore[index]
    except Exception:
        raise ValueError("adaptive request schema name unavailable") from None
    if name == "adaptive_qa_plan":
        return "adaptive-planning"
    if name == "adaptive_qa_answer":
        return "adaptive-final"
    raise ValueError("unexpected adaptive request schema")


def _first_target(catalog: dict[str, object]) -> dict[str, object]:
    school = catalog["schools"][0]  # type: ignore[index]
    degree = school["degrees"][0]
    intake = degree["intakes"][0]
    college = intake["colleges"][0]
    department = college["departments"][0]
    return {
        "school_id": school["school_id"],
        "document_id": intake["document_id"],
        "degree_id": degree["degree_id"],
        "intake": {"year": intake["year"], "month": intake["month"]},
        "college_id": college["college_id"],
        "department_id": department["department_id"],
        "application_route": None,
    }


if __name__ == "__main__":
    main()
