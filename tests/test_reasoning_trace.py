from __future__ import annotations

import json
import socket
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
from jgrad_admission_rag.reasoning.reasoning_trace import (
    InteractionTraceOutcome,
    ReasoningTraceError,
    build_reasoning_trace,
    canonical_reasoning_trace_bytes,
    load_reasoning_trace,
    load_reasoning_trace_bytes,
)
from jgrad_admission_rag.reasoning.rule_interaction import (
    InteractionRelationship,
    RuleInteraction,
    RuleInteractionPolicy,
    RuleInteractionReport,
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
REAL_FIXTURE = Path(__file__).parent / "fixtures" / "applicability_real_scenarios_v1.json"
TRACE_FIXTURE = Path(__file__).parent / "fixtures" / "reasoning_trace_scenarios_v1.json"


def _scope(kind: str = "global", target: str | None = None) -> RuleScope:
    return RuleScope(
        scope_type=kind,  # type: ignore[arg-type]
        scope_targets=(target,) if target else (),
    )


def _rule(
    rule_id: str,
    *,
    expected: int = 22,
    scope: RuleScope | None = None,
    fact_id: str | None = None,
    document_id: str = DOCUMENT_ID,
    kb_hash: str = KB_HASH,
    pdf_hash: str = PDF_HASH,
) -> ApplicabilityRule:
    return ApplicabilityRule(
        rule_id=rule_id,
        mode=LogicalMode.ALL,
        predicates=(
            ApplicabilityPredicate(
                field_path="eligibility_facts.age_at_enrollment",
                operator=PredicateOperator.MINIMUM,
                expected_value=expected,
            ),
        ),
        scope=scope or _scope(),
        evidence_bindings=(
            OfficialEvidenceBinding(
                document_id=document_id,
                source_kb_sha256=kb_hash,
                source_pdf_sha256=pdf_hash,
                fact_id=fact_id or f"fact:{rule_id}",
                source_pages=(7,),
                authoritative_fact_text_sha256="c" * 64,
            ),
        ),
        annotation_note="PLANTED_ANNOTATION_SECRET must never enter a trace.",
    )


def _decision(
    rule: ApplicabilityRule,
    status: ApplicabilityStatus = ApplicabilityStatus.CONFIRMED,
) -> ApplicabilityDecision:
    missing = status is ApplicabilityStatus.NEEDS_INFORMATION
    return ApplicabilityDecision(
        rule_id=rule.rule_id,
        logical_mode=rule.mode,
        status=status,
        predicate_outcomes=(
            PredicateOutcome(
                field_path=rule.predicates[0].field_path,
                operator=rule.predicates[0].operator,
                status=status,
            ),
        ),
        missing_profile_fields=(rule.predicates[0].field_path,) if missing else (),
        diagnostics=(ApplicabilityDiagnostic.MISSING_PROFILE_FACT,) if missing else (),
        official_evidence=(
            OfficialEvidenceReference(
                document_id=rule.evidence_bindings[0].document_id,
                fact_id=rule.evidence_bindings[0].fact_id,
                source_pages=rule.evidence_bindings[0].source_pages,
                role=EvidenceRole.PRIMARY,
            ),
        ),
        scope_status=ApplicabilityStatus.CONFIRMED,
        document_id=rule.evidence_bindings[0].document_id,
        source_kb_sha256=rule.evidence_bindings[0].source_kb_sha256,
        source_pdf_sha256=rule.evidence_bindings[0].source_pdf_sha256,
    )


def _entry(
    rule: ApplicabilityRule,
    decision: ApplicabilityDecision,
    subject: str,
    disposition: ResolutionDisposition | None = None,
    override: ActivatedOverride | None = None,
) -> RuleResolutionEntry:
    if disposition is None:
        disposition = {
            ApplicabilityStatus.CONFIRMED: ResolutionDisposition.ACTIVE,
            ApplicabilityStatus.NEEDS_INFORMATION: ResolutionDisposition.PENDING,
            ApplicabilityStatus.NOT_APPLICABLE: ResolutionDisposition.NOT_APPLICABLE,
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


def _resolution(*entries: RuleResolutionEntry) -> RuleResolution:
    disposition_order = {
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
                disposition_order[item.disposition],
                specificity[item.scope.scope_type],
                item.rule_id,
            ),
        )
    )
    return RuleResolution(
        policy_id="reviewed-precedence",
        document_id=entries[0].official_evidence[0].document_id,
        source_kb_sha256=KB_HASH
        if entries[0].official_evidence[0].document_id == DOCUMENT_ID
        else REAL_KB_HASH,
        source_pdf_sha256=PDF_HASH
        if entries[0].official_evidence[0].document_id == DOCUMENT_ID
        else REAL_PDF_HASH,
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


def _report(
    resolution: RuleResolution,
    relationship: InteractionRelationship | None = None,
) -> RuleInteractionReport:
    interactions = ()
    if relationship is not None:
        rule_ids = tuple(sorted(item.rule_id for item in resolution.entries))
        interactions = (
            RuleInteraction(
                subject_key=resolution.entries[0].subject_key,
                rule_ids=rule_ids,  # type: ignore[arg-type]
                relationship=relationship,
                rationale="Short reviewed relationship rationale.",
            ),
        )
    return analyze_rule_interactions(
        resolution,
        RuleInteractionPolicy(policy_id="reviewed-interactions", interactions=interactions),
    )


def _two_rule_trace(
    relationship: InteractionRelationship | None = InteractionRelationship.COMPATIBLE,
):
    left = _rule("left", expected=20)
    right = _rule("right", expected=22)
    decisions = (_decision(left), _decision(right))
    resolution = _resolution(
        _entry(left, decisions[0], "eligibility.age"),
        _entry(right, decisions[1], "eligibility.age"),
    )
    return build_reasoning_trace(
        "trace:synthetic",
        (right, left),
        tuple(reversed(decisions)),
        _report(resolution, relationship),
    )


REAL_DATA = json.loads(REAL_FIXTURE.read_text(encoding="utf-8"))
REAL_KB_HASH = REAL_DATA["source_kb_sha256"]
REAL_PDF_HASH = REAL_DATA["source_pdf_sha256"]


def test_trace_preserves_steps_evidence_dependencies_and_canonical_order() -> None:
    trace = _two_rule_trace()

    assert tuple(item.rule_id for item in trace.source_rules) == ("left", "right")
    assert tuple(item.step_id for item in trace.applicability_steps) == (
        "applicability:left",
        "applicability:right",
    )
    assert tuple(item.step_id for item in trace.resolution_steps) == (
        "resolution:left",
        "resolution:right",
    )
    interaction = trace.interaction_steps[0]
    assert interaction.outcome is InteractionTraceOutcome.COMPATIBLE
    assert interaction.dependencies == ("resolution:left", "resolution:right")
    assert interaction.endpoints[0].official_evidence[0].fact_id == "fact:left"
    assert interaction.endpoints[1].official_evidence[0].source_pages == (7,)
    assert trace.terminal_step_ids == (interaction.step_id,)
    assert trace.coverage.rule_count == 2
    assert trace.coverage.interaction_step_count == 1
    assert trace.coverage.interaction_analysis_complete is True

    payload = canonical_reasoning_trace_bytes(trace)
    assert payload.endswith(b"\n")
    assert payload == canonical_reasoning_trace_bytes(load_reasoning_trace_bytes(payload))
    assert b"PLANTED_ANNOTATION_SECRET" not in payload


@pytest.mark.parametrize(
    ("relationship", "outcome", "certainty"),
    [
        (InteractionRelationship.CONFLICT, "conflict", "confirmed"),
        (InteractionRelationship.AMBIGUOUS, "ambiguity", "confirmed"),
    ],
)
def test_reviewed_warning_outcome_is_copied_exactly(
    relationship: InteractionRelationship,
    outcome: str,
    certainty: str,
) -> None:
    step = _two_rule_trace(relationship).interaction_steps[0]
    assert step.outcome.value == outcome
    assert step.certainty is not None and step.certainty.value == certainty
    assert step.reviewed_rationale == "Short reviewed relationship rationale."
    assert step.diagnostic is None


@pytest.mark.parametrize(
    ("relationship", "outcome"),
    [
        (InteractionRelationship.CONFLICT, InteractionTraceOutcome.CONFLICT),
        (InteractionRelationship.AMBIGUOUS, InteractionTraceOutcome.AMBIGUITY),
    ],
)
def test_pending_endpoint_keeps_reviewed_warning_potential(
    relationship: InteractionRelationship,
    outcome: InteractionTraceOutcome,
) -> None:
    left = _rule("left")
    right = _rule("right")
    left_decision = _decision(left)
    right_decision = _decision(right, ApplicabilityStatus.NEEDS_INFORMATION)
    resolution = _resolution(
        _entry(left, left_decision, "eligibility.age"),
        _entry(right, right_decision, "eligibility.age"),
    )
    trace = build_reasoning_trace(
        "trace:potential",
        (left, right),
        (left_decision, right_decision),
        _report(resolution, relationship),
    )
    step = trace.interaction_steps[0]
    assert step.outcome is outcome
    assert step.certainty is not None and step.certainty.value == "potential"


def test_unreviewed_live_pair_remains_visible_and_incomplete() -> None:
    trace = _two_rule_trace(None)
    step = trace.interaction_steps[0]
    assert step.outcome is InteractionTraceOutcome.UNREVIEWED_INTERACTION
    assert step.diagnostic is not None
    assert step.reviewed_rationale is None
    assert trace.coverage.interaction_analysis_complete is False
    assert trace.coverage.interaction_warning_counts[-2].count == 1


def test_direct_override_and_inactive_reviewed_pair_are_not_recomputed() -> None:
    broad = _rule("broad", scope=_scope())
    narrow = _rule("narrow", scope=_scope("department", "Systems"))
    broad_decision = _decision(broad)
    narrow_decision = _decision(narrow)
    override = ActivatedOverride(
        subject_key="eligibility.age",
        overrider_rule_id="narrow",
        rationale="Reviewed direct specificity edge.",
    )
    resolution = _resolution(
        _entry(
            broad,
            broad_decision,
            "eligibility.age",
            ResolutionDisposition.OVERRIDDEN,
            override,
        ),
        _entry(narrow, narrow_decision, "eligibility.age"),
    )
    trace = build_reasoning_trace(
        "trace:override",
        (broad, narrow),
        (broad_decision, narrow_decision),
        _report(resolution, InteractionRelationship.COMPATIBLE),
    )

    broad_step = next(item for item in trace.resolution_steps if item.rule_id == "broad")
    assert broad_step.disposition is ResolutionDisposition.OVERRIDDEN
    assert broad_step.activated_override == override
    assert trace.interaction_steps[0].outcome is InteractionTraceOutcome.INACTIVE
    assert trace.interaction_steps[0].certainty is None
    assert trace.coverage.interaction_analysis_complete is True


def test_zero_interaction_trace_keeps_resolution_as_terminal() -> None:
    rule = _rule("solo")
    decision = _decision(rule, ApplicabilityStatus.NEEDS_INFORMATION)
    resolution = _resolution(_entry(rule, decision, "eligibility.age"))
    trace = build_reasoning_trace(
        "trace:solo",
        (rule,),
        (decision,),
        _report(resolution),
    )

    assert trace.interaction_steps == ()
    assert trace.terminal_step_ids == ("resolution:solo",)
    assert trace.resolution_steps[0].disposition is ResolutionDisposition.PENDING
    assert trace.coverage.interaction_analysis_complete is True


@pytest.mark.parametrize(
    "tamper",
    [
        "expected_value",
        "predicate_outcome",
        "disposition",
        "interaction_outcome",
        "evidence_page",
        "identity",
        "dependency",
        "terminal",
        "count",
        "completeness",
        "missing_step",
        "duplicate_step",
        "source_expected_value",
        "source_decision_status",
        "forward_edge",
        "cycle",
        "relabelled_step",
    ],
)
def test_loader_rejects_tampered_trace(tamper: str) -> None:
    payload = json.loads(canonical_reasoning_trace_bytes(_two_rule_trace()))
    if tamper == "expected_value":
        payload["applicability_steps"][0]["predicates"][0]["expected_value"] = 99
    elif tamper == "predicate_outcome":
        payload["applicability_steps"][0]["predicates"][0]["outcome_status"] = "not_applicable"
    elif tamper == "disposition":
        payload["resolution_steps"][0]["disposition"] = "pending"
    elif tamper == "interaction_outcome":
        payload["interaction_steps"][0]["outcome"] = "conflict"
    elif tamper == "evidence_page":
        payload["interaction_steps"][0]["endpoints"][0]["official_evidence"][0]["source_pages"] = [
            8
        ]
    elif tamper == "identity":
        payload["document_id"] = "another-document"
    elif tamper == "dependency":
        payload["interaction_steps"][0]["dependencies"][0] = "resolution:ghost"
    elif tamper == "terminal":
        payload["terminal_step_ids"] = ["resolution:left"]
    elif tamper == "count":
        payload["coverage"]["interaction_step_count"] = 2
    elif tamper == "completeness":
        payload["coverage"]["interaction_analysis_complete"] = False
    elif tamper == "missing_step":
        payload["applicability_steps"].pop()
    elif tamper == "duplicate_step":
        payload["resolution_steps"].append(payload["resolution_steps"][0])
    elif tamper == "source_expected_value":
        payload["source_rules"][0]["predicates"][0]["expected_value"] = 99
    elif tamper == "source_decision_status":
        payload["source_decisions"][0]["status"] = "not_applicable"
    elif tamper == "forward_edge":
        payload["resolution_steps"][0]["dependencies"] = [
            payload["interaction_steps"][0]["step_id"]
        ]
    elif tamper == "cycle":
        payload["applicability_steps"][0]["dependencies"] = ["resolution:left"]
    elif tamper == "relabelled_step":
        payload["interaction_steps"][0]["step_id"] = "interaction:relabeled"

    with pytest.raises(ReasoningTraceError):
        load_reasoning_trace_bytes(json.dumps(payload).encode())


@pytest.mark.parametrize(
    "failure",
    [
        "duplicate_rule",
        "missing_rule",
        "extra_rule",
        "duplicate_decision",
        "missing_decision",
        "extra_decision",
        "mode",
        "status",
        "evidence",
        "source",
    ],
)
def test_builder_rejects_rule_decision_and_source_mismatch(failure: str) -> None:
    left = _rule("left")
    right = _rule("right")
    decisions = (_decision(left), _decision(right))
    resolution = _resolution(
        _entry(left, decisions[0], "eligibility.age"),
        _entry(right, decisions[1], "eligibility.age"),
    )
    rules: tuple[ApplicabilityRule, ...] = (left, right)
    supplied_decisions = decisions
    if failure == "duplicate_rule":
        rules = (left, left)
    elif failure == "missing_rule":
        rules = (left,)
    elif failure == "extra_rule":
        rules = (left, right, _rule("extra"))
    elif failure == "duplicate_decision":
        supplied_decisions = (decisions[0], decisions[0])
    elif failure == "missing_decision":
        supplied_decisions = (decisions[0],)
    elif failure == "extra_decision":
        extra = _rule("extra")
        supplied_decisions = decisions + (_decision(extra),)
    elif failure == "mode":
        supplied_decisions = (
            decisions[0].model_copy(update={"logical_mode": LogicalMode.ANY}),
            decisions[1],
        )
    elif failure == "status":
        supplied_decisions = (
            _decision(left, ApplicabilityStatus.NOT_APPLICABLE),
            decisions[1],
        )
    elif failure == "evidence":
        changed_reference = (
            decisions[0].official_evidence[0].model_copy(update={"role": EvidenceRole.ATTACHED})
        )
        supplied_decisions = (
            decisions[0].model_copy(update={"official_evidence": (changed_reference,)}),
            decisions[1],
        )
    elif failure == "source":
        supplied_decisions = (
            decisions[0].model_copy(update={"source_kb_sha256": "d" * 64}),
            decisions[1],
        )

    with pytest.raises(ReasoningTraceError):
        build_reasoning_trace(
            "trace:invalid",
            rules,
            supplied_decisions,
            _report(resolution, InteractionRelationship.COMPATIBLE),
        )


def test_error_does_not_echo_secret_input() -> None:
    secret = "PLANTED_PROFILE_QUERY_PATH_SECRET"
    with pytest.raises(ReasoningTraceError) as caught:
        load_reasoning_trace_bytes(secret.encode())
    assert secret not in str(caught.value)


def test_trace_is_immutable_and_path_loader_rejects_symlink(tmp_path: Path) -> None:
    trace = _two_rule_trace()
    with pytest.raises(ValidationError):
        trace.trace_id = "changed"  # type: ignore[misc]

    target = tmp_path / "trace.json"
    target.write_bytes(canonical_reasoning_trace_bytes(trace))
    assert load_reasoning_trace(target) == trace
    link = tmp_path / "trace-link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ReasoningTraceError, match="unavailable or unsafe"):
        load_reasoning_trace(link)


def test_build_and_load_do_not_access_network_or_model_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "socket", deny_network)
    trace = _two_rule_trace()
    assert load_reasoning_trace_bytes(canonical_reasoning_trace_bytes(trace)) == trace
    assert "sentence_transformers" not in sys.modules
    assert "openai" not in sys.modules


def test_reviewed_scenario_table_covers_synthetic_and_real_boundaries() -> None:
    fixture = json.loads(TRACE_FIXTURE.read_text(encoding="utf-8"))
    synthetic = fixture["synthetic_scenarios"]
    real = fixture["real_kb_scenarios"]
    assert {item["scenario_id"] for item in synthetic} == {
        "confirmed-active-compatible",
        "pending-and-unreviewed",
        "direct-override-inactive-pair",
        "reviewed-warning-matrix",
    }
    assert real["fact_id"] == "fact:00063"
    assert real["source_pages"] == [7]
    assert real["statuses"] == ["confirmed", "not_applicable", "needs_information"]
    assert real["interaction_step_count"] == 0
    assert real["final_eligibility_present"] is False


@pytest.mark.parametrize(
    ("scenario_id", "expected_status"),
    [
        ("confirmed", ApplicabilityStatus.CONFIRMED),
        ("not-applicable", ApplicabilityStatus.NOT_APPLICABLE),
        ("needs-information", ApplicabilityStatus.NEEDS_INFORMATION),
    ],
)
def test_real_fact_00063_trace_preserves_reviewed_status_and_page(
    scenario_id: str,
    expected_status: ApplicabilityStatus,
) -> None:
    fixture_rule = REAL_DATA["rule"]
    fact = REAL_DATA["fact"]
    scope = RuleScope(**fixture_rule["scope"])
    rule = ApplicabilityRule(
        rule_id=fixture_rule["rule_id"],
        mode=fixture_rule["mode"],
        predicates=tuple(ApplicabilityPredicate(**item) for item in fixture_rule["predicates"]),
        scope=scope,
        evidence_bindings=(
            OfficialEvidenceBinding(
                document_id=REAL_DATA["document_id"],
                source_kb_sha256=REAL_KB_HASH,
                source_pdf_sha256=REAL_PDF_HASH,
                fact_id=fact["fact_id"],
                source_pages=tuple(fact["source_pages"]),
                authoritative_fact_text_sha256=fact["authoritative_fact_text_sha256"],
            ),
        ),
        annotation_note=fixture_rule["annotation_note"],
    )
    age_status = expected_status
    decision = ApplicabilityDecision(
        rule_id=rule.rule_id,
        logical_mode=rule.mode,
        status=expected_status,
        predicate_outcomes=(
            PredicateOutcome(
                field_path=rule.predicates[0].field_path,
                operator=rule.predicates[0].operator,
                status=ApplicabilityStatus.CONFIRMED,
            ),
            PredicateOutcome(
                field_path=rule.predicates[1].field_path,
                operator=rule.predicates[1].operator,
                status=age_status,
            ),
        ),
        missing_profile_fields=(rule.predicates[1].field_path,)
        if expected_status is ApplicabilityStatus.NEEDS_INFORMATION
        else (),
        diagnostics=(ApplicabilityDiagnostic.MISSING_PROFILE_FACT,)
        if expected_status is ApplicabilityStatus.NEEDS_INFORMATION
        else (),
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
        source_kb_sha256=REAL_KB_HASH,
        source_pdf_sha256=REAL_PDF_HASH,
    )
    resolution = _resolution(_entry(rule, decision, "eligibility.individual_review"))
    trace = build_reasoning_trace(
        f"trace:real:{scenario_id}",
        (rule,),
        (decision,),
        _report(resolution),
    )

    assert trace.applicability_steps[0].status is expected_status
    assert trace.applicability_steps[0].official_evidence[0].fact_id == "fact:00063"
    assert trace.applicability_steps[0].official_evidence[0].source_pages == (7,)
    assert trace.interaction_steps == ()
    assert fixture_rule["annotation_note"] not in canonical_reasoning_trace_bytes(trace).decode()
