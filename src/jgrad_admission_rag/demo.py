"""Audited assembly of the supported offline local demo workspace."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .builder.kb_builder import DocumentBuildError, build_document_kb
from .corpus import (
    CorpusAuditError,
    CorpusBuildError,
    CorpusRegistration,
    audit_corpus_manifest,
    build_corpus_manifest,
)
from .corpus_selection import (
    CorpusPolicyCompatibilityError,
    validate_corpus_version_policy,
)
from .reasoning.query_intent import (
    QueryIntentCatalog,
    QueryIntentError,
    canonical_query_intent_catalog_bytes,
    load_query_intent_catalog_bytes,
)
from .reasoning.reviewed_report_plan import (
    ReviewedReportPlan,
    ReviewedReportPlanError,
    canonical_reviewed_report_plan_bytes,
    load_reviewed_report_plan_bytes,
)
from .retrieval.embedding import DeterministicFakeEmbeddingProvider
from .retrieval.local_index import IndexBuildError
from .retrieval.source_kb import SourceKbReadError, read_source_kb_exact
from .schemas.corpus_manifest import (
    CorpusManifestError,
    canonical_corpus_manifest_bytes,
    load_corpus_manifest,
)
from .schemas.corpus_version import (
    CorpusFamilyVersionPolicy,
    CorpusVersionPolicy,
    CorpusVersionSchemaError,
    canonical_corpus_version_policy_bytes,
    load_corpus_version_policy,
)
from .schemas.document_identity import (
    DocumentIdentity,
    DocumentIdentityError,
    canonical_document_identity_bytes,
    load_document_identity_bytes,
)
from .schemas.document_kb import canonical_document_kb_bytes
from .schemas.page_scope_manifest import (
    PageScopeManifest,
    PageScopeManifestError,
    canonical_page_scope_manifest_bytes,
    load_page_scope_manifest,
    load_page_scope_manifest_bytes,
)
from .utils import sha256_file

_CONFIG_PACKAGE = "jgrad_admission_rag.demo_config"
_CONFIG_FILENAMES = {
    "identity": "document_identity.json",
    "plan": "reviewed_report_plan.json",
    "page_scope": "page_scope_manifest.json",
    "query_intent": "query_intent_catalog.json",
}
_RUNTIME_DIRECTORY = "runtime-v1"
_OWNERSHIP_FILENAME = ".jgrad-demo-owned.json"
_CORPUS_ID = "jgrad-demo-isct"
_INDEX_DIMENSION = 8


class DemoError(Exception):
    """An actionable, safe-to-display local demo failure."""


@dataclass(frozen=True, slots=True)
class DemoConfigBundle:
    identity: DocumentIdentity
    plan: ReviewedReportPlan
    page_scope: PageScopeManifest
    query_intent: QueryIntentCatalog
    identity_bytes: bytes
    plan_bytes: bytes
    page_scope_bytes: bytes
    query_intent_bytes: bytes


@dataclass(frozen=True, slots=True)
class DemoRuntime:
    workspace: Path
    runtime_root: Path
    corpus_root: Path
    manifest_path: Path
    policy_path: Path
    report_plan_path: Path
    page_scope_manifest_path: Path
    query_intent_catalog_path: Path
    identity: DocumentIdentity
    source_kb_sha256: str
    reused: bool


def load_demo_config(config_dir: Path | None = None) -> DemoConfigBundle:
    """Load one complete reviewed configuration without consulting test artifacts."""

    try:
        values = {
            key: _read_config_bytes(filename, config_dir)
            for key, filename in _CONFIG_FILENAMES.items()
        }
        identity = load_document_identity_bytes(values["identity"])
        plan = load_reviewed_report_plan_bytes(values["plan"])
        page_scope = load_page_scope_manifest_bytes(values["page_scope"])
        query_intent = load_query_intent_catalog_bytes(values["query_intent"])
        if plan.document_identity != identity or page_scope.document_identity != identity:
            raise ValueError
        return DemoConfigBundle(
            identity=identity,
            plan=plan,
            page_scope=page_scope,
            query_intent=query_intent,
            identity_bytes=canonical_document_identity_bytes(identity),
            plan_bytes=canonical_reviewed_report_plan_bytes(plan),
            page_scope_bytes=canonical_page_scope_manifest_bytes(page_scope),
            query_intent_bytes=canonical_query_intent_catalog_bytes(query_intent),
        )
    except (
        DocumentIdentityError,
        OSError,
        PageScopeManifestError,
        QueryIntentError,
        ReviewedReportPlanError,
        TypeError,
        ValueError,
    ):
        raise DemoError("reviewed demo configuration is unavailable or incompatible") from None


def default_workspace(identity: DocumentIdentity, cwd: Path | None = None) -> Path:
    root = (cwd or Path.cwd()).resolve(strict=False)
    return root / "outputs" / "demo" / identity.document_id


def prepare_demo(
    pdf_path: Path,
    workspace: Path,
    *,
    rebuild: bool = False,
    config_dir: Path | None = None,
) -> DemoRuntime:
    """Validate one explicit official PDF and build or audit its local runtime."""

    bundle = load_demo_config(config_dir)
    pdf = _validate_pdf(pdf_path, bundle.identity)
    root = _prepare_workspace(workspace)
    runtime_root = root / _RUNTIME_DIRECTORY
    replace_runtime = False

    if runtime_root.exists() or runtime_root.is_symlink():
        if not rebuild:
            try:
                return _validate_runtime(root, runtime_root, bundle, reused=True)
            except DemoError:
                raise DemoError(
                    "demo workspace is stale or incompatible; rerun with --rebuild"
                ) from None
        _assert_owned_runtime(root, runtime_root, bundle)
        replace_runtime = True

    prefix = f".{_RUNTIME_DIRECTORY}.build-"
    try:
        stage = Path(tempfile.mkdtemp(prefix=prefix, dir=root)).resolve(strict=True)
    except OSError:
        raise DemoError("demo workspace is not writable") from None
    try:
        _build_runtime(pdf, stage, bundle)
        validated = _validate_runtime(root, stage, bundle, reused=False)
        _activate_runtime(root, stage, runtime_root, replace=replace_runtime)
        return DemoRuntime(
            workspace=root,
            runtime_root=runtime_root.resolve(strict=True),
            corpus_root=runtime_root.resolve(strict=True),
            manifest_path=runtime_root.resolve(strict=True) / validated.manifest_path.name,
            policy_path=runtime_root.resolve(strict=True) / validated.policy_path.name,
            report_plan_path=(
                runtime_root.resolve(strict=True) / "config" / validated.report_plan_path.name
            ),
            page_scope_manifest_path=(
                runtime_root.resolve(strict=True)
                / "config"
                / validated.page_scope_manifest_path.name
            ),
            query_intent_catalog_path=(
                runtime_root.resolve(strict=True)
                / "config"
                / validated.query_intent_catalog_path.name
            ),
            identity=validated.identity,
            source_kb_sha256=validated.source_kb_sha256,
            reused=False,
        )
    except DemoError:
        _remove_owned_stage(root, stage, prefix)
        raise
    except Exception:
        _remove_owned_stage(root, stage, prefix)
        raise DemoError("demo artifacts could not be built safely") from None


def _build_runtime(pdf: Path, root: Path, bundle: DemoConfigBundle) -> None:
    identity = bundle.identity
    document_id = identity.document_id
    kb_relative = f"documents/{document_id}/document_kb.json"
    index_relative = f"indexes/{document_id}"
    kb_path = root / Path(*kb_relative.split("/"))
    index_path = root / Path(*index_relative.split("/"))
    try:
        kb = build_document_kb(
            pdf,
            identity,
            source_pdf_label=f"{document_id}.pdf",
        )
        if not kb.diagnostics.quality_gate.passed:
            raise DemoError("official PDF failed the reviewed KB quality gate")
        _write_bytes(kb_path, canonical_document_kb_bytes(kb))
        source = read_source_kb_exact(kb_path)
        if source.sha256 != bundle.plan.source_kb_sha256:
            raise DemoError("official PDF build does not match the reviewed demo data version")

        from .retrieval.local_index import build_local_index

        build_local_index(
            kb_path,
            index_path,
            DeterministicFakeEmbeddingProvider(_INDEX_DIMENSION),
        )
        manifest = build_corpus_manifest(
            _CORPUS_ID,
            root,
            (CorpusRegistration(kb_relative, index_relative),),
        )
        policy = CorpusVersionPolicy(
            corpus_id=_CORPUS_ID,
            family_policies=(
                CorpusFamilyVersionPolicy(
                    document_family_id=identity.document_family_id,
                    active_document_id=document_id,
                ),
            ),
        )
        _write_bytes(root / "corpus.json", canonical_corpus_manifest_bytes(manifest))
        _write_bytes(root / "policy.json", canonical_corpus_version_policy_bytes(policy))
        _write_bytes(root / _OWNERSHIP_FILENAME, _ownership_bytes(bundle))
        config_root = root / "config"
        _write_bytes(config_root / _CONFIG_FILENAMES["identity"], bundle.identity_bytes)
        _write_bytes(config_root / _CONFIG_FILENAMES["plan"], bundle.plan_bytes)
        _write_bytes(config_root / _CONFIG_FILENAMES["page_scope"], bundle.page_scope_bytes)
        _write_bytes(config_root / _CONFIG_FILENAMES["query_intent"], bundle.query_intent_bytes)
    except DemoError:
        raise
    except (CorpusBuildError, DocumentBuildError, IndexBuildError, SourceKbReadError, ValueError):
        raise DemoError("official PDF artifacts could not be assembled safely") from None
    except OSError:
        raise DemoError("demo workspace is not writable") from None


def _validate_runtime(
    workspace: Path,
    runtime_root: Path,
    bundle: DemoConfigBundle,
    *,
    reused: bool,
) -> DemoRuntime:
    try:
        if runtime_root.is_symlink() or not runtime_root.is_dir():
            raise ValueError
        resolved_runtime = runtime_root.resolve(strict=True)
        if resolved_runtime.parent != workspace:
            raise ValueError
        config_root = resolved_runtime / "config"
        if config_root.is_symlink() or not config_root.is_dir():
            raise ValueError
        ownership_path = resolved_runtime / _OWNERSHIP_FILENAME
        if (
            ownership_path.is_symlink()
            or not ownership_path.is_file()
            or ownership_path.read_bytes() != _ownership_bytes(bundle)
        ):
            raise ValueError
        expected_configs = {
            _CONFIG_FILENAMES["identity"]: bundle.identity_bytes,
            _CONFIG_FILENAMES["plan"]: bundle.plan_bytes,
            _CONFIG_FILENAMES["page_scope"]: bundle.page_scope_bytes,
            _CONFIG_FILENAMES["query_intent"]: bundle.query_intent_bytes,
        }
        for filename, expected in expected_configs.items():
            path = config_root / filename
            if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
                raise ValueError

        manifest_path = resolved_runtime / "corpus.json"
        policy_path = resolved_runtime / "policy.json"
        manifest = load_corpus_manifest(manifest_path)
        policy = load_corpus_version_policy(policy_path)
        if manifest_path.read_bytes() != canonical_corpus_manifest_bytes(manifest):
            raise ValueError
        if policy_path.read_bytes() != canonical_corpus_version_policy_bytes(policy):
            raise ValueError
        audited = audit_corpus_manifest(manifest, resolved_runtime)
        validate_corpus_version_policy(policy, audited)
        if len(audited.entries) != 1 or audited.entries[0].identity != bundle.identity:
            raise ValueError
        entry = audited.entries[0]
        if entry.index_state != "ready" or entry.source_kb_sha256 != bundle.plan.source_kb_sha256:
            raise ValueError
        source = read_source_kb_exact(resolved_runtime / Path(*entry.kb_path.split("/")))
        if (
            source.sha256 != bundle.plan.source_kb_sha256
            or source.knowledge_base.manifest.identity != bundle.identity
            or source.knowledge_base.manifest.source_pdf != f"{bundle.identity.document_id}.pdf"
        ):
            raise ValueError
        source_pages = {
            page
            for collection in (
                source.knowledge_base.entities,
                source.knowledge_base.facts,
                source.knowledge_base.retrieval_units,
            )
            for item in collection
            for page in item.source_pages
        }
        if not source_pages:
            raise ValueError
        plan_path = config_root / _CONFIG_FILENAMES["plan"]
        page_scope_path = config_root / _CONFIG_FILENAMES["page_scope"]
        intent_path = config_root / _CONFIG_FILENAMES["query_intent"]
        if load_reviewed_report_plan_bytes(plan_path.read_bytes()) != bundle.plan:
            raise ValueError
        if (
            load_page_scope_manifest(page_scope_path, expected_page_count=max(source_pages))
            != bundle.page_scope
        ):
            raise ValueError
        if load_query_intent_catalog_bytes(intent_path.read_bytes()) != bundle.query_intent:
            raise ValueError
        return DemoRuntime(
            workspace=workspace,
            runtime_root=resolved_runtime,
            corpus_root=resolved_runtime,
            manifest_path=manifest_path,
            policy_path=policy_path,
            report_plan_path=plan_path,
            page_scope_manifest_path=page_scope_path,
            query_intent_catalog_path=intent_path,
            identity=bundle.identity,
            source_kb_sha256=source.sha256,
            reused=reused,
        )
    except (
        CorpusAuditError,
        CorpusManifestError,
        CorpusPolicyCompatibilityError,
        CorpusVersionSchemaError,
        OSError,
        PageScopeManifestError,
        QueryIntentError,
        ReviewedReportPlanError,
        SourceKbReadError,
        TypeError,
        ValueError,
    ):
        raise DemoError("demo workspace audit failed") from None


def _validate_pdf(path_value: Path, identity: DocumentIdentity) -> Path:
    try:
        path = Path(path_value)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise OSError
        resolved = path.resolve(strict=True)
        actual = sha256_file(resolved)
    except (OSError, TypeError, ValueError):
        raise DemoError("--pdf must be an absolute path to the downloaded official PDF") from None
    if actual != identity.source_pdf_sha256:
        raise DemoError(
            "PDF version mismatch; download the reviewed edition from "
            f"{identity.official_source_url} and retry"
        )
    return resolved


def _prepare_workspace(path_value: Path) -> Path:
    try:
        requested = Path(path_value)
        if not requested.is_absolute() or requested == Path(requested.anchor):
            raise OSError
        if _has_symlink_component(requested):
            raise OSError
        requested.mkdir(parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise OSError
        resolved = requested.resolve(strict=True)
        descriptor, probe_name = tempfile.mkstemp(prefix=".jgrad-demo-write-probe-", dir=resolved)
        os.close(descriptor)
        Path(probe_name).unlink()
        return resolved
    except (OSError, RuntimeError, TypeError, ValueError):
        raise DemoError("--workspace must be an absolute writable directory") from None


def _read_config_bytes(filename: str, config_dir: Path | None) -> bytes:
    if config_dir is None:
        return resources.files(_CONFIG_PACKAGE).joinpath(filename).read_bytes()
    root = Path(config_dir)
    if (
        not root.is_absolute()
        or root.is_symlink()
        or not root.is_dir()
        or _has_symlink_component(root)
    ):
        raise OSError
    path = root / filename
    if (
        path.is_symlink()
        or not path.is_file()
        or path.parent.resolve(strict=True) != root.resolve(strict=True)
    ):
        raise OSError
    return path.read_bytes()


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _assert_owned_runtime(
    workspace: Path,
    runtime_root: Path,
    bundle: DemoConfigBundle,
) -> None:
    try:
        candidate = runtime_root.resolve(strict=False)
        if (
            candidate.parent != workspace
            or candidate.name != _RUNTIME_DIRECTORY
            or runtime_root.is_symlink()
            or not runtime_root.is_dir()
        ):
            raise OSError
        marker = candidate / _OWNERSHIP_FILENAME
        if (
            marker.is_symlink()
            or not marker.is_file()
            or marker.read_bytes() != _ownership_bytes(bundle)
        ):
            raise OSError
    except OSError:
        raise DemoError("demo workspace cannot be rebuilt safely") from None


def _ownership_bytes(bundle: DemoConfigBundle) -> bytes:
    payload = {
        "document_id": bundle.identity.document_id,
        "owner": "jgrad-demo",
        "schema_version": "1.0",
    }
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _activate_runtime(
    workspace: Path,
    stage: Path,
    runtime_root: Path,
    *,
    replace: bool,
) -> None:
    backup: Path | None = None
    try:
        if replace:
            backup = Path(
                tempfile.mkdtemp(prefix=f".{_RUNTIME_DIRECTORY}.previous-", dir=workspace)
            )
            backup.rmdir()
            os.rename(runtime_root, backup)
        os.rename(stage, runtime_root)
    except OSError:
        if backup is not None and backup.is_dir() and not runtime_root.exists():
            try:
                os.rename(backup, runtime_root)
            except OSError:
                pass
        raise DemoError("demo workspace could not be activated safely") from None
    if backup is not None:
        try:
            shutil.rmtree(backup)
        except OSError:
            pass


def _remove_owned_stage(workspace: Path, stage: Path, prefix: str) -> None:
    try:
        candidate = stage.resolve(strict=False)
        if (
            candidate.parent == workspace
            and candidate.name.startswith(prefix)
            and candidate.is_dir()
            and not candidate.is_symlink()
        ):
            shutil.rmtree(candidate)
    except OSError:
        pass


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def runtime_fingerprint(runtime: DemoRuntime) -> str:
    """Return a non-secret stable summary identifier for acceptance evidence."""

    payload = (
        f"{runtime.identity.document_id}\0{runtime.identity.source_pdf_sha256}\0"
        f"{runtime.source_kb_sha256}"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "DemoConfigBundle",
    "DemoError",
    "DemoRuntime",
    "default_workspace",
    "load_demo_config",
    "prepare_demo",
    "runtime_fingerprint",
]
