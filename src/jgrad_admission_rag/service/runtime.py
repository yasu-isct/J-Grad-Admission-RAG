"""Immutable server-owned configuration and mutable lifecycle state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..retrieval.embedding import EmbeddingProvider
from ..generation.provider import GenerationProvider
from ..generation.question_analysis import QuestionUnderstandingProvider
from ..reasoning.query_intent import QueryIntentCatalog
from ..reasoning.reviewed_report_plan import ReviewedReportPlan
from ..schemas.page_scope_manifest import PageScopeManifest
from .date_presentation import ReviewedDatePresentation
from .response_cache import ExactResponseCache


class ServiceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_root: Path | None = None
    manifest_path: Path | None = None
    policy_path: Path | None = None
    report_plan_paths: tuple[Path, ...] = ()
    page_scope_manifest_paths: tuple[Path, ...] = ()
    query_intent_catalog_path: Path | None = None
    date_presentation_paths: tuple[Path, ...] = ()
    source_pdf_path: Path | None = None
    source_pdf_document_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$",
    )
    source_pdf_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    max_pdf_bytes: int = Field(default=25 * 1024 * 1024, gt=0, strict=True)
    max_metadata_bytes: int = Field(default=256 * 1024, gt=0, strict=True)
    upload_chunk_bytes: int = Field(default=64 * 1024, gt=0, strict=True)
    job_root: Path | None = None
    job_worker_max_active: int = Field(default=1, ge=1, le=8, strict=True)
    job_shutdown_grace_seconds: float = Field(default=0.25, ge=0, le=60, strict=True)
    generation_provider_name: str = Field(
        default="reviewed-state-offline",
        pattern=r"^(reviewed-state-offline|openai-responses|deepseek-responses)$",
    )
    generation_model_name: str | None = Field(default=None, min_length=1, max_length=200)
    generation_timeout_seconds: float | None = Field(default=None, gt=0, le=120)
    generation_max_retries: int = Field(default=1, ge=0, le=2, strict=True)
    natural_answer_cache_capacity: int = Field(default=128, ge=1, le=1_024, strict=True)
    natural_answer_cache_ttl_seconds: int = Field(default=600, ge=1, le=3_600, strict=True)

    @model_validator(mode="after")
    def query_paths_must_be_complete_and_absolute(self) -> ServiceSettings:
        paths = (self.corpus_root, self.manifest_path, self.policy_path)
        if any(path is not None for path in paths) and not all(path is not None for path in paths):
            raise ValueError("query runtime paths must be supplied together")
        if any(path is not None and not path.is_absolute() for path in paths):
            raise ValueError("query runtime paths must be absolute")
        if any(not path.is_absolute() for path in self.report_plan_paths):
            raise ValueError("reviewed report plan paths must be absolute")
        if any(not path.is_absolute() for path in self.page_scope_manifest_paths):
            raise ValueError("page scope manifest paths must be absolute")
        if bool(self.report_plan_paths) != bool(self.page_scope_manifest_paths):
            raise ValueError("report plans and page scope manifests must be configured together")
        if (
            self.query_intent_catalog_path is not None
            and not self.query_intent_catalog_path.is_absolute()
        ):
            raise ValueError("query intent catalog path must be absolute")
        if any(not path.is_absolute() for path in self.date_presentation_paths):
            raise ValueError("reviewed date presentation paths must be absolute")
        source_fields = (
            self.source_pdf_path,
            self.source_pdf_document_id,
            self.source_pdf_sha256,
        )
        if any(value is not None for value in source_fields) and not all(
            value is not None for value in source_fields
        ):
            raise ValueError("verified source PDF settings must be supplied together")
        if self.source_pdf_path is not None and (
            not self.source_pdf_path.is_absolute()
            or self.source_pdf_path.resolve(strict=False) != self.source_pdf_path
        ):
            raise ValueError("verified source PDF path must be canonical and absolute")
        if self.job_root is not None and (
            not self.job_root.is_absolute() or self.job_root.resolve(strict=False) != self.job_root
        ):
            raise ValueError("job repository root must be canonical and absolute")
        if (self.generation_provider_name != "reviewed-state-offline") != bool(
            self.generation_model_name
        ):
            raise ValueError("online generation requires one model; offline generation has none")
        return self


@dataclass(frozen=True, slots=True)
class ServiceDependencies:
    provider_factory: Callable[[], EmbeddingProvider] | None = None
    generation_provider_factory: Callable[[], GenerationProvider] | None = None
    question_understanding_provider_factory: Callable[[], QuestionUnderstandingProvider] | None = (
        None
    )
    repository_factory: Callable[[Path], Any] | None = None
    worker_factory: Callable[..., Any] | None = None


@dataclass(frozen=True, slots=True)
class VerifiedSourceDocument:
    document_id: str
    source_pdf_sha256: str
    content: bytes


@dataclass(slots=True)
class ServiceState:
    provider: EmbeddingProvider | None = None
    initialization_failed: bool = False
    provider_lock: Lock = field(default_factory=Lock)
    generation_provider: GenerationProvider | None = None
    generation_initialization_failed: bool = False
    generation_provider_lock: Lock = field(default_factory=Lock)
    question_understanding_provider: QuestionUnderstandingProvider | None = None
    question_understanding_initialization_failed: bool = False
    question_understanding_provider_lock: Lock = field(default_factory=Lock)
    natural_answer_cache: ExactResponseCache[Any] | None = None
    job_repository: Any | None = None
    job_worker: Any | None = None
    job_initialization_failed: bool = False
    report_plans: tuple[ReviewedReportPlan, ...] = ()
    page_scope_manifests: tuple[PageScopeManifest, ...] = ()
    report_initialization_failed: bool = False
    query_intent_catalog: QueryIntentCatalog | None = None
    query_intent_initialization_failed: bool = False
    date_presentations: tuple[ReviewedDatePresentation, ...] = ()
    date_presentation_initialization_failed: bool = False
    source_document: VerifiedSourceDocument | None = None
    source_document_initialization_failed: bool = False


__all__ = [
    "ServiceDependencies",
    "ServiceSettings",
    "ServiceState",
    "VerifiedSourceDocument",
]
