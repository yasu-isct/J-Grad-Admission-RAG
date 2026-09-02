"""Deterministic applicability checks for human-reviewed admission rules.

This module executes typed rules. It deliberately does not derive rules from
guideline text and does not make final eligibility or admission decisions.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from ..schemas.evidence_pack import EvidencePack
from .applicant_profile import ApplicantProfile
from .query_intent import QueryIntent

APPLICABILITY_RULE_SCHEMA_VERSION = "1.0"
APPLICABILITY_DECISION_SCHEMA_VERSION = "1.0"
SUPPORTED_APPLICABILITY_RULE_SCHEMA_VERSIONS = frozenset({APPLICABILITY_RULE_SCHEMA_VERSION})
SUPPORTED_APPLICABILITY_DECISION_SCHEMA_VERSIONS = frozenset(
    {APPLICABILITY_DECISION_SCHEMA_VERSION}
)

__all__ = [
    "APPLICABILITY_DECISION_SCHEMA_VERSION",
    "APPLICABILITY_RULE_SCHEMA_VERSION",
    "SUPPORTED_APPLICABILITY_DECISION_SCHEMA_VERSIONS",
    "SUPPORTED_APPLICABILITY_RULE_SCHEMA_VERSIONS",
    "ApplicabilityDecision",
    "ApplicabilityDiagnostic",
    "ApplicabilityError",
    "ApplicabilityPredicate",
    "ApplicabilityRule",
    "ApplicabilityStatus",
    "EvidenceRole",
    "LogicalMode",
    "OfficialEvidenceBinding",
    "OfficialEvidenceReference",
    "PredicateOperator",
    "PredicateOutcome",
    "RuleScope",
    "canonical_applicability_decision_bytes",
    "canonical_applicability_rule_bytes",
    "evaluate_applicability",
    "load_applicability_decision",
    "load_applicability_decision_bytes",
    "load_applicability_rule",
    "load_applicability_rule_bytes",
]


class ApplicabilityError(Exception):
    """Raised when applicability inputs cannot be evaluated safely."""


class ApplicabilityModel(BaseModel):
    """Base for immutable, closed applicability records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ApplicabilityStatus(str, Enum):
    CONFIRMED = "confirmed"
    NOT_APPLICABLE = "not_applicable"
    NEEDS_INFORMATION = "needs_information"


class LogicalMode(str, Enum):
    ALL = "all"
    ANY = "any"


class PredicateOperator(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    ON_OR_BEFORE = "on_or_before"
    ON_OR_AFTER = "on_or_after"
    IS_EMPTY = "is_empty"
    IS_NON_EMPTY = "is_non_empty"


class ApplicabilityDiagnostic(str, Enum):
    MISSING_OFFICIAL_EVIDENCE = "missing_official_evidence"
    MISSING_PROFILE_FACT = "missing_profile_fact"
    MISSING_SCOPE = "missing_scope"
    SCOPE_INPUT_CONFLICT = "scope_input_conflict"


class EvidenceRole(str, Enum):
    PRIMARY = "primary"
    ATTACHED = "attached"


PredicateValue = str | StrictInt | StrictFloat | StrictBool | None


@dataclass(frozen=True)
class _FieldSpec:
    kind: Literal["string", "integer", "boolean", "collection", "date"]
    getter: tuple[str, ...]


_FIELD_SPECS = {
    "target_application.requested_degree_level": _FieldSpec(
        "string", ("target_application", "requested_degree_level")
    ),
    "target_application.intake_year": _FieldSpec("integer", ("target_application", "intake_year")),
    "target_application.intake_month": _FieldSpec(
        "integer", ("target_application", "intake_month")
    ),
    "target_application.application_route": _FieldSpec(
        "string", ("target_application", "application_route")
    ),
    "citizenship_and_residence.citizenship_country_codes": _FieldSpec(
        "collection", ("citizenship_and_residence", "citizenship_country_codes")
    ),
    "citizenship_and_residence.current_residence_country_code": _FieldSpec(
        "string", ("citizenship_and_residence", "current_residence_country_code")
    ),
    "citizenship_and_residence.residence_status_category": _FieldSpec(
        "string", ("citizenship_and_residence", "residence_status_category")
    ),
    "eligibility_facts.age_at_enrollment": _FieldSpec(
        "integer", ("eligibility_facts", "age_at_enrollment")
    ),
    "eligibility_facts.professional_experience_months": _FieldSpec(
        "integer", ("eligibility_facts", "professional_experience_months")
    ),
    "eligibility_facts.research_experience_months": _FieldSpec(
        "integer", ("eligibility_facts", "research_experience_months")
    ),
    "eligibility_facts.individual_review_requested": _FieldSpec(
        "boolean", ("eligibility_facts", "individual_review_requested")
    ),
    "eligibility_facts.individual_review_completed": _FieldSpec(
        "boolean", ("eligibility_facts", "individual_review_completed")
    ),
    "academic_credentials.first.completion_date": _FieldSpec(
        "date", ("academic_credentials", "first", "completion_date")
    ),
    "academic_credentials.first.expected_completion_date": _FieldSpec(
        "date", ("academic_credentials", "first", "expected_completion_date")
    ),
    "language_test_results.first.test_date": _FieldSpec(
        "date", ("language_test_results", "first", "test_date")
    ),
}

_OPERATORS_BY_KIND = {
    "string": frozenset({PredicateOperator.EQUALS, PredicateOperator.NOT_EQUALS}),
    "integer": frozenset(
        {
            PredicateOperator.EQUALS,
            PredicateOperator.NOT_EQUALS,
            PredicateOperator.MINIMUM,
            PredicateOperator.MAXIMUM,
        }
    ),
    "boolean": frozenset({PredicateOperator.EQUALS, PredicateOperator.NOT_EQUALS}),
    "collection": frozenset(
        {
            PredicateOperator.CONTAINS,
            PredicateOperator.IS_EMPTY,
            PredicateOperator.IS_NON_EMPTY,
        }
    ),
    "date": frozenset(
        {
            PredicateOperator.EQUALS,
            PredicateOperator.NOT_EQUALS,
            PredicateOperator.ON_OR_BEFORE,
            PredicateOperator.ON_OR_AFTER,
        }
    ),
}


class ApplicabilityPredicate(ApplicabilityModel):
    field_path: str
    operator: PredicateOperator
    expected_value: PredicateValue = None

    @field_validator("field_path")
    @classmethod
    def field_path_must_be_allowlisted(cls, value: str) -> str:
        if value not in _FIELD_SPECS:
            raise ValueError("field path is not allowlisted")
        return value

    @model_validator(mode="after")
    def operator_and_value_must_match_field(self) -> ApplicabilityPredicate:
        spec = _FIELD_SPECS[self.field_path]
        if self.operator not in _OPERATORS_BY_KIND[spec.kind]:
            raise ValueError("operator is incompatible with field path")
        empty_operator = self.operator in {
            PredicateOperator.IS_EMPTY,
            PredicateOperator.IS_NON_EMPTY,
        }
        if empty_operator and self.expected_value is not None:
            raise ValueError("empty checks cannot have an expected value")
        if not empty_operator and self.expected_value is None:
            raise ValueError("operator requires an expected value")
        _validate_expected_value(spec.kind, self.expected_value)
        return self


class RuleScope(ApplicabilityModel):
    scope_type: Literal["global", "college", "department", "program"]
    scope_targets: tuple[str, ...] = ()
    parent_college: str | None = None

    @field_validator("scope_targets")
    @classmethod
    def targets_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        _validate_sorted_unique_strings(values, "scope targets")
        return values

    @field_validator("parent_college")
    @classmethod
    def parent_college_must_be_explicit(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_trimmed(value, "parent college")
        return value

    @model_validator(mode="after")
    def global_and_targeted_scope_must_reconcile(self) -> RuleScope:
        if self.scope_type == "global" and (self.scope_targets or self.parent_college):
            raise ValueError("global scope cannot have targets")
        if self.scope_type != "global" and not (self.scope_targets or self.parent_college):
            raise ValueError("targeted scope requires a target or parent college")
        return self


class OfficialEvidenceBinding(ApplicabilityModel):
    document_id: str
    source_kb_sha256: str
    source_pdf_sha256: str
    fact_id: str
    source_pages: tuple[int, ...]
    fact_text_sha256: str

    @field_validator("document_id", "fact_id")
    @classmethod
    def identifiers_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value, "evidence identifier")
        return value

    @field_validator("source_kb_sha256", "source_pdf_sha256", "fact_text_sha256")
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("evidence hash must be lowercase SHA-256")
        return value

    @field_validator("source_pages")
    @classmethod
    def pages_must_be_canonical(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if not values or any(value <= 0 for value in values):
            raise ValueError("evidence pages must be positive and non-empty")
        if values != tuple(sorted(set(values))):
            raise ValueError("evidence pages must be sorted and unique")
        return values


class ApplicabilityRule(ApplicabilityModel):
    schema_version: Literal["1.0"] = APPLICABILITY_RULE_SCHEMA_VERSION
    rule_id: str
    mode: LogicalMode
    predicates: tuple[ApplicabilityPredicate, ...] = Field(min_length=1)
    scope: RuleScope
    evidence_bindings: tuple[OfficialEvidenceBinding, ...] = Field(min_length=1)
    annotation_note: str

    @field_validator("rule_id", "annotation_note")
    @classmethod
    def strings_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value, "rule value")
        return value

    @model_validator(mode="after")
    def predicates_and_bindings_must_be_unique(self) -> ApplicabilityRule:
        predicate_keys = tuple(
            (predicate.field_path, predicate.operator.value) for predicate in self.predicates
        )
        binding_keys = tuple(
            (binding.document_id, binding.fact_id) for binding in self.evidence_bindings
        )
        if len(predicate_keys) != len(set(predicate_keys)):
            raise ValueError("rule predicates must be unique")
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("evidence bindings must be unique")
        return self


class PredicateOutcome(ApplicabilityModel):
    field_path: str
    operator: PredicateOperator
    status: ApplicabilityStatus


class OfficialEvidenceReference(ApplicabilityModel):
    document_id: str
    fact_id: str
    source_pages: tuple[int, ...]
    role: EvidenceRole


class ApplicabilityDecision(ApplicabilityModel):
    schema_version: Literal["1.0"] = APPLICABILITY_DECISION_SCHEMA_VERSION
    rule_id: str
    status: ApplicabilityStatus
    predicate_outcomes: tuple[PredicateOutcome, ...]
    missing_profile_fields: tuple[str, ...] = ()
    diagnostics: tuple[ApplicabilityDiagnostic, ...] = ()
    official_evidence: tuple[OfficialEvidenceReference, ...]
    scope_status: ApplicabilityStatus
    document_id: str
    source_kb_sha256: str
    source_pdf_sha256: str


def evaluate_applicability(
    profile: ApplicantProfile,
    intent: QueryIntent,
    evidence_pack: EvidencePack,
    rule: ApplicabilityRule,
) -> ApplicabilityDecision:
    """Execute one reviewed rule against detached, validated inputs."""

    profile, intent, evidence_pack, rule = _revalidate_inputs(profile, intent, evidence_pack, rule)
    if intent.query != evidence_pack.request.query:
        raise ApplicabilityError("applicability inputs are inconsistent")

    evidence_refs, evidence_missing = _bind_official_evidence(evidence_pack, rule)
    outcomes, missing_fields = _evaluate_predicates(profile, rule.predicates)
    scope_status, scope_diagnostics = _evaluate_scope(profile, intent, rule.scope)
    diagnostics = list(scope_diagnostics)
    if missing_fields:
        diagnostics.append(ApplicabilityDiagnostic.MISSING_PROFILE_FACT)
    if evidence_missing:
        diagnostics.append(ApplicabilityDiagnostic.MISSING_OFFICIAL_EVIDENCE)

    predicate_status = _combine_predicates(rule.mode, outcomes)
    status = _combine_with_scope(predicate_status, scope_status)
    if evidence_missing:
        status = ApplicabilityStatus.NEEDS_INFORMATION

    runtime = evidence_pack.runtime
    return ApplicabilityDecision(
        rule_id=rule.rule_id,
        status=status,
        predicate_outcomes=outcomes,
        missing_profile_fields=missing_fields,
        diagnostics=tuple(sorted(set(diagnostics), key=lambda value: value.value)),
        official_evidence=evidence_refs,
        scope_status=scope_status,
        document_id=runtime.document_id,
        source_kb_sha256=runtime.source_kb_sha256,
        source_pdf_sha256=runtime.source_pdf_sha256,
    )


def canonical_applicability_rule_bytes(rule: ApplicabilityRule) -> bytes:
    return _canonical_model_bytes(rule, ApplicabilityRule, "Applicability rule")


def canonical_applicability_decision_bytes(decision: ApplicabilityDecision) -> bytes:
    return _canonical_model_bytes(decision, ApplicabilityDecision, "Applicability decision")


def load_applicability_rule_bytes(raw_bytes: bytes) -> ApplicabilityRule:
    """Load one rule from strict JSON without exposing supplied content in errors."""

    return _load_model_bytes(
        raw_bytes,
        ApplicabilityRule,
        SUPPORTED_APPLICABILITY_RULE_SCHEMA_VERSIONS,
        "Applicability rule",
    )


def load_applicability_rule(path_value: str | Path) -> ApplicabilityRule:
    """Load one rule only from a regular, non-symlinked file."""

    return _load_model_path(path_value, load_applicability_rule_bytes, "Applicability rule")


def load_applicability_decision_bytes(raw_bytes: bytes) -> ApplicabilityDecision:
    """Load one deterministic decision from strict JSON."""

    return _load_model_bytes(
        raw_bytes,
        ApplicabilityDecision,
        SUPPORTED_APPLICABILITY_DECISION_SCHEMA_VERSIONS,
        "Applicability decision",
    )


def load_applicability_decision(path_value: str | Path) -> ApplicabilityDecision:
    """Load one decision only from a regular, non-symlinked file."""

    return _load_model_path(path_value, load_applicability_decision_bytes, "Applicability decision")


def _revalidate_inputs(
    profile: ApplicantProfile,
    intent: QueryIntent,
    evidence_pack: EvidencePack,
    rule: ApplicabilityRule,
) -> tuple[ApplicantProfile, QueryIntent, EvidencePack, ApplicabilityRule]:
    try:
        return (
            ApplicantProfile.model_validate(profile.model_dump(mode="json")),
            QueryIntent.model_validate(intent.model_dump(mode="json")),
            EvidencePack.model_validate(evidence_pack.model_dump(mode="json")),
            ApplicabilityRule.model_validate(rule.model_dump(mode="json")),
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise ApplicabilityError("applicability inputs are invalid or unsupported") from None


def _bind_official_evidence(
    evidence_pack: EvidencePack, rule: ApplicabilityRule
) -> tuple[tuple[OfficialEvidenceReference, ...], bool]:
    runtime = evidence_pack.runtime
    primary = {item.fact_id: item for item in evidence_pack.primary_evidence}
    attached = {item.fact_id: item for item in evidence_pack.attached_reference_evidence}
    references: list[OfficialEvidenceReference] = []
    missing = False
    for binding in rule.evidence_bindings:
        if (
            binding.document_id != runtime.document_id
            or binding.source_kb_sha256 != runtime.source_kb_sha256
            or binding.source_pdf_sha256 != runtime.source_pdf_sha256
        ):
            raise ApplicabilityError("official evidence binding is inconsistent")
        record = primary.get(binding.fact_id)
        role = EvidenceRole.PRIMARY
        if record is None:
            record = attached.get(binding.fact_id)
            role = EvidenceRole.ATTACHED
        if record is None:
            missing = True
            continue
        if (
            record.document_id != binding.document_id
            or record.source_pages != binding.source_pages
            or _sha256_text(record.text) != binding.fact_text_sha256
            or not _evidence_scope_matches_rule(record, rule.scope)
        ):
            raise ApplicabilityError("official evidence binding is inconsistent")
        references.append(
            OfficialEvidenceReference(
                document_id=record.document_id,
                fact_id=record.fact_id,
                source_pages=record.source_pages,
                role=role,
            )
        )
    return tuple(references), missing


def _evaluate_predicates(
    profile: ApplicantProfile, predicates: tuple[ApplicabilityPredicate, ...]
) -> tuple[tuple[PredicateOutcome, ...], tuple[str, ...]]:
    outcomes: list[PredicateOutcome] = []
    missing: set[str] = set()
    for predicate in predicates:
        value = _profile_value(profile, predicate.field_path)
        if value is None:
            status = ApplicabilityStatus.NEEDS_INFORMATION
            missing.add(predicate.field_path)
        else:
            status = _predicate_status(value, predicate)
        outcomes.append(
            PredicateOutcome(
                field_path=predicate.field_path,
                operator=predicate.operator,
                status=status,
            )
        )
    return tuple(outcomes), tuple(sorted(missing))


def _profile_value(profile: ApplicantProfile, path: str) -> Any:
    value: Any = profile
    for segment in _FIELD_SPECS[path].getter:
        if segment == "first":
            if value is None or not value:
                return None
            value = value[0]
        else:
            value = getattr(value, segment)
    if isinstance(value, Enum):
        return value.value
    return value


def _predicate_status(value: Any, predicate: ApplicabilityPredicate) -> ApplicabilityStatus:
    expected: Any = predicate.expected_value
    if _FIELD_SPECS[predicate.field_path].kind == "date":
        expected = date.fromisoformat(str(expected))
    operator = predicate.operator
    checks = {
        PredicateOperator.EQUALS: lambda: value == expected,
        PredicateOperator.NOT_EQUALS: lambda: value != expected,
        PredicateOperator.CONTAINS: lambda: expected in value,
        PredicateOperator.MINIMUM: lambda: value >= expected,
        PredicateOperator.MAXIMUM: lambda: value <= expected,
        PredicateOperator.ON_OR_BEFORE: lambda: value <= expected,
        PredicateOperator.ON_OR_AFTER: lambda: value >= expected,
        PredicateOperator.IS_EMPTY: lambda: len(value) == 0,
        PredicateOperator.IS_NON_EMPTY: lambda: len(value) > 0,
    }
    return (
        ApplicabilityStatus.CONFIRMED if checks[operator]() else ApplicabilityStatus.NOT_APPLICABLE
    )


def _combine_predicates(
    mode: LogicalMode, outcomes: tuple[PredicateOutcome, ...]
) -> ApplicabilityStatus:
    statuses = tuple(outcome.status for outcome in outcomes)
    if mode is LogicalMode.ALL:
        if ApplicabilityStatus.NOT_APPLICABLE in statuses:
            return ApplicabilityStatus.NOT_APPLICABLE
        if all(status is ApplicabilityStatus.CONFIRMED for status in statuses):
            return ApplicabilityStatus.CONFIRMED
        return ApplicabilityStatus.NEEDS_INFORMATION
    if ApplicabilityStatus.CONFIRMED in statuses:
        return ApplicabilityStatus.CONFIRMED
    if all(status is ApplicabilityStatus.NOT_APPLICABLE for status in statuses):
        return ApplicabilityStatus.NOT_APPLICABLE
    return ApplicabilityStatus.NEEDS_INFORMATION


def _evaluate_scope(
    profile: ApplicantProfile, intent: QueryIntent, scope: RuleScope
) -> tuple[ApplicabilityStatus, tuple[ApplicabilityDiagnostic, ...]]:
    if scope.scope_type == "global":
        return ApplicabilityStatus.CONFIRMED, ()

    profile_targets = _optional_set(profile.target_application.department_or_program)
    query_targets = set(intent.requested_scope.department_or_program_targets)
    profile_colleges = _optional_set(profile.target_application.graduate_school_or_college)
    query_colleges = set(intent.requested_scope.parent_college_values)
    if _known_disjoint(profile_targets, query_targets) or _known_disjoint(
        profile_colleges, query_colleges
    ):
        return (
            ApplicabilityStatus.NEEDS_INFORMATION,
            (ApplicabilityDiagnostic.SCOPE_INPUT_CONFLICT,),
        )

    supplied_targets = profile_targets | query_targets
    supplied_colleges = profile_colleges | query_colleges
    expected_targets = set(scope.scope_targets)
    if scope.scope_type == "college":
        expected_colleges = expected_targets | _optional_set(scope.parent_college)
        return _match_scope(expected_colleges, supplied_colleges)

    components = []
    if expected_targets:
        components.append(_match_scope(expected_targets, supplied_targets)[0])
    if scope.parent_college:
        components.append(_match_scope({scope.parent_college}, supplied_colleges)[0])
    return _combine_scope_components(tuple(components))


def _match_scope(
    expected: set[str], supplied: set[str]
) -> tuple[ApplicabilityStatus, tuple[ApplicabilityDiagnostic, ...]]:
    if not supplied:
        return ApplicabilityStatus.NEEDS_INFORMATION, (ApplicabilityDiagnostic.MISSING_SCOPE,)
    if expected & supplied:
        return ApplicabilityStatus.CONFIRMED, ()
    return ApplicabilityStatus.NOT_APPLICABLE, ()


def _combine_with_scope(
    predicate_status: ApplicabilityStatus, scope_status: ApplicabilityStatus
) -> ApplicabilityStatus:
    if ApplicabilityStatus.NOT_APPLICABLE in {predicate_status, scope_status}:
        return ApplicabilityStatus.NOT_APPLICABLE
    if predicate_status is scope_status is ApplicabilityStatus.CONFIRMED:
        return ApplicabilityStatus.CONFIRMED
    return ApplicabilityStatus.NEEDS_INFORMATION


def _combine_scope_components(
    statuses: tuple[ApplicabilityStatus, ...],
) -> tuple[ApplicabilityStatus, tuple[ApplicabilityDiagnostic, ...]]:
    if ApplicabilityStatus.NOT_APPLICABLE in statuses:
        return ApplicabilityStatus.NOT_APPLICABLE, ()
    if statuses and all(status is ApplicabilityStatus.CONFIRMED for status in statuses):
        return ApplicabilityStatus.CONFIRMED, ()
    return ApplicabilityStatus.NEEDS_INFORMATION, (ApplicabilityDiagnostic.MISSING_SCOPE,)


def _evidence_scope_matches_rule(record: Any, scope: RuleScope) -> bool:
    if scope.scope_type == "global":
        return record.scope_type == "global"
    if record.scope_type != scope.scope_type:
        return False
    if scope.scope_targets and not set(scope.scope_targets).issubset(record.scope_targets):
        return False
    return scope.parent_college is None or scope.parent_college == record.parent_college


def _validate_expected_value(kind: str, value: PredicateValue) -> None:
    if value is None:
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("predicate value must be finite")
    if kind in {"string", "collection"}:
        if not isinstance(value, str) or isinstance(value, bool):
            raise ValueError("predicate value must be a string")
        _validate_trimmed(value, "predicate value")
    elif kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("predicate value must be an integer")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError("predicate value must be a boolean")
    elif kind == "date":
        if not isinstance(value, str):
            raise ValueError("date predicate value must be an ISO date string")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("date predicate value must be an ISO date string") from None


def _canonical_model_bytes(value: Any, model_type: type[BaseModel], name: str) -> bytes:
    try:
        if not isinstance(value, model_type):
            raise TypeError
        validated = model_type.model_validate(value.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValidationError, ValueError):
        raise ApplicabilityError(f"{name} is invalid or unsupported") from None
    return f"{serialized}\n".encode("utf-8")


def _load_model_bytes(
    raw_bytes: bytes,
    model_type: type[Any],
    supported_versions: frozenset[str],
    name: str,
) -> Any:
    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        if not isinstance(payload, dict) or payload.get("schema_version") not in supported_versions:
            raise ValueError
        return model_type.model_validate(payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValidationError,
        ValueError,
    ):
        raise ApplicabilityError(f"{name} bytes are invalid or unsupported") from None


def _load_model_path(path_value: Any, loader: Any, name: str) -> Any:
    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError
        raw_bytes = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise ApplicabilityError(f"{name} file is unavailable or unsafe") from None
    return loader(raw_bytes)


def _reject_constant(_: str) -> Any:
    raise ValueError("non-finite JSON numbers are not supported")


def _optional_set(value: str | None) -> set[str]:
    return {value} if value is not None else set()


def _known_disjoint(left: set[str], right: set[str]) -> bool:
    return bool(left and right and left.isdisjoint(right))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_trimmed(value: str, name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty and trimmed")


def _validate_sorted_unique_strings(values: tuple[str, ...], name: str) -> None:
    for value in values:
        _validate_trimmed(value, name)
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{name} must be sorted and unique")
