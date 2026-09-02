from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from jgrad_admission_rag.evaluation.retrieval_evaluation import load_retrieval_evaluation_bytes
from jgrad_admission_rag.evaluation.semantic_gate import (
    MetricFloors,
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
    ".gitattributes",
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


@pytest.mark.parametrize(
    ("field", "observed"),
    (
        ("recall_at_1", 0.4193627450980392),
        ("recall_at_3", 0.7568627450980392),
        ("recall_at_5", 0.8563725490196079),
        ("recall_at_10", 0.9416666666666667),
        ("mrr", 0.9607843137254901),
    ),
)
def test_global_floors_use_unrounded_exact_comparisons(field: str, observed: float) -> None:
    policy = _policy()
    exact = policy.model_copy(
        update={"global_floors": policy.global_floors.model_copy(update={field: observed})}
    )
    too_high = policy.model_copy(
        update={
            "global_floors": policy.global_floors.model_copy(
                update={field: math.nextafter(observed, math.inf)}
            )
        }
    )

    assert _evaluate(policy=exact).passed is True
    assert f"global.{field}" in _evaluate(policy=too_high).failure_codes


@pytest.mark.parametrize(
    ("field", "cap", "code"),
    (
        ("missing_gold_at_10", 10, "count.missing_gold_at_10"),
        ("partial_top_10_queries", 5, "count.partial_top_10_queries"),
    ),
)
def test_count_caps_fail_at_one_less_than_the_accepted_value(
    field: str, cap: int, code: str
) -> None:
    policy = _policy()
    changed = policy.model_copy(
        update={"count_caps": policy.count_caps.model_copy(update={field: cap})}
    )

    assert code in _evaluate(policy=changed).failure_codes


def test_zero_hit_cap_fails_when_a_zero_hit_is_introduced() -> None:
    report = load_retrieval_evaluation_bytes(_report_bytes())
    overall = report.aggregates.overall.model_copy(update={"zero_hit_query_ids": ("rq:0001",)})
    changed = report.model_copy(
        update={"aggregates": report.aggregates.model_copy(update={"overall": overall})}
    )
    policy = _policy()
    policy_bytes = POLICY_PATH.read_bytes()

    result = evaluate_semantic_gate(
        changed,
        policy,
        _manifest(policy_bytes, _report_bytes()),
        ROOT,
        report_sha256=_sha256(_report_bytes()),
        policy_sha256=_sha256(policy_bytes),
    )

    assert "count.zero_hit_queries" in result.failure_codes


@pytest.mark.parametrize(
    ("dimension", "group", "observed"),
    (
        ("category", "eligibility", 0.7666666666666666),
        ("multiple_clause", "true", 0.7642857142857142),
        ("query_style", "exact_term", 0.8452380952380952),
    ),
)
def test_weak_slice_floors_reject_a_value_above_the_observation(
    dimension: str, group: str, observed: float
) -> None:
    policy = _policy()
    floors = tuple(
        item.model_copy(update={"recall_at_10": math.nextafter(observed, math.inf)})
        if (item.dimension, item.group) == (dimension, group)
        else item
        for item in policy.weak_slice_floors
    )
    changed = policy.model_copy(update={"weak_slice_floors": floors})

    assert f"slice.{dimension}.{group}.recall_at_10" in _evaluate(policy=changed).failure_codes


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("embedding_provider", "different-provider", "runtime.provider"),
        ("embedding_revision", "0" * 40, "runtime.revision"),
        ("embedding_dimension", 768, "runtime.dimension"),
        ("source_kb_sha256", "0" * 64, "runtime.kb"),
        ("payloads_sha256", "0" * 64, "runtime.payloads"),
        ("vectors_sha256", "0" * 64, "runtime.vectors"),
    ),
)
def test_runtime_binding_drift_is_explicit(field: str, value: str | int, code: str) -> None:
    report = load_retrieval_evaluation_bytes(_report_bytes())
    changed = report.model_copy(
        update={"runtime": report.runtime.model_copy(update={field: value})}
    )
    policy_bytes = POLICY_PATH.read_bytes()

    result = evaluate_semantic_gate(
        changed,
        _policy(),
        _manifest(policy_bytes, _report_bytes()),
        ROOT,
        report_sha256=_sha256(_report_bytes()),
        policy_sha256=_sha256(policy_bytes),
    )

    assert code in result.failure_codes


def test_reference_recovery_requires_primary_and_attachment_credit() -> None:
    report = load_retrieval_evaluation_bytes(_report_bytes())
    query = next(item for item in report.queries if item.query_id == "rq:0012")
    changed_query = query.model_copy(update={"reference_only_gold_fact_ids": ()})
    changed = report.model_copy(
        update={
            "queries": tuple(
                changed_query if item.query_id == "rq:0012" else item for item in report.queries
            )
        }
    )
    policy_bytes = POLICY_PATH.read_bytes()
    result = evaluate_semantic_gate(
        changed,
        _policy(),
        _manifest(policy_bytes, _report_bytes()),
        ROOT,
        report_sha256=_sha256(_report_bytes()),
        policy_sha256=_sha256(policy_bytes),
    )

    assert {"rq0012.combined_reference_coverage", "rq0012.reference_only_fact_ids"} <= set(
        result.failure_codes
    )


def test_strict_policy_rejects_nonfinite_and_unknown_schema_fields() -> None:
    with pytest.raises(ValueError):
        MetricFloors(
            recall_at_1=math.nan,
            recall_at_3=0.74,
            recall_at_5=0.84,
            recall_at_10=0.93,
            mrr=0.95,
        )
    with pytest.raises(Exception, match="invalid or unsupported"):
        load_semantic_gate_policy_bytes(b'{"schema_version":"1.0","unknown":true}')


def test_implementation_contract_rejects_extra_paths_and_symlinks(tmp_path: Path) -> None:
    policy_bytes = POLICY_PATH.read_bytes()
    manifest = _manifest(policy_bytes, _report_bytes()).model_copy(
        update={
            "implementation_paths": _manifest(policy_bytes, _report_bytes()).implementation_paths
            + ("extra.py",)
        }
    )
    with pytest.raises(ImplementationContractError, match="path set"):
        _evaluate(manifest=manifest)

    target = tmp_path / "target.py"
    target.write_text("x = 1\n", encoding="utf-8")
    link = tmp_path / "link.py"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(ImplementationContractError, match="symlinks"):
        implementation_contract(tmp_path, ("link.py",))
