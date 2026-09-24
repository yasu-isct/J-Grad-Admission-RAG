"""Build the mixed-language M9-05 benchmark on the current formal KB contract."""

from __future__ import annotations

import json
from pathlib import Path

from jgrad_admission_rag.evaluation.retrieval_queries import (
    RetrievalBenchmark,
    load_retrieval_benchmark,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
CURRENT = FIXTURES / "retrieval_queries_rule04c_v1.json"
CROSS_LANGUAGE = FIXTURES / "retrieval_queries_v1.json"
OUTPUT = FIXTURES / "grounded_rag_retrieval_queries_v1.json"


def main() -> None:
    current = load_retrieval_benchmark(CURRENT)
    cross_language = load_retrieval_benchmark(CROSS_LANGUAGE)
    chinese_queries = [
        item.model_dump(mode="json")
        for item in cross_language.queries
        if item.query_language == "zh"
    ]
    payload = current.model_dump(mode="json")
    payload["language"] = "ja+zh"
    payload["queries"].extend(chinese_queries)
    by_id = {item["query_id"]: item for item in payload["queries"]}
    reviewed_variants = (
        (
            "rq:0036",
            "rq:0039",
            "TOEFLの有効な種類を教えてください。",
            "日本語の有効種別表現。共通英語試験規則の同じ審査済み証拠を使う。",
        ),
        (
            "rq:0036",
            "rq:0040",
            "英語外部試験としてTOEFL iBTは認められますか。",
            "日本語のTOEFL iBT確認表現。共通英語試験規則の同じ審査済み証拠を使う。",
        ),
        (
            "rq:0036",
            "rq:0041",
            "TOEFL iBT Home Editionは有効ですか。",
            "日本語のHome Edition確認表現。共通英語試験規則の同じ審査済み証拠を使う。",
        ),
        (
            "rq:0001",
            "rq:0042",
            "出願期間と書類必着日はいつですか。",
            "日本語の簡潔な日程表現。審査済みの出願期間・必着日証拠を使う。",
        ),
    )
    for source_id, query_id, query, note in reviewed_variants:
        variant = dict(by_id[source_id])
        variant.update(query_id=query_id, query=query, annotation_note=note)
        if source_id == "rq:0036":
            variant["query_language"] = "ja"
            reviewed_fact_id = "fact:00111" if query_id == "rq:0041" else "fact:00109"
            evidence = dict(by_id[source_id]["gold_evidence"][-1])
            evidence["fact_id"] = reviewed_fact_id
            variant["gold_evidence"] = [evidence]
            variant["relevant_fact_ids"] = [reviewed_fact_id]
            variant["requires_multiple_clauses"] = False
        payload["queries"].append(variant)
    benchmark = RetrievalBenchmark.model_validate(payload)
    OUTPUT.write_bytes(
        (
            json.dumps(
                benchmark.model_dump(mode="json"),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )


if __name__ == "__main__":
    main()
