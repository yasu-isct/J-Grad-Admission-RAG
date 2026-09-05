from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

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
from jgrad_admission_rag.reasoning.query_intent import IntentCategory
from jgrad_admission_rag.reasoning.reviewed_report_plan import (
    PlanValidationFailure,
    ReviewedReportPlan,
    ReviewedReportPlanError,
    canonical_reviewed_report_plan_bytes,
    load_reviewed_report_plan,
    load_reviewed_report_plan_bytes,
)
from jgrad_admission_rag.reasoning.rule_interaction import (
    RuleInteraction,
    InteractionRelationship,
    RuleInteractionPolicy,
    analyze_rule_interactions,
)
from jgrad_admission_rag.reasoning.rule_resolution import (
    OverrideEdge,
    ResolutionDisposition,
    RulePrecedencePolicy,
    RuleSubjectAssignment,
    resolve_rule_precedence,
)
from jgrad_admission_rag.schemas.document_identity import DocumentIdentity

KB_HASH = "a" * 64
PDF_HASH = "b" * 64
TEXT_HASH = "c" * 64
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "reviewed_report_plan_isct_master_v1.json"


def _typed_failure(error: ValidationError) -> PlanValidationFailure:
    underlying = error.errors()[0].get("ctx", {}).get("error")
    assert getattr(underlying, "failure", None) is not None
    return underlying.failure


def _identity() -> DocumentIdentity:
    return DocumentIdentity.model_validate(
        {
            "document_id": "doc",
            "document_family_id": "family",
            "edition_id": "edition",
            "institution_id": "institution",
            "institution_name": "Institution",
            "degree_levels": ["master"],
            "intake_terms": [{"year": 2027, "month": 4}],
            "official_title": "Reviewed document",
            "official_source_url": "https://example.edu/admission.pdf",
            "source_pdf_sha256": PDF_HASH,
        }
    )


def _rule(
    rule_id: str = "rule-a",
    *,
    scope: RuleScope | None = None,
    kb_hash: str = KB_HASH,
    document_id: str = "doc",
    pdf_hash: str = PDF_HASH,
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
        scope=scope or RuleScope(scope_type="global"),
        evidence_bindings=(
            OfficialEvidenceBinding(
                document_id=document_id,
                source_kb_sha256=kb_hash,
                source_pdf_sha256=pdf_hash,
                fact_id=f"fact:{rule_id}",
                source_pages=(7,),
                authoritative_fact_text_sha256=TEXT_HASH,
            ),
        ),
        annotation_note="Reviewed test rule.",
    )


def _precedence(
    rules: tuple[ApplicabilityRule, ...],
    *,
    subjects: tuple[RuleSubjectAssignment, ...] | None = None,
    edges: tuple[OverrideEdge, ...] = (),
) -> RulePrecedencePolicy:
    return RulePrecedencePolicy(
        policy_id="precedence",
        subjects=subjects
        or tuple(
            RuleSubjectAssignment(rule_id=rule.rule_id, subject_key="eligibility.age")
            for rule in rules
        ),
        override_edges=edges,
    )


def _plan(
    rules: tuple[ApplicabilityRule, ...] | None = None,
    *,
    identity: DocumentIdentity | None = None,
    precedence: RulePrecedencePolicy | None = None,
    interactions: RuleInteractionPolicy | None = None,
    categories: tuple[IntentCategory, ...] = (IntentCategory.ELIGIBILITY,),
) -> ReviewedReportPlan:
    rules = rules or (_rule(),)
    return ReviewedReportPlan(
        plan_id="reviewed-plan-v1",
        document_identity=identity or _identity(),
        rules=rules,
        precedence_policy=precedence or _precedence(rules),
        interaction_policy=interactions
        or RuleInteractionPolicy(policy_id="interactions", interactions=()),
        covered_categories=categories,
        coverage_status="partial_reviewed_rules",
        reviewed_coverage_statement="Covers one reviewed age criterion.",
        limitation_statement="Does not establish overall eligibility or admission.",
    )


def _decision(rule: ApplicabilityRule, status: ApplicabilityStatus) -> ApplicabilityDecision:
    missing = (
        ("eligibility_facts.age_at_enrollment",)
        if status is ApplicabilityStatus.NEEDS_INFORMATION
        else ()
    )
    diagnostics = (
        (ApplicabilityDiagnostic.MISSING_PROFILE_FACT,)
        if status is ApplicabilityStatus.NEEDS_INFORMATION
        else ()
    )
    binding = rule.evidence_bindings[0]
    return ApplicabilityDecision(
        rule_id=rule.rule_id,
        logical_mode=rule.mode,
        status=status,
        predicate_outcomes=(
            PredicateOutcome(
                field_path="eligibility_facts.age_at_enrollment",
                operator=PredicateOperator.MINIMUM,
                status=status,
            ),
        ),
        missing_profile_fields=missing,
        diagnostics=diagnostics,
        official_evidence=(
            OfficialEvidenceReference(
                document_id=binding.document_id,
                fact_id=binding.fact_id,
                source_pages=binding.source_pages,
                role=EvidenceRole.PRIMARY,
            ),
        ),
        scope_status=ApplicabilityStatus.CONFIRMED,
        document_id=binding.document_id,
        source_kb_sha256=binding.source_kb_sha256,
        source_pdf_sha256=binding.source_pdf_sha256,
    )


def test_real_reviewed_plan_fixture_reuses_the_accepted_rule() -> None:
    plan = load_reviewed_report_plan(FIXTURE_PATH)

    assert plan.plan_id == "isct-master-reviewed-report-plan-v1"
    assert plan.coverage_status == "partial_reviewed_rules"
    assert plan.covered_categories == (IntentCategory.ELIGIBILITY,)
    assert plan.source_kb_sha256 == (
        "d752d58b073f9bf57dc399e477ec8325f4ed0ccaaca351f67a05c9f8304f258f"
    )
    rule = plan.rules[0]
    binding = rule.evidence_bindings[0]
    assert rule.rule_id == "isct-master-individual-review-age-22-criterion"
    assert binding.fact_id == "fact:00063"
    assert binding.source_pages == (7,)
    assert canonical_reviewed_report_plan_bytes(
        load_reviewed_report_plan_bytes(canonical_reviewed_report_plan_bytes(plan))
    ) == canonical_reviewed_report_plan_bytes(plan)


def test_plan_canonical_bytes_are_deterministic_immutable_and_finite() -> None:
    plan = _plan()
    first = canonical_reviewed_report_plan_bytes(plan)
    second = canonical_reviewed_report_plan_bytes(_plan())

    assert first == second
    assert first.endswith(b"\n")
    assert b"NaN" not in first
    with pytest.raises(ValidationError):
        plan.plan_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "2.0"},
        {"coverage_status": "complete"},
        {"coverage_status": "eligible"},
        {"coverage_status": "ineligible"},
        {"coverage_status": "pass"},
        {"plan_id": 7},
        {"plan_id": ""},
        {"plan_id": "C:\\private\\plan.json"},
        {"rules": []},
        {"covered_categories": []},
        {"reviewed_coverage_statement": "x" * 501},
        {"limitation_statement": "x" * 501},
    ],
)
def test_version_coercion_invented_states_and_unbounded_text_are_rejected(
    change: dict[str, object],
) -> None:
    payload = _plan().model_dump(mode="json")
    payload.update(change)
    with pytest.raises(ReviewedReportPlanError, match="invalid or unsupported"):
        load_reviewed_report_plan_bytes(json.dumps(payload).encode())


def test_extra_sensitive_fields_are_rejected_without_public_echo() -> None:
    payload = _plan().model_dump(mode="json")
    planted = {
        "applicant_profile": "profile-secret",
        "query": "query-secret",
        "retrieval_score": 0.99,
        "local_path": "path-secret",
        "official_fact_text": "official-text-secret",
        "callable": "executable-secret",
    }
    payload.update(planted)
    with pytest.raises(ReviewedReportPlanError) as exc_info:
        load_reviewed_report_plan_bytes(json.dumps(payload).encode())
    message = str(exc_info.value)
    assert all(value not in message for value in planted.values() if isinstance(value, str))
    canonical = canonical_reviewed_report_plan_bytes(_plan()).decode()
    assert all(key not in canonical for key in planted)

    bypassed = _plan().model_copy(update={"query": "copied-query-secret"})
    with pytest.raises(ReviewedReportPlanError) as copied_error:
        canonical_reviewed_report_plan_bytes(bypassed)
    assert "copied-query-secret" not in str(copied_error.value)


def test_rule_and_category_collections_require_unique_canonical_order() -> None:
    first = _rule("a")
    second = _rule("b")
    precedence = _precedence((first, second))
    for rules in ((second, first), (first, first)):
        with pytest.raises(ValidationError, match="rule_order"):
            _plan(rules, precedence=precedence)
    for categories in (
        (IntentCategory.FEES, IntentCategory.ELIGIBILITY),
        (IntentCategory.ELIGIBILITY, IntentCategory.ELIGIBILITY),
    ):
        with pytest.raises(ValidationError, match="category_order"):
            _plan(categories=categories)


@pytest.mark.parametrize(
    "rule",
    [
        _rule(document_id="other"),
        _rule(pdf_hash="d" * 64),
    ],
)
def test_every_nested_binding_must_match_the_plan_document(rule: ApplicabilityRule) -> None:
    with pytest.raises(ValidationError, match="source_identity") as exc_info:
        _plan((rule,), precedence=_precedence((rule,)))
    assert _typed_failure(exc_info.value) is PlanValidationFailure.SOURCE_IDENTITY


def test_all_nested_bindings_must_share_one_current_kb() -> None:
    first = _rule("a")
    second = _rule("b", kb_hash="d" * 64)
    with pytest.raises(ValidationError, match="source_kb") as exc_info:
        _plan((first, second), precedence=_precedence((first, second)))
    assert _typed_failure(exc_info.value) is PlanValidationFailure.SOURCE_KB


def test_precedence_subjects_must_cover_exactly_the_included_rules() -> None:
    first = _rule("a")
    second = _rule("b")
    for subjects in (
        (RuleSubjectAssignment(rule_id="a", subject_key="eligibility.age"),),
        (
            RuleSubjectAssignment(rule_id="a", subject_key="eligibility.age"),
            RuleSubjectAssignment(rule_id="b", subject_key="eligibility.age"),
            RuleSubjectAssignment(rule_id="ghost", subject_key="eligibility.age"),
        ),
    ):
        policy = _precedence((first, second), subjects=subjects)
        with pytest.raises(ValidationError, match="precedence_subjects"):
            _plan((first, second), precedence=policy)


def test_unknown_override_endpoint_and_unproven_direction_are_rejected() -> None:
    broad = _rule("broad")
    narrow = _rule(
        "narrow",
        scope=RuleScope(
            scope_type="department",
            scope_targets=("Program",),
            parent_college="College",
        ),
    )
    ghost_subjects = (
        RuleSubjectAssignment(rule_id="broad", subject_key="eligibility.age"),
        RuleSubjectAssignment(rule_id="ghost", subject_key="eligibility.age"),
        RuleSubjectAssignment(rule_id="narrow", subject_key="eligibility.age"),
    )
    ghost_edge = OverrideEdge(
        subject_key="eligibility.age",
        overrider_rule_id="ghost",
        overridden_rule_id="broad",
        rationale="Reviewed edge.",
    )
    with pytest.raises(ValidationError, match="precedence_endpoint"):
        _plan(
            (broad, narrow),
            precedence=_precedence((broad, narrow), subjects=ghost_subjects, edges=(ghost_edge,)),
        )

    wrong_edge = OverrideEdge(
        subject_key="eligibility.age",
        overrider_rule_id="broad",
        overridden_rule_id="narrow",
        rationale="Wrong reviewed direction.",
    )
    with pytest.raises(ValidationError, match="precedence_scope") as exc_info:
        _plan((broad, narrow), precedence=_precedence((broad, narrow), edges=(wrong_edge,)))
    assert _typed_failure(exc_info.value) is PlanValidationFailure.PRECEDENCE_SCOPE


def test_interaction_endpoints_and_assigned_subject_must_reconcile() -> None:
    first = _rule("a")
    second = _rule("b")
    rules = (first, second)
    unknown = RuleInteractionPolicy(
        policy_id="interactions",
        interactions=(
            RuleInteraction(
                subject_key="eligibility.age",
                rule_ids=("a", "ghost"),
                relationship=InteractionRelationship.CONFLICT,
                rationale="Reviewed.",
            ),
        ),
    )
    with pytest.raises(ValidationError, match="interaction_endpoint"):
        _plan(rules, precedence=_precedence(rules), interactions=unknown)

    mismatched = RuleInteractionPolicy(
        policy_id="interactions",
        interactions=(
            RuleInteraction(
                subject_key="other.subject",
                rule_ids=("a", "b"),
                relationship=InteractionRelationship.AMBIGUOUS,
                rationale="Reviewed.",
            ),
        ),
    )
    with pytest.raises(ValidationError, match="interaction_subject") as exc_info:
        _plan(rules, precedence=_precedence(rules), interactions=mismatched)
    assert _typed_failure(exc_info.value) is PlanValidationFailure.INTERACTION_SUBJECT


@pytest.mark.parametrize(
    ("status", "disposition"),
    [
        (ApplicabilityStatus.CONFIRMED, ResolutionDisposition.ACTIVE),
        (ApplicabilityStatus.NEEDS_INFORMATION, ResolutionDisposition.PENDING),
        (ApplicabilityStatus.NOT_APPLICABLE, ResolutionDisposition.NOT_APPLICABLE),
    ],
)
def test_one_rule_zero_override_runs_through_real_resolution_and_interaction(
    status: ApplicabilityStatus,
    disposition: ResolutionDisposition,
) -> None:
    plan = _plan()
    resolution = resolve_rule_precedence(
        plan.rules,
        (_decision(plan.rules[0], status),),
        plan.precedence_policy,
    )
    report = analyze_rule_interactions(resolution, plan.interaction_policy)

    assert resolution.entries[0].disposition is disposition
    assert report.warnings == ()
    assert report.live_same_subject_pair_count == 0
    assert report.unreviewed_live_pair_count == 0
    assert report.analysis_complete is True


def test_path_loader_accepts_only_regular_non_symlink_files(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    path.write_bytes(canonical_reviewed_report_plan_bytes(_plan()))
    assert load_reviewed_report_plan(path) == _plan()

    with pytest.raises(ReviewedReportPlanError, match="unavailable or unsafe"):
        load_reviewed_report_plan(tmp_path / "missing-secret.json")

    link = tmp_path / "linked.json"
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(ReviewedReportPlanError, match="unavailable or unsafe"):
        load_reviewed_report_plan(link)


def test_plan_import_does_not_load_service_or_model_dependencies() -> None:
    script = """
import sys
import jgrad_admission_rag.reasoning.reviewed_report_plan
assert "sentence_transformers" not in sys.modules
assert "fastapi" not in sys.modules
"""
    subprocess.run([sys.executable, "-c", script], check=True)
