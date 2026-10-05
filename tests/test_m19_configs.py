"""Bounded compiler proofs: external approval, full evidence, semantics and reuse.

All source PDFs here are generated blank synthetic metadata fixtures. No real build.
"""

# ruff: noqa: F811
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import shutil

import pytest

from scripts import m19_configs as compiler
from tests.test_author01 import synthetic_v2, v2_inputs, _rewrite, _request  # noqa: F401
from jgrad_admission_rag.reviewed_source_evidence import canonical_json_bytes, parse_json
from jgrad_admission_rag.reasoning.material_slice_report import assemble_report
from jgrad_admission_rag.reviewed_fragment_import import publish_candidate, validate_candidate

DOCS = Path(__file__).resolve().parents[1] / "docs/onboarding"


def write(path, value):
    path.write_bytes(canonical_json_bytes(value))


@pytest.fixture
def compiler_case(tmp_path, synthetic_v2, v2_inputs):
    raws, plan, _, _, _, _, _, pdfs = synthetic_v2
    docs = tmp_path / "tests" / "approved-synthetic"
    docs.mkdir(parents=True)
    generated_v2 = tmp_path / "metadata"
    approval = parse_json((DOCS / "m19-design-approval.json").read_bytes())
    for name in approval["base_inputs"]:
        source = generated_v2 / name
        shutil.copyfile(source if source.exists() else DOCS / name, docs / name)
    replacements = {
        s.identity.source_pdf_sha256: s.identity.source_pdf_sha256 for s in plan.sources
    }
    original_sources = parse_json(v2_inputs[0][1])["sources"]
    replacements.update(
        {
            s["sha256"]: sha256(pdfs[s["source_id"]]).hexdigest()
            for s in original_sources
            if s["source_id"] in pdfs
        }
    )
    for name, raw in [
        ("utokyo-gsfs-complex-2027.sources.json", v2_inputs[0][1]),
        ("gsfs-source-set-contract-v0.1.examples.json", v2_inputs[0][2]),
    ]:
        value = _rewrite(parse_json(raw), replacements)
        write(docs / name, value)
        replacements[sha256(raw).hexdigest()] = sha256((docs / name).read_bytes()).hexdigest()
    new_seed = _rewrite(
        parse_json((DOCS / "m19-questionnaire-evidence-seed-v3.json").read_bytes()), replacements
    )
    # Retain exact synthetic baseline records and add only the reviewed new rows.
    new_seed["records"][:10] = parse_json(raws[4])["records"]
    write(docs / "m19-questionnaire-evidence-seed-v3.json", new_seed)
    author = parse_json((DOCS / "m19-questionnaire-authoring.json").read_bytes())
    author["seed"]["sha256"] = sha256(
        (docs / "m19-questionnaire-evidence-seed-v3.json").read_bytes()
    ).hexdigest()
    write(docs / "m19-questionnaire-authoring.json", author)
    write(
        docs / "m19-source-review-pin-v3.json",
        dict(bundle_id=new_seed["bundle_id"], revision=3, bundle_sha256=author["seed"]["sha256"]),
    )
    review = _rewrite(parse_json((DOCS / "m19-source-review.json").read_bytes()), replacements)
    review.update(
        seed_sha256=author["seed"]["sha256"],
        authoring_sha256=sha256(
            (docs / "m19-questionnaire-authoring.json").read_bytes()
        ).hexdigest(),
    )
    write(docs / "m19-source-review.json", review)
    approval.update(
        synthetic=True,
        approval_id="synthetic-fixture-not-real-approval",
        approved_seed_sha256=author["seed"]["sha256"],
        approved_authoring_sha256=review["authoring_sha256"],
        base_inputs={
            n: sha256((docs / n).read_bytes()).hexdigest() for n in approval["base_inputs"]
        },
    )
    write(docs / "m19-design-approval.json", approval)
    shutil.copyfile(
        DOCS / "author01-reference-workspace-preview-v2.json",
        docs / "author01-reference-workspace-preview-v2.json",
    )
    return docs, pdfs


def compile_case(case):
    docs, pdfs = case
    return compiler.compile_configs(docs, pdf_bytes=pdfs, synthetic=True)


def test_full_reproducible_projection_and_old_four_semantics(compiler_case, tmp_path):
    files, snapshot, _ = compile_case(compiler_case)
    assert compile_case(compiler_case)[0] == files
    second = tmp_path / "tests" / "second-workspace"
    shutil.copytree(compiler_case[0], second)
    assert compile_case((second, compiler_case[1]))[0] == files
    old_plan = parse_json(
        (compiler_case[0] / "author01-material-slice-report-plan-v2.json").read_bytes()
    )
    assert parse_json(files["plan.json"])["topics"][:4] == old_plan["topics"]
    old_policy = parse_json(
        (compiler_case[0] / "author01-material-condition-policy-v2.json").read_bytes()
    )
    for before, after in zip(
        old_policy["rules"], parse_json(files["policy.json"])["rules"][:4], strict=True
    ):
        before, after = deepcopy(before), deepcopy(after)
        for value in [before, after]:
            for row in value["required_context_records"]:
                row.pop("required_bindings")
        assert before == after
    assert len(snapshot.plan.topics) == 5
    assert len(parse_json(snapshot.presentation)["topics"]) == 5
    assert (
        sum(
            d["fact_count"]
            for d in parse_json(snapshot.candidate_files["lineage.json"])["documents"]
        )
        == 51
    )
    output = tmp_path / "output"
    compiler.write_or_check(files, output)
    mtimes = {p.name: p.stat().st_mtime_ns for p in output.iterdir()}
    compiler.write_or_check(files, output, check=True)
    assert mtimes == {p.name: p.stat().st_mtime_ns for p in output.iterdir()}
    (output / "policy.json").write_bytes(files["policy.json"] + b" ")
    with pytest.raises(ValueError, match="drift"):
        compiler.write_or_check(files, output, check=True)


@pytest.mark.parametrize(
    "mutation",
    [
        "author",
        "base",
        "missing_approval",
        "school",
        "year",
        "route",
        "batch",
        "stage",
        "header",
        "claim",
        "template",
    ],
)
def test_unapproved_and_malformed_inputs_fail_before_output(compiler_case, mutation):
    docs, _ = compiler_case
    if mutation == "missing_approval":
        (docs / "m19-design-approval.json").unlink()
    elif mutation == "base":
        path = docs / "author01-material-condition-policy-v2.json"
        path.write_bytes(path.read_bytes() + b" ")
    else:
        path = docs / "m19-questionnaire-authoring.json"
        value = parse_json(path.read_bytes())
        if mutation == "author":
            value["reader"]["summary"]["text"] = "unapproved"
        elif mutation in ["school", "year", "route", "batch"]:
            field = dict(
                school="institution_id",
                year="admission_cycle",
                route="selection_route_id",
                batch="examination_schedule_id",
            )[mutation]
            value["target"][field] = 2030 if mutation == "year" else "wrong"
        elif mutation == "stage":
            next(c for c in value["claims"] if c["field"] == "stage")["value"] = "enrollment"
        elif mutation == "header":
            value["required_context"]["E11"].remove("E11-3")
        elif mutation == "claim":
            value["claims"][0]["fragment_ids"] = ["E09-3"]
        else:
            value["condition"]["template"] = "arbitrary_eval"
        write(path, value)
        # For structure tests only, update this visibly synthetic test approval.
        # The real approval/input files are never touched.
        if mutation not in ["author", "school", "year", "route", "batch"]:
            approval = parse_json((docs / "m19-design-approval.json").read_bytes())
            approval["approved_authoring_sha256"] = sha256(path.read_bytes()).hexdigest()
            write(docs / "m19-design-approval.json", approval)
            review = parse_json((docs / "m19-source-review.json").read_bytes())
            review["authoring_sha256"] = approval["approved_authoring_sha256"]
            write(docs / "m19-source-review.json", review)
    with pytest.raises((ValueError, FileNotFoundError)):
        compile_case(compiler_case)


@pytest.mark.parametrize("employed", [True, False, None])
@pytest.mark.parametrize("retain", [True, False, None])
def test_nine_conditions_preserve_null_and_required_materials(compiler_case, employed, retain):
    _, snapshot, _ = compile_case(compiler_case)
    report = snapshot.report(canonical_json_bytes(_request(employed, retain)))["report"]
    results = report["topic_results"]
    assert [r["disposition"] for r in results[:2]] == ["submission_not_required"] * 2
    assert [r["disposition"] for r in results[-2:]] == ["submission_required"] * 2
    expected = (
        "submission_required"
        if employed is True and retain is True
        else "rule_not_applicable"
        if employed is False or retain is False
        else "needs_information"
    )
    assert results[2]["disposition"] == expected


def test_candidate_publish_and_second_call_reuse_same_bytes(compiler_case, tmp_path):
    _, snapshot, mapper_inputs = compile_case(compiler_case)
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    paths = {}
    for source_id, raw in compiler_case[1].items():
        paths[source_id] = pdfs / (source_id + ".pdf")
        paths[source_id].write_bytes(raw)
    store = tmp_path / "synthetic-store"
    root, status, hashes = publish_candidate(store, *mapper_inputs, paths)
    assert status == "generated"
    mtimes = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
    second, status, again = publish_candidate(store, *mapper_inputs, paths)
    assert second == root and status == "reused" and hashes == again
    assert mtimes == {p: p.stat().st_mtime_ns for p in mtimes}
    assert validate_candidate(root, *mapper_inputs) == hashes
    assert root.name == snapshot.plan.candidate_reference.build_id


def test_wrong_target_has_no_positive_result(compiler_case):
    _, snapshot, _ = compile_case(compiler_case)
    for field, value in [
        ("institution_id", "other"),
        ("admission_cycle", 2030),
        ("selection_route_id", "other"),
        ("examination_schedule_id", "B"),
        ("intake", {"year": 2027, "month": 10}),
    ]:
        request = _request()
        request["target"][field] = value
        result = snapshot.report(canonical_json_bytes(request))["report"]
        assert result["status"] == "not_covered" and result["topic_results"] == []


def test_missing_candidate_fragment_bytes_fail(compiler_case):
    _, snapshot, _ = compile_case(compiler_case)
    files = dict(snapshot.candidate_files)
    files["lineage.json"] += b" "
    with pytest.raises(ValueError):
        assemble_report(
            plan_raw=snapshot.plan_raw,
            trust_raw=snapshot.trust_raw,
            policy_raw=snapshot.policy_raw,
            policy_trust_raw=snapshot.policy_trust_raw,
            seed_raw=snapshot.seed_raw,
            request_raw=canonical_json_bytes(_request()),
            candidate_files=files,
            pdf_bytes=snapshot.pdf_bytes,
        )


def approve_synthetic_edit(docs):
    """Visible test-only reviewer fixture; forbidden for the real frozen inputs."""
    assert "tests" in docs.parts
    approval = parse_json((docs / "m19-design-approval.json").read_bytes())
    assert approval["synthetic"] is True
    approval["approved_authoring_sha256"] = sha256(
        (docs / "m19-questionnaire-authoring.json").read_bytes()
    ).hexdigest()
    write(docs / "m19-design-approval.json", approval)
    review = parse_json((docs / "m19-source-review.json").read_bytes())
    review["authoring_sha256"] = approval["approved_authoring_sha256"]
    write(docs / "m19-source-review.json", review)


@pytest.fixture
def other_compiler_case(compiler_case):
    docs, pdfs = compiler_case
    replacements = {
        "utokyo": "synthetic-campus",
        "utokyo-gsfs": "synthetic-grad",
        "utokyo-gsfs-complex": "synthetic-program",
        "utokyo-gsfs-complex-master-2027-general-a-202704": "synthetic-target",
        "utokyo-gsfs-complex-master-2027-general-a-202704-s1": "synthetic-source-set",
        "application-questionnaire": "synthetic-project-form",
        "application_questionnaire": "synthetic_project_form",
        "报考志愿调查表": "合成项目表",
    }
    for path in docs.glob("*.json"):
        write(path, _rewrite(parse_json(path.read_bytes()), replacements))
    manifest_hash = sha256(
        (docs / "utokyo-gsfs-complex-2027.sources.json").read_bytes()
    ).hexdigest()
    contract_hash = sha256(
        (docs / "gsfs-source-set-contract-v0.1.examples.json").read_bytes()
    ).hexdigest()
    for name in ["author01-essay-evidence-seed-v2.json", "m19-questionnaire-evidence-seed-v3.json"]:
        path = docs / name
        seed = parse_json(path.read_bytes())
        seed["source_manifest"]["sha256"] = manifest_hash
        seed["target_contract"]["sha256"] = contract_hash
        write(path, seed)
    path = docs / "author01-material-condition-policy-v2.json"
    policy = parse_json(path.read_bytes())
    policy["evidence_prerequisites"]["source_manifest_sha256"] = manifest_hash
    policy["evidence_prerequisites"]["target_contract_sha256"] = contract_hash
    write(path, policy)
    for name, seed_name in [
        ("author01-essay-authoring-input.json", "author01-essay-evidence-seed-v2.json"),
        ("m19-questionnaire-authoring.json", "m19-questionnaire-evidence-seed-v3.json"),
    ]:
        author = parse_json((docs / name).read_bytes())
        author["seed"]["sha256"] = sha256((docs / seed_name).read_bytes()).hexdigest()
        write(docs / name, author)
    approval = parse_json((docs / "m19-design-approval.json").read_bytes())
    approval["base_inputs"] = {
        n: sha256((docs / n).read_bytes()).hexdigest() for n in approval["base_inputs"]
    }
    approval["approved_seed_sha256"] = sha256(
        (docs / "m19-questionnaire-evidence-seed-v3.json").read_bytes()
    ).hexdigest()
    write(docs / "m19-design-approval.json", approval)
    pin = parse_json((docs / "m19-source-review-pin-v3.json").read_bytes())
    pin["bundle_sha256"] = approval["approved_seed_sha256"]
    write(docs / "m19-source-review-pin-v3.json", pin)
    review = parse_json((docs / "m19-source-review.json").read_bytes())
    review["seed_sha256"] = approval["approved_seed_sha256"]
    write(docs / "m19-source-review.json", review)
    approve_synthetic_edit(docs)
    return docs, pdfs


def test_other_school_and_one_semantic_field_generate_without_special_branch(other_compiler_case):
    before, snapshot, _ = compile_case(other_compiler_case)
    assert snapshot.plan.target.institution_id == "synthetic-campus"
    assert snapshot.plan.topics[-1].topic_id == "synthetic-project-form"
    path = other_compiler_case[0] / "m19-questionnaire-authoring.json"
    author = parse_json(path.read_bytes())
    next(c for c in author["claims"] if c["field"] == "material_name")["value"]["zh"] = "合成审核表"
    write(path, author)
    approve_synthetic_edit(other_compiler_case[0])
    after, _, _ = compile_case(other_compiler_case)
    assert parse_json(after["plan.json"])["topics"][-1]["material_name_zh"] == "合成审核表"
    assert "合成审核表" in after["m19-material-presentation.mjs"].decode()
    assert (
        parse_json(before["plan.json"])["topics"][:4]
        == parse_json(after["plan.json"])["topics"][:4]
    )


def test_committed_package_binds_external_inputs_and_projection_without_private_pdf():
    from types import SimpleNamespace
    from jgrad_admission_rag.reasoning.material_slice_report import load_plan
    from scripts import m18_presentation

    _, raws, _, author = compiler.inputs(DOCS)
    output = DOCS / "m19-generated"
    manifest = parse_json((output / "manifest.json").read_bytes())
    assert manifest["input_hashes"] == {n: sha256(r).hexdigest() for n, r in sorted(raws.items())}
    assert manifest["tool_sha256"] == sha256(Path(compiler.__file__).read_bytes()).hexdigest()
    assert (
        manifest["m18_tool_sha256"]
        == sha256(Path(m18_presentation.__file__).read_bytes()).hexdigest()
    )
    for name, expected in manifest["outputs"].items():
        assert sha256((output / name).read_bytes()).hexdigest() == expected
    plan, *_ = load_plan(
        *(
            (output / n).read_bytes()
            for n in [
                "plan.json",
                "plan-trust.json",
                "policy.json",
                "policy-trust.json",
                "seed.json",
            ]
        )
    )
    evidence = (DOCS / "m19-evidence/live-evidence.json").read_bytes()
    snapshot = SimpleNamespace(
        plan=plan,
        seed_raw=(output / "seed.json").read_bytes(),
        presentation=evidence,
        snapshot_id=manifest["snapshot_id"],
    )
    old_author = parse_json(raws["author01-essay-authoring-input.json"])
    old_author["seed"] = deepcopy(author["seed"])
    projected, _ = compiler.projected_catalog(
        snapshot,
        [
            (old_author, parse_json(raws["m18-presentation-build.json"])),
            compiler.author_projection(author),
        ],
        parse_json(raws["m18-migrated-material-displays.json"]),
    )
    module = (output / "m19-material-presentation.mjs").read_bytes()
    assert parse_json(module.decode().split(" = ", 1)[1].removesuffix(";\n").encode()) == projected
    static = (
        DOCS.parents[1] / "src/jgrad_admission_rag/service/static/m19-material-presentation.mjs"
    )
    assert static.read_bytes() == module
