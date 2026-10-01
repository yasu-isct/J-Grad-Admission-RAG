"""Read-only, fail-closed projection of the reviewed B-schedule source map."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..corpus import audit_corpus_manifest, resolve_registered_corpus_kb_path
from ..schemas.corpus_manifest import load_corpus_manifest
from ..schemas.document_kb import load_document_kb


class ExamPresentationError(ValueError):
    pass


_REVIEWED_CONFIG_SHA256 = "368ed4de43dd2dde8eda986d2ad2d6922e8cfb7c3640583381b1b559a4170aa7"


@dataclass(frozen=True)
class ReviewedExamPresentation:
    data: dict[str, Any]
    sha256: str
    facts: dict[str, Any]


def load_exam_presentation(
    path: Path, corpus_root: Path, manifest_path: Path
) -> ReviewedExamPresentation:
    """Validate one server-owned review record against the registered, audited KB."""
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("unsafe presentation path")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != _REVIEWED_CONFIG_SHA256:
            raise ValueError("presentation differs from reviewed source map")
        data = json.loads(raw)
        if data["schema_version"] != "1.0" or data["presentation_id"] != "isct-cs-b-exams-2026-v1":
            raise ValueError("unknown presentation")
        identity = data["source_identity"]
        scope = data["target_scope"]
        if (identity["institution_id"], identity["document_id"]) != (
            "isct",
            "isct_2027_4_2026_9_master",
        ):
            raise ValueError("source identity mismatch")
        if (
            scope["school_id"],
            scope["document_id"],
            scope["college_id"],
            scope["department_id"],
            scope["degree_id"],
            scope["application_route"],
        ) != (
            "isct",
            identity["document_id"],
            "情報理工学院",
            "情報工学系",
            "master",
            "b_schedule",
        ):
            raise ValueError("target scope mismatch")
        if scope["intakes"] != [{"year": 2026, "month": 9}, {"year": 2027, "month": 4}]:
            raise ValueError("intake scope mismatch")
        audited = audit_corpus_manifest(load_corpus_manifest(manifest_path), corpus_root)
        matches = [
            entry
            for entry in audited.entries
            if entry.identity.document_id == identity["document_id"]
        ]
        if len(matches) != 1:
            raise ValueError("ambiguous source")
        entry = matches[0]
        if (
            entry.identity.institution_id != identity["institution_id"]
            or entry.identity.source_pdf_sha256 != identity["source_pdf_sha256"]
            or entry.source_kb_sha256 != identity["source_kb_sha256"]
        ):
            raise ValueError("source hash mismatch")
        kb = load_document_kb(resolve_registered_corpus_kb_path(corpus_root, entry.kb_path))
        facts = {fact.fact_id: fact for fact in kb.facts}
        if len(facts) != len(kb.facts):
            raise ValueError("duplicate Fact")
        records = data["source_records"]
        ids = [record["source_id"] for record in records]
        if len(ids) != len(set(ids)) or set(ids) != {
            "pdf:cover:1",
            "fact:00002",
            "fact:00004",
            "fact:00287",
            "fact:00288",
            "fact:00289",
        }:
            raise ValueError("source record set mismatch")
        for record in records:
            if record["kind"] == "pdf_page":
                if (
                    record["source_id"] != "pdf:cover:1"
                    or record["physical_page"] != 1
                    or record["fact_id"] is not None
                    or record["role"] != "year_context_only"
                ):
                    raise ValueError("cover binding mismatch")
                continue
            fact = facts[record["source_id"]]
            if (
                record["source_pages"] != fact.source_pages
                or record["fact_type"] != fact.fact_type
                or record["scope_type"] != fact.scope_type
                or record["scope_targets"] != fact.scope_targets
                or record["parent_college"] != fact.parent_college
                or record["fact_text_sha256"]
                != hashlib.sha256(fact.text.encode("utf-8")).hexdigest()
            ):
                raise ValueError("Fact binding mismatch")
            if (record["role"] == "department_basis") != (
                record["source_id"] in {"fact:00287", "fact:00288", "fact:00289"}
            ):
                raise ValueError("source authority mismatch")
        bindings = data["field_bindings"]
        fields = [field for binding in bindings for field in binding["fields"]]
        expected = {
            "written_date",
            "written_start_time",
            "written_end_time",
            "duration_minutes",
            "subject_groups.A",
            "subject_groups.B",
            "subject_groups.C",
            "questions_per_group",
            "total_questions",
            "answer_language",
            "specialist_points",
            "english_points",
            "english_assessment",
            "oral_date",
            "oral_selection_note_zh",
            "oral_announcement_date",
            "oral_announcement_time",
            "oral_announcement_time_qualifier",
            "english_submission_link",
        }
        if len(fields) != len(set(fields)) or set(fields) != expected:
            raise ValueError("field binding mismatch")
        for binding in bindings:
            fact = facts[binding["source_id"]]
            if (
                binding["source_id"] not in {"fact:00287", "fact:00288", "fact:00289"}
                or binding["physical_page"] != 52
                or fact.source_pages != [52]
            ):
                raise ValueError("field source mismatch")
            for anchor in binding["anchors"]:
                if fact.text[anchor["start"] : anchor["end"]] != anchor["exact_text"]:
                    raise ValueError("source quotation mismatch")
        schedule = data["schedule"]
        if (
            schedule["route"],
            schedule["exam_year"],
            schedule["timezone"],
            schedule["written_date"],
            schedule["written_start_time"],
            schedule["written_end_time"],
            schedule["duration_minutes"],
            schedule["questions_per_group"],
            schedule["total_questions"],
            schedule["answer_language"],
            schedule["specialist_points"],
            schedule["english_points"],
            schedule["english_assessment"],
            schedule["oral_date"],
            schedule["oral_announcement_date"],
            schedule["oral_announcement_time"],
            schedule["oral_announcement_time_qualifier"],
        ) != (
            "b_schedule",
            2026,
            "Asia/Tokyo",
            "2026-08-18",
            "09:30",
            "12:00",
            150,
            1,
            3,
            "ja",
            900,
            100,
            "external_score",
            "2026-08-24",
            "2026-08-20",
            "17:00",
            "around_from",
        ):
            raise ValueError("schedule differs from review")
        if [group["group"] for group in schedule["subject_groups"]] != ["A", "B", "C"] or schedule[
            "subject_groups"
        ] != [
            {"group": "A", "subjects_zh": ["微积分", "线性代数", "概率统计"]},
            {"group": "B", "subjects_zh": ["数理逻辑", "自动机与形式语言"]},
            {"group": "C", "subjects_zh": ["数据结构与算法", "编程"]},
        ]:
            raise ValueError("subject groups differ from review")
        year = data["year_basis"]
        if (
            year["kind"] != "reviewed_cross_page_context"
            or year["exam_year"] != 2026
            or year["physical_pages"] != [1, 2, 52]
            or year["source_ids"] != ["pdf:cover:1", "fact:00002", "fact:00004", "fact:00288"]
        ):
            raise ValueError("year context mismatch")
        return ReviewedExamPresentation(data, hashlib.sha256(raw).hexdigest(), facts)
    except (OSError, KeyError, IndexError, TypeError, ValueError) as error:
        raise ExamPresentationError("reviewed examination presentation is unavailable") from error


def applies_to(data: dict[str, Any], target: Any) -> bool:
    scope = data["target_scope"]
    return (
        all(
            getattr(target, key) == scope[key]
            for key in (
                "school_id",
                "document_id",
                "college_id",
                "department_id",
                "degree_id",
                "application_route",
            )
        )
        and target.intake.model_dump() in scope["intakes"]
    )


def is_reviewed_target(target: Any) -> bool:
    return (
        target.school_id,
        target.document_id,
        target.college_id,
        target.department_id,
        target.degree_id.value,
        target.application_route,
        target.intake.year,
        target.intake.month,
    ) in {
        (
            "isct",
            "isct_2027_4_2026_9_master",
            "情報理工学院",
            "情報工学系",
            "master",
            "b_schedule",
            2026,
            9,
        ),
        (
            "isct",
            "isct_2027_4_2026_9_master",
            "情報理工学院",
            "情報工学系",
            "master",
            "b_schedule",
            2027,
            4,
        ),
    }


def exam_response(
    target: Any,
    presentation: ReviewedExamPresentation | None,
    failed: bool,
    plan: Any,
    source_document: Any,
) -> dict[str, Any]:
    from .demo_requirements import DemoEvidence

    target_identity = target.model_dump(mode="json")
    if not is_reviewed_target(target):
        return {
            "schema_version": "1.0",
            "status": "not_covered",
            "target_identity": target_identity,
            "message_zh": "本项目尚未整理考试安排。",
            "schedule": None,
            "evidence": [],
        }
    if presentation is None or failed or not applies_to(presentation.data, target):
        return {
            "schema_version": "1.0",
            "status": "unavailable" if failed else "not_covered",
            "target_identity": target_identity,
            "message_zh": "考试资料暂不可用，请查看官方募集要项。"
            if failed
            else "本项目尚未整理考试安排。",
            "schedule": None,
            "evidence": [],
        }
    data = presentation.data
    source = data["source_identity"]
    identity = plan.document_identity
    if (
        identity.institution_id != source["institution_id"]
        or identity.document_id != source["document_id"]
        or identity.source_pdf_sha256 != source["source_pdf_sha256"]
    ):
        return exam_response(target, None, True, plan, source_document)
    local_pdf_url = (
        f"/documents/{identity.document_id}/source.pdf"
        if source_document is not None
        and source_document.document_id == identity.document_id
        and source_document.source_pdf_sha256 == source["source_pdf_sha256"]
        else None
    )
    evidence = []
    for fact_id in ("fact:00288", "fact:00289", "fact:00287"):
        fact = presentation.facts[fact_id]
        evidence.append(
            DemoEvidence(
                document_id=identity.document_id,
                official_title=identity.official_title,
                school_name="東京科学大学",
                intake_name=f"{target.intake.year}年{target.intake.month}月入学",
                fact_id=fact.fact_id,
                pages=tuple(fact.source_pages),
                official_text=fact.text,
                source_url=identity.official_source_url,
                scope_type=fact.scope_type,
                scope_targets=tuple(fact.scope_targets),
                parent_college=fact.parent_college,
                limitation="考试安排按本册已审核原文整理；考试与出愿状态请以学校公告为准。",
                local_pdf_url=local_pdf_url,
            ).model_dump(mode="json")
        )
    return {
        "schema_version": "1.0",
        "status": "available",
        "target_identity": target_identity,
        "message_zh": "已整理本册信息工学系 B 日程考试安排。",
        "presentation_id": data["presentation_id"],
        "presentation_sha256": presentation.sha256,
        "source_identity": source,
        "schedule": data["schedule"],
        "evidence": evidence,
        "year_basis": data["year_basis"],
    }
