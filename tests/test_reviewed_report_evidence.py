from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from jgrad_admission_rag.corpus import CorpusRegistration, build_corpus_manifest
from jgrad_admission_rag.corpus_selection import select_corpus_documents
from jgrad_admission_rag.reasoning.applicability import (
    ApplicabilityPredicate,
    ApplicabilityRule,
    LogicalMode,
    OfficialEvidenceBinding,
    PredicateOperator,
    RuleScope,
)
from jgrad_admission_rag.reasoning.query_intent import IntentCategory
from jgrad_admission_rag.reasoning.reviewed_report_evidence import (
    ReviewedReportEvidenceBundle,
    ReviewedReportEvidenceError,
    ReviewedReportEvidenceFailure,
    canonical_reviewed_report_evidence_bundle_bytes,
    load_reviewed_report_evidence_bundle_bytes,
    prepare_reviewed_report_evidence,
)
from jgrad_admission_rag.reasoning.reviewed_report_plan import ReviewedReportPlan
from jgrad_admission_rag.reasoning.rule_interaction import RuleInteractionPolicy
from jgrad_admission_rag.reasoning.rule_resolution import (
    RulePrecedencePolicy,
    RuleSubjectAssignment,
)
from jgrad_admission_rag.retrieval.embedding import DeterministicFakeEmbeddingProvider
from jgrad_admission_rag.retrieval.local_index import build_local_index
from jgrad_admission_rag.schemas.corpus_manifest import CorpusManifest
from jgrad_admission_rag.schemas.corpus_version import (
    CorpusFamilyVersionPolicy,
    CorpusSelectionRequest,
    CorpusSelectionResult,
    CorpusVersionPolicy,
)
from jgrad_admission_rag.schemas.document_identity import DocumentIdentity
from jgrad_admission_rag.schemas.document_kb import canonical_document_kb_bytes
from tests.test_corpus_manifest import _identity, _kb


@dataclass(frozen=True)
class _Context:
    root: Path
    kb_path: Path
    manifest: CorpusManifest
    policy: CorpusVersionPolicy
    selection: CorpusSelectionResult
    plan: ReviewedReportPlan


def _rule(
    identity: DocumentIdentity,
    source_kb_sha256: str,
    fact_text: str,
    *,
    rule_id: str = "reviewed-rule-a",
    fact_id: str = "fact:00000",
    pages: tuple[int, ...] = (1,),
    text_hash: str | None = None,
    scope: RuleScope | None = None,
) -> ApplicabilityRule:
    return ApplicabilityRule(
        rule_id=rule_id,
        mode=LogicalMode.ALL,
        predicates=(
            ApplicabilityPredicate(
                field_path="eligibility_facts.age_at_enrollment",
                operator=PredicateOperator.MINIMUM,
                expected_value=18,
            ),
        ),
        scope=scope or RuleScope(scope_type="global"),
        evidence_bindings=(
            OfficialEvidenceBinding(
                document_id=identity.document_id,
                source_kb_sha256=source_kb_sha256,
                source_pdf_sha256=identity.source_pdf_sha256,
                fact_id=fact_id,
                source_pages=pages,
                authoritative_fact_text_sha256=text_hash
                or hashlib.sha256(fact_text.encode("utf-8")).hexdigest(),
            ),
        ),
        annotation_note="Reviewed test rule.",
    )


def _plan(
    identity: DocumentIdentity,
    source_kb_sha256: str,
    fact_text: str,
    *,
    rules: tuple[ApplicabilityRule, ...] | None = None,
    plan_id: str = "reviewed-plan-v1",
) -> ReviewedReportPlan:
    rules = rules or (_rule(identity, source_kb_sha256, fact_text),)
    return ReviewedReportPlan(
        plan_id=plan_id,
        document_identity=identity,
        rules=rules,
        precedence_policy=RulePrecedencePolicy(
            policy_id=f"{plan_id}-precedence",
            subjects=tuple(
                RuleSubjectAssignment(rule_id=rule.rule_id, subject_key="eligibility.age")
                for rule in rules
            ),
            override_edges=(),
        ),
        interaction_policy=RuleInteractionPolicy(
            policy_id=f"{plan_id}-interactions",
            interactions=(),
        ),
        covered_categories=(IntentCategory.ELIGIBILITY,),
        coverage_status="partial_reviewed_rules",
        reviewed_coverage_statement="Covers reviewed synthetic eligibility rules.",
        limitation_statement="Does not establish overall eligibility or admission.",
    )


def _context(
    tmp_path: Path,
    *,
    document_id: str = "sample-2027",
    canonical_kb: bool = True,
) -> _Context:
    identity = _identity(document_id, family="sample", institution="sample-u")
    kb = _kb(identity)
    kb_path = tmp_path / "documents" / document_id / "document_kb.json"
    kb_path.parent.mkdir(parents=True)
    kb_bytes = (
        canonical_document_kb_bytes(kb)
        if canonical_kb
        else (
            json.dumps(kb.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
    )
    kb_path.write_bytes(kb_bytes)
    index_relative = f"indexes/{document_id}"
    build_local_index(
        kb_path,
        tmp_path / Path(*index_relative.split("/")),
        DeterministicFakeEmbeddingProvider(4),
    )
    kb_relative = f"documents/{document_id}/document_kb.json"
    manifest = build_corpus_manifest(
        "admissions",
        tmp_path,
        (CorpusRegistration(kb_relative, index_relative),),
    )
    policy = CorpusVersionPolicy(
        corpus_id="admissions",
        family_policies=(
            CorpusFamilyVersionPolicy(
                document_family_id="sample",
                active_document_id=document_id,
            ),
        ),
    )
    selection = select_corpus_documents(
        manifest,
        policy,
        CorpusSelectionRequest(document_ids=(document_id,)),
    )
    source_hash = hashlib.sha256(kb_path.read_bytes()).hexdigest()
    return _Context(
        root=tmp_path,
        kb_path=kb_path,
        manifest=manifest,
        policy=policy,
        selection=selection,
        plan=_plan(identity, source_hash, kb.facts[0].text),
    )


def _prepare(context: _Context, plans: tuple[ReviewedReportPlan, ...] | None = None):
    return prepare_reviewed_report_evidence(
        context.root,
        context.manifest,
        context.policy,
        context.selection,
        (context.plan,) if plans is None else plans,
    )


def _failure(context: _Context, plan: ReviewedReportPlan) -> ReviewedReportEvidenceError:
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        _prepare(context, (plan,))
    return exc_info.value


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_exact_selected_plan_materializes_detached_deduplicated_evidence(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    fact_text = _kb(context.plan.document_identity).facts[0].text
    source_hash = context.manifest.entries[0].source_kb_sha256
    rules = (
        _rule(
            context.plan.document_identity,
            source_hash,
            fact_text,
            rule_id="reviewed-rule-a",
        ),
        _rule(
            context.plan.document_identity,
            source_hash,
            fact_text,
            rule_id="reviewed-rule-b",
        ),
    )
    plan = _plan(
        context.plan.document_identity,
        source_hash,
        fact_text,
        rules=rules,
    )
    before = _file_snapshot(tmp_path)

    bundle = _prepare(context, (plan,))

    assert bundle.plan_id == plan.plan_id
    assert bundle.document_identity == plan.document_identity
    assert bundle.source_kb_sha256 == source_hash
    assert len(bundle.evidence_records) == 1
    record = bundle.evidence_records[0]
    assert record.document_id == plan.document_identity.document_id
    assert record.fact_id == "fact:00000"
    assert record.text == fact_text
    assert record.source_pages == (1,)
    assert record.section_path == ("Eligibility",)
    assert record.fact_type == "eligibility"
    assert record.scope_type == "global"
    assert record.rule_ids == ("reviewed-rule-a", "reviewed-rule-b")
    assert bundle.counts.model_dump() == {
        "record_count": 1,
        "rule_count": 2,
        "source_page_count": 1,
    }
    assert _file_snapshot(tmp_path) == before


def test_bundle_canonical_round_trip_is_exact_finite_and_has_no_retrieval_fields(
    tmp_path: Path,
) -> None:
    bundle = _prepare(_context(tmp_path))
    raw = canonical_reviewed_report_evidence_bundle_bytes(bundle)

    assert (
        canonical_reviewed_report_evidence_bundle_bytes(
            load_reviewed_report_evidence_bundle_bytes(raw)
        )
        == raw
    )
    assert raw.endswith(b"\n")
    assert b"NaN" not in raw
    payload = json.loads(raw)
    serialized_keys = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "query",
        "rank",
        "score",
        "channel",
        "local_path",
        "applicant_profile",
    ):
        assert forbidden not in serialized_keys
    assert "source_pdf_sha256" not in payload
    with pytest.raises(ValidationError):
        bundle.plan_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"schema_version": "2.0"}),
        lambda payload: payload.update({"extra": "secret"}),
        lambda payload: payload.update({"plan_id": "C:\\private\\plan.json"}),
        lambda payload: payload["counts"].update({"record_count": 2}),
        lambda payload: payload["counts"].update({"rule_count": "1"}),
        lambda payload: payload["evidence_records"][0].update({"source_pages": ["1"]}),
        lambda payload: payload["evidence_records"][0].update({"rule_ids": ["z", "a"]}),
    ],
)
def test_bundle_loader_rejects_version_extra_coercion_order_and_count_tampering(
    tmp_path: Path,
    mutation,
) -> None:
    payload = _prepare(_context(tmp_path)).model_dump(mode="json")
    mutation(payload)
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        load_reviewed_report_evidence_bundle_bytes(json.dumps(payload).encode())
    assert exc_info.value.code is ReviewedReportEvidenceFailure.INVALID_BUNDLE
    assert str(exc_info.value) == "reviewed report evidence operation failed"


def test_canonical_bundle_rejects_model_copy_extra_without_echo() -> None:
    payload = {
        "schema_version": "1.0",
        "plan_id": "plan-v1",
        "document_identity": _identity("doc"),
        "source_kb_sha256": "a" * 64,
        "evidence_records": [
            {
                "document_id": "doc",
                "fact_id": "fact:00000",
                "text": "Exact official text.",
                "source_pages": [1],
                "section_path": ["Eligibility"],
                "fact_type": "eligibility",
                "scope_type": "global",
                "scope_targets": [],
                "parent_college": None,
                "rule_ids": ["rule-a"],
            }
        ],
        "counts": {"record_count": 1, "rule_count": 1, "source_page_count": 1},
    }
    bundle = ReviewedReportEvidenceBundle.model_validate(payload)
    bypassed = bundle.model_copy(update={"query": "copied-query-secret"})
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        canonical_reviewed_report_evidence_bundle_bytes(bypassed)
    assert exc_info.value.code is ReviewedReportEvidenceFailure.INVALID_BUNDLE
    assert "copied-query-secret" not in str(exc_info.value)


def test_zero_and_multiple_selected_documents_fail_before_audit(tmp_path: Path) -> None:
    context = _context(tmp_path)
    selected = context.selection.selected_documents[0]
    for documents in ((), (selected, selected)):
        selection = context.selection.model_copy(update={"selected_documents": documents})
        with pytest.raises(ReviewedReportEvidenceError) as exc_info:
            prepare_reviewed_report_evidence(
                context.root,
                context.manifest,
                context.policy,
                selection,
                (context.plan,),
            )
        assert exc_info.value.code is ReviewedReportEvidenceFailure.SELECTION_CARDINALITY


def test_zero_and_duplicate_exact_plan_matches_have_distinct_codes(tmp_path: Path) -> None:
    context = _context(tmp_path)
    with pytest.raises(ReviewedReportEvidenceError) as empty_error:
        _prepare(context, ())
    assert empty_error.value.code is ReviewedReportEvidenceFailure.INVALID_INPUT

    other_identity = _identity("other-2027", family="sample", institution="sample-u")
    missing = _plan(other_identity, "d" * 64, "Other official text.")
    assert _failure(context, missing).code is ReviewedReportEvidenceFailure.PLAN_NOT_FOUND

    duplicate = context.plan.model_copy(update={"plan_id": "reviewed-plan-v2"})
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        _prepare(context, (context.plan, duplicate))
    assert exc_info.value.code is ReviewedReportEvidenceFailure.PLAN_AMBIGUOUS


def test_stale_selection_policy_registration_and_unready_entry_fail_closed(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    stale_selection = context.selection.model_copy(update={"corpus_id": "other-corpus"})
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        prepare_reviewed_report_evidence(
            context.root,
            context.manifest,
            context.policy,
            stale_selection,
            (context.plan,),
        )
    assert exc_info.value.code is ReviewedReportEvidenceFailure.SELECTION_STALE

    stale_policy = context.policy.model_copy(update={"corpus_id": "other-corpus"})
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        prepare_reviewed_report_evidence(
            context.root,
            context.manifest,
            stale_policy,
            context.selection,
            (context.plan,),
        )
    assert exc_info.value.code is ReviewedReportEvidenceFailure.SELECTION_STALE

    selected = context.selection.selected_documents[0]
    unready_entry = selected.entry.model_copy(
        update={"index_state": "not_indexed", "index_path": None, "index_manifest": None}
    )
    unready_selection = context.selection.model_copy(
        update={
            "selected_documents": (selected.model_copy(update={"entry": unready_entry}),),
        }
    )
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        prepare_reviewed_report_evidence(
            context.root,
            context.manifest,
            context.policy,
            unready_selection,
            (context.plan,),
        )
    assert exc_info.value.code is ReviewedReportEvidenceFailure.INVALID_INPUT

    context.kb_path.write_bytes(context.kb_path.read_bytes() + b" ")
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        _prepare(context)
    assert exc_info.value.code is ReviewedReportEvidenceFailure.CORPUS_AUDIT_FAILED


def test_traversal_and_symlinked_kb_fail_without_reading_outside_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path / "corpus")
    outside = tmp_path / "outside-secret.json"
    outside.write_text("official-secret", encoding="utf-8")
    selected = context.selection.selected_documents[0]
    unsafe_entry = selected.entry.model_copy(update={"kb_path": "../outside-secret.json"})
    unsafe_selection = context.selection.model_copy(
        update={"selected_documents": (selected.model_copy(update={"entry": unsafe_entry}),)}
    )
    original_read = Path.read_bytes

    def deny_outside_read(path: Path) -> bytes:
        if path == outside:
            raise AssertionError("outside path must not be read")
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", deny_outside_read)
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        prepare_reviewed_report_evidence(
            context.root,
            context.manifest,
            context.policy,
            unsafe_selection,
            (context.plan,),
        )
    assert exc_info.value.code is ReviewedReportEvidenceFailure.INVALID_INPUT
    assert outside.read_text(encoding="utf-8") == "official-secret"

    replacement = context.kb_path.with_suffix(".target")
    context.kb_path.replace(replacement)
    try:
        context.kb_path.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        _prepare(context)
    assert exc_info.value.code is ReviewedReportEvidenceFailure.CORPUS_AUDIT_FAILED


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"source_kb_sha256": "d" * 64}, ReviewedReportEvidenceFailure.KB_HASH_MISMATCH),
        ({"fact_id": "fact:missing"}, ReviewedReportEvidenceFailure.FACT_NOT_FOUND),
        ({"pages": (2,)}, ReviewedReportEvidenceFailure.FACT_PAGES_MISMATCH),
        ({"text_hash": "d" * 64}, ReviewedReportEvidenceFailure.FACT_TEXT_MISMATCH),
        (
            {
                "scope": RuleScope(
                    scope_type="department",
                    scope_targets=("Other",),
                    parent_college="Other College",
                )
            },
            ReviewedReportEvidenceFailure.FACT_SCOPE_MISMATCH,
        ),
    ],
)
def test_kb_and_fact_binding_mismatches_have_stable_codes(
    tmp_path: Path,
    change: dict[str, object],
    expected: ReviewedReportEvidenceFailure,
) -> None:
    context = _context(tmp_path)
    identity = context.plan.document_identity
    source_hash = change.get("source_kb_sha256", context.plan.source_kb_sha256)
    rule = _rule(
        identity,
        source_hash,  # type: ignore[arg-type]
        _kb(identity).facts[0].text,
        fact_id=change.get("fact_id", "fact:00000"),  # type: ignore[arg-type]
        pages=change.get("pages", (1,)),  # type: ignore[arg-type]
        text_hash=change.get("text_hash"),  # type: ignore[arg-type]
        scope=change.get("scope"),  # type: ignore[arg-type]
    )
    plan = _plan(identity, source_hash, _kb(identity).facts[0].text, rules=(rule,))  # type: ignore[arg-type]
    assert _failure(context, plan).code is expected


def test_identity_duplicate_fact_and_noncanonical_kb_are_rejected_after_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    from jgrad_admission_rag.reasoning import reviewed_report_evidence as module

    original_loader = module._load_canonical_kb
    raw, kb, source_hash = original_loader(context.kb_path)
    other_identity = _identity("other-2027", family="sample", institution="sample-u")
    wrong_identity_kb = kb.model_copy(
        update={"manifest": kb.manifest.model_copy(update={"identity": other_identity})}
    )
    monkeypatch.setattr(
        module,
        "_load_canonical_kb",
        lambda _path: (raw, wrong_identity_kb, source_hash),
    )
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        _prepare(context)
    assert exc_info.value.code is ReviewedReportEvidenceFailure.KB_IDENTITY_MISMATCH

    duplicate_kb = kb.model_copy(update={"facts": [kb.facts[0], kb.facts[0].model_copy()]})
    monkeypatch.setattr(
        module,
        "_load_canonical_kb",
        lambda _path: (raw, duplicate_kb, source_hash),
    )
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        _prepare(context)
    assert exc_info.value.code is ReviewedReportEvidenceFailure.FACT_DUPLICATE

    monkeypatch.setattr(module, "_load_canonical_kb", original_loader)


def test_audited_but_noncanonical_kb_is_rejected(tmp_path: Path) -> None:
    context = _context(tmp_path, canonical_kb=False)
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        _prepare(context)
    assert exc_info.value.code is ReviewedReportEvidenceFailure.KB_NOT_CANONICAL


def test_quality_failure_before_audit_is_a_corpus_failure_without_partial_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    failed_kb = _kb(context.plan.document_identity, passed=False)
    context.kb_path.write_bytes(canonical_document_kb_bytes(failed_kb))
    from jgrad_admission_rag.reasoning import reviewed_report_evidence as module

    calls: list[str] = []
    original = module._record_from_fact

    def record_spy(document_id, fact, rule_ids):
        calls.append(fact.fact_id)
        return original(document_id, fact, rule_ids)

    monkeypatch.setattr(module, "_record_from_fact", record_spy)
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        _prepare(context)
    assert exc_info.value.code is ReviewedReportEvidenceFailure.CORPUS_AUDIT_FAILED
    assert calls == []


def test_quality_failure_after_audit_is_a_kb_failure_without_partial_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    failed_kb_bytes = canonical_document_kb_bytes(_kb(context.plan.document_identity, passed=False))
    from jgrad_admission_rag.reasoning import reviewed_report_evidence as module

    original_audit = module.audit_corpus_manifest
    original_record = module._record_from_fact
    calls: list[str] = []

    def audit_then_drift(manifest, corpus_root):
        audited = original_audit(manifest, corpus_root)
        context.kb_path.write_bytes(failed_kb_bytes)
        return audited

    def record_spy(document_id, fact, rule_ids):
        calls.append(fact.fact_id)
        return original_record(document_id, fact, rule_ids)

    monkeypatch.setattr(module, "audit_corpus_manifest", audit_then_drift)
    monkeypatch.setattr(module, "_record_from_fact", record_spy)
    with pytest.raises(ReviewedReportEvidenceError) as exc_info:
        _prepare(context)
    assert exc_info.value.code is ReviewedReportEvidenceFailure.KB_QUALITY_FAILED
    assert calls == []


def test_later_failed_binding_returns_no_partial_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    identity = context.plan.document_identity
    source_hash = context.plan.source_kb_sha256
    text = _kb(identity).facts[0].text
    rules = (
        _rule(identity, source_hash, text, rule_id="a-valid"),
        _rule(
            identity,
            source_hash,
            text,
            rule_id="b-missing",
            fact_id="fact:missing",
        ),
    )
    plan = _plan(identity, source_hash, text, rules=rules)
    from jgrad_admission_rag.reasoning import reviewed_report_evidence as module

    calls: list[str] = []
    original = module._record_from_fact

    def record_spy(document_id, fact, rule_ids):
        calls.append(fact.fact_id)
        return original(document_id, fact, rule_ids)

    monkeypatch.setattr(module, "_record_from_fact", record_spy)
    assert _failure(context, plan).code is ReviewedReportEvidenceFailure.FACT_NOT_FOUND
    assert calls == []


def test_public_error_never_echoes_planted_content(tmp_path: Path) -> None:
    context = _context(tmp_path)
    planted = "private-path-hash-secret-official-text"
    identity = context.plan.document_identity
    rule = _rule(
        identity,
        context.plan.source_kb_sha256,
        _kb(identity).facts[0].text,
        fact_id=planted,
    )
    error = _failure(
        context,
        _plan(identity, context.plan.source_kb_sha256, "unused", rules=(rule,)),
    )
    assert str(error) == "reviewed report evidence operation failed"
    assert planted not in str(error)
    assert error.__suppress_context__ is True


def test_import_is_inert_and_core_has_no_service_or_model_dependency() -> None:
    script = """
import sys
import jgrad_admission_rag.reasoning.reviewed_report_evidence
assert "sentence_transformers" not in sys.modules
assert "fastapi" not in sys.modules
"""
    subprocess.run([sys.executable, "-c", script], check=True)
