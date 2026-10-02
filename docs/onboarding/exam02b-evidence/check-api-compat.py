"""Four bounded real HTTP checks against isolated EXAM-02B service.

Every attempted POST, including an HTTP error, counts toward the task budget.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx


HERE = Path(__file__).resolve().parent
OLD = json.loads(
    (HERE.parent / "exam01-evidence/cs-april-response.json").read_text(encoding="utf-8")
)
NEW = json.loads((HERE / "computer-science-base-v2.json").read_text(encoding="utf-8"))
BASE = "http://127.0.0.1:8010/v1/base-requirements"
TARGET = NEW["examination_information"]["target_identity"]
results = []


def post(label: str, target: dict, params: dict) -> dict:
    response = httpx.post(BASE, params=params, json=target, timeout=120)
    payload = response.json()
    results.append(
        {
            "case": label,
            "http_status": response.status_code,
            "exam_status": payload.get("examination_information", {}).get("status"),
        }
    )
    return payload


def main() -> None:
    try:
        old = post("cs-old-explicit-1.0", TARGET, {"include_examination_information": "true"})
        assert old["examination_information"] == OLD["examination_information"]
        assert old["requirements"] == OLD["requirements"]
        ordinary = post("cs-old-default", TARGET, {})
        assert ordinary.get("examination_information") is None
        assert ordinary["requirements"] == OLD["requirements"]
        earth = json.loads((HERE / "applied-chemistry-base-v2.json").read_text(encoding="utf-8"))
        earth_target = earth["examination_information"]["target_identity"]
        excluded = post(
            "earth-life-excluded",
            earth_target,
            {
                "include_examination_information": "true",
                "exam_presentation_version": "2",
                "course_id": "地球生命コース",
            },
        )
        exam = excluded["examination_information"]
        assert exam["status"] == "not_covered_course"
        assert exam["pathways"] == exam["evidence"] == []
        wrong = dict(TARGET, school_id="gsfs")
        invalid = post(
            "wrong-school-fails-closed",
            wrong,
            {"include_examination_information": "true", "exam_presentation_version": "2"},
        )
        assert (
            invalid.get("examination_information", {}).get("status") != "available_official_paths"
        )
    finally:
        (HERE / "api-compat-journal.json").write_text(
            json.dumps(
                {"attempted_product_posts": len(results), "cases": results},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(f"{len(results)} bounded HTTP compatibility/negative checks passed")


if __name__ == "__main__":
    main()
