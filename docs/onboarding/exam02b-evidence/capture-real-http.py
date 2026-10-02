"""Bounded EXAM-02B read-only product verification on one local dev service.

Usage: python capture-real-http.py http://127.0.0.1:8010
The existing system-control April response is reused; at most 35 new base POSTs.
No applicant POST, model call, download, parser or build is performed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / "src/jgrad_admission_rag/demo_config/exam02b_source_bindings.json"
FIRST = HERE / "system-control-base-v2.json"
JOURNAL = HERE / "real-http-journal.json"
SAMPLE_INDEXES = {
    0: "math",
    1: "physics",
    9: "materials",
    10: "applied-chemistry",
    12: "computer-science",
    14: "architecture",
    15: "civil-environment",
    16: "transdisciplinary",
    17: "social-human",
}


def main(base_url: str) -> None:
    departments = json.loads(SOURCE.read_text(encoding="utf-8"))["departments"]
    wanted = {departments[index]["department_id"]: slug for index, slug in SAMPLE_INDEXES.items()}
    prior = json.loads(FIRST.read_text(encoding="utf-8"))
    prior_target = prior["examination_information"]["target_identity"]
    records = []
    april = []
    attempts = 0
    with httpx.Client(base_url=base_url, timeout=45) as client:
        catalog = client.get("/v1/target-catalog").json()
        school = next(row for row in catalog["schools"] if row["school_id"] == "isct")
        for intake in school["degrees"][0]["intakes"]:
            for college in intake["colleges"]:
                for department in college["departments"]:
                    routes = department["application_routes"]
                    request = {
                        "schema_version": "1.0",
                        "school_id": "isct",
                        "document_id": intake["document_id"],
                        "degree_id": "master",
                        "intake": {"year": intake["year"], "month": intake["month"]},
                        "college_id": college["college_id"],
                        "department_id": department["department_id"],
                        "application_route": routes[0]["route_id"] if routes else None,
                    }
                    reused = request == prior_target
                    if reused:
                        body = prior
                        status = 200
                    else:
                        attempts += 1
                        response = client.post(
                            "/v1/base-requirements?include_examination_information=true"
                            "&exam_presentation_version=2",
                            json=request,
                        )
                        status = response.status_code
                        body = response.json()
                    exam = body.get("examination_information", {})
                    written = next(
                        (
                            row["written"]
                            for row in exam.get("pathways", [])
                            if row["source_route"] == "b_schedule"
                        ),
                        {},
                    )
                    record = {
                        "department_id": request["department_id"],
                        "intake": request["intake"],
                        "route": request["application_route"],
                        "http_status": status,
                        "reused_saved_response": reused,
                        "examination_status": exam.get("status"),
                        "written_status": written.get("status"),
                        "subject_components": len(written.get("subjects_zh", [])),
                        "field_bindings": len(exam.get("field_bindings", [])),
                        "evidence_facts": len(exam.get("evidence", [])),
                    }
                    if request["department_id"] in {
                        departments[1]["department_id"],
                        departments[15]["department_id"],
                    }:
                        record["english_cards"] = [
                            {
                                "title": row["title"],
                                "summary": row["reviewed_summary"],
                                "official_status": row["official_status"],
                            }
                            for row in body.get("requirements", [])
                            if row["category"] == "language"
                        ]
                    records.append(record)
                    JOURNAL.write_text(
                        json.dumps(
                            {"new_post_attempts": attempts, "records": records},
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    if status != 200 or exam.get("status") != "available_official_paths":
                        raise RuntimeError(f"product response failed: {record}")
                    if intake["year"] == 2027:
                        april.append(body)
                        slug = wanted.get(request["department_id"])
                        if slug:
                            (HERE / f"{slug}-base-v2.json").write_text(
                                json.dumps(body, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8",
                            )
    assert len(records) == 36 and len(april) == 18 and attempts == 35
    result = subprocess.run(
        ["node", str(HERE / "make-report-samples.mjs")],
        input=json.dumps(april, ensure_ascii=False),
        text=True,
        cwd=ROOT,
        capture_output=True,
        check=True,
        encoding="utf-8",
    )
    print(f"36 real target responses; {attempts} new POSTs + 1 saved response")
    print(result.stdout.strip())


if __name__ == "__main__":
    main(sys.argv[1])
