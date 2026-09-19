"""Server-owned presentation models for the interactive applicant demo."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    model_validator,
)

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
    LanguageTestKind,
)
from ..reasoning.reviewed_report_evidence import (
    ReviewedReportEvidenceBundle,
    ReviewedReportEvidenceRecord,
)
from ..reasoning.reviewed_report_plan import ReviewedReportPlan
from ..schemas.document_identity import DegreeLevel, IntakeTerm


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


class DemoApplicantComparisonRequest(DemoModel):
    schema_version: Literal["1.0"] = "1.0"
    target: DemoTargetRequest
    applicant: DemoApplicantInput


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
                reviewed_summary=rule.annotation_note,
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
    return DemoApplicantComparisonResponse(
        target=base.target,
        comparison_statement="服务端已将个人自报信息与当前审核规则进行保守对照。",
        partial_checklist_statement="这是当前人工审核范围内的准备视图，不是学校官方完整 checklist。",
        limitation_statement="本结果不是完整 checklist，不判断最终资格、材料完整性、受理或录取。",
        items=tuple(items),
        counts=counts,
    )


def _demo_applicant_profile(
    target: DemoTargetRequest, applicant: DemoApplicantInput
) -> ApplicantProfile:
    credentials = None
    if applicant.credential_basis is not None or applicant.completion_state is not None:
        credentials = (
            {
                "institution_country_code": None,
                "degree_level": "bachelor",
                "credential_basis": applicant.credential_basis,
                "completion_state": applicant.completion_state,
                "completion_date": None,
                "expected_completion_date": None,
                "years_of_education": None,
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
                "individual_review_status": None,
                "individual_review_requested": None,
                "individual_review_completed": None,
            },
            "language_test_results": None,
        }
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
) -> DemoRequirement:
    return DemoRequirement(
        requirement_id=f"rule:{rule.rule_id}",
        category=category,
        title=title,
        description=description or rule.annotation_note,
        reviewed_summary=reviewed_summary,
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
    )


__all__ = [
    "DemoBaseRequirementsResponse",
    "DemoTargetCatalogResponse",
    "DemoTargetRequest",
    "build_demo_base_requirements",
    "build_demo_target_catalog",
]
