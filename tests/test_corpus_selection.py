from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.corpus import CorpusRegistration, build_corpus_manifest
from jgrad_admission_rag.corpus_selection import (
    CorpusPolicyCompatibilityError,
    CorpusSelectionAmbiguousError,
    CorpusSelectionNoMatchError,
    CorpusSelectionNotReadyError,
    CorpusSelectionResultCompatibilityError,
    CorpusSelectionVersionMismatchError,
    revalidate_corpus_selection_result,
    select_corpus_documents,
    validate_corpus_version_policy,
)
from jgrad_admission_rag.retrieval.embedding import DeterministicFakeEmbeddingProvider
from jgrad_admission_rag.retrieval.local_index import build_local_index
from jgrad_admission_rag.schemas.corpus_manifest import CorpusManifest
from jgrad_admission_rag.schemas.corpus_version import (
    CorpusFamilyVersionPolicy,
    CorpusSelectionRequest,
    CorpusSelectionResult,
    CorpusVersionPolicy,
    CorpusVersionSchemaError,
    canonical_corpus_selection_request_bytes,
    canonical_corpus_selection_result_bytes,
    canonical_corpus_version_policy_bytes,
    load_corpus_selection_request_bytes,
    load_corpus_selection_result_bytes,
    load_corpus_version_policy,
    load_corpus_version_policy_bytes,
)
from jgrad_admission_rag.schemas.document_identity import DegreeLevel, IntakeTerm
from tests.test_corpus_manifest import _identity, _write_kb


def _add_document(
    root: Path,
    document_id: str,
    *,
    family: str,
    institution: str,
    edition: str,
    ready: bool = True,
    degree_levels: tuple[str, ...] = ("master",),
    intake_terms: tuple[tuple[int, int], ...] = ((2027, 4),),
) -> CorpusRegistration:
    identity = _identity(
        document_id,
        family=family,
        edition=edition,
        institution=institution,
    ).model_copy(
        update={
            "degree_levels": tuple(DegreeLevel(value) for value in degree_levels),
            "intake_terms": tuple(
                IntakeTerm(year=year, month=month) for year, month in intake_terms
            ),
        }
    )
    relative = f"documents/{document_id}/document_kb.json"
    kb_path = _write_kb(root, relative, identity)
    if not ready:
        return CorpusRegistration(relative)
    index_relative = f"indexes/{document_id}"
    build_local_index(
        kb_path,
        root / Path(*index_relative.split("/")),
        DeterministicFakeEmbeddingProvider(4),
    )
    return CorpusRegistration(relative, index_relative)


def _manifest_and_policy(root: Path) -> tuple[CorpusManifest, CorpusVersionPolicy]:
    registrations = (
        _add_document(
            root,
            "alpha-old",
            family="alpha",
            institution="alpha-u",
            edition="2026",
            intake_terms=((2026, 4),),
        ),
        _add_document(
            root,
            "alpha-new",
            family="alpha",
            institution="alpha-u",
            edition="2027",
            degree_levels=("master", "doctoral"),
            intake_terms=((2026, 9), (2027, 4)),
        ),
        _add_document(
            root,
            "beta-new",
            family="beta",
            institution="beta-u",
            edition="2027",
        ),
        _add_document(
            root,
            "archive-only",
            family="archive",
            institution="archive-u",
            edition="2025",
        ),
    )
    manifest = build_corpus_manifest("admissions", root, registrations)
    policy = CorpusVersionPolicy(
        corpus_id="admissions",
        family_policies=(
            CorpusFamilyVersionPolicy(
                document_family_id="alpha",
                active_document_id="alpha-new",
                historical_document_ids=("alpha-old",),
            ),
            CorpusFamilyVersionPolicy(
                document_family_id="archive",
                active_document_id=None,
                historical_document_ids=("archive-only",),
            ),
            CorpusFamilyVersionPolicy(
                document_family_id="beta",
                active_document_id="beta-new",
            ),
        ),
    )
    return manifest, policy


def test_policy_is_canonical_immutable_and_structural_load_is_separate(
    tmp_path: Path,
) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)
    raw = canonical_corpus_version_policy_bytes(policy)
    loaded = load_corpus_version_policy_bytes(raw)

    assert loaded == policy
    assert validate_corpus_version_policy(loaded, manifest).policy == policy
    with pytest.raises(ValidationError):
        loaded.corpus_id = "changed"

    unrelated = manifest.model_copy(update={"corpus_id": "other"})
    assert load_corpus_version_policy_bytes(raw) == policy
    with pytest.raises(CorpusPolicyCompatibilityError, match="corpus ID"):
        validate_corpus_version_policy(policy, unrelated)


def test_policy_loader_rejects_version_extra_order_and_symlink(tmp_path: Path) -> None:
    _, policy = _manifest_and_policy(tmp_path)
    payload = policy.model_dump(mode="json")
    variants = []
    changed = dict(payload)
    changed["schema_version"] = "2.0"
    variants.append(changed)
    changed = dict(payload)
    changed["extra"] = True
    variants.append(changed)
    for variant in variants:
        with pytest.raises(CorpusVersionSchemaError):
            load_corpus_version_policy_bytes(json.dumps(variant).encode())

    changed = dict(payload)
    changed["family_policies"] = list(reversed(payload["family_policies"]))
    normalized = load_corpus_version_policy_bytes(json.dumps(changed).encode())
    assert normalized == policy
    assert canonical_corpus_version_policy_bytes(
        normalized
    ) == canonical_corpus_version_policy_bytes(policy)

    target = tmp_path / "policy.json"
    target.write_bytes(canonical_corpus_version_policy_bytes(policy))
    link = tmp_path / "policy-link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are unavailable")
    with pytest.raises(CorpusVersionSchemaError):
        load_corpus_version_policy(link)


@pytest.mark.parametrize(
    "family_policy",
    [
        CorpusFamilyVersionPolicy(
            document_family_id="alpha",
            active_document_id="alpha-new",
            historical_document_ids=(),
        ),
        CorpusFamilyVersionPolicy(
            document_family_id="alpha",
            active_document_id="beta-new",
            historical_document_ids=("alpha-new", "alpha-old"),
        ),
        CorpusFamilyVersionPolicy(
            document_family_id="alpha",
            active_document_id="unknown",
            historical_document_ids=("alpha-new", "alpha-old"),
        ),
    ],
)
def test_policy_requires_exact_document_coverage_and_actual_family(
    tmp_path: Path, family_policy: CorpusFamilyVersionPolicy
) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)
    changed = policy.model_copy(
        update={"family_policies": (family_policy, *policy.family_policies[1:])}
    )
    with pytest.raises(CorpusPolicyCompatibilityError):
        validate_corpus_version_policy(changed, manifest)


def test_structural_policy_rejects_duplicate_or_multiply_classified_ids() -> None:
    with pytest.raises(ValidationError):
        CorpusFamilyVersionPolicy(
            document_family_id="family",
            active_document_id="doc",
            historical_document_ids=("doc",),
        )
    with pytest.raises(ValidationError):
        CorpusFamilyVersionPolicy(
            document_family_id="family",
            historical_document_ids=("doc", "doc"),
        )
    family = CorpusFamilyVersionPolicy(document_family_id="family")
    with pytest.raises(ValidationError):
        CorpusVersionPolicy(corpus_id="corpus", family_policies=(family, family))


def test_policy_invalidates_on_membership_changes_but_not_index_only_change(
    tmp_path: Path,
) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)
    extra_registration = _add_document(
        tmp_path,
        "beta-old",
        family="beta",
        institution="beta-u",
        edition="2026",
    )
    expanded = build_corpus_manifest(
        "admissions",
        tmp_path,
        tuple(CorpusRegistration(entry.kb_path, entry.index_path) for entry in manifest.entries)
        + (extra_registration,),
    )
    with pytest.raises(CorpusPolicyCompatibilityError):
        validate_corpus_version_policy(policy, expanded)

    removed = build_corpus_manifest(
        "admissions",
        tmp_path,
        tuple(
            CorpusRegistration(entry.kb_path, entry.index_path)
            for entry in manifest.entries
            if entry.identity.document_id != "alpha-old"
        ),
    )
    with pytest.raises(CorpusPolicyCompatibilityError):
        validate_corpus_version_policy(policy, removed)

    successor = _add_document(
        tmp_path,
        "alpha-future",
        family="alpha",
        institution="alpha-u",
        edition="2028",
    )
    replaced = build_corpus_manifest(
        "admissions",
        tmp_path,
        tuple(
            CorpusRegistration(entry.kb_path, entry.index_path)
            for entry in manifest.entries
            if entry.identity.document_id != "alpha-new"
        )
        + (successor,),
    )
    with pytest.raises(CorpusPolicyCompatibilityError):
        validate_corpus_version_policy(policy, replaced)

    alpha_new = next(
        entry for entry in manifest.entries if entry.identity.document_id == "alpha-new"
    )
    index_only = manifest.model_copy(
        update={
            "entries": tuple(
                entry.model_copy(update={"index_path": "indexes/alternate-alpha-new"})
                if entry.identity.document_id == alpha_new.identity.document_id
                else entry
                for entry in manifest.entries
            )
        }
    )
    assert validate_corpus_version_policy(policy, index_only).policy == policy


def test_request_requires_positive_canonical_constraints() -> None:
    with pytest.raises(ValidationError):
        CorpusSelectionRequest()
    assert CorpusSelectionRequest(document_ids=("b", "a")).document_ids == ("a", "b")
    with pytest.raises(ValidationError):
        CorpusSelectionRequest(document_ids=("a", "a"))
    with pytest.raises(ValidationError):
        CorpusSelectionRequest(document_ids=("a",), allow_multiple_documents=1)


def test_default_active_selection_and_exact_and_or_filters(tmp_path: Path) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)
    result = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(
            institution_ids=("alpha-u", "beta-u"),
            document_family_ids=("alpha",),
            degree_levels=("doctoral",),
            intake_terms=({"year": 2026, "month": 9},),
        ),
    )

    assert result.request.version_mode == "active_only"
    assert result.request.allow_multiple_documents is False
    assert [item.entry.identity.document_id for item in result.selected_documents] == ["alpha-new"]
    assert result.selected_documents[0].version_classification == "active"


@pytest.mark.parametrize(
    ("selection_request", "expected_id"),
    [
        (CorpusSelectionRequest(document_ids=("beta-new",)), "beta-new"),
        (CorpusSelectionRequest(institution_ids=("beta-u",)), "beta-new"),
        (CorpusSelectionRequest(document_family_ids=("beta",)), "beta-new"),
        (CorpusSelectionRequest(degree_levels=("doctoral",)), "alpha-new"),
        (
            CorpusSelectionRequest(intake_terms=({"year": 2026, "month": 9},)),
            "alpha-new",
        ),
    ],
)
def test_each_identity_constraint_matches_exact_reviewed_values(
    tmp_path: Path, selection_request: CorpusSelectionRequest, expected_id: str
) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)
    result = select_corpus_documents(manifest, policy, selection_request)
    assert result.selected_documents[0].entry.identity.document_id == expected_id


def test_historical_and_all_versions_require_explicit_modes(tmp_path: Path) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)
    with pytest.raises(CorpusSelectionVersionMismatchError) as mismatch:
        select_corpus_documents(
            manifest,
            policy,
            CorpusSelectionRequest(document_ids=("alpha-old",)),
        )
    assert mismatch.value.matches == (("alpha-old", "historical"),)

    historical = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(
            document_family_ids=("alpha",),
            version_mode="historical_only",
        ),
    )
    assert historical.selected_documents[0].entry.identity.document_id == "alpha-old"

    with pytest.raises(CorpusSelectionAmbiguousError):
        select_corpus_documents(
            manifest,
            policy,
            CorpusSelectionRequest(
                document_family_ids=("alpha",),
                version_mode="all_versions",
            ),
        )
    all_versions = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(
            document_family_ids=("alpha",),
            version_mode="all_versions",
            allow_multiple_documents=True,
        ),
    )
    assert [item.entry.identity.document_id for item in all_versions.selected_documents] == [
        "alpha-new",
        "alpha-old",
    ]


def test_no_active_family_returns_version_mismatch(tmp_path: Path) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)
    with pytest.raises(CorpusSelectionVersionMismatchError):
        select_corpus_documents(
            manifest,
            policy,
            CorpusSelectionRequest(document_family_ids=("archive",)),
        )


def test_active_not_indexed_never_falls_back_to_ready_historical(tmp_path: Path) -> None:
    old = _add_document(
        tmp_path,
        "sample-old",
        family="sample",
        institution="sample-u",
        edition="2026",
        ready=True,
    )
    new = _add_document(
        tmp_path,
        "sample-new",
        family="sample",
        institution="sample-u",
        edition="2027",
        ready=False,
    )
    manifest = build_corpus_manifest("admissions", tmp_path, (old, new))
    policy = CorpusVersionPolicy(
        corpus_id="admissions",
        family_policies=(
            CorpusFamilyVersionPolicy(
                document_family_id="sample",
                active_document_id="sample-new",
                historical_document_ids=("sample-old",),
            ),
        ),
    )

    with pytest.raises(CorpusSelectionNotReadyError) as not_ready:
        select_corpus_documents(
            manifest,
            policy,
            CorpusSelectionRequest(document_family_ids=("sample",)),
        )
    assert not_ready.value.document_states == (("sample-new", "not_indexed"),)


def test_no_match_and_unauthorized_multi_document_are_distinct(tmp_path: Path) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)
    with pytest.raises(CorpusSelectionNoMatchError):
        select_corpus_documents(
            manifest,
            policy,
            CorpusSelectionRequest(institution_ids=("unknown-u",)),
        )
    with pytest.raises(CorpusSelectionAmbiguousError) as ambiguous:
        select_corpus_documents(
            manifest,
            policy,
            CorpusSelectionRequest(institution_ids=("alpha-u", "beta-u")),
        )
    assert ambiguous.value.document_ids == ("alpha-new", "beta-new")


def test_explicit_multi_document_result_is_canonical_complete_and_detached(
    tmp_path: Path, monkeypatch
) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)

    def forbid_file_open(*args, **kwargs):
        raise AssertionError("selector must not open artifacts")

    monkeypatch.setattr(Path, "open", forbid_file_open)
    result = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(
            institution_ids=("alpha-u", "beta-u"),
            allow_multiple_documents=True,
        ),
    )

    assert [item.entry.identity.document_id for item in result.selected_documents] == [
        "alpha-new",
        "beta-new",
    ]
    assert result.selected_document_count == 2
    assert result.selected_family_count == 2
    assert result.selected_institution_count == 2
    assert all(item.entry.index_manifest is not None for item in result.selected_documents)
    with pytest.raises(ValidationError):
        result.selected_documents[0].entry.index_state = "not_indexed"


def test_request_and_result_canonical_round_trips_reject_tampering(tmp_path: Path) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)
    request = CorpusSelectionRequest(document_ids=("alpha-new",))
    assert (
        load_corpus_selection_request_bytes(canonical_corpus_selection_request_bytes(request))
        == request
    )
    result = select_corpus_documents(manifest, policy, request)
    raw = canonical_corpus_selection_result_bytes(result)
    assert load_corpus_selection_result_bytes(raw) == result

    payload = result.model_dump(mode="json")
    payload["selected_document_count"] = 2
    with pytest.raises(CorpusVersionSchemaError):
        load_corpus_selection_result_bytes(json.dumps(payload).encode())

    payload = result.model_dump(mode="json")
    payload["selected_documents"][0]["version_classification"] = "historical"
    with pytest.raises(CorpusVersionSchemaError):
        load_corpus_selection_result_bytes(json.dumps(payload).encode())


def test_result_model_rejects_not_ready_entry(tmp_path: Path) -> None:
    registration = _add_document(
        tmp_path,
        "not-ready",
        family="sample",
        institution="sample-u",
        edition="2027",
        ready=False,
    )
    manifest = build_corpus_manifest("admissions", tmp_path, (registration,))
    with pytest.raises(ValidationError):
        CorpusSelectionResult(
            corpus_id="admissions",
            request=CorpusSelectionRequest(document_ids=("not-ready",)),
            selected_documents=(
                {
                    "version_classification": "active",
                    "entry": manifest.entries[0],
                },
            ),
            selected_document_count=1,
            selected_family_count=1,
            selected_institution_count=1,
        )


def test_result_revalidation_accepts_current_canonical_selection(
    tmp_path: Path, monkeypatch
) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)
    result = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(
            document_family_ids=("alpha",),
            version_mode="all_versions",
            allow_multiple_documents=True,
        ),
    )
    loaded = load_corpus_selection_result_bytes(canonical_corpus_selection_result_bytes(result))

    def forbid_file_open(*args, **kwargs):
        raise AssertionError("result revalidation must not open artifacts")

    monkeypatch.setattr(Path, "open", forbid_file_open)

    revalidated = revalidate_corpus_selection_result(loaded, manifest, policy)

    assert revalidated == result
    assert revalidated is not loaded


def test_result_revalidation_rejects_omitted_or_substituted_selection(
    tmp_path: Path,
) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)
    request = CorpusSelectionRequest(
        institution_ids=("alpha-u", "beta-u"),
        allow_multiple_documents=True,
    )
    result = select_corpus_documents(manifest, policy, request)
    omitted = CorpusSelectionResult(
        corpus_id=result.corpus_id,
        request=request,
        selected_documents=(result.selected_documents[0],),
        selected_document_count=1,
        selected_family_count=1,
        selected_institution_count=1,
    )
    alpha_old = next(
        entry for entry in manifest.entries if entry.identity.document_id == "alpha-old"
    )
    substituted = CorpusSelectionResult(
        corpus_id=result.corpus_id,
        request=request,
        selected_documents=(
            {
                "version_classification": "active",
                "entry": alpha_old,
            },
            result.selected_documents[1],
        ),
        selected_document_count=2,
        selected_family_count=2,
        selected_institution_count=2,
    )

    for stale_result in (omitted, substituted):
        with pytest.raises(CorpusSelectionResultCompatibilityError):
            revalidate_corpus_selection_result(stale_result, manifest, policy)


def test_result_revalidation_rejects_active_classification_change(tmp_path: Path) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)
    result = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(
            document_family_ids=("alpha",),
            version_mode="all_versions",
            allow_multiple_documents=True,
        ),
    )
    changed_policy = policy.model_copy(
        update={
            "family_policies": tuple(
                family.model_copy(
                    update={
                        "active_document_id": "alpha-old",
                        "historical_document_ids": ("alpha-new",),
                    }
                )
                if family.document_family_id == "alpha"
                else family
                for family in policy.family_policies
            )
        }
    )

    with pytest.raises(CorpusSelectionResultCompatibilityError):
        revalidate_corpus_selection_result(result, manifest, changed_policy)


def test_result_revalidation_rejects_same_id_index_metadata_change(tmp_path: Path) -> None:
    manifest, policy = _manifest_and_policy(tmp_path)
    result = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(document_ids=("alpha-new",)),
    )
    changed_manifest = manifest.model_copy(
        update={
            "entries": tuple(
                entry.model_copy(update={"index_path": "indexes/rebuilt-alpha-new"})
                if entry.identity.document_id == "alpha-new"
                else entry
                for entry in manifest.entries
            )
        }
    )
    assert validate_corpus_version_policy(policy, changed_manifest).policy == policy

    with pytest.raises(CorpusSelectionResultCompatibilityError):
        revalidate_corpus_selection_result(result, changed_manifest, policy)
