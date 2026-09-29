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
  return {schema_version: "1.0", target: scope.request, applicant: legacyApplicant(controls)};
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
      dates, sources
    };
  });
  return {
    scope, topics, coverage: base.coverage_statement,
    limitation: base.limitation_statement, target: base.target,
    raw: base
  };
}

export function mapSliceEvidence(scope, evidence) {
  requireValue(scope.kind === "reviewed_material_slice"
    && evidence?.schema_version === "1.0"
    && evidence.snapshot_id === scope.item.snapshot_id
    && same(evidence.target, scope.item.target)
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
        context: [record.scope_note_zh, array(record.official_heading_path).join(" › "),
          record.role === "basis" ? "本条依据" : "关联上下文",
          record.stage === "enrollment_context_only" ? "入学手续关联，非申请阶段义务" : ""].filter(Boolean).join(" · "),
        record_id: record.record_id
      };
    });
    requireValue(sources.length > 0, "材料主题依据缺失");
    return {
      id: topic.topic_id, category: "materials", title: topic.material_name_zh,
      summary: topic.context_note_zh, description: topic.context_note_zh,
      status: "当前条件待报告判断", status_code: "needs_information",
      deadline: "", limitation: "", dates: [], sources
    };
  });
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

export function legacyReport(mapped, comparison = null, profileDisclosure = []) {
  requireValue(mapped?.scope?.kind === "legacy_applicant" && mapped.topics?.length, "当前要求尚未加载");
  if (comparison) {
    requireValue(Array.isArray(profileDisclosure), "个人情况展示无效");
    requireValue(comparison.schema_version === "1.0"
      && legacyTargetMatches(mapped.scope, comparison.target)
      && Array.isArray(comparison.items)
      && comparison.counts?.total === comparison.items.length, "个人对照目标不匹配");
    for (const item of comparison.items)
      if (!["not_covered", "needs_review", "needs_information"].includes(item.comparison_status))
        requireValue(array(item.evidence).length > 0, "个人对照引用缺失");
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
    comparison, profileDisclosure, text: lines.join("\n"), raw: {base: mapped.raw, comparison},
    presentation: {intro: intro.slice(3), topics, comparison: comparisonPresentation, conclusion}};
}

export function sliceReport(scope, mapped, payload, employment = {current: "unknown", retain: "unknown"}) {
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
    return {
      title: result.material_name_zh,
      status: statusNames[result.disposition] || result.disposition,
      status_code: result.disposition, condition: result.condition_status,
      explanation: result.explanation_zh, missing_fields: array(result.missing_fields),
      limitations: array(result.limitations_zh),
      citations: sourceRecords
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
  return {kind: "reviewed_material_slice", scope, topics, employment, text: wrapper,
    canonicalMarkdown: payload.markdown, raw: payload.report};
}

const readerTopicNames = {dates: "关键时间", materials: "材料与待办", other: "其他已加载要求"};

export function readerReportOptions(report) {
  requireValue(report?.scope && Array.isArray(report.topics), "报告尚未校验");
  return {
    dates: report.kind === "legacy_applicant" && report.topics.some((topic) => topic.category === "dates"),
    materials: report.topics.some((topic) => report.kind === "reviewed_material_slice" || topic.category === "materials"),
    other: report.kind === "legacy_applicant" && report.topics.some((topic) => !["dates", "materials"].includes(topic.category))
  };
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
      : "先补充个人条件，确认这一项是否需要提交。"};
  if (preparation === "not_yet")
    return {state: "待补材料", action: "自报尚未准备；请准备材料并核对提交格式。"};
  if (preparation === "available")
    return {state: "已自报准备", action: "请核对内容、有效性和提交方式；不表示学校已审核或受理。"};
  return {state: "待填写准备情况", action: "尚未填写准备情况，暂不能算作缺失材料。"};
}

function sliceMaterialState(topic, employment) {
  if (topic.status_code === "submission_not_required")
    return {state: "本项无需提交", action: topic.explanation};
  if (topic.status_code === "rule_not_applicable")
    return {state: "本条条件不适用", action: topic.explanation};
  if (topic.status_code === "submission_required")
    return {state: "需要准备，完成情况未填写", action: topic.explanation};
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
  section("接下来先做什么", view.priorities.length ? view.priorities : ["当前所选范围没有明确的待补材料；这不表示全部申请材料齐全。"]);
  if (view.selected.includes("dates")) {
    section("关键时间", view.dates.length
      ? view.dates.map((item) => `${item.label}：${item.value}${item.note ? `；${item.note}` : ""}`)
      : ["当前已覆盖资料尚未整理日期，请核对完整募集要项。"]);
    if (view.dateNote) lines.push(view.dateNote);
  }
  if (view.selected.includes("materials"))
    section("材料准备清单", view.materials.length
      ? view.materials.map((item) => `${item.title}｜${item.state}。${item.action}`)
      : ["当前所选资料没有可整理的材料主题。"]);
  if (view.selected.includes("other"))
    section("其他已加载要求", view.other.length
      ? view.other.map((item) => `${item.title}：${item.summary}（${item.status}）`)
      : ["当前已加载资料没有其他主题。"]);
  lines.push("", `范围说明：${view.limitation}`);
  return lines.join("\n");
}

export function readerReport(report, selected) {
  const available = readerReportOptions(report);
  requireValue(selected && ["dates", "materials", "other"].every((key) => typeof selected[key] === "boolean"), "报告主题选择无效");
  requireValue(Object.keys(available).every((key) => !selected[key] || available[key]), "选中主题未加载");
  const chosen = Object.keys(available).filter((key) => selected[key]);
  requireValue(chosen.length > 0, "请至少选择一类报告内容");
  const target = scopeLabel(report.scope);
  const dates = [];
  const materials = [];
  const other = [];
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
      if (date.unknown.includes("end_time") && !dateNote)
        dateNote = "官方未明确的具体时刻不作推测；请按已审核日期和官方原文核对。";
    }
  }
  if (selected.materials) {
    const comparison = new Map(array(report.comparison?.items)
      .filter((item) => item.category === "materials").map((item) => [item.item_id || item.title, item]));
    for (const topic of report.topics) {
      if (report.kind === "legacy_applicant" && topic.category !== "materials") continue;
      const state = report.kind === "legacy_applicant"
        ? legacyMaterialState(topic, comparison.get(topic.id) || comparison.get(topic.title))
        : sliceMaterialState(topic, report.employment);
      const item = {title: topic.title, ...state};
      materials.push(item);
      if (["待补材料", "待填写准备情况", "待确认适用", "需要准备，完成情况未填写"].includes(state.state))
        priorities.push(`${topic.title}：${state.state}。${state.action}`);
    }
    if (report.kind === "legacy_applicant" && !report.comparison)
      priorities.unshift("未填写准备情况，暂不能判断还缺哪些材料；可先保存基础要求。");
  }
  if (selected.other) {
    for (const topic of report.topics.filter((item) => !["dates", "materials"].includes(item.category))) {
      other.push({title: topic.title, summary: topic.summary, status: topic.status});
      if (["needs_information", "needs_review", "not_covered"].includes(topic.status_code))
        priorities.push(`${topic.title}：${topic.status}。请核对该项条件。`);
    }
  }
  const limitation = report.kind === "reviewed_material_slice"
    ? `仅整理当前已审核的 ${report.topics.length} 个材料主题，不是完整清单或资格判断；历史资料请核对官方最新信息。`
    : "仅整理当前已审核资料与本次自报；已准备不代表有效、已提交或学校受理，未覆盖内容请核对完整募集要项。";
  const view = {target, selected: chosen, priorities, dates, dateNote, materials, other, limitation};
  return {...view, text: readerText(view)};
}

export {statusNames};
