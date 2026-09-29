"""Additive closed HTTP presentation contracts for reviewed reference slices."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..reasoning.material_slice_report import ReviewedMaterialSliceReport
from ..reviewed_source_evidence import Digest, Identifier, Target
from .demo_requirements import DemoSchool


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReferenceCapabilities(_Closed):
    applicant_check: bool
    evidence_browse: bool
    reference_report: bool


class ReferenceProfileTarget(_Closed):
    graduate_school_or_college: str
    department_or_program: str
    application_route: str


class ReferenceTargetItem(_Closed):
    entry_id: Identifier
    kind: Literal["legacy_applicant", "reviewed_material_slice"]
    institution_name: str
    availability: Literal["ready", "unavailable"]
    capabilities: ReferenceCapabilities
    organization_name: str | None = None
    program_name: str | None = None
    program_display_name: str | None = None
    program_alias: str | None = None
    href: Literal["/app"] | None = None
    legacy_catalog: DemoSchool | None = None
    legacy_edition_labels: dict[str, str] = Field(default_factory=dict)
    target: Target | None = None
    request_profile_target: ReferenceProfileTarget | None = None
    snapshot_id: Digest | None = None
    revision: int | None = None
    limitations_zh: tuple[str, ...] = ()
    reason_code: Literal["reference_configuration_invalid"] | None = None


class ReferenceTargetsResponse(_Closed):
    schema_version: Literal["1.0"]
    items: tuple[ReferenceTargetItem, ...]


class ReferenceFragment(_Closed):
    fragment_id: Identifier
    fragment_role: str
    quote_text: str
    authoritative_fact_text_sha256: Digest
    fact_id: str


class ReferenceRecord(_Closed):
    record_id: Identifier
    role: Literal["basis", "context"]
    stage: Literal["application", "enrollment_context_only"]
    scope_note_zh: str
    official_heading_path: tuple[str, ...]
    manual_anchor: str
    physical_page: int = Field(gt=0)
    printed_page_label: str | None
    source_id: Identifier
    source_title: str
    official_source_url: str = Field(pattern=r"^https://")
    fragments: tuple[ReferenceFragment, ...] = Field(min_length=1)


class ReferenceRelation(_Closed):
    from_id: Identifier = Field(alias="from")
    kind: Identifier
    to: Identifier


class ReferenceTopic(_Closed):
    topic_id: Identifier
    material_name_zh: str
    context_note_zh: str
    records: tuple[ReferenceRecord, ...] = Field(min_length=1)
    relations: tuple[ReferenceRelation, ...] = ()

    @model_validator(mode="after")
    def visible_relations(self):
        ids = {record.record_id for record in self.records}
        if any(row.from_id not in ids or row.to not in ids for row in self.relations):
            raise ValueError("display relation outside visible topic records")
        return self


class ReferenceEvidenceResponse(_Closed):
    schema_version: Literal["1.0"]
    snapshot_id: Digest
    target: Target
    plan_id: Identifier
    revision: int = Field(gt=0)
    limitations_zh: tuple[str, ...]
    topics: tuple[ReferenceTopic, ...] = Field(min_length=1)


class ReferenceReportResponse(_Closed):
    schema_version: Literal["1.0"]
    slice_id: Identifier
    snapshot_id: Digest
    report: ReviewedMaterialSliceReport
    markdown: str
