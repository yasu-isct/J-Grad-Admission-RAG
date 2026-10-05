"""Bounded generation tests use only synthetic PDF bytes and isolated metadata."""
# ruff: noqa: F811 -- pytest resolves the imported fixture names by parameter.

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from jgrad_admission_rag.reviewed_source_evidence import canonical_json_bytes, parse_json
from scripts import m18_presentation as generator
from jgrad_admission_rag.reasoning.material_slice_report import load_plan
from tests.test_author01 import synthetic_v2, v2_inputs  # noqa: F401
from tests import test_author01 as author01_tests


DOCS = Path(__file__).resolve().parents[1] / "docs/onboarding"


@pytest.fixture
def presentation_inputs(tmp_path, synthetic_v2):
    raws, plan, _, _, _, _, candidate_files, pdfs = synthetic_v2
    docs = tmp_path / "metadata"
    descriptor = parse_json((DOCS / "m18-presentation-build.json").read_bytes())
    for name in (
        "m18-presentation-build.json",
        "m18-migrated-material-displays.json",
        "author01-reference-workspace-preview-v2.json",
    ):
        (docs / name).write_bytes((DOCS / name).read_bytes())
    author_path = docs / descriptor["authoring"]
    author = parse_json(author_path.read_bytes())
    author["seed"]["sha256"] = sha256(raws[4]).hexdigest()
    author_path.write_bytes(canonical_json_bytes(author))
    candidate = tmp_path / parse_json(candidate_files["candidate.json"])["build_id"]
    pdf_dir = tmp_path / "synthetic-pdfs"
    pdf_dir.mkdir()
    for source in plan.sources:
        (pdf_dir / f"{source.identity.source_pdf_sha256}.pdf").write_bytes(pdfs[source.source_id])
    return docs / "m18-presentation-build.json", candidate, pdf_dir


def catalog(files):
    text = files[generator.MODULE].decode()
    return json.loads(text.split(" = ", 1)[1].removesuffix(";\n"))


def test_full_loader_reproducibility_and_read_only_check(
    presentation_inputs, tmp_path, monkeypatch
):
    descriptor, candidate, pdf_dir = presentation_inputs
    first = generator.build(descriptor, candidate, pdf_dir)
    assert generator.build(descriptor, candidate, pdf_dir) == first
    copy = tmp_path / "other-workspace"
    shutil.copytree(descriptor.parent, copy)
    assert generator.build(copy / descriptor.name, candidate, pdf_dir) == first
    entry = catalog(first)["entries"][0]
    assert len(entry["topics"]) == 4
    essay = entry["topics"][-1]
    assert essay["display"][:2] == ["申请小论文", "小論文"]
    assert essay["guide"]["steps"][1] == "第一部分：写明希望研究的主题，以及对该主题感兴趣的理由。"
    assert sum(len(r["fragments"]) for t in entry["topics"] for r in t["records"]) == 37
    assert [t["preparation_control"] for t in entry["topics"]] == [
        None,
        None,
        None,
        "self_report_tri_state",
    ]
    assert sum(map(len, first.values())) < 1024**2
    output = tmp_path / "generated"
    generator.write_or_check(first, output)
    state = {path: path.stat().st_mtime_ns for path in output.iterdir()}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("check must not write")

    monkeypatch.setattr(Path, "write_bytes", forbidden)
    generator.write_or_check(generator.build(descriptor, candidate, pdf_dir), output, check=True)
    assert state == {path: path.stat().st_mtime_ns for path in output.iterdir()}


@pytest.mark.parametrize("filename", generator.FILES)
def test_output_drift_rejected(presentation_inputs, tmp_path, filename):
    files = generator.build(*presentation_inputs)
    generator.write_or_check(files, tmp_path)
    (tmp_path / filename).write_bytes(files[filename] + b" ")
    with pytest.raises(ValueError, match="drift"):
        generator.write_or_check(files, tmp_path, check=True)


@pytest.mark.parametrize(
    "mutation",
    [
        "school",
        "year",
        "route",
        "intake",
        "claim",
        "context",
        "mapping",
        "duplicate",
        "alias",
        "seed_hash",
    ],
)
def test_invalid_authoring_or_mapping_rejected(presentation_inputs, mutation):
    descriptor_path, candidate, pdf_dir = presentation_inputs
    descriptor = parse_json(descriptor_path.read_bytes())
    author_path = descriptor_path.parent / descriptor["authoring"]
    author = parse_json(author_path.read_bytes())
    if mutation == "school":
        author["target"]["institution_id"] = "synthetic-wrong"
    elif mutation == "year":
        author["target"]["admission_cycle"] = 2030
    elif mutation == "route":
        author["target"]["selection_route_id"] = "synthetic-wrong"
    elif mutation == "intake":
        author["target"]["intake"]["month"] = 10
    elif mutation == "claim":
        author["claims"][0]["fragment_ids"] = ["missing"]
    elif mutation == "context":
        author["required_context"]["E09"].remove("E09-3")
    elif mutation == "mapping":
        descriptor["guide_bindings"].pop("guide.preparation.0")
    elif mutation == "seed_hash":
        author["seed"]["sha256"] = "0" * 64
    else:
        path = descriptor_path.parent / descriptor["displays"]
        displays = parse_json(path.read_bytes())
        if mutation == "duplicate":
            displays["materials"].append(displays["materials"][0])
        else:
            author["material_code"] = "english_score_sheet"
        path.write_bytes(canonical_json_bytes(displays))
    author_path.write_bytes(canonical_json_bytes(author))
    descriptor_path.write_bytes(canonical_json_bytes(descriptor))
    with pytest.raises(ValueError):
        generator.build(descriptor_path, candidate, pdf_dir)


def test_changed_author_input_changes_manifest_and_one_guide(presentation_inputs, tmp_path):
    before = generator.build(*presentation_inputs)
    descriptor = presentation_inputs[0]
    author_path = descriptor.parent / "author01-essay-authoring-input.json"
    author = parse_json(author_path.read_bytes())
    author["guide"]["preparation"][0] = "合成验证：仅修改这一处指南。"
    author_path.write_bytes(canonical_json_bytes(author))
    after = generator.build(*presentation_inputs)
    assert (
        catalog(after)["entries"][0]["topics"][-1]["guide"]["steps"][0]
        == "合成验证：仅修改这一处指南。"
    )
    assert (
        catalog(before)["entries"][0]["topics"][:-1] == catalog(after)["entries"][0]["topics"][:-1]
    )
    assert (
        parse_json(before[generator.MANIFEST])["content_id"]
        != parse_json(after[generator.MANIFEST])["content_id"]
    )
    generator.write_or_check(before, tmp_path)
    with pytest.raises(ValueError, match="drift"):
        generator.write_or_check(after, tmp_path, check=True)


def test_changed_candidate_cannot_generate(presentation_inputs):
    candidate = presentation_inputs[1] / "lineage.json"
    candidate.write_bytes(candidate.read_bytes() + b" ")
    with pytest.raises(ValueError):
        generator.build(*presentation_inputs)


@pytest.fixture
def synthetic_other(tmp_path, monkeypatch, v2_inputs):
    """A different, wholly synthetic school/topic/source via the full existing loader."""
    replacements = {
        "utokyo": "synthetic-campus",
        "utokyo-gsfs": "synthetic-grad",
        "utokyo-gsfs-complex": "synthetic-program",
        "utokyo-gsfs-complex-master-2027-general-a-202704": "synthetic-target",
        "utokyo-gsfs-complex-master-2027-general-a-202704-s1": "synthetic-source-set",
        "utokyo-gsfs-complex-2027-material-evidence": "synthetic-bundle",
        "complex-master-a-additional": "synthetic-b-additional",
        "complex-guide-2027-revised": "synthetic-a-guide",
        "gsfs-master-2027": "synthetic-c-common",
        "application-essay": "synthetic-writing",
        "application_essay": "synthetic_writing",
        "申请小论文": "合成练习说明",
        "小論文": "合成原文",
    }
    originals = tmp_path / "synthetic-originals"
    originals.mkdir()
    names = (
        "reviewed-fragment-import-v1.json",
        "material-condition-policy-v1.json",
        "material-slice-report-plan-v1.json",
        "author01-source-review.json",
        "author01-essay-authoring-input.json",
    )
    for name in names:
        value = author01_tests._rewrite(parse_json((DOCS / name).read_bytes()), replacements)
        (originals / name).write_bytes(canonical_json_bytes(value))
    input_raws = tuple(
        canonical_json_bytes(author01_tests._rewrite(parse_json(raw), replacements))
        for raw in v2_inputs[0]
    )
    changed_seed = parse_json(input_raws[0])
    changed_seed["source_manifest"]["sha256"] = sha256(input_raws[1]).hexdigest()
    changed_seed["target_contract"]["sha256"] = sha256(input_raws[2]).hexdigest()
    input_raws = (canonical_json_bytes(changed_seed), *input_raws[1:])
    metadata_hashes = {
        sha256(v2_inputs[0][i]).hexdigest(): sha256(input_raws[i]).hexdigest() for i in (1, 2)
    }
    for name in names:
        path = originals / name
        path.write_bytes(
            canonical_json_bytes(
                author01_tests._rewrite(parse_json(path.read_bytes()), metadata_hashes)
            )
        )
    # This historical helper operates only on isolated synthetic bytes here. No
    # real pin or candidate is overwritten/published.
    monkeypatch.setattr(author01_tests, "DOCS", originals)
    isolated = tmp_path / "other"
    isolated.mkdir()
    fixture = author01_tests.synthetic_v2.__wrapped__(
        isolated, monkeypatch, (input_raws, *v2_inputs[1:])
    )
    raws, plan, _, _, _, _, candidate_files, pdfs = fixture
    docs = isolated / "metadata"
    for name in (
        "m18-presentation-build.json",
        "m18-migrated-material-displays.json",
        "author01-reference-workspace-preview-v2.json",
    ):
        (docs / name).write_bytes((DOCS / name).read_bytes())
    author_path = docs / "author01-essay-authoring-input.json"
    author = parse_json(author_path.read_bytes())
    author["seed"]["sha256"] = sha256(raws[4]).hexdigest()
    author_path.write_bytes(canonical_json_bytes(author))
    template_path = docs / "author01-reference-workspace-preview-v2.json"
    template = parse_json(template_path.read_bytes())
    template["slices"][0].update(
        slice_id="synthetic-preview",
        institution_name="合成学校（验证专用）",
        organization_name="合成研究科",
        program_name="合成专攻",
    )
    template_path.write_bytes(canonical_json_bytes(template))
    candidate = isolated / parse_json(candidate_files["candidate.json"])["build_id"]
    pdf_dir = isolated / "synthetic-pdfs"
    pdf_dir.mkdir()
    for source in plan.sources:
        (pdf_dir / f"{source.identity.source_pdf_sha256}.pdf").write_bytes(pdfs[source.source_id])
    inputs = docs / "m18-presentation-build.json", candidate, pdf_dir
    return inputs, generator.load_snapshot(*inputs)


def test_different_synthetic_school_topic_and_sources_need_no_js_branch(synthetic_other):
    inputs, snapshot = synthetic_other
    files = generator.build(*inputs)
    entry = catalog(files)["entries"][0]
    assert entry["target"]["institution_id"] == "synthetic-campus"
    own = entry["topics"][-1]
    assert own["id"] == "synthetic-writing"
    assert own["display"][0] == "合成练习说明"
    assert own["records"][0]["source_id"] == "synthetic-b-additional"
    assert snapshot.plan.target.institution_id == "synthetic-campus"


def test_committed_projection_and_manifest_match_reviewed_inputs_without_private_assets():
    """Saved audited response closes CI display drift; full loader is tested above."""
    raws = tuple((DOCS / name).read_bytes() for name in author01_tests.PLAN_NAMES)
    plan, *_ = load_plan(*raws)
    evidence_raw = (DOCS / "author01-evidence/live-evidence.json").read_bytes()
    evidence = parse_json(evidence_raw)
    snapshot = SimpleNamespace(
        plan=plan, seed_raw=raws[4], presentation=evidence_raw, snapshot_id=evidence["snapshot_id"]
    )
    descriptor = parse_json((DOCS / "m18-presentation-build.json").read_bytes())
    value, _ = generator.project(
        snapshot,
        parse_json((DOCS / descriptor["authoring"]).read_bytes()),
        parse_json((DOCS / descriptor["displays"]).read_bytes()),
        descriptor,
    )
    static = DOCS.parents[1] / "src/jgrad_admission_rag/service/static"
    files = {name: (static / name).read_bytes() for name in generator.FILES}
    assert catalog(files) == value
    manifest = parse_json(files[generator.MANIFEST])
    assert (
        manifest["snapshot_id"]
        == "a729b19705be68c9a4e79bc71d6dbaaed12710989aeac79b90cf34347bf89164"
    )
    for name, expected in manifest["outputs"].items():
        assert sha256(files[name]).hexdigest() == expected
    for field, name in descriptor["metadata"].items():
        assert manifest["input_hashes"][field] == sha256((DOCS / name).read_bytes()).hexdigest()
    for field, name in (
        ("descriptor", "m18-presentation-build.json"),
        ("authoring", descriptor["authoring"]),
        ("displays", descriptor["displays"]),
    ):
        assert manifest["input_hashes"][field] == sha256((DOCS / name).read_bytes()).hexdigest()
