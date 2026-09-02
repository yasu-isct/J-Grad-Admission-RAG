"""Reviewed interaction analysis over resolved admission rules."""

from __future__ import annotations

import json
from enum import Enum
from itertools import combinations
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

from .applicability import ApplicabilityStatus, OfficialEvidenceReference, RuleScope
from .rule_resolution import ResolutionDisposition, RuleResolution, RuleResolutionEntry

RULE_INTERACTION_POLICY_SCHEMA_VERSION = "1.0"
RULE_INTERACTION_REPORT_SCHEMA_VERSION = "1.0"
SUPPORTED_RULE_INTERACTION_POLICY_SCHEMA_VERSIONS = frozenset(
    {RULE_INTERACTION_POLICY_SCHEMA_VERSION}
)
SUPPORTED_RULE_INTERACTION_REPORT_SCHEMA_VERSIONS = frozenset(
    {RULE_INTERACTION_REPORT_SCHEMA_VERSION}
)

_LIVE_DISPOSITIONS = frozenset({ResolutionDisposition.ACTIVE, ResolutionDisposition.PENDING})


class RuleInteractionError(Exception):
    """Raised when interaction inputs or artifacts fail safe validation."""


class RuleInteractionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InteractionRelationship(str, Enum):
    COMPATIBLE = "compatible"
    CONFLICT = "conflict"
    AMBIGUOUS = "ambiguous"


class InteractionWarningKind(str, Enum):
    CONFLICT = "conflict"
    AMBIGUITY = "ambiguity"
    UNREVIEWED_INTERACTION = "unreviewed_interaction"


class InteractionCertainty(str, Enum):
    CONFIRMED = "confirmed"
    POTENTIAL = "potential"


class InteractionDiagnostic(str, Enum):
    MISSING_REVIEWED_RELATIONSHIP = "missing_reviewed_relationship"


class RuleInteraction(RuleInteractionModel):
    subject_key: str
    rule_ids: tuple[str, str]
    relationship: InteractionRelationship
    rationale: str = Field(max_length=500)

    @field_validator("subject_key", "rationale")
    @classmethod
    def strings_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @field_validator("rule_ids", mode="before")
    @classmethod
    def rule_pair_must_be_canonical(cls, values: Any) -> tuple[str, str]:
        if not isinstance(values, (list, tuple)) or len(values) != 2:
            raise ValueError("interaction requires exactly two rule IDs")
        for value in values:
            if not isinstance(value, str):
                raise ValueError("interaction rule IDs must be strings")
            _validate_trimmed(value)
        if values[0] == values[1]:
            raise ValueError("interaction rule IDs must be distinct")
        return tuple(sorted(values))


class RuleInteractionPolicy(RuleInteractionModel):
    schema_version: Literal["1.0"] = RULE_INTERACTION_POLICY_SCHEMA_VERSION
    policy_id: str
    interactions: tuple[RuleInteraction, ...] = ()

    @field_validator("policy_id")
    @classmethod
    def policy_id_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @model_validator(mode="after")
    def interactions_must_be_canonical(self) -> RuleInteractionPolicy:
        keys = tuple(_interaction_key(item) for item in self.interactions)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("interaction pairs must be sorted and unique")
        return self


class InteractionEndpoint(RuleInteractionModel):
    rule_id: str
    original_status: ApplicabilityStatus
    disposition: ResolutionDisposition
    scope: RuleScope
    official_evidence: tuple[OfficialEvidenceReference, ...]

    @field_validator("rule_id")
    @classmethod
    def rule_id_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @model_validator(mode="after")
    def evidence_must_be_unique(self) -> InteractionEndpoint:
        keys = tuple((item.document_id, item.fact_id, item.role) for item in self.official_evidence)
        if len(keys) != len(set(keys)):
            raise ValueError("interaction endpoint evidence must be unique")
        return self


class RuleInteractionWarning(RuleInteractionModel):
    pair_id: str
    kind: InteractionWarningKind
    certainty: InteractionCertainty
    subject_key: str
    rule_ids: tuple[str, str]
    endpoints: tuple[InteractionEndpoint, InteractionEndpoint]
    reviewed_rationale: str | None = Field(default=None, max_length=500)
    diagnostic: InteractionDiagnostic | None = None

    @field_validator("pair_id", "subject_key")
    @classmethod
    def identifiers_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @model_validator(mode="after")
    def warning_fields_must_reconcile(self) -> RuleInteractionWarning:
        if self.rule_ids[0] >= self.rule_ids[1]:
            raise ValueError("warning rule IDs must be distinct and sorted")
        if tuple(item.rule_id for item in self.endpoints) != self.rule_ids:
            raise ValueError("warning endpoints do not reconcile")
        if self.pair_id != _pair_id(self.subject_key, self.rule_ids):
            raise ValueError("warning pair ID does not reconcile")
        is_unreviewed = self.kind is InteractionWarningKind.UNREVIEWED_INTERACTION
        if is_unreviewed != (self.diagnostic is not None):
            raise ValueError("warning diagnostic does not reconcile")
        if is_unreviewed != (self.reviewed_rationale is None):
            raise ValueError("warning rationale does not reconcile")
        return self


class RuleInteractionReport(RuleInteractionModel):
    schema_version: Literal["1.0"] = RULE_INTERACTION_REPORT_SCHEMA_VERSION
    policy_id: str
    document_id: str
    source_kb_sha256: str
    source_pdf_sha256: str
    source_resolution: RuleResolution
    reviewed_interactions: tuple[RuleInteraction, ...]
    warnings: tuple[RuleInteractionWarning, ...]
    reviewed_compatible_pair_ids: tuple[str, ...]
    inactive_policy_pair_ids: tuple[str, ...]
    live_same_subject_pair_count: StrictInt = Field(ge=0)
    reviewed_live_pair_count: StrictInt = Field(ge=0)
    unreviewed_live_pair_count: StrictInt = Field(ge=0)
    analysis_complete: StrictBool

    @field_validator("policy_id", "document_id")
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
    def report_must_be_recomputable(self) -> RuleInteractionReport:
        RuleInteractionPolicy(
            policy_id=self.policy_id,
            interactions=self.reviewed_interactions,
        )
        identity = (
            self.source_resolution.document_id,
            self.source_resolution.source_kb_sha256,
            self.source_resolution.source_pdf_sha256,
        )
        if identity != (self.document_id, self.source_kb_sha256, self.source_pdf_sha256):
            raise ValueError("interaction report source identity does not reconcile")
        _validate_interactions_against_resolution(
            self.source_resolution, self.reviewed_interactions
        )
        expected = _build_analysis(self.source_resolution, self.reviewed_interactions)
        if (
            self.warnings != expected.warnings
            or self.reviewed_compatible_pair_ids != expected.reviewed_compatible_pair_ids
            or self.inactive_policy_pair_ids != expected.inactive_policy_pair_ids
            or self.live_same_subject_pair_count != expected.live_pair_count
            or self.reviewed_live_pair_count != expected.reviewed_pair_count
            or self.unreviewed_live_pair_count != expected.unreviewed_pair_count
            or self.analysis_complete != (expected.unreviewed_pair_count == 0)
        ):
            raise ValueError("interaction report analysis does not reconcile")
        return self


class _ExpectedAnalysis(RuleInteractionModel):
    warnings: tuple[RuleInteractionWarning, ...]
    reviewed_compatible_pair_ids: tuple[str, ...]
    inactive_policy_pair_ids: tuple[str, ...]
    live_pair_count: int
    reviewed_pair_count: int
    unreviewed_pair_count: int


def analyze_rule_interactions(
    resolution: RuleResolution, policy: RuleInteractionPolicy
) -> RuleInteractionReport:
    """Analyze only reviewed relationships among active and pending resolved rules."""

    resolution, policy = _revalidate_inputs(resolution, policy)
    _validate_interactions_against_resolution(resolution, policy.interactions)
    expected = _build_analysis(resolution, policy.interactions)
    return RuleInteractionReport(
        policy_id=policy.policy_id,
        document_id=resolution.document_id,
        source_kb_sha256=resolution.source_kb_sha256,
        source_pdf_sha256=resolution.source_pdf_sha256,
        source_resolution=resolution,
        reviewed_interactions=policy.interactions,
        warnings=expected.warnings,
        reviewed_compatible_pair_ids=expected.reviewed_compatible_pair_ids,
        inactive_policy_pair_ids=expected.inactive_policy_pair_ids,
        live_same_subject_pair_count=expected.live_pair_count,
        reviewed_live_pair_count=expected.reviewed_pair_count,
        unreviewed_live_pair_count=expected.unreviewed_pair_count,
        analysis_complete=expected.unreviewed_pair_count == 0,
    )


def canonical_rule_interaction_policy_bytes(policy: RuleInteractionPolicy) -> bytes:
    return _canonical_model_bytes(policy, RuleInteractionPolicy, "Rule interaction policy")


def canonical_rule_interaction_report_bytes(report: RuleInteractionReport) -> bytes:
    return _canonical_model_bytes(report, RuleInteractionReport, "Rule interaction report")


def load_rule_interaction_policy_bytes(raw_bytes: bytes) -> RuleInteractionPolicy:
    return _load_model_bytes(
        raw_bytes,
        RuleInteractionPolicy,
        SUPPORTED_RULE_INTERACTION_POLICY_SCHEMA_VERSIONS,
        "Rule interaction policy",
    )


def load_rule_interaction_policy(path_value: str | Path) -> RuleInteractionPolicy:
    return _load_model_path(
        path_value, load_rule_interaction_policy_bytes, "Rule interaction policy"
    )


def load_rule_interaction_report_bytes(raw_bytes: bytes) -> RuleInteractionReport:
    return _load_model_bytes(
        raw_bytes,
        RuleInteractionReport,
        SUPPORTED_RULE_INTERACTION_REPORT_SCHEMA_VERSIONS,
        "Rule interaction report",
    )


def load_rule_interaction_report(path_value: str | Path) -> RuleInteractionReport:
    return _load_model_path(
        path_value, load_rule_interaction_report_bytes, "Rule interaction report"
    )


def _revalidate_inputs(
    resolution: Any, policy: Any
) -> tuple[RuleResolution, RuleInteractionPolicy]:
    try:
        return (
            RuleResolution.model_validate(resolution.model_dump(mode="json")),
            RuleInteractionPolicy.model_validate(policy.model_dump(mode="json")),
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise RuleInteractionError("rule interaction inputs are invalid or unsupported") from None


def _validate_interactions_against_resolution(
    resolution: RuleResolution, interactions: tuple[RuleInteraction, ...]
) -> None:
    entries = {entry.rule_id: entry for entry in resolution.entries}
    for interaction in interactions:
        try:
            left = entries[interaction.rule_ids[0]]
            right = entries[interaction.rule_ids[1]]
        except KeyError:
            raise RuleInteractionError(
                "rule interaction inputs are invalid or inconsistent"
            ) from None
        if (
            left.subject_key != interaction.subject_key
            or right.subject_key != interaction.subject_key
        ):
            raise RuleInteractionError("rule interaction inputs are invalid or inconsistent")


def _build_analysis(
    resolution: RuleResolution, interactions: tuple[RuleInteraction, ...]
) -> _ExpectedAnalysis:
    entry_by_id = {entry.rule_id: entry for entry in resolution.entries}
    live_pairs = _live_pairs(resolution.entries)
    reviewed = {_interaction_key(item): item for item in interactions}
    warnings: list[RuleInteractionWarning] = []
    compatible_ids: list[str] = []
    reviewed_count = 0
    unreviewed_count = 0

    for subject_key, rule_ids in live_pairs:
        pair_id = _pair_id(subject_key, rule_ids)
        interaction = reviewed.get((subject_key, rule_ids))
        if interaction is None:
            unreviewed_count += 1
            warnings.append(
                _warning(
                    subject_key,
                    rule_ids,
                    entry_by_id,
                    InteractionWarningKind.UNREVIEWED_INTERACTION,
                    None,
                )
            )
            continue
        reviewed_count += 1
        if interaction.relationship is InteractionRelationship.COMPATIBLE:
            compatible_ids.append(pair_id)
        else:
            kind = (
                InteractionWarningKind.CONFLICT
                if interaction.relationship is InteractionRelationship.CONFLICT
                else InteractionWarningKind.AMBIGUITY
            )
            warnings.append(
                _warning(
                    subject_key,
                    rule_ids,
                    entry_by_id,
                    kind,
                    interaction.rationale,
                )
            )

    live_pair_keys = set(live_pairs)
    inactive_ids = tuple(
        sorted(
            _pair_id(item.subject_key, item.rule_ids)
            for item in interactions
            if _interaction_key(item) not in live_pair_keys
        )
    )
    return _ExpectedAnalysis(
        warnings=tuple(sorted(warnings, key=lambda item: item.pair_id)),
        reviewed_compatible_pair_ids=tuple(sorted(compatible_ids)),
        inactive_policy_pair_ids=inactive_ids,
        live_pair_count=len(live_pairs),
        reviewed_pair_count=reviewed_count,
        unreviewed_pair_count=unreviewed_count,
    )


def _live_pairs(
    entries: tuple[RuleResolutionEntry, ...],
) -> tuple[tuple[str, tuple[str, str]], ...]:
    by_subject: dict[str, list[str]] = {}
    for entry in entries:
        if entry.disposition in _LIVE_DISPOSITIONS:
            by_subject.setdefault(entry.subject_key, []).append(entry.rule_id)
    pairs = [
        (subject_key, pair)
        for subject_key, rule_ids in by_subject.items()
        for pair in combinations(sorted(rule_ids), 2)
    ]
    return tuple(sorted(pairs))


def _warning(
    subject_key: str,
    rule_ids: tuple[str, str],
    entry_by_id: dict[str, RuleResolutionEntry],
    kind: InteractionWarningKind,
    rationale: str | None,
) -> RuleInteractionWarning:
    entries = (entry_by_id[rule_ids[0]], entry_by_id[rule_ids[1]])
    certainty = (
        InteractionCertainty.CONFIRMED
        if all(entry.disposition is ResolutionDisposition.ACTIVE for entry in entries)
        else InteractionCertainty.POTENTIAL
    )
    return RuleInteractionWarning(
        pair_id=_pair_id(subject_key, rule_ids),
        kind=kind,
        certainty=certainty,
        subject_key=subject_key,
        rule_ids=rule_ids,
        endpoints=tuple(_endpoint(entry) for entry in entries),
        reviewed_rationale=rationale,
        diagnostic=(
            InteractionDiagnostic.MISSING_REVIEWED_RELATIONSHIP
            if kind is InteractionWarningKind.UNREVIEWED_INTERACTION
            else None
        ),
    )


def _endpoint(entry: RuleResolutionEntry) -> InteractionEndpoint:
    return InteractionEndpoint(
        rule_id=entry.rule_id,
        original_status=entry.original_status,
        disposition=entry.disposition,
        scope=entry.scope,
        official_evidence=entry.official_evidence,
    )


def _interaction_key(interaction: RuleInteraction) -> tuple[str, tuple[str, str]]:
    return interaction.subject_key, interaction.rule_ids


def _pair_id(subject_key: str, rule_ids: tuple[str, str]) -> str:
    return json.dumps(
        [subject_key, rule_ids[0], rule_ids[1]],
        ensure_ascii=False,
        separators=(",", ":"),
    )


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
    except (TypeError, ValidationError, ValueError, RuleInteractionError):
        raise RuleInteractionError(f"{name} is invalid or unsupported") from None
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
        RuleInteractionError,
    ):
        raise RuleInteractionError(f"{name} bytes are invalid or unsupported") from None


def _load_model_path(path_value: Any, loader: Any, name: str) -> Any:
    try:
        path = Path(path_value)
        if path.is_symlink() or not path.is_file():
            raise OSError
        raw_bytes = path.read_bytes()
    except (OSError, TypeError, ValueError):
        raise RuleInteractionError(f"{name} file is unavailable or unsafe") from None
    return loader(raw_bytes)


def _reject_constant(_: str) -> Any:
    raise ValueError("non-finite JSON numbers are unsupported")


def _validate_trimmed(value: str) -> None:
    if not value or value != value.strip():
        raise ValueError("string must be non-empty and trimmed")


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("value must be lowercase SHA-256")
