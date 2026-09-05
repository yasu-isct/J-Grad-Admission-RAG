from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .retrieval_evaluation import (
    RetrievalEvaluationReport,
    canonical_retrieval_evaluation_bytes,
)

SEMANTIC_GATE_POLICY_SCHEMA_VERSION = "1.0"
SEMANTIC_GATE_MANIFEST_SCHEMA_VERSION = "1.0"
SEMANTIC_GATE_RESULT_SCHEMA_VERSION = "1.0"
SEMANTIC_GATE_VERSION = "semantic-retrieval-gate-v1"


class SemanticGateError(Exception):
    """Raised when semantic-gate input is unsafe or cannot be trusted."""


class SemanticGateInputError(SemanticGateError):
    """Raised when a gate file path or serialized bytes are unsafe."""


class ImplementationContractError(SemanticGateError):
    """Raised when declared retrieval-affecting repository files do not reconcile."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BaselineBinding(_StrictModel):
    report_sha256: str
    source_kb_sha256: str
    source_pdf_sha256: str
    document_id: str
    benchmark_sha256: str
    fact_content_sha256: str
    fact_structure_sha256: str
    payloads_sha256: str
    vectors_sha256: str
    embedding_provider: Literal["sentence-transformers"]
    embedding_model: Literal["BAAI/bge-m3"]
    embedding_revision: Literal["5617a9f61b028005a4858fdac845db406aefb181"]
    embedding_dimension: Literal[1024]

    @field_validator(
        "report_sha256",
        "source_kb_sha256",
        "source_pdf_sha256",
        "benchmark_sha256",
        "fact_content_sha256",
        "fact_structure_sha256",
        "payloads_sha256",
        "vectors_sha256",
    )
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value


class MetricFloors(_StrictModel):
    recall_at_1: float = Field(ge=0, le=1)
    recall_at_3: float = Field(ge=0, le=1)
    recall_at_5: float = Field(ge=0, le=1)
    recall_at_10: float = Field(ge=0, le=1)
    mrr: float = Field(ge=0, le=1)

    @field_validator("*")
    @classmethod
    def values_must_be_finite(cls, value: float) -> float:
        _validate_finite(value)
        return value


class CountCaps(_StrictModel):
    zero_hit_queries: int = Field(ge=0)
    missing_gold_at_10: int = Field(ge=0)
    partial_top_10_queries: int = Field(ge=0)


class SliceFloor(_StrictModel):
    dimension: Literal["category", "query_style", "scope_sensitive", "multiple_clause"]
    group: str
    recall_at_10: float = Field(ge=0, le=1)

    @field_validator("group")
    @classmethod
    def group_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @field_validator("recall_at_10")
    @classmethod
    def floor_must_be_finite(cls, value: float) -> float:
        _validate_finite(value)
        return value


class ReferenceRecoveryRule(_StrictModel):
    query_id: Literal["rq:0012"]
    primary_recall_at_10_floor: float = Field(ge=0, le=1)
    combined_coverage: Literal[1.0]
    reference_only_fact_ids: tuple[Literal["fact:00062", "fact:00070"], ...]

    @field_validator("primary_recall_at_10_floor")
    @classmethod
    def primary_floor_must_be_finite(cls, value: float) -> float:
        _validate_finite(value)
        return value

    @field_validator("reference_only_fact_ids")
    @classmethod
    def reference_ids_must_be_exact(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != ("fact:00062", "fact:00070"):
            raise ValueError("reference-only Fact IDs must preserve the accepted pair")
        return values


class SemanticGatePolicy(_StrictModel):
    schema_version: Literal["1.0"] = SEMANTIC_GATE_POLICY_SCHEMA_VERSION
    gate_version: Literal["semantic-retrieval-gate-v1"] = SEMANTIC_GATE_VERSION
    baseline: BaselineBinding
    global_floors: MetricFloors
    count_caps: CountCaps
    weak_slice_floors: tuple[SliceFloor, ...]
    reference_recovery: ReferenceRecoveryRule

    @model_validator(mode="after")
    def slices_must_be_exact(self) -> SemanticGatePolicy:
        expected = (
            ("category", "eligibility"),
            ("multiple_clause", "true"),
            ("query_style", "exact_term"),
        )
        observed = tuple((item.dimension, item.group) for item in self.weak_slice_floors)
        if observed != expected:
            raise ValueError("weak slice floors must use the accepted deterministic order")
        return self


class SemanticGateManifest(_StrictModel):
    schema_version: Literal["1.0"] = SEMANTIC_GATE_MANIFEST_SCHEMA_VERSION
    gate_version: Literal["semantic-retrieval-gate-v1"] = SEMANTIC_GATE_VERSION
    policy_sha256: str
    report_sha256: str
    implementation_globs: tuple[str, ...]
    implementation_paths: tuple[str, ...]
    implementation_sha256: str

    @field_validator("policy_sha256", "report_sha256", "implementation_sha256")
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value

    @field_validator("implementation_globs")
    @classmethod
    def globs_must_be_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or values != tuple(sorted(set(values))):
            raise ValueError("implementation globs must be non-empty, sorted, and unique")
        for value in values:
            _validate_relative_posix_path(value, allow_glob=True)
        return values

    @field_validator("implementation_paths")
    @classmethod
    def paths_must_be_sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or values != tuple(sorted(set(values))):
            raise ValueError("implementation paths must be non-empty, sorted, and unique")
        for value in values:
            _validate_relative_posix_path(value, allow_glob=False)
        return values


class GateCheck(_StrictModel):
    code: str
    subject: str
    observed: float | int | str | bool
    comparator: Literal[">=", "<=", "=="]
    threshold: float | int | str | bool
    margin: float | None = None
    passed: bool

    @field_validator("code", "subject")
    @classmethod
    def strings_must_be_trimmed(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @field_validator("margin")
    @classmethod
    def margin_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None:
            _validate_finite(value)
        return value


class SemanticGateResult(_StrictModel):
    schema_version: Literal["1.0"] = SEMANTIC_GATE_RESULT_SCHEMA_VERSION
    gate_version: Literal["semantic-retrieval-gate-v1"] = SEMANTIC_GATE_VERSION
    passed: bool
    report_sha256: str
    policy_sha256: str
    implementation_sha256: str
    checks: tuple[GateCheck, ...]
    failure_codes: tuple[str, ...]

    @field_validator("report_sha256", "policy_sha256", "implementation_sha256")
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value

    @model_validator(mode="after")
    def result_must_reconcile(self) -> SemanticGateResult:
        expected_failures = tuple(sorted(check.code for check in self.checks if not check.passed))
        if self.failure_codes != expected_failures:
            raise ValueError("failure codes do not reconcile with checks")
        if self.passed != (not self.failure_codes):
            raise ValueError("gate pass state does not reconcile with checks")
        return self


def canonical_semantic_gate_policy_bytes(policy: SemanticGatePolicy) -> bytes:
    return _canonical_bytes(policy, SemanticGatePolicy, "semantic gate policy")


def canonical_semantic_gate_manifest_bytes(manifest: SemanticGateManifest) -> bytes:
    return _canonical_bytes(manifest, SemanticGateManifest, "semantic gate manifest")


def canonical_semantic_gate_result_bytes(result: SemanticGateResult) -> bytes:
    return _canonical_bytes(result, SemanticGateResult, "semantic gate result")


def load_semantic_gate_policy_bytes(raw_bytes: bytes) -> SemanticGatePolicy:
    return _load_model_bytes(raw_bytes, SemanticGatePolicy, "semantic gate policy")


def load_semantic_gate_manifest_bytes(raw_bytes: bytes) -> SemanticGateManifest:
    return _load_model_bytes(raw_bytes, SemanticGateManifest, "semantic gate manifest")


def read_regular_file_bytes(path_value: str | Path, *, label: str) -> bytes:
    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        raise SemanticGateInputError(f"{label} path is missing or unsafe")
    try:
        return path.read_bytes()
    except OSError as error:
        raise SemanticGateInputError(f"{label} path could not be read") from error


def implementation_contract(
    repository_root: str | Path,
    implementation_globs: Sequence[str],
) -> tuple[tuple[str, ...], str]:
    root = _repository_root(repository_root)
    if not implementation_globs:
        raise ImplementationContractError("implementation globs must not be empty")
    discovered: list[str] = []
    for pattern in implementation_globs:
        _validate_relative_posix_path(pattern, allow_glob=True)
        matches = sorted(root.glob(pattern))
        if not matches:
            raise ImplementationContractError("implementation glob did not match a file")
        for path in matches:
            if path.is_symlink():
                raise ImplementationContractError("implementation contract cannot include symlinks")
            if not path.is_file():
                continue
            discovered.append(_relative_posix(root, path))
    if len(discovered) != len(set(discovered)):
        raise ImplementationContractError("implementation glob set contains duplicate paths")
    paths = tuple(sorted(discovered))
    if not paths:
        raise ImplementationContractError("implementation glob set did not resolve regular files")
    return paths, _hash_implementation_paths(root, paths)


def evaluate_semantic_gate(
    report: RetrievalEvaluationReport,
    policy: SemanticGatePolicy,
    manifest: SemanticGateManifest,
    repository_root: str | Path,
    *,
    report_sha256: str | None = None,
    policy_sha256: str | None = None,
    benchmark_sha256: str | None = None,
) -> SemanticGateResult:
    if not isinstance(report, RetrievalEvaluationReport):
        raise SemanticGateInputError("report must be a RetrievalEvaluationReport")
    if not isinstance(policy, SemanticGatePolicy) or not isinstance(manifest, SemanticGateManifest):
        raise SemanticGateInputError("policy and manifest must use semantic gate schemas")
    report_hash = report_sha256 or _sha256(canonical_retrieval_evaluation_bytes(report))
    policy_hash = policy_sha256 or _sha256(canonical_semantic_gate_policy_bytes(policy))
    _validate_sha256(report_hash)
    _validate_sha256(policy_hash)
    benchmark_hash = benchmark_sha256 or _benchmark_sha256(repository_root)
    _validate_sha256(benchmark_hash)
    paths, implementation_hash = implementation_contract(
        repository_root, manifest.implementation_globs
    )
    if paths != manifest.implementation_paths:
        raise ImplementationContractError("implementation path set no longer matches the manifest")

    checks: list[GateCheck] = []
    baseline = policy.baseline
    _equal(checks, "report_sha256", "report", report_hash, baseline.report_sha256)
    _equal(checks, "manifest.report_sha256", "manifest", manifest.report_sha256, report_hash)
    _equal(checks, "manifest.policy_sha256", "manifest", manifest.policy_sha256, policy_hash)
    _equal(
        checks,
        "manifest.implementation_sha256",
        "implementation_contract",
        manifest.implementation_sha256,
        implementation_hash,
    )
    _equal(
        checks,
        "report.semantic",
        "quality.semantic_evaluation",
        report.quality.semantic_evaluation,
        True,
    )
    _equal(
        checks, "report.eligible", "quality.quality_eligible", report.quality.quality_eligible, True
    )
    _equal(
        checks,
        "report.gate_status",
        "quality.gate_status",
        report.quality.gate_status,
        "not_evaluated",
    )
    _equal(
        checks,
        "runtime.provider",
        "runtime.embedding_provider",
        report.runtime.embedding_provider,
        baseline.embedding_provider,
    )
    _equal(
        checks,
        "runtime.model",
        "runtime.embedding_model",
        report.runtime.embedding_model,
        baseline.embedding_model,
    )
    _equal(
        checks,
        "runtime.revision",
        "runtime.embedding_revision",
        report.runtime.embedding_revision or "",
        baseline.embedding_revision,
    )
    _equal(
        checks,
        "runtime.dimension",
        "runtime.embedding_dimension",
        report.runtime.embedding_dimension,
        baseline.embedding_dimension,
    )
    _equal(
        checks,
        "runtime.kb",
        "runtime.source_kb_sha256",
        report.runtime.source_kb_sha256,
        baseline.source_kb_sha256,
    )
    _equal(
        checks,
        "runtime.source_pdf",
        "runtime.source_pdf_sha256",
        report.runtime.source_pdf_sha256,
        baseline.source_pdf_sha256,
    )
    _equal(
        checks,
        "runtime.payloads",
        "runtime.payloads_sha256",
        report.runtime.payloads_sha256,
        baseline.payloads_sha256,
    )
    _equal(
        checks,
        "runtime.vectors",
        "runtime.vectors_sha256",
        report.runtime.vectors_sha256,
        baseline.vectors_sha256,
    )
    _equal(
        checks,
        "benchmark.document",
        "benchmark.document_id",
        report.benchmark.document_id,
        baseline.document_id,
    )
    _equal(
        checks,
        "benchmark.source_pdf",
        "benchmark.source_pdf_sha256",
        report.benchmark.source_pdf_sha256,
        baseline.source_pdf_sha256,
    )
    _equal(
        checks,
        "benchmark.fact_content",
        "benchmark.fact_content_sha256",
        report.benchmark.fact_content_sha256,
        baseline.fact_content_sha256,
    )
    _equal(
        checks,
        "benchmark.fact_structure",
        "benchmark.fact_structure_sha256",
        report.benchmark.fact_structure_sha256,
        baseline.fact_structure_sha256,
    )
    _equal(
        checks,
        "benchmark.file",
        "frozen benchmark SHA-256",
        benchmark_hash,
        baseline.benchmark_sha256,
    )

    overall = report.aggregates.overall
    for field, threshold in policy.global_floors.model_dump(mode="python").items():
        observed = overall.mrr if field == "mrr" else getattr(overall.recall, field)
        _at_least(checks, f"global.{field}", "overall", observed, threshold)
    missing_gold = sum(len(query.missing_gold.at_10) for query in report.queries)
    partial_queries = sum(query.recall.recall_at_10 < 1.0 for query in report.queries)
    _at_most(
        checks,
        "count.zero_hit_queries",
        "overall",
        len(overall.zero_hit_query_ids),
        policy.count_caps.zero_hit_queries,
    )
    _at_most(
        checks,
        "count.missing_gold_at_10",
        "overall",
        missing_gold,
        policy.count_caps.missing_gold_at_10,
    )
    _at_most(
        checks,
        "count.partial_top_10_queries",
        "overall",
        partial_queries,
        policy.count_caps.partial_top_10_queries,
    )

    summaries = {
        (item.dimension, item.group): item.summary for item in report.aggregates.breakdowns
    }
    for slice_floor in policy.weak_slice_floors:
        summary = summaries.get((slice_floor.dimension, slice_floor.group))
        if summary is None:
            raise SemanticGateInputError("required weak-slice breakdown is missing")
        _at_least(
            checks,
            f"slice.{slice_floor.dimension}.{slice_floor.group}.recall_at_10",
            "weak_slice",
            summary.recall.recall_at_10,
            slice_floor.recall_at_10,
        )

    query = next(
        (item for item in report.queries if item.query_id == policy.reference_recovery.query_id),
        None,
    )
    if query is None:
        raise SemanticGateInputError("reference recovery query is missing")
    primary = {item.fact_id for item in query.ranked_primary_facts}
    combined = len(
        (primary | set(query.reference_only_gold_fact_ids)) & set(query.relevant_fact_ids)
    ) / len(query.relevant_fact_ids)
    _at_least(
        checks,
        "rq0012.primary_recall_at_10",
        "rq:0012",
        query.recall.recall_at_10,
        policy.reference_recovery.primary_recall_at_10_floor,
    )
    _equal(
        checks,
        "rq0012.combined_reference_coverage",
        "rq:0012",
        combined,
        policy.reference_recovery.combined_coverage,
    )
    _equal(
        checks,
        "rq0012.reference_only_fact_ids",
        "rq:0012",
        query.reference_only_gold_fact_ids,
        policy.reference_recovery.reference_only_fact_ids,
    )

    failure_codes = tuple(sorted(check.code for check in checks if not check.passed))
    return SemanticGateResult(
        passed=not failure_codes,
        report_sha256=report_hash,
        policy_sha256=policy_hash,
        implementation_sha256=implementation_hash,
        checks=tuple(checks),
        failure_codes=failure_codes,
    )


def baseline_privacy_violations(raw_bytes: bytes, raw_queries: Sequence[str]) -> tuple[str, ...]:
    """Return stable privacy violation codes without echoing private values."""

    if not isinstance(raw_bytes, bytes):
        raise SemanticGateInputError("baseline privacy scan requires bytes")
    violations: set[str] = set()
    try:
        value = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SemanticGateInputError("baseline privacy scan requires JSON") from error
    if not isinstance(value, dict):
        raise SemanticGateInputError("baseline privacy scan requires an object")
    for query in raw_queries:
        if query.encode("utf-8") in raw_bytes:
            violations.add("raw_query_text")
    for marker, code in (
        (b"C:\\", "windows_path"),
        (b"/Users/", "unix_home_path"),
        (b"/home/", "unix_home_path"),
    ):
        if marker in raw_bytes:
            violations.add(code)
    for key in _walk_keys(value):
        if key in {
            "query",
            "text",
            "evidence",
            "answer",
            "applicant_profile",
            "cache",
            "cache_path",
            "token",
            "access_token",
            "api_key",
        }:
            violations.add("forbidden_content_field")
    for text in _walk_strings(value):
        if text.startswith(("gho_", "ghp_", "hf_", "sk-")):
            violations.add("secret_marker")
    return tuple(sorted(violations))


def _canonical_bytes(value: BaseModel, model_type: type[BaseModel], label: str) -> bytes:
    if not isinstance(value, model_type):
        raise SemanticGateInputError(f"{label} has the wrong type")
    try:
        validated = model_type.model_validate(value.model_dump(mode="json"))
        return (
            json.dumps(
                validated.model_dump(mode="json"),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, ValidationError) as error:
        raise SemanticGateInputError(f"{label} cannot be serialized") from error


def _load_model_bytes(raw_bytes: bytes, model_type: type[BaseModel], label: str):
    if not isinstance(raw_bytes, bytes):
        raise SemanticGateInputError(f"{label} input must be bytes")
    try:
        value = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("not an object")
        return model_type.model_validate(value)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        ValidationError,
    ) as error:
        raise SemanticGateInputError(f"{label} bytes are invalid or unsupported") from error


def _repository_root(path_value: str | Path) -> Path:
    root = Path(path_value)
    if root.is_symlink() or not root.is_dir():
        raise ImplementationContractError("repository root is missing or unsafe")
    try:
        return root.resolve(strict=True)
    except OSError as error:
        raise ImplementationContractError("repository root could not be resolved") from error


def _hash_implementation_paths(root: Path, paths: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in paths:
        _validate_relative_posix_path(relative, allow_glob=False)
        path = root.joinpath(*PurePosixPath(relative).parts)
        if path.is_symlink() or not path.is_file():
            raise ImplementationContractError("implementation file is missing or unsafe")
        if _relative_posix(root, path) != relative:
            raise ImplementationContractError("implementation file escapes repository root")
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ImplementationContractError("implementation file could not be read") from error
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
    return digest.hexdigest()


def _relative_posix(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(root).as_posix()
    except (OSError, ValueError) as error:
        raise ImplementationContractError("implementation file escapes repository root") from error


def _validate_relative_posix_path(value: str, *, allow_glob: bool) -> None:
    if not isinstance(value, str) or not value or value != value.strip() or "\\" in value:
        raise ValueError("implementation paths must be trimmed POSIX relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("implementation paths must stay within the repository")
    if not allow_glob and any(character in value for character in "*?[]"):
        raise ValueError("implementation paths cannot contain glob characters")


def _walk_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                yield key
            yield from _walk_keys(child)


def _walk_strings(value: object):
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)
    elif isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _sha256(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()


def _benchmark_sha256(repository_root: str | Path) -> str:
    root = _repository_root(repository_root)
    return _sha256(
        read_regular_file_bytes(
            root / "tests/fixtures/retrieval_queries_v1.json", label="benchmark"
        )
    )


def _equal(
    checks: list[GateCheck],
    code: str,
    subject: str,
    observed: float | int | str | bool | tuple[str, ...],
    threshold: float | int | str | bool | tuple[str, ...],
) -> None:
    checks.append(
        GateCheck(
            code=code,
            subject=subject,
            observed=_display(observed),
            comparator="==",
            threshold=_display(threshold),
            margin=None,
            passed=observed == threshold,
        )
    )


def _at_least(
    checks: list[GateCheck], code: str, subject: str, observed: float, threshold: float
) -> None:
    _validate_finite(observed)
    checks.append(
        GateCheck(
            code=code,
            subject=subject,
            observed=observed,
            comparator=">=",
            threshold=threshold,
            margin=observed - threshold,
            passed=observed >= threshold,
        )
    )


def _at_most(
    checks: list[GateCheck], code: str, subject: str, observed: int, threshold: int
) -> None:
    checks.append(
        GateCheck(
            code=code,
            subject=subject,
            observed=observed,
            comparator="<=",
            threshold=threshold,
            margin=float(threshold - observed),
            passed=observed <= threshold,
        )
    )


def _display(value: float | int | str | bool | tuple[str, ...]) -> float | int | str | bool:
    return ",".join(value) if isinstance(value, tuple) else value


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("value must be lowercase SHA-256 hex")


def _validate_trimmed(value: str) -> None:
    if not value or value != value.strip():
        raise ValueError("value must be a non-empty trimmed string")


def _validate_finite(value: float) -> None:
    if not math.isfinite(value):
        raise ValueError("value must be finite")
