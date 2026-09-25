"""One-call natural answer generation over server-owned typed propositions."""

from __future__ import annotations

import unicodedata
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .contracts import (
    ClaimKind,
    GeneratedClaim,
    GenerationEvidence,
    GenerationModel,
    GenerationProviderIdentity,
    GenerationDraft,
    GenerationRequest,
    GenerationRuleFinding,
    GenerationTarget,
)
from .grounded_rag import GroundedCitation, GroundedModel
from .provider import GenerationProvider, generate_checked

CONSOLIDATED_PIPELINE_VERSION = "consolidated-natural-answer-v1"
CLAIM_SEMANTICS_VERSION = "typed-claim-semantics-v1"
MAX_CONSOLIDATED_EVIDENCE_RECORDS = 16
MAX_CONSOLIDATED_EVIDENCE_CHARACTERS = 60_000
_CHARACTER_NORMALIZATION = str.maketrans({"資": "资", "報": "报", "語": "语", "滿": "满"})


class PropositionPredicate(str, Enum):
    MAXIMUM_POINTS = "maximum_points"
    EXAM_LISTED = "exam_listed"
    EXACT_EVIDENCE = "exact_evidence"


class ConsolidatedEvidenceRecord(GenerationModel):
    evidence: GenerationEvidence
    document_id: str
    fact_id: str
    source_pages: tuple[int, ...]
    source_kb_sha256: str
    source_pdf_sha256: str
    scope_type: Literal["global", "university", "college", "department", "program", "unknown"]
    scope_targets: tuple[str, ...] = ()
    parent_college: str | None = None

    def citation(self) -> GroundedCitation:
        return GroundedCitation(
            evidence_id=self.evidence.evidence_id,
            document_id=self.document_id,
            fact_id=self.fact_id,
            source_pages=self.source_pages,
            role=self.evidence.role,
            source_kb_sha256=self.source_kb_sha256,
            source_pdf_sha256=self.source_pdf_sha256,
        )


class ClaimableProposition(GenerationModel):
    proposition_id: str = Field(pattern=r"^proposition:[0-9]{4}$")
    obligation_ids: tuple[str, ...] = Field(min_length=1)
    predicate: PropositionPredicate
    subject: str = Field(min_length=1, max_length=500)
    numeric_value: int | None = Field(default=None, ge=0, le=100_000, strict=True)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    exact_evidence_text: str | None = Field(default=None, min_length=1, max_length=20_000)

    @model_validator(mode="after")
    def predicate_fields_must_reconcile(self) -> ClaimableProposition:
        if self.predicate is PropositionPredicate.MAXIMUM_POINTS:
            if self.numeric_value is None or self.exact_evidence_text is not None:
                raise ValueError("maximum-points proposition requires only a numeric value")
        elif self.predicate is PropositionPredicate.EXAM_LISTED:
            if self.numeric_value is not None or self.exact_evidence_text is not None:
                raise ValueError("exam-listed proposition cannot carry a value or exact text")
        elif self.numeric_value is not None or self.exact_evidence_text is None:
            raise ValueError("exact-evidence proposition requires only exact evidence text")
        if self.obligation_ids != tuple(sorted(set(self.obligation_ids))):
            raise ValueError("obligation IDs must be sorted and unique")
        if self.evidence_ids != tuple(sorted(set(self.evidence_ids))):
            raise ValueError("proposition evidence IDs must be sorted and unique")
        return self


class ConsolidatedGroundedClaim(GroundedModel):
    claim_id: str
    kind: Literal[ClaimKind.REVIEWED_RULE] = ClaimKind.REVIEWED_RULE
    text: str = Field(min_length=1, max_length=25_000)
    citations: tuple[GroundedCitation, ...] = Field(min_length=1)
    obligation_ids: tuple[str, ...] = Field(min_length=1)


class ConsolidatedGroundedAnswer(GroundedModel):
    answer: str = Field(max_length=200_000)
    provider: GenerationProviderIdentity
    claims: tuple[ConsolidatedGroundedClaim, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def answer_must_match_claims(self) -> ConsolidatedGroundedAnswer:
        if self.answer != "\n".join(item.text for item in self.claims):
            raise ValueError("consolidated answer must equal ordered claim text")
        return self


def run_consolidated_grounded_rag(
    provider: GenerationProvider,
    *,
    request_id: str,
    question: str,
    target: GenerationTarget,
    evidence: tuple[ConsolidatedEvidenceRecord, ...],
    propositions: tuple[ClaimableProposition, ...],
) -> ConsolidatedGroundedAnswer:
    if not evidence or not propositions:
        raise ValueError("consolidated generation requires evidence and propositions")
    if (
        len(evidence) > MAX_CONSOLIDATED_EVIDENCE_RECORDS
        or sum(len(item.evidence.text) + len(item.evidence.scope_label or "") for item in evidence)
        > MAX_CONSOLIDATED_EVIDENCE_CHARACTERS
    ):
        raise ValueError("consolidated evidence exceeds its hard bound")
    evidence_ids = tuple(item.evidence.evidence_id for item in evidence)
    if evidence_ids != tuple(f"evidence:{index:04d}" for index in range(1, len(evidence) + 1)):
        raise ValueError("consolidated evidence IDs must be contiguous")
    evidence_by_id = {item.evidence.evidence_id: item for item in evidence}
    source_identities = {
        (item.document_id, item.source_kb_sha256, item.source_pdf_sha256) for item in evidence
    }
    if len(source_identities) != 1:
        raise ValueError("consolidated evidence crosses source identities")
    if any(not _evidence_scope_matches_target(item, target) for item in evidence):
        raise ValueError("consolidated evidence crosses the requested target scope")
    if any(set(item.evidence_ids) - set(evidence_by_id) for item in propositions):
        raise ValueError("proposition cites unknown evidence")
    proposition_by_id = {item.proposition_id: item for item in propositions}
    if len(proposition_by_id) != len(propositions):
        raise ValueError("proposition IDs must be unique")
    for proposition in propositions:
        supporting_text = "\n".join(
            evidence_by_id[item].evidence.text for item in proposition.evidence_ids
        )
        if proposition.predicate is PropositionPredicate.EXACT_EVIDENCE:
            if proposition.exact_evidence_text not in {
                evidence_by_id[item].evidence.text for item in proposition.evidence_ids
            }:
                raise ValueError("exact proposition text is not authoritative evidence")
        elif proposition.predicate is PropositionPredicate.MAXIMUM_POINTS and str(
            proposition.numeric_value
        ) not in unicodedata.normalize("NFKC", supporting_text):
            raise ValueError("typed numeric proposition is absent from evidence")
        elif proposition.predicate is PropositionPredicate.EXAM_LISTED and (
            unicodedata.normalize("NFKC", proposition.subject).casefold()
            not in unicodedata.normalize("NFKC", supporting_text).casefold()
        ):
            raise ValueError("typed exam proposition is absent from evidence")

    request = GenerationRequest(
        request_id=request_id,
        question=question,
        target=target,
        rule_findings=tuple(
            GenerationRuleFinding(
                finding_id=proposition.proposition_id,
                status="confirmed",
                statement=_proposition_statement(proposition),
                evidence_ids=proposition.evidence_ids,
            )
            for proposition in propositions
        ),
        evidence=tuple(item.evidence for item in evidence),
    )
    checked_provider: GenerationProvider = provider
    if provider.identity.provider == "reviewed-state-offline":
        checked_provider = _ReviewedConsolidatedProvider(provider.identity, proposition_by_id)
    generated = generate_checked(
        checked_provider,
        request,
        claim_text_validator=lambda claim, _: _claim_matches_proposition(
            claim,
            proposition_by_id=proposition_by_id,
        ),
    )
    claims = tuple(
        _ground_claim(claim, proposition_by_id=proposition_by_id, evidence_by_id=evidence_by_id)
        for claim in generated.output.claims
    )
    return ConsolidatedGroundedAnswer(
        answer="\n".join(item.text for item in claims),
        provider=generated.provider,
        claims=claims,
    )


class _ReviewedConsolidatedProvider:
    """Explicit offline renderer; it is never presented as online model output."""

    def __init__(self, identity, propositions: dict[str, ClaimableProposition]) -> None:
        self.identity = identity
        self._propositions = propositions

    def generate(self, request: GenerationRequest) -> GenerationDraft:
        claims = tuple(
            GeneratedClaim(
                claim_id=f"claim:{index:04d}",
                kind=ClaimKind.REVIEWED_RULE,
                text=_offline_text(self._propositions[finding.finding_id]),
                evidence_ids=finding.evidence_ids,
                finding_ids=(finding.finding_id,),
            )
            for index, finding in enumerate(request.rule_findings, start=1)
        )
        return GenerationDraft(
            answer="\n".join(item.text for item in claims),
            claims=claims,
            needs_review=False,
            refused=False,
        )


def _offline_text(proposition: ClaimableProposition) -> str:
    if proposition.predicate is PropositionPredicate.MAXIMUM_POINTS:
        return f"{proposition.subject}的英语满分为{proposition.numeric_value}分。"
    if proposition.predicate is PropositionPredicate.EXAM_LISTED:
        return f"当前募集要项将{proposition.subject}列为英语外部考试之一。"
    assert proposition.exact_evidence_text is not None
    return proposition.exact_evidence_text


def _proposition_statement(proposition: ClaimableProposition) -> str:
    if proposition.predicate is PropositionPredicate.MAXIMUM_POINTS:
        return (
            f"predicate=maximum_points; subject={proposition.subject}; "
            f"value={proposition.numeric_value}; unit=points"
        )
    if proposition.predicate is PropositionPredicate.EXAM_LISTED:
        return f"predicate=exam_listed; subject={proposition.subject}"
    return f"predicate=exact_evidence; subject={proposition.subject}"


def _claim_matches_proposition(
    claim: GeneratedClaim,
    *,
    proposition_by_id: dict[str, ClaimableProposition],
) -> bool:
    if claim.kind is not ClaimKind.REVIEWED_RULE or len(claim.finding_ids) != 1:
        return False
    proposition = proposition_by_id.get(claim.finding_ids[0])
    if proposition is None or claim.evidence_ids != proposition.evidence_ids:
        return False
    if proposition.predicate is PropositionPredicate.EXACT_EVIDENCE:
        return claim.text == proposition.exact_evidence_text
    if proposition.predicate is PropositionPredicate.EXAM_LISTED:
        return _matches_exam_listed(claim.text, proposition)
    return _matches_maximum_points(claim.text, proposition)


def _matches_maximum_points(text: str, proposition: ClaimableProposition) -> bool:
    normalized = unicodedata.normalize("NFKC", text).casefold().translate(_CHARACTER_NORMALIZATION)
    subject = (
        unicodedata.normalize("NFKC", proposition.subject)
        .casefold()
        .translate(_CHARACTER_NORMALIZATION)
    )
    value = proposition.numeric_value
    allowed = {
        f"{subject}的英语满分为{value}分。",
        f"根据当前审核资料,{subject}的英语满分为{value}分。",
        f"{subject}では英语を{value}点満点で評価します。",
        f"{subject}の英语は{value}点満点です。",
        f"the maximum english score for {subject} is {value} points.",
    }
    return normalized in allowed


def _matches_exam_listed(text: str, proposition: ClaimableProposition) -> bool:
    normalized = unicodedata.normalize("NFKC", text).casefold().translate(_CHARACTER_NORMALIZATION)
    subject = unicodedata.normalize("NFKC", proposition.subject).casefold()
    allowed = {
        f"当前募集要项将{subject}列为英语外部考试之一。",
        f"根据当前审核资料，{subject}被列为英语外部考试之一。",
        f"現在の募集要項では、{subject}が英语外部試験の一つとして記載されています。",
        f"the current admission guidelines list {subject} as an external english test.",
    }
    return normalized in allowed


def _evidence_scope_matches_target(
    record: ConsolidatedEvidenceRecord,
    target: GenerationTarget,
) -> bool:
    if record.scope_type == "unknown":
        return False
    if record.scope_type in {"global", "university"}:
        return not record.scope_targets and record.parent_college is None
    if record.scope_type == "college":
        expected_colleges = set(record.scope_targets)
        if record.parent_college is not None:
            expected_colleges.add(record.parent_college)
        return target.parent_college in expected_colleges
    if not record.scope_targets or not set(record.scope_targets).intersection(target.scope_targets):
        return False
    return record.parent_college is None or record.parent_college == target.parent_college


def _ground_claim(
    claim: GeneratedClaim,
    *,
    proposition_by_id: dict[str, ClaimableProposition],
    evidence_by_id: dict[str, ConsolidatedEvidenceRecord],
) -> ConsolidatedGroundedClaim:
    proposition = proposition_by_id[claim.finding_ids[0]]
    citations = tuple(
        sorted(
            (evidence_by_id[item].citation() for item in proposition.evidence_ids),
            key=lambda item: (item.document_id, item.fact_id, item.source_pages),
        )
    )
    return ConsolidatedGroundedClaim(
        claim_id=claim.claim_id,
        text=claim.text,
        citations=citations,
        obligation_ids=proposition.obligation_ids,
    )


__all__ = [
    "CLAIM_SEMANTICS_VERSION",
    "CONSOLIDATED_PIPELINE_VERSION",
    "ClaimableProposition",
    "ConsolidatedEvidenceRecord",
    "ConsolidatedGroundedAnswer",
    "ConsolidatedGroundedClaim",
    "PropositionPredicate",
    "run_consolidated_grounded_rag",
]
