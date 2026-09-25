"""FastAPI application factory for the local versioned service."""

from __future__ import annotations

import hashlib
import re
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, AsyncIterator
from uuid import UUID
from uuid import uuid4

from anyio import CancelScope, open_file, to_thread
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.datastructures import FormData, UploadFile

from ..builder.kb_builder import DocumentBuildError, build_document_kb
from ..generation import (
    GenerationError,
    GenerationErrorCode,
    GroundedRagError,
    GroundedRagErrorCode,
    GroundedRagTarget,
    run_grounded_rag,
)
from ..corpus import audit_corpus_manifest, resolve_registered_corpus_kb_path
from ..corpus_search import (
    CorpusSearchError,
    CorpusSearchInputError,
    CorpusSearchProviderError,
    CorpusSearchResult,
    prepare_corpus_search_context,
    search_corpus,
)
from ..corpus_selection import (
    CorpusPolicyCompatibilityError,
    CorpusSelectionAmbiguousError,
    CorpusSelectionNoMatchError,
    CorpusSelectionNotReadyError,
    CorpusSelectionRequestError,
    CorpusSelectionVersionMismatchError,
    select_corpus_documents,
    validate_corpus_version_policy,
)
from ..reasoning.applicant_report import (
    ApplicantReportError,
    ApplicantReportFailure,
    build_applicant_report,
    render_applicant_report_markdown,
)
from ..reasoning.applicability import ApplicabilityStatus
from ..reasoning.cited_answer import (
    CitedAnswer,
    ProcessNoticeKind,
    ReportStatus,
)
from ..reasoning.rule_resolution import ResolutionDisposition
from ..reasoning.query_intent import (
    DiagnosticCode,
    QueryIntent,
    QueryIntentError,
    load_query_intent_catalog,
    parse_query_intent,
)
from ..reasoning.reviewed_report_evidence import (
    ReviewedReportEvidenceBundle,
    ReviewedReportEvidenceError,
    ReviewedReportEvidenceFailure,
    prepare_reviewed_report_evidence,
)
from ..reasoning.reviewed_report_plan import (
    ReviewedReportPlan,
    load_reviewed_report_plan,
)
from ..retrieval.metadata_search import MetadataFilter, ScopePreference
from ..retrieval.evidence_pack import build_corpus_evidence_pack
from ..schemas.corpus_manifest import CorpusManifestError, load_corpus_manifest
from ..schemas.corpus_version import CorpusVersionSchemaError, load_corpus_version_policy
from ..schemas.corpus_version import CorpusSelectionRequest
from ..schemas.evidence_pack import EvidencePack
from ..schemas.document_identity import (
    DocumentIdentity,
    DocumentIdentityError,
    canonical_document_identity_bytes,
    load_document_identity_bytes,
)
from ..schemas.document_kb import load_document_kb
from ..schemas.page_scope_manifest import (
    PageScopeManifest,
    load_page_scope_manifest,
    load_page_scope_manifest_bytes,
)
from .build_execution import build_response
from .contracts import (
    BUILD_ERROR_RESPONSES,
    CATALOG_ERROR_RESPONSES,
    HEALTH_ERROR_RESPONSES,
    GROUNDED_ERROR_RESPONSES,
    JOB_ERROR_RESPONSES,
    INTENT_ERROR_RESPONSES,
    QUERY_ERROR_RESPONSES,
    REPORT_ERROR_RESPONSES,
    ApplicantReportRequest,
    ApplicantReportResponse,
    BuildJobReceipt,
    BuildJobStatus,
    BuildOptions,
    BuildResponse,
    CorpusQueryRequest,
    ErrorEnvelope,
    HealthResponse,
    QueryIntentParseRequest,
    ReviewedDocumentCatalogItem,
    ReviewedDocumentCatalogResponse,
    ReviewedDocumentPublicIdentity,
)
from .demo_requirements import (
    DemoApplicantComparisonRequest,
    DemoApplicantComparisonResponse,
    DemoBaseRequirementsResponse,
    DemoTargetCatalogResponse,
    DemoTargetRequest,
    build_demo_applicant_comparison,
    build_demo_applicant_profile,
    build_demo_base_requirements,
    build_demo_evidence_inventory,
    build_demo_target_catalog,
    build_demo_target_summary,
)
from .grounded_answers import (
    GenerationStatusResponse,
    GroundedAnswerRequest,
    GroundedAnswerResponse,
    NaturalLanguageAnswerResponse,
    NaturalLanguageSubanswer,
)
from .date_presentation import (
    ReviewedDatePresentation,
    load_reviewed_date_presentation,
    validate_highlights_against_official_text,
)
from .jobs import (
    BuildJobRecord,
    BuildJobRepository,
    BuildJobWorker,
    JobConflictError,
    JobNotFoundError,
    JobRepositoryError,
    JobRepositoryUnavailableError,
    JobState,
    JobValidationError,
)
from .runtime import (
    ServiceDependencies,
    ServiceSettings,
    ServiceState,
    VerifiedSourceDocument,
)

GROUNDED_RETRIEVAL_TOP_K = 12
GROUNDED_RETRIEVAL_CANDIDATE_K = 48


BUILD_OPENAPI_EXTRA = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["pdf", "identity"],
                    "properties": {
                        "pdf": {"type": "string", "format": "binary"},
                        "identity": DocumentIdentity.model_json_schema(),
                        "options": BuildOptions.model_json_schema(),
                    },
                },
                "encoding": {
                    "identity": {"contentType": "application/json"},
                    "options": {"contentType": "application/json"},
                },
            }
        },
    }
}


class ApiProblem(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.envelope = ErrorEnvelope(code=code, message=message, details=details)
        super().__init__(message)


def create_app(
    settings: ServiceSettings | None = None,
    dependencies: ServiceDependencies | None = None,
) -> FastAPI:
    """Create an inert app; provider initialization occurs only inside lifespan."""

    selected_settings = settings or ServiceSettings()
    selected_dependencies = dependencies or ServiceDependencies()
    state = ServiceState()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if selected_dependencies.provider_factory is not None:
            try:
                state.provider = selected_dependencies.provider_factory()
            except Exception:
                state.initialization_failed = True
                state.provider = None
        if selected_dependencies.generation_provider_factory is not None:
            try:
                state.generation_provider = selected_dependencies.generation_provider_factory()
            except Exception:
                state.generation_initialization_failed = True
                state.generation_provider = None
        if selected_dependencies.question_understanding_provider_factory is not None:
            try:
                state.question_understanding_provider = (
                    selected_dependencies.question_understanding_provider_factory()
                )
            except Exception:
                state.question_understanding_initialization_failed = True
                state.question_understanding_provider = None
        if selected_settings.job_root is not None:
            try:
                repository_factory = selected_dependencies.repository_factory or BuildJobRepository
                repository = repository_factory(selected_settings.job_root)
                state.job_repository = repository
                worker_factory = selected_dependencies.worker_factory or BuildJobWorker
                worker = worker_factory(
                    repository,
                    max_active=selected_settings.job_worker_max_active,
                    shutdown_grace_seconds=selected_settings.job_shutdown_grace_seconds,
                )
                state.job_worker = worker
                snapshot = await worker.start()
                state.job_initialization_failed = not snapshot.healthy
            except Exception:
                state.job_initialization_failed = True
        if selected_settings.report_plan_paths:
            try:
                state.report_plans = await to_thread.run_sync(
                    partial(_load_report_plans, selected_settings)
                )
                state.page_scope_manifests = await to_thread.run_sync(
                    partial(_load_page_scope_manifests, selected_settings)
                )
                if {plan.document_identity for plan in state.report_plans} != {
                    manifest.document_identity for manifest in state.page_scope_manifests
                }:
                    raise ValueError
                if selected_settings.date_presentation_paths:
                    state.date_presentations = await to_thread.run_sync(
                        partial(
                            _load_date_presentations,
                            selected_settings,
                            state.report_plans,
                        )
                    )
            except Exception:
                state.report_initialization_failed = True
                state.report_plans = ()
                state.page_scope_manifests = ()
                state.date_presentations = ()
                state.date_presentation_initialization_failed = True
        if selected_settings.source_pdf_path is not None:
            try:
                state.source_document = await to_thread.run_sync(
                    partial(
                        _load_verified_source_document,
                        selected_settings,
                        state.report_plans,
                        state.date_presentations,
                    )
                )
            except Exception:
                state.source_document_initialization_failed = True
                state.source_document = None
        if selected_settings.query_intent_catalog_path is not None:
            try:
                state.query_intent_catalog = await to_thread.run_sync(
                    load_query_intent_catalog,
                    selected_settings.query_intent_catalog_path,
                )
            except Exception:
                state.query_intent_initialization_failed = True
                state.query_intent_catalog = None
        try:
            yield
        finally:
            if state.job_worker is not None:
                try:
                    await state.job_worker.stop()
                except Exception:
                    state.job_initialization_failed = True
            elif state.job_repository is not None:
                try:
                    await to_thread.run_sync(state.job_repository.close)
                except Exception:
                    state.job_initialization_failed = True
            state.provider = None
            state.generation_provider = None
            state.question_understanding_provider = None
            state.report_plans = ()
            state.page_scope_manifests = ()
            state.query_intent_catalog = None
            state.date_presentations = ()
            state.source_document = None

    app = FastAPI(
        title="J-Grad Admission RAG API",
        version="1.0.0",
        lifespan=lifespan,
        redirect_slashes=False,
    )
    app.state.service_settings = selected_settings
    app.state.service_state = state

    @app.exception_handler(ApiProblem)
    async def api_problem_handler(_: Request, error: ApiProblem) -> JSONResponse:
        return _error_response(error.status_code, error.envelope)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, __: RequestValidationError) -> JSONResponse:
        return _error_response(422, _error("invalid_request", "request validation failed"))

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, error: StarletteHTTPException) -> JSONResponse:
        if error.status_code == 404:
            return _error_response(404, _error("invalid_request", "route not found"))
        if error.status_code == 405:
            return _error_response(405, _error("invalid_request", "method not allowed"))
        return _error_response(error.status_code, _error("invalid_request", "request failed"))

    @app.exception_handler(Exception)
    async def internal_handler(_: Request, __: Exception) -> JSONResponse:
        return _error_response(500, _error("internal_error", "internal service error"))

    @app.middleware("http")
    async def enforce_media_type(request: Request, call_next):
        if request.method == "POST" and request.url.path in {
            "/v1/knowledge-bases/build",
            "/v1/build-jobs",
            "/v1/corpus/query",
            "/v1/applicant-reports",
            "/v1/query-intents/parse",
            "/v1/base-requirements",
            "/v1/applicant-comparison",
            "/v1/grounded-answers",
            "/v1/natural-language-answers",
        }:
            media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            expected = (
                "multipart/form-data"
                if request.url.path in {"/v1/knowledge-bases/build", "/v1/build-jobs"}
                else "application/json"
            )
            if media_type != expected:
                return _secure_response(
                    request.url.path,
                    _error_response(
                        415,
                        _error("unsupported_media_type", "request content type is unsupported"),
                    ),
                )
        return _secure_response(request.url.path, await call_next(request))

    @app.get("/app", include_in_schema=False)
    def local_app() -> FileResponse:
        return FileResponse(_ui_asset_path("app.html"), media_type="text/html; charset=utf-8")

    @app.get("/assets/app.css", include_in_schema=False)
    def local_app_css() -> FileResponse:
        return FileResponse(_ui_asset_path("app.css"), media_type="text/css; charset=utf-8")

    @app.get("/assets/app.js", include_in_schema=False)
    def local_app_js() -> FileResponse:
        return FileResponse(_ui_asset_path("app.js"), media_type="text/javascript; charset=utf-8")

    @app.get("/assets/overview.js", include_in_schema=False)
    def local_overview_js() -> FileResponse:
        return FileResponse(
            _ui_asset_path("overview.js"), media_type="text/javascript; charset=utf-8"
        )

    @app.api_route(
        "/documents/{document_id}/source.pdf",
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )
    def verified_source_pdf(document_id: str, request: Request) -> Response:
        if state.source_document is None:
            raise ApiProblem(
                503,
                "source_document_unavailable",
                "verified local source PDF is unavailable",
            )
        if document_id != state.source_document.document_id:
            raise ApiProblem(404, "source_document_not_found", "source document was not found")
        if request.query_params:
            raise ApiProblem(422, "invalid_request", "source document query is invalid")
        return _source_pdf_response(request, state.source_document)

    @app.get(
        "/v1/health/live",
        response_model=HealthResponse,
        responses=HEALTH_ERROR_RESPONSES,
        operation_id="getV1HealthLive",
    )
    def live() -> HealthResponse:
        return HealthResponse(status="live", ready=True)

    @app.get(
        "/v1/health/ready",
        response_model=HealthResponse,
        responses=HEALTH_ERROR_RESPONSES,
        operation_id="getV1HealthReady",
    )
    def ready() -> HealthResponse:
        configured = all(
            path is not None
            for path in (
                selected_settings.corpus_root,
                selected_settings.manifest_path,
                selected_settings.policy_path,
            )
        )
        is_ready = configured and state.provider is not None and not state.initialization_failed
        if selected_settings.job_root is not None:
            is_ready = is_ready and _job_worker_ready(state)
        if selected_settings.report_plan_paths:
            is_ready = is_ready and _report_service_ready(state)
        if selected_settings.query_intent_catalog_path is not None:
            is_ready = is_ready and _query_intent_service_ready(state)
        if selected_settings.date_presentation_paths:
            is_ready = is_ready and bool(state.date_presentations)
        if selected_settings.source_pdf_path is not None:
            is_ready = (
                is_ready
                and state.source_document is not None
                and not state.source_document_initialization_failed
            )
        return HealthResponse(status="ready" if is_ready else "not_ready", ready=is_ready)

    @app.get(
        "/v1/generation-status",
        response_model=GenerationStatusResponse,
        operation_id="getV1GenerationStatus",
    )
    def generation_status() -> GenerationStatusResponse:
        return _generation_status_response(selected_settings, state)

    @app.get(
        "/v1/reviewed-documents",
        response_model=ReviewedDocumentCatalogResponse,
        responses=CATALOG_ERROR_RESPONSES,
        operation_id="getV1ReviewedDocuments",
    )
    async def reviewed_documents() -> ReviewedDocumentCatalogResponse:
        if not _report_service_ready(state):
            raise ApiProblem(
                503,
                "report_service_unavailable",
                "reviewed document catalog is unavailable",
            )
        return await to_thread.run_sync(
            partial(_build_reviewed_document_catalog, selected_settings, state)
        )

    @app.get(
        "/v1/target-catalog",
        response_model=DemoTargetCatalogResponse,
        responses=CATALOG_ERROR_RESPONSES,
        operation_id="getV1TargetCatalog",
    )
    async def target_catalog() -> DemoTargetCatalogResponse:
        if not _report_service_ready(state):
            raise ApiProblem(503, "report_service_unavailable", "target catalog is unavailable")
        return await to_thread.run_sync(
            partial(_build_demo_target_catalog_response, selected_settings, state)
        )

    @app.post(
        "/v1/base-requirements",
        response_model=DemoBaseRequirementsResponse,
        responses=REPORT_ERROR_RESPONSES,
        operation_id="postV1BaseRequirements",
    )
    async def base_requirements(request: DemoTargetRequest) -> DemoBaseRequirementsResponse:
        if not _report_service_ready(state):
            raise ApiProblem(
                503,
                "report_service_unavailable",
                "base requirements service is unavailable",
            )
        return await to_thread.run_sync(
            partial(_build_demo_base_requirements_response, request, selected_settings, state)
        )

    @app.post(
        "/v1/applicant-comparison",
        response_model=DemoApplicantComparisonResponse,
        responses=REPORT_ERROR_RESPONSES,
        operation_id="postV1ApplicantComparison",
    )
    async def applicant_comparison(
        request: DemoApplicantComparisonRequest,
    ) -> DemoApplicantComparisonResponse:
        if not _report_service_ready(state):
            raise ApiProblem(
                503,
                "report_service_unavailable",
                "applicant comparison service is unavailable",
            )
        return await to_thread.run_sync(
            partial(_build_demo_applicant_comparison_response, request, selected_settings, state)
        )

    @app.post(
        "/v1/grounded-answers",
        response_model=GroundedAnswerResponse,
        responses=GROUNDED_ERROR_RESPONSES,
        operation_id="postV1GroundedAnswers",
    )
    async def grounded_answer(request: GroundedAnswerRequest) -> GroundedAnswerResponse:
        if not _grounded_answer_service_ready(state):
            raise ApiProblem(
                503,
                "grounded_service_unavailable",
                "grounded answer service is unavailable",
            )
        return await to_thread.run_sync(
            partial(_build_grounded_answer_response, request, selected_settings, state)
        )

    @app.post(
        "/v1/natural-language-answers",
        response_model=NaturalLanguageAnswerResponse,
        responses=GROUNDED_ERROR_RESPONSES,
        operation_id="postV1NaturalLanguageAnswers",
    )
    async def natural_language_answer(
        request: GroundedAnswerRequest,
    ) -> NaturalLanguageAnswerResponse:
        if not _natural_language_service_ready(state):
            code = (
                "online_generation_not_configured"
                if selected_settings.generation_provider_name == "openai-responses"
                else "grounded_service_unavailable"
            )
            message = (
                "online generation service is not configured"
                if code == "online_generation_not_configured"
                else "grounded answer service is unavailable"
            )
            raise ApiProblem(503, code, message)
        return await to_thread.run_sync(
            partial(_build_natural_language_answer_response, request, selected_settings, state)
        )

    @app.post(
        "/v1/query-intents/parse",
        response_model=QueryIntent,
        responses=INTENT_ERROR_RESPONSES,
        operation_id="postV1QueryIntentsParse",
    )
    def parse_intent(request: QueryIntentParseRequest) -> QueryIntent:
        if not _query_intent_service_ready(state):
            raise ApiProblem(
                503,
                "intent_service_unavailable",
                "query intent service is unavailable",
            )
        try:
            intent = parse_query_intent(request.query, state.query_intent_catalog)
        except QueryIntentError:
            raise ApiProblem(422, "invalid_request", "query intent is invalid") from None
        except Exception:
            raise ApiProblem(
                503,
                "intent_service_unavailable",
                "query intent service is unavailable",
            ) from None
        rejected = {
            DiagnosticCode.NO_RECOGNIZED_INTENT,
            DiagnosticCode.AMBIGUOUS_ALIAS,
        }
        if rejected.intersection(intent.diagnostics):
            raise ApiProblem(422, "invalid_request", "query intent is invalid")
        return intent

    @app.post(
        "/v1/knowledge-bases/build",
        response_model=BuildResponse,
        responses=BUILD_ERROR_RESPONSES,
        operation_id="postV1KnowledgeBasesBuild",
        openapi_extra=BUILD_OPENAPI_EXTRA,
    )
    async def build_knowledge_base(request: Request) -> BuildResponse:
        form, pdf, identity_bytes, options = await _parse_build_form(request, selected_settings)
        try:
            return await _build_uploaded_kb(pdf, identity_bytes, options, selected_settings)
        finally:
            await _close_form(form)

    @app.post(
        "/v1/build-jobs",
        response_model=BuildJobReceipt,
        status_code=202,
        responses={status: value for status, value in JOB_ERROR_RESPONSES.items() if status != 404},
        operation_id="postV1BuildJobs",
        openapi_extra=BUILD_OPENAPI_EXTRA,
    )
    async def submit_build_job(request: Request) -> BuildJobReceipt:
        repository, worker = _require_job_runtime(state)
        form, pdf, identity_bytes, options = await _parse_build_form(request, selected_settings)
        try:
            async with _validated_upload(
                pdf, identity_bytes, selected_settings, owned_filename="source.pdf"
            ) as staged:
                pdf_path, identity = staged
                try:
                    record = await to_thread.run_sync(
                        partial(
                            repository.create,
                            canonical_document_identity_bytes(identity),
                            options.model_dump_json().encode("utf-8"),
                            pdf_path,
                        )
                    )
                    worker.wake()
                except JobValidationError:
                    raise ApiProblem(
                        409,
                        "source_binding_mismatch",
                        "PDF does not match reviewed identity",
                    ) from None
                except JobRepositoryError:
                    raise ApiProblem(
                        503, "job_service_unavailable", "job service is unavailable"
                    ) from None
            return _job_receipt(record)
        finally:
            await _close_form(form)

    @app.get(
        "/v1/build-jobs/{job_id}",
        response_model=BuildJobStatus,
        responses=_job_route_responses(),
        operation_id="getV1BuildJob",
    )
    async def get_build_job(job_id: str) -> BuildJobStatus:
        job_id = _canonical_job_id(job_id)
        repository, _ = _require_job_runtime(state)
        return _job_status(await _job_repository_call(repository.get, job_id))

    @app.get(
        "/v1/build-jobs/{job_id}/result",
        response_model=BuildResponse,
        responses=_job_route_responses(),
        operation_id="getV1BuildJobResult",
    )
    async def get_build_job_result(job_id: str) -> BuildResponse:
        job_id = _canonical_job_id(job_id)
        repository, _ = _require_job_runtime(state)
        try:
            return await to_thread.run_sync(repository.read_result, job_id)
        except JobConflictError:
            raise ApiProblem(409, "job_result_not_ready", "job result is not available") from None
        except Exception as error:
            _raise_job_problem(error)

    @app.post(
        "/v1/build-jobs/{job_id}/cancel",
        response_model=BuildJobStatus,
        responses=_job_route_responses(),
        operation_id="postV1BuildJobCancel",
    )
    async def cancel_build_job(job_id: str) -> BuildJobStatus:
        job_id = _canonical_job_id(job_id)
        repository, _ = _require_job_runtime(state)
        current = await _job_repository_call(repository.get, job_id)
        if current.state == JobState.CANCELLED:
            return _job_status(current)
        try:
            return _job_status(await to_thread.run_sync(repository.request_cancel, job_id))
        except JobConflictError:
            try:
                current = await to_thread.run_sync(repository.get, job_id)
            except Exception as error:
                _raise_job_problem(error)
            if current.state == JobState.CANCELLED:
                return _job_status(current)
            raise ApiProblem(409, "job_cancellation_conflict", "job cannot be cancelled") from None
        except Exception as error:
            _raise_job_problem(error)

    @app.post(
        "/v1/build-jobs/{job_id}/retry",
        response_model=BuildJobReceipt,
        status_code=202,
        responses=_job_route_responses(),
        operation_id="postV1BuildJobRetry",
    )
    async def retry_build_job(job_id: str) -> BuildJobReceipt:
        job_id = _canonical_job_id(job_id)
        repository, worker = _require_job_runtime(state)
        try:
            record = await to_thread.run_sync(repository.create_retry, job_id)
        except JobConflictError:
            raise ApiProblem(409, "job_retry_conflict", "job cannot be retried") from None
        except Exception as error:
            _raise_job_problem(error)
        worker.wake()
        return _job_receipt(record)

    @app.delete(
        "/v1/build-jobs/{job_id}",
        status_code=204,
        response_class=Response,
        responses=_job_route_responses(),
        operation_id="deleteV1BuildJob",
    )
    async def delete_build_job(job_id: str) -> Response:
        job_id = _canonical_job_id(job_id)
        repository, _ = _require_job_runtime(state)
        try:
            await to_thread.run_sync(repository.delete_terminal, job_id)
        except JobConflictError:
            raise ApiProblem(409, "job_delete_conflict", "job cannot be deleted") from None
        except Exception as error:
            _raise_job_problem(error)
        return Response(status_code=204)

    @app.post(
        "/v1/corpus/query",
        response_model=CorpusSearchResult,
        responses=QUERY_ERROR_RESPONSES,
        operation_id="postV1CorpusQuery",
    )
    def query_corpus(request: CorpusQueryRequest) -> CorpusSearchResult:
        return _query_corpus(request, selected_settings, state)

    @app.post(
        "/v1/applicant-reports",
        response_model=ApplicantReportResponse,
        responses=REPORT_ERROR_RESPONSES,
        operation_id="postV1ApplicantReports",
    )
    async def applicant_report(request: ApplicantReportRequest) -> ApplicantReportResponse:
        if not _report_service_ready(state):
            raise ApiProblem(
                503,
                "report_service_unavailable",
                "applicant report service is unavailable",
            )
        return await to_thread.run_sync(
            partial(_build_applicant_report_response, request, selected_settings, state)
        )

    return app


async def _parse_build_form(
    request: Request, settings: ServiceSettings
) -> tuple[FormData, UploadFile, bytes, BuildOptions]:
    try:
        form = await request.form(
            max_files=1,
            max_fields=3,
            max_part_size=settings.max_metadata_bytes,
        )
    except StarletteHTTPException as error:
        if error.status_code == 400 and "maximum size" in str(error.detail).lower():
            raise ApiProblem(
                413,
                "payload_too_large",
                "metadata part exceeds configured limit",
            ) from None
        raise ApiProblem(422, "invalid_request", "multipart request is invalid") from None
    except Exception:
        raise ApiProblem(422, "invalid_request", "multipart request is invalid") from None
    try:
        items = list(form.multi_items())
        names = [name for name, _ in items]
        allowed = {"pdf", "identity", "options"}
        if set(names) - allowed or any(names.count(name) != 1 for name in set(names)):
            raise ApiProblem(422, "invalid_request", "multipart fields are invalid")
        values = dict(items)
        if set(values) not in ({"pdf", "identity"}, {"pdf", "identity", "options"}):
            raise ApiProblem(422, "invalid_request", "required multipart fields are missing")
        pdf = values["pdf"]
        identity_value = values["identity"]
        options_value = values.get("options")
        if (
            not isinstance(pdf, UploadFile)
            or not isinstance(identity_value, str)
            or (options_value is not None and not isinstance(options_value, str))
        ):
            raise ApiProblem(422, "invalid_request", "multipart field types are invalid")
        if pdf.content_type != "application/pdf":
            raise ApiProblem(415, "unsupported_media_type", "uploaded file must be a PDF")
        identity_bytes = identity_value.encode("utf-8")
        options_bytes = options_value.encode("utf-8") if options_value is not None else b"{}"
        if (
            len(identity_bytes) > settings.max_metadata_bytes
            or len(options_bytes) > settings.max_metadata_bytes
        ):
            raise ApiProblem(413, "payload_too_large", "metadata part exceeds configured limit")
        try:
            options = BuildOptions.model_validate_json(options_bytes)
        except ValidationError:
            raise ApiProblem(422, "invalid_request", "build options are invalid") from None
        return form, pdf, identity_bytes, options
    except BaseException:
        await _close_form(form)
        raise


async def _close_form(form: FormData) -> None:
    with CancelScope(shield=True):
        await form.close()


async def _build_uploaded_kb(
    upload: UploadFile,
    identity_bytes: bytes,
    options: BuildOptions,
    settings: ServiceSettings,
) -> BuildResponse:
    async with _validated_upload(
        upload, identity_bytes, settings, owned_filename="uploaded.pdf"
    ) as staged:
        pdf_path, identity = staged
        try:
            return await to_thread.run_sync(
                partial(
                    build_response,
                    pdf_path,
                    identity,
                    options,
                    source_pdf="uploaded.pdf",
                    builder=build_document_kb,
                )
            )
        except DocumentBuildError:
            raise ApiProblem(
                409, "source_binding_mismatch", "PDF does not match reviewed identity"
            ) from None
        except Exception:
            raise ApiProblem(500, "internal_error", "knowledge-base build failed") from None


@asynccontextmanager
async def _validated_upload(
    upload: UploadFile,
    identity_bytes: bytes,
    settings: ServiceSettings,
    *,
    owned_filename: str,
) -> AsyncIterator[tuple[Path, DocumentIdentity]]:
    if owned_filename not in {"source.pdf", "uploaded.pdf"}:
        raise ApiProblem(500, "internal_error", "internal service error")
    try:
        identity = load_document_identity_bytes(identity_bytes)
    except DocumentIdentityError:
        raise ApiProblem(422, "invalid_request", "reviewed identity is invalid") from None
    temporary = await to_thread.run_sync(partial(TemporaryDirectory, prefix="jgrad-build-"))
    try:
        pdf_path = Path(temporary.name).resolve() / owned_filename
        digest = hashlib.sha256()
        size = 0
        header = b""
        handle = await open_file(pdf_path, "wb")
        async with handle:
            while chunk := await upload.read(settings.upload_chunk_bytes):
                size += len(chunk)
                if size > settings.max_pdf_bytes:
                    raise ApiProblem(413, "payload_too_large", "PDF exceeds configured limit")
                if len(header) < 5:
                    header += chunk[: 5 - len(header)]
                digest.update(chunk)
                await handle.write(chunk)
        if size == 0 or header != b"%PDF-":
            raise ApiProblem(422, "invalid_request", "uploaded payload is not a valid PDF")
        if digest.hexdigest() != identity.source_pdf_sha256:
            raise ApiProblem(409, "source_binding_mismatch", "PDF does not match reviewed identity")
        yield pdf_path, identity
    finally:
        with CancelScope(shield=True):
            await to_thread.run_sync(temporary.cleanup)


def _job_route_responses() -> dict[int, dict[str, type[ErrorEnvelope]]]:
    return {
        status: value
        for status, value in JOB_ERROR_RESPONSES.items()
        if status in {404, 409, 422, 500, 503}
    }


def _canonical_job_id(value: str) -> str:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise ApiProblem(422, "invalid_request", "job ID or request is invalid") from None
    if str(parsed) != value:
        raise ApiProblem(422, "invalid_request", "job ID or request is invalid")
    return value


def _job_worker_ready(state: ServiceState) -> bool:
    try:
        return (
            state.job_repository is not None
            and state.job_worker is not None
            and state.job_repository.is_open
            and state.job_worker.snapshot.healthy
            and not state.job_initialization_failed
        )
    except Exception:
        return False


def _require_job_runtime(state: ServiceState):
    if not _job_worker_ready(state):
        raise ApiProblem(503, "job_service_unavailable", "job service is unavailable")
    return state.job_repository, state.job_worker


async def _job_repository_call(function, *args):
    try:
        return await to_thread.run_sync(function, *args)
    except Exception as error:
        _raise_job_problem(error)


def _raise_job_problem(error: Exception) -> None:
    if isinstance(error, JobValidationError):
        raise ApiProblem(422, "invalid_request", "job ID or request is invalid") from None
    if isinstance(error, JobNotFoundError):
        raise ApiProblem(404, "job_not_found", "job was not found") from None
    if isinstance(error, JobConflictError):
        raise ApiProblem(
            409, "job_state_conflict", "job state does not allow this operation"
        ) from None
    if isinstance(error, (JobRepositoryUnavailableError, JobRepositoryError)):
        raise ApiProblem(503, "job_service_unavailable", "job service is unavailable") from None
    raise ApiProblem(500, "internal_error", "internal service error") from None


def _job_receipt(record: BuildJobRecord) -> BuildJobReceipt:
    job_id = str(record.job_id)
    return BuildJobReceipt(
        job_id=record.job_id,
        state=record.state.value,
        phase=record.phase.value,
        attempt=record.attempt,
        parent_job_id=record.parent_job_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        result_available=record.result_available,
        status_path=f"/v1/build-jobs/{job_id}",
        result_path=f"/v1/build-jobs/{job_id}/result",
    )


def _job_status(record: BuildJobRecord) -> BuildJobStatus:
    receipt = _job_receipt(record)
    return BuildJobStatus(
        **receipt.model_dump(mode="python"),
        started_at=record.started_at,
        finished_at=record.finished_at,
        diagnostic_code=(record.diagnostic_code.value if record.diagnostic_code else None),
        transitions=tuple(
            {
                "sequence": item.sequence,
                "from_state": item.from_state.value if item.from_state else None,
                "to_state": item.to_state.value,
                "phase": item.phase.value,
                "at": item.at,
                "diagnostic_code": (item.diagnostic_code.value if item.diagnostic_code else None),
            }
            for item in record.transitions
        ),
    )


def _query_corpus(
    request: CorpusQueryRequest,
    settings: ServiceSettings,
    state: ServiceState,
) -> CorpusSearchResult:
    if state.provider is None or state.initialization_failed:
        raise ApiProblem(503, "provider_unavailable", "query provider is unavailable")
    if (
        settings.corpus_root is None
        or settings.manifest_path is None
        or settings.policy_path is None
    ):
        raise ApiProblem(503, "corpus_unavailable", "corpus runtime is unavailable")
    try:
        manifest = load_corpus_manifest(settings.manifest_path)
        policy = load_corpus_version_policy(settings.policy_path)
    except (CorpusManifestError, CorpusVersionSchemaError):
        raise ApiProblem(503, "corpus_unavailable", "corpus runtime is unavailable") from None
    try:
        selection = select_corpus_documents(manifest, policy, request.selection)
    except CorpusSelectionNoMatchError:
        raise ApiProblem(404, "selection_no_match", "selection matched no document") from None
    except CorpusSelectionVersionMismatchError as error:
        raise ApiProblem(
            409,
            "selection_version_mismatch",
            "selection excludes available document versions",
            {"matches": [list(match) for match in error.matches]},
        ) from None
    except CorpusSelectionNotReadyError as error:
        raise ApiProblem(
            409,
            "selection_not_ready",
            "selected documents are not ready",
            {"documents": [list(item) for item in error.document_states]},
        ) from None
    except CorpusSelectionAmbiguousError as error:
        raise ApiProblem(
            409,
            "selection_ambiguous",
            "selection matched multiple documents",
            {"document_ids": list(error.document_ids)},
        ) from None
    except CorpusSelectionRequestError:
        raise ApiProblem(422, "invalid_request", "selection request is invalid") from None
    except CorpusPolicyCompatibilityError:
        raise ApiProblem(503, "corpus_unavailable", "corpus runtime is unavailable") from None
    try:
        context = prepare_corpus_search_context(settings.corpus_root, manifest, policy, selection)
        search = request.search
        with state.provider_lock:
            return search_corpus(
                context,
                search.query,
                state.provider,
                top_k=search.top_k,
                candidate_k=search.candidate_k,
                metadata_filter=MetadataFilter(**search.metadata_filter.model_dump()),
                scope_preference=ScopePreference(**search.scope_preference.model_dump()),
            )
    except CorpusSearchInputError:
        raise ApiProblem(422, "invalid_request", "corpus search request is invalid") from None
    except CorpusSearchProviderError:
        raise ApiProblem(503, "provider_unavailable", "query provider is unavailable") from None
    except CorpusSearchError:
        raise ApiProblem(503, "corpus_unavailable", "corpus runtime is unavailable") from None


def _load_report_plans(settings: ServiceSettings) -> tuple[ReviewedReportPlan, ...]:
    if (
        settings.corpus_root is None
        or settings.manifest_path is None
        or settings.policy_path is None
        or not settings.report_plan_paths
    ):
        raise ValueError
    plans = tuple(load_reviewed_report_plan(path) for path in settings.report_plan_paths)
    plan_ids = tuple(plan.plan_id for plan in plans)
    identities = tuple(plan.document_identity for plan in plans)
    if len(plan_ids) != len(set(plan_ids)) or len(identities) != len(set(identities)):
        raise ValueError
    manifest = load_corpus_manifest(settings.manifest_path)
    policy = load_corpus_version_policy(settings.policy_path)
    audited = audit_corpus_manifest(manifest, settings.corpus_root)
    validate_corpus_version_policy(policy, audited)
    corpus_identities = {entry.identity for entry in audited.entries}
    if any(identity not in corpus_identities for identity in identities):
        raise ValueError
    return plans


def _load_page_scope_manifests(settings: ServiceSettings) -> tuple[PageScopeManifest, ...]:
    if (
        settings.corpus_root is None
        or settings.manifest_path is None
        or not settings.page_scope_manifest_paths
    ):
        raise ValueError
    audited = audit_corpus_manifest(
        load_corpus_manifest(settings.manifest_path),
        settings.corpus_root,
    )
    entries = {entry.identity: entry for entry in audited.entries}
    manifests = []
    for path in settings.page_scope_manifest_paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError
        candidate = load_page_scope_manifest_bytes(path.read_bytes())
        entry = entries.get(candidate.document_identity)
        if entry is None:
            raise ValueError
        kb_path = resolve_registered_corpus_kb_path(settings.corpus_root, entry.kb_path)
        kb = load_document_kb(kb_path)
        source_pages = {
            page
            for collection in (kb.entities, kb.facts, kb.retrieval_units)
            for item in collection
            for page in item.source_pages
        }
        if not source_pages:
            raise ValueError
        manifests.append(load_page_scope_manifest(path, expected_page_count=max(source_pages)))
    manifests = tuple(manifests)
    identities = tuple(manifest.document_identity for manifest in manifests)
    manifest_ids = tuple(manifest.manifest_id for manifest in manifests)
    if len(identities) != len(set(identities)) or len(manifest_ids) != len(set(manifest_ids)):
        raise ValueError
    return manifests


def _load_date_presentations(
    settings: ServiceSettings,
    plans: tuple[ReviewedReportPlan, ...],
) -> tuple[ReviewedDatePresentation, ...]:
    if (
        settings.corpus_root is None
        or settings.manifest_path is None
        or not settings.date_presentation_paths
    ):
        raise ValueError
    audited = audit_corpus_manifest(
        load_corpus_manifest(settings.manifest_path),
        settings.corpus_root,
    )
    entries = {entry.identity.document_id: entry for entry in audited.entries}
    plan_identities = {plan.document_identity.document_id: plan.document_identity for plan in plans}
    presentations = []
    for path in settings.date_presentation_paths:
        presentation = load_reviewed_date_presentation(path)
        identity = plan_identities.get(presentation.document_id)
        entry = entries.get(presentation.document_id)
        if (
            identity is None
            or entry is None
            or entry.identity != identity
            or presentation.source_pdf_sha256 != identity.source_pdf_sha256
        ):
            raise ValueError
        kb_path = resolve_registered_corpus_kb_path(settings.corpus_root, entry.kb_path)
        kb = load_document_kb(kb_path)
        validate_highlights_against_official_text(
            presentation,
            {fact.fact_id: fact.text for fact in kb.facts},
        )
        presentations.append(presentation)
    presentations = tuple(presentations)
    document_ids = tuple(item.document_id for item in presentations)
    if len(document_ids) != len(set(document_ids)):
        raise ValueError
    return presentations


def _load_verified_source_document(
    settings: ServiceSettings,
    plans: tuple[ReviewedReportPlan, ...],
    presentations: tuple[ReviewedDatePresentation, ...],
) -> VerifiedSourceDocument:
    path = settings.source_pdf_path
    document_id = settings.source_pdf_document_id
    expected_sha256 = settings.source_pdf_sha256
    if path is None or document_id is None or expected_sha256 is None:
        raise ValueError
    matching_identities = tuple(
        plan.document_identity
        for plan in plans
        if plan.document_identity.document_id == document_id
    )
    if len(matching_identities) != 1 or matching_identities[0].source_pdf_sha256 != expected_sha256:
        raise ValueError
    matching_presentations = tuple(
        presentation for presentation in presentations if presentation.document_id == document_id
    )
    if settings.date_presentation_paths and (
        len(matching_presentations) != 1
        or matching_presentations[0].source_pdf_sha256 != expected_sha256
    ):
        raise ValueError
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError
    content = path.read_bytes()
    if (
        not content.startswith(b"%PDF-")
        or len(content) > settings.max_pdf_bytes
        or hashlib.sha256(content).hexdigest() != expected_sha256
    ):
        raise ValueError
    return VerifiedSourceDocument(
        document_id=document_id,
        source_pdf_sha256=expected_sha256,
        content=content,
    )


def _build_reviewed_document_catalog(
    settings: ServiceSettings,
    state: ServiceState,
) -> ReviewedDocumentCatalogResponse:
    if (
        settings.corpus_root is None
        or settings.manifest_path is None
        or settings.policy_path is None
    ):
        raise ApiProblem(
            503,
            "report_service_unavailable",
            "reviewed document catalog is unavailable",
        )
    try:
        manifest = load_corpus_manifest(settings.manifest_path)
        policy = load_corpus_version_policy(settings.policy_path)
        audited = audit_corpus_manifest(manifest, settings.corpus_root)
        validated_policy = validate_corpus_version_policy(policy, audited)
        classifications = dict(validated_policy.classification_by_document_id)
        corpus_identities = {entry.identity for entry in audited.entries}
        if any(plan.document_identity not in corpus_identities for plan in state.report_plans):
            raise ValueError

        items = []
        for entry in audited.entries:
            matching_plans = tuple(
                plan for plan in state.report_plans if plan.document_identity == entry.identity
            )
            if len(matching_plans) > 1:
                raise ValueError
            if entry.index_state != "ready" or not matching_plans:
                continue
            plan = matching_plans[0]
            identity = entry.identity
            items.append(
                ReviewedDocumentCatalogItem(
                    identity=ReviewedDocumentPublicIdentity(
                        document_id=identity.document_id,
                        document_family_id=identity.document_family_id,
                        edition_id=identity.edition_id,
                        institution_id=identity.institution_id,
                        institution_name=identity.institution_name,
                        degree_levels=identity.degree_levels,
                        intake_terms=identity.intake_terms,
                        official_title=identity.official_title,
                        official_source_url=identity.official_source_url,
                        publication_date=identity.publication_date,
                        revision_date=identity.revision_date,
                    ),
                    version_classification=classifications[identity.document_id],
                    plan_id=plan.plan_id,
                    coverage_status=plan.coverage_status,
                    covered_categories=plan.covered_categories,
                    reviewed_coverage_statement=plan.reviewed_coverage_statement,
                    limitation_statement=plan.limitation_statement,
                )
            )
        items.sort(key=lambda item: item.identity.document_id)
        return ReviewedDocumentCatalogResponse(items=tuple(items))
    except ApiProblem:
        raise
    except Exception:
        raise ApiProblem(
            503,
            "report_service_unavailable",
            "reviewed document catalog is unavailable",
        ) from None


def _build_demo_target_catalog_response(
    settings: ServiceSettings,
    state: ServiceState,
) -> DemoTargetCatalogResponse:
    reviewed = _build_reviewed_document_catalog(settings, state)
    ready_ids = {item.identity.document_id for item in reviewed.items}
    return build_demo_target_catalog(
        tuple(
            plan for plan in state.report_plans if plan.document_identity.document_id in ready_ids
        )
    )


def _build_demo_base_requirements_response(
    request: DemoTargetRequest,
    settings: ServiceSettings,
    state: ServiceState,
) -> DemoBaseRequirementsResponse:
    plan, evidence, date_presentation = _load_demo_context(request, settings, state)
    try:
        return build_demo_base_requirements(
            request,
            plan,
            evidence,
            date_presentation=date_presentation,
            source_pdf_document_id=(
                state.source_document.document_id if state.source_document is not None else None
            ),
        )
    except (KeyError, ValueError):
        raise ApiProblem(422, "invalid_request", "target selection is invalid") from None


def _build_demo_applicant_comparison_response(
    request: DemoApplicantComparisonRequest,
    settings: ServiceSettings,
    state: ServiceState,
) -> DemoApplicantComparisonResponse:
    plan, evidence, _ = _load_demo_context(request.target, settings, state)
    try:
        return build_demo_applicant_comparison(request, plan, evidence)
    except (KeyError, ValueError, ValidationError):
        raise ApiProblem(422, "invalid_request", "applicant comparison is invalid") from None


def _load_demo_context(
    request: DemoTargetRequest,
    settings: ServiceSettings,
    state: ServiceState,
) -> tuple[
    ReviewedReportPlan,
    ReviewedReportEvidenceBundle,
    ReviewedDatePresentation | None,
]:
    if (
        settings.corpus_root is None
        or settings.manifest_path is None
        or settings.policy_path is None
    ):
        raise ApiProblem(
            503,
            "report_service_unavailable",
            "base requirements service is unavailable",
        )
    try:
        manifest = load_corpus_manifest(settings.manifest_path)
        policy = load_corpus_version_policy(settings.policy_path)
        selection = select_corpus_documents(
            manifest,
            policy,
            CorpusSelectionRequest(document_ids=(request.document_id,)),
        )
    except CorpusSelectionRequestError:
        raise ApiProblem(422, "invalid_request", "target selection is invalid") from None
    except CorpusSelectionNoMatchError:
        raise ApiProblem(404, "report_plan_not_found", "reviewed target was not found") from None
    except (
        CorpusSelectionAmbiguousError,
        CorpusSelectionNotReadyError,
        CorpusSelectionVersionMismatchError,
    ):
        raise ApiProblem(
            409, "corpus_selection_conflict", "reviewed target is unavailable"
        ) from None
    except (CorpusManifestError, CorpusVersionSchemaError, CorpusPolicyCompatibilityError):
        raise ApiProblem(
            503,
            "report_service_unavailable",
            "base requirements service is unavailable",
        ) from None

    selected_identity = selection.selected_documents[0].entry.identity
    matching_plans = tuple(
        plan for plan in state.report_plans if plan.document_identity == selected_identity
    )
    matching_scopes = tuple(
        item for item in state.page_scope_manifests if item.document_identity == selected_identity
    )
    if len(matching_plans) != 1 or len(matching_scopes) != 1:
        raise ApiProblem(
            503,
            "report_service_unavailable",
            "base requirements service is unavailable",
        )
    try:
        evidence = prepare_reviewed_report_evidence(
            settings.corpus_root,
            manifest,
            policy,
            selection,
            state.report_plans,
            matching_scopes[0],
        )
        matching_date_presentations = tuple(
            item
            for item in state.date_presentations
            if item.document_id == selected_identity.document_id
        )
        if len(matching_date_presentations) > 1:
            raise ValueError
        return (
            matching_plans[0],
            evidence,
            matching_date_presentations[0] if matching_date_presentations else None,
        )
    except ReviewedReportEvidenceError as error:
        _raise_report_evidence_problem(error)


def _report_service_ready(state: ServiceState) -> bool:
    return (
        bool(state.report_plans)
        and bool(state.page_scope_manifests)
        and not state.report_initialization_failed
    )


def _grounded_answer_service_ready(state: ServiceState) -> bool:
    return (
        state.provider is not None
        and not state.initialization_failed
        and state.generation_provider is not None
        and not state.generation_initialization_failed
        and _report_service_ready(state)
        and _query_intent_service_ready(state)
    )


def _natural_language_service_ready(state: ServiceState) -> bool:
    return (
        _grounded_answer_service_ready(state)
        and state.question_understanding_provider is not None
        and not state.question_understanding_initialization_failed
    )


def _generation_status_response(
    settings: ServiceSettings,
    state: ServiceState,
) -> GenerationStatusResponse:
    online = settings.generation_provider_name == "openai-responses"
    configured = _natural_language_service_ready(state)
    return GenerationStatusResponse(
        provider=settings.generation_provider_name,
        model=settings.generation_model_name or "grounded-reviewed-v1",
        mode="online_model" if online else "offline_rules",
        configured=configured,
        label=(
            "在线大模型回答"
            if online and configured
            else "在线生成服务未配置"
            if online
            else "离线规则结果"
        ),
    )


def _build_natural_language_answer_response(
    request: GroundedAnswerRequest,
    settings: ServiceSettings,
    state: ServiceState,
) -> NaturalLanguageAnswerResponse:
    analyzer = state.question_understanding_provider
    if analyzer is None:
        raise ApiProblem(
            503, "grounded_service_unavailable", "grounded answer service is unavailable"
        )
    try:
        with state.question_understanding_provider_lock:
            analysis = analyzer.analyze(request.question)
    except GenerationError as error:
        if error.code is GenerationErrorCode.PROVIDER_TIMEOUT:
            raise ApiProblem(
                504, "generation_provider_timeout", "question analysis timed out"
            ) from None
        if error.code is GenerationErrorCode.MISSING_API_KEY:
            raise ApiProblem(
                503,
                "online_generation_not_configured",
                "online generation service is not configured",
            ) from None
        raise ApiProblem(502, "question_analysis_failed", "question analysis failed") from None
    except Exception:
        raise ApiProblem(502, "question_analysis_failed", "question analysis failed") from None

    subanswers: list[NaturalLanguageSubanswer] = []
    for subquestion in analysis.subquestions:
        language = analysis.detected_language.value
        if subquestion.requested_intent == "exam_identity":
            subanswers.append(
                NaturalLanguageSubanswer(
                    subquestion=subquestion,
                    status="interpreted",
                    message=_localized_message(
                        language,
                        "已将这一简称规范化为 TOEIC L&R；这只是问题理解，不是官方受理结论。",
                        "この略称を TOEIC L&R として正規化しました。これは質問理解であり、公式の受理可否ではありません。",
                    ),
                )
            )
            continue
        if subquestion.requested_intent == "language_test_acceptance" and re.search(
            r"\bJLPT\b|\bJ\.TEST\b", subquestion.retrieval_query, re.IGNORECASE
        ):
            subanswers.append(
                NaturalLanguageSubanswer(
                    subquestion=subquestion,
                    status="no_clear_evidence",
                    message=_localized_message(
                        language,
                        "当前审核资料中未找到明确依据。",
                        "現在の確認済み資料では明確な根拠を確認できませんでした。",
                    ),
                )
            )
            continue
        child_request = GroundedAnswerRequest(
            question=subquestion.retrieval_query,
            target=request.target,
            applicant=request.applicant,
        )
        try:
            result = _build_grounded_answer_response(
                child_request,
                settings,
                state,
                generation_question=_localized_generation_question(
                    subquestion.question, analysis.detected_language.value
                ),
            )
        except ApiProblem as error:
            if error.envelope.code in {
                "insufficient_evidence",
                "unsupported_question",
            }:
                status = (
                    "needs_clarification"
                    if subquestion.needs_clarification
                    else "no_clear_evidence"
                )
                message = (
                    _localized_message(
                        language,
                        "需要补充信息后才能在当前审核范围内判断。",
                        "現在の確認範囲で判断するには追加情報が必要です。",
                    )
                    if status == "needs_clarification"
                    else _localized_message(
                        language,
                        "当前审核资料中未找到明确依据。",
                        "現在の確認済み資料では明確な根拠を確認できませんでした。",
                    )
                )
                subanswers.append(
                    NaturalLanguageSubanswer(
                        subquestion=subquestion,
                        status=status,
                        message=message,
                    )
                )
                continue
            raise
        subanswers.append(
            NaturalLanguageSubanswer(
                subquestion=subquestion,
                status="answered",
                message=_localized_message(
                    language,
                    "已找到并通过服务器引用校验的官方依据。",
                    "サーバー側の引用検証を通過した公式根拠を確認しました。",
                ),
                result=result,
            )
        )

    answered = sum(item.status in {"answered", "interpreted"} for item in subanswers)
    unavailable = len(subanswers) - answered
    if language == "ja":
        summary = f"{len(subanswers)}件に分解し、{answered}件に根拠を確認しました。{unavailable}件は確認が必要です。"
    else:
        summary = f"已拆分为 {len(subanswers)} 个子问题：{answered} 个找到已校验依据，{unavailable} 个仍需补充或未找到明确依据。"
    return NaturalLanguageAnswerResponse(
        mode=_generation_status_response(settings, state),
        analysis=analysis,
        summary=summary,
        subanswers=tuple(subanswers),
        missing_context=analysis.missing_context,
        unsupported_parts=analysis.unsupported_parts,
    )


def _localized_generation_question(question: str, language: str) -> str:
    if language in {"zh", "mixed"}:
        return f"请用自然中文回答，并且只回答这个子问题：{question}"
    return f"自然な日本語で、このサブ質問だけに回答してください：{question}"


def _localized_message(language: str, chinese: str, japanese: str) -> str:
    return japanese if language == "ja" else chinese


def _query_intent_service_ready(state: ServiceState) -> bool:
    return state.query_intent_catalog is not None and not state.query_intent_initialization_failed


def _build_grounded_answer_response(
    request: GroundedAnswerRequest,
    settings: ServiceSettings,
    state: ServiceState,
    *,
    generation_question: str | None = None,
) -> GroundedAnswerResponse:
    if (
        settings.corpus_root is None
        or settings.manifest_path is None
        or settings.policy_path is None
        or state.provider is None
        or state.generation_provider is None
        or state.query_intent_catalog is None
    ):
        raise ApiProblem(
            503,
            "grounded_service_unavailable",
            "grounded answer service is unavailable",
        )

    plan, reviewed_evidence, _ = _load_demo_context(request.target, settings, state)
    try:
        manifest = load_corpus_manifest(settings.manifest_path)
        policy = load_corpus_version_policy(settings.policy_path)
        selection = select_corpus_documents(
            manifest,
            policy,
            CorpusSelectionRequest(document_ids=(request.target.document_id,)),
        )
        context = prepare_corpus_search_context(settings.corpus_root, manifest, policy, selection)
        if context.row_count < 1:
            raise ApiProblem(
                422,
                "insufficient_evidence",
                "grounded answer has insufficient reviewed evidence",
            )
        top_k, candidate_k = _bounded_grounded_retrieval_depth(context.row_count)
        with state.provider_lock:
            search_result = search_corpus(
                context,
                request.question,
                state.provider,
                top_k=top_k,
                candidate_k=candidate_k,
                metadata_filter=MetadataFilter(),
                scope_preference=ScopePreference(
                    preferred_scope_targets=(request.target.department_id,),
                    preferred_parent_colleges=(request.target.college_id,),
                ),
            )
        evidence_pack = build_corpus_evidence_pack(search_result)
    except ApiProblem:
        raise
    except CorpusSearchInputError:
        raise ApiProblem(422, "invalid_request", "grounded question is invalid") from None
    except CorpusSearchProviderError:
        raise ApiProblem(503, "provider_unavailable", "query provider is unavailable") from None
    except (
        CorpusManifestError,
        CorpusPolicyCompatibilityError,
        CorpusSearchError,
        CorpusSelectionAmbiguousError,
        CorpusSelectionNoMatchError,
        CorpusSelectionNotReadyError,
        CorpusSelectionRequestError,
        CorpusSelectionVersionMismatchError,
        CorpusVersionSchemaError,
    ):
        raise ApiProblem(
            503,
            "grounded_service_unavailable",
            "grounded answer service is unavailable",
        ) from None
    except Exception:
        raise ApiProblem(
            500,
            "grounded_preparation_failed",
            "grounded answer preparation failed",
        ) from None

    try:
        intent = parse_query_intent(request.question, state.query_intent_catalog)
        if {
            DiagnosticCode.NO_RECOGNIZED_INTENT,
            DiagnosticCode.AMBIGUOUS_ALIAS,
        }.intersection(intent.diagnostics):
            raise ValueError
        profile = build_demo_applicant_profile(request.target, request.applicant)
        report_id = f"grounded-{uuid4().hex}"
        report = build_applicant_report(
            report_id,
            profile,
            intent,
            plan,
            reviewed_evidence,
        )
        target_summary = build_demo_target_summary(state.report_plans, request.target)
        reviewed_answer = _project_reviewed_answer_to_retrieval(
            evidence_pack,
            report.cited_answer,
            intent,
        )
        if reviewed_answer is None:
            raise ApiProblem(
                422,
                "insufficient_evidence",
                "grounded answer has insufficient reviewed evidence",
            )
    except ApiProblem:
        raise
    except ApplicantReportError as error:
        if error.code in {
            ApplicantReportFailure.INVALID_INPUT,
            ApplicantReportFailure.UNSUPPORTED_INTENT,
        }:
            raise ApiProblem(
                422,
                "unsupported_question",
                "question is outside the current reviewed scope",
            ) from None
        if error.code is ApplicantReportFailure.PLAN_EVIDENCE_MISMATCH:
            raise ApiProblem(
                409,
                "report_preparation_failed",
                "reviewed report preparation failed",
            ) from None
        raise ApiProblem(
            500,
            "grounded_preparation_failed",
            "grounded answer preparation failed",
        ) from None
    except (QueryIntentError, ValidationError, ValueError):
        raise ApiProblem(
            422,
            "unsupported_question",
            "question is outside the current reviewed scope",
        ) from None
    except Exception:
        raise ApiProblem(
            500,
            "grounded_preparation_failed",
            "grounded answer preparation failed",
        ) from None

    grounded_target = GroundedRagTarget(
        document_id=request.target.document_id,
        application_label=" / ".join(
            (
                target_summary.school_name,
                target_summary.degree_name,
                target_summary.intake_name,
                target_summary.college_name,
                target_summary.department_name,
            )
        ),
        scope_targets=(request.target.department_id,),
        parent_college=request.target.college_id,
    )
    try:
        with state.generation_provider_lock:
            answer = run_grounded_rag(
                state.generation_provider,
                request_id=f"request:{uuid4().hex}",
                question=generation_question or request.question,
                target=grounded_target,
                applicant_facts=(),
                evidence_pack=evidence_pack,
                cited_answer=reviewed_answer,
            )
    except GroundedRagError as error:
        _raise_grounded_problem(error.code)
    except Exception:
        raise ApiProblem(
            500,
            "grounded_generation_failed",
            "grounded answer generation failed",
        ) from None
    cited_fact_ids = tuple(item.fact_id for item in answer.citation_inventory)
    try:
        evidence = build_demo_evidence_inventory(
            plan,
            reviewed_evidence,
            request.target,
            cited_fact_ids,
            source_pdf_document_id=(
                state.source_document.document_id if state.source_document is not None else None
            ),
        )
        return GroundedAnswerResponse(
            target=target_summary,
            reviewed_scope_statement=plan.reviewed_coverage_statement,
            official_source_url=plan.document_identity.official_source_url,
            local_pdf_url=(
                f"/documents/{request.target.document_id}/source.pdf"
                if state.source_document is not None
                and state.source_document.document_id == request.target.document_id
                else None
            ),
            answer=answer,
            evidence=evidence,
        )
    except Exception:
        raise ApiProblem(
            500,
            "grounded_presentation_failed",
            "grounded answer presentation failed",
        ) from None


def _bounded_grounded_retrieval_depth(row_count: int) -> tuple[int, int]:
    """Keep model-facing retrieval independent of selected-document size."""

    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 1:
        raise ValueError("row_count must be a positive integer")
    top_k = min(GROUNDED_RETRIEVAL_TOP_K, row_count)
    return top_k, min(GROUNDED_RETRIEVAL_CANDIDATE_K, row_count)


def _project_reviewed_answer_to_retrieval(
    evidence_pack: EvidencePack,
    cited_answer: CitedAnswer,
    intent: QueryIntent,
) -> CitedAnswer | None:
    """Project reviewed findings to the exact bounded retrieval result.

    The applicant report is intentionally a whole-plan audit object.  A natural-language
    answer must instead expose only intent-matched findings whose complete, server-owned
    citation set occurred in this request's bounded retrieval result.  No citation is
    inserted from the wider reviewed bundle after retrieval, and no retained rule state
    is rewritten or discarded based on another retained finding.
    """

    retrieved = {
        (
            record.document_id,
            record.fact_id,
            record.source_pages,
            "primary" if record.role == "primary" else "reference",
        )
        for record in evidence_pack.primary_evidence + evidence_pack.attached_reference_evidence
    }
    if not retrieved or not cited_answer.interaction_analysis_complete:
        return None

    prefixes_by_category = {
        "application_dates": ("application_dates.",),
        "contacts_forms": ("contacts.",),
        "eligibility": ("eligibility.",),
        "fees": ("fees.",),
        "language_tests": ("language.",),
    }
    allowed_subject_prefixes = tuple(
        prefix
        for category in intent.requested_categories
        for prefix in prefixes_by_category.get(category.value, ())
    )
    if not allowed_subject_prefixes:
        return None

    def citation_key(citation: Any) -> tuple[str, str, tuple[int, ...], str]:
        return (
            citation.document_id,
            citation.fact_id,
            citation.source_pages,
            "primary" if citation.role.value == "primary" else "reference",
        )

    candidates = tuple(
        finding
        for finding in cited_answer.rule_findings
        if finding.subject_key.startswith(allowed_subject_prefixes)
        and {citation_key(citation) for citation in finding.citations} <= retrieved
    )
    if not candidates:
        return None

    def subject_family(subject_key: str) -> str:
        return re.sub(r"-(?:apr|sep)$", "", subject_key)

    active_families = {
        subject_family(finding.subject_key)
        for finding in candidates
        if finding.original_status is ApplicabilityStatus.CONFIRMED
        and finding.disposition is ResolutionDisposition.ACTIVE
    }
    explicitly_requested_fragments: tuple[str, ...] = ()
    normalized_query = intent.query.casefold()
    if any(token in normalized_query for token in ("提出", "提交", "成绩单", "report")):
        explicitly_requested_fragments += ("-report-",)
    if any(token in normalized_query for token in ("受験日", "考试日期", "試験日")):
        explicitly_requested_fragments += ("-test-date-",)
    if "g179" in normalized_query:
        explicitly_requested_fragments += ("-g179-",)
    requested_families = {
        subject_family(finding.subject_key)
        for finding in candidates
        if any(fragment in finding.subject_key for fragment in explicitly_requested_fragments)
    }
    pending_families = {
        subject_family(finding.subject_key)
        for finding in candidates
        if finding.disposition is ResolutionDisposition.PENDING
    }
    selected_families = active_families | requested_families
    if not selected_families:
        selected_families = pending_families
    if not selected_families:
        return None
    findings = tuple(
        finding
        for finding in candidates
        if subject_family(finding.subject_key) in selected_families
    )

    rule_ids = tuple(sorted(finding.rule_id for finding in findings))
    selected_rules = set(rule_ids)
    warnings = tuple(
        warning
        for warning in cited_answer.interaction_warnings
        if set(warning.rule_ids) <= selected_rules
        and {citation_key(citation) for citation in warning.citations} <= retrieved
    )
    missing_information = tuple(
        item for item in cited_answer.missing_information if item.rule_id in selected_rules
    )
    process_notices = tuple(
        item
        for item in cited_answer.process_notices
        if item.rule_ids and set(item.rule_ids) <= selected_rules
    )
    interaction_steps = {warning.source_interaction_step_id for warning in warnings} | {
        step_id
        for notice in process_notices
        for step_id in notice.source_step_ids
        if step_id.startswith("interaction:")
    }
    source_trace_step_ids = (
        tuple(f"applicability:{rule_id}" for rule_id in rule_ids)
        + tuple(f"resolution:{rule_id}" for rule_id in rule_ids)
        + tuple(sorted(interaction_steps))
    )
    inventory = {
        (
            citation.document_id,
            citation.fact_id,
            citation.source_pages,
            citation.role.value,
            citation.source_rule_id,
            citation.source_step_ids,
        ): citation
        for source in findings + warnings
        for citation in source.citations
    }
    citation_inventory = tuple(inventory[key] for key in sorted(inventory))
    review_notice_kinds = {
        ProcessNoticeKind.MISSING_OFFICIAL_EVIDENCE,
        ProcessNoticeKind.OVERRIDE_EVIDENCE_INCOMPLETE,
        ProcessNoticeKind.INTERACTION_EVIDENCE_INCOMPLETE,
        ProcessNoticeKind.SCOPE_INPUT_CONFLICT,
        ProcessNoticeKind.INTERACTION_ANALYSIS_INCOMPLETE,
    }
    if warnings or any(item.kind in review_notice_kinds for item in process_notices):
        report_status = ReportStatus.NEEDS_REVIEW
    elif (
        missing_information
        or any(item.disposition is ResolutionDisposition.PENDING for item in findings)
        or any(item.kind is ProcessNoticeKind.MISSING_SCOPE for item in process_notices)
    ):
        report_status = ReportStatus.NEEDS_INFORMATION
    else:
        report_status = ReportStatus.COMPLETE

    try:
        return CitedAnswer(
            answer_id=cited_answer.answer_id,
            source_trace_id=cited_answer.source_trace_id,
            document_id=cited_answer.document_id,
            source_kb_sha256=cited_answer.source_kb_sha256,
            source_pdf_sha256=cited_answer.source_pdf_sha256,
            report_status=report_status,
            interaction_analysis_complete=True,
            source_rule_ids=rule_ids,
            source_trace_step_ids=source_trace_step_ids,
            rule_findings=findings,
            interaction_warnings=warnings,
            missing_information=missing_information,
            process_notices=process_notices,
            citation_inventory=citation_inventory,
        )
    except (ValidationError, ValueError):
        return None


def _raise_grounded_problem(code: GroundedRagErrorCode) -> None:
    mapping = {
        GroundedRagErrorCode.INVALID_INPUT: (422, "invalid_request"),
        GroundedRagErrorCode.INSUFFICIENT_EVIDENCE: (422, "insufficient_evidence"),
        GroundedRagErrorCode.EVIDENCE_MISMATCH: (409, "evidence_mismatch"),
        GroundedRagErrorCode.RULE_STATE_MISMATCH: (409, "rule_state_mismatch"),
        GroundedRagErrorCode.PROVIDER_UNAVAILABLE: (503, "generation_provider_unavailable"),
        GroundedRagErrorCode.PROVIDER_TIMEOUT: (504, "generation_provider_timeout"),
        GroundedRagErrorCode.PROVIDER_REFUSAL: (502, "generation_provider_refusal"),
        GroundedRagErrorCode.INCOMPLETE_RESPONSE: (502, "incomplete_response"),
        GroundedRagErrorCode.MALFORMED_OUTPUT: (502, "malformed_output"),
        GroundedRagErrorCode.INVALID_CITATION: (502, "invalid_citation"),
        GroundedRagErrorCode.UNSUPPORTED_CLAIM: (502, "unsupported_claim"),
    }
    status, public_code = mapping[code]
    raise ApiProblem(status, public_code, "grounded answer could not be produced") from None


def _build_applicant_report_response(
    request: ApplicantReportRequest,
    settings: ServiceSettings,
    state: ServiceState,
) -> ApplicantReportResponse:
    if (
        settings.corpus_root is None
        or settings.manifest_path is None
        or settings.policy_path is None
    ):
        raise ApiProblem(
            503,
            "report_service_unavailable",
            "applicant report service is unavailable",
        )
    try:
        manifest = load_corpus_manifest(settings.manifest_path)
        policy = load_corpus_version_policy(settings.policy_path)
    except (CorpusManifestError, CorpusVersionSchemaError):
        raise ApiProblem(
            503,
            "report_service_unavailable",
            "applicant report service is unavailable",
        ) from None
    try:
        selection = select_corpus_documents(manifest, policy, request.selection)
    except CorpusSelectionRequestError:
        raise ApiProblem(422, "invalid_request", "applicant report request is invalid") from None
    except CorpusSelectionNoMatchError:
        raise ApiProblem(
            404,
            "report_plan_not_found",
            "no reviewed report plan matches the selection",
        ) from None
    except (
        CorpusSelectionAmbiguousError,
        CorpusSelectionNotReadyError,
        CorpusSelectionVersionMismatchError,
    ):
        raise ApiProblem(
            409,
            "corpus_selection_conflict",
            "corpus selection cannot produce one current report",
        ) from None
    except CorpusPolicyCompatibilityError:
        raise ApiProblem(
            503,
            "report_service_unavailable",
            "applicant report service is unavailable",
        ) from None
    if len(selection.selected_documents) != 1:
        raise ApiProblem(
            409,
            "corpus_selection_conflict",
            "corpus selection cannot produce one current report",
        )
    selected_identity = selection.selected_documents[0].entry.identity
    matching_plans = tuple(
        plan for plan in state.report_plans if plan.document_identity == selected_identity
    )
    if not matching_plans:
        raise ApiProblem(
            404,
            "report_plan_not_found",
            "no reviewed report plan matches the selection",
        )
    if len(matching_plans) != 1:
        raise ApiProblem(
            503,
            "report_service_unavailable",
            "applicant report service is unavailable",
        )
    matching_page_scopes = tuple(
        manifest
        for manifest in state.page_scope_manifests
        if manifest.document_identity == selected_identity
    )
    if len(matching_page_scopes) != 1:
        raise ApiProblem(
            503,
            "report_service_unavailable",
            "applicant report service is unavailable",
        )
    try:
        evidence = prepare_reviewed_report_evidence(
            settings.corpus_root,
            manifest,
            policy,
            selection,
            state.report_plans,
            matching_page_scopes[0],
        )
    except ReviewedReportEvidenceError as error:
        _raise_report_evidence_problem(error)
    plan = matching_plans[0]
    try:
        report = build_applicant_report(
            request.report_id,
            request.profile,
            request.intent,
            plan,
            evidence,
        )
    except ApplicantReportError as error:
        if error.code in {
            ApplicantReportFailure.INVALID_INPUT,
            ApplicantReportFailure.UNSUPPORTED_INTENT,
        }:
            raise ApiProblem(
                422,
                "invalid_request",
                "applicant report request is invalid",
            ) from None
        if error.code is ApplicantReportFailure.PLAN_EVIDENCE_MISMATCH:
            raise ApiProblem(
                409,
                "report_preparation_failed",
                "reviewed report preparation failed",
            ) from None
        raise ApiProblem(
            500,
            "report_generation_failed",
            "applicant report generation failed",
        ) from None
    except Exception:
        raise ApiProblem(
            500,
            "report_generation_failed",
            "applicant report generation failed",
        ) from None
    try:
        markdown = render_applicant_report_markdown(report)
        return ApplicantReportResponse(report=report, markdown=markdown)
    except Exception:
        raise ApiProblem(
            500,
            "report_generation_failed",
            "applicant report generation failed",
        ) from None


def _raise_report_evidence_problem(error: ReviewedReportEvidenceError) -> None:
    if error.code is ReviewedReportEvidenceFailure.PLAN_NOT_FOUND:
        raise ApiProblem(
            404,
            "report_plan_not_found",
            "no reviewed report plan matches the selection",
        ) from None
    if error.code in {
        ReviewedReportEvidenceFailure.SELECTION_CARDINALITY,
        ReviewedReportEvidenceFailure.SELECTION_STALE,
    }:
        raise ApiProblem(
            409,
            "corpus_selection_conflict",
            "corpus selection cannot produce one current report",
        ) from None
    if error.code in {
        ReviewedReportEvidenceFailure.CORPUS_AUDIT_FAILED,
        ReviewedReportEvidenceFailure.KB_UNAVAILABLE,
        ReviewedReportEvidenceFailure.KB_QUALITY_FAILED,
    }:
        raise ApiProblem(
            503,
            "report_service_unavailable",
            "applicant report service is unavailable",
        ) from None
    raise ApiProblem(
        409,
        "report_preparation_failed",
        "reviewed report preparation failed",
    ) from None


def _error(code: str, message: str, details: dict[str, Any] | None = None) -> ErrorEnvelope:
    return ErrorEnvelope(code=code, message=message, details=details)


def _error_response(status: int, envelope: ErrorEnvelope) -> JSONResponse:
    return JSONResponse(status_code=status, content=envelope.model_dump(mode="json"))


def _ui_asset_path(filename: str) -> Path:
    return Path(__file__).with_name("static") / filename


def _source_pdf_response(request: Request, document: VerifiedSourceDocument) -> Response:
    content = document.content
    size = len(content)
    range_header = request.headers.get("range")
    start = 0
    end = size - 1
    status_code = 200
    if range_header is not None:
        try:
            if not range_header.startswith("bytes=") or "," in range_header:
                raise ValueError
            value = range_header.removeprefix("bytes=")
            start_value, separator, end_value = value.partition("-")
            if separator != "-" or (not start_value and not end_value):
                raise ValueError
            if start_value:
                start = int(start_value)
                end = int(end_value) if end_value else size - 1
                if start < 0 or start >= size or end < start:
                    raise ValueError
                end = min(end, size - 1)
            else:
                suffix_length = int(end_value)
                if suffix_length <= 0:
                    raise ValueError
                start = max(size - suffix_length, 0)
                end = size - 1
            status_code = 206
        except (TypeError, ValueError):
            return Response(
                status_code=416,
                headers={
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "no-store",
                    "Content-Range": f"bytes */{size}",
                    "Content-Type": "application/pdf",
                    "X-Content-Type-Options": "nosniff",
                },
            )
    selected_length = end - start + 1
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store",
        "Content-Disposition": f'inline; filename="{document.document_id}.pdf"',
        "Content-Length": str(selected_length),
        "X-Content-Type-Options": "nosniff",
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    body = b"" if request.method == "HEAD" else content[start : end + 1]
    response = Response(
        content=body,
        status_code=status_code,
        media_type="application/pdf",
        headers=headers,
    )
    response.headers["Content-Length"] = str(selected_length)
    return response


def _secure_response(path: str, response: Response) -> Response:
    if (
        path.startswith("/v1/")
        or path == "/app"
        or path.startswith("/assets/")
        or path.startswith("/documents/")
    ):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
    if path == "/app" or path.startswith("/assets/"):
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


__all__ = ["create_app"]
