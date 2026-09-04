"""Pure reviewed-policy validation and pre-retrieval corpus selection."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from .schemas.corpus_manifest import CorpusDocumentEntry, CorpusManifest
from .schemas.corpus_version import (
    CorpusSelectionRequest,
    CorpusSelectionResult,
    CorpusVersionPolicy,
    SelectedCorpusDocument,
    canonical_corpus_selection_result_bytes,
)


class CorpusSelectionError(Exception):
    """Base class for deterministic corpus-selection failures."""


class CorpusPolicyCompatibilityError(CorpusSelectionError):
    """Raised when a reviewed policy does not exactly classify the current inventory."""


class CorpusSelectionRequestError(CorpusSelectionError):
    """Raised when the supplied selection request is invalid."""


class CorpusSelectionNoMatchError(CorpusSelectionError):
    """Raised when positive identity constraints match no corpus document."""


class CorpusSelectionVersionMismatchError(CorpusSelectionError):
    """Raised when identity matches exist but the requested version class excludes them."""

    def __init__(self, matches: tuple[tuple[str, str], ...]) -> None:
        self.matches = matches
        super().__init__("identity matches do not satisfy the requested version mode")


class CorpusSelectionNotReadyError(CorpusSelectionError):
    """Raised when a selected inventory entry has no ready index."""

    def __init__(self, document_states: tuple[tuple[str, str], ...]) -> None:
        self.document_states = document_states
        super().__init__("one or more selected documents are not ready")


class CorpusSelectionAmbiguousError(CorpusSelectionError):
    """Raised when multiple ready documents match without explicit authorization."""

    def __init__(self, document_ids: tuple[str, ...]) -> None:
        self.document_ids = document_ids
        super().__init__("multiple documents matched but multiple selection is disabled")


@dataclass(frozen=True, slots=True)
class ValidatedCorpusVersionPolicy:
    policy: CorpusVersionPolicy
    classification_by_document_id: tuple[tuple[str, str], ...]


def validate_corpus_version_policy(
    policy: CorpusVersionPolicy,
    manifest: CorpusManifest,
) -> ValidatedCorpusVersionPolicy:
    """Require the reviewed policy to classify the current inventory exactly once."""

    try:
        if not isinstance(policy, CorpusVersionPolicy) or not isinstance(manifest, CorpusManifest):
            raise TypeError
        detached_policy = CorpusVersionPolicy.model_validate(policy.model_dump(mode="json"))
        detached_manifest = CorpusManifest.model_validate(manifest.model_dump(mode="json"))
    except (TypeError, ValidationError) as error:
        raise CorpusPolicyCompatibilityError("policy or corpus manifest is invalid") from error
    if detached_policy.corpus_id != detached_manifest.corpus_id:
        raise CorpusPolicyCompatibilityError("policy corpus ID does not match the manifest")

    documents_by_family: dict[str, set[str]] = {}
    for entry in detached_manifest.entries:
        documents_by_family.setdefault(entry.identity.document_family_id, set()).add(
            entry.identity.document_id
        )
    policy_by_family = {
        family.document_family_id: family for family in detached_policy.family_policies
    }
    if set(policy_by_family) != set(documents_by_family):
        raise CorpusPolicyCompatibilityError("policy family coverage does not match the manifest")

    classifications: list[tuple[str, str]] = []
    classified_ids: set[str] = set()
    for family_id in sorted(documents_by_family):
        family_policy = policy_by_family[family_id]
        active_ids = (
            {family_policy.active_document_id}
            if family_policy.active_document_id is not None
            else set()
        )
        historical_ids = set(family_policy.historical_document_ids)
        family_classified = active_ids | historical_ids
        if family_classified != documents_by_family[family_id]:
            raise CorpusPolicyCompatibilityError(
                "policy document coverage or family relationship does not match the manifest"
            )
        if classified_ids & family_classified:
            raise CorpusPolicyCompatibilityError("a document is classified more than once")
        classified_ids.update(family_classified)
        classifications.extend((document_id, "active") for document_id in sorted(active_ids))
        classifications.extend(
            (document_id, "historical") for document_id in sorted(historical_ids)
        )
    if classified_ids != {entry.identity.document_id for entry in detached_manifest.entries}:
        raise CorpusPolicyCompatibilityError("policy does not classify every manifest document")
    return ValidatedCorpusVersionPolicy(
        policy=detached_policy,
        classification_by_document_id=tuple(sorted(classifications)),
    )


def select_corpus_documents(
    manifest: CorpusManifest,
    policy: CorpusVersionPolicy,
    request: CorpusSelectionRequest,
) -> CorpusSelectionResult:
    """Select ready corpus entries without opening artifacts or running retrieval."""

    validated_policy = validate_corpus_version_policy(policy, manifest)
    try:
        if not isinstance(request, CorpusSelectionRequest):
            raise TypeError
        detached_request = CorpusSelectionRequest.model_validate(request.model_dump(mode="json"))
        detached_manifest = CorpusManifest.model_validate(manifest.model_dump(mode="json"))
    except (TypeError, ValidationError) as error:
        raise CorpusSelectionRequestError("corpus selection request is invalid") from error

    classifications = dict(validated_policy.classification_by_document_id)
    identity_matches = tuple(
        entry for entry in detached_manifest.entries if _matches_identity(entry, detached_request)
    )
    if not identity_matches:
        raise CorpusSelectionNoMatchError("selection constraints matched no corpus document")

    version_matches = tuple(
        entry
        for entry in identity_matches
        if _matches_version(
            classifications[entry.identity.document_id], detached_request.version_mode
        )
    )
    if not version_matches:
        raise CorpusSelectionVersionMismatchError(
            tuple(
                (entry.identity.document_id, classifications[entry.identity.document_id])
                for entry in identity_matches
            )
        )

    not_ready = tuple(
        (entry.identity.document_id, entry.index_state)
        for entry in version_matches
        if entry.index_state != "ready"
    )
    if not_ready:
        raise CorpusSelectionNotReadyError(not_ready)
    if len(version_matches) > 1 and not detached_request.allow_multiple_documents:
        raise CorpusSelectionAmbiguousError(
            tuple(entry.identity.document_id for entry in version_matches)
        )

    selected = tuple(
        SelectedCorpusDocument(
            version_classification=classifications[entry.identity.document_id],
            entry=entry.model_copy(deep=True),
        )
        for entry in version_matches
    )
    try:
        result = CorpusSelectionResult(
            corpus_id=detached_manifest.corpus_id,
            request=detached_request,
            selected_documents=selected,
            selected_document_count=len(selected),
            selected_family_count=len(
                {item.entry.identity.document_family_id for item in selected}
            ),
            selected_institution_count=len(
                {item.entry.identity.institution_id for item in selected}
            ),
        )
        return CorpusSelectionResult.model_validate_json(
            canonical_corpus_selection_result_bytes(result)
        )
    except (TypeError, ValidationError, ValueError) as error:
        raise CorpusSelectionError("corpus selection result validation failed") from error


def _matches_identity(
    entry: CorpusDocumentEntry,
    request: CorpusSelectionRequest,
) -> bool:
    identity = entry.identity
    return (
        (not request.document_ids or identity.document_id in request.document_ids)
        and (not request.institution_ids or identity.institution_id in request.institution_ids)
        and (
            not request.document_family_ids
            or identity.document_family_id in request.document_family_ids
        )
        and (
            not request.degree_levels
            or any(level in identity.degree_levels for level in request.degree_levels)
        )
        and (
            not request.intake_terms
            or any(term in identity.intake_terms for term in request.intake_terms)
        )
    )


def _matches_version(classification: str, mode: str) -> bool:
    return (
        mode == "all_versions"
        or (mode == "active_only" and classification == "active")
        or (mode == "historical_only" and classification == "historical")
    )


__all__ = [
    "CorpusPolicyCompatibilityError",
    "CorpusSelectionAmbiguousError",
    "CorpusSelectionError",
    "CorpusSelectionNoMatchError",
    "CorpusSelectionNotReadyError",
    "CorpusSelectionRequestError",
    "CorpusSelectionVersionMismatchError",
    "ValidatedCorpusVersionPolicy",
    "select_corpus_documents",
    "validate_corpus_version_policy",
]
