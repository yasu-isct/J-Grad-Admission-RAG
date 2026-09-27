"""Read-only inventory for explicitly named local KB/index artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence, cast

from ..corpus import audit_corpus_manifest
from ..retrieval.local_index import load_local_index
from ..schemas.corpus_manifest import load_corpus_manifest

ArtifactRole = Literal["production", "release-baseline", "historical", "candidate-duplicate"]
_ROLES = ("production", "release-baseline", "historical", "candidate-duplicate")


@dataclass(frozen=True, slots=True)
class ArtifactRequest:
    role: ArtifactRole
    path: Path


def inventory_artifacts(requests: Sequence[ArtifactRequest]) -> list[dict[str, Any]]:
    """Inspect only caller-named paths and mark exact identity duplicates."""

    records = [_inspect(request) for request in requests]
    counts: dict[str, int] = {}
    for record in records:
        identity = record.get("artifact_identity")
        if identity is not None:
            counts[identity] = counts.get(identity, 0) + 1
    for record in records:
        identity = record.get("artifact_identity")
        record["duplicate_candidate"] = identity is not None and counts[identity] > 1
    return records


def _artifact(value: str) -> ArtifactRequest:
    role, separator, raw_path = value.partition("=")
    if not separator or role not in _ROLES or not raw_path:
        raise argparse.ArgumentTypeError("must be ROLE=ABSOLUTE_PATH with a supported role")
    path = Path(raw_path)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("artifact path must be absolute")
    return ArtifactRequest(role=cast(ArtifactRole, role), path=path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m jgrad_admission_rag.operations.artifact_inventory",
        description="Inspect explicitly named local index/runtime artifacts without mutation.",
    )
    parser.add_argument(
        "--artifact",
        action="append",
        type=_artifact,
        required=True,
        metavar="ROLE=ABSOLUTE_PATH",
        help="Repeat for each explicit path; no directory discovery is performed.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    print(json.dumps(inventory_artifacts(args.artifact), ensure_ascii=False, indent=2))


def _inspect(request: ArtifactRequest) -> dict[str, Any]:
    path = request.path
    base: dict[str, Any] = {
        "path": str(path),
        "role": request.role,
        "accessibility": "invalid",
        "artifact_kind": None,
        "artifact_identity": None,
        "identity": None,
    }
    try:
        resolved = _resolve_explicit_path(path)
        runtime_root = resolved / "runtime-v1" if (resolved / "runtime-v1").is_dir() else resolved
        _assert_readable_tree(runtime_root)
        if (runtime_root / "corpus.json").is_file():
            manifest = load_corpus_manifest(runtime_root / "corpus.json")
            audited = audit_corpus_manifest(manifest, runtime_root)
            ready = [entry for entry in audited.entries if entry.index_state == "ready"]
            if len(ready) != 1 or ready[0].index_manifest is None:
                raise ValueError("runtime must contain exactly one ready index")
            index = ready[0].index_manifest
            kind = "demo-runtime"
        elif (resolved / "manifest.json").is_file():
            index = load_local_index(resolved, mmap=True).manifest
            kind = "local-index"
        else:
            raise ValueError("path is neither a Demo runtime nor a local index")
        identity = {
            "document_id": index.document_id,
            "source_pdf_sha256": index.source_pdf_sha256,
            "source_kb_schema_version": index.source_kb_schema_version,
            "source_kb_sha256": index.source_kb_sha256,
            "index_schema_version": index.index_schema_version,
            "payload_count": index.payload_count,
            "vector_count": index.vector_count,
            "embedding_provider": index.embedding_provider,
            "embedding_model": index.embedding_model,
            "embedding_revision": index.embedding_revision,
            "embedding_dimension": index.embedding_dimension,
            "distance_metric": index.distance_metric,
            "vectors_normalized": index.vectors_normalized,
            "payloads_sha256": index.payloads_sha256,
            "vectors_sha256": index.vectors_sha256,
        }
        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        base.update(
            accessibility="ready",
            artifact_kind=kind,
            artifact_identity=hashlib.sha256(canonical).hexdigest(),
            identity=identity,
        )
    except PermissionError:
        base["accessibility"] = "access_denied"
    except FileNotFoundError:
        base["accessibility"] = "missing"
    except Exception:
        base["accessibility"] = "invalid"
    return base


def _resolve_explicit_path(path_value: Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute() or path == Path(path.anchor) or _has_symlink_component(path):
        raise ValueError("artifact path must be an explicit safe absolute path")
    try:
        status = os.stat(path)
    except PermissionError:
        raise
    except FileNotFoundError:
        raise
    if not path.is_dir() or status.st_mode == 0:
        raise ValueError("artifact path must be a directory")
    return path.resolve(strict=True)


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _assert_readable_tree(root: Path) -> None:
    pending = [root]
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise ValueError("artifact trees must not contain symbolic links")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    with open(entry.path, "rb") as handle:
                        handle.read(1)
                else:
                    raise ValueError("artifact tree contains an unsupported entry")


__all__ = ["ArtifactRequest", "ArtifactRole", "inventory_artifacts"]


if __name__ == "__main__":
    main()
