/* Pure presentation adapter. The server remains the authority for every finding. */
const statusNames = {
  required: "需要提交／满足对应条件时适用",
  conditional: "有条件适用",
  needs_information: "信息不足，待确认",
  needs_review: "需要学校或人工确认",
  not_applicable: "本条条件不适用",
  not_covered: "当前审核范围未覆盖",
  recorded: "已记录",
  possible_match: "可能匹配，仍需核对",
  submission_required: "需要提交",
  submission_not_required: "无需提交（仅此材料本身）",
  rule_not_applicable: "本条条件不适用，不能推定一般性免交",
  unknown: "未知／待确认",
  available: "已准备",
  not_yet: "尚未取得"
};
const categoryNames = {dates: "日期", eligibility: "申请资格", language: "语言", materials: "材料"};
function publicReviewedText(value) { return text(value).replace(/\bRULE-\d+[A-Z]?\b\s*/g, "").trim(); }
function publicStatus(value) { return statusNames[value] || "需核对具体说明"; }

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}
function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
function nonempty(value) { return typeof value === "string" && value.trim().length > 0; }
function array(value) { return Array.isArray(value) ? value : []; }
function text(value) { return value == null ? "" : String(value); }

export function readyEntries(catalog) {
  requireValue(catalog?.schema_version === "1.0" && Array.isArray(catalog.items), "能力目录无效");
  const entries = catalog.items.filter((item) => item.availability === "ready");
  const ids = new Set();
  for (const item of entries) {
    requireValue(nonempty(item.entry_id) && !ids.has(item.entry_id), "能力目录身份重复");
    requireValue(["legacy_applicant", "reviewed_material_slice"].includes(item.kind), "能力类型无效");
    requireValue(item.capabilities?.evidence_browse && item.capabilities?.reference_report, "能力广告与页面不一致");
    if (item.kind === "legacy_applicant") requireValue(item.legacy_catalog?.school_name, "旧目录缺失");
    else requireValue(item.target && item.request_profile_target && nonempty(item.snapshot_id), "材料切片身份缺失");
    ids.add(item.entry_id);
  }
  return entries;
}

export function scopesFor(item) {
  if (item.kind === "reviewed_material_slice") {
    const target = item.target;
    return [{
      entry_id: item.entry_id, kind: item.kind, item,
      school: item.institution_name,
      organization: item.organization_name,
      program: item.program_alias
        ? `${item.program_alias} / ${item.program_display_name || item.program_name}`
        : item.program_display_name || item.program_name,
      degree: target.degree_level === "master" ? "修士" : target.degree_level,
      edition: `${target.admission_cycle} 年度 · 历史资料`,
      intake: `${target.intake.year} 年 ${target.intake.month} 月`,
      route: `${target.selection_route_id === "general-ordinary" ? "一般选拔" : target.selection_route_id} · ${target.examination_schedule_id} 日程`,
      request: null,
    }];
  }
  const school = item.legacy_catalog;
  const result = [];
  for (const degree of array(school.degrees))
    for (const intake of array(degree.intakes))
      for (const college of array(intake.colleges))
        for (const department of array(college.departments)) {
          const routes = array(department.application_routes);
          for (const route of routes.length ? routes : [null]) result.push({
            entry_id: item.entry_id, kind: item.kind, item,
            school: school.school_name, organization: college.college_name,
            program: department.department_name, degree: degree.degree_name,
            // The old catalog has an intake and document identity, but no separate admission cycle.
            edition: item.legacy_edition_labels?.[intake.document_id]
              || "当前已审核募集要项（版本名称未提供）",
            intake: intake.intake_name, route: route?.route_name || "一般选拔",
            request: {
              schema_version: "1.0", school_id: school.school_id,
              document_id: intake.document_id, degree_id: degree.degree_id,
              intake: {year: intake.year, month: intake.month},
              college_id: college.college_id, department_id: department.department_id,
              application_route: route?.route_id || null
            }
          });
        }
  requireValue(result.length > 0, "审核目标目录为空");
  return result;
}

export function scopeKey(scope) {
  return JSON.stringify([scope.entry_id, scope.request || scope.item.target]);
}
export function scopeLabel(scope) {
  return [scope.school, scope.organization, scope.program, scope.degree, scope.edition, scope.intake, scope.route].filter(Boolean).join(" · ");
}

export function legacyApplicant(controls) {
  const value = (id) => controls[id] || null;
  const concrete = (id) => {
    const selected = value(id);
    return selected && !selected.startsWith("ui_") ? selected : null;
  };
  const score = value("english_score");
  requireValue(!score || concrete("english_test_kind"), "填写英语分数时须选择考试类型");
  requireValue(!value("english_test_date") || concrete("english_test_kind"), "填写考试日期时须选择考试类型");
  requireValue(!score || (Number.isFinite(Number(score)) && Number(score) >= 0 && Number(score) <= 10000), "英语分数无效");
  return {
    credential_basis: concrete("credential_basis"),
    completion_state: concrete("completion_state"),
    english_test_kind: concrete("english_test_kind"),
    english_score: score === null ? null : Number(score),
    english_test_date: value("english_test_date"),
    english_official_report_available: value("english_official_report_available") === "true" ? true
      : value("english_official_report_available") === "false" ? false : null,
    japanese_background: concrete("japanese_background"),
    materials: array(controls.materials).map((item) => ({
      code: item.code,
      preparation: ["available", "not_yet"].includes(item.value) ? item.value : "unknown"
    }))
  };
}

export function hasSuppliedProfile(controls) {
  return Object.entries(controls).some(([key, value]) => key === "materials"
    ? array(value).some((item) => nonempty(item.value))
    : nonempty(value));
}

export function comparisonRequest(scope, controls) {
  requireValue(scope.kind === "legacy_applicant" && scope.request, "目标类型不匹配");
  return {schema_version: "1.0", target: scope.request, applicant: legacyApplicant(controls),
    ...(controls.english_preparation ? {english_preparation: controls.english_preparation} : {}),
    ...(controls.application_preparation ? {application_preparation: controls.application_preparation} : {})};
}

export function validateEnglishPreparationResult(scope, payload) {
  const result = payload?.english_preparation_result;
  requireValue(scope?.kind === "legacy_applicant" && result
    && result.document_id === scope.request.document_id
    && legacyTargetMatches(scope, result.target) && Array.isArray(result.checks),
  "英语核对结果与当前目标不匹配");
  const ids = new Set();
  for (const check of result.checks) {
    requireValue(nonempty(check.check_id) && !ids.has(check.check_id)
      && ["reported_match", "action_needed", "needs_information", "not_applicable", "not_covered"].includes(check.status)
      && nonempty(check.title) && nonempty(check.explanation) && nonempty(check.next_action)
      && Array.isArray(check.rule_ids) && Array.isArray(check.evidence), "英语核对项无效");
    ids.add(check.check_id);
    if (["reported_match", "action_needed"].includes(check.status))
      requireValue(check.rule_ids.length > 0 && check.evidence.length > 0, "英语核对依据缺失");
    for (const source of check.evidence) validateLegacyEvidence(source, scope);
  }
  return result;
}

export function validateApplicationPreparationResult(scope, payload) {
  const result = payload?.application_preparation_result;
  requireValue(scope?.kind === "legacy_applicant" && result
    && result.document_id === scope.request.document_id
    && legacyTargetMatches(scope, result.target) && Array.isArray(result.checks),
  "毕业与提交核对结果与当前目标不匹配");
  const ids = new Set();
  for (const check of result.checks) {
    requireValue(nonempty(check.check_id) && !ids.has(check.check_id)
      && ["reported_match", "action_needed", "needs_information", "not_applicable", "not_covered"].includes(check.status)
      && nonempty(check.title) && nonempty(check.explanation) && nonempty(check.next_action)
      && Array.isArray(check.rule_ids) && Array.isArray(check.evidence), "毕业与提交核对项无效");
    ids.add(check.check_id);
    if (check.status === "reported_match")
      requireValue(check.rule_ids.length > 0 && check.evidence.length > 0, "毕业与提交核对依据缺失");
    for (const source of check.evidence) validateLegacyEvidence(source, scope);
  }
  return result;
}

export function sliceReportRequest(scope, employment) {
  requireValue(scope.kind === "reviewed_material_slice", "目标类型不匹配");
  const item = scope.item, target = item.target, alias = item.request_profile_target;
  const condition = (value) => value === "yes" ? true : value === "no" ? false : null;
  return {
    schema_version: "1.0", target,
    applicant_profile: {
      schema_version: "1.0",
      target_application: {
        graduate_school_or_college: alias.graduate_school_or_college,
        department_or_program: alias.department_or_program,
        requested_degree_level: target.degree_level,
        intake_year: target.intake.year, intake_month: target.intake.month,
        application_route: alias.application_route
      },
      citizenship_and_residence: {citizenship_country_codes: null, current_residence_country_code: null, residence_status_category: null},
      academic_credentials: null,
      eligibility_facts: {age_at_enrollment: null, professional_experience_months: null, research_experience_months: null, individual_review_status: null, individual_review_requested: null, individual_review_completed: null},
      language_test_results: null, application_submission: null, preapplication_actions: null
    },
    employment: {
      currently_employed_in_organization: condition(employment.current),
      retain_employment_at_enrollment: condition(employment.retain)
    }
  };
}

function validHttps(raw) {
  try {
    const url = new URL(raw);
    return url.protocol === "https:" && !url.username && !url.password;
  } catch { return false; }
}

function validateLegacyEvidence(evidence, scope) {
  requireValue(nonempty(evidence?.official_title) && nonempty(evidence?.official_text)
    && validHttps(evidence?.source_url)
    && evidence.document_id === scope.request.document_id
    && evidence.school_name === scope.school
    && evidence.intake_name === scope.intake
    && array(evidence.pages).length > 0
    && array(evidence.pages).every((page) => Number.isSafeInteger(page) && page > 0), "官方依据不完整");
  for (const mark of array(evidence.highlights))
    requireValue(evidence.official_text.slice(mark.start, mark.end) === mark.exact_text, "官方引文与原文不一致");
  return {
    title: evidence.official_title, pages: evidence.pages,
    fact_id: evidence.fact_id, document_id: evidence.document_id,
    printed: null, quote: evidence.official_text, source_url: evidence.source_url,
    local_pdf_url: evidence.local_pdf_url || null, context: evidence.limitation || "",
    highlights: array(evidence.highlights)
  };
}

function legacyTargetMatches(scope, target) {
  return target?.school_name === scope.school && target?.degree_name === scope.degree
    && target?.intake_name === scope.intake && target?.college_name === scope.organization
    && target?.department_name === scope.program
    && (target?.application_route_name || null) === (scope.route === "一般选拔" ? null : scope.route);
}

export function mapLegacyBase(scope, base) {
  requireValue(scope.kind === "legacy_applicant" && base?.schema_version === "1.0"
    && legacyTargetMatches(scope, base.target) && Array.isArray(base.requirements), "基础要求目标不匹配");
  const topics = base.requirements.map((requirement) => {
    const sources = array(requirement.evidence).map((source) => validateLegacyEvidence(source, scope));
    const dates = array(requirement.date_events).map((event) => {
      const eventSources = array(event.evidence).map((source) => validateLegacyEvidence(source, scope));
      requireValue(eventSources.length > 0, "日期依据缺失");
      return {
        label: event.label, display: event.display_text,
        event_type: event.event_type || null,
        precision: event.precision, unknown: array(event.unknown_fields),
        uncertainty: event.uncertainty_note || "", sources: eventSources
      };
    });
    if (!["not_covered", "needs_review", "needs_information"].includes(requirement.official_status))
      requireValue(sources.length > 0 || dates.length > 0, "已审核要求缺少引用");
    return {
      id: requirement.requirement_id, category: requirement.category, title: requirement.title,
      summary: publicReviewedText(requirement.reviewed_summary || requirement.description),
      description: publicReviewedText(requirement.description),
      status: statusNames[requirement.official_status] || requirement.official_status,
      status_code: requirement.official_status,
      deadline: requirement.deadline || "", limitation: requirement.limitation || "",
      dates, sources,
      guide: requirement.category === "materials"
        ? materialGuide(scope, {id: requirement.requirement_id, sources}) : null
    };
  });
  return {
    scope, topics, coverage: base.coverage_statement,
    limitation: base.limitation_statement, target: base.target,
    raw: base
  };
}

const examSource = {
  institution_id: "isct", document_id: "isct_2027_4_2026_9_master",
  source_pdf_sha256: "57fdb935ffd2f6aa759f2c77f58b45826977225239fc1576d932b891ea50c735",
  source_kb_sha256: "7fa46e49b7949aec289746dd5ec3c839969a822874f76c26f9ad2b64bc00f5ce"
};
const examPresentationSha = "368ed4de43dd2dde8eda986d2ad2d6922e8cfb7c3640583381b1b559a4170aa7";
const examPresentationV2Sha = "906ceaa57ac615f1d2acb1da1265f93c690e8574b31fc8a2303e2b12605acfad";

function validateExamInformationV2(scope, info) {
  try {
    requireValue(scope?.kind === "legacy_applicant" && info?.schema_version === "2.0"
      && ["available_official_paths", "not_covered", "not_covered_course", "unavailable"].includes(info.status), "考试信息状态无效");
    const request = scope.request;
    requireValue(Object.keys(request).every((key) => same(request[key], info.target_identity?.[key])), "考试信息目标不匹配");
    if (info.status !== "available_official_paths") {
      requireValue(same(info.pathways, []) && same(info.evidence, []) && same(info.field_bindings, []), "未覆盖考试信息含肯定结论");
      if (info.status === "not_covered_course") requireValue(info.applicability?.course_state === "excluded"
        || info.applicability?.course_state === "unknown", "课程排除状态无效");
      return {status: info.status, message: info.message_zh};
    }
    requireValue(request.school_id === "isct" && request.document_id === examSource.document_id
      && request.degree_id === "master" && [[2026, 9], [2027, 4]].some(([year, month]) =>
        request.intake.year === year && request.intake.month === month)
      && info.presentation_id === "isct-18-departments-exams-2026-v2"
      && info.presentation_sha256 === examPresentationV2Sha
      && same(info.source_identity, examSource), "考试来源身份不匹配");
    const applicability = info.applicability;
    requireValue(applicability?.catalog_route === request.application_route
      && applicability.personal_route_state === (request.application_route === "b_schedule" ? "catalog_b" : "unconfirmed")
      && ["unspecified", "covered"].includes(applicability.course_state)
      && Array.isArray(applicability.covered_course_ids) && Array.isArray(applicability.excluded_course_ids)
      && (applicability.covered_course_ids.length === 0
        ? applicability.excluded_course_ids.length === 0
        : same(applicability.excluded_course_ids, ["地球生命コース"])), "考试路径或课程作用域不匹配");
    requireValue(info.year_basis?.exam_year === 2026
      && info.year_basis.kind === "reviewed_cross_page_context"
      && same(info.year_basis.physical_pages, [1, 2])
      && Number.isSafeInteger(info.year_basis.department_page), "考试年份来源不完整");
    const evidence = array(info.evidence);
    const evidenceById = new Map();
    for (const row of evidence) {
      validateLegacyEvidence(row, scope);
      requireValue(nonempty(row.fact_id) && row.scope_type === "department"
        && row.parent_college === request.college_id
        && array(row.scope_targets).includes(request.department_id), "考试证据作用域不匹配");
      requireValue(!evidenceById.has(row.fact_id), "考试证据重复");
      evidenceById.set(row.fact_id, row);
    }
    const bindings = new Map();
    for (const field of array(info.field_bindings)) {
      requireValue(nonempty(field.field_path) && !bindings.has(field.field_path), "考试字段重复");
      if (field.value_zh === null)
        requireValue(nonempty(field.missing_reason_zh) && same(field.sources, []), "未知字段伪装为有依据");
      else {
        requireValue(nonempty(field.value_zh) && array(field.sources).length > 0, "考试字段来源缺失");
        for (const source of field.sources) {
          requireValue(nonempty(source.exact_text) && array(source.physical_pages).length > 0, "考试原文锚点缺失");
          if (source.source_id === "fact:00002") requireValue(field.field_path === "exam.year", "年份来源越界");
          else if (source.source_id.startsWith("fact:")) {
            const row = evidenceById.get(source.source_id);
            requireValue(row && same(row.pages, source.physical_pages)
              && row.official_text.includes(source.exact_text), "考试原文与字段不符");
          } else requireValue(source.source_id === `pdf_page:${source.physical_pages[0]}`
            && source.physical_pages.length === 1, "PDF页锚点不符");
        }
      }
      bindings.set(field.field_path, field);
    }
    const required = ["exam.year", "a.oral", "b.written_status", "b.written_sessions", "b.subjects",
      "b.selection_rule", "b.points", "english.submission", "b.oral", "b.answer_language"];
    requireValue(required.every((key) => bindings.has(key))
      && (applicability.covered_course_ids.length === 0 || bindings.has("course.coverage_exclusion")), "考试字段覆盖不足");
    const value = (key) => bindings.get(key)?.value_zh?.replaceAll("**", "") ?? null;
    const paths = array(info.pathways);
    requireValue(paths.length === 2 && paths[0].source_route === "a_schedule"
      && paths[1].source_route === "b_schedule"
      && paths.every((path) => path.personal_eligibility === (request.application_route === "b_schedule"
        && path.source_route === "b_schedule" ? "catalog_b" : "unconfirmed")), "官方路径与个人适用性混淆");
    const a = paths[0];
    const b = paths[1];
    requireValue(a.oral?.description_zh === value("a.oral")
      && a.oral.status === (value("a.oral").includes("明确不举行") ? "not_held" : "held")
      && a.written.status === "unknown" && b.oral?.description_zh === value("b.oral")
      && b.written?.status === value("b.written_status")
      && b.written.points_zh === value("b.points")
      && b.english?.submission_zh === value("english.submission"), "考试路径内容与来源映射不一致");
    if (b.written.status === "held") requireValue(
      b.written.time_zh === value("b.written_sessions")
      && array(b.written.subjects_zh).length > 0
      && b.written.subjects_zh.join("；") === value("b.subjects")
      && b.written.selection_rule_zh === value("b.selection_rule")
      && b.written.answer_language_zh === value("b.answer_language")
      && b.written.administration_language_zh === value("exam.administration_language"), "笔试科目或时段与来源不符");
    else requireValue(b.written.status === "not_held" && b.written.time_zh === null
      && same(b.written.subjects_zh, []), "无笔试状态含笔试内容");
    return {status: "available", schema_version: "2.0", pathways: paths,
      applicability, evidence, field_bindings: info.field_bindings, year_basis: info.year_basis,
      message: info.message_zh, official_title: info.official_title,
      official_source_url: info.official_source_url, local_pdf_url: info.local_pdf_url};
  } catch { return null; }
}

export function validateExamInformation(scope, info) {
  if (info?.schema_version === "2.0") return validateExamInformationV2(scope, info);
  try {
    requireValue(scope?.kind === "legacy_applicant" && info?.schema_version === "1.0"
      && ["available", "not_covered", "unavailable"].includes(info.status), "考试信息状态无效");
    const request = scope.request;
    requireValue(Object.keys(request).every((key) => same(request[key], info.target_identity?.[key])), "考试信息目标不匹配");
    if (info.status !== "available") {
      requireValue(info.schedule === null && same(info.evidence, []), "未知考试信息含肯定内容");
      return {status: info.status, message: info.message_zh};
    }
    requireValue(request.school_id === "isct" && request.document_id === examSource.document_id
      && request.college_id === "情報理工学院" && request.department_id === "情報工学系"
      && request.degree_id === "master" && request.application_route === "b_schedule"
      && [[2026, 9], [2027, 4]].some(([year, month]) => request.intake.year === year && request.intake.month === month)
      && info.presentation_id === "isct-cs-b-exams-2026-v1"
      && info.presentation_sha256 === examPresentationSha
      && same(info.source_identity, examSource), "考试信息来源不匹配");
    const s = info.schedule;
    requireValue(s && s.route === "b_schedule" && s.exam_year === 2026 && s.timezone === "Asia/Tokyo"
      && s.written_date === "2026-08-18" && s.written_start_time === "09:30"
      && s.written_end_time === "12:00" && s.duration_minutes === 150
      && s.questions_per_group === 1 && s.total_questions === 3
      && s.answer_language === "ja" && s.specialist_points === 900 && s.english_points === 100
      && s.english_assessment === "external_score" && s.oral_date === "2026-08-24"
      && s.oral_announcement_date === "2026-08-20" && s.oral_announcement_time === "17:00"
      && s.oral_announcement_time_qualifier === "around_from"
      && same(s.subject_groups, [
        {group: "A", subjects_zh: ["微积分", "线性代数", "概率统计"]},
        {group: "B", subjects_zh: ["数理逻辑", "自动机与形式语言"]},
        {group: "C", subjects_zh: ["数据结构与算法", "编程"]}
      ]) && nonempty(s.oral_selection_note_zh), "考试安排不完整");
    requireValue(info.year_basis?.kind === "reviewed_cross_page_context"
      && info.year_basis.exam_year === 2026 && same(info.year_basis.physical_pages, [1, 2, 52])
      && same(info.year_basis.source_ids, ["pdf:cover:1", "fact:00002", "fact:00004", "fact:00288"]), "考试年份依据不完整");
    const evidence = array(info.evidence);
    requireValue(evidence.length === 3 && same(evidence.map((row) => row.fact_id),
      ["fact:00288", "fact:00289", "fact:00287"]), "考试原文依据不完整");
    for (const row of evidence) {
      validateLegacyEvidence(row, scope);
      requireValue(same(row.pages, [52]) && row.scope_type === "department"
        && same(row.scope_targets, ["情報工学系"]) && row.parent_college === "情報理工学院", "考试原文作用域不匹配");
    }
    return {status: "available", schedule: s, evidence, year_basis: info.year_basis};
  } catch { return null; }
}

export function examReportRows(exam) {
  if (exam?.status !== "available") return [];
  if (exam.schema_version === "2.0") {
    const view = examV2View(exam);
    return [view.lead, view.course, ...view.subjects, view.selection, view.points, view.aOral,
      view.bOral, view.specialist, view.english, view.language].filter(Boolean);
  }
  const s = exam.schedule;
  const dateZh = (value, year = true) => {
    const [y, m, d] = value.split("-").map(Number);
    return `${year ? `${y}年` : ""}${m}月${d}日`;
  };
  return [
    `专业笔试：${dateZh(s.written_date)} ${s.written_start_time}–${s.written_end_time}（日本时间，${s.duration_minutes}分钟）。`,
    ...s.subject_groups.map((group) => `${group.group}组：${group.subjects_zh.join("、")}。`),
    `每组各出${s.questions_per_group}题，共${s.total_questions}题；专业笔试用日语作答。`,
    `专业笔试${s.specialist_points}分，英语${s.english_points}分；英语不另设笔试，按指定外部英语成绩评价，仍需按规定提交证明。`,
    `口述对象：${dateZh(s.oral_announcement_date, false)}${Number(s.oral_announcement_time.split(":")[0])}时左右起公布；口述日期${dateZh(s.oral_date, false)}。${s.oral_selection_note_zh}`
  ];
}

export function examV2View(exam) {
  requireValue(exam?.schema_version === "2.0" && exam.status === "available", "考试资料尚未校验");
  const [a, b] = exam.pathways;
  const written = b.written;
  const scope = exam.applicability.personal_route_state === "catalog_b"
    ? "信息工学系目录为 B 日程；A 日程仅作为同册官方资料查阅。"
    : "学校公布的 A/B 日程可查阅；本人参加路径与资格须由学校确认。";
  const lead = written.status === "not_held"
    ? `学校公布的 B 日程明确不举行笔试。${scope}`
    : `学校公布的 B 日程笔试：2026年8月18日 ${written.time_zh
      .replace(/^8\/18\s*/, "").split("；时长（分钟）：")[0]}。${scope}`;
  const subjects = written.status === "held" ? [written.subjects_zh.join("；")] : [];
  const selection = written.status === "held" && written.selection_rule_zh
    ? `选答方式：${written.selection_rule_zh}` : null;
  const points = written.points_zh ? `评价与英语：${written.points_zh}` : null;
  const aOral = `${a.label_zh}口述：${a.oral.description_zh.replace(/^A：/, "")}。`;
  const bOral = `${b.label_zh}口述：${b.oral.description_zh.replaceAll("**", "")}。`;
  const condition = exam.field_bindings.find((field) => field.field_path === "b.specialist_condition")?.value_zh;
  const specialist = condition ? `专门科目条件：${condition.replaceAll("**", "")}。` : null;
  const english = b.english.submission_zh ? `本系英语证明原文：${b.english.submission_zh}。材料准备结果仍按既有规则核对。` : null;
  const language = written.answer_language_zh
    ? `笔试作答语言：${written.answer_language_zh}。`
    : written.administration_language_zh ? `考试实施语言：${written.administration_language_zh}；原文未另载笔试答案语言。` : null;
  const course = exam.applicability.excluded_course_ids.length
    ? `本册覆盖课程：${exam.applicability.covered_course_ids.join("、")}；${exam.applicability.excluded_course_ids.join("、")}采用另册，当前未覆盖其考试安排。` : null;
  return {lead, subjects, selection, points, aOral, bOral, specialist, english, language, course};
}

export function mapSliceEvidence(scope, evidence) {
  requireValue(scope.kind === "reviewed_material_slice"
    && evidence?.schema_version === "1.0"
    && evidence.snapshot_id === scope.item.snapshot_id
    && same(evidence.target, scope.item.target)
    && (!Number.isSafeInteger(scope.item.revision) || evidence.revision === scope.item.revision)
    && Array.isArray(evidence.topics) && evidence.topics.length > 0, "官方依据与当前目标不匹配");
  const topics = evidence.topics.map((topic) => {
    const sources = array(topic.records).map((record) => {
      requireValue(nonempty(record.source_title) && Number.isSafeInteger(record.physical_page)
        && record.physical_page > 0 && array(record.fragments).length > 0, "材料依据不完整");
      const quotes = record.fragments.map((fragment) => {
        requireValue(nonempty(fragment.quote_text), "材料原文缺失");
        return fragment.quote_text;
      });
      return {
        title: record.source_title, pages: [record.physical_page],
        printed: record.printed_page_label, quote: quotes.join("\n\n"),
        source_url: record.official_source_url, local_pdf_url: null,
        source_id: record.source_id, role: record.role, stage: record.stage,
        fragments: record.fragments,
        heading: array(record.official_heading_path).join(" › "),
        context: [record.scope_note_zh, array(record.official_heading_path).join(" › "),
          record.role === "basis" ? "本条依据" : "关联上下文",
          record.stage === "enrollment_context_only" ? "入学手续关联，非申请阶段义务" : ""].filter(Boolean).join(" · "),
        record_id: record.record_id
      };
    });
    requireValue(sources.length > 0, "材料主题依据缺失");
    const ids = new Set(sources.map((source) => source.record_id));
    const relations = array(topic.relations).filter((relation) => relation
      && ids.has(relation.from) && ids.has(relation.to) && typeof relation.kind === "string");
    return {
      id: topic.topic_id, category: "materials", title: topic.material_name_zh,
      summary: topic.context_note_zh, description: topic.context_note_zh,
      status: "当前条件待报告判断", status_code: "needs_information",
      deadline: "", limitation: "", dates: [], sources, relations
    };
  });
  if (scope.item.snapshot_id === authorEssayIdentity.snapshot_id) {
    requireValue(authorEssayScopeMatches(scope)
      && topics.length === 4 && new Set(topics.map((topic) => topic.id)).size === 4
      && ["english-score-sheets", "checklist-submission", "work-study-plan", "application-essay"]
        .every((id) => topics.some((topic) => topic.id === id)), "新材料切片范围不匹配");
    const essay = topics.find((topic) => topic.id === "application-essay");
    requireValue(authorEssaySourcesMatch(essay.sources), "小论文原文或表头缺失");
  }
  return {
    scope, topics, coverage: `历史招生资料 · 已审核的 ${topics.length} 个材料主题`,
    limitation: array(evidence.limitations_zh).join("；"), target: evidence.target,
    raw: evidence
  };
}

function sourceLines(source) {
  const page = source.pages.join("、");
  return [`出处：${source.title} · 物理页 ${page}${source.printed ? `（印刷页 ${source.printed}）` : ""}`,
    source.context ? `上下文：${source.context}` : "",
    `官方原文：${source.quote}`, `官方链接：${source.source_url}`].filter(Boolean);
}

export function legacyReport(mapped, comparison = null, profileDisclosure = [], exam = null) {
  requireValue(mapped?.scope?.kind === "legacy_applicant" && mapped.topics?.length, "当前要求尚未加载");
  if (comparison) {
    requireValue(Array.isArray(profileDisclosure), "个人情况展示无效");
    requireValue(comparison.schema_version === "1.0"
      && legacyTargetMatches(mapped.scope, comparison.target)
      && Array.isArray(comparison.items)
      && comparison.counts?.total === comparison.items.length, "个人对照目标不匹配");
    if (comparison.english_preparation_result)
      validateEnglishPreparationResult(mapped.scope, comparison);
    if (comparison.application_preparation_result)
      validateApplicationPreparationResult(mapped.scope, comparison);
    for (const item of comparison.items) {
      // This field records only the applicant's Japanese background; it makes no official finding.
      const applicantOnlyJapanese = item.item_id === "japanese:background"
        && item.category === "japanese" && item.comparison_status === "recorded"
        && item.official_status == null;
      if (!applicantOnlyJapanese
        && !["not_covered", "needs_review", "needs_information"].includes(item.comparison_status))
        requireValue(array(item.evidence).length > 0, "个人对照引用缺失");
    }
  }
  const intro = [
    "募集要项参考报告", scopeLabel(mapped.scope), "",
    "资料性质：当前已审核结果的页面导出；不是最终资格判断。",
    `审核覆盖：${mapped.coverage}`, `范围限制：${mapped.limitation}`
  ];
  const topics = mapped.topics.map((topic, index) => {
    const lines = [`类别：${categoryNames[topic.category] || "其他已审核事项"}；官方状态：${topic.status}`,
      `说明：${topic.summary}`];
    if (topic.description !== topic.summary) lines.push(`详情：${topic.description}`);
    if (topic.deadline) lines.push(`截止说明：${topic.deadline}`);
    const references = [];
    for (const date of topic.dates) {
      lines.push(`日期：${date.label} · ${date.display} · 精度 ${date.precision}`);
      if (date.unknown.length) lines.push(`未知时间字段：${date.unknown.join("、")}`);
      if (date.uncertainty) lines.push(`日期限制：${date.uncertainty}`);
      references.push(...date.sources);
    }
    references.push(...topic.sources);
    if (topic.limitation) lines.push(`限制：${topic.limitation}`);
    return {heading: `${index + 1}. ${topic.title}`, lines, references};
  });
  const lines = [...intro, "", "基础要求"];
  for (const topic of topics)
    lines.push("", topic.heading, ...topic.lines, ...topic.references.flatMap(sourceLines));
  let comparisonPresentation = null;
  if (comparison) {
    const overview = [comparison.comparison_statement,
      `准备状态：共 ${comparison.counts.total} 项；需补充 ${comparison.counts.action_required}；需审核 ${comparison.counts.review_required}；已记录 ${comparison.counts.recorded}`,
      "本次自报；未填写／不知道保持未知，自报不适用不代表官方豁免："];
    for (const field of profileDisclosure) {
      requireValue(nonempty(field.label) && nonempty(field.value), "个人情况展示缺失");
      overview.push(`${field.label}：${field.value}`);
    }
    const items = comparison.items.map((item) => {
      const itemLines = [item.description, `下一步：${item.next_action}`];
      if (item.official_status) itemLines.push(`官方适用性：${publicStatus(item.official_status)}`);
      if (item.preparation_status) itemLines.push(`自报准备状态：${publicStatus(item.preparation_status)}`);
      if (item.limitation) itemLines.push(`限制：${item.limitation}`);
      return {
        heading: `${item.title} · ${publicStatus(item.comparison_status)}`,
        lines: itemLines,
        references: array(item.evidence).map((evidence) => validateLegacyEvidence(evidence, mapped.scope))
      };
    });
    const end = [comparison.partial_checklist_statement, comparison.limitation_statement];
    comparisonPresentation = {overview, items, end};
    lines.push("", "个人情况与规则对照（仅依据本次自报）", ...overview);
    for (const item of items)
      lines.push("", item.heading, ...item.lines, ...item.references.flatMap(sourceLines));
    lines.push(...end);
  } else lines.push("", "未加入个人情况；不作个人适用性判断。");
  const conclusion = "请逐项核对未覆盖内容、未知条件与官方原文；材料准备不代表学校已受理。";
  lines.push("", conclusion);
  return {kind: "legacy_applicant", scope: mapped.scope, topics: mapped.topics,
    ...(exam?.status === "available" ? {exam} : {}),
    comparison, profileDisclosure, text: lines.join("\n"), raw: {base: mapped.raw, comparison},
    presentation: {intro: intro.slice(3), topics, comparison: comparisonPresentation, conclusion}};
}

export function sliceReport(scope, mapped, payload, employment = {current: "unknown", retain: "unknown"}, preparation = {}) {
  requireValue(scope.kind === "reviewed_material_slice" && mapped?.raw?.snapshot_id === scope.item.snapshot_id
    && payload?.schema_version === "1.0" && payload.slice_id === scope.entry_id
    && payload.snapshot_id === scope.item.snapshot_id && same(payload.report?.target, scope.item.target)
    && payload.report.status === "evaluated" && Array.isArray(payload.report.topic_results)
    && nonempty(payload.markdown), "报告与当前目标或证据不匹配");
  const citations = new Map(array(payload.report.evidence_inventory).map((row) => [row.citation_key, row]));
  requireValue(citations.size === array(payload.report.evidence_inventory).length, "报告引用重复");
  const loadedSources = mapped.topics.flatMap((topic) => topic.sources);
  const topics = payload.report.topic_results.map((result) => {
    const keys = [...array(result.basis_citation_keys), ...array(result.context_citation_keys)];
    requireValue(array(result.basis_citation_keys).length > 0 && keys.every((key) => citations.has(key)), "报告引用缺失");
    const sourceRecords = keys.map((key) => citations.get(key));
    for (const row of sourceRecords) requireValue(nonempty(row.quote_text)
      && nonempty(row.source_title) && array(row.physical_pages).length > 0
      && loadedSources.some((source) => source.record_id === row.record_id
        && source.title === row.source_title
        && source.pages.length === row.physical_pages.length
        && source.pages.every((page, index) => page === row.physical_pages[index])
        && source.quote.includes(row.quote_text)), "报告引文与已加载原文不一致");
    const mappedTopic = mapped.topics.find((topic) => topic.id === result.topic_id);
    return {
      id: result.topic_id, material_code: result.material_code,
      title: result.material_name_zh,
      status: statusNames[result.disposition] || result.disposition,
      status_code: result.disposition, condition: result.condition_status,
      explanation: result.explanation_zh, missing_fields: array(result.missing_fields),
      limitations: array(result.limitations_zh),
      citations: sourceRecords,
      guide: mappedTopic ? materialGuide(scope, mappedTopic) : null
    };
  });
  requireValue(topics.length === mapped.topics.length, "材料主题数量不匹配");
  requireValue(["unknown", "yes", "no"].includes(employment.current)
    && ["unknown", "yes", "no"].includes(employment.retain), "个人条件无效");
  const conditionName = {unknown: "未知／待确认", yes: "是", no: "否"};
  const wrapper = [
    "募集要项参考报告", scopeLabel(scope),
    "历史资料、部分材料范围；请核对报告中的条件、未知事项和完整官方出处。",
    `本次自报：目前受雇 ${conditionName[employment.current]}；入学后继续在职 ${conditionName[employment.retain]}。`,
    "", payload.markdown, "", "已加载原文引文（与预览一致）",
    ...topics.flatMap((topic) => [topic.title, ...topic.citations.flatMap((cite) => [
      `${cite.source_title} · 物理页 ${cite.physical_pages.join("、")}${cite.printed_page_label ? ` · 印刷页 ${cite.printed_page_label}` : ""}`,
      cite.quote_text
    ])])
  ].join("\n");
  return withSlicePreparation({kind: "reviewed_material_slice", scope, topics, employment, text: wrapper,
    canonicalMarkdown: payload.markdown, raw: payload.report}, preparation);
}

// Applicant input is a page-local projection; it never changes the reviewed disposition.
export function withSlicePreparation(report, preparation = {}) {
  requireValue(report?.kind === "reviewed_material_slice" && Array.isArray(report.topics)
    && preparation && typeof preparation === "object" && !Array.isArray(preparation)
    && Object.entries(preparation).every(([key, value]) =>
      report.topics.some((topic) => topic.id === key)
      && ["unknown", "available", "not_yet"].includes(value)), "材料准备自报无效");
  return {...report, preparation: {...preparation}};
}

const readerTopicNames = {dates: "关键时间", materials: "材料与待办", other: "其他已加载要求", exams: "考试安排"};

const authorEssayIdentity = {
  kind: "reviewed_material_slice", institution_id: "utokyo", organization_id: "utokyo-gsfs",
  program_id: "utokyo-gsfs-complex", degree_level: "master", admission_cycle: 2027,
  selection_route_id: "general-ordinary", examination_schedule_id: "A", intake_year: 2027,
  intake_month: 4, target_id: "utokyo-gsfs-complex-master-2027-general-a-202704",
  snapshot_id: "a729b19705be68c9a4e79bc71d6dbaaed12710989aeac79b90cf34347bf89164"
};
const authorEssayGuide = {
  purpose: "本固定目标范围内申请人需要提交的小论文，用于说明希望研究的主题、动机和自身优势。",
  steps: ["使用专攻网站指定格式，以日语或英语填写。",
    "第一部分：写明希望研究的主题，以及对该主题感兴趣的理由。",
    "第二部分：结合过去学习、研究或课外活动经历，具体说明能用于修士阶段学习和研究的自身优势。",
    "出愿期间，通过网上出愿系统上传PDF。"],
  warnings: ["字数和版式以指定模板为准；本次资料未包含模板细目。",
    "本项来源只明确出愿期间，未核定具体截止日期或时刻。",
    "准备情况由本人填写，不代表学校确认材料已完成或申请资格成立。"],
  conditions: [],
  sourceNote: "中文要点整理自专攻追加材料表第1页与入试案内第28页（印刷26）；下方分别保留两份原文。"
};
const authorEssayFragments = {
  E09: ["令和9年度（2027）年度　修士課程入試（入試日程Ａ）出願に関する専攻独自の追加提出物一覧",
    "【複雑理工学専攻】", "出願期間中に「オンライン出願システム」により提出する書類等",
    "(※PDFファイルのアップロードによる）", "提出物", "小論文", "対象者，備考",
    "【対象者】全員", "日本語又は英語で作成すること。"],
  E10: ["修士課程 一般選抜", "小論文の作成・提出要領",
    "以下の(A)(B)を、当専攻ホームページで指定するフォーマットに日本語または英語で書くこと。文字数や書式などはフォーマットに指示する。オンライン出願サイトより提出せよ。",
    "（A) 取り組みたい研究テーマとそのテーマに興味を持った理由",
    "（B) 自己アピール：これまでの学修・研究・課外活動などの経験に基づき、修士課程での学修・研究に活かせる自分の強みを具体的に記述"]
};

function authorEssayScopeMatches(scope) {
  const identity = materialScopeIdentity(scope);
  return identity && Object.entries(authorEssayIdentity).every(([key, value]) => identity[key] === value);
}

function authorEssaySourcesMatch(sources) {
  const normalize = (value) => text(value).replace(/\s+/g, "");
  return array(sources).length === 2 && Object.entries(authorEssayFragments).every(([recordId, quotes]) => {
    const source = sources.find((row) => row.record_id === recordId);
    if (!source || source.role !== "basis" || source.stage !== "application"
      || source.source_id !== (recordId === "E09" ? "complex-master-a-additional" : "complex-guide-2027-revised")
      || !same(source.pages, [recordId === "E09" ? 1 : 28])
      || (recordId === "E10" && source.printed !== "26")
      || array(source.fragments).length !== quotes.length) return false;
    return quotes.every((quote, index) => {
      const matches = source.fragments.filter((fragment) => fragment.fragment_id === `${recordId}-${index + 1}`);
      return matches.length === 1 && normalize(matches[0].quote_text) === normalize(quote);
    });
  });
}

// Presentation only. Code meanings are bound to reviewed document/snapshot identity;
// applicability and preparation still come from reviewed responses.
const materialDisplays = [
  {identity: {kind: "legacy_applicant", school_id: "isct",
    document_id: "isct_2027_4_2026_9_master"}, materials: {
    address_label: ["邮寄地址标签", "宛名ラベル", "贴在提交出愿材料的信封上的标签。"],
    application_form: ["入学申请表", "入学志願票", "本次入学申请使用的正式表格。"],
    statement_of_purpose: ["志愿理由书", "志望理由書", "说明申请该方向理由的文书。"],
    bachelor_transcript: ["学士课程成绩证明", "学士課程の成績証明書", "记录学士课程成绩的证明文件。"],
    graduation_or_expected_graduation_certificate: ["毕业或预计毕业证明", "学士課程の卒業証明書又は卒業見込み証明書", "证明学士课程已毕业或预计毕业的文件。"]
  }},
  {identity: {kind: "reviewed_material_slice", institution_id: "utokyo",
    organization_id: "utokyo-gsfs", program_id: "utokyo-gsfs-complex",
    snapshot_id: "2794e4548763e98b36e168cb9a3a062d75008711c313a8a18fbb760bf19a9a98"}, materials: {
    "english-score-sheets": ["英语成绩单", "英語のスコアシート", "说明英语考试成绩的单据；是否提交按当前专攻要求判断。"],
    "checklist-submission": ["提交材料检查表", "提出書類等チェックシート（修士課程一般選抜用）", "用于核对待交文件；参照清单不等于要提交清单本身。"],
    "work-study-plan": ["学业与职务兼顾计划书", "学業・職務両立計画書", "说明在职入学时如何兼顾学业与职务的计划书。"]
  }},
  {identity: authorEssayIdentity, materials: {
    "english-score-sheets": ["英语成绩单", "英語のスコアシート", "说明英语考试成绩的单据；是否提交按当前专攻要求判断。"],
    "checklist-submission": ["提交材料检查表", "提出書類等チェックシート（修士課程一般選抜用）", "用于核对待交文件；参照清单不等于要提交清单本身。"],
    "work-study-plan": ["学业与职务兼顾计划书", "学業・職務両立計画書", "说明在职入学时如何兼顾学业与职务的计划书。"],
    "application-essay": ["申请小论文", "小論文", authorEssayGuide.purpose],
    application_essay: ["申请小论文", "小論文", authorEssayGuide.purpose]
  }}
];

// Human guidance is attached only to the exact reviewed p.10 table in this edition.
const isctMaterialGuides = {
  address_label: {
    purpose: "标明出愿材料邮寄收件信息的标签。",
    steps: ["从网上出愿个人页面取得，用A4纸彩色打印。", "贴在角形2号信封上（240×332毫米）。", "寄出前核对标签信息。"],
    warnings: ["A4彩色打印和信封尺寸只适用于当前资料的这项标签。"],
    conditions: []
  },
  application_form: {
    purpose: "网上出愿后打印并提交的正式申请表。",
    steps: ["先完成报名费等付款和证件照片上传，再打印申请表。", "从网上出愿个人页面用A4纸彩色打印。", "核对内容，并与所需出愿材料一并准备。"],
    warnings: ["若暂时无法打印，先检查付款和照片上传是否完成；本页不核验这两项进度。"],
    conditions: []
  },
  statement_of_purpose: {
    purpose: "说明申请理由等内容的指定文书。",
    steps: ["使用募集要项提供的指定格式。", "打印在一张A4纸上，可以双面打印。", "查看目标学系是否指定题目；没有指定题目不等于免交。"],
    warnings: ["本项是否需要提交，仍按当前学历资格路径的审核结果确认。"],
    conditions: []
  },
  bachelor_transcript: {
    purpose: "证明学士课程各科成绩的大学文件。",
    steps: ["准备大学出具的学士课程成绩证明，不用研究生阶段成绩替代。", "按本资料共同要求准备原件；普通复印件或自行下载打印件不能直接替代。", "无论已毕业或预计毕业，都先核对这项材料在当前路径是否适用。"],
    warnings: ["成绩证明与毕业证明可合在同一份大学证明中；仍需核对两项内容。"],
    conditions: [
      {title: "如果有转学经历", text: "一并准备转学前大学等的成绩证明。"},
      {title: "如果成绩分成教养／专业或本科／专攻科等部分", text: "两部分都要准备。"},
      {title: "如果因保存期限、学校关闭或受灾等无法开具", text: "应在出愿期间开始前向入试课咨询；本页不认定替代文件已获批准。"},
      {title: "如果无法提交原件", text: "查看共同要求，由毕业大学或使领馆、公证机关等公共机构完成原本证明；普通复印件不能直接替代。"},
      {title: "如果证明不是日文或英文", text: "附毕业大学出具的日文或英文翻译；大学无法出具时，按原文办理公共机构的译文内容认证。仅本人翻译或只认证声明、签名不足以代替内容认证。"}
    ]
  },
  graduation_or_expected_graduation_certificate: {
    purpose: "证明学士课程已经毕业或预计毕业的大学文件。",
    steps: ["按自己的毕业状态准备毕业证明或预计毕业证明。", "外国大学申请人还需学位取得或预计取得证明；两类内容可以由同一证明记载。", "使用大学出具的文件，核对原件、语言和翻译要求。"],
    warnings: ["成绩证明与毕业证明可合在一份大学证明中；本页不判断手中的替代证明是否有效。"],
    conditions: [
      {title: "如果申请2026年9月入学", text: "证明须体现可在2026年9月27日前毕业；该日期不适用于2027年4月入学。", intakeYear: 2026, intakeMonth: 9},
      {title: "如果毕业证明无法提供", text: "原文允许大学出具载明毕业或预计毕业年月、姓名、出生日期的证明；年月可用入学与毕业年月表示。"},
      {title: "如果外国大学的毕业或学位证明均无法提供", text: "另有须写明取得或预计取得学位等内容的大学证明要求；不要把两种替代情形合并。"},
      {title: "如果无法提交原件", text: "按原文由毕业大学或使领馆、公证机关等公共机构完成原本证明；普通复印件不能直接替代。"},
      {title: "如果证明不是日文或英文", text: "附毕业大学出具的日文或英文翻译；大学无法出具时，按原文办理公共机构的译文内容认证。仅本人翻译或只认证声明、签名不足以代替内容认证。"}
    ]
  }
};
const isctMaterialRowMarkers = {
  address_label: ["①宛名ラベル"],
  application_form: ["②入学志願票"],
  statement_of_purpose: ["③志望理由書"],
  bachelor_transcript: ["④学士課程の成績証", "明書"],
  graduation_or_expected_graduation_certificate: ["⑤学士課程の卒業証", "卒業見込み証明書"]
};

function materialScopeIdentity(scope) {
  if (!scope || scope.kind !== scope.item?.kind) return null;
  if (scope.kind === "legacy_applicant") {
    if (scope.request?.school_id !== scope.item.legacy_catalog?.school_id) return null;
    return {
    kind: scope.kind, school_id: scope.request?.school_id,
    document_id: scope.request?.document_id
    };
  }
  if (scope.kind === "reviewed_material_slice") return {
    kind: scope.kind, institution_id: scope.item.target?.institution_id,
    organization_id: scope.item.target?.organization_id,
    program_id: scope.item.target?.program_id,
    snapshot_id: scope.item.snapshot_id, target_id: scope.item.target?.target_id,
    degree_level: scope.item.target?.degree_level, admission_cycle: scope.item.target?.admission_cycle,
    selection_route_id: scope.item.target?.selection_route_id,
    examination_schedule_id: scope.item.target?.examination_schedule_id,
    intake_year: scope.item.target?.intake?.year, intake_month: scope.item.target?.intake?.month
  };
  return null;
}

export function materialDisplay(scope, rawCode, originalName) {
  const code = String(rawCode || "").replace(/^material:/, "");
  const identity = materialScopeIdentity(scope);
  const catalog = identity && materialDisplays.find((entry) =>
    Object.entries(entry.identity).every(([key, value]) => identity[key] === value));
  const row = catalog?.materials[code];
  if (!row) return {name: originalName, official: "", description: "说明待核实。", verified: false};
  return {name: row[0], official: row[1], description: row[2], verified: true};
}

export function materialGuide(scope, topic) {
  const identity = materialScopeIdentity(scope);
  if (authorEssayScopeMatches(scope) && ["application-essay", "application_essay"].includes(topic?.id))
    return authorEssaySourcesMatch(topic.sources) ? authorEssayGuide : null;
  if (identity?.kind !== "legacy_applicant" || identity.school_id !== "isct"
    || identity.document_id !== "isct_2027_4_2026_9_master") return null;
  const code = String(topic?.id || "").replace(/^material:/, "");
  const guide = isctMaterialGuides[code];
  const markers = isctMaterialRowMarkers[code];
  if (!guide || !markers || !array(topic.sources || topic.evidence).some((source) =>
    source.fact_id === "fact:00104" && source.document_id === identity.document_id
      && array(source.pages).includes(10)
      && markers.every((marker) => text(source.quote || source.official_text).includes(marker)))) return null;
  return {...guide, conditions: guide.conditions.filter((condition) =>
    condition.intakeYear === undefined || (scope.request?.intake?.year === condition.intakeYear
      && scope.request?.intake?.month === condition.intakeMonth))};
}

function readerMaterialLine(item) {
  const guide = item.guide;
  const joinSentences = (rows) => `${rows.map((row) => row.replace(/[。；]$/, "")).join("；")}。`;
  return `${item.title}${item.official ? `（${item.official}）` : ""}｜${guide?.purpose || item.description}｜${item.state}。${item.action}`
    + (guide ? ` 准备方法：${joinSentences(guide.steps)} 注意：${joinSentences(guide.warnings)}`
      + (guide.conditions.length ? ` 特殊情况：${joinSentences(guide.conditions.map((row) => `${row.title}：${row.text}`))}` : "") : "");
}

export function readerReportOptions(report) {
  requireValue(report?.scope && Array.isArray(report.topics), "报告尚未校验");
  const options = {
    dates: report.kind === "legacy_applicant" && report.topics.some((topic) => topic.category === "dates"),
    materials: report.topics.some((topic) => report.kind === "reviewed_material_slice" || topic.category === "materials"),
    other: report.kind === "legacy_applicant" && report.topics.some((topic) => !["dates", "materials"].includes(topic.category))
  };
  if (report.kind === "legacy_applicant" && report.exam?.status === "available") options.exams = true;
  return options;
}

function legacyMaterialState(topic, comparisonItem) {
  const applicability = comparisonItem?.official_status || topic.status_code;
  const preparation = comparisonItem?.preparation_status || "unknown";
  if (applicability === "not_applicable" || comparisonItem?.comparison_status === "not_applicable")
    return {state: "本项无需提交", action: "按当前已审核的适用条件，本项无需提交。"};
  if (applicability === "not_covered")
    return {state: "当前资料未覆盖", action: "当前资料不能判断这一项，请查看完整募集要项。"};
  if (applicability !== "required")
    return {state: "待确认适用", action: preparation === "not_yet"
      ? "自报尚未准备；先确认适用条件，再决定是否需要补材料。"
      : preparation === "available"
        ? "已自报准备；先确认这一项是否需要提交。"
        : "尚未填写准备情况；先确认这一项是否需要提交。"};
  if (preparation === "not_yet")
    return {state: "待准备", action: "你填写为尚未准备；请核对该材料的具体要求。"};
  if (preparation === "available")
    return {state: "已准备（自报）", action: "请核对材料是否符合要求。"};
  return {state: "尚未填写准备情况", action: "请填写准备情况；目前不计为缺材料。"};
}

function sliceMaterialState(topic, employment, preparation = "unknown") {
  if (topic.status_code === "submission_not_required")
    return {state: "本项无需提交", action: topic.explanation};
  if (topic.status_code === "rule_not_applicable")
    return {state: "本条条件不适用", action: topic.explanation};
  if (topic.status_code === "submission_required" && preparation === "available")
    return {state: "已准备（自报）", action: "官方仍需提交；请核对材料内容、格式与提交情况，自报不代表学校受理。"};
  if (topic.status_code === "submission_required" && preparation === "not_yet")
    return {state: "待准备", action: "你填写为尚未准备；请按本项要求准备并提交，自报不改变官方提交要求。"};
  if (topic.status_code === "submission_required")
    return {state: "需提交，尚未填写准备情况", action: topic.explanation};
  if (topic.status_code === "not_covered")
    return {state: "当前资料未覆盖", action: "本切片未确认这一项。"};
  const missing = [];
  if (employment.current === "unknown") missing.push("目前是否在职");
  if (employment.retain === "unknown") missing.push("入学后是否继续在职");
  return {state: "待确认适用", action: `${topic.explanation}${missing.length ? `请补充${missing.join("、")}。` : "请向学校确认适用条件。"}`};
}

function readerText(view) {
  const lines = ["出愿准备参考", `目标：${view.target}`, `本次关注：${view.selected.map((key) => readerTopicNames[key]).join("、")}`];
  const section = (title, rows) => {
    lines.push("", title);
    for (const row of rows) lines.push(`- ${row}`);
  };
  if (view.priorityRows.length) section("接下来先做什么", view.priorityRows);
  if (view.selected.includes("dates")) {
    section("关键时间", view.dates.length
      ? view.dates.map((item) => `${item.label}：${item.value}${item.note ? `；${item.note}` : ""}`)
      : ["当前已覆盖资料尚未整理日期，请核对完整募集要项。"]);
    if (view.dateNote) lines.push(view.dateNote);
  }
  if (view.selected.includes("materials"))
    section("材料准备清单", view.materials.length
      ? view.materials.map((item) => item.line)
      : ["当前所选资料没有可整理的材料主题。"]);
  if (view.selected.includes("materials") && view.english.length)
    section("英语成绩与证明", view.english);
  if (view.selected.includes("materials") && view.submission.length)
    section("毕业与提交提醒", view.submission);
  if (view.selected.includes("other"))
    section("其他已加载要求", view.other.length
      ? view.other.map((item) => `${item.title}：${item.summary}（${item.status}）`)
      : ["当前已加载资料没有其他主题。"]);
  if (view.selected.includes("exams")) section("考试安排", view.exams);
  lines.push("", `范围说明：${view.limitation}`);
  return lines.join("\n");
}

export function readerReport(report, selected) {
  const available = readerReportOptions(report);
  requireValue(selected && ["dates", "materials", "other"].every((key) => typeof selected[key] === "boolean")
    && (selected.exams === undefined || typeof selected.exams === "boolean"), "报告主题选择无效");
  requireValue(Object.keys(available).every((key) => !selected[key] || available[key]), "选中主题未加载");
  const chosen = Object.keys(available).filter((key) => selected[key]);
  requireValue(chosen.length > 0, "请至少选择一类报告内容");
  const target = scopeLabel(report.scope);
  const dates = [];
  const materials = [];
  const other = [];
  const exams = selected.exams ? examReportRows(report.exam) : [];
  const english = [];
  const submission = [];
  const priorities = [];
  let dateNote = "";
  if (selected.dates) {
    const seen = new Set();
    const names = {registration_open: "登记开放", application_window: "出愿期间", arrival_deadline: "材料送达必着", recommended_arrival: "建议提前到达"};
    for (const topic of report.topics) for (const date of array(topic.dates)) {
      const kind = date.event_type || "other";
      const key = `${kind}:${date.display}`;
      if (seen.has(key)) continue;
      seen.add(key);
      dates.push({label: names[kind] || date.label, value: date.display,
        note: kind === "recommended_arrival" ? "建议时间不等于强制截止" : ""});
      if (date.unknown.some((field) => field === "start_time" || field === "end_time") && !dateNote)
        dateNote = "官方未明确的具体时刻不作推测；请按已审核日期和官方原文核对。";
    }
  }
  if (selected.materials) {
    const guide = report.kind === "legacy_applicant"
      ? report.topics.find((topic) => topic.id === "language:preparation-guide") : null;
    if (guide) english.push(...guide.summary.split("\n").filter(Boolean));
    if (report.kind === "legacy_applicant") {
      const submission = report.topics.find((topic) =>
        /^rule:isct-master-english-submission-computer-science-(apr|sep)$/.test(topic.id));
      if (submission) english.push(submission.summary);
    }
    const detailed = report.comparison?.english_preparation_result;
    if (detailed) {
      for (const check of detailed.checks) {
        const status = {reported_match: "按填写已具备", action_needed: "待处理",
          needs_information: "待确认", not_applicable: "不适用", not_covered: "未覆盖"}[check.status];
        english.push(`${check.title}：${status}。${check.explanation} 下一步：${check.next_action}`);
        if (check.status === "action_needed") priorities.push(`英语 · ${check.title}：${check.next_action}`);
      }
    }
    const application = report.comparison?.application_preparation_result;
    if (application) {
      for (const check of application.checks) {
        const status = {reported_match: "按填写已记录", action_needed: "需处理",
          needs_information: "待确认", not_applicable: "不适用", not_covered: "未覆盖"}[check.status];
        const line = `${check.title}：${status}。${check.explanation} 下一步：${check.next_action}`;
        submission.push(line);
        if (check.status === "action_needed" || check.status === "needs_information")
          priorities.push(`毕业与提交 · ${check.title}：${check.next_action}`);
      }
    }
    const unfilled = [];
    const conditional = [];
    const comparison = new Map(array(report.comparison?.items)
      .filter((item) => item.category === "materials").map((item) => [item.item_id || item.title, item]));
    for (const topic of report.topics) {
      if (report.kind === "legacy_applicant" && topic.category !== "materials") continue;
      const state = report.kind === "legacy_applicant"
        ? legacyMaterialState(topic, comparison.get(topic.id) || comparison.get(topic.title))
        : sliceMaterialState(topic, report.employment, report.preparation?.[topic.id]);
      const display = materialDisplay(report.scope, topic.id || topic.material_code, topic.title);
      const item = {title: display.name, official: display.official,
        description: display.description, verified: display.verified, guide: topic.guide, ...state};
      item.line = readerMaterialLine(item);
      materials.push(item);
      if (["待准备", "需提交，尚未填写准备情况"].includes(state.state))
        priorities.push(`${display.name}：${state.state}。${state.action}`);
      else if (state.state === "尚未填写准备情况") unfilled.push(display.name);
      else if (state.state === "待确认适用") conditional.push(item);
    }
    if (report.kind === "legacy_applicant" && !report.comparison)
      priorities.unshift("尚未填写准备情况，暂不能判断还缺哪些材料；可先保存基础要求。");
    else if (unfilled.length)
      priorities.push(`${unfilled.join("、")}：尚未填写准备情况；不能算作缺失材料。`);
    if (conditional.length) priorities.push(conditional.length === 1
      ? `${conditional[0].title}：待确认适用。${conditional[0].action}`
      : `${conditional.map((item) => item.title).join("、")}：待确认适用；请先确认这些材料的适用条件。`);
  }
  if (selected.other) {
    for (const topic of report.topics.filter((item) => !["dates", "materials"].includes(item.category)
      && item.id !== "language:preparation-guide")) {
      other.push({title: topic.title, summary: topic.summary, status: topic.status});
      if (["needs_information", "needs_review", "not_covered"].includes(topic.status_code))
        priorities.push(`${topic.title}：${topic.status}。请核对该项条件。`);
    }
  }
  const limitation = report.kind === "reviewed_material_slice"
    ? `仅整理当前已审核的 ${report.topics.length} 个材料主题，不是完整清单或资格判断；历史资料请核对官方最新信息。`
    : selected.materials
      ? "仅整理当前已审核资料与本次自报；已准备不代表有效、已提交或学校受理，未覆盖内容请核对完整募集要项。"
      : "仅整理当前已审核资料；未覆盖内容请核对完整募集要项。";
  const priorityRows = priorities.length ? priorities : selected.materials
    ? ["当前所选范围没有明确的待补材料；这不表示全部申请材料齐全。"] : [];
  const view = {target, selected: chosen, priorities, priorityRows, dates, dateNote, materials, english, submission, other,
    ...(selected.exams ? {exams} : {}), limitation};
  return {...view, text: readerText(view)};
}

export {statusNames};
