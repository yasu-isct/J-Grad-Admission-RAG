"""Reviewed, partial material evidence and teacher report over a pinned candidate slice.

The existing candidate and source PDFs are read only. Raw KB scope and quality are
never promoted; the separate plan supplies the narrowly reviewed locator.
"""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import os
from pathlib import Path
import stat
from typing import Annotated, Literal, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from ..reviewed_fragment_import import Candidate, Lineage
from ..reviewed_source_evidence import (
    Bundle,
    Digest,
    Identifier,
    SourceSet,
    Target,
    Text,
    canonical_json_bytes,
    parse_json,
)
from ..schemas.document_identity import DocumentIdentity
from ..schemas.document_kb import canonical_document_kb_bytes, load_document_kb_bytes
from .applicability import OfficialEvidenceBinding
from .material_conditions import (
    MaterialConditionPolicy,
    MaterialConditionRequest,
    PolicyTrust,
    evaluate,
    load_policy,
    load_request,
)


class MaterialSliceError(ValueError):
    """A reviewed input or report failed closed; no path or applicant facts are exposed."""


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Positive = Annotated[int, Field(strict=True, gt=0)]
Count = Annotated[int, Field(strict=True, ge=0)]


class PlanTrust(Closed):
    plan_id: Identifier
    revision: Positive
    plan_sha256: Digest


class PolicyReference(Closed):
    policy_id: Identifier
    revision: Positive
    sha256: Digest


class SeedReference(Closed):
    bundle_id: Identifier
    revision: Positive
    sha256: Digest


class FilePin(Closed):
    relative_path: Text
    sha256: Digest


class CandidateReference(Closed):
    build_id: Digest
    files: tuple[FilePin, ...] = Field(min_length=1)
    import_config_sha256: Digest
    source_manifest_sha256: Digest
    target_contract_sha256: Digest


class DescriptorDocument(Closed):
    source_id: Identifier
    identity: DocumentIdentity

    @field_validator("identity", mode="before")
    @classmethod
    def complete_identity(cls, value):
        if not isinstance(value, dict) or set(value) != set(DocumentIdentity.model_fields):
            raise ValueError("complete descriptor identity required")
        return value


class CandidateDescriptor(Closed):
    bundle_id: Identifier
    bundle_revision: Positive
    bundle_sha256: Digest
    candidate_schema_version: Literal["1.0"]
    document_identity_schema_version: Literal["1.0"]
    documents: tuple[DescriptorDocument, ...] = Field(min_length=1)
    embedding_text_version: Literal["1"]
    import_config_sha256: Digest
    kb_schema_version: Literal["0.6"]
    lineage_schema_version: Literal["1.0"]
    mapper_version: Literal["1"]
    profile_id: Literal["reviewed-source-v1"]
    profile_version: Literal["1"]
    source_manifest_sha256: Digest
    source_set: SourceSet
    target: Target
    target_contract_sha256: Digest


class PlanSource(Closed):
    source_id: Identifier
    source_role: Literal["common_guideline", "program_guide", "additional_materials"]
    identity: DocumentIdentity
    kb_sha256: Digest
    physical_page_count: Positive

    @field_validator("identity", mode="before")
    @classmethod
    def complete_identity(cls, value):
        if not isinstance(value, dict) or set(value) != set(DocumentIdentity.model_fields):
            raise ValueError("complete source identity required")
        return value


class PlanRelation(Closed):
    from_id: Identifier = Field(alias="from")
    kind: Identifier
    to: Identifier


class ReviewProvenance(Closed):
    image_origin: Text
    method: Text
    reviewed_on: Annotated[str, StringConstraints(strict=True, pattern=r"^\d{4}-\d{2}-\d{2}$")]
    reviewer_id: Identifier
    reviewer_kind: Literal["agent", "human"]
    status: Literal["design_reviewed_for_teacher_slice_not_full_kb_approval"]

    @field_validator("reviewed_on")
    @classmethod
    def valid_date(cls, value):
        date.fromisoformat(value)
        return value


class ScopeReview(Closed):
    manual_anchor: Text
    official_heading_path: tuple[Text, ...] = Field(min_length=1)
    physical_page: Positive
    printed_page_label: Text | None
    record_id: Identifier
    record_revision: Positive
    required_bindings: tuple[OfficialEvidenceBinding, ...] = Field(min_length=1)
    review_image_sha256: Digest
    review_status: Literal["reviewed_for_selected_target"]
    reviewed_target_id: Identifier
    scope_note_zh: Text
    source_id: Identifier
    source_role: Literal["common_guideline", "program_guide", "additional_materials"]
    stage: Literal["application", "enrollment_context_only"]
    use: Literal["basis", "context"]

    @field_validator("required_bindings", mode="before")
    @classmethod
    def strict_binding_pages(cls, values):
        if not isinstance(values, (list, tuple)):
            raise ValueError("bindings must be a sequence")
        for value in values:
            if not isinstance(value, dict) or not isinstance(
                value.get("source_pages"), (list, tuple)
            ):
                raise ValueError("binding pages must be present")
            if any(type(page) is not int for page in value["source_pages"]):
                raise ValueError("binding pages must be strict integers")
        return values


class PlanTopic(Closed):
    basis_record_ids: tuple[Identifier, ...] = Field(min_length=1)
    condition_rule_id: Identifier
    context_note_zh: Text
    matched_explanation_zh: Text
    material_code: Identifier
    material_name_zh: Text
    needs_information_explanation_zh: Text
    not_matched_explanation_zh: Text
    proposed_effect_when_matched: Literal["required", "not_required"]
    required_context_record_ids: tuple[Identifier, ...] = Field(min_length=1)
    stage: Literal["application"]
    topic_id: Identifier


class MaterialSlicePlan(Closed):
    schema_version: Literal["1.0"]
    artifact_role: Literal["reviewed-material-slice-plan"]
    audience: Literal["teacher_preview"]
    authority: Literal["reviewed_material_slice"]
    production_enabled: Literal[False]
    coverage: Literal["partial"]
    historical_reference: Literal[True]
    plan_id: Identifier
    revision: Positive
    target: Target
    source_set: SourceSet
    candidate_reference: CandidateReference
    policy_reference: PolicyReference
    seed_reference: SeedReference
    sources: tuple[PlanSource, ...] = Field(min_length=1)
    scope_reviews: tuple[ScopeReview, ...] = Field(min_length=1)
    relations: tuple[PlanRelation, ...]
    topics: tuple[PlanTopic, ...] = Field(min_length=1)
    review: ReviewProvenance
    limitations_zh: tuple[Text, ...] = Field(min_length=1)

    @field_validator("production_enabled", mode="before")
    @classmethod
    def strict_false(cls, value):
        if value is not False:
            raise ValueError("production flag must be false")
        return value

    @field_validator("historical_reference", mode="before")
    @classmethod
    def strict_true(cls, value):
        if value is not True:
            raise ValueError("historical flag must be true")
        return value

    @model_validator(mode="after")
    def graph(self):
        ids = [row.source_id for row in self.sources]
        records = [row.record_id for row in self.scope_reviews]
        topics = [row.condition_rule_id for row in self.topics]
        if any(len(rows) != len(set(rows)) for rows in (ids, records, topics)):
            raise ValueError("duplicate source, record or topic")
        if len({(r.from_id, r.kind, r.to) for r in self.relations}) != len(self.relations):
            raise ValueError("duplicate relation")
        by_id = {row.source_id: row for row in self.sources}
        by_record = {row.record_id: row for row in self.scope_reviews}
        if set(records) != {
            rid for topic in self.topics for rid in topic.required_context_record_ids
        }:
            raise ValueError("uncovered or missing reviewed record")
        for row in self.scope_reviews:
            source = by_id.get(row.source_id)
            if (
                source is None
                or row.source_role != source.source_role
                or row.reviewed_target_id != self.target.target_id
                or row.physical_page > source.physical_page_count
            ):
                raise ValueError("review scope/source mismatch")
            for binding in row.required_bindings:
                if (
                    binding.document_id != source.identity.document_id
                    or binding.source_kb_sha256 != source.kb_sha256
                    or binding.source_pdf_sha256 != source.identity.source_pdf_sha256
                    or tuple(binding.source_pages) != (row.physical_page,)
                ):
                    raise ValueError("review binding/source mismatch")
        for topic in self.topics:
            if len(set(topic.required_context_record_ids)) != len(
                topic.required_context_record_ids
            ):
                raise ValueError("duplicate topic context")
            if not set(topic.basis_record_ids).issubset(topic.required_context_record_ids):
                raise ValueError("missing topic basis")
            for rid in topic.basis_record_ids:
                if by_record[rid].use != "basis" or by_record[rid].stage != "application":
                    raise ValueError("topic basis lacks application review")
        if any(r.from_id not in by_record or r.to not in by_record for r in self.relations):
            raise ValueError("relation outside reviewed records")
        return self


def digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _normalized(value: BaseModel) -> bytes:
    return canonical_json_bytes(value.model_dump(mode="json", by_alias=True))


def _lineage_relation_bytes(lineage: Lineage) -> tuple[bytes, ...]:
    return tuple(
        _normalized(
            PlanRelation.model_validate({"from": row.from_id, "kind": row.kind, "to": row.to})
        )
        for row in lineage.relations
    )


def load_plan(
    raw: bytes, trust_raw: bytes, policy_raw: bytes, policy_trust_raw: bytes, seed_raw: bytes
):
    """Pure exact-byte trust/plan/policy/seed gate, before candidate or PDF I/O."""
    try:
        trust = PlanTrust.model_validate(parse_json(trust_raw))
        if digest(raw) != trust.plan_sha256:
            raise ValueError("plan pin mismatch")
        plan = MaterialSlicePlan.model_validate(parse_json(raw))
        if (plan.plan_id, plan.revision) != (trust.plan_id, trust.revision):
            raise ValueError("plan identity mismatch")
        _candidate_file_names(plan)
        policy_trust = PolicyTrust.model_validate(parse_json(policy_trust_raw))
        policy = load_policy(policy_raw, policy_trust)
        if (
            plan.policy_reference.policy_id != policy.policy_id
            or plan.policy_reference.revision != policy.revision
            or plan.policy_reference.sha256 != digest(policy_raw)
            or plan.target != policy.target
            or plan.seed_reference.sha256 != digest(seed_raw)
        ):
            raise ValueError("policy, target or seed reference mismatch")
        seed = Bundle.model_validate(parse_json(seed_raw))
        if (
            seed.bundle_id != plan.seed_reference.bundle_id
            or seed.revision != plan.seed_reference.revision
            or seed.target != plan.target
            or seed.source_set != plan.source_set
            or len(seed.records) != len(plan.scope_reviews)
            or set(seed.required_source_ids) != {row.source_id for row in plan.sources}
        ):
            raise ValueError("seed identity mismatch")
        if (
            policy.evidence_prerequisites.bundle_id != seed.bundle_id
            or policy.evidence_prerequisites.bundle_sha256 != digest(seed_raw)
            or policy.evidence_prerequisites.candidate_build_id != plan.candidate_reference.build_id
            or policy.evidence_prerequisites.candidate_manifest_sha256
            != next(
                f.sha256
                for f in plan.candidate_reference.files
                if f.relative_path == "candidate.json"
            )
            or policy.evidence_prerequisites.source_manifest_sha256
            != plan.candidate_reference.source_manifest_sha256
            or policy.evidence_prerequisites.target_contract_sha256
            != plan.candidate_reference.target_contract_sha256
        ):
            raise ValueError("candidate prerequisites mismatch")
        if len(plan.topics) != len(policy.rules):
            raise ValueError("topic count mismatch")
        if {row.source_id for row in policy.evidence_prerequisites.documents} != {
            row.source_id for row in plan.sources
        }:
            raise ValueError("policy source set mismatch")
        reviews = {row.record_id: row for row in plan.scope_reviews}
        for topic, rule in zip(plan.topics, policy.rules, strict=True):
            if (
                topic.condition_rule_id != rule.condition_rule_id
                or topic.topic_id != rule.topic_id
                or topic.material_code != rule.material_code
                or topic.stage != rule.stage
                or topic.proposed_effect_when_matched != rule.proposed_effect_when_matched
                or topic.basis_record_ids != rule.basis_record_ids
                or topic.required_context_record_ids
                != tuple(record.record_id for record in rule.required_context_records)
            ):
                raise ValueError("topic/policy rule mismatch")
            for record in rule.required_context_records:
                review = reviews[record.record_id]
                if review.record_revision != record.record_revision or tuple(
                    _normalized(binding) for binding in review.required_bindings
                ) != tuple(_normalized(binding) for binding in record.required_bindings):
                    raise ValueError("review/policy evidence mismatch")
        return plan, policy, seed, trust.plan_sha256, policy_trust.policy_sha256
    except (ValidationError, ValueError, TypeError, KeyError, StopIteration, IndexError) as exc:
        raise MaterialSliceError("invalid or unbound report plan") from exc


class ReviewedFact(Closed):
    binding: OfficialEvidenceBinding
    text: Text
    fragment_id: Identifier
    fragment_role: Literal[
        "context",
        "clause",
        "cross_reference",
        "table_group_header",
        "table_group_note",
        "table_column_header",
        "table_row_label",
        "table_cell",
    ]
    capture_method: Literal["manual_transcription"]
    raw_scope_type: Literal["unknown"]
    raw_section_path: tuple[str, ...]


class ReviewedRecord(Closed):
    record_id: Identifier
    record_revision: Positive
    source_id: Identifier
    topic_id: Identifier
    stage: Literal["application", "enrollment_context_only"]
    use: Literal["basis", "context"]
    official_heading_path: tuple[Text, ...] = Field(min_length=1)
    manual_anchor: Text
    physical_page: Positive
    printed_page_label: Text | None
    scope_note_zh: Text
    reviewed_target_id: Identifier
    facts: tuple[ReviewedFact, ...] = Field(min_length=1)


class ReviewedMaterialSliceEvidence(Closed):
    schema_version: Literal["1.0"]
    artifact_role: Literal["reviewed-material-slice-evidence"]
    production_enabled: Literal[False]
    authority: Literal["reviewed_material_slice"]
    coverage: Literal["partial"]
    plan_id: Identifier
    revision: Positive
    plan_sha256: Digest
    policy_sha256: Digest
    target: Target
    candidate_build_id: Digest
    candidate_manifest_sha256: Digest
    lineage_sha256: Digest
    sources: tuple[PlanSource, ...] = Field(min_length=1)
    records: tuple[ReviewedRecord, ...] = Field(min_length=1)
    relations: tuple[PlanRelation, ...]
    slice_validation_status: Literal["verified"]


def _candidate_file_names(plan: MaterialSlicePlan) -> set[str]:
    names = [row.relative_path for row in plan.candidate_reference.files]
    if len(names) != len(set(names)):
        raise ValueError("duplicate candidate filename")
    expected = {"candidate.json", "lineage.json"} | {
        f"documents/{row.source_id}/document_kb.json" for row in plan.sources
    }
    if set(names) != expected:
        raise ValueError("candidate file set differs from reviewed plan")
    for name in names:
        if Path(name).is_absolute() or Path(name).as_posix() != name or ".." in Path(name).parts:
            raise ValueError("unsafe candidate filename")
    return expected


def read_candidate_files(root: Path, plan: MaterialSlicePlan) -> dict[str, bytes]:
    """Read exactly the pinned candidate tree, rejecting links/reparse points."""
    wanted = _candidate_file_names(plan)
    expected_dirs = {""}
    for name in wanted:
        parts = Path(name).parts
        expected_dirs.update(Path(*parts[:idx]).as_posix() for idx in range(1, len(parts)))
    try:
        current = root.absolute()
        while True:
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
            ):
                raise ValueError("candidate path is a link")
            if current == current.parent:
                break
            current = current.parent
        files = set()
        dirs = {""}
        pending = [(root, "")]
        while pending:
            folder, prefix = pending.pop()
            for entry in os.scandir(folder):
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
                    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
                ):
                    raise ValueError("candidate tree contains a link")
                relative = f"{prefix}/{entry.name}".lstrip("/")
                if entry.is_dir(follow_symlinks=False):
                    dirs.add(relative)
                    pending.append((Path(entry.path), relative))
                elif entry.is_file(follow_symlinks=False):
                    files.add(relative)
                else:
                    raise ValueError("unsupported candidate entry")
        if files != wanted or dirs != expected_dirs:
            raise ValueError("candidate file set mismatch")
        result = {}
        for row in plan.candidate_reference.files:
            path = root / row.relative_path
            before = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or getattr(
                before, "st_file_attributes", 0
            ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError("unsafe candidate file")
            raw = path.read_bytes()
            after = path.stat(follow_symlinks=False)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("candidate changed during read")
            if digest(raw) != row.sha256:
                raise ValueError("candidate hash mismatch")
            result[row.relative_path] = raw
        return result
    except (OSError, ValueError) as exc:
        raise MaterialSliceError("candidate tree unavailable or invalid") from exc


def read_pdf_bytes(pdf_dir: Path, plan: MaterialSlicePlan) -> dict[str, bytes]:
    """Open only three pinned source names once; page checks use captured bytes."""
    try:
        current = pdf_dir.absolute()
        while True:
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
            ):
                raise ValueError("PDF directory traverses a link")
            if current == current.parent:
                break
            current = current.parent
        result = {}
        for source in plan.sources:
            path = pdf_dir / f"{source.identity.source_pdf_sha256}.pdf"
            info = path.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                or not stat.S_ISREG(info.st_mode)
            ):
                raise ValueError("unsafe PDF source")
            raw = path.read_bytes()
            after = path.stat(follow_symlinks=False)
            if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("PDF source changed during read")
            result[source.source_id] = raw
        return result
    except (OSError, ValueError) as exc:
        raise MaterialSliceError("source PDF unavailable or unsafe") from exc


def _audit_pdf_bytes(raw: bytes, source: PlanSource) -> None:
    import pymupdf

    if digest(raw) != source.identity.source_pdf_sha256:
        raise ValueError("source PDF digest mismatch")
    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        if not pdf.is_pdf or pdf.needs_pass or pdf.page_count != source.physical_page_count:
            raise ValueError("source PDF metadata mismatch")


def verify_evidence_bytes(
    plan: MaterialSlicePlan,
    policy: MaterialConditionPolicy,
    seed: Bundle,
    *,
    plan_sha256: str,
    policy_sha256: str,
    candidate_files: Mapping[str, bytes],
    pdf_bytes: Mapping[str, bytes],
) -> ReviewedMaterialSliceEvidence:
    """Pure bytes-bound audit of the immutable candidate, seed and source PDFs."""
    try:
        if set(candidate_files) != _candidate_file_names(plan):
            raise ValueError("candidate set mismatch")
        for row in plan.candidate_reference.files:
            if digest(candidate_files[row.relative_path]) != row.sha256:
                raise ValueError("candidate file hash mismatch")
        candidate = Candidate.model_validate(parse_json(candidate_files["candidate.json"]))
        lineage = Lineage.model_validate(parse_json(candidate_files["lineage.json"]))
        descriptor = CandidateDescriptor.model_validate(candidate.input_descriptor)
        source_by_id = {row.source_id: row for row in plan.sources}
        descriptor_docs = tuple(
            DescriptorDocument(source_id=s.source_id, identity=s.identity.model_dump(mode="json"))
            for s in sorted(plan.sources, key=lambda row: row.source_id)
        )
        if (
            candidate.build_id != plan.candidate_reference.build_id
            or candidate.build_id != digest(canonical_json_bytes(candidate.input_descriptor))
            or descriptor.bundle_id != seed.bundle_id
            or descriptor.bundle_revision != seed.revision
            or descriptor.bundle_sha256 != plan.seed_reference.sha256
            or descriptor.target != plan.target
            or descriptor.source_set != plan.source_set
            or descriptor.documents != descriptor_docs
            or descriptor.import_config_sha256 != plan.candidate_reference.import_config_sha256
            or descriptor.source_manifest_sha256 != plan.candidate_reference.source_manifest_sha256
            or descriptor.target_contract_sha256 != plan.candidate_reference.target_contract_sha256
            or candidate.lineage_sha256 != digest(candidate_files["lineage.json"])
            or candidate.build_id != lineage.build_id
            or lineage.target != plan.target
            or lineage.source_set != plan.source_set
            or lineage.bundle.bundle_id != seed.bundle_id
            or lineage.bundle.revision != seed.revision
            or lineage.bundle.sha256 != descriptor.bundle_sha256
            or lineage.source_manifest_sha256 != descriptor.source_manifest_sha256
            or lineage.target_contract_sha256 != descriptor.target_contract_sha256
            or lineage.import_config_sha256 != descriptor.import_config_sha256
            or policy.evidence_prerequisites.lineage_sha256
            != digest(candidate_files["lineage.json"])
        ):
            raise ValueError("candidate/lineage provenance mismatch")
        if set(pdf_bytes) != set(source_by_id):
            raise ValueError("PDF source set mismatch")
        for source in plan.sources:
            _audit_pdf_bytes(pdf_bytes[source.source_id], source)
            if (
                source.identity.institution_id != plan.target.institution_id
                or source.identity.document_id != source.source_id
                or plan.target.degree_level not in source.identity.degree_levels
                or not any(
                    term.year == plan.target.intake.year and term.month == plan.target.intake.month
                    for term in source.identity.intake_terms
                )
            ):
                raise ValueError("source identity outside target")
        if (
            len(candidate.documents) != len(plan.sources)
            or len(lineage.documents) != len(plan.sources)
            or len(policy.evidence_prerequisites.documents) != len(plan.sources)
        ):
            raise ValueError("candidate source count mismatch")
        lineage_docs = {row.source_id: row for row in lineage.documents}
        candidate_docs = {row.document_id: row for row in candidate.documents}
        policy_docs = {row.source_id: row for row in policy.evidence_prerequisites.documents}
        kb_facts = {}
        for source in plan.sources:
            relative = f"documents/{source.source_id}/document_kb.json"
            raw = candidate_files[relative]
            doc = candidate_docs[source.source_id]
            lineage_doc = lineage_docs[source.source_id]
            policy_doc = policy_docs[source.source_id]
            kb = load_document_kb_bytes(raw)
            if (
                doc.relative_path != relative
                or doc.kb_sha256 != digest(raw)
                or doc.kb_sha256 != source.kb_sha256
                or lineage_doc.kb_sha256 != source.kb_sha256
                or lineage_doc.identity != source.identity
                or policy_doc.identity != source.identity
                or policy_doc.kb_sha256 != source.kb_sha256
                or kb.manifest.identity != source.identity
                or kb.manifest.source_pdf != f"{source.identity.source_pdf_sha256}.pdf"
                or canonical_document_kb_bytes(kb) != raw
                or kb.entities
                or kb.diagnostics.quality_gate.passed
                or len(kb.facts) != lineage_doc.fact_count
            ):
                raise ValueError("candidate KB/source mismatch")
            facts = {fact.fact_id: fact for fact in kb.facts}
            if len(facts) != len(kb.facts):
                raise ValueError("duplicate KB Fact")
            kb_facts[source.source_id] = facts
        seed_records = {row.record_id: row for row in seed.records}
        reviews = {row.record_id: row for row in plan.scope_reviews}
        lineage_records = {row.record_id: row for row in lineage.records}
        if set(seed_records) != set(reviews) or set(reviews) != set(lineage_records):
            raise ValueError("record set mismatch")
        records = []
        seen_facts = set()
        for review in plan.scope_reviews:
            origin = seed_records[review.record_id]
            mapped = lineage_records[review.record_id]
            if (
                origin.revision != review.record_revision
                or origin.source_id != review.source_id
                or origin.physical_page != review.physical_page
                or origin.printed_page_label != review.printed_page_label
                or origin.manual_anchor != review.manual_anchor
                or origin.topic_id != mapped.topic_id
                or origin.review_record_id != mapped.review_record_id
                or origin.capture_method != mapped.capture_method
                or mapped.revision != review.record_revision
                or mapped.source_id != review.source_id
                or mapped.source_pdf_sha256
                != source_by_id[review.source_id].identity.source_pdf_sha256
                or mapped.physical_page != review.physical_page
                or mapped.printed_page_label != review.printed_page_label
                or mapped.manual_anchor != review.manual_anchor
                or tuple(origin.required_fragment_ids) != tuple(mapped.required_fragment_ids)
                or len(origin.fragments) != len(mapped.fragments)
                or len(origin.fragments) != len(review.required_bindings)
            ):
                raise ValueError("record provenance mismatch")
            by_fragment = {row.fragment_id: row for row in origin.fragments}
            by_mapped = {row.fragment_id: row for row in mapped.fragments}
            if set(by_fragment) != set(by_mapped) or set(by_fragment) != set(
                origin.required_fragment_ids
            ):
                raise ValueError("record fragment mismatch")
            facts = []
            for fid, binding in zip(
                origin.required_fragment_ids, review.required_bindings, strict=True
            ):
                fragment = by_fragment[fid]
                mapped_fragment = by_mapped[fid]
                fact = kb_facts[review.source_id].get(binding.fact_id)
                if fact is None or binding.fact_id in seen_facts:
                    raise ValueError("missing or duplicate Fact")
                seen_facts.add(binding.fact_id)
                if (
                    mapped_fragment.role != fragment.role
                    or mapped_fragment.qualified_fact.document_id != binding.document_id
                    or mapped_fragment.qualified_fact.kb_sha256 != binding.source_kb_sha256
                    or mapped_fragment.qualified_fact.fact_id != binding.fact_id
                    or fact.text != fragment.text
                    or digest(fact.text.encode("utf-8")) != binding.authoritative_fact_text_sha256
                    or tuple(fact.source_pages) != tuple(binding.source_pages)
                    or fact.scope_type != "unknown"
                    or fact.scope_targets
                    or fact.section_path
                    or fact.metadata.get("fragment_id") != fid
                    or fact.metadata.get("fragment_role") != fragment.role
                    or fact.metadata.get("record_id") != origin.record_id
                    or fact.metadata.get("record_revision") != origin.revision
                    or fact.metadata.get("capture_method") != origin.capture_method
                ):
                    raise ValueError("Fact text/page/lineage mismatch")
                facts.append(
                    ReviewedFact(
                        binding=binding,
                        text=fact.text,
                        fragment_id=fid,
                        fragment_role=fragment.role,
                        capture_method=origin.capture_method,
                        raw_scope_type="unknown",
                        raw_section_path=tuple(fact.section_path),
                    )
                )
            records.append(
                ReviewedRecord(
                    record_id=review.record_id,
                    record_revision=review.record_revision,
                    source_id=review.source_id,
                    topic_id=origin.topic_id,
                    stage=review.stage,
                    use=review.use,
                    official_heading_path=review.official_heading_path,
                    manual_anchor=review.manual_anchor,
                    physical_page=review.physical_page,
                    printed_page_label=review.printed_page_label,
                    scope_note_zh=review.scope_note_zh,
                    reviewed_target_id=review.reviewed_target_id,
                    facts=tuple(facts),
                )
            )
        if set(seen_facts) != {fact_id for rows in kb_facts.values() for fact_id in rows}:
            raise ValueError("candidate has unreviewed or omitted Facts")
        seed_relations = tuple(_normalized(row) for row in seed.relations)
        plan_relations = tuple(_normalized(row) for row in plan.relations)
        lineage_relations = _lineage_relation_bytes(lineage)
        if seed_relations != plan_relations or plan_relations != lineage_relations:
            raise ValueError("reviewed relation mismatch")
        return ReviewedMaterialSliceEvidence(
            schema_version="1.0",
            artifact_role="reviewed-material-slice-evidence",
            production_enabled=False,
            authority="reviewed_material_slice",
            coverage="partial",
            plan_id=plan.plan_id,
            revision=plan.revision,
            plan_sha256=plan_sha256,
            policy_sha256=policy_sha256,
            target=plan.target,
            candidate_build_id=candidate.build_id,
            candidate_manifest_sha256=digest(candidate_files["candidate.json"]),
            lineage_sha256=digest(candidate_files["lineage.json"]),
            sources=plan.sources,
            records=tuple(records),
            relations=plan.relations,
            slice_validation_status="verified",
        )
    except (OSError, ValidationError, ValueError, TypeError, KeyError, IndexError) as exc:
        raise MaterialSliceError("reviewed source slice is invalid") from exc


class Citation(Closed):
    citation_key: Text
    record_id: Identifier
    document_id: Identifier
    source_kb_sha256: Digest
    source_pdf_sha256: Digest
    fact_id: Text
    authoritative_fact_text_sha256: Digest
    physical_pages: tuple[Positive, ...] = Field(min_length=1)
    printed_page_label: Text | None
    source_title: Text
    official_source_url: Text
    official_heading_path: tuple[Text, ...] = Field(min_length=1)
    manual_anchor: Text
    fragment_role: Text
    quote_text: Text
    stage: Literal["application", "enrollment_context_only"]
    use: Literal["basis", "context"]


class TopicResult(Closed):
    condition_rule_id: Identifier
    topic_id: Identifier
    material_code: Identifier
    material_name_zh: Text
    stage: Literal["application"]
    condition_status: Literal["matched", "not_matched", "needs_information"]
    disposition: Literal[
        "submission_required", "submission_not_required", "rule_not_applicable", "needs_information"
    ]
    missing_fields: tuple[Text, ...]
    explanation_zh: Text
    limitations_zh: tuple[Text, ...]
    basis_citation_keys: tuple[Text, ...] = Field(min_length=1)
    context_citation_keys: tuple[Text, ...]


class ReviewedMaterialSliceReport(Closed):
    schema_version: Literal["1.0"]
    artifact_role: Literal["reviewed-material-slice-report"]
    production_enabled: Literal[False]
    audience: Literal["teacher_preview"]
    authority: Literal["reviewed_material_slice"]
    coverage: Literal["partial"]
    historical_reference: Literal[True]
    plan_id: Identifier
    revision: Positive
    plan_sha256: Digest
    policy_sha256: Digest
    request_sha256: Digest
    evidence_sha256: Digest | None
    target: Target
    status: Literal["evaluated", "not_covered", "target_mismatch"]
    conflict_fields: tuple[Text, ...]
    topic_results: tuple[TopicResult, ...]
    evidence_inventory: tuple[Citation, ...]
    sources: tuple[PlanSource, ...]
    limitations_zh: tuple[Text, ...] = Field(min_length=1)


def _citation_inventory(evidence: ReviewedMaterialSliceEvidence) -> tuple[Citation, ...]:
    sources = {row.source_id: row for row in evidence.sources}
    citations = []
    for record in evidence.records:
        source = sources[record.source_id]
        for fact in record.facts:
            binding = fact.binding
            citations.append(
                Citation(
                    citation_key=f"{binding.document_id}:{binding.fact_id}",
                    record_id=record.record_id,
                    document_id=binding.document_id,
                    source_kb_sha256=binding.source_kb_sha256,
                    source_pdf_sha256=binding.source_pdf_sha256,
                    fact_id=binding.fact_id,
                    authoritative_fact_text_sha256=binding.authoritative_fact_text_sha256,
                    physical_pages=tuple(binding.source_pages),
                    printed_page_label=record.printed_page_label,
                    source_title=source.identity.official_title,
                    official_source_url=source.identity.official_source_url,
                    official_heading_path=record.official_heading_path,
                    manual_anchor=record.manual_anchor,
                    fragment_role=fact.fragment_role,
                    quote_text=fact.text,
                    stage=record.stage,
                    use=record.use,
                )
            )
    keys = [row.citation_key for row in citations]
    if len(keys) != len(set(keys)):
        raise MaterialSliceError("duplicate citation")
    return tuple(citations)


def _assemble_report(
    plan: MaterialSlicePlan,
    policy: MaterialConditionPolicy,
    request: MaterialConditionRequest,
    *,
    plan_sha256: str,
    policy_sha256: str,
    evidence: ReviewedMaterialSliceEvidence | None,
) -> ReviewedMaterialSliceReport:
    """Internal projection of inputs already bound by the public byte gate."""
    from .material_conditions import canonical_request_bytes

    plan = MaterialSlicePlan.model_validate(plan.model_dump(mode="json", by_alias=True))
    policy = MaterialConditionPolicy.model_validate(policy.model_dump(mode="json"))
    request = MaterialConditionRequest.model_validate(request.model_dump(mode="json"))
    preview = evaluate(policy, request, policy_sha256)
    matched = preview.status == "evaluated"
    if matched and evidence is None:
        raise MaterialSliceError("verified evidence required for covered request")
    if evidence is not None:
        evidence = ReviewedMaterialSliceEvidence.model_validate(
            evidence.model_dump(mode="json", by_alias=True)
        )
        if (
            evidence.plan_id != plan.plan_id
            or evidence.plan_sha256 != plan_sha256
            or evidence.policy_sha256 != policy_sha256
            or evidence.target != plan.target
        ):
            raise MaterialSliceError("evidence does not bind the report inputs")
    inventory = _citation_inventory(evidence) if matched else ()
    if matched:
        by_record = {}
        for citation in inventory:
            by_record.setdefault(citation.record_id, []).append(citation.citation_key)
        results = []
        for topic, condition, rule in zip(plan.topics, preview.entries, policy.rules, strict=True):
            if (
                topic.condition_rule_id != condition.condition_rule_id
                or topic.condition_rule_id != rule.condition_rule_id
            ):
                raise MaterialSliceError("topic condition alignment mismatch")
            status = condition.condition_status
            disposition = (
                "submission_required"
                if status == "matched" and rule.proposed_effect_when_matched == "required"
                else "submission_not_required"
                if status == "matched"
                else "rule_not_applicable"
                if status == "not_matched"
                else "needs_information"
            )
            explanation = (
                topic.matched_explanation_zh
                if status == "matched"
                else topic.not_matched_explanation_zh
                if status == "not_matched"
                else topic.needs_information_explanation_zh
            )
            context_ids = tuple(
                rid
                for rid in topic.required_context_record_ids
                if rid not in topic.basis_record_ids
            )
            if not all(rid in by_record for rid in topic.required_context_record_ids):
                raise MaterialSliceError("topic lacks complete reviewed context")
            results.append(
                TopicResult(
                    condition_rule_id=rule.condition_rule_id,
                    topic_id=rule.topic_id,
                    material_code=rule.material_code,
                    material_name_zh=topic.material_name_zh,
                    stage=topic.stage,
                    condition_status=status,
                    disposition=disposition,
                    missing_fields=condition.missing_fields,
                    explanation_zh=explanation,
                    limitations_zh=(topic.context_note_zh,),
                    basis_citation_keys=tuple(
                        key for rid in topic.basis_record_ids for key in by_record[rid]
                    ),
                    context_citation_keys=tuple(
                        key for rid in context_ids for key in by_record[rid]
                    ),
                )
            )
    else:
        results = []
    return ReviewedMaterialSliceReport(
        schema_version="1.0",
        artifact_role="reviewed-material-slice-report",
        production_enabled=False,
        audience="teacher_preview",
        authority="reviewed_material_slice",
        coverage="partial",
        historical_reference=True,
        plan_id=plan.plan_id,
        revision=plan.revision,
        plan_sha256=plan_sha256,
        policy_sha256=policy_sha256,
        request_sha256=digest(canonical_request_bytes(request)),
        evidence_sha256=digest(_normalized(evidence)) if matched else None,
        target=request.target,
        status=preview.status,
        conflict_fields=preview.conflict_fields,
        topic_results=tuple(results),
        evidence_inventory=inventory,
        sources=evidence.sources if matched else (),
        limitations_zh=plan.limitations_zh,
    )


def assemble_reports(
    *,
    plan_raw: bytes,
    trust_raw: bytes,
    policy_raw: bytes,
    policy_trust_raw: bytes,
    seed_raw: bytes,
    request_raws: tuple[bytes, ...],
    candidate_files: Mapping[str, bytes] | None,
    pdf_bytes: Mapping[str, bytes] | None,
) -> tuple[ReviewedMaterialSliceReport, ...]:
    """Bind every report to external pinned bytes; audit a covered batch only once."""
    plan, policy, seed, plan_sha, policy_sha = load_plan(
        plan_raw, trust_raw, policy_raw, policy_trust_raw, seed_raw
    )
    requests = tuple(load_request(raw) for raw in request_raws)
    covered = any(
        evaluate(policy, request, policy_sha).status == "evaluated" for request in requests
    )
    evidence = (
        verify_evidence_bytes(
            plan,
            policy,
            seed,
            plan_sha256=plan_sha,
            policy_sha256=policy_sha,
            candidate_files=candidate_files or {},
            pdf_bytes=pdf_bytes or {},
        )
        if covered
        else None
    )
    return tuple(
        _assemble_report(
            plan,
            policy,
            request,
            plan_sha256=plan_sha,
            policy_sha256=policy_sha,
            evidence=evidence,
        )
        for request in requests
    )


def assemble_report(
    *,
    plan_raw: bytes,
    trust_raw: bytes,
    policy_raw: bytes,
    policy_trust_raw: bytes,
    seed_raw: bytes,
    request_raw: bytes,
    candidate_files: Mapping[str, bytes] | None,
    pdf_bytes: Mapping[str, bytes] | None,
) -> ReviewedMaterialSliceReport:
    """Public single-report entrypoint with no caller-supplied evidence snapshot."""
    return assemble_reports(
        plan_raw=plan_raw,
        trust_raw=trust_raw,
        policy_raw=policy_raw,
        policy_trust_raw=policy_trust_raw,
        seed_raw=seed_raw,
        request_raws=(request_raw,),
        candidate_files=candidate_files,
        pdf_bytes=pdf_bytes,
    )[0]


def load_report(
    raw: bytes,
    *,
    plan_raw: bytes,
    trust_raw: bytes,
    policy_raw: bytes,
    policy_trust_raw: bytes,
    seed_raw: bytes,
    request_raw: bytes,
    candidate_files: Mapping[str, bytes] | None,
    pdf_bytes: Mapping[str, bytes] | None,
) -> ReviewedMaterialSliceReport:
    """Reject forged reports by recomputing from external pinned bytes."""
    try:
        expected = assemble_report(
            plan_raw=plan_raw,
            trust_raw=trust_raw,
            policy_raw=policy_raw,
            policy_trust_raw=policy_trust_raw,
            seed_raw=seed_raw,
            request_raw=request_raw,
            candidate_files=candidate_files,
            pdf_bytes=pdf_bytes,
        )
        supplied = ReviewedMaterialSliceReport.model_validate(parse_json(raw))
        if raw != _normalized(supplied) or _normalized(expected) != _normalized(supplied):
            raise ValueError("report differs from trusted recomputation")
        return expected
    except (ValidationError, ValueError, TypeError, KeyError, IndexError) as exc:
        raise MaterialSliceError("invalid or unbound material report") from exc


def _markdown_text(value: str) -> str:
    """Escape user-independent text and prevent raw HTML/Markdown control."""
    import html
    import re

    escaped = html.escape(value, quote=True)
    return (
        re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", escaped).replace("\r", " ").replace("\n", " ")
    )


def _render_markdown(report: ReviewedMaterialSliceReport) -> str:
    """Internal formatter; callers must first use a byte-bound public entrypoint."""
    report = ReviewedMaterialSliceReport.model_validate(report.model_dump(mode="json"))
    target = report.target
    lines = [
        "# 募集要项参考报告（历史固定切片／部分材料主题）",
        "",
        f"选定范围：{_markdown_text(str(target.intake.year))} 年 "
        f"{_markdown_text(str(target.intake.month))} 月入学；"
        f"{_markdown_text(target.degree_level)}；"
        f"{_markdown_text(target.selection_route_id)}；"
        f"日程 {_markdown_text(target.examination_schedule_id)}。",
        "",
    ]
    if report.status != "evaluated":
        lines.extend(
            [
                "当前选择不在本审核切片内。"
                if report.status == "not_covered"
                else "所填目标与选择冲突，未生成材料结论。",
                "",
            ]
        )
        if report.conflict_fields:
            lines.append(
                "冲突字段：" + "、".join(_markdown_text(x) for x in report.conflict_fields)
            )
            lines.append("")
    else:
        by_key = {row.citation_key: row for row in report.evidence_inventory}
        labels = {
            "submission_required": "需要提交（仅此审核条件与主题）",
            "submission_not_required": "无需提交（仅此材料本身）",
            "rule_not_applicable": "本条条件不适用；不能据此推定一般性免交",
            "needs_information": "信息不足",
        }
        roles = {
            "table_group_header": "表格上传组表头",
            "table_group_note": "表格上传组说明",
            "table_column_header": "表格列标题",
            "table_row_label": "表格材料行",
            "table_cell": "表格对象单元格",
        }
        for topic in report.topic_results:
            lines.extend(
                [
                    f"## {_markdown_text(topic.material_name_zh)}",
                    "",
                    f"审核结果：{labels[topic.disposition]}。",
                    "",
                    "中文审核说明：" + _markdown_text(topic.explanation_zh),
                    "",
                ]
            )
            if topic.missing_fields:
                lines.extend(
                    [
                        "尚未填写的事实："
                        + "、".join(_markdown_text(x) for x in topic.missing_fields),
                        "",
                    ]
                )
            for note in topic.limitations_zh:
                lines.extend(["关联说明：" + _markdown_text(note), ""])
            for label, keys in (
                ("本条依据的官方原文", topic.basis_citation_keys),
                ("关联上下文（不构成额外提交义务）", topic.context_citation_keys),
            ):
                if not keys:
                    continue
                lines.extend([f"### {label}", ""])
                for key in keys:
                    citation = by_key[key]
                    page = f"物理页 {', '.join(map(str, citation.physical_pages))}"
                    if citation.printed_page_label is not None:
                        page += f"；印刷页 {_markdown_text(citation.printed_page_label)}"
                    stage = "；入学手续关联" if citation.stage == "enrollment_context_only" else ""
                    role = roles.get(citation.fragment_role)
                    prefix = f"{_markdown_text(role)}：" if role else ""
                    lines.extend(
                        [
                            f"- {_markdown_text(citation.source_title)}（{page}{stage}）",
                            "  日文官方原文：",
                            "> " + prefix + _markdown_text(citation.quote_text),
                            "  章节："
                            + " › ".join(_markdown_text(x) for x in citation.official_heading_path),
                            f"  官方来源：<{citation.official_source_url}>",
                            "",
                        ]
                    )
    lines.extend(["## 覆盖范围与限制", ""])
    lines.extend("- " + _markdown_text(value) for value in report.limitations_zh)
    return "\n".join(lines) + "\n"


def render_markdown(
    raw: bytes,
    *,
    plan_raw: bytes,
    trust_raw: bytes,
    policy_raw: bytes,
    policy_trust_raw: bytes,
    seed_raw: bytes,
    request_raw: bytes,
    candidate_files: Mapping[str, bytes] | None,
    pdf_bytes: Mapping[str, bytes] | None,
) -> str:
    """Render only after recomputing the supplied report from pinned external bytes."""
    report = load_report(
        raw,
        plan_raw=plan_raw,
        trust_raw=trust_raw,
        policy_raw=policy_raw,
        policy_trust_raw=policy_trust_raw,
        seed_raw=seed_raw,
        request_raw=request_raw,
        candidate_files=candidate_files,
        pdf_bytes=pdf_bytes,
    )
    return _render_markdown(report)
