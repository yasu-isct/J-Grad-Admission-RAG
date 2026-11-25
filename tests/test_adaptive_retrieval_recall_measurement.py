"""Offline checks of measurement semantics; no model calls or new CI threshold."""

import importlib.util
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
