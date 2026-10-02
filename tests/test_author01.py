"""AUTHOR-01 uses pinned text and synthetic PDFs; no accepted asset is opened."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pymupdf
import pytest

from jgrad_admission_rag.reviewed_fragment_import import (
    Candidate,
    ImportTrust,
    Lineage,
    load_inputs,
    map_candidate,
)
from jgrad_admission_rag.reviewed_source_evidence import (
    EvidenceError,
    canonical_json_bytes,
    parse_json,
)
from jgrad_admission_rag.schemas.document_kb import load_document_kb_bytes
from jgrad_admission_rag.reasoning.material_conditions import evaluate, load_request
from jgrad_admission_rag.reasoning.material_slice_report import (
    MaterialSliceError,
    assemble_report,
    load_plan,
    render_markdown,
)
from scripts import author01_generate_configs as generator


DOCS = Path(__file__).resolve().parents[1] / "docs" / "onboarding"
SEED_NAME = "author01-essay-evidence-seed-v2.json"
PLAN_NAMES = (
    "author01-material-slice-report-plan-v2.json",
    "author01-material-slice-report-trust-v2.json",
    "author01-material-condition-policy-v2.json",
    "author01-material-condition-trust-v2.json",
    SEED_NAME,
)


def _digest(raw):
    return sha256(raw).hexdigest()


def _rewrite(payload, replacements):
    if isinstance(payload, dict):
        return {key: _rewrite(value, replacements) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_rewrite(value, replacements) for value in payload]
    return replacements.get(payload, payload) if isinstance(payload, str) else payload


@pytest.fixture(scope="module")
def v2_inputs():
    seed_raw = (DOCS / SEED_NAME).read_bytes()
    config_raw = (DOCS / "author01-reviewed-fragment-import-v2.json").read_bytes()
    trust = ImportTrust.model_validate(
        parse_json((DOCS / "author01-reviewed-fragment-import-trust-v2.json").read_bytes())
    )
    raws = (
        seed_raw,
        (DOCS / "utokyo-gsfs-complex-2027.sources.json").read_bytes(),
        (DOCS / "gsfs-source-set-contract-v0.1.examples.json").read_bytes(),
        config_raw,
    )
    evidence, config = load_inputs(*raws, trust)
    return raws, trust, evidence, config


def test_checked_in_candidate_pins_and_old_three_condition_semantics(v2_inputs):
    raws, _, evidence, config = v2_inputs
    files = map_candidate(evidence, config, *raws[1:])
    plan, policy, _, _, _ = load_plan(*(DOCS.joinpath(name).read_bytes() for name in PLAN_NAMES))
    assert plan.revision == policy.revision == 2
    assert plan.seed_reference.revision == 2 and plan.source_set.revision == 1
    assert {row.relative_path: row.sha256 for row in plan.candidate_reference.files} == {
        name: _digest(raw) for name, raw in files.items()
    }
    assert len(plan.topics) == len(policy.rules) == 4
    old = parse_json((DOCS / "material-condition-policy-v1.json").read_bytes())
    for previous, current in zip(old["rules"], policy.rules[:3], strict=True):
        current = current.model_dump(mode="json")
        for key in (
            "condition_rule_id",
            "topic_id",
            "material_code",
            "stage",
            "mode",
            "predicates",
            "proposed_effect_when_matched",
            "basis_record_ids",
        ):
            assert current[key] == previous[key]
        assert [row["record_id"] for row in current["required_context_records"]] == [
            row["record_id"] for row in previous["required_context_records"]
        ]


def test_reviewed_revision_two_preserves_old_records_relations_and_source_set(v2_inputs):
    raws, _, evidence, _ = v2_inputs
    old = parse_json((DOCS / "gsfs-material-evidence-seed-v1.json").read_bytes())
    new = parse_json(raws[0])
    pin = parse_json((DOCS / "author01-essay-review-pin-v2.json").read_bytes())
    assert _digest(raws[0]) == pin["bundle_sha256"]
    assert new["records"][:8] == old["records"]
    assert new["relations"][:5] == old["relations"]
    assert new["topics"][:3] == old["topics"]
    assert new["source_set"] == old["source_set"]
    assert new["source_manifest"] == old["source_manifest"]
    assert new["target"] == old["target"]
    assert new["revision"] == 2
    assert len(evidence.bundle.records) == 10
    assert len(evidence.bundle.topics) == 4
    assert len(evidence.bundle.relations) == 6
    assert sum(len(row.fragments) for row in evidence.bundle.records[8:]) == 14


def test_v2_pure_mapper_binds_all_37_fragments_without_pdf_io(v2_inputs, monkeypatch):
    raws, _, evidence, config = v2_inputs

    def no_io(*_args, **_kwargs):
        pytest.fail("pure fragment mapping attempted real PDF I/O")

    monkeypatch.setattr("jgrad_admission_rag.reviewed_fragment_import.audit_sources", no_io)
    files = map_candidate(evidence, config, *raws[1:])
    assert files == map_candidate(evidence, config, *raws[1:])
    assert len(files) == 5
    assert sum(map(len, files.values())) < 8 * 1024 * 1024
    candidate = Candidate.model_validate(parse_json(files["candidate.json"]))
    lineage = Lineage.model_validate(parse_json(files["lineage.json"]))
    assert candidate.input_descriptor["bundle_revision"] == 2
    assert candidate.input_descriptor["source_set"]["revision"] == 1
    assert {row.source_id: row.fact_count for row in lineage.documents} == {
        "gsfs-master-2027": 2,
        "complex-guide-2027-revised": 17,
        "complex-master-a-additional": 18,
    }
    assert len(lineage.records) == 10 and len(lineage.relations) == 6
    expected = {
        fragment.fragment_id: (record, fragment)
        for record in evidence.bundle.records
        for fragment in record.fragments
    }
    seen = set()
    for document in candidate.documents:
        kb = load_document_kb_bytes(files[document.relative_path])
        assert not kb.entities and not kb.diagnostics.quality_gate.passed
        assert len(kb.facts) == len(kb.retrieval_units)
        for fact, unit in zip(kb.facts, kb.retrieval_units, strict=True):
            fragment_id = fact.metadata["fragment_id"]
            record, fragment = expected[fragment_id]
            assert fact.text == fragment.text
            assert fact.source_pages == [record.physical_page]
            assert fact.fact_id == (
                f"fact:reviewed:{record.source_id}:{record.record_id}:"
                f"r{record.revision}:{fragment_id}"
            )
            assert fact.scope_type == "unknown" and fact.scope_targets == []
            assert fact.section_path == [] and fact.evidence == []
            assert unit.fact_id == fact.fact_id and unit.source_pages == fact.source_pages
            seen.add(fragment_id)
    assert seen == set(expected) and len(seen) == 37


@pytest.mark.parametrize("fragment_id", ["E09-3", "E09-8", "E10-4", "E10-5"])
def test_missing_required_essay_fragment_rejected_even_with_fresh_pin(v2_inputs, fragment_id):
    raws, trust, _, _ = v2_inputs
    seed = parse_json(raws[0])
    record = next(row for row in seed["records"] if fragment_id in row["required_fragment_ids"])
    record["fragments"] = [row for row in record["fragments"] if row["fragment_id"] != fragment_id]
    changed_seed = canonical_json_bytes(seed)
    config = parse_json(raws[3])
    config["bundle_sha256"] = _digest(changed_seed)
    changed_config = canonical_json_bytes(config)
    changed_trust = trust.model_copy(
        update={
            "bundle_sha256": _digest(changed_seed),
            "import_config_sha256": _digest(changed_config),
        }
    )
    with pytest.raises(EvidenceError):
        load_inputs(changed_seed, raws[1], raws[2], changed_config, changed_trust)


@pytest.mark.parametrize("input_index", [0, 1, 2, 3])
def test_changed_input_bytes_cannot_reuse_old_pins(v2_inputs, input_index):
    raws, trust, _, _ = v2_inputs
    changed = list(raws)
    changed[input_index] += b" "
    with pytest.raises(ValueError):
        load_inputs(*changed, trust)


@pytest.fixture
def synthetic_v2(tmp_path, monkeypatch, v2_inputs):
    """Run the actual config projection on synthetic source identities and bytes."""
    originals, _, _, _ = v2_inputs
    manifest = parse_json(originals[1])
    contract = parse_json(originals[2])
    seed = parse_json(originals[0])
    required_sources = set(seed["required_source_ids"])
    pdfs = {}
    replacements = {}
    for source in manifest["sources"]:
        if source["source_id"] not in required_sources:
            continue
        with pymupdf.open() as pdf:
            for _ in range(source["physical_page_count"]):
                pdf.new_page()
            pdfs[source["source_id"]] = pdf.tobytes()
        replacements[source["sha256"]] = _digest(pdfs[source["source_id"]])
    manifest_raw = canonical_json_bytes(_rewrite(manifest, replacements))
    contract_raw = canonical_json_bytes(_rewrite(contract, replacements))
    replacements[_digest(originals[1])] = _digest(manifest_raw)
    replacements[_digest(originals[2])] = _digest(contract_raw)
    seed_raw = canonical_json_bytes(_rewrite(seed, replacements))
    monkeypatch.setattr(generator, "SEED_HASH", _digest(seed_raw))
    docs = tmp_path / "metadata"
    docs.mkdir()
    for name in (
        "reviewed-fragment-import-v1.json",
        "material-condition-policy-v1.json",
        "material-slice-report-plan-v1.json",
        "author01-source-review.json",
        "author01-essay-authoring-input.json",
    ):
        docs.joinpath(name).write_bytes(
            canonical_json_bytes(_rewrite(parse_json((DOCS / name).read_bytes()), replacements))
        )
    docs.joinpath(SEED_NAME).write_bytes(seed_raw)
    import_trust = ImportTrust.model_validate(generator.import_metadata(docs))
    config_raw = docs.joinpath("author01-reviewed-fragment-import-v2.json").read_bytes()
    evidence, config = load_inputs(seed_raw, manifest_raw, contract_raw, config_raw, import_trust)
    candidate_files = map_candidate(evidence, config, manifest_raw, contract_raw, config_raw)
    candidate = parse_json(candidate_files["candidate.json"])
    candidate_root = tmp_path / candidate["build_id"]
    for name, raw in candidate_files.items():
        path = candidate_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    generator.finalize_metadata(docs, candidate_root, tmp_path / "synthetic-pdfs")
    raws = tuple(docs.joinpath(name).read_bytes() for name in PLAN_NAMES)
    plan, policy, seed, plan_sha, policy_sha = load_plan(*raws)
    return raws, plan, policy, seed, plan_sha, policy_sha, candidate_files, pdfs


def _request(employed=None, retaining=None):
    payload = parse_json((DOCS / "material-condition-examples-v1.json").read_bytes())["cases"][0][
        "request"
    ]
    payload["employment"] = {
        "currently_employed_in_organization": employed,
        "retain_employment_at_enrollment": retaining,
    }
    return payload


def _assemble(synthetic_v2, payload, **overrides):
    raws, _, _, _, _, _, candidate_files, pdfs = synthetic_v2
    inputs = dict(
        plan_raw=raws[0],
        trust_raw=raws[1],
        policy_raw=raws[2],
        policy_trust_raw=raws[3],
        seed_raw=raws[4],
        request_raw=canonical_json_bytes(payload),
        candidate_files=candidate_files,
        pdf_bytes=pdfs,
    )
    inputs.update(overrides)
    return assemble_report(**inputs), inputs


@pytest.mark.parametrize(
    "employed,retaining,work_disposition",
    [
        (True, True, "submission_required"),
        (False, None, "rule_not_applicable"),
        (None, None, "needs_information"),
    ],
)
def test_v2_request_existing_conditions_to_bound_four_topic_report(
    synthetic_v2, employed, retaining, work_disposition
):
    _, plan, policy, _, _, policy_sha, _, _ = synthetic_v2
    payload = _request(employed, retaining)
    preview = evaluate(policy, load_request(canonical_json_bytes(payload)), policy_sha)
    assert preview.status == "evaluated" and len(preview.entries) == 4
    essay_condition = preview.entries[-1]
    assert essay_condition.topic_id == "application-essay"
    assert essay_condition.condition_status == "matched" and essay_condition.missing_fields == ()
    essay_rule = policy.rules[-1]
    assert essay_rule.mode == "all" and not essay_rule.predicates
    assert essay_rule.stage == "application" and essay_rule.material_code == "application_essay"
    report, bound_inputs = _assemble(synthetic_v2, payload)
    assert report.status == "evaluated" and len(report.topic_results) == 4
    assert [result.disposition for result in report.topic_results] == [
        "submission_not_required",
        "submission_not_required",
        work_disposition,
        "submission_required",
    ]
    assert len(report.evidence_inventory) == 37
    essay = report.topic_results[-1]
    assert essay.topic_id == "application-essay" and essay.material_name_zh == "申请小论文"
    assert essay.condition_status == "matched" and essay.missing_fields == ()
    assert {row.record_id for row in report.evidence_inventory[-14:]} == {"E09", "E10"}
    markdown = render_markdown(canonical_json_bytes(report.model_dump(mode="json")), **bound_inputs)
    assert "申请小论文" in markdown and "小論文" in markdown and "自己アピール" in markdown
    assert "未知" in plan.topics[-1].context_note_zh or "未包含" in plan.topics[-1].context_note_zh


@pytest.mark.parametrize(
    "field,value",
    [
        ("institution_id", "other"),
        ("program_id", "other"),
        ("admission_cycle", 2028),
        ("selection_route_id", "other"),
        ("examination_schedule_id", "B"),
        ("intake", {"year": 2027, "month": 10}),
    ],
)
def test_wrong_target_returns_no_conclusion_without_candidate_io(synthetic_v2, field, value):
    payload = _request()
    payload["target"][field] = value
    report, _ = _assemble(synthetic_v2, payload, candidate_files=None, pdf_bytes=None)
    assert report.status == "not_covered"
    assert report.topic_results == () and report.evidence_inventory == () and report.sources == ()


@pytest.mark.parametrize("changed_source", ["pdf", "kb", "lineage", "seed", "plan"])
def test_bound_report_rejects_changed_source_bytes(synthetic_v2, changed_source):
    raws, _, _, _, _, _, candidate_files, pdfs = synthetic_v2
    overrides = {}
    if changed_source == "pdf":
        changed = dict(pdfs)
        changed["complex-guide-2027-revised"] += b" "
        overrides["pdf_bytes"] = changed
    elif changed_source in {"kb", "lineage"}:
        changed = dict(candidate_files)
        key = (
            "documents/complex-master-a-additional/document_kb.json"
            if changed_source == "kb"
            else "lineage.json"
        )
        changed[key] += b" "
        overrides["candidate_files"] = changed
    elif changed_source == "seed":
        overrides["seed_raw"] = raws[4] + b" "
    else:
        overrides["plan_raw"] = raws[0] + b" "
    with pytest.raises(MaterialSliceError):
        _assemble(synthetic_v2, _request(), **overrides)


@pytest.mark.parametrize("fragment_id", ["E09-3", "E09-8", "E10-4", "E10-5"])
def test_plan_and_policy_cannot_drop_required_essay_context(synthetic_v2, fragment_id):
    raws, *_ = synthetic_v2
    plan = parse_json(raws[0])
    policy = parse_json(raws[2])
    for review in plan["scope_reviews"]:
        review["required_bindings"] = [
            binding
            for binding in review["required_bindings"]
            if not binding["fact_id"].endswith(":" + fragment_id)
        ]
    for rule in policy["rules"]:
        for record in rule["required_context_records"]:
            record["required_bindings"] = [
                binding
                for binding in record["required_bindings"]
                if not binding["fact_id"].endswith(":" + fragment_id)
            ]
    policy_raw = canonical_json_bytes(policy)
    plan["policy_reference"]["sha256"] = _digest(policy_raw)
    plan_raw = canonical_json_bytes(plan)
    trust = parse_json(raws[1]) | {"plan_sha256": _digest(plan_raw)}
    policy_trust = parse_json(raws[3]) | {"policy_sha256": _digest(policy_raw)}
    with pytest.raises(MaterialSliceError):
        _assemble(
            synthetic_v2,
            _request(),
            plan_raw=plan_raw,
            trust_raw=canonical_json_bytes(trust),
            policy_raw=policy_raw,
            policy_trust_raw=canonical_json_bytes(policy_trust),
        )
