from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.corpus import (
    CorpusAuditError,
    CorpusBuildError,
    CorpusRegistration,
    audit_corpus_manifest,
    build_corpus_manifest,
)
from jgrad_admission_rag.retrieval.embedding import DeterministicFakeEmbeddingProvider
from jgrad_admission_rag.retrieval.local_index import build_local_index
from jgrad_admission_rag.schemas.corpus_manifest import (
    CorpusManifest,
    CorpusManifestError,
    canonical_corpus_manifest_bytes,
    load_corpus_manifest,
    load_corpus_manifest_bytes,
)
from jgrad_admission_rag.schemas.document_identity import DocumentIdentity
from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    DocumentKnowledgeBase,
    KnowledgeManifest,
    QualityGateResult,
    RetrievalUnit,
    ScopedFact,
)


def _identity(
    document_id: str,
    *,
    family: str | None = None,
    edition: str = "2027-04",
    institution: str = "sample-u",
    pdf_hash: str | None = None,
) -> DocumentIdentity:
    digest = pdf_hash or hashlib.sha256(document_id.encode()).hexdigest()
    return DocumentIdentity(
        document_id=document_id,
        document_family_id=family or f"{document_id}-family",
        edition_id=edition,
        institution_id=institution,
        institution_name=f"{institution} University",
        degree_levels=["master"],
        intake_terms=[{"year": 2027, "month": 4}],
        official_title=f"Guidelines {document_id}",
        official_source_url=f"https://example.edu/{document_id}.pdf",
        source_pdf_sha256=digest,
    )


def _kb(identity: DocumentIdentity, *, passed: bool = True) -> DocumentKnowledgeBase:
    fact = ScopedFact(
        fact_id="fact:00000",
        fact_type="eligibility",
        scope_type="global",
        title="Eligibility",
        text="Applicants must satisfy the stated eligibility requirement.",
        source_pages=[1],
        section_path=["Eligibility"],
        embedding_text="Eligibility: applicants must satisfy the requirement.",
    )
    return DocumentKnowledgeBase(
        manifest=KnowledgeManifest(identity=identity, source_pdf="source.pdf", chunk_count=1),
        facts=[fact],
        retrieval_units=[
            RetrievalUnit(
                unit_id="unit:00000",
                fact_id=fact.fact_id,
                text=fact.embedding_text,
                source_pages=[1],
                section_path=["Eligibility"],
            )
        ],
        diagnostics=BuildDiagnostics(quality_gate=QualityGateResult(passed=passed)),
    )


def _write_kb(
    root: Path, relative: str, identity: DocumentIdentity, *, passed: bool = True
) -> Path:
    path = root / Path(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_kb(identity, passed=passed).model_dump(mode="json"), separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="",
    )
    return path


def _two_document_corpus(root: Path) -> tuple[CorpusManifest, Path, Path]:
    alpha_path = _write_kb(
        root,
        "alpha/document_kb.json",
        _identity("alpha-2027", family="alpha", institution="alpha-u"),
    )
    beta_path = _write_kb(
        root,
        "beta/document_kb.json",
        _identity("beta-2027", family="beta", institution="beta-u"),
    )
    index_path = root / "indexes" / "beta"
    build_local_index(beta_path, index_path, DeterministicFakeEmbeddingProvider(4))
    manifest = build_corpus_manifest(
        "graduate-admissions",
        root,
        (
            CorpusRegistration("beta/document_kb.json", "indexes/beta"),
            CorpusRegistration("alpha/document_kb.json"),
        ),
    )
    return manifest, alpha_path, beta_path


def test_build_is_explicit_canonical_detached_and_auditable(tmp_path: Path) -> None:
    manifest, alpha_path, beta_path = _two_document_corpus(tmp_path)

    assert [entry.identity.document_id for entry in manifest.entries] == [
        "alpha-2027",
        "beta-2027",
    ]
    assert (
        manifest.document_count,
        manifest.document_family_count,
        manifest.institution_count,
        manifest.indexed_document_count,
        manifest.unindexed_document_count,
    ) == (2, 2, 2, 1, 1)
    alpha, beta = manifest.entries
    assert alpha.index_state == "not_indexed"
    assert alpha.index_path is None and alpha.index_manifest is None
    assert alpha.source_kb_sha256 == hashlib.sha256(alpha_path.read_bytes()).hexdigest()
    assert beta.index_state == "ready"
    assert beta.index_manifest is not None
    assert beta.index_manifest.document_id == beta.identity.document_id
    assert (
        beta.index_manifest.source_kb_sha256 == hashlib.sha256(beta_path.read_bytes()).hexdigest()
    )
    reordered = build_corpus_manifest(
        "graduate-admissions",
        tmp_path,
        (
            CorpusRegistration("alpha/document_kb.json"),
            CorpusRegistration("beta/document_kb.json", "indexes/beta"),
        ),
    )
    assert canonical_corpus_manifest_bytes(reordered) == canonical_corpus_manifest_bytes(manifest)
    assert audit_corpus_manifest(manifest, tmp_path) == manifest

    with pytest.raises(ValidationError):
        manifest.document_count = 99
    with pytest.raises(ValidationError):
        beta.index_manifest.embedding_model = "changed"


def test_structural_loader_does_not_reopen_artifacts(tmp_path: Path) -> None:
    manifest, alpha_path, _ = _two_document_corpus(tmp_path)
    raw = canonical_corpus_manifest_bytes(manifest)
    alpha_path.unlink()

    assert load_corpus_manifest_bytes(raw) == manifest
    with pytest.raises(CorpusAuditError):
        audit_corpus_manifest(manifest, tmp_path)


def test_canonical_loader_rejects_version_extra_order_and_count_tampering(tmp_path: Path) -> None:
    manifest, _, _ = _two_document_corpus(tmp_path)
    payload = manifest.model_dump(mode="json")
    variants = []
    for field, value in (("schema_version", "2.0"), ("document_count", 3)):
        changed = dict(payload)
        changed[field] = value
        variants.append(changed)
    changed = dict(payload)
    changed["unexpected"] = True
    variants.append(changed)
    changed = dict(payload)
    changed["entries"] = list(reversed(payload["entries"]))
    variants.append(changed)

    for variant in variants:
        raw = json.dumps(variant).encode()
        with pytest.raises(CorpusManifestError):
            load_corpus_manifest_bytes(raw)


@pytest.mark.parametrize(
    "path",
    ["", "/kb.json", "../kb.json", "a/../kb.json", "a\\kb.json", "C:/kb.json", "a//b"],
)
def test_registration_rejects_noncanonical_paths(path: str) -> None:
    with pytest.raises(CorpusBuildError):
        CorpusRegistration(path)


def test_builder_requires_absolute_root_nonempty_tuple_and_no_discovery(tmp_path: Path) -> None:
    _write_kb(tmp_path, "unregistered.json", _identity("unregistered"))
    with pytest.raises(CorpusBuildError):
        build_corpus_manifest("corpus", Path("relative"), ())
    with pytest.raises(CorpusBuildError):
        build_corpus_manifest("corpus", tmp_path, [])  # type: ignore[arg-type]
    with pytest.raises(CorpusBuildError):
        build_corpus_manifest("corpus", tmp_path, (CorpusRegistration("missing.json"),))


@pytest.mark.parametrize("duplicate", ["kb", "index"])
def test_registration_paths_must_be_unique_before_artifact_loading(
    tmp_path: Path, duplicate: str
) -> None:
    kb_path = "same.json" if duplicate == "kb" else "missing-a.json"
    first_index = "same-index" if duplicate == "index" else None
    second_index = "same-index" if duplicate == "index" else None
    with pytest.raises(
        CorpusBuildError, match=f"duplicate {duplicate.upper() if duplicate == 'kb' else duplicate}"
    ):
        build_corpus_manifest(
            "corpus",
            tmp_path,
            (
                CorpusRegistration(kb_path, first_index),
                CorpusRegistration(
                    kb_path if duplicate == "kb" else "missing-b.json", second_index
                ),
            ),
        )


@pytest.mark.parametrize("collision", ["document", "family_edition", "pdf"])
def test_corpus_identity_collisions_fail_closed(tmp_path: Path, collision: str) -> None:
    common_hash = "a" * 64
    first = _identity(
        "same" if collision == "document" else "first",
        family="family" if collision == "family_edition" else "first-family",
        pdf_hash=common_hash if collision == "pdf" else None,
    )
    second = _identity(
        "same" if collision == "document" else "second",
        family="family" if collision == "family_edition" else "second-family",
        pdf_hash=common_hash if collision == "pdf" else None,
    )
    _write_kb(tmp_path, "one/kb.json", first)
    _write_kb(tmp_path, "two/kb.json", second)

    with pytest.raises(CorpusBuildError, match="corpus-wide invariants"):
        build_corpus_manifest(
            "corpus",
            tmp_path,
            (CorpusRegistration("one/kb.json"), CorpusRegistration("two/kb.json")),
        )


def test_same_family_and_institution_allow_distinct_editions(tmp_path: Path) -> None:
    _write_kb(
        tmp_path,
        "2027/kb.json",
        _identity("sample-2027", family="sample-family", edition="2027", institution="sample-u"),
    )
    _write_kb(
        tmp_path,
        "2028/kb.json",
        _identity("sample-2028", family="sample-family", edition="2028", institution="sample-u"),
    )

    manifest = build_corpus_manifest(
        "corpus",
        tmp_path,
        (CorpusRegistration("2028/kb.json"), CorpusRegistration("2027/kb.json")),
    )

    assert manifest.document_count == 2
    assert manifest.document_family_count == 1
    assert manifest.institution_count == 1


def test_quality_failure_and_stale_or_corrupt_index_are_rejected(tmp_path: Path) -> None:
    bad_path = _write_kb(tmp_path, "bad.json", _identity("bad"), passed=False)
    with pytest.raises(CorpusBuildError, match="quality gate"):
        build_corpus_manifest("corpus", tmp_path, (CorpusRegistration("bad.json"),))

    good = _identity("good")
    good_path = _write_kb(tmp_path, "good.json", good)
    index_path = tmp_path / "index"
    build_local_index(good_path, index_path, DeterministicFakeEmbeddingProvider(4))
    good_path.write_bytes(good_path.read_bytes() + b" ")
    with pytest.raises(CorpusBuildError, match="invalid, stale, or unsafe"):
        build_corpus_manifest("corpus", tmp_path, (CorpusRegistration("good.json", "index"),))

    good_path.write_text("{}", encoding="utf-8")
    with pytest.raises(CorpusBuildError):
        build_corpus_manifest("corpus", tmp_path, (CorpusRegistration("good.json"),))
    assert bad_path.is_file()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_kb_sha256", "f" * 64),
        ("document_id", "different-document"),
        ("source_pdf_sha256", "e" * 64),
        ("source_kb_schema_version", "0.5"),
        ("embedding_model", "changed-after-registration"),
    ],
)
def test_audit_detects_changed_index_bindings(tmp_path: Path, field: str, value: str) -> None:
    manifest, _, _ = _two_document_corpus(tmp_path)
    index_manifest_path = tmp_path / "indexes" / "beta" / "manifest.json"
    payload = json.loads(index_manifest_path.read_text(encoding="utf-8"))
    payload[field] = value
    index_manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CorpusAuditError):
        audit_corpus_manifest(manifest, tmp_path)


def test_missing_index_artifact_cannot_be_ready(tmp_path: Path) -> None:
    _two_document_corpus(tmp_path)
    (tmp_path / "indexes" / "beta" / "embeddings.npy").unlink()
    with pytest.raises(CorpusBuildError, match="invalid, stale, or unsafe"):
        build_corpus_manifest(
            "corpus",
            tmp_path,
            (CorpusRegistration("beta/document_kb.json", "indexes/beta"),),
        )


def test_legacy_kb_requires_explicit_migration(tmp_path: Path) -> None:
    identity = _identity("legacy")
    payload = _kb(identity).model_dump(mode="json")
    payload["manifest"]["schema_version"] = "0.5"
    payload["manifest"]["document_id"] = identity.document_id
    payload["manifest"]["pdf_sha256"] = identity.source_pdf_sha256
    del payload["manifest"]["identity"]
    (tmp_path / "legacy.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CorpusBuildError, match="explicit migration"):
        build_corpus_manifest("corpus", tmp_path, (CorpusRegistration("legacy.json"),))


def test_indexed_legacy_kb_requires_explicit_migration(tmp_path: Path) -> None:
    identity = _identity("legacy-indexed")
    kb_path = _write_kb(tmp_path, "legacy.json", identity)
    index_path = tmp_path / "index"
    build_local_index(kb_path, index_path, DeterministicFakeEmbeddingProvider(4))

    payload = _kb(identity).model_dump(mode="json")
    payload["manifest"]["schema_version"] = "0.5"
    payload["manifest"]["document_id"] = identity.document_id
    payload["manifest"]["pdf_sha256"] = identity.source_pdf_sha256
    del payload["manifest"]["identity"]
    kb_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CorpusBuildError, match="explicit migration"):
        build_corpus_manifest(
            "corpus",
            tmp_path,
            (CorpusRegistration("legacy.json", "index"),),
        )


def test_loader_rejects_symlink_manifest_when_supported(tmp_path: Path) -> None:
    manifest, _, _ = _two_document_corpus(tmp_path)
    target = tmp_path / "manifest-target.json"
    target.write_bytes(canonical_corpus_manifest_bytes(manifest))
    link = tmp_path / "manifest-link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(CorpusManifestError):
        load_corpus_manifest(link)


def test_builder_rejects_symlinked_root_when_supported(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    _write_kb(root, "kb.json", _identity("sample"))
    link = tmp_path / "root-link"
    try:
        link.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(CorpusBuildError, match="root is unavailable or unsafe"):
        build_corpus_manifest("corpus", link, (CorpusRegistration("kb.json"),))
