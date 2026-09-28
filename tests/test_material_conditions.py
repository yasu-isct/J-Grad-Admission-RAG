from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from jgrad_admission_rag.reasoning.condition_core import combine, compare
from jgrad_admission_rag.reasoning.material_condition_cli import main
from jgrad_admission_rag.reasoning.material_conditions import (
    MaterialConditionError,
    PolicyTrust,
    canonical_request_bytes,
    evaluate,
    load_policy,
    load_preview,
    load_request,
)
from jgrad_admission_rag.reviewed_source_evidence import canonical_json_bytes, parse_json


DOCS = Path(__file__).resolve().parents[1] / "docs" / "onboarding"


@pytest.fixture
def source():
    raw = (DOCS / "material-condition-policy-v1.json").read_bytes()
    trust = PolicyTrust.model_validate(
        parse_json((DOCS / "material-condition-trust-v1.json").read_bytes())
    )
    policy = load_policy(raw, trust)
    requests = [
        case["request"]
        for case in parse_json((DOCS / "material-condition-examples-v1.json").read_bytes())["cases"]
    ]
    return raw, trust, policy, requests


@pytest.mark.parametrize(
    "employed,retain,expected",
    [
        (True, True, "matched"),
        (True, False, "not_matched"),
        (False, True, "not_matched"),
        (False, False, "not_matched"),
        (True, None, "needs_information"),
        (None, True, "needs_information"),
        (False, None, "not_matched"),
        (None, False, "not_matched"),
        (None, None, "needs_information"),
    ],
)
def test_employment_nine_cell_matrix(source, employed, retain, expected):
    policy_raw, trust, policy, requests = source
    payload = deepcopy(requests[0])
    payload["employment"] = dict(
        currently_employed_in_organization=employed, retain_employment_at_enrollment=retain
    )
    request = load_request(canonical_json_bytes(payload))
    preview = evaluate(policy, request, trust.policy_sha256)
    assert preview.status == "evaluated"
    assert [entry.condition_status for entry in preview.entries] == ["matched", "matched", expected]
    work = preview.entries[2]
    assert work.missing_fields == tuple(
        path
        for path, value in (
            ("employment.currently_employed_in_organization", employed),
            ("employment.retain_employment_at_enrollment", retain),
        )
        if value is None
    )
    encoded = canonical_json_bytes(preview.model_dump(mode="json"))
    assert b"required" not in encoded and b"official_evidence" not in encoded
    assert (
        load_preview(
            encoded, policy_raw=policy_raw, trust=trust, request_raw=canonical_json_bytes(payload)
        )
        == preview
    )


def test_null_object_missing_keys_and_input_order_normalize(source):
    _, trust, policy, requests = source
    payload = deepcopy(requests[0])
    payload["employment"] = None
    first = load_request(canonical_json_bytes(payload))
    payload["employment"] = {}
    second = load_request(canonical_json_bytes(payload))
    assert canonical_request_bytes(first) == canonical_request_bytes(second)
    assert evaluate(policy, first, trust.policy_sha256) == evaluate(
        policy, second, trust.policy_sha256
    )
    assert (
        evaluate(policy, first, trust.policy_sha256).entries[2].condition_status
        == "needs_information"
    )
    assert canonical_request_bytes(first) == canonical_request_bytes(
        load_request(canonical_json_bytes(dict(reversed(list(payload.items())))))
    )


def test_three_reviewed_synthetic_cases_match_versioned_examples(source):
    _, trust, policy, _ = source
    cases = parse_json((DOCS / "material-condition-examples-v1.json").read_bytes())["cases"]
    for case in cases:
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / ("material_condition_" + case["case_id"].replace("-", "_") + ".json")
        )
        assert fixture.read_bytes() == canonical_json_bytes(case["request"])
        request = load_request(fixture.read_bytes())
        preview = evaluate(policy, request, trust.policy_sha256)
        assert [entry.condition_status for entry in preview.entries[:2]] == (
            case["expected_other_condition_statuses"]
        )
        assert preview.entries[2].condition_status == case["expected_work_plan_condition"]
        assert all("required" not in entry.model_dump_json() for entry in preview.entries)


@pytest.mark.parametrize(
    "path",
    [
        "target_id",
        "institution_id",
        "organization_id",
        "program_id",
        "degree_level",
        "admission_cycle",
        "selection_route_id",
        "examination_schedule_id",
        "intake.year",
        "intake.month",
    ],
)
def test_all_target_dimensions_fail_before_conditions(source, path):
    _, trust, policy, requests = source
    payload = deepcopy(requests[0])
    node = payload["target"]
    parts = path.split(".")
    for part in parts[:-1]:
        node = node[part]
    key = parts[-1]
    node[key] = node[key] + 1 if type(node[key]) is int else "different"
    preview = evaluate(policy, load_request(canonical_json_bytes(payload)), trust.policy_sha256)
    assert preview.status == "not_covered" and preview.entries == ()


@pytest.mark.parametrize(
    "field,value",
    [
        ("requested_degree_level", "doctorate"),
        ("intake_year", 2026),
        ("intake_month", 10),
        ("graduate_school_or_college", "OTHER"),
        ("department_or_program", "OTHER"),
        ("application_route", "OTHER"),
    ],
)
def test_known_profile_target_conflict_rejects_entries(source, field, value):
    _, trust, policy, requests = source
    payload = deepcopy(requests[0])
    payload["applicant_profile"]["target_application"][field] = value
    preview = evaluate(policy, load_request(canonical_json_bytes(payload)), trust.policy_sha256)
    assert preview.status == "target_mismatch" and preview.entries == ()
    assert preview.conflict_fields == (field,)


def test_multiple_conflicts_are_sorted_and_blank_profile_is_not_fabricated(source):
    _, trust, policy, requests = source
    payload = deepcopy(requests[0])
    fields = payload["applicant_profile"]["target_application"]
    fields["application_route"] = "OTHER"
    fields["intake_year"] = 2026
    mismatch = evaluate(policy, load_request(canonical_json_bytes(payload)), trust.policy_sha256)
    assert mismatch.conflict_fields == ("application_route", "intake_year")
    for field in fields:
        fields[field] = None
    assert (
        evaluate(policy, load_request(canonical_json_bytes(payload)), trust.policy_sha256).status
        == "evaluated"
    )


@pytest.mark.parametrize("bad", ["true", "false", 0, 1])
def test_employment_must_be_strict_bool_or_null(source, bad):
    payload = deepcopy(source[3][0])
    payload["employment"]["currently_employed_in_organization"] = bad
    with pytest.raises(MaterialConditionError):
        load_request(canonical_json_bytes(payload))


def test_missing_explicit_target_is_invalid_request(source):
    payload = deepcopy(source[3][0])
    del payload["target"]["intake"]
    with pytest.raises(MaterialConditionError):
        load_request(canonical_json_bytes(payload))


def test_policy_pin_duplicate_and_forged_result_fail(source):
    raw, trust, policy, requests = source
    with pytest.raises(MaterialConditionError):
        load_policy(raw + b" ", trust)
    with pytest.raises(MaterialConditionError):
        load_request(b'{"schema_version":"1.0","schema_version":"1.0"}')
    request = load_request(canonical_json_bytes(requests[0]))
    preview = evaluate(policy, request, trust.policy_sha256)
    forged = parse_json(canonical_json_bytes(preview.model_dump(mode="json")))
    forged["entries"][2]["condition_status"] = "not_matched"
    with pytest.raises(MaterialConditionError):
        load_preview(
            canonical_json_bytes(forged),
            policy_raw=raw,
            trust=trust,
            request_raw=canonical_json_bytes(requests[0]),
        )
    forged = parse_json(canonical_json_bytes(preview.model_dump(mode="json")))
    forged["request_sha256"] = "0" * 64
    with pytest.raises(MaterialConditionError):
        load_preview(
            canonical_json_bytes(forged),
            policy_raw=raw,
            trust=trust,
            request_raw=canonical_json_bytes(requests[0]),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "duplicate_rule",
        "duplicate_predicate",
        "contradiction",
        "wrong_document",
        "wrong_fact",
        "runtime_verified",
        "bad_alias",
        "bad_operator",
        "bad_expected",
        "bool_page",
    ],
)
def test_policy_graph_rejects_unsafe_mutations(source, mutation):
    raw, trust, _, _ = source
    payload = parse_json(raw)
    if mutation == "extra":
        payload["new_unreviewed_field"] = True
    elif mutation == "duplicate_rule":
        payload["rules"].append(deepcopy(payload["rules"][0]))
    elif mutation == "duplicate_predicate":
        payload["rules"][2]["predicates"].append(deepcopy(payload["rules"][2]["predicates"][0]))
    elif mutation == "contradiction":
        pred = deepcopy(payload["rules"][2]["predicates"][0])
        pred["expected_value"] = False
        payload["rules"][2]["predicates"].append(pred)
    elif mutation == "wrong_document":
        payload["rules"][0]["required_context_records"][0]["required_bindings"][0][
            "document_id"
        ] = "wrong"
    elif mutation == "wrong_fact":
        payload["rules"][0]["required_context_records"][0]["required_bindings"][0]["fact_id"] = (
            "fact:forged"
        )
    elif mutation == "runtime_verified":
        payload["evidence_prerequisites"]["runtime_evidence_verified"] = True
    elif mutation == "bad_alias":
        payload["profile_target_aliases"]["application_route"].append("general-ordinary")
    elif mutation == "bad_operator":
        payload["rules"][2]["predicates"][0]["operator"] = "contains"
    elif mutation == "bad_expected":
        payload["rules"][2]["predicates"][0]["expected_value"] = 1
    elif mutation == "bool_page":
        payload["rules"][0]["required_context_records"][0]["required_bindings"][0][
            "source_pages"
        ] = [True]
    changed = canonical_json_bytes(payload)
    synthetic_trust = trust.model_copy(update={"policy_sha256": sha256(changed).hexdigest()})
    with pytest.raises(MaterialConditionError):
        load_policy(changed, synthetic_trust)


@pytest.mark.parametrize(
    "mutation",
    ["same", "source_pages", "authoritative_fact_text_sha256", "record_revision", "fact_id"],
)
def test_reused_context_record_requires_identical_complete_bindings(source, mutation):
    raw, trust, _, _ = source
    payload = parse_json(raw)
    duplicate = deepcopy(payload["rules"][0]["required_context_records"][0])
    binding = duplicate["required_bindings"][0]
    if mutation == "source_pages":
        binding["source_pages"] = [999]
    elif mutation == "authoritative_fact_text_sha256":
        binding["authoritative_fact_text_sha256"] = "0" * 64
    elif mutation == "record_revision":
        duplicate["record_revision"] += 1
        binding["fact_id"] = binding["fact_id"].replace(":r1:", ":r2:")
    elif mutation == "fact_id":
        binding["fact_id"] = binding["fact_id"].replace(":E01-1", ":E01-2")
    payload["rules"][1]["required_context_records"].append(duplicate)
    changed = canonical_json_bytes(payload)
    synthetic_trust = trust.model_copy(update={"policy_sha256": sha256(changed).hexdigest()})
    if mutation == "same":
        assert (
            load_policy(changed, synthetic_trust).rules[1].required_context_records[-1].record_id
            == (duplicate["record_id"])
        )
    else:
        with pytest.raises(MaterialConditionError):
            load_policy(changed, synthetic_trust)


def test_other_school_uses_same_policy_algorithm_and_is_isolated(source):
    raw, trust, _, requests = source
    payload = parse_json(raw)
    payload["policy_id"] = "second-school-material-policy"
    payload["target"]["institution_id"] = "second"
    payload["target"]["organization_id"] = "second-grad"
    payload["target"]["program_id"] = "second-program"
    payload["target"]["target_id"] = "second-target"
    payload["profile_target_aliases"]["graduate_school_or_college"] = ["second-grad"]
    payload["profile_target_aliases"]["department_or_program"] = ["second-program"]
    for doc in payload["evidence_prerequisites"]["documents"]:
        doc["identity"]["institution_id"] = "second"
    synthetic_raw = canonical_json_bytes(payload)
    synthetic_trust = trust.model_copy(
        update={
            "policy_id": payload["policy_id"],
            "policy_sha256": sha256(synthetic_raw).hexdigest(),
        }
    )
    policy = load_policy(synthetic_raw, synthetic_trust)
    original = load_request(canonical_json_bytes(requests[0]))
    assert evaluate(policy, original, synthetic_trust.policy_sha256).status == "not_covered"
    request_payload = deepcopy(requests[0])
    request_payload["target"] = payload["target"]
    request_payload["applicant_profile"]["target_application"].update(
        graduate_school_or_college="second-grad", department_or_program="second-program"
    )
    request = load_request(canonical_json_bytes(request_payload))
    assert (
        evaluate(policy, request, synthetic_trust.policy_sha256).entries[2].condition_status
        == "matched"
    )


def test_core_supports_legacy_operators_and_empty_tri_state():
    samples = [
        ("equals", 3, 3, True),
        ("not_equals", 3, 4, True),
        ("contains", ("A", "B"), "B", True),
        ("minimum", 4, 3, True),
        ("maximum", 2, 3, True),
        ("on_or_before", 2, 3, True),
        ("on_or_after", 4, 3, True),
        ("is_empty", (), None, True),
        ("is_non_empty", (1,), None, True),
    ]
    for operator, value, expected, result in samples:
        assert compare(value, operator, expected) is result
    with pytest.raises(ValueError):
        compare(1, "unsupported", 1)
    assert combine("all", ()) is True and combine("any", ()) is False
    assert combine("all", (False, None)) is False
    assert combine("any", (False, None)) is None
    with pytest.raises(ValueError):
        combine("xor", (True, False))


def test_cli_is_atomic_on_invalid_batch(source, tmp_path, capsys):
    _, _, _, requests = source
    valid = tmp_path / "valid.json"
    bad = tmp_path / "bad.json"
    valid.write_bytes(canonical_json_bytes(requests[0]))
    bad.write_bytes(b"{}")
    result = main(
        [
            "--policy",
            str(DOCS / "material-condition-policy-v1.json"),
            "--trust",
            str(DOCS / "material-condition-trust-v1.json"),
            "--request",
            str(valid),
            "--request",
            str(bad),
        ]
    )
    assert result == 2 and capsys.readouterr().out == ""
