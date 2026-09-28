"""Pinned, condition-only previews for reviewed material topics; no KB or PDF access."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    field_validator,
    model_validator,
)

from ..reviewed_source_evidence import Digest, Identifier, Target, canonical_json_bytes, parse_json
from ..schemas.document_identity import DocumentIdentity
from .applicant_profile import ApplicantProfile
from .applicability import OfficialEvidenceBinding
from .condition_core import combine, compare


class MaterialConditionError(ValueError):
    """Untrusted input or unsupported preview; never echo applicant facts."""


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PolicyTrust(ClosedModel):
    policy_id: Identifier
    revision: Annotated[int, Field(strict=True, gt=0)]
    policy_sha256: Digest


class ProfileTargetAliases(ClosedModel):
    graduate_school_or_college: tuple[str, ...] = Field(min_length=1)
    department_or_program: tuple[str, ...] = Field(min_length=1)
    application_route: tuple[str, ...] = Field(min_length=1)

    @field_validator("*")
    @classmethod
    def unique_explicit(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or any(not x or x != x.strip() for x in values):
            raise ValueError("aliases must be explicit and unique")
        return values


class PolicyDocument(ClosedModel):
    source_id: Identifier
    identity: DocumentIdentity
    kb_sha256: Digest


class EvidencePrerequisites(ClosedModel):
    bundle_id: Identifier
    bundle_revision: Annotated[int, Field(strict=True, gt=0)]
    bundle_sha256: Digest
    candidate_build_id: Digest
    candidate_manifest_sha256: Digest
    documents: tuple[PolicyDocument, ...] = Field(min_length=1)
    lineage_sha256: Digest
    runtime_evidence_verified: Literal[False]
    source_manifest_sha256: Digest
    target_contract_sha256: Digest

    @field_validator("runtime_evidence_verified", mode="before")
    @classmethod
    def require_false(cls, value):
        if value is not False:
            raise ValueError("runtime evidence is not verified")
        return value

    @model_validator(mode="after")
    def document_ids_unique(self):
        ids = [row.source_id for row in self.documents]
        if len(ids) != len(set(ids)) or any(
            row.identity.document_id != row.source_id for row in self.documents
        ):
            raise ValueError("policy source/document IDs must be unique and equal")
        return self


class ContextRecord(ClosedModel):
    record_id: Identifier
    record_revision: Annotated[int, Field(strict=True, gt=0)]
    required_bindings: tuple[OfficialEvidenceBinding, ...] = Field(min_length=1)

    @field_validator("required_bindings", mode="before")
    @classmethod
    def pages_are_strict_in_legacy_binding(cls, values):
        # Narrow this additive policy boundary without changing the old v1 model.
        if not isinstance(values, (list, tuple)):
            raise ValueError("required bindings must be a sequence")
        for value in values:
            if not isinstance(value, dict):
                raise ValueError("required binding must be an object")
            pages = value.get("source_pages")
            if not isinstance(pages, (list, tuple)) or any(type(page) is not int for page in pages):
                raise ValueError("source pages must be strict integers")
        return values


class ConditionPredicate(ClosedModel):
    field_path: Literal[
        "employment.currently_employed_in_organization",
        "employment.retain_employment_at_enrollment",
    ]
    operator: Literal["equals", "not_equals"]
    expected_value: StrictBool


class ConditionRule(ClosedModel):
    basis_record_ids: tuple[Identifier, ...] = Field(min_length=1)
    condition_rule_id: Identifier
    limitation_zh: str = Field(min_length=1)
    material_code: Identifier
    mode: Literal["all", "any"]
    predicates: tuple[ConditionPredicate, ...]
    proposed_effect_when_matched: Literal["required", "not_required"]
    required_context_records: tuple[ContextRecord, ...] = Field(min_length=1)
    stage: Literal["application"]
    topic_id: Identifier

    @model_validator(mode="after")
    def coherent_rule(self):
        keys = [(p.field_path, p.operator, p.expected_value) for p in self.predicates]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate condition predicate")
        if self.mode == "all":
            for field_path in {p.field_path for p in self.predicates}:
                predicates = [p for p in self.predicates if p.field_path == field_path]
                if not any(
                    all(compare(value, p.operator, p.expected_value) for p in predicates)
                    for value in (True, False)
                ):
                    raise ValueError("contradictory all-mode predicates")
        record_ids = [row.record_id for row in self.required_context_records]
        if len(record_ids) != len(set(record_ids)) or not set(self.basis_record_ids).issubset(
            record_ids
        ):
            raise ValueError("missing or duplicate required context record")
        if len(self.basis_record_ids) != len(set(self.basis_record_ids)):
            raise ValueError("duplicate basis record")
        return self


class MaterialConditionPolicy(ClosedModel):
    schema_version: Literal["1.0"]
    artifact_role: Literal["material-condition-policy"]
    production_enabled: Literal[False]
    authority: Literal["condition_only"]
    review_status: Literal["design_reviewed_not_activated"]
    policy_id: Identifier
    revision: Annotated[int, Field(strict=True, gt=0)]
    condition_logic_version: Literal["1"]
    target: Target
    profile_target_aliases: ProfileTargetAliases
    evidence_prerequisites: EvidencePrerequisites
    rules: tuple[ConditionRule, ...] = Field(min_length=1)

    @field_validator("production_enabled", mode="before")
    @classmethod
    def require_false(cls, value):
        if value is not False:
            raise ValueError("policy cannot be production enabled")
        return value

    @model_validator(mode="after")
    def policy_graph(self):
        rules = self.rules
        if len({r.condition_rule_id for r in rules}) != len(rules) or len(
            {(r.topic_id, r.material_code) for r in rules}
        ) != len(rules):
            raise ValueError("duplicate condition rule or topic/material")
        docs = {row.identity.document_id: row for row in self.evidence_prerequisites.documents}
        if any(row.identity.institution_id != self.target.institution_id for row in docs.values()):
            raise ValueError("policy document institution mismatch")
        aliases = self.profile_target_aliases
        if (
            self.target.organization_id not in aliases.graduate_school_or_college
            or self.target.program_id not in aliases.department_or_program
            or self.target.selection_route_id not in aliases.application_route
        ):
            raise ValueError("canonical target aliases are required")
        seen = {}
        for rule in rules:
            for record in rule.required_context_records:
                keys = []
                for binding in record.required_bindings:
                    document = docs.get(binding.document_id)
                    if (
                        document is None
                        or document.kb_sha256 != binding.source_kb_sha256
                        or document.identity.source_pdf_sha256 != binding.source_pdf_sha256
                        or not binding.fact_id.startswith(
                            f"fact:reviewed:{binding.document_id}:{record.record_id}:r{record.record_revision}:"
                        )
                    ):
                        raise ValueError("context binding does not match reviewed document/record")
                    keys.append((binding.document_id, binding.fact_id))
                if len(keys) != len(set(keys)):
                    raise ValueError("duplicate context binding")
                prior = seen.setdefault(record.record_id, (record.record_revision, tuple(keys)))
                if prior != (record.record_revision, tuple(keys)):
                    raise ValueError("inconsistent context record across rules")
        return self


class EmploymentFacts(ClosedModel):
    currently_employed_in_organization: StrictBool | None = None
    retain_employment_at_enrollment: StrictBool | None = None


class MaterialConditionRequest(ClosedModel):
    schema_version: Literal["1.0"]
    target: Target
    applicant_profile: ApplicantProfile
    employment: EmploymentFacts | None = None

    @field_validator("applicant_profile", mode="before")
    @classmethod
    def original_profile_only(cls, value):
        if not isinstance(value, dict):
            raise ValueError("applicant_profile must be a versioned profile object")
        return value

    @model_validator(mode="after")
    def normalize_employment(self):
        if self.employment is None:
            object.__setattr__(self, "employment", EmploymentFacts())
        return self


class ConditionOutcome(ClosedModel):
    field_path: Literal[
        "employment.currently_employed_in_organization",
        "employment.retain_employment_at_enrollment",
    ]
    operator: Literal["equals", "not_equals"]
    status: Literal["matched", "not_matched", "needs_information"]


class ConditionEntry(ClosedModel):
    condition_rule_id: Identifier
    topic_id: Identifier
    material_code: Identifier
    condition_status: Literal["matched", "not_matched", "needs_information"]
    predicate_outcomes: tuple[ConditionOutcome, ...]
    missing_fields: tuple[str, ...]


class MaterialConditionPreview(ClosedModel):
    schema_version: Literal["1.0"]
    artifact_role: Literal["material-condition-preview"]
    production_enabled: Literal[False]
    authority: Literal["condition_only"]
    policy_id: Identifier
    revision: Annotated[int, Field(strict=True, gt=0)]
    policy_sha256: Digest
    request_sha256: Digest
    target: Target
    status: Literal["evaluated", "not_covered", "target_mismatch"]
    conflict_fields: tuple[str, ...]
    entries: tuple[ConditionEntry, ...]

    @field_validator("production_enabled", mode="before")
    @classmethod
    def require_false(cls, value):
        if value is not False:
            raise ValueError("preview cannot be production enabled")
        return value


def load_policy(raw: bytes, trust: PolicyTrust) -> MaterialConditionPolicy:
    if sha256(raw).hexdigest() != trust.policy_sha256:
        raise MaterialConditionError("policy pin mismatch")
    try:
        policy = MaterialConditionPolicy.model_validate(parse_json(raw))
        if (policy.policy_id, policy.revision) != (trust.policy_id, trust.revision):
            raise ValueError("policy identity mismatch")
        return policy
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise MaterialConditionError("invalid material condition policy") from exc


def load_request(raw: bytes) -> MaterialConditionRequest:
    try:
        return MaterialConditionRequest.model_validate(parse_json(raw))
    except (ValidationError, ValueError, TypeError) as exc:
        raise MaterialConditionError("invalid material condition request") from exc


def canonical_request_bytes(request: MaterialConditionRequest) -> bytes:
    return canonical_json_bytes(
        MaterialConditionRequest.model_validate(request.model_dump(mode="json")).model_dump(
            mode="json"
        )
    )


def _profile_conflicts(
    request: MaterialConditionRequest, policy: MaterialConditionPolicy
) -> tuple[str, ...]:
    profile = request.applicant_profile.target_application
    target = policy.target
    aliases = policy.profile_target_aliases
    degree_map = {
        "master": "master",
        "doctoral": "doctorate",
        "professional_degree": "professional",
    }
    checks = {
        "requested_degree_level": profile.requested_degree_level is not None
        and profile.requested_degree_level.value != degree_map.get(target.degree_level),
        "intake_year": profile.intake_year is not None
        and profile.intake_year != target.intake.year,
        "intake_month": profile.intake_month is not None
        and profile.intake_month.value != target.intake.month,
        "graduate_school_or_college": profile.graduate_school_or_college is not None
        and profile.graduate_school_or_college not in aliases.graduate_school_or_college,
        "department_or_program": profile.department_or_program is not None
        and profile.department_or_program not in aliases.department_or_program,
        "application_route": profile.application_route is not None
        and profile.application_route not in aliases.application_route,
    }
    return tuple(sorted(key for key, mismatch in checks.items() if mismatch))


def evaluate(
    policy: MaterialConditionPolicy, request: MaterialConditionRequest, policy_sha256: str
) -> MaterialConditionPreview:
    policy = MaterialConditionPolicy.model_validate(policy.model_dump(mode="json"))
    request = MaterialConditionRequest.model_validate(request.model_dump(mode="json"))
    if len(policy_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in policy_sha256):
        raise MaterialConditionError("invalid policy digest")
    base = dict(
        schema_version="1.0",
        artifact_role="material-condition-preview",
        production_enabled=False,
        authority="condition_only",
        policy_id=policy.policy_id,
        revision=policy.revision,
        policy_sha256=policy_sha256,
        request_sha256=sha256(canonical_request_bytes(request)).hexdigest(),
        target=request.target,
    )
    if request.target != policy.target:
        return MaterialConditionPreview(
            **base, status="not_covered", conflict_fields=(), entries=()
        )
    conflicts = _profile_conflicts(request, policy)
    if conflicts:
        return MaterialConditionPreview(
            **base, status="target_mismatch", conflict_fields=conflicts, entries=()
        )
    entries = []
    for rule in policy.rules:
        outcomes = []
        values = []
        missing = []
        for predicate in rule.predicates:
            field = predicate.field_path.removeprefix("employment.")
            value = getattr(request.employment, field)
            result = (
                None
                if value is None
                else compare(value, predicate.operator, predicate.expected_value)
            )
            values.append(result)
            status = (
                "needs_information" if result is None else ("matched" if result else "not_matched")
            )
            outcomes.append(
                ConditionOutcome(
                    field_path=predicate.field_path, operator=predicate.operator, status=status
                )
            )
            if result is None:
                missing.append(predicate.field_path)
        combined = combine(rule.mode, values)
        entries.append(
            ConditionEntry(
                condition_rule_id=rule.condition_rule_id,
                topic_id=rule.topic_id,
                material_code=rule.material_code,
                condition_status="needs_information"
                if combined is None
                else "matched"
                if combined
                else "not_matched",
                predicate_outcomes=tuple(outcomes),
                missing_fields=tuple(dict.fromkeys(missing)),
            )
        )
    return MaterialConditionPreview(
        **base, status="evaluated", conflict_fields=(), entries=tuple(entries)
    )


def load_preview(
    raw: bytes, *, policy_raw: bytes, trust: PolicyTrust, request_raw: bytes
) -> MaterialConditionPreview:
    """Reject self-reported results by reloading the externally pinned policy and request."""
    try:
        supplied = MaterialConditionPreview.model_validate(parse_json(raw))
        policy = load_policy(policy_raw, trust)
        request = load_request(request_raw)
        expected = evaluate(policy, request, trust.policy_sha256)
        if canonical_json_bytes(supplied.model_dump(mode="json")) != canonical_json_bytes(
            expected.model_dump(mode="json")
        ):
            raise ValueError("preview differs from recomputed condition")
        return supplied
    except (ValidationError, ValueError, TypeError) as exc:
        raise MaterialConditionError("invalid or unbound condition preview") from exc


def load_policy_files(policy_path: Path, trust_path: Path) -> tuple[MaterialConditionPolicy, str]:
    try:
        if any(path.is_symlink() or not path.is_file() for path in (policy_path, trust_path)):
            raise OSError
        trust = PolicyTrust.model_validate(parse_json(trust_path.read_bytes()))
        raw = policy_path.read_bytes()
        return load_policy(raw, trust), sha256(raw).hexdigest()
    except (OSError, ValidationError, ValueError, TypeError) as exc:
        raise MaterialConditionError("policy/trust files unavailable or invalid") from exc
