/* Pure presentation adapter. The server remains the authority for every finding. */
import {reviewedMaterialPresentation} from "./material-presentation-catalog.mjs";
const statusNames = {
  required: "提出が必要／該当する条件の場合に適用",
  conditional: "条件付きで対象",
  needs_information: "情報不足・要確認",
  needs_review: "大学または担当者による確認が必要",
  not_applicable: "この条件の対象外",
  not_covered: "確認済み資料の対象外",
  recorded: "記録済み",
  possible_match: "該当する可能性あり・要確認",
  submission_required: "提出が必要",
  submission_not_required: "提出不要（この書類自体のみ）",
  rule_not_applicable: "この条件には該当しません。一般的な提出免除ではありません",
  unknown: "不明・確認待ち",
  available: "準備済み",
  not_yet: "未取得"
};
const categoryNames = {dates: "日程", eligibility: "出願資格", language: "語学", materials: "書類"};
function publicReviewedText(value) { return text(value).replace(/\bRULE-\d+[A-Z]?\b\s*/g, "").trim(); }
function publicStatus(value) { return statusNames[value] || "詳細の確認が必要"; }

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}
function same(a, b) {
  const canonical = (value) => Array.isArray(value) ? value.map(canonical)
    : value && typeof value === "object"
      ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])])) : value;
  return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
}
function nonempty(value) { return typeof value === "string" && value.trim().length > 0; }
function array(value) { return Array.isArray(value) ? value : []; }
function text(value) { return value == null ? "" : String(value); }

export function readyEntries(catalog) {
  requireValue(catalog?.schema_version === "1.0" && Array.isArray(catalog.items), "対象一覧の形式が正しくありません");
  const entries = catalog.items.filter((item) => item.availability === "ready");
  const ids = new Set();
  for (const item of entries) {
    requireValue(nonempty(item.entry_id) && !ids.has(item.entry_id), "対象一覧の識別情報が重複しています");
    requireValue(["legacy_applicant", "reviewed_material_slice"].includes(item.kind), "対象の種類が正しくありません");
    requireValue(item.capabilities?.evidence_browse && item.capabilities?.reference_report, "利用できる機能と画面が一致しません");
    if (item.kind === "legacy_applicant") requireValue(item.legacy_catalog?.school_name, "対象一覧がありません");
    else requireValue(item.target && item.request_profile_target && nonempty(item.snapshot_id), "書類サンプルの識別情報がありません");
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
      edition: `${target.admission_cycle} 年度 · 過去の資料`,
      intake: `${target.intake.year} 年 ${target.intake.month} 月`,
      route: `${target.selection_route_id === "general-ordinary" ? "一般選抜" : target.selection_route_id} · ${target.examination_schedule_id} 日程`,
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
              || "確認済み募集要項（版の名称は未登録）",
            intake: intake.intake_name, route: route?.route_name || "一般選抜",
            request: {
              schema_version: "1.0", school_id: school.school_id,
              document_id: intake.document_id, degree_id: degree.degree_id,
              intake: {year: intake.year, month: intake.month},
              college_id: college.college_id, department_id: department.department_id,
              application_route: route?.route_id || null
            }
          });
        }
  requireValue(result.length > 0, "対象一覧が空です");
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
  requireValue(!score || concrete("english_test_kind"), "英語スコアを入力する場合は試験の種類を選んでください");
  requireValue(!value("english_test_date") || concrete("english_test_kind"), "受験日を入力する場合は試験の種類を選んでください");
  requireValue(!score || (Number.isFinite(Number(score)) && Number(score) >= 0 && Number(score) <= 10000), "英語スコアの値が正しくありません");
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
  requireValue(scope.kind === "legacy_applicant" && scope.request, "対象の種類が一致しません");
  return {schema_version: "1.0", target: scope.request, applicant: legacyApplicant(controls),
    ...(controls.english_preparation ? {english_preparation: controls.english_preparation} : {}),
    ...(controls.application_preparation ? {application_preparation: controls.application_preparation} : {})};
}

export function validateEnglishPreparationResult(scope, payload) {
  const result = payload?.english_preparation_result;
  requireValue(scope?.kind === "legacy_applicant" && result
    && result.document_id === scope.request.document_id
    && legacyTargetMatches(scope, result.target) && Array.isArray(result.checks),
  "英語の照合結果と志望先が一致しません");
  const ids = new Set();
  for (const check of result.checks) {
    requireValue(nonempty(check.check_id) && !ids.has(check.check_id)
      && ["reported_match", "action_needed", "needs_information", "not_applicable", "not_covered"].includes(check.status)
      && nonempty(check.title) && nonempty(check.explanation) && nonempty(check.next_action)
      && Array.isArray(check.rule_ids) && Array.isArray(check.evidence), "英語の確認項目が正しくありません");
    ids.add(check.check_id);
    if (["reported_match", "action_needed"].includes(check.status))
      requireValue(check.rule_ids.length > 0 && check.evidence.length > 0, "英語の照合に必要な根拠がありません");
    for (const source of check.evidence) validateLegacyEvidence(source, scope);
  }
  return result;
}

export function validateApplicationPreparationResult(scope, payload) {
  const result = payload?.application_preparation_result;
  requireValue(scope?.kind === "legacy_applicant" && result
    && result.document_id === scope.request.document_id
    && legacyTargetMatches(scope, result.target) && Array.isArray(result.checks),
  "卒業・提出の照合結果と志望先が一致しません");
  const ids = new Set();
  for (const check of result.checks) {
    requireValue(nonempty(check.check_id) && !ids.has(check.check_id)
      && ["reported_match", "action_needed", "needs_information", "not_applicable", "not_covered"].includes(check.status)
      && nonempty(check.title) && nonempty(check.explanation) && nonempty(check.next_action)
      && Array.isArray(check.rule_ids) && Array.isArray(check.evidence), "卒業・提出の確認項目が正しくありません");
    ids.add(check.check_id);
    if (check.status === "reported_match")
      requireValue(check.rule_ids.length > 0 && check.evidence.length > 0, "卒業・提出の照合に必要な根拠がありません");
    for (const source of check.evidence) validateLegacyEvidence(source, scope);
  }
  return result;
}

export function sliceReportRequest(scope, employment) {
  requireValue(scope.kind === "reviewed_material_slice", "対象の種類が一致しません");
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
    && array(evidence.pages).every((page) => Number.isSafeInteger(page) && page > 0), "公式資料の根拠が不足しています");
  for (const mark of array(evidence.highlights))
    requireValue(evidence.official_text.slice(mark.start, mark.end) === mark.exact_text, "引用と公式原文が一致しません");
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
    && (target?.application_route_name || null) === (scope.route === "一般選抜" ? null : scope.route);
}

export function mapLegacyBase(scope, base) {
  requireValue(scope.kind === "legacy_applicant" && base?.schema_version === "1.0"
    && legacyTargetMatches(scope, base.target) && Array.isArray(base.requirements), "基本要件の志望先が一致しません");
  const topics = base.requirements.map((requirement) => {
    const sources = array(requirement.evidence).map((source) => validateLegacyEvidence(source, scope));
    const dates = array(requirement.date_events).map((event) => {
      const eventSources = array(event.evidence).map((source) => validateLegacyEvidence(source, scope));
      requireValue(eventSources.length > 0, "日程の根拠がありません");
      return {
        label: event.label, display: event.display_text,
        event_type: event.event_type || null,
        precision: event.precision, unknown: array(event.unknown_fields),
        uncertainty: event.uncertainty_note || "", sources: eventSources
      };
    });
    if (!["not_covered", "needs_review", "needs_information"].includes(requirement.official_status))
      requireValue(sources.length > 0 || dates.length > 0, "確認済み要件の引用がありません");
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
      && ["available_official_paths", "not_covered", "not_covered_course", "unavailable"].includes(info.status), "試験情報の状態が正しくありません");
    const request = scope.request;
    requireValue(Object.keys(request).every((key) => same(request[key], info.target_identity?.[key])), "試験情報の対象が一致しません");
    if (info.status !== "available_official_paths") {
      requireValue(same(info.pathways, []) && same(info.evidence, []) && same(info.field_bindings, []), "未確認の試験情報に確定した記述があります");
      if (info.status === "not_covered_course") requireValue(info.applicability?.course_state === "excluded"
        || info.applicability?.course_state === "unknown", "コースの除外状態が正しくありません");
      return {status: info.status, message: info.message_zh};
    }
    requireValue(request.school_id === "isct" && request.document_id === examSource.document_id
      && request.degree_id === "master" && [[2026, 9], [2027, 4]].some(([year, month]) =>
        request.intake.year === year && request.intake.month === month)
      && info.presentation_id === "isct-18-departments-exams-2026-v2"
      && info.presentation_sha256 === examPresentationV2Sha
      && same(info.source_identity, examSource), "試験情報の出典が一致しません");
    const applicability = info.applicability;
    requireValue(applicability?.catalog_route === request.application_route
      && applicability.personal_route_state === (request.application_route === "b_schedule" ? "catalog_b" : "unconfirmed")
      && ["unspecified", "covered"].includes(applicability.course_state)
      && Array.isArray(applicability.covered_course_ids) && Array.isArray(applicability.excluded_course_ids)
      && (applicability.covered_course_ids.length === 0
        ? applicability.excluded_course_ids.length === 0
        : same(applicability.excluded_course_ids, ["地球生命コース"])), "試験日程またはコースの対象範囲が一致しません");
    requireValue(info.year_basis?.exam_year === 2026
      && info.year_basis.kind === "reviewed_cross_page_context"
      && same(info.year_basis.physical_pages, [1, 2])
      && Number.isSafeInteger(info.year_basis.department_page), "試験年度の出典が不足しています");
    const evidence = array(info.evidence);
    const evidenceById = new Map();
    for (const row of evidence) {
      validateLegacyEvidence(row, scope);
      requireValue(nonempty(row.fact_id) && row.scope_type === "department"
        && row.parent_college === request.college_id
        && array(row.scope_targets).includes(request.department_id), "試験の根拠資料の対象範囲が一致しません");
      requireValue(!evidenceById.has(row.fact_id), "試験の根拠が重複しています");
      evidenceById.set(row.fact_id, row);
    }
    const bindings = new Map();
    for (const field of array(info.field_bindings)) {
      requireValue(nonempty(field.field_path) && !bindings.has(field.field_path), "試験項目が重複しています");
      if (field.value_zh === null)
        requireValue(nonempty(field.missing_reason_zh) && same(field.sources, []), "未確認項目に根拠があると記録されています");
      else {
        requireValue(nonempty(field.value_zh) && array(field.sources).length > 0, "試験項目の出典がありません");
        for (const source of field.sources) {
          requireValue(nonempty(source.exact_text) && array(source.physical_pages).length > 0, "試験の原文箇所がありません");
          if (source.source_id === "fact:00002") requireValue(field.field_path === "exam.year", "年度の出典が対象範囲外です");
          else if (source.source_id.startsWith("fact:")) {
            const row = evidenceById.get(source.source_id);
            requireValue(row && same(row.pages, source.physical_pages)
              && row.official_text.includes(source.exact_text), "試験の原文と項目が一致しません");
          } else requireValue(source.source_id === `pdf_page:${source.physical_pages[0]}`
            && source.physical_pages.length === 1, "PDFの参照ページが一致しません");
        }
      }
      bindings.set(field.field_path, field);
    }
    const required = ["exam.year", "a.oral", "b.written_status", "b.written_sessions", "b.subjects",
      "b.selection_rule", "b.points", "english.submission", "b.oral", "b.answer_language"];
    requireValue(required.every((key) => bindings.has(key))
      && (applicability.covered_course_ids.length === 0 || bindings.has("course.coverage_exclusion")), "試験項目が不足しています");
    const value = (key) => bindings.get(key)?.value_zh?.replaceAll("**", "") ?? null;
    const paths = array(info.pathways);
    requireValue(paths.length === 2 && paths[0].source_route === "a_schedule"
      && paths[1].source_route === "b_schedule"
      && paths.every((path) => path.personal_eligibility === (request.application_route === "b_schedule"
        && path.source_route === "b_schedule" ? "catalog_b" : "unconfirmed")), "公式の日程と本人への適用が一致しません");
    const a = paths[0];
    const b = paths[1];
    requireValue(a.oral?.description_zh === value("a.oral")
      && a.oral.status === (value("a.oral").includes("実施しないと明記") ? "not_held" : "held")
      && a.written.status === "unknown" && b.oral?.description_zh === value("b.oral")
      && b.written?.status === value("b.written_status")
      && b.written.points_zh === value("b.points")
      && b.english?.submission_zh === value("english.submission"), "試験日程の内容と出典の対応が一致しません");
    if (b.written.status === "held") requireValue(
      b.written.time_zh === value("b.written_sessions")
      && array(b.written.subjects_zh).length > 0
      && b.written.subjects_zh.join("；") === value("b.subjects")
      && b.written.selection_rule_zh === value("b.selection_rule")
      && b.written.answer_language_zh === value("b.answer_language")
      && b.written.administration_language_zh === value("exam.administration_language"), "筆答試験の科目・時間帯が出典と一致しません");
    else requireValue(b.written.status === "not_held" && b.written.time_zh === null
      && same(b.written.subjects_zh, []), "筆答試験なしの状態に試験内容があります");
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
      && ["available", "not_covered", "unavailable"].includes(info.status), "試験情報の状態が正しくありません");
    const request = scope.request;
    requireValue(Object.keys(request).every((key) => same(request[key], info.target_identity?.[key])), "試験情報の対象が一致しません");
    if (info.status !== "available") {
      requireValue(info.schedule === null && same(info.evidence, []), "未確認の試験情報に確定した記述があります");
      return {status: info.status, message: info.message_zh};
    }
    requireValue(request.school_id === "isct" && request.document_id === examSource.document_id
      && request.college_id === "情報理工学院" && request.department_id === "情報工学系"
      && request.degree_id === "master" && request.application_route === "b_schedule"
      && [[2026, 9], [2027, 4]].some(([year, month]) => request.intake.year === year && request.intake.month === month)
      && info.presentation_id === "isct-cs-b-exams-2026-v1"
      && info.presentation_sha256 === examPresentationSha
      && same(info.source_identity, examSource), "試験情報の出典が一致しません");
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
        {group: "A", subjects_zh: ["微分積分学", "線形代数学", "確率統計"]},
        {group: "B", subjects_zh: ["数理論理学", "オートマトンと形式言語"]},
        {group: "C", subjects_zh: ["データ構造とアルゴリズム", "プログラミング"]}
      ]) && nonempty(s.oral_selection_note_zh), "試験日程が不足しています");
    requireValue(info.year_basis?.kind === "reviewed_cross_page_context"
      && info.year_basis.exam_year === 2026 && same(info.year_basis.physical_pages, [1, 2, 52])
      && same(info.year_basis.source_ids, ["pdf:cover:1", "fact:00002", "fact:00004", "fact:00288"]), "試験年度の根拠が不足しています");
    const evidence = array(info.evidence);
    requireValue(evidence.length === 3 && same(evidence.map((row) => row.fact_id),
      ["fact:00288", "fact:00289", "fact:00287"]), "試験の原文が不足しています");
    for (const row of evidence) {
      validateLegacyEvidence(row, scope);
      requireValue(same(row.pages, [52]) && row.scope_type === "department"
        && same(row.scope_targets, ["情報工学系"]) && row.parent_college === "情報理工学院", "試験の原文の対象範囲が一致しません");
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
    `専門筆答試験：${dateZh(s.written_date)} ${s.written_start_time}–${s.written_end_time}（日本時間、${s.duration_minutes}分）。`,
    ...s.subject_groups.map((group) => `${group.group}群：${group.subjects_zh.join("、")}。`),
    `各群${s.questions_per_group}問、合計${s.total_questions}問を出題。専門筆答試験は日本語で解答します。`,
    `専門筆答試験${s.specialist_points}点、英語${s.english_points}点。英語の筆答試験は行わず、指定の外部英語試験で評価します。規定に従った証明の提出が必要です。`,
    `口述対象者：${dateZh(s.oral_announcement_date, false)}${Number(s.oral_announcement_time.split(":")[0])}時頃から発表。口述試験は${dateZh(s.oral_date, false)}。${s.oral_selection_note_zh}`
  ];
}

export function examV2View(exam) {
  requireValue(exam?.schema_version === "2.0" && exam.status === "available", "試験資料が未確認です");
  const [a, b] = exam.pathways;
  const written = b.written;
  const scope = exam.applicability.personal_route_state === "catalog_b"
    ? "情報工学系の選択対象はB日程です。A日程は同じ冊子の参考情報としてのみ表示します。"
    : "大学が公表したA・B日程を参照できます。本人が受験する日程と資格は大学に確認してください。";
  const lead = written.status === "not_held"
    ? `大学の案内では、B日程の筆答試験は実施しません。${scope}`
    : `大学が公表したB日程の筆答試験：2026年8月18日 ${written.time_zh
      .replace(/^8\/18\s*/, "").split("；所要時間（分）：")[0]}。${scope}`;
  const subjects = written.status === "held" ? [written.subjects_zh.join("；")] : [];
  const selection = written.status === "held" && written.selection_rule_zh
    ? `解答方法：${written.selection_rule_zh}` : null;
  const points = written.points_zh ? `配点・英語：${written.points_zh}` : null;
  const aOral = `${a.label_zh}の口述試験：${a.oral.description_zh.replace(/^A：/, "")}。`;
  const bOral = `${b.label_zh}の口述試験：${b.oral.description_zh.replaceAll("**", "")}。`;
  const condition = exam.field_bindings.find((field) => field.field_path === "b.specialist_condition")?.value_zh;
  const specialist = condition ? `専門科目の条件：${condition.replaceAll("**", "")}。` : null;
  const english = b.english.submission_zh ? `この系の英語証明について：${b.english.submission_zh}。書類の準備状況は既存の要件に基づいて照合します。` : null;
  const language = written.answer_language_zh
    ? `筆答試験の解答言語：${written.answer_language_zh}。`
    : written.administration_language_zh ? `試験の実施言語：${written.administration_language_zh}。筆答試験の解答言語は原文に別記されていません。` : null;
  const course = exam.applicability.excluded_course_ids.length
    ? `本冊子の対象コース：${exam.applicability.covered_course_ids.join("、")}。${exam.applicability.excluded_course_ids.join("、")}は別冊のため、試験日程は未収録です。` : null;
  return {lead, subjects, selection, points, aOral, bOral, specialist, english, language, course};
}

export function mapSliceEvidence(scope, evidence) {
  requireValue(scope.kind === "reviewed_material_slice"
    && evidence?.schema_version === "1.0"
    && evidence.snapshot_id === scope.item.snapshot_id
    && same(evidence.target, scope.item.target)
    && (!Number.isSafeInteger(scope.item.revision) || evidence.revision === scope.item.revision)
    && Array.isArray(evidence.topics) && evidence.topics.length > 0, "公式資料の根拠と志望先が一致しません");
  const topics = evidence.topics.map((topic) => {
    const sources = array(topic.records).map((record) => {
      requireValue(nonempty(record.source_title) && Number.isSafeInteger(record.physical_page)
        && record.physical_page > 0 && array(record.fragments).length > 0, "書類の根拠が不足しています");
      const quotes = record.fragments.map((fragment) => {
        requireValue(nonempty(fragment.quote_text), "書類の原文がありません");
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
          record.role === "basis" ? "この項目の根拠" : "関連する記載",
          record.stage === "enrollment_context_only" ? "入学手続きに関連する記載（出願時の義務ではありません）" : ""].filter(Boolean).join(" · "),
        record_id: record.record_id
      };
    });
    requireValue(sources.length > 0, "書類項目の根拠がありません");
    const ids = new Set(sources.map((source) => source.record_id));
    const relations = array(topic.relations).filter((relation) => relation
      && ids.has(relation.from) && ids.has(relation.to) && typeof relation.kind === "string");
    return {
      id: topic.topic_id, category: "materials", title: topic.material_name_zh,
      summary: topic.context_note_zh, description: topic.context_note_zh,
      status: "条件の確認にはレポートの表示が必要です", status_code: "needs_information",
      deadline: "", limitation: "", dates: [], sources, relations
    };
  });
  const generated = generatedEntry(scope);
  requireValue(!reviewedMaterialPresentation.entries.some((row) => row.snapshot_id === scope.item.snapshot_id)
    || generated, "表示一覧と志望先の情報が一致しません");
  if (generated) {
    requireValue(topics.length === generated.topics.length
      && new Set(topics.map((topic) => topic.id)).size === topics.length,
      "新しい書類サンプルの対象範囲が一致しません");
    for (const row of generated.topics) {
      const topic = topics.find((topic) => topic.id === row.id);
      requireValue(topic && generatedSourcesMatch(row, topic.sources)
        && same(topic.relations, row.relations), "書類の原文・表の見出し・関連情報がありません");
    }
  }
  return {
    scope, topics, coverage: `過去の募集資料 · 確認済みの書類 ${topics.length}項目`,
    limitation: array(evidence.limitations_zh).join("；"), target: evidence.target,
    raw: evidence
  };
}

function sourceLines(source) {
  const page = source.pages.join("、");
  return [`出典：${source.title} · PDFページ ${page}${source.printed ? `（印刷页 ${source.printed}）` : ""}`,
    source.context ? `関連情報：${source.context}` : "",
    `公式原文：${source.quote}`, `公式リンク：${source.source_url}`].filter(Boolean);
}

export function legacyReport(mapped, comparison = null, profileDisclosure = [], exam = null) {
  requireValue(mapped?.scope?.kind === "legacy_applicant" && mapped.topics?.length, "要件が未読み込みです");
  if (comparison) {
    requireValue(Array.isArray(profileDisclosure), "本人情報の表示が正しくありません");
    requireValue(comparison.schema_version === "1.0"
      && legacyTargetMatches(mapped.scope, comparison.target)
      && Array.isArray(comparison.items)
      && comparison.counts?.total === comparison.items.length, "本人情報の照合対象が一致しません");
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
        requireValue(array(item.evidence).length > 0, "本人情報の照合に必要な引用がありません");
    }
  }
  const intro = [
    "募集要項の参考レポート", scopeLabel(mapped.scope), "",
    "確認済みの結果を整理したレポートです。最終的な資格判定ではありません。",
    `確認済みの範囲：${mapped.coverage}`, `対象範囲の制限：${mapped.limitation}`
  ];
  const topics = mapped.topics.map((topic, index) => {
    const lines = [`区分：${categoryNames[topic.category] || "その他の確認済み項目"}／公式要件：${topic.status}`,
      `説明：${topic.summary}`];
    if (topic.description !== topic.summary) lines.push(`詳細：${topic.description}`);
    if (topic.deadline) lines.push(`締切について：${topic.deadline}`);
    const references = [];
    for (const date of topic.dates) {
      lines.push(`日程：${date.label} · ${date.display} · 日時の粒度 ${date.precision}`);
      if (date.unknown.length) lines.push(`未確認の日時項目：${date.unknown.join("、")}`);
      if (date.uncertainty) lines.push(`日程の注意事項：${date.uncertainty}`);
      references.push(...date.sources);
    }
    references.push(...topic.sources);
    if (topic.limitation) lines.push(`留意事項：${topic.limitation}`);
    return {heading: `${index + 1}. ${topic.title}`, lines, references};
  });
  const lines = [...intro, "", "基本要件"];
  for (const topic of topics)
    lines.push("", topic.heading, ...topic.lines, ...topic.references.flatMap(sourceLines));
  let comparisonPresentation = null;
  if (comparison) {
    const overview = [comparison.comparison_statement,
      `準備状況：全${comparison.counts.total}項目／追加準備${comparison.counts.action_required}／要確認${comparison.counts.review_required}／記録済み${comparison.counts.recorded}`,
      "今回の自己申告です。未入力・不明は未確認のまま扱います。本人が対象外と申告しても、公式の免除を意味しません。"];
    for (const field of profileDisclosure) {
      requireValue(nonempty(field.label) && nonempty(field.value), "本人情報の表示がありません");
      overview.push(`${field.label}：${field.value}`);
    }
    const items = comparison.items.map((item) => {
      const itemLines = [item.description, `次にすること：${item.next_action}`];
      if (item.official_status) itemLines.push(`公式要件の適用：${publicStatus(item.official_status)}`);
      if (item.preparation_status) itemLines.push(`準備状況（自己申告）：${publicStatus(item.preparation_status)}`);
      if (item.limitation) itemLines.push(`留意事項：${item.limitation}`);
      return {
        heading: `${item.title} · ${publicStatus(item.comparison_status)}`,
        lines: itemLines,
        references: array(item.evidence).map((evidence) => validateLegacyEvidence(evidence, mapped.scope))
      };
    });
    const end = [comparison.partial_checklist_statement, comparison.limitation_statement];
    comparisonPresentation = {overview, items, end};
    lines.push("", "本人の状況と要件の照合（今回の自己申告に基づく）", ...overview);
    for (const item of items)
      lines.push("", item.heading, ...item.lines, ...item.references.flatMap(sourceLines));
    lines.push(...end);
  } else lines.push("", "本人情報が未入力のため、個別の適用を判断していません。");
  const conclusion = "未収録の内容や不明な条件を、公式原文で確認してください。書類の準備済みは、大学での受理を意味しません。";
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
    && nonempty(payload.markdown), "レポートの対象または根拠が一致しません");
  const citations = new Map(array(payload.report.evidence_inventory).map((row) => [row.citation_key, row]));
  requireValue(citations.size === array(payload.report.evidence_inventory).length, "レポートの引用が重複しています");
  const loadedSources = mapped.topics.flatMap((topic) => topic.sources);
  const topics = payload.report.topic_results.map((result) => {
    const keys = [...array(result.basis_citation_keys), ...array(result.context_citation_keys)];
    requireValue(array(result.basis_citation_keys).length > 0 && keys.every((key) => citations.has(key)), "レポートの引用がありません");
    const sourceRecords = keys.map((key) => citations.get(key));
    for (const row of sourceRecords) requireValue(nonempty(row.quote_text)
      && nonempty(row.source_title) && array(row.physical_pages).length > 0
      && loadedSources.some((source) => source.record_id === row.record_id
        && source.title === row.source_title
        && source.pages.length === row.physical_pages.length
        && source.pages.every((page, index) => page === row.physical_pages[index])
        && source.quote.includes(row.quote_text)), "レポートの引用と読み込み済み原文が一致しません");
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
  requireValue(topics.length === mapped.topics.length
    && (!generatedEntry(scope) || (new Set(topics.map((topic) => topic.id)).size === topics.length
      && topics.every((topic) => mapped.topics.some((row) => row.id === topic.id)))),
    "書類項目の数または識別情報が一致しません");
  requireValue(["unknown", "yes", "no"].includes(employment.current)
    && ["unknown", "yes", "no"].includes(employment.retain), "本人の条件が正しくありません");
  const conditionName = {unknown: "不明・確認待ち", yes: "はい", no: "いいえ"};
  const wrapper = [
    "募集要項の参考レポート", scopeLabel(scope),
    "過去資料の一部の書類が対象です。条件・未確認事項と公式資料全体を確認してください。",
    `自己申告：現在在職中 ${conditionName[employment.current]}／入学後も在職 ${conditionName[employment.retain]}。`,
    "", payload.markdown, "", "読み込み済みの原文（プレビューと同じ内容）",
    ...topics.flatMap((topic) => [topic.title, ...topic.citations.flatMap((cite) => [
      `${cite.source_title} · PDFページ ${cite.physical_pages.join("、")}${cite.printed_page_label ? ` · 印刷页 ${cite.printed_page_label}` : ""}`,
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
      && ["unknown", "available", "not_yet"].includes(value)), "準備状況の入力が正しくありません");
  return {...report, preparation: {...preparation}};
}

const readerTopicNames = {dates: "重要な日程", materials: "書類・次にすること", other: "読み込み済みのその他の要件", exams: "試験日程"};

// Generated display data is matched by every target field and snapshot.
function generatedEntry(scope) {
  requireValue(reviewedMaterialPresentation?.schema_version === "1.0"
    && Array.isArray(reviewedMaterialPresentation.entries), "表示一覧を読み込めません。ページを再読み込みしてください");
  const entries = reviewedMaterialPresentation.entries;
  requireValue(new Set(entries.map((entry) => entry.snapshot_id)).size === entries.length,
    "表示一覧の識別情報が重複しています");
  if (scope?.kind !== "reviewed_material_slice") return null;
  const entry = entries.find((row) => row.snapshot_id === scope.item?.snapshot_id);
  if (!entry) return null;
  if (!same(entry.target, scope.item.target) || entry.revision !== scope.item.revision) return null;
  requireValue(Array.isArray(entry.topics) && entry.topics.length > 0
    && new Set(entry.topics.map((topic) => topic.id)).size === entry.topics.length,
    "表示一覧と志望先の情報が一致しません");
  return entry;
}

function generatedTopic(scope, code) {
  return generatedEntry(scope)?.topics.find((row) => row.id === code || row.material_code === code);
}

function generatedSourcesMatch(topic, sources) {
  const normalize = (value) => text(value).replace(/\s+/g, "");
  if (!topic || array(sources).length !== array(topic.records).length
    || new Set(sources.map((source) => source.record_id)).size !== sources.length) return false;
  return topic.records.every((record) => {
    const source = sources.find((row) => row.record_id === record.record_id);
    if (!source || source.source_id !== record.source_id || source.title !== record.source_title
      || source.source_url !== record.official_source_url || source.role !== record.role
      || source.stage !== record.stage || !same(source.pages, [record.physical_page])
      || source.printed !== record.printed_page_label
      || source.heading !== record.official_heading_path.join(" › ")
      || array(source.fragments).length !== record.fragments.length) return false;
    return record.fragments.every((fragment) => {
      const matches = source.fragments.filter((row) => row.fragment_id === fragment.fragment_id);
      return matches.length === 1 && matches[0].fragment_role === fragment.fragment_role
        && matches[0].fact_id === fragment.fact_id
        && matches[0].authoritative_fact_text_sha256 === fragment.authoritative_fact_text_sha256
        && normalize(matches[0].quote_text) === normalize(fragment.quote_text);
    });
  });
}

export function slicePreparationControls(mapped) {
  const entry = generatedEntry(mapped?.scope);
  if (!entry) return [];
  return entry.topics.filter((row) => row.preparation_control === "self_report_tri_state")
    .map((row) => {
      const topic = mapped.topics.find((topic) => topic.id === row.id);
      requireValue(topic && generatedSourcesMatch(row, topic.sources) && row.guide,
        "準備状況の入力欄の出典が不足しています");
      return {id: row.id, name: row.display[0], type: row.preparation_control};
    });
}

// Presentation only. Code meanings are bound to reviewed document/snapshot identity;
// applicability and preparation still come from reviewed responses.
const materialDisplays = [
  {identity: {kind: "legacy_applicant", school_id: "isct",
    document_id: "isct_2027_4_2026_9_master"}, materials: {
    address_label: ["宛名ラベル", "宛名ラベル", "出願書類を郵送する封筒に貼るラベルです。"],
    application_form: ["入学志願票", "入学志願票", "今回の出願に用いる正式な申請用紙です。"],
    statement_of_purpose: ["志望理由書", "志望理由書", "志望する分野を選んだ理由を説明する書類です。"],
    bachelor_transcript: ["学士課程の成績証明書", "学士課程の成績証明書", "学士課程の成績を証明する書類です。"],
    graduation_or_expected_graduation_certificate: ["卒業・卒業見込証明書", "学士課程の卒業証明書又は卒業見込み証明書", "学士課程の卒業または卒業見込みを証明する書類です。"]
  }},
  {identity: {kind: "reviewed_material_slice", institution_id: "utokyo",
    organization_id: "utokyo-gsfs", program_id: "utokyo-gsfs-complex",
    snapshot_id: "2794e4548763e98b36e168cb9a3a062d75008711c313a8a18fbb760bf19a9a98"}, materials: {
    "english-score-sheets": ["英語スコア証明", "英語のスコアシート", "英語試験のスコアを証明する書類です。提出要否は選択中の専攻の要件に従います。"],
    "checklist-submission": ["提出書類等チェックシート", "提出書類等チェックシート（修士課程一般選抜用）", "提出書類の確認に用います。参照する指示は、シート自体の提出を求めるものではありません。"],
    "work-study-plan": ["学業・職務両立計画書", "学業・職務両立計画書", "在職したまま入学する場合に、学業と職務をどう両立するかを説明する計画書です。"]
  }},

];

// Human guidance is attached only to the exact reviewed p.10 table in this edition.
const isctMaterialGuides = {
  address_label: {
    purpose: "出願書類の郵送先を記載したラベルです。",
    steps: ["オンライン出願のマイページから取得し、A4用紙にカラー印刷します。", "角形2号封筒（240×332mm）に貼り付けます。", "発送前に記載内容を確認します。"],
    warnings: ["A4カラー印刷と封筒のサイズは、この資料の宛名ラベルに適用される指定です。"],
    conditions: []
  },
  application_form: {
    purpose: "オンライン出願後に印刷・提出する正式な志願票です。",
    steps: ["検定料等の支払いと顔写真のアップロードを完了してから、志願票を印刷します。", "オンライン出願のマイページから、A4用紙にカラー印刷します。", "内容を確認し、必要な出願書類と一緒に準備します。"],
    warnings: ["印刷できない場合は、支払いと写真のアップロードを確認してください。この画面では両手続きの進捗を確認しません。"],
    conditions: []
  },
  statement_of_purpose: {
    purpose: "志望理由などを記載する所定の書類です。",
    steps: ["募集要項で指定された書式を使用します。", "A4用紙1枚に印刷します。両面印刷も可能です。", "志望する系にテーマの指定があるか確認します。テーマの指定がなくても提出は必要です。"],
    warnings: ["この書類の提出要否は、学歴に応じた出願資格の確認結果に従います。"],
    conditions: []
  },
  bachelor_transcript: {
    purpose: "学士課程の各科目の成績を証明する、大学発行の書類です。",
    steps: ["大学発行の学士課程の成績証明書を準備します。大学院の成績証明書では代用できません。", "共通の指定に従って原本を準備します。通常のコピーや自分でダウンロード・印刷したものでは代用できません。", "卒業済み・卒業見込みにかかわらず、この書類が自分の出願資格区分で必要かを確認します。"],
    warnings: ["成績と卒業の証明が大学の1つの証明書にまとまっていても構いません。両方の記載を確認してください。"],
    conditions: [
      {title: "編入学した場合", text: "編入学前の大学等の成績証明書も準備してください。"},
      {title: "成績が教養・専門、本科・専攻科などに分かれている場合", text: "両方の証明書を準備してください。"},
      {title: "保存期間の経過、閉校、被災などで発行できない場合", text: "出願期間の開始前に入試課へ相談してください。この画面では代替書類の承認を判断しません。"},
      {title: "原本を提出できない場合", text: "共通要件を確認し、卒業大学・大使館・領事館・公証機関などの公的機関による原本証明を受けてください。通常のコピーでは代用できません。"},
      {title: "証明書が日本語・英語以外の場合", text: "卒業大学発行の日本語または英語の翻訳を添付します。大学が発行できない場合は、原文の指定に従い公的機関で訳文の内容の証明を受けます。本人による翻訳のみ、または宣誓・署名のみの証明では代用できません。"}
    ]
  },
  graduation_or_expected_graduation_certificate: {
    purpose: "学士課程の卒業または卒業見込みを証明する大学発行の書類です。",
    steps: ["卒業状況に応じて卒業証明書または卒業見込証明書を準備します。", "外国の大学の出願者は、学位の取得または取得見込みの証明も必要です。卒業と学位の証明は1つの書類に記載されていても構いません。", "大学発行の書類を使用し、原本・言語・翻訳の要件を確認します。"],
    warnings: ["成績と卒業の証明が1つにまとまっていても構いません。手元の代替書類の有効性はこの画面では判断しません。"],
    conditions: [
      {title: "2026年9月入学に出願する場合", text: "2026年9月27日までに卒業できることを示す必要があります。この日付は2027年4月入学には適用しません。", intakeYear: 2026, intakeMonth: 9},
      {title: "卒業証明書を提出できない場合", text: "原文では、卒業・卒業見込みの年月、氏名、生年月日を記載した大学の証明書を認めています。年月は入学・卒業年月で示すこともできます。"},
      {title: "外国の大学の卒業・学位証明がいずれも提出できない場合", text: "取得または取得見込みの学位などを記載した大学の証明書に関する別の要件があります。2つの代替条件を混同しないでください。"},
      {title: "原本を提出できない場合", text: "原文に従い、卒業大学・大使館・領事館・公証機関などの公的機関による原本証明を受けてください。通常のコピーでは代用できません。"},
      {title: "証明書が日本語・英語以外の場合", text: "卒業大学発行の日本語または英語の翻訳を添付します。大学が発行できない場合は、原文の指定に従い公的機関で訳文の内容の証明を受けます。本人による翻訳のみ、または宣誓・署名のみの証明では代用できません。"}
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
  const generated = generatedTopic(scope, code);
  if (generated) return {name: generated.display[0], official: generated.display[1],
    description: generated.display[2], verified: true};
  const identity = materialScopeIdentity(scope);
  const catalog = identity && materialDisplays.find((entry) =>
    Object.entries(entry.identity).every(([key, value]) => identity[key] === value));
  const row = catalog?.materials[code];
  if (!row) return {name: originalName, official: "", description: "説明は確認中です。", verified: false};
  return {name: row[0], official: row[1], description: row[2], verified: true};
}

export function materialGuide(scope, topic) {
  const identity = materialScopeIdentity(scope);
  const generated = generatedTopic(scope, topic?.id);
  if (generated) return generatedSourcesMatch(generated, topic.sources) ? generated.guide : null;
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
  return `${item.title}${item.official && item.official !== item.title ? `（${item.official}）` : ""}｜${guide?.purpose || item.description}｜${item.state}。${item.action}`
    + (guide ? ` 準備方法：${joinSentences(guide.steps)} 注意事項：${joinSentences(guide.warnings)}`
      + (guide.conditions.length ? ` 条件別の注意事項：${joinSentences(guide.conditions.map((row) => `${row.title}：${row.text}`))}` : "") : "");
}

export function readerReportOptions(report) {
  requireValue(report?.scope && Array.isArray(report.topics), "レポートが未検証です");
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
    return {state: "この書類の提出は不要", action: "確認済みの適用条件では、この書類の提出は不要です。"};
  if (applicability === "not_covered")
    return {state: "対象資料の範囲外", action: "この資料だけでは判断できません。募集要項全体を確認してください。"};
  if (applicability !== "required")
    return {state: "適用条件を要確認", action: preparation === "not_yet"
      ? "未準備と申告されています。まず適用条件を確認し、書類を追加する必要があるかを確かめてください。"
      : preparation === "available"
        ? "準備済みと申告されています。まず提出が必要かを確認してください。"
        : "準備状況は未入力です。まず提出が必要かを確認してください。"};
  if (preparation === "not_yet")
    return {state: "準備が必要", action: "未準備と入力されています。書類の具体的な要件を確認してください。"};
  if (preparation === "available")
    return {state: "準備済み（自己申告）", action: "書類が要件を満たすか確認してください。"};
  return {state: "準備状況が未入力", action: "準備状況を記録してください。現在は不足書類とは数えていません。"};
}

function sliceMaterialState(topic, employment, preparation = "unknown") {
  if (topic.status_code === "submission_not_required")
    return {state: "この書類の提出は不要", action: topic.explanation};
  if (topic.status_code === "rule_not_applicable")
    return {state: "この条件の対象外", action: topic.explanation};
  if (topic.status_code === "submission_required" && preparation === "available")
    return {state: "準備済み（自己申告）", action: "公式要件では提出が必要です。内容・書式・提出状況を確認してください。自己申告は大学での受理を意味しません。"};
  if (topic.status_code === "submission_required" && preparation === "not_yet")
    return {state: "準備が必要", action: "未準備と入力されています。この書類の要件に従って準備・提出してください。自己申告で提出要件が変わることはありません。"};
  if (topic.status_code === "submission_required")
    return {state: "提出が必要・準備状況は未入力", action: topic.explanation};
  if (topic.status_code === "not_covered")
    return {state: "対象資料の範囲外", action: "このサンプルでは未確認です。"};
  const missing = [];
  if (employment.current === "unknown") missing.push("現在在職しているか");
  if (employment.retain === "unknown") missing.push("入学後も在職するか");
  return {state: "適用条件を要確認", action: `${topic.explanation}${missing.length ? `入力してください：${missing.join("、")}。` : "適用条件を大学に確認してください。"}`};
}

function readerText(view) {
  const lines = ["出願準備レポート", `志望先：${view.target}`, `選択した内容：${view.selected.map((key) => readerTopicNames[key]).join("、")}`];
  const section = (title, rows) => {
    lines.push("", title);
    for (const row of rows) lines.push(`- ${row}`);
  };
  if (view.priorityRows.length) section("次に準備すること", view.priorityRows);
  if (view.selected.includes("dates")) {
    section("重要な日程", view.dates.length
      ? view.dates.map((item) => `${item.label}：${item.value}${item.note ? `；${item.note}` : ""}`)
      : ["対象資料の日程はまだ整理されていません。募集要項全体をご確認ください。"]);
    if (view.dateNote) lines.push(view.dateNote);
  }
  if (view.selected.includes("materials"))
    section("書類の準備リスト", view.materials.length
      ? view.materials.map((item) => item.line)
      : ["選択した資料に、レポートに含められる書類項目がありません。"]);
  if (view.selected.includes("materials") && view.english.length)
    section("英語スコア・証明書", view.english);
  if (view.selected.includes("materials") && view.submission.length)
    section("卒業・提出に関する確認事項", view.submission);
  if (view.selected.includes("other"))
    section("読み込み済みのその他の要件", view.other.length
      ? view.other.map((item) => `${item.title}：${item.summary}（${item.status}）`)
      : ["その他の項目はありません。"]);
  if (view.selected.includes("exams")) section("試験日程", view.exams);
  lines.push("", `対象範囲：${view.limitation}`);
  return lines.join("\n");
}

export function readerReport(report, selected) {
  const available = readerReportOptions(report);
  requireValue(selected && ["dates", "materials", "other"].every((key) => typeof selected[key] === "boolean")
    && (selected.exams === undefined || typeof selected.exams === "boolean"), "レポート項目の選択が正しくありません");
  requireValue(Object.keys(available).every((key) => !selected[key] || available[key]), "選択した項目が未読み込みです");
  const chosen = Object.keys(available).filter((key) => selected[key]);
  requireValue(chosen.length > 0, "レポートに含める項目を1つ以上選択してください");
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
    const names = {registration_open: "登録開始", application_window: "出願期間", arrival_deadline: "書類の必着期限", recommended_arrival: "早めの到着の目安"};
    for (const topic of report.topics) for (const date of array(topic.dates)) {
      const kind = date.event_type || "other";
      const key = `${kind}:${date.display}`;
      if (seen.has(key)) continue;
      seen.add(key);
      dates.push({label: names[kind] || date.label, value: date.display,
        note: kind === "recommended_arrival" ? "推奨日は必須の締切日ではありません" : ""});
      if (date.unknown.some((field) => field === "start_time" || field === "end_time") && !dateNote)
        dateNote = "公式に明記されていない時刻は推定していません。確認済みの日程と公式原文を参照してください。";
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
        const status = {reported_match: "申告上は準備済み", action_needed: "対応待ち",
          needs_information: "確認待ち", not_applicable: "対象外", not_covered: "未収録"}[check.status];
        english.push(`${check.title}：${status}。${check.explanation} 次にすること：${check.next_action}`);
        if (check.status === "action_needed") priorities.push(`英語 · ${check.title}：${check.next_action}`);
      }
    }
    const application = report.comparison?.application_preparation_result;
    if (application) {
      for (const check of application.checks) {
        const status = {reported_match: "申告内容を記録済み", action_needed: "対応が必要",
          needs_information: "確認待ち", not_applicable: "対象外", not_covered: "未収録"}[check.status];
        const line = `${check.title}：${status}。${check.explanation} 次にすること：${check.next_action}`;
        submission.push(line);
        if (check.status === "action_needed" || check.status === "needs_information")
          priorities.push(`卒業・提出 · ${check.title}：${check.next_action}`);
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
      if (["準備が必要", "提出が必要・準備状況は未入力"].includes(state.state))
        priorities.push(`${display.name}：${state.state}。${state.action}`);
      else if (state.state === "準備状況が未入力") unfilled.push(display.name);
      else if (state.state === "適用条件を要確認") conditional.push(item);
    }
    if (report.kind === "legacy_applicant" && !report.comparison)
      priorities.unshift("準備状況が未入力のため、不足している書類は判断できません。基本要件を先に保存できます。");
    else if (unfilled.length)
      priorities.push(`${unfilled.join("、")}：準備状況は未入力です。不足書類とは数えていません。`);
    if (conditional.length) priorities.push(conditional.length === 1
      ? `${conditional[0].title}：適用条件を要確認。${conditional[0].action}`
      : `${conditional.map((item) => item.title).join("、")}：適用条件を要確認。先に各書類が対象となるか確認してください。`);
  }
  if (selected.other) {
    for (const topic of report.topics.filter((item) => !["dates", "materials"].includes(item.category)
      && item.id !== "language:preparation-guide")) {
      other.push({title: topic.title, summary: topic.summary, status: topic.status});
      if (["needs_information", "needs_review", "not_covered"].includes(topic.status_code))
        priorities.push(`${topic.title}：${topic.status}。この項目の条件を確認してください。`);
    }
  }
  const limitation = report.kind === "reviewed_material_slice"
    ? `確認済みの書類${report.topics.length}項目のみを整理しています。完全な一覧や資格判定ではありません。過去資料のため、最新の公式情報を確認してください。`
    : selected.materials
      ? "確認済み資料と今回の自己申告のみを整理しています。準備済みは有効・提出済み・受理済みを意味しません。未収録の内容は募集要項全体で確認してください。"
      : "確認済み資料のみを整理しています。未収録の内容は募集要項全体で確認してください。";
  const priorityRows = priorities.length ? priorities : selected.materials
    ? ["選択範囲に明確な不足書類はありません。出願書類がすべて揃っていることを意味しません。"] : [];
  const view = {target, selected: chosen, priorities, priorityRows, dates, dateNote, materials, english, submission, other,
    ...(selected.exams ? {exams} : {}), limitation};
  return {...view, text: readerText(view)};
}

export {statusNames};
