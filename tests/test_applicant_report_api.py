from __future__ import annotations

import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jgrad_admission_rag.reasoning.applicant_report import (
    ApplicantReport,
    render_applicant_report_markdown,
)
from jgrad_admission_rag.reasoning.query_intent import IntentCategory
from jgrad_admission_rag.reasoning.reviewed_report_plan import (
    canonical_reviewed_report_plan_bytes,
)
from jgrad_admission_rag.reasoning.reviewed_report_evidence import (
    ReviewedReportEvidenceError,
    ReviewedReportEvidenceFailure,
)
from jgrad_admission_rag.schemas.corpus_manifest import canonical_corpus_manifest_bytes
from jgrad_admission_rag.schemas.corpus_version import canonical_corpus_version_policy_bytes
from jgrad_admission_rag.service import ServiceDependencies, ServiceSettings, create_app
from tests.test_applicant_report import _intent, _profile
from tests.test_corpus_search import ControlledProvider
from tests.test_reviewed_report_evidence import _context


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _runtime(tmp_path: Path, *, configure_plan: bool = True):
    context = _context(tmp_path)
    manifest_path = tmp_path / "corpus.json"
    policy_path = tmp_path / "policy.json"
    plan_path = tmp_path / "reviewed-plan.json"
    manifest_path.write_bytes(canonical_corpus_manifest_bytes(context.manifest))
    policy_path.write_bytes(canonical_corpus_version_policy_bytes(context.policy))
    plan_path.write_bytes(canonical_reviewed_report_plan_bytes(context.plan))
    settings = ServiceSettings(
        corpus_root=tmp_path.resolve(),
        manifest_path=manifest_path.resolve(),
        policy_path=policy_path.resolve(),
        report_plan_paths=(plan_path.resolve(),) if configure_plan else (),
    )
    dependencies = ServiceDependencies(provider_factory=ControlledProvider)
    return context, settings, dependencies, plan_path


def _payload(context, *, report_id: str = "report-001") -> dict:
    return {
        "schema_version": "1.0",
        "report_id": report_id,
        "profile": _profile().model_dump(mode="json"),
        "intent": _intent(IntentCategory.ELIGIBILITY).model_dump(mode="json"),
        "selection": context.selection.request.model_dump(mode="json"),
    }


def test_report_route_runs_reviewed_pipeline_and_returns_exact_markdown(tmp_path: Path) -> None:
    context, settings, dependencies, _ = _runtime(tmp_path)
    app = create_app(settings, dependencies)

    with TestClient(app) as client:
        assert client.get("/v1/health/ready").json()["ready"] is True
        first = client.post("/v1/applicant-reports", json=_payload(context))
        second = client.post("/v1/applicant-reports", json=_payload(context))

    assert first.status_code == 200
    assert first.content == second.content
    body = first.json()
    assert body["schema_version"] == "1.0"
    assert body["report"]["report_id"] == "report-001"
    assert body["report"]["plan_id"] == context.plan.plan_id
    assert body["report"]["document_identity"] == context.plan.document_identity.model_dump(
        mode="json"
    )
    report = ApplicantReport.model_validate(body["report"])
    assert body["markdown"] == render_applicant_report_markdown(report)
    assert context.plan.rules[0].evidence_bindings[0].fact_id in first.text
    assert "rank" not in body["markdown"].lower()


@pytest.mark.parametrize(
    ("age", "status", "applicability"),
    (
        (24, "complete", "confirmed"),
        (17, "complete", "not_applicable"),
        (None, "needs_information", "needs_information"),
    ),
)
def test_report_route_preserves_existing_reasoning_statuses(
    tmp_path: Path,
    age: int | None,
    status: str,
    applicability: str,
) -> None:
    context, settings, dependencies, _ = _runtime(tmp_path)
    payload = _payload(context)
    payload["profile"] = _profile(age).model_dump(mode="json")

    with TestClient(create_app(settings, dependencies)) as client:
        response = client.post("/v1/applicant-reports", json=payload)

    assert response.status_code == 200
    report = response.json()["report"]
    assert report["report_status"] == status
    assert report["reasoning_trace"]["applicability_steps"][0]["status"] == applicability
    assert "総合的な出願資格" in response.json()["markdown"]


def test_report_route_is_unavailable_without_explicit_plan_and_preserves_readiness(
    tmp_path: Path,
) -> None:
    context, settings, dependencies, _ = _runtime(tmp_path, configure_plan=False)
    app = create_app(settings, dependencies)

    with TestClient(app) as client:
        ready = client.get("/v1/health/ready")
        response = client.post("/v1/applicant-reports", json=_payload(context))

    assert ready.json()["ready"] is True
    assert (response.status_code, response.json()["code"]) == (
        503,
        "report_service_unavailable",
    )


def test_report_plan_initialization_failure_makes_service_not_ready(tmp_path: Path) -> None:
    context, settings, dependencies, plan_path = _runtime(tmp_path)
    plan_path.write_text("{}", encoding="utf-8")
    app = create_app(settings, dependencies)

    with TestClient(app) as client:
        ready = client.get("/v1/health/ready")
        response = client.post("/v1/applicant-reports", json=_payload(context))

    assert ready.json() == {
        "schema_version": "1.0",
        "status": "not_ready",
        "ready": False,
    }
    assert (response.status_code, response.json()["code"]) == (
        503,
        "report_service_unavailable",
    )


def test_missing_report_plan_makes_service_not_ready(tmp_path: Path) -> None:
    context, settings, dependencies, plan_path = _runtime(tmp_path)
    plan_path.unlink()

    with TestClient(create_app(settings, dependencies)) as client:
        ready = client.get("/v1/health/ready")
        response = client.post("/v1/applicant-reports", json=_payload(context))

    assert ready.json()["ready"] is False
    assert (response.status_code, response.json()["code"]) == (
        503,
        "report_service_unavailable",
    )


def test_report_plans_load_only_in_lifespan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jgrad_admission_rag.service.app as app_module

    _, settings, dependencies, _ = _runtime(tmp_path)
    real_loader = app_module.load_reviewed_report_plan
    calls: list[Path] = []

    def tracked_loader(path: Path):
        calls.append(path)
        return real_loader(path)

    monkeypatch.setattr(app_module, "load_reviewed_report_plan", tracked_loader)
    app = create_app(settings, dependencies)
    assert calls == []

    with TestClient(app):
        assert calls == list(settings.report_plan_paths)


def test_duplicate_report_configuration_fails_closed(tmp_path: Path) -> None:
    context, settings, dependencies, plan_path = _runtime(tmp_path)
    duplicate_settings = settings.model_copy(
        update={"report_plan_paths": (plan_path.resolve(), plan_path.resolve())}
    )

    with TestClient(create_app(duplicate_settings, dependencies)) as client:
        ready = client.get("/v1/health/ready")
        response = client.post("/v1/applicant-reports", json=_payload(context))

    assert ready.json()["ready"] is False
    assert (response.status_code, response.json()["code"]) == (
        503,
        "report_service_unavailable",
    )


def test_identity_incompatible_report_configuration_fails_closed(tmp_path: Path) -> None:
    context, settings, dependencies, _ = _runtime(tmp_path / "current")
    other = _context(tmp_path / "other", document_id="other-2027")
    other_plan_path = (tmp_path / "other-plan.json").resolve()
    other_plan_path.write_bytes(canonical_reviewed_report_plan_bytes(other.plan))
    incompatible_settings = settings.model_copy(update={"report_plan_paths": (other_plan_path,)})

    with TestClient(create_app(incompatible_settings, dependencies)) as client:
        ready = client.get("/v1/health/ready")
        response = client.post("/v1/applicant-reports", json=_payload(context))

    assert ready.json()["ready"] is False
    assert (response.status_code, response.json()["code"]) == (
        503,
        "report_service_unavailable",
    )


def test_unconfigured_plan_files_are_never_discovered(tmp_path: Path) -> None:
    context, settings, dependencies, plan_path = _runtime(tmp_path, configure_plan=False)
    assert plan_path.exists()

    with TestClient(create_app(settings, dependencies)) as client:
        response = client.post("/v1/applicant-reports", json=_payload(context))

    assert (response.status_code, response.json()["code"]) == (
        503,
        "report_service_unavailable",
    )


@pytest.mark.parametrize(
    ("mutation", "status", "code"),
    (
        (lambda body: body.update({"extra": "private"}), 422, "invalid_request"),
        (lambda body: body.update({"report_id": "../unsafe"}), 422, "invalid_request"),
        (
            lambda body: body["intent"].update({"query": "unknown"}),
            422,
            "invalid_request",
        ),
    ),
)
def test_report_request_is_strict_and_privacy_safe(
    tmp_path: Path, mutation, status: int, code: str
) -> None:
    context, settings, dependencies, _ = _runtime(tmp_path)
    body = _payload(context)
    mutation(body)

    with TestClient(create_app(settings, dependencies)) as client:
        response = client.post("/v1/applicant-reports", json=body)

    assert (response.status_code, response.json()["code"]) == (status, code)
    assert "private" not in response.text


def test_report_route_rejects_media_type_and_missing_plan(tmp_path: Path) -> None:
    context, settings, dependencies, _ = _runtime(tmp_path)
    missing = _payload(context)
    missing["selection"]["document_ids"] = ["missing-document"]

    with TestClient(create_app(settings, dependencies)) as client:
        media = client.post(
            "/v1/applicant-reports",
            content=b"{}",
            headers={"content-type": "text/plain"},
        )
        no_plan = client.post("/v1/applicant-reports", json=missing)
        wrong_method = client.get("/v1/applicant-reports")

    assert (media.status_code, media.json()["code"]) == (415, "unsupported_media_type")
    assert (no_plan.status_code, no_plan.json()["code"]) == (404, "report_plan_not_found")
    assert (wrong_method.status_code, wrong_method.json()["code"]) == (405, "invalid_request")


def test_report_route_rejects_unsupported_intent_and_caller_authored_rules(
    tmp_path: Path,
) -> None:
    context, settings, dependencies, _ = _runtime(tmp_path)
    unsupported = _payload(context)
    unsupported["intent"] = _intent(IntentCategory.APPLICATION_DATES).model_dump(mode="json")
    injected = _payload(context)
    injected["rules"] = [{"rule_id": "caller-rule"}]

    with TestClient(create_app(settings, dependencies)) as client:
        unsupported_response = client.post("/v1/applicant-reports", json=unsupported)
        injected_response = client.post("/v1/applicant-reports", json=injected)

    assert (unsupported_response.status_code, unsupported_response.json()["code"]) == (
        422,
        "invalid_request",
    )
    assert (injected_response.status_code, injected_response.json()["code"]) == (
        422,
        "invalid_request",
    )
    assert "caller-rule" not in injected_response.text


def test_report_route_delegates_without_provider_calls_or_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jgrad_admission_rag.service.app as app_module

    context, settings, _, _ = _runtime(tmp_path)
    provider = ControlledProvider()
    dependencies = ServiceDependencies(provider_factory=lambda: provider)
    payload = _payload(context)
    original_payload = copy.deepcopy(payload)
    before = _files(tmp_path)
    calls: list[str] = []
    real_select = app_module.select_corpus_documents
    real_prepare = app_module.prepare_reviewed_report_evidence
    real_build = app_module.build_applicant_report

    def tracked_select(*args, **kwargs):
        calls.append("select")
        return real_select(*args, **kwargs)

    def tracked_prepare(*args, **kwargs):
        calls.append("prepare")
        return real_prepare(*args, **kwargs)

    def tracked_build(*args, **kwargs):
        calls.append("build")
        return real_build(*args, **kwargs)

    monkeypatch.setattr(app_module, "select_corpus_documents", tracked_select)
    monkeypatch.setattr(app_module, "prepare_reviewed_report_evidence", tracked_prepare)
    monkeypatch.setattr(app_module, "build_applicant_report", tracked_build)

    with TestClient(create_app(settings, dependencies)) as client:
        response = client.post("/v1/applicant-reports", json=payload)

    assert response.status_code == 200
    assert calls == ["select", "prepare", "build"]
    assert provider.query_calls == []
    assert provider.document_calls == 0
    assert payload == original_payload
    assert _files(tmp_path) == before


def test_report_route_offloads_lifespan_and_request_disk_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jgrad_admission_rag.service.app as app_module

    context, settings, dependencies, _ = _runtime(tmp_path)
    real_run_sync = app_module.to_thread.run_sync
    offloaded: list[str] = []

    async def tracked_run_sync(function, *args, **kwargs):
        name = getattr(function, "func", function).__name__
        offloaded.append(name)
        return await real_run_sync(function, *args, **kwargs)

    monkeypatch.setattr(app_module.to_thread, "run_sync", tracked_run_sync)

    with TestClient(create_app(settings, dependencies)) as client:
        response = client.post("/v1/applicant-reports", json=_payload(context))

    assert response.status_code == 200
    assert offloaded == ["_load_report_plans", "_build_applicant_report_response"]


def test_renderer_failure_is_a_privacy_safe_generation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jgrad_admission_rag.service.app as app_module

    context, settings, dependencies, _ = _runtime(tmp_path)

    def fail_renderer(_):
        raise RuntimeError("private renderer failure")

    monkeypatch.setattr(app_module, "render_applicant_report_markdown", fail_renderer)
    with TestClient(create_app(settings, dependencies)) as client:
        response = client.post("/v1/applicant-reports", json=_payload(context))

    assert response.status_code == 500
    assert response.json() == {
        "schema_version": "1.0",
        "code": "report_generation_failed",
        "message": "applicant report generation failed",
        "details": None,
    }


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    (
        (
            ReviewedReportEvidenceFailure.SELECTION_STALE,
            409,
            "corpus_selection_conflict",
        ),
        (
            ReviewedReportEvidenceFailure.FACT_TEXT_MISMATCH,
            409,
            "report_preparation_failed",
        ),
        (
            ReviewedReportEvidenceFailure.CORPUS_AUDIT_FAILED,
            503,
            "report_service_unavailable",
        ),
    ),
)
def test_evidence_failures_have_stable_privacy_safe_mappings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: ReviewedReportEvidenceFailure,
    status: int,
    code: str,
) -> None:
    import jgrad_admission_rag.service.app as app_module

    context, settings, dependencies, _ = _runtime(tmp_path)

    def fail_preparation(*_args, **_kwargs):
        raise ReviewedReportEvidenceError(failure)

    monkeypatch.setattr(app_module, "prepare_reviewed_report_evidence", fail_preparation)
    with TestClient(create_app(settings, dependencies)) as client:
        response = client.post("/v1/applicant-reports", json=_payload(context))

    assert (response.status_code, response.json()["code"]) == (status, code)
    assert failure.value not in response.text


def test_report_route_detects_corpus_staleness_after_startup(tmp_path: Path) -> None:
    context, settings, dependencies, _ = _runtime(tmp_path)

    with TestClient(create_app(settings, dependencies)) as client:
        context.kb_path.write_bytes(context.kb_path.read_bytes() + b" ")
        response = client.post("/v1/applicant-reports", json=_payload(context))

    assert (response.status_code, response.json()["code"]) == (
        503,
        "report_service_unavailable",
    )


def test_report_route_enforces_one_document_after_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jgrad_admission_rag.service.app as app_module

    context, settings, dependencies, _ = _runtime(tmp_path)
    multiple = context.selection.model_copy(
        update={"selected_documents": context.selection.selected_documents * 2}
    )
    monkeypatch.setattr(app_module, "select_corpus_documents", lambda *_args: multiple)

    with TestClient(create_app(settings, dependencies)) as client:
        response = client.post("/v1/applicant-reports", json=_payload(context))

    assert (response.status_code, response.json()["code"]) == (
        409,
        "corpus_selection_conflict",
    )


def test_report_plan_paths_must_be_absolute() -> None:
    with pytest.raises(ValueError):
        ServiceSettings(report_plan_paths=(Path("relative-plan.json"),))
