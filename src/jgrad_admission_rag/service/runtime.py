"""Immutable server-owned configuration and mutable lifecycle state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..retrieval.embedding import EmbeddingProvider


class ServiceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_root: Path | None = None
    manifest_path: Path | None = None
    policy_path: Path | None = None
    max_pdf_bytes: int = Field(default=25 * 1024 * 1024, gt=0, strict=True)
    max_metadata_bytes: int = Field(default=256 * 1024, gt=0, strict=True)
    upload_chunk_bytes: int = Field(default=64 * 1024, gt=0, strict=True)

    @model_validator(mode="after")
    def query_paths_must_be_complete_and_absolute(self) -> ServiceSettings:
        paths = (self.corpus_root, self.manifest_path, self.policy_path)
        if any(path is not None for path in paths) and not all(path is not None for path in paths):
            raise ValueError("query runtime paths must be supplied together")
        if any(path is not None and not path.is_absolute() for path in paths):
            raise ValueError("query runtime paths must be absolute")
        return self


@dataclass(frozen=True, slots=True)
class ServiceDependencies:
    provider_factory: Callable[[], EmbeddingProvider] | None = None


@dataclass(slots=True)
class ServiceState:
    provider: EmbeddingProvider | None = None
    initialization_failed: bool = False
    provider_lock: Lock = field(default_factory=Lock)


__all__ = ["ServiceDependencies", "ServiceSettings", "ServiceState"]
