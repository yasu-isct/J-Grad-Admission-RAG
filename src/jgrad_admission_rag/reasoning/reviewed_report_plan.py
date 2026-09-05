"""Reviewed, server-owned rule plans for one exact admission document."""

from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..schemas.document_identity import DocumentIdentity
from .applicability import ApplicabilityRule
from .query_intent import IntentCategory
from .rule_interaction import RuleInteractionPolicy
from .rule_resolution import RulePrecedencePolicy, _is_proven_narrower

REVIEWED_REPORT_PLAN_SCHEMA_VERSION = "1.0"
SUPPORTED_REVIEWED_REPORT_PLAN_SCHEMA_VERSIONS = frozenset({REVIEWED_REPORT_PLAN_SCHEMA_VERSION})
_SAFE_PLAN_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")


class ReviewedReportPlanError(Exception):
    """Raised when a reviewed report plan is invalid, unsupported, or unsafe."""


class PlanValidationFailure(str, Enum):
    """Stable classifications for focused validation assertions."""

    RULE_ORDER = "rule_order"
    CATEGORY_ORDER = "category_order"
    SOURCE_IDENTITY = "source_identity"
    SOURCE_KB = "source_kb"
    PRECEDENCE_SUBJECTS = "precedence_subjects"
    PRECEDENCE_ENDPOINT = "precedence_endpoint"
    PRECEDENCE_SCOPE = "precedence_scope"
    INTERACTION_ENDPOINT = "interaction_endpoint"
    INTERACTION_SUBJECT = "interaction_subject"


class _PlanInvariantError(ValueError):
    def __init__(self, failure: PlanValidationFailure) -> None:
        self.failure = failure
        super().__init__(failure.value)


class ReviewedReportPlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewedReportPlan(ReviewedReportPlanModel):
    """One reviewed, intentionally partial rulebook for one exact document."""

    schema_version: Literal["1.0"] = REVIEWED_REPORT_PLAN_SCHEMA_VERSION
    plan_id: str = Field(max_length=200)
    document_identity: DocumentIdentity
    rules: tuple[ApplicabilityRule, ...] = Field(min_length=1)
    precedence_policy: RulePrecedencePolicy
    interaction_policy: RuleInteractionPolicy
    covered_categories: tuple[IntentCategory, ...] = Field(min_length=1)
    coverage_status: Literal["partial_reviewed_rules"] = "partial_reviewed_rules"
    reviewed_coverage_statement: str = Field(min_length=1, max_length=500)
    limitation_statement: str = Field(min_length=1, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def nested_snapshots_must_be_revalidated(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        detached = dict(value)
        identity = detached.get("document_identity")
        if isinstance(identity, DocumentIdentity):
            detached["document_identity"] = identity.model_dump(mode="json")
        rules = detached.get("rules")
        if isinstance(rules, (list, tuple)):
            detached["rules"] = [
                item.model_dump(mode="json") if isinstance(item, ApplicabilityRule) else item
                for item in rules
            ]
        precedence = detached.get("precedence_policy")
        if isinstance(precedence, RulePrecedencePolicy):
            detached["precedence_policy"] = precedence.model_dump(mode="json")
        interaction = detached.get("interaction_policy")
        if isinstance(interaction, RuleInteractionPolicy):
            detached["interaction_policy"] = interaction.model_dump(mode="json")
        return detached

    @field_validator(
        "plan_id",
        "reviewed_coverage_statement",
        "limitation_statement",
        mode="before",
    )
    @classmethod
    def text_must_be_strict(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("plan text must be a string")
        return value

    @field_validator("plan_id", "reviewed_coverage_statement", "limitation_statement")
    @classmethod
    def text_must_be_explicit(cls, value: str) -> str:
        if not value or value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("plan text must be non-empty, trimmed, and printable")
        return value

    @field_validator("plan_id")
    @classmethod
    def plan_id_must_be_path_independent(cls, value: str) -> str:
        if _SAFE_PLAN_ID.fullmatch(value) is None:
            raise ValueError("plan ID is unsafe or unsupported")
        return value

    @field_validator("rules")
    @classmethod
    def rules_must_be_canonical(
        cls, values: tuple[ApplicabilityRule, ...]
    ) -> tuple[ApplicabilityRule, ...]:
        identifiers = tuple(rule.rule_id for rule in values)
        if identifiers != tuple(sorted(identifiers)) or len(identifiers) != len(set(identifiers)):
            raise _PlanInvariantError(PlanValidationFailure.RULE_ORDER)
        return values

    @field_validator("covered_categories")
    @classmethod
    def categories_must_be_canonical(
        cls, values: tuple[IntentCategory, ...]
    ) -> tuple[IntentCategory, ...]:
        keys = tuple(category.value for category in values)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise _PlanInvariantError(PlanValidationFailure.CATEGORY_ORDER)
        return values

    @model_validator(mode="after")
    def objects_must_reconcile(self) -> ReviewedReportPlan:
        _validate_cross_object_invariants(self)
        return self

    @property
    def source_kb_sha256(self) -> str:
        """Return the common reviewed KB binding without serializing a duplicate field."""

        return self.rules[0].evidence_bindings[0].source_kb_sha256


def canonical_reviewed_report_plan_bytes(plan: ReviewedReportPlan) -> bytes:
    """Serialize a fully revalidated plan as canonical finite UTF-8 JSON."""

    try:
        if not isinstance(plan, ReviewedReportPlan) or set(plan.__dict__) != set(
            ReviewedReportPlan.model_fields
        ):
            raise TypeError
        validated = ReviewedReportPlan.model_validate(plan.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValidationError, ValueError):
        raise ReviewedReportPlanError("reviewed report plan is invalid or unsupported") from None
    return f"{serialized}\n".encode("utf-8")


def load_reviewed_report_plan_bytes(raw_bytes: bytes) -> ReviewedReportPlan:
    """Load strict versioned plan JSON without echoing supplied content."""

    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") not in SUPPORTED_REVIEWED_REPORT_PLAN_SCHEMA_VERSIONS
        ):
            raise ValueError
        return ReviewedReportPlan.model_validate(payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValidationError,
        ValueError,
    ):
        raise ReviewedReportPlanError(
            "reviewed report plan bytes are invalid or unsupported"
        ) from None


def load_reviewed_report_plan(path_value: str | Path) -> ReviewedReportPlan:
    """Load a plan only from a regular non-symlink file."""

    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError
        raw_bytes = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise ReviewedReportPlanError(
            "reviewed report plan file is unavailable or unsafe"
        ) from None
    return load_reviewed_report_plan_bytes(raw_bytes)


def _validate_cross_object_invariants(plan: ReviewedReportPlan) -> None:
    rule_ids = {rule.rule_id for rule in plan.rules}
    expected_document = plan.document_identity.document_id
    expected_pdf = plan.document_identity.source_pdf_sha256
    source_kb_hashes: set[str] = set()
    for rule in plan.rules:
        for binding in rule.evidence_bindings:
            if (
                binding.document_id != expected_document
                or binding.source_pdf_sha256 != expected_pdf
            ):
                raise _PlanInvariantError(PlanValidationFailure.SOURCE_IDENTITY)
            source_kb_hashes.add(binding.source_kb_sha256)
    if len(source_kb_hashes) != 1:
        raise _PlanInvariantError(PlanValidationFailure.SOURCE_KB)

    assignments = {
        assignment.rule_id: assignment.subject_key for assignment in plan.precedence_policy.subjects
    }
    rule_by_id = {rule.rule_id: rule for rule in plan.rules}
    for edge in plan.precedence_policy.override_edges:
        if edge.overrider_rule_id not in rule_ids or edge.overridden_rule_id not in rule_ids:
            raise _PlanInvariantError(PlanValidationFailure.PRECEDENCE_ENDPOINT)
        if not _is_proven_narrower(
            rule_by_id[edge.overrider_rule_id].scope,
            rule_by_id[edge.overridden_rule_id].scope,
        ):
            raise _PlanInvariantError(PlanValidationFailure.PRECEDENCE_SCOPE)

    for interaction in plan.interaction_policy.interactions:
        left, right = interaction.rule_ids
        if left not in rule_ids or right not in rule_ids:
            raise _PlanInvariantError(PlanValidationFailure.INTERACTION_ENDPOINT)
    if set(assignments) != rule_ids:
        raise _PlanInvariantError(PlanValidationFailure.PRECEDENCE_SUBJECTS)
    for interaction in plan.interaction_policy.interactions:
        left, right = interaction.rule_ids
        if (
            assignments[left] != interaction.subject_key
            or assignments[right] != interaction.subject_key
        ):
            raise _PlanInvariantError(PlanValidationFailure.INTERACTION_SUBJECT)


def _reject_constant(_: str) -> Any:
    raise ValueError("non-finite JSON numbers are not supported")


__all__ = [
    "REVIEWED_REPORT_PLAN_SCHEMA_VERSION",
    "SUPPORTED_REVIEWED_REPORT_PLAN_SCHEMA_VERSIONS",
    "PlanValidationFailure",
    "ReviewedReportPlan",
    "ReviewedReportPlanError",
    "canonical_reviewed_report_plan_bytes",
    "load_reviewed_report_plan",
    "load_reviewed_report_plan_bytes",
]
