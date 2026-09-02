"""Deterministic cited findings and fixed Japanese rendering from reasoning traces."""

from __future__ import annotations

import base64
import html
import json
import re
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    field_validator,
    model_validator,
)

from .applicability import (
    ApplicabilityDiagnostic,
    ApplicabilityStatus,
    EvidenceRole,
    OfficialEvidenceReference,
    RuleScope,
)
from .reasoning_trace import (
    ApplicabilityTraceStep,
    InteractionTraceOutcome,
    InteractionTraceStep,
    ReasoningTrace,
    ResolutionTraceStep,
)
from .rule_interaction import InteractionCertainty
from .rule_resolution import ActivatedOverride, ResolutionDisposition

CITED_ANSWER_SCHEMA_VERSION = "1.0"
SUPPORTED_CITED_ANSWER_SCHEMA_VERSIONS = frozenset({CITED_ANSWER_SCHEMA_VERSION})

__all__ = [
    "CITED_ANSWER_SCHEMA_VERSION",
    "SUPPORTED_CITED_ANSWER_SCHEMA_VERSIONS",
    "AnswerCitation",
    "CitedAnswer",
    "CitedAnswerError",
    "InteractionAnswerWarning",
    "MissingInformationEntry",
    "ProcessNotice",
    "ProcessNoticeKind",
    "ReportStatus",
    "RuleFinding",
    "build_cited_answer",
    "canonical_cited_answer_bytes",
    "render_cited_answer_markdown",
]

_SAFE_IDENTIFIER = re.compile(r"^[^\W][\w._:/-]*$", re.UNICODE)


class CitedAnswerError(Exception):
    """Raised when a cited answer cannot be produced without unsafe inference or leakage."""


class CitedAnswerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportStatus(str, Enum):
    COMPLETE = "complete"
    NEEDS_INFORMATION = "needs_information"
    NEEDS_REVIEW = "needs_review"


class ProcessNoticeKind(str, Enum):
    MISSING_OFFICIAL_EVIDENCE = "missing_official_evidence"
    OVERRIDE_EVIDENCE_INCOMPLETE = "override_evidence_incomplete"
    INTERACTION_EVIDENCE_INCOMPLETE = "interaction_evidence_incomplete"
    MISSING_SCOPE = "missing_scope"
    SCOPE_INPUT_CONFLICT = "scope_input_conflict"
    INTERACTION_ANALYSIS_INCOMPLETE = "interaction_analysis_incomplete"


_REVIEW_NOTICE_KINDS = frozenset(
    {
        ProcessNoticeKind.MISSING_OFFICIAL_EVIDENCE,
        ProcessNoticeKind.OVERRIDE_EVIDENCE_INCOMPLETE,
        ProcessNoticeKind.INTERACTION_EVIDENCE_INCOMPLETE,
        ProcessNoticeKind.SCOPE_INPUT_CONFLICT,
        ProcessNoticeKind.INTERACTION_ANALYSIS_INCOMPLETE,
    }
)


class AnswerCitation(CitedAnswerModel):
    document_id: str
    fact_id: str
    source_pages: tuple[int, ...]
    role: EvidenceRole
    source_rule_id: str
    source_step_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("document_id", "fact_id", "source_rule_id")
    @classmethod
    def identifiers_must_be_safe(cls, value: str) -> str:
        _validate_safe_identifier(value)
        return value

    @field_validator("source_pages")
    @classmethod
    def pages_must_be_canonical(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if not values or any(value <= 0 for value in values):
            raise ValueError("citation pages must be positive and non-empty")
        if values != tuple(sorted(set(values))):
            raise ValueError("citation pages must be sorted and unique")
        return values

    @field_validator("source_step_ids")
    @classmethod
    def source_steps_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("citation source steps must be sorted and unique")
        if any(not value or value != value.strip() for value in values):
            raise ValueError("citation source steps must be explicit")
        return values


class RuleFinding(CitedAnswerModel):
    finding_id: str
    rule_id: str
    subject_key: str
    scope: RuleScope
    original_status: ApplicabilityStatus
    disposition: ResolutionDisposition
    source_applicability_step_id: str
    source_resolution_step_id: str
    activated_override: ActivatedOverride | None = None
    citations: tuple[AnswerCitation, ...] = Field(min_length=1)

    @field_validator("finding_id", "rule_id", "subject_key")
    @classmethod
    def identifiers_must_be_safe(cls, value: str) -> str:
        _validate_safe_identifier(value)
        return value

    @model_validator(mode="after")
    def finding_must_be_cited_and_reconcile(self) -> RuleFinding:
        if self.finding_id != f"finding:{self.rule_id}":
            raise ValueError("finding ID does not reconcile")
        if self.source_applicability_step_id != f"applicability:{self.rule_id}":
            raise ValueError("finding applicability source does not reconcile")
        if self.source_resolution_step_id != f"resolution:{self.rule_id}":
            raise ValueError("finding resolution source does not reconcile")
        if (self.disposition is ResolutionDisposition.OVERRIDDEN) != (
            self.activated_override is not None
        ):
            raise ValueError("finding override does not reconcile")
        expected_disposition = {
            ApplicabilityStatus.NEEDS_INFORMATION: ResolutionDisposition.PENDING,
            ApplicabilityStatus.NOT_APPLICABLE: ResolutionDisposition.NOT_APPLICABLE,
        }.get(self.original_status)
        if expected_disposition is not None and self.disposition is not expected_disposition:
            raise ValueError("finding disposition does not reconcile")
        if self.original_status is ApplicabilityStatus.CONFIRMED and self.disposition not in {
            ResolutionDisposition.ACTIVE,
            ResolutionDisposition.OVERRIDDEN,
        }:
            raise ValueError("finding disposition does not reconcile")
        cited_rules = {item.source_rule_id for item in self.citations}
        expected_cited_rules = {self.rule_id}
        if self.activated_override is not None:
            expected_cited_rules.add(self.activated_override.overrider_rule_id)
        if cited_rules != expected_cited_rules:
            raise ValueError("finding citation rules do not reconcile")
        if self.activated_override is not None and (
            self.activated_override.subject_key != self.subject_key
            or self.activated_override.overrider_rule_id == self.rule_id
        ):
            raise ValueError("finding override does not reconcile")
        for citation in self.citations:
            expected_steps = (
                self.source_applicability_step_id,
                self.source_resolution_step_id,
            )
            if citation.source_rule_id != self.rule_id:
                expected_steps = (
                    f"applicability:{citation.source_rule_id}",
                    f"resolution:{citation.source_rule_id}",
                )
            if citation.source_step_ids != tuple(sorted(expected_steps)):
                raise ValueError("finding citation source steps do not reconcile")
        _validate_citation_order(self.citations)
        return self


class InteractionAnswerWarning(CitedAnswerModel):
    warning_id: str
    pair_id: str
    kind: Literal["conflict", "ambiguity", "unreviewed_interaction"]
    certainty: InteractionCertainty
    rule_ids: tuple[str, str]
    source_interaction_step_id: str
    citations: tuple[AnswerCitation, ...] = Field(min_length=2)

    @field_validator("warning_id")
    @classmethod
    def warning_id_must_be_safe(cls, value: str) -> str:
        _validate_safe_identifier(value)
        return value

    @field_validator("rule_ids")
    @classmethod
    def rule_ids_must_be_safe(cls, values: tuple[str, str]) -> tuple[str, str]:
        if values[0] >= values[1]:
            raise ValueError("warning rule IDs must be sorted and distinct")
        for value in values:
            _validate_safe_identifier(value)
        return values

    @model_validator(mode="after")
    def warning_must_cite_both_rules(self) -> InteractionAnswerWarning:
        if self.warning_id != _warning_id(self.pair_id):
            raise ValueError("warning ID does not reconcile")
        _, left, right = _parse_pair_id(self.pair_id)
        if self.rule_ids != (left, right):
            raise ValueError("warning rule pair does not reconcile")
        if self.source_interaction_step_id != f"interaction:{self.pair_id}":
            raise ValueError("warning source step does not reconcile")
        if {item.source_rule_id for item in self.citations} != set(self.rule_ids):
            raise ValueError("warning citations must cover both rules")
        for citation in self.citations:
            expected_steps = tuple(
                sorted(
                    (
                        f"resolution:{citation.source_rule_id}",
                        self.source_interaction_step_id,
                    )
                )
            )
            if citation.source_step_ids != expected_steps:
                raise ValueError("warning citation source steps do not reconcile")
        _validate_citation_order(self.citations)
        return self


class MissingInformationEntry(CitedAnswerModel):
    rule_id: str
    field_path: str
    source_applicability_step_id: str
    source_resolution_step_id: str

    @field_validator("rule_id", "field_path")
    @classmethod
    def identifiers_must_be_safe(cls, value: str) -> str:
        _validate_safe_identifier(value)
        return value

    @model_validator(mode="after")
    def source_steps_must_reconcile(self) -> MissingInformationEntry:
        if self.source_applicability_step_id != f"applicability:{self.rule_id}":
            raise ValueError("missing-information applicability source does not reconcile")
        if self.source_resolution_step_id != f"resolution:{self.rule_id}":
            raise ValueError("missing-information resolution source does not reconcile")
        return self


class ProcessNotice(CitedAnswerModel):
    kind: ProcessNoticeKind
    rule_ids: tuple[str, ...] = ()
    source_step_ids: tuple[str, ...] = ()

    @field_validator("rule_ids")
    @classmethod
    def rule_ids_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("notice rule IDs must be sorted and unique")
        for value in values:
            _validate_safe_identifier(value)
        return values

    @field_validator("source_step_ids")
    @classmethod
    def source_steps_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("notice source steps must be sorted and unique")
        return values


class CitedAnswer(CitedAnswerModel):
    schema_version: Literal["1.0"] = CITED_ANSWER_SCHEMA_VERSION
    answer_id: str
    source_trace_id: str
    document_id: str
    source_kb_sha256: str
    source_pdf_sha256: str
    report_status: ReportStatus
    interaction_analysis_complete: StrictBool
    source_rule_ids: tuple[str, ...] = Field(min_length=1)
    source_trace_step_ids: tuple[str, ...] = Field(min_length=2)
    rule_findings: tuple[RuleFinding, ...]
    interaction_warnings: tuple[InteractionAnswerWarning, ...]
    missing_information: tuple[MissingInformationEntry, ...]
    process_notices: tuple[ProcessNotice, ...]
    citation_inventory: tuple[AnswerCitation, ...]

    @field_validator("answer_id", "source_trace_id", "document_id")
    @classmethod
    def identifiers_must_be_safe(cls, value: str) -> str:
        _validate_safe_identifier(value)
        return value

    @field_validator("source_kb_sha256", "source_pdf_sha256")
    @classmethod
    def hashes_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value

    @field_validator("source_rule_ids")
    @classmethod
    def source_rules_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(set(values))):
            raise ValueError("answer source rule IDs must be sorted and unique")
        for value in values:
            _validate_safe_identifier(value)
        return values

    @model_validator(mode="after")
    def collections_and_status_must_reconcile(self) -> CitedAnswer:
        _validate_answer_collections(self)
        if self.report_status is not _derive_report_status(
            self.rule_findings,
            self.interaction_warnings,
            self.missing_information,
            self.process_notices,
        ):
            raise ValueError("answer report status does not reconcile")
        return self


def build_cited_answer(answer_id: str, trace: ReasoningTrace) -> CitedAnswer:
    """Build cited rule findings from one fully validated reasoning trace."""

    try:
        _validate_safe_identifier(answer_id)
        validated_trace = ReasoningTrace.model_validate(trace.model_dump(mode="json"))
        _validate_trace_identifiers(validated_trace)
        applicability_by_rule = {item.rule_id: item for item in validated_trace.applicability_steps}
        resolution_by_rule = {item.rule_id: item for item in validated_trace.resolution_steps}

        findings: list[RuleFinding] = []
        missing: list[MissingInformationEntry] = []
        notices: list[ProcessNotice] = []
        for resolution in validated_trace.resolution_steps:
            applicability = applicability_by_rule[resolution.rule_id]
            for field_path in applicability.missing_profile_fields:
                missing.append(
                    MissingInformationEntry(
                        rule_id=resolution.rule_id,
                        field_path=field_path,
                        source_applicability_step_id=applicability.step_id,
                        source_resolution_step_id=resolution.step_id,
                    )
                )
            notices.extend(_diagnostic_notices(applicability, resolution))
            finding = _build_finding(resolution, applicability.step_id, resolution_by_rule)
            if isinstance(finding, ProcessNotice):
                notices.append(finding)
            else:
                findings.append(finding)

        warnings: list[InteractionAnswerWarning] = []
        for interaction in validated_trace.interaction_steps:
            result = _build_warning(interaction)
            if result is None:
                continue
            if isinstance(result, ProcessNotice):
                notices.append(result)
            else:
                warnings.append(result)
        if not validated_trace.coverage.interaction_analysis_complete:
            notices.append(
                ProcessNotice(
                    kind=ProcessNoticeKind.INTERACTION_ANALYSIS_INCOMPLETE,
                    source_step_ids=tuple(
                        item.step_id
                        for item in validated_trace.interaction_steps
                        if item.outcome is InteractionTraceOutcome.UNREVIEWED_INTERACTION
                    ),
                )
            )

        findings_tuple = tuple(sorted(findings, key=lambda item: item.rule_id))
        warnings_tuple = tuple(sorted(warnings, key=lambda item: item.pair_id))
        missing_tuple = tuple(
            sorted(set(missing), key=lambda item: (item.rule_id, item.field_path))
        )
        notices_tuple = tuple(sorted(set(notices), key=_notice_key))
        inventory = _citation_inventory(findings_tuple, warnings_tuple)
        status = _derive_report_status(findings_tuple, warnings_tuple, missing_tuple, notices_tuple)
        return CitedAnswer(
            answer_id=answer_id,
            source_trace_id=validated_trace.trace_id,
            document_id=validated_trace.document_id,
            source_kb_sha256=validated_trace.source_kb_sha256,
            source_pdf_sha256=validated_trace.source_pdf_sha256,
            report_status=status,
            interaction_analysis_complete=(validated_trace.coverage.interaction_analysis_complete),
            source_rule_ids=tuple(item.rule_id for item in validated_trace.resolution_steps),
            source_trace_step_ids=tuple(
                item.step_id
                for item in (
                    validated_trace.applicability_steps
                    + validated_trace.resolution_steps
                    + validated_trace.interaction_steps
                )
            ),
            rule_findings=findings_tuple,
            interaction_warnings=warnings_tuple,
            missing_information=missing_tuple,
            process_notices=notices_tuple,
            citation_inventory=inventory,
        )
    except (AttributeError, TypeError, ValidationError, ValueError, CitedAnswerError):
        raise CitedAnswerError("cited answer input is invalid or inconsistent") from None


def canonical_cited_answer_bytes(answer: CitedAnswer) -> bytes:
    """Serialize one fully revalidated answer as canonical UTF-8 JSON with LF."""

    try:
        if not isinstance(answer, CitedAnswer):
            raise TypeError
        validated = CitedAnswer.model_validate(answer.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValidationError, ValueError, CitedAnswerError):
        raise CitedAnswerError("cited answer is invalid or unsupported") from None
    return f"{serialized}\n".encode("utf-8")


def render_cited_answer_markdown(answer: CitedAnswer) -> str:
    """Render stable Japanese Markdown without hashes or arbitrary source prose."""

    try:
        validated = CitedAnswer.model_validate(answer.model_dump(mode="json"))
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise CitedAnswerError("cited answer is invalid or unsupported") from None

    lines = [
        "# レポート準備状況",
        "",
        f"**状態:** {_status_label(validated.report_status)}",
        "",
        "> この状態は規則調査レポートの準備状況です。入学資格、合否、合格可能性、または出願推奨を示すものではありません。",
        "",
        "## 規則ごとの確認結果",
        "",
    ]
    if validated.rule_findings:
        lines.extend(_render_finding(item) for item in validated.rule_findings)
    else:
        lines.append("- 公式根拠を伴う規則所見はありません。")

    if validated.missing_information:
        lines.extend(["", "## 追加で必要な情報", ""])
        lines.extend(
            f"- 規則 `{item.rule_id}`: `{item.field_path}` の情報が不足しています。"
            for item in validated.missing_information
        )

    if validated.interaction_warnings or validated.process_notices:
        lines.extend(["", "## 確認が必要な事項", ""])
        lines.extend(_render_warning(item) for item in validated.interaction_warnings)
        lines.extend(_render_notice(item) for item in validated.process_notices)

    lines.extend(["", "## 出典一覧", ""])
    if validated.citation_inventory:
        lines.extend(_render_inventory_item(item) for item in validated.citation_inventory)
    else:
        lines.append("- 表示可能な公式出典はありません。")

    lines.extend(
        [
            "",
            "## 制約",
            "",
            "- 本レポートは、検証済みトレースに記録された規則単位の結果のみを表示します。",
            "- 公式文書本文の要約や、記録されていない条件の推測は行いません。",
            "- 最終的な出願資格や必要手続は、該当する大学の公式窓口と募集要項で確認してください。",
            "",
        ]
    )
    return "\n".join(lines)


def _build_finding(
    resolution: ResolutionTraceStep,
    applicability_step_id: str,
    resolution_by_rule: dict[str, ResolutionTraceStep],
) -> RuleFinding | ProcessNotice:
    own_citations = _citations(
        resolution.rule_id,
        resolution.official_evidence,
        (applicability_step_id, resolution.step_id),
    )
    if not own_citations:
        return ProcessNotice(
            kind=ProcessNoticeKind.MISSING_OFFICIAL_EVIDENCE,
            rule_ids=(resolution.rule_id,),
            source_step_ids=(applicability_step_id, resolution.step_id),
        )
    citations = own_citations
    if resolution.activated_override is not None:
        overrider_id = resolution.activated_override.overrider_rule_id
        overrider = resolution_by_rule.get(overrider_id)
        if overrider is None:
            return _override_notice(resolution, applicability_step_id, overrider_id)
        overrider_citations = _citations(
            overrider_id,
            overrider.official_evidence,
            (f"applicability:{overrider_id}", overrider.step_id),
        )
        if not overrider_citations:
            return _override_notice(resolution, applicability_step_id, overrider_id)
        citations = tuple(sorted(own_citations + overrider_citations, key=_citation_key))
    return RuleFinding(
        finding_id=f"finding:{resolution.rule_id}",
        rule_id=resolution.rule_id,
        subject_key=resolution.subject_key,
        scope=resolution.scope,
        original_status=resolution.original_status,
        disposition=resolution.disposition,
        source_applicability_step_id=applicability_step_id,
        source_resolution_step_id=resolution.step_id,
        activated_override=resolution.activated_override,
        citations=citations,
    )


def _override_notice(
    resolution: ResolutionTraceStep,
    applicability_step_id: str,
    overrider_id: str,
) -> ProcessNotice:
    return ProcessNotice(
        kind=ProcessNoticeKind.OVERRIDE_EVIDENCE_INCOMPLETE,
        rule_ids=tuple(sorted((resolution.rule_id, overrider_id))),
        source_step_ids=tuple(
            sorted(
                (
                    applicability_step_id,
                    resolution.step_id,
                    f"applicability:{overrider_id}",
                    f"resolution:{overrider_id}",
                )
            )
        ),
    )


def _build_warning(
    interaction: InteractionTraceStep,
) -> InteractionAnswerWarning | ProcessNotice | None:
    if interaction.outcome in {
        InteractionTraceOutcome.COMPATIBLE,
        InteractionTraceOutcome.INACTIVE,
    }:
        return None
    citations = tuple(
        sorted(
            (
                citation
                for endpoint in interaction.endpoints
                for citation in _citations(
                    endpoint.rule_id,
                    endpoint.official_evidence,
                    (f"resolution:{endpoint.rule_id}", interaction.step_id),
                )
            ),
            key=_citation_key,
        )
    )
    if {item.source_rule_id for item in citations} != set(interaction.rule_ids):
        return ProcessNotice(
            kind=ProcessNoticeKind.INTERACTION_EVIDENCE_INCOMPLETE,
            rule_ids=interaction.rule_ids,
            source_step_ids=(interaction.step_id,),
        )
    if interaction.certainty is None:
        raise CitedAnswerError("cited answer input is invalid or inconsistent")
    return InteractionAnswerWarning(
        warning_id=_warning_id(interaction.pair_id),
        pair_id=interaction.pair_id,
        kind=interaction.outcome.value,  # type: ignore[arg-type]
        certainty=interaction.certainty,
        rule_ids=interaction.rule_ids,
        source_interaction_step_id=interaction.step_id,
        citations=citations,
    )


def _diagnostic_notices(
    applicability: ApplicabilityTraceStep,
    resolution: ResolutionTraceStep,
) -> tuple[ProcessNotice, ...]:
    mapping = {
        ApplicabilityDiagnostic.MISSING_OFFICIAL_EVIDENCE: (
            ProcessNoticeKind.MISSING_OFFICIAL_EVIDENCE
        ),
        ApplicabilityDiagnostic.MISSING_SCOPE: ProcessNoticeKind.MISSING_SCOPE,
        ApplicabilityDiagnostic.SCOPE_INPUT_CONFLICT: (ProcessNoticeKind.SCOPE_INPUT_CONFLICT),
    }
    return tuple(
        ProcessNotice(
            kind=mapping[diagnostic],
            rule_ids=(resolution.rule_id,),
            source_step_ids=(applicability.step_id, resolution.step_id),
        )
        for diagnostic in applicability.diagnostics
        if diagnostic in mapping
    )


def _citations(
    rule_id: str,
    evidence: tuple[OfficialEvidenceReference, ...],
    step_ids: tuple[str, ...],
) -> tuple[AnswerCitation, ...]:
    return tuple(
        sorted(
            (
                AnswerCitation(
                    document_id=item.document_id,
                    fact_id=item.fact_id,
                    source_pages=item.source_pages,
                    role=item.role,
                    source_rule_id=rule_id,
                    source_step_ids=tuple(sorted(step_ids)),
                )
                for item in evidence
            ),
            key=_citation_key,
        )
    )


def _citation_inventory(
    findings: tuple[RuleFinding, ...],
    warnings: tuple[InteractionAnswerWarning, ...],
) -> tuple[AnswerCitation, ...]:
    citations = {
        _citation_key(citation): citation
        for source in findings + warnings
        for citation in source.citations
    }
    return tuple(citations[key] for key in sorted(citations))


def _derive_report_status(
    findings: tuple[RuleFinding, ...],
    warnings: tuple[InteractionAnswerWarning, ...],
    missing: tuple[MissingInformationEntry, ...],
    notices: tuple[ProcessNotice, ...],
) -> ReportStatus:
    if warnings or any(item.kind in _REVIEW_NOTICE_KINDS for item in notices):
        return ReportStatus.NEEDS_REVIEW
    if (
        missing
        or any(item.disposition is ResolutionDisposition.PENDING for item in findings)
        or any(item.kind is ProcessNoticeKind.MISSING_SCOPE for item in notices)
    ):
        return ReportStatus.NEEDS_INFORMATION
    return ReportStatus.COMPLETE


def _validate_answer_collections(answer: CitedAnswer) -> None:
    _validate_source_step_inventory(answer.source_rule_ids, answer.source_trace_step_ids)
    source_steps = set(answer.source_trace_step_ids)
    if answer.rule_findings != tuple(sorted(answer.rule_findings, key=lambda item: item.rule_id)):
        raise ValueError("answer findings are not canonical")
    if len({item.rule_id for item in answer.rule_findings}) != len(answer.rule_findings):
        raise ValueError("answer findings must have unique rules")
    if answer.interaction_warnings != tuple(
        sorted(answer.interaction_warnings, key=lambda item: item.pair_id)
    ):
        raise ValueError("answer warnings are not canonical")
    if len({item.pair_id for item in answer.interaction_warnings}) != len(
        answer.interaction_warnings
    ):
        raise ValueError("answer warnings must have unique pairs")
    missing_keys = tuple((item.rule_id, item.field_path) for item in answer.missing_information)
    if missing_keys != tuple(sorted(set(missing_keys))):
        raise ValueError("answer missing information is not canonical")
    notice_keys = tuple(_notice_key(item) for item in answer.process_notices)
    if notice_keys != tuple(sorted(set(notice_keys))):
        raise ValueError("answer process notices are not canonical")
    _validate_citation_order(answer.citation_inventory)
    expected_inventory = _citation_inventory(answer.rule_findings, answer.interaction_warnings)
    if answer.citation_inventory != expected_inventory:
        raise ValueError("answer citation inventory does not reconcile")
    incomplete_notices = tuple(
        item
        for item in answer.process_notices
        if item.kind is ProcessNoticeKind.INTERACTION_ANALYSIS_INCOMPLETE
    )
    if answer.interaction_analysis_complete == bool(incomplete_notices):
        raise ValueError("answer interaction completeness does not reconcile")
    source_rules = set(answer.source_rule_ids)
    finding_rules = {item.rule_id for item in answer.rule_findings}
    notice_rules = {rule_id for item in answer.process_notices for rule_id in item.rule_ids}
    warning_rules = {rule_id for item in answer.interaction_warnings for rule_id in item.rule_ids}
    citation_rules = {item.source_rule_id for item in answer.citation_inventory}
    if not finding_rules.issubset(source_rules) or not source_rules.issubset(
        finding_rules | notice_rules
    ):
        raise ValueError("answer source rules do not reconcile")
    if not notice_rules.issubset(source_rules) or not warning_rules.issubset(source_rules):
        raise ValueError("answer referenced rules do not reconcile")
    if not citation_rules.issubset(source_rules):
        raise ValueError("answer citation rules do not reconcile")
    if any(item.document_id != answer.document_id for item in answer.citation_inventory):
        raise ValueError("answer citation identity does not reconcile")
    for finding in answer.rule_findings:
        if {
            finding.source_applicability_step_id,
            finding.source_resolution_step_id,
        }.difference(source_steps):
            raise ValueError("answer finding source steps do not reconcile")
    for warning in answer.interaction_warnings:
        if warning.source_interaction_step_id not in source_steps:
            raise ValueError("answer warning source step does not reconcile")
    for citation in answer.citation_inventory:
        if set(citation.source_step_ids).difference(source_steps):
            raise ValueError("answer citation source steps do not reconcile")
    for item in answer.missing_information:
        if item.rule_id not in source_rules or {
            item.source_applicability_step_id,
            item.source_resolution_step_id,
        }.difference(source_steps):
            raise ValueError("answer missing-information source does not reconcile")
    for notice in answer.process_notices:
        _validate_notice_sources(notice, source_rules, source_steps)


def _validate_source_step_inventory(rule_ids: tuple[str, ...], step_ids: tuple[str, ...]) -> None:
    expected_rule_steps = tuple(f"applicability:{item}" for item in rule_ids) + tuple(
        f"resolution:{item}" for item in rule_ids
    )
    if step_ids[: len(expected_rule_steps)] != expected_rule_steps:
        raise ValueError("answer source step inventory does not reconcile")
    interaction_steps = step_ids[len(expected_rule_steps) :]
    if interaction_steps != tuple(sorted(set(interaction_steps))):
        raise ValueError("answer interaction source steps are not canonical")
    for step_id in interaction_steps:
        if not step_id.startswith("interaction:"):
            raise ValueError("answer source step inventory is invalid")
        _, left, right = _parse_pair_id(step_id.removeprefix("interaction:"))
        if left not in rule_ids or right not in rule_ids:
            raise ValueError("answer interaction source rules do not reconcile")


def _validate_notice_sources(
    notice: ProcessNotice,
    source_rules: set[str],
    source_steps: set[str],
) -> None:
    if set(notice.rule_ids).difference(source_rules) or set(notice.source_step_ids).difference(
        source_steps
    ):
        raise ValueError("answer notice source does not reconcile")
    single_rule_kinds = {
        ProcessNoticeKind.MISSING_OFFICIAL_EVIDENCE,
        ProcessNoticeKind.MISSING_SCOPE,
        ProcessNoticeKind.SCOPE_INPUT_CONFLICT,
    }
    if notice.kind in single_rule_kinds:
        if len(notice.rule_ids) != 1:
            raise ValueError("answer notice rule shape does not reconcile")
        rule_id = notice.rule_ids[0]
        expected = tuple(sorted((f"applicability:{rule_id}", f"resolution:{rule_id}")))
        if notice.source_step_ids != expected:
            raise ValueError("answer notice step shape does not reconcile")
        return
    if notice.kind is ProcessNoticeKind.OVERRIDE_EVIDENCE_INCOMPLETE:
        if len(notice.rule_ids) != 2:
            raise ValueError("answer override notice rule shape does not reconcile")
        expected = tuple(
            sorted(
                step_id
                for rule_id in notice.rule_ids
                for step_id in (f"applicability:{rule_id}", f"resolution:{rule_id}")
            )
        )
        if notice.source_step_ids != expected:
            raise ValueError("answer override notice step shape does not reconcile")
        return
    if notice.kind is ProcessNoticeKind.INTERACTION_EVIDENCE_INCOMPLETE:
        if len(notice.rule_ids) != 2 or len(notice.source_step_ids) != 1:
            raise ValueError("answer interaction notice shape does not reconcile")
        step_id = notice.source_step_ids[0]
        if not step_id.startswith("interaction:"):
            raise ValueError("answer interaction notice step does not reconcile")
        _, left, right = _parse_pair_id(step_id.removeprefix("interaction:"))
        if notice.rule_ids != (left, right):
            raise ValueError("answer interaction notice rules do not reconcile")
        return
    if notice.kind is ProcessNoticeKind.INTERACTION_ANALYSIS_INCOMPLETE:
        if notice.rule_ids or not notice.source_step_ids:
            raise ValueError("answer incomplete-analysis notice shape does not reconcile")
        if any(not item.startswith("interaction:") for item in notice.source_step_ids):
            raise ValueError("answer incomplete-analysis notice steps do not reconcile")
        for step_id in notice.source_step_ids:
            _parse_pair_id(step_id.removeprefix("interaction:"))
        return
    raise ValueError("answer notice kind is unsupported")


def _validate_trace_identifiers(trace: ReasoningTrace) -> None:
    _validate_safe_identifier(trace.trace_id)
    _validate_safe_identifier(trace.document_id)
    for step in trace.applicability_steps:
        _validate_safe_identifier(step.rule_id)
        _validate_safe_identifier(step.subject_key)
        for field_path in step.missing_profile_fields:
            _validate_safe_identifier(field_path)
        for evidence in step.official_evidence:
            _validate_safe_identifier(evidence.document_id)
            _validate_safe_identifier(evidence.fact_id)
    for step in trace.resolution_steps:
        _validate_safe_identifier(step.rule_id)
        _validate_safe_identifier(step.subject_key)
        if step.activated_override is not None:
            _validate_safe_identifier(step.activated_override.overrider_rule_id)
    for step in trace.interaction_steps:
        _warning_id(step.pair_id)


def _render_finding(finding: RuleFinding) -> str:
    citations = _markers(finding.citations)
    scope = _scope_label(finding.scope)
    if finding.disposition is ResolutionDisposition.ACTIVE:
        message = "このトレースに記録された情報に対して、確認済みの規則が適用されます。"
    elif finding.disposition is ResolutionDisposition.OVERRIDDEN:
        assert finding.activated_override is not None
        message = (
            "この規則は、明示的に有効化されたより具体的な規則 "
            f"`{finding.activated_override.overrider_rule_id}` に置き換えられています。"
        )
    elif finding.disposition is ResolutionDisposition.NOT_APPLICABLE:
        message = "このトレースに記録された情報に対して、確認済みの規則は適用されません。"
    else:
        message = "情報が不足しているため、この規則の適用可否はまだ確定できません。"
    return f"- 規則 `{finding.rule_id}`（対象: {scope}）: {message} {citations}"


def _render_warning(warning: InteractionAnswerWarning) -> str:
    labels = {
        "conflict": "規則間の競合",
        "ambiguity": "規則間の曖昧さ",
        "unreviewed_interaction": "未確認の規則間関係",
    }
    certainty = "確定" if warning.certainty is InteractionCertainty.CONFIRMED else "可能性"
    left, right = warning.rule_ids
    return (
        f"- **{labels[warning.kind]}（{certainty}）:** `{left}` と `{right}`。"
        f" {_markers(warning.citations)}"
    )


def _render_notice(notice: ProcessNotice) -> str:
    labels = {
        ProcessNoticeKind.MISSING_OFFICIAL_EVIDENCE: "公式根拠が不足しているため、規則所見を表示できません。",
        ProcessNoticeKind.OVERRIDE_EVIDENCE_INCOMPLETE: "置換元と置換先の公式根拠がそろっていないため、置換所見を表示できません。",
        ProcessNoticeKind.INTERACTION_EVIDENCE_INCOMPLETE: "両方の規則の公式根拠がそろっていないため、規則間警告を表示できません。",
        ProcessNoticeKind.MISSING_SCOPE: "対象範囲の情報が不足しています。",
        ProcessNoticeKind.SCOPE_INPUT_CONFLICT: "対象範囲の入力が整合していないため、確認が必要です。",
        ProcessNoticeKind.INTERACTION_ANALYSIS_INCOMPLETE: "規則間関係の確認が完了していません。",
    }
    rules = ""
    if notice.rule_ids:
        rules = " 対象規則: " + ", ".join(f"`{item}`" for item in notice.rule_ids) + "。"
    return f"- **処理上の通知:** {labels[notice.kind]}{rules}"


def _render_inventory_item(citation: AnswerCitation) -> str:
    role = "主要" if citation.role is EvidenceRole.PRIMARY else "参照先"
    source = (
        "規則間警告"
        if any(item.startswith("interaction:") for item in citation.source_step_ids)
        else "規則所見"
    )
    return (
        f"- {_marker(citation)} 文書 `{citation.document_id}` / 規則 "
        f"`{citation.source_rule_id}` / 役割: {role} / 参照元: {source}"
    )


def _markers(citations: tuple[AnswerCitation, ...]) -> str:
    markers = tuple(dict.fromkeys(_marker(item) for item in citations))
    return " ".join(markers)


def _marker(citation: AnswerCitation) -> str:
    if len(citation.source_pages) == 1:
        pages = f"p.{citation.source_pages[0]}"
    else:
        pages = "pp." + ",".join(str(item) for item in citation.source_pages)
    return f"[{citation.fact_id}, {pages}]"


def _scope_label(scope: RuleScope) -> str:
    if scope.scope_type == "global":
        return "全体"
    details = list(scope.scope_targets)
    if scope.parent_college is not None:
        details.append(scope.parent_college)
    escaped = ", ".join(_escape_text(item) for item in details)
    return f"{scope.scope_type}: {escaped}"


def _escape_text(value: str) -> str:
    escaped = html.escape(value, quote=True)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", escaped)


def _status_label(status: ReportStatus) -> str:
    return {
        ReportStatus.COMPLETE: "完了",
        ReportStatus.NEEDS_INFORMATION: "追加情報が必要",
        ReportStatus.NEEDS_REVIEW: "確認が必要",
    }[status]


def _warning_id(pair_id: str) -> str:
    _parse_pair_id(pair_id)
    encoded = base64.urlsafe_b64encode(pair_id.encode("utf-8")).decode("ascii").rstrip("=")
    return f"warning:{encoded}"


def _parse_pair_id(pair_id: str) -> tuple[str, str, str]:
    try:
        payload = json.loads(pair_id)
        if (
            not isinstance(payload, list)
            or len(payload) != 3
            or not all(isinstance(item, str) for item in payload)
        ):
            raise ValueError
        subject, left, right = payload
        _validate_safe_identifier(subject)
        _validate_safe_identifier(left)
        _validate_safe_identifier(right)
        if left >= right:
            raise ValueError
        canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if pair_id != canonical:
            raise ValueError
    except (json.JSONDecodeError, TypeError, ValueError):
        raise CitedAnswerError("cited answer input is invalid or inconsistent") from None
    return subject, left, right


def _citation_key(citation: AnswerCitation) -> tuple[Any, ...]:
    return (
        citation.document_id,
        citation.fact_id,
        citation.source_pages,
        citation.role.value,
        citation.source_rule_id,
        citation.source_step_ids,
    )


def _notice_key(notice: ProcessNotice) -> tuple[Any, ...]:
    return (notice.kind.value, notice.rule_ids, notice.source_step_ids)


def _validate_citation_order(citations: tuple[AnswerCitation, ...]) -> None:
    keys = tuple(_citation_key(item) for item in citations)
    if keys != tuple(sorted(set(keys))):
        raise ValueError("citations must be sorted and unique")


def _validate_safe_identifier(value: str) -> None:
    if not isinstance(value, str) or _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError("identifier is unsafe or unsupported")


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("value must be lowercase SHA-256")
