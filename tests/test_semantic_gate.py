from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jgrad_admission_rag.evaluation.retrieval_evaluation import load_retrieval_evaluation_bytes
from jgrad_admission_rag.evaluation.semantic_gate import (
    ImplementationContractError,
    SemanticGateManifest,
    baseline_privacy_violations,
    canonical_semantic_gate_policy_bytes,
    evaluate_semantic_gate,
    implementation_contract,
    load_semantic_gate_manifest_bytes,
    load_semantic_gate_policy_bytes,
)

ROOT = Path(__file__).parents[1]
REPORT_PATH = Path(__file__).parent / "fixtures" / "semantic_retrieval_baseline_v1.json"
POLICY_PATH = ROOT / "config" / "semantic_retrieval_gate_v1.json"
MANIFEST_PATH = ROOT / "config" / "semantic_retrieval_gate_manifest_v1.json"
GLOBS = (
    "pyproject.toml",
    "src/jgrad_admission_rag/cli/*.py",
    "src/jgrad_admission_rag/evaluation/*.py",
    "src/jgrad_admission_rag/retrieval/*.py",
    "src/jgrad_admission_rag/schemas/*.py",
    "tests/fixtures/retrieval_queries_v1.json",
)


def _sha256(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def _report_bytes() -> bytes:
    return REPORT_PATH.read_bytes()


def _policy():
    return load_semantic_gate_policy_bytes(POLICY_PATH.read_bytes())


def _manifest(policy_bytes: bytes, report_bytes: bytes) -> SemanticGateManifest:
    paths, implementation_sha256 = implementation_contract(ROOT, GLOBS)
    return SemanticGateManifest(
        policy_sha256=_sha256(policy_bytes),
        report_sha256=_sha256(report_bytes),
        implementation_globs=GLOBS,
        implementation_paths=paths,
        implementation_sha256=implementation_sha256,
    )


def _evaluate(*, policy=None, manifest=None):
    report_bytes = _report_bytes()
    policy = policy or _policy()
    policy_bytes = canonical_semantic_gate_policy_bytes(policy)
    manifest = manifest or _manifest(policy_bytes, report_bytes)
    return evaluate_semantic_gate(
        load_retrieval_evaluation_bytes(report_bytes),
        policy,
        manifest,
        ROOT,
        report_sha256=_sha256(report_bytes),
        policy_sha256=_sha256(policy_bytes),
        benchmark_sha256=_sha256((ROOT / "tests/fixtures/retrieval_queries_v1.json").read_bytes()),
    )


def test_frozen_semantic_baseline_passes_every_required_check() -> None:
    result = _evaluate()

    assert result.passed is True
    assert result.failure_codes == ()
    assert {check.code for check in result.checks} >= {
        "global.recall_at_1",
        "global.recall_at_3",
        "global.recall_at_5",
        "global.recall_at_10",
        "global.mrr",
        "count.zero_hit_queries",
        "count.missing_gold_at_10",
        "count.partial_top_10_queries",
        "slice.category.eligibility.recall_at_10",
        "slice.multiple_clause.true.recall_at_10",
        "slice.query_style.exact_term.recall_at_10",
        "rq0012.combined_reference_coverage",
        "rq0012.reference_only_fact_ids",
    }


def test_checked_in_manifest_matches_the_current_implementation_contract() -> None:
    policy_bytes = POLICY_PATH.read_bytes()
    report_bytes = _report_bytes()
    manifest = load_semantic_gate_manifest_bytes(MANIFEST_PATH.read_bytes())

    result = evaluate_semantic_gate(
        load_retrieval_evaluation_bytes(report_bytes),
        _policy(),
        manifest,
        ROOT,
        report_sha256=_sha256(report_bytes),
        policy_sha256=_sha256(policy_bytes),
    )

    assert result.passed is True


def test_policy_tightening_returns_a_deterministic_failure() -> None:
    policy = _policy().model_copy(
        update={"global_floors": _policy().global_floors.model_copy(update={"recall_at_1": 0.5})}
    )

    result = _evaluate(policy=policy)

    assert result.passed is False
    assert result.failure_codes == ("global.recall_at_1",)


def test_runtime_identity_drift_is_reported_without_loading_a_model() -> None:
    report = load_retrieval_evaluation_bytes(_report_bytes())
    changed = report.model_copy(
        update={"runtime": report.runtime.model_copy(update={"embedding_model": "other-model"})}
    )
    policy = _policy()
    policy_bytes = POLICY_PATH.read_bytes()
    manifest = _manifest(policy_bytes, _report_bytes())

    result = evaluate_semantic_gate(
        changed,
        policy,
        manifest,
        ROOT,
        report_sha256=_sha256(_report_bytes()),
        policy_sha256=_sha256(policy_bytes),
    )

    assert result.passed is False
    assert result.failure_codes == ("runtime.model",)


def test_manifest_rejects_changed_declared_path_set() -> None:
    policy_bytes = POLICY_PATH.read_bytes()
    manifest = _manifest(policy_bytes, _report_bytes()).model_copy(
        update={"implementation_paths": ("pyproject.toml",)}
    )

    with pytest.raises(ImplementationContractError, match="path set"):
        _evaluate(manifest=manifest)


def test_compact_baseline_has_no_query_text_or_sensitive_fields() -> None:
    benchmark = json.loads((ROOT / "tests/fixtures/retrieval_queries_v1.json").read_text("utf-8"))
    raw_queries = tuple(item["query"] for item in benchmark["queries"])

    assert baseline_privacy_violations(_report_bytes(), raw_queries) == ()
    assert baseline_privacy_violations(
        b'{"lexical_tokenizer_version":"nfkc-casefold-ja23-v1","query":"secret"}', ()
    ) == ("forbidden_content_field",)
    assert baseline_privacy_violations(b'{"value":"gho_example"}', ()) == ("secret_marker",)


def test_gate_modules_do_not_import_embedding_runtime() -> None:
    sources = (
        ROOT / "src/jgrad_admission_rag/evaluation/semantic_gate.py",
        ROOT / "src/jgrad_admission_rag/cli/check_retrieval_gate.py",
    )

    assert all("retrieval.embedding" not in source.read_text("utf-8") for source in sources)
