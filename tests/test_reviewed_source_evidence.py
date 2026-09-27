from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import socket
import subprocess

import pymupdf
import pytest

from jgrad_admission_rag.reviewed_evidence_cli import main
from jgrad_admission_rag.reviewed_source_evidence import (
    Bundle,
    EvidenceError,
    Trust,
    canonical_bundle_bytes,
    canonical_json_bytes,
    inspect_evidence,
    load_evidence_bytes,
    render_markdown,
)


DOCS = Path(__file__).resolve().parents[1] / "docs" / "onboarding"


@pytest.fixture
def seed():
    return json.loads((DOCS / "gsfs-material-evidence-seed-v1.json").read_bytes())


def encode_inputs(bundle, manifest, contract):
    manifest_raw = canonical_json_bytes(manifest)
    contract_raw = canonical_json_bytes(contract)
    bundle["source_manifest"]["sha256"] = sha256(manifest_raw).hexdigest()
    bundle["target_contract"]["sha256"] = sha256(contract_raw).hexdigest()
    raw = canonical_json_bytes(bundle)
    return raw, dict(
        manifest_bytes=manifest_raw,
        target_contract_bytes=contract_raw,
        trust=Trust(
            bundle_id=bundle["bundle_id"],
            revision=bundle["revision"],
            bundle_sha256=sha256(raw).hexdigest(),
        ),
    )


@pytest.fixture
def synthetic(seed, tmp_path):
    """A second school, unrelated topic/record/source IDs, through the same path."""
    bundle = deepcopy(seed)
    bundle["bundle_id"] = "second-school-evidence"
    bundle["target"].update(
        institution_id="second",
        organization_id="second-grad",
        program_id="second-program",
        target_id="second-target",
    )
    bundle["source_set"] = {"source_set_id": "second-source-set", "revision": 3}
    bundle["topics"] = [{"topic_id": "portfolio", "title_zh": "作品集", "record_ids": ["S1"]}]
    record = deepcopy(bundle["records"][0])
    record.update(
        record_id="S1",
        topic_id="portfolio",
        source_id="second-source",
        physical_page=1,
        fragments=[
            {"fragment_id": "S1-c", "role": "context", "text": "修士"},
            {"fragment_id": "S1-1", "role": "clause", "text": "原本は不要。"},
        ],
        required_fragment_ids=["S1-c", "S1-1"],
    )
    pdf = pymupdf.open()
    pdf.new_page()
    pdf_raw = pdf.tobytes()
    pdf.close()
    record["source_pdf_sha256"] = sha256(pdf_raw).hexdigest()
    bundle["records"] = [record]
    bundle["relations"] = []
    bundle["required_source_ids"] = ["second-source"]
    source = {
        "source_id": "second-source",
        "sha256": record["source_pdf_sha256"],
        "physical_page_count": 1,
        "official_url": "https://second.example/admission.pdf",
    }
    conditional = {**source, "source_id": "conditional-unused"}
    manifest = {"sources": [source, conditional]}
    contract = {
        "target": deepcopy(bundle["target"]),
        "source_set": {
            **bundle["source_set"],
            "target_id": bundle["target"]["target_id"],
            "members": [
                {
                    "source_id": s["source_id"],
                    "source_pdf_sha256": s["sha256"],
                    "physical_page_count": 1,
                    "requirement": requirement,
                }
                for s, requirement in ((source, "core"), (conditional, "conditional"))
            ],
        },
    }
    path = tmp_path / "explicit.pdf"
    path.write_bytes(pdf_raw)
    return bundle, manifest, contract, {"second-source": path}


def inspect_synthetic(inputs, **overrides):
    bundle, manifest, contract, paths = inputs
    raw, bindings = encode_inputs(bundle, manifest, contract)
    request = dict(
        target=bundle["target"],
        source_set=bundle["source_set"],
        topic_id=bundle["topics"][0]["topic_id"],
        source_paths=paths,
    )
    request.update(overrides)
    return inspect_evidence(raw, **bindings, **request)


def test_real_seed_canonical_roundtrip_and_pin(seed):
    bundle = Bundle.model_validate(seed)
    raw = canonical_bundle_bytes(bundle)
    assert raw.endswith(b"\n") and b"\r\n" not in raw
    assert raw == canonical_bundle_bytes(Bundle.model_validate_json(raw))
    assert raw == canonical_json_bytes(dict(reversed(list(seed.items()))))
    trust = Trust.model_validate_json((DOCS / "evid01-review-pin.json").read_bytes())
    evidence = load_evidence_bytes(
        (DOCS / "gsfs-material-evidence-seed-v1.json").read_bytes(),
        trust=trust,
        manifest_bytes=(DOCS / seed["source_manifest"]["file"]).read_bytes(),
        target_contract_bytes=(DOCS / seed["target_contract"]["file"]).read_bytes(),
    )
    assert len(evidence.bundle.records) == 8


def test_pure_loader_has_no_io(synthetic, monkeypatch):
    bundle, manifest, contract, _ = synthetic
    raw, bindings = encode_inputs(bundle, manifest, contract)

    def fail(*args, **kwargs):
        pytest.fail("pure load attempted I/O")

    monkeypatch.setattr("builtins.open", fail)
    monkeypatch.setattr(Path, "open", fail)
    monkeypatch.setattr(pymupdf, "open", fail)
    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(subprocess, "Popen", fail)
    assert load_evidence_bytes(raw, **bindings).bundle.target.institution_id == "second"


def test_second_school_fresh_read_only_audit_and_preview(synthetic, monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("query invoked a forbidden downstream operation")

    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(subprocess, "Popen", fail)
    monkeypatch.setattr(pymupdf.Page, "get_text", fail)
    monkeypatch.setattr(pymupdf.Page, "get_pixmap", fail)
    for module, name in (
        ("jgrad_admission_rag.builder.extractor", "extract_pdf"),
        ("jgrad_admission_rag.builder.kb_builder", "build_document_kb"),
    ):
        monkeypatch.setattr(f"{module}.{name}", fail)
    before = {p: p.read_bytes() for p in synthetic[3].values()}
    # A conditional path, even if explicitly supplied, must not be read.
    synthetic[3]["conditional-unused"] = Path("not-present.pdf")
    preview = inspect_synthetic(synthetic)
    assert preview == inspect_synthetic(synthetic)
    assert preview["status"] == "source_identity_verified"
    assert preview["records"][0]["official_url"].endswith("#page=1")
    assert len(preview["source_audit"]) == 1
    markdown = render_markdown(preview)
    assert "原本は不要。" in markdown and "中文审核注释（非官方引文）" in markdown
    assert all(p.read_bytes() == raw for p, raw in before.items())
    synthetic[3]["second-source"].write_bytes(b"changed after first successful call")
    with pytest.raises(EvidenceError, match="source bytes changed"):
        inspect_synthetic(synthetic)


@pytest.mark.parametrize(
    "field",
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
@pytest.mark.parametrize("change", ["different", "missing", "null"])
def test_every_target_dimension_is_required(synthetic, field, change):
    target = deepcopy(synthetic[0]["target"])
    container = target
    if field.startswith("intake."):
        container = target["intake"]
        field = field.split(".")[1]
    if change == "missing":
        del container[field]
    elif change == "null":
        container[field] = None
    else:
        container[field] = container[field] + 1 if isinstance(container[field], int) else "other"
    with pytest.raises(EvidenceError) as error:
        inspect_synthetic(synthetic, target=target)
    assert error.value.code == "not_covered"


@pytest.mark.parametrize(
    "overrides",
    [
        {"topic_id": "unknown"},
        {"source_set": {"source_set_id": "second-source-set", "revision": 2}},
        {"source_set": {"source_set_id": "other", "revision": 3}},
        {"source_set": {}},
    ],
)
def test_uncovered_never_audits(synthetic, overrides, monkeypatch):
    monkeypatch.setattr(
        "jgrad_admission_rag.reviewed_source_evidence.audit_sources",
        lambda *args: pytest.fail("uncovered request must not audit"),
    )
    with pytest.raises(EvidenceError) as error:
        inspect_synthetic(synthetic, **overrides)
    assert error.value.code == "not_covered"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b["records"].append(deepcopy(b["records"][0])),
        lambda b: b["records"][0]["fragments"].pop(0),
        lambda b: b["records"][0]["fragments"][0].update(text="  "),
        lambda b: b["records"][0]["fragments"].append(deepcopy(b["records"][0]["fragments"][0])),
        lambda b: b["records"][0].update(physical_page=True),
        lambda b: b["records"][0].update(physical_page=0),
        lambda b: b["records"][0].update(physical_page="1"),
        lambda b: b["records"][0].update(parser_locator="fake"),
        lambda b: b["records"][0].update(bbox=[1, 2, 3, 4]),
        lambda b: b["records"][0].update(fact_id="fake"),
        lambda b: b["records"][0].update(source_pdf_sha256="0" * 64),
        lambda b: b["records"][0].update(review_record_id="missing"),
        lambda b: b["records"][0].update(topic_id="missing"),
        lambda b: b["topics"][0]["record_ids"].append("S1"),
        lambda b: b["topics"][0]["record_ids"].append("missing"),
        lambda b: b["relations"].append({"from": "S1", "kind": "context", "to": "missing"}),
        lambda b: b.update(required_source_ids=[]),
        lambda b: b["review_records"][0].update(method=""),
        lambda b: b["target"].update(institution_id="other"),
        lambda b: b["source_set"].update(revision=1),
    ],
)
def test_invalid_contract_even_with_new_pin(synthetic, mutation):
    mutation(synthetic[0])
    with pytest.raises(EvidenceError) as error:
        inspect_synthetic(synthetic)
    assert error.value.code == "invalid_schema"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b["records"][0]["fragments"][1].update(text="原本は必要。"),
        lambda b: b["records"][0].update(physical_page=2),
        lambda b: b["records"][0].update(printed_page_label="99"),
        lambda b: b["records"][0]["fragments"].pop(0),
        lambda b: b["records"][0].update(review_note_zh="changed"),
        lambda b: b["relations"].append({"from": "S1", "kind": "fake", "to": "S1"}),
        lambda b: b["source_set"].update(revision=4),
        lambda b: b["review_records"][0].update(reviewer_kind="human"),
    ],
)
def test_any_reviewed_content_change_breaks_old_pin(synthetic, mutation):
    bundle, manifest, contract, _ = synthetic
    _, bindings = encode_inputs(bundle, manifest, contract)
    mutation(bundle)
    with pytest.raises(EvidenceError) as error:
        load_evidence_bytes(canonical_json_bytes(bundle), **bindings)
    assert error.value.code == "digest_mismatch"


def test_whitespace_and_metadata_bytes_are_pinned(synthetic):
    bundle, manifest, contract, _ = synthetic
    raw, bindings = encode_inputs(bundle, manifest, contract)
    with pytest.raises(EvidenceError) as error:
        load_evidence_bytes(raw + b" ", **bindings)
    assert error.value.code == "digest_mismatch"
    for key in ("manifest_bytes", "target_contract_bytes"):
        changed = {**bindings, key: bindings[key] + b" "}
        with pytest.raises(EvidenceError) as error:
            load_evidence_bytes(raw, **changed)
        assert error.value.code == "binding_digest_mismatch"
    changed = {**bindings, "trust": bindings["trust"].model_copy(update={"revision": 99})}
    with pytest.raises(EvidenceError) as error:
        load_evidence_bytes(raw, **changed)
    assert error.value.code == "revision_mismatch"


@pytest.mark.parametrize(
    "case,code",
    [
        ("missing", "missing_source"),
        ("absent", "missing_source"),
        ("hash", "source_hash_mismatch"),
        ("page", "page_out_of_range"),
        ("count", "page_count_mismatch"),
        ("pdf", "invalid_pdf"),
        ("members", "invalid_schema"),
    ],
)
def test_audit_failure_codes(synthetic, case, code):
    bundle, manifest, contract, paths = synthetic
    if case == "missing":
        paths.clear()
    elif case == "absent":
        paths["second-source"] = Path("absent.pdf")
    elif case == "hash":
        paths["second-source"].write_bytes(b"changed")
    elif case == "page":
        bundle["records"][0]["physical_page"] = 2
    elif case == "count":
        manifest["sources"][0]["physical_page_count"] = 2
        contract["source_set"]["members"][0]["physical_page_count"] = 2
    elif case == "members":
        contract["source_set"]["members"].pop()
    else:
        raw = b"not a PDF"
        paths["second-source"].write_bytes(raw)
        digest = sha256(raw).hexdigest()
        bundle["records"][0]["source_pdf_sha256"] = digest
        manifest["sources"][0]["sha256"] = digest
        contract["source_set"]["members"][0]["source_pdf_sha256"] = digest
    with pytest.raises(EvidenceError) as error:
        inspect_synthetic(synthetic)
    assert error.value.code == code


def test_cli_success_then_stale_input_emits_only_error(synthetic, tmp_path, capsys):
    bundle, manifest, contract, paths = synthetic
    raw, bindings = encode_inputs(bundle, manifest, contract)
    files = {
        "bundle": raw,
        "manifest": bindings["manifest_bytes"],
        "target-contract": bindings["target_contract_bytes"],
        "trust": canonical_json_bytes(bindings["trust"].model_dump(mode="json")),
        "request": canonical_json_bytes(
            {"target": bundle["target"], "source_set": bundle["source_set"]}
        ),
    }
    argv = []
    for name, content in files.items():
        path = tmp_path / f"{name}.json"
        path.write_bytes(content)
        argv.extend([f"--{name}", str(path)])
    argv.extend(
        [
            "--topic",
            "portfolio",
            "--source",
            f"second-source={paths['second-source']}",
            "--format",
            "json",
        ]
    )
    assert main(argv) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["records"][0]["fragments"][1]["text"] == "原本は不要。"
    assert output.err == ""
    (tmp_path / "bundle.json").write_bytes(raw + b" ")
    assert main(argv) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"status": "digest_mismatch", "preview": None}
