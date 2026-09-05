"""Exact official evidence materialization for one reviewed report plan."""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from ..corpus import CorpusAuditError, audit_corpus_manifest, resolve_registered_corpus_kb_path
from ..corpus_selection import (
    CorpusSelectionError,
    revalidate_corpus_selection_result,
)
from ..schemas.corpus_manifest import CorpusManifest
from ..schemas.corpus_version import CorpusSelectionResult, CorpusVersionPolicy
from ..schemas.document_identity import DocumentIdentity
from ..schemas.document_kb import (
    DocumentKnowledgeBase,
    DocumentKnowledgeBaseError,
    canonical_document_kb_bytes,
)
from .applicability import _evidence_scope_matches_rule
from .reviewed_report_plan import ReviewedReportPlan

REVIEWED_REPORT_EVIDENCE_SCHEMA_VERSION = "1.0"
SUPPORTED_REVIEWED_REPORT_EVIDENCE_SCHEMA_VERSIONS = frozenset(
    {REVIEWED_REPORT_EVIDENCE_SCHEMA_VERSION}
)
MAX_REVIEWED_REPORT_PLANS = 1000
_GENERIC_ERROR_MESSAGE = "reviewed report evidence operation failed"
_SAFE_PLAN_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")


class ReviewedReportEvidenceFailure(str, Enum):
    """Stable privacy-safe failure codes for evidence preparation."""

    INVALID_INPUT = "invalid_input"
    INVALID_BUNDLE = "invalid_bundle"
    SELECTION_CARDINALITY = "selection_cardinality"
    CORPUS_AUDIT_FAILED = "corpus_audit_failed"
    SELECTION_STALE = "selection_stale"
    PLAN_NOT_FOUND = "plan_not_found"
    PLAN_AMBIGUOUS = "plan_ambiguous"
    KB_UNAVAILABLE = "kb_unavailable"
    KB_NOT_CANONICAL = "kb_not_canonical"
    KB_IDENTITY_MISMATCH = "kb_identity_mismatch"
    KB_HASH_MISMATCH = "kb_hash_mismatch"
    KB_QUALITY_FAILED = "kb_quality_failed"
    FACT_DUPLICATE = "fact_duplicate"
    FACT_NOT_FOUND = "fact_not_found"
    FACT_PAGES_MISMATCH = "fact_pages_mismatch"
    FACT_TEXT_MISMATCH = "fact_text_mismatch"
    FACT_SCOPE_MISMATCH = "fact_scope_mismatch"


class ReviewedReportEvidenceError(Exception):
    """One generic public error carrying an allowlisted diagnostic code."""

    def __init__(self, code: ReviewedReportEvidenceFailure) -> None:
        self.code = code
        super().__init__(_GENERIC_ERROR_MESSAGE)


class ReviewedReportEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewedReportEvidenceRecord(ReviewedReportEvidenceModel):
    document_id: str
    fact_id: str
    text: str
    source_pages: tuple[StrictInt, ...] = Field(min_length=1)
    section_path: tuple[str, ...] = Field(min_length=1)
    fact_type: str
    scope_type: Literal["global", "university", "college", "department", "program", "unknown"]
    scope_targets: tuple[str, ...] = ()
    parent_college: str | None = None
    rule_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("document_id", "fact_id", "fact_type")
    @classmethod
    def identifiers_must_be_explicit(cls, value: str) -> str:
        _validate_trimmed(value)
        return value

    @field_validator("text")
    @classmethod
    def official_text_must_be_exact_and_nonempty(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("official text must be a non-empty string")
        return value

    @field_validator("source_pages")
    @classmethod
    def pages_must_be_canonical(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value <= 0 for value in values) or values != tuple(sorted(set(values))):
            raise ValueError("source pages must be positive, sorted, and unique")
        return values

    @field_validator("section_path")
    @classmethod
    def section_path_must_be_explicit(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _validate_trimmed(value)
        return values

    @field_validator("scope_targets", "rule_ids")
    @classmethod
    def string_sets_must_be_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _validate_trimmed(value)
        if values != tuple(sorted(set(values))):
            raise ValueError("record string sets must be sorted and unique")
        return values

    @field_validator("parent_college")
    @classmethod
    def parent_college_must_be_explicit(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_trimmed(value)
        return value

    @model_validator(mode="after")
    def scope_fields_must_reconcile(self) -> ReviewedReportEvidenceRecord:
        if self.scope_type == "global" and (self.scope_targets or self.parent_college):
            raise ValueError("global evidence cannot have targeted scope")
        return self


class ReviewedReportEvidenceCounts(ReviewedReportEvidenceModel):
    record_count: StrictInt = Field(ge=1)
    rule_count: StrictInt = Field(ge=1)
    source_page_count: StrictInt = Field(ge=1)


class ReviewedReportEvidenceBundle(ReviewedReportEvidenceModel):
    schema_version: Literal["1.0"] = REVIEWED_REPORT_EVIDENCE_SCHEMA_VERSION
    plan_id: str
    document_identity: DocumentIdentity
    source_kb_sha256: str
    evidence_records: tuple[ReviewedReportEvidenceRecord, ...] = Field(min_length=1)
    counts: ReviewedReportEvidenceCounts

    @model_validator(mode="before")
    @classmethod
    def nested_snapshots_must_be_revalidated(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        detached = dict(value)
        identity = detached.get("document_identity")
        if isinstance(identity, DocumentIdentity):
            detached["document_identity"] = identity.model_dump(mode="json")
        records = detached.get("evidence_records")
        if isinstance(records, (list, tuple)):
            detached["evidence_records"] = [
                item.model_dump(mode="json")
                if isinstance(item, ReviewedReportEvidenceRecord)
                else item
                for item in records
            ]
        counts = detached.get("counts")
        if isinstance(counts, ReviewedReportEvidenceCounts):
            detached["counts"] = counts.model_dump(mode="json")
        return detached

    @field_validator("plan_id")
    @classmethod
    def plan_id_must_be_explicit(cls, value: str) -> str:
        if not isinstance(value, str) or _SAFE_PLAN_ID.fullmatch(value) is None:
            raise ValueError("plan ID is unsafe or unsupported")
        return value

    @field_validator("source_kb_sha256")
    @classmethod
    def source_hash_must_be_sha256(cls, value: str) -> str:
        _validate_sha256(value)
        return value

    @model_validator(mode="after")
    def records_and_counts_must_reconcile(self) -> ReviewedReportEvidenceBundle:
        keys = tuple((item.document_id, item.fact_id) for item in self.evidence_records)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("evidence records must be sorted and unique")
        if any(
            record.document_id != self.document_identity.document_id
            for record in self.evidence_records
        ):
            raise ValueError("evidence record document identity does not reconcile")
        expected = ReviewedReportEvidenceCounts(
            record_count=len(self.evidence_records),
            rule_count=len(
                {rule_id for record in self.evidence_records for rule_id in record.rule_ids}
            ),
            source_page_count=len(
                {
                    (record.document_id, page)
                    for record in self.evidence_records
                    for page in record.source_pages
                }
            ),
        )
        if self.counts != expected:
            raise ValueError("evidence aggregate counts do not reconcile")
        return self


def prepare_reviewed_report_evidence(
    corpus_root: str | Path,
    manifest: CorpusManifest,
    policy: CorpusVersionPolicy,
    selection: CorpusSelectionResult,
    plans: tuple[ReviewedReportPlan, ...],
) -> ReviewedReportEvidenceBundle:
    """Materialize every exact reviewed binding for one audited selected document."""

    if isinstance(selection, CorpusSelectionResult) and isinstance(
        selection.selected_documents, tuple
    ):
        if len(selection.selected_documents) != 1:
            _fail(ReviewedReportEvidenceFailure.SELECTION_CARDINALITY)
    try:
        if (
            not isinstance(manifest, CorpusManifest)
            or not isinstance(policy, CorpusVersionPolicy)
            or not isinstance(selection, CorpusSelectionResult)
            or not isinstance(plans, tuple)
            or not plans
            or len(plans) > MAX_REVIEWED_REPORT_PLANS
        ):
            raise TypeError
        detached_manifest = CorpusManifest.model_validate(manifest.model_dump(mode="json"))
        detached_policy = CorpusVersionPolicy.model_validate(policy.model_dump(mode="json"))
        detached_selection = CorpusSelectionResult.model_validate(selection.model_dump(mode="json"))
        detached_plans = tuple(
            ReviewedReportPlan.model_validate(plan.model_dump(mode="json")) for plan in plans
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        _fail(ReviewedReportEvidenceFailure.INVALID_INPUT)

    try:
        audited_manifest = audit_corpus_manifest(detached_manifest, corpus_root)
    except CorpusAuditError:
        _fail(ReviewedReportEvidenceFailure.CORPUS_AUDIT_FAILED)
    try:
        validated_selection = revalidate_corpus_selection_result(
            detached_selection,
            audited_manifest,
            detached_policy,
        )
    except CorpusSelectionError:
        _fail(ReviewedReportEvidenceFailure.SELECTION_STALE)
    if len(validated_selection.selected_documents) != 1:
        _fail(ReviewedReportEvidenceFailure.SELECTION_CARDINALITY)

    selected = validated_selection.selected_documents[0].entry
    matching_plans = tuple(
        plan for plan in detached_plans if plan.document_identity == selected.identity
    )
    if not matching_plans:
        _fail(ReviewedReportEvidenceFailure.PLAN_NOT_FOUND)
    if len(matching_plans) != 1:
        _fail(ReviewedReportEvidenceFailure.PLAN_AMBIGUOUS)
    plan = matching_plans[0]

    try:
        kb_path = resolve_registered_corpus_kb_path(corpus_root, selected.kb_path)
    except CorpusAuditError:
        _fail(ReviewedReportEvidenceFailure.KB_UNAVAILABLE)
    raw_bytes, kb, source_kb_sha256 = _load_canonical_kb(kb_path)
    del raw_bytes
    if kb.manifest.identity != selected.identity or kb.manifest.identity != plan.document_identity:
        _fail(ReviewedReportEvidenceFailure.KB_IDENTITY_MISMATCH)
    if not kb.diagnostics.quality_gate.passed:
        _fail(ReviewedReportEvidenceFailure.KB_QUALITY_FAILED)
    if source_kb_sha256 != selected.source_kb_sha256 or source_kb_sha256 != plan.source_kb_sha256:
        _fail(ReviewedReportEvidenceFailure.KB_HASH_MISMATCH)

    fact_by_id: dict[str, Any] = {}
    for fact in kb.facts:
        if fact.fact_id in fact_by_id:
            _fail(ReviewedReportEvidenceFailure.FACT_DUPLICATE)
        fact_by_id[fact.fact_id] = fact

    rule_ids_by_fact: dict[str, set[str]] = {}
    for rule in plan.rules:
        for binding in rule.evidence_bindings:
            fact = fact_by_id.get(binding.fact_id)
            if fact is None:
                _fail(ReviewedReportEvidenceFailure.FACT_NOT_FOUND)
            if tuple(fact.source_pages) != binding.source_pages:
                _fail(ReviewedReportEvidenceFailure.FACT_PAGES_MISMATCH)
            if hashlib.sha256(fact.text.encode("utf-8")).hexdigest() != (
                binding.authoritative_fact_text_sha256
            ):
                _fail(ReviewedReportEvidenceFailure.FACT_TEXT_MISMATCH)
            if not _evidence_scope_matches_rule(fact, rule.scope):
                _fail(ReviewedReportEvidenceFailure.FACT_SCOPE_MISMATCH)
            rule_ids_by_fact.setdefault(binding.fact_id, set()).add(rule.rule_id)

    records = tuple(
        _record_from_fact(
            selected.identity.document_id,
            fact_by_id[fact_id],
            tuple(sorted(rule_ids)),
        )
        for fact_id, rule_ids in sorted(rule_ids_by_fact.items())
    )
    counts = ReviewedReportEvidenceCounts(
        record_count=len(records),
        rule_count=len({rule_id for record in records for rule_id in record.rule_ids}),
        source_page_count=len(
            {(record.document_id, page) for record in records for page in record.source_pages}
        ),
    )
    try:
        bundle = ReviewedReportEvidenceBundle(
            plan_id=plan.plan_id,
            document_identity=selected.identity.model_copy(deep=True),
            source_kb_sha256=source_kb_sha256,
            evidence_records=records,
            counts=counts,
        )
        return load_reviewed_report_evidence_bundle_bytes(
            canonical_reviewed_report_evidence_bundle_bytes(bundle)
        )
    except (ReviewedReportEvidenceError, ValidationError, ValueError):
        _fail(ReviewedReportEvidenceFailure.INVALID_BUNDLE)


def canonical_reviewed_report_evidence_bundle_bytes(
    bundle: ReviewedReportEvidenceBundle,
) -> bytes:
    """Serialize a revalidated evidence bundle as canonical finite JSON."""

    try:
        if not isinstance(bundle, ReviewedReportEvidenceBundle) or set(bundle.__dict__) != set(
            ReviewedReportEvidenceBundle.model_fields
        ):
            raise TypeError
        validated = ReviewedReportEvidenceBundle.model_validate(bundle.model_dump(mode="json"))
        serialized = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValidationError, ValueError):
        _fail(ReviewedReportEvidenceFailure.INVALID_BUNDLE)
    return f"{serialized}\n".encode("utf-8")


def load_reviewed_report_evidence_bundle_bytes(
    raw_bytes: bytes,
) -> ReviewedReportEvidenceBundle:
    """Load strict bundle bytes without accepting a persistence path."""

    try:
        if not isinstance(raw_bytes, bytes):
            raise TypeError
        payload = json.loads(raw_bytes.decode("utf-8"), parse_constant=_reject_constant)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version")
            not in SUPPORTED_REVIEWED_REPORT_EVIDENCE_SCHEMA_VERSIONS
        ):
            raise ValueError
        return ReviewedReportEvidenceBundle.model_validate(payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValidationError,
        ValueError,
    ):
        _fail(ReviewedReportEvidenceFailure.INVALID_BUNDLE)


def _load_canonical_kb(path: Path) -> tuple[bytes, DocumentKnowledgeBase, str]:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError
        raw_bytes = path.read_bytes()
        kb = DocumentKnowledgeBase.model_validate_json(raw_bytes)
    except (OSError, ValidationError, ValueError):
        _fail(ReviewedReportEvidenceFailure.KB_UNAVAILABLE)
    try:
        if canonical_document_kb_bytes(kb) != raw_bytes:
            _fail(ReviewedReportEvidenceFailure.KB_NOT_CANONICAL)
    except DocumentKnowledgeBaseError:
        _fail(ReviewedReportEvidenceFailure.KB_NOT_CANONICAL)
    return raw_bytes, kb, hashlib.sha256(raw_bytes).hexdigest()


def _record_from_fact(
    document_id: str,
    fact: Any,
    rule_ids: tuple[str, ...],
) -> ReviewedReportEvidenceRecord:
    return ReviewedReportEvidenceRecord(
        document_id=document_id,
        fact_id=fact.fact_id,
        text=fact.text,
        source_pages=tuple(fact.source_pages),
        section_path=tuple(fact.section_path),
        fact_type=fact.fact_type,
        scope_type=fact.scope_type,
        scope_targets=tuple(sorted(set(fact.scope_targets))),
        parent_college=fact.parent_college,
        rule_ids=rule_ids,
    )


def _fail(code: ReviewedReportEvidenceFailure) -> Any:
    raise ReviewedReportEvidenceError(code) from None


def _validate_trimmed(value: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("string must be non-empty and trimmed")


def _validate_sha256(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("value must be lowercase SHA-256")


def _reject_constant(_: str) -> Any:
    raise ValueError("non-finite JSON numbers are not supported")


__all__ = [
    "REVIEWED_REPORT_EVIDENCE_SCHEMA_VERSION",
    "SUPPORTED_REVIEWED_REPORT_EVIDENCE_SCHEMA_VERSIONS",
    "ReviewedReportEvidenceBundle",
    "ReviewedReportEvidenceCounts",
    "ReviewedReportEvidenceError",
    "ReviewedReportEvidenceFailure",
    "ReviewedReportEvidenceRecord",
    "canonical_reviewed_report_evidence_bundle_bytes",
    "load_reviewed_report_evidence_bundle_bytes",
    "prepare_reviewed_report_evidence",
]
