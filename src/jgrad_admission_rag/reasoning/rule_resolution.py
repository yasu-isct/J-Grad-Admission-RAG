"""Deterministic specificity and explicit override resolution for reviewed rules."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .applicability import (
    ApplicabilityDecision,
    ApplicabilityDiagnostic,
    ApplicabilityRule,
    ApplicabilityStatus,
    OfficialEvidenceReference,
    RuleScope,
)

RULE_PRECEDENCE_POLICY_SCHEMA_VERSION = "1.0"
RULE_RESOLUTION_SCHEMA_VERSION = "1.0"
SUPPORTED_RULE_PRECEDENCE_POLICY_SCHEMA_VERSIONS = frozenset(
    {RULE_PRECEDENCE_POLICY_SCHEMA_VERSION}
)
SUPPORTED_RULE_RESOLUTION_SCHEMA_VERSIONS = frozenset({RULE_RESOLUTION_SCHEMA_VERSION})

_SPECIFICITY = {"global": 0, "college": 1, "department": 2, "program": 3}
_DISPOSITION_ORDER = {"active": 0, "overridden": 1, "pending": 2, "not_applicable": 3}


class RuleResolutionError(Exception):
    """Raised when reviewed resolution inputs cannot be reconciled safely."""


class RuleResolutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResolutionDisposition(str, Enum):
    ACTIVE = "active"
    OVERRIDDEN = "overridden"
    PENDING = "pending"
    NOT_APPLICABLE = "not_applicable"


class RuleSubjectAssignment(RuleResolutionModel):
    rule_id: str
    subject_key: str

    @field_validator("rule_id", "subject_key")
    @classmethod
    def strings_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value


class OverrideEdge(RuleResolutionModel):
    subject_key: str
    overrider_rule_id: str
    overridden_rule_id: str
    rationale: str = Field(max_length=500)

    @field_validator("subject_key", "overrider_rule_id", "overridden_rule_id", "rationale")
    @classmethod
    def strings_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @model_validator(mode="after")
    def endpoints_must_be_distinct(self) -> OverrideEdge:
        if self.overrider_rule_id == self.overridden_rule_id:
            raise ValueError("override edge cannot reference one rule twice")
        return self


class RulePrecedencePolicy(RuleResolutionModel):
    schema_version: Literal["1.0"] = RULE_PRECEDENCE_POLICY_SCHEMA_VERSION
    policy_id: str
    subjects: tuple[RuleSubjectAssignment, ...] = Field(min_length=1)
    override_edges: tuple[OverrideEdge, ...] = ()

    @field_validator("policy_id")
    @classmethod
    def policy_id_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @model_validator(mode="after")
    def assignments_and_edges_must_be_canonical(self) -> RulePrecedencePolicy:
        subject_keys = tuple((item.rule_id, item.subject_key) for item in self.subjects)
        if subject_keys != tuple(sorted(subject_keys)) or len(
            {item[0] for item in subject_keys}
        ) != len(subject_keys):
            raise ValueError("policy subjects must be sorted and uniquely assigned")
        edge_keys = tuple(
            (edge.subject_key, edge.overrider_rule_id, edge.overridden_rule_id)
            for edge in self.override_edges
        )
        if edge_keys != tuple(sorted(edge_keys)) or len(set(edge_keys)) != len(edge_keys):
            raise ValueError("override edges must be sorted and unique")
        assignments = {item.rule_id: item.subject_key for item in self.subjects}
        for edge in self.override_edges:
            if (
                assignments.get(edge.overrider_rule_id) != edge.subject_key
                or assignments.get(edge.overridden_rule_id) != edge.subject_key
            ):
                raise ValueError("override endpoints must share the declared subject")
        _validate_acyclic(self.override_edges)
        return self


class ActivatedOverride(RuleResolutionModel):
    subject_key: str
    overrider_rule_id: str
    rationale: str = Field(max_length=500)

    @field_validator("subject_key", "overrider_rule_id", "rationale")
    @classmethod
    def strings_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value


class RuleResolutionEntry(RuleResolutionModel):
    rule_id: str
    subject_key: str
    original_status: ApplicabilityStatus
    scope: RuleScope
    disposition: ResolutionDisposition
    activated_override: ActivatedOverride | None = None
    official_evidence: tuple[OfficialEvidenceReference, ...]

    @field_validator("rule_id", "subject_key")
    @classmethod
    def identifiers_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @model_validator(mode="after")
    def disposition_must_reconcile(self) -> RuleResolutionEntry:
        if (self.disposition is ResolutionDisposition.OVERRIDDEN) != (
            self.activated_override is not None
        ):
            raise ValueError("resolution entry override details do not reconcile")
        if self.activated_override is not None and (
            self.activated_override.subject_key != self.subject_key
            or self.activated_override.overrider_rule_id == self.rule_id
        ):
            raise ValueError("resolution entry override details do not reconcile")
        evidence_keys = tuple(
            (item.document_id, item.fact_id, item.role) for item in self.official_evidence
        )
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("resolution evidence must be unique")
        expected = {
            ApplicabilityStatus.NEEDS_INFORMATION: ResolutionDisposition.PENDING,
            ApplicabilityStatus.NOT_APPLICABLE: ResolutionDisposition.NOT_APPLICABLE,
        }.get(self.original_status)
        if expected is not None and self.disposition is not expected:
            raise ValueError("non-confirmed rule disposition does not reconcile")
        if self.original_status is ApplicabilityStatus.CONFIRMED and self.disposition not in {
            ResolutionDisposition.ACTIVE,
            ResolutionDisposition.OVERRIDDEN,
        }:
            raise ValueError("confirmed rule disposition does not reconcile")
        return self


class RuleResolution(RuleResolutionModel):
    schema_version: Literal["1.0"] = RULE_RESOLUTION_SCHEMA_VERSION
    policy_id: str
    document_id: str
    source_kb_sha256: str
    source_pdf_sha256: str
    entries: tuple[RuleResolutionEntry, ...] = Field(min_length=1)
    active_rule_ids: tuple[str, ...]
    overridden_rule_ids: tuple[str, ...]
    pending_rule_ids: tuple[str, ...]
    not_applicable_rule_ids: tuple[str, ...]

    @field_validator("policy_id", "document_id")
    @classmethod
    def identifiers_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @field_validator("source_kb_sha256", "source_pdf_sha256")
    @classmethod
    def source_hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value

    @model_validator(mode="after")
    def entries_and_lists_must_reconcile(self) -> RuleResolution:
        entry_ids = tuple(entry.rule_id for entry in self.entries)
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("resolution entries must have unique rules")
        entry_by_id = {entry.rule_id: entry for entry in self.entries}
        if any(
            evidence.document_id != self.document_id
            for entry in self.entries
            for evidence in entry.official_evidence
        ):
            raise ValueError("resolution evidence document does not reconcile")
        for entry in self.entries:
            if (
                entry.original_status is ApplicabilityStatus.CONFIRMED
                and not entry.official_evidence
            ):
                raise ValueError("confirmed resolution entry must preserve official evidence")
            if entry.activated_override is None:
                continue
            overrider = entry_by_id.get(entry.activated_override.overrider_rule_id)
            if (
                overrider is None
                or overrider.subject_key != entry.subject_key
                or overrider.original_status is not ApplicabilityStatus.CONFIRMED
                or not _is_proven_narrower(overrider.scope, entry.scope)
            ):
                raise ValueError("resolution override reference does not reconcile")
        expected_order = tuple(sorted(self.entries, key=_entry_sort_key))
        if self.entries != expected_order:
            raise ValueError("resolution entries are not canonical")
        expected_lists = {
            ResolutionDisposition.ACTIVE: self.active_rule_ids,
            ResolutionDisposition.OVERRIDDEN: self.overridden_rule_ids,
            ResolutionDisposition.PENDING: self.pending_rule_ids,
            ResolutionDisposition.NOT_APPLICABLE: self.not_applicable_rule_ids,
        }
        for disposition, actual in expected_lists.items():
            expected = tuple(
                sorted(entry.rule_id for entry in self.entries if entry.disposition is disposition)
            )
            if actual != expected:
                raise ValueError("resolution rule lists do not reconcile")
        return self


def resolve_rule_precedence(
    rules: tuple[ApplicabilityRule, ...],
    decisions: tuple[ApplicabilityDecision, ...],
    policy: RulePrecedencePolicy,
) -> RuleResolution:
    """Resolve only reviewed, direct overrides among fully validated rule decisions."""

    rules, decisions, policy = _revalidate_inputs(rules, decisions, policy)
    rule_by_id = _unique_by_id(rules, "rule_id")
    decision_by_id = _unique_by_id(decisions, "rule_id")
    if not rule_by_id or set(rule_by_id) != set(decision_by_id):
        raise RuleResolutionError("rule resolution inputs are invalid or inconsistent")
    assignments = {item.rule_id: item.subject_key for item in policy.subjects}
    if set(assignments) != set(rule_by_id):
        raise RuleResolutionError("rule resolution inputs are invalid or inconsistent")

    source_identity: tuple[str, str, str] | None = None
    for rule_id, rule in rule_by_id.items():
        decision = decision_by_id[rule_id]
        if decision.logical_mode is not rule.mode:
            raise RuleResolutionError("rule resolution inputs are invalid or inconsistent")
        predicate_keys = tuple(
            (predicate.field_path, predicate.operator) for predicate in rule.predicates
        )
        outcome_keys = tuple(
            (outcome.field_path, outcome.operator) for outcome in decision.predicate_outcomes
        )
        if predicate_keys != outcome_keys:
            raise RuleResolutionError("rule resolution inputs are invalid or inconsistent")
        identity = (
            decision.document_id,
            decision.source_kb_sha256,
            decision.source_pdf_sha256,
        )
        if source_identity is None:
            source_identity = identity
        elif identity != source_identity:
            raise RuleResolutionError("rule resolution inputs are invalid or inconsistent")
        _validate_evidence_reconciliation(rule, decision, identity)

    for edge in policy.override_edges:
        try:
            overrider = rule_by_id[edge.overrider_rule_id]
            overridden = rule_by_id[edge.overridden_rule_id]
        except KeyError:
            raise RuleResolutionError(
                "rule resolution inputs are invalid or inconsistent"
            ) from None
        if not _is_proven_narrower(overrider.scope, overridden.scope):
            raise RuleResolutionError("rule resolution inputs are invalid or inconsistent")

    activated_by_target: dict[str, OverrideEdge] = {}
    for edge in policy.override_edges:
        if (
            decision_by_id[edge.overrider_rule_id].status is ApplicabilityStatus.CONFIRMED
            and decision_by_id[edge.overridden_rule_id].status is ApplicabilityStatus.CONFIRMED
        ):
            if edge.overridden_rule_id in activated_by_target:
                raise RuleResolutionError("rule resolution inputs are ambiguous")
            activated_by_target[edge.overridden_rule_id] = edge

    entries: list[RuleResolutionEntry] = []
    for rule_id, rule in rule_by_id.items():
        decision = decision_by_id[rule_id]
        activated = activated_by_target.get(rule_id)
        if decision.status is ApplicabilityStatus.NEEDS_INFORMATION:
            disposition = ResolutionDisposition.PENDING
        elif decision.status is ApplicabilityStatus.NOT_APPLICABLE:
            disposition = ResolutionDisposition.NOT_APPLICABLE
        elif activated is None:
            disposition = ResolutionDisposition.ACTIVE
        else:
            disposition = ResolutionDisposition.OVERRIDDEN
        entries.append(
            RuleResolutionEntry(
                rule_id=rule_id,
                subject_key=assignments[rule_id],
                original_status=decision.status,
                scope=rule.scope,
                disposition=disposition,
                activated_override=(
                    ActivatedOverride(
                        subject_key=activated.subject_key,
                        overrider_rule_id=activated.overrider_rule_id,
                        rationale=activated.rationale,
                    )
                    if activated is not None
                    else None
                ),
                official_evidence=decision.official_evidence,
            )
        )
    entries_tuple = tuple(sorted(entries, key=_entry_sort_key))
    assert source_identity is not None
    return RuleResolution(
        policy_id=policy.policy_id,
        document_id=source_identity[0],
        source_kb_sha256=source_identity[1],
        source_pdf_sha256=source_identity[2],
        entries=entries_tuple,
        active_rule_ids=_ids_for(entries_tuple, ResolutionDisposition.ACTIVE),
        overridden_rule_ids=_ids_for(entries_tuple, ResolutionDisposition.OVERRIDDEN),
        pending_rule_ids=_ids_for(entries_tuple, ResolutionDisposition.PENDING),
        not_applicable_rule_ids=_ids_for(entries_tuple, ResolutionDisposition.NOT_APPLICABLE),
    )


def canonical_rule_precedence_policy_bytes(policy: RulePrecedencePolicy) -> bytes:
    return _canonical_model_bytes(policy, RulePrecedencePolicy, "Rule precedence policy")


def canonical_rule_resolution_bytes(resolution: RuleResolution) -> bytes:
    return _canonical_model_bytes(resolution, RuleResolution, "Rule resolution")


def load_rule_precedence_policy_bytes(raw_bytes: bytes) -> RulePrecedencePolicy:
    return _load_model_bytes(
        raw_bytes,
        RulePrecedencePolicy,
        SUPPORTED_RULE_PRECEDENCE_POLICY_SCHEMA_VERSIONS,
        "Rule precedence policy",
    )


def load_rule_precedence_policy(path_value: str | Path) -> RulePrecedencePolicy:
    return _load_model_path(path_value, load_rule_precedence_policy_bytes, "Rule precedence policy")


def load_rule_resolution_bytes(raw_bytes: bytes) -> RuleResolution:
    return _load_model_bytes(
        raw_bytes,
        RuleResolution,
        SUPPORTED_RULE_RESOLUTION_SCHEMA_VERSIONS,
        "Rule resolution",
    )


def load_rule_resolution(path_value: str | Path) -> RuleResolution:
    return _load_model_path(path_value, load_rule_resolution_bytes, "Rule resolution")


def _revalidate_inputs(
    rules: Any, decisions: Any, policy: Any
) -> tuple[tuple[ApplicabilityRule, ...], tuple[ApplicabilityDecision, ...], RulePrecedencePolicy]:
    try:
        if not isinstance(rules, tuple) or not isinstance(decisions, tuple):
            raise TypeError
        return (
            tuple(ApplicabilityRule.model_validate(item.model_dump(mode="json")) for item in rules),
            tuple(
                ApplicabilityDecision.model_validate(item.model_dump(mode="json"))
                for item in decisions
            ),
            RulePrecedencePolicy.model_validate(policy.model_dump(mode="json")),
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise RuleResolutionError("rule resolution inputs are invalid or unsupported") from None


def _unique_by_id(values: tuple[Any, ...], field: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        identifier = getattr(value, field)
        if identifier in result:
            raise RuleResolutionError("rule resolution inputs are invalid or inconsistent")
        result[identifier] = value
    return result


def _validate_evidence_reconciliation(
    rule: ApplicabilityRule,
    decision: ApplicabilityDecision,
    identity: tuple[str, str, str],
) -> None:
    binding_by_key = {(item.document_id, item.fact_id): item for item in rule.evidence_bindings}
    reference_keys: set[tuple[str, str]] = set()
    for reference in decision.official_evidence:
        key = (reference.document_id, reference.fact_id)
        binding = binding_by_key.get(key)
        if binding is None or reference.source_pages != binding.source_pages:
            raise RuleResolutionError("rule resolution inputs are invalid or inconsistent")
        reference_keys.add(key)
    for binding in rule.evidence_bindings:
        if (binding.document_id, binding.source_kb_sha256, binding.source_pdf_sha256) != identity:
            raise RuleResolutionError("rule resolution inputs are invalid or inconsistent")
    missing = ApplicabilityDiagnostic.MISSING_OFFICIAL_EVIDENCE in decision.diagnostics
    if not missing and reference_keys != set(binding_by_key):
        raise RuleResolutionError("rule resolution inputs are invalid or inconsistent")


def _is_proven_narrower(narrower: RuleScope, broader: RuleScope) -> bool:
    if _SPECIFICITY[narrower.scope_type] <= _SPECIFICITY[broader.scope_type]:
        return False
    if broader.scope_type == "global":
        return True
    if broader.scope_type == "college":
        colleges = set(broader.scope_targets)
        if broader.parent_college:
            colleges.add(broader.parent_college)
        return narrower.parent_college in colleges
    if broader.scope_type == "department" and narrower.scope_type == "program":
        return bool(set(broader.scope_targets).intersection(narrower.scope_targets)) and (
            broader.parent_college is None or broader.parent_college == narrower.parent_college
        )
    return False


def _validate_acyclic(edges: tuple[OverrideEdge, ...]) -> None:
    graph: dict[str, set[str]] = {}
    for edge in edges:
        graph.setdefault(edge.overrider_rule_id, set()).add(edge.overridden_rule_id)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("override edges must be acyclic")
        if node in visited:
            return
        visiting.add(node)
        for target in graph.get(node, set()):
            visit(target)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def _entry_sort_key(entry: RuleResolutionEntry) -> tuple[int, int, str]:
    return (
        _DISPOSITION_ORDER[entry.disposition.value],
        _SPECIFICITY[entry.scope.scope_type],
        entry.rule_id,
    )


def _ids_for(
    entries: tuple[RuleResolutionEntry, ...], disposition: ResolutionDisposition
) -> tuple[str, ...]:
    return tuple(sorted(entry.rule_id for entry in entries if entry.disposition is disposition))


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
        raise RuleResolutionError(f"{name} is invalid or unsupported") from None
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
        raise RuleResolutionError(f"{name} bytes are invalid or unsupported") from None


def _load_model_path(path_value: Any, loader: Any, name: str) -> Any:
    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError
        raw_bytes = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise RuleResolutionError(f"{name} file is unavailable or unsafe") from None
    return loader(raw_bytes)


def _reject_constant(_: str) -> Any:
    raise ValueError("non-finite JSON numbers are unsupported")


def _validate_trimmed(value: str) -> None:
    if not value or value != value.strip():
        raise ValueError("string must be non-empty and trimmed")


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("value must be lowercase SHA-256")
