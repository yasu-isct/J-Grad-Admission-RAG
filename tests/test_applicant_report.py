from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jgrad_admission_rag.reasoning.applicability import (
    ApplicabilityError,
    ApplicabilityPredicate,
    ApplicabilityRule,
    LogicalMode,
    OfficialEvidenceBinding,
    PredicateOperator,
    RuleScope,
)
from jgrad_admission_rag.reasoning.applicant_profile import ApplicantProfile
from jgrad_admission_rag.reasoning.applicant_report import (
    ApplicantReportError,
    ApplicantReportFailure,
    build_applicant_report,
    canonical_applicant_report_bytes,
    load_applicant_report_bytes,
    render_applicant_report_markdown,
)
from jgrad_admission_rag.reasoning.cited_answer import ReportStatus
from jgrad_admission_rag.reasoning.cited_answer import CitedAnswerError
from jgrad_admission_rag.reasoning.query_intent import (
    DiagnosticCode,
    IntentCategory,
    IntentMention,
    MentionKind,
    QueryIntent,
    RequestedScope,
)
from jgrad_admission_rag.reasoning.reviewed_report_evidence import (
    ReviewedReportEvidenceBundle,
    ReviewedReportEvidenceCounts,
    ReviewedReportEvidenceRecord,
)
from jgrad_admission_rag.reasoning.reviewed_report_plan import ReviewedReportPlan
from jgrad_admission_rag.reasoning.reasoning_trace import ReasoningTraceError
from jgrad_admission_rag.reasoning.rule_interaction import (
    InteractionRelationship,
    InteractionWarningKind,
    RuleInteraction,
    RuleInteractionError,
    RuleInteractionPolicy,
)
from jgrad_admission_rag.reasoning.rule_resolution import (
    OverrideEdge,
    ResolutionDisposition,
    RulePrecedencePolicy,
    RuleSubjectAssignment,
    RuleResolutionError,
)
from tests.test_reviewed_report_evidence import _context, _prepare


def _profile(
    age: int | None = 24,
    *,
    secret: str | None = None,
    college: str | None = None,
) -> ApplicantProfile:
    return ApplicantProfile.model_validate(
        {
            "schema_version": "1.0",
            "target_application": {
                "graduate_school_or_college": secret or college,
                "department_or_program": None,
                "requested_degree_level": "master",
                "intake_year": 2027,
                "intake_month": 4,
                "application_route": secret,
            },
            "citizenship_and_residence": {
                "citizenship_country_codes": None,
                "current_residence_country_code": None,
                "residence_status_category": None,
            },
            "academic_credentials": None,
            "eligibility_facts": {
                "age_at_enrollment": age,
                "professional_experience_months": None,
                "research_experience_months": None,
                "individual_review_status": None,
                "individual_review_requested": None,
                "individual_review_completed": None,
            },
            "language_test_results": None,
        }
    )


def _intent(*categories: IntentCategory, secret: str = "") -> QueryIntent:
    query_parts = [category.value for category in categories]
    query_parts.append(secret)
    query = " ".join(part for part in query_parts if part) or "unknown"
    mentions = []
    cursor = 0
    for category in categories:
        surface = category.value
        start = query.index(surface, cursor)
        mentions.append(
            IntentMention(
                canonical_value=category.value,
                mention_kind=MentionKind.INTENT,
                start_offset=start,
                end_offset=start + len(surface),
                surface=surface,
            )
        )
        cursor = start + len(surface)
    return QueryIntent(
        schema_version="1.0",
        parser_version="lexical-ja-v1",
        catalog_version="report-test-v1",
        query=query,
        requested_categories=tuple(sorted(set(categories), key=lambda item: item.value)),
        requested_scope=RequestedScope(
            department_or_program_targets=(),
            parent_college_values=(),
            target_degree_level=None,
            intake_year=None,
            intake_month=None,
        ),
        matched_mentions=tuple(mentions),
        diagnostics=() if categories else (DiagnosticCode.NO_RECOGNIZED_INTENT,),
    )


def _build(tmp_path: Path, *, age: int | None = 24, secret: str = ""):
    context = _context(tmp_path)
    evidence = _prepare(context)
    report = build_applicant_report(
        "sample-report-v1",
        _profile(age, secret=secret or None),
        _intent(IntentCategory.ELIGIBILITY, secret=secret),
        context.plan,
        evidence,
    )
    return context.plan, evidence, report


def _synthetic_rule(
    identity,
    source_kb_sha256: str,
    *,
    rule_id: str,
    fact_id: str,
    field_path: str = "eligibility_facts.age_at_enrollment",
    operator: PredicateOperator = PredicateOperator.MINIMUM,
    expected_value: int = 18,
    scope: RuleScope | None = None,
    pages: tuple[int, ...] | None = None,
) -> tuple[ApplicabilityRule, str]:
    text = f"Official text for {fact_id}."
    return (
        ApplicabilityRule(
            rule_id=rule_id,
            mode=LogicalMode.ALL,
            predicates=(
                ApplicabilityPredicate(
                    field_path=field_path,
                    operator=operator,
                    expected_value=expected_value,
                ),
            ),
            scope=scope or RuleScope(scope_type="global"),
            evidence_bindings=(
                OfficialEvidenceBinding(
                    document_id=identity.document_id,
                    source_kb_sha256=source_kb_sha256,
                    source_pdf_sha256=identity.source_pdf_sha256,
                    fact_id=fact_id,
                    source_pages=pages or (int(fact_id.rsplit(":", maxsplit=1)[1]) + 1,),
                    authoritative_fact_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                ),
            ),
            annotation_note=f"Reviewed annotation for {rule_id}.",
        ),
        text,
    )


def _synthetic_plan_and_evidence(
    base_plan: ReviewedReportPlan,
    rule_specs: tuple[tuple[ApplicabilityRule, str], ...],
    subjects: tuple[tuple[str, str], ...],
    *,
    overrides: tuple[OverrideEdge, ...] = (),
    interactions: tuple[RuleInteraction, ...] = (),
) -> tuple[ReviewedReportPlan, ReviewedReportEvidenceBundle]:
    rules = tuple(item[0] for item in rule_specs)
    plan = ReviewedReportPlan(
        plan_id="multi-rule-plan-v1",
        document_identity=base_plan.document_identity,
        rules=rules,
        precedence_policy=RulePrecedencePolicy(
            policy_id="multi-rule-precedence-v1",
            subjects=tuple(
                RuleSubjectAssignment(rule_id=rule_id, subject_key=subject)
                for rule_id, subject in subjects
            ),
            override_edges=overrides,
        ),
        interaction_policy=RuleInteractionPolicy(
            policy_id="multi-rule-interactions-v1",
            interactions=interactions,
        ),
        covered_categories=(IntentCategory.ELIGIBILITY,),
        coverage_status="partial_reviewed_rules",
        reviewed_coverage_statement="Covers reviewed synthetic multi-rule behavior.",
        limitation_statement="Does not establish overall eligibility or admission.",
    )
    grouped: dict[str, tuple[ApplicabilityRule, str, list[str]]] = {}
    for rule, text in rule_specs:
        fact_id = rule.evidence_bindings[0].fact_id
        if fact_id not in grouped:
            grouped[fact_id] = (rule, text, [])
        grouped[fact_id][2].append(rule.rule_id)
    records = tuple(
        ReviewedReportEvidenceRecord(
            document_id=plan.document_identity.document_id,
            fact_id=fact_id,
            text=text,
            source_pages=rule.evidence_bindings[0].source_pages,
            section_path=("Eligibility",),
            fact_type="eligibility",
            scope_type=rule.scope.scope_type,
            scope_targets=rule.scope.scope_targets,
            parent_college=rule.scope.parent_college,
            rule_ids=tuple(sorted(rule_ids)),
        )
        for fact_id, (rule, text, rule_ids) in sorted(grouped.items())
    )
    evidence = ReviewedReportEvidenceBundle(
        plan_id=plan.plan_id,
        document_identity=plan.document_identity,
        source_kb_sha256=plan.source_kb_sha256,
        evidence_records=records,
        counts=ReviewedReportEvidenceCounts(
            record_count=len(records),
            rule_count=len(rules),
            source_page_count=len({page for record in records for page in record.source_pages}),
        ),
    )
    return plan, evidence


def test_report_round_trip_is_exact_self_auditing_and_private(tmp_path: Path) -> None:
    secret = "PLANTED_APPLICANT_QUERY_PATH_MODEL_SECRET"
    plan, evidence, report = _build(tmp_path, secret=secret)

    raw = canonical_applicant_report_bytes(report)
    loaded = load_applicant_report_bytes(raw)
    markdown = render_applicant_report_markdown(report)

    assert loaded == report
    assert canonical_applicant_report_bytes(loaded) == raw
    assert report.plan_id == plan.plan_id
    assert report.evidence_bundle == evidence
    assert report.report_status is ReportStatus.COMPLETE
    assert report.counts.rule_count == 1
    assert report.counts.finding_count == 1
    assert report.counts.evidence_record_count == 1
    assert report.counts.source_page_count == 1
    assert report.cited_answer == loaded.cited_answer
    assert secret not in raw.decode("utf-8")
    assert secret not in markdown
    assert report.source_kb_sha256 not in markdown
    for forbidden in (
        '"query"',
        '"applicant_profile"',
        '"ranking_score"',
        '"rank"',
        '"channel"',
        '"local_path"',
        '"model_output"',
        '"eligibility_conclusion"',
    ):
        assert forbidden not in raw.decode("utf-8")
    assert "部分的な規則範囲です" in markdown
    assert evidence.evidence_records[0].text in markdown
    assert "[fact:00000, p.1]" in markdown


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"plan_id": "other-plan"}),
        lambda value: value["document_identity"].update({"document_id": "other-document"}),
        lambda value: value.update({"reviewed_coverage_statement": "altered coverage"}),
        lambda value: value["counts"].update({"finding_count": 0}),
        lambda value: value.update({"report_status": "needs_review"}),
        lambda value: value["reasoning_trace"].update({"trace_id": "trace:altered"}),
        lambda value: value["cited_answer"].update({"answer_id": "answer:altered"}),
        lambda value: value["cited_answer"]["rule_findings"][0]["citations"][0].update(
            {"source_pages": [2]}
        ),
        lambda value: value["evidence_bundle"]["evidence_records"][0].update(
            {"text": "altered official text"}
        ),
        lambda value: value["evidence_bundle"].update({"evidence_records": []}),
        lambda value: value.update({"query": "forbidden extra"}),
        lambda value: value.pop("limitation_statement"),
    ],
)
def test_report_loader_rejects_tampered_derived_or_source_fields(
    tmp_path: Path,
    mutation,
) -> None:
    _, _, report = _build(tmp_path)
    payload = report.model_dump(mode="json")
    mutation(payload)
    with pytest.raises(ApplicantReportError) as exc_info:
        load_applicant_report_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    assert exc_info.value.code is ApplicantReportFailure.INVALID_REPORT
    assert str(exc_info.value) == "applicant report operation failed"


def test_report_serialization_and_rendering_reject_hidden_model_copy_fields(
    tmp_path: Path,
) -> None:
    _, _, report = _build(tmp_path)
    bypassed = report.model_copy(update={"conclusion": "planted conclusion"})
    for operation in (canonical_applicant_report_bytes, render_applicant_report_markdown):
        with pytest.raises(ApplicantReportError) as exc_info:
            operation(bypassed)
        assert exc_info.value.code is ApplicantReportFailure.INVALID_REPORT
        assert "planted conclusion" not in str(exc_info.value)


def test_plan_evidence_identity_text_scope_rule_map_and_coverage_mismatches_fail(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    evidence = _prepare(context)
    variants = []
    for field, value in (
        ("plan_id", "other-plan"),
        ("source_kb_sha256", "d" * 64),
    ):
        variants.append(evidence.model_copy(update={field: value}))

    record = evidence.evidence_records[0]
    for changes in (
        {"text": "changed"},
        {"source_pages": (2,)},
        {"scope_type": "unknown"},
        {"rule_ids": ("other-rule",)},
    ):
        changed = record.model_copy(update=changes)
        variants.append(evidence.model_copy(update={"evidence_records": (changed,)}))

    extra = record.model_copy(update={"fact_id": "fact:extra"})
    variants.append(
        ReviewedReportEvidenceBundle(
            plan_id=evidence.plan_id,
            document_identity=evidence.document_identity,
            source_kb_sha256=evidence.source_kb_sha256,
            evidence_records=(record, extra),
            counts={"record_count": 2, "rule_count": 1, "source_page_count": 1},
        )
    )
    for variant in variants:
        with pytest.raises(ApplicantReportError) as exc_info:
            build_applicant_report(
                "sample-report-v1",
                _profile(),
                _intent(IntentCategory.ELIGIBILITY),
                context.plan,
                variant,
            )
        assert exc_info.value.code is ApplicantReportFailure.PLAN_EVIDENCE_MISMATCH


def test_empty_unsupported_and_mixed_intents_fail_before_applicant_evaluation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    evidence = _prepare(context)
    from jgrad_admission_rag.reasoning import applicant_report as module

    calls = []

    def evaluation_spy(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("applicant evaluation must not run")

    monkeypatch.setattr(module, "evaluate_applicability_with_direct_evidence", evaluation_spy)
    for intent in (
        _intent(),
        _intent(IntentCategory.FEES),
        _intent(IntentCategory.ELIGIBILITY, IntentCategory.FEES),
    ):
        with pytest.raises(ApplicantReportError) as exc_info:
            build_applicant_report(
                "sample-report-v1",
                _profile(),
                intent,
                context.plan,
                evidence,
            )
        assert exc_info.value.code is ApplicantReportFailure.UNSUPPORTED_INTENT
    assert calls == []


@pytest.mark.parametrize(
    ("attribute", "error", "expected"),
    [
        (
            "evaluate_applicability_with_direct_evidence",
            ApplicabilityError("planted"),
            ApplicantReportFailure.APPLICABILITY_FAILED,
        ),
        (
            "resolve_rule_precedence",
            RuleResolutionError("planted"),
            ApplicantReportFailure.RESOLUTION_FAILED,
        ),
        (
            "analyze_rule_interactions",
            RuleInteractionError("planted"),
            ApplicantReportFailure.INTERACTION_FAILED,
        ),
        (
            "build_reasoning_trace",
            ReasoningTraceError("planted"),
            ApplicantReportFailure.TRACE_FAILED,
        ),
        (
            "build_cited_answer",
            CitedAnswerError("planted"),
            ApplicantReportFailure.ANSWER_FAILED,
        ),
    ],
)
def test_pipeline_failures_have_stable_privacy_safe_stage_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    error: Exception,
    expected: ApplicantReportFailure,
) -> None:
    context = _context(tmp_path)
    evidence = _prepare(context)
    from jgrad_admission_rag.reasoning import applicant_report as module

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(module, attribute, fail)
    with pytest.raises(ApplicantReportError) as exc_info:
        build_applicant_report(
            "stage-error-v1",
            _profile(),
            _intent(IntentCategory.ELIGIBILITY),
            context.plan,
            evidence,
        )
    assert exc_info.value.code is expected
    assert str(exc_info.value) == "applicant report operation failed"
    assert "planted" not in str(exc_info.value)


def test_hidden_supplied_report_fields_are_rejected_before_build(tmp_path: Path) -> None:
    context = _context(tmp_path)
    evidence = _prepare(context)
    profile = _profile()
    intent = _intent(IntentCategory.ELIGIBILITY)
    variants = (
        (profile.model_copy(update={"report": "planted"}), intent, context.plan, evidence),
        (profile, intent.model_copy(update={"trace": "planted"}), context.plan, evidence),
        (profile, intent, context.plan.model_copy(update={"answer": "planted"}), evidence),
        (profile, intent, context.plan, evidence.model_copy(update={"conclusion": "planted"})),
    )
    for supplied_profile, supplied_intent, supplied_plan, supplied_evidence in variants:
        with pytest.raises(ApplicantReportError) as exc_info:
            build_applicant_report(
                "hidden-input-v1",
                supplied_profile,
                supplied_intent,
                supplied_plan,
                supplied_evidence,
            )
        assert exc_info.value.code is ApplicantReportFailure.INVALID_INPUT


@pytest.mark.parametrize(
    ("age", "status", "missing"),
    [
        (24, ReportStatus.COMPLETE, ()),
        (17, ReportStatus.COMPLETE, ()),
        (None, ReportStatus.NEEDS_INFORMATION, ("eligibility_facts.age_at_enrollment",)),
    ],
)
def test_applicant_statuses_are_inherited_without_overall_eligibility_wording(
    tmp_path: Path,
    age: int | None,
    status: ReportStatus,
    missing: tuple[str, ...],
) -> None:
    _, _, report = _build(tmp_path, age=age)
    markdown = render_applicant_report_markdown(report)

    assert report.report_status is status
    assert tuple(item.field_path for item in report.cited_answer.missing_information) == missing
    assert "応募者は不適格" not in markdown
    assert "総合的な出願資格" in markdown


def test_multi_rule_report_uses_public_precedence_for_every_disposition(tmp_path: Path) -> None:
    context = _context(tmp_path)
    identity = context.plan.document_identity
    source_hash = context.plan.source_kb_sha256
    rules = (
        _synthetic_rule(
            identity,
            source_hash,
            rule_id="a-broad",
            fact_id="fact:00001",
        ),
        _synthetic_rule(
            identity,
            source_hash,
            rule_id="b-narrow",
            fact_id="fact:00002",
            scope=RuleScope(scope_type="college", scope_targets=("Science College",)),
        ),
        _synthetic_rule(
            identity,
            source_hash,
            rule_id="c-pending",
            fact_id="fact:00003",
            field_path="eligibility_facts.professional_experience_months",
            expected_value=1,
        ),
        _synthetic_rule(
            identity,
            source_hash,
            rule_id="d-not-applicable",
            fact_id="fact:00004",
            operator=PredicateOperator.MAXIMUM,
            expected_value=10,
        ),
    )
    subjects = (
        ("a-broad", "eligibility.age"),
        ("b-narrow", "eligibility.age"),
        ("c-pending", "eligibility.experience"),
        ("d-not-applicable", "eligibility.other"),
    )
    plan, evidence = _synthetic_plan_and_evidence(
        context.plan,
        rules,
        subjects,
        overrides=(
            OverrideEdge(
                subject_key="eligibility.age",
                overrider_rule_id="b-narrow",
                overridden_rule_id="a-broad",
                rationale="The reviewed college rule is narrower.",
            ),
        ),
    )

    report = build_applicant_report(
        "multi-disposition-v1",
        _profile(college="Science College"),
        _intent(IntentCategory.ELIGIBILITY),
        plan,
        evidence,
    )
    dispositions = {
        item.rule_id: item.disposition
        for item in report.reasoning_trace.source_interaction_report.source_resolution.entries
    }
    assert dispositions == {
        "a-broad": ResolutionDisposition.OVERRIDDEN,
        "b-narrow": ResolutionDisposition.ACTIVE,
        "c-pending": ResolutionDisposition.PENDING,
        "d-not-applicable": ResolutionDisposition.NOT_APPLICABLE,
    }
    assert report.report_status is ReportStatus.NEEDS_INFORMATION


@pytest.mark.parametrize(
    ("relationship", "warning_kind", "status"),
    [
        (InteractionRelationship.COMPATIBLE, None, ReportStatus.COMPLETE),
        (
            InteractionRelationship.CONFLICT,
            InteractionWarningKind.CONFLICT,
            ReportStatus.NEEDS_REVIEW,
        ),
        (
            InteractionRelationship.AMBIGUOUS,
            InteractionWarningKind.AMBIGUITY,
            ReportStatus.NEEDS_REVIEW,
        ),
        (None, InteractionWarningKind.UNREVIEWED_INTERACTION, ReportStatus.NEEDS_REVIEW),
    ],
)
def test_multi_rule_report_inherits_every_reviewed_and_unreviewed_interaction_path(
    tmp_path: Path,
    relationship: InteractionRelationship | None,
    warning_kind: InteractionWarningKind | None,
    status: ReportStatus,
) -> None:
    context = _context(tmp_path)
    identity = context.plan.document_identity
    source_hash = context.plan.source_kb_sha256
    rules = (
        _synthetic_rule(
            identity,
            source_hash,
            rule_id="a-rule",
            fact_id="fact:00001",
        ),
        _synthetic_rule(
            identity,
            source_hash,
            rule_id="b-rule",
            fact_id="fact:00002",
        ),
    )
    interactions = (
        (
            RuleInteraction(
                subject_key="eligibility.age",
                rule_ids=("a-rule", "b-rule"),
                relationship=relationship,
                rationale="Reviewed interaction relationship.",
            ),
        )
        if relationship is not None
        else ()
    )
    plan, evidence = _synthetic_plan_and_evidence(
        context.plan,
        rules,
        (("a-rule", "eligibility.age"), ("b-rule", "eligibility.age")),
        interactions=interactions,
    )

    report = build_applicant_report(
        f"interaction-{relationship.value if relationship else 'unreviewed'}-v1",
        _profile(),
        _intent(IntentCategory.ELIGIBILITY),
        plan,
        evidence,
    )
    warnings = report.reasoning_trace.source_interaction_report.warnings
    assert tuple(item.kind for item in warnings) == ((warning_kind,) if warning_kind else ())
    assert report.report_status is status


def test_shared_multi_page_evidence_is_deduplicated_and_rendered_once(tmp_path: Path) -> None:
    context = _context(tmp_path)
    identity = context.plan.document_identity
    source_hash = context.plan.source_kb_sha256
    rules = (
        _synthetic_rule(
            identity,
            source_hash,
            rule_id="a-rule",
            fact_id="fact:00010",
            pages=(2, 4),
        ),
        _synthetic_rule(
            identity,
            source_hash,
            rule_id="b-rule",
            fact_id="fact:00010",
            pages=(2, 4),
        ),
    )
    plan, evidence = _synthetic_plan_and_evidence(
        context.plan,
        rules,
        (("a-rule", "subject.a"), ("b-rule", "subject.b")),
    )

    report = build_applicant_report(
        "shared-evidence-v1",
        _profile(),
        _intent(IntentCategory.ELIGIBILITY),
        plan,
        evidence,
    )
    markdown = render_applicant_report_markdown(report)

    assert report.counts.evidence_record_count == 1
    assert report.counts.source_page_count == 2
    assert evidence.evidence_records[0].rule_ids == ("a-rule", "b-rule")
    assert markdown.count(evidence.evidence_records[0].text) == 1
    assert "[fact:00010, pp.2,4]" in markdown


def test_official_markdown_html_and_backticks_remain_literal_and_cannot_hide_footer(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    evidence = _prepare(context)
    planted = "# heading\n[link](https://evil.invalid)\n<script>alert(1)</script>\n> quote\n``````"
    plan_payload = context.plan.model_dump(mode="json")
    plan_payload["rules"][0]["evidence_bindings"][0]["authoritative_fact_text_sha256"] = (
        hashlib.sha256(planted.encode("utf-8")).hexdigest()
    )
    plan_payload["reviewed_coverage_statement"] = "Reviewed [link](https://evil.invalid) <b>x</b>."
    plan = ReviewedReportPlan.model_validate(plan_payload)
    evidence_payload = evidence.model_dump(mode="json")
    evidence_payload["evidence_records"][0]["text"] = planted
    evidence_bundle = ReviewedReportEvidenceBundle.model_validate(evidence_payload)

    report = build_applicant_report(
        "literal-report-v1",
        _profile(),
        _intent(IntentCategory.ELIGIBILITY),
        plan,
        evidence_bundle,
    )
    markdown = render_applicant_report_markdown(report)

    assert planted in markdown
    assert "```````\n" + planted + "\n```````" in markdown
    assert "Reviewed \\[link\\]" in markdown
    assert "&lt;b&gt;x&lt;/b&gt;" in markdown
    assert markdown.index(planted) < markdown.index("状態が「完了」でも")
    assert render_applicant_report_markdown(report) == markdown


def test_public_error_is_generic_and_import_is_inert(tmp_path: Path) -> None:
    context = _context(tmp_path)
    planted = "private-invalid-report-id"
    with pytest.raises(ApplicantReportError) as exc_info:
        build_applicant_report(
            f"bad/{planted}",
            _profile(secret=planted),
            _intent(IntentCategory.ELIGIBILITY, secret=planted),
            context.plan,
            _prepare(context),
        )
    assert exc_info.value.code is ApplicantReportFailure.INVALID_INPUT
    assert planted not in str(exc_info.value)
    assert exc_info.value.__suppress_context__ is True

    script = """
import sys
import jgrad_admission_rag.reasoning.applicant_report
assert "sentence_transformers" not in sys.modules
assert "fastapi" not in sys.modules
"""
    subprocess.run([sys.executable, "-c", script], check=True)
