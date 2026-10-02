"""Fail-closed, read-only projection of the EXAM-02A field bindings.

This is an explicit v2 opt-in. The accepted information-engineering B-schedule
1.0 response remains in exam_presentation.py without changing its fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..corpus import audit_corpus_manifest, resolve_registered_corpus_kb_path
from ..schemas.corpus_manifest import load_corpus_manifest
from ..schemas.document_kb import load_document_kb
from .demo_requirements import DemoEvidence
from .exam_presentation import ExamPresentationError, ReviewedExamPresentation


SOURCE_SHA256 = "c724d2e228a128fff1cc863aca68e72cd10ee02bbe4c4ce67c835f7e2d632ef3"
PRESENTATION_ID = "isct-18-departments-exams-2026-v2"
DOCUMENT_ID = "isct_2027_4_2026_9_master"
INTAKES = [{"year": 2026, "month": 9}, {"year": 2027, "month": 4}]
FIELD_PATHS = {
    "exam.year",
    "a.oral",
    "b.written_status",
    "b.written_sessions",
    "b.subjects",
    "b.selection_rule",
    "b.points",
    "english.submission",
    "b.oral",
    "b.answer_language",
}
COURSES = {
    "地球惑星科学系": ("地球惑星科学コース",),
    "応用化学系": (
        "応用化学コース",
        "原子核工学コース",
        "人間医療科学技術コース",
        "エネルギー・情報コース",
    ),
    "生命理工学系": ("生命理工学コース", "人間医療科学技術コース"),
}
EXCLUDED_COURSE = "地球生命コース"


def load_exam_presentation_v2(
    path: Path, corpus_root: Path, manifest_path: Path, source_pdf_path: Path
) -> ReviewedExamPresentation:
    """Load one packaged map only if its registered PDF, KB and anchors match."""
    try:
        if path.is_symlink() or not path.is_file() or source_pdf_path.is_symlink():
            raise ValueError("unsafe source path")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
            raise ValueError("field map differs from checked candidate")
        data = json.loads(raw)
        source = data["source_identity"]
        if (
            data["schema_version"] != "candidate-1"
            or source["document_id"] != DOCUMENT_ID
            or hashlib.sha256(source_pdf_path.read_bytes()).hexdigest()
            != source["source_pdf_sha256"]
        ):
            raise ValueError("PDF or source identity mismatch")
        audited = audit_corpus_manifest(load_corpus_manifest(manifest_path), corpus_root)
        matches = [item for item in audited.entries if item.identity.document_id == DOCUMENT_ID]
        if len(matches) != 1:
            raise ValueError("ambiguous registered corpus")
        entry = matches[0]
        if (
            entry.identity.institution_id != "isct"
            or entry.identity.source_pdf_sha256 != source["source_pdf_sha256"]
            or entry.source_kb_sha256 != source["source_kb_sha256"]
        ):
            raise ValueError("registered source mismatch")
        kb = load_document_kb(resolve_registered_corpus_kb_path(corpus_root, entry.kb_path))
        facts = {fact.fact_id: fact for fact in kb.facts}
        if len(facts) != len(kb.facts) or len(facts) != 391:
            raise ValueError("KB Fact count mismatch")
        departments = data["departments"]
        if len(departments) != 18 or len({x["department_id"] for x in departments}) != 18:
            raise ValueError("department map mismatch")
        for item in departments:
            if item["intakes"] != INTAKES or item["catalog_route"] != (
                "b_schedule" if item["department_id"] == "情報工学系" else None
            ):
                raise ValueError("target catalog mismatch")
            fields = {field["field_path"]: field for field in item["fields"]}
            if len(fields) != len(item["fields"]) or not FIELD_PATHS <= fields.keys():
                raise ValueError("missing or duplicate field")
            if item["department_id"] in COURSES and "course.coverage_exclusion" not in fields:
                raise ValueError("missing course exclusion")
            if item["department_id"] == "建築学系" and "b.specialist_condition" not in fields:
                raise ValueError("missing adviser condition")
            for field in fields.values():
                if field["value_zh"] is None:
                    if field["sources"] or not field["missing_reason_zh"]:
                        raise ValueError("unknown field has unsupported source")
                    continue
                if not field["value_zh"] or not field["sources"]:
                    raise ValueError("positive field lacks source")
                for binding in field["sources"]:
                    if not binding["exact_text"] or not binding["table_scope"]:
                        raise ValueError("source anchor incomplete")
                    source_id = binding["source_id"]
                    if source_id.startswith("fact:"):
                        fact = facts[source_id]
                        if (
                            fact.source_pages != binding["physical_pages"]
                            or hashlib.sha256(fact.text.encode("utf-8")).hexdigest()
                            != binding["fact_text_sha256"]
                            or binding["exact_text"] not in fact.text
                        ):
                            raise ValueError("Fact text or page mismatch")
                        if source_id == "fact:00002" and field["field_path"] == "exam.year":
                            if fact.scope_targets:
                                raise ValueError("global year scope mismatch")
                        elif (
                            fact.parent_college != item["college_id"]
                            or item["department_id"] not in fact.scope_targets
                        ):
                            raise ValueError("department Fact scope mismatch")
                    elif not (
                        source_id.startswith("pdf_page:")
                        and binding["manual_pdf_visual_check"]
                        and binding["physical_pages"] == [int(source_id.split(":")[1])]
                    ):
                        raise ValueError("PDF page anchor mismatch")
        return ReviewedExamPresentation(data, hashlib.sha256(raw).hexdigest(), facts)
    except (OSError, KeyError, IndexError, TypeError, ValueError) as error:
        raise ExamPresentationError(
            "reviewed examination v2 presentation is unavailable"
        ) from error


def _plain(value: str | None) -> str | None:
    return value.replace("**", "") if value is not None else None


def _empty(target: Any, status: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "status": status,
        "target_identity": target.model_dump(mode="json"),
        "message_zh": message,
        "pathways": [],
        "evidence": [],
        "field_bindings": [],
    }


def exam_response_v2(
    target: Any,
    presentation: ReviewedExamPresentation | None,
    failed: bool,
    plan: Any,
    source_document: Any,
    course_id: str | None = None,
) -> dict[str, Any]:
    """Project the exact catalog target; source path never assigns personal eligibility."""
    if (
        target.school_id != "isct"
        or target.document_id != DOCUMENT_ID
        or target.degree_id.value != "master"
        or target.intake.model_dump() not in INTAKES
    ):
        return _empty(target, "not_covered", "本项目尚未整理该目标的考试安排。")
    if presentation is None or failed:
        return _empty(target, "unavailable", "考试来源暂不可用，请查看官方募集要项。")
    matches = [
        item
        for item in presentation.data["departments"]
        if item["college_id"] == target.college_id
        and item["department_id"] == target.department_id
        and item["catalog_route"] == target.application_route
    ]
    if len(matches) != 1:
        return _empty(target, "not_covered", "本项目尚未整理该目标的考试安排。")
    item = matches[0]
    source = presentation.data["source_identity"]
    identity = plan.document_identity
    if (
        identity.institution_id != "isct"
        or identity.document_id != source["document_id"]
        or identity.source_pdf_sha256 != source["source_pdf_sha256"]
    ):
        return _empty(target, "unavailable", "官方来源身份不匹配，考试安排暂不可用。")
    covered = COURSES.get(item["department_id"], ())
    excluded = (EXCLUDED_COURSE,) if covered else ()
    if course_id is not None and course_id not in covered:
        message = (
            "地球生命课程采用另册，本项目尚未覆盖该课程考试安排。"
            if course_id == EXCLUDED_COURSE and covered
            else "当前课程不在本册已核对范围，考试安排暂不可用。"
        )
        result = _empty(target, "not_covered_course", message)
        result["applicability"] = {
            "catalog_route": target.application_route,
            "personal_route_state": "catalog_b"
            if target.application_route == "b_schedule"
            else "unconfirmed",
            "course_state": "excluded" if course_id == EXCLUDED_COURSE and covered else "unknown",
            "covered_course_ids": list(covered),
            "excluded_course_ids": list(excluded),
        }
        return result
    fields = {field["field_path"]: field for field in item["fields"]}

    def value(path: str) -> str | None:
        return _plain(fields[path]["value_zh"])

    if value("b.written_status") not in {"held", "not_held"}:
        return _empty(target, "unavailable", "笔试状态无法核对，考试安排暂不可用。")
    local_pdf_url = (
        f"/documents/{DOCUMENT_ID}/source.pdf"
        if source_document is not None
        and source_document.document_id == DOCUMENT_ID
        and source_document.source_pdf_sha256 == source["source_pdf_sha256"]
        else None
    )
    fact_ids = sorted(
        {
            binding["source_id"]
            for field in item["fields"]
            for binding in field["sources"]
            if binding["source_id"].startswith("fact:") and binding["source_id"] != "fact:00002"
        }
    )
    evidence = [
        DemoEvidence(
            document_id=DOCUMENT_ID,
            official_title=identity.official_title,
            school_name="東京科学大学",
            intake_name=f"{target.intake.year}年{target.intake.month}月入学",
            fact_id=fact_id,
            pages=tuple(presentation.facts[fact_id].source_pages),
            official_text=presentation.facts[fact_id].text,
            source_url=identity.official_source_url,
            scope_type=presentation.facts[fact_id].scope_type,
            scope_targets=tuple(presentation.facts[fact_id].scope_targets),
            parent_college=presentation.facts[fact_id].parent_college,
            limitation="仅为本册官方路径的资料整理；本人参加资格和课程适用性须按学校通知核对。",
            local_pdf_url=local_pdf_url,
        ).model_dump(mode="json")
        for fact_id in fact_ids
    ]
    field_bindings = [
        {
            "field_path": field["field_path"],
            "value_zh": field["value_zh"],
            "missing_reason_zh": field.get("missing_reason_zh"),
            "sources": [
                {
                    "source_id": binding["source_id"],
                    "physical_pages": binding["physical_pages"],
                    "exact_text": binding["exact_text"],
                }
                for binding in field["sources"]
            ],
        }
        for field in item["fields"]
    ]
    a_oral = value("a.oral")
    b_oral = value("b.oral")
    written_status = value("b.written_status")
    b_subjects = value("b.subjects")
    pathways = [
        {
            "source_route": "a_schedule",
            "label_zh": "学校公布的 A 日程",
            "personal_eligibility": "unconfirmed",
            "written": {"status": "unknown", "time_zh": None, "subjects_zh": []},
            "oral": {
                "status": "not_held" if "明确不举行" in a_oral else "held",
                "description_zh": a_oral,
            },
        },
        {
            "source_route": "b_schedule",
            "label_zh": "学校公布的 B 日程",
            "personal_eligibility": "catalog_b"
            if target.application_route == "b_schedule"
            else "unconfirmed",
            "written": {
                "status": written_status,
                "time_zh": value("b.written_sessions") if written_status == "held" else None,
                "subjects_zh": [part.strip() for part in b_subjects.split("；") if part.strip()]
                if written_status == "held"
                else [],
                "selection_rule_zh": value("b.selection_rule")
                if written_status == "held"
                else None,
                "points_zh": value("b.points"),
                "answer_language_zh": value("b.answer_language")
                if written_status == "held"
                else None,
                "administration_language_zh": value("exam.administration_language")
                if "exam.administration_language" in fields
                else None,
            },
            "oral": {"status": "held", "description_zh": b_oral},
            "english": {"submission_zh": value("english.submission")},
        },
    ]
    return {
        "schema_version": "2.0",
        "status": "available_official_paths",
        "target_identity": target.model_dump(mode="json"),
        "message_zh": "学校公布的路径可查阅；实际参加路径和资格以学校通知为准。",
        "presentation_id": PRESENTATION_ID,
        "presentation_sha256": presentation.sha256,
        "source_identity": {"institution_id": "isct", **source},
        "year_basis": {
            **presentation.data["year_basis"],
            "department_page": int(item["fields"][0]["sources"][-1]["physical_pages"][0]),
        },
        "applicability": {
            "catalog_route": target.application_route,
            "personal_route_state": "catalog_b"
            if target.application_route == "b_schedule"
            else "unconfirmed",
            "course_state": "covered" if course_id else "unspecified",
            "covered_course_ids": list(covered),
            "excluded_course_ids": list(excluded),
        },
        "pathways": pathways,
        "field_bindings": field_bindings,
        "evidence": evidence,
        "local_pdf_url": local_pdf_url,
        "official_source_url": identity.official_source_url,
        "official_title": identity.official_title,
    }
