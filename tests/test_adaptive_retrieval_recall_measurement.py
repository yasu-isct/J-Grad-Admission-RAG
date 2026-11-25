"""Offline checks of measurement semantics; no model calls or new CI threshold."""

import importlib.util
import json
import statistics
from pathlib import Path
from types import SimpleNamespace

import pytest


def harness():
    path = Path(__file__).resolve().parents[1] / "scripts/evaluate_adaptive_retrieval_recall.py"
    spec = importlib.util.spec_from_file_location("adaptive_recall_measurement", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recall_uses_unchanged_gold_and_deduplicates():
    measure = harness()
    assert measure.score(["a", "b"], ["a", "a", "unrelated"]) == 0.5
    assert measure.score(["a", "b"], []) == 0
    with pytest.raises(ValueError):
        measure.score([], [])


def test_no_lookup_stays_empty_without_search(monkeypatch):
    import jgrad_admission_rag.service.app as product

    measure = harness()

    def forbidden(*args):
        pytest.fail("no_lookup must not retrieve")

    monkeypatch.setattr(product, "_retrieve_natural_answer_evidence", forbidden)
    plan = {"needs_local_lookup": False, "search_queries": []}
    archive = {"status": "ok", "plan": plan, "plan_sha256": measure.digest(plan)}
    assert measure.select_for_plan(archive, None, None, None) == ()


def test_fallback_delegates_to_existing_product(monkeypatch):
    import jgrad_admission_rag.service.app as product

    measure = harness()
    seen = []

    def fallback(request, analysis, settings, state):
        seen.append((request.question, analysis, settings, state))
        return ("existing-product-fallback",)

    monkeypatch.setattr(product, "_retrieve_deterministic_fallback", fallback)
    request = SimpleNamespace(question="出願期間はいつですか。")
    assert measure.select_for_plan({"status": "fallback"}, request, "settings", "state") == (
        "existing-product-fallback",
    )
    assert len(seen) == 1
    assert seen[0][2:] == ("settings", "state")


def test_modified_archive_rejected():
    measure = harness()
    archive = {"status": "ok", "plan": {"needs_local_lookup": False}, "plan_sha256": "wrong"}
    with pytest.raises(AssertionError):
        measure.select_for_plan(archive, None, None, None)


def test_capture_requires_exact_authorization_before_client_creation():
    measure = harness()
    with pytest.raises(ValueError, match="126"):
        measure.capture(Path("unused"), 0)


def test_archives_preserve_actual_requests_raw_output_and_all_three_rounds():
    measure = harness()
    settings = measure.read(measure.OUT / "run-settings.json")
    targets = {t["query_id"]: t for t in measure.read(measure.OUT / "targets.json")}
    for number in (1, 2, 3):
        paths = sorted((measure.OUT / "plans" / f"round-{number}").glob("*.json"))
        assert len(paths) == 42
        assert {measure.read(p)["query_id"] for p in paths} == set(targets)
        for path in paths:
            archive = measure.read(path)
            assert archive["settings_sha256"] == measure.digest(settings)
            assert archive["wire_request_sha256"] == measure.digest(archive["wire_request"])
            wire = archive["wire_request"]
            assert wire["input"][0]["content"] == settings["system_prompt"]
            request = json.loads(wire["input"][1]["content"])
            assert request["question"] == targets[archive["query_id"]]["question"]
            assert request["target_label"] == targets[archive["query_id"]]["target_label"]
            assert wire["text"]["format"]["name"] == "adaptive_qa_plan"
            assert wire["text"]["format"]["schema"] == settings["wire_schema"]
            assert not {"temperature", "seed", "top_p"}.intersection(wire)
            if archive["status"] == "ok":
                assert archive["plan_sha256"] == measure.digest(archive["plan"])
                assert archive["raw_response_sha256"] == measure.digest(archive["raw_response"])
                raw_text = "".join(
                    c["text"]
                    for item in archive["raw_response"]["output"]
                    for c in item.get("content", [])
                    if c.get("type") == "output_text"
                )
                raw_plan = json.loads(raw_text)
                for key in ("draft_answer", "needs_local_lookup", "search_queries"):
                    assert raw_plan[key] == archive["plan"][key]


def test_saved_results_score_unchanged_gold_and_respect_product_scope_and_limits():
    from jgrad_admission_rag.service.app import _retrieved_evidence_matches_target
    from jgrad_admission_rag.service.demo_requirements import DemoTargetRequest

    measure = harness()
    gold = {q["query_id"]: q for q in measure.read(measure.BENCHMARK)["queries"]}
    targets = {
        t["query_id"]: DemoTargetRequest.model_validate(t["target"])
        for t in measure.read(measure.OUT / "targets.json")
    }
    summary = measure.read(measure.OUT / "summary.json")
    for name in ("single-query", "round-1", "round-2", "round-3"):
        rows = measure.read(measure.OUT / "results" / (name + ".json"))
        assert len(rows) == 42
        for row in rows:
            assert row["gold_fact_ids"] == gold[row["query_id"]]["relevant_fact_ids"]
            selected = row["selected"]
            ids = [s["fact_id"] for s in selected]
            assert len(ids) == len(set(ids)) <= 16
            assert all(s["text_characters"] <= 20_000 for s in selected)
            assert (
                sum(s["text_characters"] + len(" / ".join(s["section_path"])) for s in selected)
                <= 60_000
            )
            assert all(
                _retrieved_evidence_matches_target(SimpleNamespace(**s), targets[row["query_id"]])
                for s in selected
            )
            assert row["recall"] == measure.score(row["gold_fact_ids"], ids)
            if name != "single-query":
                archive = measure.read(
                    measure.OUT / "plans" / name / (row["query_id"].replace(":", "-") + ".json")
                )
                assert row["plan_archive_sha256"] == measure.digest(archive)
        for group in ("all", "ja", "zh"):
            subset = [r for r in rows if group == "all" or r["query_language"] == group]
            assert summary["paths"][name]["groups"][group]["recall"] == statistics.mean(
                r["recall"] for r in subset
            )
    # No score threshold: this is an archive/formula check, not a retrieval release gate.
    for group in ("all", "ja", "zh"):
        recalls = [summary["paths"][f"round-{n}"]["groups"][group]["recall"] for n in (1, 2, 3)]
        assert summary["adaptive_three_rounds"][group] == {
            "mean": statistics.mean(recalls),
            "min": min(recalls),
            "max": max(recalls),
        }
