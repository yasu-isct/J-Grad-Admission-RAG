"""Server-owned presentation models for the interactive applicant demo."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..reasoning.applicability import ApplicabilityPredicate, ApplicabilityRule, PredicateOperator
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
                    requirement_id=f"material:{entry.code}",
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
