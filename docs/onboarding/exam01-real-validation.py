"""One bounded read-only EXAM-01 session against the already registered 391 runtime."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from jgrad_admission_rag.service import ServiceSettings, create_app


ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = Path("D:/J-Grad-Admission-RAG")
RUNTIME = ASSET_ROOT / "outputs/m10-09-deepseek-live/runtime-v1"
PDF = ASSET_ROOT / "outputs/real_pdf/isct_2027_4_2026_9_master.pdf"
KB = RUNTIME / "documents/isct_2027_4_2026_9_master/document_kb.json"
OUT = ROOT / "outputs/exam01-evidence"
DOCUMENT = "isct_2027_4_2026_9_master"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def target(
    year: int,
    month: int,
    *,
    college: str = "情報理工学院",
    department: str = "情報工学系",
    route: str | None = "b_schedule",
) -> dict:
    return {
        "schema_version": "1.0",
        "school_id": "isct",
        "document_id": DOCUMENT,
        "degree_id": "master",
        "intake": {"year": year, "month": month},
        "college_id": college,
        "department_id": department,
        "application_route": route,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "journal.json").exists():
        raise RuntimeError("EXAM-01 product session has already been recorded")
    before = {"pdf": sha(PDF), "kb": sha(KB)}
    assert before == {
        "pdf": "57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735",
        "kb": "7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce",
    }
    settings = ServiceSettings(
        corpus_root=RUNTIME,
        manifest_path=RUNTIME / "corpus.json",
        policy_path=RUNTIME / "policy.json",
        report_plan_paths=(RUNTIME / "config/reviewed_report_plan.json",),
        page_scope_manifest_paths=(RUNTIME / "config/page_scope_manifest.json",),
        date_presentation_paths=(RUNTIME / "config/reviewed_date_presentation.json",),
        exam_presentation_paths=(
            ROOT / "src/jgrad_admission_rag/demo_config/reviewed_exam_presentation.json",
        ),
        source_pdf_path=PDF,
        source_pdf_document_id=DOCUMENT,
        source_pdf_sha256=before["pdf"],
    )
    requests = [
        ("cs_april", target(2027, 4), True),
        ("cs_september", target(2026, 9), True),
        (
            "non_cs",
            target(2027, 4, college="工学院", department="システム制御系", route=None),
            True,
        ),
        ("legacy", target(2027, 4), False),
    ]
    journal = {
        "real_product_sessions": 1,
        "base_or_applicant_posts": 0,
        "paid_calls": 0,
        "downloads": 0,
        "parser_or_index_builds": 0,
        "before": before,
        "results": {},
    }
    try:
        with TestClient(create_app(settings)) as client:
            for name, body, include_exam in requests:
                endpoint = "/v1/base-requirements"
                if include_exam:
                    endpoint += "?include_examination_information=true"
                journal["base_or_applicant_posts"] += 1
                response = client.post(endpoint, json=body)
                payload = response.json()
                (OUT / f"{name}.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                journal["results"][name] = {
                    "status_code": response.status_code,
                    "exam_status": payload.get("examination_information", {}).get("status"),
                }
    finally:
        journal["after"] = {"pdf": sha(PDF), "kb": sha(KB)}
        (OUT / "journal.json").write_text(
            json.dumps(journal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    assert journal["before"] == journal["after"]
    assert journal["base_or_applicant_posts"] == 4
    assert [journal["results"][name]["status_code"] for name, _, _ in requests] == [200] * 4
    assert [journal["results"][name]["exam_status"] for name, _, _ in requests] == [
        "available",
        "available",
        "not_covered",
        None,
    ]
    april = json.loads((OUT / "cs_april.json").read_text(encoding="utf-8"))
    september = json.loads((OUT / "cs_september.json").read_text(encoding="utf-8"))
    legacy = json.loads((OUT / "legacy.json").read_text(encoding="utf-8"))
    assert (
        april["examination_information"]["schedule"]
        == september["examination_information"]["schedule"]
    )
    assert april["examination_information"]["schedule"]["exam_year"] == 2026
    assert {k: v for k, v in april.items() if k != "examination_information"} == legacy
    print(json.dumps(journal, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
