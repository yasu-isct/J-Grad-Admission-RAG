from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.reasoning.applicability import (
    ApplicabilityDecision,
    ApplicabilityDiagnostic,
    ApplicabilityError,
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
    canonical_applicability_decision_bytes,
    canonical_applicability_rule_bytes,
    evaluate_applicability,
    load_applicability_decision,
    load_applicability_decision_bytes,
    load_applicability_rule,
    load_applicability_rule_bytes,
)
from jgrad_admission_rag.reasoning.applicant_profile import ApplicantProfile
from jgrad_admission_rag.reasoning.query_intent import (
    DiagnosticCode,
    IntentMention,
    MentionKind,
    QueryIntent,
    RequestedScope,
)
from jgrad_admission_rag.schemas.evidence_pack import (
    AttachedReferenceEvidence,
    EvidenceCounts,
    EvidenceMetadataFilter,
    EvidencePack,
    EvidenceRequest,
    EvidenceRuntime,
    EvidenceScopePreference,
    IncomingRelation,
    PrimaryEvidence,
    ResolvedReferenceRelation,
)

KB_HASH = "a" * 64
PDF_HASH = "b" * 64
OFFICIAL_TEXT = "Reviewed official rule text"
CONTRACT_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "applicability_real_scenarios_v1.json"


def _profile(**changes: object) -> ApplicantProfile:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "target_application": {
            "graduate_school_or_college": None,
            "department_or_program": None,
            "requested_degree_level": "master",
            "intake_year": 2027,
            "intake_month": 4,
            "application_route": None,
        },
        "citizenship_and_residence": {
            "citizenship_country_codes": ("JP",),
            "current_residence_country_code": "JP",
            "residence_status_category": None,
        },
        "academic_credentials": (
            {
                "institution_country_code": "JP",
                "degree_level": "bachelor",
                "completion_state": "completed",
                "completion_date": "2026-03-20",
                "expected_completion_date": None,
                "years_of_education": 16,
            },
        ),
        "eligibility_facts": {
            "age_at_enrollment": 24,
            "professional_experience_months": 12,
            "research_experience_months": None,
            "individual_review_status": "not_requested",
            "individual_review_requested": False,
            "individual_review_completed": False,
        },
        "language_test_results": None,
    }
    for key, value in changes.items():
        section, field = key.split("__", maxsplit=1)
        section_value = dict(payload[section])  # type: ignore[arg-type]
        section_value[field] = value
        payload[section] = section_value
    return ApplicantProfile.model_validate(payload)


def _intent(*, target: str | None = None, college: str | None = None) -> QueryIntent:
    if target is not None and college is not None:
        raise ValueError("test intent supports one scope mention")
    value = target or college
    if value is None:
        return QueryIntent(
            schema_version="1.0",
            parser_version="lexical-ja-v1",
            catalog_version="test-v1",
            query="eligibility question",
            requested_categories=(),
            requested_scope=RequestedScope(
                department_or_program_targets=(),
                parent_college_values=(),
                target_degree_level=None,
                intake_year=None,
                intake_month=None,
            ),
            matched_mentions=(),
            diagnostics=(DiagnosticCode.NO_RECOGNIZED_INTENT,),
        )
    kind = MentionKind.SCOPE_TARGET if target is not None else MentionKind.PARENT_COLLEGE
    return QueryIntent(
        schema_version="1.0",
        parser_version="lexical-ja-v1",
        catalog_version="test-v1",
        query=value,
        requested_categories=(),
        requested_scope=RequestedScope(
            department_or_program_targets=(value,) if target is not None else (),
            parent_college_values=(value,) if college is not None else (),
            target_degree_level=None,
            intake_year=None,
            intake_month=None,
        ),
        matched_mentions=(
            IntentMention(
                canonical_value=value,
                mention_kind=kind,
                start_offset=0,
                end_offset=len(value),
                surface=value,
            ),
        ),
        diagnostics=(),
    )


def _runtime() -> EvidenceRuntime:
    return EvidenceRuntime(
        document_id="doc",
        source_kb_sha256=KB_HASH,
        source_pdf_sha256=PDF_HASH,
        index_schema_version="0.1",
        source_kb_schema_version="0.5",
        payloads_sha256="c" * 64,
        vectors_sha256="d" * 64,
        index_builder_version="0.1.0",
        embedding_provider="deterministic-fake",
        embedding_model="sha256-counter-v1",
        embedding_dimension=8,
        distance_metric="cosine",
        semantic=False,
        lexical_tokenizer_version="nfkc-casefold-ja23-v1",
        lexical_scoring_version="bm25-v1",
        fusion_version="rrf-v1",
        rrf_k=60,
        metadata_filter_version="exact-metadata-v1",
        scope_rerank_version="scope-match-v1",
        scope_target_match_boost=0.0,
        parent_college_match_boost=0.0,
        reference_expansion_version="reference-one-hop-v1",
        reference_expansion_depth=1,
        corpus_row_count=2,
        eligible_row_count=2,
        vector_candidate_count=2,
        lexical_candidate_count=2,
    )


def _primary(
    fact_id: str,
    text: str,
    row: int,
    rank: int,
    *,
    scope_type: str = "global",
    scope_targets: tuple[str, ...] = (),
    parent_college: str | None = None,
) -> PrimaryEvidence:
    return PrimaryEvidence(
        primary_rank=rank,
        ranking_score=2 / (60 + rank),
        fused_score=2 / (60 + rank),
        scope_boost_total=0.0,
        fusion_version="rrf-v1",
        vector_rank=rank,
        vector_score=0.9,
        lexical_rank=rank,
        lexical_score=2.0,
        matched_channels=("vector", "lexical"),
        row_index=row,
        document_id="doc",
        unit_id=f"unit:{row}",
        fact_id=fact_id,
        text=text,
        source_pages=(row + 1,),
        section_path=("募集要項",),
        fact_type="eligibility",
        scope_type=scope_type,
        scope_targets=scope_targets,
        parent_college=parent_college,
    )


def _pack(
    *,
    role: EvidenceRole = EvidenceRole.PRIMARY,
    include_rule: bool = True,
    scope_type: str = "global",
    scope_targets: tuple[str, ...] = (),
    parent_college: str | None = None,
) -> EvidencePack:
    query = _intent().query
    source = _primary("fact:source", "Reference source", 0, 1)
    rule_primary = _primary(
        "fact:rule",
        OFFICIAL_TEXT,
        1,
        1,
        scope_type=scope_type,
        scope_targets=scope_targets,
        parent_college=parent_college,
    )
    primaries: tuple[PrimaryEvidence, ...]
    attached: tuple[AttachedReferenceEvidence, ...] = ()
    relations: tuple[ResolvedReferenceRelation, ...] = ()
    if not include_rule:
        primaries = (source,)
    elif role is EvidenceRole.PRIMARY:
        primaries = (rule_primary,)
    else:
        primaries = (source,)
        incoming = IncomingRelation(
            source_primary_rank=1,
            source_fact_id=source.fact_id,
            label="下記",
            reference_key="key",
            direction="forward",
        )
        attached = (
            AttachedReferenceEvidence(
                row_index=1,
                document_id="doc",
                unit_id="unit:1",
                fact_id="fact:rule",
                text=OFFICIAL_TEXT,
                source_pages=(2,),
                section_path=("募集要項",),
                fact_type="eligibility",
                scope_type=scope_type,
                scope_targets=scope_targets,
                parent_college=parent_college,
                incoming_relations=(incoming,),
            ),
        )
        relations = (
            ResolvedReferenceRelation(
                source_primary_rank=1,
                source_claim_index=0,
                source_fact_id=source.fact_id,
                label="下記",
                reference_key="key",
                direction="forward",
                selected_target_fact_id="fact:rule",
                candidate_target_fact_ids=("fact:rule",),
                reason="unique_match",
                disposition="attached_target",
                target_row_index=1,
            ),
        )
    return EvidencePack(
        request=EvidenceRequest(
            query=query,
            top_k_requested=1,
            candidate_k_requested=2,
            candidate_k_resolved=2,
            metadata_filter=EvidenceMetadataFilter(),
            scope_preference=EvidenceScopePreference(),
        ),
        runtime=_runtime(),
        primary_evidence=primaries,
        attached_reference_evidence=attached,
        resolved_relations=relations,
        reference_warnings=(),
        counts=EvidenceCounts(
            primary_evidence_count=len(primaries),
            attached_evidence_count=len(attached),
            resolved_relation_count=len(relations),
            warning_count=0,
            warning_status_counts={"ambiguous": 0, "unresolved": 0},
            unique_evidence_count=len(primaries) + len(attached),
        ),
    )


def _predicate(
    path: str = "eligibility_facts.age_at_enrollment",
    operator: PredicateOperator = PredicateOperator.MINIMUM,
    value: object = 18,
) -> ApplicabilityPredicate:
    return ApplicabilityPredicate(field_path=path, operator=operator, expected_value=value)


def _binding(**changes: object) -> OfficialEvidenceBinding:
    payload = {
        "document_id": "doc",
        "source_kb_sha256": KB_HASH,
        "source_pdf_sha256": PDF_HASH,
        "fact_id": "fact:rule",
        "source_pages": (2,),
        "authoritative_fact_text_sha256": hashlib.sha256(OFFICIAL_TEXT.encode()).hexdigest(),
    }
    payload.update(changes)
    return OfficialEvidenceBinding.model_validate(payload)


def _rule(
    *predicates: ApplicabilityPredicate,
    mode: LogicalMode = LogicalMode.ALL,
    scope: RuleScope | None = None,
    binding: OfficialEvidenceBinding | None = None,
) -> ApplicabilityRule:
    return ApplicabilityRule(
        rule_id="reviewed-rule-1",
        mode=mode,
        predicates=predicates or (_predicate(),),
        scope=scope or RuleScope(scope_type="global"),
        evidence_bindings=(binding or _binding(),),
        annotation_note="Human-reviewed interpretation fixture.",
    )


@pytest.mark.parametrize(
    ("path", "operator", "expected", "status"),
    [
        ("target_application.requested_degree_level", "equals", "master", "confirmed"),
        ("target_application.intake_year", "not_equals", 2026, "confirmed"),
        ("target_application.intake_month", "maximum", 3, "not_applicable"),
        ("citizenship_and_residence.citizenship_country_codes", "contains", "JP", "confirmed"),
        ("citizenship_and_residence.citizenship_country_codes", "is_non_empty", None, "confirmed"),
        ("eligibility_facts.professional_experience_months", "minimum", 24, "not_applicable"),
        ("eligibility_facts.individual_review_requested", "equals", False, "confirmed"),
        ("academic_credentials.first.completion_date", "on_or_before", "2026-03-20", "confirmed"),
        ("academic_credentials.first.completion_date", "on_or_after", "2026-03-20", "confirmed"),
        (
            "academic_credentials.first.completion_date",
            "on_or_after",
            "2027-01-01",
            "not_applicable",
        ),
    ],
)
def test_typed_predicate_operators(path: str, operator: str, expected: object, status: str) -> None:
    decision = evaluate_applicability(
        _profile(),
        _intent(),
        _pack(),
        _rule(_predicate(path, PredicateOperator(operator), expected)),
    )

    assert decision.status.value == status


@pytest.mark.parametrize(
    ("mode", "ages", "expected"),
    [
        (LogicalMode.ALL, (18, 30), ApplicabilityStatus.CONFIRMED),
        (LogicalMode.ALL, (25, 30), ApplicabilityStatus.NOT_APPLICABLE),
        (LogicalMode.ANY, (25, 30), ApplicabilityStatus.CONFIRMED),
        (LogicalMode.ANY, (25, 20), ApplicabilityStatus.NOT_APPLICABLE),
    ],
)
def test_all_and_any_truth_tables(
    mode: LogicalMode, ages: tuple[int, int], expected: ApplicabilityStatus
) -> None:
    predicates = (
        _predicate(operator=PredicateOperator.MINIMUM, value=ages[0]),
        _predicate(operator=PredicateOperator.MAXIMUM, value=ages[1]),
    )

    assert (
        evaluate_applicability(_profile(), _intent(), _pack(), _rule(*predicates, mode=mode)).status
        is expected
    )


def test_versioned_synthetic_fixture_freezes_atomic_and_aggregate_contract() -> None:
    fixture = json.loads(CONTRACT_FIXTURE_PATH.read_text(encoding="utf-8"))[
        "synthetic_contract_cases"
    ]
    for case in fixture["atomic"]:
        profile = _profile(eligibility_facts__age_at_enrollment=case["profile_value"])
        predicate = _predicate(
            operator=PredicateOperator(case["operator"]), value=case["expected_value"]
        )
        assert (
            evaluate_applicability(profile, _intent(), _pack(), _rule(predicate)).status.value
            == case["expected_status"]
        )

    status_predicates = {
        "confirmed": (
            _predicate(operator=PredicateOperator.MINIMUM, value=22),
            _predicate(
                "eligibility_facts.professional_experience_months",
                PredicateOperator.MAXIMUM,
                20,
            ),
        ),
        "not_applicable": (
            _predicate(operator=PredicateOperator.MAXIMUM, value=21),
            _predicate(
                "eligibility_facts.professional_experience_months",
                PredicateOperator.MINIMUM,
                20,
            ),
        ),
        "needs_information": (
            _predicate(
                "eligibility_facts.research_experience_months",
                PredicateOperator.MINIMUM,
                1,
            ),
            _predicate(
                "language_test_results.first.test_date",
                PredicateOperator.ON_OR_AFTER,
                "2026-01-01",
            ),
        ),
    }
    for mode, fixture_key in (
        (LogicalMode.ALL, "all_truth_table"),
        (LogicalMode.ANY, "any_truth_table"),
    ):
        for case in fixture[fixture_key]:
            predicates = tuple(
                status_predicates[value][index] for index, value in enumerate(case["inputs"])
            )
            actual = evaluate_applicability(
                _profile(), _intent(), _pack(), _rule(*predicates, mode=mode)
            )
            assert actual.status.value == case["expected_status"]


@pytest.mark.parametrize("mode", [LogicalMode.ALL, LogicalMode.ANY])
def test_unknown_branch_in_each_aggregate_truth_table(mode: LogicalMode) -> None:
    predicates = (
        _predicate(operator=PredicateOperator.MINIMUM, value=18),
        _predicate(
            "eligibility_facts.research_experience_months",
            PredicateOperator.MINIMUM,
            1,
        ),
    )
    decision = evaluate_applicability(_profile(), _intent(), _pack(), _rule(*predicates, mode=mode))

    expected = (
        ApplicabilityStatus.NEEDS_INFORMATION
        if mode is LogicalMode.ALL
        else ApplicabilityStatus.CONFIRMED
    )
    assert decision.status is expected


@pytest.mark.parametrize(
    ("profile", "predicate", "expected"),
    [
        (
            _profile(eligibility_facts__professional_experience_months=0),
            _predicate(
                "eligibility_facts.professional_experience_months",
                PredicateOperator.MINIMUM,
                0,
            ),
            ApplicabilityStatus.CONFIRMED,
        ),
        (
            _profile(citizenship_and_residence__citizenship_country_codes=()),
            _predicate(
                "citizenship_and_residence.citizenship_country_codes",
                PredicateOperator.IS_EMPTY,
                None,
            ),
            ApplicabilityStatus.CONFIRMED,
        ),
        (
            _profile(citizenship_and_residence__citizenship_country_codes=None),
            _predicate(
                "citizenship_and_residence.citizenship_country_codes",
                PredicateOperator.IS_EMPTY,
                None,
            ),
            ApplicabilityStatus.NEEDS_INFORMATION,
        ),
        (
            _profile(eligibility_facts__individual_review_requested=False),
            _predicate(
                "eligibility_facts.individual_review_requested",
                PredicateOperator.EQUALS,
                False,
            ),
            ApplicabilityStatus.CONFIRMED,
        ),
    ],
)
def test_unknown_false_zero_and_explicit_empty_remain_distinct(
    profile: ApplicantProfile,
    predicate: ApplicabilityPredicate,
    expected: ApplicabilityStatus,
) -> None:
    decision = evaluate_applicability(profile, _intent(), _pack(), _rule(predicate))
    assert decision.status is expected


def test_unknown_profile_fact_produces_needs_information_without_leaking_value() -> None:
    decision = evaluate_applicability(
        _profile(eligibility_facts__research_experience_months=None),
        _intent(),
        _pack(),
        _rule(
            _predicate("eligibility_facts.research_experience_months", PredicateOperator.MINIMUM, 1)
        ),
    )

    assert decision.status is ApplicabilityStatus.NEEDS_INFORMATION
    assert decision.missing_profile_fields == ("eligibility_facts.research_experience_months",)
    assert ApplicabilityDiagnostic.MISSING_PROFILE_FACT in decision.diagnostics
    assert "24" not in canonical_applicability_decision_bytes(decision).decode()


def test_unicode_string_comparison_is_exact() -> None:
    predicate = _predicate(
        "target_application.application_route",
        PredicateOperator.EQUALS,
        "一般選抜",
    )
    matching = _profile(target_application__application_route="一般選抜")
    different = _profile(target_application__application_route="一般選考")

    assert (
        evaluate_applicability(matching, _intent(), _pack(), _rule(predicate)).status
        is ApplicabilityStatus.CONFIRMED
    )
    assert (
        evaluate_applicability(different, _intent(), _pack(), _rule(predicate)).status
        is ApplicabilityStatus.NOT_APPLICABLE
    )


@pytest.mark.parametrize("role", [EvidenceRole.PRIMARY, EvidenceRole.ATTACHED])
def test_evidence_binding_accepts_primary_and_attached_records(role: EvidenceRole) -> None:
    decision = evaluate_applicability(_profile(), _intent(), _pack(role=role), _rule())

    assert decision.status is ApplicabilityStatus.CONFIRMED
    assert decision.official_evidence[0].role is role


def test_missing_evidence_never_confirms_rule() -> None:
    decision = evaluate_applicability(_profile(), _intent(), _pack(include_rule=False), _rule())

    assert decision.status is ApplicabilityStatus.NEEDS_INFORMATION
    assert decision.official_evidence == ()
    assert ApplicabilityDiagnostic.MISSING_OFFICIAL_EVIDENCE in decision.diagnostics


@pytest.mark.parametrize(
    "binding_change",
    [
        {"document_id": "other-doc"},
        {"source_kb_sha256": "e" * 64},
        {"source_pdf_sha256": "e" * 64},
        {"source_pages": (1,)},
    ],
)
def test_evidence_source_identity_and_page_mismatches_fail_closed(
    binding_change: dict[str, object],
) -> None:
    with pytest.raises(ApplicabilityError, match="binding is inconsistent"):
        evaluate_applicability(
            _profile(), _intent(), _pack(), _rule(binding=_binding(**binding_change))
        )


def test_authoritative_fact_hash_is_not_confused_with_evidence_projection_hash() -> None:
    rule = _rule(binding=_binding(authoritative_fact_text_sha256="e" * 64))

    decision = evaluate_applicability(_profile(), _intent(), _pack(), rule)

    assert decision.status is ApplicabilityStatus.CONFIRMED
    assert decision.source_kb_sha256 == KB_HASH


def test_wrong_fact_id_is_missing_evidence_and_duplicate_binding_is_rejected() -> None:
    missing = evaluate_applicability(
        _profile(),
        _intent(),
        _pack(),
        _rule(binding=_binding(fact_id="fact:absent")),
    )
    assert missing.status is ApplicabilityStatus.NEEDS_INFORMATION
    assert ApplicabilityDiagnostic.MISSING_OFFICIAL_EVIDENCE in missing.diagnostics

    binding = _binding()
    payload = _rule().model_dump(mode="json")
    payload["evidence_bindings"] = [
        binding.model_dump(mode="json"),
        binding.model_dump(mode="json"),
    ]
    with pytest.raises(ValidationError, match="bindings must be unique"):
        ApplicabilityRule.model_validate(payload)


def test_evidence_scope_must_match_reviewed_rule_scope() -> None:
    rule = _rule(scope=RuleScope(scope_type="department", scope_targets=("情報工学系",)))
    with pytest.raises(ApplicabilityError, match="binding is inconsistent"):
        evaluate_applicability(
            _profile(target_application__department_or_program="情報工学系"),
            _intent(),
            _pack(),
            rule,
        )


@pytest.mark.parametrize(
    ("scope", "profile", "intent", "expected", "diagnostic"),
    [
        (RuleScope(scope_type="global"), _profile(), _intent(), "confirmed", None),
        (
            RuleScope(scope_type="department", scope_targets=("情報工学系",)),
            _profile(target_application__department_or_program="情報工学系"),
            _intent(target="情報工学系"),
            "confirmed",
            None,
        ),
        (
            RuleScope(scope_type="department", scope_targets=("情報工学系",)),
            _profile(target_application__department_or_program="機械系"),
            _intent(target="機械系"),
            "not_applicable",
            None,
        ),
        (
            RuleScope(scope_type="department", scope_targets=("情報工学系",)),
            _profile(),
            _intent(),
            "needs_information",
            ApplicabilityDiagnostic.MISSING_SCOPE,
        ),
        (
            RuleScope(scope_type="department", scope_targets=("情報工学系",)),
            _profile(target_application__department_or_program="情報工学系"),
            _intent(target="機械系"),
            "needs_information",
            ApplicabilityDiagnostic.SCOPE_INPUT_CONFLICT,
        ),
    ],
)
def test_scope_matching_and_conflict_are_three_state(
    scope: RuleScope,
    profile: ApplicantProfile,
    intent: QueryIntent,
    expected: str,
    diagnostic: ApplicabilityDiagnostic | None,
) -> None:
    pack = _pack(
        scope_type=scope.scope_type,
        scope_targets=scope.scope_targets,
        parent_college=scope.parent_college,
    )
    pack = pack.model_copy(
        update={"request": pack.request.model_copy(update={"query": intent.query})}
    )
    decision = evaluate_applicability(profile, intent, pack, _rule(scope=scope))

    assert decision.status.value == expected
    if diagnostic is not None:
        assert diagnostic in decision.diagnostics


@pytest.mark.parametrize(
    "payload",
    [
        {"field_path": "unknown.path", "operator": "equals", "expected_value": "x"},
        {
            "field_path": "eligibility_facts.age_at_enrollment",
            "operator": "contains",
            "expected_value": 18,
        },
        {
            "field_path": "eligibility_facts.age_at_enrollment",
            "operator": "minimum",
            "expected_value": "18",
        },
        {
            "field_path": "citizenship_and_residence.citizenship_country_codes",
            "operator": "is_empty",
            "expected_value": "JP",
        },
        {
            "field_path": "academic_credentials.first.completion_date",
            "operator": "on_or_before",
            "expected_value": "not-a-date",
        },
    ],
)
def test_predicate_contract_rejects_untyped_or_unallowlisted_rules(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ApplicabilityPredicate.model_validate(payload)


@pytest.mark.parametrize(
    "predicates",
    [
        (
            _predicate(operator=PredicateOperator.MINIMUM, value=22),
            _predicate(operator=PredicateOperator.MAXIMUM, value=21),
        ),
        (
            _predicate(operator=PredicateOperator.EQUALS, value=22),
            _predicate(operator=PredicateOperator.NOT_EQUALS, value=22),
        ),
        (
            _predicate(operator=PredicateOperator.EQUALS, value=22),
            _predicate(operator=PredicateOperator.EQUALS, value=23),
        ),
        (
            _predicate(
                "citizenship_and_residence.citizenship_country_codes",
                PredicateOperator.CONTAINS,
                "JP",
            ),
            _predicate(
                "citizenship_and_residence.citizenship_country_codes",
                PredicateOperator.IS_EMPTY,
                None,
            ),
        ),
    ],
)
def test_all_mode_rejects_obvious_predicate_contradictions(
    predicates: tuple[ApplicabilityPredicate, ...],
) -> None:
    with pytest.raises(ValidationError, match="contradictory"):
        _rule(*predicates, mode=LogicalMode.ALL)

    assert _rule(*predicates, mode=LogicalMode.ANY).mode is LogicalMode.ANY


@pytest.mark.parametrize(
    "mutation",
    [
        {
            "status": "confirmed",
            "missing_profile_fields": ["eligibility_facts.age_at_enrollment"],
            "diagnostics": ["missing_profile_fact"],
        },
        {
            "status": "confirmed",
            "official_evidence": [],
            "diagnostics": ["missing_official_evidence"],
        },
        {
            "status": "confirmed",
            "scope_status": "needs_information",
            "diagnostics": ["scope_input_conflict"],
        },
        {
            "status": "confirmed",
            "predicate_outcomes": [
                {
                    "field_path": "eligibility_facts.age_at_enrollment",
                    "operator": "minimum",
                    "status": "not_applicable",
                }
            ],
        },
    ],
)
def test_decision_contract_rejects_internally_contradictory_states(
    mutation: dict[str, object],
) -> None:
    decision = evaluate_applicability(_profile(), _intent(), _pack(), _rule())
    payload = decision.model_dump(mode="json")
    payload.update(mutation)
    typed_mutation = dict(mutation)
    if "status" in typed_mutation:
        typed_mutation["status"] = ApplicabilityStatus(typed_mutation["status"])
    if "scope_status" in typed_mutation:
        typed_mutation["scope_status"] = ApplicabilityStatus(typed_mutation["scope_status"])
    if "missing_profile_fields" in typed_mutation:
        typed_mutation["missing_profile_fields"] = tuple(typed_mutation["missing_profile_fields"])
    if "diagnostics" in typed_mutation:
        typed_mutation["diagnostics"] = tuple(
            ApplicabilityDiagnostic(value) for value in typed_mutation["diagnostics"]
        )
    if "predicate_outcomes" in typed_mutation:
        typed_mutation["predicate_outcomes"] = tuple(
            PredicateOutcome.model_validate(value) for value in typed_mutation["predicate_outcomes"]
        )
    if "official_evidence" in typed_mutation:
        typed_mutation["official_evidence"] = tuple(
            OfficialEvidenceReference.model_validate(value)
            for value in typed_mutation["official_evidence"]
        )

    with pytest.raises(ValidationError):
        ApplicabilityDecision.model_validate(payload)
    unsafe_copy = decision.model_copy(update=typed_mutation)
    with pytest.raises(ApplicabilityError, match="invalid or unsupported"):
        canonical_applicability_decision_bytes(unsafe_copy)
    unsafe_construct = ApplicabilityDecision.model_construct(
        **{**decision.__dict__, **typed_mutation}
    )
    with pytest.raises(ApplicabilityError, match="invalid or unsupported"):
        canonical_applicability_decision_bytes(unsafe_construct)
    with pytest.raises(ApplicabilityError, match="invalid or unsupported"):
        load_applicability_decision_bytes(
            (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        )


def test_rules_and_decisions_are_immutable_canonical_and_detached() -> None:
    rule = _rule()
    first = canonical_applicability_rule_bytes(rule)
    second = canonical_applicability_rule_bytes(
        ApplicabilityRule.model_validate(rule.model_dump(mode="json"))
    )
    decision = evaluate_applicability(_profile(), _intent(), _pack(), rule)

    assert first == second and first.endswith(b"\n")
    decision_bytes = canonical_applicability_decision_bytes(decision)
    assert decision_bytes.endswith(b"\n")
    assert OFFICIAL_TEXT.encode() not in decision_bytes
    assert _intent().query.encode() not in decision_bytes
    with pytest.raises(ValidationError):
        ApplicabilityRule.model_validate({**rule.model_dump(mode="json"), "extra": True})
    with pytest.raises(ValidationError):
        rule.rule_id = "changed"  # type: ignore[misc]


def test_rule_and_decision_loaders_round_trip_regular_files(tmp_path: Path) -> None:
    rule = _rule()
    decision = evaluate_applicability(_profile(), _intent(), _pack(), rule)
    rule_path = tmp_path / "rule.json"
    decision_path = tmp_path / "decision.json"
    rule_path.write_bytes(canonical_applicability_rule_bytes(rule))
    decision_path.write_bytes(canonical_applicability_decision_bytes(decision))

    assert load_applicability_rule_bytes(rule_path.read_bytes()) == rule
    assert load_applicability_rule(rule_path) == rule
    assert load_applicability_decision_bytes(decision_path.read_bytes()) == decision
    assert load_applicability_decision(decision_path) == decision


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json",
        b'{"schema_version":"2.0"}',
        b'{"schema_version":"1.0","expected_value":NaN}',
        "secret-not-bytes",
    ],
)
def test_rule_loader_fails_closed_without_echoing_secrets(raw: object) -> None:
    with pytest.raises(ApplicabilityError, match="invalid or unsupported") as caught:
        load_applicability_rule_bytes(raw)  # type: ignore[arg-type]
    assert "secret-not-bytes" not in str(caught.value)


def test_rule_path_loader_rejects_missing_file_and_symlink(tmp_path: Path) -> None:
    with pytest.raises(ApplicabilityError, match="unavailable or unsafe"):
        load_applicability_rule(tmp_path / "secret-missing-rule.json")

    target = tmp_path / "rule.json"
    target.write_bytes(canonical_applicability_rule_bytes(_rule()))
    link = tmp_path / "rule-link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ApplicabilityError, match="unavailable or unsafe"):
        load_applicability_rule(link)


@pytest.mark.parametrize(
    ("argument", "invalid"),
    [
        ("profile", ApplicantProfile.model_construct(schema_version="secret-profile")),
        ("intent", QueryIntent.model_construct(schema_version="secret-intent")),
        ("pack", EvidencePack.model_construct(schema_version="secret-pack")),
        ("rule", ApplicabilityRule.model_construct(schema_version="secret-rule")),
    ],
)
def test_constructed_invalid_public_input_is_fully_revalidated(
    argument: str, invalid: object
) -> None:
    arguments = {
        "profile": _profile(),
        "intent": _intent(),
        "pack": _pack(),
        "rule": _rule(),
    }
    arguments[argument] = invalid
    with pytest.raises(ApplicabilityError, match="invalid or unsupported") as caught:
        evaluate_applicability(
            arguments["profile"],  # type: ignore[arg-type]
            arguments["intent"],  # type: ignore[arg-type]
            arguments["pack"],  # type: ignore[arg-type]
            arguments["rule"],  # type: ignore[arg-type]
        )
    assert "secret-" not in str(caught.value)


def test_query_and_evidence_pack_must_describe_the_same_query() -> None:
    with pytest.raises(ApplicabilityError, match="inputs are inconsistent"):
        evaluate_applicability(
            _profile(),
            _intent(target="情報工学系"),
            _pack(),
            _rule(),
        )
