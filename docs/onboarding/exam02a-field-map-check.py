"""Check the EXAM-02A candidate's field coverage against existing read-only assets.

Usage: python docs/onboarding/exam02a-field-map-check.py PATH_TO_391_KB PATH_TO_PDF
No PDF, KB, index or runtime asset is changed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
FIELDS = {
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


def main(kb_path: Path, pdf_path: Path) -> None:
    import fitz

    data = json.loads((HERE / "exam02a-field-bindings.json").read_text(encoding="utf-8"))
    kb_bytes = kb_path.read_bytes()
    assert hashlib.sha256(kb_bytes).hexdigest() == data["source_identity"]["source_kb_sha256"]
    assert hashlib.sha256(pdf_path.read_bytes()).hexdigest() == data["source_identity"]["source_pdf_sha256"]
    pdf = fitz.open(pdf_path)
    facts = {fact["fact_id"]: fact for fact in json.loads(kb_bytes)["facts"]}
    assert len(facts) == 391
    departments = data["departments"]
    assert len(departments) == 18
    assert len({item["department_id"] for item in departments}) == 18
    matrix = list(csv.DictReader((HERE / "exam02a-target-matrix.csv").open(encoding="utf-8-sig", newline="")))
    assert len(matrix) == 36
    targets = {(r["department_id"], int(r["intake_year"]), int(r["intake_month"])) for r in matrix}
    assert len(targets) == 36
    anchor_count = 0
    field_count = 0
    for item in departments:
        name = item["department_id"]
        assert {(name, t["year"], t["month"]) for t in item["intakes"]} <= targets
        fields = {f["field_path"]: f for f in item["fields"]}
        assert len(fields) == len(item["fields"])
        assert FIELDS <= fields.keys(), (name, FIELDS - fields.keys())
        matrix_row = next(r for r in matrix if r["department_id"] == name)
        assert fields["b.written_sessions"]["value_zh"].startswith(matrix_row["written_time"])
        assert fields["b.subjects"]["value_zh"] == matrix_row["subjects_and_selection"]
        assert fields["b.points"]["value_zh"] == matrix_row["points_and_english"]
        if matrix_row["written_answer_language"]:
            assert fields["b.answer_language"]["value_zh"] == matrix_row["written_answer_language"]
        else:
            assert fields["b.answer_language"]["value_zh"] is None
        if matrix_row["exam_administration_language"]:
            assert "exam.administration_language" in fields
        if "地球生命" in matrix_row["course_coverage"]:
            assert "course.coverage_exclusion" in fields
        if name == "建築学系":
            assert "b.specialist_condition" in fields
        for field in fields.values():
            if field["value_zh"] is None:
                assert not field["sources"] and field["missing_reason_zh"], (name, field["field_path"])
                field_count += 1
                continue
            assert field["value_zh"] and field["sources"], (name, field["field_path"])
            field_count += 1
            for source in field["sources"]:
                assert source["exact_text"] and source["table_scope"]
                assert source["physical_pages"] and source["printed_pages"]
                if source["source_id"].startswith("fact:"):
                    fact = facts[source["source_id"]]
                    assert fact["source_pages"] == source["physical_pages"]
                    if field["field_path"] == "exam.year" and source["source_id"] == "fact:00002":
                        assert fact["scope_type"] == "unknown" and not fact["scope_targets"]
                    else:
                        assert fact["parent_college"] == item["college_id"]
                        assert name in fact["scope_targets"]
                    assert hashlib.sha256(fact["text"].encode("utf-8")).hexdigest() == source["fact_text_sha256"]
                    assert source["exact_text"] in fact["text"]
                else:
                    assert source["source_id"].startswith("pdf_page:") and source["manual_pdf_visual_check"]
                    page = int(source["source_id"].split(":")[1])
                    assert source["physical_pages"] == [page]
                    # The p.40 right-hand vertical note is visually legible but split
                    # into individual characters by extraction; it stays a manual anchor.
                    if page != 40:
                        assert source["exact_text"] in pdf[page - 1].get_text(sort=True)
                anchor_count += 1
    print(f"{len(departments)} departments / {len(targets)} targets / {field_count} fields / {anchor_count} source anchors checked")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
