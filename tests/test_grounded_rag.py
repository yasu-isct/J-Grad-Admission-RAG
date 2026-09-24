from __future__ import annotations

import json

import pytest

from jgrad_admission_rag.generation import (
    ApplicantFact,
    ClaimKind,
    DeterministicFakeGenerationProvider,
    GeneratedClaim,
    GenerationDraft,
    GenerationError,
    GenerationErrorCode,
    GenerationLimitation,
    GenerationProviderIdentity,
    GroundedRagError,
    GroundedRagErrorCode,
    GroundedRagTarget,
    canonical_grounded_answer_bytes,
    run_grounded_rag,
)
from jgrad_admission_rag.reasoning.applicability import (
    ApplicabilityStatus,
    EvidenceRole as ReviewedEvidenceRole,
    RuleScope,
)
from jgrad_admission_rag.reasoning.cited_answer import (
    AnswerCitation,
    CitedAnswer,
    InteractionAnswerWarning,
    MissingInformationEntry,
    ReportStatus,
    RuleFinding,
)
from jgrad_admission_rag.reasoning.cited_answer import _citation_inventory, _warning_id
from jgrad_admission_rag.reasoning.rule_interaction import InteractionCertainty
from jgrad_admission_rag.reasoning.rule_resolution import ResolutionDisposition
from jgrad_admission_rag.schemas.evidence_pack import (
    AttachedReferenceEvidence,
    EvidenceCounts,
    EvidenceMetadataFilter,
    EvidencePack,
    EvidenceRequest,
    EvidenceRuntime,
    EvidenceScopePreference,
    IncomingRelation,
    PrimaryEvidence,
    ResolvedReferenceRelation,
)

KB_HASH = "a" * 64
PDF_HASH = "b" * 64
DOCUMENT_ID = "doc"
RULE_ID = "rule:one"
FINDING_ID = f"finding:{RULE_ID}"


class _RecordingDraftProvider:
    identity = GenerationProviderIdentity(provider="recording", model="recording")

    def __init__(self, draft: GenerationDraft) -> None:
        self.draft = draft
        self.calls = 0

    def generate(self, request: object) -> GenerationDraft:
        del request
        self.calls += 1
        return self.draft


def _runtime() -> EvidenceRuntime:
    return EvidenceRuntime(
        document_id=DOCUMENT_ID,
        source_kb_sha256=KB_HASH,
        source_pdf_sha256=PDF_HASH,
        index_schema_version="0.1",
        source_kb_schema_version="0.5",
        payloads_sha256="c" * 64,
        vectors_sha256="d" * 64,
        index_builder_version="0.1.0",
        embedding_provider="deterministic-fake",
        embedding_model="sha256-counter-v1",
        embedding_dimension=8,
        distance_metric="cosine",
        semantic=False,
        lexical_tokenizer_version="nfkc-casefold-ja23-v1",
        lexical_scoring_version="bm25-v1",
        fusion_version="rrf-v1",
        rrf_k=60,
        metadata_filter_version="exact-metadata-v1",
        scope_rerank_version="scope-match-v1",
        scope_target_match_boost=0.0,
        parent_college_match_boost=0.0,
        reference_expansion_version="reference-one-hop-v1",
        reference_expansion_depth=1,
        corpus_row_count=2,
        eligible_row_count=2,
        vector_candidate_count=2,
        lexical_candidate_count=2,
    )


def _pack(*, empty: bool = False) -> EvidencePack:
    request = EvidenceRequest(
        query="中国語の質問",
        top_k_requested=1,
        candidate_k_requested=2,
        candidate_k_resolved=2,
        metadata_filter=EvidenceMetadataFilter(),
        scope_preference=EvidenceScopePreference(),
    )
    if empty:
        return EvidencePack(
            request=request,
            runtime=_runtime(),
            primary_evidence=(),
            attached_reference_evidence=(),
            resolved_relations=(),
            reference_warnings=(),
            counts=EvidenceCounts(
                primary_evidence_count=0,
                attached_evidence_count=0,
                resolved_relation_count=0,
                warning_count=0,
                warning_status_counts={"ambiguous": 0, "unresolved": 0},
                unique_evidence_count=0,
            ),
        )
    primary = PrimaryEvidence(
        primary_rank=1,
        ranking_score=2 / 61,
        fused_score=2 / 61,
        scope_boost_total=0.0,
        fusion_version="rrf-v1",
        vector_rank=1,
        vector_score=0.9,
        lexical_rank=1,
        lexical_score=2.0,
        matched_channels=("vector", "lexical"),
        row_index=0,
        document_id=DOCUMENT_ID,
        unit_id="unit:primary",
        fact_id="fact:primary",
        text="Primary official evidence",
        source_pages=(1,),
        section_path=("募集要項", "日程"),
        fact_type="date",
        scope_type="global",
    )
    incoming = IncomingRelation(
        source_primary_rank=1,
        source_fact_id=primary.fact_id,
        label="参照",
        reference_key="attached",
        direction="forward",
    )
    attached = AttachedReferenceEvidence(
        row_index=1,
        document_id=DOCUMENT_ID,
        unit_id="unit:attached",
        fact_id="fact:attached",
        text="Attached official evidence",
        source_pages=(2,),
        section_path=("募集要項", "資格"),
        fact_type="eligibility",
        scope_type="global",
        incoming_relations=(incoming,),
    )
    relation = ResolvedReferenceRelation(
        source_primary_rank=1,
        source_claim_index=0,
        source_fact_id=primary.fact_id,
        label="参照",
        reference_key="attached",
        direction="forward",
        selected_target_fact_id=attached.fact_id,
        candidate_target_fact_ids=(attached.fact_id,),
        reason="unique_match",
        disposition="attached_target",
        target_row_index=1,
    )
    return EvidencePack(
        request=request,
        runtime=_runtime(),
        primary_evidence=(primary,),
        attached_reference_evidence=(attached,),
        resolved_relations=(relation,),
        reference_warnings=(),
        counts=EvidenceCounts(
            primary_evidence_count=1,
            attached_evidence_count=1,
            resolved_relation_count=1,
            warning_count=0,
            warning_status_counts={"ambiguous": 0, "unresolved": 0},
            unique_evidence_count=2,
        ),
    )


def _scoped_pack(
    *, scope_target: str | None = None, parent_college: str | None = None
) -> EvidencePack:
    payload = _pack().model_dump(mode="json")
    if scope_target is not None:
        payload["request"]["metadata_filter"]["scope_targets"] = [scope_target]
    if parent_college is not None:
        payload["request"]["metadata_filter"]["parent_colleges"] = [parent_college]
    scope_type = "program" if scope_target is not None else "college"
    for collection in ("primary_evidence", "attached_reference_evidence"):
        for record in payload[collection]:
            record["scope_type"] = scope_type
            record["scope_targets"] = [scope_target] if scope_target is not None else []
            record["parent_college"] = parent_college
    return EvidencePack.model_validate(payload)


def _cited_answer(
    *,
    status: ApplicabilityStatus = ApplicabilityStatus.CONFIRMED,
    document_id: str = DOCUMENT_ID,
    primary_role: ReviewedEvidenceRole = ReviewedEvidenceRole.PRIMARY,
    primary_fact_id: str = "fact:primary",
    scope: RuleScope | None = None,
) -> CitedAnswer:
    disposition = {
        ApplicabilityStatus.CONFIRMED: ResolutionDisposition.ACTIVE,
        ApplicabilityStatus.NOT_APPLICABLE: ResolutionDisposition.NOT_APPLICABLE,
        ApplicabilityStatus.NEEDS_INFORMATION: ResolutionDisposition.PENDING,
    }[status]
    citations = tuple(
        sorted(
            (
                AnswerCitation(
                    document_id=document_id,
                    fact_id=primary_fact_id,
                    source_pages=(1,),
                    role=primary_role,
                    source_rule_id=RULE_ID,
                    source_step_ids=(f"applicability:{RULE_ID}", f"resolution:{RULE_ID}"),
                ),
                AnswerCitation(
                    document_id=document_id,
                    fact_id="fact:attached",
                    source_pages=(2,),
                    role=ReviewedEvidenceRole.ATTACHED,
                    source_rule_id=RULE_ID,
                    source_step_ids=(f"applicability:{RULE_ID}", f"resolution:{RULE_ID}"),
                ),
            ),
            key=lambda item: item.fact_id,
        )
    )
    finding = RuleFinding(
        finding_id=FINDING_ID,
        rule_id=RULE_ID,
        subject_key="eligibility",
        scope=scope or RuleScope(scope_type="global"),
        original_status=status,
        disposition=disposition,
        source_applicability_step_id=f"applicability:{RULE_ID}",
        source_resolution_step_id=f"resolution:{RULE_ID}",
        citations=citations,
    )
    missing = (
        (
            MissingInformationEntry(
                rule_id=RULE_ID,
                field_path="academic.expected_completion_date",
                source_applicability_step_id=f"applicability:{RULE_ID}",
                source_resolution_step_id=f"resolution:{RULE_ID}",
            ),
        )
        if status is ApplicabilityStatus.NEEDS_INFORMATION
        else ()
    )
    return CitedAnswer(
        answer_id="answer:one",
        source_trace_id="trace:one",
        document_id=document_id,
        source_kb_sha256=KB_HASH,
        source_pdf_sha256=PDF_HASH,
        report_status=(
            ReportStatus.NEEDS_INFORMATION
            if status is ApplicabilityStatus.NEEDS_INFORMATION
            else ReportStatus.COMPLETE
        ),
        interaction_analysis_complete=True,
        source_rule_ids=(RULE_ID,),
        source_trace_step_ids=(f"applicability:{RULE_ID}", f"resolution:{RULE_ID}"),
        rule_findings=(finding,),
        interaction_warnings=(),
        missing_information=missing,
        process_notices=(),
        citation_inventory=citations,
    )


def _draft(*, needs_review: bool = False, missing: tuple[str, ...] = ()) -> GenerationDraft:
    claims = (
        GeneratedClaim(
            claim_id="claim:0001",
            kind=ClaimKind.OFFICIAL_FACT,
            text="draft official",
            evidence_ids=("evidence:0001",),
        ),
        GeneratedClaim(
            claim_id="claim:0002",
            kind=ClaimKind.REVIEWED_RULE,
            text="draft rule",
            evidence_ids=("evidence:0001", "evidence:0002"),
            finding_ids=(FINDING_ID,),
        ),
        GeneratedClaim(
            claim_id="claim:0003",
            kind=ClaimKind.APPLICANT_STATEMENT,
            text="draft applicant",
            applicant_fact_paths=("profile.status",),
        ),
    )
    return GenerationDraft(
        answer="\n".join(item.text for item in claims),
        claims=claims,
        missing_information=missing,
        needs_review=needs_review,
        refused=False,
    )


def _warning_answer() -> CitedAnswer:
    rule_ids = ("rule:one", "rule:two")
    base_citations = (
        AnswerCitation(
            document_id=DOCUMENT_ID,
            fact_id="fact:primary",
            source_pages=(1,),
            role=ReviewedEvidenceRole.PRIMARY,
            source_rule_id=rule_ids[0],
            source_step_ids=("applicability:rule:one", "resolution:rule:one"),
        ),
        AnswerCitation(
            document_id=DOCUMENT_ID,
            fact_id="fact:attached",
            source_pages=(2,),
            role=ReviewedEvidenceRole.ATTACHED,
            source_rule_id=rule_ids[1],
            source_step_ids=("applicability:rule:two", "resolution:rule:two"),
        ),
    )
    findings = tuple(
        RuleFinding(
            finding_id=f"finding:{rule_id}",
            rule_id=rule_id,
            subject_key="eligibility",
            scope=RuleScope(scope_type="global"),
            original_status=ApplicabilityStatus.CONFIRMED,
            disposition=ResolutionDisposition.ACTIVE,
            source_applicability_step_id=f"applicability:{rule_id}",
            source_resolution_step_id=f"resolution:{rule_id}",
            citations=(citation,),
        )
        for rule_id, citation in zip(rule_ids, base_citations, strict=True)
    )
    pair_id = json.dumps(["eligibility", *rule_ids], separators=(",", ":"))
    interaction_step = f"interaction:{pair_id}"
    warning_citations = tuple(
        sorted(
            (
                citation.model_copy(
                    update={
                        "source_step_ids": tuple(
                            sorted((f"resolution:{citation.source_rule_id}", interaction_step))
                        )
                    }
                )
                for citation in base_citations
            ),
            key=lambda item: item.fact_id,
        )
    )
    warning = InteractionAnswerWarning(
        warning_id=_warning_id(pair_id),
        pair_id=pair_id,
        kind="conflict",
        certainty=InteractionCertainty.CONFIRMED,
        rule_ids=rule_ids,
        source_interaction_step_id=interaction_step,
        citations=warning_citations,
    )
    inventory = _citation_inventory(findings, (warning,))
    return CitedAnswer(
        answer_id="answer:warning",
        source_trace_id="trace:warning",
        document_id=DOCUMENT_ID,
        source_kb_sha256=KB_HASH,
        source_pdf_sha256=PDF_HASH,
        report_status=ReportStatus.NEEDS_REVIEW,
        interaction_analysis_complete=True,
        source_rule_ids=rule_ids,
        source_trace_step_ids=(
            "applicability:rule:one",
            "applicability:rule:two",
            "resolution:rule:one",
            "resolution:rule:two",
            interaction_step,
        ),
        rule_findings=findings,
        interaction_warnings=(warning,),
        missing_information=(),
        process_notices=(),
        citation_inventory=inventory,
    )


def _run(
    draft: GenerationDraft | None = None,
    *,
    pack: EvidencePack | None = None,
    answer: CitedAnswer | None = None,
    target: GroundedRagTarget | None = None,
    provider: object | None = None,
):
    return run_grounded_rag(
        provider or DeterministicFakeGenerationProvider(draft),
        request_id="request:one",
        target=target or GroundedRagTarget(document_id=DOCUMENT_ID, application_label="target"),
        applicant_facts=(ApplicantFact(field_path="profile.status", value="synthetic"),),
        evidence_pack=pack or _pack(),
        cited_answer=answer or _cited_answer(),
    )


def test_orchestrator_hydrates_authoritative_primary_and_reference_citations() -> None:
    result = _run(_draft())
    assert result.document_id == DOCUMENT_ID
    assert result.source_kb_sha256 == KB_HASH
    assert result.source_pdf_sha256 == PDF_HASH
    assert result.reviewed_state == _cited_answer()
    assert result.claims[0].citations[0].fact_id == "fact:primary"
    assert {item.fact_id for item in result.claims[1].citations} == {
        "fact:primary",
        "fact:attached",
    }
    assert {item.role.value for item in result.claims[1].citations} == {
        "primary",
        "reference",
    }
    assert result.claims[2].citations == ()
    assert result.claims[2].applicant_fact_paths == ("profile.status",)
    assert "draft" not in result.answer


def test_orchestrator_is_byte_deterministic() -> None:
    first = canonical_grounded_answer_bytes(_run(_draft()))
    second = canonical_grounded_answer_bytes(_run(_draft()))
    assert first == second


@pytest.mark.parametrize(
    "answer",
    (
        _cited_answer(document_id="foreign-doc"),
        _cited_answer(primary_role=ReviewedEvidenceRole.ATTACHED),
        _cited_answer(primary_fact_id="fact:foreign"),
        _cited_answer().model_copy(update={"source_kb_sha256": "e" * 64}),
    ),
)
def test_orchestrator_rejects_foreign_identity_and_role(answer: CitedAnswer) -> None:
    with pytest.raises(GroundedRagError) as caught:
        _run(_draft(), answer=answer)
    assert caught.value.code is GroundedRagErrorCode.EVIDENCE_MISMATCH


def test_orchestrator_rejects_tampered_pages_before_provider_call() -> None:
    pack = _pack()
    tampered_primary = pack.primary_evidence[0].model_copy(update={"source_pages": (9,)})
    tampered_pack = pack.model_copy(update={"primary_evidence": (tampered_primary,)})

    class MustNotRun:
        identity = GenerationProviderIdentity(provider="never", model="never")

        def generate(self, request: object) -> GenerationDraft:
            del request
            raise AssertionError("provider must not run")

    with pytest.raises(GroundedRagError) as caught:
        run_grounded_rag(
            MustNotRun(),
            request_id="request:one",
            target=GroundedRagTarget(document_id=DOCUMENT_ID, application_label="target"),
            applicant_facts=(),
            evidence_pack=tampered_pack,
            cited_answer=_cited_answer(),
        )
    assert caught.value.code is GroundedRagErrorCode.EVIDENCE_MISMATCH


@pytest.mark.parametrize(
    "target",
    (
        GroundedRagTarget(document_id="foreign-doc", application_label="target"),
        GroundedRagTarget(
            document_id=DOCUMENT_ID,
            application_label="target",
            scope_targets=("different-program",),
        ),
    ),
)
def test_orchestrator_rejects_target_mismatch_before_provider_call(
    target: GroundedRagTarget,
) -> None:
    with pytest.raises(GroundedRagError) as caught:
        run_grounded_rag(
            DeterministicFakeGenerationProvider(_draft()),
            request_id="request:one",
            target=target,
            applicant_facts=(),
            evidence_pack=_pack(),
            cited_answer=_cited_answer(),
        )
    assert caught.value.code is GroundedRagErrorCode.EVIDENCE_MISMATCH


def test_orchestrator_rejects_parent_college_mismatch_before_provider_call() -> None:
    pack = _scoped_pack(parent_college="Foreign College")
    provider = _RecordingDraftProvider(_draft())
    with pytest.raises(GroundedRagError) as caught:
        _run(
            pack=pack,
            provider=provider,
            target=GroundedRagTarget(
                document_id=DOCUMENT_ID,
                application_label="target",
                parent_college="Selected College",
            ),
        )
    assert caught.value.code is GroundedRagErrorCode.EVIDENCE_MISMATCH
    assert provider.calls == 0


def test_orchestrator_accepts_matching_parent_college_and_reviewed_scope() -> None:
    college = "Selected College"
    result = _run(
        _draft(),
        pack=_scoped_pack(parent_college=college),
        answer=_cited_answer(scope=RuleScope(scope_type="college", scope_targets=(college,))),
        target=GroundedRagTarget(
            document_id=DOCUMENT_ID,
            application_label="target",
            parent_college=college,
        ),
    )
    assert result.reviewed_state.rule_findings[0].scope.scope_targets == (college,)


def test_orchestrator_rejects_confirmed_finding_for_different_program() -> None:
    pack = _scoped_pack(scope_target="program:B")
    target = GroundedRagTarget(
        document_id=DOCUMENT_ID,
        application_label="target",
        scope_targets=("program:B",),
    )
    wrong_scope = RuleScope(scope_type="program", scope_targets=("program:A",))
    provider = _RecordingDraftProvider(_draft())
    with pytest.raises(GroundedRagError) as caught:
        _run(
            pack=pack,
            answer=_cited_answer(scope=wrong_scope),
            target=target,
            provider=provider,
        )
    assert caught.value.code is GroundedRagErrorCode.EVIDENCE_MISMATCH
    assert provider.calls == 0


def test_orchestrator_preserves_explicit_not_applicable_scope_mismatch() -> None:
    pack = _scoped_pack(scope_target="program:B")
    target = GroundedRagTarget(
        document_id=DOCUMENT_ID,
        application_label="target",
        scope_targets=("program:B",),
    )
    other_scope = RuleScope(scope_type="program", scope_targets=("program:A",))
    result = _run(
        _draft(),
        pack=pack,
        answer=_cited_answer(status=ApplicabilityStatus.NOT_APPLICABLE, scope=other_scope),
        target=target,
    )
    assert "original_status=not_applicable" in result.claims[1].text
    assert "scope_targets=program:A" in result.claims[1].text


def test_orchestrator_rejects_unknown_evidence_and_missing_finding() -> None:
    unknown = GeneratedClaim(
        claim_id="claim:0001",
        kind=ClaimKind.OFFICIAL_FACT,
        text="draft",
        evidence_ids=("evidence:9999",),
    )
    draft = GenerationDraft(
        answer=unknown.text,
        claims=(unknown,),
        needs_review=False,
        refused=False,
    )
    with pytest.raises(GroundedRagError) as caught:
        _run(draft)
    assert caught.value.code is GroundedRagErrorCode.INVALID_CITATION

    official_only = _draft().model_copy(
        update={"claims": (_draft().claims[0],), "answer": "draft official"}
    )
    with pytest.raises(GroundedRagError) as caught:
        _run(official_only)
    assert caught.value.code is GroundedRagErrorCode.RULE_STATE_MISMATCH


def test_orchestrator_rejects_unsupported_multi_evidence_official_claim() -> None:
    claim = GeneratedClaim(
        claim_id="claim:0001",
        kind=ClaimKind.OFFICIAL_FACT,
        text="draft",
        evidence_ids=("evidence:0001", "evidence:0002"),
    )
    draft = GenerationDraft(
        answer=claim.text,
        claims=(claim,),
        needs_review=False,
        refused=False,
    )
    with pytest.raises(GroundedRagError) as caught:
        _run(draft)
    assert caught.value.code is GroundedRagErrorCode.UNSUPPORTED_CLAIM


def test_orchestrator_preserves_pending_and_missing_state() -> None:
    missing = ("academic.expected_completion_date",)
    pending_answer = _cited_answer(status=ApplicabilityStatus.NEEDS_INFORMATION)
    result = _run(_draft(needs_review=True, missing=missing), answer=pending_answer)
    assert result.needs_review is True
    assert result.missing_information == missing
    assert "[needs_information]" in result.claims[1].text

    with pytest.raises(GroundedRagError) as caught:
        _run(_draft(needs_review=False, missing=missing), answer=pending_answer)
    assert caught.value.code is GroundedRagErrorCode.RULE_STATE_MISMATCH


def test_orchestrator_projects_citable_interaction_warning_as_required_review() -> None:
    captured = None

    class RecordingProvider:
        identity = GenerationProviderIdentity(provider="recording", model="recording")

        def generate(self, request):
            nonlocal captured
            captured = request
            return GenerationDraft(
                answer="",
                limitations=(GenerationLimitation.NEEDS_REVIEW,),
                needs_review=True,
                refused=False,
            )

    result = run_grounded_rag(
        RecordingProvider(),
        request_id="request:warning",
        target=GroundedRagTarget(document_id=DOCUMENT_ID, application_label="target"),
        applicant_facts=(),
        evidence_pack=_pack(),
        cited_answer=_warning_answer(),
    )
    assert captured is not None
    warning_finding = next(
        item for item in captured.rule_findings if item.finding_id.startswith("finding:warning:")
    )
    assert warning_finding.status == "needs_review"
    assert warning_finding.evidence_ids == ("evidence:0001", "evidence:0002")
    assert result.reviewed_state.report_status is ReportStatus.NEEDS_REVIEW
    assert result.needs_review is True


def test_orchestrator_rejects_insufficient_evidence_before_provider() -> None:
    with pytest.raises(GroundedRagError) as caught:
        _run(_draft(), pack=_pack(empty=True))
    assert caught.value.code is GroundedRagErrorCode.INSUFFICIENT_EVIDENCE


def test_orchestrator_maps_provider_failure_without_payload_or_context() -> None:
    secret = "PRIVATE_PROVIDER_PAYLOAD"

    class BrokenProvider:
        identity = GenerationProviderIdentity(provider="broken", model="broken")

        def generate(self, request: object) -> GenerationDraft:
            del request
            raise RuntimeError(secret)

    with pytest.raises(GroundedRagError) as caught:
        run_grounded_rag(
            BrokenProvider(),
            request_id="request:one",
            target=GroundedRagTarget(document_id=DOCUMENT_ID, application_label="target"),
            applicant_facts=(),
            evidence_pack=_pack(),
            cited_answer=_cited_answer(),
        )
    assert caught.value.code is GroundedRagErrorCode.PROVIDER_UNAVAILABLE
    assert secret not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    ("generation_code", "grounded_code"),
    (
        (GenerationErrorCode.PROVIDER_TIMEOUT, GroundedRagErrorCode.PROVIDER_TIMEOUT),
        (GenerationErrorCode.PROVIDER_REFUSAL, GroundedRagErrorCode.PROVIDER_REFUSAL),
        (GenerationErrorCode.INCOMPLETE_RESPONSE, GroundedRagErrorCode.INCOMPLETE_RESPONSE),
        (GenerationErrorCode.MALFORMED_OUTPUT, GroundedRagErrorCode.MALFORMED_OUTPUT),
    ),
)
def test_orchestrator_preserves_stable_provider_failure_classification(
    generation_code: GenerationErrorCode,
    grounded_code: GroundedRagErrorCode,
) -> None:
    class FailingProvider:
        identity = GenerationProviderIdentity(provider="failing", model="failing")

        def generate(self, request: object) -> GenerationDraft:
            del request
            raise GenerationError(generation_code)

    with pytest.raises(GroundedRagError) as caught:
        run_grounded_rag(
            FailingProvider(),
            request_id="request:one",
            target=GroundedRagTarget(document_id=DOCUMENT_ID, application_label="target"),
            applicant_facts=(),
            evidence_pack=_pack(),
            cited_answer=_cited_answer(),
        )
    assert caught.value.code is grounded_code
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_default_fake_returns_explicit_uncited_abstention() -> None:
    result = _run()
    assert result.answer == ""
    assert result.claims == ()
    assert result.citation_inventory == ()
    assert result.needs_review is True
    assert result.limitations == (GenerationLimitation.PROVIDER_NOT_CALLED,)
