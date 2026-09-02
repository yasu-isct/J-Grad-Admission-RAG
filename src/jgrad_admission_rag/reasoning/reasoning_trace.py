"""Deterministic, evidence-linked audit traces for reviewed reasoning artifacts."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from .applicability import (
    APPLICABILITY_RULE_SCHEMA_VERSION,
    ApplicabilityDecision,
    ApplicabilityDiagnostic,
    ApplicabilityPredicate,
    ApplicabilityRule,
    ApplicabilityStatus,
    LogicalMode,
    OfficialEvidenceBinding,
    OfficialEvidenceReference,
    PredicateOperator,
    PredicateValue,
    RuleScope,
)
from .rule_interaction import (
    InteractionCertainty,
    InteractionDiagnostic,
    InteractionEndpoint,
    InteractionRelationship,
    InteractionWarningKind,
    RuleInteractionReport,
)
from .rule_resolution import ActivatedOverride, ResolutionDisposition, RuleResolutionEntry

REASONING_TRACE_SCHEMA_VERSION = "1.0"
SUPPORTED_REASONING_TRACE_SCHEMA_VERSIONS = frozenset({REASONING_TRACE_SCHEMA_VERSION})

__all__ = [
    "REASONING_TRACE_SCHEMA_VERSION",
    "SUPPORTED_REASONING_TRACE_SCHEMA_VERSIONS",
    "ApplicabilityTraceStep",
    "InteractionTraceOutcome",
    "InteractionTraceStep",
    "ReasoningTrace",
    "ReasoningTraceCoverage",
    "ReasoningTraceError",
    "ResolutionTraceStep",
    "ReviewedRuleSnapshot",
    "TracePredicateRecord",
    "TraceWarningCount",
    "build_reasoning_trace",
    "canonical_reasoning_trace_bytes",
    "load_reasoning_trace",
    "load_reasoning_trace_bytes",
]


class ReasoningTraceError(Exception):
    """Raised when reasoning artifacts cannot be reconciled without data leakage."""


class ReasoningTraceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InteractionTraceOutcome(str, Enum):
    COMPATIBLE = "compatible"
    CONFLICT = "conflict"
    AMBIGUITY = "ambiguity"
    UNREVIEWED_INTERACTION = "unreviewed_interaction"
    INACTIVE = "inactive"


class ReviewedPredicateSnapshot(ReasoningTraceModel):
    field_path: str
    operator: PredicateOperator
    expected_value: PredicateValue = None

    @model_validator(mode="after")
    def predicate_must_remain_valid(self) -> ReviewedPredicateSnapshot:
        ApplicabilityPredicate.model_validate(self.model_dump(mode="json"))
        return self


class ReviewedRuleSnapshot(ReasoningTraceModel):
    schema_version: Literal["1.0"] = APPLICABILITY_RULE_SCHEMA_VERSION
    rule_id: str
    mode: LogicalMode
    predicates: tuple[ReviewedPredicateSnapshot, ...] = Field(min_length=1)
    scope: RuleScope
    evidence_bindings: tuple[OfficialEvidenceBinding, ...] = Field(min_length=1)

    @field_validator("rule_id")
    @classmethod
    def rule_id_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @model_validator(mode="after")
    def reviewed_rule_contract_must_remain_valid(self) -> ReviewedRuleSnapshot:
        ApplicabilityRule(
            rule_id=self.rule_id,
            mode=self.mode,
            predicates=tuple(
                ApplicabilityPredicate.model_validate(item.model_dump(mode="json"))
                for item in self.predicates
            ),
            scope=self.scope,
            evidence_bindings=self.evidence_bindings,
            annotation_note="privacy-safe reviewed rule snapshot",
        )
        return self


class TracePredicateRecord(ReasoningTraceModel):
    field_path: str
    operator: PredicateOperator
    expected_value: PredicateValue = None
    outcome_status: ApplicabilityStatus

    @model_validator(mode="after")
    def predicate_must_remain_valid(self) -> TracePredicateRecord:
        ApplicabilityPredicate(
            field_path=self.field_path,
            operator=self.operator,
            expected_value=self.expected_value,
        )
        return self


class ApplicabilityTraceStep(ReasoningTraceModel):
    step_id: str
    dependencies: tuple[str, ...] = ()
    rule_id: str
    logical_mode: LogicalMode
    subject_key: str
    scope: RuleScope
    predicates: tuple[TracePredicateRecord, ...] = Field(min_length=1)
    status: ApplicabilityStatus
    scope_status: ApplicabilityStatus
    missing_profile_fields: tuple[str, ...]
    diagnostics: tuple[ApplicabilityDiagnostic, ...]
    official_evidence: tuple[OfficialEvidenceReference, ...]

    @field_validator("step_id", "rule_id", "subject_key")
    @classmethod
    def identifiers_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value


class ResolutionTraceStep(ReasoningTraceModel):
    step_id: str
    dependencies: tuple[str, ...]
    rule_id: str
    original_status: ApplicabilityStatus
    disposition: ResolutionDisposition
    subject_key: str
    scope: RuleScope
    activated_override: ActivatedOverride | None = None
    official_evidence: tuple[OfficialEvidenceReference, ...]

    @field_validator("step_id", "rule_id", "subject_key")
    @classmethod
    def identifiers_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value


class InteractionTraceStep(ReasoningTraceModel):
    step_id: str
    dependencies: tuple[str, str]
    pair_id: str
    subject_key: str
    rule_ids: tuple[str, str]
    outcome: InteractionTraceOutcome
    certainty: InteractionCertainty | None = None
    diagnostic: InteractionDiagnostic | None = None
    reviewed_rationale: str | None = Field(default=None, max_length=500)
    endpoints: tuple[InteractionEndpoint, InteractionEndpoint]

    @field_validator("step_id", "pair_id", "subject_key")
    @classmethod
    def identifiers_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value


class TraceWarningCount(ReasoningTraceModel):
    kind: InteractionWarningKind
    certainty: InteractionCertainty
    count: StrictInt = Field(ge=0)


class ReasoningTraceCoverage(ReasoningTraceModel):
    rule_count: StrictInt = Field(ge=1)
    applicability_step_count: StrictInt = Field(ge=1)
    resolution_step_count: StrictInt = Field(ge=1)
    interaction_step_count: StrictInt = Field(ge=0)
    interaction_warning_counts: tuple[TraceWarningCount, ...]
    interaction_analysis_complete: StrictBool


class ReasoningTrace(ReasoningTraceModel):
    schema_version: Literal["1.0"] = REASONING_TRACE_SCHEMA_VERSION
    trace_id: str
    document_id: str
    source_kb_sha256: str
    source_pdf_sha256: str
    source_rules: tuple[ReviewedRuleSnapshot, ...] = Field(min_length=1)
    source_decisions: tuple[ApplicabilityDecision, ...] = Field(min_length=1)
    source_interaction_report: RuleInteractionReport
    applicability_steps: tuple[ApplicabilityTraceStep, ...] = Field(min_length=1)
    resolution_steps: tuple[ResolutionTraceStep, ...] = Field(min_length=1)
    interaction_steps: tuple[InteractionTraceStep, ...]
    terminal_step_ids: tuple[str, ...]
    coverage: ReasoningTraceCoverage

    @field_validator("trace_id", "document_id")
    @classmethod
    def identifiers_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @field_validator("source_kb_sha256", "source_pdf_sha256")
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value

    @model_validator(mode="after")
    def graph_must_be_independently_recomputable(self) -> ReasoningTrace:
        try:
            _validate_trace_sources(
                self.source_rules,
                self.source_decisions,
                self.source_interaction_report,
            )
            expected = _derive_trace(
                self.source_rules,
                self.source_decisions,
                self.source_interaction_report,
            )
            identity = (
                self.source_interaction_report.document_id,
                self.source_interaction_report.source_kb_sha256,
                self.source_interaction_report.source_pdf_sha256,
            )
            if identity != (self.document_id, self.source_kb_sha256, self.source_pdf_sha256):
                raise ValueError
            if (
                self.applicability_steps != expected.applicability_steps
                or self.resolution_steps != expected.resolution_steps
                or self.interaction_steps != expected.interaction_steps
                or self.terminal_step_ids != expected.terminal_step_ids
                or self.coverage != expected.coverage
            ):
                raise ValueError
            _validate_graph(self)
        except (ReasoningTraceError, ValueError):
            raise ValueError("reasoning trace does not reconcile") from None
        return self


class _DerivedTrace(ReasoningTraceModel):
    applicability_steps: tuple[ApplicabilityTraceStep, ...]
    resolution_steps: tuple[ResolutionTraceStep, ...]
    interaction_steps: tuple[InteractionTraceStep, ...]
    terminal_step_ids: tuple[str, ...]
    coverage: ReasoningTraceCoverage


def build_reasoning_trace(
    trace_id: str,
    rules: tuple[ApplicabilityRule, ...],
    decisions: tuple[ApplicabilityDecision, ...],
    interaction_report: RuleInteractionReport,
) -> ReasoningTrace:
    """Project validated RSN-03/04/05 artifacts into one explicit audit graph."""

    try:
        _validate_trimmed(trace_id)
        validated_rules, validated_decisions, validated_report = _revalidate_inputs(
            rules, decisions, interaction_report
        )
        snapshots = tuple(sorted((_snapshot(rule) for rule in validated_rules), key=_rule_id))
        decisions_sorted = tuple(sorted(validated_decisions, key=_rule_id))
        _validate_trace_sources(snapshots, decisions_sorted, validated_report)
        derived = _derive_trace(snapshots, decisions_sorted, validated_report)
        return ReasoningTrace(
            trace_id=trace_id,
            document_id=validated_report.document_id,
            source_kb_sha256=validated_report.source_kb_sha256,
            source_pdf_sha256=validated_report.source_pdf_sha256,
            source_rules=snapshots,
            source_decisions=decisions_sorted,
            source_interaction_report=validated_report,
            **derived.model_dump(),
        )
    except (AttributeError, TypeError, ValidationError, ValueError, ReasoningTraceError):
        raise ReasoningTraceError("reasoning trace inputs are invalid or inconsistent") from None


def canonical_reasoning_trace_bytes(trace: ReasoningTrace) -> bytes:
    """Serialize a fully revalidated trace as canonical UTF-8 JSON with LF."""

    try:
        if not isinstance(trace, ReasoningTrace):
            raise TypeError
        validated = ReasoningTrace.model_validate(trace.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValidationError, ValueError, ReasoningTraceError):
        raise ReasoningTraceError("reasoning trace is invalid or unsupported") from None
    return f"{serialized}\n".encode("utf-8")


def load_reasoning_trace_bytes(raw_bytes: bytes) -> ReasoningTrace:
    """Load and independently recompute a canonical reasoning trace."""

    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") not in SUPPORTED_REASONING_TRACE_SCHEMA_VERSIONS
        ):
            raise ValueError
        return ReasoningTrace.model_validate(payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValidationError,
        ValueError,
        ReasoningTraceError,
    ):
        raise ReasoningTraceError("reasoning trace bytes are invalid or unsupported") from None


def load_reasoning_trace(path_value: str | Path) -> ReasoningTrace:
    """Load a trace only from a regular, non-symlinked file."""

    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError
        raw_bytes = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise ReasoningTraceError("reasoning trace file is unavailable or unsafe") from None
    return load_reasoning_trace_bytes(raw_bytes)


def _revalidate_inputs(
    rules: Any,
    decisions: Any,
    interaction_report: Any,
) -> tuple[tuple[ApplicabilityRule, ...], tuple[ApplicabilityDecision, ...], RuleInteractionReport]:
    if not isinstance(rules, tuple) or not isinstance(decisions, tuple):
        raise TypeError
    return (
        tuple(ApplicabilityRule.model_validate(item.model_dump(mode="json")) for item in rules),
        tuple(
            ApplicabilityDecision.model_validate(item.model_dump(mode="json")) for item in decisions
        ),
        RuleInteractionReport.model_validate(interaction_report.model_dump(mode="json")),
    )


def _snapshot(rule: ApplicabilityRule) -> ReviewedRuleSnapshot:
    return ReviewedRuleSnapshot(
        rule_id=rule.rule_id,
        mode=rule.mode,
        predicates=tuple(
            ReviewedPredicateSnapshot(
                field_path=item.field_path,
                operator=item.operator,
                expected_value=item.expected_value,
            )
            for item in rule.predicates
        ),
        scope=rule.scope,
        evidence_bindings=rule.evidence_bindings,
    )


def _validate_trace_sources(
    rules: tuple[ReviewedRuleSnapshot, ...],
    decisions: tuple[ApplicabilityDecision, ...],
    report: RuleInteractionReport,
) -> None:
    if not rules or not decisions:
        raise ReasoningTraceError("reasoning trace sources are invalid or inconsistent")
    if rules != tuple(sorted(rules, key=_rule_id)) or decisions != tuple(
        sorted(decisions, key=_rule_id)
    ):
        raise ReasoningTraceError("reasoning trace sources are invalid or inconsistent")
    rule_by_id = _unique_by_id(rules)
    decision_by_id = _unique_by_id(decisions)
    entry_by_id = _unique_by_id(report.source_resolution.entries)
    if set(rule_by_id) != set(decision_by_id) or set(rule_by_id) != set(entry_by_id):
        raise ReasoningTraceError("reasoning trace sources are invalid or inconsistent")

    identity = (report.document_id, report.source_kb_sha256, report.source_pdf_sha256)
    for rule_id, rule in rule_by_id.items():
        decision = decision_by_id[rule_id]
        entry = entry_by_id[rule_id]
        if decision.logical_mode is not rule.mode:
            raise ReasoningTraceError("reasoning trace sources are invalid or inconsistent")
        predicate_keys = tuple((item.field_path, item.operator) for item in rule.predicates)
        outcome_keys = tuple(
            (item.field_path, item.operator) for item in decision.predicate_outcomes
        )
        if predicate_keys != outcome_keys:
            raise ReasoningTraceError("reasoning trace sources are invalid or inconsistent")
        if (
            decision.document_id,
            decision.source_kb_sha256,
            decision.source_pdf_sha256,
        ) != identity:
            raise ReasoningTraceError("reasoning trace sources are invalid or inconsistent")
        if (
            entry.original_status is not decision.status
            or entry.scope != rule.scope
            or entry.official_evidence != decision.official_evidence
        ):
            raise ReasoningTraceError("reasoning trace sources are invalid or inconsistent")
        _validate_evidence(rule, decision, identity)


def _validate_evidence(
    rule: ReviewedRuleSnapshot,
    decision: ApplicabilityDecision,
    identity: tuple[str, str, str],
) -> None:
    bindings = {(item.document_id, item.fact_id): item for item in rule.evidence_bindings}
    references: set[tuple[str, str]] = set()
    for binding in rule.evidence_bindings:
        if (
            binding.document_id,
            binding.source_kb_sha256,
            binding.source_pdf_sha256,
        ) != identity:
            raise ReasoningTraceError("reasoning trace sources are invalid or inconsistent")
    for reference in decision.official_evidence:
        key = (reference.document_id, reference.fact_id)
        binding = bindings.get(key)
        if binding is None or binding.source_pages != reference.source_pages:
            raise ReasoningTraceError("reasoning trace sources are invalid or inconsistent")
        references.add(key)
    missing = ApplicabilityDiagnostic.MISSING_OFFICIAL_EVIDENCE in decision.diagnostics
    if not missing and references != set(bindings):
        raise ReasoningTraceError("reasoning trace sources are invalid or inconsistent")


def _derive_trace(
    rules: tuple[ReviewedRuleSnapshot, ...],
    decisions: tuple[ApplicabilityDecision, ...],
    report: RuleInteractionReport,
) -> _DerivedTrace:
    decision_by_id = {item.rule_id: item for item in decisions}
    entry_by_id = {item.rule_id: item for item in report.source_resolution.entries}

    applicability_steps = tuple(
        _applicability_step(rule, decision_by_id[rule.rule_id], entry_by_id[rule.rule_id])
        for rule in rules
    )
    resolution_steps = tuple(_resolution_step(entry_by_id[rule.rule_id]) for rule in rules)
    interaction_steps = _interaction_steps(report, entry_by_id)

    referenced_resolutions = {
        dependency for step in interaction_steps for dependency in step.dependencies
    }
    unreferenced_resolutions = tuple(
        step.step_id for step in resolution_steps if step.step_id not in referenced_resolutions
    )
    terminal_step_ids = unreferenced_resolutions + tuple(step.step_id for step in interaction_steps)
    warning_counts = tuple(
        TraceWarningCount(
            kind=kind,
            certainty=certainty,
            count=sum(
                warning.kind is kind and warning.certainty is certainty
                for warning in report.warnings
            ),
        )
        for kind in InteractionWarningKind
        for certainty in InteractionCertainty
    )
    coverage = ReasoningTraceCoverage(
        rule_count=len(rules),
        applicability_step_count=len(applicability_steps),
        resolution_step_count=len(resolution_steps),
        interaction_step_count=len(interaction_steps),
        interaction_warning_counts=warning_counts,
        interaction_analysis_complete=report.analysis_complete,
    )
    return _DerivedTrace(
        applicability_steps=applicability_steps,
        resolution_steps=resolution_steps,
        interaction_steps=interaction_steps,
        terminal_step_ids=terminal_step_ids,
        coverage=coverage,
    )


def _applicability_step(
    rule: ReviewedRuleSnapshot,
    decision: ApplicabilityDecision,
    entry: RuleResolutionEntry,
) -> ApplicabilityTraceStep:
    predicates = tuple(
        TracePredicateRecord(
            field_path=predicate.field_path,
            operator=predicate.operator,
            expected_value=predicate.expected_value,
            outcome_status=outcome.status,
        )
        for predicate, outcome in zip(rule.predicates, decision.predicate_outcomes, strict=True)
    )
    return ApplicabilityTraceStep(
        step_id=f"applicability:{rule.rule_id}",
        rule_id=rule.rule_id,
        logical_mode=rule.mode,
        subject_key=entry.subject_key,
        scope=rule.scope,
        predicates=predicates,
        status=decision.status,
        scope_status=decision.scope_status,
        missing_profile_fields=decision.missing_profile_fields,
        diagnostics=decision.diagnostics,
        official_evidence=decision.official_evidence,
    )


def _resolution_step(entry: RuleResolutionEntry) -> ResolutionTraceStep:
    return ResolutionTraceStep(
        step_id=f"resolution:{entry.rule_id}",
        dependencies=(f"applicability:{entry.rule_id}",),
        rule_id=entry.rule_id,
        original_status=entry.original_status,
        disposition=entry.disposition,
        subject_key=entry.subject_key,
        scope=entry.scope,
        activated_override=entry.activated_override,
        official_evidence=entry.official_evidence,
    )


def _interaction_steps(
    report: RuleInteractionReport,
    entry_by_id: dict[str, RuleResolutionEntry],
) -> tuple[InteractionTraceStep, ...]:
    warning_by_id = {item.pair_id: item for item in report.warnings}
    reviewed_by_id = {
        _pair_id(item.subject_key, item.rule_ids): item for item in report.reviewed_interactions
    }
    live_ids = set(report.reviewed_compatible_pair_ids) | set(warning_by_id)
    pair_ids = tuple(sorted(live_ids | set(report.inactive_policy_pair_ids)))
    steps: list[InteractionTraceStep] = []
    for pair_id in pair_ids:
        warning = warning_by_id.get(pair_id)
        interaction = reviewed_by_id.get(pair_id)
        if warning is not None:
            subject_key = warning.subject_key
            rule_ids = warning.rule_ids
            endpoints = warning.endpoints
            outcome = InteractionTraceOutcome(warning.kind.value)
            certainty = warning.certainty
            diagnostic = warning.diagnostic
            rationale = warning.reviewed_rationale
        elif interaction is not None:
            subject_key = interaction.subject_key
            rule_ids = interaction.rule_ids
            endpoints = tuple(_endpoint(entry_by_id[item]) for item in rule_ids)
            if pair_id in report.inactive_policy_pair_ids:
                outcome = InteractionTraceOutcome.INACTIVE
            elif interaction.relationship is InteractionRelationship.COMPATIBLE:
                outcome = InteractionTraceOutcome.COMPATIBLE
            else:
                raise ReasoningTraceError("reasoning trace sources are invalid or inconsistent")
            certainty = None
            diagnostic = None
            rationale = interaction.rationale
        else:
            raise ReasoningTraceError("reasoning trace sources are invalid or inconsistent")
        steps.append(
            InteractionTraceStep(
                step_id=f"interaction:{pair_id}",
                dependencies=tuple(f"resolution:{item}" for item in rule_ids),
                pair_id=pair_id,
                subject_key=subject_key,
                rule_ids=rule_ids,
                outcome=outcome,
                certainty=certainty,
                diagnostic=diagnostic,
                reviewed_rationale=rationale,
                endpoints=endpoints,
            )
        )
    return tuple(steps)


def _endpoint(entry: RuleResolutionEntry) -> InteractionEndpoint:
    return InteractionEndpoint(
        rule_id=entry.rule_id,
        original_status=entry.original_status,
        disposition=entry.disposition,
        scope=entry.scope,
        official_evidence=entry.official_evidence,
    )


def _validate_graph(trace: ReasoningTrace) -> None:
    steps: tuple[ApplicabilityTraceStep | ResolutionTraceStep | InteractionTraceStep, ...] = (
        trace.applicability_steps + trace.resolution_steps + trace.interaction_steps
    )
    step_ids = tuple(step.step_id for step in steps)
    if len(step_ids) != len(set(step_ids)):
        raise ValueError("trace step IDs must be unique")
    position = {step_id: index for index, step_id in enumerate(step_ids)}
    for index, step in enumerate(steps):
        if len(step.dependencies) != len(set(step.dependencies)):
            raise ValueError("trace dependencies must be unique")
        if any(
            dependency not in position or position[dependency] >= index
            for dependency in step.dependencies
        ):
            raise ValueError("trace dependencies must point backward")
    if len(trace.terminal_step_ids) != len(set(trace.terminal_step_ids)) or any(
        item not in position for item in trace.terminal_step_ids
    ):
        raise ValueError("trace terminal steps are invalid")


def _unique_by_id(values: tuple[Any, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        if value.rule_id in result:
            raise ReasoningTraceError("reasoning trace sources are invalid or inconsistent")
        result[value.rule_id] = value
    return result


def _rule_id(value: Any) -> str:
    return value.rule_id


def _pair_id(subject_key: str, rule_ids: tuple[str, str]) -> str:
    return json.dumps(
        [subject_key, rule_ids[0], rule_ids[1]],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _validate_trimmed(value: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("value must be a non-empty trimmed string")


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("value must be lowercase SHA-256")


def _reject_constant(_: str) -> Any:
    raise ValueError("non-finite JSON numbers are unsupported")
