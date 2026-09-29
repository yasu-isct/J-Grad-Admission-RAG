"""Synthetic reference workspace routes; no accepted PDFs or runtime assets are read."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from jgrad_admission_rag.reasoning.material_slice_report import load_plan
from jgrad_admission_rag.reviewed_source_evidence import canonical_json_bytes, parse_json
from jgrad_admission_rag.service import create_app
from jgrad_admission_rag.service.runtime import ServiceSettings
from jgrad_admission_rag.service.demo_requirements import DemoTargetCatalogResponse
from jgrad_admission_rag.service.reference_contracts import ReferenceEvidenceResponse
from tests.test_material_slice_report import make_tiny_synthetic_slice
from tests.test_applicant_report_api import _runtime as legacy_runtime


DOCS = Path(__file__).resolve().parents[1] / "docs" / "onboarding"


def _local_slice(tmp_path, institution_id="utokyo"):
    names = (
        "material-slice-report-plan-v1.json",
        "material-slice-report-trust-v1.json",
        "material-condition-policy-v1.json",
        "material-condition-trust-v1.json",
        "gsfs-material-evidence-seed-v1.json",
    )
    original = tuple((DOCS / name).read_bytes() for name in names)
    reviewed = (original, *load_plan(*original), [])
    raws, plan, _, _, _, _, candidates, pdfs = make_tiny_synthetic_slice(
        reviewed, institution_id=institution_id
    )
    paths = []
    for name, raw in zip(names, raws, strict=True):
        path = tmp_path / name
        path.write_bytes(raw)
        paths.append(path)
    candidate_root = tmp_path / "candidate"
    for name, raw in candidates.items():
        path = candidate_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    pdf_dir = tmp_path / "pdf"
    pdf_dir.mkdir()
    for source in plan.sources:
        (pdf_dir / f"{source.identity.source_pdf_sha256}.pdf").write_bytes(pdfs[source.source_id])
    row = {
        "slice_id": "synthetic-reviewed-slice",
        "institution_name": "合成大学",
        "organization_name": "合成研究科",
        "program_name": "合成专攻",
        "plan_path": str(paths[0]),
        "trust_path": str(paths[1]),
        "policy_path": str(paths[2]),
        "policy_trust_path": str(paths[3]),
        "seed_path": str(paths[4]),
        "candidate_root": str(candidate_root),
        "pdf_dir": str(pdf_dir),
    }
    config_path = tmp_path / "reference.json"
    config_path.write_bytes(canonical_json_bytes({"schema_version": "1.0", "slices": [row]}))
    request = parse_json(
        (
            Path(__file__).parent / "fixtures" / "material_condition_employed_and_retaining.json"
        ).read_bytes()
    )
    return config_path, row, plan, request


@pytest.fixture
def local_slice(tmp_path):
    return _local_slice(tmp_path)


def test_synthetic_reference_catalog_evidence_and_explicit_report(local_slice, monkeypatch):
    config_path, _, plan, request = local_slice
    from jgrad_admission_rag.service import reference_workspace as workspace

    reads = 0
    original = workspace.read_pdf_bytes

    def counted(*args, **kwargs):
        nonlocal reads
        reads += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(workspace, "read_pdf_bytes", counted)
    with TestClient(
        create_app(ServiceSettings(reference_workspace_config_path=config_path))
    ) as client:
        catalog = client.get("/v1/reference-targets")
        assert catalog.status_code == 200
        item = catalog.json()["items"][0]
        assert item["kind"] == "reviewed_material_slice"
        assert item["availability"] == "ready"
        assert item["target"] == plan.target.model_dump(mode="json")
        assert item["program_alias"] == "CBMS"
        assert item["program_display_name"] == "複雑理工学専攻"
        assert reads == 1
        evidence = client.get(f"/v1/reference-slices/{item['entry_id']}/evidence")
        assert evidence.status_code == 200
        assert len(evidence.json()["topics"]) == 1
        assert len(evidence.json()["topics"][0]["records"][0]["fragments"]) == 2
        assert evidence.json()["topics"][0]["relations"] == []
        old_client = deepcopy(evidence.json())
        old_client["topics"][0].pop("relations")
        assert ReferenceEvidenceResponse.model_validate(old_client).topics[0].relations == ()
        bad_relation = deepcopy(evidence.json())
        bad_relation["topics"][0]["relations"] = [
            {
                "from": "outside",
                "kind": "cross_reference",
                "to": bad_relation["topics"][0]["records"][0]["record_id"],
            }
        ]
        with pytest.raises(ValueError, match="outside visible topic"):
            ReferenceEvidenceResponse.model_validate(bad_relation)
        assert reads == 1
        (Path(config_path.parent) / "candidate" / "candidate.json").write_bytes(b"{}")
        report = client.post(f"/v1/reference-slices/{item['entry_id']}/reports", json=request)
        assert report.status_code == 200
        assert report.json()["report"]["status"] == "evaluated"
        assert report.json()["snapshot_id"] == item["snapshot_id"]
        assert "日文官方原文" in report.json()["markdown"]
        assert reads == 1
        changed = deepcopy(request)
        changed["target"]["institution_id"] = "other"
        uncovered = client.post(f"/v1/reference-slices/{item['entry_id']}/reports", json=changed)
        assert uncovered.status_code == 200
        assert uncovered.json()["report"]["status"] == "not_covered"
        assert uncovered.json()["report"]["evidence_inventory"] == []
        changed = deepcopy(request)
        changed["applicant_profile"]["target_application"]["application_route"] = "other"
        mismatch = client.post(f"/v1/reference-slices/{item['entry_id']}/reports", json=changed)
        assert mismatch.status_code == 200
        assert mismatch.json()["report"]["status"] == "target_mismatch"
        assert mismatch.json()["report"]["topic_results"] == []
        assert (
            client.post(
                f"/v1/reference-slices/{item['entry_id']}/reports", json=request | {"evidence": {}}
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/v1/reference-slices/{item['entry_id']}/reports",
                content=b"{{",
                headers={"content-type": "application/json"},
            ).status_code
            == 422
        )
        assert (
            client.get(f"/v1/reference-slices/{item['entry_id']}/evidence?extra=1").status_code
            == 422
        )
        lock = client.app.state.service_state.reference_report_lock
        assert lock.acquire(blocking=False)
        try:
            assert (
                client.post(
                    f"/v1/reference-slices/{item['entry_id']}/reports", json=request
                ).status_code
                == 429
            )
        finally:
            lock.release()
        assert client.get("/v1/reference-slices/unknown/evidence").status_code == 404
        assert client.get("/v1/reference-slices/../evidence").status_code == 404
        assert client.get("/app/reference").status_code == 200
        assert client.get("/app/reference").headers["content-security-policy"]


def test_bad_optional_config_does_not_break_old_service(local_slice):
    config_path, row, _, _ = local_slice
    row = dict(row)
    row["slice_id"] = "same"
    config_path.write_bytes(canonical_json_bytes({"schema_version": "1.0", "slices": [row, row]}))
    with TestClient(
        create_app(ServiceSettings(reference_workspace_config_path=config_path))
    ) as client:
        assert client.get("/v1/health/live").status_code == 200
        assert client.get("/app").status_code == 200
        entries = client.get("/v1/reference-targets").json()["items"]
        assert len(entries) == 1 and entries[0]["availability"] == "unavailable"
        assert client.get("/v1/reference-slices/same/evidence").status_code == 503


def test_second_institution_uses_same_adapter(tmp_path):
    config_path, _, plan, _ = _local_slice(tmp_path, institution_id="second")
    with TestClient(
        create_app(ServiceSettings(reference_workspace_config_path=config_path))
    ) as client:
        item = client.get("/v1/reference-targets").json()["items"][0]
        assert item["availability"] == "ready"
        assert item["target"]["institution_id"] == "second"
        assert item["target"] == plan.target.model_dump(mode="json")
        assert item["program_alias"] is None
        assert (
            len(client.get(f"/v1/reference-slices/{item['entry_id']}/evidence").json()["topics"])
            == 1
        )


def test_old_runtime_without_selectable_targets_is_not_advertised(tmp_path):
    reference_root = tmp_path / "reference"
    reference_root.mkdir()
    config_path, _, _, _ = _local_slice(reference_root)
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    _, settings, dependencies, _ = legacy_runtime(legacy_root)
    settings = ServiceSettings(
        **(settings.model_dump() | {"reference_workspace_config_path": config_path})
    )
    with TestClient(create_app(settings, dependencies)) as client:
        items = client.get("/v1/reference-targets").json()["items"]
        assert {item["kind"] for item in items} == {"reviewed_material_slice"}
        assert client.get("/v1/target-catalog").json()["schools"] == []
        assert client.get("/v1/health/ready").json()["ready"] is True


def test_legacy_catalog_advertises_current_export_without_gsfs_config(tmp_path, monkeypatch):
    from jgrad_admission_rag.service import reference_app

    _, settings, dependencies, _ = legacy_runtime(tmp_path)
    catalog = DemoTargetCatalogResponse.model_validate(
        {
            "schema_version": "1.0",
            "schools": [
                {
                    "school_id": "synthetic-school",
                    "school_name": "合成大学",
                    "degrees": [
                        {
                            "degree_id": "master",
                            "degree_name": "修士课程",
                            "intakes": [
                                {
                                    "document_id": "synthetic-doc",
                                    "year": 2027,
                                    "month": 4,
                                    "intake_name": "2027 年 4 月",
                                    "colleges": [
                                        {
                                            "college_id": "college",
                                            "college_name": "合成学院",
                                            "departments": [
                                                {
                                                    "department_id": "department",
                                                    "department_name": "合成专攻",
                                                    "application_routes": [],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )
    monkeypatch.setattr(reference_app, "_build_demo_target_catalog_response", lambda *_: catalog)
    with TestClient(create_app(settings, dependencies)) as client:
        entries = client.get("/v1/reference-targets").json()["items"]
        assert len(entries) == 1
        assert entries[0]["kind"] == "legacy_applicant"
        assert entries[0]["capabilities"] == {
            "applicant_check": True,
            "evidence_browse": True,
            "reference_report": True,
        }
        assert entries[0]["legacy_catalog"] == catalog.schools[0].model_dump(mode="json")


@pytest.mark.parametrize("mutation", ["extra", "relative", "oversize", "bad_pin", "missing_source"])
def test_bad_reference_inputs_fail_optional_capability(local_slice, mutation):
    config_path, row, _, _ = local_slice
    if mutation == "extra":
        row = dict(row) | {"untrusted_client_path": "C:/fake"}
    elif mutation == "relative":
        row = dict(row) | {"plan_path": "relative-plan.json"}
    elif mutation == "bad_pin":
        Path(row["trust_path"]).write_bytes(b"{}")
    elif mutation == "missing_source":
        (Path(row["candidate_root"]) / "candidate.json").unlink()
    if mutation == "oversize":
        config_path.write_bytes(b" " * (256 * 1024 + 1))
    else:
        config_path.write_bytes(canonical_json_bytes({"schema_version": "1.0", "slices": [row]}))
    with TestClient(
        create_app(ServiceSettings(reference_workspace_config_path=config_path))
    ) as client:
        assert client.get("/v1/health/live").status_code == 200
        assert client.get("/app").status_code == 200
        assert (
            client.get("/v1/reference-targets").json()["items"][0]["availability"] == "unavailable"
        )
