"""Synthetic contract tests; these never read the accepted candidate or source PDFs."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import os
from pathlib import Path

import pymupdf
import pytest

from jgrad_admission_rag.reasoning.material_slice_report_cli import main as cli_main
from jgrad_admission_rag.reviewed_fragment_import import (
    BundleBinding,
    Candidate,
    CandidateDocument,
    Lineage,
    LineageDocument,
    LineageFragment,
    LineageRecord,
    QualifiedFact,
    LineageRelation,
)
from jgrad_admission_rag.reasoning.material_conditions import load_request
from jgrad_admission_rag.reasoning.material_slice_report import (
    MaterialSliceError,
    ReviewedFact,
    ReviewedMaterialSliceEvidence,
    ReviewedRecord,
    assemble_report,
    load_plan,
    load_report,
    render_markdown,
    read_candidate_files,
    read_pdf_bytes,
    verify_evidence_bytes,
    _lineage_relation_bytes,
)
from jgrad_admission_rag.reviewed_source_evidence import canonical_json_bytes, parse_json
from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    QualityGateResult,
    ScopedFact,
    canonical_document_kb_bytes,
)


DOCS = Path(__file__).resolve().parents[1] / "docs" / "onboarding"


@pytest.fixture
def reviewed_inputs():
    names = (
        "material-slice-report-plan-v1.json",
        "material-slice-report-trust-v1.json",
        "material-condition-policy-v1.json",
        "material-condition-trust-v1.json",
        "gsfs-material-evidence-seed-v1.json",
    )
    raws = tuple((DOCS / name).read_bytes() for name in names)
    plan, policy, seed, plan_sha, policy_sha = load_plan(*raws)
    cases = parse_json((DOCS / "material-condition-examples-v1.json").read_bytes())["cases"]
    return raws, plan, policy, seed, plan_sha, policy_sha, cases


def synthetic_projection(plan, seed, plan_sha, policy_sha):
    """Only a pure in-memory assembly fixture, not a replacement for the source audit."""
    seed_records = {row.record_id: row for row in seed.records}
    records = []
    for review in plan.scope_reviews:
        origin = seed_records[review.record_id]
        fragments = {row.fragment_id: row for row in origin.fragments}
        facts = []
        for binding in review.required_bindings:
            fragment_id = binding.fact_id.rsplit(":", 1)[-1]
            fragment = fragments[fragment_id]
            facts.append(
                ReviewedFact(
                    binding=binding,
                    text=fragment.text,
                    fragment_id=fragment_id,
                    fragment_role=fragment.role,
                    capture_method="manual_transcription",
                    raw_scope_type="unknown",
                    raw_section_path=(),
                )
            )
        records.append(
            ReviewedRecord(
                record_id=review.record_id,
                record_revision=review.record_revision,
                source_id=review.source_id,
                topic_id=origin.topic_id,
                stage=review.stage,
                use=review.use,
                official_heading_path=review.official_heading_path,
                manual_anchor=review.manual_anchor,
                physical_page=review.physical_page,
                printed_page_label=review.printed_page_label,
                scope_note_zh=review.scope_note_zh,
                reviewed_target_id=review.reviewed_target_id,
                facts=tuple(facts),
            )
        )
    return ReviewedMaterialSliceEvidence(
        schema_version="1.0",
        artifact_role="reviewed-material-slice-evidence",
        production_enabled=False,
        authority="reviewed_material_slice",
        coverage="partial",
        plan_id=plan.plan_id,
        revision=plan.revision,
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        target=plan.target,
        candidate_build_id=plan.candidate_reference.build_id,
        candidate_manifest_sha256=next(
            row.sha256
            for row in plan.candidate_reference.files
            if row.relative_path == "candidate.json"
        ),
        lineage_sha256=next(
            row.sha256
            for row in plan.candidate_reference.files
            if row.relative_path == "lineage.json"
        ),
        sources=plan.sources,
        records=tuple(records),
        relations=plan.relations,
        slice_validation_status="verified",
    )


@pytest.mark.parametrize(
    "employed,retain,expected",
    [
        (True, True, "submission_required"),
        (True, False, "rule_not_applicable"),
        (False, True, "rule_not_applicable"),
        (False, False, "rule_not_applicable"),
        (True, None, "needs_information"),
        (None, True, "needs_information"),
        (False, None, "rule_not_applicable"),
        (None, False, "rule_not_applicable"),
        (None, None, "needs_information"),
    ],
)
def test_nine_condition_dispositions(reviewed_inputs, employed, retain, expected):
    _, plan, policy, seed, plan_sha, policy_sha, cases = reviewed_inputs
    payload = deepcopy(cases[0]["request"])
    payload["employment"] = {
        "currently_employed_in_organization": employed,
        "retain_employment_at_enrollment": retain,
    }
    report = assemble_report(
        plan,
        policy,
        load_request(canonical_json_bytes(payload)),
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        evidence=synthetic_projection(plan, seed, plan_sha, policy_sha),
    )
    assert [row.disposition for row in report.topic_results] == [
        "submission_not_required",
        "submission_not_required",
        expected,
    ]
    assert len(report.evidence_inventory) == 23
    assert len(report.sources) == 3
    assert len(report.topic_results[2].basis_citation_keys) == 10
    assert len(report.topic_results[2].context_citation_keys) == 3
    assert report.topic_results[2].missing_fields == tuple(
        path
        for path, value in (
            ("employment.currently_employed_in_organization", employed),
            ("employment.retain_employment_at_enrollment", retain),
        )
        if value is None
    )
    markdown = render_markdown(report)
    assert "募集要项参考报告（历史固定切片／部分材料主题）" in markdown
    assert "日文官方原文" in markdown and "物理页 28；印刷页 26" in markdown
    assert "入学手续关联" in markdown
    assert "表格上传组表头" in markdown
    assert "fact:reviewed" not in markdown
    if employed is False and retain is None:
        assert "一般性免交" in markdown


def test_wrong_target_and_profile_conflict_avoid_evidence(reviewed_inputs):
    raws, plan, policy, _, plan_sha, policy_sha, cases = reviewed_inputs
    payload = deepcopy(cases[0]["request"])
    payload["target"]["institution_id"] = "other"
    request_raw = canonical_json_bytes(payload)
    report = assemble_report(
        plan,
        policy,
        load_request(request_raw),
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        evidence=None,
    )
    assert report.status == "not_covered"
    assert not report.topic_results and not report.evidence_inventory and not report.sources
    assert (
        load_report(
            canonical_json_bytes(report.model_dump(mode="json")),
            plan_raw=raws[0],
            trust_raw=raws[1],
            policy_raw=raws[2],
            policy_trust_raw=raws[3],
            seed_raw=raws[4],
            request_raw=request_raw,
            candidate_files=None,
            pdf_bytes=None,
        )
        == report
    )
    forged = report.model_dump(mode="json")
    forged["status"] = "evaluated"
    with pytest.raises(MaterialSliceError):
        load_report(
            canonical_json_bytes(forged),
            plan_raw=raws[0],
            trust_raw=raws[1],
            policy_raw=raws[2],
            policy_trust_raw=raws[3],
            seed_raw=raws[4],
            request_raw=request_raw,
            candidate_files=None,
            pdf_bytes=None,
        )
    payload = deepcopy(cases[0]["request"])
    payload["applicant_profile"]["target_application"]["application_route"] = "other"
    report = assemble_report(
        plan,
        policy,
        load_request(canonical_json_bytes(payload)),
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        evidence=None,
    )
    assert report.status == "target_mismatch"
    assert report.conflict_fields == ("application_route",)
    assert not report.topic_results and not report.evidence_inventory


def test_request_key_order_does_not_change_report(reviewed_inputs):
    _, plan, policy, seed, plan_sha, policy_sha, cases = reviewed_inputs
    evidence = synthetic_projection(plan, seed, plan_sha, policy_sha)
    payload = cases[0]["request"]
    first = load_request(canonical_json_bytes(payload))
    second = load_request(canonical_json_bytes(dict(reversed(list(payload.items())))))
    assert assemble_report(
        plan,
        policy,
        first,
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        evidence=evidence,
    ) == assemble_report(
        plan,
        policy,
        second,
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        evidence=evidence,
    )


def test_markdown_quotes_escape_html_and_controls(reviewed_inputs):
    _, plan, policy, seed, plan_sha, policy_sha, cases = reviewed_inputs
    evidence = synthetic_projection(plan, seed, plan_sha, policy_sha)
    report = assemble_report(
        plan,
        policy,
        load_request(canonical_json_bytes(cases[0]["request"])),
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        evidence=evidence,
    )
    citation = report.evidence_inventory[0].model_copy(
        update={"quote_text": "<script>alert(1)</script> * [malicious](https://evil.example)"}
    )
    changed = report.model_copy(
        update={"evidence_inventory": (citation, *report.evidence_inventory[1:])}
    )
    markdown = render_markdown(changed)
    assert "<script>" not in markdown
    assert "&lt;script&gt;" in markdown
    assert "\\[malicious\\]" in markdown


@pytest.mark.parametrize(
    "mutation",
    [
        "page",
        "binding",
        "stage",
        "missing_review",
        "topic_effect",
        "relation",
        "table_header",
        "path_escape",
        "duplicate_file",
        "missing_identity_field",
    ],
)
def test_plan_must_match_external_reviewed_inputs(reviewed_inputs, mutation):
    raws, *_ = reviewed_inputs
    plan = parse_json(raws[0])
    if mutation == "page":
        plan["scope_reviews"][0]["physical_page"] = 999
    elif mutation == "binding":
        plan["scope_reviews"][0]["required_bindings"][0]["authoritative_fact_text_sha256"] = (
            "0" * 64
        )
    elif mutation == "stage":
        plan["scope_reviews"][5]["stage"] = "enrollment_context_only"
    elif mutation == "missing_review":
        plan["scope_reviews"].pop()
    elif mutation == "topic_effect":
        plan["topics"][2]["proposed_effect_when_matched"] = "not_required"
    elif mutation == "relation":
        plan["relations"][0]["to"] = "missing"
    elif mutation == "table_header":
        plan["scope_reviews"][7]["required_bindings"].pop(0)
    elif mutation == "path_escape":
        plan["candidate_reference"]["files"][0]["relative_path"] = "../outside.json"
    elif mutation == "duplicate_file":
        plan["candidate_reference"]["files"].append(
            deepcopy(plan["candidate_reference"]["files"][0])
        )
    elif mutation == "missing_identity_field":
        del plan["sources"][0]["identity"]["official_title"]
    changed = canonical_json_bytes(plan)
    trust = parse_json(raws[1])
    trust["plan_sha256"] = sha256(changed).hexdigest()
    with pytest.raises(MaterialSliceError):
        load_plan(changed, canonical_json_bytes(trust), raws[2], raws[3], raws[4])


def test_lineage_relation_alias_matches_pinned_plan(reviewed_inputs):
    _, plan, _, _, _, _, _ = reviewed_inputs
    relation = plan.relations[0]
    lineage = Lineage.model_construct(
        relations=(
            LineageRelation.model_validate(
                {
                    "from": relation.from_id,
                    "kind": relation.kind,
                    "to": relation.to,
                    "from_facts": [
                        {"document_id": "a", "kb_sha256": "0" * 64, "fact_id": "fact:a"}
                    ],
                    "to_facts": [{"document_id": "b", "kb_sha256": "0" * 64, "fact_id": "fact:b"}],
                }
            ),
        )
    )
    assert _lineage_relation_bytes(lineage) == (
        canonical_json_bytes(relation.model_dump(mode="json", by_alias=True)),
    )


def make_tiny_synthetic_slice(reviewed_inputs, institution_id="utokyo"):
    """One-page, two-Fact slice built from models, without old importer or real assets."""
    raws, *_ = reviewed_inputs
    plan = parse_json(raws[0])
    policy = parse_json(raws[2])
    seed = parse_json(raws[4])
    if institution_id != "utokyo":
        target_id = f"{institution_id}-master-2027-general-a-202704"
        for payload in (plan, policy, seed):
            payload["target"]["institution_id"] = institution_id
            payload["target"]["organization_id"] = f"{institution_id}-grad"
            payload["target"]["program_id"] = f"{institution_id}-program"
            payload["target"]["target_id"] = target_id
        policy["profile_target_aliases"]["graduate_school_or_college"] = [f"{institution_id}-grad"]
        policy["profile_target_aliases"]["department_or_program"] = [f"{institution_id}-program"]
    source_id = "complex-guide-2027-revised"
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf_raw = pdf.tobytes()
    pdf_hash = sha256(pdf_raw).hexdigest()
    plan["sources"] = [next(x for x in plan["sources"] if x["source_id"] == source_id)]
    plan["sources"][0]["identity"]["source_pdf_sha256"] = pdf_hash
    plan["sources"][0]["physical_page_count"] = 1
    if institution_id != "utokyo":
        plan["sources"][0]["identity"].update(
            institution_id=institution_id,
            institution_name="Synthetic University",
            official_title="Synthetic admissions guide",
            official_source_url="https://example.org/synthetic-guide.pdf",
        )
    plan["scope_reviews"] = [next(x for x in plan["scope_reviews"] if x["record_id"] == "E02")]
    review = plan["scope_reviews"][0]
    review["physical_page"] = 1
    review["reviewed_target_id"] = plan["target"]["target_id"]
    plan["relations"] = []
    plan["topics"] = [plan["topics"][0]]
    plan["topics"][0]["required_context_record_ids"] = ["E02"]
    policy["rules"] = [policy["rules"][0]]
    policy["rules"][0]["required_context_records"] = [
        next(x for x in policy["rules"][0]["required_context_records"] if x["record_id"] == "E02")
    ]
    policy["evidence_prerequisites"]["documents"] = [
        next(
            x for x in policy["evidence_prerequisites"]["documents"] if x["source_id"] == source_id
        )
    ]
    policy["evidence_prerequisites"]["documents"][0]["identity"] = deepcopy(
        plan["sources"][0]["identity"]
    )
    seed["required_source_ids"] = [source_id]
    seed["topics"] = [seed["topics"][0]]
    seed["topics"][0]["record_ids"] = ["E02"]
    seed["records"] = [next(x for x in seed["records"] if x["record_id"] == "E02")]
    seed["records"][0]["physical_page"] = 1
    seed["records"][0]["source_pdf_sha256"] = pdf_hash
    seed["relations"] = []
    seed_raw = canonical_json_bytes(seed)
    seed_hash = sha256(seed_raw).hexdigest()
    plan["seed_reference"]["sha256"] = seed_hash
    policy["evidence_prerequisites"]["bundle_sha256"] = seed_hash
    identity = plan["sources"][0]["identity"]
    fragments = seed["records"][0]["fragments"]
    facts = []
    bindings = []
    lineage_fragments = []
    for fragment in fragments:
        fid = fragment["fragment_id"]
        fact_id = f"fact:reviewed:{source_id}:E02:r1:{fid}"
        facts.append(
            ScopedFact(
                fact_id=fact_id,
                fact_type="reviewed_source_fragment",
                scope_type="unknown",
                text=fragment["text"],
                source_pages=[1],
                section_path=[],
                embedding_text="synthetic",
                metadata={
                    "record_id": "E02",
                    "record_revision": 1,
                    "fragment_id": fid,
                    "fragment_role": fragment["role"],
                    "capture_method": "manual_transcription",
                },
            )
        )
        bindings.append(
            {
                "document_id": source_id,
                "source_kb_sha256": "0" * 64,
                "source_pdf_sha256": pdf_hash,
                "fact_id": fact_id,
                "source_pages": [1],
                "authoritative_fact_text_sha256": sha256(
                    fragment["text"].encode("utf-8")
                ).hexdigest(),
            }
        )
    kb = DocumentKnowledgeBase(
        manifest=KnowledgeManifest(
            identity=identity,
            source_pdf=f"{pdf_hash}.pdf",
            chunk_count=len(facts),
        ),
        facts=facts,
        diagnostics=BuildDiagnostics(quality_gate=QualityGateResult(passed=False)),
    )
    kb_raw = canonical_document_kb_bytes(kb)
    kb_hash = sha256(kb_raw).hexdigest()
    plan["sources"][0]["kb_sha256"] = kb_hash
    policy["evidence_prerequisites"]["documents"][0]["kb_sha256"] = kb_hash
    for binding in bindings:
        binding["source_kb_sha256"] = kb_hash
    review["required_bindings"] = deepcopy(bindings)
    policy["rules"][0]["required_context_records"][0]["required_bindings"] = deepcopy(bindings)
    for fragment, binding in zip(fragments, bindings, strict=True):
        lineage_fragments.append(
            LineageFragment(
                fragment_id=fragment["fragment_id"],
                role=fragment["role"],
                qualified_fact=QualifiedFact(
                    document_id=source_id,
                    kb_sha256=kb_hash,
                    fact_id=binding["fact_id"],
                ),
            )
        )
    descriptor = {
        "bundle_id": seed["bundle_id"],
        "bundle_revision": seed["revision"],
        "bundle_sha256": seed_hash,
        "candidate_schema_version": "1.0",
        "document_identity_schema_version": "1.0",
        "documents": [{"source_id": source_id, "identity": identity}],
        "embedding_text_version": "1",
        "import_config_sha256": plan["candidate_reference"]["import_config_sha256"],
        "kb_schema_version": "0.6",
        "lineage_schema_version": "1.0",
        "mapper_version": "1",
        "profile_id": "reviewed-source-v1",
        "profile_version": "1",
        "source_manifest_sha256": plan["candidate_reference"]["source_manifest_sha256"],
        "source_set": plan["source_set"],
        "target": plan["target"],
        "target_contract_sha256": plan["candidate_reference"]["target_contract_sha256"],
    }
    build_id = sha256(canonical_json_bytes(descriptor)).hexdigest()
    plan["candidate_reference"]["build_id"] = build_id
    policy["evidence_prerequisites"]["candidate_build_id"] = build_id
    lineage = Lineage(
        schema_version="1.0",
        artifact_role="reviewed-fragment-lineage",
        production_enabled=False,
        build_id=build_id,
        bundle=BundleBinding(bundle_id=seed["bundle_id"], revision=1, sha256=seed_hash),
        source_manifest_sha256=descriptor["source_manifest_sha256"],
        target_contract_sha256=descriptor["target_contract_sha256"],
        import_config_sha256=descriptor["import_config_sha256"],
        target=plan["target"],
        source_set=plan["source_set"],
        documents=(
            LineageDocument(
                source_id=source_id, identity=identity, kb_sha256=kb_hash, fact_count=2
            ),
        ),
        records=(
            LineageRecord(
                record_id="E02",
                revision=1,
                topic_id="english-score-sheets",
                source_id=source_id,
                source_pdf_sha256=pdf_hash,
                physical_page=1,
                printed_page_label="26",
                manual_anchor=review["manual_anchor"],
                capture_method="manual_transcription",
                review_record_id=seed["records"][0]["review_record_id"],
                fragments=tuple(lineage_fragments),
                required_fragment_ids=tuple(seed["records"][0]["required_fragment_ids"]),
            ),
        ),
        relations=(),
    )
    lineage_raw = canonical_json_bytes(lineage.model_dump(mode="json", by_alias=True))
    candidate = Candidate(
        schema_version="1.0",
        artifact_role="reviewed-kb-candidate",
        production_enabled=False,
        coverage="reviewed_fragments_only",
        pdf_reference_resolution="not_run",
        build_id=build_id,
        input_descriptor=descriptor,
        documents=(
            CandidateDocument(
                document_id=source_id,
                relative_path=f"documents/{source_id}/document_kb.json",
                kb_sha256=kb_hash,
            ),
        ),
        lineage_sha256=sha256(lineage_raw).hexdigest(),
    )
    candidate_raw = canonical_json_bytes(candidate.model_dump(mode="json"))
    candidate_files = {
        "candidate.json": candidate_raw,
        "lineage.json": lineage_raw,
        f"documents/{source_id}/document_kb.json": kb_raw,
    }
    plan["candidate_reference"]["files"] = [
        {"relative_path": name, "sha256": sha256(raw).hexdigest()}
        for name, raw in sorted(candidate_files.items())
    ]
    policy["evidence_prerequisites"]["candidate_manifest_sha256"] = sha256(
        candidate_raw
    ).hexdigest()
    policy["evidence_prerequisites"]["lineage_sha256"] = sha256(lineage_raw).hexdigest()
    policy_raw = canonical_json_bytes(policy)
    policy_sha = sha256(policy_raw).hexdigest()
    plan["policy_reference"]["sha256"] = policy_sha
    plan_raw = canonical_json_bytes(plan)
    plan_sha = sha256(plan_raw).hexdigest()
    trust = parse_json(raws[1])
    trust["plan_sha256"] = plan_sha
    policy_trust = parse_json(raws[3])
    policy_trust["policy_sha256"] = policy_sha
    trust_raw = canonical_json_bytes(trust)
    policy_trust_raw = canonical_json_bytes(policy_trust)
    loaded_plan, loaded_policy, loaded_seed, _, _ = load_plan(
        plan_raw, trust_raw, policy_raw, policy_trust_raw, seed_raw
    )
    return (
        (plan_raw, trust_raw, policy_raw, policy_trust_raw, seed_raw),
        loaded_plan,
        loaded_policy,
        loaded_seed,
        plan_sha,
        policy_sha,
        candidate_files,
        {source_id: pdf_raw},
    )


@pytest.fixture
def tiny_synthetic_slice(reviewed_inputs):
    return make_tiny_synthetic_slice(reviewed_inputs)


def test_tiny_synthetic_candidate_is_fully_audited(tiny_synthetic_slice):
    _, plan, policy, seed, plan_sha, policy_sha, candidate_files, pdf_bytes = tiny_synthetic_slice
    evidence = verify_evidence_bytes(
        plan,
        policy,
        seed,
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        candidate_files=candidate_files,
        pdf_bytes=pdf_bytes,
    )
    assert len(evidence.records) == 1
    assert len(evidence.records[0].facts) == 2


@pytest.mark.parametrize(
    "mutation", ["kb_hash", "pdf_hash", "missing_fact", "extra_file", "lineage_key"]
)
def test_tiny_synthetic_candidate_fails_closed(tiny_synthetic_slice, mutation):
    _, plan, policy, seed, plan_sha, policy_sha, candidate_files, pdf_bytes = tiny_synthetic_slice
    candidate_files = dict(candidate_files)
    pdf_bytes = dict(pdf_bytes)
    if mutation == "kb_hash":
        kb_name = next(name for name in candidate_files if name.endswith("document_kb.json"))
        candidate_files[kb_name] += b" "
    elif mutation == "pdf_hash":
        pdf_bytes[next(iter(pdf_bytes))] += b" "
    elif mutation == "missing_fact":
        candidate_files.pop(
            next(name for name in candidate_files if name.endswith("document_kb.json"))
        )
    elif mutation == "extra_file":
        candidate_files["unexpected.json"] = b"{}"
    elif mutation == "lineage_key":
        candidate_files["lineage.json"] += b" "
    with pytest.raises(MaterialSliceError):
        verify_evidence_bytes(
            plan,
            policy,
            seed,
            plan_sha256=plan_sha,
            policy_sha256=policy_sha,
            candidate_files=candidate_files,
            pdf_bytes=pdf_bytes,
        )


def test_bound_report_loader_recomputes_synthetic_source(tiny_synthetic_slice, reviewed_inputs):
    raws, plan, policy, seed, plan_sha, policy_sha, candidate_files, pdf_bytes = (
        tiny_synthetic_slice
    )
    request_raw = canonical_json_bytes(reviewed_inputs[-1][0]["request"])
    evidence = verify_evidence_bytes(
        plan,
        policy,
        seed,
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        candidate_files=candidate_files,
        pdf_bytes=pdf_bytes,
    )
    report = assemble_report(
        plan,
        policy,
        load_request(request_raw),
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        evidence=evidence,
    )
    encoded = canonical_json_bytes(report.model_dump(mode="json"))
    assert (
        load_report(
            encoded,
            plan_raw=raws[0],
            trust_raw=raws[1],
            policy_raw=raws[2],
            policy_trust_raw=raws[3],
            seed_raw=raws[4],
            request_raw=request_raw,
            candidate_files=candidate_files,
            pdf_bytes=pdf_bytes,
        )
        == report
    )
    forged = report.model_dump(mode="json")
    forged["evidence_inventory"][0]["quote_text"] = "伪造原文"
    with pytest.raises(MaterialSliceError):
        load_report(
            canonical_json_bytes(forged),
            plan_raw=raws[0],
            trust_raw=raws[1],
            policy_raw=raws[2],
            policy_trust_raw=raws[3],
            seed_raw=raws[4],
            request_raw=request_raw,
            candidate_files=candidate_files,
            pdf_bytes=pdf_bytes,
        )


def test_second_institution_one_topic_has_no_school_branch(reviewed_inputs):
    _, plan, policy, seed, plan_sha, policy_sha, candidate_files, pdf_bytes = (
        make_tiny_synthetic_slice(reviewed_inputs, institution_id="second")
    )
    evidence = verify_evidence_bytes(
        plan,
        policy,
        seed,
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        candidate_files=candidate_files,
        pdf_bytes=pdf_bytes,
    )
    original = load_request(canonical_json_bytes(reviewed_inputs[-1][0]["request"]))
    wrong = assemble_report(
        plan,
        policy,
        original,
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        evidence=None,
    )
    assert wrong.status == "not_covered" and not wrong.topic_results
    payload = deepcopy(reviewed_inputs[-1][0]["request"])
    payload["target"] = plan.target.model_dump(mode="json")
    payload["applicant_profile"]["target_application"].update(
        graduate_school_or_college="second-grad",
        department_or_program="second-program",
    )
    report = assemble_report(
        plan,
        policy,
        load_request(canonical_json_bytes(payload)),
        plan_sha256=plan_sha,
        policy_sha256=policy_sha,
        evidence=evidence,
    )
    assert report.status == "evaluated"
    assert (
        len(report.topic_results) == 1
        and report.topic_results[0].topic_id == "english-score-sheets"
    )


def test_synthetic_cli_batch_is_atomic(tiny_synthetic_slice, reviewed_inputs, tmp_path, capsys):
    raws, plan, _, _, _, _, candidate_files, pdf_bytes = tiny_synthetic_slice
    names = ("plan", "trust", "policy", "policy-trust", "seed")
    args = []
    for name, raw in zip(names, raws, strict=True):
        path = tmp_path / f"{name}.json"
        path.write_bytes(raw)
        args.extend((f"--{name}", str(path)))
    candidate_root = tmp_path / "candidate"
    for name, raw in candidate_files.items():
        path = candidate_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    for source_id, raw in pdf_bytes.items():
        source = next(row for row in plan.sources if row.source_id == source_id)
        (pdf_dir / f"{source.identity.source_pdf_sha256}.pdf").write_bytes(raw)
    args.extend(("--candidate-root", str(candidate_root), "--pdf-dir", str(pdf_dir)))
    valid = tmp_path / "request.json"
    valid.write_bytes(canonical_json_bytes(reviewed_inputs[-1][0]["request"]))
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"{}")
    assert cli_main(args + ["--request", str(valid), "--request", str(bad)]) == 2
    assert capsys.readouterr().out == ""
    assert cli_main(args + ["--request", str(valid)]) == 0
    output = capsys.readouterr().out
    envelope = parse_json(output.encode("utf-8"))
    assert envelope["report"]["status"] == "evaluated"
    assert "日文官方原文" in envelope["markdown"]
    assert cli_main(args + ["--request", str(valid), "--format", "markdown"]) == 0
    assert capsys.readouterr().out.startswith("# 募集要项参考报告")
    (candidate_root / "unexpected.json").write_text("{}", encoding="utf-8")
    assert cli_main(args + ["--request", str(valid)]) == 2
    assert capsys.readouterr().out == ""


def test_candidate_symlink_is_rejected(tiny_synthetic_slice, tmp_path):
    _, plan, _, _, _, _, candidate_files, _ = tiny_synthetic_slice
    root = tmp_path / "candidate"
    for name, raw in candidate_files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    victim = root / "candidate.json"
    victim.unlink()
    target = tmp_path / "target.json"
    target.write_bytes(candidate_files["candidate.json"])
    try:
        os.symlink(target, victim)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    with pytest.raises(MaterialSliceError):
        read_candidate_files(root, plan)


def test_pdf_symlink_is_rejected(tiny_synthetic_slice, tmp_path):
    _, plan, _, _, _, _, _, pdf_bytes = tiny_synthetic_slice
    source = plan.sources[0]
    target = tmp_path / "actual.pdf"
    target.write_bytes(pdf_bytes[source.source_id])
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    link = pdf_dir / f"{source.identity.source_pdf_sha256}.pdf"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    with pytest.raises(MaterialSliceError):
        read_pdf_bytes(pdf_dir, plan)


def test_uncovered_cli_skips_missing_source_assets(
    tiny_synthetic_slice, reviewed_inputs, tmp_path, capsys
):
    raws, _, _, _, _, _, _, _ = tiny_synthetic_slice
    names = ("plan", "trust", "policy", "policy-trust", "seed")
    args = []
    for name, raw in zip(names, raws, strict=True):
        path = tmp_path / f"{name}.json"
        path.write_bytes(raw)
        args.extend((f"--{name}", str(path)))
    args.extend(
        (
            "--candidate-root",
            str(tmp_path / "absent-candidate"),
            "--pdf-dir",
            str(tmp_path / "absent-pdfs"),
        )
    )
    payload = deepcopy(reviewed_inputs[-1][0]["request"])
    payload["target"]["institution_id"] = "different"
    request = tmp_path / "uncovered.json"
    request.write_bytes(canonical_json_bytes(payload))
    assert cli_main(args + ["--request", str(request)]) == 0
    envelope = parse_json(capsys.readouterr().out.encode("utf-8"))
    assert envelope["report"]["status"] == "not_covered"
    assert envelope["report"]["evidence_inventory"] == []
