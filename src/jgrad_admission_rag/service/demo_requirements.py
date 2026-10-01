"""Server-owned presentation models for the interactive applicant demo."""

from __future__ import annotations

from datetime import date, time
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    model_serializer,
    model_validator,
)
from pydantic_core import PydanticCustomError

from ..reasoning.applicability import ApplicabilityPredicate, ApplicabilityRule, PredicateOperator
from ..reasoning.application_materials import (
    ApplicationMaterialApplicability,
    ApplicationMaterialCode,
    resolve_application_materials,
)
from ..reasoning.applicant_profile import (
    ApplicantProfile,
    CompletionState,
    CredentialBasis,
    IndividualReviewStatus,
    LanguageTestKind,
)
from ..reasoning.applicant_report import ApplicantReport, build_applicant_report
from ..reasoning.query_intent import (
    IntentCategory,
    IntentMention,
    MentionKind,
    QueryIntent,
    RequestedScope,
)
from ..reasoning.reviewed_report_evidence import (
    ReviewedReportEvidenceBundle,
    ReviewedReportEvidenceRecord,
)
from ..reasoning.reviewed_report_plan import ReviewedReportPlan
from ..schemas.document_identity import DegreeLevel, IntakeTerm
from .date_presentation import ReviewedDatePresentation, ordered_highlights_for_event


class DemoModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DemoRoute(DemoModel):
    route_id: str
    route_name: str


class DemoDepartment(DemoModel):
    department_id: str
    department_name: str
    application_routes: tuple[DemoRoute, ...] = ()


class DemoCollege(DemoModel):
    college_id: str
    college_name: str
    departments: tuple[DemoDepartment, ...] = Field(min_length=1)


class DemoIntake(DemoModel):
    document_id: str
    year: int = Field(ge=1, strict=True)
    month: int = Field(ge=1, le=12, strict=True)
    intake_name: str
    colleges: tuple[DemoCollege, ...] = Field(min_length=1)


class DemoDegree(DemoModel):
    degree_id: DegreeLevel
    degree_name: str
    intakes: tuple[DemoIntake, ...] = Field(min_length=1)


class DemoSchool(DemoModel):
    school_id: str
    school_name: str
    degrees: tuple[DemoDegree, ...] = Field(min_length=1)


class DemoTargetCatalogResponse(DemoModel):
    schema_version: Literal["1.0"] = "1.0"
    schools: tuple[DemoSchool, ...]


class DemoTargetRequest(DemoModel):
    schema_version: Literal["1.0"] = "1.0"
    school_id: str
    document_id: str
    degree_id: DegreeLevel
    intake: IntakeTerm
    college_id: str
    department_id: str
    application_route: str | None = None


class DemoEvidenceHighlight(DemoModel):
    highlight_id: str
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)
    exact_text: str = Field(min_length=1)
    claim_ids: tuple[str, ...] = Field(min_length=1)


class DemoEvidence(DemoModel):
    document_id: str
    official_title: str
    school_name: str
    intake_name: str
    fact_id: str
    pages: tuple[int, ...] = Field(min_length=1)
    official_text: str
    source_url: str
    scope_type: str
    scope_targets: tuple[str, ...] = ()
    parent_college: str | None = None
    limitation: str
    highlights: tuple[DemoEvidenceHighlight, ...] = ()
    local_pdf_url: str | None = Field(
        default=None,
        pattern=r"^/documents/[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?/source\.pdf$",
    )


class DemoDateEvent(DemoModel):
    event_id: str
    event_type: Literal[
        "registration_open",
        "application_window",
        "arrival_deadline",
        "recommended_arrival",
    ]
    label: str
    display_text: str
    start_date: date
    start_time: time | None = None
    end_date: date | None = None
    end_time: time | None = None
    timezone: Literal["Asia/Tokyo"]
    nature: Literal["opens", "period", "must_arrive", "recommended_arrival"]
    precision: Literal["date", "minute"]
    unknown_fields: tuple[Literal["start_time", "end_date", "end_time"], ...] = ()
    uncertainty_note: str | None = None
    highlight_ids: tuple[str, ...] = Field(min_length=1)
    evidence: tuple[DemoEvidence, ...] = Field(min_length=1)


class DemoRequirement(DemoModel):
    requirement_id: str
    category: Literal["dates", "materials", "eligibility", "language"]
    title: str
    description: str
    reviewed_summary: str | None = None
    official_status: Literal[
        "required",
        "conditional",
        "needs_information",
        "needs_review",
        "not_applicable",
        "not_covered",
    ]
    deadline: str | None = None
    evidence: tuple[DemoEvidence, ...] = ()
    date_events: tuple[DemoDateEvent, ...] = ()
    limitation: str


class DemoTargetSummary(DemoModel):
    school_name: str
    degree_name: str
    intake_name: str
    college_name: str
    department_name: str
    application_route_name: str | None = None


class DemoBaseRequirementsResponse(DemoModel):
    schema_version: Literal["1.0"] = "1.0"
    target: DemoTargetSummary
    coverage_status: Literal["partial_reviewed_rules"] = "partial_reviewed_rules"
    coverage_statement: str
    limitation_statement: str
    requirements: tuple[DemoRequirement, ...]
    examination_information: dict[str, Any] | None = None

    @model_serializer(mode="wrap")
    def omit_unrequested_exam(self, handler):
        result = handler(self)
        if "examination_information" not in self.model_fields_set:
            result.pop("examination_information", None)
        return result


class DemoJapaneseBackground(str, Enum):
    STUDIED = "studied"
    CERTIFICATE_AVAILABLE = "certificate_available"
    NOT_STUDIED = "not_studied"


class DemoMaterialPreparation(str, Enum):
    AVAILABLE = "available"
    NOT_YET = "not_yet"
    UNKNOWN = "unknown"


class DemoMaterialInput(DemoModel):
    code: ApplicationMaterialCode
    preparation: DemoMaterialPreparation


class DemoApplicantInput(DemoModel):
    credential_basis: CredentialBasis | None = None
    completion_state: CompletionState | None = None
    english_test_kind: LanguageTestKind | None = None
    english_score: StrictInt | StrictFloat | None = Field(
        default=None, ge=0, le=10_000, allow_inf_nan=False
    )
    english_test_date: date | None = None
    english_official_report_available: StrictBool | None = None
    japanese_background: DemoJapaneseBackground | None = None
    materials: tuple[DemoMaterialInput, ...] = ()

    @model_validator(mode="after")
    def supplied_fields_must_reconcile(self) -> "DemoApplicantInput":
        if (self.english_score is not None or self.english_test_date is not None) and (
            self.english_test_kind is None
        ):
            raise ValueError("English score or date requires a test kind")
        codes = tuple(item.code for item in self.materials)
        if len(codes) != len(set(codes)):
            raise ValueError("material codes must not repeat")
        return self


class DemoEnglishPreparationInput(DemoModel):
    downloaded_online_pdf: StrictBool | None = None
    toeic_verification_qr_present: StrictBool | None = None
    toeic_digital_official_score_certificate: StrictBool | None = None
    toefl_test_taker_score_report_pdf: StrictBool | None = None
    toefl_di_code_g179_set: StrictBool | None = None


class DemoApplicationPreparationInput(DemoModel):
    completion_date: date | None = None
    expected_completion_date: date | None = None
    individual_review_status: IndividualReviewStatus | None = None
    materials_dispatched_date: date | None = None
    materials_arrival_date: date | None = None
    online_steps_completed: StrictBool | None = None


class DemoApplicantComparisonRequest(DemoModel):
    schema_version: Literal["1.0"] = "1.0"
    target: DemoTargetRequest
    applicant: DemoApplicantInput
    english_preparation: DemoEnglishPreparationInput | None = None
    application_preparation: DemoApplicationPreparationInput | None = None

    @model_validator(mode="after")
    def application_fields_must_reconcile(self) -> "DemoApplicantComparisonRequest":
        preparation = self.application_preparation
        if preparation is None:
            return self
        state = self.applicant.completion_state
        if preparation.completion_date is not None and state is not CompletionState.COMPLETED:
            raise PydanticCustomError(
                "completion_date_state_mismatch",
                "Graduation date requires completion_state=completed",
                {"field": "application_preparation.completion_date"},
            )
        if (
            preparation.expected_completion_date is not None
            and state is not CompletionState.EXPECTED
        ):
            raise PydanticCustomError(
                "expected_completion_date_state_mismatch",
                "Expected graduation date requires completion_state=expected",
                {"field": "application_preparation.expected_completion_date"},
            )
        if (
            preparation.materials_dispatched_date is not None
            and preparation.materials_arrival_date is not None
            and preparation.materials_arrival_date < preparation.materials_dispatched_date
        ):
            raise PydanticCustomError(
                "arrival_before_dispatch",
                "Materials arrival cannot be before dispatch",
                {"field": "application_preparation.materials_arrival_date"},
            )
        if (
            preparation.individual_review_status is not None
            and self.applicant.credential_basis
            not in {
                CredentialBasis.FOREIGN_15_YEAR_EDUCATION,
                CredentialBasis.UNIVERSITY_THREE_YEAR_ENROLLMENT,
            }
        ):
            raise PydanticCustomError(
                "individual_review_path_mismatch",
                "Individual review progress requires a supported review path",
                {"field": "application_preparation.individual_review_status"},
            )
        return self

    @model_validator(mode="after")
    def english_fields_must_match_test_kind(self) -> "DemoApplicantComparisonRequest":
        proof = self.english_preparation
        if proof is None:
            return self
        kind = self.applicant.english_test_kind
        if kind is not LanguageTestKind.TOEIC_LR and (
            proof.toeic_verification_qr_present is not None
            or proof.toeic_digital_official_score_certificate is not None
        ):
            raise PydanticCustomError(
                "english_proof_kind_mismatch",
                "TOEIC proof fields require english_test_kind=toeic_lr",
                {"field": "english_preparation.toeic_*", "expected_test_kind": "toeic_lr"},
            )
        if kind not in {LanguageTestKind.TOEFL_IBT, LanguageTestKind.TOEFL_IBT_HOME_EDITION} and (
            proof.toefl_test_taker_score_report_pdf is not None
            or proof.toefl_di_code_g179_set is not None
        ):
            raise PydanticCustomError(
                "english_proof_kind_mismatch",
                "TOEFL proof fields require a TOEFL iBT english_test_kind",
                {"field": "english_preparation.toefl_*", "expected_test_kind": "toefl_ibt"},
            )
        return self


class DemoEnglishPreparationCheck(DemoModel):
    check_id: str
    title: str
    status: Literal[
        "reported_match", "action_needed", "needs_information", "not_applicable", "not_covered"
    ]
    explanation: str
    next_action: str
    rule_ids: tuple[str, ...] = ()
    evidence: tuple[DemoEvidence, ...] = ()


class DemoEnglishPreparationResult(DemoModel):
    document_id: str
    target: DemoTargetSummary
    scope_statement: str
    checks: tuple[DemoEnglishPreparationCheck, ...]


class DemoApplicationPreparationCheck(DemoModel):
    check_id: str
    title: str
    status: Literal[
        "reported_match", "action_needed", "needs_information", "not_applicable", "not_covered"
    ]
    explanation: str
    next_action: str
    rule_ids: tuple[str, ...] = ()
    evidence: tuple[DemoEvidence, ...] = ()


class DemoApplicationPreparationResult(DemoModel):
    document_id: str
    target: DemoTargetSummary
    scope_statement: str
    checks: tuple[DemoApplicationPreparationCheck, ...]


class DemoComparisonItem(DemoModel):
    item_id: str
    category: Literal["education", "english", "japanese", "materials"]
    title: str
    comparison_status: Literal[
        "recorded",
        "possible_match",
        "needs_information",
        "needs_review",
        "not_applicable",
        "not_covered",
    ]
    description: str
    action_group: Literal["recorded", "action_required", "review_required"]
    next_action: str = Field(min_length=1)
    official_status: str | None = None
    preparation_status: DemoMaterialPreparation | None = None
    evidence: tuple[DemoEvidence, ...] = ()
    limitation: str

    @model_validator(mode="after")
    def action_group_must_match_status(self) -> "DemoComparisonItem":
        expected = (
            "recorded"
            if self.comparison_status in {"recorded", "possible_match", "not_applicable"}
            else (
                "action_required"
                if self.comparison_status == "needs_information"
                else "review_required"
            )
        )
        if self.action_group != expected:
            raise ValueError("action group must match comparison status")
        expected_action = _readiness_fields(self.comparison_status, self.category)["next_action"]
        if self.next_action != expected_action:
            raise ValueError("next action must match comparison status and category")
        return self


class DemoReadinessCounts(DemoModel):
    total: int = Field(ge=0, strict=True)
    recorded: int = Field(ge=0, strict=True)
    action_required: int = Field(ge=0, strict=True)
    review_required: int = Field(ge=0, strict=True)


class DemoApplicantComparisonResponse(DemoModel):
    schema_version: Literal["1.0"] = "1.0"
    target: DemoTargetSummary
    comparison_statement: str
    partial_checklist_statement: str
    limitation_statement: str
    items: tuple[DemoComparisonItem, ...]
    counts: DemoReadinessCounts
    english_preparation_result: DemoEnglishPreparationResult | None = None
    application_preparation_result: DemoApplicationPreparationResult | None = None

    @model_serializer(mode="wrap")
    def omit_unrequested_english_result(self, handler):
        payload = handler(self)
        if self.english_preparation_result is None:
            payload.pop("english_preparation_result", None)
        if self.application_preparation_result is None:
            payload.pop("application_preparation_result", None)
        return payload

    @model_validator(mode="after")
    def counts_must_match_items(self) -> "DemoApplicantComparisonResponse":
        expected = {
            group: sum(item.action_group == group for item in self.items)
            for group in ("recorded", "action_required", "review_required")
        }
        if self.counts.total != len(self.items) or any(
            getattr(self.counts, group) != count for group, count in expected.items()
        ):
            raise ValueError("readiness counts must reconcile with comparison items")
        return self


_DEGREE_NAMES = {
    DegreeLevel.MASTER: "修士课程",
    DegreeLevel.DOCTORAL: "博士课程",
    DegreeLevel.PROFESSIONAL_DEGREE: "专业学位课程",
}
_INSTITUTION_NAMES = {"isct": "東京科学大学"}
_ROUTE_NAMES = {
    "a_schedule": "A 日程",
    "b_schedule": "B 日程",
    "individual eligibility review route": "个别资格审查路径",
}
_TARGET_FIELDS = {
    "target_application.requested_degree_level",
    "target_application.intake_year",
    "target_application.intake_month",
    "target_application.graduate_school",
    "target_application.department_or_program",
    "target_application.application_route",
}


def build_demo_target_catalog(plans: tuple[ReviewedReportPlan, ...]) -> DemoTargetCatalogResponse:
    """Project reviewed plan scope into one deterministic target-selection catalog."""

    schools: dict[str, dict[DegreeLevel, list[tuple[ReviewedReportPlan, IntakeTerm]]]] = {}
    for plan in plans:
        identity = plan.document_identity
        degree_map = schools.setdefault(identity.institution_id, {})
        for degree in identity.degree_levels:
            degree_map.setdefault(degree, []).extend(
                (plan, intake) for intake in identity.intake_terms
            )

    school_items = []
    for school_id, degree_map in sorted(schools.items()):
        degree_items = []
        for degree, plan_intakes in sorted(degree_map.items(), key=lambda item: item[0].value):
            intake_items = []
            for plan, intake in sorted(
                plan_intakes,
                key=lambda item: (
                    item[1].year,
                    item[1].month,
                    item[0].document_identity.document_id,
                ),
            ):
                colleges = _college_catalog(plan)
                if not colleges:
                    continue
                intake_items.append(
                    DemoIntake(
                        document_id=plan.document_identity.document_id,
                        year=intake.year,
                        month=intake.month,
                        intake_name=f"{intake.year}年{intake.month}月入学",
                        colleges=colleges,
                    )
                )
            if intake_items:
                degree_items.append(
                    DemoDegree(
                        degree_id=degree,
                        degree_name=_DEGREE_NAMES[degree],
                        intakes=tuple(intake_items),
                    )
                )
        if degree_items:
            fallback_name = plan_intakes[0][0].document_identity.institution_name
            school_items.append(
                DemoSchool(
                    school_id=school_id,
                    school_name=_INSTITUTION_NAMES.get(school_id, fallback_name),
                    degrees=tuple(degree_items),
                )
            )
    return DemoTargetCatalogResponse(schools=tuple(school_items))


def build_demo_base_requirements(
    request: DemoTargetRequest,
    plan: ReviewedReportPlan,
    evidence_bundle: ReviewedReportEvidenceBundle,
    *,
    date_presentation: ReviewedDatePresentation | None = None,
    source_pdf_document_id: str | None = None,
) -> DemoBaseRequirementsResponse:
    """Build a safe, profile-free requirements view from reviewed typed artifacts."""

    catalog = build_demo_target_catalog((plan,))
    target = _resolve_catalog_target(catalog, request)
    evidence_by_fact = {record.fact_id: record for record in evidence_bundle.evidence_records}
    requirements: list[DemoRequirement] = []

    date_rules = tuple(
        rule
        for rule in plan.rules
        if ("application-window" in rule.rule_id or "materials-arrival-window" in rule.rule_id)
        and _rule_matches_target(rule, request)
    )
    for rule in date_rules:
        arrival = "materials-arrival-window" in rule.rule_id
        date_events = _date_events(
            plan,
            request,
            evidence_by_fact,
            date_presentation,
            (
                ("arrival_deadline", "recommended_arrival")
                if arrival
                else ("registration_open", "application_window")
            ),
            source_pdf_document_id,
        )
        requirements.append(
            _rule_requirement(
                plan,
                rule,
                evidence_by_fact,
                category="dates",
                title="材料必着期限" if arrival else "网上登记与出愿期间",
                status="needs_information" if arrival else "required",
                limitation=(
                    "仅显示官方期间；不根据寄出日期推断到达、受理或出愿完成。"
                    if arrival
                    else "仅显示已审核的官方期间；请以官方文件与学校最新通知为准。"
                ),
                request=request,
                description=(
                    "请根据下方官方日文核对材料实际到达期间；寄出日期不等于到达日期。"
                    if arrival
                    else "请根据下方官方日文核对网上登记开始时间与出愿期间。"
                ),
                reviewed_summary=None if date_events else rule.annotation_note,
                date_events=date_events,
            )
        )

    materials = plan.application_materials
    if materials is not None:
        record = evidence_by_fact[materials.evidence_binding.fact_id]
        for entry in materials.entries:
            requirements.append(
                DemoRequirement(
                    requirement_id=f"material:{entry.code.value}",
                    category="materials",
                    title=entry.official_name,
                    description=(
                        "RULE-05A 已审核的 p.10 共通提交材料。"
                        if not entry.exempt_for_eligibility_review_paths
                        else "普通资格路径通常需要；资格审查路径需结合之后填写的学历信息判断。"
                    ),
                    official_status=(
                        "required"
                        if not entry.exempt_for_eligibility_review_paths
                        else "needs_information"
                    ),
                    evidence=(
                        _demo_evidence(
                            plan,
                            record,
                            "只表示 p.10 共通材料的审核适用性；不判断提交、到达、受理或完整性。",
                            request.intake,
                        ),
                    ),
                    limitation="只表示 p.10 共通材料的审核适用性；不判断提交、到达、受理或完整性。",
                )
            )

    eligibility_rule = next(
        (
            rule
            for rule in plan.rules
            if "direct-path-1-university" in rule.rule_id and _rule_matches_target(rule, request)
        ),
        None,
    )
    if eligibility_rule is not None:
        requirements.append(
            _rule_requirement(
                plan,
                eligibility_rule,
                evidence_by_fact,
                category="eligibility",
                title="学历与出愿资格需要结合个人情况判断",
                status="needs_information",
                limitation="基础视图不选择资格路径，也不生成最终出愿资格结论。",
                request=request,
                description="请在下一步填写最高学历、毕业状态、受教育年限及个别资格审查情况。",
            )
        )

    language_rules = tuple(
        rule
        for rule in plan.rules
        if (
            "english-external-score-required" in rule.rule_id
            or "english-submission-" in rule.rule_id
        )
        and _rule_matches_target(rule, request)
    )
    seen_language_facts: set[str] = set()
    for rule in language_rules:
        fact_ids = {binding.fact_id for binding in rule.evidence_bindings}
        if fact_ids <= seen_language_facts:
            continue
        seen_language_facts.update(fact_ids)
        requirements.append(
            _rule_requirement(
                plan,
                rule,
                evidence_by_fact,
                category="language",
                title=(
                    "英语成绩单提交方式"
                    if "english-submission-" in rule.rule_id
                    else "英语考试要求"
                ),
                status="conditional" if _has_profile_predicate(rule) else "required",
                limitation="这里只说明已审核规则；不判断成绩有效、学校已收到或申请人已满足要求。",
                request=request,
                description=(
                    "请按该系的官方方式准备英语成绩单；具体考试类型、日期和材料状态将在个人信息步骤中核对。"
                    if "english-submission-" in rule.rule_id
                    else "该目标适用已审核的英语考试要求；个人成绩与证明材料尚未比较。"
                ),
                reviewed_summary=(
                    "信息工学系须在出愿时提交英语成绩单；截止后不能补交，已交成绩单不能替换，成绩单不退还。"
                    if rule.rule_id
                    == f"isct-master-english-submission-computer-science-{'apr' if request.intake.month == 4 else 'sep'}"
                    and {binding.fact_id for binding in rule.evidence_bindings} == {"fact:00287"}
                    else None
                ),
            )
        )

    if (
        request.school_id == "isct"
        and request.document_id == "isct_2027_4_2026_9_master"
        and plan.document_identity.document_id == request.document_id
    ):
        month = "apr" if request.intake.month == 4 else "sep"
        names = (
            ("math-written-exam",)
            if request.department_id == "数学系"
            else (
                "approved-kind-toeic_lr",
                "toefl-report-toefl_ibt",
                "test-date",
                "online-pdf",
                "external-score-required",
            )
        )
        guide_rules = tuple(
            next(
                (
                    rule
                    for rule in plan.rules
                    if rule.rule_id == f"isct-master-english-{name}-{month}"
                    and _rule_matches_target(rule, request)
                ),
                None,
            )
            for name in names
        )
        date_rule = next(
            (
                rule
                for rule in guide_rules
                if rule is not None and rule.rule_id == f"isct-master-english-test-date-{month}"
            ),
            None,
        )
        date_bound = date_rule is None or any(
            predicate.field_path == "language_test_results.selected.test_date"
            and predicate.expected_value == "2024-06-11"
            for predicate in date_rule.predicates
        )
        if all(guide_rules) and date_bound:
            fact_ids = sorted(
                {binding.fact_id for rule in guide_rules for binding in rule.evidence_bindings}
            )
            expected_facts = (
                {"fact:00123"}
                if request.department_id == "数学系"
                else {"fact:00110", "fact:00111", "fact:00114", "fact:00115", "fact:00122"}
            )
            if set(fact_ids) == expected_facts and all(
                fact_id in evidence_by_fact for fact_id in fact_ids
            ):
                math = request.department_id == "数学系"
                guide = (
                    "当前资料中，数学系采用校内英语笔试，不要求提交上述英语外部成绩单。\n"
                    "请查看数学系已审核的考试安排。"
                    if math
                    else "可用考试：TOEIC L&R、TOEFL iBT、TOEFL iBT Home Edition。\n"
                    "TOEIC-IP、TOEFL-ITP等团体考试不能用于本轮申请。\n"
                    "考试日期须为2024年6月11日或之后（仅本募集版本）。\n"
                    "打印在线下载的官方PDF；ETS寄给本人或学校的纸质成绩单不能替代。\n"
                    "TOEIC：核对数字官方成绩证明或同等形式及真伪验证二维码；无二维码的纸质证明不接受。\n"
                    "TOEFL：打印Test Taker Score Report PDF，并为本次成绩设置学校DI代码G179。"
                )
                requirements.append(
                    DemoRequirement(
                        requirement_id="language:preparation-guide",
                        category="language",
                        title="英语成绩怎么准备",
                        description=guide,
                        reviewed_summary=guide,
                        official_status="conditional" if not math else "not_applicable",
                        evidence=tuple(
                            _demo_evidence(
                                plan,
                                evidence_by_fact[fact_id],
                                "只适用于当前东科大募集版本；各学系提交方式须另行核对。",
                                request.intake,
                            )
                            for fact_id in fact_ids
                        ),
                        limitation="只说明已审核的类型、日期与证明形式；不判断成绩或学校受理。",
                    )
                )

    if plan.language_score_allocation is not None:
        for entry in plan.language_score_allocation.entries:
            if entry.parent_college == request.college_id and entry.target == request.department_id:
                record = evidence_by_fact[entry.evidence_binding.fact_id]
                requirements.append(
                    DemoRequirement(
                        requirement_id=f"language-allocation:{entry.target}",
                        category="language",
                        title="英语成绩评价配点",
                        description=f"该系已审核的英语成绩配点上限为 {entry.maximum_points} 分。",
                        official_status="conditional",
                        evidence=(
                            _demo_evidence(
                                plan,
                                record,
                                plan.language_score_allocation.limitation_statement,
                                request.intake,
                            ),
                        ),
                        limitation=plan.language_score_allocation.limitation_statement,
                    )
                )

    if plan.language_evaluation is not None:
        for entry in plan.language_evaluation.entries:
            if (
                entry.parent_college == request.college_id
                and entry.target == request.department_id
                and (
                    entry.application_route is None
                    or entry.application_route == request.application_route
                )
            ):
                record = evidence_by_fact[entry.evidence_binding.fact_id]
                requirements.append(
                    DemoRequirement(
                        requirement_id=f"language-evaluation:{entry.target}:{entry.application_route or 'all'}",
                        category="language",
                        title="英语评价方式",
                        description="已审核该目标使用英语成绩或校内笔试的方式；不判断个人考试结果。",
                        official_status="conditional",
                        evidence=(
                            _demo_evidence(
                                plan,
                                record,
                                entry.limitation_statement,
                                request.intake,
                            ),
                        ),
                        limitation=entry.limitation_statement,
                    )
                )

    if not any(item.category == "language" for item in requirements):
        requirements.append(
            DemoRequirement(
                requirement_id="language:not-covered",
                category="language",
                title="语言要求仍需确认",
                description="当前审核范围没有足够依据为该目标展示自动化语言规则。",
                official_status="not_covered",
                limitation="未覆盖不表示不需要语言成绩，也不表示已经满足要求。",
            )
        )

    return DemoBaseRequirementsResponse(
        target=target,
        coverage_statement="当前只展示人工审核并与官方 Fact 绑定的部分日期、材料、资格和语言规则。",
        limitation_statement="本报告不判断最终出愿资格、材料受理、录取结果或成功概率。",
        requirements=tuple(requirements),
    )


def build_demo_applicant_comparison(
    request: DemoApplicantComparisonRequest,
    plan: ReviewedReportPlan,
    evidence_bundle: ReviewedReportEvidenceBundle,
) -> DemoApplicantComparisonResponse:
    """Compare minimal applicant assertions without producing an eligibility conclusion."""

    base = build_demo_base_requirements(request.target, plan, evidence_bundle)
    applicant = request.applicant
    language_evidence = _category_evidence(base, "language")
    items: list[DemoComparisonItem] = []

    material_result = None
    if plan.application_materials is not None:
        material_result = resolve_application_materials(
            _demo_applicant_profile(request.target, applicant),
            plan.application_materials,
        )

    qualification_rules = _qualification_rules_for_input(plan, request.target, applicant)
    eligibility_evidence = _rules_evidence(
        plan, qualification_rules, evidence_bundle, request.target.intake
    )
    if applicant.credential_basis is None:
        education_status = "needs_information"
        education_description = "尚未提供明确的学历资格路径；空值不会被解释为不满足或满足。"
    elif not qualification_rules:
        education_status = "not_covered"
        education_description = "当前审核规则没有与该学历输入匹配的资格路径，需要人工核对。"
    elif not any("direct-path-" in rule.rule_id for rule in qualification_rules):
        education_status = "needs_review"
        education_description = (
            "已记录的学历路径属于个别资格审查范围，需要学校审核；这里不判断资格成立。"
        )
    else:
        education_status = "possible_match"
        education_description = "已记录的学历路径可能对应普通资格路径，仍需核对毕业状态和官方证明。"
    if applicant.completion_state is not None:
        completion_labels = {
            CompletionState.COMPLETED: "已毕业",
            CompletionState.EXPECTED: "预计毕业",
            CompletionState.NOT_COMPLETED: "尚未完成",
        }
        education_description += (
            f" 毕业状态已记录为：{completion_labels[applicant.completion_state]}。"
        )
    items.append(
        DemoComparisonItem(
            item_id="education:credential",
            category="education",
            title="学历与资格路径",
            comparison_status=education_status,
            description=education_description,
            **_readiness_fields(education_status, "education"),
            evidence=eligibility_evidence,
            limitation="这是申请人自报信息与已审核路径的保守对照，不是出愿资格认定。",
        )
    )

    english_supplied = any(
        value is not None
        for value in (
            applicant.english_test_kind,
            applicant.english_score,
            applicant.english_test_date,
            applicant.english_official_report_available,
        )
    )
    english_status = "recorded" if english_supplied else "needs_information"
    items.append(
        DemoComparisonItem(
            item_id="english:result",
            category="english",
            title="英语考试与官方成绩单",
            comparison_status=english_status,
            description=(
                "英语考试信息已记录并与该目标的审核规则并列展示；仍需核对考试类型、有效期和提交方式。"
                if english_supplied
                else "尚未提供英语考试信息；这不会被解释为不满足要求。"
            ),
            **_readiness_fields(english_status, "english"),
            evidence=language_evidence,
            limitation="记录成绩不等于成绩有效、官方成绩单可用、学校已收到或已满足英语要求。",
        )
    )

    japanese_supplied = applicant.japanese_background is not None
    japanese_status = "recorded" if japanese_supplied else "needs_information"
    items.append(
        DemoComparisonItem(
            item_id="japanese:background",
            category="japanese",
            title="日语学习或证明情况",
            comparison_status=japanese_status,
            description=(
                "日语情况已记录；当前审核证据不足以判断是否满足任何项目要求。"
                if japanese_supplied
                else "尚未提供日语情况；当前审核证据也不足以生成满足结论。"
            ),
            **_readiness_fields(japanese_status, "japanese"),
            limitation="本项只记录申请人输入，不推断日语能力、免除、项目资格或录取结果。",
        )
    )

    supplied_materials = {item.code: item.preparation for item in applicant.materials}
    base_materials = {
        requirement.requirement_id.removeprefix("material:"): requirement
        for requirement in base.requirements
        if requirement.category == "materials"
    }
    if material_result is not None:
        for entry in material_result.entries:
            preparation = supplied_materials.get(entry.code, DemoMaterialPreparation.UNKNOWN)
            requirement = base_materials.get(entry.code.value)
            applicability = entry.applicability.value
            if entry.applicability is ApplicationMaterialApplicability.ELIGIBILITY_REVIEW_PATH:
                status = "needs_review"
            elif entry.applicability is ApplicationMaterialApplicability.NEEDS_INFORMATION:
                status = "needs_information"
            elif entry.applicability is ApplicationMaterialApplicability.NOT_COVERED:
                status = "not_covered"
            elif preparation is DemoMaterialPreparation.AVAILABLE:
                status = "recorded"
            else:
                status = "needs_information"
            items.append(
                DemoComparisonItem(
                    item_id=f"material:{entry.code.value}",
                    category="materials",
                    title=entry.official_name,
                    comparison_status=status,
                    official_status=applicability,
                    preparation_status=preparation,
                    description=_material_comparison_description(applicability, preparation),
                    **_readiness_fields(status, "materials"),
                    evidence=requirement.evidence if requirement is not None else (),
                    limitation="个人准备状态与官方适用性分开记录；已有材料不表示其有效、已提交或已受理。",
                )
            )

    counts = DemoReadinessCounts(
        total=len(items),
        recorded=sum(item.action_group == "recorded" for item in items),
        action_required=sum(item.action_group == "action_required" for item in items),
        review_required=sum(item.action_group == "review_required" for item in items),
    )
    preparation_report = None
    if (
        request.english_preparation is not None or request.application_preparation is not None
    ) and (
        request.target.school_id == "isct"
        and request.target.document_id == "isct_2027_4_2026_9_master"
        and plan.document_identity.document_id == request.target.document_id
    ):
        preparation_report = _reviewed_preparation_report(request, plan, evidence_bundle)
    return DemoApplicantComparisonResponse(
        target=base.target,
        comparison_statement="服务端已将个人自报信息与当前审核规则进行保守对照。",
        partial_checklist_statement="这是当前人工审核范围内的准备视图，不是学校官方完整 checklist。",
        limitation_statement="本结果不是完整 checklist，不判断最终资格、材料完整性、受理或录取。",
        items=tuple(items),
        counts=counts,
        english_preparation_result=(
            _english_preparation_result(
                request, plan, evidence_bundle, base.target, preparation_report
            )
            if request.english_preparation is not None
            else None
        ),
        application_preparation_result=(
            _application_preparation_result(
                request, plan, evidence_bundle, base.target, preparation_report
            )
            if request.application_preparation is not None
            else None
        ),
    )


def _reviewed_preparation_report(
    request: DemoApplicantComparisonRequest,
    plan: ReviewedReportPlan,
    evidence_bundle: ReviewedReportEvidenceBundle,
) -> ApplicantReport:
    categories = (
        [IntentCategory.ELIGIBILITY, IntentCategory.APPLICATION_DATES]
        if request.application_preparation is not None
        else []
    )
    if request.english_preparation is not None:
        categories.append(IntentCategory.LANGUAGE_TESTS)
    categories = sorted(categories, key=lambda item: item.value)
    query = " ".join(item.value for item in categories)
    offsets = []
    offset = 0
    for category in categories:
        offsets.append((category, offset))
        offset += len(category.value) + 1
    intent = QueryIntent(
        schema_version="1.0",
        parser_version="lexical-ja-v1",
        catalog_version="prep02-v1",
        query=query,
        requested_categories=tuple(categories),
        requested_scope=RequestedScope(
            department_or_program_targets=(),
            parent_college_values=(),
            target_degree_level=None,
            intake_year=None,
            intake_month=None,
        ),
        matched_mentions=tuple(
            IntentMention(
                canonical_value=category.value,
                mention_kind=MentionKind.INTENT,
                start_offset=start,
                end_offset=start + len(category.value),
                surface=category.value,
            )
            for category, start in offsets
        ),
        diagnostics=(),
    )
    return build_applicant_report(
        f"prep02-{uuid4().hex}",
        _demo_applicant_profile(
            request.target,
            request.applicant,
            request.english_preparation,
            request.application_preparation,
        ),
        intent,
        plan,
        evidence_bundle,
    )


def _application_preparation_result(
    request: DemoApplicantComparisonRequest,
    plan: ReviewedReportPlan,
    evidence_bundle: ReviewedReportEvidenceBundle,
    target: DemoTargetSummary,
    report: ApplicantReport | None,
) -> DemoApplicationPreparationResult:
    scope = "仅按本次填写核对毕业时间和提交进度；不认定资格、材料送达证明或学校受理。"
    if report is None or (
        plan.document_identity.institution_id != "isct"
        or plan.document_identity.document_id != "isct_2027_4_2026_9_master"
        or plan.document_identity.source_pdf_sha256
        != "57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735"
        or plan.source_kb_sha256
        != "7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce"
    ):
        return DemoApplicationPreparationResult(
            document_id=request.target.document_id,
            target=target,
            scope_statement=scope,
            checks=(
                DemoApplicationPreparationCheck(
                    check_id="application:coverage",
                    title="毕业与提交提醒",
                    status="not_covered",
                    explanation="当前资料未覆盖这一目标的毕业与提交进度核对。",
                    next_action="请查看当前目标的官方原文。",
                ),
            ),
        )

    preparation = request.application_preparation
    assert preparation is not None
    decisions = {item.rule_id: item for item in report.reasoning_trace.source_decisions}
    resolutions = {item.rule_id: item for item in report.reasoning_trace.resolution_steps}
    conflicts = {
        rule_id
        for item in report.reasoning_trace.interaction_steps
        if item.outcome.value in {"conflict", "ambiguity", "unreviewed_interaction"}
        for rule_id in item.rule_ids
    }
    rules = {item.rule_id: item for item in plan.rules}
    records = {item.fact_id: item for item in evidence_bundle.evidence_records}
    suffix = "apr" if request.target.intake.month == 4 else "sep"

    def bound(stem: str, *, append_suffix: bool = True):
        rule_id = f"isct-master-{stem}{f'-{suffix}' if append_suffix else ''}"
        rule, decision, resolution = (
            rules.get(rule_id),
            decisions.get(rule_id),
            resolutions.get(rule_id),
        )
        if (
            rule is None
            or decision is None
            or resolution is None
            or rule_id in conflicts
            or resolution.disposition.value == "overridden"
            or decision.scope_status.value != "confirmed"
            or not _rule_matches_target(rule, request.target)
        ):
            return None
        evidence = tuple(
            _demo_evidence(plan, records[binding.fact_id], scope, request.target.intake)
            for binding in rule.evidence_bindings
            if binding.fact_id in records
        )
        if len(evidence) != len(rule.evidence_bindings):
            return None
        return rule, decision, evidence

    def result(
        check_id: str, title: str, status: str, explanation: str, next_action: str, source=None
    ):
        return DemoApplicationPreparationCheck(
            check_id=check_id,
            title=title,
            status=status,
            explanation=explanation,
            next_action=next_action,
            rule_ids=(source[0].rule_id,) if source else (),
            evidence=source[2] if source else (),
        )

    checks = []
    basis = request.applicant.credential_basis
    state = request.applicant.completion_state
    graduation = (
        preparation.completion_date
        if state is CompletionState.COMPLETED
        else preparation.expected_completion_date
        if state is CompletionState.EXPECTED
        else None
    )
    path = {
        CredentialBasis.UNIVERSITY_GRADUATION: "direct-path-1-university",
        CredentialBasis.FOREIGN_16_YEAR_BACHELOR_EQUIVALENT: "direct-path-3-foreign_16_year",
    }.get(basis)
    source = (
        bound(f"{path}-{suffix}-{state.value}", append_suffix=False)
        if path and state in {CompletionState.COMPLETED, CompletionState.EXPECTED}
        else None
    )
    field = (
        "academic_credentials.first.completion_date"
        if state is CompletionState.COMPLETED
        else "academic_credentials.first.expected_completion_date"
    )
    date_predicates = (
        tuple(outcome for outcome in source[1].predicate_outcomes if outcome.field_path == field)
        if source
        else ()
    )
    deadline = (
        next(
            (
                str(predicate.expected_value)
                for predicate in source[0].predicates
                if predicate.field_path == field
            ),
            None,
        )
        if source
        else None
    )
    label = "毕业日期" if state is CompletionState.COMPLETED else "预计毕业日期"
    if basis in {
        CredentialBasis.FOREIGN_15_YEAR_EDUCATION,
        CredentialBasis.UNIVERSITY_THREE_YEAR_ENROLLMENT,
    }:
        checks.append(
            result(
                "application:graduation",
                "毕业时间",
                "needs_information",
                "当前学历路径需按个别资格审查条件核对，不能套用普通毕业期限作资格结论。",
                "请查看已有资格审查提醒并向学校确认适用路径。",
            )
        )
    elif basis is None or state is None or graduation is None:
        checks.append(
            result(
                "application:graduation",
                "毕业时间",
                "needs_information",
                "毕业路径、状态或日期尚未填全；不会视为未毕业。",
                "请补充适用的毕业日期或预计毕业日期。",
                source,
            )
        )
    elif not source or len(date_predicates) != 1 or not deadline:
        checks.append(
            result(
                "application:graduation",
                "毕业时间",
                "not_covered",
                "当前路径的毕业日期无法可靠对照已审核规则。",
                "请查看官方原文并确认适用路径。",
            )
        )
    else:
        special = (
            bound(f"{path}-sep-special-contact", append_suffix=False)
            if suffix == "sep" and state is CompletionState.EXPECTED
            else None
        )
        special_dates = (
            tuple(item for item in special[1].predicate_outcomes if item.field_path == field)
            if special
            else ()
        )
        if (
            special
            and len(special_dates) == 2
            and all(item.status.value == "confirmed" for item in special_dates)
        ):
            checks.append(
                result(
                    "application:graduation",
                    "预计毕业日期",
                    "needs_information",
                    "预计毕业日期落在本批次的特殊联系期间，不能直接按一般超期判断。",
                    "请按官方说明在出愿前联系学校确认适用方式。",
                    special,
                )
            )
        elif date_predicates[0].status.value == "confirmed":
            checks.append(
                result(
                    "application:graduation",
                    label,
                    "reported_match",
                    f"{label}在本批次规定的{deadline}期限内。这里只核对日期这一项，学历资格仍需结合其他条件确认。",
                    "继续核对学历证明和其他申请条件。",
                    source,
                )
            )
        elif date_predicates[0].status.value == "not_applicable":
            checks.append(
                result(
                    "application:graduation",
                    label,
                    "action_needed",
                    f"{label}晚于本批次要求的{deadline}；这里只核对日期，不判断整个人是否有资格。",
                    "请向学校确认适用的申请方式。",
                    source,
                )
            )
        else:
            checks.append(
                result(
                    "application:graduation",
                    label,
                    "needs_information",
                    "毕业时间与当前路径的对应关系尚待确认。",
                    "请核对毕业日期及适用路径。",
                    source,
                )
            )

    arrival = bound("materials-arrival-window")
    arrival_date = preparation.materials_arrival_date
    dispatched = preparation.materials_dispatched_date
    if arrival is None:
        checks.append(
            result(
                "application:arrival",
                "材料送达",
                "not_covered",
                "当前目标缺少可核对的送达期间依据。",
                "请查看官方原文。",
            )
        )
    elif arrival_date is None:
        dispatch_text = f"已记录{dispatched.isoformat()}寄出；" if dispatched else ""
        checks.append(
            result(
                "application:arrival",
                "材料送达",
                "needs_information",
                f"{dispatch_text}材料实际送达日期尚未确认；寄出不等于按时送达。",
                "请核实材料能否在必着截止前送达，并确认实际送达日期。",
                arrival,
            )
        )
    else:
        predicates = {
            item.operator.value: item
            for item in arrival[1].predicate_outcomes
            if item.field_path == "application_submission.materials_arrival_date"
        }
        boundaries = {
            item.operator.value: str(item.expected_value)
            for item in arrival[0].predicates
            if item.field_path == "application_submission.materials_arrival_date"
        }
        start, end = predicates.get("on_or_after"), predicates.get("on_or_before")
        if (
            not start
            or not end
            or not boundaries.get("on_or_after")
            or not boundaries.get("on_or_before")
        ):
            checks.append(
                result(
                    "application:arrival",
                    "材料送达",
                    "not_covered",
                    "送达期间的审核条件不完整。",
                    "请查看官方原文。",
                )
            )
        elif start.status.value == end.status.value == "confirmed":
            checks.append(
                result(
                    "application:arrival",
                    "材料送达",
                    "reported_match",
                    f"按你填写的日期，材料在公布的{boundaries['on_or_after']}至{boundaries['on_or_before']}接收期间内送达；是否受理请查看学校通知。",
                    "保留送达记录，核对学校的受理通知。",
                    arrival,
                )
            )
        elif start.status.value == "not_applicable":
            checks.append(
                result(
                    "application:arrival",
                    "材料送达",
                    "action_needed",
                    f"填写的送达日期早于{boundaries['on_or_after']}接收期开始日；不能据此判断已受理。",
                    "请向学校确认该次送达如何处理。",
                    arrival,
                )
            )
        elif end.status.value == "not_applicable":
            checks.append(
                result(
                    "application:arrival",
                    "材料送达",
                    "action_needed",
                    f"填写的送达日期晚于{boundaries['on_or_before']}必着截止日；不能据此判断已受理。",
                    "请向学校确认该次送达如何处理。",
                    arrival,
                )
            )
        else:
            checks.append(
                result(
                    "application:arrival",
                    "材料送达",
                    "needs_information",
                    "送达日期与已审核期间暂无法可靠核对。",
                    "请查看官方原文。",
                    arrival,
                )
            )

    online = bound("online-steps-not-completion")
    if online is None:
        checks.append(
            result(
                "application:online",
                "网上手续",
                "not_covered",
                "当前目标缺少网上手续的审核依据。",
                "请查看官方原文。",
            )
        )
    elif preparation.online_steps_completed is True and online[1].status.value == "confirmed":
        checks.append(
            result(
                "application:online",
                "网上手续",
                "reported_match",
                "按你的填写，网上注册、照片上传及缴费均已完成；纸质材料送达仍需单独确认。",
                "继续核对材料实际送达和学校通知。",
                online,
            )
        )
    elif preparation.online_steps_completed is False:
        checks.append(
            result(
                "application:online",
                "网上手续",
                "action_needed",
                "按你的填写，网上手续尚未全部完成。",
                "请核对注册、照片上传及缴费步骤。",
                online,
            )
        )
    else:
        checks.append(
            result(
                "application:online",
                "网上手续",
                "needs_information",
                "尚未确认网上注册、照片上传及缴费是否均已完成。",
                "请确认网上手续进度。",
                online,
            )
        )

    if basis in {
        CredentialBasis.FOREIGN_15_YEAR_EDUCATION,
        CredentialBasis.UNIVERSITY_THREE_YEAR_ENROLLMENT,
    }:
        review_status = preparation.individual_review_status
        review_text = {
            IndividualReviewStatus.NOT_REQUESTED: (
                "action_needed",
                "你填写为尚未申请个别资格审查。",
                "请查看该路径的资格审查要求。",
            ),
            IndividualReviewStatus.REQUESTED: (
                "needs_information",
                "你填写为已申请、等待结果；不能视为审查通过。",
                "请关注学校的审查结果。",
            ),
            IndividualReviewStatus.COMPLETED: (
                "needs_information",
                "你填写为办理流程已完成；这不表示审查通过。",
                "请核对学校的正式审查结果。",
            ),
            None: (
                "needs_information",
                "尚未填写个别资格审查办理进度。",
                "请确认是否已申请及学校的处理情况。",
            ),
        }[review_status]
        qualification = _qualification_rules_for_input(plan, request.target, request.applicant)
        evidence = _rules_evidence(plan, qualification, evidence_bundle, request.target.intake)
        checks.append(
            DemoApplicationPreparationCheck(
                check_id="application:review",
                title="个别资格审查",
                status=review_text[0],
                explanation=review_text[1],
                next_action=review_text[2],
                rule_ids=tuple(rule.rule_id for rule in qualification),
                evidence=evidence,
            )
        )
    return DemoApplicationPreparationResult(
        document_id=request.target.document_id,
        target=target,
        scope_statement=scope,
        checks=tuple(checks),
    )


def _english_preparation_result(
    request: DemoApplicantComparisonRequest,
    plan: ReviewedReportPlan,
    evidence_bundle: ReviewedReportEvidenceBundle,
    target: DemoTargetSummary,
    preparation_report: ApplicantReport | None,
) -> DemoEnglishPreparationResult:
    """Translate the existing reviewed report trace into bounded preparation checks."""

    scope_statement = "只核对当前已审核资料与本次自报；不判断整份成绩、资格或学校受理。"
    if (request.target.school_id, request.target.document_id) != (
        "isct",
        "isct_2027_4_2026_9_master",
    ) or plan.document_identity.document_id != request.target.document_id:
        return DemoEnglishPreparationResult(
            document_id=request.target.document_id,
            target=target,
            scope_statement=scope_statement,
            checks=(
                DemoEnglishPreparationCheck(
                    check_id="english:coverage",
                    title="英语证明核对",
                    status="not_covered",
                    explanation="当前资料未覆盖这项目标的详细英语证明核对。",
                    next_action="请查看当前目标的已审核要求和官方原文。",
                ),
            ),
        )

    report = preparation_report
    if report is None:
        raise ValueError("reviewed preparation report missing for supported target")
    decisions = {item.rule_id: item for item in report.reasoning_trace.source_decisions}
    resolution = {item.rule_id: item for item in report.reasoning_trace.resolution_steps}
    conflicts = {
        rule_id
        for item in report.reasoning_trace.interaction_steps
        if item.outcome.value in {"conflict", "ambiguity", "unreviewed_interaction"}
        for rule_id in item.rule_ids
    }
    rules = {item.rule_id: item for item in plan.rules}
    records = {item.fact_id: item for item in evidence_bundle.evidence_records}
    suffix = "apr" if request.target.intake.month == 4 else "sep"

    def binding(stem: str, field: str | None = None, expected: object = True):
        rule_id = f"isct-master-english-{stem}-{suffix}"
        rule = rules.get(rule_id)
        if rule is None or not _rule_matches_target(rule, request.target):
            return None
        if field is not None and not any(
            predicate.field_path == field and predicate.expected_value == expected
            for predicate in rule.predicates
        ):
            return None
        decision, step = decisions.get(rule_id), resolution.get(rule_id)
        if decision is None or step is None or rule_id in conflicts:
            return None
        if step.disposition.value == "overridden":
            return None
        evidence = tuple(
            _demo_evidence(
                plan,
                records[item.fact_id],
                scope_statement,
                request.target.intake,
            )
            for item in rule.evidence_bindings
            if item.fact_id in records
        )
        if len(evidence) != len(rule.evidence_bindings):
            return None
        return rule_id, decision, evidence

    def check(
        check_id: str,
        title: str,
        bound,
        value: object,
        good: str,
        bad: str,
        unknown: str,
        action: str,
        *,
        bad_action: str | None = None,
    ) -> DemoEnglishPreparationCheck:
        if bound is None:
            return DemoEnglishPreparationCheck(
                check_id=check_id,
                title=title,
                status="not_covered",
                explanation="当前目标缺少可核对的完整审核依据。",
                next_action="请查看官方原文或向学校确认。",
            )
        rule_id, decision, evidence = bound
        # A confirmed rule means its condition fired. A failed true predicate is
        # only an action when the applicant explicitly supplied false (or an old date).
        predicate = next(
            (
                item
                for item in decision.predicate_outcomes
                if item.field_path
                == {
                    "english:date": "language_test_results.selected.test_date",
                    "english:kind": "language_test_results.selected.test_kind",
                }.get(check_id, f"language_test_results.selected.{check_id.split(':')[-1]}")
            ),
            None,
        )
        if value is None:
            status, explanation, next_action = "needs_information", unknown, action
        elif (
            resolution[rule_id].disposition.value == "pending"
            or decision.scope_status.value != "confirmed"
            or predicate is None
        ):
            status, explanation, next_action = (
                "not_covered",
                "当前目标的审核条件不能确认这一项。",
                "请查看官方原文。",
            )
        elif predicate.status.value == "confirmed" and decision.status.value == "confirmed":
            status, explanation, next_action = (
                "reported_match",
                good,
                "继续核对证明内容与提交方式。",
            )
        elif predicate.status.value == "not_applicable":
            status, explanation, next_action = "action_needed", bad, bad_action or action
        else:
            status, explanation, next_action = "needs_information", unknown, action
        return DemoEnglishPreparationCheck(
            check_id=check_id,
            title=title,
            status=status,
            explanation=explanation,
            next_action=next_action,
            rule_ids=(rule_id,),
            evidence=evidence,
        )

    math = binding("math-written-exam")
    if math and math[1].status.value == "confirmed" and math[1].scope_status.value == "confirmed":
        checks = (
            DemoEnglishPreparationCheck(
                check_id="english:math",
                title="数学系英语笔试",
                status="not_applicable",
                explanation="当前目标采用校内英语笔试，不要求提交上述外部英语成绩单。",
                next_action="请查看数学系已审核的考试安排。",
                rule_ids=(math[0],),
                evidence=math[2],
            ),
        )
        return DemoEnglishPreparationResult(
            document_id=request.target.document_id,
            target=target,
            scope_statement=scope_statement,
            checks=checks,
        )

    kind = request.applicant.english_test_kind
    if kind in {
        LanguageTestKind.TOEIC_LR,
        LanguageTestKind.TOEFL_IBT,
        LanguageTestKind.TOEFL_IBT_HOME_EDITION,
    }:
        kind_bound = binding(
            f"approved-kind-{kind.value}", "language_test_results.selected.test_kind", kind.value
        )
        kind_good, kind_bad = (
            "该考试类型属于本轮接受范围；仍需核对日期与证明。",
            "当前类型不在本轮接受范围。",
        )
    elif kind in {LanguageTestKind.TOEIC_IP, LanguageTestKind.TOEFL_ITP}:
        kind_bound = binding(
            f"unapproved-kind-{kind.value}", "language_test_results.selected.test_kind", kind.value
        )
        kind_good, kind_bad = "", "本轮不接受此考试类型。"
    else:
        kind_bound = None
        kind_good, kind_bad = "", ""
    if (
        kind in {LanguageTestKind.TOEIC_IP, LanguageTestKind.TOEFL_ITP}
        and kind_bound
        and kind_bound[1].status.value == "confirmed"
        and resolution[kind_bound[0]].disposition.value == "active"
    ):
        kind_check = DemoEnglishPreparationCheck(
            check_id="english:kind",
            title="考试类型",
            status="action_needed",
            explanation=kind_bad,
            next_action="请改用本轮接受的考试类型。",
            rule_ids=(kind_bound[0],),
            evidence=kind_bound[2],
        )
    elif kind is LanguageTestKind.OTHER:
        kind_check = DemoEnglishPreparationCheck(
            check_id="english:kind",
            title="考试类型",
            status="needs_information",
            explanation="尚未确认该考试类型是否可用。",
            next_action="请核对本轮接受的考试类型。",
        )
    elif kind is None:
        kind_check = DemoEnglishPreparationCheck(
            check_id="english:kind",
            title="考试类型",
            status="needs_information",
            explanation="尚未填写考试类型。",
            next_action="请选择本次拟提交的考试类型。",
        )
    else:
        kind_check = check(
            "english:kind",
            "考试类型",
            kind_bound,
            kind.value if kind else None,
            kind_good,
            kind_bad,
            "尚未填写考试类型。",
            "请选择本次拟提交的考试类型。",
        )
    checks = [kind_check]
    if kind_check.status == "reported_match":
        exam_date = request.applicant.english_test_date
        date_bound = binding("test-date", "language_test_results.selected.test_date", "2024-06-11")
        checks.append(
            check(
                "english:date",
                "考试日期",
                date_bound,
                exam_date,
                "考试日期符合本轮日期要求。",
                "此次考试日期早于本轮要求。",
                "尚未填写考试日期。",
                "请填写考试日期并核对当前募集版本。",
            )
        )
        proof = request.english_preparation
        specs = [
            ("downloaded_online_pdf", "在线下载的官方PDF", "online-pdf"),
        ]
        if kind is LanguageTestKind.TOEIC_LR:
            specs += [
                ("toeic_verification_qr_present", "TOEIC真伪验证二维码", "toeic-qr"),
                (
                    "toeic_digital_official_score_certificate",
                    "TOEIC数字官方证明或同等形式",
                    "toeic-digital-certificate",
                ),
            ]
        else:
            specs += [
                (
                    "toefl_test_taker_score_report_pdf",
                    "TOEFL Test Taker Score Report PDF",
                    f"toefl-report-{kind.value}",
                ),
                ("toefl_di_code_g179_set", "本次成绩的G179设置", f"toefl-g179-{kind.value}"),
            ]
        for field, title, stem in specs:
            bound = binding(stem, f"language_test_results.selected.{field}")
            checks.append(
                check(
                    f"english:{field}",
                    title,
                    bound,
                    getattr(proof, field),
                    "按你的填写，已准备本项；仍需核对证明内容。",
                    "按你的填写，当前尚未具备本项要求。",
                    "尚未确认本项准备情况。",
                    f"请核对{title}后再准备提交。",
                )
            )
    return DemoEnglishPreparationResult(
        document_id=request.target.document_id,
        target=target,
        scope_statement=scope_statement,
        checks=tuple(checks),
    )


def _demo_applicant_profile(
    target: DemoTargetRequest,
    applicant: DemoApplicantInput,
    english_preparation: DemoEnglishPreparationInput | None = None,
    application_preparation: DemoApplicationPreparationInput | None = None,
) -> ApplicantProfile:
    credentials = None
    if (
        applicant.credential_basis is not None
        or applicant.completion_state is not None
        or (
            application_preparation is not None
            and (
                application_preparation.completion_date is not None
                or application_preparation.expected_completion_date is not None
            )
        )
    ):
        credentials = (
            {
                "institution_country_code": None,
                "degree_level": "bachelor",
                "credential_basis": applicant.credential_basis,
                "completion_state": applicant.completion_state,
                "completion_date": (
                    application_preparation.completion_date
                    if application_preparation is not None
                    else None
                ),
                "expected_completion_date": (
                    application_preparation.expected_completion_date
                    if application_preparation is not None
                    else None
                ),
                "years_of_education": None,
            },
        )
    language_results = None
    if (
        applicant.english_test_kind is not None
        or applicant.english_score is not None
        or applicant.english_test_date is not None
        or applicant.english_official_report_available is not None
        or (
            english_preparation is not None
            and any(value is not None for value in english_preparation.model_dump().values())
        )
    ):
        language_results = (
            {
                "test_kind": applicant.english_test_kind,
                "score": applicant.english_score,
                "test_date": applicant.english_test_date,
                "validity_status": None,
                "official_report_available": applicant.english_official_report_available,
                **(english_preparation.model_dump() if english_preparation is not None else {}),
            },
        )
    return ApplicantProfile.model_validate(
        {
            "schema_version": "1.0",
            "target_application": {
                "graduate_school_or_college": target.college_id,
                "department_or_program": target.department_id,
                "requested_degree_level": target.degree_id.value,
                "intake_year": target.intake.year,
                "intake_month": target.intake.month,
                "application_route": target.application_route,
            },
            "citizenship_and_residence": {
                "citizenship_country_codes": None,
                "current_residence_country_code": None,
                "residence_status_category": None,
            },
            "academic_credentials": credentials,
            "eligibility_facts": {
                "age_at_enrollment": None,
                "professional_experience_months": None,
                "research_experience_months": None,
                "individual_review_status": (
                    application_preparation.individual_review_status
                    if application_preparation is not None
                    else None
                ),
                "individual_review_requested": None,
                "individual_review_completed": None,
            },
            "language_test_results": language_results,
            "application_submission": (
                {
                    "materials_dispatched_date": application_preparation.materials_dispatched_date,
                    "materials_arrival_date": application_preparation.materials_arrival_date,
                    "online_steps_completed": application_preparation.online_steps_completed,
                }
                if application_preparation is not None
                else None
            ),
        }
    )


def build_demo_applicant_profile(
    target: DemoTargetRequest, applicant: DemoApplicantInput
) -> ApplicantProfile:
    """Build the strict reasoning profile used by the demo and grounded-answer API."""

    return _demo_applicant_profile(target, applicant)


def build_demo_target_summary(
    plans: tuple[ReviewedReportPlan, ...], request: DemoTargetRequest
) -> DemoTargetSummary:
    """Resolve one request through the same reviewed target catalog shown in the UI."""

    return _resolve_catalog_target(build_demo_target_catalog(plans), request)


def build_demo_evidence_inventory(
    plan: ReviewedReportPlan,
    evidence: ReviewedReportEvidenceBundle,
    request: DemoTargetRequest,
    fact_ids: tuple[str, ...],
    *,
    source_pdf_document_id: str | None,
) -> tuple[DemoEvidence, ...]:
    """Expose only cited exact evidence records with safe, verified navigation metadata."""

    records = {item.fact_id: item for item in evidence.evidence_records}
    return tuple(
        _demo_evidence(
            plan,
            records[fact_id],
            "生成内容只绑定到这段已审核官方原文；请通过 PDF 页码和官方网页最终核对。",
            request.intake,
            local_pdf_url=(
                f"/documents/{request.document_id}/source.pdf"
                if source_pdf_document_id == request.document_id
                else None
            ),
        )
        for fact_id in sorted(set(fact_ids))
    )


def _category_evidence(
    response: DemoBaseRequirementsResponse,
    category: Literal["eligibility", "language"],
) -> tuple[DemoEvidence, ...]:
    collected: list[DemoEvidence] = []
    seen: set[tuple[str, str]] = set()
    for requirement in response.requirements:
        if requirement.category != category:
            continue
        for evidence in requirement.evidence:
            key = (evidence.document_id, evidence.fact_id)
            if key not in seen:
                collected.append(evidence)
                seen.add(key)
    return tuple(collected)


def _qualification_rules_for_input(
    plan: ReviewedReportPlan,
    target: DemoTargetRequest,
    applicant: DemoApplicantInput,
) -> tuple[ApplicabilityRule, ...]:
    basis = applicant.credential_basis
    if basis is None:
        return ()
    matched = []
    for rule in plan.rules:
        if not _rule_matches_target(rule, target):
            continue
        basis_predicates = tuple(
            predicate
            for predicate in rule.predicates
            if predicate.field_path == "academic_credentials.first.credential_basis"
            and predicate.operator is PredicateOperator.EQUALS
        )
        if not basis_predicates or basis_predicates[0].expected_value != basis.value:
            continue
        completion_predicates = tuple(
            predicate
            for predicate in rule.predicates
            if predicate.field_path == "academic_credentials.first.completion_state"
            and predicate.operator is PredicateOperator.EQUALS
        )
        if (
            applicant.completion_state is not None
            and completion_predicates
            and all(
                predicate.expected_value != applicant.completion_state.value
                for predicate in completion_predicates
            )
        ):
            continue
        matched.append(rule)
    return tuple(matched)


def _rules_evidence(
    plan: ReviewedReportPlan,
    rules: tuple[ApplicabilityRule, ...],
    bundle: ReviewedReportEvidenceBundle,
    intake: IntakeTerm,
) -> tuple[DemoEvidence, ...]:
    evidence_by_fact = {record.fact_id: record for record in bundle.evidence_records}
    collected = []
    seen: set[str] = set()
    for rule in rules:
        for binding in rule.evidence_bindings:
            if binding.fact_id in seen:
                continue
            collected.append(
                _demo_evidence(
                    plan,
                    evidence_by_fact[binding.fact_id],
                    "仅支持当前学历路径的保守对照；不构成最终出愿资格认定。",
                    intake,
                )
            )
            seen.add(binding.fact_id)
    return tuple(collected)


def _material_comparison_description(
    applicability: str, preparation: DemoMaterialPreparation
) -> str:
    applicability_labels = {
        "required": "该材料在当前官方共通清单中适用。",
        "eligibility_review_path": "该材料由个别资格审查路径承接，不在共通清单重复判断。",
        "needs_information": "学历路径信息不足，暂不能确定该材料在共通清单中的适用性。",
        "not_covered": "当前审核范围不足以判断该材料的适用性。",
    }
    preparation_labels = {
        DemoMaterialPreparation.AVAILABLE: "个人输入：已有。",
        DemoMaterialPreparation.NOT_YET: "个人输入：尚未准备。",
        DemoMaterialPreparation.UNKNOWN: "个人输入：未提供或不确定。",
    }
    return f"{applicability_labels[applicability]} {preparation_labels[preparation]}"


def _readiness_fields(status: str, category: str) -> dict[str, str]:
    if status in {"recorded", "possible_match", "not_applicable"}:
        actions = {
            "education": "继续核对官方证明与适用条件，不要把可能匹配当作资格确认。",
            "english": "核对考试类型、有效期、官方成绩单与该系提交方式。",
            "japanese": "保留当前记录；如项目另有要求，请以官方原文或学校答复为准。",
            "materials": "核对材料内容、有效性和提交方式；已有不表示已提交或已受理。",
        }
        return {"action_group": "recorded", "next_action": actions[category]}
    if status == "needs_information":
        actions = {
            "education": "补充最接近的学历路径和毕业状态后重新对照。",
            "english": "如已参加考试，请补充考试类型、成绩、日期和官方成绩单情况。",
            "japanese": "如有相关学习或证明，可记录；当前不会据此判断满足要求。",
            "materials": "确认该材料是否已有；若学历路径未知，请先补充学历信息。",
        }
        return {"action_group": "action_required", "next_action": actions[category]}
    actions = {
        "education": "查看绑定的官方依据，并向学校确认个别资格审查或未覆盖条件。",
        "english": "查看官方依据并向该系确认当前未覆盖或需审核的英语条件。",
        "japanese": "向学校确认项目是否另有日语要求。",
        "materials": "查看官方依据；资格审查路径或未覆盖状态需由学校确认。",
    }
    return {"action_group": "review_required", "next_action": actions[category]}


def _college_catalog(plan: ReviewedReportPlan) -> tuple[DemoCollege, ...]:
    departments: dict[str, set[str]] = {}
    routes: dict[tuple[str, str], set[str]] = {}
    for rule in plan.rules:
        if rule.scope.parent_college is not None and rule.scope.scope_type == "department":
            departments.setdefault(rule.scope.parent_college, set()).update(
                rule.scope.scope_targets
            )
            route_values = {
                str(predicate.expected_value)
                for predicate in rule.predicates
                if predicate.field_path == "target_application.application_route"
                and predicate.operator is PredicateOperator.EQUALS
                and predicate.expected_value not in {"individual eligibility review route"}
            }
            for department in rule.scope.scope_targets:
                routes.setdefault((rule.scope.parent_college, department), set()).update(
                    route_values
                )
    if plan.language_score_allocation is not None:
        for entry in plan.language_score_allocation.entries:
            departments.setdefault(entry.parent_college, set()).add(entry.target)
    if plan.language_evaluation is not None:
        for entry in plan.language_evaluation.entries:
            departments.setdefault(entry.parent_college, set()).add(entry.target)
            if entry.application_route is not None:
                routes.setdefault((entry.parent_college, entry.target), set()).add(
                    entry.application_route
                )
    return tuple(
        DemoCollege(
            college_id=college,
            college_name=college,
            departments=tuple(
                DemoDepartment(
                    department_id=department,
                    department_name=department,
                    application_routes=tuple(
                        DemoRoute(route_id=route, route_name=_ROUTE_NAMES.get(route, route))
                        for route in sorted(routes.get((college, department), set()))
                    ),
                )
                for department in sorted(targets)
            ),
        )
        for college, targets in sorted(departments.items())
        if targets
    )


def _resolve_catalog_target(
    catalog: DemoTargetCatalogResponse, request: DemoTargetRequest
) -> DemoTargetSummary:
    school = next((item for item in catalog.schools if item.school_id == request.school_id), None)
    degree = (
        next((item for item in school.degrees if item.degree_id == request.degree_id), None)
        if school
        else None
    )
    intake = (
        next(
            (
                item
                for item in degree.intakes
                if item.document_id == request.document_id
                and item.year == request.intake.year
                and item.month == request.intake.month
            ),
            None,
        )
        if degree
        else None
    )
    college = (
        next((item for item in intake.colleges if item.college_id == request.college_id), None)
        if intake
        else None
    )
    department = (
        next(
            (item for item in college.departments if item.department_id == request.department_id),
            None,
        )
        if college
        else None
    )
    if not all((school, degree, intake, college, department)):
        raise ValueError("demo target is not in the reviewed catalog")
    route = next(
        (
            item
            for item in department.application_routes
            if item.route_id == request.application_route
        ),
        None,
    )
    if department.application_routes and route is None:
        raise ValueError("demo target route is required")
    if not department.application_routes and request.application_route is not None:
        raise ValueError("demo target route is unavailable")
    return DemoTargetSummary(
        school_name=school.school_name,
        degree_name=degree.degree_name,
        intake_name=intake.intake_name,
        college_name=college.college_name,
        department_name=department.department_name,
        application_route_name=route.route_name if route else None,
    )


def _rule_matches_target(rule: ApplicabilityRule, request: DemoTargetRequest) -> bool:
    if rule.scope.parent_college is not None and rule.scope.parent_college != request.college_id:
        return False
    if rule.scope.scope_targets and request.department_id not in rule.scope.scope_targets:
        return False
    values = {
        "target_application.requested_degree_level": request.degree_id.value,
        "target_application.intake_year": request.intake.year,
        "target_application.intake_month": request.intake.month,
        "target_application.graduate_school": request.college_id,
        "target_application.department_or_program": request.department_id,
        "target_application.application_route": request.application_route,
    }
    return all(
        _predicate_accepts(values[predicate.field_path], predicate)
        for predicate in rule.predicates
        if predicate.field_path in _TARGET_FIELDS
    )


def _predicate_accepts(value: object, predicate: ApplicabilityPredicate) -> bool:
    expected = predicate.expected_value
    if predicate.operator is PredicateOperator.EQUALS:
        return value == expected
    if predicate.operator is PredicateOperator.NOT_EQUALS:
        return value != expected
    if predicate.operator is PredicateOperator.CONTAINS:
        return isinstance(value, (tuple, list, set)) and expected in value
    return True


def _has_profile_predicate(rule: ApplicabilityRule) -> bool:
    return any(predicate.field_path not in _TARGET_FIELDS for predicate in rule.predicates)


def _rule_requirement(
    plan: ReviewedReportPlan,
    rule: ApplicabilityRule,
    evidence_by_fact: dict[str, ReviewedReportEvidenceRecord],
    *,
    category: Literal["dates", "materials", "eligibility", "language"],
    title: str,
    status: Literal["required", "conditional", "needs_information"],
    limitation: str,
    request: DemoTargetRequest,
    description: str | None = None,
    reviewed_summary: str | None = None,
    date_events: tuple[DemoDateEvent, ...] = (),
) -> DemoRequirement:
    return DemoRequirement(
        requirement_id=f"rule:{rule.rule_id}",
        category=category,
        title=title,
        description=description or rule.annotation_note,
        reviewed_summary=reviewed_summary,
        date_events=date_events,
        official_status=status,
        evidence=tuple(
            _demo_evidence(plan, evidence_by_fact[binding.fact_id], limitation, request.intake)
            for binding in rule.evidence_bindings
        ),
        limitation=limitation,
    )


def _demo_evidence(
    plan: ReviewedReportPlan,
    record: ReviewedReportEvidenceRecord,
    limitation: str,
    intake: IntakeTerm,
    *,
    highlights: tuple[DemoEvidenceHighlight, ...] = (),
    local_pdf_url: str | None = None,
) -> DemoEvidence:
    identity = plan.document_identity
    return DemoEvidence(
        document_id=record.document_id,
        official_title=identity.official_title,
        school_name=_INSTITUTION_NAMES.get(identity.institution_id, identity.institution_name),
        intake_name=f"{intake.year}年{intake.month}月入学",
        fact_id=record.fact_id,
        pages=record.source_pages,
        official_text=record.text,
        source_url=identity.official_source_url,
        scope_type=record.scope_type,
        scope_targets=record.scope_targets,
        parent_college=record.parent_college,
        limitation=limitation,
        highlights=highlights,
        local_pdf_url=local_pdf_url,
    )


def _date_events(
    plan: ReviewedReportPlan,
    request: DemoTargetRequest,
    evidence_by_fact: dict[str, ReviewedReportEvidenceRecord],
    presentation: ReviewedDatePresentation | None,
    event_types: tuple[str, ...],
    source_pdf_document_id: str | None,
) -> tuple[DemoDateEvent, ...]:
    if presentation is None:
        return ()
    if (
        presentation.document_id != plan.document_identity.document_id
        or presentation.source_pdf_sha256 != plan.document_identity.source_pdf_sha256
    ):
        raise ValueError("date presentation identity mismatch")
    result = []
    for event in presentation.events:
        if (
            event.intake_year != request.intake.year
            or event.intake_month != request.intake.month
            or event.event_type not in event_types
        ):
            continue
        grouped: dict[str, list[DemoEvidenceHighlight]] = {}
        fact_order: list[str] = []
        for highlight in ordered_highlights_for_event(presentation, event):
            if highlight.fact_id not in grouped:
                grouped[highlight.fact_id] = []
                fact_order.append(highlight.fact_id)
            grouped[highlight.fact_id].append(
                DemoEvidenceHighlight(
                    highlight_id=highlight.highlight_id,
                    start=highlight.start,
                    end=highlight.end,
                    exact_text=highlight.exact_text,
                    claim_ids=highlight.claim_ids,
                )
            )
        evidence = tuple(
            _demo_evidence(
                plan,
                evidence_by_fact[fact_id],
                "日期结论仅复述已审核的官方日期语义；请通过原文与 PDF 页码最终核对。",
                request.intake,
                highlights=tuple(grouped[fact_id]),
                local_pdf_url=(
                    f"/documents/{presentation.document_id}/source.pdf"
                    if source_pdf_document_id == presentation.document_id
                    else None
                ),
            )
            for fact_id in fact_order
        )
        result.append(
            DemoDateEvent(
                event_id=event.event_id,
                event_type=event.event_type,
                label=event.label,
                display_text=event.display_text,
                start_date=event.start_date,
                start_time=event.start_time,
                end_date=event.end_date,
                end_time=event.end_time,
                timezone=event.timezone,
                nature=event.nature,
                precision=event.precision,
                unknown_fields=event.unknown_fields,
                uncertainty_note=event.uncertainty_note,
                highlight_ids=event.highlight_ids,
                evidence=evidence,
            )
        )
    return tuple(result)


__all__ = [
    "DemoApplicantComparisonRequest",
    "DemoApplicantComparisonResponse",
    "DemoApplicantInput",
    "DemoBaseRequirementsResponse",
    "DemoEvidence",
    "DemoDateEvent",
    "DemoEvidenceHighlight",
    "DemoModel",
    "DemoTargetCatalogResponse",
    "DemoTargetRequest",
    "DemoTargetSummary",
    "build_demo_applicant_profile",
    "build_demo_evidence_inventory",
    "build_demo_base_requirements",
    "build_demo_applicant_comparison",
    "build_demo_target_catalog",
    "build_demo_target_summary",
]
