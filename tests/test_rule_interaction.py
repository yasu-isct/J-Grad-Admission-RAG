from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.reasoning.applicability import (
    ApplicabilityStatus,
    EvidenceRole,
    OfficialEvidenceReference,
    RuleScope,
)
from jgrad_admission_rag.reasoning.rule_interaction import (
    InteractionCertainty,
    InteractionRelationship,
    InteractionWarningKind,
    RuleInteraction,
    RuleInteractionError,
    RuleInteractionPolicy,
    analyze_rule_interactions,
    canonical_rule_interaction_policy_bytes,
    canonical_rule_interaction_report_bytes,
    load_rule_interaction_policy,
    load_rule_interaction_policy_bytes,
    load_rule_interaction_report_bytes,
)
from jgrad_admission_rag.reasoning.rule_resolution import (
    ActivatedOverride,
    ResolutionDisposition,
    RuleResolution,
    RuleResolutionEntry,
)

KB_HASH = "a" * 64
PDF_HASH = "b" * 64
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "rule_interaction_scenarios_v1.json"


def _scope(kind: str = "global", target: str | None = None) -> RuleScope:
    return RuleScope(
        scope_type=kind,  # type: ignore[arg-type]
        scope_targets=(target,) if target else (),
        parent_college=None,
    )


def _entry(
    rule_id: str,
    subject: str,
    disposition: ResolutionDisposition = ResolutionDisposition.ACTIVE,
    *,
    scope: RuleScope | None = None,
    fact_id: str | None = None,
) -> RuleResolutionEntry:
    status = {
        ResolutionDisposition.ACTIVE: ApplicabilityStatus.CONFIRMED,
        ResolutionDisposition.PENDING: ApplicabilityStatus.NEEDS_INFORMATION,
        ResolutionDisposition.NOT_APPLICABLE: ApplicabilityStatus.NOT_APPLICABLE,
    }[disposition]
    return RuleResolutionEntry(
        rule_id=rule_id,
        subject_key=subject,
        original_status=status,
        scope=scope or _scope(),
        disposition=disposition,
        official_evidence=(
            OfficialEvidenceReference(
                document_id="doc",
                fact_id=fact_id or f"fact:{rule_id}",
                source_pages=(len(rule_id),),
                role=EvidenceRole.PRIMARY,
            ),
        ),
    )


def _resolution(*entries: RuleResolutionEntry) -> RuleResolution:
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
        policy_id="precedence-policy",
        document_id="doc",
        source_kb_sha256=KB_HASH,
        source_pdf_sha256=PDF_HASH,
        entries=canonical,
        active_rule_ids=tuple(
            sorted(
                item.rule_id
                for item in canonical
                if item.disposition is ResolutionDisposition.ACTIVE
            )
        ),
        overridden_rule_ids=tuple(
            sorted(
                item.rule_id
                for item in canonical
                if item.disposition is ResolutionDisposition.OVERRIDDEN
            )
        ),
        pending_rule_ids=tuple(
            sorted(
                item.rule_id
                for item in canonical
                if item.disposition is ResolutionDisposition.PENDING
            )
        ),
        not_applicable_rule_ids=tuple(
            sorted(
                item.rule_id
                for item in canonical
                if item.disposition is ResolutionDisposition.NOT_APPLICABLE
            )
        ),
    )


def _policy(
    relationship: InteractionRelationship | None,
    *,
    rule_ids: tuple[str, str] = ("left", "right"),
    subject: str = "eligibility.route",
) -> RuleInteractionPolicy:
    interactions = ()
    if relationship is not None:
        interactions = (
            RuleInteraction(
                subject_key=subject,
                rule_ids=rule_ids,
                relationship=relationship,
                rationale="Reviewed pair relationship.",
            ),
        )
    return RuleInteractionPolicy(policy_id="interaction-policy", interactions=interactions)


@pytest.mark.parametrize(
    ("relationship", "left_disposition", "right_disposition", "kind", "certainty"),
    [
        ("conflict", "active", "active", "conflict", "confirmed"),
        ("conflict", "active", "pending", "conflict", "potential"),
        ("conflict", "pending", "pending", "conflict", "potential"),
        ("ambiguous", "active", "active", "ambiguity", "confirmed"),
        ("ambiguous", "active", "pending", "ambiguity", "potential"),
        ("ambiguous", "pending", "pending", "ambiguity", "potential"),
    ],
)
def test_reviewed_conflict_and_ambiguity_warning_matrix(
    relationship: str,
    left_disposition: str,
    right_disposition: str,
    kind: str,
    certainty: str,
) -> None:
    left = _entry("left", "eligibility.route", ResolutionDisposition(left_disposition))
    right = _entry("right", "eligibility.route", ResolutionDisposition(right_disposition))
    report = analyze_rule_interactions(
        _resolution(left, right), _policy(InteractionRelationship(relationship))
    )

    assert report.analysis_complete is True
    assert report.live_same_subject_pair_count == 1
    assert report.reviewed_live_pair_count == 1
    assert report.unreviewed_live_pair_count == 0
    assert len(report.warnings) == 1
    warning = report.warnings[0]
    assert warning.kind is InteractionWarningKind(kind)
    assert warning.certainty is InteractionCertainty(certainty)
    assert warning.rule_ids == ("left", "right")
    assert tuple(item.official_evidence for item in warning.endpoints) == (
        left.official_evidence,
        right.official_evidence,
    )


def test_compatible_pair_is_covered_without_warning() -> None:
    resolution = _resolution(
        _entry("left", "documents"),
        _entry("right", "documents"),
    )
    report = analyze_rule_interactions(
        resolution, _policy(InteractionRelationship.COMPATIBLE, subject="documents")
    )
    assert report.warnings == ()
    assert len(report.reviewed_compatible_pair_ids) == 1
    assert report.analysis_complete is True


def test_missing_relationship_emits_one_unreviewed_warning() -> None:
    report = analyze_rule_interactions(
        _resolution(
            _entry("left", "eligibility.route"),
            _entry("right", "eligibility.route"),
        ),
        _policy(None),
    )
    assert report.analysis_complete is False
    assert report.reviewed_live_pair_count == 0
    assert report.unreviewed_live_pair_count == 1
    assert len(report.warnings) == 1
    assert report.warnings[0].kind is InteractionWarningKind.UNREVIEWED_INTERACTION
    assert report.warnings[0].certainty is InteractionCertainty.CONFIRMED


def test_three_live_rules_cover_every_pair_exactly_once() -> None:
    resolution = _resolution(
        _entry("alpha", "eligibility.route"),
        _entry("beta", "eligibility.route"),
        _entry("gamma", "eligibility.route", ResolutionDisposition.PENDING),
    )
    policy = RuleInteractionPolicy(
        policy_id="interaction-policy",
        interactions=(
            RuleInteraction(
                subject_key="eligibility.route",
                rule_ids=("alpha", "beta"),
                relationship=InteractionRelationship.COMPATIBLE,
                rationale="Reviewed compatible pair.",
            ),
            RuleInteraction(
                subject_key="eligibility.route",
                rule_ids=("alpha", "gamma"),
                relationship=InteractionRelationship.CONFLICT,
                rationale="Reviewed conflict pair.",
            ),
        ),
    )
    report = analyze_rule_interactions(resolution, policy)
    assert report.live_same_subject_pair_count == 3
    assert report.reviewed_live_pair_count == 2
    assert report.unreviewed_live_pair_count == 1
    assert len(report.reviewed_compatible_pair_ids) == 1
    assert [(item.kind.value, item.certainty.value) for item in report.warnings] == [
        ("conflict", "potential"),
        ("unreviewed_interaction", "potential"),
    ]
    assert report.analysis_complete is False


def test_different_subjects_never_form_a_pair() -> None:
    report = analyze_rule_interactions(
        _resolution(_entry("left", "documents"), _entry("right", "fees")),
        _policy(None),
    )
    assert report.live_same_subject_pair_count == 0
    assert report.warnings == ()
    assert report.analysis_complete is True


@pytest.mark.parametrize(
    "inactive_disposition",
    [ResolutionDisposition.NOT_APPLICABLE, ResolutionDisposition.OVERRIDDEN],
)
def test_inactive_endpoint_policy_is_reported_without_warning(
    inactive_disposition: ResolutionDisposition,
) -> None:
    active = _entry("left", "eligibility.route")
    if inactive_disposition is ResolutionDisposition.NOT_APPLICABLE:
        inactive = _entry("right", "eligibility.route", inactive_disposition)
        resolution = _resolution(active, inactive)
    else:
        narrower = _entry(
            "left",
            "eligibility.route",
            scope=_scope("college", "Engineering"),
        )
        inactive = RuleResolutionEntry(
            rule_id="right",
            subject_key="eligibility.route",
            original_status=ApplicabilityStatus.CONFIRMED,
            scope=_scope(),
            disposition=ResolutionDisposition.OVERRIDDEN,
            activated_override=ActivatedOverride(
                subject_key="eligibility.route",
                overrider_rule_id="left",
                rationale="Reviewed direct replacement.",
            ),
            official_evidence=_entry("right", "eligibility.route").official_evidence,
        )
        resolution = _resolution(narrower, inactive)
    report = analyze_rule_interactions(resolution, _policy(InteractionRelationship.CONFLICT))
    assert report.warnings == ()
    assert len(report.inactive_policy_pair_ids) == 1
    assert report.live_same_subject_pair_count == 0
    assert report.analysis_complete is True


def test_reversed_pair_input_produces_identical_canonical_output() -> None:
    resolution = _resolution(
        _entry("left", "eligibility.route"),
        _entry("right", "eligibility.route"),
    )
    forward = _policy(InteractionRelationship.CONFLICT)
    reversed_policy = _policy(InteractionRelationship.CONFLICT, rule_ids=("right", "left"))
    assert reversed_policy == forward
    assert canonical_rule_interaction_report_bytes(
        analyze_rule_interactions(resolution, reversed_policy)
    ) == canonical_rule_interaction_report_bytes(analyze_rule_interactions(resolution, forward))


def test_policy_rejects_self_duplicate_and_multiple_relationship_pairs() -> None:
    with pytest.raises(ValidationError):
        RuleInteraction(
            subject_key="subject",
            rule_ids=("same", "same"),
            relationship=InteractionRelationship.CONFLICT,
            rationale="Reviewed.",
        )

    base = RuleInteraction(
        subject_key="subject",
        rule_ids=("left", "right"),
        relationship=InteractionRelationship.CONFLICT,
        rationale="Reviewed.",
    )
    reversed_duplicate = RuleInteraction(
        subject_key="subject",
        rule_ids=("right", "left"),
        relationship=InteractionRelationship.AMBIGUOUS,
        rationale="Reviewed differently.",
    )
    for interactions in ((base, base), (base, reversed_duplicate)):
        with pytest.raises(ValidationError):
            RuleInteractionPolicy(policy_id="policy", interactions=interactions)


@pytest.mark.parametrize("failure", ["ghost", "cross-subject"])
def test_policy_endpoints_must_exist_and_share_subject(failure: str) -> None:
    resolution = _resolution(
        _entry("left", "eligibility.route"),
        _entry("right", "other" if failure == "cross-subject" else "eligibility.route"),
    )
    rule_ids = ("ghost", "left") if failure == "ghost" else ("left", "right")
    policy = _policy(InteractionRelationship.CONFLICT, rule_ids=rule_ids)
    with pytest.raises(RuleInteractionError, match="invalid or inconsistent"):
        analyze_rule_interactions(resolution, policy)


def test_policy_and_report_are_immutable_and_round_trip_canonically() -> None:
    resolution = _resolution(
        _entry("left", "eligibility.route"),
        _entry("right", "eligibility.route"),
    )
    policy = _policy(InteractionRelationship.AMBIGUOUS)
    report = analyze_rule_interactions(resolution, policy)
    assert (
        load_rule_interaction_policy_bytes(canonical_rule_interaction_policy_bytes(policy))
        == policy
    )
    assert (
        load_rule_interaction_report_bytes(canonical_rule_interaction_report_bytes(report))
        == report
    )
    with pytest.raises(ValidationError):
        report.policy_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "payload",
    [b"not-json", b'{"schema_version":"2.0"}', b'{"schema_version":"1.0","x":NaN}'],
)
def test_policy_loader_rejects_malformed_or_wrong_version(payload: bytes) -> None:
    with pytest.raises(RuleInteractionError):
        load_rule_interaction_policy_bytes(payload)


def test_extra_fields_and_constructed_inputs_fail_without_secret_echo() -> None:
    policy = _policy(InteractionRelationship.CONFLICT)
    payload = policy.model_dump(mode="json")
    payload["profile_secret"] = "profile-secret-value"
    with pytest.raises(RuleInteractionError) as exc_info:
        load_rule_interaction_policy_bytes(json.dumps(payload).encode())
    assert "profile-secret-value" not in str(exc_info.value)

    copied = policy.model_copy(update={"policy_id": " query-secret-value "})
    resolution = _resolution(
        _entry("left", "eligibility.route"),
        _entry("right", "eligibility.route"),
    )
    with pytest.raises(RuleInteractionError) as exc_info:
        analyze_rule_interactions(resolution, copied)
    assert "query-secret-value" not in str(exc_info.value)

    copied_resolution = resolution.model_copy(update={"active_rule_ids": ("ghost",)})
    with pytest.raises(RuleInteractionError, match="invalid or unsupported"):
        analyze_rule_interactions(copied_resolution, policy)


def test_path_loader_rejects_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "policy.json"
    target.write_bytes(
        canonical_rule_interaction_policy_bytes(_policy(InteractionRelationship.COMPATIBLE))
    )
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(RuleInteractionError, match="unavailable or unsafe"):
        load_rule_interaction_policy(link)


def _report_payload() -> dict[str, object]:
    report = analyze_rule_interactions(
        _resolution(
            _entry("left", "eligibility.route"),
            _entry("right", "eligibility.route"),
        ),
        _policy(InteractionRelationship.CONFLICT),
    )
    return report.model_dump(mode="json")


@pytest.mark.parametrize(
    "tamper",
    [
        "missing-warning",
        "duplicate-warning",
        "certainty",
        "kind",
        "status",
        "disposition",
        "ghost-rule",
        "evidence-loss",
        "evidence-change",
        "identity",
        "duplicate-reviewed-relation",
        "count",
        "count-type",
        "completeness",
        "completeness-type",
    ],
)
def test_report_loader_rejects_tampered_analysis(tamper: str) -> None:
    payload = _report_payload()
    warnings = payload["warnings"]
    assert isinstance(warnings, list)
    warning = warnings[0]
    assert isinstance(warning, dict)
    endpoints = warning["endpoints"]
    assert isinstance(endpoints, list)
    endpoint = endpoints[0]
    assert isinstance(endpoint, dict)

    if tamper == "missing-warning":
        payload["warnings"] = []
    elif tamper == "duplicate-warning":
        warnings.append(dict(warning))
    elif tamper == "certainty":
        warning["certainty"] = "potential"
    elif tamper == "kind":
        warning["kind"] = "ambiguity"
    elif tamper == "status":
        endpoint["original_status"] = "not_applicable"
    elif tamper == "disposition":
        endpoint["disposition"] = "pending"
    elif tamper == "ghost-rule":
        warning["rule_ids"][0] = "ghost"
    elif tamper == "evidence-loss":
        endpoint["official_evidence"] = []
    elif tamper == "evidence-change":
        endpoint["official_evidence"][0]["source_pages"] = [999]
    elif tamper == "identity":
        payload["document_id"] = "different"
    elif tamper == "duplicate-reviewed-relation":
        payload["reviewed_interactions"].append(payload["reviewed_interactions"][0])
    elif tamper == "count":
        payload["reviewed_live_pair_count"] = 2
    elif tamper == "count-type":
        payload["reviewed_live_pair_count"] = "1"
    elif tamper == "completeness":
        payload["analysis_complete"] = False
    else:
        payload["analysis_complete"] = 1

    with pytest.raises(RuleInteractionError):
        load_rule_interaction_report_bytes(json.dumps(payload).encode())


def test_zero_policy_report_rejects_false_complete_and_lost_unreviewed_pair() -> None:
    report = analyze_rule_interactions(
        _resolution(
            _entry("left", "eligibility.route"),
            _entry("right", "eligibility.route"),
        ),
        _policy(None),
    )
    payload = report.model_dump(mode="json")
    payload["analysis_complete"] = True
    payload["warnings"] = []
    payload["unreviewed_live_pair_count"] = 0
    with pytest.raises(RuleInteractionError):
        load_rule_interaction_report_bytes(json.dumps(payload).encode())


def test_analysis_does_not_load_embeddings_or_access_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "socket", deny_network)
    report = analyze_rule_interactions(
        _resolution(
            _entry("left", "eligibility.route"),
            _entry("right", "eligibility.route"),
        ),
        _policy(InteractionRelationship.COMPATIBLE),
    )
    assert report.analysis_complete is True
    assert "sentence_transformers" not in sys.modules
    assert "openai" not in sys.modules


def test_reviewed_fixture_characterizes_real_pair_without_inventing_semantics() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert {case["relationship"] for case in fixture["synthetic_cases"]} == {
        "ambiguous",
        "compatible",
        "conflict",
        "unreviewed",
    }
    real = fixture["real_kb_characterization"]
    assert real["candidate_pair"][0]["fact_id"] == "fact:00088"
    assert real["candidate_pair"][1]["fact_id"] == "fact:00089"
    assert all(item["source_pages"] == [10] for item in real["candidate_pair"])
    assert real["reviewed_relationship"] == "unreviewed"
    assert real["defensible_conflict_or_ambiguity_found"] is False
