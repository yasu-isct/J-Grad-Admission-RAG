from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

from jgrad_admission_rag.reasoning.applicability import (
    ApplicabilityDecision,
    ApplicabilityDiagnostic,
    ApplicabilityPredicate,
    ApplicabilityRule,
    ApplicabilityStatus,
    EvidenceRole,
    LogicalMode,
    OfficialEvidenceBinding,
    OfficialEvidenceReference,
    PredicateOperator,
    PredicateOutcome,
    RuleScope,
)
from jgrad_admission_rag.reasoning.cited_answer import (
    CitedAnswerError,
    ProcessNoticeKind,
    ReportStatus,
    build_cited_answer,
    canonical_cited_answer_bytes,
    render_cited_answer_markdown,
)
from jgrad_admission_rag.reasoning.cited_answer import _build_finding
from jgrad_admission_rag.reasoning.reasoning_trace import (
    ReasoningTrace,
    ResolutionTraceStep,
    build_reasoning_trace,
)
from jgrad_admission_rag.reasoning.rule_interaction import (
    InteractionRelationship,
    RuleInteraction,
    RuleInteractionPolicy,
    analyze_rule_interactions,
)
from jgrad_admission_rag.reasoning.rule_resolution import (
    ActivatedOverride,
    ResolutionDisposition,
    RuleResolution,
    RuleResolutionEntry,
)

KB_HASH = "a" * 64
PDF_HASH = "b" * 64
DOCUMENT_ID = "reviewed-document"
SCENARIO_FIXTURE = Path(__file__).parent / "fixtures" / "cited_answer_scenarios_v1.json"
REAL_FIXTURE = Path(__file__).parent / "fixtures" / "applicability_real_scenarios_v1.json"
REAL_DATA = json.loads(REAL_FIXTURE.read_text(encoding="utf-8"))


def _scope(kind: str = "global", target: str | None = None) -> RuleScope:
    return RuleScope(
        scope_type=kind,  # type: ignore[arg-type]
        scope_targets=(target,) if target else (),
    )


def _rule(
    rule_id: str,
    *,
    scope: RuleScope | None = None,
    pages: tuple[int, ...] = (7,),
    fact_id: str | None = None,
) -> ApplicabilityRule:
    return ApplicabilityRule(
        rule_id=rule_id,
        mode=LogicalMode.ALL,
        predicates=(
            ApplicabilityPredicate(
                field_path="eligibility_facts.age_at_enrollment",
                operator=PredicateOperator.MINIMUM,
                expected_value=22,
            ),
        ),
        scope=scope or _scope(),
        evidence_bindings=(
            OfficialEvidenceBinding(
                document_id=DOCUMENT_ID,
                source_kb_sha256=KB_HASH,
                source_pdf_sha256=PDF_HASH,
                fact_id=fact_id or f"fact:{rule_id}",
                source_pages=pages,
                authoritative_fact_text_sha256="c" * 64,
            ),
        ),
        annotation_note="PLANTED_ANNOTATION_AND_OFFICIAL_TEXT_SECRET",
    )


def _decision(
    rule: ApplicabilityRule,
    status: ApplicabilityStatus = ApplicabilityStatus.CONFIRMED,
    *,
    role: EvidenceRole = EvidenceRole.PRIMARY,
    missing_evidence: bool = False,
) -> ApplicabilityDecision:
    missing_profile = status is ApplicabilityStatus.NEEDS_INFORMATION and not missing_evidence
    diagnostics: tuple[ApplicabilityDiagnostic, ...] = ()
    if missing_profile:
        diagnostics = (ApplicabilityDiagnostic.MISSING_PROFILE_FACT,)
    if missing_evidence:
        diagnostics = (ApplicabilityDiagnostic.MISSING_OFFICIAL_EVIDENCE,)
        status = ApplicabilityStatus.NEEDS_INFORMATION
    return ApplicabilityDecision(
        rule_id=rule.rule_id,
        logical_mode=rule.mode,
        status=status,
        predicate_outcomes=(
            PredicateOutcome(
                field_path=rule.predicates[0].field_path,
                operator=rule.predicates[0].operator,
                status=(ApplicabilityStatus.CONFIRMED if missing_evidence else status),
            ),
        ),
        missing_profile_fields=(rule.predicates[0].field_path,) if missing_profile else (),
        diagnostics=diagnostics,
        official_evidence=(
            ()
            if missing_evidence
            else (
                OfficialEvidenceReference(
                    document_id=DOCUMENT_ID,
                    fact_id=rule.evidence_bindings[0].fact_id,
                    source_pages=rule.evidence_bindings[0].source_pages,
                    role=role,
                ),
            )
        ),
        scope_status=ApplicabilityStatus.CONFIRMED,
        document_id=DOCUMENT_ID,
        source_kb_sha256=KB_HASH,
        source_pdf_sha256=PDF_HASH,
    )


def _entry(
    rule: ApplicabilityRule,
    decision: ApplicabilityDecision,
    *,
    subject: str = "eligibility.age",
    disposition: ResolutionDisposition | None = None,
    override: ActivatedOverride | None = None,
) -> RuleResolutionEntry:
    if disposition is None:
        disposition = {
            ApplicabilityStatus.CONFIRMED: ResolutionDisposition.ACTIVE,
            ApplicabilityStatus.NOT_APPLICABLE: ResolutionDisposition.NOT_APPLICABLE,
            ApplicabilityStatus.NEEDS_INFORMATION: ResolutionDisposition.PENDING,
        }[decision.status]
    return RuleResolutionEntry(
        rule_id=rule.rule_id,
        subject_key=subject,
        original_status=decision.status,
        scope=rule.scope,
        disposition=disposition,
        activated_override=override,
        official_evidence=decision.official_evidence,
    )


def _resolution(
    *entries: RuleResolutionEntry,
    document_id: str = DOCUMENT_ID,
    kb_hash: str = KB_HASH,
    pdf_hash: str = PDF_HASH,
) -> RuleResolution:
    order = {
        ResolutionDisposition.ACTIVE: 0,
        ResolutionDisposition.OVERRIDDEN: 1,
        ResolutionDisposition.PENDING: 2,
        ResolutionDisposition.NOT_APPLICABLE: 3,
    }
    specificity = {"global": 0, "college": 1, "department": 2, "program": 3}
    canonical = tuple(
        sorted(
            entries,
            key=lambda item: (
                order[item.disposition],
                specificity[item.scope.scope_type],
                item.rule_id,
            ),
        )
    )
    return RuleResolution(
        policy_id="reviewed-precedence",
        document_id=document_id,
        source_kb_sha256=kb_hash,
        source_pdf_sha256=pdf_hash,
        entries=canonical,
        active_rule_ids=_ids(canonical, ResolutionDisposition.ACTIVE),
        overridden_rule_ids=_ids(canonical, ResolutionDisposition.OVERRIDDEN),
        pending_rule_ids=_ids(canonical, ResolutionDisposition.PENDING),
        not_applicable_rule_ids=_ids(canonical, ResolutionDisposition.NOT_APPLICABLE),
    )


def _ids(
    entries: tuple[RuleResolutionEntry, ...], disposition: ResolutionDisposition
) -> tuple[str, ...]:
    return tuple(sorted(item.rule_id for item in entries if item.disposition is disposition))


def _trace(
    rules: tuple[ApplicabilityRule, ...],
    decisions: tuple[ApplicabilityDecision, ...],
    resolution: RuleResolution,
    relationship: InteractionRelationship | None = None,
) -> ReasoningTrace:
    interactions = ()
    if relationship is not None:
        rule_ids = tuple(sorted(item.rule_id for item in resolution.entries))
        interactions = (
            RuleInteraction(
                subject_key=resolution.entries[0].subject_key,
                rule_ids=rule_ids,  # type: ignore[arg-type]
                relationship=relationship,
                rationale="PLANTED_REVIEWED_RATIONALE_SECRET",
            ),
        )
    report = analyze_rule_interactions(
        resolution,
        RuleInteractionPolicy(policy_id="reviewed-interactions", interactions=interactions),
    )
    return build_reasoning_trace("trace:reviewed", rules, decisions, report)


def _single_trace(
    status: ApplicabilityStatus,
    *,
    role: EvidenceRole = EvidenceRole.PRIMARY,
    pages: tuple[int, ...] = (7,),
    missing_evidence: bool = False,
) -> ReasoningTrace:
    rule = _rule("age-rule", pages=pages, fact_id="fact:00063")
    decision = _decision(rule, status, role=role, missing_evidence=missing_evidence)
    resolution = _resolution(_entry(rule, decision))
    return _trace((rule,), (decision,), resolution)


def _real_trace(status: ApplicabilityStatus) -> ReasoningTrace:
    fixture_rule = REAL_DATA["rule"]
    fact = REAL_DATA["fact"]
    rule = ApplicabilityRule(
        rule_id=fixture_rule["rule_id"],
        mode=fixture_rule["mode"],
        predicates=tuple(ApplicabilityPredicate(**item) for item in fixture_rule["predicates"]),
        scope=RuleScope(**fixture_rule["scope"]),
        evidence_bindings=(
            OfficialEvidenceBinding(
                document_id=REAL_DATA["document_id"],
                source_kb_sha256=REAL_DATA["source_kb_sha256"],
                source_pdf_sha256=REAL_DATA["source_pdf_sha256"],
                fact_id=fact["fact_id"],
                source_pages=tuple(fact["source_pages"]),
                authoritative_fact_text_sha256=fact["authoritative_fact_text_sha256"],
            ),
        ),
        annotation_note=fixture_rule["annotation_note"],
    )
    missing = status is ApplicabilityStatus.NEEDS_INFORMATION
    decision = ApplicabilityDecision(
        rule_id=rule.rule_id,
        logical_mode=rule.mode,
        status=status,
        predicate_outcomes=(
            PredicateOutcome(
                field_path=rule.predicates[0].field_path,
                operator=rule.predicates[0].operator,
                status=ApplicabilityStatus.CONFIRMED,
            ),
            PredicateOutcome(
                field_path=rule.predicates[1].field_path,
                operator=rule.predicates[1].operator,
                status=status,
            ),
        ),
        missing_profile_fields=(rule.predicates[1].field_path,) if missing else (),
        diagnostics=(ApplicabilityDiagnostic.MISSING_PROFILE_FACT,) if missing else (),
        official_evidence=(
            OfficialEvidenceReference(
                document_id=REAL_DATA["document_id"],
                fact_id=fact["fact_id"],
                source_pages=tuple(fact["source_pages"]),
                role=EvidenceRole.PRIMARY,
            ),
        ),
        scope_status=ApplicabilityStatus.CONFIRMED,
        document_id=REAL_DATA["document_id"],
        source_kb_sha256=REAL_DATA["source_kb_sha256"],
        source_pdf_sha256=REAL_DATA["source_pdf_sha256"],
    )
    resolution = _resolution(
        _entry(rule, decision, subject="eligibility.individual_review"),
        document_id=REAL_DATA["document_id"],
        kb_hash=REAL_DATA["source_kb_sha256"],
        pdf_hash=REAL_DATA["source_pdf_sha256"],
    )
    return _trace((rule,), (decision,), resolution)


@pytest.mark.parametrize(
    ("status", "disposition", "report_status", "phrase"),
    [
        (
            ApplicabilityStatus.CONFIRMED,
            ResolutionDisposition.ACTIVE,
            ReportStatus.COMPLETE,
            "確認済みの規則が適用されます",
        ),
        (
            ApplicabilityStatus.NOT_APPLICABLE,
            ResolutionDisposition.NOT_APPLICABLE,
            ReportStatus.COMPLETE,
            "確認済みの規則は適用されません",
        ),
        (
            ApplicabilityStatus.NEEDS_INFORMATION,
            ResolutionDisposition.PENDING,
            ReportStatus.NEEDS_INFORMATION,
            "適用可否はまだ確定できません",
        ),
    ],
)
def test_real_fact_00063_rule_findings_preserve_status_page_and_non_eligibility(
    status: ApplicabilityStatus,
    disposition: ResolutionDisposition,
    report_status: ReportStatus,
    phrase: str,
) -> None:
    answer = build_cited_answer("answer:real-age", _real_trace(status))
    finding = answer.rule_findings[0]
    markdown = render_cited_answer_markdown(answer)

    assert answer.report_status is report_status
    assert finding.original_status is status
    assert finding.disposition is disposition
    assert finding.citations[0].fact_id == "fact:00063"
    assert finding.citations[0].source_pages == (7,)
    assert answer.document_id == REAL_DATA["document_id"]
    assert answer.source_kb_sha256 == REAL_DATA["source_kb_sha256"]
    assert answer.source_pdf_sha256 == REAL_DATA["source_pdf_sha256"]
    assert "[fact:00063, p.7]" in markdown
    assert phrase in markdown
    assert "入学資格、合否、合格可能性、または出願推奨を示すものではありません" in markdown
    assert "適格" not in markdown
    assert "不適格" not in markdown


def test_active_real_markdown_snapshot_is_exact_and_deterministic() -> None:
    answer = build_cited_answer("answer:real-age", _real_trace(ApplicabilityStatus.CONFIRMED))
    expected = """# レポート準備状況

**状態:** 完了

> この状態は規則調査レポートの準備状況です。入学資格、合否、合格可能性、または出願推奨を示すものではありません。

## 規則ごとの確認結果

- 規則 `isct-master-individual-review-age-22-criterion`（対象: department: 技術経営専門職学位課程, 環境・社会理工学院）: このトレースに記録された情報に対して、確認済みの規則が適用されます。 [fact:00063, p.7]

## 出典一覧

- [fact:00063, p.7] 文書 `isct_2027_4_2026_9_master` / 規則 `isct-master-individual-review-age-22-criterion` / 役割: 主要 / 参照元: 規則所見

## 制約

- 本レポートは、検証済みトレースに記録された規則単位の結果のみを表示します。
- 公式文書本文の要約や、記録されていない条件の推測は行いません。
- 最終的な出願資格や必要手続は、該当する大学の公式窓口と募集要項で確認してください。
"""
    assert render_cited_answer_markdown(answer) == expected
    assert render_cited_answer_markdown(answer) == render_cited_answer_markdown(answer)
    assert canonical_cited_answer_bytes(answer) == canonical_cited_answer_bytes(answer)
    assert canonical_cited_answer_bytes(answer).endswith(b"\n")


def test_pending_finding_lists_only_canonical_missing_field_without_value() -> None:
    answer = build_cited_answer(
        "answer:pending", _single_trace(ApplicabilityStatus.NEEDS_INFORMATION)
    )
    assert answer.report_status is ReportStatus.NEEDS_INFORMATION
    assert tuple((item.rule_id, item.field_path) for item in answer.missing_information) == (
        ("age-rule", "eligibility_facts.age_at_enrollment"),
    )
    markdown = render_cited_answer_markdown(answer)
    assert "## 追加で必要な情報" in markdown
    assert "eligibility_facts.age_at_enrollment" in markdown
    assert "22" not in markdown


def test_missing_official_evidence_suppresses_finding_and_requires_review() -> None:
    answer = build_cited_answer(
        "answer:missing-evidence",
        _single_trace(
            ApplicabilityStatus.NEEDS_INFORMATION,
            missing_evidence=True,
        ),
    )
    assert answer.report_status is ReportStatus.NEEDS_REVIEW
    assert answer.rule_findings == ()
    assert answer.citation_inventory == ()
    assert {item.kind for item in answer.process_notices} == {
        ProcessNoticeKind.MISSING_OFFICIAL_EVIDENCE
    }
    markdown = render_cited_answer_markdown(answer)
    assert "公式根拠が不足" in markdown
    assert "確認済みの規則" not in markdown


@pytest.mark.parametrize(
    ("diagnostic", "expected_status", "notice_kind"),
    [
        (
            ApplicabilityDiagnostic.MISSING_SCOPE,
            ReportStatus.NEEDS_INFORMATION,
            ProcessNoticeKind.MISSING_SCOPE,
        ),
        (
            ApplicabilityDiagnostic.SCOPE_INPUT_CONFLICT,
            ReportStatus.NEEDS_REVIEW,
            ProcessNoticeKind.SCOPE_INPUT_CONFLICT,
        ),
    ],
)
def test_scope_diagnostics_become_fixed_process_notices(
    diagnostic: ApplicabilityDiagnostic,
    expected_status: ReportStatus,
    notice_kind: ProcessNoticeKind,
) -> None:
    rule = _rule("scope-rule")
    base = _decision(rule)
    decision = ApplicabilityDecision(
        **{
            **base.model_dump(mode="python"),
            "status": ApplicabilityStatus.NEEDS_INFORMATION,
            "scope_status": ApplicabilityStatus.NEEDS_INFORMATION,
            "diagnostics": (diagnostic,),
        }
    )
    answer = build_cited_answer(
        "answer:scope-diagnostic",
        _trace((rule,), (decision,), _resolution(_entry(rule, decision))),
    )
    assert answer.report_status is expected_status
    assert notice_kind in {item.kind for item in answer.process_notices}


def test_compatible_pair_creates_no_warning_and_complete_report() -> None:
    left = _rule("left")
    right = _rule("right")
    decisions = (_decision(left), _decision(right))
    resolution = _resolution(_entry(left, decisions[0]), _entry(right, decisions[1]))
    answer = build_cited_answer(
        "answer:compatible",
        _trace((left, right), decisions, resolution, InteractionRelationship.COMPATIBLE),
    )
    assert answer.report_status is ReportStatus.COMPLETE
    assert answer.interaction_warnings == ()
    assert "規則間の競合" not in render_cited_answer_markdown(answer)


@pytest.mark.parametrize(
    ("relationship", "expected_kind", "expected_label"),
    [
        (InteractionRelationship.CONFLICT, "conflict", "規則間の競合"),
        (InteractionRelationship.AMBIGUOUS, "ambiguity", "規則間の曖昧さ"),
    ],
)
def test_confirmed_interaction_warning_cites_both_rules(
    relationship: InteractionRelationship,
    expected_kind: str,
    expected_label: str,
) -> None:
    left = _rule("left")
    right = _rule("right")
    decisions = (_decision(left), _decision(right))
    resolution = _resolution(_entry(left, decisions[0]), _entry(right, decisions[1]))
    answer = build_cited_answer(
        "answer:warning",
        _trace((left, right), decisions, resolution, relationship),
    )
    warning = answer.interaction_warnings[0]
    assert answer.report_status is ReportStatus.NEEDS_REVIEW
    assert warning.kind == expected_kind
    assert warning.certainty.value == "confirmed"
    assert warning.rule_ids == ("left", "right")
    assert {item.source_rule_id for item in warning.citations} == {"left", "right"}
    assert all(
        warning.source_interaction_step_id in item.source_step_ids for item in warning.citations
    )
    assert expected_label in render_cited_answer_markdown(answer)


def test_confirmed_conflict_markdown_snapshot_is_exact() -> None:
    left = _rule("left")
    right = _rule("right")
    decisions = (_decision(left), _decision(right))
    resolution = _resolution(_entry(left, decisions[0]), _entry(right, decisions[1]))
    answer = build_cited_answer(
        "answer:conflict-snapshot",
        _trace(
            (left, right),
            decisions,
            resolution,
            InteractionRelationship.CONFLICT,
        ),
    )
    expected = """# レポート準備状況

**状態:** 確認が必要

> この状態は規則調査レポートの準備状況です。入学資格、合否、合格可能性、または出願推奨を示すものではありません。

## 規則ごとの確認結果

- 規則 `left`（対象: 全体）: このトレースに記録された情報に対して、確認済みの規則が適用されます。 [fact:left, p.7]
- 規則 `right`（対象: 全体）: このトレースに記録された情報に対して、確認済みの規則が適用されます。 [fact:right, p.7]

## 確認が必要な事項

- **規則間の競合（確定）:** `left` と `right`。 [fact:left, p.7] [fact:right, p.7]

## 出典一覧

- [fact:left, p.7] 文書 `reviewed-document` / 規則 `left` / 役割: 主要 / 参照元: 規則所見
- [fact:left, p.7] 文書 `reviewed-document` / 規則 `left` / 役割: 主要 / 参照元: 規則間警告
- [fact:right, p.7] 文書 `reviewed-document` / 規則 `right` / 役割: 主要 / 参照元: 規則所見
- [fact:right, p.7] 文書 `reviewed-document` / 規則 `right` / 役割: 主要 / 参照元: 規則間警告

## 制約

- 本レポートは、検証済みトレースに記録された規則単位の結果のみを表示します。
- 公式文書本文の要約や、記録されていない条件の推測は行いません。
- 最終的な出願資格や必要手続は、該当する大学の公式窓口と募集要項で確認してください。
"""
    assert render_cited_answer_markdown(answer) == expected


def test_pending_endpoint_makes_conflict_potential_but_review_precedes_information() -> None:
    left = _rule("left")
    right = _rule("right")
    decisions = (
        _decision(left),
        _decision(right, ApplicabilityStatus.NEEDS_INFORMATION),
    )
    resolution = _resolution(_entry(left, decisions[0]), _entry(right, decisions[1]))
    answer = build_cited_answer(
        "answer:potential",
        _trace(
            (left, right),
            decisions,
            resolution,
            InteractionRelationship.CONFLICT,
        ),
    )
    assert answer.report_status is ReportStatus.NEEDS_REVIEW
    assert answer.interaction_warnings[0].certainty.value == "potential"
    assert answer.missing_information
    assert "競合（可能性）" in render_cited_answer_markdown(answer)


def test_unreviewed_pair_is_warning_and_incomplete_notice_without_rationale() -> None:
    left = _rule("left")
    right = _rule("right")
    decisions = (_decision(left), _decision(right))
    resolution = _resolution(_entry(left, decisions[0]), _entry(right, decisions[1]))
    answer = build_cited_answer(
        "answer:unreviewed",
        _trace((left, right), decisions, resolution),
    )
    assert answer.report_status is ReportStatus.NEEDS_REVIEW
    assert answer.interaction_analysis_complete is False
    assert answer.interaction_warnings[0].kind == "unreviewed_interaction"
    assert ProcessNoticeKind.INTERACTION_ANALYSIS_INCOMPLETE in {
        item.kind for item in answer.process_notices
    }
    markdown = render_cited_answer_markdown(answer)
    assert "未確認の規則間関係" in markdown
    assert "PLANTED_REVIEWED_RATIONALE_SECRET" not in markdown


def test_direct_override_finding_cites_overridden_and_overrider_rules() -> None:
    broad = _rule("broad", scope=_scope())
    narrow = _rule("narrow", scope=_scope("department", "情報工学系"))
    broad_decision = _decision(broad)
    narrow_decision = _decision(narrow)
    override = ActivatedOverride(
        subject_key="eligibility.age",
        overrider_rule_id="narrow",
        rationale="PLANTED_OVERRIDE_RATIONALE_SECRET",
    )
    resolution = _resolution(
        _entry(
            broad,
            broad_decision,
            disposition=ResolutionDisposition.OVERRIDDEN,
            override=override,
        ),
        _entry(narrow, narrow_decision),
    )
    answer = build_cited_answer(
        "answer:override",
        _trace(
            (broad, narrow),
            (broad_decision, narrow_decision),
            resolution,
            InteractionRelationship.COMPATIBLE,
        ),
    )
    broad_finding = next(item for item in answer.rule_findings if item.rule_id == "broad")
    assert broad_finding.disposition is ResolutionDisposition.OVERRIDDEN
    assert {item.source_rule_id for item in broad_finding.citations} == {"broad", "narrow"}
    assert answer.interaction_warnings == ()
    assert answer.report_status is ReportStatus.COMPLETE
    markdown = render_cited_answer_markdown(answer)
    assert "より具体的な規則 `narrow` に置き換えられています" in markdown
    assert "PLANTED_OVERRIDE_RATIONALE_SECRET" not in markdown


def test_override_without_both_evidence_groups_degrades_to_process_notice() -> None:
    evidence = (
        OfficialEvidenceReference(
            document_id=DOCUMENT_ID,
            fact_id="fact:broad",
            source_pages=(7,),
            role=EvidenceRole.PRIMARY,
        ),
    )
    override = ActivatedOverride(
        subject_key="eligibility.age",
        overrider_rule_id="narrow",
        rationale="Reviewed direct override.",
    )
    broad = ResolutionTraceStep(
        step_id="resolution:broad",
        dependencies=("applicability:broad",),
        rule_id="broad",
        original_status=ApplicabilityStatus.CONFIRMED,
        disposition=ResolutionDisposition.OVERRIDDEN,
        subject_key="eligibility.age",
        scope=_scope(),
        activated_override=override,
        official_evidence=evidence,
    )
    narrow = ResolutionTraceStep(
        step_id="resolution:narrow",
        dependencies=("applicability:narrow",),
        rule_id="narrow",
        original_status=ApplicabilityStatus.CONFIRMED,
        disposition=ResolutionDisposition.ACTIVE,
        subject_key="eligibility.age",
        scope=_scope("department", "情報工学系"),
        official_evidence=(),
    )
    result = _build_finding(
        broad,
        "applicability:broad",
        {"broad": broad, "narrow": narrow},
    )
    assert result.kind is ProcessNoticeKind.OVERRIDE_EVIDENCE_INCOMPLETE


def test_attached_multi_page_citation_has_stable_marker_and_inventory_order() -> None:
    answer = build_cited_answer(
        "answer:attached",
        _single_trace(
            ApplicabilityStatus.CONFIRMED,
            role=EvidenceRole.ATTACHED,
            pages=(7, 9, 10),
        ),
    )
    citation = answer.citation_inventory[0]
    assert citation.role is EvidenceRole.ATTACHED
    assert citation.source_pages == (7, 9, 10)
    markdown = render_cited_answer_markdown(answer)
    assert "[fact:00063, pp.7,9,10]" in markdown
    assert "役割: 参照先" in markdown


def test_scope_text_is_markdown_and_html_escaped() -> None:
    target = "Dept](javascript:alert(1))<script>"
    rule = _rule("scope-rule", scope=_scope("department", target))
    decision = _decision(rule)
    answer = build_cited_answer(
        "answer:scope",
        _trace((rule,), (decision,), _resolution(_entry(rule, decision))),
    )
    markdown = render_cited_answer_markdown(answer)
    assert "](javascript:" not in markdown
    assert "<script>" not in markdown
    assert "&lt;script&gt;" in markdown


def test_inventory_deduplicates_only_identical_provenance() -> None:
    answer = build_cited_answer("answer:inventory", _single_trace(ApplicabilityStatus.CONFIRMED))
    assert answer.rule_findings[0].citations == answer.citation_inventory
    assert len(answer.citation_inventory) == 1


def test_canonical_serialization_rejects_uncited_or_tampered_findings() -> None:
    answer = build_cited_answer("answer:tamper", _single_trace(ApplicabilityStatus.CONFIRMED))
    uncited = answer.rule_findings[0].model_copy(update={"citations": ()})
    tampered = answer.model_copy(update={"rule_findings": (uncited,)})
    with pytest.raises(CitedAnswerError):
        canonical_cited_answer_bytes(tampered)

    wrong_status = answer.model_copy(update={"report_status": ReportStatus.NEEDS_REVIEW})
    with pytest.raises(CitedAnswerError):
        canonical_cited_answer_bytes(wrong_status)

    missing_source_rule = answer.model_copy(update={"source_rule_ids": ("other",)})
    with pytest.raises(CitedAnswerError):
        canonical_cited_answer_bytes(missing_source_rule)

    wrong_citation_step = (
        answer.rule_findings[0]
        .citations[0]
        .model_copy(update={"source_step_ids": ("resolution:ghost",)})
    )
    wrong_finding = answer.rule_findings[0].model_copy(update={"citations": (wrong_citation_step,)})
    tampered = answer.model_copy(update={"rule_findings": (wrong_finding,)})
    with pytest.raises(CitedAnswerError):
        canonical_cited_answer_bytes(tampered)

    wrong_document = answer.citation_inventory[0].model_copy(
        update={"document_id": "another-document"}
    )
    tampered = answer.model_copy(update={"citation_inventory": (wrong_document,)})
    with pytest.raises(CitedAnswerError):
        canonical_cited_answer_bytes(tampered)

    wrong_step = answer.rule_findings[0].model_copy(
        update={"source_resolution_step_id": "resolution:other"}
    )
    tampered = answer.model_copy(update={"rule_findings": (wrong_step,)})
    with pytest.raises(CitedAnswerError):
        canonical_cited_answer_bytes(tampered)


@pytest.mark.parametrize("tamper", ["identity", "unsafe_trace", "unsafe_rule"])
def test_builder_strictly_rejects_invalid_or_unsafe_trace(tamper: str) -> None:
    trace = _single_trace(ApplicabilityStatus.CONFIRMED)
    if tamper == "identity":
        trace = trace.model_copy(update={"document_id": "other-document"})
    elif tamper == "unsafe_trace":
        trace = trace.model_copy(update={"trace_id": "trace:<script>"})
    else:
        rule = _rule("bad`rule")
        decision = _decision(rule)
        trace = _trace((rule,), (decision,), _resolution(_entry(rule, decision)))
    with pytest.raises(CitedAnswerError):
        build_cited_answer("answer:unsafe", trace)


def test_output_omits_hashes_values_queries_text_rationales_and_secrets() -> None:
    left = _rule("left")
    right = _rule("right")
    decisions = (_decision(left), _decision(right))
    resolution = _resolution(_entry(left, decisions[0]), _entry(right, decisions[1]))
    answer = build_cited_answer(
        "answer:privacy",
        _trace(
            (left, right),
            decisions,
            resolution,
            InteractionRelationship.CONFLICT,
        ),
    )
    markdown = render_cited_answer_markdown(answer)
    payload = canonical_cited_answer_bytes(answer).decode()
    forbidden_markdown = (
        KB_HASH,
        PDF_HASH,
        "PLANTED_ANNOTATION_AND_OFFICIAL_TEXT_SECRET",
        "PLANTED_REVIEWED_RATIONALE_SECRET",
        "ApplicantProfile",
        "raw query",
        "retrieval_score",
        "C:\\private\\secret.pdf",
        "22",
    )
    assert all(item not in markdown for item in forbidden_markdown)
    assert "PLANTED_ANNOTATION_AND_OFFICIAL_TEXT_SECRET" not in payload
    assert "PLANTED_REVIEWED_RATIONALE_SECRET" not in payload
    assert KB_HASH in payload and PDF_HASH in payload


def test_errors_do_not_echo_planted_secret() -> None:
    secret = "PLANTED_PATH_QUERY_PROFILE_SECRET?<script>"
    with pytest.raises(CitedAnswerError) as caught:
        build_cited_answer(secret, _single_trace(ApplicabilityStatus.CONFIRMED))
    assert secret not in str(caught.value)


def test_build_and_render_do_not_access_network_or_model_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "socket", deny_network)
    answer = build_cited_answer("answer:offline", _single_trace(ApplicabilityStatus.CONFIRMED))
    assert render_cited_answer_markdown(answer)
    assert "sentence_transformers" not in sys.modules
    assert "openai" not in sys.modules


def test_json_model_contains_source_steps_and_no_complete_trace_snapshot() -> None:
    answer = build_cited_answer("answer:audit", _single_trace(ApplicabilityStatus.CONFIRMED))
    payload = json.loads(canonical_cited_answer_bytes(answer))
    finding = payload["rule_findings"][0]
    assert finding["source_applicability_step_id"] == "applicability:age-rule"
    assert finding["source_resolution_step_id"] == "resolution:age-rule"
    assert "source_interaction_report" not in payload
    assert "source_rules" not in payload


def test_reviewed_scenario_fixture_covers_real_and_synthetic_contract() -> None:
    fixture = json.loads(SCENARIO_FIXTURE.read_text(encoding="utf-8"))
    real = fixture["real_fact_00063"]
    synthetic = fixture["synthetic_scenarios"]
    assert real["fact_id"] == "fact:00063"
    assert real["source_pages"] == [7]
    assert {item["applicability"] for item in real["scenarios"]} == {
        "confirmed",
        "not_applicable",
        "needs_information",
    }
    assert real["final_eligibility_present"] is False
    assert {item["scenario_id"] for item in synthetic} == {
        "direct-override",
        "compatible",
        "confirmed-conflict",
        "potential-conflict",
        "ambiguity",
        "unreviewed",
        "missing-evidence",
        "attached-multi-page",
    }
