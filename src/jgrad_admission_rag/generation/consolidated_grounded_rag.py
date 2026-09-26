"""One-call natural answer generation over server-owned typed propositions."""

from __future__ import annotations

import re
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

CONSOLIDATED_PIPELINE_VERSION = "consolidated-natural-answer-v4"
CLAIM_SEMANTICS_VERSION = "protected-literal-claims-v4"
MAX_CONSOLIDATED_EVIDENCE_RECORDS = 16
MAX_CONSOLIDATED_EVIDENCE_CHARACTERS = 60_000
_CHARACTER_NORMALIZATION = str.maketrans(
    {"資": "资", "報": "报", "語": "语", "滿": "满", "點": "点", "錄": "录"}
)
_NUMBER_TOKEN = re.compile(r"(?<![A-Za-z])\d+(?:[./:-]\d+)*(?![A-Za-z])")
_EXAM_ENTITY_ALIASES = {
    "toeic_lr": ("toeic l&r", "toeic", "托业", "トーイック"),
    "toefl_ibt_home_edition": ("toefl ibt home edition", "toefl home edition"),
    "toefl_ibt": ("toefl ibt",),
    "toefl_itp": ("toefl itp",),
    "toeic_ip": ("toeic ip", "toeic-ip", "托业ip", "托业 ip", "トーイックip", "トーイック ip"),
    "jlpt": ("jlpt", "日本语能力考试", "日本語能力試験"),
    "j_test": ("j.test", "j-test", "j test"),
}


class PropositionPredicate(str, Enum):
    MAXIMUM_POINTS = "maximum_points"
    EXAM_LISTED = "exam_listed"
    DATE_RANGE = "date_range"
    EXAM_NORMALIZATION = "exam_normalization"
    UNPUBLISHED_SCORE_CONVERSION = "unpublished_score_conversion"
    NO_REVIEWED_EVIDENCE = "no_reviewed_evidence"
    MISSING_APPLICANT_INFORMATION = "missing_applicant_information"


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
    object: str | None = Field(default=None, min_length=1, max_length=500)
    numeric_value: int | None = Field(default=None, ge=0, le=100_000, strict=True)
    protected_literals: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()

    @model_validator(mode="after")
    def predicate_fields_must_reconcile(self) -> ClaimableProposition:
        if self.predicate is PropositionPredicate.MAXIMUM_POINTS:
            if self.numeric_value is None or self.object is not None or not self.evidence_ids:
                raise ValueError("maximum-points proposition requires evidence and a numeric value")
        elif self.predicate is PropositionPredicate.EXAM_LISTED:
            if self.numeric_value is not None or self.object is not None or not self.evidence_ids:
                raise ValueError("exam-listed proposition requires evidence and no value")
        elif self.predicate is PropositionPredicate.DATE_RANGE:
            if self.numeric_value is not None or self.object is not None or not self.evidence_ids:
                raise ValueError("date-range proposition requires evidence and protected dates")
            if len(self.protected_literals) < 2:
                raise ValueError("date-range proposition requires at least two protected dates")
        elif self.predicate is PropositionPredicate.EXAM_NORMALIZATION:
            if self.object is None or self.numeric_value is not None or self.evidence_ids:
                raise ValueError("exam normalization requires only source and canonical exam")
        elif self.predicate is PropositionPredicate.UNPUBLISHED_SCORE_CONVERSION:
            if self.object is None or self.evidence_ids:
                raise ValueError("unpublished conversion requires an exam and no evidence")
        elif self.predicate is PropositionPredicate.NO_REVIEWED_EVIDENCE and (
            self.object is not None or self.numeric_value is not None or self.evidence_ids
        ):
            raise ValueError("no-reviewed-evidence proposition cannot cite evidence or a value")
        elif self.predicate is PropositionPredicate.MISSING_APPLICANT_INFORMATION:
            if self.object is not None or self.numeric_value is not None or self.evidence_ids:
                raise ValueError("missing-information proposition cannot cite evidence or a value")
            if not self.missing_fields:
                raise ValueError("missing-information proposition requires missing fields")
        if (
            self.predicate is not PropositionPredicate.MISSING_APPLICANT_INFORMATION
            and self.missing_fields
        ):
            raise ValueError("only missing-information propositions carry missing fields")
        if self.obligation_ids != tuple(sorted(set(self.obligation_ids))):
            raise ValueError("obligation IDs must be sorted and unique")
        if self.evidence_ids != tuple(sorted(set(self.evidence_ids))):
            raise ValueError("proposition evidence IDs must be sorted and unique")
        if self.protected_literals != tuple(sorted(set(self.protected_literals))):
            raise ValueError("protected literals must be sorted and unique")
        if self.missing_fields != tuple(sorted(set(self.missing_fields))):
            raise ValueError("missing fields must be sorted and unique")
        return self


class ConsolidatedGroundedClaim(GroundedModel):
    claim_id: str
    kind: Literal[ClaimKind.REVIEWED_RULE, ClaimKind.REVIEWED_DISPOSITION]
    text: str = Field(min_length=1, max_length=25_000)
    citations: tuple[GroundedCitation, ...] = ()
    obligation_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def citations_must_match_kind(self) -> ConsolidatedGroundedClaim:
        if (self.kind is ClaimKind.REVIEWED_RULE) != bool(self.citations):
            raise ValueError("only reviewed-rule claims carry citations")
        return self


class ConsolidatedGroundedAnswer(GroundedModel):
    answer: str = Field(max_length=200_000)
    provider: GenerationProviderIdentity
    claims: tuple[ConsolidatedGroundedClaim, ...] = Field(min_length=1)
    missing_information: tuple[str, ...] = ()
    needs_review: bool

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
    if not propositions:
        raise ValueError("consolidated generation requires propositions")
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
    if evidence and len(source_identities) != 1:
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
        if proposition.predicate is PropositionPredicate.MAXIMUM_POINTS and str(
            proposition.numeric_value
        ) not in unicodedata.normalize("NFKC", supporting_text):
            raise ValueError("typed numeric proposition is absent from evidence")
        elif proposition.predicate is PropositionPredicate.EXAM_LISTED and (
            unicodedata.normalize("NFKC", proposition.subject).casefold()
            not in unicodedata.normalize("NFKC", supporting_text).casefold()
        ):
            raise ValueError("typed exam proposition is absent from evidence")
        elif proposition.predicate is PropositionPredicate.DATE_RANGE and any(
            _normalize(literal) not in _normalize(supporting_text)
            for literal in proposition.protected_literals
        ):
            raise ValueError("typed date proposition is absent from evidence")

    request = GenerationRequest(
        request_id=request_id,
        question=question,
        target=target,
        rule_findings=tuple(
            GenerationRuleFinding(
                finding_id=proposition.proposition_id,
                status=(
                    "confirmed" if proposition.evidence_ids else _disposition_status(proposition)
                ),
                statement=_proposition_statement(proposition),
                evidence_ids=proposition.evidence_ids,
                missing_fields=proposition.missing_fields,
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
        missing_information=generated.output.missing_information,
        needs_review=generated.output.needs_review,
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
                kind=(
                    ClaimKind.REVIEWED_RULE
                    if finding.evidence_ids
                    else ClaimKind.REVIEWED_DISPOSITION
                ),
                text=_offline_text(self._propositions[finding.finding_id]),
                evidence_ids=finding.evidence_ids,
                finding_ids=(finding.finding_id,),
            )
            for index, finding in enumerate(request.rule_findings, start=1)
        )
        return GenerationDraft(
            answer="\n".join(item.text for item in claims),
            claims=claims,
            missing_information=tuple(
                sorted(
                    field for finding in request.rule_findings for field in finding.missing_fields
                )
            ),
            needs_review=any(not finding.evidence_ids for finding in request.rule_findings),
            refused=False,
        )


def _offline_text(proposition: ClaimableProposition) -> str:
    if proposition.predicate is PropositionPredicate.MAXIMUM_POINTS:
        return f"{proposition.subject}的英语满分为{proposition.numeric_value}分。"
    if proposition.predicate is PropositionPredicate.EXAM_LISTED:
        return f"当前募集要项将{proposition.subject}列为英语外部考试之一。"
    if proposition.predicate is PropositionPredicate.DATE_RANGE:
        return f"{proposition.subject}的申请期间为{'至'.join(proposition.protected_literals)}。"
    if proposition.predicate is PropositionPredicate.EXAM_NORMALIZATION:
        return f"这里的“{proposition.subject}”按{proposition.object}理解。"
    if proposition.predicate is PropositionPredicate.UNPUBLISHED_SCORE_CONVERSION:
        score = f" {proposition.numeric_value} 分" if proposition.numeric_value is not None else ""
        return f"当前审核资料未公开{proposition.object}{score}到最终英语配点的换算关系。"
    if proposition.predicate is PropositionPredicate.MISSING_APPLICANT_INFORMATION:
        return f"还需要补充{proposition.subject}信息，才能继续判断。"
    return f"当前审核资料中未找到{proposition.subject}的要求或替代规则。"


def _proposition_statement(proposition: ClaimableProposition) -> str:
    if proposition.predicate is PropositionPredicate.MAXIMUM_POINTS:
        return (
            f"predicate=maximum_points; subject={proposition.subject}; "
            f"value={proposition.numeric_value}; unit=points"
        )
    if proposition.predicate is PropositionPredicate.EXAM_LISTED:
        return f"predicate=exam_listed; subject={proposition.subject}"
    if proposition.predicate is PropositionPredicate.DATE_RANGE:
        return (
            f"predicate=date_range; subject={proposition.subject}; "
            f"protected_literals={','.join(proposition.protected_literals)}"
        )
    if proposition.predicate is PropositionPredicate.EXAM_NORMALIZATION:
        return (
            f"predicate=exam_normalization; source={proposition.subject}; "
            f"canonical={proposition.object}"
        )
    if proposition.predicate is PropositionPredicate.UNPUBLISHED_SCORE_CONVERSION:
        return (
            f"predicate=unpublished_score_conversion; exam={proposition.object}; "
            f"score={proposition.numeric_value}"
        )
    if proposition.predicate is PropositionPredicate.MISSING_APPLICANT_INFORMATION:
        return (
            f"predicate=missing_applicant_information; subject={proposition.subject}; "
            f"missing_fields={','.join(proposition.missing_fields)}"
        )
    return f"predicate=no_reviewed_evidence; subject={proposition.subject}"


def _claim_matches_proposition(
    claim: GeneratedClaim,
    *,
    proposition_by_id: dict[str, ClaimableProposition],
) -> bool:
    if len(claim.finding_ids) != 1:
        return False
    proposition = proposition_by_id.get(claim.finding_ids[0])
    if proposition is None or claim.evidence_ids != proposition.evidence_ids:
        return False
    expected_kind = (
        ClaimKind.REVIEWED_RULE if proposition.evidence_ids else ClaimKind.REVIEWED_DISPOSITION
    )
    if claim.kind is not expected_kind:
        return False
    return _preserves_protected_literals(claim.text, proposition)


def _preserves_protected_literals(text: str, proposition: ClaimableProposition) -> bool:
    """Check only server-owned literals; free-text semantics remain a generation/eval concern."""

    normalized = _normalize(text)
    expected_numbers = tuple(
        token
        for value in (
            *proposition.protected_literals,
            *((str(proposition.numeric_value),) if proposition.numeric_value is not None else ()),
        )
        for token in _numbers(_normalize(value))
    )
    if _numbers(normalized) != expected_numbers:
        return False
    required_literal_groups: list[frozenset[str]] = []
    if proposition.predicate in {
        PropositionPredicate.MAXIMUM_POINTS,
        PropositionPredicate.EXAM_LISTED,
        PropositionPredicate.EXAM_NORMALIZATION,
        PropositionPredicate.NO_REVIEWED_EVIDENCE,
        PropositionPredicate.MISSING_APPLICANT_INFORMATION,
    }:
        required_literal_groups.append(_subject_aliases(proposition.subject))
    if proposition.object is not None:
        required_literal_groups.append(_subject_aliases(proposition.object))
    required_literal_groups.extend(
        frozenset({_normalize(literal)}) for literal in proposition.protected_literals
    )
    if any(
        not any(literal in normalized for literal in group) for group in required_literal_groups
    ):
        return False
    expected_exams = _exam_entities(
        " ".join(
            item
            for item in (proposition.subject, proposition.object, *proposition.protected_literals)
            if item is not None
        )
    )
    mentioned_exams = _exam_entities(text)
    return mentioned_exams == expected_exams


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().translate(_CHARACTER_NORMALIZATION)


def _numbers(value: str) -> tuple[str, ...]:
    return tuple(_NUMBER_TOKEN.findall(value))


def _subject_aliases(subject: str) -> frozenset[str]:
    normalized = _normalize(subject)
    aliases = {normalized}
    if normalized == "信息工学系":
        aliases.add("情报工学系")
    if normalized in {"申请期间", "出願期間"}:
        aliases.update(("申请期间", "申請受付期間", "出願期間", "申请期限"))
    if normalized == "toeic l&r":
        aliases.update(("toeic", "托业", "トーイック"))
    if normalized == "toeic ip":
        aliases.update(("toeic-ip", "托业ip", "托业 ip", "トーイックip", "トーイック ip"))
    return frozenset(aliases)


def _exam_entities(value: str) -> frozenset[str]:
    normalized = _normalize(value)
    entities = {
        entity
        for entity, aliases in _EXAM_ENTITY_ALIASES.items()
        if any(_normalize(alias) in normalized for alias in aliases)
    }
    if "toefl_ibt_home_edition" in entities:
        entities.discard("toefl_ibt")
    if "toefl_itp" in entities:
        entities.discard("toefl_ibt")
    if "toeic_ip" in entities:
        entities.discard("toeic_lr")
    return frozenset(entities)


def _disposition_status(proposition: ClaimableProposition) -> str:
    if proposition.predicate is PropositionPredicate.EXAM_NORMALIZATION:
        return "interpreted"
    if proposition.predicate is PropositionPredicate.MISSING_APPLICANT_INFORMATION:
        return "needs_information"
    return "not_covered"


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
        kind=claim.kind,
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
