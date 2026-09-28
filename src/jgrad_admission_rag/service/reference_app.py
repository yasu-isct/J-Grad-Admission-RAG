"""Additive optional reference routes around the unchanged legacy service factory."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from anyio import to_thread
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse

from ..reasoning.material_conditions import load_request as load_material_request
from ..reasoning.material_slice_report import MaterialSliceError
from ..reviewed_source_evidence import canonical_json_bytes
from .app import (
    ApiProblem,
    _build_demo_target_catalog_response,
    _error,
    _error_response,
    _report_service_ready,
    _secure_response,
    create_app as create_legacy_app,
)
from .reference_contracts import (
    ReferenceEvidenceResponse,
    ReferenceReportResponse,
    ReferenceTargetsResponse,
)
from .reference_workspace import load_reference_workspace
from .runtime import ServiceDependencies, ServiceSettings


def create_app(
    settings: ServiceSettings | None = None,
    dependencies: ServiceDependencies | None = None,
) -> FastAPI:
    """Extend one FastAPI service without changing frozen legacy implementation bytes."""
    selected_settings = settings or ServiceSettings()
    app = create_legacy_app(selected_settings, dependencies)
    state = app.state.service_state
    legacy_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def reference_lifespan(application: FastAPI):
        async with legacy_lifespan(application):
            if selected_settings.reference_workspace_config_path is not None:
                try:
                    state.reference_slices = await to_thread.run_sync(
                        partial(
                            load_reference_workspace,
                            selected_settings.reference_workspace_config_path,
                        )
                    )
                except Exception:
                    state.reference_initialization_failed = True
                    state.reference_slices = ()
                if (
                    _report_service_ready(state)
                    and state.provider is not None
                    and not state.initialization_failed
                ):
                    try:
                        state.reference_legacy_catalog = await to_thread.run_sync(
                            partial(
                                _build_demo_target_catalog_response,
                                selected_settings,
                                state,
                            )
                        )
                    except Exception:
                        state.reference_legacy_catalog = None
                if state.reference_legacy_catalog is not None:
                    legacy_ids = {
                        f"legacy-{school.school_id}"
                        for school in state.reference_legacy_catalog.schools
                    }
                    if any(
                        snapshot.config.slice_id in legacy_ids
                        for snapshot in state.reference_slices
                    ):
                        state.reference_initialization_failed = True
                        state.reference_slices = ()
            try:
                yield
            finally:
                state.reference_slices = ()
                state.reference_legacy_catalog = None

    app.router.lifespan_context = reference_lifespan

    @app.middleware("http")
    async def reference_page_security(request: Request, call_next):
        if request.method == "POST" and re.fullmatch(
            r"/v1/reference-slices/[^/]+/reports", request.url.path
        ):
            media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                return _secure_response(
                    request.url.path,
                    _error_response(
                        415,
                        _error("unsupported_media_type", "request content type is unsupported"),
                    ),
                )
        response = await call_next(request)
        if request.url.path == "/app/reference":
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self'; base-uri 'none'; "
                "form-action 'self'; frame-ancestors 'none'; object-src 'none'"
            )
            response.headers["Permissions-Policy"] = (
                "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
            )
            response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
            response.headers["X-Frame-Options"] = "DENY"
        return response

    static = Path(__file__).with_name("static")

    @app.get("/app/reference", include_in_schema=False)
    def reference_app() -> FileResponse:
        return FileResponse(static / "reference.html", media_type="text/html; charset=utf-8")

    @app.get("/assets/reference.js", include_in_schema=False)
    def reference_app_js() -> FileResponse:
        return FileResponse(static / "reference.js", media_type="text/javascript; charset=utf-8")

    @app.get("/assets/reference.css", include_in_schema=False)
    def reference_app_css() -> FileResponse:
        return FileResponse(static / "reference.css", media_type="text/css; charset=utf-8")

    @app.get(
        "/v1/reference-targets",
        response_model=ReferenceTargetsResponse,
        operation_id="getV1ReferenceTargets",
    )
    def reference_targets(request: Request) -> Response:
        if request.query_params:
            raise ApiProblem(422, "invalid_request", "query is invalid")
        items = []
        if state.reference_legacy_catalog is not None:
            for school in state.reference_legacy_catalog.schools:
                items.append(
                    {
                        "entry_id": f"legacy-{school.school_id}",
                        "kind": "legacy_applicant",
                        "institution_name": school.school_name,
                        "availability": "ready",
                        "capabilities": {
                            "applicant_check": True,
                            "evidence_browse": False,
                            "reference_report": False,
                        },
                        "href": "/app",
                        "legacy_catalog": school.model_dump(mode="json"),
                    }
                )
        for snapshot in state.reference_slices:
            items.append(
                {
                    "entry_id": snapshot.config.slice_id,
                    "kind": "reviewed_material_slice",
                    "institution_name": snapshot.config.institution_name,
                    "organization_name": snapshot.config.organization_name,
                    "program_name": snapshot.config.program_name,
                    "availability": "ready",
                    "capabilities": {
                        "applicant_check": False,
                        "evidence_browse": True,
                        "reference_report": True,
                    },
                    "target": snapshot.plan.target.model_dump(mode="json"),
                    "request_profile_target": dict(snapshot.profile_aliases),
                    "snapshot_id": snapshot.snapshot_id,
                    "revision": snapshot.plan.revision,
                    "limitations_zh": snapshot.plan.limitations_zh,
                }
            )
        if (
            selected_settings.reference_workspace_config_path is not None
            and state.reference_initialization_failed
        ):
            items.append(
                {
                    "entry_id": "reviewed-slice-unavailable",
                    "kind": "reviewed_material_slice",
                    "institution_name": "审核材料切片",
                    "availability": "unavailable",
                    "reason_code": "reference_configuration_invalid",
                    "capabilities": {
                        "applicant_check": False,
                        "evidence_browse": False,
                        "reference_report": False,
                    },
                }
            )
        validated = ReferenceTargetsResponse.model_validate(
            {"schema_version": "1.0", "items": items}
        )
        encoded = canonical_json_bytes(validated.model_dump(mode="json"))
        if len(encoded) > 1024 * 1024:
            raise ApiProblem(503, "reference_unavailable", "reviewed reference is unavailable")
        return Response(content=encoded, media_type="application/json")

    def reference_slice(slice_id: str):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slice_id) or len(slice_id) > 120:
            raise ApiProblem(404, "reference_slice_not_found", "reference slice was not found")
        for snapshot in state.reference_slices:
            if snapshot.config.slice_id == slice_id:
                return snapshot
        if state.reference_initialization_failed:
            raise ApiProblem(503, "reference_unavailable", "reviewed reference is unavailable")
        raise ApiProblem(404, "reference_slice_not_found", "reference slice was not found")

    @app.get(
        "/v1/reference-slices/{slice_id}/evidence",
        response_model=ReferenceEvidenceResponse,
        operation_id="getV1ReferenceEvidence",
    )
    def reference_evidence(slice_id: str, request: Request) -> Response:
        if request.query_params:
            raise ApiProblem(422, "invalid_request", "query is invalid")
        snapshot = reference_slice(slice_id)
        if len(snapshot.presentation) > 1024 * 1024:
            raise ApiProblem(503, "reference_unavailable", "reviewed reference is unavailable")
        return Response(content=snapshot.presentation, media_type="application/json")

    @app.post(
        "/v1/reference-slices/{slice_id}/reports",
        response_model=ReferenceReportResponse,
        operation_id="postV1ReferenceReport",
    )
    async def reference_report(slice_id: str, request: Request) -> Response:
        snapshot = reference_slice(slice_id)
        if request.query_params:
            raise ApiProblem(422, "invalid_request", "query is invalid")
        if not state.reference_report_lock.acquire(blocking=False):
            raise ApiProblem(429, "reference_busy", "reference report is busy")
        try:
            chunks = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 256 * 1024:
                    raise ApiProblem(422, "invalid_request", "request is too large")
                chunks.append(chunk)
            raw = b"".join(chunks)
            try:
                load_material_request(raw)
            except ValueError:
                raise ApiProblem(422, "invalid_request", "request validation failed") from None
            try:
                envelope = await to_thread.run_sync(partial(snapshot.report, raw))
                encoded = canonical_json_bytes(envelope)
            except (MaterialSliceError, ValueError):
                raise ApiProblem(
                    503, "reference_unavailable", "reviewed reference is unavailable"
                ) from None
            if len(encoded) > 512 * 1024:
                raise ApiProblem(503, "reference_unavailable", "reviewed reference is unavailable")
            return Response(content=encoded, media_type="application/json")
        finally:
            state.reference_report_lock.release()

    return app
