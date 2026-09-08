"""Deterministic, self-auditing reports over reviewed admission rules."""

from __future__ import annotations

import hashlib
import html
import json
import re
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from ..schemas.document_identity import DocumentIdentity
from .applicability import (
    ApplicabilityError,
    DirectOfficialEvidence,
    EvidenceRole,
    OfficialEvidenceReference,
    _evidence_scope_matches_rule,
    evaluate_applicability_with_direct_evidence,
)
from .applicant_profile import ApplicantProfile
from .cited_answer import (
    CitedAnswer,
    CitedAnswerError,
    ReportStatus,
    build_cited_answer,
    render_cited_answer_markdown,
)
from .query_intent import QueryIntent
from .reasoning_trace import ReasoningTrace, ReasoningTraceError, build_reasoning_trace
from .reviewed_report_evidence import ReviewedReportEvidenceBundle
from .reviewed_report_plan import ReviewedReportPlan
from .rule_interaction import RuleInteractionError, analyze_rule_interactions
from .rule_resolution import RuleResolutionError, resolve_rule_precedence

APPLICANT_REPORT_SCHEMA_VERSION = "1.0"
SUPPORTED_APPLICANT_REPORT_SCHEMA_VERSIONS = frozenset({APPLICANT_REPORT_SCHEMA_VERSION})
_GENERIC_ERROR_MESSAGE = "applicant report operation failed"
_SAFE_REPORT_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")


class ApplicantReportFailure(str, Enum):
    """Stable privacy-safe report failure codes."""

    INVALID_INPUT = "invalid_input"
    PLAN_EVIDENCE_MISMATCH = "plan_evidence_mismatch"
    UNSUPPORTED_INTENT = "unsupported_intent"
    APPLICABILITY_FAILED = "applicability_failed"
    RESOLUTION_FAILED = "resolution_failed"
    INTERACTION_FAILED = "interaction_failed"
    TRACE_FAILED = "trace_failed"
    ANSWER_FAILED = "answer_failed"
    INVALID_REPORT = "invalid_report"


class ApplicantReportError(Exception):
    """One generic public error carrying an allowlisted diagnostic code."""

    def __init__(self, code: ApplicantReportFailure) -> None:
        self.code = code
        super().__init__(_GENERIC_ERROR_MESSAGE)


class ApplicantReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApplicantReportCounts(ApplicantReportModel):
    rule_count: StrictInt = Field(ge=1)
    finding_count: StrictInt = Field(ge=0)
    evidence_record_count: StrictInt = Field(ge=1)
    source_page_count: StrictInt = Field(ge=1)


class ApplicantReport(ApplicantReportModel):
    """One partial reviewed-rule report with independently rebuildable derivations."""

    schema_version: Literal["1.0"] = APPLICANT_REPORT_SCHEMA_VERSION
    report_id: str
    plan_id: str
    document_identity: DocumentIdentity
    source_kb_sha256: str
    coverage_status: Literal["partial_reviewed_rules"] = "partial_reviewed_rules"
    reviewed_coverage_statement: str
    limitation_statement: str
    source_plan: ReviewedReportPlan
    evidence_bundle: ReviewedReportEvidenceBundle
    reasoning_trace: ReasoningTrace
    cited_answer: CitedAnswer
    counts: ApplicantReportCounts
    report_status: ReportStatus

    @model_validator(mode="before")
    @classmethod
    def nested_sources_must_be_revalidated(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        detached = dict(value)
        nested_types = {
            "document_identity": DocumentIdentity,
            "source_plan": ReviewedReportPlan,
            "evidence_bundle": ReviewedReportEvidenceBundle,
            "reasoning_trace": ReasoningTrace,
            "cited_answer": CitedAnswer,
            "counts": ApplicantReportCounts,
        }
        for field_name, model_type in nested_types.items():
            item = detached.get(field_name)
            if isinstance(item, model_type):
                detached[field_name] = item.model_dump(mode="json")
        return detached

    @field_validator("report_id")
    @classmethod
    def report_id_must_be_safe(cls, value: str) -> str:
        if not isinstance(value, str) or _SAFE_REPORT_ID.fullmatch(value) is None:
            raise ValueError("report ID is unsafe or unsupported")
        return value

    @field_validator("plan_id", "reviewed_coverage_statement", "limitation_statement")
    @classmethod
    def reviewed_text_must_be_explicit(cls, value: str) -> str:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("reviewed report text must be explicit")
        return value

    @field_validator("source_kb_sha256")
    @classmethod
    def source_hash_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value

    @model_validator(mode="after")
    def report_must_be_self_auditing(self) -> ApplicantReport:
        try:
            _validate_report_contract(self)
        except (
            ApplicabilityError,
            CitedAnswerError,
            ReasoningTraceError,
            RuleInteractionError,
            RuleResolutionError,
            TypeError,
            ValueError,
        ):
            raise ValueError("applicant report does not reconcile") from None
        return self


def build_applicant_report(
    report_id: str,
    profile: ApplicantProfile,
    intent: QueryIntent,
    plan: ReviewedReportPlan,
    evidence_bundle: ReviewedReportEvidenceBundle,
) -> ApplicantReport:
    """Run one reviewed plan through the existing M4 reasoning pipeline."""

    try:
        _validate_report_id(report_id)
        profile, intent, plan, evidence_bundle = _revalidate_build_inputs(
            profile, intent, plan, evidence_bundle
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        _fail(ApplicantReportFailure.INVALID_INPUT)

    if not intent.requested_categories or not set(intent.requested_categories).issubset(
        plan.covered_categories
    ):
        _fail(ApplicantReportFailure.UNSUPPORTED_INTENT)
    try:
        _validate_plan_evidence(plan, evidence_bundle)
    except ValueError:
        _fail(ApplicantReportFailure.PLAN_EVIDENCE_MISMATCH)

    records = {record.fact_id: record for record in evidence_bundle.evidence_records}
    decisions = []
    try:
        for rule in plan.rules:
            direct_evidence = DirectOfficialEvidence(
                document_id=plan.document_identity.document_id,
                source_kb_sha256=plan.source_kb_sha256,
                source_pdf_sha256=plan.document_identity.source_pdf_sha256,
                official_evidence=tuple(
                    OfficialEvidenceReference(
                        document_id=binding.document_id,
                        fact_id=binding.fact_id,
                        source_pages=records[binding.fact_id].source_pages,
                        role=EvidenceRole.PRIMARY,
                    )
                    for binding in rule.evidence_bindings
                ),
            )
            decisions.append(
                evaluate_applicability_with_direct_evidence(
                    profile,
                    intent,
                    direct_evidence,
                    rule,
                )
            )
    except (ApplicabilityError, KeyError, ValidationError, ValueError):
        _fail(ApplicantReportFailure.APPLICABILITY_FAILED)

    decisions_tuple = tuple(decisions)
    try:
        resolution = resolve_rule_precedence(
            plan.rules,
            decisions_tuple,
            plan.precedence_policy,
        )
    except RuleResolutionError:
        _fail(ApplicantReportFailure.RESOLUTION_FAILED)
    try:
        interaction_report = analyze_rule_interactions(resolution, plan.interaction_policy)
    except RuleInteractionError:
        _fail(ApplicantReportFailure.INTERACTION_FAILED)
    try:
        trace = build_reasoning_trace(
            f"trace:{report_id}",
            plan.rules,
            decisions_tuple,
            interaction_report,
        )
    except ReasoningTraceError:
        _fail(ApplicantReportFailure.TRACE_FAILED)
    try:
        answer = build_cited_answer(f"answer:{report_id}", trace)
    except CitedAnswerError:
        _fail(ApplicantReportFailure.ANSWER_FAILED)

    counts = ApplicantReportCounts(
        rule_count=len(plan.rules),
        finding_count=len(answer.rule_findings),
        evidence_record_count=len(evidence_bundle.evidence_records),
        source_page_count=len(
            {page for record in evidence_bundle.evidence_records for page in record.source_pages}
        ),
    )
    try:
        report = ApplicantReport(
            report_id=report_id,
            plan_id=plan.plan_id,
            document_identity=plan.document_identity,
            source_kb_sha256=plan.source_kb_sha256,
            coverage_status=plan.coverage_status,
            reviewed_coverage_statement=plan.reviewed_coverage_statement,
            limitation_statement=plan.limitation_statement,
            source_plan=plan,
            evidence_bundle=evidence_bundle,
            reasoning_trace=trace,
            cited_answer=answer,
            counts=counts,
            report_status=answer.report_status,
        )
        return load_applicant_report_bytes(canonical_applicant_report_bytes(report))
    except (ApplicantReportError, ValidationError, ValueError):
        _fail(ApplicantReportFailure.INVALID_REPORT)


def canonical_applicant_report_bytes(report: ApplicantReport) -> bytes:
    """Serialize one revalidated report as canonical finite UTF-8 JSON."""

    try:
        if not isinstance(report, ApplicantReport) or set(report.__dict__) != set(
            ApplicantReport.model_fields
        ):
            raise TypeError
        validated = ApplicantReport.model_validate(report.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (
        ApplicabilityError,
        CitedAnswerError,
        ReasoningTraceError,
        RuleInteractionError,
        RuleResolutionError,
        TypeError,
        ValidationError,
        ValueError,
    ):
        _fail(ApplicantReportFailure.INVALID_REPORT)
    return f"{serialized}\n".encode("utf-8")


def load_applicant_report_bytes(raw_bytes: bytes) -> ApplicantReport:
    """Load strict report bytes without accepting a persistence path."""

    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") not in SUPPORTED_APPLICANT_REPORT_SCHEMA_VERSIONS
        ):
            raise ValueError
        return ApplicantReport.model_validate(payload)
    except (
        ApplicabilityError,
        CitedAnswerError,
        ReasoningTraceError,
        RuleInteractionError,
        RuleResolutionError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValidationError,
        ValueError,
    ):
        _fail(ApplicantReportFailure.INVALID_REPORT)


def render_applicant_report_markdown(report: ApplicantReport) -> str:
    """Render fixed Japanese report text plus literal inert official evidence."""

    try:
        if not isinstance(report, ApplicantReport) or set(report.__dict__) != set(
            ApplicantReport.model_fields
        ):
            raise TypeError
        validated = ApplicantReport.model_validate(report.model_dump(mode="json"))
        answer_markdown = render_cited_answer_markdown(validated.cited_answer)
        result_heading = "## 規則ごとの確認結果"
        before_results, after_heading = answer_markdown.split(result_heading, maxsplit=1)
    except (
        ApplicabilityError,
        CitedAnswerError,
        ReasoningTraceError,
        RuleInteractionError,
        RuleResolutionError,
        AttributeError,
        TypeError,
        ValidationError,
        ValueError,
    ):
        _fail(ApplicantReportFailure.INVALID_REPORT)

    coverage = "\n".join(
        (
            "## 審査済み範囲",
            "",
            "> **部分的な規則範囲です。** このレポートだけでは、総合的な出願資格、合否、合格可能性、または推奨を判断できません。",
            "",
            f"- **確認済み設定:** {_escape_markdown_inline(validated.reviewed_coverage_statement)}",
            f"- **制限事項:** {_escape_markdown_inline(validated.limitation_statement)}",
            "",
        )
    )
    lines = [
        before_results.rstrip(),
        "",
        coverage.rstrip(),
        "",
        result_heading + after_heading,
    ]
    active_direct_ids = {
        finding.rule_id
        for finding in validated.cited_answer.rule_findings
        if finding.disposition.value == "active"
        and finding.rule_id.startswith("isct-master-direct-path-")
    }
    reviewed_notes = [
        rule.annotation_note
        for rule in validated.source_plan.rules
        if rule.rule_id in active_direct_ids
    ]
    if reviewed_notes:
        lines.extend(("", "## 直接経路の審査済み説明", ""))
        lines.extend(f"- {_escape_markdown_inline(note)}" for note in reviewed_notes)
    lines.extend(("", "## 公式根拠（原文）", ""))
    for record in validated.evidence_bundle.evidence_records:
        lines.extend(
            (
                f"### {_evidence_marker(record.fact_id, record.source_pages)}",
                "",
                f"- **文書:** `{record.document_id}`",
                "- **公式原文:**",
                "",
                _literal_fenced_block(record.text),
                "",
            )
        )
    lines.extend(
        (
            "> **状態が「完了」でも、意味するのはレポート生成の準備完了だけです。部分的な規則範囲から、総合的な出願資格、合否、合格可能性、または推奨は判断できません。",
            "",
        )
    )
    return "\n".join(lines)


def _revalidate_build_inputs(
    profile: Any,
    intent: Any,
    plan: Any,
    evidence_bundle: Any,
) -> tuple[ApplicantProfile, QueryIntent, ReviewedReportPlan, ReviewedReportEvidenceBundle]:
    _require_exact_model(profile, ApplicantProfile)
    _require_exact_model(intent, QueryIntent)
    _require_exact_model(plan, ReviewedReportPlan)
    _require_exact_model(evidence_bundle, ReviewedReportEvidenceBundle)
    return (
        ApplicantProfile.model_validate(profile.model_dump(mode="json")),
        QueryIntent.model_validate(intent.model_dump(mode="json")),
        ReviewedReportPlan.model_validate(plan.model_dump(mode="json")),
        ReviewedReportEvidenceBundle.model_validate(evidence_bundle.model_dump(mode="json")),
    )


def _require_exact_model(value: Any, model_type: type[BaseModel]) -> None:
    if not isinstance(value, model_type) or set(value.__dict__) != set(model_type.model_fields):
        raise TypeError


def _validate_plan_evidence(
    plan: ReviewedReportPlan,
    evidence_bundle: ReviewedReportEvidenceBundle,
) -> None:
    if (
        plan.plan_id != evidence_bundle.plan_id
        or plan.document_identity != evidence_bundle.document_identity
        or plan.source_kb_sha256 != evidence_bundle.source_kb_sha256
    ):
        raise ValueError
    records = {record.fact_id: record for record in evidence_bundle.evidence_records}
    expected_rule_ids: dict[str, set[str]] = {}
    for rule in plan.rules:
        for binding in rule.evidence_bindings:
            expected_rule_ids.setdefault(binding.fact_id, set()).add(rule.rule_id)
            record = records.get(binding.fact_id)
            if record is None or (
                record.document_id != binding.document_id
                or record.source_pages != binding.source_pages
                or hashlib.sha256(record.text.encode("utf-8")).hexdigest()
                != binding.authoritative_fact_text_sha256
                or not _evidence_scope_matches_rule(record, rule.scope)
            ):
                raise ValueError
    if set(records) != set(expected_rule_ids):
        raise ValueError
    for fact_id, rule_ids in expected_rule_ids.items():
        if records[fact_id].rule_ids != tuple(sorted(rule_ids)):
            raise ValueError


def _validate_report_contract(report: ApplicantReport) -> None:
    plan = report.source_plan
    evidence = report.evidence_bundle
    if (
        report.plan_id != plan.plan_id
        or report.document_identity != plan.document_identity
        or report.source_kb_sha256 != plan.source_kb_sha256
        or report.coverage_status != plan.coverage_status
        or report.reviewed_coverage_statement != plan.reviewed_coverage_statement
        or report.limitation_statement != plan.limitation_statement
    ):
        raise ValueError
    _validate_plan_evidence(plan, evidence)
    trace = report.reasoning_trace
    if trace.trace_id != f"trace:{report.report_id}":
        raise ValueError
    resolution = resolve_rule_precedence(
        plan.rules,
        trace.source_decisions,
        plan.precedence_policy,
    )
    interaction = analyze_rule_interactions(resolution, plan.interaction_policy)
    expected_trace = build_reasoning_trace(
        trace.trace_id,
        plan.rules,
        trace.source_decisions,
        interaction,
    )
    if trace != expected_trace:
        raise ValueError
    answer = report.cited_answer
    if answer.answer_id != f"answer:{report.report_id}":
        raise ValueError
    if answer != build_cited_answer(answer.answer_id, expected_trace):
        raise ValueError
    _validate_decision_and_citation_evidence(report)
    expected_counts = ApplicantReportCounts(
        rule_count=len(plan.rules),
        finding_count=len(answer.rule_findings),
        evidence_record_count=len(evidence.evidence_records),
        source_page_count=len(
            {page for record in evidence.evidence_records for page in record.source_pages}
        ),
    )
    if report.counts != expected_counts or report.report_status is not answer.report_status:
        raise ValueError


def _validate_decision_and_citation_evidence(report: ApplicantReport) -> None:
    records = {record.fact_id: record for record in report.evidence_bundle.evidence_records}
    rules = {rule.rule_id: rule for rule in report.source_plan.rules}
    expected_pairs: set[tuple[str, str, tuple[int, ...]]] = set()
    for decision in report.reasoning_trace.source_decisions:
        rule = rules.get(decision.rule_id)
        if rule is None:
            raise ValueError
        expected_refs = tuple(
            OfficialEvidenceReference(
                document_id=binding.document_id,
                fact_id=binding.fact_id,
                source_pages=records[binding.fact_id].source_pages,
                role=EvidenceRole.PRIMARY,
            )
            for binding in rule.evidence_bindings
        )
        if decision.official_evidence != expected_refs:
            raise ValueError
        expected_pairs.update(
            (decision.rule_id, reference.fact_id, reference.source_pages)
            for reference in expected_refs
        )
    actual_pairs = {
        (citation.source_rule_id, citation.fact_id, citation.source_pages)
        for citation in report.cited_answer.citation_inventory
    }
    if actual_pairs != expected_pairs:
        raise ValueError


def _evidence_marker(fact_id: str, pages: tuple[int, ...]) -> str:
    page_label = f"p.{pages[0]}" if len(pages) == 1 else "pp." + ",".join(map(str, pages))
    return f"[{fact_id}, {page_label}]"


def _literal_fenced_block(text: str) -> str:
    longest_run = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, longest_run + 1)
    return f"{fence}\n{text}\n{fence}"


def _escape_markdown_inline(value: str) -> str:
    escaped = html.escape(value, quote=True).replace("\\", "\\\\")
    for character in "`*_{}[]()#+-.!|>":
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _validate_report_id(value: Any) -> None:
    if not isinstance(value, str) or _SAFE_REPORT_ID.fullmatch(value) is None:
        raise ValueError


def _validate_sha256(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError


def _reject_constant(_: str) -> Any:
    raise ValueError


def _fail(code: ApplicantReportFailure) -> Any:
    raise ApplicantReportError(code) from None


__all__ = [
    "APPLICANT_REPORT_SCHEMA_VERSION",
    "SUPPORTED_APPLICANT_REPORT_SCHEMA_VERSIONS",
    "ApplicantReport",
    "ApplicantReportCounts",
    "ApplicantReportError",
    "ApplicantReportFailure",
    "build_applicant_report",
    "canonical_applicant_report_bytes",
    "load_applicant_report_bytes",
    "render_applicant_report_markdown",
]
