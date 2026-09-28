from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from pydantic import ValidationError

from jgrad_admission_rag.reviewed_fragment_import import (
    Candidate,
    ImportError,
    ImportTrust,
    Lineage,
    load_inputs,
    map_candidate,
    publish_candidate,
    read_context,
    validate_candidate,
)
from jgrad_admission_rag.reviewed_source_evidence import (
    EvidenceError,
    canonical_json_bytes,
    parse_json,
)
from jgrad_admission_rag.schemas.document_kb import load_document_kb_bytes


DOCS = Path(__file__).resolve().parents[1] / "docs" / "onboarding"


@pytest.fixture
def inputs():
    raws = tuple(
        (DOCS / name).read_bytes()
        for name in (
            "gsfs-material-evidence-seed-v1.json",
            "utokyo-gsfs-complex-2027.sources.json",
            "gsfs-source-set-contract-v0.1.examples.json",
            "reviewed-fragment-import-v1.json",
        )
    )
    trust = ImportTrust.model_validate(
        parse_json((DOCS / "reviewed-fragment-import-trust-v1.json").read_bytes())
    )
    evidence, config = load_inputs(*raws, trust)
    return raws, trust, evidence, config


def test_real_seed_maps_exact_fragments_and_context_without_pdf_io(inputs, monkeypatch):
    raws, _, evidence, config = inputs

    def no_pdf(*_args, **_kwargs):
        pytest.fail("pure mapping attempted PDF audit")

    monkeypatch.setattr("jgrad_admission_rag.reviewed_fragment_import.audit_sources", no_pdf)
    files = map_candidate(evidence, config, *raws[1:])
    assert len(files) == 5 and sum(map(len, files.values())) < 8 * 1024 * 1024
    assert files == map_candidate(evidence, config, *raws[1:])
    candidate = Candidate.model_validate(parse_json(files["candidate.json"]))
    lineage = Lineage.model_validate(parse_json(files["lineage.json"]))
    assert (
        candidate.build_id == sha256(canonical_json_bytes(candidate.input_descriptor)).hexdigest()
    )
    assert len(lineage.records) == 8 and len(lineage.relations) == 5
    assert [doc.fact_count for doc in lineage.documents] == [12, 9, 2]
    assert sum(doc.fact_count for doc in lineage.documents) == 23
    source_fragments = {
        fragment.fragment_id: (record, fragment)
        for record in evidence.bundle.records
        for fragment in record.fragments
    }
    facts = {}
    for doc in candidate.documents:
        kb = load_document_kb_bytes(files[doc.relative_path])
        assert kb.manifest.identity == next(
            row.identity for row in config.documents if row.source_id == doc.document_id
        )
        assert kb.entities == [] and len(kb.facts) == len(kb.retrieval_units)
        assert not kb.diagnostics.quality_gate.passed
        assert {item.metric for item in kb.diagnostics.quality_gate.violations} == {
            "missing_section_paths",
            "unknown_scope_facts",
        }
        assert kb.diagnostics.raw_reference_occurrence_count == 0
        assert kb.diagnostics.reference_claim_count == 0
        for fact, unit in zip(kb.facts, kb.retrieval_units, strict=True):
            fragment_id = fact.metadata["fragment_id"]
            record, fragment = source_fragments[fragment_id]
            assert fact.text == fragment.text and fact.source_pages == [record.physical_page]
            assert fact.fact_id == (
                f"fact:reviewed:{record.source_id}:{record.record_id}:"
                f"r{record.revision}:{fragment_id}"
            )
            assert fact.scope_type == "unknown" and fact.scope_targets == []
            assert fact.section_path == [] and fact.evidence == []
            assert unit.fact_id == fact.fact_id and unit.source_pages == fact.source_pages
            facts[fact.fact_id] = fact
    assert len(facts) == 23
    assert all(
        len(relation.from_facts) > 0 and len(relation.to_facts) > 0
        for relation in lineage.relations
    )


def test_wrong_pin_config_target_and_missing_context_fail_closed(inputs):
    raws, trust, _, _ = inputs
    with pytest.raises(ImportError):
        load_inputs(*raws[:3], raws[3] + b" ", trust)
    changed = list(raws)
    config = parse_json(raws[3])
    config["target"]["program_id"] = "wrong"
    changed[3] = canonical_json_bytes(config)
    changed_trust = trust.model_copy(
        update={"import_config_sha256": sha256(changed[3]).hexdigest()}
    )
    with pytest.raises(ImportError):
        load_inputs(*changed, changed_trust)
    tampered = parse_json(raws[0])
    tampered["records"][0]["required_fragment_ids"].pop()
    changed[0] = canonical_json_bytes(tampered)
    changed_trust = changed_trust.model_copy(
        update={"bundle_sha256": sha256(changed[0]).hexdigest()}
    )
    with pytest.raises((EvidenceError, ImportError)):
        load_inputs(*changed, changed_trust)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        parse_json(b'{"schema_version":"1.0","schema_version":"1.0"}')
    config = parse_json(raws[3])
    config["production_enabled"] = 0
    changed_config = canonical_json_bytes(config)
    changed_trust = trust.model_copy(
        update={"import_config_sha256": sha256(changed_config).hexdigest()}
    )
    with pytest.raises(ImportError):
        load_inputs(*raws[:3], changed_config, changed_trust)
    config = parse_json(raws[3])
    config["documents"][0]["identity"]["source_pdf_sha256"] = "0" * 64
    changed_config = canonical_json_bytes(config)
    changed_trust = trust.model_copy(
        update={"import_config_sha256": sha256(changed_config).hexdigest()}
    )
    with pytest.raises(ImportError):
        load_inputs(*raws[:3], changed_config, changed_trust)
    config = parse_json(raws[3])
    config["documents"][0]["identity"]["document_family_id"] = "wrong-family"
    changed_config = canonical_json_bytes(config)
    changed_trust = trust.model_copy(
        update={"import_config_sha256": sha256(changed_config).hexdigest()}
    )
    with pytest.raises(ImportError):
        load_inputs(*raws[:3], changed_config, changed_trust)


def test_metadata_change_changes_build_identity_and_lineage_rejects_forgery(inputs):
    raws, trust, evidence, config = inputs
    baseline = map_candidate(evidence, config, *raws[1:])
    changed = parse_json(raws[3])
    changed["documents"][0]["identity"]["official_title"] += "（改訂）"
    config_raw = canonical_json_bytes(changed)
    changed_trust = trust.model_copy(
        update={"import_config_sha256": sha256(config_raw).hexdigest()}
    )
    _, changed_config = load_inputs(*raws[:3], config_raw, changed_trust)
    modified = map_candidate(evidence, changed_config, *raws[1:3], config_raw)
    assert Candidate.model_validate(parse_json(baseline["candidate.json"])).build_id != (
        Candidate.model_validate(parse_json(modified["candidate.json"])).build_id
    )
    lineage = parse_json(baseline["lineage.json"])
    lineage["records"][0]["fragments"][0]["qualified_fact"]["kb_sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        Lineage.model_validate(lineage)
    lineage = parse_json(baseline["lineage.json"])
    lineage["relations"][0]["to_facts"].pop()
    with pytest.raises(ValidationError):
        Lineage.model_validate(lineage)
    lineage = parse_json(baseline["lineage.json"])
    lineage["records"][0]["physical_page"] = True
    with pytest.raises(ValidationError):
        Lineage.model_validate(lineage)
    candidate = parse_json(baseline["candidate.json"])
    candidate["documents"][0]["relative_path"] = "../outside.json"
    with pytest.raises(ValidationError):
        Candidate.model_validate(candidate)


def test_candidate_validation_and_bidirectional_context(inputs, tmp_path, monkeypatch):
    raws, _, evidence, config = inputs
    monkeypatch.setattr(
        "jgrad_admission_rag.reviewed_fragment_import.audit_sources", lambda *_args: []
    )
    paths = {source_id: tmp_path / source_id for source_id in evidence.bundle.required_source_ids}
    root, status, hashes = publish_candidate(
        tmp_path / "candidates", evidence, config, *raws[1:], paths
    )
    assert status == "generated" and len(hashes) == 5
    mtimes = {name: (root / name).stat().st_mtime_ns for name in hashes}
    again, status, again_hashes = publish_candidate(
        tmp_path / "candidates", evidence, config, *raws[1:], paths
    )
    assert again == root and status == "reused" and hashes == again_hashes
    assert mtimes == {name: (root / name).stat().st_mtime_ns for name in hashes}
    lineage = Lineage.model_validate(parse_json((root / "lineage.json").read_bytes()))
    relation = lineage.relations[0]
    left = read_context(root, lineage, relation.from_id)
    right = read_context(root, lineage, relation.to)
    assert {fact.fact_id for fact in left} == {fact.fact_id for fact in right}
    by_fact = read_context(root, lineage, relation.from_facts[0])
    assert {fact.fact_id for fact in by_fact} == {fact.fact_id for fact in left}
    extra = root / "unlisted.txt"
    extra.write_text("x")
    with pytest.raises(ImportError):
        validate_candidate(root, evidence, config, *raws[1:])
    extra.unlink()
    victim = root / next(name for name in hashes if name.endswith("document_kb.json"))
    original = victim.read_bytes()
    victim.unlink()
    with pytest.raises(ImportError):
        validate_candidate(root, evidence, config, *raws[1:])
    victim.write_bytes(original)
    victim.write_bytes(victim.read_bytes() + b" ")
    with pytest.raises(ImportError):
        publish_candidate(tmp_path / "candidates", evidence, config, *raws[1:], paths)


def test_candidate_rejects_symlink(inputs, tmp_path, monkeypatch):
    raws, _, evidence, config = inputs
    monkeypatch.setattr(
        "jgrad_admission_rag.reviewed_fragment_import.audit_sources", lambda *_args: []
    )
    paths = {source_id: tmp_path / source_id for source_id in evidence.bundle.required_source_ids}
    root, _, _ = publish_candidate(tmp_path / "candidates", evidence, config, *raws[1:], paths)
    link = root / "unlisted-link"
    try:
        link.symlink_to(root / "candidate.json")
    except OSError:
        pytest.skip("this Windows host cannot create test symlinks")
    with pytest.raises(ImportError):
        validate_candidate(root, evidence, config, *raws[1:])


def test_concurrent_publish_is_single_immutable_result(inputs, tmp_path, monkeypatch):
    raws, _, evidence, config = inputs
    monkeypatch.setattr(
        "jgrad_admission_rag.reviewed_fragment_import.audit_sources", lambda *_args: []
    )
    paths = {source_id: tmp_path / source_id for source_id in evidence.bundle.required_source_ids}

    def run():
        return publish_candidate(tmp_path / "candidates", evidence, config, *raws[1:], paths)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda _: run(), range(2)))
    assert a[0] == b[0] and a[2] == b[2]
    assert sorted((a[1], b[1])) == ["generated", "reused"]
    assert len(list((tmp_path / "candidates").iterdir())) == 1


def test_missing_or_wrong_pdf_is_rejected_before_candidate_publication(inputs, tmp_path):
    raws, _, evidence, config = inputs
    paths = {
        source_id: tmp_path / f"{source_id}.pdf"
        for source_id in evidence.bundle.required_source_ids
    }
    with pytest.raises(EvidenceError, match="source unavailable"):
        publish_candidate(tmp_path / "candidates", evidence, config, *raws[1:], paths)
    assert not (tmp_path / "candidates").exists()
    for path in paths.values():
        path.write_bytes(b"not a reviewed PDF")
    with pytest.raises(EvidenceError, match="source bytes changed"):
        publish_candidate(tmp_path / "candidates", evidence, config, *raws[1:], paths)
    assert not (tmp_path / "candidates").exists()


def test_second_school_pure_mapping_uses_same_algorithm(inputs):
    raws, _, evidence, _ = inputs
    seed, manifest, contract, config = (deepcopy(parse_json(raw)) for raw in raws)
    seed["bundle_id"] = "second-school-reviewed"
    seed["target"]["institution_id"] = "second"
    seed["source_set"] = {"source_set_id": "second-set", "revision": 2}
    record = seed["records"][0]
    record["source_id"] = "second-guide"
    seed["records"] = [record]
    seed["topics"] = [
        {"topic_id": record["topic_id"], "title_zh": "测试", "record_ids": [record["record_id"]]}
    ]
    seed["relations"] = []
    seed["required_source_ids"] = ["second-guide"]
    manifest["sources"] = [
        dict(
            source_id="second-guide",
            sha256=record["source_pdf_sha256"],
            physical_page_count=30,
            official_url="https://second.example/guide.pdf",
        )
    ]
    contract["target"] = seed["target"]
    contract["source_set"] = dict(
        source_set_id="second-set",
        revision=2,
        target_id=seed["target"]["target_id"],
        members=[
            dict(
                source_id="second-guide",
                source_pdf_sha256=record["source_pdf_sha256"],
                document_family_id="second-family",
                edition_id="2027",
                revision_date=None,
                physical_page_count=30,
                requirement="core",
            )
        ],
    )
    manifest_raw, contract_raw = canonical_json_bytes(manifest), canonical_json_bytes(contract)
    seed["source_manifest"]["sha256"] = sha256(manifest_raw).hexdigest()
    seed["target_contract"]["sha256"] = sha256(contract_raw).hexdigest()
    seed_raw = canonical_json_bytes(seed)
    identity = config["documents"][0]["identity"]
    identity.update(
        document_id="second-guide",
        document_family_id="second-family",
        institution_id="second",
        official_source_url="https://second.example/guide.pdf",
        source_pdf_sha256=record["source_pdf_sha256"],
    )
    config.update(
        bundle_id=seed["bundle_id"],
        bundle_revision=seed["revision"],
        bundle_sha256=sha256(seed_raw).hexdigest(),
        target=seed["target"],
        source_set=seed["source_set"],
        documents=[dict(source_id="second-guide", identity=identity)],
    )
    config_raw = canonical_json_bytes(config)
    trust = ImportTrust(
        bundle_id=seed["bundle_id"],
        revision=seed["revision"],
        bundle_sha256=sha256(seed_raw).hexdigest(),
        import_config_sha256=sha256(config_raw).hexdigest(),
    )
    other_evidence, other_config = load_inputs(
        seed_raw, manifest_raw, contract_raw, config_raw, trust
    )
    files = map_candidate(other_evidence, other_config, manifest_raw, contract_raw, config_raw)
    assert len(files) == 3
    kb = load_document_kb_bytes(files["documents/second-guide/document_kb.json"])
    assert len(kb.facts) == 2 and all(
        f.text in [x.text for x in evidence.bundle.records[0].fragments] for f in kb.facts
    )
