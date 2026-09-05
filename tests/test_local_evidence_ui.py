from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from jgrad_admission_rag.corpus import CorpusRegistration, build_corpus_manifest
from jgrad_admission_rag.reasoning.reviewed_report_plan import (
    canonical_reviewed_report_plan_bytes,
)
from jgrad_admission_rag.schemas.corpus_manifest import canonical_corpus_manifest_bytes
from jgrad_admission_rag.schemas.corpus_version import (
    CorpusFamilyVersionPolicy,
    CorpusVersionPolicy,
    canonical_corpus_version_policy_bytes,
)
from jgrad_admission_rag.service import (
    ReviewedDocumentPublicIdentity,
    ServiceDependencies,
    ServiceSettings,
    create_app,
)
from tests.test_applicant_report_api import _payload, _runtime
from tests.test_corpus_search import ControlledProvider, _prepared_two_document_corpus
from tests.test_reviewed_report_evidence import _context, _plan


SECURITY_HEADERS = {
    "cache-control": "no-store",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
}


def test_catalog_returns_strict_safe_reviewed_document(tmp_path: Path) -> None:
    context, settings, dependencies, _ = _runtime(tmp_path)

    with TestClient(create_app(settings, dependencies)) as client:
        response = client.get("/v1/reviewed-documents")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0",
        "items": [
            {
                "identity": {
                    key: value
                    for key, value in context.plan.document_identity.model_dump(mode="json").items()
                    if key != "source_pdf_sha256"
                },
                "version_classification": "active",
                "plan_id": context.plan.plan_id,
                "coverage_status": "partial_reviewed_rules",
                "covered_categories": ["eligibility"],
                "reviewed_coverage_statement": context.plan.reviewed_coverage_statement,
                "limitation_statement": context.plan.limitation_statement,
            }
        ],
    }
    assert "source_pdf_sha256" not in response.text
    assert "source_kb_sha256" not in response.text
    assert "kb_path" not in response.text
    assert "index_path" not in response.text
    assert "predicates" not in response.text
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


def test_public_catalog_identity_rejects_hash_or_extra_fields(tmp_path: Path) -> None:
    context = _context(tmp_path)
    payload = context.plan.document_identity.model_dump(mode="json")

    with pytest.raises(ValidationError):
        ReviewedDocumentPublicIdentity.model_validate(payload)


def test_catalog_disk_validation_is_offloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jgrad_admission_rag.service.app as app_module

    _, settings, dependencies, _ = _runtime(tmp_path)
    real_run_sync = app_module.to_thread.run_sync
    offloaded: list[str] = []

    async def tracked_run_sync(function, *args, **kwargs):
        offloaded.append(getattr(function, "func", function).__name__)
        return await real_run_sync(function, *args, **kwargs)

    monkeypatch.setattr(app_module.to_thread, "run_sync", tracked_run_sync)
    with TestClient(create_app(settings, dependencies)) as client:
        response = client.get("/v1/reviewed-documents")

    assert response.status_code == 200
    assert offloaded == ["_load_report_plans", "_build_reviewed_document_catalog"]


def test_catalog_is_unavailable_without_report_configuration(tmp_path: Path) -> None:
    _, settings, dependencies, _ = _runtime(tmp_path, configure_plan=False)

    with TestClient(create_app(settings, dependencies)) as client:
        response = client.get("/v1/reviewed-documents")

    assert response.status_code == 503
    assert response.json()["code"] == "report_service_unavailable"


def test_catalog_reports_historical_classification(tmp_path: Path) -> None:
    context, settings, dependencies, _ = _runtime(tmp_path)
    historical = CorpusVersionPolicy(
        corpus_id=context.manifest.corpus_id,
        family_policies=(
            CorpusFamilyVersionPolicy(
                document_family_id=context.plan.document_identity.document_family_id,
                historical_document_ids=(context.plan.document_identity.document_id,),
            ),
        ),
    )
    settings.policy_path.write_bytes(canonical_corpus_version_policy_bytes(historical))

    with TestClient(create_app(settings, dependencies)) as client:
        response = client.get("/v1/reviewed-documents")

    assert response.status_code == 200
    assert response.json()["items"][0]["version_classification"] == "historical"


def test_catalog_order_is_canonical_for_multiple_reviewed_documents(tmp_path: Path) -> None:
    manifest, policy, _, _, _ = _prepared_two_document_corpus(tmp_path)
    plans = tuple(
        _plan(
            entry.identity,
            entry.source_kb_sha256,
            f"Official {entry.identity.document_id.split('-', 1)[0]} evidence.",
            plan_id=f"plan-{entry.identity.document_id}",
        )
        for entry in reversed(manifest.entries)
    )
    plan_paths = []
    for plan in plans:
        path = (tmp_path / f"{plan.plan_id}.json").resolve()
        path.write_bytes(canonical_reviewed_report_plan_bytes(plan))
        plan_paths.append(path)
    manifest_path = (tmp_path / "corpus.json").resolve()
    policy_path = (tmp_path / "policy.json").resolve()
    manifest_path.write_bytes(canonical_corpus_manifest_bytes(manifest))
    policy_path.write_bytes(canonical_corpus_version_policy_bytes(policy))
    settings = ServiceSettings(
        corpus_root=tmp_path.resolve(),
        manifest_path=manifest_path,
        policy_path=policy_path,
        report_plan_paths=tuple(plan_paths),
    )

    with TestClient(
        create_app(settings, ServiceDependencies(provider_factory=ControlledProvider))
    ) as client:
        response = client.get("/v1/reviewed-documents")

    assert response.status_code == 200
    assert [item["identity"]["document_id"] for item in response.json()["items"]] == [
        "alpha-2027",
        "beta-2027",
    ]


def test_catalog_can_be_valid_and_empty_when_reviewed_document_is_not_ready(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    relative_kb = context.kb_path.relative_to(tmp_path).as_posix()
    manifest = build_corpus_manifest(
        "empty-reviewed-catalog",
        tmp_path,
        (CorpusRegistration(relative_kb),),
    )
    policy = CorpusVersionPolicy(
        corpus_id=manifest.corpus_id,
        family_policies=(
            CorpusFamilyVersionPolicy(
                document_family_id=context.plan.document_identity.document_family_id,
                active_document_id=context.plan.document_identity.document_id,
            ),
        ),
    )
    manifest_path = (tmp_path / "empty-corpus.json").resolve()
    policy_path = (tmp_path / "empty-policy.json").resolve()
    plan_path = (tmp_path / "empty-plan.json").resolve()
    manifest_path.write_bytes(canonical_corpus_manifest_bytes(manifest))
    policy_path.write_bytes(canonical_corpus_version_policy_bytes(policy))
    plan_path.write_bytes(canonical_reviewed_report_plan_bytes(context.plan))
    settings = ServiceSettings(
        corpus_root=tmp_path.resolve(),
        manifest_path=manifest_path,
        policy_path=policy_path,
        report_plan_paths=(plan_path,),
    )

    with TestClient(
        create_app(settings, ServiceDependencies(provider_factory=ControlledProvider))
    ) as client:
        response = client.get("/v1/reviewed-documents")

    assert response.status_code == 200
    assert response.json() == {"schema_version": "1.0", "items": []}


def test_catalog_fails_closed_when_corpus_or_policy_changes(tmp_path: Path) -> None:
    context, settings, dependencies, _ = _runtime(tmp_path)

    with TestClient(create_app(settings, dependencies)) as client:
        context.kb_path.write_bytes(context.kb_path.read_bytes() + b" ")
        stale_corpus = client.get("/v1/reviewed-documents")

    assert stale_corpus.status_code == 503
    assert stale_corpus.json()["code"] == "report_service_unavailable"
    assert str(context.kb_path) not in stale_corpus.text


def test_duplicate_plan_registry_keeps_catalog_unavailable(tmp_path: Path) -> None:
    _, settings, dependencies, plan_path = _runtime(tmp_path)
    duplicate = settings.model_copy(
        update={"report_plan_paths": (plan_path.resolve(), plan_path.resolve())}
    )

    with TestClient(create_app(duplicate, dependencies)) as client:
        response = client.get("/v1/reviewed-documents")

    assert response.status_code == 503
    assert response.json()["code"] == "report_service_unavailable"


def test_local_ui_assets_are_fixed_offline_and_security_hardened(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(create_app()) as client:
        html = client.get("/app")
        css = client.get("/assets/app.css")
        javascript = client.get("/assets/app.js")
        alias = client.get("/app/")
        docs = client.get("/docs")

    assert html.status_code == css.status_code == javascript.status_code == 200
    assert alias.status_code == 404
    assert html.headers["content-type"].startswith("text/html")
    assert css.headers["content-type"].startswith("text/css")
    assert "javascript" in javascript.headers["content-type"]
    for response in (html, css, javascript):
        for name, value in SECURITY_HEADERS.items():
            assert response.headers[name] == value
        policy = response.headers["content-security-policy"]
        assert "default-src 'none'" in policy
        assert "script-src 'self'" in policy
        assert "style-src 'self'" in policy
        assert "connect-src 'self'" in policy
        assert response.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" not in docs.headers
    assert 'href="/assets/app.css"' in html.text
    assert 'src="/assets/app.js"' in html.text
    assert "http://" not in html.text
    assert "https://" not in html.text


def test_local_ui_contract_has_accessible_states_and_safe_rendering() -> None:
    static_root = Path(__file__).parents[1] / "src" / "jgrad_admission_rag" / "service" / "static"
    html = (static_root / "app.html").read_text(encoding="utf-8")
    css = (static_root / "app.css").read_text(encoding="utf-8")
    javascript = (static_root / "app.js").read_text(encoding="utf-8")

    assert 'lang="ja"' in html
    assert '<label for="document-select">' in html
    assert '<label for="query-input">' in html
    assert 'maxlength="1000"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'type="submit"' in html
    assert 'type="button" hidden' in html
    assert "根拠候補" in html
    assert "出願資格や合否の判定ではありません" in html
    assert "@media (max-width: 760px)" in css
    assert ":focus-visible" in css
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
        "serviceWorker",
        "console.",
        "/v1/applicant-reports",
    ):
        assert forbidden not in javascript
    assert "textContent" in javascript
    assert "replaceChildren" in javascript
    assert "document_ids: [item.identity.document_id]" in javascript
    assert "allow_multiple_documents: false" in javascript
    assert "body: JSON.stringify(searchRequest(item, query))" in javascript
    assert 'cache: "no-store"' in javascript
    assert "window.location" not in javascript
    assert "URLSearchParams" not in javascript


def test_ui_and_catalog_do_not_change_report_or_query_routes(tmp_path: Path) -> None:
    context, settings, dependencies, _ = _runtime(tmp_path)

    with TestClient(create_app(settings, dependencies)) as client:
        report = client.post("/v1/applicant-reports", json=_payload(context))
        query_media = client.post(
            "/v1/corpus/query",
            content=b"{}",
            headers={"content-type": "text/plain"},
        )

    assert report.status_code == 200
    assert (query_media.status_code, query_media.json()["code"]) == (
        415,
        "unsupported_media_type",
    )
