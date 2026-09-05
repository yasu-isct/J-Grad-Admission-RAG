from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jgrad_admission_rag.service import ServiceSettings, create_app


CATALOG = Path(__file__).parents[1] / "config" / "query_intent_catalog_v1.json"


def _settings(tmp_path: Path) -> ServiceSettings:
    catalog_path = (tmp_path / "query-intent.json").resolve()
    shutil.copyfile(CATALOG, catalog_path)
    return ServiceSettings(query_intent_catalog_path=catalog_path)


def test_intent_route_delegates_to_lifespan_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jgrad_admission_rag.service.app as app_module

    settings = _settings(tmp_path)
    real_loader = app_module.load_query_intent_catalog
    real_parser = app_module.parse_query_intent
    calls: list[tuple[str, object]] = []

    def tracked_loader(path: Path):
        calls.append(("load", path))
        return real_loader(path)

    def tracked_parser(query: str, catalog):
        calls.append(("parse", (query, catalog.catalog_version)))
        return real_parser(query, catalog)

    monkeypatch.setattr(app_module, "load_query_intent_catalog", tracked_loader)
    monkeypatch.setattr(app_module, "parse_query_intent", tracked_parser)
    app = create_app(settings)
    assert calls == []

    with TestClient(app) as client:
        response = client.post(
            "/v1/query-intents/parse",
            json={"schema_version": "1.0", "query": "情報理工学院の出願資格"},
        )

    assert response.status_code == 200
    assert response.json()["requested_categories"] == ["eligibility"]
    assert response.json()["requested_scope"]["parent_college_values"] == ["情報理工学院"]
    assert calls[0] == ("load", settings.query_intent_catalog_path)
    assert calls[1][0] == "parse"


def test_unconfigured_intent_route_preserves_existing_readiness() -> None:
    with TestClient(create_app()) as client:
        ready = client.get("/v1/health/ready")
        response = client.post(
            "/v1/query-intents/parse",
            json={"schema_version": "1.0", "query": "出願資格"},
        )

    assert ready.json()["ready"] is False
    assert response.status_code == 503
    assert response.json() == {
        "schema_version": "1.0",
        "code": "intent_service_unavailable",
        "message": "query intent service is unavailable",
        "details": None,
    }


def test_unconfigured_catalog_keeps_configured_report_runtime_ready(tmp_path: Path) -> None:
    from tests.test_applicant_report_api import _runtime

    _context, settings, dependencies, _plan = _runtime(tmp_path)
    with TestClient(create_app(settings, dependencies)) as client:
        assert client.get("/v1/health/ready").json()["ready"] is True
        response = client.post(
            "/v1/query-intents/parse",
            json={"schema_version": "1.0", "query": "出願資格"},
        )

    assert (response.status_code, response.json()["code"]) == (
        503,
        "intent_service_unavailable",
    )


def test_invalid_configured_catalog_fails_readiness_without_leaking_path(tmp_path: Path) -> None:
    path = (tmp_path / "private-name.json").resolve()
    path.write_text("{}", encoding="utf-8")
    with TestClient(create_app(ServiceSettings(query_intent_catalog_path=path))) as client:
        ready = client.get("/v1/health/ready")
        response = client.post(
            "/v1/query-intents/parse",
            json={"schema_version": "1.0", "query": "出願資格"},
        )

    assert ready.json()["ready"] is False
    assert response.status_code == 503
    assert "private-name" not in response.text


def test_invalid_catalog_makes_otherwise_ready_runtime_not_ready(tmp_path: Path) -> None:
    from tests.test_applicant_report_api import _runtime

    _context, settings, dependencies, _plan = _runtime(tmp_path)
    invalid = (tmp_path / "invalid-intent.json").resolve()
    invalid.write_text("{}", encoding="utf-8")
    configured = settings.model_copy(update={"query_intent_catalog_path": invalid})

    with TestClient(create_app(configured, dependencies)) as client:
        assert client.get("/v1/health/ready").json()["ready"] is False


@pytest.mark.parametrize(
    "payload",
    (
        {"schema_version": "1.0", "query": "何を確認できますか"},
        {"schema_version": "1.0", "query": "情報系の出願資格"},
        {"schema_version": "1.0", "query": " 出願資格"},
        {"schema_version": "1.0", "query": "x" * 1001},
        {"schema_version": "2.0", "query": "出願資格"},
        {"schema_version": "1.0", "query": "出願資格", "extra": "private"},
    ),
)
def test_intent_route_rejects_unrecognized_ambiguous_or_invalid_input(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.post("/v1/query-intents/parse", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert "private" not in response.text


def test_intent_route_rejects_media_type_and_documents_openapi(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        media = client.post(
            "/v1/query-intents/parse",
            content=b"{}",
            headers={"content-type": "text/plain"},
        )
        schema = client.get("/openapi.json").json()

    assert (media.status_code, media.json()["code"]) == (415, "unsupported_media_type")
    operation = schema["paths"]["/v1/query-intents/parse"]["post"]
    assert operation["operationId"] == "postV1QueryIntentsParse"
    assert set(operation["responses"]) >= {"200", "415", "422", "500", "503"}


def test_intent_runtime_failure_is_privacy_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jgrad_admission_rag.service.app as app_module

    def fail_parser(*_args):
        raise RuntimeError("private query and catalog content")

    monkeypatch.setattr(app_module, "parse_query_intent", fail_parser)
    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.post(
            "/v1/query-intents/parse",
            json={"schema_version": "1.0", "query": "出願資格"},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "intent_service_unavailable"
    assert "private" not in response.text


def test_intent_catalog_is_not_reloaded_or_discovered_per_request(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert settings.query_intent_catalog_path is not None

    with TestClient(create_app(settings)) as client:
        settings.query_intent_catalog_path.write_text("{}", encoding="utf-8")
        response = client.post(
            "/v1/query-intents/parse",
            json={"schema_version": "1.0", "query": "出願資格"},
        )

    assert response.status_code == 200
    assert response.json()["catalog_version"] == "science-tokyo-ja-v2"


def test_intent_catalog_path_must_be_absolute() -> None:
    with pytest.raises(ValueError):
        ServiceSettings(query_intent_catalog_path=Path("relative.json"))
