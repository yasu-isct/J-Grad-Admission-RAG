"""Server-owned, frozen reviewed slices for optional local reference browsing."""

from __future__ import annotations

import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..reasoning.material_slice_report import (
    MaterialSlicePlan,
    ReviewedMaterialSliceEvidence,
    assemble_report,
    load_plan,
    read_candidate_files,
    read_pdf_bytes,
    verify_evidence_bytes,
    _render_markdown,
)
from ..reviewed_source_evidence import Identifier, canonical_json_bytes, parse_json
from .reference_contracts import ReferenceEvidenceResponse, ReferenceReportResponse


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReferenceSliceConfig(_Closed):
    slice_id: Identifier
    institution_name: str = Field(min_length=1, max_length=120)
    organization_name: str = Field(min_length=1, max_length=120)
    program_name: str = Field(min_length=1, max_length=120)
    plan_path: Path
    trust_path: Path
    policy_path: Path
    policy_trust_path: Path
    seed_path: Path
    candidate_root: Path
    pdf_dir: Path

    @model_validator(mode="after")
    def absolute_paths(self):
        for field in (
            "plan_path",
            "trust_path",
            "policy_path",
            "policy_trust_path",
            "seed_path",
            "candidate_root",
            "pdf_dir",
        ):
            if not getattr(self, field).is_absolute():
                raise ValueError("reference paths must be absolute")
        return self


class ReferenceWorkspaceConfig(_Closed):
    schema_version: Literal["1.0"]
    slices: tuple[ReferenceSliceConfig, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [row.slice_id for row in self.slices]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate reference slice ID")
        return self


def _safe_path(path: Path) -> None:
    current = path.absolute()
    if not path.is_absolute() or current != path or path.resolve(strict=False) != path:
        raise ValueError("reference path must be canonical and absolute")
    while True:
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            raise ValueError("reference path traverses a link")
        if current == current.parent:
            break
        current = current.parent


def _read_metadata(path: Path) -> bytes:
    _safe_path(path)
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_size > 256 * 1024:
        raise ValueError("reference metadata is not a bounded regular file")
    raw = path.read_bytes()
    after = path.stat(follow_symlinks=False)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ValueError("reference metadata changed during read")
    return raw


def _source_size(config: ReferenceSliceConfig, plan: MaterialSlicePlan) -> int:
    _safe_path(config.candidate_root)
    _safe_path(config.pdf_dir)
    paths = [config.candidate_root / row.relative_path for row in plan.candidate_reference.files]
    paths.extend(
        config.pdf_dir / f"{source.identity.source_pdf_sha256}.pdf" for source in plan.sources
    )
    total = 0
    for path in paths:
        _safe_path(path)
        info = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("reference source is not a regular file")
        total += info.st_size
        if total > 64 * 1024 * 1024:
            raise ValueError("reference slice exceeds source size limit")
    return total


def _presentation(
    plan: MaterialSlicePlan, evidence: ReviewedMaterialSliceEvidence, snapshot_id: str
) -> bytes:
    records = {record.record_id: record for record in evidence.records}
    sources = {source.source_id: source for source in evidence.sources}
    topics = []
    for topic in plan.topics:
        entries = []
        for record_id in topic.required_context_record_ids:
            record = records[record_id]
            source = sources[record.source_id]
            entries.append(
                {
                    "record_id": record.record_id,
                    "role": "basis" if record_id in topic.basis_record_ids else "context",
                    "stage": record.stage,
                    "scope_note_zh": record.scope_note_zh,
                    "official_heading_path": record.official_heading_path,
                    "manual_anchor": record.manual_anchor,
                    "physical_page": record.physical_page,
                    "printed_page_label": record.printed_page_label,
                    "source_id": record.source_id,
                    "source_title": source.identity.official_title,
                    "official_source_url": source.identity.official_source_url,
                    "fragments": [
                        {
                            "fragment_id": fact.fragment_id,
                            "fragment_role": fact.fragment_role,
                            "quote_text": fact.text,
                            "authoritative_fact_text_sha256": fact.binding.authoritative_fact_text_sha256,
                            "fact_id": fact.binding.fact_id,
                        }
                        for fact in record.facts
                    ],
                }
            )
        topics.append(
            {
                "topic_id": topic.topic_id,
                "material_name_zh": topic.material_name_zh,
                "context_note_zh": topic.context_note_zh,
                "records": entries,
                "relations": [
                    relation.model_dump(mode="json", by_alias=True)
                    for relation in evidence.relations
                    if relation.from_id in topic.required_context_record_ids
                    and relation.to in topic.required_context_record_ids
                ],
            }
        )
    response = ReferenceEvidenceResponse.model_validate(
        {
            "schema_version": "1.0",
            "snapshot_id": snapshot_id,
            "target": plan.target.model_dump(mode="json"),
            "plan_id": plan.plan_id,
            "revision": plan.revision,
            "limitations_zh": plan.limitations_zh,
            "topics": topics,
        }
    )
    return canonical_json_bytes(response.model_dump(mode="json", by_alias=True))


@dataclass(frozen=True, slots=True)
class ReferenceSliceSnapshot:
    config: ReferenceSliceConfig
    plan: MaterialSlicePlan
    snapshot_id: str
    profile_aliases: Mapping[str, str]
    plan_raw: bytes
    trust_raw: bytes
    policy_raw: bytes
    policy_trust_raw: bytes
    seed_raw: bytes
    candidate_files: Mapping[str, bytes]
    pdf_bytes: Mapping[str, bytes]
    presentation: bytes

    def report(self, request_raw: bytes) -> dict:
        report = assemble_report(
            plan_raw=self.plan_raw,
            trust_raw=self.trust_raw,
            policy_raw=self.policy_raw,
            policy_trust_raw=self.policy_trust_raw,
            seed_raw=self.seed_raw,
            request_raw=request_raw,
            candidate_files=self.candidate_files,
            pdf_bytes=self.pdf_bytes,
        )
        markdown = _render_markdown(report)
        return ReferenceReportResponse.model_validate(
            {
                "schema_version": "1.0",
                "slice_id": self.config.slice_id,
                "snapshot_id": self.snapshot_id,
                "report": report.model_dump(mode="json"),
                "markdown": markdown,
            }
        ).model_dump(mode="json")


def load_reference_workspace(path: Path) -> tuple[ReferenceSliceSnapshot, ...]:
    config = ReferenceWorkspaceConfig.model_validate(parse_json(_read_metadata(path)))
    snapshots = []
    targets = set()
    plan_ids = set()
    total_bytes = 0
    for row in config.slices:
        raws = tuple(
            _read_metadata(getattr(row, field))
            for field in (
                "plan_path",
                "trust_path",
                "policy_path",
                "policy_trust_path",
                "seed_path",
            )
        )
        plan, policy, seed, plan_sha, policy_sha = load_plan(*raws)
        target_key = canonical_json_bytes(plan.target.model_dump(mode="json"))
        if target_key in targets or plan.plan_id in plan_ids:
            raise ValueError("duplicate reference plan and target")
        targets.add(target_key)
        plan_ids.add(plan.plan_id)
        total_bytes += _source_size(row, plan)
        if total_bytes > 128 * 1024 * 1024:
            raise ValueError("reference workspace exceeds source size limit")
        candidate_files = read_candidate_files(row.candidate_root, plan)
        pdf_bytes = read_pdf_bytes(row.pdf_dir, plan)
        evidence = verify_evidence_bytes(
            plan,
            policy,
            seed,
            plan_sha256=plan_sha,
            policy_sha256=policy_sha,
            candidate_files=candidate_files,
            pdf_bytes=pdf_bytes,
        )
        bindings = {
            "plan": sha256(raws[0]).hexdigest(),
            "policy": sha256(raws[2]).hexdigest(),
            "seed": sha256(raws[4]).hexdigest(),
            "candidate": {
                name: sha256(raw).hexdigest() for name, raw in sorted(candidate_files.items())
            },
            "pdf": {name: sha256(raw).hexdigest() for name, raw in sorted(pdf_bytes.items())},
        }
        snapshot_id = sha256(canonical_json_bytes(bindings)).hexdigest()
        snapshots.append(
            ReferenceSliceSnapshot(
                config=row,
                plan=plan,
                snapshot_id=snapshot_id,
                profile_aliases=MappingProxyType(
                    {
                        "graduate_school_or_college": policy.profile_target_aliases.graduate_school_or_college[
                            0
                        ],
                        "department_or_program": policy.profile_target_aliases.department_or_program[
                            0
                        ],
                        "application_route": policy.profile_target_aliases.application_route[0],
                    }
                ),
                plan_raw=raws[0],
                trust_raw=raws[1],
                policy_raw=raws[2],
                policy_trust_raw=raws[3],
                seed_raw=raws[4],
                candidate_files=MappingProxyType(candidate_files),
                pdf_bytes=MappingProxyType(pdf_bytes),
                presentation=_presentation(plan, evidence, snapshot_id),
            )
        )
    return tuple(snapshots)
