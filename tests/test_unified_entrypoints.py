"""Production launcher and offline wheel must ship the same unified page."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jgrad_admission_rag.service import cli, reference_app
from jgrad_admission_rag.service.demo_requirements import DemoTargetCatalogResponse
from jgrad_admission_rag.service.runtime import ServiceSettings
from tests.test_applicant_report_api import _runtime


ROOT = Path(__file__).resolve().parents[1]


def test_formal_serve_factory_exposes_unified_dependencies_without_slice_config() -> None:
    # Use the actual jgrad-serve factory, not the public service alias.
    client = TestClient(cli.create_app(ServiceSettings()))
    html = client.get("/app")
    assert html.status_code == 200
    assert 'id="school-select"' in html.text
    assert 'id="step-nav-4"' in html.text
    assert 'class="secondary reference-generate"' in html.text
    assert "script-src 'self'" in html.headers["content-security-policy"]
    for path, media_type in (
        ("/assets/unified.js", "text/javascript"),
        ("/assets/unified-core.mjs", "text/javascript"),
        ("/assets/unified.css", "text/css"),
        ("/assets/app.js", "text/javascript"),
        ("/assets/app.css", "text/css"),
        ("/assets/overview.js", "text/javascript"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(media_type)
    catalog = client.get("/v1/reference-targets")
    assert catalog.status_code == 200
    assert catalog.json() == {"schema_version": "1.0", "items": []}
    assert client.get("/app/advanced").text == html.text
    redirect = client.get("/app/reference", follow_redirects=False)
    assert redirect.status_code == 307 and redirect.headers["location"] == "/app"
    client.close()


def test_formal_serve_factory_advertises_legacy_catalog_without_gsfs(
    tmp_path: Path, monkeypatch
) -> None:
    context, settings, dependencies, _ = _runtime(tmp_path)
    assert settings.reference_workspace_config_path is None
    # The tiny applicant-report fixture has no ready vector index. Supply its
    # reviewed target catalog at the adapter boundary without building one.
    identity = context.plan.document_identity
    ready_catalog = DemoTargetCatalogResponse.model_validate(
        {
            "schema_version": "1.0",
            "schools": [
                {
                    "school_id": identity.institution_id,
                    "school_name": identity.institution_name,
                    "degrees": [
                        {
                            "degree_id": "master",
                            "degree_name": "修士课程",
                            "intakes": [
                                {
                                    "document_id": identity.document_id,
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
    monkeypatch.setattr(
        reference_app,
        "_build_demo_target_catalog_response",
        lambda *_: ready_catalog,
    )
    with TestClient(cli.create_app(settings, dependencies)) as client:
        catalog = client.get("/v1/reference-targets")
        assert catalog.status_code == 200
        entries = catalog.json()["items"]
        assert len(entries) == 1
        assert entries[0]["kind"] == "legacy_applicant"
        assert entries[0]["legacy_catalog"]["school_id"] == identity.institution_id


def test_formal_serve_parser_accepts_optional_reference_configuration(tmp_path: Path) -> None:
    args = cli._parser().parse_args(
        [
            "--corpus-root",
            str(tmp_path),
            "--manifest",
            str(tmp_path / "corpus.json"),
            "--policy",
            str(tmp_path / "policy.json"),
            "--provider",
            "deterministic-fake",
            "--reference-workspace-config",
            str(tmp_path / "reference.json"),
        ]
    )
    assert args.reference_workspace_config == str(tmp_path / "reference.json")


def test_offline_wheel_contains_unified_static_dependency_closure(tmp_path: Path) -> None:
    static = ROOT / "src/jgrad_admission_rag/service/static"
    html = (static / "advanced.html").read_text(encoding="utf-8")
    script = (static / "app.js").read_text(encoding="utf-8")
    resources = re.findall(r"/(assets/[^\"']+)", html)
    imports = re.findall(r'import\("/(assets/[^\"]+)"\)', script)
    assert "recursive-include src/jgrad_admission_rag/service/static *.mjs" in (
        ROOT / "MANIFEST.in"
    ).read_text(encoding="utf-8")
    for resource in resources:
        assert (static / resource.removeprefix("assets/")).is_file()
    for imported in imports:
        assert (static / imported.removeprefix("assets/")).is_file()
    if importlib.util.find_spec("setuptools") is None:
        pytest.skip("offline wheel build requires a locally installed setuptools backend")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--no-index",
            "-w",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list(tmp_path.glob("jgrad_admission_rag-*.whl"))
    assert len(wheels) == 1
    prefix = "jgrad_admission_rag/service/static/"
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        for name in ("app.html", "advanced.html", "unified.css", "unified.js", "unified-core.mjs"):
            assert prefix + name in names
        for resource in resources:
            assert prefix + resource.removeprefix("assets/") in names
        for imported in imports:
            assert prefix + imported.removeprefix("assets/") in names
