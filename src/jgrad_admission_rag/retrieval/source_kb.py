from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from ..schemas.document_kb import DocumentKnowledgeBase


class SourceKbReadError(Exception):
    """Raised when exact source-KB bytes cannot be read and parsed safely."""


@dataclass(frozen=True, slots=True)
class ExactSourceKnowledgeBase:
    knowledge_base: DocumentKnowledgeBase
    sha256: str


def read_source_kb_exact(path_value: str | Path) -> ExactSourceKnowledgeBase:
    """Read one regular non-symlink KB file once, hash exact bytes, and parse it."""

    path = Path(path_value)
    if path.is_symlink() or not path.is_file():
        raise SourceKbReadError("source KB is missing or is not a regular non-symlink file")
    try:
        raw_bytes = path.read_bytes()
        knowledge_base = DocumentKnowledgeBase.model_validate_json(raw_bytes)
    except (OSError, ValueError, ValidationError) as error:
        raise SourceKbReadError(
            "source KB is not valid UTF-8 DocumentKnowledgeBase JSON"
        ) from error
    return ExactSourceKnowledgeBase(
        knowledge_base=knowledge_base,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )
