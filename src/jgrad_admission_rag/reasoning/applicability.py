"""Deterministic applicability checks for human-reviewed admission rules.

This module executes typed rules. It deliberately does not derive rules from
guideline text and does not make final eligibility or admission decisions.
"""

from __future__ import annotations

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
    "DirectOfficialEvidence",
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
    "evaluate_applicability_with_direct_evidence",
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
    MULTIPLE_ACADEMIC_CREDENTIALS = "multiple_academic_credentials"


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
    "academic_credentials.first.institution_country_code": _FieldSpec(
        "string", ("academic_credentials", "first", "institution_country_code")
    ),
    "academic_credentials.first.degree_level": _FieldSpec(
        "string", ("academic_credentials", "first", "degree_level")
    ),
    "academic_credentials.first.credential_basis": _FieldSpec(
        "string", ("academic_credentials", "first", "credential_basis")
    ),
    "academic_credentials.first.completion_state": _FieldSpec(
        "string", ("academic_credentials", "first", "completion_state")
    ),
    "academic_credentials.first.years_of_education": _FieldSpec(
        "integer", ("academic_credentials", "first", "years_of_education")
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
    authoritative_fact_text_sha256: str

    @field_validator("document_id", "fact_id")
    @classmethod
    def identifiers_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value, "evidence identifier")
        return value

    @field_validator(
        "source_kb_sha256",
        "source_pdf_sha256",
        "authoritative_fact_text_sha256",
    )
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
            (
                predicate.field_path,
                predicate.operator.value,
                json.dumps(predicate.expected_value, ensure_ascii=False, sort_keys=True),
            )
            for predicate in self.predicates
        )
        binding_keys = tuple(
            (binding.document_id, binding.fact_id) for binding in self.evidence_bindings
        )
        if len(predicate_keys) != len(set(predicate_keys)):
            raise ValueError("rule predicates must be unique")
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("evidence bindings must be unique")
        if self.mode is LogicalMode.ALL:
            _validate_all_predicates_consistent(self.predicates)
        return self


class PredicateOutcome(ApplicabilityModel):
    field_path: str
    operator: PredicateOperator
    status: ApplicabilityStatus

    @model_validator(mode="after")
    def field_and_operator_must_be_supported(self) -> PredicateOutcome:
        spec = _FIELD_SPECS.get(self.field_path)
        if spec is None or self.operator not in _OPERATORS_BY_KIND[spec.kind]:
            raise ValueError("predicate outcome is unsupported")
        return self


class OfficialEvidenceReference(ApplicabilityModel):
    document_id: str
    fact_id: str
    source_pages: tuple[int, ...]
    role: EvidenceRole

    @field_validator("document_id", "fact_id")
    @classmethod
    def identifiers_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value, "evidence reference identifier")
        return value

    @field_validator("source_pages")
    @classmethod
    def pages_must_be_canonical(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if not values or any(value <= 0 for value in values):
            raise ValueError("evidence reference pages must be positive and non-empty")
        if values != tuple(sorted(set(values))):
            raise ValueError("evidence reference pages must be sorted and unique")
        return values


class DirectOfficialEvidence(ApplicabilityModel):
    """Exact plan-bound evidence with no retrieval request or ranking metadata."""

    document_id: str
    source_kb_sha256: str
    source_pdf_sha256: str
    official_evidence: tuple[OfficialEvidenceReference, ...] = Field(min_length=1)

    @field_validator("document_id")
    @classmethod
    def document_id_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value, "direct evidence document identifier")
        return value

    @field_validator("source_kb_sha256", "source_pdf_sha256")
    @classmethod
    def source_hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value, "direct evidence source hash")
        return value

    @model_validator(mode="after")
    def references_must_be_exact_primary_evidence(self) -> DirectOfficialEvidence:
        keys = tuple((item.document_id, item.fact_id, item.role) for item in self.official_evidence)
        if len(keys) != len(set(keys)):
            raise ValueError("direct official evidence must be unique")
        if any(
            item.document_id != self.document_id or item.role is not EvidenceRole.PRIMARY
            for item in self.official_evidence
        ):
            raise ValueError("direct official evidence identity or role does not reconcile")
        return self


class ApplicabilityDecision(ApplicabilityModel):
    schema_version: Literal["1.0"] = APPLICABILITY_DECISION_SCHEMA_VERSION
    rule_id: str
    logical_mode: LogicalMode
    status: ApplicabilityStatus
    predicate_outcomes: tuple[PredicateOutcome, ...] = Field(min_length=1)
    missing_profile_fields: tuple[str, ...] = ()
    diagnostics: tuple[ApplicabilityDiagnostic, ...] = ()
    official_evidence: tuple[OfficialEvidenceReference, ...]
    scope_status: ApplicabilityStatus
    document_id: str
    source_kb_sha256: str
    source_pdf_sha256: str

    @field_validator("rule_id", "document_id")
    @classmethod
    def identifiers_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value, "decision identifier")
        return value

    @field_validator("source_kb_sha256", "source_pdf_sha256")
    @classmethod
    def source_hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value, "decision source hash")
        return value

    @field_validator("missing_profile_fields")
    @classmethod
    def missing_fields_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(value not in _FIELD_SPECS for value in values):
            raise ValueError("missing profile field is not allowlisted")
        if values != tuple(sorted(set(values))):
            raise ValueError("missing profile fields must be sorted and unique")
        return values

    @field_validator("diagnostics")
    @classmethod
    def diagnostics_must_be_canonical(
        cls, values: tuple[ApplicabilityDiagnostic, ...]
    ) -> tuple[ApplicabilityDiagnostic, ...]:
        if values != tuple(sorted(set(values), key=lambda value: value.value)):
            raise ValueError("diagnostics must be sorted and unique")
        return values

    @model_validator(mode="after")
    def fields_must_reconcile(self) -> ApplicabilityDecision:
        _validate_decision_consistency(self)
        return self


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
    runtime = evidence_pack.runtime
    return _evaluate_applicability_core(
        profile,
        intent,
        rule,
        evidence_refs,
        evidence_missing,
        (runtime.document_id, runtime.source_kb_sha256, runtime.source_pdf_sha256),
    )


def evaluate_applicability_with_direct_evidence(
    profile: ApplicantProfile,
    intent: QueryIntent,
    direct_evidence: DirectOfficialEvidence,
    rule: ApplicabilityRule,
) -> ApplicabilityDecision:
    """Execute one reviewed rule using exact evidence without fabricating retrieval state."""

    profile, intent, direct_evidence, rule = _revalidate_direct_inputs(
        profile, intent, direct_evidence, rule
    )
    evidence_refs = _bind_direct_official_evidence(direct_evidence, rule)
    return _evaluate_applicability_core(
        profile,
        intent,
        rule,
        evidence_refs,
        False,
        (
            direct_evidence.document_id,
            direct_evidence.source_kb_sha256,
            direct_evidence.source_pdf_sha256,
        ),
    )


def _evaluate_applicability_core(
    profile: ApplicantProfile,
    intent: QueryIntent,
    rule: ApplicabilityRule,
    evidence_refs: tuple[OfficialEvidenceReference, ...],
    evidence_missing: bool,
    source_identity: tuple[str, str, str],
) -> ApplicabilityDecision:
    outcomes, missing_fields = _evaluate_predicates(profile, rule.predicates)
    scope_status, scope_diagnostics = _evaluate_scope(profile, intent, rule.scope)
    diagnostics = list(scope_diagnostics)
    if missing_fields:
        diagnostics.append(ApplicabilityDiagnostic.MISSING_PROFILE_FACT)
    if evidence_missing:
        diagnostics.append(ApplicabilityDiagnostic.MISSING_OFFICIAL_EVIDENCE)
    multiple_credentials = _uses_first_credential(rule) and bool(
        profile.academic_credentials and len(profile.academic_credentials) > 1
    )
    if multiple_credentials:
        diagnostics.append(ApplicabilityDiagnostic.MULTIPLE_ACADEMIC_CREDENTIALS)

    predicate_status = _combine_predicates(rule.mode, outcomes)
    status = _combine_with_scope(predicate_status, scope_status)
    if evidence_missing:
        status = ApplicabilityStatus.NEEDS_INFORMATION
    if multiple_credentials:
        status = ApplicabilityStatus.NEEDS_INFORMATION

    return ApplicabilityDecision(
        rule_id=rule.rule_id,
        logical_mode=rule.mode,
        status=status,
        predicate_outcomes=outcomes,
        missing_profile_fields=missing_fields,
        diagnostics=tuple(sorted(set(diagnostics), key=lambda value: value.value)),
        official_evidence=evidence_refs,
        scope_status=scope_status,
        document_id=source_identity[0],
        source_kb_sha256=source_identity[1],
        source_pdf_sha256=source_identity[2],
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


def _revalidate_direct_inputs(
    profile: ApplicantProfile,
    intent: QueryIntent,
    direct_evidence: DirectOfficialEvidence,
    rule: ApplicabilityRule,
) -> tuple[ApplicantProfile, QueryIntent, DirectOfficialEvidence, ApplicabilityRule]:
    try:
        if not isinstance(direct_evidence, DirectOfficialEvidence) or set(
            direct_evidence.__dict__
        ) != set(DirectOfficialEvidence.model_fields):
            raise TypeError
        return (
            ApplicantProfile.model_validate(profile.model_dump(mode="json")),
            QueryIntent.model_validate(intent.model_dump(mode="json")),
            DirectOfficialEvidence.model_validate(direct_evidence.model_dump(mode="json")),
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


def _bind_direct_official_evidence(
    direct_evidence: DirectOfficialEvidence,
    rule: ApplicabilityRule,
) -> tuple[OfficialEvidenceReference, ...]:
    identity = (
        direct_evidence.document_id,
        direct_evidence.source_kb_sha256,
        direct_evidence.source_pdf_sha256,
    )
    references = {item.fact_id: item for item in direct_evidence.official_evidence}
    if set(references) != {binding.fact_id for binding in rule.evidence_bindings}:
        raise ApplicabilityError("direct official evidence binding is inconsistent")
    ordered: list[OfficialEvidenceReference] = []
    for binding in rule.evidence_bindings:
        if (
            binding.document_id,
            binding.source_kb_sha256,
            binding.source_pdf_sha256,
        ) != identity:
            raise ApplicabilityError("direct official evidence binding is inconsistent")
        reference = references[binding.fact_id]
        if (
            reference.document_id != binding.document_id
            or reference.source_pages != binding.source_pages
        ):
            raise ApplicabilityError("direct official evidence binding is inconsistent")
        ordered.append(reference)
    return tuple(ordered)


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


def _uses_first_credential(rule: ApplicabilityRule) -> bool:
    return any(
        predicate.field_path.startswith("academic_credentials.first.")
        for predicate in rule.predicates
    )


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


def _validate_all_predicates_consistent(
    predicates: tuple[ApplicabilityPredicate, ...],
) -> None:
    by_path: dict[str, list[ApplicabilityPredicate]] = {}
    for predicate in predicates:
        by_path.setdefault(predicate.field_path, []).append(predicate)
    for field_path, field_predicates in by_path.items():
        expected_by_operator: dict[PredicateOperator, list[Any]] = {}
        for predicate in field_predicates:
            expected_by_operator.setdefault(predicate.operator, []).append(
                _normalized_expected(predicate)
            )
        equals_values = expected_by_operator.get(PredicateOperator.EQUALS, [])
        not_equals_values = expected_by_operator.get(PredicateOperator.NOT_EQUALS, [])
        if len(set(equals_values)) > 1 or set(equals_values).intersection(not_equals_values):
            raise ValueError("all-mode predicates are contradictory")
        equals = equals_values[0] if equals_values else None

        spec = _FIELD_SPECS[field_path]
        if spec.kind in {"integer", "date"}:
            lower_values = expected_by_operator.get(
                PredicateOperator.MINIMUM, []
            ) + expected_by_operator.get(PredicateOperator.ON_OR_AFTER, [])
            upper_values = expected_by_operator.get(
                PredicateOperator.MAXIMUM, []
            ) + expected_by_operator.get(PredicateOperator.ON_OR_BEFORE, [])
            lower = max(lower_values) if lower_values else None
            upper = min(upper_values) if upper_values else None
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("all-mode predicates are contradictory")
            if equals is not None and (
                (lower is not None and equals < lower) or (upper is not None and equals > upper)
            ):
                raise ValueError("all-mode predicates are contradictory")

        operators = set(expected_by_operator)
        if PredicateOperator.IS_EMPTY in operators and operators.intersection(
            {PredicateOperator.IS_NON_EMPTY, PredicateOperator.CONTAINS}
        ):
            raise ValueError("all-mode predicates are contradictory")


def _normalized_expected(predicate: ApplicabilityPredicate) -> Any:
    if _FIELD_SPECS[predicate.field_path].kind == "date" and predicate.expected_value is not None:
        return date.fromisoformat(str(predicate.expected_value))
    return predicate.expected_value


def _validate_decision_consistency(decision: ApplicabilityDecision) -> None:
    missing_from_outcomes = tuple(
        sorted(
            {
                outcome.field_path
                for outcome in decision.predicate_outcomes
                if outcome.status is ApplicabilityStatus.NEEDS_INFORMATION
            }
        )
    )
    if decision.missing_profile_fields != missing_from_outcomes:
        raise ValueError("decision missing profile fields do not reconcile")

    diagnostics = set(decision.diagnostics)
    has_missing_profile = ApplicabilityDiagnostic.MISSING_PROFILE_FACT in diagnostics
    if has_missing_profile != bool(decision.missing_profile_fields):
        raise ValueError("decision missing profile diagnostic does not reconcile")

    scope_diagnostics = diagnostics.intersection(
        {
            ApplicabilityDiagnostic.MISSING_SCOPE,
            ApplicabilityDiagnostic.SCOPE_INPUT_CONFLICT,
        }
    )
    if decision.scope_status is ApplicabilityStatus.NEEDS_INFORMATION:
        if len(scope_diagnostics) != 1:
            raise ValueError("decision scope diagnostics do not reconcile")
    elif scope_diagnostics:
        raise ValueError("decision scope diagnostics do not reconcile")

    missing_evidence = ApplicabilityDiagnostic.MISSING_OFFICIAL_EVIDENCE in diagnostics
    if not decision.official_evidence and not missing_evidence:
        raise ValueError("decision official evidence does not reconcile")
    evidence_keys = tuple(
        (reference.document_id, reference.fact_id, reference.role)
        for reference in decision.official_evidence
    )
    if len(evidence_keys) != len(set(evidence_keys)):
        raise ValueError("decision official evidence must be unique")
    if any(
        reference.document_id != decision.document_id for reference in decision.official_evidence
    ):
        raise ValueError("decision evidence document does not reconcile")

    predicate_status = _combine_predicates(decision.logical_mode, decision.predicate_outcomes)
    expected_status = _combine_with_scope(predicate_status, decision.scope_status)
    if missing_evidence:
        expected_status = ApplicabilityStatus.NEEDS_INFORMATION
    if ApplicabilityDiagnostic.MULTIPLE_ACADEMIC_CREDENTIALS in diagnostics:
        expected_status = ApplicabilityStatus.NEEDS_INFORMATION
    if decision.status is not expected_status:
        raise ValueError("decision status does not reconcile")


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


def _validate_trimmed(value: str, name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty and trimmed")


def _validate_sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be lowercase SHA-256")


def _validate_sorted_unique_strings(values: tuple[str, ...], name: str) -> None:
    for value in values:
        _validate_trimmed(value, name)
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{name} must be sorted and unique")
