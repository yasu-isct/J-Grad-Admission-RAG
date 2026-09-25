from __future__ import annotations

import pytest

from jgrad_admission_rag.generation import (
    ClaimKind,
    DeterministicFakeGenerationProvider,
    GeneratedClaim,
    GenerationDraft,
    GenerationError,
    GenerationErrorCode,
    GenerationEvidence,
    GenerationTarget,
)
from jgrad_admission_rag.generation.consolidated_grounded_rag import (
    ClaimableProposition,
    ConsolidatedEvidenceRecord,
    PropositionPredicate,
    run_consolidated_grounded_rag,
)
from jgrad_admission_rag.generation.contracts import EvidenceRole, assemble_generation_answer


def _evidence(
    text: str = "情報工学系では英語を100点満点で評価する。",
) -> ConsolidatedEvidenceRecord:
    return ConsolidatedEvidenceRecord(
        evidence=GenerationEvidence(
            evidence_id="evidence:0001",
            role=EvidenceRole.PRIMARY,
            text=text,
            scope_label="情報理工学院 / 情報工学系",
        ),
        document_id="document-1",
        fact_id="fact:00001",
        source_pages=(52,),
        source_kb_sha256="1" * 64,
        source_pdf_sha256="2" * 64,
        scope_type="department",
        scope_targets=("情報工学系",),
        parent_college="情報理工学院",
    )


def _proposition() -> ClaimableProposition:
    return ClaimableProposition(
        proposition_id="proposition:0001",
        obligation_ids=("subquestion:02",),
        predicate=PropositionPredicate.MAXIMUM_POINTS,
        subject="情報工学系",
        numeric_value=100,
        evidence_ids=("evidence:0001",),
    )


def _draft(text: str) -> GenerationDraft:
    claims = (
        GeneratedClaim(
            claim_id="claim:0001",
            kind=ClaimKind.REVIEWED_RULE,
            text=text,
            evidence_ids=("evidence:0001",),
            finding_ids=("proposition:0001",),
        ),
    )
    return GenerationDraft(
        answer=assemble_generation_answer(claims),
        claims=claims,
        needs_review=False,
        refused=False,
    )


def _run(text: str):
    return run_consolidated_grounded_rag(
        DeterministicFakeGenerationProvider(_draft(text)),
        request_id="request:test",
        question="请自然回答英语配点。",
        target=GenerationTarget(
            application_label="Science Tokyo / 情報工学系",
            scope_targets=("情報工学系",),
            parent_college="情報理工学院",
        ),
        evidence=(_evidence(),),
        propositions=(_proposition(),),
    )


@pytest.mark.parametrize(
    "text",
    (
        "情報工学系的英语满分为100分。",
        "根据当前审核资料，情報工学系的英语满分为100分。",
        "情報工学系では英語を100点満点で評価します。",
        "The maximum English score for 情報工学系 is 100 points.",
    ),
)
def test_consolidated_generation_preserves_validated_natural_claim_text(text: str) -> None:
    result = _run(text)

    assert result.answer == text
    assert result.claims[0].text == text
    assert result.claims[0].obligation_ids == ("subquestion:02",)
    assert result.claims[0].citations[0].fact_id == "fact:00001"


@pytest.mark.parametrize(
    "text",
    (
        "情報工学系的英语满分为840分。",
        "TOEIC 100分会换算为情報工学系英语满分。",
        "情報工学系的英语100分保证录取。",
        "情報工学系不需要英语，满分为100分。",
        "情報工学系的英语满分不是100分。",
        "情報工学系的英语最低分和满分都是100分。",
        "情報工学系的英语满分为100分，而且学校很好。",
    ),
)
def test_consolidated_generation_rejects_changed_relation_number_exam_or_polarity(
    text: str,
) -> None:
    with pytest.raises(GenerationError) as caught:
        _run(text)

    assert caught.value.code is GenerationErrorCode.UNSUPPORTED_CLAIM


def test_exact_evidence_proposition_requires_verbatim_authoritative_text() -> None:
    evidence = _evidence("提出期間は2026年6月1日から6月5日まで。")
    proposition = ClaimableProposition(
        proposition_id="proposition:0001",
        obligation_ids=("subquestion:01",),
        predicate=PropositionPredicate.EXACT_EVIDENCE,
        subject="application_dates",
        exact_evidence_text=evidence.evidence.text,
        evidence_ids=("evidence:0001",),
    )
    draft = _draft(evidence.evidence.text)

    result = run_consolidated_grounded_rag(
        DeterministicFakeGenerationProvider(draft),
        request_id="request:test",
        question="出願期間は？",
        target=GenerationTarget(
            application_label="target",
            scope_targets=("情報工学系",),
            parent_college="情報理工学院",
        ),
        evidence=(evidence,),
        propositions=(proposition,),
    )

    assert result.answer == evidence.evidence.text


@pytest.mark.parametrize(
    "text",
    (
        "当前募集要项将TOEIC列为英语外部考试之一。",
        "現在の募集要項では、TOEICが英語外部試験の一つとして記載されています。",
        "The current admission guidelines list TOEIC as an external English test.",
    ),
)
def test_exam_listed_accepts_only_closed_natural_templates(text: str) -> None:
    evidence = _evidence("英語外部試験としてTOEICを利用できる。")
    proposition = ClaimableProposition(
        proposition_id="proposition:0001",
        obligation_ids=("subquestion:01",),
        predicate=PropositionPredicate.EXAM_LISTED,
        subject="TOEIC",
        evidence_ids=("evidence:0001",),
    )

    result = run_consolidated_grounded_rag(
        DeterministicFakeGenerationProvider(_draft(text)),
        request_id="request:test",
        question="TOEICは使えますか。",
        target=GenerationTarget(
            application_label="Science Tokyo / 情報工学系",
            scope_targets=("情報工学系",),
            parent_college="情報理工学院",
        ),
        evidence=(evidence,),
        propositions=(proposition,),
    )

    assert result.answer == text


def test_exam_listed_rejects_new_acceptance_semantics() -> None:
    evidence = _evidence("英語外部試験としてTOEICを利用できる。")
    proposition = ClaimableProposition(
        proposition_id="proposition:0001",
        obligation_ids=("subquestion:01",),
        predicate=PropositionPredicate.EXAM_LISTED,
        subject="TOEIC",
        evidence_ids=("evidence:0001",),
    )

    with pytest.raises(GenerationError) as caught:
        run_consolidated_grounded_rag(
            DeterministicFakeGenerationProvider(_draft("TOEICは必ず受理されます。")),
            request_id="request:test",
            question="TOEICは使えますか。",
            target=GenerationTarget(
                application_label="Science Tokyo / 情報工学系",
                scope_targets=("情報工学系",),
                parent_college="情報理工学院",
            ),
            evidence=(evidence,),
            propositions=(proposition,),
        )

    assert caught.value.code is GenerationErrorCode.UNSUPPORTED_CLAIM


def test_cross_scope_evidence_fails_before_provider_call() -> None:
    class RecordingProvider(DeterministicFakeGenerationProvider):
        calls = 0

        def generate(self, request):
            self.calls += 1
            return super().generate(request)

    evidence = _evidence().model_copy(
        update={"scope_targets": ("別の学系",), "parent_college": "別の学院"}
    )
    provider = RecordingProvider(_draft("情報工学系的英语满分为100分。"))

    with pytest.raises(ValueError, match="target scope"):
        run_consolidated_grounded_rag(
            provider,
            request_id="request:test",
            question="英语配点？",
            target=GenerationTarget(
                application_label="Science Tokyo / 情報工学系",
                scope_targets=("情報工学系",),
                parent_college="情報理工学院",
            ),
            evidence=(evidence,),
            propositions=(_proposition(),),
        )

    assert provider.calls == 0


@pytest.mark.parametrize(
    ("scope_type", "scope_targets", "parent_college"),
    (
        ("global", (), None),
        ("university", (), None),
        ("college", ("情報理工学院",), None),
        ("department", ("情報工学系",), "情報理工学院"),
    ),
)
def test_allowed_scope_shapes_reach_provider(
    scope_type: str,
    scope_targets: tuple[str, ...],
    parent_college: str | None,
) -> None:
    evidence = _evidence().model_copy(
        update={
            "scope_type": scope_type,
            "scope_targets": scope_targets,
            "parent_college": parent_college,
        }
    )

    assert run_consolidated_grounded_rag(
        DeterministicFakeGenerationProvider(_draft("情報工学系的英语满分为100分。")),
        request_id="request:test",
        question="英语配点？",
        target=GenerationTarget(
            application_label="Science Tokyo / 情報工学系",
            scope_targets=("情報工学系",),
            parent_college="情報理工学院",
        ),
        evidence=(evidence,),
        propositions=(_proposition(),),
    ).claims
