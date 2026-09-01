from jgrad_admission_rag.builder.kb_builder import evaluate_quality_gates
from jgrad_admission_rag.schemas.document_kb import (
    BuildDiagnostics,
    BuildQualityThresholds,
    ReferenceDiagnostic,
)


def _reference_claim(status: str) -> ReferenceDiagnostic:
    return ReferenceDiagnostic(
        source_fact_id="fact:00001",
        label="下記（1）",
        reference_key="item:1",
        direction="forward",
        status=status,
        candidate_target_fact_ids=(["fact:00002", "fact:00003"] if status != "unresolved" else []),
        selected_target_fact_id="fact:00002" if status == "resolved" else None,
        top_score=0.9 if status != "unresolved" else None,
        score_margin=0.1 if status == "ambiguous" else None,
        reason=status,
    )


def test_quality_gates_pass_at_exact_boundary_and_allow_disabled_metrics() -> None:
    diagnostics = BuildDiagnostics(
        missing_source_page_fact_ids=["fact:00001"],
        unknown_scope_fact_ids=["fact:00002"],
        reference_claims=[_reference_claim("unresolved")],
    )
    thresholds = BuildQualityThresholds(
        max_missing_source_pages=1,
        max_unknown_scope_facts=None,
        max_unresolved_references=1,
    )

    result = evaluate_quality_gates(diagnostics, thresholds)

    assert result.passed
    assert result.violations == []


def test_quality_gates_report_multiple_structured_violations() -> None:
    unresolved = _reference_claim("unresolved")
    ambiguous = _reference_claim("ambiguous")
    diagnostics = BuildDiagnostics(
        missing_source_page_fact_ids=["fact:00001"],
        missing_section_path_fact_ids=["fact:00002"],
        unexplained_oversized_fact_ids=["fact:00003"],
        reference_claims=[unresolved, ambiguous],
    )
    thresholds = BuildQualityThresholds(
        max_missing_source_pages=0,
        max_missing_section_paths=0,
        max_unexplained_oversized_facts=0,
        max_unresolved_references=0,
        max_ambiguous_references=0,
    )

    result = evaluate_quality_gates(diagnostics, thresholds)

    assert not result.passed
    assert [violation.metric for violation in result.violations] == [
        "missing_source_pages",
        "missing_section_paths",
        "unexplained_oversized_facts",
        "unresolved_references",
        "ambiguous_references",
    ]
    assert result.violations[0].related_ids == ["fact:00001"]
    assert result.violations[-1].related_claims == [ambiguous]
