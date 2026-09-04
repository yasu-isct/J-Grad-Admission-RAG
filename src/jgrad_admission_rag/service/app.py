"""FastAPI application factory for the local versioned service."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from anyio import CancelScope
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.datastructures import FormData, UploadFile

from ..builder.kb_builder import DocumentBuildError, build_document_kb
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
)
from ..retrieval.metadata_search import MetadataFilter, ScopePreference
from ..schemas.corpus_manifest import CorpusManifestError, load_corpus_manifest
from ..schemas.corpus_version import CorpusVersionSchemaError, load_corpus_version_policy
from ..schemas.document_identity import (
    DocumentIdentity,
    DocumentIdentityError,
    load_document_identity_bytes,
)
from ..schemas.document_kb import BuildQualityThresholds, DocumentKnowledgeBase
from .contracts import (
    BUILD_ERROR_RESPONSES,
    HEALTH_ERROR_RESPONSES,
    QUERY_ERROR_RESPONSES,
    BuildOptions,
    BuildResponse,
    BuildSummary,
    CorpusQueryRequest,
    ErrorEnvelope,
    HealthResponse,
)
from .runtime import ServiceDependencies, ServiceSettings, ServiceState


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
        yield
        state.provider = None

    app = FastAPI(
        title="J-Grad Admission RAG API",
        version="1.0.0",
        lifespan=lifespan,
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
            "/v1/corpus/query",
        }:
            media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            expected = (
                "multipart/form-data"
                if request.url.path == "/v1/knowledge-bases/build"
                else "application/json"
            )
            if media_type != expected:
                return _error_response(
                    415,
                    _error("unsupported_media_type", "request content type is unsupported"),
                )
        return await call_next(request)

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
        return HealthResponse(status="ready" if is_ready else "not_ready", ready=is_ready)

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
        "/v1/corpus/query",
        response_model=CorpusSearchResult,
        responses=QUERY_ERROR_RESPONSES,
        operation_id="postV1CorpusQuery",
    )
    def query_corpus(request: CorpusQueryRequest) -> CorpusSearchResult:
        return _query_corpus(request, selected_settings, state)

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
    try:
        identity = load_document_identity_bytes(identity_bytes)
    except DocumentIdentityError:
        raise ApiProblem(422, "invalid_request", "reviewed identity is invalid") from None
    with TemporaryDirectory(prefix="jgrad-build-") as temporary:
        pdf_path = Path(temporary) / "uploaded.pdf"
        digest = hashlib.sha256()
        size = 0
        header = b""
        with pdf_path.open("wb") as handle:
            while chunk := await upload.read(settings.upload_chunk_bytes):
                size += len(chunk)
                if size > settings.max_pdf_bytes:
                    raise ApiProblem(413, "payload_too_large", "PDF exceeds configured limit")
                if len(header) < 5:
                    header += chunk[: 5 - len(header)]
                digest.update(chunk)
                handle.write(chunk)
        if size == 0 or header != b"%PDF-":
            raise ApiProblem(422, "invalid_request", "uploaded payload is not a valid PDF")
        if digest.hexdigest() != identity.source_pdf_sha256:
            raise ApiProblem(409, "source_binding_mismatch", "PDF does not match reviewed identity")
        try:
            kb = build_document_kb(
                pdf_path,
                identity,
                max_chars=options.max_chars,
                short_fact_threshold=options.short_fact_threshold,
                reference_ambiguity_margin=options.reference_ambiguity_margin,
                quality_thresholds=BuildQualityThresholds.model_validate(
                    options.quality_thresholds.model_dump()
                ),
            )
        except DocumentBuildError:
            raise ApiProblem(
                409, "source_binding_mismatch", "PDF does not match reviewed identity"
            ) from None
        except Exception:
            raise ApiProblem(500, "internal_error", "knowledge-base build failed") from None
        kb = DocumentKnowledgeBase.model_validate(kb.model_dump(mode="json"))
        kb.manifest.source_pdf = "uploaded.pdf"
        passed = kb.diagnostics.quality_gate.passed
        return BuildResponse(
            status="quality_passed" if passed else "quality_failed",
            accepted_for_indexing=passed,
            knowledge_base=kb,
            summary=_build_summary(kb),
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


def _build_summary(kb: DocumentKnowledgeBase) -> BuildSummary:
    diagnostics = kb.diagnostics
    return BuildSummary(
        document_id=kb.manifest.document_id,
        kb_schema_version=kb.manifest.schema_version,
        chunks=kb.manifest.chunk_count,
        facts=len(kb.facts),
        retrieval_units=len(kb.retrieval_units),
        dropped_chunks=diagnostics.dropped_chunk_count,
        dropped_chunk_reasons=dict(diagnostics.dropped_chunk_reasons),
        missing_source_pages=len(diagnostics.missing_source_page_fact_ids),
        missing_section_paths=len(diagnostics.missing_section_path_fact_ids),
        empty_or_noninformative=len(diagnostics.empty_or_noninformative_fact_ids),
        short_facts=len(diagnostics.short_fact_ids),
        unknown_scopes=len(diagnostics.unknown_scope_fact_ids),
        max_chunk_chars=diagnostics.max_chunk_chars,
        oversized_facts=len(diagnostics.oversized_fact_ids),
        reference_links=kb.manifest.reference_link_count,
        reference_status_counts=dict(diagnostics.reference_status_counts),
        quality_gate_passed=diagnostics.quality_gate.passed,
        quality_gate_violations=tuple(
            {
                "metric": item.metric,
                "actual": item.actual,
                "limit": item.limit,
                "related_id_count": len(item.related_ids),
                "related_claim_count": len(item.related_claims),
            }
            for item in diagnostics.quality_gate.violations
        ),
    )


def _error(code: str, message: str, details: dict[str, Any] | None = None) -> ErrorEnvelope:
    return ErrorEnvelope(code=code, message=message, details=details)


def _error_response(status: int, envelope: ErrorEnvelope) -> JSONResponse:
    return JSONResponse(status_code=status, content=envelope.model_dump(mode="json"))


__all__ = ["create_app"]
