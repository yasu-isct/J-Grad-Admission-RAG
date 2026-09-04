"""FastAPI application factory for the local versioned service."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, AsyncIterator
from uuid import UUID

from anyio import CancelScope, open_file, to_thread
from fastapi import FastAPI, Request, Response
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
    canonical_document_identity_bytes,
    load_document_identity_bytes,
)
from .build_execution import build_response
from .contracts import (
    BUILD_ERROR_RESPONSES,
    HEALTH_ERROR_RESPONSES,
    JOB_ERROR_RESPONSES,
    QUERY_ERROR_RESPONSES,
    BuildJobReceipt,
    BuildJobStatus,
    BuildOptions,
    BuildResponse,
    CorpusQueryRequest,
    ErrorEnvelope,
    HealthResponse,
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
        }:
            media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            expected = (
                "multipart/form-data"
                if request.url.path in {"/v1/knowledge-bases/build", "/v1/build-jobs"}
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
        if selected_settings.job_root is not None:
            is_ready = is_ready and _job_worker_ready(state)
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


def _error(code: str, message: str, details: dict[str, Any] | None = None) -> ErrorEnvelope:
    return ErrorEnvelope(code=code, message=message, details=details)


def _error_response(status: int, envelope: ErrorEnvelope) -> JSONResponse:
    return JSONResponse(status_code=status, content=envelope.model_dump(mode="json"))


__all__ = ["create_app"]
