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
        "审核资料表明，情報工学系英语科目的上限是100分。",
        "情報工学系の英語評価は上限100点となっています。",
        "The maximum English score for 情報工学系 is 100 points.",
        "说得直白一点，情報工学系这里的英语评价天花板就是100分。",
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
    ),
)
def test_consolidated_generation_rejects_changed_protected_number_or_exam(text: str) -> None:
    with pytest.raises(GenerationError) as caught:
        _run(text)

    assert caught.value.code is GenerationErrorCode.UNSUPPORTED_CLAIM


@pytest.mark.parametrize(
    "text",
    (
        "申请期间从2026年6月1日至6月5日。",
        "请在2026年6月1日到6月5日这一申请期间内提交。",
        "审核资料记载的申请期限是2026年6月1日至6月5日。",
        "出願期間は2026年6月1日から6月5日までです。",
        "2026年6月1日から6月5日が申請受付期間です。",
    ),
)
def test_date_proposition_accepts_natural_non_verbatim_summaries(text: str) -> None:
    evidence = _evidence("提出期間は2026年6月1日から6月5日まで。")
    proposition = ClaimableProposition(
        proposition_id="proposition:0001",
        obligation_ids=("subquestion:01",),
        predicate=PropositionPredicate.DATE_RANGE,
        subject="申请期间",
        protected_literals=("2026年6月1日", "6月5日"),
        evidence_ids=("evidence:0001",),
    )
    draft = _draft(text)

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

    assert result.answer == text
    assert result.answer != evidence.evidence.text


def test_date_proposition_rejects_an_altered_date() -> None:
    evidence = _evidence("提出期間は2026年6月1日から6月5日まで。")
    proposition = ClaimableProposition(
        proposition_id="proposition:0001",
        obligation_ids=("subquestion:01",),
        predicate=PropositionPredicate.DATE_RANGE,
        subject="申请期间",
        protected_literals=("2026年6月1日", "6月5日"),
        evidence_ids=("evidence:0001",),
    )

    with pytest.raises(GenerationError) as caught:
        run_consolidated_grounded_rag(
            DeterministicFakeGenerationProvider(_draft("申请期间从2026年6月1日至6月6日。")),
            request_id="request:test",
            question="申请期间？",
            target=GenerationTarget(
                application_label="target",
                scope_targets=("情報工学系",),
                parent_college="情報理工学院",
            ),
            evidence=(evidence,),
            propositions=(proposition,),
        )

    assert caught.value.code is GenerationErrorCode.UNSUPPORTED_CLAIM


@pytest.mark.parametrize(
    "text",
    (
        "当前募集要项将TOEIC列为英语外部考试之一。",
        "根据审核资料，TOEIC被列为英语外部考试。",
        "現在の募集要項では、TOEICが英語外部試験の一つとして記載されています。",
        "確認済み資料にはTOEICが英語試験として記載されています。",
        "The current admission guidelines list TOEIC as an external English test.",
        "换一种说法，在这份已审核材料里，TOEIC出现在英语外部考试名单中。",
    ),
)
def test_exam_listed_accepts_materially_different_paraphrases(text: str) -> None:
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


def test_exam_listed_rejects_an_altered_exam_entity() -> None:
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
            DeterministicFakeGenerationProvider(_draft("TOEFL iBT被列为英语外部考试。")),
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


def test_missing_answer_obligation_fails_closed() -> None:
    propositions = (
        ClaimableProposition(
            proposition_id="proposition:0001",
            obligation_ids=("subquestion:01",),
            predicate=PropositionPredicate.EXAM_NORMALIZATION,
            subject="托业",
            object="TOEIC L&R",
        ),
        ClaimableProposition(
            proposition_id="proposition:0002",
            obligation_ids=("subquestion:02",),
            predicate=PropositionPredicate.NO_REVIEWED_EVIDENCE,
            subject="JLPT",
        ),
    )
    claim = GeneratedClaim(
        claim_id="claim:0001",
        kind=ClaimKind.REVIEWED_DISPOSITION,
        text="这里的“托业”按TOEIC L&R理解。",
        finding_ids=("proposition:0001",),
    )
    draft = GenerationDraft(
        answer=claim.text,
        claims=(claim,),
        needs_review=True,
        refused=False,
    )

    with pytest.raises(GenerationError) as caught:
        run_consolidated_grounded_rag(
            DeterministicFakeGenerationProvider(draft),
            request_id="request:test",
            question="托业和JLPT？",
            target=GenerationTarget(application_label="target"),
            evidence=(),
            propositions=propositions,
        )

    assert caught.value.code is GenerationErrorCode.STATE_MISMATCH


@pytest.mark.parametrize(
    "text",
    (
        "当前审核资料中未找到JLPT的要求或替代规则。",
        "在现有审核范围内，没有找到JLPT成绩要求或替代规定。",
        "目前的审核资料未确认JLPT要件或替代规则。",
        "確認済み資料ではJLPTの要件や代替規則を確認できません。",
        "現在の確認範囲ではJLPT要件または代替ルールが見当たりません。",
        "谨慎地说，就目前完成审核的材料而言，关于JLPT的规则证据仍然空缺。",
    ),
)
def test_no_reviewed_evidence_accepts_scoped_abstention_paraphrases(text: str) -> None:
    proposition = ClaimableProposition(
        proposition_id="proposition:0001",
        obligation_ids=("subquestion:01",),
        predicate=PropositionPredicate.NO_REVIEWED_EVIDENCE,
        subject="JLPT",
    )
    claim = GeneratedClaim(
        claim_id="claim:0001",
        kind=ClaimKind.REVIEWED_DISPOSITION,
        text=text,
        finding_ids=("proposition:0001",),
    )
    draft = GenerationDraft(
        answer=text,
        claims=(claim,),
        needs_review=True,
        refused=False,
    )

    result = run_consolidated_grounded_rag(
        DeterministicFakeGenerationProvider(draft),
        request_id="request:test",
        question="JLPT有要求吗？",
        target=GenerationTarget(application_label="target"),
        evidence=(),
        propositions=(proposition,),
    )

    assert result.answer == text
    assert result.claims[0].citations == ()


def test_reset_guide_answerfact_slices_cover_required_product_questions() -> None:
    cases = (
        (
            "信息工学系英语最高是多少分？",
            _proposition(),
            _evidence(),
            "換个自然说法，情報工学系的英语评价上限就是100分。",
            ClaimKind.REVIEWED_RULE,
            (),
        ),
        (
            "TOEFL iBT Home Edition 可以使用吗？",
            ClaimableProposition(
                proposition_id="proposition:0001",
                obligation_ids=("subquestion:01",),
                predicate=PropositionPredicate.EXAM_LISTED,
                subject="TOEFL iBT Home Edition",
                evidence_ids=("evidence:0001",),
            ),
            _evidence("英語外部試験としてTOEFL iBT Home Editionを利用できる。"),
            "已审核的考试清单里可以看到TOEFL iBT Home Edition这一项。",
            ClaimKind.REVIEWED_RULE,
            (),
        ),
        (
            "申请日期是什么时候？",
            ClaimableProposition(
                proposition_id="proposition:0001",
                obligation_ids=("subquestion:01",),
                predicate=PropositionPredicate.DATE_RANGE,
                subject="申请期间",
                protected_literals=("2026年6月1日", "6月5日"),
                evidence_ids=("evidence:0001",),
            ),
            _evidence("提出期間は2026年6月1日から6月5日まで。"),
            "请留意，申请窗口是2026年6月1日到6月5日。",
            ClaimKind.REVIEWED_RULE,
            (),
        ),
        (
            "我还没填考试日期，现在能判断吗？",
            ClaimableProposition(
                proposition_id="proposition:0001",
                obligation_ids=("subquestion:01",),
                predicate=PropositionPredicate.MISSING_APPLICANT_INFORMATION,
                subject="考试日期",
                missing_fields=("exam_date",),
            ),
            None,
            "请先告诉我考试日期，之后才能继续核对。",
            ClaimKind.REVIEWED_DISPOSITION,
            ("exam_date",),
        ),
    )
    for question, proposition, evidence, text, kind, missing_information in cases:
        claim = GeneratedClaim(
            claim_id="claim:0001",
            kind=kind,
            text=text,
            evidence_ids=proposition.evidence_ids,
            finding_ids=(proposition.proposition_id,),
        )
        draft = GenerationDraft(
            answer=text,
            claims=(claim,),
            missing_information=missing_information,
            needs_review=kind is ClaimKind.REVIEWED_DISPOSITION,
            refused=False,
        )

        result = run_consolidated_grounded_rag(
            DeterministicFakeGenerationProvider(draft),
            request_id="request:reset-guide",
            question=question,
            target=GenerationTarget(
                application_label="Science Tokyo / 情報工学系",
                scope_targets=("情報工学系",),
                parent_college="情報理工学院",
            ),
            evidence=(() if evidence is None else (evidence,)),
            propositions=(proposition,),
        )

        assert result.answer == text
        assert result.claims[0].kind is kind
        assert result.missing_information == missing_information


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
