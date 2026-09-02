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
from jgrad_admission_rag.reasoning.rule_resolution import (
    OverrideEdge,
    RulePrecedencePolicy,
    RuleResolutionError,
    RuleSubjectAssignment,
    canonical_rule_precedence_policy_bytes,
    canonical_rule_resolution_bytes,
    load_rule_precedence_policy,
    load_rule_precedence_policy_bytes,
    load_rule_resolution_bytes,
    resolve_rule_precedence,
)

KB_HASH = "a" * 64
PDF_HASH = "b" * 64
TEXT_HASH = "c" * 64
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "rule_resolution_scenarios_v1.json"


def _scope(kind: str, *, targets: tuple[str, ...] = (), college: str | None = None) -> RuleScope:
    return RuleScope(scope_type=kind, scope_targets=targets, parent_college=college)  # type: ignore[arg-type]


def _rule(rule_id: str, scope: RuleScope, *, fact_id: str | None = None) -> ApplicabilityRule:
    return ApplicabilityRule(
        rule_id=rule_id,
        mode=LogicalMode.ALL,
        predicates=(
            ApplicabilityPredicate(
                field_path="eligibility_facts.age_at_enrollment",
                operator=PredicateOperator.MINIMUM,
                expected_value=18,
            ),
        ),
        scope=scope,
        evidence_bindings=(
            OfficialEvidenceBinding(
                document_id="doc",
                source_kb_sha256=KB_HASH,
                source_pdf_sha256=PDF_HASH,
                fact_id=fact_id or f"fact:{rule_id}",
                source_pages=(1,),
                authoritative_fact_text_sha256=TEXT_HASH,
            ),
        ),
        annotation_note="Reviewed test rule.",
    )


def _decision(
    rule: ApplicabilityRule,
    status: ApplicabilityStatus = ApplicabilityStatus.CONFIRMED,
    *,
    kb_hash: str = KB_HASH,
    evidence_fact_id: str | None = None,
) -> ApplicabilityDecision:
    outcome = status
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
                status=outcome,
            ),
        ),
        missing_profile_fields=missing,
        diagnostics=diagnostics,
        official_evidence=(
            OfficialEvidenceReference(
                document_id="doc",
                fact_id=evidence_fact_id or binding.fact_id,
                source_pages=binding.source_pages,
                role=EvidenceRole.PRIMARY,
            ),
        ),
        scope_status=ApplicabilityStatus.CONFIRMED,
        document_id="doc",
        source_kb_sha256=kb_hash,
        source_pdf_sha256=PDF_HASH,
    )


def _policy(
    rules: tuple[ApplicabilityRule, ...],
    edges: tuple[tuple[str, str, str], ...],
    subjects: dict[str, str] | None = None,
) -> RulePrecedencePolicy:
    assigned = subjects or {rule.rule_id: "eligibility.age" for rule in rules}
    return RulePrecedencePolicy(
        policy_id="reviewed-policy",
        subjects=tuple(
            RuleSubjectAssignment(rule_id=rule_id, subject_key=subject)
            for rule_id, subject in sorted(assigned.items())
        ),
        override_edges=tuple(
            OverrideEdge(
                subject_key=subject,
                overrider_rule_id=overrider,
                overridden_rule_id=overridden,
                rationale="Reviewed direct replacement.",
            )
            for subject, overrider, overridden in sorted(edges)
        ),
    )


@pytest.mark.parametrize(
    ("narrow_scope", "broad_scope"),
    [
        (_scope("college", targets=("Engineering",)), _scope("global")),
        (
            _scope("department", targets=("Computer Science",), college="Engineering"),
            _scope("global"),
        ),
        (
            _scope("department", targets=("Computer Science",), college="Engineering"),
            _scope("college", targets=("Engineering",)),
        ),
        (
            _scope(
                "program",
                targets=("AI Program", "Computer Science"),
                college="Engineering",
            ),
            _scope("department", targets=("Computer Science",), college="Engineering"),
        ),
    ],
)
def test_reviewed_direct_edge_activates_for_proven_containment(
    narrow_scope: RuleScope, broad_scope: RuleScope
) -> None:
    broad = _rule("broad", broad_scope)
    narrow = _rule("narrow", narrow_scope)
    resolution = resolve_rule_precedence(
        (broad, narrow),
        (_decision(broad), _decision(narrow)),
        _policy((broad, narrow), (("eligibility.age", "narrow", "broad"),)),
    )

    assert resolution.active_rule_ids == ("narrow",)
    assert resolution.overridden_rule_ids == ("broad",)
    broad_entry = next(entry for entry in resolution.entries if entry.rule_id == "broad")
    assert broad_entry.activated_override is not None
    assert broad_entry.activated_override.overrider_rule_id == "narrow"
    assert broad_entry.official_evidence == _decision(broad).official_evidence


@pytest.mark.parametrize(
    ("narrow_status", "broad_status", "expected_narrow", "expected_broad"),
    [
        ("confirmed", "confirmed", "active", "overridden"),
        ("needs_information", "confirmed", "pending", "active"),
        ("not_applicable", "confirmed", "not_applicable", "active"),
        ("confirmed", "needs_information", "active", "pending"),
        ("confirmed", "not_applicable", "active", "not_applicable"),
    ],
)
def test_edge_activates_only_when_both_endpoints_are_confirmed(
    narrow_status: str, broad_status: str, expected_narrow: str, expected_broad: str
) -> None:
    broad = _rule("broad", _scope("global"))
    narrow = _rule("narrow", _scope("college", targets=("Engineering",)))
    resolution = resolve_rule_precedence(
        (broad, narrow),
        (
            _decision(broad, ApplicabilityStatus(broad_status)),
            _decision(narrow, ApplicabilityStatus(narrow_status)),
        ),
        _policy((broad, narrow), (("eligibility.age", "narrow", "broad"),)),
    )
    dispositions = {entry.rule_id: entry.disposition.value for entry in resolution.entries}
    assert dispositions == {"narrow": expected_narrow, "broad": expected_broad}


def test_no_direct_edge_leaves_confirmed_rules_active_and_subjects_independent() -> None:
    broad = _rule("broad", _scope("global"))
    narrow = _rule("narrow", _scope("college", targets=("Engineering",)))
    other_broad = _rule("other-broad", _scope("global"))
    other_narrow = _rule("other-narrow", _scope("college", targets=("Science",)))
    rules = (broad, narrow, other_broad, other_narrow)
    subjects = {
        "broad": "documents",
        "narrow": "documents",
        "other-broad": "fees",
        "other-narrow": "fees",
    }
    resolution = resolve_rule_precedence(
        rules,
        tuple(_decision(rule) for rule in rules),
        _policy(rules, (("fees", "other-narrow", "other-broad"),), subjects),
    )
    assert set(resolution.active_rule_ids) == {"broad", "narrow", "other-narrow"}
    assert resolution.overridden_rule_ids == ("other-broad",)


@pytest.mark.parametrize(
    ("narrow", "broad"),
    [
        (_scope("global"), _scope("global")),
        (_scope("college", targets=("Science",)), _scope("college", targets=("Engineering",))),
        (
            _scope("department", targets=("CS",), college="Science"),
            _scope("college", targets=("Engineering",)),
        ),
        (
            _scope("program", targets=("AI",), college="Engineering"),
            _scope("department", targets=("CS",), college="Engineering"),
        ),
        (_scope("global"), _scope("college", targets=("Engineering",))),
    ],
)
def test_equal_wrong_direction_or_unproven_containment_is_rejected(
    narrow: RuleScope, broad: RuleScope
) -> None:
    first = _rule("first", narrow)
    second = _rule("second", broad)
    with pytest.raises(RuleResolutionError, match="invalid or inconsistent"):
        resolve_rule_precedence(
            (first, second),
            (_decision(first), _decision(second)),
            _policy((first, second), (("eligibility.age", "first", "second"),)),
        )


def test_policy_rejects_self_duplicate_cycle_and_subject_mismatch() -> None:
    base = {
        "policy_id": "p",
        "subjects": [
            {"rule_id": "a", "subject_key": "s"},
            {"rule_id": "b", "subject_key": "s"},
        ],
    }
    edge = {
        "subject_key": "s",
        "overrider_rule_id": "a",
        "overridden_rule_id": "b",
        "rationale": "Reviewed.",
    }
    for edges in (
        [{**edge, "overridden_rule_id": "a"}],
        [edge, edge],
        [edge, {**edge, "overrider_rule_id": "b", "overridden_rule_id": "a"}],
        [{**edge, "subject_key": "different"}],
    ):
        with pytest.raises(ValidationError):
            RulePrecedencePolicy.model_validate({**base, "override_edges": edges})


def test_missing_endpoint_and_policy_assignment_are_rejected() -> None:
    broad = _rule("broad", _scope("global"))
    narrow = _rule("narrow", _scope("college", targets=("Engineering",)))
    extra = _rule("extra", _scope("college", targets=("Science",)))
    policy = _policy(
        (broad, narrow, extra),
        (("eligibility.age", "narrow", "broad"),),
    )
    with pytest.raises(RuleResolutionError):
        resolve_rule_precedence((broad, narrow), (_decision(broad), _decision(narrow)), policy)


@pytest.mark.parametrize("failure", ["duplicate-rule", "duplicate-decision", "missing-decision"])
def test_rule_and_decision_cardinality_is_strict(failure: str) -> None:
    broad = _rule("broad", _scope("global"))
    narrow = _rule("narrow", _scope("college", targets=("Engineering",)))
    rules = (broad, narrow)
    decisions = (_decision(broad), _decision(narrow))
    if failure == "duplicate-rule":
        rules = (broad, broad, narrow)
    elif failure == "duplicate-decision":
        decisions = (decisions[0], decisions[0], decisions[1])
    else:
        decisions = (decisions[0],)
    with pytest.raises(RuleResolutionError):
        resolve_rule_precedence(
            rules,
            decisions,
            _policy((broad, narrow), (("eligibility.age", "narrow", "broad"),)),
        )


def test_mode_evidence_and_mixed_source_mismatches_are_rejected() -> None:
    broad = _rule("broad", _scope("global"))
    narrow = _rule("narrow", _scope("college", targets=("Engineering",)))
    policy = _policy((broad, narrow), (("eligibility.age", "narrow", "broad"),))
    bad_mode = _decision(broad).model_copy(update={"logical_mode": LogicalMode.ANY})
    bad_evidence = _decision(broad, evidence_fact_id="fact:wrong")
    mixed_source = _decision(narrow, kb_hash="d" * 64)
    bad_outcome = _decision(broad).model_copy(
        update={
            "predicate_outcomes": (
                PredicateOutcome(
                    field_path="eligibility_facts.professional_experience_months",
                    operator=PredicateOperator.MINIMUM,
                    status=ApplicabilityStatus.CONFIRMED,
                ),
            )
        }
    )
    for decisions in (
        (bad_mode, _decision(narrow)),
        (bad_evidence, _decision(narrow)),
        (_decision(broad), mixed_source),
        (bad_outcome, _decision(narrow)),
    ):
        with pytest.raises(RuleResolutionError):
            resolve_rule_precedence((broad, narrow), decisions, policy)


def test_multiple_active_direct_overriders_are_ambiguous() -> None:
    broad = _rule("broad", _scope("global"))
    college = _rule("college", _scope("college", targets=("Engineering",)))
    department = _rule("department", _scope("department", targets=("CS",), college="Engineering"))
    rules = (broad, college, department)
    policy = _policy(
        rules,
        (
            ("eligibility.age", "college", "broad"),
            ("eligibility.age", "department", "broad"),
        ),
    )
    with pytest.raises(RuleResolutionError, match="ambiguous"):
        resolve_rule_precedence(rules, tuple(_decision(rule) for rule in rules), policy)


def test_direct_edges_do_not_infer_transitive_override() -> None:
    global_rule = _rule("global", _scope("global"))
    college = _rule("college", _scope("college", targets=("Engineering",)))
    department = _rule("department", _scope("department", targets=("CS",), college="Engineering"))
    rules = (global_rule, college, department)
    resolution = resolve_rule_precedence(
        rules,
        tuple(_decision(rule) for rule in rules),
        _policy(
            rules,
            (
                ("eligibility.age", "college", "global"),
                ("eligibility.age", "department", "college"),
            ),
        ),
    )
    global_entry = next(entry for entry in resolution.entries if entry.rule_id == "global")
    assert global_entry.activated_override is not None
    assert global_entry.activated_override.overrider_rule_id == "college"
    assert global_entry.activated_override.overrider_rule_id != "department"


def test_output_is_canonical_immutable_and_round_trips() -> None:
    broad = _rule("broad", _scope("global"))
    narrow = _rule("narrow", _scope("college", targets=("Engineering",)))
    policy = _policy((broad, narrow), (("eligibility.age", "narrow", "broad"),))
    resolution = resolve_rule_precedence(
        (narrow, broad), (_decision(narrow), _decision(broad)), policy
    )
    assert load_rule_resolution_bytes(canonical_rule_resolution_bytes(resolution)) == resolution
    assert (
        load_rule_precedence_policy_bytes(canonical_rule_precedence_policy_bytes(policy)) == policy
    )
    with pytest.raises(ValidationError):
        resolution.entries[0].rule_id = "changed"  # type: ignore[misc]


def test_loaded_resolution_rejects_tampered_entry_relationships() -> None:
    broad = _rule("broad", _scope("global"))
    narrow = _rule("narrow", _scope("college", targets=("Engineering",)))
    resolution = resolve_rule_precedence(
        (broad, narrow),
        (_decision(broad), _decision(narrow)),
        _policy((broad, narrow), (("eligibility.age", "narrow", "broad"),)),
    )
    payload = resolution.model_dump(mode="json")
    overridden = next(item for item in payload["entries"] if item["rule_id"] == "broad")
    overridden["activated_override"]["subject_key"] = "different"
    with pytest.raises(RuleResolutionError):
        load_rule_resolution_bytes(json.dumps(payload).encode())

    for tampered_overrider in ("ghost", "broad"):
        payload = resolution.model_dump(mode="json")
        overridden = next(item for item in payload["entries"] if item["rule_id"] == "broad")
        overridden["activated_override"]["overrider_rule_id"] = tampered_overrider
        with pytest.raises(RuleResolutionError):
            load_rule_resolution_bytes(json.dumps(payload).encode())

    payload = resolution.model_dump(mode="json")
    payload["entries"][0]["official_evidence"][0]["document_id"] = "different"
    with pytest.raises(RuleResolutionError):
        load_rule_resolution_bytes(json.dumps(payload).encode())

    payload = resolution.model_dump(mode="json")
    confirmed = next(item for item in payload["entries"] if item["rule_id"] == "narrow")
    confirmed["official_evidence"] = []
    with pytest.raises(RuleResolutionError):
        load_rule_resolution_bytes(json.dumps(payload).encode())


@pytest.mark.parametrize("overrider_status", ["needs_information", "not_applicable"])
def test_loaded_resolution_rejects_nonconfirmed_overrider(overrider_status: str) -> None:
    broad = _rule("broad", _scope("global"))
    narrow = _rule("narrow", _scope("college", targets=("Engineering",)))
    resolution = resolve_rule_precedence(
        (broad, narrow),
        (_decision(broad), _decision(narrow)),
        _policy((broad, narrow), (("eligibility.age", "narrow", "broad"),)),
    )
    payload = resolution.model_dump(mode="json")
    narrow_entry = next(item for item in payload["entries"] if item["rule_id"] == "narrow")
    narrow_entry["original_status"] = overrider_status
    narrow_entry["disposition"] = (
        "pending" if overrider_status == "needs_information" else "not_applicable"
    )
    payload["active_rule_ids"] = []
    if overrider_status == "needs_information":
        payload["pending_rule_ids"] = ["narrow"]
    else:
        payload["not_applicable_rule_ids"] = ["narrow"]
    with pytest.raises(RuleResolutionError):
        load_rule_resolution_bytes(json.dumps(payload).encode())


@pytest.mark.parametrize(
    "payload",
    [b"not-json", b'{"schema_version":"2.0"}', b'{"schema_version":"1.0","x":NaN}'],
)
def test_loaders_reject_malformed_or_unsupported_bytes_without_echoing_secrets(
    payload: bytes,
) -> None:
    with pytest.raises(RuleResolutionError) as exc_info:
        load_rule_precedence_policy_bytes(payload)
    assert "secret" not in str(exc_info.value)


def test_extra_fields_and_constructed_models_fail_without_echoing_planted_secrets() -> None:
    broad = _rule("broad", _scope("global"))
    narrow = _rule("narrow", _scope("college", targets=("Engineering",)))
    policy = _policy((broad, narrow), (("eligibility.age", "narrow", "broad"),))
    payload = policy.model_dump(mode="json")
    payload["planted_secret"] = "profile-secret-value"
    with pytest.raises(RuleResolutionError) as exc_info:
        load_rule_precedence_policy_bytes(json.dumps(payload).encode())
    assert "profile-secret-value" not in str(exc_info.value)

    copied = policy.model_copy(update={"policy_id": " path-secret-value "})
    with pytest.raises(RuleResolutionError) as exc_info:
        resolve_rule_precedence((broad, narrow), (_decision(broad), _decision(narrow)), copied)
    assert "path-secret-value" not in str(exc_info.value)


def test_resolution_does_not_load_embeddings_or_access_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "socket", deny_network)
    broad = _rule("broad", _scope("global"))
    narrow = _rule("narrow", _scope("college", targets=("Engineering",)))
    resolution = resolve_rule_precedence(
        (broad, narrow),
        (_decision(broad), _decision(narrow)),
        _policy((broad, narrow), (("eligibility.age", "narrow", "broad"),)),
    )
    assert resolution.overridden_rule_ids == ("broad",)
    assert "sentence_transformers" not in sys.modules
    assert "openai" not in sys.modules


def test_path_loader_rejects_symlinks(tmp_path: Path) -> None:
    broad = _rule("broad", _scope("global"))
    narrow = _rule("narrow", _scope("college", targets=("Engineering",)))
    target = tmp_path / "policy.json"
    target.write_bytes(
        canonical_rule_precedence_policy_bytes(
            _policy((broad, narrow), (("eligibility.age", "narrow", "broad"),))
        )
    )
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(RuleResolutionError, match="unavailable or unsafe"):
        load_rule_precedence_policy(link)


def test_reviewed_fixture_characterizes_real_specificity_without_inventing_override() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    synthetic = fixture["synthetic_contract"]
    assert len(synthetic["activation_truth_table"]) == 5
    assert {case["activated"] for case in synthetic["activation_truth_table"]} == {False, True}
    assert len(synthetic["invalid_edges"]) == 9
    real = fixture["real_kb_characterization"]
    assert real["defensible_override_found"] is False
    assert real["scope_inventory"] == {"department": 126, "global": 2, "unknown": 170}
    assert real["candidate_pair"][0]["scope_type"] == "global"
    assert real["candidate_pair"][1]["scope_type"] == "department"
    assert real["candidate_pair"][0]["source_pages"] == [10]
    assert real["candidate_pair"][1]["source_pages"] == [7]
    assert "not semantically" in real["review_conclusion"]
